"""Phoneme score calibration on native speech (section 8.4). Idempotent.

1. Downloads LibriSpeech test-clean (~350 MB) to data/calibration/ (skipped if present).
2. Scores every phone of the reference text with the same pipeline the app uses
   (model_server/phonemes.py), on content words only — function words are never judged.
3. Writes native_mean / native_std / p05 / n_samples per phoneme to phoneme_calibration,
   plus a global row "*" used for phonemes without enough samples.

Usage (from backend/):  python scripts/calibrate_phonemes.py [--limit 800]
Afterwards the corpus can be deleted (data/calibration/LibriSpeech).
"""

import argparse
import asyncio
import sys
import tarfile
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from sqlalchemy import func  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from api.config import get_settings  # noqa: E402
from api.db.models import PhonemeCalibration  # noqa: E402
from api.db.session import SessionLocal, engine  # noqa: E402
from api.pronunciation.g2p import WORD_SEP, espeak_phonemes  # noqa: E402
from api.pronunciation.rules import FUNCTION_WORDS  # noqa: E402

URL = "https://www.openslr.org/resources/12/test-clean.tar.gz"
MAX_SECONDS = 20  # one wav2vec2 pass; longer utterances are skipped
MIN_SAMPLES = 30  # per phoneme, otherwise it falls back to the global row


def download(dest: Path) -> Path:
    corpus = dest / "LibriSpeech" / "test-clean"
    if corpus.exists():
        return corpus
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "test-clean.tar.gz"
    if not archive.exists():
        print(f"downloading {URL} …")
        tmp = archive.with_suffix(".part")

        last_mb = -1

        def progress(blocks: int, block_size: int, total: int) -> None:
            nonlocal last_mb
            mb = blocks * block_size // 2**20
            if mb != last_mb and mb % 25 == 0:
                print(f"  {mb} / {total // 2**20} MB", flush=True)
                last_mb = mb

        urllib.request.urlretrieve(URL, tmp, reporthook=progress)
        tmp.rename(archive)
    print("extracting …")
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter="data")
    archive.unlink()
    return corpus


def utterances(corpus: Path) -> list[tuple[Path, str]]:
    items = []
    for trans in sorted(corpus.rglob("*.trans.txt")):
        for line in trans.read_text().splitlines():
            utt_id, text = line.split(" ", 1)
            items.append((trans.parent / f"{utt_id}.flac", text.lower()))
    return items


def expected_phones(words: list[str]) -> list[list[str]]:
    joined = espeak_phonemes(" ".join(words)).split(WORD_SEP)
    if len(joined) == len(words):  # sentence-level G2P keeps weak forms; use it when it lines up
        return [w.split() for w in joined]
    return [espeak_phonemes(w).replace(WORD_SEP, " ").split() for w in words]


def collect(limit: int) -> dict[str, list[float]]:
    from model_server.phonemes import PhonemeScorer

    corpus = download(get_settings().data_path / "calibration")
    items = utterances(corpus)[:limit]
    scorer = PhonemeScorer(get_settings().phoneme_model)
    scores: dict[str, list[float]] = defaultdict(list)
    t0, used = time.time(), 0
    for n, (path, text) in enumerate(items, 1):
        audio, sr = sf.read(path, dtype="float32")
        if sr != 16_000 or len(audio) > MAX_SECONDS * sr:
            continue
        words = text.split()
        for word, res in zip(words, scorer.score(audio, expected_phones(words)), strict=True):
            if word in FUNCTION_WORDS or not res["aligned"]:
                continue
            for p in res["phones"]:
                if "score" in p:
                    scores[p["p"]].append(p["score"])
        used += 1
        if n % 50 == 0:
            print(f"  {n}/{len(items)} utterances, {time.time() - t0:.0f}s")
    print(f"scored {used} utterances, {sum(map(len, scores.values()))} phones")
    return scores


def summarize(values: list[float]) -> dict:
    arr = np.asarray(values)
    return {"native_mean": float(arr.mean()), "native_std": float(arr.std()),
            "p05": float(np.percentile(arr, 5)), "n_samples": len(arr)}


async def save(scores: dict[str, list[float]]) -> None:
    rows = [{"phoneme": p, "accent": "en-us", **summarize(v)} for p, v in scores.items() if len(v) >= MIN_SAMPLES]
    rows.append({"phoneme": "*", "accent": "en-us", **summarize([x for v in scores.values() for x in v])})
    async with SessionLocal() as db:
        stmt = insert(PhonemeCalibration).values(rows)
        await db.execute(stmt.on_conflict_do_update(
            constraint="uq_phoneme_calibration_phoneme",
            set_={c: stmt.excluded[c] for c in ("native_mean", "native_std", "p05", "n_samples")}
            | {"updated_at": func.now()},
        ))
        await db.commit()
    await engine.dispose()
    for r in sorted(rows, key=lambda r: r["phoneme"]):
        print(f"  {r['phoneme']:5} mean={r['native_mean']:6.2f} std={r['native_std']:5.2f} "
              f"p05={r['p05']:6.2f} n={r['n_samples']}")
    print(f"saved {len(rows)} rows to phoneme_calibration")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=800, help="utterances to score (test-clean has 2620)")
    args = parser.parse_args()
    asyncio.run(save(collect(args.limit)))
