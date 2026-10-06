"""Phoneme scoring with wav2vec2 CTC (section 8.1, steps 3–6), GPU fp16.

For one audio window (≤ ~15 s) and the expected phones of each word:
  posteriors → CTC forced alignment of the expected phones → per-phone GOP score
  (mean log-posterior of the expected phone minus the best competing phone over the
  aligned frames) → free greedy decoding over each word's frames ("heard" phones).

The decision of what counts as an error (calibration, variants, user offsets) lives in
the API (api/pronunciation/rules.py); this module only measures.
"""

import numpy as np
import torch
import torchaudio.functional as AF
from transformers import AutoFeatureExtractor, AutoTokenizer, Wav2Vec2ForCTC

FRAME_MS = 20  # wav2vec2 conv stride: 320 samples at 16 kHz

# Phones espeak-ng en-us produces, plus what a Brazilian speaker typically substitutes.
# GOP competitors are restricted to these, otherwise phones of unrelated languages
# (tonal vowels etc.) would dominate the "best competitor".
EN_US_PHONES = {
    "p", "b", "t", "d", "k", "ɡ", "f", "v", "θ", "ð", "s", "z", "ʃ", "ʒ", "h", "tʃ", "dʒ",
    "m", "n", "ŋ", "l", "ɹ", "w", "j", "ɾ", "ʔ", "i", "iː", "ɪ", "eɪ", "ɛ", "æ", "ɑː", "ɑ",
    "ɔː", "ɔ", "oʊ", "ʊ", "uː", "u", "ʌ", "ə", "ɚ", "ɜː", "aɪ", "aʊ", "ɔɪ", "ɐ", "ᵻ", "oːɹ",
    "ɑːɹ", "ɔːɹ", "ɛɹ", "ɪɹ", "ʊɹ", "aɪɚ", "aɪə", "l̩", "n̩", "əl", "iə",
}
PORTUGUESE_SUBSTITUTES = {"e", "o", "a", "r", "x", "ʁ", "ɣ", "ɲ", "ʎ", "ã", "õ", "ẽ", "ĩ", "ũ"}


class PhonemeScorer:
    def __init__(self, model_name: str) -> None:
        self.features = AutoFeatureExtractor.from_pretrained(model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = Wav2Vec2ForCTC.from_pretrained(model_name, torch_dtype=torch.float16).to("cuda").eval()
        self.vocab: dict[str, int] = self.tokenizer.get_vocab()
        self.id_to_phone = {i: p for p, i in self.vocab.items()}
        self.blank = self.tokenizer.pad_token_id
        competitors = [self.vocab[p] for p in EN_US_PHONES | PORTUGUESE_SUBSTITUTES if p in self.vocab]
        self.competitor_ids = torch.tensor(sorted(competitors), device="cuda")

    def warmup(self) -> None:
        self.score(np.zeros(16_000, dtype=np.float32), [["h", "ə"]])

    @torch.inference_mode()
    def log_posteriors(self, audio: np.ndarray) -> torch.Tensor:
        inputs = self.features(audio, sampling_rate=16_000, return_tensors="pt")
        logits = self.model(inputs.input_values.to("cuda", torch.float16)).logits[0]
        return torch.log_softmax(logits.float(), dim=-1)  # (frames, vocab)

    @torch.inference_mode()
    def score(self, audio: np.ndarray, words: list[list[str]]) -> list[dict]:
        """``words``: expected phones per word. Returns one dict per word:
        {phones: [{p, start_ms, end_ms, score, competitor} | {p, unknown: True}], heard, start_ms, end_ms}
        (``aligned: False`` when the window could not be aligned)."""
        lp = self.log_posteriors(audio)
        n_frames = lp.shape[0]

        targets: list[int] = []
        owners: list[tuple[int, int]] = []  # (word index, phone index) per target
        for wi, phones in enumerate(words):
            for pi, phone in enumerate(phones):
                if phone in self.vocab:
                    targets.append(self.vocab[phone])
                    owners.append((wi, pi))

        results = [{"phones": [{"p": p, "unknown": p not in self.vocab} for p in phones], "heard": [],
                    "aligned": False} for phones in words]
        repeats = sum(1 for a, b in zip(targets, targets[1:]) if a == b)
        if not targets or n_frames < len(targets) + repeats:
            return results  # too short to align: nothing reliable to say

        alignment, frame_scores = AF.forced_align(
            lp.unsqueeze(0), torch.tensor([targets], dtype=torch.int32, device=lp.device), blank=self.blank
        )
        spans = AF.merge_tokens(alignment[0], frame_scores[0].exp())

        word_frames: dict[int, list[int]] = {}
        for span, (wi, pi) in zip(spans, owners, strict=True):
            frames = lp[span.start : span.end]
            expected = frames[:, span.token].mean()
            others = self.competitor_ids[self.competitor_ids != span.token]
            competitor_means = frames[:, others].mean(dim=0)
            best = int(competitor_means.argmax())
            results[wi]["phones"][pi].update({
                "start_ms": span.start * FRAME_MS,
                "end_ms": span.end * FRAME_MS,
                "score": round(float(expected - competitor_means[best]), 3),
                "competitor": self.id_to_phone[int(others[best])],
            })
            word_frames.setdefault(wi, []).extend((span.start, span.end))

        for wi, frames in word_frames.items():
            start, end = max(0, min(frames) - 1), min(n_frames, max(frames) + 1)
            results[wi].update({
                "aligned": True,
                "start_ms": start * FRAME_MS,
                "end_ms": end * FRAME_MS,
                "heard": self._greedy(lp[start:end]),
            })
        return results

    def _greedy(self, lp: torch.Tensor) -> list[str]:
        ids = lp.argmax(dim=-1).tolist()
        out, prev = [], None
        for i in ids:
            if i != prev and i != self.blank:
                out.append(self.id_to_phone[i])
            prev = i
        return out
