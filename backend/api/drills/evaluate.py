"""Scoring of one drill attempt (section 11)."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from api.db.models import DrillItem
from api.llm.client import LLMClient
from api.pronunciation.align import distance
from api.pronunciation.pipeline import expected_phones, normalize
from api.pronunciation.rules import Candidate, Context, judge_word
from api.realtime.model_client import ModelClient

SR = 16_000
MAX_SCRIPT_S = 30  # script mode scores the whole recording in one pass
MIN_READ_OVERLAP = 0.6  # transcript vs reference: did they read the right text?
REWRITE_PASS = 0.8
TECH_MIN_S = 20

JUDGE = """\
You grade a 30-60 second spoken explanation by a backend developer practicing for interviews. \
The answer is a speech-to-text transcript; ignore grammar and transcription glitches, judge \
only the technical content against the key points. Pass if the main idea is correct and most \
key points are covered.
Answer with JSON: {"passed": true|false, "score": 0.0-1.0, "feedback": "two sentences to the learner (you)"}"""


class Judgement(BaseModel):
    passed: bool
    score: float
    feedback: str


@dataclass
class AttemptResult:
    passed: bool
    score: float
    transcript: str
    feedback: str
    details: dict = field(default_factory=dict)
    errors: list[Candidate] = field(default_factory=list)  # focus errors only (they decided the result)


def tokens(text: str) -> list[str]:
    return [t for t in (normalize(x) for x in re.findall(r"[A-Za-z0-9'.-]+", text)) if t]


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta and not tb:
        return 1.0
    return 1 - distance(ta, tb) / max(len(ta), len(tb))


def matches_focus(focus: str | None, c: Candidate) -> bool:
    if not focus or focus == "suspect":
        return True
    if focus.startswith("pron:"):
        return c.category == focus
    return c.phone == focus


async def evaluate_pron_read(item: DrillItem, pcm: bytes, models: ModelClient, ctx: Context) -> AttemptResult:
    seconds = len(pcm) / 2 / SR
    if seconds > MAX_SCRIPT_S:
        return AttemptResult(False, 0.0, "", f"Recording too long ({seconds:.0f} s). Read just the text shown.")
    reference = tokens(item.target_text)
    transcript_task = asyncio.create_task(models.transcribe(pcm))
    phones = await asyncio.to_thread(expected_phones, reference, ctx.pronunciations)
    results = await models.phonemes(pcm, phones)  # script mode: the reference text, not the transcript
    transcript = (await transcript_task)["text"]

    overlap = similarity(transcript, item.target_text)
    candidates: list[Candidate] = []
    scored = 0
    for i, (word, res) in enumerate(zip(reference, results, strict=True)):
        if res.get("aligned"):
            scored += 1
        nxt = results[i + 1] if i + 1 < len(results) else None
        candidates += judge_word(ctx, word, i, res, [p["p"] for p in nxt["phones"]] if nxt else None)

    target_word = re.search(r'"([^"]+)"', item.prompt_text or "")
    focus_word = normalize(target_word.group(1)) if target_word else ""
    # only the drill's focus decides pass/fail (the phoneme, the category, or anything for a
    # suspect); other slips — coarticulation and the like — are reported, not penalized
    focus_errors = [c for c in candidates if c.word == focus_word and matches_focus(item.focus, c)]
    error_words = {c.word_index for c in candidates}
    score = round(1 - len(error_words) / scored, 2) if scored else 0.0
    if overlap < MIN_READ_OVERLAP:
        return AttemptResult(False, score, transcript, "That didn't match the text — read the sentences shown.",
                             {"overlap": round(overlap, 2)})
    passed = not focus_errors
    if passed:
        feedback = f'"{focus_word}" sounded right.' if focus_word else "Well read."
    else:
        c = focus_errors[0]
        heard = f"/{c.heard_phone}/" if c.heard_phone else "nothing"
        feedback = (f'In "{c.word}" we heard {heard} where /{c.phone}/ was expected.' if c.phone
                    else f'In "{c.word}" there was an extra /{c.heard_phone}/ sound.')
    return AttemptResult(passed, score, transcript, feedback,
                         {"overlap": round(overlap, 2), "focus_word": focus_word,
                          "words_with_errors": sorted({c.word for c in candidates})}, focus_errors)


async def evaluate_rewrite(item: DrillItem, pcm: bytes, models: ModelClient) -> AttemptResult:
    transcript = (await models.transcribe(pcm))["text"]
    sim = similarity(transcript, item.target_text)
    passed = sim >= REWRITE_PASS
    feedback = "Correct." if passed else f'Aim for: "{item.target_text}"'
    return AttemptResult(passed, round(sim, 2), transcript, feedback, {"similarity": round(sim, 2)})


async def evaluate_tech(item: DrillItem, pcm: bytes, models: ModelClient, llm: LLMClient | None) -> AttemptResult:
    seconds = len(pcm) / 2 / SR
    transcript = (await models.transcribe(pcm))["text"]
    if seconds < TECH_MIN_S:
        return AttemptResult(False, 0.0, transcript, f"Too short ({seconds:.0f} s): explain for 30 to 60 seconds.",
                             {"seconds": round(seconds)})
    if llm is not None:
        try:
            raw = await llm.complete_json([
                {"role": "system", "content": JUDGE},
                {"role": "user", "content": json.dumps({"task": item.prompt_text, "key_points": item.target_text,
                                                        "answer": transcript})},
            ])
            j = Judgement.model_validate_json(raw)
            return AttemptResult(j.passed, max(0.0, min(1.0, j.score)), transcript, j.feedback, {"seconds": round(seconds)})
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("drills").warning("tech drill judge failed: %r", exc)
    words = len(tokens(transcript))
    return AttemptResult(words >= 50, 0.5, transcript,
                         "Content was not evaluated (LLM unavailable); counted as practice by length.",
                         {"seconds": round(seconds), "words": words, "llm": False})
