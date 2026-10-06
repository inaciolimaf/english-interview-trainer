"""Simplified SM-2 spaced repetition (section 11). Pure functions."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

MIN_EASE = 1.3
MAX_EASE = 3.0
RELEARN_MINUTES = 10  # a failed item comes back in the same drill session or the next one
MATURE_DAYS = 7
RETIRE_AFTER = 3  # consecutive passes at intervals >= 7 days


@dataclass(frozen=True)
class SrsState:
    ease: float = 2.5
    interval_days: float = 0.0
    repetitions: int = 0  # consecutive passes
    lapses: int = 0
    mature_streak: int = 0
    retired: bool = False


def review(state: SrsState, passed: bool, now: datetime) -> tuple[SrsState, datetime]:
    """New state and the next due date after one attempt."""
    if not passed:
        new = replace(state, ease=max(MIN_EASE, state.ease - 0.2), interval_days=0.0, repetitions=0,
                      lapses=state.lapses + 1, mature_streak=0)
        return new, now + timedelta(minutes=RELEARN_MINUTES)

    mature = state.interval_days >= MATURE_DAYS  # this review came after a long interval
    repetitions = state.repetitions + 1
    if repetitions == 1:
        interval = 1.0
    elif repetitions == 2:
        interval = 3.0
    else:
        interval = round(state.interval_days * state.ease, 2)
    streak = state.mature_streak + 1 if mature else 0
    new = replace(state, ease=min(MAX_EASE, state.ease + 0.05), interval_days=interval,
                  repetitions=repetitions, mature_streak=streak, retired=streak >= RETIRE_AFTER)
    return new, now + timedelta(days=interval)


def reinforce(state: SrsState) -> SrsState:
    """The same error happened again in an interview: bring the item back, un-retire it."""
    return replace(state, interval_days=0.0, repetitions=0, mature_streak=0, retired=False)
