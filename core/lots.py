"""FIFO lot matching for sells parsed from the Fidelity Activity CSV.

Pure functions; DB writes happen in jobs/ingest_portfolio.py.

Long-term boundary (IRS): the holding period starts the day after acquisition,
so a sale is long-term only when sold strictly after acquired_at + 1 year.

Wash-sale basis adjustment is phase 2 (PLAN.md §5); realized events recorded
here carry wash_sale=False until that lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta


@dataclass
class OpenLot:
    lot_id: int
    ticker: str
    open_qty: float
    cost_basis: float  # per share
    acquired_at: date


@dataclass
class RealizedSlice:
    lot_id: int
    qty: float
    sold_at: date
    proceeds: float  # total for this slice
    gain: float
    term: str  # 'short' | 'long'


def holding_term(acquired_at: date, sold_at: date) -> str:
    return "long" if sold_at > acquired_at + relativedelta(years=1) else "short"


def match_fifo(
    lots: list[OpenLot], qty: float, sold_at: date, price: float
) -> list[RealizedSlice]:
    """Allocate a sell of `qty` shares across open lots, oldest first.

    Raises if the lots cannot cover the sell — that means the lot records in
    the DB are behind the Activity CSV, and silently continuing would corrupt
    every later tax computation.
    """
    if qty <= 0:
        raise ValueError("sell qty must be positive")
    if price <= 0:
        raise ValueError("sell price must be positive")

    remaining = qty
    slices: list[RealizedSlice] = []
    for lot in sorted(lots, key=lambda l: (l.acquired_at, l.lot_id)):
        if remaining <= 0:
            break
        if lot.open_qty <= 0:
            continue
        take = min(lot.open_qty, remaining)
        proceeds = take * price
        gain = take * (price - lot.cost_basis)
        slices.append(
            RealizedSlice(
                lot_id=lot.lot_id,
                qty=take,
                sold_at=sold_at,
                proceeds=proceeds,
                gain=gain,
                term=holding_term(lot.acquired_at, sold_at),
            )
        )
        remaining -= take

    if remaining > 1e-9:
        raise ValueError(
            f"sell of {qty} exceeds open lots by {remaining}; "
            "seed or ingest the missing lots first"
        )
    return slices
