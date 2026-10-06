"""Background analysis of one candidate turn (section 10.1): fluency, pronunciation,
grammar/technical/vocabulary; persists errors with Opus clips (errors only), then the
turn's full audio is dropped. Sends live feedback in live/hybrid mode (10.2)."""

import asyncio
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select

from api.analysis.fluency import fluency_errors, fluency_metrics
from api.analysis.language import LanguageIssue, analyze_language
from api.analysis.pron_filter import describe, filter_candidates
from api.db.models import AudioClip, Error, Turn, UserSettings
from api.db.session import SessionLocal
from api.llm.client import LLMClient
from api.pronunciation.pipeline import find_candidates, find_suspects, load_context, normalize, score_turn
from api.pronunciation.rules import FUNCTION_WORDS, Context
from api.realtime import hub
from api.realtime.model_client import ModelClient
from api.storage.clips import PRON_PAD_MS, clip_path, cut, save_opus

log = logging.getLogger("analysis")

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
LIVE_MAX_ITEMS = 3


@dataclass
class TurnJob:
    turn_id: uuid.UUID
    turn_idx: int
    session_id: uuid.UUID
    user_id: uuid.UUID
    pcm: bytes  # full turn audio (16 kHz PCM16) — kept only until the analysis ends
    words: list[dict]  # asr words, times relative to the turn start
    text: str
    question: str
    seniority: str
    session_type: str
    feedback_mode: str
    llm: LLMClient | None
    notes: list[str] = field(default_factory=list)


def word_quality(ctx: Context, words: list[dict], results: dict[int, dict]) -> tuple[list[float | None], Counter]:
    """Per word: the lowest phone z-score against the native calibration (None = not judged),
    and how many phones of each kind were judged (denominator of the phoneme heatmap)."""
    word_z: list[float | None] = [None] * len(words)
    phone_counts: Counter = Counter()
    for i, res in results.items():
        if not res.get("aligned") or normalize(words[i]["w"]) in FUNCTION_WORDS:
            continue
        zs = []
        for p in res["phones"]:
            if "score" in p:
                stats = ctx.calibration.get(p["p"])
                zs.append((p["score"] - stats.mean) / stats.std if stats.std else 0.0)
                phone_counts[p["p"]] += 1
        if zs:
            word_z[i] = round(min(zs), 2)
    return word_z, phone_counts


def anchor_span(words: list[dict], quote: str) -> tuple[int, int] | None:
    """Time range of the sentence containing ``quote`` (grammar/vocabulary clips)."""
    q = [t for t in (normalize(x) for x in quote.split()) if t]
    tokens = [normalize(w["w"]) for w in words]
    if not q:
        return None
    for i in range(len(tokens) - len(q) + 1):
        if tokens[i : i + len(q)] == q:
            start, end = i, i + len(q) - 1
            while start > 0 and not re.search(r"[.?!]$", words[start - 1]["w"]):
                start -= 1
            while end < len(words) - 1 and not re.search(r"[.?!]$", words[end]["w"]):
                end += 1
            return words[start]["start_ms"], words[end]["end_ms"]
    return None


async def analyze_turn(job: TurnJob, models: ModelClient) -> None:
    async with SessionLocal() as db:
        settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == job.user_id))
        ctx = await load_context(db, job.user_id, settings.phoneme_threshold_k if settings else 2.0)

    metrics = fluency_metrics(job.words)

    async def pronunciation():
        try:
            results = await score_turn(models, job.pcm, job.words, ctx.pronunciations)
        except Exception as exc:  # noqa: BLE001
            job.notes.append(f"pronunciation failed: {exc!r}")
            log.exception("pronunciation analysis failed")
            return [], [], {}
        candidates = find_candidates(ctx, job.words, results)
        kept = await filter_candidates(job.llm, candidates, job.text)
        suspects = find_suspects(ctx, job.words, {c.word_index for c in candidates})
        return kept, suspects, results

    async def language() -> list[LanguageIssue]:
        if job.llm is None:
            return []
        try:
            return await analyze_language(job.llm, job.question, job.text, job.seniority, job.session_type)
        except Exception as exc:  # noqa: BLE001 — no key / provider down: keep the rest of the analysis
            job.notes.append(f"language analysis failed: {exc!r}")
            log.warning("language analysis failed: %r", exc)
            return []

    (kept, suspects, results), issues = await asyncio.gather(pronunciation(), language())
    word_z, phone_counts = word_quality(ctx, job.words, results)
    word_errors: dict[str, str] = {}  # asr word index → pronunciation error id (clickable words)

    errors: list[tuple[Error, tuple[int, int, int] | None]] = []  # (row, (start, end, pad) to clip)
    base = dict(user_id=job.user_id, session_id=job.session_id, turn_id=job.turn_id)
    for c, severity, explanation in kept:
        row = Error(**base, id=uuid.uuid4(), kind="pronunciation", category=c.category, severity=severity,
                    original_text=c.word, explanation=explanation, word=c.word,
                    expected_phonemes=c.expected, heard_phonemes=c.heard, phoneme_index=c.phone_index,
                    score=c.score, corrected_text=describe(c))
        span = (c.start_ms, c.end_ms, PRON_PAD_MS) if c.start_ms is not None else None
        errors.append((row, span))
        word_errors.setdefault(str(c.word_index), str(row.id))
    for s in suspects:
        row = Error(**base, id=uuid.uuid4(), kind="pronunciation", category="pron:suspect", severity="low",
                    original_text=s.word, word=s.word, score=s.probability,
                    explanation=(f'The speech recognizer was unsure about "{s.word}" '
                                 f"({s.probability:.0%} confidence) — it may not have sounded clear. "
                                 "It will come back in a reading drill."))
        errors.append((row, (s.start_ms, s.end_ms, PRON_PAD_MS)))
        word_errors.setdefault(str(s.word_index), str(row.id))
    for issue in issues:
        row = Error(**base, kind=issue.kind, category=issue.category, severity=issue.severity,
                    original_text=issue.original_text or None, corrected_text=issue.corrected_text,
                    explanation=issue.explanation)
        span = anchor_span(job.words, issue.original_text) if issue.kind != "technical" else None
        errors.append((row, (*span, 0) if span else None))
    for e in fluency_errors(metrics):
        errors.append((Error(**base, **e), None))

    async with SessionLocal() as db:
        for row, span in errors:
            row.id = row.id or uuid.uuid4()
            if span:
                audio, start, end = cut(job.pcm, span[0], span[1], pad_ms=span[2])
                if len(audio):
                    path = clip_path(job.user_id, job.session_id, row.id)
                    await asyncio.to_thread(save_opus, audio, path)
                    clip = AudioClip(id=uuid.uuid4(), user_id=job.user_id, file_path=str(path),
                                     duration_ms=end - start, source_turn_id=job.turn_id, start_ms=start, end_ms=end)
                    db.add(clip)
                    await db.flush()
                    row.audio_clip_id = clip.id
            db.add(row)
        turn = await db.get(Turn, job.turn_id)
        turn.metrics = {**metrics, "word_z": word_z, "phone_counts": dict(phone_counts),
                        "word_errors": word_errors, "analysis_notes": job.notes}
        turn.analysis_status = "done"
        await db.commit()
    job.pcm = b""  # section 10.3: the full turn audio is gone; only the error clips remain

    await send_live_feedback(job, [row for row, _ in errors])
    log.info("turn %s analyzed: %d errors (%s)", job.turn_idx, len(errors), ", ".join(job.notes) or "ok")


def live_items(feedback_mode: str, errors: list[Error]) -> list[dict]:
    if feedback_mode not in ("live", "hybrid"):
        return []
    shown = [e for e in errors if e.category != "pron:suspect"]
    if feedback_mode == "hybrid":
        shown = [e for e in shown if e.severity == "high"]
    shown.sort(key=lambda e: SEVERITY_RANK[e.severity])
    return [
        {"error_id": str(e.id), "kind": e.kind, "category": e.category, "severity": e.severity,
         "original_text": e.original_text, "corrected_text": e.corrected_text, "explanation": e.explanation,
         "word": e.word}
        for e in shown[:LIVE_MAX_ITEMS]
    ]


async def send_live_feedback(job: TurnJob, errors: list[Error]) -> None:
    items = live_items(job.feedback_mode, errors)
    if items:
        await hub.push(job.session_id, {"type": "live_feedback", "turn_idx": job.turn_idx, "items": items})
