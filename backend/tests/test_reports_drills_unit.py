import uuid
from datetime import UTC, datetime, timedelta

from api.db.models import DrillItem, Error, InterviewSession, Turn
from api.drills.evaluate import similarity
from api.drills.generate import contains_word, dedup_key, pron_focus
from api.reports.report import deterministic_part, interruption_examples
from api.routes.dashboard import trend
from api.routes.drills import pick_items

NOW = datetime(2026, 10, 6, tzinfo=UTC)


def item(kind, lapses, overdue_h):
    return DrillItem(id=uuid.uuid4(), kind=kind, lapses=lapses, due_at=NOW - timedelta(hours=overdue_h))


def test_pick_items_prioritizes_lapses_and_respects_budget():
    due = [item("pron_read", 0, 50), item("tech_explain", 3, 1), item("grammar_rewrite", 1, 2)] + \
          [item("tech_explain", 0, h) for h in range(10)]
    chosen = pick_items(due)
    assert [d.lapses for d in chosen[:3]] == [3, 1, 0]
    assert chosen[2].kind == "pron_read"  # most overdue among 0 lapses
    assert sum({"pron_read": 45, "grammar_rewrite": 40, "tech_explain": 90}[d.kind] for d in chosen) <= 8 * 60


def err(kind, category, **kw):
    return Error(kind=kind, category=category, **kw)


def test_dedup_keys():
    assert dedup_key(err("pronunciation", "pron:phoneme:θ", word="Throughput,")) == ("pron_read", "pron|throughput")
    assert dedup_key(err("grammar", "gram:article", original_text="the Redis", corrected_text="Redis")) == \
        ("grammar_rewrite", "gram:article")
    assert dedup_key(err("grammar", "gram:article", original_text="x", corrected_text=None)) is None
    assert dedup_key(err("technical", "tech:caching")) == ("tech_explain", "tech:caching")
    assert dedup_key(err("fluency", "flu:filler")) is None


def test_pron_focus():
    assert pron_focus(err("pronunciation", "pron:phoneme:θ", expected_phonemes="θ ɹ uː", phoneme_index=0)) == "θ"
    assert pron_focus(err("pronunciation", "pron:epenthesis", expected_phonemes="s t æ k", phoneme_index=0)) == "pron:epenthesis"
    assert pron_focus(err("pronunciation", "pron:suspect")) == "suspect"


def test_contains_word_and_similarity():
    assert contains_word("Our throughput doubled.", "throughput")
    assert not contains_word("Throughputs doubled.", "throughput")
    assert similarity("I have worked here since 2020.", "I've worked here since 2020") < 1
    assert similarity("I have worked here since 2020", "i have worked here since 2020.") == 1.0


def test_trend():
    assert trend(1.0, 2.0) == "down" and trend(2.0, 1.0) == "up"
    assert trend(1.05, 1.0) == "flat" and trend(1.0, 0) == "new" and trend(0, 0) == "flat"


def turn(idx, role, text, interrupted=False, metrics=None):
    return Turn(id=uuid.uuid4(), idx=idx, role=role, full_text=text, spoken_text=text, interrupted=interrupted,
                metrics=metrics, analysis_status="done" if role == "candidate" else None)


def test_deterministic_report_and_interruptions():
    m = {"words": 120, "speaking_s": 60, "filler_count": 6, "long_pauses": [{"ms": 2500}], "word_z": [0.1] * 100 + [None] * 20}
    turns = [turn(0, "interviewer", "Tell me about caching and why you would"), turn(1, "candidate", "Wait, which cache layer?"),
             turn(2, "interviewer", "The CDN one."), turn(3, "candidate", "ok", metrics=m)]
    turns[0].interrupted = True
    errors = [err("pronunciation", "pron:phoneme:θ", word="think", turn_id=turns[3].id, dismissed=False),
              err("pronunciation", "pron:phoneme:θ", word="think", turn_id=turns[3].id, dismissed=False),
              err("pronunciation", "pron:suspect", word="redis", turn_id=turns[3].id, dismissed=False),
              err("grammar", "gram:article", dismissed=False), err("grammar", "gram:article", dismissed=True)]
    report, scores = deterministic_part(InterviewSession(type="technical"), turns, errors)
    assert report["pronunciation"] == {"scored_words": 100, "error_words": 1, "accuracy": 99.0}
    # 120 words from metrics + 4 counted from the text of the turn without metrics, over 60 s
    assert report["fluency"]["wpm"] == 124.0 and report["fluency"]["fillers_per_min"] == 6.0
    assert report["errors_by_kind"] == {"pronunciation": 2, "grammar": 1}
    assert scores["grammar_per_100_words"] == round(100 / report["fluency"]["words"], 2)
    (ex,) = interruption_examples(turns)
    assert ex["candidate_said"].startswith("Wait") and not ex["polite_opener"]
