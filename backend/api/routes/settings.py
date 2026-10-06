from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import User, UserSettings
from api.db.session import get_db
from api.deps import get_current_user

router = APIRouter(prefix="/settings")

FIELDS = (
    "feedback_mode", "default_interviewer_style", "default_seniority", "default_duration_min",
    "turn_taking_mode", "end_of_turn_silence_ms", "tts_voice", "tts_speed", "phoneme_threshold_k",
)


class SettingsPatch(BaseModel):
    feedback_mode: Literal["live", "end", "hybrid"] | None = None
    default_interviewer_style: Literal["friendly", "neutral", "tough"] | None = None
    default_seniority: Literal["mid", "senior"] | None = None
    default_duration_min: int | None = None
    turn_taking_mode: Literal["auto", "push_to_talk"] | None = None
    end_of_turn_silence_ms: int | None = None
    tts_voice: str | None = None
    tts_speed: float | None = None
    phoneme_threshold_k: float | None = None


async def _load(db: AsyncSession, user: User) -> UserSettings:
    return await db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))


@router.get("")
async def get_settings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    s = await _load(db, user)
    return {f: getattr(s, f) for f in FIELDS}


@router.patch("")
async def patch_settings(
    body: SettingsPatch, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    s = await _load(db, user)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(s, field, value)
    await db.commit()
    return {f: getattr(s, f) for f in FIELDS}
