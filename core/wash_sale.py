"""Wash-sale detection and basis adjustment (PLAN.md §1 [3], §6). Pure functions.

Rules encoded (IRS §1091), all enforced in code — never left to LLM judgment:
- Applies to LOSS sales only. A gain sale never triggers a wash sale.
- Window: 30 days before through 30 days after the sale (61 days, inclusive).
- Replacement shares are matched share-for-share, FIFO by acquisition date,
  across ALL accounts (IRA and spouse accounts included).
- Taxable replacement: the disallowed loss is added to the replacement lot's
  per-share basis and the original holding period tacks on (earlier
  acquired_at wins).
- IRA replacement: the loss is PERMANENTLY disallowed — no basis step-up ever.

v1 limitation: "substantially identical" = same ticker only (does not catch
e.g. two S&P 500 ETFs); replacement candidates are open, not-yet-adjusted lots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

WINDOW_DAYS = 30


@dataclass
class LossSlice:
    """One realized loss slice from a sell (loss_per_share > 0)."""

    source_lot_id: int
    qty: float
    loss_per_share: float
    original_acquired_at: date


@dataclass
class ReplacementBuy:
    """A candidate replacement lot: same ticker, acquired inside the window."""

    lot_id: int
    qty_available: float
    acquired_at: date
    tax_type: str  # 'taxable' | 'ira' | 'other'


@dataclass
class Adjustment:
    """Basis/holding-period adjustment to apply to one replacement lot."""

    replacement_lot_id: int
    qty_matched: float
    basis_increase_per_share: float
    tacked_acquired_at: date


@dataclass
class WashSaleOutcome:
    triggered: bool = False
    disallowed_loss: float = 0.0        # total loss that cannot be claimed now
    permanently_lost: float = 0.0       # portion gone forever (IRA replacement)
    adjustments: list[Adjustment] = field(default_factory=list)


def wash_sale_window(sold_at: date) -> tuple[date, date]:
    return sold_at - timedelta(days=WINDOW_DAYS), sold_at + timedelta(days=WINDOW_DAYS)


def in_window(acquired_at: date, sold_at: date) -> bool:
    start, end = wash_sale_window(sold_at)
    return start <= acquired_at <= end


def evaluate_wash_sale(
    slices: list[LossSlice],
    buys: list[ReplacementBuy],
    sold_at: date,
) -> WashSaleOutcome:
    """Match loss shares against replacement shares, share-for-share FIFO."""
    outcome = WashSaleOutcome()

    loss_slices = [s for s in slices if s.loss_per_share > 0 and s.qty > 0]
    source_ids = {s.source_lot_id for s in loss_slices}
    candidates = sorted(
        (
            b
            for b in buys
            if b.qty_available > 0
            and b.lot_id not in source_ids  # the sold shares are not their own replacement
            and in_window(b.acquired_at, sold_at)
        ),
        key=lambda b: (b.acquired_at, b.lot_id),
    )
    if not loss_slices or not candidates:
        return outcome

    remaining = {b.lot_id: b.qty_available for b in candidates}
    for s in sorted(loss_slices, key=lambda s: (s.original_acquired_at, s.source_lot_id)):
        loss_qty = s.qty
        for buy in candidates:
            if loss_qty <= 0:
                break
            avail = remaining[buy.lot_id]
            if avail <= 0:
                continue
            matched = min(loss_qty, avail)
            remaining[buy.lot_id] -= matched
            loss_qty -= matched

            disallowed = matched * s.loss_per_share
            outcome.triggered = True
            outcome.disallowed_loss += disallowed
            if buy.tax_type == "ira":
                # Replacement inside an IRA: the loss evaporates permanently.
                outcome.permanently_lost += disallowed
            else:
                outcome.adjustments.append(
                    Adjustment(
                        replacement_lot_id=buy.lot_id,
                        qty_matched=matched,
                        basis_increase_per_share=s.loss_per_share,
                        tacked_acquired_at=min(s.original_acquired_at, buy.acquired_at),
                    )
                )
    return outcome
