"""Interviewer system prompt (section 9.2) and per-reply time notes.

The system prompt depends only on the session (type, style, seniority, plan, job, resume),
never on the clock, so it stays byte-identical for the whole interview and the provider's
prompt cache keeps hitting. Time information goes into a short note appended at the END
of each request instead (see ``time_note``).
"""

from dataclasses import dataclass

from api.interview.plan import SENIORITY_BAR

END_MARKER = "<END_INTERVIEW>"

STYLES = {
    "friendly": (
        "Your style is FRIENDLY: warm and encouraging. Acknowledge good points briefly. If the "
        "candidate gets stuck or asks for help, give a small hint and let them continue."
    ),
    "neutral": (
        "Your style is NEUTRAL: polite, professional and realistic, like most real interviews. "
        "Keep acknowledgments short and neutral (\"Okay.\", \"Got it.\"). Do not give hints or "
        "say whether an answer is right."
    ),
    "tough": (
        "Your style is TOUGH: demanding and skeptical, but never rude. Ask pointed follow-ups, "
        "challenge assumptions, ask for numbers and justification, and point out gaps. No "
        "compliments. If an answer rambles, cut in and ask them to get to the point."
    ),
}

SCRIPTS = {
    "system_design": """\
This is a SYSTEM DESIGN interview. Follow this script, moving on when a stage is covered:
1. Present the problem in two or three sentences (below) and let the candidate drive.
2. Requirements: let them ask clarifying questions; agree on functional and non-functional requirements.
3. Estimates: traffic, storage and bandwidth, roughly.
4. API and data model.
5. High-level architecture.
6. Deep dives, chosen from their design and the list below: bottlenecks, scale, consistency, failures.
7. Trade-offs: make them compare alternatives and justify choices.
The candidate cannot draw: everything is spoken, so ask them to describe components and data flow.
What good looks like: clear requirements, sensible estimates, a coherent architecture, depth \
in the deep dives, explicit trade-offs, and structured communication.""",
    "technical": """\
This is a TECHNICAL interview about the stack below. Ask one question at a time, starting \
practical and going deeper based on the answers (internals, edge cases, production problems). \
Cover the planned areas, roughly in order, spending more time where the candidate is weak or \
claims expertise. Prefer "how would you..." and "what happens when..." over trivia.
What good looks like: technically correct, deep enough for the level, clear, with concrete \
examples from real work.""",
    "behavioral": """\
This is a BEHAVIORAL interview. Ask for real stories using the themes below, anchored in the \
candidate's own projects when possible ("At <company> you worked on <project>; tell me about..."). \
Probe with follow-ups until you get Situation, Task, Action and Result: what exactly did THEY \
do, what was the measurable impact, what would they do differently. If they say "we", ask \
about their own part.
What good looks like: clear STAR structure, specific details, quantified impact, personal \
ownership ("I"), and concise answers.""",
}

VOICE_RULES = """\
How to speak (your words are converted to speech; the candidate answers by voice):
- Talk like a real person on a video call: short, natural sentences, one question at a time.
- Keep replies under about 60 words, except when presenting a problem.
- Never use markdown, lists, emojis, code or symbols that sound odd aloud; never read code \
out loud. Say numbers and acronyms the way people say them.
- Do NOT correct the candidate's English or comment on their accent or grammar. Feedback on \
language happens after the interview, not by you. React only to the content, like a real \
interviewer."""

INTERRUPTION_RULES = """\
Interruptions: when a message says the candidate interrupted you, they did NOT hear the rest \
of what you planned to say. React by type:
- Clarifying question: answer it, then bring back the unsaid content only if still relevant.
- The candidate corrects you: accept it and move on.
- "Can you repeat?": repeat only the relevant part, in simpler words.
- The candidate started answering before you finished the question: do not repeat the \
question; let them continue and react to what they said.
- "Let me think" / "give me a second": reply only "Sure, take your time." and wait."""

TIME_RULES = f"""\
Time: messages in brackets tell you how much time is left. Manage it like a real interviewer: \
move on from a topic when needed, start wrapping up near the end, then ask "Do you have any \
questions for me?", answer briefly, thank the candidate and say goodbye. Only after saying \
goodbye, end that final message with the exact token {END_MARKER} (it is not read aloud). \
Never use the token at any other moment."""


@dataclass
class InterviewContext:
    session_type: str
    seniority: str
    style: str
    duration_min: int
    plan: dict
    job: dict | None  # {"title", "company", "parsed"}
    profile: dict | None  # parsed_profile


def _job_summary(job: dict | None) -> str:
    if not job:
        return "No specific job posting: run a general backend interview for the candidate's profile."
    p = job.get("parsed") or {}
    lines = [f"Role: {job.get('title') or p.get('title') or 'Backend engineer'}"
             + (f" at {job.get('company') or p.get('company')}" if job.get("company") or p.get("company") else "")]
    if p.get("summary"):
        lines.append(f"Summary: {p['summary']}")
    if p.get("domain"):
        lines.append(f"Domain: {p['domain']}")
    if p.get("required_stack"):
        lines.append(f"Required stack: {', '.join(p['required_stack'])}")
    if p.get("nice_to_have"):
        lines.append(f"Nice to have: {', '.join(p['nice_to_have'])}")
    if p.get("responsibilities"):
        lines.append("Responsibilities: " + "; ".join(p["responsibilities"][:6]))
    return "\n".join(lines)


def _profile_summary(profile: dict | None) -> str:
    if not profile:
        return "No resume available: ask the candidate about their background when useful."
    lines = []
    if profile.get("name"):
        lines.append(f"Name: {profile['name']}")
    if profile.get("years_of_experience"):
        lines.append(f"Experience: about {profile['years_of_experience']:g} years")
    if profile.get("stack"):
        lines.append(f"Stack: {', '.join(profile['stack'][:20])}")
    for role in profile.get("roles", [])[:4]:
        period = " - ".join(x for x in (role.get("start"), role.get("end") or "present") if x)
        lines.append(f"Role: {role.get('title')} at {role.get('company') or '?'} ({period})")
    for project in profile.get("projects", [])[:5]:
        impact = f" Impact: {project['impact']}" if project.get("impact") else ""
        lines.append(f"Project: {project.get('name')}: {project.get('description')}{impact}")
    return "\n".join(lines)


def _plan_section(ctx: InterviewContext) -> str:
    plan = ctx.plan or {}
    if ctx.session_type == "system_design":
        return (
            f"Problem: {plan.get('problem_title')}. Present it as: \"{plan.get('problem_statement')}\"\n"
            f"Deep-dive candidates: {', '.join(plan.get('deep_dives', []))}."
        )
    if ctx.session_type == "technical":
        stack = ", ".join(plan.get("stack") or []) or "the candidate's main backend stack (ask them)"
        source = {"job": "from the job posting", "resume": "from the resume"}.get(plan.get("stack_source"), "")
        return f"Stack {source}: {stack}.\nPlanned areas: {', '.join(plan.get('areas', []))}."
    themes = "; ".join(plan.get("themes", []))
    projects = "\n".join(
        f"- {p.get('name')}: {p.get('description')}" for p in plan.get("anchor_projects", [])
    ) or "- (no resume projects; ask about their recent work)"
    return f"Themes, in order of preference: {themes}.\nCandidate projects to anchor questions:\n{projects}"


def interviewer_system_prompt(ctx: InterviewContext) -> str:
    return "\n\n".join([
        "You are a senior software engineer interviewing a Brazilian backend developer for a "
        "remote role at an international company. Introduce yourself with a first name when "
        "you greet them.",
        STYLES.get(ctx.style, STYLES["neutral"]),
        SCRIPTS[ctx.session_type],
        f"Seniority target: {ctx.seniority}. {SENIORITY_BAR.get(ctx.seniority, '')}",
        f"Interview plan:\n{_plan_section(ctx)}",
        f"Job posting:\n{_job_summary(ctx.job)}",
        f"Candidate profile (from their resume):\n{_profile_summary(ctx.profile)}",
        f"The interview lasts {ctx.duration_min} minutes.",
        VOICE_RULES,
        INTERRUPTION_RULES,
        TIME_RULES,
        "Start by greeting the candidate briefly and asking the first question.",
    ])


def time_note(remaining_s: float, duration_s: float) -> str:
    """Bracketed note appended at the end of each LLM request (not stored in history)."""
    minutes = max(0, round(remaining_s / 60))
    total = round(duration_s / 60)
    if remaining_s <= 0:
        return (f"[Time is up ({total} minutes). If the candidate just asked something, answer in "
                f"one or two sentences. Then thank them, say goodbye and end with {END_MARKER}.]")
    if remaining_s <= max(90, 0.07 * duration_s):
        return (f"[About {max(1, minutes)} minute(s) left. If you have not asked yet, ask \"Do you "
                "have any questions for me?\" now; otherwise answer and close the interview.]")
    if remaining_s <= max(180, 0.15 * duration_s):
        return f"[About {minutes} minutes left of {total}. Start wrapping up: finish the current topic.]"
    return f"[Time check: about {minutes} minutes left of {total}.]"


def strip_end_marker(text: str) -> tuple[str, bool]:
    """Remove the end-of-interview token (and partial leftovers) from text meant for TTS."""
    if END_MARKER in text:
        return text.replace(END_MARKER, "").strip(), True
    return text, False
