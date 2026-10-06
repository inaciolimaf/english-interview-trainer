"""Interview engine over the WebSocket (spec 03): time management and closing, the
end-of-interview token, the tough interviewer's cut-in and abandoned sessions.
Needs Postgres and the model server; the LLM is faked."""

import asyncio
import json

import pytest
import websockets

from api.config import get_settings
from api.interview.prompts import END_MARKER
from api.realtime import orchestrator as orch_module
from api.realtime import ws as ws_module
from tests.conftest import PORT, FakeLLM, db_fetchval, is_up
from tests.test_ws_integration import (
    GREETING, Client, finish_greeting, is_type, open_session, state_is, synth_16k,
)

pytestmark = pytest.mark.skipif(
    not is_up(f"{get_settings().model_server_url}/health"), reason="model server not running"
)

GOODBYE = f"Thanks a lot for your time today, it was great talking to you. Goodbye! {END_MARKER}"


async def backdate(session_id: str, minutes: float) -> None:
    await db_fetchval(
        "UPDATE interview_sessions SET started_at = now() - make_interval(secs => $2) WHERE id = $1::uuid",
        session_id, minutes * 60,
    )


async def reconnect(session_id: str) -> Client:
    return Client(await websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview/{session_id}", max_size=None))


async def test_time_up_closes_the_interview(server, use_llm):
    llm = FakeLLM([GREETING, GOODBYE])
    session_id, client = await open_session(
        llm, use_llm, duration_min=15, before_connect=lambda sid: backdate(sid, 15.5)  # past the end
    )
    try:
        await finish_greeting(client)
        await client.speak(await synth_16k("No, I don't have any questions."), realtime=False)
        sentence = await client.until(is_type("tts_sentence"), timeout=15)
        assert END_MARKER not in sentence["text"]
        end = await client.until(is_type("tts_end"))
        await client.ws.send(json.dumps({"type": "playback_done", "turn_id": end["turn_id"]}))
        await client.until(is_type("session_ended"), timeout=5)
        assert "Time is up" in llm.calls[-1][-1]["content"]  # time note is the last message
        assert llm.calls[-1][0] == llm.calls[0][0]  # same system prompt for the whole session
    finally:
        await client.ws.close()
    assert await db_fetchval("SELECT status FROM interview_sessions WHERE id = $1::uuid", session_id) == "completed"
    turns = await db_fetchval("SELECT string_agg(full_text, ' ') FROM turns WHERE session_id = $1::uuid", session_id)
    assert END_MARKER not in turns


async def test_early_end_token_is_ignored(server, use_llm):
    llm = FakeLLM([f"Hi, I'm Alex. Let's get started with the first question. {END_MARKER}"])
    session_id, client = await open_session(llm, use_llm, duration_min=30)
    try:
        await finish_greeting(client)  # reaches LISTENING instead of ending
        await client.drain(0.5)
        assert not any(m.get("type") == "session_ended" for m in client.log)
    finally:
        await client.ws.close()


async def test_tough_interviewer_cuts_in_on_long_answers(server, use_llm, monkeypatch):
    monkeypatch.setattr(orch_module, "TOUGH_CUT_IN_S", 2.0)
    llm = FakeLLM([GREETING, "Let me stop you there. What was your own role in that project?"])
    session_id, client = await open_session(llm, use_llm, interviewer_style="tough")
    try:
        await finish_greeting(client)
        speech = await synth_16k(
            "So in my last company we had a monolith and we decided to split it, and first we "
            "looked at the billing module because it had the most traffic and the most incidents"
        )
        talking = asyncio.create_task(client.speak(speech, realtime=True))  # ~6 s, no pause
        final = await client.until(is_type("transcript_final"), timeout=6)
        assert not talking.done()  # cut in while the candidate is still talking
        await client.until(is_type("tts_sentence"), timeout=5)
        await talking
        await client.drain(0.5)
        assert "cutting in" in llm.calls[-1][-1]["content"]
        assert final["text"]
        # the speech we cut into must not count as a barge-in against our own cut-in
        assert not any(m.get("type") in ("duck", "stop_playback") for m in client.log)
    finally:
        await client.ws.close()


async def test_dropped_connection_marks_session_abandoned_and_rejoin_reactivates(server, use_llm, monkeypatch):
    monkeypatch.setattr(ws_module, "ABANDON_GRACE_S", 0.5)
    session_id, client = await open_session(FakeLLM([GREETING]), use_llm)
    await finish_greeting(client)
    await client.ws.close()  # no end_session: tab closed / network drop
    await asyncio.sleep(1.2)
    status = "SELECT status FROM interview_sessions WHERE id = $1::uuid"
    assert await db_fetchval(status, session_id) == "abandoned"

    again = await reconnect(session_id)
    try:
        await again.until(state_is("LISTENING"))  # history reloaded: greeting already given
        assert await db_fetchval(status, session_id) == "active"
    finally:
        await again.ws.close()
