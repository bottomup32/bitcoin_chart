"""Parsing tests for the yfinance adapter with a stubbed yfinance module.

Regression: with group_by="ticker" a SINGLE-ticker download still returns a
(ticker, field) MultiIndex on current yfinance — indexing by field alone
raised KeyError and killed the whole batch.
"""

import sys
import types
from datetime import date

import pandas as pd

from adapters.prices import fetch_yfinance

DATES = pd.to_datetime(["2026-08-05", "2026-08-06"])


def _frame(multi: bool, ticker: str = "SPY") -> pd.DataFrame:
    data = {
        "Open": [499.0, 501.0],
        "Close": [500.0, 502.0],
        "Adj Close": [498.0, 500.0],
        "Volume": [1000, 1100],
    }
    df = pd.DataFrame(data, index=DATES)
    if multi:
        df.columns = pd.MultiIndex.from_product([[ticker], df.columns])
    return df


def _stub_yfinance(monkeypatch, frame: pd.DataFrame):
    stub = types.ModuleType("yfinance")
    stub.download = lambda **kwargs: frame
    monkeypatch.setitem(sys.modules, "yfinance", stub)


def test_single_ticker_multiindex_columns(monkeypatch):
    _stub_yfinance(monkeypatch, _frame(multi=True))
    records = fetch_yfinance(["SPY"], date(2026, 8, 5), date(2026, 8, 6))
    assert len(records) == 2
    assert records[-1].ticker == "SPY"
    assert records[-1].close == 502.0
    assert records[-1].adj_close == 500.0
    assert records[-1].open == 501.0


def test_single_ticker_flat_columns(monkeypatch):
    _stub_yfinance(monkeypatch, _frame(multi=False))
    records = fetch_yfinance(["SPY"], date(2026, 8, 5), date(2026, 8, 6))
    assert len(records) == 2


def test_missing_adj_close_falls_back_to_close(monkeypatch):
    frame = _frame(multi=True).drop(columns=[("SPY", "Adj Close")])
    _stub_yfinance(monkeypatch, frame)
    records = fetch_yfinance(["SPY"], date(2026, 8, 5), date(2026, 8, 6))
    assert records[0].adj_close == records[0].close


def test_unknown_ticker_skipped(monkeypatch):
    _stub_yfinance(monkeypatch, _frame(multi=True, ticker="SPY"))
    records = fetch_yfinance(["SPY", "NVDA"], date(2026, 8, 5), date(2026, 8, 6))
    assert {r.ticker for r in records} == {"SPY"}


def test_empty_frame(monkeypatch):
    _stub_yfinance(monkeypatch, pd.DataFrame())
    assert fetch_yfinance(["SPY"], date(2026, 8, 5), date(2026, 8, 6)) == []
