import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import DrillAttempt, DrillItem, DrillSession, Error, User, UserSettings
from api.db.session import get_db
from api.deps import get_current_user
from api.drills.evaluate import evaluate_pron_read, evaluate_rewrite, evaluate_tech
from api.drills.srs import SrsState, review
from api.llm.client import LLMClient, get_llm
from api.pronunciation.pipeline import load_context
from api.realtime.model_client import ModelServerError

router = APIRouter(prefix="/drills")

SESSION_BUDGET_S = 8 * 60  # aim for a 5–10 min session
MAX_ITEMS = 10
ESTIMATED_S = {"pron_read": 45, "grammar_rewrite": 40, "tech_explain": 90}
MAX_AUDIO_BYTES = 70 * 16_000 * 2  # 70 s of 16 kHz PCM16


def item_out(d: DrillItem) -> dict:
    return {
        "id": str(d.id), "kind": d.kind, "prompt_text": d.prompt_text, "target_text": d.target_text,
        "focus": d.focus, "ease": d.ease, "interval_days": d.interval_days, "repetitions": d.repetitions,
        "lapses": d.lapses, "due_at": d.due_at, "retired": d.retired, "occurrences": d.occurrences,
    }


@router.get("/summary")
async def summary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    now = datetime.now(UTC)
    base = select(func.count()).select_from(DrillItem).where(DrillItem.user_id == user.id)
    return {
        "due": await db.scalar(base.where(DrillItem.retired.is_(False), DrillItem.due_at <= now)),
        "active": await db.scalar(base.where(DrillItem.retired.is_(False))),
        "retired": await db.scalar(base.where(DrillItem.retired)),
        "next_due_at": await db.scalar(
            select(func.min(DrillItem.due_at)).where(DrillItem.user_id == user.id, DrillItem.retired.is_(False))
        ),
    }


@router.get("/items")
async def list_items(status: str = "active", user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)) -> list[dict]:
    q = select(DrillItem).where(DrillItem.user_id == user.id)
    if status == "active":
        q = q.where(DrillItem.retired.is_(False))
    elif status == "retired":
        q = q.where(DrillItem.retired)
    return [item_out(d) for d in await db.scalars(q.order_by(DrillItem.due_at))]


def pick_items(due: list[DrillItem]) -> list[DrillItem]:
    """Most lapses first, then most overdue; stop around the time budget."""
    chosen, total = [], 0
    for d in sorted(due, key=lambda d: (-d.lapses, d.due_at)):
        cost = ESTIMATED_S[d.kind]
        if chosen and (total + cost > SESSION_BUDGET_S or len(chosen) >= MAX_ITEMS):
            break
        chosen.append(d)
        total += cost
    return chosen


@router.post("/sessions")
async def start_session(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    due = (await db.scalars(select(DrillItem).where(
        DrillItem.user_id == user.id, DrillItem.retired.is_(False), DrillItem.due_at <= datetime.now(UTC)
    ))).all()
    items = pick_items(list(due))
    session = DrillSession(user_id=user.id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {"id": str(session.id), "started_at": session.started_at, "items": [item_out(d) for d in items],
            "estimated_s": sum(ESTIMATED_S[d.kind] for d in items)}


@router.post("/sessions/{session_id}/attempts")
async def attempt(
    session_id: uuid.UUID, item_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), llm: LLMClient = Depends(get_llm),
) -> dict:
    """Body: the spoken attempt as raw PCM16 mono 16 kHz."""
    session = await db.get(DrillSession, session_id)
    item = await db.get(DrillItem, item_id)
    if session is None or session.user_id != user.id or item is None or item.user_id != user.id:
        raise HTTPException(404, "Drill session or item not found")
    pcm = await request.body()
    if len(pcm) < 16_000 or len(pcm) > MAX_AUDIO_BYTES:
        raise HTTPException(422, "Recording must be between 0.5 and 70 seconds")

    models = request.app.state.models
    try:
        if item.kind == "pron_read":
            settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
            ctx = await load_context(db, user.id, settings.phoneme_threshold_k)
            result = await evaluate_pron_read(item, pcm, models, ctx)
        elif item.kind == "grammar_rewrite":
            result = await evaluate_rewrite(item, pcm, models)
        else:
            result = await evaluate_tech(item, pcm, models, llm)
    except ModelServerError as exc:
        raise HTTPException(503, f"Model server error: {exc}") from exc

    now = datetime.now(UTC)
    state, due = review(SrsState(item.ease, item.interval_days, item.repetitions, item.lapses,
                                 item.mature_streak, item.retired), result.passed, now)
    if item.kind == "pron_read" and item.focus == "suspect":
        if result.passed:  # confirmation drill: read cleanly → the suspicion was a false alarm
            state = SrsState(state.ease, state.interval_days, state.repetitions, state.lapses, state.mature_streak, True)
        elif result.errors:
            item.focus = result.errors[0].phone or result.errors[0].category  # confirmed
    item.ease, item.interval_days, item.repetitions, item.lapses = state.ease, state.interval_days, state.repetitions, state.lapses
    item.mature_streak, item.retired, item.due_at = state.mature_streak, state.retired, due

    record = DrillAttempt(id=uuid.uuid4(), drill_session_id=session.id, drill_item_id=item.id,
                          transcript=result.transcript, score=result.score, passed=result.passed)
    db.add(record)
    await db.flush()
    for c in result.errors:  # drill errors count in the error explorer (no interview session)
        db.add(Error(user_id=user.id, drill_attempt_id=record.id, kind="pronunciation", category=c.category,
                     severity="medium", original_text=c.word, word=c.word, expected_phonemes=c.expected,
                     heard_phonemes=c.heard, phoneme_index=c.phone_index, score=c.score,
                     explanation=f"Drill: in \"{c.word}\" /{c.phone or '+'}/ was not clear."))
    await db.commit()
    return {"passed": result.passed, "score": result.score, "transcript": result.transcript,
            "feedback": result.feedback, "details": result.details, "item": item_out(item)}


@router.post("/sessions/{session_id}/finish")
async def finish_session(session_id: uuid.UUID, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)) -> dict:
    session = await db.get(DrillSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Drill session not found")
    attempts = (await db.scalars(select(DrillAttempt).where(DrillAttempt.drill_session_id == session_id))).all()
    summary_ = {"attempts": len(attempts), "passed": sum(1 for a in attempts if a.passed),
                "items": len({a.drill_item_id for a in attempts})}
    session.ended_at, session.summary = datetime.now(UTC), summary_
    await db.commit()
    return summary_
