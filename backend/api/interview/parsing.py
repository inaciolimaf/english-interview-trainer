"""Resume and job posting extraction with the LLM in JSON mode (sections 6.1 and 6.2)."""

import json
from io import BytesIO
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader

from api.llm.client import LLMClient

M = TypeVar("M", bound=BaseModel)


class Role(BaseModel):
    title: str
    company: str | None = None
    start: str | None = None  # free text as written ("Jan 2021", "2019")
    end: str | None = None  # None/"present" for the current job
    highlights: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: str
    impact: str | None = None  # quantified results when the resume has them
    stack: list[str] = Field(default_factory=list)


class ParsedProfile(BaseModel):
    name: str | None = None
    years_of_experience: float | None = None
    stack: list[str] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)


class ParsedJob(BaseModel):
    title: str | None = None
    company: str | None = None
    seniority: Literal["junior", "mid", "senior", "staff", "unknown"] = "unknown"
    required_stack: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    domain: str | None = None  # business domain, e.g. "fintech", "e-commerce", "healthcare"
    summary: str | None = None  # two sentences about the role


class ParseError(RuntimeError):
    pass


def pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


RESUME_INSTRUCTIONS = """\
Extract a structured profile from the resume below. Answer with a single JSON object that \
matches this JSON Schema exactly (no extra keys, no comments):

{schema}

Rules:
- Use only facts present in the resume; use null or [] when something is missing.
- "stack": technologies, languages, frameworks, databases and cloud services the person used.
- "projects": include significant work described inside roles too (one entry per system or \
initiative), keeping numbers such as latency, users or revenue in "impact".
- Keep the resume's language for names; write descriptions in English."""

JOB_INSTRUCTIONS = """\
Extract the key facts of the job posting below. Answer with a single JSON object that \
matches this JSON Schema exactly (no extra keys, no comments):

{schema}

Rules:
- "seniority": infer from title and requirements; "unknown" if it is not possible.
- "required_stack" vs "nice_to_have": follow the posting's wording (required/must vs plus/nice).
- "domain": the company's business domain in one or two words, lower case.
- "summary": two short sentences in English about what the role does."""


async def _extract(llm: LLMClient, instructions: str, document: str, model: type[M]) -> M:
    """Ask for JSON, validate with Pydantic, and retry once with the validation error."""
    schema = json.dumps(model.model_json_schema())
    messages = [
        {"role": "system", "content": instructions.format(schema=schema)},
        {"role": "user", "content": document},
    ]
    last_error = ""
    for _ in range(2):
        raw = await llm.complete_json(messages)
        try:
            return model.model_validate_json(raw)
        except ValidationError as exc:
            last_error = str(exc)
            messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"That JSON is invalid:\n{last_error}\nReturn the corrected JSON only."},
            ]
    raise ParseError(f"LLM returned invalid JSON twice: {last_error[:500]}")


async def parse_resume(llm: LLMClient, text: str) -> ParsedProfile:
    return await _extract(llm, RESUME_INSTRUCTIONS, text, ParsedProfile)


async def parse_job(llm: LLMClient, text: str) -> ParsedJob:
    return await _extract(llm, JOB_INSTRUCTIONS, text, ParsedJob)
