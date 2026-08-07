"""Price adapters: yfinance primary, Stooq fallback (PLAN.md §1 [1]).

Both return the same PriceRecord shape; the ingest job upserts them into the
first-class `prices` table. Evaluation only ever reads that table, so a
retroactive re-adjustment upstream cannot silently rewrite past scores.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta

import requests


@dataclass
class PriceRecord:
    ticker: str
    trade_date: date
    close: float
    adj_close: float
    volume: int | None
    source: str


def fetch_yfinance(tickers: list[str], start: date, end: date) -> list[PriceRecord]:
    """Daily bars for [start, end] inclusive via yfinance (version pinned)."""
    import yfinance as yf

    if not tickers:
        return []
    df = yf.download(
        tickers=list(tickers),
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
        auto_adjust=False,
        actions=False,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    if df is None or df.empty:
        return []

    records: list[PriceRecord] = []
    for ticker in tickers:
        try:
            sub = df[ticker] if len(tickers) > 1 else df
        except KeyError:
            continue
        sub = sub.dropna(subset=["Close", "Adj Close"])
        for ts, row in sub.iterrows():
            close = float(row["Close"])
            adj_close = float(row["Adj Close"])
            if close <= 0 or adj_close <= 0:
                continue
            volume = row.get("Volume")
            records.append(
                PriceRecord(
                    ticker=ticker,
                    trade_date=ts.date(),
                    close=close,
                    adj_close=adj_close,
                    volume=int(volume) if volume == volume else None,  # NaN guard
                    source="yfinance",
                )
            )
    return records


def fetch_stooq(ticker: str, start: date, end: date) -> list[PriceRecord]:
    """Fallback: Stooq daily CSV for one US ticker.

    Stooq's close is split-adjusted but not dividend-adjusted, so adj_close is
    an approximation here — acceptable for a fallback, flagged via source.
    """
    url = (
        "https://stooq.com/q/d/l/"
        f"?s={ticker.lower()}.us&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    body = resp.text.strip()
    if not body or body.lower().startswith("no data"):
        return []

    records: list[PriceRecord] = []
    for row in csv.DictReader(io.StringIO(body)):
        try:
            trade_date = date.fromisoformat(row["Date"])
            close = float(row["Close"])
        except (KeyError, ValueError):
            continue
        if close <= 0:
            continue
        volume_raw = row.get("Volume", "")
        records.append(
            PriceRecord(
                ticker=ticker,
                trade_date=trade_date,
                close=close,
                adj_close=close,
                volume=int(float(volume_raw)) if volume_raw not in ("", None) else None,
                source="stooq",
            )
        )
    return records
