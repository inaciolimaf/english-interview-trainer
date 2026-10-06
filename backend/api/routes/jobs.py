import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import JobPosting, User
from api.db.session import get_db
from api.deps import get_current_user
from api.interview.parsing import parse_job
from api.llm.client import LLMClient, get_llm

log = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs")


class JobCreate(BaseModel):
    raw_text: str = Field(min_length=50, max_length=50_000)
    title: str | None = None
    company: str | None = None


def job_out(j: JobPosting, parse_error: str | None = None) -> dict:
    return {
        "id": str(j.id), "title": j.title, "company": j.company, "raw_text": j.raw_text,
        "parsed": j.parsed, "created_at": j.created_at, "parse_error": parse_error,
    }


async def _owned(db: AsyncSession, user: User, job_id: uuid.UUID) -> JobPosting:
    job = await db.get(JobPosting, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "Job posting not found")
    return job


async def _parse_into(job: JobPosting, llm: LLMClient, keep_title: bool) -> str | None:
    try:
        parsed = await parse_job(llm, job.raw_text)
    except Exception as exc:  # noqa: BLE001 — shown in the UI
        log.warning("job parse failed: %r", exc)
        return str(exc)
    job.parsed = parsed.model_dump()
    if not keep_title:
        job.title = parsed.title or job.title
        job.company = job.company or parsed.company
    return None


@router.get("")
async def list_jobs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = await db.scalars(
        select(JobPosting).where(JobPosting.user_id == user.id).order_by(JobPosting.created_at.desc())
    )
    return [job_out(j) for j in rows]


@router.post("")
async def create_job(
    body: JobCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
) -> dict:
    job = JobPosting(
        user_id=user.id, raw_text=body.raw_text.strip(),
        title=(body.title or "").strip() or "Untitled job", company=(body.company or "").strip() or None,
    )
    error = await _parse_into(job, llm, keep_title=bool(body.title))
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job_out(job, error)


@router.post("/{job_id}/reparse")
async def reparse_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
) -> dict:
    job = await _owned(db, user, job_id)
    error = await _parse_into(job, llm, keep_title=job.title != "Untitled job")
    await db.commit()
    await db.refresh(job)
    return job_out(job, error)


@router.delete("/{job_id}", status_code=204)
async def delete_job(
    job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    job = await _owned(db, user, job_id)
    await db.delete(job)
    await db.commit()
