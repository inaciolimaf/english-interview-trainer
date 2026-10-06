import numpy as np
import soundfile as sf

from api.analysis.fluency import fluency_errors, fluency_metrics
from api.storage.clips import MAX_CLIP_MS, cut, save_opus


def w(text, start, end):
    return {"w": text, "start_ms": start, "end_ms": end, "p": 0.9}


WORDS = [w("So,", 0, 300), w("um,", 400, 600), w("I", 700, 800), w("would", 800, 1000), w("use", 1000, 1200),
         w("uh", 1300, 1500), w("Redis,", 1500, 2000), w("you", 4500, 4600), w("know,", 4600, 4900),
         w("um", 5000, 5200), w("caching.", 5300, 6000)]


def test_fluency_metrics():
    m = fluency_metrics(WORDS)
    assert m["fillers"] == {"um": 2, "uh": 1, "you know": 1} and m["filler_count"] == 4
    assert m["long_pauses"] == [{"after_word": 6, "ms": 2500, "at_ms": 2000}]
    assert m["words"] == 8 and m["wpm"] == 80.0


def test_fluency_errors():
    cats = {e["category"]: e for e in fluency_errors(fluency_metrics(WORDS))}
    assert set(cats) == {"flu:filler", "flu:long_pause"}
    assert "4 fillers" in cats["flu:filler"]["explanation"]


def test_no_fluency_errors_for_clean_answer():
    clean = [w("I", 0, 200), w("would", 200, 400), w("shard", 400, 800), w("it.", 800, 1100)]
    assert fluency_errors(fluency_metrics(clean)) == []
    assert fluency_metrics([])["wpm"] == 0.0


def pcm(seconds: float) -> bytes:
    t = np.arange(int(16_000 * seconds)) / 16_000
    return (np.sin(2 * np.pi * 440 * t) * 8000).astype("<i2").tobytes()


def test_cut_pads_and_clamps():
    audio, start, end = cut(pcm(3.0), 100, 900, pad_ms=300)
    assert (start, end) == (0, 1200) and len(audio) == 1.2 * 16_000
    audio, start, end = cut(pcm(3.0), 2500, 2900, pad_ms=300)
    assert end == 3000
    _, start, end = cut(pcm(20.0), 0, 20_000)
    assert end - start == MAX_CLIP_MS


def test_opus_roundtrip(tmp_path):
    audio, _, _ = cut(pcm(2.0), 500, 1500)
    path = tmp_path / "clip.opus"
    save_opus(audio, path)
    data, sr = sf.read(path)
    assert sr == 16_000 and abs(len(data) / sr - 1.0) < 0.05
    assert path.stat().st_size < 10_000  # compressed
