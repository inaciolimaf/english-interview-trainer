import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Resume, User
from api.db.session import get_db
from api.deps import get_current_user
from api.interview.parsing import parse_resume, pdf_text
from api.llm.client import LLMClient, get_llm
from api.storage.files import save_upload

log = logging.getLogger(__name__)
router = APIRouter(prefix="/resumes")

MAX_PDF_BYTES = 10 * 2**20


def resume_out(r: Resume, parse_error: str | None = None) -> dict:
    return {
        "id": str(r.id), "file_name": Path(r.file_path).name, "is_active": r.is_active,
        "parsed_profile": r.parsed_profile, "created_at": r.created_at,
        "text_chars": len(r.raw_text), "parse_error": parse_error,
    }


async def _owned(db: AsyncSession, user: User, resume_id: uuid.UUID) -> Resume:
    resume = await db.get(Resume, resume_id)
    if resume is None or resume.user_id != user.id:
        raise HTTPException(404, "Resume not found")
    return resume


async def _parse_into(resume: Resume, llm: LLMClient) -> str | None:
    """Fill parsed_profile; on failure keep the resume and report why (re-parse later)."""
    try:
        resume.parsed_profile = (await parse_resume(llm, resume.raw_text)).model_dump()
        return None
    except Exception as exc:  # noqa: BLE001 — shown in the UI
        log.warning("resume parse failed: %r", exc)
        return str(exc)


@router.get("")
async def list_resumes(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = await db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc()))
    return [resume_out(r) for r in rows]


@router.post("")
async def upload_resume(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
) -> dict:
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF larger than 10 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Upload a PDF file")
    try:
        text = pdf_text(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Could not read the PDF: {exc}") from exc
    if len(text) < 50:
        raise HTTPException(422, "No text found in the PDF (is it a scanned image?)")

    path = save_upload(data, ".pdf")
    await db.execute(update(Resume).where(Resume.user_id == user.id).values(is_active=False))
    resume = Resume(user_id=user.id, file_path=str(path), raw_text=text, is_active=True)
    error = await _parse_into(resume, llm)
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return resume_out(resume, error)


@router.post("/{resume_id}/reparse")
async def reparse_resume(
    resume_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
) -> dict:
    resume = await _owned(db, user, resume_id)
    error = await _parse_into(resume, llm)
    await db.commit()
    await db.refresh(resume)
    return resume_out(resume, error)


@router.post("/{resume_id}/activate")
async def activate_resume(
    resume_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    resume = await _owned(db, user, resume_id)
    await db.execute(update(Resume).where(Resume.user_id == user.id).values(is_active=False))
    resume.is_active = True
    await db.commit()
    await db.refresh(resume)
    return resume_out(resume)


@router.delete("/{resume_id}", status_code=204)
async def delete_resume(
    resume_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    resume = await _owned(db, user, resume_id)
    Path(resume.file_path).unlink(missing_ok=True)
    await db.delete(resume)
    await db.commit()
