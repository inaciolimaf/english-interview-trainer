from api.interview.prompts import (
    END_MARKER, InterviewContext, interviewer_system_prompt, strip_end_marker, time_note,
)

JOB = {"title": "Senior Backend Engineer", "company": "Acme Pay",
       "parsed": {"domain": "fintech", "required_stack": ["Go", "PostgreSQL"], "summary": "Payments."}}
PROFILE = {"name": "Ana", "stack": ["Node.js"], "projects": [{"name": "Ledger", "description": "Built a ledger"}]}


def ctx(**kw) -> InterviewContext:
    base = dict(session_type="system_design", seniority="senior", style="neutral", duration_min=30,
                plan={"problem_title": "Payment processing", "problem_statement": "Design payments.",
                      "deep_dives": ["idempotency keys"]},
                job=JOB, profile=PROFILE)
    return InterviewContext(**{**base, **kw})


def test_prompt_contains_all_sections():
    p = interviewer_system_prompt(ctx())
    for expected in ("SYSTEM DESIGN", "Design payments.", "idempotency keys", "Acme Pay", "Go, PostgreSQL",
                     "Ledger", "Seniority target: senior", "Do NOT correct", "interrupted you", END_MARKER,
                     "30 minutes"):
        assert expected in p, expected


def test_prompt_is_deterministic_and_clock_free():
    assert interviewer_system_prompt(ctx()) == interviewer_system_prompt(ctx())
    assert "left" not in interviewer_system_prompt(ctx()).split("Time:")[0]


def test_styles_change_the_prompt():
    prompts = {s: interviewer_system_prompt(ctx(style=s)) for s in ("friendly", "neutral", "tough")}
    assert "hint" in prompts["friendly"] and "FRIENDLY" in prompts["friendly"]
    assert "TOUGH" in prompts["tough"] and "challenge" in prompts["tough"]
    assert len(set(prompts.values())) == 3


def test_types_have_their_scripts():
    assert "STAR" in interviewer_system_prompt(ctx(session_type="behavioral", plan={"themes": ["a conflict"]}))
    tech = interviewer_system_prompt(ctx(session_type="technical", plan={"stack": ["Go"], "stack_source": "job", "areas": ["caching"]}))
    assert "TECHNICAL" in tech and "from the job posting: Go" in tech


def test_prompt_without_job_or_resume():
    p = interviewer_system_prompt(ctx(job=None, profile=None))
    assert "No specific job posting" in p and "No resume available" in p


def test_time_notes_by_phase():
    assert time_note(20 * 60, 30 * 60).startswith("[Time check: about 20 minutes left of 30")
    assert "wrapping up" in time_note(4 * 60, 30 * 60)
    assert "Do you have any questions for me?" in time_note(80, 30 * 60)
    assert END_MARKER in time_note(-5, 30 * 60)


def test_strip_end_marker():
    assert strip_end_marker(f"Thanks, bye! {END_MARKER}") == ("Thanks, bye!", True)
    assert strip_end_marker(END_MARKER) == ("", True)
    assert strip_end_marker("Hello.") == ("Hello.", False)
