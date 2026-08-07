"""Paper-trading fill sizing (PLAN.md §4). Pure.

The virtual ledger starts as a replica of real holdings; orchestrator
decisions are executed at the NEXT session's open with zero slippage.
Sizing conventions (v1):

- sell → close the whole open position
- trim → close half
- add  → +25% of the current position (or a starter position if none)
- buy  → a starter position of STARTER_PCT of portfolio value
- hold → no trade (still scored via returns, just not a fill)
"""

from __future__ import annotations

STARTER_PCT = 0.05  # new positions start at 5% of portfolio value


def fill_qty(
    action: str,
    open_qty: float,
    portfolio_value: float,
    fill_price: float,
) -> float:
    """Signed share quantity for a paper fill; 0.0 means no trade."""
    if fill_price <= 0:
        raise ValueError("fill_price must be positive")
    if action == "hold":
        return 0.0
    if action == "sell":
        return -open_qty
    if action == "trim":
        return -open_qty / 2
    starter = (portfolio_value * STARTER_PCT) / fill_price if portfolio_value > 0 else 0.0
    if action == "add":
        return open_qty * 0.25 if open_qty > 0 else starter
    if action == "buy":
        return starter if open_qty <= 0 else open_qty * 0.25
    raise ValueError(f"unknown action: {action}")
