from datetime import date, timedelta

import pytest

from core.indicators import Bar, realized_vol, summarize_ticker


def make_bars(prices, start=date(2026, 1, 5), volume=1000):
    return [
        Bar(trade_date=start + timedelta(days=i), close=p, adj_close=p, volume=volume)
        for i, p in enumerate(prices)
    ]


def test_summarize_returns_and_excess():
    # ticker rises 1%/day for 70 sessions, benchmark is flat
    bars = make_bars([100 * (1.01 ** i) for i in range(70)])
    spy = make_bars([100.0] * 70)
    s = summarize_ticker(bars, spy)
    assert s["return_5d"] == pytest.approx(1.01 ** 5 - 1, abs=1e-4)
    assert s["excess_vs_spy_21d"] == pytest.approx(1.01 ** 21 - 1, abs=1e-4)
    assert s["pct_below_63d_high"] == pytest.approx(0.0)
    assert s["sessions_of_data"] == 70


def test_insufficient_data_yields_nulls_not_errors():
    bars = make_bars([100, 101, 102])
    s = summarize_ticker(bars, bars)
    assert s["return_21d"] is None
    assert s["vol_21d_annualized"] is None
    assert s["last_close"] == 102


def test_flat_series_has_zero_vol():
    bars = make_bars([100.0] * 30)
    assert realized_vol(bars) == pytest.approx(0.0)


def test_empty_bars():
    assert summarize_ticker([], []) == {}
