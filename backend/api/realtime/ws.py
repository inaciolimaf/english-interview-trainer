import asyncio
import json
import logging
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update

from api.db.models import InterviewSession
from api.db.session import SessionLocal
from api.llm.client import LLMClient, get_llm
from api.realtime.model_client import ModelClient
from api.realtime.orchestrator import Orchestrator

log = logging.getLogger("realtime")
router = APIRouter()

ABANDON_GRACE_S = 120  # a dropped connection may come back (reconnect) within this window
STALE_AFTER = timedelta(hours=1)  # on startup: active sessions this far past their end

_connections: Counter[uuid.UUID] = Counter()
_tasks: set[asyncio.Task] = set()


def get_models(websocket: WebSocket) -> ModelClient:
    return websocket.app.state.models


async def mark_abandoned_if_gone(session_id: uuid.UUID) -> None:
    await asyncio.sleep(ABANDON_GRACE_S)
    if _connections[session_id]:
        return
    async with SessionLocal() as db:
        await db.execute(
            update(InterviewSession)
            .where(InterviewSession.id == session_id, InterviewSession.status == "active")
            .values(status="abandoned", ended_at=datetime.now(UTC))
        )
        await db.commit()
    log.info("session %s abandoned", session_id)


async def abandon_stale_sessions() -> None:
    """Startup cleanup: sessions left active by a crash or a closed tab long ago."""
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        sessions = (await db.scalars(select(InterviewSession).where(InterviewSession.status == "active"))).all()
        for s in sessions:
            if s.started_at + timedelta(minutes=s.duration_min) + STALE_AFTER < now:
                s.status, s.ended_at = "abandoned", now
        await db.commit()


@router.websocket("/ws/interview/{session_id}")
async def interview_ws(
    websocket: WebSocket,
    session_id: uuid.UUID,
    llm: LLMClient = Depends(get_llm),
    models: ModelClient = Depends(get_models),
) -> None:
    await websocket.accept()
    ended = False

    async def on_ended() -> None:
        nonlocal ended
        ended = True
        await websocket.close()

    orch = Orchestrator(
        session_id,
        send_json=lambda m: websocket.send_text(json.dumps(m)),
        send_bytes=websocket.send_bytes,
        llm=llm,
        models=models,
        on_ended=on_ended,
        analysis=websocket.app.state.analysis,
    )
    try:
        await orch.start()
    except LookupError:
        await websocket.close(code=4404, reason="session not found")
        return
    _connections[session_id] += 1
    try:
        while not ended:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                orch.on_audio(msg["bytes"])
            elif msg.get("text") is not None:
                data = json.loads(msg["text"])
                if data.get("type") == "end_session":
                    await orch.end_session()
                    break
                await orch.on_message(data)
    except (WebSocketDisconnect, RuntimeError):
        pass  # RuntimeError: receive after close (session ended by the server)
    finally:
        await orch.close()
        _connections[session_id] -= 1
        if not ended:
            task = asyncio.create_task(mark_abandoned_if_gone(session_id))
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)
