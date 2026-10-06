"""AI coach that walks the candidate through a session report and answers questions about it.

The data block (report + grouped errors + transcript) goes into the system prompt, which is
identical for every message of the conversation, so the provider's prompt cache keeps hitting.
"""

from collections import defaultdict

from api.analysis.language import TAXONOMY
from api.db.models import Error, InterviewSession, Turn
from api.llm.client import Message

START = "Start the debrief."
MAX_TRANSCRIPT_CHARS = 14_000
EXAMPLES_PER_GROUP = 3

SYSTEM = """\
You are a friendly, honest English and interview coach. Your student is a Brazilian backend \
developer with intermediate spoken English who just finished a mock job interview. You are \
going through the report of that interview with them, in a chat.

How to talk:
- Simple, clear English (they are intermediate). Short paragraphs. You may use **bold** and \
"- " bullet lines; no tables, no headings.
- Be direct and kind: say what went wrong, why it matters in a real interview, and exactly how \
to fix it. Use their own words as examples.
- Only use the data below. Never invent errors, quotes, scores or numbers. If they ask about \
something that is not in the data, say so and answer from general knowledge.

Special markers (the app turns them into buttons):
- [[clip:ERROR_ID]] lets them hear their own recording of that error. Only use ids listed in \
the data with "clip: yes". Put it right after the example it belongs to.
- [[say:short phrase]] lets them hear the correct pronunciation or sentence in a native voice. \
Use it for the corrected sentence or word you want them to repeat (max 20 words).

The debrief:
- When asked to start: one short paragraph with the overall picture (scores, one real \
strength), say how many key points you will cover (4 to 7), then explain point 1.
- Explain ONE point per message, in this order of importance for a real interview: answer \
structure and clarity; the biggest technical gap; the most frequent grammar pattern; the most \
frequent pronunciation pattern; vocabulary and technical terms; fluency (fillers, pauses). \
Skip any area with nothing important.
- For each point: what happened (quote them, add a clip when there is one), why it matters, \
how to fix it, a model sentence with [[say:...]], and a tiny exercise ("Say it out loud three \
times", "Answer this question again using...").
- End every message with one short line offering the next step (next point, an exercise, or \
a question). When all points are done, give a 3-line practice plan.
- When they ask a question, answer it fully first; then offer to continue the debrief.

=== INTERVIEW DATA ===
{data}"""


def _short(text: str | None, n: int = 220) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def group_errors(errors: list[Error]) -> list[tuple[str, list[Error]]]:
    """Errors grouped by category, most frequent first (dismissed ones excluded)."""
    groups: dict[str, list[Error]] = defaultdict(list)
    for e in errors:
        if not e.dismissed:
            groups[e.category].append(e)
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _category_label(category: str) -> str:
    if category in TAXONOMY:
        return TAXONOMY[category]
    if category == "pron:suspect":
        return "words the speech recognizer could not hear clearly"
    return category.replace(":", " ").replace("_", " ")


def build_context(session: InterviewSession, turns: list[Turn], errors: list[Error]) -> str:
    lines: list[str] = [
        f"Interview: {session.type.replace('_', ' ')}, target seniority {session.seniority}, "
        f"{session.interviewer_style} interviewer, {session.duration_min} minutes.",
    ]
    report = session.report or {}
    scores = session.scores or {}
    if scores:
        lines.append(
            "Scores: overall {o}/5, pronunciation accuracy {p}%, grammar errors per 100 words {g}, "
            "speaking rate {w} wpm, fillers per minute {f}.".format(
                o=scores.get("overall", "n/a"), p=scores.get("pronunciation_accuracy", "n/a"),
                g=scores.get("grammar_per_100_words", "n/a"), w=scores.get("wpm", "n/a"),
                f=scores.get("fillers_per_min", "n/a")))
    for r in report.get("rubric", []):
        lines.append(f"Rubric — {r.get('label', r['criterion'])}: {r['score']}/5. {_short(r.get('justification'), 400)}")
    if report.get("strengths"):
        lines.append("Strengths: " + " | ".join(report["strengths"]))
    if report.get("improvements"):
        lines.append("Top improvements: " + " | ".join(report["improvements"]))
    if report.get("better_answer"):
        b = report["better_answer"]
        lines.append(f"Weakest question: {b['question']} | They said: {b['answer_summary']} | "
                     f"Model answer: {b['improved_answer']}")
    if report.get("interruptions") and report["interruptions"].get("assessment"):
        lines.append(f"How they interrupted: {report['interruptions']['assessment']}")

    lines.append("\nErrors grouped by category (count, then examples):")
    for category, group in group_errors(errors):
        lines.append(f"\n[{category}] {_category_label(category)} — {len(group)}×")
        if category == "pron:suspect":
            lines.append("  words: " + ", ".join(sorted({e.word or '' for e in group})))
            continue
        for e in group[:EXAMPLES_PER_GROUP]:
            parts = [f"  - id {e.id}", f"clip: {'yes' if e.audio_clip_id else 'no'}"]
            if e.kind == "pronunciation":
                parts.append(f"word '{e.word}' expected /{e.expected_phonemes}/ heard /{e.heard_phonemes}/")
            elif e.original_text:
                parts.append(f"said '{_short(e.original_text, 160)}'")
                if e.corrected_text:
                    parts.append(f"better '{_short(e.corrected_text, 160)}'")
            parts.append(f"note: {_short(e.explanation)}")
            lines.append(" | ".join(parts))

    lines.append("\nTranscript:")
    transcript = []
    for t in turns:
        who = "Interviewer" if t.role == "interviewer" else "Candidate"
        transcript.append(f"{who}: {t.spoken_text if t.role == 'interviewer' else t.full_text}")
    text = "\n".join(transcript)
    lines.append(text if len(text) <= MAX_TRANSCRIPT_CHARS else "…" + text[-MAX_TRANSCRIPT_CHARS:])
    return "\n".join(lines)


def build_messages(context: str, history: list[dict]) -> list[Message]:
    messages: list[Message] = [{"role": "system", "content": SYSTEM.format(data=context)}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    return messages
