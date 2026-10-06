import random

from api.interview.plan import SYSTEM_DESIGN_PROBLEMS, build_plan, choose_design_problem

FINTECH_JOB = {
    "domain": "fintech", "summary": "Build payment APIs.", "responsibilities": ["Own the ledger"],
    "required_stack": ["Python", "PostgreSQL", "Kafka"], "nice_to_have": ["AWS"],
}
PROFILE = {
    "stack": ["Node.js", "TypeScript", "Redis"],
    "projects": [{"name": "Checkout", "description": "Rewrote checkout", "impact": "-30% p99"}],
}


def test_design_problem_matches_job_domain():
    for seed in range(20):
        p = choose_design_problem(FINTECH_JOB, set(), random.Random(seed))
        assert "fintech" in p.domains


def test_design_problem_avoids_recent_ones():
    fintech_ids = {p.id for p in SYSTEM_DESIGN_PROBLEMS if "fintech" in p.domains}
    recent = fintech_ids - {"payments"}
    assert choose_design_problem(FINTECH_JOB, recent, random.Random(1)).id == "payments"


def test_design_problem_without_job_is_general():
    p = choose_design_problem(None, set(), random.Random(3))
    assert "general" in p.domains


def test_technical_stack_comes_from_job_then_resume():
    with_job = build_plan("technical", FINTECH_JOB, PROFILE, set(), random.Random(0))
    assert with_job["stack"] == ["Python", "PostgreSQL", "Kafka"]
    assert with_job["stack_source"] == "job"
    assert "messaging and queues" in with_job["areas"]
    without_job = build_plan("technical", None, PROFILE, set(), random.Random(0))
    assert without_job["stack"] == ["Node.js", "TypeScript", "Redis"]
    assert without_job["stack_source"] == "resume"
    assert "caching" in without_job["areas"]


def test_behavioral_plan_anchors_resume_projects():
    plan = build_plan("behavioral", None, PROFILE, set(), random.Random(0))
    assert plan["anchor_projects"][0]["name"] == "Checkout"
    assert len(plan["themes"]) == 5
