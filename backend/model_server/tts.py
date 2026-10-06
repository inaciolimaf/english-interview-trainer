"""Text-to-speech with Kokoro-82M (GPU), with per-word timing mapped to characters."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 24_000
_WORDLIKE = re.compile(r"\w")


@dataclass
class Token:
    text: str
    start_ms: float | None
    end_ms: float | None


def align_tokens_to_text(text: str, tokens: list[Token]) -> list[dict]:
    """Map Kokoro tokens (already offset in ms) to char ranges of the original ``text``.

    Kokoro's G2P may normalize the text (numbers, abbreviations), so tokens are matched
    left-to-right case-insensitively; tokens that can't be found are merged into the
    previous word's time range. Punctuation-only tokens are skipped.
    """
    words: list[dict] = []
    cursor = 0
    lowered = text.lower()
    for tok in tokens:
        if tok.start_ms is None or not _WORDLIKE.search(tok.text):
            continue
        idx = lowered.find(tok.text.lower(), cursor)
        if idx == -1:
            if words:
                words[-1]["end_ms"] = max(words[-1]["end_ms"], round(tok.end_ms or tok.start_ms))
            continue
        words.append({
            "w": text[idx : idx + len(tok.text)],
            "start_ms": round(tok.start_ms),
            "end_ms": round(tok.end_ms if tok.end_ms is not None else tok.start_ms),
            "char_start": idx,
            "char_end": idx + len(tok.text),
        })
        cursor = idx + len(tok.text)
    return words


class TextToSpeech:
    def __init__(self, default_voice: str) -> None:
        from kokoro import KPipeline

        self.pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cuda")
        self.default_voice = default_voice

    def warmup(self) -> None:
        for _ in self.synthesize("Hello there.", None, 1.0):
            pass

    def synthesize(self, text: str, voice: str | None, speed: float) -> Iterator[tuple[bytes, list[Token]]]:
        """Yield (pcm16 bytes at 24 kHz, tokens with absolute ms) per Kokoro chunk.

        A normal sentence is one chunk; very long text is split by Kokoro itself.
        """
        offset_ms = 0.0
        for result in self.pipeline(text, voice=voice or self.default_voice, speed=speed):
            if result.audio is None:
                continue
            audio = result.audio.detach().cpu().numpy()
            tokens = [
                Token(
                    t.text,
                    None if t.start_ts is None else offset_ms + t.start_ts * 1000,
                    None if t.end_ts is None else offset_ms + t.end_ts * 1000,
                )
                for t in (result.tokens or [])
            ]
            pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
            offset_ms += len(audio) / SAMPLE_RATE * 1000
            yield pcm, tokens
