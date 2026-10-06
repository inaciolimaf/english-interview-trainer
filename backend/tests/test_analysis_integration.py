"""Spec 04 end to end. Needs Postgres and the model server; the LLM is faked."""

import asyncio
import json
import uuid

import asyncpg
import httpx
import pytest

from api.config import get_settings
from api.db.constants import DEFAULT_USER_ID
from api.pronunciation.pipeline import find_candidates, normalize, score_turn
from api.pronunciation.rules import Calibration, Context, Stats, Variants
from api.realtime.model_client import ModelClient
from tests.conftest import (
    BASE, FakeLLM, _dsn, db_fetchval, is_up, restore_adjustments_rows, snapshot_adjustments, track,
)
from tests.test_ws_integration import GREETING, finish_greeting, is_type, open_session, synth_16k

pytestmark = pytest.mark.skipif(
    not is_up(f"{get_settings().model_server_url}/health"), reason="model server not running"
)


async def calibration_from_db() -> Calibration:
    conn = await asyncpg.connect(_dsn())
    try:
        rows = await conn.fetch("SELECT phoneme, native_mean, native_std FROM phoneme_calibration")
    finally:
        await conn.close()
    stats = {r["phoneme"]: Stats(r["native_mean"], r["native_std"]) for r in rows}
    return Calibration({k: v for k, v in stats.items() if k != "*"}, fallback=stats.get("*", Stats(3.5, 2.7)))


async def analyze_said(said: str, whisper_heard: dict[str, str]) -> list:
    """Synthesize ``said``, transcribe it, pretend Whisper 'corrected' some words, run detection."""
    models = ModelClient()
    try:
        pcm = await synth_16k(said)
        words = (await models.transcribe(pcm))["words"]
        for w in words:
            fixed = whisper_heard.get(normalize(w["w"]))
            if fixed:
                w["w"] = fixed
        ctx = Context(calibration=await calibration_from_db(), variants=Variants(general={("ʊ", "ʌ"), ("ʊ", "ə")}))
        results = await score_turn(models, pcm, words)
        return find_candidates(ctx, words, results)
    finally:
        await models.close()


async def test_detects_th_stopping_that_whisper_hides():
    bad = await analyze_said("We measured the truput of the new system.", {"truput": "throughput", "trueput": "throughput"})
    theta = [c for c in bad if c.word == "throughput" and c.phone == "θ"]
    assert theta, [(c.word, c.phone, c.heard_phone, c.score) for c in bad]
    assert theta[0].heard_phone == "t" and theta[0].category == "pron:phoneme:θ"

    good = await analyze_said("We measured the throughput of the new system.", {})
    assert not [c for c in good if c.word == "throughput" and c.phone == "θ"]


def route(messages: list[dict]) -> str:
    """Fake LLM in JSON mode, answering by request type with data taken from the request."""
    payload = json.loads(messages[1]["content"])
    if "candidates" in payload:  # pronunciation filter: keep the first candidate
        return json.dumps({"keep": [{"id": 0, "severity": "high", "explanation": "Use /θ/."}]})
    first_words = " ".join(payload["candidate_answer"].split()[:3])
    return json.dumps({"issues": [
        {"kind": "grammar", "category": "gram:verb_tense", "original_text": first_words,
         "corrected_text": first_words + " (fixed)", "explanation": "Use the present perfect.", "severity": "high"},
        {"kind": "grammar", "category": "gram:article", "original_text": "words never spoken here",
         "corrected_text": "-", "explanation": "invented", "severity": "high"},
    ]})


async def test_turn_analysis_live_feedback_and_clips(server, use_llm):
    llm = FakeLLM([GREETING, "I see. What did you measure?"], json_router=route)
    session_id, client = await open_session(llm, use_llm, feedback_mode="live")
    try:
        await finish_greeting(client)
        await client.speak(await synth_16k("I work here since two thousand twenty on the billing system."), realtime=False)
        live = await client.until(is_type("live_feedback"), timeout=30)
    finally:
        await client.ws.close()
    assert 1 <= len(live["items"]) <= 3
    assert any(i["category"] == "gram:verb_tense" for i in live["items"])
    assert not any(i["explanation"] == "invented" for i in live["items"])

    async with httpx.AsyncClient(base_url=BASE) as c:
        errors = (await c.get(f"/api/sessions/{session_id}/errors")).json()
        grammar = next(e for e in errors if e["category"] == "gram:verb_tense")
        assert grammar["audio_url"]  # anchored → clip of the sentence
        clip = await c.get(grammar["audio_url"])
        assert clip.status_code == 200 and clip.headers["content-type"] == "audio/ogg"
        assert clip.content[:4] == b"OggS"
        turn = next(t for t in (await c.get(f"/api/sessions/{session_id}")).json()["turns"] if t["role"] == "candidate")
        assert turn["analysis_status"] == "done" and turn["metrics"]["wpm"] > 0
    assert all(e["explanation"] != "invented" for e in errors)


@pytest.fixture
async def restore_adjustments():
    saved = await snapshot_adjustments()
    await restore_adjustments_rows([])  # start from no adjustments
    yield
    await restore_adjustments_rows(saved)


async def test_not_an_error_adjusts_thresholds(server, use_llm, restore_adjustments):
    use_llm(FakeLLM())
    async with httpx.AsyncClient(base_url=BASE) as c:
        session_id = track("interview_sessions", (await c.post("/api/sessions", json={"type": "technical"})).json()["id"])
        ids = [uuid.uuid4() for _ in range(2)]
        for eid in ids:
            await db_fetchval(
                "INSERT INTO errors (id, user_id, session_id, kind, category, severity, word, expected_phonemes, "
                "heard_phonemes, phoneme_index, explanation) VALUES ($1, $2, $3::uuid, 'pronunciation', "
                "'pron:phoneme:θ', 'medium', 'think', 'θ ɪ ŋ k', 't ɪ ŋ k', 0, 'x')",
                eid, DEFAULT_USER_ID, session_id)
        first = (await c.post(f"/api/errors/{ids[0]}/dismiss")).json()
        assert first["dismissed"]
        q = "SELECT \"offset\" FROM user_phoneme_adjustments WHERE phoneme = 'θ' AND word IS NOT DISTINCT FROM $1"
        assert await db_fetchval(q, None) == 0.5
        assert await db_fetchval(q, "think") is None
        await c.post(f"/api/errors/{ids[1]}/dismiss")  # same word again → word-specific tolerance
        assert await db_fetchval(q, None) == 1.0
        assert await db_fetchval(q, "think") == 1.0
        listed = (await c.get(f"/api/sessions/{session_id}/errors")).json()
        assert all(e["dismissed"] for e in listed)
