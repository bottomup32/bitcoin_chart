"""NYSE session arithmetic — the single place trade dates come from.

Jobs must never compute ``today()`` themselves: the daily batch runs after the
US close (00:30/01:30 UTC), so the UTC date is already the *next* day. Every
job asks this module for "the most recent completed NYSE session" instead
(PLAN.md §1).
"""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pandas_market_calendars as mcal

_CALENDAR_NAME = "XNYS"

# Give vendors time to settle official closing data before we ingest.
SETTLE_BUFFER = timedelta(minutes=60)


def _calendar():
    return mcal.get_calendar(_CALENDAR_NAME)


def latest_completed_session(now: datetime | None = None) -> date | None:
    """Most recent NYSE session whose close (+ settle buffer) has passed."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    sched = _calendar().schedule(
        start_date=(now - timedelta(days=14)).date(), end_date=now.date()
    )
    if sched.empty:
        return None
    completed = sched[sched["market_close"] + SETTLE_BUFFER <= pd.Timestamp(now)]
    if completed.empty:
        return None
    return completed.index[-1].date()


def sessions_between(start: date, end: date) -> list[date]:
    """All NYSE sessions in [start, end], inclusive."""
    if start > end:
        return []
    sched = _calendar().schedule(start_date=start, end_date=end)
    return [ts.date() for ts in sched.index]


def nth_session_after(d: date, n: int) -> date | None:
    """The n-th NYSE session strictly after d (n >= 1). Used by evaluation."""
    if n < 1:
        raise ValueError("n must be >= 1")
    # 63 trading days ≈ 92 calendar days; pad generously.
    sched = _calendar().schedule(
        start_date=d + timedelta(days=1), end_date=d + timedelta(days=n * 2 + 30)
    )
    if len(sched) < n:
        return None
    return sched.index[n - 1].date()


def is_session(d: date) -> bool:
    return bool(sessions_between(d, d))
