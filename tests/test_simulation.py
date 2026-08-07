import pytest

from core.simulation import fill_qty


def test_sell_closes_position():
    assert fill_qty("sell", 10, 100_000, 50.0) == -10


def test_trim_halves_position():
    assert fill_qty("trim", 10, 100_000, 50.0) == -5


def test_add_grows_position_by_quarter():
    assert fill_qty("add", 8, 100_000, 50.0) == 2.0


def test_buy_starts_at_5pct_of_portfolio():
    assert fill_qty("buy", 0, 100_000, 50.0) == pytest.approx(100.0)  # 5000/50


def test_add_without_position_uses_starter():
    assert fill_qty("add", 0, 100_000, 50.0) == pytest.approx(100.0)


def test_hold_is_no_trade():
    assert fill_qty("hold", 10, 100_000, 50.0) == 0.0


def test_invalid_inputs():
    with pytest.raises(ValueError):
        fill_qty("sell", 10, 100_000, 0.0)
    with pytest.raises(ValueError):
        fill_qty("yolo", 10, 100_000, 50.0)
