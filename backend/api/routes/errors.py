import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import AudioClip, Error, InterviewSession, User, UserPhonemeAdjustment
from api.db.session import get_db
from api.deps import get_current_user
from api.pronunciation.pipeline import INSERTION, normalize

router = APIRouter()

OFFSET_STEP = 0.5  # threshold moves this much (GOP units) per "Not an error" on a phoneme
WORD_OFFSET_STEP = 1.0  # extra tolerance for one specific word
WORD_DISMISSALS = 2  # same word + phoneme dismissed this many times → word-specific adjustment


def error_out(e: Error) -> dict:
    return {
        "id": str(e.id), "turn_id": str(e.turn_id) if e.turn_id else None, "kind": e.kind,
        "category": e.category, "severity": e.severity, "original_text": e.original_text,
        "corrected_text": e.corrected_text, "explanation": e.explanation, "word": e.word,
        "expected_phonemes": e.expected_phonemes, "heard_phonemes": e.heard_phonemes,
        "phoneme_index": e.phoneme_index, "score": e.score, "dismissed": e.dismissed,
        "audio_url": f"/api/audio_clips/{e.audio_clip_id}" if e.audio_clip_id else None,
        "created_at": e.created_at,
        "session_id": str(e.session_id) if e.session_id else None,
    }


@router.get("/sessions/{session_id}/errors")
async def session_errors(
    session_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    session = await db.get(InterviewSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Session not found")
    rows = await db.scalars(select(Error).where(Error.session_id == session_id).order_by(Error.created_at))
    return [error_out(e) for e in rows]


@router.get("/errors")
async def explore_errors(
    kind: str | None = None, category: str | None = None, since: datetime | None = None,
    until: datetime | None = None, dismissed: bool | None = False, limit: int = 50, offset: int = 0,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Error explorer (section 12): filters by kind, category (prefix ok: "pron:"), period, dismissed."""
    q = select(Error).where(Error.user_id == user.id)
    if kind:
        q = q.where(Error.kind == kind)
    if category:
        q = q.where(Error.category.startswith(category) if category.endswith(":") else Error.category == category)
    if since:
        q = q.where(Error.created_at >= since)
    if until:
        q = q.where(Error.created_at < until)
    if dismissed is not None:
        q = q.where(Error.dismissed.is_(dismissed))
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = await db.scalars(q.order_by(Error.created_at.desc()).limit(min(limit, 200)).offset(offset))
    facets = (await db.execute(
        select(Error.kind, Error.category, func.count()).where(Error.user_id == user.id)
        .group_by(Error.kind, Error.category).order_by(func.count().desc())
    )).all()
    return {"total": total, "items": [error_out(e) for e in rows],
            "categories": [{"kind": k, "category": c, "count": n} for k, c, n in facets]}


@router.get("/audio_clips/{clip_id}")
async def audio_clip(
    clip_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> FileResponse:
    clip = await db.get(AudioClip, clip_id)
    if clip is None or clip.user_id != user.id or not Path(clip.file_path).exists():
        raise HTTPException(404, "Clip not found")
    return FileResponse(clip.file_path, media_type="audio/ogg")


def dismissed_phone(e: Error) -> str | None:
    """The phoneme an error is about ("+" for an extra vowel); None if not a phoneme error."""
    if e.kind != "pronunciation" or e.category == "pron:suspect":
        return None
    if e.category in ("pron:epenthesis", "pron:final_ed"):
        return INSERTION
    phones = (e.expected_phonemes or "").split()
    if e.phoneme_index is not None and 0 <= e.phoneme_index < len(phones):
        return phones[e.phoneme_index]
    return None


async def _bump(db: AsyncSession, user_id: uuid.UUID, phoneme: str, word: str | None, step: float) -> None:
    stmt = insert(UserPhonemeAdjustment).values(
        user_id=user_id, phoneme=phoneme, word=word, offset=step, dismiss_count=1
    )
    await db.execute(stmt.on_conflict_do_update(
        constraint="uq_user_phoneme_adjustments_user_id",
        set_={"offset": UserPhonemeAdjustment.offset + step,
              "dismiss_count": UserPhonemeAdjustment.dismiss_count + 1, "updated_at": func.now()},
    ))


@router.post("/errors/{error_id}/dismiss")
async def dismiss_error(
    error_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """"Not an error" (section 8.6): hide it and make the detector more tolerant for that phoneme;
    repeated dismissals on the same word create a word-specific adjustment."""
    error = await db.get(Error, error_id)
    if error is None or error.user_id != user.id:
        raise HTTPException(404, "Error not found")
    if error.dismissed:
        return error_out(error)
    error.dismissed, error.dismissed_at = True, datetime.now(UTC)

    phone = dismissed_phone(error)
    if phone:
        word = normalize(error.word or "")
        if phone == INSERTION:  # extra-vowel errors: always word-specific
            await _bump(db, user.id, INSERTION, word, 0.0)
        else:
            await _bump(db, user.id, phone, None, OFFSET_STEP)
            same_word = await db.scalar(
                select(func.count()).select_from(Error).where(
                    Error.user_id == user.id, Error.dismissed, Error.word == error.word,
                    Error.expected_phonemes == error.expected_phonemes, Error.phoneme_index == error.phoneme_index,
                )
            )
            if same_word >= WORD_DISMISSALS:  # autoflush: the count includes this dismissal
                await _bump(db, user.id, phone, word, WORD_OFFSET_STEP)
    await db.commit()
    await db.refresh(error)
    return error_out(error)
