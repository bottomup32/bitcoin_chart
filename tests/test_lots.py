from datetime import date

import pytest

from core.lots import OpenLot, holding_term, match_fifo


def lot(lot_id, qty, basis, acquired):
    return OpenLot(lot_id=lot_id, ticker="AAPL", open_qty=qty, cost_basis=basis,
                   acquired_at=acquired)


def test_holding_term_boundary():
    acquired = date(2025, 3, 10)
    assert holding_term(acquired, date(2025, 9, 1)) == "short"
    # exactly one year later is still short ("more than one year" required)
    assert holding_term(acquired, date(2026, 3, 10)) == "short"
    assert holding_term(acquired, date(2026, 3, 11)) == "long"


def test_fifo_consumes_oldest_first():
    lots = [
        lot(2, 10, 150.0, date(2025, 6, 1)),
        lot(1, 10, 100.0, date(2024, 1, 1)),
    ]
    slices = match_fifo(lots, qty=15, sold_at=date(2026, 3, 1), price=200.0)
    assert [s.lot_id for s in slices] == [1, 2]
    assert slices[0].qty == 10 and slices[1].qty == 5
    assert slices[0].term == "long" and slices[1].term == "short"
    assert slices[0].gain == pytest.approx(10 * 100.0)
    assert slices[1].gain == pytest.approx(5 * 50.0)
    assert sum(s.proceeds for s in slices) == pytest.approx(15 * 200.0)


def test_partial_sell_single_lot():
    slices = match_fifo([lot(1, 10, 100.0, date(2024, 1, 1))],
                        qty=3, sold_at=date(2024, 6, 1), price=90.0)
    assert len(slices) == 1
    assert slices[0].qty == 3
    assert slices[0].gain == pytest.approx(3 * -10.0)
    assert slices[0].term == "short"


def test_oversell_raises():
    with pytest.raises(ValueError, match="exceeds open lots"):
        match_fifo([lot(1, 5, 100.0, date(2024, 1, 1))],
                   qty=6, sold_at=date(2024, 6, 1), price=100.0)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        match_fifo([], qty=0, sold_at=date(2024, 6, 1), price=100.0)
    with pytest.raises(ValueError):
        match_fifo([], qty=1, sold_at=date(2024, 6, 1), price=0.0)
