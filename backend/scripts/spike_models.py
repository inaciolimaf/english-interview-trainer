"""Spec 01, part B — load every model at once on the user's hardware and measure it.

- GPU: faster-whisper (large-v3-turbo, int8) + wav2vec2 phoneme CTC (fp16) + Kokoro-82M TTS
- CPU: Pipecat Smart Turn v3 (end-of-turn detector, ONNX)
- VRAM with everything loaded, latencies, and the VERIFICAR items
- LLM streaming test: DeepSeek V4.1 Flash via OpenRouter (needs OPENROUTER_API_KEY in .env)

Writes the report to docs/spike-report.md.  Usage (from backend/): python scripts/spike_models.py
"""

import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import httpx  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torchaudio.functional as AF  # noqa: E402

from api.config import REPO_ROOT, get_settings  # noqa: E402
from api.pronunciation.g2p import WORD_SEP, espeak_phonemes  # noqa: E402

settings = get_settings()
SR = 16_000
SMART_TURN_REPO = "pipecat-ai/smart-turn-v3"
SMART_TURN_FILE = "smart-turn-v3.2-cpu.onnx"

TARGETS = {"vram_gb": 3.0, "stt_10s_s": 1.0, "tts_first_audio_ms": 300.0}

SENTENCE = "Thanks for joining today. Let's start with a quick introduction about your background."
TEXT_10S = (
    "To scale the write path, I would put a message queue in front of the database, "
    "so the API can acknowledge requests quickly and the consumers can process them asynchronously."
)
TEXT_60S = " ".join([
    "Let me walk you through the design of a URL shortener.",
    "First, the functional requirements: users submit a long URL and get a short alias back,",
    "and anyone who opens the short link is redirected to the original address.",
    "The system is read heavy, maybe a hundred reads for every write,",
    "so throughput and latency on the redirect path matter the most.",
    "For storage I would start with PostgreSQL, using the short code as the primary key,",
    "and put Redis in front of it as a cache, with a time to live of one day.",
    "To generate the codes, I prefer a counter based approach encoded in base sixty two,",
    "because it avoids collisions and keeps the codes short.",
    "If we need to scale further, we can shard the database by the hash of the code",
    "and add read replicas, accepting eventual consistency for analytics.",
    "Finally, I would add rate limiting at the load balancer to prevent abuse,",
    "and monitor the cache hit ratio, the error rate and the tail latency.",
])

results: dict = {"notes": [], "decisions": {}}


def note(msg: str) -> None:
    print(f"  · {msg}")
    results["notes"].append(msg)


def timeit(fn, runs: int = 3, warmup: int = 1) -> tuple[float, object]:
    out = None
    for _ in range(warmup):
        out = fn()
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times), out


def nvidia_smi_process_mb() -> float | None:
    """VRAM used by THIS process according to the driver (covers CTranslate2 + PyTorch)."""
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        for p in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
            if p.pid == os.getpid() and p.usedGpuMemory:
                return p.usedGpuMemory / 2**20
    except Exception as exc:  # noqa: BLE001
        print(f"pynvml failed: {exc}")
    return None


def nvidia_smi_total_mb() -> float:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    ).stdout.split(",")
    return float(out[0])


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
section("Environment")
gpu_name = torch.cuda.get_device_name(0)
baseline_vram_mb = nvidia_smi_total_mb()
results["env"] = {
    "python": platform.python_version(),
    "torch": torch.__version__,
    "torch_cuda": torch.version.cuda,
    "gpu": gpu_name,
    "gpu_total_mb": torch.cuda.get_device_properties(0).total_memory / 2**20,
    "cpu_threads": os.cpu_count(),
    "baseline_vram_mb": baseline_vram_mb,
}
print(json.dumps(results["env"], indent=2))

# ---------------------------------------------------------------------------
section("Loading Kokoro (GPU)")
from kokoro import KPipeline  # noqa: E402

t0 = time.perf_counter()
tts = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cuda")
voice = settings.tts_voice or "af_heart"
results["load_s"] = {"kokoro": time.perf_counter() - t0}
vram_after_kokoro = nvidia_smi_total_mb()
note(
    f"Kokoro loaded in {results['load_s']['kokoro']:.1f}s, voice={voice}, "
    f"+{vram_after_kokoro - baseline_vram_mb:.0f} MB VRAM"
)


def synth(text: str) -> tuple[np.ndarray, list]:
    """Full synthesis at 24 kHz; also returns Kokoro's per-token timestamps."""
    chunks, tokens = [], []
    offset = 0.0
    for r in tts(text, voice=voice):
        audio = r.audio.cpu().numpy()
        for t in r.tokens or []:
            if t.start_ts is not None:
                tokens.append((t.text, offset + t.start_ts, offset + (t.end_ts or t.start_ts)))
        chunks.append(audio)
        offset += len(audio) / 24_000
    return np.concatenate(chunks), tokens


def to_16k(audio_24k: np.ndarray) -> np.ndarray:
    return AF.resample(torch.from_numpy(audio_24k), 24_000, SR).numpy().astype(np.float32)


print("Generating test audio with Kokoro...")
a10_24, tokens10 = synth(TEXT_10S)
a60_24, _ = synth(TEXT_60S)
audio_10s, audio_60s = to_16k(a10_24), to_16k(a60_24)
# pad/trim to exactly 10 s and 60 s so latencies are comparable
audio_10s = np.pad(audio_10s, (0, max(0, 10 * SR - len(audio_10s))))[: 10 * SR]
if len(audio_60s) < 60 * SR:
    audio_60s = np.tile(audio_60s, int(np.ceil(60 * SR / len(audio_60s))))
audio_60s = audio_60s[: 60 * SR]
note(f"Test audio: 10s clip (speech {len(a10_24) / 24_000:.1f}s) and 60s clip")

# Kokoro word timestamps (VERIFICAR)
kokoro_ts_ok = len(tokens10) > 0
results["decisions"]["kokoro_timestamps"] = (
    f"AVAILABLE — KPipeline results expose per-token `start_ts`/`end_ts` (seconds) for "
    f"English (misaki G2P). Sample: "
    + ", ".join(f"{w}@{s:.2f}-{e:.2f}s" for w, s, e in tokens10[:5])
    if kokoro_ts_ok
    else "NOT available — estimate by distributing sentence duration proportionally to "
    "characters/phonemes per word."
)
note(results["decisions"]["kokoro_timestamps"])

# ---------------------------------------------------------------------------
section("Loading Smart Turn v3 (CPU, ONNX)")
import onnxruntime as ort  # noqa: E402
from huggingface_hub import hf_hub_download  # noqa: E402
from transformers import WhisperFeatureExtractor  # noqa: E402

t0 = time.perf_counter()
st_path = hf_hub_download(SMART_TURN_REPO, SMART_TURN_FILE)
so = ort.SessionOptions()
so.inter_op_num_threads = 1
so.intra_op_num_threads = 1
so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
smart_turn = ort.InferenceSession(st_path, sess_options=so, providers=["CPUExecutionProvider"])
st_features = WhisperFeatureExtractor(chunk_length=8)
results["load_s"]["smart_turn"] = time.perf_counter() - t0
st_inputs = [(i.name, i.shape) for i in smart_turn.get_inputs()]
note(f"Smart Turn loaded ({Path(st_path).stat().st_size / 2**20:.1f} MB), inputs={st_inputs}")


def end_of_turn_prob(audio_16k: np.ndarray) -> float:
    audio = audio_16k[-8 * SR:]  # keep the END of the turn (same as pipecat's inference.py)
    feats = st_features(
        audio, sampling_rate=SR, return_tensors="np", padding="max_length",
        max_length=8 * SR, truncation=True, do_normalize=True,
    ).input_features.astype(np.float32)
    return float(smart_turn.run(None, {st_inputs[0][0]: feats})[0].reshape(-1)[0])


# ---------------------------------------------------------------------------
section("Loading faster-whisper (GPU)")
from faster_whisper import WhisperModel  # noqa: E402

t0 = time.perf_counter()
whisper = WhisperModel(
    settings.whisper_model, device="cuda", compute_type=settings.whisper_compute_type
)
results["load_s"]["whisper"] = time.perf_counter() - t0
vram_after_whisper = nvidia_smi_total_mb()
note(
    f"faster-whisper {settings.whisper_model}/{settings.whisper_compute_type} loaded in "
    f"{results['load_s']['whisper']:.1f}s, +{vram_after_whisper - vram_after_kokoro:.0f} MB VRAM"
)


def transcribe(audio: np.ndarray):
    segments, _ = whisper.transcribe(
        audio, language="en", beam_size=1, word_timestamps=True, vad_filter=False,
        condition_on_previous_text=False,
    )
    return list(segments)


# ---------------------------------------------------------------------------
section("Loading wav2vec2 phonemes (GPU, fp16)")
from transformers import AutoFeatureExtractor, AutoTokenizer, Wav2Vec2ForCTC  # noqa: E402

t0 = time.perf_counter()
w2v_fe = AutoFeatureExtractor.from_pretrained(settings.phoneme_model)
w2v_tok = AutoTokenizer.from_pretrained(settings.phoneme_model)
w2v = Wav2Vec2ForCTC.from_pretrained(settings.phoneme_model, torch_dtype=torch.float16)
w2v = w2v.to("cuda").eval()
results["load_s"]["wav2vec2"] = time.perf_counter() - t0
vram_after_w2v = nvidia_smi_total_mb()
note(
    f"wav2vec2 {settings.phoneme_model} loaded in {results['load_s']['wav2vec2']:.1f}s, "
    f"+{vram_after_w2v - vram_after_whisper:.0f} MB VRAM"
)


@torch.inference_mode()
def phoneme_logprobs(audio: np.ndarray) -> torch.Tensor:
    inputs = w2v_fe(audio, sampling_rate=SR, return_tensors="pt")
    logits = w2v(inputs.input_values.to("cuda", torch.float16)).logits
    return torch.log_softmax(logits.float(), dim=-1)  # (1, frames, vocab)


# ---------------------------------------------------------------------------
section("Latencies (median of 3 after warm-up)")
lat: dict[str, float] = {}

lat["stt_10s_s"], segs10 = timeit(lambda: transcribe(audio_10s))
transcript10 = " ".join(s.text.strip() for s in segs10)
n_words = sum(len(s.words or []) for s in segs10)
note(f"STT 10s: {lat['stt_10s_s']:.3f}s — {n_words} words with timestamps — '{transcript10}'")

lat["stt_60s_s"], segs60 = timeit(lambda: transcribe(audio_60s), runs=2)
note(f"STT 60s: {lat['stt_60s_s']:.3f}s")

lat["phonemes_10s_s"], logp10 = timeit(lambda: phoneme_logprobs(audio_10s))
torch.cuda.synchronize()
greedy = logp10[0].argmax(-1).cpu().tolist()
decoded = w2v_tok.decode(greedy)
note(f"wav2vec2 10s: {lat['phonemes_10s_s']:.3f}s — greedy: '{decoded[:90]}...'")


def tts_first_audio() -> float:
    t0 = time.perf_counter()
    for _ in tts(SENTENCE, voice=voice):
        torch.cuda.synchronize()
        return time.perf_counter() - t0
    return float("nan")


tts_first_audio()  # warm-up
lat["tts_first_audio_ms"] = statistics.median(tts_first_audio() * 1000 for _ in range(5))
sent_audio, _ = synth(SENTENCE)
note(
    f"TTS first audio for one sentence ({len(sent_audio) / 24_000:.1f}s of speech): "
    f"{lat['tts_first_audio_ms']:.0f} ms (GPU)"
)

lat["end_of_turn_ms"], _ = timeit(lambda: end_of_turn_prob(audio_10s), runs=10)
lat["end_of_turn_ms"] *= 1000
p_complete = end_of_turn_prob(to_16k(a10_24))
cut = to_16k(synth("So for the database layer I would probably use")[0])
p_incomplete = end_of_turn_prob(cut)
note(
    f"Smart Turn inference: {lat['end_of_turn_ms']:.1f} ms — P(end) complete sentence="
    f"{p_complete:.2f}, incomplete ('...I would probably use')={p_incomplete:.2f} "
    f"(weak probe: Kokoro reads any text with sentence-final intonation; validate with the "
    f"user's real voice in spec 02)"
)
results["latency"] = lat
results["smart_turn_probe"] = {"complete": p_complete, "incomplete": p_incomplete}

# ---------------------------------------------------------------------------
section("VRAM with everything loaded")
torch.cuda.synchronize()
torch_peak_mb = torch.cuda.max_memory_allocated() / 2**20
torch_reserved_mb = torch.cuda.max_memory_reserved() / 2**20
process_mb = nvidia_smi_process_mb()
total_used_mb = nvidia_smi_total_mb()
results["vram"] = {
    "torch_max_allocated_mb": torch_peak_mb,
    "torch_max_reserved_mb": torch_reserved_mb,
    "process_nvidia_smi_mb": process_mb,
    "gpu_used_total_mb": total_used_mb,
    "gpu_used_by_spike_mb": total_used_mb - baseline_vram_mb,
}
print(json.dumps(results["vram"], indent=2))
vram_gb = (process_mb or (total_used_mb - baseline_vram_mb)) / 1024

# ---------------------------------------------------------------------------
section("VERIFICAR: forced alignment")
fa_info = {"available": hasattr(AF, "forced_align")}
try:
    vocab = w2v_tok.get_vocab()
    expected = espeak_phonemes(TEXT_10S).replace(WORD_SEP, " ").split()
    missing = sorted({p for p in expected if p not in vocab})
    ids = [vocab[p] for p in expected if p in vocab]
    fa_info["espeak_phones_missing_from_model_vocab"] = missing
    fa_info["coverage"] = f"{len(ids)}/{len(expected)} phones"
    blank = w2v_tok.pad_token_id
    for device in ("cuda", "cpu"):
        lp = logp10.to(device)
        targets = torch.tensor([ids], dtype=torch.int32, device=device)
        t0 = time.perf_counter()
        aligned, scores = AF.forced_align(lp, targets, blank=blank)
        if device == "cuda":
            torch.cuda.synchronize()
        fa_info[f"{device}_ms"] = (time.perf_counter() - t0) * 1000
    spans = AF.merge_tokens(aligned[0], scores[0].exp())
    fa_info["aligned_spans"] = len(spans)
    fa_info["ok"] = len(spans) == len(ids)
    results["decisions"]["forced_align"] = (
        f"AVAILABLE — torchaudio {__import__('torchaudio').__version__} "
        f"`functional.forced_align` works on CUDA ({fa_info['cuda_ms']:.1f} ms) and CPU "
        f"({fa_info['cpu_ms']:.1f} ms) for 10 s; {fa_info['aligned_spans']} spans for "
        f"{len(ids)} target phones. torchaudio has deprecated it (removal planned upstream), so "
        f"spec 04 should wrap it behind a small interface and keep a ~40-line CTC Viterbi as "
        f"fallback. espeak phones missing from the model vocab: {missing or 'none'}."
    )
except Exception as exc:  # noqa: BLE001
    fa_info["error"] = repr(exc)
    results["decisions"]["forced_align"] = (
        f"NOT usable ({exc!r}) — implement CTC Viterbi alignment in numpy/torch (spec 04)."
    )
results["forced_align"] = fa_info
note(results["decisions"]["forced_align"])

# ---------------------------------------------------------------------------
section("VERIFICAR: LLM streaming via OpenRouter")
llm: dict = {"base_url": settings.openrouter_base_url, "model": settings.llm_model}
try:
    listed = httpx.get(f"{settings.openrouter_base_url}/models", timeout=15).json()["data"]
    llm["model_listed"] = any(m["id"] == settings.llm_model for m in listed)
except Exception as exc:  # noqa: BLE001
    llm["models_error"] = repr(exc)
if not settings.openrouter_api_key:
    llm["status"] = "SKIPPED — OPENROUTER_API_KEY not set in .env"
else:
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_headers={"X-Title": "English Interview Trainer"},
    )
    try:
        t0 = time.perf_counter()
        stream = client.chat.completions.create(
            model=settings.llm_model,
            stream=True,
            max_tokens=60,
            messages=[
                {"role": "system", "content": "You are a friendly job interviewer."},
                {"role": "user", "content": "Greet the candidate in one short sentence."},
            ],
        )
        first, text, served_model = None, "", None
        for chunk in stream:
            served_model = served_model or chunk.model
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                first = first or time.perf_counter() - t0
                text += delta
        llm.update(
            status="OK", served_model=served_model,
            first_token_ms=(first or 0) * 1000, total_ms=(time.perf_counter() - t0) * 1000,
            sample=text.strip(),
        )
    except Exception as exc:  # noqa: BLE001
        llm.update(status="FAILED", error=repr(exc)[:300])
results["llm"] = llm
results["decisions"]["llm_model"] = (
    f"`{settings.llm_model}` on OpenRouter (served as `{llm['served_model']}`), streaming OK, "
    f"first token {llm['first_token_ms']:.0f} ms"
    if llm.get("status") == "OK"
    else f"`{settings.llm_model}` on OpenRouter — listed in the public model catalog: "
    f"{llm.get('model_listed')}. Live streaming call: {llm.get('status')}."
)
note(results["decisions"]["llm_model"])

results["decisions"]["turn_detector"] = (
    f"Pipecat Smart Turn v3.2 CPU (`{SMART_TURN_REPO}/{SMART_TURN_FILE}`): BSD-2-Clause, "
    f"8.7 MB ONNX int8, audio-based (captures intonation, as spec 7.4 prefers), English "
    f"supported (multilingual), {lat['end_of_turn_ms']:.0f} ms per inference on 1 CPU thread. "
    f"Rejected LiveKit turn-detector: custom restrictive license (LiveKit Agents only), "
    f"165 MB quantized ONNX, text-only (needs the transcript first)."
)

# ---------------------------------------------------------------------------
section("Verdict")
checks = {
    "VRAM ≤ 3 GB": (vram_gb <= TARGETS["vram_gb"], f"{vram_gb:.2f} GB"),
    "STT 10 s < 1 s": (lat["stt_10s_s"] < TARGETS["stt_10s_s"], f"{lat['stt_10s_s']:.3f} s"),
    "TTS first audio < 300 ms": (
        lat["tts_first_audio_ms"] < TARGETS["tts_first_audio_ms"],
        f"{lat['tts_first_audio_ms']:.0f} ms",
    ),
}
results["checks"] = {k: {"pass": v[0], "value": v[1]} for k, v in checks.items()}
for k, (ok, val) in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}  {k}: {val}")
all_pass = all(ok for ok, _ in checks.values())

# ---------------------------------------------------------------------------
lines = [
    "# Spike report — models on local hardware (spec 01, part B)",
    "",
    f"Generated by `backend/scripts/spike_models.py` on {datetime.now():%Y-%m-%d %H:%M}.",
    "",
    f"**Result: {'✅ all targets met' if all_pass else '❌ at least one target missed'}**",
    "",
    "## Environment",
    "",
    *[f"- {k}: `{v}`" for k, v in results["env"].items()],
    "",
    "## Targets",
    "",
    "| Check | Value | Result |",
    "|---|---|---|",
    *[f"| {k} | {v['value']} | {'✅' if v['pass'] else '❌'} |" for k, v in results["checks"].items()],
    "",
    "## Latencies (median, after warm-up)",
    "",
    "| Step | Value |",
    "|---|---|",
    f"| Transcription 10 s (word timestamps, beam 1) | {lat['stt_10s_s']:.3f} s |",
    f"| Transcription 60 s (word timestamps, beam 1) | {lat['stt_60s_s']:.3f} s |",
    f"| Phoneme posteriors 10 s (wav2vec2 fp16) | {lat['phonemes_10s_s']:.3f} s |",
    f"| TTS time to first audio (one sentence) | {lat['tts_first_audio_ms']:.0f} ms |",
    f"| End-of-turn inference (Smart Turn, 8 s window) | {lat['end_of_turn_ms']:.1f} ms |",
    "",
    "## Memory",
    "",
    "| Metric | MB |",
    "|---|---|",
    *[f"| {k} | {v:.0f} |" if isinstance(v, (int, float)) else f"| {k} | {v} |"
      for k, v in results["vram"].items()],
    "",
    "Load times (s): " + ", ".join(f"{k} {v:.1f}" for k, v in results["load_s"].items()),
    "",
    "## Decisions (VERIFICAR items)",
    "",
    f"- **LLM (OpenRouter) model ID:** {results['decisions']['llm_model']}",
    f"- **Kokoro word timestamps:** {results['decisions']['kokoro_timestamps']}",
    f"- **Forced alignment:** {results['decisions']['forced_align']}",
    f"- **End-of-turn detector:** {results['decisions']['turn_detector']}",
    f"- **Kokoro voice:** `{voice}` (American; `af_*` female, `am_*` male).",
    "",
    "## Notes",
    "",
    *[f"- {n}" for n in results["notes"]],
    "",
    "## Raw data",
    "",
    "```json",
    json.dumps({k: results[k] for k in ("latency", "vram", "forced_align", "llm",
                                         "smart_turn_probe")}, indent=2, default=str),
    "```",
    "",
]
report_path = REPO_ROOT / "docs" / "spike-report.md"
report_path.parent.mkdir(exist_ok=True)
report_path.write_text("\n".join(lines), encoding="utf-8")
print(f"\nReport written to {report_path}")

del whisper, w2v
gc.collect()
sys.exit(0 if all_pass else 1)
