import asyncio
import json

from api.analysis.language import LanguageIssue, validate_issues
from api.analysis.pipeline import anchor_span, live_items
from api.analysis.pron_filter import fallback, filter_candidates
from api.db.models import Error
from api.pronunciation.pipeline import windows
from api.pronunciation.rules import Candidate
from model_server.gpu_queue import GpuQueue, Priority
from tests.conftest import FakeLLM

ANSWER = "I work here since 2020 and we use the Redis for cache the sessions."


def issue(kind, category, quote, severity="medium"):
    return LanguageIssue(kind=kind, category=category, original_text=quote, corrected_text="x",
                         explanation="e", severity=severity)


def test_language_quotes_must_exist_in_the_answer():
    kept = validate_issues([
        issue("grammar", "gram:verb_tense", "I work here since 2020"),
        issue("grammar", "gram:article", "the Redis"),
        issue("grammar", "gram:article", "a invented sentence"),  # not said → dropped
        issue("vocabulary", "vocab:made_up", "cache the sessions"),  # unknown category → vocab:other
        issue("technical", "tech:caching", "no eviction policy"),  # technical: kept, unanchored
    ], ANSWER)
    assert [(i.category, i.original_text) for i in kept] == [
        ("gram:verb_tense", "I work here since 2020"), ("gram:article", "the Redis"),
        ("vocab:other", "cache the sessions"), ("tech:caching", ""),
    ]


def test_category_must_match_kind():
    (i,) = validate_issues([issue("grammar", "tech:caching", "the Redis")], ANSWER)
    assert i.category == "gram:other"


def cand(word, strength, tech=False, category="pron:phoneme:θ"):
    return Candidate(word=word, word_index=0, category=category, expected="θ ɪ ŋ k", heard="t ɪ ŋ k",
                     phone="θ", heard_phone="t", phone_index=0, score=-strength, threshold=0.0, is_tech=tech)


def test_filter_cannot_invent_errors():
    cands = [cand("think", 3), cand("three", 0.2)]
    llm = FakeLLM(json_replies=[json.dumps({"keep": [
        {"id": 0, "severity": "high", "explanation": "Use /θ/."},
        {"id": 7, "severity": "high", "explanation": "invented"},
        {"id": 0, "severity": "low", "explanation": "duplicate"},
    ]})])
    kept = asyncio.run(filter_candidates(llm, cands, "I think three"))
    assert [(c.word, sev, exp) for c, sev, exp in kept] == [("think", "high", "Use /θ/.")]


def test_filter_falls_back_without_llm():
    kept = fallback([cand("think", 3), cand("three", 0.2), cand("throughput", 1.5, tech=True)])
    assert [c.word for c, _, _ in kept] == ["think", "throughput"]  # weak margin dropped
    assert kept[1][1] == "high" and "tongue between your teeth" in kept[0][2]


def test_filter_falls_back_when_llm_fails():
    class Broken(FakeLLM):
        async def complete_json(self, messages):
            raise RuntimeError("OPENROUTER_API_KEY is not set in .env")
    kept = asyncio.run(filter_candidates(Broken(), [cand("think", 3)], "I think"))
    assert kept and kept[0][0].word == "think"


def err(severity, category="gram:article"):
    return Error(kind="grammar", category=category, severity=severity, explanation="e")


def test_live_items_modes():
    errors = [err("low"), err("high"), err("medium"), err("high"), err("high"), err("high", "pron:suspect")]
    live = live_items("live", errors)
    assert len(live) == 3 and [i["severity"] for i in live] == ["high", "high", "high"]
    assert all(i["category"] != "pron:suspect" for i in live)
    assert [i["severity"] for i in live_items("hybrid", [err("medium"), err("high")])] == ["high"]
    assert live_items("end", errors) == []


def w(text, start, end):
    return {"w": text, "start_ms": start, "end_ms": end, "p": 0.9}


def test_anchor_span_is_the_whole_sentence():
    words = [w("Hello.", 0, 400), w("I", 500, 600), w("work", 600, 900), w("here", 900, 1100),
             w("since", 1100, 1400), w("2020.", 1400, 2000), w("Thanks.", 2200, 2600)]
    assert anchor_span(words, "here since") == (500, 2000)
    assert anchor_span(words, "not said") is None


def test_windows_split_on_length_and_pauses():
    words = [w(str(i), i * 1000, i * 1000 + 800) for i in range(20)]  # 20 s, no pauses
    assert [len(x) for x in windows(words)] == [15, 5]
    words = [w("a", 0, 500), w("b", 600, 900), w("c", 3000, 3400)]  # 2.1 s pause
    assert windows(words) == [[0, 1], [2]]


def test_gpu_queue_runs_high_priority_first():
    order = []

    async def main():
        q = GpuQueue()
        q.start()
        blocker = asyncio.create_task(q.submit(Priority.LOW, lambda: (order.append("low-0"), __import__("time").sleep(0.2))))
        await asyncio.sleep(0.05)  # low-0 is running
        lows = [asyncio.create_task(q.submit(Priority.LOW, order.append, f"low-{i}")) for i in (1, 2)]
        await asyncio.sleep(0)
        high = asyncio.create_task(q.submit(Priority.HIGH, order.append, "high"))
        await asyncio.gather(blocker, high, *lows)
        await q.stop()

    asyncio.run(main())
    assert order == ["low-0", "high", "low-1", "low-2"]  # waits for at most one low job


def test_extract_json_tolerates_leaked_reasoning():
    from api.llm.client import extract_json
    assert extract_json('{"a": 1}') == '{"a": 1}'
    assert extract_json('We need answer JSON only... {"keep": [{"id": 0}]} done') == '{"keep": [{"id": 0}]}'
    assert extract_json('```json\n{"x": {"y": 2}}\n```') == '{"x": {"y": 2}}'


def test_numbers_are_not_judged():
    from api.pronunciation.rules import Calibration, Context, Stats, Variants, judge_word
    ctx = Context(calibration=Calibration({}, Stats(3.0, 1.0)), variants=Variants())
    res = {"aligned": True, "heard": ["t", "w"], "phones": [{"p": "θ", "score": -9.0, "competitor": "t"}]}
    assert judge_word(ctx, "2021", 0, res) == [] and judge_word(ctx, "p99", 0, res) == []


def test_tech_vocabulary_overrides_espeak():
    from api.pronunciation.pipeline import expected_phones
    out = expected_phones(["the", "idempotency", "key"], {"idempotency": ["aɪ", "d", "ɛ", "m"]})
    assert out[1] == ["aɪ", "d", "ɛ", "m"] and out[0] and out[2]
