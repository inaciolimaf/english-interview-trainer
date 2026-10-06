"""AI coach: debrief start, questions, persistence, grounding data. Needs Postgres; LLM faked."""

import json
import uuid

import httpx

from api.db.constants import DEFAULT_USER_ID
from tests.conftest import FakeLLM, db_fetchval, track

REPORT = {"rubric": [{"criterion": "clarity", "label": "Clear explanations", "score": 2, "justification": "Hard to follow."}],
          "strengths": ["Real examples"], "improvements": ["Structure answers"], "better_answer": None,
          "interruptions": None, "llm_ok": True, "analysis_pending": 0}


async def make_session(c: httpx.AsyncClient, with_report: bool = True) -> tuple[str, uuid.UUID]:
    sid = track("interview_sessions", (await c.post("/api/sessions", json={"type": "technical"})).json()["id"])
    error_id = uuid.uuid4()
    await db_fetchval("UPDATE interview_sessions SET report = $2::jsonb, scores = $3::jsonb WHERE id = $1::uuid",
                      sid, json.dumps(REPORT) if with_report else None, json.dumps({"overall": 2.0}))
    await db_fetchval(
        "INSERT INTO errors (id, user_id, session_id, kind, category, severity, original_text, corrected_text, explanation) "
        "VALUES ($1, $2, $3::uuid, 'grammar', 'gram:preposition', 'medium', 'handle with the requests', "
        "'handle the requests', 'handle takes a direct object')", error_id, DEFAULT_USER_ID, sid)
    return sid, error_id


async def test_coach_debrief_and_questions(server, use_llm):
    llm = use_llm(FakeLLM(["Overall you did well. Point 1: structure. [[say:handle the requests]]",
                           "Because handle takes a direct object.", "Point 2: fluency."]))
    async with httpx.AsyncClient(base_url=server, timeout=30) as c:
        sid, error_id = await make_session(c)
        start = await c.post(f"/api/sessions/{sid}/coach", json={})
        assert start.status_code == 200 and start.text.startswith("Overall you did well.")
        system = llm.calls[0][0]["content"]
        assert str(error_id) in system and "gram:preposition" in system and "Clear explanations: 2/5" in system
        assert llm.calls[0][-1]["content"] == "Start the debrief."

        answer = await c.post(f"/api/sessions/{sid}/coach", json={"message": "Why is 'handle with' wrong?"})
        assert "direct object" in answer.text
        assert llm.calls[1][-1] == {"role": "user", "content": "Why is 'handle with' wrong?"}
        assert llm.calls[1][0]["content"] == system  # same system prompt → prompt cache hits

        await c.post(f"/api/sessions/{sid}/coach", json={})  # "next point"
        assert llm.calls[2][-1]["content"] == "Next point, please."

        history = (await c.get(f"/api/sessions/{sid}/coach")).json()
        assert [m["role"] for m in history] == ["assistant", "user", "assistant", "user", "assistant"]  # start is hidden
        assert (await c.delete(f"/api/sessions/{sid}/coach")).status_code == 204
        assert (await c.get(f"/api/sessions/{sid}/coach")).json() == []


async def test_coach_needs_a_report(server, use_llm):
    use_llm(FakeLLM())
    async with httpx.AsyncClient(base_url=server, timeout=30) as c:
        sid, _ = await make_session(c, with_report=False)
        assert (await c.post(f"/api/sessions/{sid}/coach", json={})).status_code == 409
