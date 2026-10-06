"""Drill generation from a session's errors (section 11)."""

import json
import logging
import re
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.analysis.language import TAXONOMY
from api.db.models import DrillItem, Error
from api.drills.srs import SrsState, reinforce
from api.llm.client import LLMClient
from api.pronunciation.pipeline import normalize

log = logging.getLogger("drills")

INSTRUCTIONS = """\
You create speaking drills for a Brazilian backend developer practicing English for job \
interviews (American English).

For each "pron" item: write 2 or 3 short, natural sentences (6 to 14 words each) from a \
backend / system design context that each contain the exact word given, so the learner can \
read them aloud. Use the word in the same form. If the word is not a real English word, name or \
technical term (it is probably a speech-recognition mistake), return "sentences": [] for it.

For each "tech" item: write a "prompt" asking the learner to explain the concept in 30 to 60 \
seconds (one sentence, addressed to "you"), and "key_points": 2 to 4 short strings a good \
answer must cover. Base it on what went wrong.

Answer with JSON: {"pron": [{"id": 0, "sentences": ["..."]}], "tech": [{"id": 0, "prompt": "...", \
"key_points": ["..."]}]}"""


class PronOut(BaseModel):
    id: int
    sentences: list[str] = Field(default_factory=list)


class TechOut(BaseModel):
    id: int
    prompt: str
    key_points: list[str] = Field(default_factory=list)


class GeneratedDrills(BaseModel):
    pron: list[PronOut] = Field(default_factory=list)
    tech: list[TechOut] = Field(default_factory=list)


def dedup_key(e: Error) -> tuple[str, str] | None:
    """(kind of drill, key): one item per word for pronunciation, per rule otherwise."""
    if e.kind == "pronunciation":
        word = normalize(e.word or e.original_text or "")
        return ("pron_read", f"pron|{word}") if word else None
    if e.kind in ("grammar", "vocabulary"):
        return ("grammar_rewrite", e.category) if e.original_text and e.corrected_text else None
    if e.kind == "technical":
        return "tech_explain", e.category
    return None  # fluency: practiced in interviews, not as drills


def pron_focus(e: Error) -> str:
    if e.category == "pron:suspect":
        return "suspect"  # confirmation drill: one clean read retires it
    phones = (e.expected_phonemes or "").split()
    if e.phoneme_index is not None and 0 <= e.phoneme_index < len(phones) and e.category.startswith(("pron:phoneme", "pron:vowel")):
        return phones[e.phoneme_index]
    return e.category


def contains_word(sentence: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", sentence, re.IGNORECASE) is not None


def pron_template(word: str) -> list[str]:
    return [f"I want to say {word} clearly in my next interview.",
            f"Today we discussed {word} with the whole backend team."]


def tech_template(e: Error) -> tuple[str, str]:
    topic = TAXONOMY.get(e.category, e.category.split(":")[-1])
    said = f' Earlier you said: "{e.original_text}".' if e.original_text else ""
    return (f"In 30 to 60 seconds, explain {topic}.{said}", e.explanation or "")


async def _llm_content(llm: LLMClient | None, pron: list[str], tech: list[Error]) -> GeneratedDrills:
    if llm is None or (not pron and not tech):
        return GeneratedDrills()
    payload = {
        "pron": [{"id": i, "word": w} for i, w in enumerate(pron)],
        "tech": [{"id": i, "topic": TAXONOMY.get(e.category, e.category), "candidate_said": e.original_text,
                  "what_went_wrong": e.explanation} for i, e in enumerate(tech)],
    }
    try:
        raw = await llm.complete_json([{"role": "system", "content": INSTRUCTIONS},
                                       {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        return GeneratedDrills.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001 — templates instead
        log.warning("drill content generation failed: %r", exc)
        return GeneratedDrills()


async def generate_drills(db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID, llm: LLMClient | None) -> dict:
    """Turn the session's non-dismissed errors into drill items. Returns counts."""
    errors = (await db.scalars(
        select(Error).where(Error.session_id == session_id, Error.dismissed.is_(False)).order_by(Error.created_at)
    )).all()
    latest: dict[str, tuple[str, Error]] = {}
    for e in errors:
        key = dedup_key(e)
        if key:
            kind, k = key
            if k not in latest or e.category != "pron:suspect":  # a real error beats a suspicion
                latest[k] = (kind, e)

    existing = {
        d.dedup_key: d for d in (await db.scalars(
            select(DrillItem).where(DrillItem.user_id == user_id, DrillItem.dedup_key.in_(list(latest)))
        )).all()
    }
    now = datetime.now(UTC)
    reinforced = 0
    new: list[tuple[str, str, Error]] = []
    for k, (kind, e) in latest.items():
        item = existing.get(k)
        if item is None:
            new.append((k, kind, e))
            continue
        state = reinforce(SrsState(item.ease, item.interval_days, item.repetitions, item.lapses,
                                   item.mature_streak, item.retired))
        item.interval_days, item.repetitions, item.mature_streak, item.retired = (
            state.interval_days, state.repetitions, state.mature_streak, state.retired)
        item.occurrences += 1
        item.due_at = now
        item.source_error_id = e.id
        if kind == "grammar_rewrite":  # practice the latest wrong sentence
            item.prompt_text, item.target_text = e.original_text, e.corrected_text
        if kind == "pron_read" and item.focus == "suspect" and e.category != "pron:suspect":
            item.focus = pron_focus(e)  # suspicion confirmed by a measured error
        reinforced += 1

    pron_words = [normalize(e.word or e.original_text or "") for _, kind, e in new if kind == "pron_read"]
    tech_errors = [e for _, kind, e in new if kind == "tech_explain"]
    content = await _llm_content(llm, pron_words, tech_errors)
    sentences = {p.id: p.sentences for p in content.pron}
    tech_out = {t.id: t for t in content.tech}

    pi = ti = 0
    llm_ok = bool(content.pron or content.tech)
    for k, kind, e in new:
        if kind == "pron_read":
            word = pron_words[pi]
            pi += 1
            if llm_ok and pi - 1 in sentences and not sentences[pi - 1]:
                continue  # the LLM says it isn't a real word (ASR glitch): no drill
            good = [s.strip() for s in sentences.get(pi - 1, []) if contains_word(s, word)][:3]
            text = " ".join(good or pron_template(word))
            prompt, target, focus = f'Read aloud, paying attention to "{word}".', text, pron_focus(e)
        elif kind == "grammar_rewrite":
            prompt, target, focus = e.original_text, e.corrected_text, e.category
        else:
            t = tech_out.get(ti)
            prompt, points = (t.prompt, "; ".join(t.key_points)) if t else tech_template(e)
            target, focus = points or (e.explanation or ""), e.category
            ti += 1
        db.add(DrillItem(user_id=user_id, source_error_id=e.id, kind=kind, prompt_text=prompt,
                         target_text=target, focus=focus, dedup_key=k, due_at=now))
    await db.commit()
    return {"created": len(new), "reinforced": reinforced}
