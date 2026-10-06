"""Final pronunciation filter (section 8.6): the LLM picks, ranks and explains error
candidates. It can only choose among the candidates it receives — enforced in code by
ids — so it cannot invent pronunciation errors. Without the LLM, a deterministic
fallback keeps the clearest candidates with template explanations."""

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from api.llm.client import LLMClient
from api.pronunciation.rules import Candidate

log = logging.getLogger(__name__)

MAX_CANDIDATES = 25
MAX_KEPT = 8
FALLBACK_MIN_STRENGTH = 1.0

TIPS = {
    "θ": "start with /θ/: put the tip of your tongue between your teeth and blow air (no /t/, /f/ or /s/).",
    "ð": "use /ð/: tongue between the teeth with voice, like a soft buzzing 'th'.",
    "h": "pronounce the /h/: a light breath out, not a Portuguese 'r' and not silent.",
    "ɹ": "use the American /ɹ/: curl the tongue back without touching the roof of the mouth.",
    "ŋ": "end with /ŋ/ from the back of the tongue; don't add a /g/ or a vowel.",
    "z": "use a buzzing /z/, not /s/.",
    "v": "use /v/: top teeth on the bottom lip, with voice.",
    "æ": "open the mouth wide for /æ/, as in 'cat' — between 'a' and 'é'.",
    "ɪ": "keep /ɪ/ short and relaxed, as in 'ship', not a long 'ee'.",
    "iː": "make /iː/ long and tense, as in 'sheep'.",
}
CATEGORY_TIPS = {
    "pron:epenthesis": "don't add an extra vowel ('es-tack', 'Goo-gui-li'); go straight to the consonant.",
    "pron:final_ed": "'-ed' is not a separate syllable here: say it as /d/ or /t/ attached to the word.",
}

INSTRUCTIONS = """\
You are a pronunciation coach for a Brazilian developer speaking English in a job interview \
(American English reference). You receive error CANDIDATES measured by a phoneme recognizer. \
Some are real errors, some are recognizer noise.

Hard rule: you may only select candidates from the list, by "id". Never invent errors, words \
or phonemes that are not in the data. If none look real, return an empty list.

Keep the ones most likely real and most useful. Prioritize: typical Brazilian errors \
(/θ/ and /ð/ as t, f, d or s; extra vowels like "es-tack" or "Goo-gui-li"; "-ed" as a syllable; \
/ɪ/ vs /iː/; /æ/ vs /ɛ/; initial /h/; final and American /ɹ/; "-tion"), technical vocabulary \
(is_tech), and errors that hurt intelligibility. Drop isolated noise: tiny margins below the \
threshold, unusual substitutions that no learner would make. At most {max_kept}.

Also drop candidates where the heard form is a valid pronunciation in context: words whose \
pronunciation depends on noun vs verb ("use", "duplicate", "estimate", "record"), common \
American alternatives ("either", "data", reduced vowels in unstressed syllables), or words that \
look like transcription mistakes rather than real words.

For each kept item: "severity" (high = hurts understanding or a key technical word; medium; \
low), and "explanation": one or two sentences to the candidate in simple English about EXACTLY \
that candidate's expected_phone and heard_phone (do not talk about other sounds of the word), \
saying what they said and how to fix it, e.g. "You said /tru:put/ — start with /θ/: put your \
tongue between your teeth."

Answer with JSON: {{"keep": [{{"id": 0, "severity": "high", "explanation": "..."}}]}}"""


class Kept(BaseModel):
    id: int
    severity: Literal["low", "medium", "high"] = "medium"
    explanation: str


class FilterResult(BaseModel):
    keep: list[Kept] = Field(default_factory=list)


def describe(c: Candidate) -> str:
    if c.category == "pron:epenthesis":
        return f'In "{c.word}" you added an extra /{c.heard_phone}/ sound'
    if c.category == "pron:final_ed":
        return f'In "{c.word}" you pronounced "-ed" as an extra syllable'
    if not c.heard_phone:
        return f'In "{c.word}" the /{c.phone}/ sound was missing'
    return f'In "{c.word}" you said /{c.heard_phone}/ instead of /{c.phone}/'


def template_explanation(c: Candidate) -> str:
    tip = CATEGORY_TIPS.get(c.category) or TIPS.get(c.phone) or f"aim for /{c.phone}/ as in the reference pronunciation."
    return f"{describe(c)} — {tip}"


def fallback(candidates: list[Candidate]) -> list[tuple[Candidate, str, str]]:
    strong = sorted((c for c in candidates if c.strength >= FALLBACK_MIN_STRENGTH), key=lambda c: -c.strength)
    out = []
    for c in strong[:MAX_KEPT]:
        severity = "high" if c.is_tech or c.strength >= 4 else "medium"
        out.append((c, severity, template_explanation(c)))
    return out


async def filter_candidates(llm: LLMClient | None, candidates: list[Candidate], answer: str) -> list[tuple[Candidate, str, str]]:
    """Returns (candidate, severity, explanation) for the errors to show."""
    if not candidates:
        return []
    ranked = sorted(candidates, key=lambda c: (-c.is_tech, -c.strength))[:MAX_CANDIDATES]
    if llm is None:
        return fallback(ranked)
    payload = [
        {"id": i, "word": c.word, "category": c.category, "expected_phone": c.phone, "heard_phone": c.heard_phone,
         "expected_word": c.expected, "heard_word": c.heard, "score": c.score, "threshold": c.threshold,
         "margin": round(c.strength, 2), "is_tech": c.is_tech}
        for i, c in enumerate(ranked)
    ]
    messages = [
        {"role": "system", "content": INSTRUCTIONS.format(max_kept=MAX_KEPT)},
        {"role": "user", "content": json.dumps({"answer": answer, "candidates": payload}, ensure_ascii=False)},
    ]
    try:
        result = FilterResult.model_validate_json(await llm.complete_json(messages))
    except Exception as exc:  # noqa: BLE001 — no key, network, invalid JSON: degrade gracefully
        log.warning("pronunciation filter LLM failed (%r); using the deterministic fallback", exc)
        return fallback(ranked)
    out, seen = [], set()
    for k in result.keep[:MAX_KEPT]:
        if 0 <= k.id < len(ranked) and k.id not in seen:  # only real candidates, once each
            seen.add(k.id)
            out.append((ranked[k.id], k.severity, k.explanation.strip() or template_explanation(ranked[k.id])))
    return out
