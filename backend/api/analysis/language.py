"""Grammar, technical and vocabulary analysis of one answer with the LLM (section 10.1, step 3)."""

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from api.llm.client import LLMClient

# Stable taxonomy (section 5.4). "*:other" catches anything the LLM can't place.
TAXONOMY: dict[str, str] = {
    "gram:preposition": "wrong or missing preposition (depend of → depend on)",
    "gram:article": "missing/extra/wrong article (a, an, the)",
    "gram:verb_tense": "wrong tense or verb form (I work there since 2020 → I've worked)",
    "gram:subject_verb_agreement": "subject-verb agreement (the service handle → handles)",
    "gram:word_order": "unnatural word order (what is the problem? in indirect questions, adjective order)",
    "gram:false_friend": "Portuguese false friend (actually, pretend, assist, eventually, realize, push)",
    "gram:missing_subject": "missing subject or dummy 'it' (is possible → it is possible)",
    "gram:plural": "plural/countable errors (informations, softwares, feedbacks)",
    "gram:other": "other grammar error",
    "tech:caching": "caching", "tech:consistency": "consistency and transactions",
    "tech:databases": "databases and data modeling", "tech:messaging": "queues and messaging",
    "tech:concurrency": "concurrency", "tech:api_design": "API design", "tech:estimation": "estimation",
    "tech:tradeoffs": "missing or wrong trade-offs", "tech:scalability": "scalability",
    "tech:reliability": "failure handling and reliability", "tech:security": "security",
    "tech:testing": "testing", "tech:other": "other technical issue",
    "vocab:missing_term": "the right technical term was not used (\"the thing that distributes requests\" → load balancer)",
    "vocab:word_choice": "unnatural word choice or collocation (make a question → ask a question)",
    "vocab:other": "other vocabulary issue",
}
KIND_PREFIX = {"grammar": "gram:", "technical": "tech:", "vocabulary": "vocab:"}
MAX_ISSUES = 8

INSTRUCTIONS = """\
You review one spoken answer of a Brazilian backend developer in an English job interview \
({session_type}, target seniority: {seniority}). The answer is a speech-to-text transcript.

Find real problems of three kinds:
- grammar: errors a fluent speaker would not make. Typical for Brazilians: prepositions, \
articles, verb tense (present perfect, "since/for"), subject-verb agreement, missing subject \
("is possible"), false friends ("actually" = currently, "pretend", "assist", "eventually"), \
uncountable plurals ("informations"), "make/do" collocations.
- technical: wrong concepts, important points omitted for the seniority, weak or missing \
trade-offs. Judge the content, not the English.
- vocabulary: vague wording where a precise technical term exists, or unnatural word choice.

Do NOT report: fillers, hesitations, repetitions or false starts (handled separately), \
casual spoken register, punctuation, capitalization, or likely transcription glitches. Do not \
report anything about pronunciation. Report at most {max_issues} issues, most important first; \
an empty list is fine.

For grammar and vocabulary, "original_text" must be copied EXACTLY from the answer (a short \
span of 2–12 words) and "corrected_text" is the fixed span. For technical issues, quote the \
relevant span if there is one, else use "" and describe what was missing.
"explanation": one or two sentences in simple English addressed to the candidate ("you").
"severity": high = changes meaning or is a serious technical mistake; medium = clearly wrong; \
low = minor or stylistic.
"category" must be one of: {categories}

Answer with JSON: {{"issues": [{{"kind": "grammar"|"technical"|"vocabulary", "category": "...", \
"original_text": "...", "corrected_text": "...", "explanation": "...", "severity": "low"|"medium"|"high"}}]}}"""


class LanguageIssue(BaseModel):
    kind: Literal["grammar", "technical", "vocabulary"]
    category: str
    original_text: str = ""
    corrected_text: str | None = None
    explanation: str
    severity: Literal["low", "medium", "high"] = "medium"


class LanguageAnalysis(BaseModel):
    issues: list[LanguageIssue] = Field(default_factory=list)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


def validate_issues(issues: list[LanguageIssue], answer: str) -> list[LanguageIssue]:
    """Keep the taxonomy stable and quotes real: grammar/vocabulary spans must exist in the
    answer (the LLM can't invent what the candidate said); unknown categories → "*:other"."""
    answer_norm = f" {_norm(answer)} "
    out = []
    for issue in issues[:MAX_ISSUES]:
        prefix = KIND_PREFIX[issue.kind]
        if issue.category not in TAXONOMY or not issue.category.startswith(prefix):
            issue = issue.model_copy(update={"category": f"{prefix}other"})
        quote = _norm(issue.original_text)
        if issue.kind != "technical" and (not quote or f" {quote} " not in answer_norm):
            continue
        if quote and f" {quote} " not in answer_norm:
            issue = issue.model_copy(update={"original_text": ""})  # technical: keep, unanchored
        out.append(issue)
    return out


async def analyze_language(
    llm: LLMClient, question: str, answer: str, seniority: str, session_type: str,
) -> list[LanguageIssue]:
    system = INSTRUCTIONS.format(
        session_type=session_type.replace("_", " "), seniority=seniority, max_issues=MAX_ISSUES,
        categories=", ".join(TAXONOMY),
    )
    user = json.dumps({"interviewer_question": question, "candidate_answer": answer})
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    raw = await llm.complete_json(messages)
    try:
        parsed = LanguageAnalysis.model_validate_json(raw)
    except ValidationError as exc:
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"Invalid JSON for the schema: {exc}. Return corrected JSON only."}]
        parsed = LanguageAnalysis.model_validate_json(await llm.complete_json(messages))
    return validate_issues(parsed.issues, answer)
