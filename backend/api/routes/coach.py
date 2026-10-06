import io
import logging
import uuid
import wave
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.coach.coach import START, build_context, build_messages
from api.db.models import Error, InterviewSession, Turn, User, UserSettings
from api.db.session import SessionLocal, get_db
from api.deps import get_current_user
from api.llm.client import LLMClient, get_llm
from api.realtime.model_client import ModelServerError

log = logging.getLogger("coach")
router = APIRouter()

COACH_MAX_TOKENS = 1200


class CoachMessage(BaseModel):
    message: str | None = Field(default=None, max_length=4000)  # None = start / continue the debrief


async def _owned_session(db: AsyncSession, user: User, session_id: uuid.UUID) -> InterviewSession:
    session = await db.get(InterviewSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Session not found")
    return session


def visible(history: list[dict]) -> list[dict]:
    return [m for m in history if not m.get("hidden")]


@router.get("/sessions/{session_id}/coach")
async def coach_history(session_id: uuid.UUID, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)) -> list[dict]:
    session = await _owned_session(db, user, session_id)
    return visible(session.coach_messages or [])


@router.delete("/sessions/{session_id}/coach", status_code=204)
async def reset_coach(session_id: uuid.UUID, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> None:
    session = await _owned_session(db, user, session_id)
    session.coach_messages = None
    await db.commit()


@router.post("/sessions/{session_id}/coach")
async def coach_reply(
    session_id: uuid.UUID, body: CoachMessage, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db), llm: LLMClient = Depends(get_llm),
) -> StreamingResponse:
    """Streams the coach's next message as plain text and saves the conversation."""
    session = await _owned_session(db, user, session_id)
    if not session.report:
        raise HTTPException(409, "The report is not ready yet")
    turns = (await db.scalars(select(Turn).where(Turn.session_id == session_id).order_by(Turn.idx))).all()
    errors = (await db.scalars(select(Error).where(Error.session_id == session_id).order_by(Error.created_at))).all()

    history: list[dict] = list(session.coach_messages or [])
    now = datetime.now(UTC).isoformat()
    if body.message and body.message.strip():
        history.append({"role": "user", "content": body.message.strip(), "at": now})
    elif not history:
        history.append({"role": "user", "content": START, "hidden": True, "at": now})
    else:
        history.append({"role": "user", "content": "Next point, please.", "at": now})
    messages = build_messages(build_context(session, turns, errors), history)

    async def stream():
        text = ""
        try:
            async for delta in llm.stream(messages, max_tokens=COACH_MAX_TOKENS):
                text += delta
                yield delta
        except Exception as exc:  # noqa: BLE001 — shown in the chat
            log.warning("coach reply failed: %r", exc)
            text += f"\n\n(Sorry — the coach could not answer: {exc})"
            yield f"\n\n(Sorry — the coach could not answer: {exc})"
        finally:
            if text.strip():  # also saves a partial answer if the page was closed mid-stream
                async with SessionLocal() as s:
                    row = await s.get(InterviewSession, session_id)
                    row.coach_messages = [*history, {"role": "assistant", "content": text,
                                                      "at": datetime.now(UTC).isoformat()}]
                    await s.commit()

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- speech helpers for the coach page (hear the correct version, ask by voice) -------------

class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)


@router.post("/speech/tts")
async def speak(body: SpeakRequest, request: Request, user: User = Depends(get_current_user),
                db: AsyncSession = Depends(get_db)) -> Response:
    settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    pcm, rate = bytearray(), 24_000
    try:
        async for meta, chunk in request.app.state.models.tts(body.text, settings.tts_voice, settings.tts_speed):
            rate = meta["sample_rate"]
            pcm.extend(chunk)
    except ModelServerError as exc:
        raise HTTPException(503, str(exc)) from exc
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(pcm))
    return Response(buf.getvalue(), media_type="audio/wav")


@router.post("/speech/stt")
async def transcribe(request: Request, user: User = Depends(get_current_user)) -> dict:
    """Body: PCM16 mono 16 kHz. Used to ask the coach by voice."""
    pcm = await request.body()
    if not 8_000 <= len(pcm) <= 120 * 16_000 * 2:
        raise HTTPException(422, "Recording must be between 0.25 and 120 seconds")
    try:
        result = await request.app.state.models.transcribe(pcm)
    except ModelServerError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"text": result["text"]}
