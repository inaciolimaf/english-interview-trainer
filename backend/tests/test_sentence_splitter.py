from api.realtime.sentence_splitter import SentenceSplitter


def run(tokens: list[str]) -> list[str]:
    splitter = SentenceSplitter()
    out = [s for t in tokens for s in splitter.feed(t)]
    return out + splitter.flush()


def chars(text: str) -> list[str]:
    return list(text)  # worst case: one character per token


def test_splits_on_sentence_end():
    assert run(chars("Hi, I'm Sarah from the platform team. How are you today? Great!")) == [
        "Hi, I'm Sarah from the platform team.",
        "How are you today?",
        "Great!",  # trailing fragment comes out on flush
    ]


def test_short_leading_fragment_merges_with_next_sentence():
    assert run(chars("Okay. Let's move on to the next topic now.")) == [
        "Okay. Let's move on to the next topic now."
    ]


def test_abbreviations_do_not_split():
    text = "We use caches, e.g. Redis or Memcached, for hot keys. Then what?"
    assert run(chars(text)) == [
        "We use caches, e.g. Redis or Memcached, for hot keys.",
        "Then what?",
    ]


def test_numbers_and_versions_do_not_split():
    text = "Latency went from 3.5 to 1.2 seconds on version 2.0 last week. Nice."
    assert run(chars(text)) == ["Latency went from 3.5 to 1.2 seconds on version 2.0 last week.", "Nice."]


def test_sentence_is_released_only_after_following_whitespace():
    s = SentenceSplitter()
    assert s.feed("Tell me about your last project.") == []  # could still be "project.json"
    assert s.feed(" What") == ["Tell me about your last project."]
    assert s.flush() == ["What"]


def test_quotes_after_punctuation():
    assert run(chars('He said "it scales." Then he left the room quietly.')) == [
        'He said "it scales."',
        "Then he left the room quietly.",
    ]
