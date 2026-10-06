"""Lets background work (turn analysis) push messages to a session's live WebSocket."""

import uuid
from collections.abc import Awaitable, Callable

Send = Callable[[dict], Awaitable[None]]
_senders: dict[uuid.UUID, Send] = {}


def register(session_id: uuid.UUID, send: Send) -> None:
    _senders[session_id] = send


def unregister(session_id: uuid.UUID, send: Send) -> None:
    if _senders.get(session_id) is send:
        del _senders[session_id]


async def push(session_id: uuid.UUID, msg: dict) -> bool:
    send = _senders.get(session_id)
    if send is None:
        return False
    await send(msg)
    return True
