"""Spec 05 end to end: reports, dashboard trends over 3 sessions, drills and the error
explorer. Needs Postgres; the drill-attempt test also needs the model server."""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest

from api.config import get_settings
from api.db.constants import DEFAULT_USER_ID
from tests.conftest import BASE, FakeLLM, _dsn, is_up, restore_adjustments_rows, snapshot_adjustments, track
from tests.test_ws_integration import synth_16k

THINK_SENTENCES = ["I think the cache should sit in front of the database.",
                   "We think the queue absorbs the traffic spikes nicely."]


def route(messages: list[dict]) -> str:
    system = messages[0]["content"]
    if system.startswith("You evaluate a mock job interview"):
        return json.dumps({
            "rubric": [
                {"criterion": "technical_correctness", "score": 4, "justification": "Mostly correct answers."},
                {"criterion": "depth", "score": 3, "justification": "Some depth on caching."},
                {"criterion": "clarity", "score": 3, "justification": "Clear enough."},
                {"criterion": "practical_examples", "score": 2, "justification": "Few real examples."},
                {"criterion": "made_up", "score": 5, "justification": "not in the rubric"},
            ],
            "strengths": ["Good caching basics"],
            "improvements": ["Give examples", "Quantify impact", "Discuss trade-offs", "Extra one"],
            "better_answer": {"question": "How would you cache?", "answer_summary": "Use Redis.",
                              "improved_answer": "I would put a read-through cache in front of the database..."},
            "interruptions": None,
        })
    if system.startswith("You create speaking drills"):
        payload = json.loads(messages[1]["content"])
        return json.dumps({
            "pron": [{"id": p["id"], "sentences": THINK_SENTENCES if p["word"] == "think" else ["no target word here"]}
                     for p in payload["pron"]],
            "tech": [{"id": t["id"], "prompt": "Explain cache invalidation in 30 to 60 seconds.",
                      "key_points": ["TTL", "write-through", "delete on update"]} for t in payload["tech"]],
        })
    return "{}"


async def db() -> asyncpg.Connection:
    return await asyncpg.connect(_dsn())


@pytest.fixture
async def clean_drills():
    start = datetime.now(UTC)
    yield
    conn = await db()
    try:
        await conn.execute("DELETE FROM drill_sessions WHERE user_id = $1 AND created_at >= $2", DEFAULT_USER_ID, start)
        await conn.execute("DELETE FROM drill_items WHERE user_id = $1 AND created_at >= $2", DEFAULT_USER_ID, start)
    finally:
        await conn.close()


async def seed_session(c: httpx.AsyncClient, days_ago: int, errors: list[tuple[str, str, int]]) -> str:
    """A completed technical session `days_ago` days back with one analyzed candidate turn.
    errors: (kind, category, count)."""
    sid = track("interview_sessions", (await c.post("/api/sessions", json={"type": "technical"})).json()["id"])
    when = datetime.now(UTC) - timedelta(days=days_ago)
    metrics = {"words": 100, "speaking_s": 50, "filler_count": 2, "long_pauses": [],
               "word_z": [0.0] * 80, "phone_counts": {"θ": 10, "ɪ": 30}}
    conn = await db()
    try:
        await conn.execute("UPDATE interview_sessions SET started_at = $2, ended_at = $2, status = 'completed' "
                           "WHERE id = $1::uuid", sid, when)
        q_turn, a_turn = uuid.uuid4(), uuid.uuid4()
        await conn.execute("INSERT INTO turns (id, session_id, idx, role, full_text, spoken_text, started_at) "
                           "VALUES ($1, $2::uuid, 0, 'interviewer', 'How would you cache sessions?', "
                           "'How would you cache sessions?', $3)", q_turn, sid, when)
        await conn.execute("INSERT INTO turns (id, session_id, idx, role, full_text, spoken_text, started_at, "
                           "metrics, analysis_status) VALUES ($1, $2::uuid, 1, 'candidate', $3, $3, $4, $5, 'done')",
                           a_turn, sid, "I think we use the Redis for the sessions.", when, json.dumps(metrics))
        for kind, category, count in errors:
            for _ in range(count):
                extra = ("think", "θ ɪ ŋ k", "t ɪ ŋ k", 0) if kind == "pronunciation" else (None, None, None, None)
                await conn.execute(
                    "INSERT INTO errors (id, user_id, session_id, turn_id, kind, category, severity, original_text, "
                    "corrected_text, explanation, word, expected_phonemes, heard_phonemes, phoneme_index, created_at) "
                    "VALUES ($1,$2,$3::uuid,$4,$5,$6,'medium',$7,$8,'why',$9,$10,$11,$12,$13)",
                    uuid.uuid4(), DEFAULT_USER_ID, sid, a_turn, kind, category,
                    "the Redis" if kind != "pronunciation" else "think", "Redis" if kind != "pronunciation" else None,
                    *extra, when)
    finally:
        await conn.close()
    return sid


async def wait_report(c: httpx.AsyncClient, sid: str, timeout: float = 20) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = (await c.get(f"/api/sessions/{sid}")).json()
        if s["report"]:
            return s
        await asyncio.sleep(0.2)
    raise AssertionError("report not generated")


@pytest.fixture
async def keep_adjustments():
    saved = await snapshot_adjustments()
    yield
    await restore_adjustments_rows(saved)


async def test_reports_dashboard_drills_and_explorer(server, fresh_data, use_llm, clean_drills, keep_adjustments):
    llm = use_llm(FakeLLM(json_router=route))
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        old = await seed_session(c, 40, [("grammar", "gram:preposition", 5), ("grammar", "gram:article", 2)])
        mid = await seed_session(c, 20, [("grammar", "gram:article", 6), ("pronunciation", "pron:phoneme:θ", 1)])
        new = await seed_session(c, 5, [("grammar", "gram:article", 1), ("pronunciation", "pron:phoneme:θ", 4),
                                        ("technical", "tech:caching", 1)])
        for sid in (old, mid, new):
            assert (await c.post(f"/api/sessions/{sid}/report")).status_code == 202
            session = await wait_report(c, sid)

        report = session["report"]  # newest session
        assert report["llm_ok"]
        assert [r["criterion"] for r in report["rubric"]] == ["technical_correctness", "depth", "clarity", "practical_examples"]
        assert len(report["improvements"]) == 3 and report["better_answer"]["improved_answer"]
        assert report["pronunciation"] == {"scored_words": 80, "error_words": 1, "accuracy": 98.8}
        assert session["scores"]["overall"] == 3.0 and session["scores"]["grammar_per_100_words"] == 1.0

        dash = (await c.get("/api/dashboard")).json()
        mine = [s for s in dash["sessions"] if s["session_id"] in (old, mid, new)]
        assert [s["session_id"] for s in mine] == [old, mid, new]  # chronological
        assert [s["grammar_per_100_words"] for s in mine] == [7.0, 6.0, 1.0]
        top = {t["category"]: t for t in dash["top_errors"]}
        assert top["gram:article"]["trend"] == "down"
        assert top["pron:phoneme:θ"]["trend"] == "up"
        assert "gram:preposition" in {o["category"] for o in dash["overcome"]["categories"]}
        theta = next(p for p in dash["phonemes"] if p["phoneme"] == "θ")
        assert theta["errors"] == 5 and theta["error_rate"] == round(5 / 30, 4)

        items = (await c.get("/api/drills/items")).json()
        by_key = {(i["kind"], i["focus"]): i for i in items}
        think = by_key[("pron_read", "θ")]
        assert think["target_text"] == " ".join(THINK_SENTENCES) and think["occurrences"] == 2  # reinforced
        assert by_key[("grammar_rewrite", "gram:article")]["target_text"] == "Redis"
        assert by_key[("tech_explain", "tech:caching")]["prompt_text"].startswith("Explain cache invalidation")
        assert not any(i["kind"] == "pron_read" and i["target_text"] == "no target word here" for i in items)
        assert (await c.get("/api/drills/summary")).json()["due"] >= 3

        grammar = (await c.get("/api/errors", params={"kind": "grammar"})).json()
        assert grammar["total"] == 14 and all(e["kind"] == "grammar" for e in grammar["items"])
        pron = (await c.get("/api/errors", params={"category": "pron:"})).json()
        assert pron["total"] == 5
        await c.post(f"/api/errors/{pron['items'][0]['id']}/dismiss")
        assert (await c.get("/api/errors", params={"category": "pron:"})).json()["total"] == 4
        assert (await c.get("/api/errors", params={"category": "pron:", "dismissed": True})).json()["total"] == 1
    assert llm.json_calls  # report + drills went through the LLM


@pytest.mark.skipif(not is_up(f"{get_settings().model_server_url}/health"), reason="model server not running")
async def test_drill_session_attempts_update_srs(server, use_llm, clean_drills):
    use_llm(FakeLLM())
    conn = await db()
    try:
        now = datetime.now(UTC)
        ids = {}
        for kind, prompt, target, focus, lapses in [
            ("pron_read", 'Read aloud, paying attention to "think".', " ".join(THINK_SENTENCES), "θ", 0),
            ("grammar_rewrite", "I work here since 2020", "I have worked here since 2020", "gram:verb_tense", 2),
            ("tech_explain", "Explain cache invalidation.", "TTL; write-through", "tech:caching", 1),
        ]:
            ids[kind] = uuid.uuid4()
            await conn.execute(
                "INSERT INTO drill_items (id, user_id, kind, prompt_text, target_text, focus, dedup_key, lapses, due_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)", ids[kind], DEFAULT_USER_ID, kind, prompt, target, focus,
                f"test|{uuid.uuid4()}", lapses, now - timedelta(minutes=5))
    finally:
        await conn.close()

    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        session = (await c.post("/api/drills/sessions")).json()
        order = [i["id"] for i in session["items"] if i["id"] in {str(v) for v in ids.values()}]
        assert order == [str(ids["grammar_rewrite"]), str(ids["tech_explain"]), str(ids["pron_read"])]  # lapses first

        async def attempt(kind: str, text: str) -> dict:
            r = await c.post(f"/api/drills/sessions/{session['id']}/attempts", params={"item_id": str(ids[kind])},
                             content=await synth_16k(text))
            assert r.status_code == 200, r.text
            return r.json()

        read = await attempt("pron_read", " ".join(THINK_SENTENCES))  # script mode on a clean read
        assert read["passed"], read
        assert read["item"]["interval_days"] == 1.0 and read["item"]["repetitions"] == 1

        stopped = await attempt("pron_read", " ".join(THINK_SENTENCES).replace("think", "tink"))  # /θ/ → /t/
        assert not stopped["passed"] and "/θ/" in stopped["feedback"], stopped
        assert stopped["item"]["lapses"] == 1 and stopped["item"]["repetitions"] == 0

        rewrite = await attempt("grammar_rewrite", "I have worked here since 2020.")
        assert rewrite["passed"] and rewrite["details"]["similarity"] >= 0.8

        wrong = await attempt("grammar_rewrite", "I work here since 2020.")
        assert not wrong["passed"] and wrong["item"]["lapses"] == 3  # back soon
        assert datetime.fromisoformat(wrong["item"]["due_at"]) < datetime.now(UTC) + timedelta(minutes=11)

        tech = await attempt("tech_explain", "Cache invalidation is hard.")
        assert not tech["passed"] and "Too short" in tech["feedback"]

        summary = (await c.post(f"/api/drills/sessions/{session['id']}/finish")).json()
        assert summary == {"attempts": 5, "passed": 2, "items": 3}
