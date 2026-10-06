"""Session report (section 10.4), saved in interview_sessions.report / .scores.

Deterministic parts (fluency, pronunciation accuracy, error counts, transcript data) are
always produced; the LLM adds rubric scores with justification, strengths, the top 3
improvements, a better answer for the weakest question and an assessment of how the
candidate interrupted. If the LLM is unavailable the report says so and keeps the rest.
"""

import json
import logging
import re
import uuid
from collections import Counter
from datetime import UTC, datetime

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from api.db.models import Error, InterviewSession, Turn
from api.db.session import SessionLocal
from api.llm.client import LLMClient

log = logging.getLogger("report")

RUBRICS: dict[str, dict[str, str]] = {
    "system_design": {
        "requirements": "Clarified functional and non-functional requirements",
        "estimation": "Reasonable back-of-the-envelope estimates",
        "architecture": "Coherent high-level architecture, API and data model",
        "deep_dive": "Depth on bottlenecks, scale, consistency and failures",
        "tradeoffs": "Explicit trade-offs and justified choices",
        "communication": "Structured, clear communication",
    },
    "technical": {
        "technical_correctness": "Answers are technically correct",
        "depth": "Depth appropriate for the seniority",
        "clarity": "Clear, well-organized explanations",
        "practical_examples": "Concrete examples from real work",
    },
    "behavioral": {
        "star_structure": "Situation, Task, Action, Result",
        "specificity": "Specific details, not generalities",
        "quantified_impact": "Measurable impact",
        "ownership": "Personal role ('I' rather than 'we')",
        "conciseness": "Concise, focused answers",
    },
}
POLITE_OPENERS = ("sorry", "excuse me", "can i just", "if i may", "just to clarify", "pardon", "sorry to")
MAX_TRANSCRIPT_CHARS = 40_000

INSTRUCTIONS = """\
You evaluate a mock job interview of a Brazilian backend developer ({session_type}, target \
seniority: {seniority}). The transcript is speech-to-text; ignore transcription glitches. Judge \
the CONTENT and communication; English mistakes are listed separately and must not lower the \
technical scores.

Return JSON with:
- "rubric": one entry per criterion below, each {{"criterion": key, "score": 1-5, \
"justification": one or two sentences citing what the candidate actually said}}. 1 = poor, \
3 = acceptable for the seniority, 5 = excellent.
{criteria}
- "strengths": 2 to 4 short bullet strings.
- "improvements": exactly 3 short, actionable bullet strings, most important first.
- "better_answer": for the candidate's weakest answer: {{"question": the interviewer's question, \
"answer_summary": one sentence summarizing what the candidate said, "improved_answer": a model \
answer of 80-150 words the candidate could say out loud, in natural spoken English}}.
- "interruptions": {interruption_instruction}

Write everything in English, addressed to the candidate as "you"."""


class RubricItem(BaseModel):
    criterion: str
    score: int = Field(ge=1, le=5)
    justification: str


class BetterAnswer(BaseModel):
    question: str
    answer_summary: str
    improved_answer: str


class InterruptionReview(BaseModel):
    assessment: str
    examples: list[dict] = Field(default_factory=list)  # {"candidate_said", "advice"}


class LlmReport(BaseModel):
    rubric: list[RubricItem]
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    better_answer: BetterAnswer | None = None
    interruptions: InterruptionReview | None = None

    @field_validator("improvements")
    @classmethod
    def top_three(cls, v: list[str]) -> list[str]:
        return v[:3]


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def interruption_examples(turns: list[Turn]) -> list[dict]:
    """Candidate turns that cut into the interviewer, with a deterministic first opinion."""
    out = []
    for prev, turn in zip(turns, turns[1:]):
        if prev.role == "interviewer" and prev.interrupted and turn.role == "candidate":
            opening = turn.full_text.strip()[:160]
            polite = opening.lower().startswith(POLITE_OPENERS)
            out.append({
                "interviewer_was_saying": prev.spoken_text[-160:],
                "candidate_said": opening,
                "polite_opener": polite,
                "advice": ("Good: you signalled the interruption politely." if polite else
                           'Signal that you are cutting in, e.g. "Sorry to cut in, but…" or '
                           '"Can I just ask something quickly?"'),
            })
    return out


def deterministic_part(session: InterviewSession, turns: list[Turn], errors: list[Error]) -> tuple[dict, dict]:
    cand = [t for t in turns if t.role == "candidate"]
    metrics = [t.metrics or {} for t in cand]
    words = sum(m.get("words", _words(t.full_text)) for m, t in zip(metrics, cand))
    speaking_s = sum(m.get("speaking_s", 0) for m in metrics)
    fillers = sum(m.get("filler_count", 0) for m in metrics)
    pauses = sum(len(m.get("long_pauses", [])) for m in metrics)
    scored = sum(1 for m in metrics for z in m.get("word_z", []) if z is not None)
    shown = [e for e in errors if not e.dismissed and e.category != "pron:suspect"]
    pron_words = {(e.turn_id, (e.word or "").lower()) for e in shown if e.kind == "pronunciation"}
    by_kind = Counter(e.kind for e in shown)
    fluency = {
        "words": words,
        "speaking_s": round(speaking_s, 1),
        "wpm": round(words / (speaking_s / 60), 1) if speaking_s else 0.0,
        "filler_count": fillers,
        "fillers_per_min": round(fillers / (speaking_s / 60), 1) if speaking_s else 0.0,
        "long_pauses": pauses,
    }
    pronunciation = {
        "scored_words": scored,
        "error_words": len(pron_words),
        "accuracy": round(100 * (1 - len(pron_words) / scored), 1) if scored else None,
    }
    grammar_rate = round(100 * by_kind.get("grammar", 0) / words, 2) if words else None
    report = {
        "fluency": fluency,
        "pronunciation": pronunciation,
        "errors_by_kind": dict(by_kind),
        "grammar_per_100_words": grammar_rate,
        "analysis_pending": sum(1 for t in cand if t.analysis_status == "pending"),
    }
    scores = {
        "pronunciation_accuracy": pronunciation["accuracy"],
        "grammar_per_100_words": grammar_rate,
        "wpm": fluency["wpm"],
        "fillers_per_min": fluency["fillers_per_min"],
        "words": words,
    }
    return report, scores


def transcript_for_llm(turns: list[Turn]) -> str:
    lines = []
    for t in turns:
        who = "Interviewer" if t.role == "interviewer" else "Candidate"
        text = t.spoken_text if t.role == "interviewer" else t.full_text
        lines.append(f"{who}: {text}" + (" [interrupted by the candidate]" if t.interrupted else ""))
    text = "\n".join(lines)
    return text[-MAX_TRANSCRIPT_CHARS:]


async def llm_part(llm: LLMClient, session: InterviewSession, turns: list[Turn], errors: list[Error],
                   interruptions: list[dict]) -> LlmReport:
    rubric = RUBRICS[session.type]
    criteria = "\n".join(f'  - "{k}": {v}' for k, v in rubric.items())
    instruction = (
        '{"assessment": two sentences on HOW the candidate interrupted the interviewer (polite '
        'signal or not, timing), "examples": [{"candidate_said": quote, "advice": better phrasing}]}'
        if interruptions else "null (the candidate never interrupted)"
    )
    system = INSTRUCTIONS.format(session_type=session.type.replace("_", " "), seniority=session.seniority,
                                 criteria=criteria, interruption_instruction=instruction)
    error_summary = Counter(e.category for e in errors if not e.dismissed and e.category != "pron:suspect")
    user = json.dumps({
        "plan": session.plan, "transcript": transcript_for_llm(turns),
        "language_errors_by_category": dict(error_summary.most_common(15)),
        "interruptions": interruptions,
    }, ensure_ascii=False)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    raw = await llm.complete_json(messages)
    try:
        parsed = LlmReport.model_validate_json(raw)
    except ValidationError as exc:
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"Invalid JSON for the schema: {exc}. Return corrected JSON only."}]
        parsed = LlmReport.model_validate_json(await llm.complete_json(messages))
    # keep exactly the rubric's criteria, in order
    by_key = {r.criterion: r for r in parsed.rubric if r.criterion in rubric}
    parsed.rubric = [by_key[k] for k in rubric if k in by_key]
    return parsed


async def generate_report(session_id: uuid.UUID, llm: LLMClient | None) -> dict:
    async with SessionLocal() as db:
        session = await db.get(InterviewSession, session_id)
        turns = (await db.scalars(select(Turn).where(Turn.session_id == session_id).order_by(Turn.idx))).all()
        errors = (await db.scalars(select(Error).where(Error.session_id == session_id))).all()

        report, scores = deterministic_part(session, turns, errors)
        interruptions = interruption_examples(turns)
        report.update({"generated_at": datetime.now(UTC).isoformat(), "llm_ok": False, "rubric": [],
                       "strengths": [], "improvements": [], "better_answer": None,
                       "interruptions": {"assessment": None, "examples": interruptions} if interruptions else None})
        if not any(t.role == "candidate" for t in turns):
            report["no_answers"] = True  # nothing to evaluate: say so instead of "LLM missing"
        elif llm is not None:
            try:
                part = await llm_part(llm, session, turns, errors, interruptions)
                labels = RUBRICS[session.type]
                report.update({
                    "llm_ok": True,
                    "rubric": [{**r.model_dump(), "label": labels[r.criterion]} for r in part.rubric],
                    "strengths": part.strengths, "improvements": part.improvements,
                    "better_answer": part.better_answer.model_dump() if part.better_answer else None,
                })
                if interruptions:
                    review = part.interruptions
                    report["interruptions"] = {
                        "assessment": review.assessment if review else None,
                        "examples": (review.examples if review and review.examples else interruptions),
                    }
                scores["rubric"] = {r.criterion: r.score for r in part.rubric}
                scores["overall"] = round(sum(r.score for r in part.rubric) / len(part.rubric), 2) if part.rubric else None
            except Exception as exc:  # noqa: BLE001 — keep the deterministic report
                log.warning("report LLM part failed: %r", exc)
                report["llm_error"] = str(exc)
        session.report, session.scores = report, scores
        await db.commit()
    return report
