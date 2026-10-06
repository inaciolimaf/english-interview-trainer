"""Pronunciation analysis of one candidate turn (section 8.1–8.2).

The turn is split into windows of ≤ 15 s at pauses; each window is one low-priority
job on the model server, so the next turn's transcription never waits behind it.
"""

import asyncio
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import AcceptedVariant, PhonemeCalibration, TechVocabulary, UserPhonemeAdjustment
from api.pronunciation.g2p import WORD_SEP, espeak_phonemes
from api.analysis.fluency import FILLERS
from api.pronunciation.rules import (
    FUNCTION_WORDS, Calibration, Candidate, Context, Stats, Variants, judge_word,
)
from api.realtime.model_client import ModelClient

SR = 16_000
MAX_WINDOW_MS = 15_000
SPLIT_GAP_MS = 1_000  # also start a new window after a long pause
WINDOW_PAD_MS = 200
SUSPECT_PROB = 0.5  # Whisper word probability below this → suspect (section 8.2)
INSERTION = "+"  # user_phoneme_adjustments.phoneme for dismissed extra-vowel errors


def normalize(word: str) -> str:
    return re.sub(r"[^a-z0-9'.-]", "", word.lower()).strip(".-'")


def windows(words: list[dict]) -> list[list[int]]:
    out: list[list[int]] = []
    for i, w in enumerate(words):
        if out:
            first = words[out[-1][0]]
            prev = words[out[-1][-1]]
            if w["end_ms"] - first["start_ms"] <= MAX_WINDOW_MS and w["start_ms"] - prev["end_ms"] < SPLIT_GAP_MS:
                out[-1].append(i)
                continue
        out.append([i])
    return out


def expected_phones(words: list[str], overrides: dict[str, list[str]] | None = None) -> list[list[str]]:
    """Sentence-level G2P keeps connected-speech weak forms; fall back to word by word.
    ``overrides``: curated pronunciations (tech vocabulary) that win over espeak."""
    if not words:
        return []
    joined = espeak_phonemes(" ".join(words)).split(WORD_SEP)
    if len(joined) == len(words):
        phones = [w.split() for w in joined]
    else:
        phones = [espeak_phonemes(w).replace(WORD_SEP, " ").split() if w else [] for w in words]
    overrides = overrides or {}
    return [overrides.get(w, p) for w, p in zip(words, phones, strict=True)]


async def score_turn(models: ModelClient, pcm16: bytes, words: list[dict],
                     overrides: dict[str, list[str]] | None = None) -> dict[int, dict]:
    """Model-server results per asr word index, with times relative to the turn."""
    total_ms = len(pcm16) // 2 * 1000 // SR
    results: dict[int, dict] = {}
    for idx in windows(words):
        start = max(0, words[idx[0]]["start_ms"] - WINDOW_PAD_MS)
        end = min(total_ms, words[idx[-1]]["end_ms"] + WINDOW_PAD_MS)
        if end - start < 200:
            continue
        norm = [normalize(words[i]["w"]) for i in idx]
        phones = await asyncio.to_thread(expected_phones, norm, overrides)
        window_pcm = pcm16[start * SR // 1000 * 2 : end * SR // 1000 * 2]
        for i, res in zip(idx, await models.phonemes(window_pcm, phones), strict=True):
            for key in ("start_ms", "end_ms"):
                if key in res:
                    res[key] += start
            for p in res["phones"]:
                for key in ("start_ms", "end_ms"):
                    if key in p:
                        p[key] += start
            results[i] = res
    return results


def find_candidates(ctx: Context, words: list[dict], results: dict[int, dict]) -> list[Candidate]:
    out = []
    for i, w in enumerate(words):
        if i not in results or w.get("p", 1.0) < SUSPECT_PROB:
            continue  # low ASR confidence: the word itself may be wrong → only a suspect
        word = normalize(w["w"])
        skip_insertions = (INSERTION, word) in ctx.offsets  # user said extra vowels here are fine
        nxt = results.get(i + 1)
        next_phones = [p["p"] for p in nxt["phones"]] if nxt else None
        for c in judge_word(ctx, word, i, results[i], next_phones):
            if skip_insertions and c.phone == "":
                continue
            out.append(c)
    return out


@dataclass
class Suspect:
    word: str
    word_index: int
    probability: float
    start_ms: int
    end_ms: int
    is_tech: bool


def find_suspects(ctx: Context, words: list[dict], flagged: set[int]) -> list[Suspect]:
    """Low-confidence Whisper words (it may have 'corrected' a mispronunciation)."""
    out = []
    for i, w in enumerate(words):
        word = normalize(w["w"])
        if i in flagged or word in FUNCTION_WORDS or word in FILLERS or len(word) < 3 or not word.isalpha():
            continue
        if w.get("p", 1.0) < SUSPECT_PROB:
            out.append(Suspect(word, i, w["p"], w["start_ms"], w["end_ms"], word in ctx.tech_terms))
    return out


async def load_context(db: AsyncSession, user_id: uuid.UUID, k: float) -> Context:
    calib_rows = (await db.scalars(select(PhonemeCalibration).where(PhonemeCalibration.accent == "en-us"))).all()
    per_phone = {r.phoneme: Stats(r.native_mean, r.native_std) for r in calib_rows if r.phoneme != "*"}
    global_row = next((r for r in calib_rows if r.phoneme == "*"), None)
    calibration = Calibration(per_phone)
    if global_row:
        calibration.fallback = Stats(global_row.native_mean, global_row.native_std)

    variants = Variants()
    for v in (await db.scalars(select(AcceptedVariant))).all():
        expected, accepted = v.expected.split(), v.accepted.split()
        if v.word is None and len(expected) == 1 and len(accepted) == 1:
            variants.general.add((expected[0], accepted[0]))
        elif v.word and " " not in v.word:
            variants.by_word.setdefault(v.word.lower(), []).append([p for p in accepted if p != "|"])

    offsets = {
        (a.phoneme, a.word): a.offset
        for a in (await db.scalars(select(UserPhonemeAdjustment).where(UserPhonemeAdjustment.user_id == user_id))).all()
    }
    terms = set()
    pronunciations: dict[str, list[str]] = {}
    for term, phonemes in (await db.execute(select(TechVocabulary.term, TechVocabulary.phonemes))).all():
        terms.update(normalize(t) for t in re.split(r"[\s/]+", term) if len(t) > 2)
        if " " not in term.strip():  # one written word ("idempotency", "PostgreSQL", "Redis")
            pronunciations[normalize(term)] = phonemes.replace(WORD_SEP, " ").split()
    return Context(calibration=calibration, variants=variants, k=k, offsets=offsets, tech_terms=terms,
                   pronunciations=pronunciations)
