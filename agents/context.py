"""Context builders: SQL + code-computed facts handed to each agent.

Everything numeric is computed here (or in core/), so agents reason over
verified inputs instead of computing — and wash-sale facts in particular come
from core/wash_sale.py, never from the model (PLAN.md §1 [3]).
"""

from __future__ import annotations

from datetime import date, timedelta

from core.indicators import Bar, summarize_ticker
from core.wash_sale import WINDOW_DAYS

BENCHMARK = "SPY"
HISTORY_SESSIONS = 70


def _bars(cur, ticker: str) -> list[Bar]:
    cur.execute(
        """
        select trade_date, close, adj_close, volume
        from prices where ticker = %s
        order by trade_date desc limit %s
        """,
        (ticker, HISTORY_SESSIONS),
    )
    rows = cur.fetchall()[::-1]
    return [Bar(r[0], float(r[1]), float(r[2]), r[3]) for r in rows]


def market_context(cur, tickers: list[str]) -> dict:
    spy = _bars(cur, BENCHMARK)
    return {
        "benchmark": {"ticker": BENCHMARK, **summarize_ticker(spy, spy)},
        "tickers": {t: summarize_ticker(_bars(cur, t), spy) for t in tickers},
    }


def portfolio_context(cur) -> dict:
    cur.execute(
        """
        select agg.ticker, agg.qty, agg.avg_cost, p.close
        from (
            select ticker, sum(qty) as qty,
                   sum(qty * avg_cost) / nullif(sum(qty), 0) as avg_cost
            from holdings
            group by ticker
        ) agg
        left join lateral (
            select close from prices
            where prices.ticker = agg.ticker
            order by trade_date desc limit 1
        ) p on true
        """
    )
    rows = cur.fetchall()
    positions = []
    total = 0.0
    for ticker, qty, avg_cost, close in rows:
        value = float(qty) * float(close) if close else None
        if value:
            total += value
        positions.append(
            {"ticker": ticker, "qty": float(qty), "avg_cost": round(float(avg_cost), 2),
             "market_value": round(value, 2) if value else None}
        )
    for p in positions:
        p["weight_pct"] = round(p["market_value"] / total * 100, 1) if p["market_value"] and total else None
    return {"total_value": round(total, 2), "positions": positions}


def correlation_context(cur, tickers: list[str]) -> dict:
    from core.indicators import correlation_matrix

    return correlation_matrix({t: _bars(cur, t) for t in tickers})


def tax_context(cur) -> dict:
    cur.execute(
        """
        select t.ticker, t.lot_id, t.open_qty, t.cost_basis, t.acquired_at,
               t.days_to_longterm, t.unrealized_pnl, a.tax_type
        from tax_status t join accounts a on a.id = t.account_id
        order by t.ticker, t.acquired_at
        """
    )
    lots = [
        {"ticker": r[0], "lot_id": r[1], "open_qty": float(r[2]),
         "cost_basis": round(float(r[3]), 2), "acquired_at": r[4].isoformat(),
         "days_to_longterm": int(r[5]),
         "unrealized_pnl": round(float(r[6]), 2) if r[6] is not None else None,
         "account_tax_type": r[7]}
        for r in cur.fetchall()
    ]

    year_start = date.today().replace(month=1, day=1)
    cur.execute(
        """
        select term, coalesce(sum(gain), 0)
        from realized_events where sold_at >= %s group by term
        """,
        (year_start,),
    )
    realized = {term: round(float(g), 2) for term, g in cur.fetchall()}

    # Code-level wash-sale exposure: selling any of these tickers at a loss
    # today would trigger §1091, because shares were bought inside the window.
    cur.execute(
        """
        select distinct l.ticker,
               bool_or(a.tax_type = 'ira') as ira_buy
        from tax_lots l join accounts a on a.id = l.account_id
        where l.acquired_at >= %s
        group by l.ticker
        """,
        (date.today() - timedelta(days=WINDOW_DAYS),),
    )
    wash_risk = {
        t: ("PERMANENT loss disallowance risk — recent IRA purchase" if ira
            else "wash sale if sold at a loss now (recent purchase in window)")
        for t, ira in cur.fetchall()
    }

    return {
        "lots": lots,
        "realized_ytd": {"short": realized.get("short", 0.0), "long": realized.get("long", 0.0)},
        "wash_sale_risk": wash_risk,
        "rule_notes": (
            "Long-term = held MORE than 1 year. days_to_longterm counts days until a sale "
            "would qualify as long-term. wash_sale_risk is computed by code from actual "
            "trades — cite it as given; never assert wash-sale conclusions of your own. "
            "realized_ytd sums raw gains; losses from already-flagged wash sales may be "
            "partially disallowed for tax purposes."
        ),
    }
