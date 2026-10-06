from datetime import UTC, datetime, timedelta

from api.drills.srs import RELEARN_MINUTES, SrsState, reinforce, review

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def run(results: list[bool]) -> list[tuple[SrsState, datetime]]:
    state, out, now = SrsState(), [], NOW
    for passed in results:
        state, due = review(state, passed, now)
        out.append((state, due))
        now = due  # review exactly when due
    return out


def test_intervals_grow_on_success():
    steps = run([True, True, True, True])
    assert [s.interval_days for s, _ in steps] == [1.0, 3.0, round(3.0 * 2.6, 2), round(7.8 * 2.65, 2)]
    assert steps[0][1] == NOW + timedelta(days=1)
    assert all(s.lapses == 0 for s, _ in steps)


def test_failure_comes_back_soon_and_counts_a_lapse():
    (s1, _), (s2, due2) = run([True, False])
    assert s2.lapses == 1 and s2.repetitions == 0 and s2.interval_days == 0
    assert s2.ease < s1.ease
    assert due2 - (NOW + timedelta(days=1)) == timedelta(minutes=RELEARN_MINUTES)


def test_ease_has_a_floor():
    state = SrsState()
    for _ in range(20):
        state, _ = review(state, False, NOW)
    assert state.ease == 1.3 and state.lapses == 20


def test_retired_after_three_mature_passes():
    steps = run([True] * 6)
    # intervals 1, 3, 7.8, ...: reviews 4, 5, 6 happen after >= 7 days
    assert [s.mature_streak for s, _ in steps] == [0, 0, 0, 1, 2, 3]
    assert [s.retired for s, _ in steps] == [False] * 5 + [True]


def test_failure_resets_the_mature_streak():
    steps = run([True, True, True, True, True, False])
    assert steps[4][0].mature_streak == 2 and steps[5][0].mature_streak == 0


def test_reinforce_unretires():
    state = run([True] * 6)[-1][0]
    again = reinforce(state)
    assert not again.retired and again.repetitions == 0 and again.mature_streak == 0
    assert again.lapses == state.lapses and again.ease == state.ease
