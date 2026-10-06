"""REST: resumes, job postings, session creation with plan and defaults, settings.
Needs Postgres; the LLM is faked."""

import json

import httpx
import pytest

from tests.conftest import FakeLLM, track
from tests.test_parsing import PROFILE_JSON

JOB_TEXT = (
    "Acme Pay is hiring a Senior Backend Engineer to build payment APIs in Go and PostgreSQL. "
    "You will own the ledger service and on-call. Nice to have: Kafka, AWS."
)
JOB_JSON = json.dumps({
    "title": "Senior Backend Engineer", "company": "Acme Pay", "seniority": "staff",
    "required_stack": ["Go", "PostgreSQL"], "nice_to_have": ["Kafka", "AWS"],
    "responsibilities": ["Build payment APIs", "Own the ledger"], "domain": "fintech",
    "summary": "Builds payment APIs.",
})


def make_pdf(text: str) -> bytes:
    """Smallest valid one-page PDF with real text (pypdf can extract it)."""
    stream = f"BT /F1 11 Tf 50 750 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


RESUME_PDF = make_pdf("Ana Souza - Backend Engineer - 6 years with Python, Node.js and PostgreSQL. Built checkout.")


@pytest.fixture
def client(server):
    with httpx.Client(base_url=server, timeout=10) as c:
        yield c


def test_resume_upload_parse_activate_and_reparse(client, use_llm):
    llm = use_llm(FakeLLM(json_replies=[PROFILE_JSON, PROFILE_JSON, PROFILE_JSON]))
    r = client.post("/api/resumes", files={"file": ("cv.pdf", RESUME_PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    first = r.json()
    track("resumes", first["id"])
    assert first["is_active"] and first["parse_error"] is None
    assert first["parsed_profile"]["name"] == "Ana Souza"
    assert "Ana Souza" in llm.json_calls[0][1]["content"]  # the PDF text reached the LLM

    second = client.post("/api/resumes", files={"file": ("cv2.pdf", RESUME_PDF, "application/pdf")}).json()
    track("resumes", second["id"])
    listed = {r["id"]: r["is_active"] for r in client.get("/api/resumes").json()}
    assert listed[second["id"]] and not listed[first["id"]]  # newest upload becomes active

    assert client.post(f"/api/resumes/{first['id']}/activate").json()["is_active"]
    assert client.post(f"/api/resumes/{first['id']}/reparse").json()["parsed_profile"]["name"] == "Ana Souza"
    assert client.delete(f"/api/resumes/{second['id']}").status_code == 204


def test_resume_kept_when_llm_fails(client, use_llm):
    use_llm(FakeLLM(json_replies=["nope", "nope"]))
    r = client.post("/api/resumes", files={"file": ("cv.pdf", RESUME_PDF, "application/pdf")}).json()
    track("resumes", r["id"])
    assert r["parsed_profile"] is None and "invalid JSON" in r["parse_error"]


def test_resume_rejects_non_pdf(client, use_llm):
    use_llm(FakeLLM())
    r = client.post("/api/resumes", files={"file": ("cv.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_jobs_crud_and_session_defaults_from_job(client, use_llm):
    use_llm(FakeLLM(json_replies=[JOB_JSON]))
    job = client.post("/api/jobs", json={"raw_text": JOB_TEXT}).json()
    track("job_postings", job["id"])
    assert job["title"] == "Senior Backend Engineer" and job["company"] == "Acme Pay"
    assert job["parsed"]["domain"] == "fintech"
    assert any(j["id"] == job["id"] for j in client.get("/api/jobs").json())

    original = client.get("/api/settings").json()
    client.patch("/api/settings", json={"default_seniority": "mid", "default_duration_min": 30})
    try:
        _sessions_from_job(client, job)
    finally:
        client.patch("/api/settings", json=original)
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204


def _sessions_from_job(client, job):
    s = client.post("/api/sessions", json={"type": "system_design", "job_posting_id": job["id"],
                                           "interviewer_style": "tough", "duration_min": 45}).json()
    track("interview_sessions", s["id"])
    assert s["seniority"] == "senior"  # "staff" in the posting → senior, overriding settings (mid)
    assert s["interviewer_style"] == "tough" and s["duration_min"] == 45
    assert s["plan"]["problem_id"] in {"payments", "wallet_ledger"}  # fintech domain

    t = client.post("/api/sessions", json={"type": "technical", "job_posting_id": job["id"]}).json()
    track("interview_sessions", t["id"])
    assert t["plan"]["stack"] == ["Go", "PostgreSQL"] and t["plan"]["stack_source"] == "job"
    assert t["duration_min"] == 30  # from settings


def test_session_rejects_invalid_duration(client, use_llm):
    use_llm(FakeLLM())
    assert client.post("/api/sessions", json={"type": "technical", "duration_min": 20}).status_code == 422


def test_settings_roundtrip(client):
    original = client.get("/api/settings").json()
    try:
        updated = client.patch("/api/settings", json={"tts_voice": "am_michael", "end_of_turn_silence_ms": 1800}).json()
        assert updated["tts_voice"] == "am_michael" and updated["end_of_turn_silence_ms"] == 1800
    finally:
        client.patch("/api/settings", json=original)
