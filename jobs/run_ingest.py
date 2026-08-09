"""Daily price ingest (GitHub Actions entrypoint).

Flow (PLAN.md §1):
1. Session guard — find the most recent completed NYSE session; exit 0 if the
   calendar says there is nothing new (holiday runs are harmless no-ops).
2. Universe = SPY + tickers with open lots + WATCHLIST env (comma-separated).
3. Per ticker, fetch from the day after its last stored bar (default lookback
   caps the very first backfill); yfinance first, Stooq fallback per ticker.
4. Upsert into `prices` — idempotent, so delayed/duplicate cron slots and
   catch-up after skipped days all resolve themselves.

Logs print counts only — never holdings detail (PLAN.md §6).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta

from adapters.news_rss import SOURCE_NAME as NEWS_SOURCE
from adapters.news_rss import fetch_news
from adapters.prices import PriceRecord, fetch_stooq, fetch_yfinance
from core.trade_date import latest_completed_session, sessions_between
from db.client import get_conn

BENCHMARK = "SPY"
DEFAULT_BACKFILL_DAYS = 45  # calendar days for a ticker's first ingest


def _universe(cur) -> list[str]:
    cur.execute("select distinct ticker from holdings")
    tickers = {row[0] for row in cur.fetchall()}
    tickers.add(BENCHMARK)
    watchlist = os.environ.get("WATCHLIST", "")
    tickers.update(t.strip().upper() for t in watchlist.split(",") if t.strip())
    return sorted(tickers)


def _start_dates(cur, tickers: list[str], session: date, backfill_days: int) -> dict[str, date]:
    cur.execute(
        "select ticker, max(trade_date) from prices where ticker = any(%s) group by ticker",
        (tickers,),
    )
    last = dict(cur.fetchall())
    default_start = session - timedelta(days=backfill_days)
    return {
        t: min(last[t] + timedelta(days=1), session) if t in last else default_start
        for t in tickers
    }


def _upsert_prices(cur, records: list[PriceRecord]) -> int:
    for r in records:
        cur.execute(
            """
            insert into prices (ticker, trade_date, close, adj_close, volume, source, open)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (ticker, trade_date) do update
                set close = excluded.close,
                    adj_close = excluded.adj_close,
                    volume = excluded.volume,
                    source = excluded.source,
                    open = coalesce(excluded.open, prices.open),
                    ingested_at = now()
            """,
            (r.ticker, r.trade_date, r.close, r.adj_close, r.volume, r.source, r.open),
        )
    return len(records)


def _archive(cur, source_name: str, session: date, tickers: list[str], n_rows: int) -> None:
    # The first-class `prices` table is the replayable store; this archive row
    # records the fetch event itself (which source covered what, when).
    cur.execute("select id from sources where name = %s", (source_name,))
    row = cur.fetchone()
    if row is None:
        return
    cur.execute(
        """
        insert into daily_ingest (source_id, ticker, kind, payload, trade_date)
        values (%s, null, 'price', %s, %s)
        """,
        (row[0], json.dumps({"tickers": len(tickers), "rows": n_rows}), session),
    )


def news_enabled() -> bool:
    return os.environ.get("NEWS_ENABLED", "1").strip().lower() not in ("0", "false", "no")


def _ingest_news(cur, conn, tickers: list[str], session: date) -> int:
    """Store per-ticker headlines. Never fails the run — news is optional.

    Separate commit from prices: a feed outage must not roll back a successful
    price ingest, which is the part the rest of the pipeline depends on.
    """
    if not news_enabled():
        return 0
    subjects = [t for t in tickers if t != BENCHMARK]
    if not subjects:
        return 0
    try:
        items, failed = fetch_news(subjects, session)
    except Exception as exc:  # noqa: BLE001
        print(f"news fetch failed ({type(exc).__name__}); continuing without news")
        return 0

    stored = 0
    for item in items:
        cur.execute(
            """
            insert into news_items (ticker, title, summary, url, published_at, source)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (ticker, source, title, published_at) do nothing
            """,
            (item.ticker, item.title, item.summary, item.url,
             item.published_at, NEWS_SOURCE),
        )
        stored += cur.rowcount
    conn.commit()
    print(f"news: {stored} new headlines from {len(items)} items"
          + (f", {len(failed)} tickers failed" if failed else ""))
    return stored


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill-days", type=int, default=DEFAULT_BACKFILL_DAYS)
    args = parser.parse_args()

    session = latest_completed_session()
    if session is None:
        print("no completed NYSE session available; exiting")
        return 0

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into trading_sessions (trade_date, is_open) values (%s, true)
            on conflict (trade_date) do nothing
            """,
            (session,),
        )

        tickers = _universe(cur)
        starts = _start_dates(cur, tickers, session, args.backfill_days)
        pending = {t: s for t, s in starts.items() if s <= session}
        if not pending:
            conn.commit()
            print(f"session {session}: all {len(tickers)} tickers up to date")
            return 0

        fetch_start = min(pending.values())
        try:
            records = fetch_yfinance(sorted(pending), fetch_start, session)
        except Exception as exc:  # noqa: BLE001 — fall through to per-ticker fallback
            print(f"yfinance batch failed ({type(exc).__name__}); using fallback")
            records = []
        records = [r for r in records if r.trade_date >= starts[r.ticker]]

        covered = {r.ticker for r in records if r.trade_date == session}
        missing = [t for t in pending if t not in covered]
        fallback_rows = 0
        for ticker in missing:
            try:
                rows = fetch_stooq(ticker, starts[ticker], session)
            except Exception as exc:  # noqa: BLE001
                print(f"stooq fallback failed for 1 ticker ({type(exc).__name__})")
                continue
            records.extend(rows)
            fallback_rows += len(rows)

        n = _upsert_prices(cur, records)
        _archive(cur, "yfinance", session, sorted(pending), n - fallback_rows)
        if fallback_rows:
            _archive(cur, "stooq", session, missing, fallback_rows)
        conn.commit()

        _ingest_news(cur, conn, tickers, session)

        expected = set(sessions_between(max(fetch_start, session - timedelta(days=7)), session))
        got_today = {r.ticker for r in records if r.trade_date == session}
        still_missing = [t for t in pending if t not in got_today]
        print(
            f"session {session}: upserted {n} rows for {len(pending)} tickers "
            f"({fallback_rows} via fallback); sessions in window: {len(expected)}"
        )
        if still_missing:
            print(f"warning: {len(still_missing)} tickers have no bar for {session}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
