"""Speech-to-text with faster-whisper (GPU, int8, word timestamps)."""

import numpy as np
from faster_whisper import WhisperModel

# Segments Whisper is likely hallucinating on (silence, noise, very short clips)
NO_SPEECH_PROB_MAX = 0.6
AVG_LOGPROB_MIN = -1.0


class SpeechToText:
    def __init__(self, model_name: str, compute_type: str) -> None:
        self.model = WhisperModel(model_name, device="cuda", compute_type=compute_type)

    def warmup(self) -> None:
        self.transcribe(np.zeros(16_000, dtype=np.float32))

    def transcribe(self, audio: np.ndarray, prompt: str | None = None) -> dict:
        """audio: float32 mono 16 kHz. Returns text + words with times in ms."""
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=1,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=prompt or None,
        )
        words, texts = [], []
        for seg in segments:
            if seg.no_speech_prob > NO_SPEECH_PROB_MAX and seg.avg_logprob < AVG_LOGPROB_MIN:
                continue
            texts.append(seg.text.strip())
            for w in seg.words or []:
                words.append({
                    "w": w.word.strip(),
                    "start_ms": round(w.start * 1000),
                    "end_ms": round(w.end * 1000),
                    "p": round(w.probability, 3),
                })
        return {"text": " ".join(t for t in texts if t), "words": words}
