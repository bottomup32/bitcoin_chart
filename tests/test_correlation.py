from datetime import date, timedelta

import pytest

from core.indicators import Bar, correlation_matrix


def bars(prices, start=date(2026, 1, 5)):
    return [Bar(start + timedelta(days=i), p, p, 1000) for i, p in enumerate(prices)]


def test_perfectly_correlated_and_anticorrelated():
    up = [100 + i + (i % 3) for i in range(64)]       # noisy uptrend
    scaled = [2 * p for p in up]                       # same returns → corr 1
    inverted = [10000.0]
    for a, b in zip(up, up[1:]):
        inverted.append(inverted[-1] / (b / a))        # inverse returns → corr -1

    m = correlation_matrix({"A": bars(up), "B": bars(scaled), "C": bars(inverted)})
    assert m["A"]["B"] == pytest.approx(1.0)
    assert m["A"]["C"] == pytest.approx(-1.0)
    assert m["B"]["A"] == m["A"]["B"]  # symmetric


def test_thin_overlap_is_omitted():
    m = correlation_matrix({"A": bars([100 + i for i in range(10)]),
                            "B": bars([100 - i for i in range(10)])})
    assert m == {"A": {}, "B": {}}


def test_flat_series_omitted():
    m = correlation_matrix({"A": bars([100.0] * 64), "B": bars([100 + i for i in range(64)])})
    assert m["A"] == {}
