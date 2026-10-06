"""HTTP client for the model server (STT, TTS stream, end-of-turn)."""

import base64
from collections.abc import AsyncIterator

import httpx

from api.config import get_settings
from model_server.framing import read_frames


class ModelServerError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.http = httpx.AsyncClient(
            base_url=base_url or get_settings().model_server_url,
            timeout=httpx.Timeout(30.0, connect=2.0),
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def transcribe(self, pcm16: bytes, prompt: str | None = None) -> dict:
        try:
            r = await self.http.post(
                "/transcribe", content=pcm16, params={"prompt": prompt} if prompt else None
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelServerError(f"transcription failed: {exc!r}") from exc
        return r.json()

    async def end_of_turn(self, pcm16: bytes) -> float | None:
        """P(turn complete), or None if the detector is unavailable (policy falls back)."""
        try:
            r = await self.http.post("/end_of_turn", content=pcm16)
            r.raise_for_status()
        except httpx.HTTPError:
            return None
        return r.json()["probability"]

    async def tts(self, text: str, voice: str | None, speed: float) -> AsyncIterator[tuple[dict, bytes]]:
        """Yield ({words, sample_rate}, pcm16) per Kokoro chunk."""
        try:
            async with self.http.stream(
                "POST", "/tts", json={"text": text, "voice": voice, "speed": speed}
            ) as r:
                r.raise_for_status()
                meta: dict | None = None
                async for frame in read_frames(r.aiter_bytes()):
                    if isinstance(frame, dict):
                        meta = frame
                    elif meta is not None:
                        yield meta, frame
                        meta = None
        except httpx.HTTPError as exc:
            raise ModelServerError(f"TTS failed: {exc!r}") from exc

    async def phonemes(self, pcm16: bytes, words: list[list[str]]) -> list[dict]:
        """Per-word phoneme scores for one window (low priority on the GPU)."""
        try:
            r = await self.http.post(
                "/phonemes", json={"audio_b64": base64.b64encode(pcm16).decode(), "words": words},
                timeout=120,  # queued behind conversation work by design
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelServerError(f"phoneme scoring failed: {exc!r}") from exc
        return r.json()["words"]
