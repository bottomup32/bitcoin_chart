"""Technical indicator summaries computed in code, not by the LLM.

Agents receive these compact numbers instead of raw price series — cheaper,
deterministic, and it keeps the LLM's job at the judgment layer.

All return math uses our stored adj_close series (PLAN.md §4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date


@dataclass
class Bar:
    trade_date: date
    close: float
    adj_close: float
    volume: int | None


def _ret(bars: list[Bar], n: int) -> float | None:
    """Return over the last n sessions (adj_close), None if not enough data."""
    if len(bars) < n + 1:
        return None
    return bars[-1].adj_close / bars[-1 - n].adj_close - 1.0


def _daily_returns(bars: list[Bar], n: int) -> list[float]:
    tail = bars[-(n + 1):]
    return [b.adj_close / a.adj_close - 1.0 for a, b in zip(tail, tail[1:])]


def realized_vol(bars: list[Bar], n: int = 21) -> float | None:
    """Annualized volatility from the last n daily returns."""
    rets = _daily_returns(bars, n)
    if len(rets) < n:  # a couple of returns would be a garbage estimate
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def summarize_ticker(bars: list[Bar], benchmark: list[Bar]) -> dict:
    """Compact per-ticker snapshot for agent context. bars sorted ascending."""
    if not bars:
        return {}

    def excess(n: int) -> float | None:
        r, b = _ret(bars, n), _ret(benchmark, n)
        return round(r - b, 4) if r is not None and b is not None else None

    highs = [b.adj_close for b in bars[-63:]]
    volumes = [b.volume for b in bars if b.volume]
    vol_ratio = None
    if len(volumes) >= 21:
        recent = sum(volumes[-5:]) / 5
        base = sum(volumes[-21:]) / 21
        vol_ratio = round(recent / base, 2) if base else None

    vol = realized_vol(bars)
    summary = {
        "last_close": round(bars[-1].close, 2),
        "as_of": bars[-1].trade_date.isoformat(),
        "return_5d": _round(_ret(bars, 5)),
        "return_21d": _round(_ret(bars, 21)),
        "return_63d": _round(_ret(bars, 63)),
        "excess_vs_spy_5d": excess(5),
        "excess_vs_spy_21d": excess(21),
        "excess_vs_spy_63d": excess(63),
        "vol_21d_annualized": round(vol, 3) if vol is not None else None,
        "volume_5d_vs_21d": vol_ratio,
        "pct_below_63d_high": _round(bars[-1].adj_close / max(highs) - 1.0) if highs else None,
        "sessions_of_data": len(bars),
    }
    return summary


def _round(x: float | None, digits: int = 4) -> float | None:
    return round(x, digits) if x is not None else None


def correlation_matrix(series: dict[str, list[Bar]], n: int = 63) -> dict[str, dict[str, float]]:
    """Pairwise correlation of daily adj_close returns, aligned by trade_date.

    Feeds the Risk agent's concentration view; pairs with fewer than 20
    overlapping returns are omitted rather than reported on thin data.
    """
    returns: dict[str, dict[date, float]] = {}
    for ticker, bars in series.items():
        tail = bars[-(n + 1):]
        returns[ticker] = {
            b.trade_date: b.adj_close / a.adj_close - 1.0 for a, b in zip(tail, tail[1:])
        }

    tickers = sorted(returns)
    matrix: dict[str, dict[str, float]] = {t: {} for t in tickers}
    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            common = sorted(set(returns[a]) & set(returns[b]))
            if len(common) < 20:
                continue
            xs = [returns[a][d] for d in common]
            ys = [returns[b][d] for d in common]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            vx = sum((x - mx) ** 2 for x in xs)
            vy = sum((y - my) ** 2 for y in ys)
            if vx <= 0 or vy <= 0:
                continue
            corr = round(cov / math.sqrt(vx * vy), 2)
            matrix[a][b] = corr
            matrix[b][a] = corr
    return matrix
