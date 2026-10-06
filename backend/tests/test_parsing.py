import json

import pytest

from api.interview.parsing import ParseError, parse_job, parse_resume
from tests.conftest import FakeLLM

PROFILE_JSON = json.dumps({
    "name": "Ana Souza", "years_of_experience": 6, "stack": ["Python", "Node.js"],
    "roles": [{"title": "Backend Engineer", "company": "Shop", "start": "2021", "end": None, "highlights": []}],
    "projects": [{"name": "Checkout", "description": "New checkout", "impact": "-30% p99", "stack": ["Python"]}],
    "achievements": [],
})


async def test_resume_parses_valid_json():
    llm = FakeLLM(json_replies=[PROFILE_JSON])
    profile = await parse_resume(llm, "resume text")
    assert profile.name == "Ana Souza" and profile.projects[0].impact == "-30% p99"
    assert "JSON Schema" in llm.json_calls[0][0]["content"]


async def test_invalid_json_is_retried_once_with_the_error():
    llm = FakeLLM(json_replies=['{"name": 5, "stack": "oops"}', PROFILE_JSON])
    profile = await parse_resume(llm, "resume text")
    assert profile.name == "Ana Souza"
    retry = llm.json_calls[1]
    assert retry[-1]["role"] == "user" and "invalid" in retry[-1]["content"]


async def test_two_invalid_answers_raise():
    llm = FakeLLM(json_replies=["not json", "still not json"])
    with pytest.raises(ParseError):
        await parse_resume(llm, "resume text")


async def test_job_seniority_is_constrained():
    llm = FakeLLM(json_replies=[json.dumps({"seniority": "principal"}), json.dumps({"seniority": "senior", "domain": "fintech"})])
    job = await parse_job(llm, "posting")
    assert job.seniority == "senior" and job.domain == "fintech"
