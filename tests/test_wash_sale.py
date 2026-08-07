from datetime import date

from core.wash_sale import (
    LossSlice,
    ReplacementBuy,
    evaluate_wash_sale,
    in_window,
    wash_sale_window,
)


def loss(lot_id=1, qty=10, lps=5.0, acquired=date(2025, 1, 10)):
    return LossSlice(source_lot_id=lot_id, qty=qty, loss_per_share=lps,
                     original_acquired_at=acquired)


def buy(lot_id=2, qty=10, acquired=date(2026, 3, 1), tax_type="taxable"):
    return ReplacementBuy(lot_id=lot_id, qty_available=qty, acquired_at=acquired,
                          tax_type=tax_type)


SOLD = date(2026, 3, 10)


def test_window_is_61_days_inclusive():
    start, end = wash_sale_window(SOLD)
    assert (end - start).days == 60
    assert in_window(date(2026, 2, 8), SOLD)      # exactly 30 days before
    assert in_window(date(2026, 4, 9), SOLD)      # exactly 30 days after
    assert not in_window(date(2026, 2, 7), SOLD)
    assert not in_window(date(2026, 4, 10), SOLD)


def test_no_trigger_without_replacement_or_loss():
    assert not evaluate_wash_sale([loss()], [], SOLD).triggered
    assert not evaluate_wash_sale([loss()], [buy(acquired=date(2026, 1, 1))], SOLD).triggered
    # gain slice (loss_per_share <= 0) never triggers
    assert not evaluate_wash_sale([loss(lps=-3.0)], [buy()], SOLD).triggered


def test_sold_lot_is_not_its_own_replacement():
    assert not evaluate_wash_sale([loss(lot_id=7)], [buy(lot_id=7)], SOLD).triggered


def test_taxable_replacement_adjusts_basis_and_tacks():
    out = evaluate_wash_sale([loss(qty=10, lps=5.0)], [buy(qty=10)], SOLD)
    assert out.triggered
    assert out.disallowed_loss == 50.0
    assert out.permanently_lost == 0.0
    [adj] = out.adjustments
    assert adj.qty_matched == 10
    assert adj.basis_increase_per_share == 5.0
    assert adj.tacked_acquired_at == date(2025, 1, 10)  # original earlier date wins


def test_partial_match_limits_disallowed_loss():
    out = evaluate_wash_sale([loss(qty=10, lps=4.0)], [buy(qty=3)], SOLD)
    assert out.disallowed_loss == 12.0
    assert out.adjustments[0].qty_matched == 3


def test_ira_replacement_is_permanent_no_adjustment():
    out = evaluate_wash_sale([loss(qty=10, lps=2.0)], [buy(tax_type="ira")], SOLD)
    assert out.triggered
    assert out.permanently_lost == 20.0
    assert out.adjustments == []


def test_fifo_across_multiple_replacements():
    buys = [
        buy(lot_id=3, qty=4, acquired=date(2026, 3, 5)),
        buy(lot_id=2, qty=4, acquired=date(2026, 2, 20)),  # earlier — consumed first
    ]
    out = evaluate_wash_sale([loss(qty=6, lps=1.0)], buys, SOLD)
    assert [(a.replacement_lot_id, a.qty_matched) for a in out.adjustments] == [(2, 4), (3, 2)]
    assert out.disallowed_loss == 6.0
