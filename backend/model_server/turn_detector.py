"""End-of-turn detector: Pipecat Smart Turn v3.2 (ONNX, CPU) — choice documented in
docs/spike-report.md. Looks at the last 8 s of the candidate's audio (intonation)."""

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from transformers import WhisperFeatureExtractor

REPO = "pipecat-ai/smart-turn-v3"
FILE = "smart-turn-v3.2-cpu.onnx"
SR = 16_000
WINDOW_S = 8


class TurnDetector:
    def __init__(self) -> None:
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            hf_hub_download(REPO, FILE), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.features = WhisperFeatureExtractor(chunk_length=WINDOW_S)

    def probability(self, audio: np.ndarray) -> float:
        """P(turn is complete) for float32 mono 16 kHz audio (same preprocessing as
        pipecat's reference inference.py: keep the END of the audio)."""
        feats = self.features(
            audio[-WINDOW_S * SR :], sampling_rate=SR, return_tensors="np",
            padding="max_length", max_length=WINDOW_S * SR, truncation=True, do_normalize=True,
        ).input_features.astype(np.float32)
        return float(self.session.run(None, {self.input_name: feats})[0].reshape(-1)[0])
