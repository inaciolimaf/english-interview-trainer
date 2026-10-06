"""Length-prefixed frames for streaming JSON + binary over one HTTP body.

Each frame: 1 byte kind (J = JSON, B = binary) + uint32 little-endian length + payload.
Used by the model server's /tts stream and read by the API's model client.
"""

import json
import struct
from collections.abc import AsyncIterator

HEADER = struct.Struct("<cI")


def json_frame(obj: dict) -> bytes:
    payload = json.dumps(obj).encode()
    return HEADER.pack(b"J", len(payload)) + payload


def binary_frame(data: bytes) -> bytes:
    return HEADER.pack(b"B", len(data)) + data


async def read_frames(chunks: AsyncIterator[bytes]) -> AsyncIterator[dict | bytes]:
    buf = bytearray()
    async for chunk in chunks:
        buf.extend(chunk)
        while len(buf) >= HEADER.size:
            kind, length = HEADER.unpack_from(buf)
            if len(buf) < HEADER.size + length:
                break
            payload = bytes(buf[HEADER.size : HEADER.size + length])
            del buf[: HEADER.size + length]
            yield json.loads(payload) if kind == b"J" else payload
