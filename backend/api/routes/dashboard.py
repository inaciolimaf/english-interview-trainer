"""Progress dashboard (section 12). Single-user data volumes: aggregate in Python."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import DrillItem, Error, InterviewSession, Turn, User
from api.db.session import get_db
from api.deps import get_current_user
from api.routes.drills import summary as drill_summary
from api.routes.errors import dismissed_phone

router = APIRouter()

SERIES = ("pronunciation_accuracy", "grammar_per_100_words", "overall", "wpm", "fillers_per_min")
TOP_WINDOW = timedelta(days=30)
OVERCOME_DROP = 0.6  # rate fell by at least 60%
OVERCOME_MIN_BEFORE = 3  # errors in the earlier window
HEATMAP_WINDOW = timedelta(days=90)


def _avg(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(mean(vals), 2) if vals else None


def _rate(count: int, words: int) -> float:
    return 100 * count / words if words else 0.0


def trend(recent: float, before: float) -> str:
    if before == 0:
        return "new" if recent > 0 else "flat"
    change = (recent - before) / before
    return "up" if change > 0.15 else "down" if change < -0.15 else "flat"


@router.get("/dashboard")
async def dashboard(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    now = datetime.now(UTC)
    sessions = (await db.scalars(
        select(InterviewSession).where(InterviewSession.user_id == user.id).order_by(InterviewSession.started_at)
    )).all()
    scored = [s for s in sessions if s.scores]

    timeline = [{
        "session_id": str(s.id), "date": s.started_at.isoformat(), "type": s.type,
        **{k: (s.scores or {}).get(k) for k in SERIES}, "rubric": (s.scores or {}).get("rubric", {}),
    } for s in scored]

    weeks: dict[str, list[InterviewSession]] = defaultdict(list)
    for s in scored:
        iso = s.started_at.isocalendar()
        weeks[f"{iso.year}-W{iso.week:02d}"].append(s)
    weekly = [{"week": w, "sessions": len(ss), **{k: _avg([(s.scores or {}).get(k) for s in ss]) for k in SERIES}}
              for w, ss in sorted(weeks.items())]

    # words spoken per day window (denominator for error rates)
    turns = (await db.execute(
        select(Turn.metrics, Turn.started_at).join(InterviewSession, Turn.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == user.id, Turn.role == "candidate", Turn.started_at >= now - max(2 * TOP_WINDOW, HEATMAP_WINDOW))
    )).all()

    def words_between(start: datetime, end: datetime) -> int:
        return sum((m or {}).get("words", 0) for m, t in turns if t and start <= t < end)

    errors = (await db.scalars(
        select(Error).where(Error.user_id == user.id, Error.session_id.is_not(None), Error.dismissed.is_(False),
                            Error.category != "pron:suspect", Error.created_at >= now - 2 * TOP_WINDOW)
    )).all()
    half = TOP_WINDOW / 2
    recent30 = Counter(e.category for e in errors if e.created_at >= now - TOP_WINDOW)
    last15 = Counter(e.category for e in errors if e.created_at >= now - half)
    prev15 = Counter(e.category for e in errors if now - TOP_WINDOW <= e.created_at < now - half)
    w_last15, w_prev15 = words_between(now - half, now), words_between(now - TOP_WINDOW, now - half)
    top = [{
        "category": cat, "count": n,
        "trend": trend(_rate(last15[cat], w_last15), _rate(prev15[cat], w_prev15)),
        "recent_per_100_words": round(_rate(last15[cat], w_last15), 2),
        "before_per_100_words": round(_rate(prev15[cat], w_prev15), 2),
    } for cat, n in recent30.most_common(5)]

    before30 = Counter(e.category for e in errors if e.created_at < now - TOP_WINDOW)
    w_recent, w_before = words_between(now - TOP_WINDOW, now), words_between(now - 2 * TOP_WINDOW, now - TOP_WINDOW)
    overcome = []
    for cat, n in before30.items():
        r_before, r_now = _rate(n, w_before), _rate(recent30[cat], w_recent)
        if n >= OVERCOME_MIN_BEFORE and r_before and r_now <= (1 - OVERCOME_DROP) * r_before:
            overcome.append({"category": cat, "before_per_100_words": round(r_before, 2),
                             "recent_per_100_words": round(r_now, 2)})
    retired = (await db.scalars(
        select(DrillItem).where(DrillItem.user_id == user.id, DrillItem.retired).order_by(DrillItem.updated_at.desc()).limit(20)
    )).all()

    occurrences: Counter = Counter()
    for m, t in turns:
        if t and t >= now - HEATMAP_WINDOW:
            occurrences.update((m or {}).get("phone_counts", {}))
    phone_errors = Counter(
        p for e in errors if e.kind == "pronunciation" and e.created_at >= now - HEATMAP_WINDOW
        and (p := dismissed_phone(e)) and p != "+"
    )
    phonemes = sorted(
        ({"phoneme": p, "occurrences": occurrences[p], "errors": phone_errors[p],
          "error_rate": round(phone_errors[p] / occurrences[p], 4)} for p in occurrences if occurrences[p] >= 5),
        key=lambda x: -x["error_rate"],
    )

    return {
        "sessions": timeline,
        "weekly": weekly,
        "top_errors": top,
        "overcome": {"categories": overcome,
                     "retired_drills": [{"id": str(d.id), "kind": d.kind, "focus": d.focus,
                                         "prompt_text": d.prompt_text} for d in retired]},
        "phonemes": phonemes,
        "drills": await drill_summary(user, db),
        "recent_sessions": [{"id": str(s.id), "type": s.type, "status": s.status,
                             "started_at": s.started_at.isoformat(), "has_report": s.report is not None,
                             "overall": (s.scores or {}).get("overall")} for s in reversed(sessions[-10:])],
    }
