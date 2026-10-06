"""Model server: persistent process holding the AI models (runs WITHOUT --reload).

Endpoints (all audio is raw little-endian PCM16 mono):
- POST /transcribe    body: 16 kHz PCM16, ?prompt=   → {text, words[{w,start_ms,end_ms,p}], ms}
- POST /tts           JSON {text, voice?, speed?}     → framed stream (see framing.py):
                      per Kokoro chunk a JSON {words, sample_rate} then a binary 24 kHz PCM16
- POST /end_of_turn   body: 16 kHz PCM16              → {probability, ms}
- POST /phonemes      JSON {audio_b64 (16 kHz PCM16, ≤ ~15 s), words: [[phone, ...], ...]}
                      → {words: [...per-word scores, see phonemes.py], ms}   (LOW priority)
- GET  /health                                         → {models, gpu_queue}

GPU work (STT, TTS) goes through one priority queue (gpu_queue.py); the end-of-turn
model runs on CPU in a thread.
"""

import os

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import asyncio  # noqa: E402
import base64  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

import numpy as np  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from api.config import get_settings  # noqa: E402
from model_server.framing import binary_frame, json_frame  # noqa: E402
from model_server.gpu_queue import GpuQueue, Priority  # noqa: E402

log = logging.getLogger("model_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

state: dict = {"models": []}


@asynccontextmanager
async def lifespan(_: FastAPI):
    from model_server.phonemes import PhonemeScorer
    from model_server.stt import SpeechToText
    from model_server.tts import TextToSpeech
    from model_server.turn_detector import TurnDetector

    settings = get_settings()
    queue = GpuQueue()
    queue.start()
    state["queue"] = queue

    t0 = time.perf_counter()
    state["stt"] = SpeechToText(settings.whisper_model, settings.whisper_compute_type)
    state["tts"] = TextToSpeech(settings.tts_voice)
    state["turn"] = TurnDetector()
    state["phonemes"] = PhonemeScorer(settings.phoneme_model)
    # warm-up through the queue so CUDA kernels are compiled before the first turn
    await queue.submit(Priority.HIGH, state["stt"].warmup)
    await queue.submit(Priority.HIGH, state["tts"].warmup)
    await queue.submit(Priority.LOW, state["phonemes"].warmup)
    state["turn"].probability(np.zeros(16_000, dtype=np.float32))
    state["models"] = [f"whisper:{settings.whisper_model}", "kokoro-82m", "smart-turn-v3.2",
                       f"phonemes:{settings.phoneme_model}"]
    log.info("models loaded in %.1fs", time.perf_counter() - t0)
    yield
    await queue.stop()


app = FastAPI(title="English Interview Trainer — Model Server", lifespan=lifespan)


def pcm16_to_float(body: bytes) -> np.ndarray:
    return np.frombuffer(body, dtype="<i2").astype(np.float32) / 32768.0


@app.get("/health")
async def health() -> dict:
    queue: GpuQueue | None = state.get("queue")
    return {"models": state["models"], "gpu_queue": queue.pending if queue else None}


@app.post("/transcribe")
async def transcribe(request: Request, prompt: str | None = None) -> dict:
    audio = pcm16_to_float(await request.body())
    t0 = time.perf_counter()
    result = await state["queue"].submit(Priority.HIGH, state["stt"].transcribe, audio, prompt)
    result["ms"] = round((time.perf_counter() - t0) * 1000)
    return result


@app.post("/end_of_turn")
async def end_of_turn(request: Request) -> dict:
    audio = pcm16_to_float(await request.body())
    t0 = time.perf_counter()
    prob = await asyncio.to_thread(state["turn"].probability, audio)
    return {"probability": prob, "ms": round((time.perf_counter() - t0) * 1000)}


class TtsRequest(BaseModel):
    text: str
    voice: str | None = None
    speed: float = 1.0


@app.post("/tts")
async def tts(req: TtsRequest) -> StreamingResponse:
    from model_server.tts import SAMPLE_RATE, align_tokens_to_text

    chunks = state["tts"].synthesize(req.text, req.voice, req.speed)

    async def stream():
        # one GPU job per Kokoro chunk; stops early if the API disconnects (barge-in)
        while True:
            item = await state["queue"].submit(Priority.TTS, next, chunks, None)
            if item is None:
                return
            pcm, tokens = item
            words = align_tokens_to_text(req.text, tokens)
            yield json_frame({"words": words, "sample_rate": SAMPLE_RATE})
            yield binary_frame(pcm)

    return StreamingResponse(stream(), media_type="application/octet-stream")


class PhonemesRequest(BaseModel):
    audio_b64: str
    words: list[list[str]]


@app.post("/phonemes")
async def phonemes(req: PhonemesRequest) -> dict:
    audio = pcm16_to_float(base64.b64decode(req.audio_b64))
    t0 = time.perf_counter()
    # LOW priority: one job per window, so a turn's transcription never waits for more than one
    words = await state["queue"].submit(Priority.LOW, state["phonemes"].score, audio, req.words)
    return {"words": words, "ms": round((time.perf_counter() - t0) * 1000)}
