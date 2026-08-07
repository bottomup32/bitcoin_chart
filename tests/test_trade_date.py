from datetime import date, datetime, timezone

from core.trade_date import (
    is_session,
    latest_completed_session,
    nth_session_after,
    sessions_between,
)


def utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_after_close_returns_same_day():
    # Tue 2026-01-06 close 16:00 ET = 21:00 UTC; 00:30 UTC next day is past it
    assert latest_completed_session(utc(2026, 1, 7, 0, 30)) == date(2026, 1, 6)


def test_before_close_returns_previous_session():
    # 15:00 UTC = 10:00 ET, market still open → Monday's session is the answer
    assert latest_completed_session(utc(2026, 1, 6, 15, 0)) == date(2026, 1, 5)


def test_settle_buffer_delays_completion():
    # 21:30 UTC is past the 21:00 close but inside the 60-min settle buffer
    assert latest_completed_session(utc(2026, 1, 6, 21, 30)) == date(2026, 1, 5)
    assert latest_completed_session(utc(2026, 1, 6, 22, 30)) == date(2026, 1, 6)


def test_weekend_returns_friday():
    assert latest_completed_session(utc(2026, 1, 4, 12, 0)) == date(2026, 1, 2)


def test_holiday_skipped():
    # 2026-07-03 observes Independence Day (July 4 is a Saturday)
    assert latest_completed_session(utc(2026, 7, 4, 12, 0)) == date(2026, 7, 2)
    assert not is_session(date(2026, 7, 3))


def test_sessions_between_and_nth_after():
    days = sessions_between(date(2026, 1, 5), date(2026, 1, 9))
    assert days == [date(2026, 1, d) for d in (5, 6, 7, 8, 9)]
    # Friday +1 session crosses the weekend to Monday
    assert nth_session_after(date(2026, 1, 9), 1) == date(2026, 1, 12)
    assert nth_session_after(date(2026, 1, 5), 5) == date(2026, 1, 12)
