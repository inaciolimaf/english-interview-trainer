from api.realtime.history import KICKOFF, TurnRecord, build_messages, spoken_prefix

SENTENCES = ["Great, thanks for that.", "Now let's talk about how you would design a cache layer."]


def test_spoken_prefix_mid_sentence():
    assert spoken_prefix(SENTENCES, 1, len("Now let's talk")) == "Great, thanks for that. Now let's talk"


def test_spoken_prefix_extends_cut_word():
    assert spoken_prefix(SENTENCES, 1, len("Now let's ta")) == "Great, thanks for that. Now let's talk"


def test_spoken_prefix_first_sentence_start():
    assert spoken_prefix(SENTENCES, 0, 0) == ""


def test_spoken_prefix_past_end_returns_everything():
    assert spoken_prefix(SENTENCES, 5, 0) == " ".join(SENTENCES)


def test_history_with_interruption():
    full = " ".join(SENTENCES)
    spoken = spoken_prefix(SENTENCES, 1, len("Now let's talk about"))
    msgs = build_messages("SYS", [
        TurnRecord("interviewer", "Hi! Tell me about yourself.", "Hi! Tell me about yourself."),
        TurnRecord("candidate", "I'm a backend developer.", "I'm a backend developer."),
        TurnRecord("interviewer", full, spoken, interrupted=True),
        TurnRecord("candidate", "Sorry, which cache?", "Sorry, which cache?"),
    ])
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1] == {"role": "user", "content": KICKOFF}
    assert msgs[4] == {"role": "assistant", "content": "Great, thanks for that. Now let's talk about—"}
    assert msgs[5]["role"] == "system"
    assert "'how you would design a cache layer.'" in msgs[5]["content"]
    assert "did NOT hear" in msgs[5]["content"]
    assert msgs[6] == {"role": "user", "content": "Sorry, which cache?"}


def test_consecutive_candidate_turns_are_merged():
    msgs = build_messages("SYS", [
        TurnRecord("interviewer", "Question?", "Question?"),
        TurnRecord("candidate", "First part", "First part"),
        TurnRecord("candidate", "second part.", "second part."),
    ])
    assert msgs[-1] == {"role": "user", "content": "First part second part."}


def test_empty_history_kicks_off():
    assert build_messages("SYS", [])[-1] == {"role": "user", "content": KICKOFF}
