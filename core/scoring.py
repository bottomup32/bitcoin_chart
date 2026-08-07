"""Scoring & weight-update math (PLAN.md §4). Pure functions, fully unit-tested.

Definitions fixed in phase 1 so every later layer builds on the same contract:

- returns are computed from our own stored adj_close series only
- hit is benchmark-relative: excess = asset return − SPY return
- hold uses a horizon-scaled band (a flat ±1% makes hold near-impossible at 21d)
- Brier feeds the weight update only on the horizon matching the opinion's
  timeframe; other horizons are diagnostic
- overlapping evaluation windows inflate n, so shrinkage uses n_eff = n / h
"""

from __future__ import annotations

import math

HORIZON_DAYS = {"1d": 1, "5d": 5, "21d": 21, "63d": 63}

# The one horizon whose Brier feeds this timeframe's weight update.
TIMEFRAME_HORIZON = {"days": "5d", "weeks": "5d", "months": "21d", "quarters": "63d"}

HOLD_BAND_BASE = 0.01  # ±1% at a 1-day horizon


def simple_return(start_price: float, end_price: float) -> float:
    if start_price <= 0:
        raise ValueError("start_price must be positive")
    return end_price / start_price - 1.0


def excess_return(asset_return: float, benchmark_return: float) -> float:
    return asset_return - benchmark_return


def hold_band(horizon_days: int, base: float = HOLD_BAND_BASE) -> float:
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    return base * math.sqrt(horizon_days)


def direction_hit(direction: str, excess: float, horizon_days: int) -> bool:
    """Did the call beat its benchmark-relative bar over this horizon?"""
    if direction in ("buy", "add"):
        return excess > 0
    if direction in ("sell", "trim"):
        return excess < 0
    if direction == "hold":
        return abs(excess) < hold_band(horizon_days)
    raise ValueError(f"unknown direction: {direction}")


def brier(confidence: float, hit: bool) -> float:
    """(confidence − outcome)²; lower is better. Requires confidence in [0, 1]."""
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be in [0, 1]")
    return (confidence - (1.0 if hit else 0.0)) ** 2


def n_effective(n: int, horizon_days: int) -> float:
    """Correct for overlapping windows: daily decisions scored at h days
    overlap ~h-fold, so they are not independent samples."""
    if n < 0:
        raise ValueError("n must be >= 0")
    return n / horizon_days


def shrunk_skill(
    raw_skill: float,
    n_eff: float,
    prior_skill: float = 0.5,
    prior_n: float = 30.0,
) -> float:
    """Bayesian shrinkage toward the prior; small samples barely move it."""
    if n_eff < 0:
        raise ValueError("n_eff must be >= 0")
    return (prior_n * prior_skill + n_eff * raw_skill) / (prior_n + n_eff)


def ema(previous: float, observation: float, alpha: float = 0.1) -> float:
    if not 0.0 < alpha <= 1.0:
        raise ValueError("alpha must be in (0, 1]")
    return (1.0 - alpha) * previous + alpha * observation
