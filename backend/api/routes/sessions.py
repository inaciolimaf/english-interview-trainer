import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import InterviewSession, JobPosting, Resume, Turn, User, UserSettings
from api.db.session import get_db
from api.deps import get_current_user
from api.analysis.worker import ReportJob
from api.interview.plan import build_plan
from api.llm.client import LLMClient, get_llm

RECENT_PROBLEMS = 5  # avoid repeating the last N system design problems
JOB_SENIORITY = {"junior": "mid", "mid": "mid", "senior": "senior", "staff": "senior"}

router = APIRouter(prefix="/sessions")


class SessionCreate(BaseModel):
    type: Literal["system_design", "technical", "behavioral"] = "technical"
    job_posting_id: uuid.UUID | None = None
    resume_id: uuid.UUID | None = None  # default: the active resume
    seniority: Literal["mid", "senior"] | None = None  # default: from the job, else settings
    interviewer_style: Literal["friendly", "neutral", "tough"] | None = None
    duration_min: Literal[15, 30, 45, 60] | None = None
    feedback_mode: Literal["live", "end", "hybrid"] | None = None


def session_out(s: InterviewSession) -> dict:
    return {
        "id": str(s.id), "type": s.type, "status": s.status, "seniority": s.seniority,
        "interviewer_style": s.interviewer_style, "duration_min": s.duration_min,
        "feedback_mode": s.feedback_mode, "started_at": s.started_at, "ended_at": s.ended_at,
        "job_posting_id": str(s.job_posting_id) if s.job_posting_id else None,
        "resume_id": str(s.resume_id) if s.resume_id else None, "plan": s.plan,
        "report": s.report, "scores": s.scores,
    }


@router.post("")
async def create_session(
    body: SessionCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    job = await db.get(JobPosting, body.job_posting_id) if body.job_posting_id else None
    if body.job_posting_id and (job is None or job.user_id != user.id):
        raise HTTPException(404, "Job posting not found")
    if body.resume_id:
        resume = await db.get(Resume, body.resume_id)
        if resume is None or resume.user_id != user.id:
            raise HTTPException(404, "Resume not found")
    else:
        resume = await db.scalar(select(Resume).where(Resume.user_id == user.id, Resume.is_active))

    job_seniority = (job.parsed or {}).get("seniority") if job else None
    recent = (await db.scalars(
        select(InterviewSession.plan)
        .where(InterviewSession.user_id == user.id, InterviewSession.type == "system_design")
        .order_by(InterviewSession.started_at.desc()).limit(RECENT_PROBLEMS)
    )).all()
    plan = build_plan(
        body.type, job.parsed if job else None, resume.parsed_profile if resume else None,
        {p.get("problem_id") for p in recent if p},
    )
    session = InterviewSession(
        user_id=user.id,
        type=body.type,
        job_posting_id=job.id if job else None,
        resume_id=resume.id if resume else None,
        plan=plan,
        seniority=body.seniority or JOB_SENIORITY.get(job_seniority or "") or settings.default_seniority,
        interviewer_style=body.interviewer_style or settings.default_interviewer_style,
        duration_min=body.duration_min or settings.default_duration_min,
        feedback_mode=body.feedback_mode or settings.feedback_mode,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session_out(session)


@router.get("/{session_id}")
async def get_session(
    session_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    session = await db.get(InterviewSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Session not found")
    turns = (await db.scalars(select(Turn).where(Turn.session_id == session_id).order_by(Turn.idx))).all()
    return {
        **session_out(session),
        "turns": [
            {
                "id": str(t.id), "idx": t.idx, "role": t.role, "full_text": t.full_text,
                "spoken_text": t.spoken_text, "interrupted": t.interrupted,
                "interrupted_at_char": t.interrupted_at_char, "audio_ms": t.audio_ms,
                "analysis_status": t.analysis_status, "metrics": t.metrics, "asr_words": t.asr_words,
            }
            for t in turns
        ],
    }


@router.get("")
async def list_sessions(
    limit: int = 20, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    rows = await db.scalars(
        select(InterviewSession).where(InterviewSession.user_id == user.id)
        .order_by(InterviewSession.started_at.desc()).limit(min(limit, 100))
    )
    return [session_out(s) for s in rows]


@router.post("/{session_id}/report", status_code=202)
async def regenerate_report(
    session_id: uuid.UUID, request: Request, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db), llm: LLMClient = Depends(get_llm),
) -> dict:
    """(Re)generate the report — e.g. for an abandoned session. Runs after pending analyses."""
    session = await db.get(InterviewSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Session not found")
    request.app.state.analysis.submit(ReportJob(session_id, llm, drills=session.report is None))
    return {"status": "queued"}
