"""SQLAlchemy models — the full data model from section 5 of the overview.

Conventions:
- UUID primary keys, ``created_at``/``updated_at`` on every table.
- Enums are ``TEXT`` + ``CHECK`` constraints (easier to evolve than PG enums).
- Phoneme sequences are stored as space-separated IPA strings (e.g. "θ ɹ uː p ʊ t").
- Every table holding personal data has a ``user_id``.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Enum values (also used by the API/seed)
FEEDBACK_MODES = ("live", "end", "hybrid")
INTERVIEWER_STYLES = ("friendly", "neutral", "tough")
SENIORITIES = ("mid", "senior")
TURN_TAKING_MODES = ("auto", "push_to_talk")
SESSION_TYPES = ("system_design", "technical", "behavioral")
SESSION_STATUSES = ("active", "completed", "abandoned")
TURN_ROLES = ("interviewer", "candidate")
ANALYSIS_STATUSES = ("pending", "done", "failed")
ERROR_KINDS = ("pronunciation", "grammar", "technical", "fluency", "vocabulary")
SEVERITIES = ("low", "medium", "high")
DRILL_KINDS = ("pron_read", "grammar_rewrite", "tech_explain")


def enum_check(column: str, values: tuple[str, ...]) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=column)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


# --- 5.1 Users and settings -------------------------------------------------


class User(Base):
    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text, unique=True)


class UserSettings(Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        enum_check("feedback_mode", FEEDBACK_MODES),
        enum_check("default_interviewer_style", INTERVIEWER_STYLES),
        enum_check("default_seniority", SENIORITIES),
        enum_check("turn_taking_mode", TURN_TAKING_MODES),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    feedback_mode: Mapped[str] = mapped_column(Text, default="end", server_default="end")
    default_interviewer_style: Mapped[str] = mapped_column(
        Text, default="neutral", server_default="neutral"
    )
    default_seniority: Mapped[str] = mapped_column(Text, default="senior", server_default="senior")
    default_duration_min: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    turn_taking_mode: Mapped[str] = mapped_column(Text, default="auto", server_default="auto")
    end_of_turn_silence_ms: Mapped[int] = mapped_column(
        Integer, default=1500, server_default="1500"
    )
    tts_voice: Mapped[str] = mapped_column(Text, default="af_heart", server_default="af_heart")
    tts_speed: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    phoneme_threshold_k: Mapped[float] = mapped_column(Float, default=2.0, server_default="2.0")


# --- 5.2 Interview context --------------------------------------------------


class Resume(Base):
    __tablename__ = "resumes"

    user_id: Mapped[uuid.UUID] = user_fk()
    file_path: Mapped[str] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text)
    parsed_profile: Mapped[dict[str, Any] | None]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class JobPosting(Base):
    __tablename__ = "job_postings"

    user_id: Mapped[uuid.UUID] = user_fk()
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text)
    parsed: Mapped[dict[str, Any] | None]


# --- 5.3 Sessions and turns -------------------------------------------------


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        enum_check("type", SESSION_TYPES),
        enum_check("seniority", SENIORITIES),
        enum_check("interviewer_style", INTERVIEWER_STYLES),
        enum_check("feedback_mode", FEEDBACK_MODES),
        enum_check("status", SESSION_STATUSES),
    )

    user_id: Mapped[uuid.UUID] = user_fk()
    type: Mapped[str] = mapped_column(Text)
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL")
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL")
    )
    seniority: Mapped[str] = mapped_column(Text)
    interviewer_style: Mapped[str] = mapped_column(Text)
    duration_min: Mapped[int] = mapped_column(Integer)
    feedback_mode: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan: Mapped[dict[str, Any] | None]
    report: Mapped[dict[str, Any] | None]
    scores: Mapped[dict[str, Any] | None]
    coach_messages: Mapped[list[Any] | None]  # AI coach conversation about the report


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        enum_check("role", TURN_ROLES),
        enum_check("analysis_status", ANALYSIS_STATUSES),
        UniqueConstraint("session_id", "idx"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text)
    full_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    spoken_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    interrupted_at_char: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Candidate turns only
    audio_ms: Mapped[int | None] = mapped_column(Integer)
    asr_words: Mapped[list[Any] | None]
    metrics: Mapped[dict[str, Any] | None]
    analysis_status: Mapped[str | None] = mapped_column(Text)


# --- 5.4 Errors -------------------------------------------------------------


class AudioClip(Base):
    __tablename__ = "audio_clips"

    user_id: Mapped[uuid.UUID] = user_fk()
    file_path: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)
    source_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("turns.id", ondelete="SET NULL")
    )
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)


class Error(Base):
    __tablename__ = "errors"
    __table_args__ = (
        enum_check("kind", ERROR_KINDS),
        enum_check("severity", SEVERITIES),
    )

    user_id: Mapped[uuid.UUID] = user_fk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id", ondelete="CASCADE"))
    drill_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drill_attempts.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, index=True)
    severity: Mapped[str] = mapped_column(Text, default="medium", server_default="medium")
    original_text: Mapped[str | None] = mapped_column(Text)
    corrected_text: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    # Pronunciation only
    word: Mapped[str | None] = mapped_column(Text)
    expected_phonemes: Mapped[str | None] = mapped_column(Text)
    heard_phonemes: Mapped[str | None] = mapped_column(Text)
    phoneme_index: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    audio_clip_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("audio_clips.id", ondelete="SET NULL")
    )
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- 5.5 Pronunciation: calibration and variants ----------------------------


class PhonemeCalibration(Base):
    __tablename__ = "phoneme_calibration"
    __table_args__ = (UniqueConstraint("phoneme", "accent"),)

    phoneme: Mapped[str] = mapped_column(Text)
    accent: Mapped[str] = mapped_column(Text, default="en-us", server_default="en-us")
    native_mean: Mapped[float] = mapped_column(Float)
    native_std: Mapped[float] = mapped_column(Float)
    p05: Mapped[float] = mapped_column(Float)
    n_samples: Mapped[int] = mapped_column(Integer)


class UserPhonemeAdjustment(Base):
    __tablename__ = "user_phoneme_adjustments"
    __table_args__ = (
        UniqueConstraint("user_id", "phoneme", "word", postgresql_nulls_not_distinct=True),
    )

    user_id: Mapped[uuid.UUID] = user_fk()
    phoneme: Mapped[str] = mapped_column(Text)
    word: Mapped[str | None] = mapped_column(Text)
    offset: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    dismiss_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    confirm_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AcceptedVariant(Base):
    __tablename__ = "accepted_variants"
    __table_args__ = (
        UniqueConstraint("word", "expected", "accepted", postgresql_nulls_not_distinct=True),
    )

    word: Mapped[str | None] = mapped_column(Text)  # NULL = general rule
    expected: Mapped[str] = mapped_column(Text)
    accepted: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class TechVocabulary(Base):
    __tablename__ = "tech_vocabulary"

    term: Mapped[str] = mapped_column(Text, unique=True)
    phonemes: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text)
    common_mistake_note: Mapped[str | None] = mapped_column(Text)


# --- 5.6 Drills -------------------------------------------------------------


class DrillItem(Base):
    __tablename__ = "drill_items"
    __table_args__ = (enum_check("kind", DRILL_KINDS), UniqueConstraint("user_id", "dedup_key"))

    user_id: Mapped[uuid.UUID] = user_fk()
    # use_alter breaks the errors -> drill_attempts -> drill_items -> errors FK cycle
    source_error_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("errors.id", ondelete="SET NULL", use_alter=True)
    )
    kind: Mapped[str] = mapped_column(Text)
    prompt_text: Mapped[str] = mapped_column(Text)
    target_text: Mapped[str] = mapped_column(Text)
    focus: Mapped[str | None] = mapped_column(Text)
    # one item per category + word/rule; a recurring error reinforces the existing item
    dedup_key: Mapped[str] = mapped_column(Text)
    occurrences: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # SM-2
    ease: Mapped[float] = mapped_column(Float, default=2.5, server_default="2.5")
    interval_days: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    repetitions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lapses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retired: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # consecutive passes reviewed at an interval >= 7 days (3 → retired)
    mature_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class DrillSession(Base):
    __tablename__ = "drill_sessions"

    user_id: Mapped[uuid.UUID] = user_fk()
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any] | None]


class DrillAttempt(Base):
    __tablename__ = "drill_attempts"

    drill_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("drill_sessions.id", ondelete="CASCADE"), index=True
    )
    drill_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("drill_items.id", ondelete="CASCADE"), index=True
    )
    transcript: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)
