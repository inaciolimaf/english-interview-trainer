"""Audio clips for errors only (section 10.3): Opus files under data/audio_clips/."""

import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

from api.config import get_settings

SR = 16_000
PRON_PAD_MS = 300  # pronunciation: the word ± 300 ms
MAX_CLIP_MS = 12_000


def clip_path(user_id: uuid.UUID, session_id: uuid.UUID, error_id: uuid.UUID) -> Path:
    path = get_settings().data_path / "audio_clips" / str(user_id) / str(session_id) / f"{error_id}.opus"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cut(pcm16: bytes, start_ms: int, end_ms: int, pad_ms: int = 0) -> tuple[np.ndarray, int, int]:
    """Slice of the turn audio as float32, clamped to the turn and to MAX_CLIP_MS.
    Returns (audio, start_ms, end_ms) actually used."""
    total_ms = len(pcm16) // 2 * 1000 // SR
    start = max(0, start_ms - pad_ms)
    end = min(total_ms, end_ms + pad_ms, start + MAX_CLIP_MS)
    samples = np.frombuffer(pcm16, dtype="<i2")[start * SR // 1000 : end * SR // 1000]
    return samples.astype(np.float32) / 32768.0, start, end


def save_opus(audio: np.ndarray, path: Path) -> None:
    sf.write(path, audio, SR, format="OGG", subtype="OPUS")
