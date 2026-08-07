"""Simulation & learning loop (PLAN.md §4, phases 4-5).

Three passes, all missing-scan driven so delayed or repeated runs
self-heal — no date arithmetic against "today":

1. Paper fills: every non-hold decision without a sim_trade whose NEXT session
   has an ingested open price gets filled there (zero slippage, PLAN.md §4).
2. Scoring: every scorable opinion (daily_signal/allocation/fundamental) and
   every decision gets one sim_evaluations row per horizon (1d/5d/21d/63d)
   as soon as the horizon's session exists in our own adj_close series.
   Brier feeds only the horizon matching the opinion's timeframe.
3. Weights: per-agent Brier → n_eff-shrunk posterior → EMA, appended to
   agent_weights (never overwritten). Small samples move weights slowly and
   changes are capped until n_eff >= 30.

The SPY series doubles as the session calendar and the benchmark, so scoring
only ever sees data run_ingest actually stored (PLAN.md §0: no external
re-fetch at evaluation time).
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import date

from core.scoring import (
    HORIZON_DAYS,
    TIMEFRAME_HORIZON,
    brier,
    direction_hit,
    ema,
    excess_return,
    shrunk_skill,
    simple_return,
)
from core.simulation import fill_qty
from db.client import get_conn

SCORABLE_AGENTS = ("daily_signal", "allocation", "fundamental")
DEFAULT_WEIGHT = 0.5
MAX_SAMPLE = 200
MIN_N_EFF = 30
MAX_STEP_SMALL_SAMPLE = 0.05
WEIGHT_FLOOR, WEIGHT_CEIL = 0.05, 0.95


def _calendar(cur) -> tuple[list[date], dict[date, float]]:
    cur.execute(
        "select trade_date, adj_close from prices where ticker = 'SPY' order by trade_date"
    )
    rows = cur.fetchall()
    return [r[0] for r in rows], {r[0]: float(r[1]) for r in rows}


def _adj_series(cur, ticker: str, cache: dict) -> dict[date, float]:
    if ticker not in cache:
        cur.execute(
            "select trade_date, adj_close from prices where ticker = %s", (ticker,)
        )
        cache[ticker] = {r[0]: float(r[1]) for r in cur.fetchall()}
    return cache[ticker]


def _nth_session(dates: list[date], start: date, n: int) -> date | None:
    idx = bisect_left(dates, start)
    if idx >= len(dates) or dates[idx] != start:
        return None  # start wasn't a session we have data for
    return dates[idx + n] if idx + n < len(dates) else None


def paper_fills(cur, dates: list[date]) -> int:
    cur.execute(
        """
        select d.id, d.ticker, d.action, r.run_date
        from orchestrator_decisions d
        join runs r on r.id = d.run_id
        left join sim_trades t on t.decision_id = d.id
        where t.id is null and d.action <> 'hold'
        """
    )
    pending = cur.fetchall()
    if not pending:
        return 0

    cur.execute(
        """
        select agg.ticker, agg.qty, agg.qty * p.close
        from (select ticker, sum(qty) qty from holdings group by ticker) agg
        left join lateral (
            select close from prices where prices.ticker = agg.ticker
            order by trade_date desc limit 1
        ) p on true
        """
    )
    open_qty: dict[str, float] = {}
    portfolio_value = 0.0
    for ticker, qty, value in cur.fetchall():
        open_qty[ticker] = float(qty)
        portfolio_value += float(value or 0)

    filled = 0
    for decision_id, ticker, action, run_date in pending:
        fill_date = _nth_session(dates, run_date, 1)
        if fill_date is None:
            continue
        cur.execute(
            "select open from prices where ticker = %s and trade_date = %s and open is not null",
            (ticker, fill_date),
        )
        row = cur.fetchone()
        if row is None:
            continue
        price = float(row[0])
        qty = fill_qty(action, open_qty.get(ticker, 0.0), portfolio_value, price)
        if qty == 0.0:
            continue
        cur.execute(
            """
            insert into sim_trades (decision_id, fill_date, fill_price, qty)
            values (%s, %s, %s, %s) on conflict (decision_id) do nothing
            """,
            (decision_id, fill_date, price, qty),
        )
        filled += cur.rowcount
    return filled


def _score_rows(cur, dates, spy_adj, rows, kind: str) -> int:
    """rows: (id, ticker, direction, confidence, timeframe|None, run_date)."""
    col = "opinion_id" if kind == "opinion" else "decision_id"
    cur.execute(f"select {col}, horizon from sim_evaluations where {col} is not null")
    done = set(cur.fetchall())

    adj_cache: dict[str, dict[date, float]] = {}
    inserted = 0
    for row_id, ticker, direction, confidence, timeframe, run_date in rows:
        series = _adj_series(cur, ticker, adj_cache)
        start_adj = series.get(run_date)
        start_spy = spy_adj.get(run_date)
        if start_adj is None or start_spy is None:
            continue
        for label, h in HORIZON_DAYS.items():
            if (row_id, label) in done:
                continue
            eval_date = _nth_session(dates, run_date, h)
            if eval_date is None or eval_date not in series:
                continue
            actual = simple_return(start_adj, series[eval_date])
            bench = simple_return(start_spy, spy_adj[eval_date])
            excess = excess_return(actual, bench)
            hit = direction_hit(direction, excess, h)
            score = None
            if kind == "opinion" and timeframe and TIMEFRAME_HORIZON.get(timeframe) == label:
                score = brier(float(confidence), hit)
            cur.execute(
                f"""
                insert into sim_evaluations
                    ({col}, horizon, eval_trade_date, actual_return,
                     benchmark_return, excess_return, brier, hit, status)
                values (%s, %s, %s, %s, %s, %s, %s, %s, 'scored')
                on conflict do nothing
                """,
                (row_id, label, eval_date, actual, bench, excess, score, hit),
            )
            inserted += cur.rowcount
    return inserted


def score_opinions(cur, dates, spy_adj) -> int:
    cur.execute(
        """
        select o.id, o.ticker, o.direction, o.confidence, o.timeframe, r.run_date
        from agent_opinions o join runs r on r.id = o.run_id
        where o.agent = any(%s)
        """,
        (list(SCORABLE_AGENTS),),
    )
    return _score_rows(cur, dates, spy_adj, cur.fetchall(), "opinion")


def score_decisions(cur, dates, spy_adj) -> int:
    cur.execute(
        """
        select d.id, d.ticker, d.action, d.confidence, null, r.run_date
        from orchestrator_decisions d join runs r on r.id = d.run_id
        """
    )
    return _score_rows(cur, dates, spy_adj, cur.fetchall(), "decision")


def update_weights(cur) -> int:
    updated = 0
    for agent in SCORABLE_AGENTS:
        cur.execute(
            """
            select e.brier, e.horizon
            from sim_evaluations e
            join agent_opinions o on o.id = e.opinion_id
            where o.agent = %s and e.brier is not null
            order by e.eval_trade_date desc
            limit %s
            """,
            (agent, MAX_SAMPLE),
        )
        rows = cur.fetchall()
        if not rows:
            continue
        briers = [float(b) for b, _ in rows]
        raw_skill = 1.0 - sum(briers) / len(briers)
        n_eff = sum(1.0 / HORIZON_DAYS[h] for _, h in rows)
        posterior = shrunk_skill(raw_skill, n_eff)

        cur.execute(
            """
            select weight from agent_weights where agent = %s
            order by effective_from desc limit 1
            """,
            (agent,),
        )
        row = cur.fetchone()
        previous = float(row[0]) if row else DEFAULT_WEIGHT

        new = ema(previous, posterior)
        if n_eff < MIN_N_EFF:  # small samples may only nudge the weight
            new = max(previous - MAX_STEP_SMALL_SAMPLE, min(previous + MAX_STEP_SMALL_SAMPLE, new))
        new = max(WEIGHT_FLOOR, min(WEIGHT_CEIL, new))

        if row is None or abs(new - previous) > 1e-4:
            cur.execute(
                """
                insert into agent_weights (agent, weight, sample_n, n_eff)
                values (%s, %s, %s, %s)
                """,
                (agent, round(new, 4), len(rows), round(n_eff, 2)),
            )
            updated += 1
    return updated


def main() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        dates, spy_adj = _calendar(cur)
        if len(dates) < 2:
            print("not enough SPY history to evaluate; run run_ingest first")
            return 0
        fills = paper_fills(cur, dates)
        n_op = score_opinions(cur, dates, spy_adj)
        n_dec = score_decisions(cur, dates, spy_adj)
        # Weights move only on new evidence — re-running the EMA on the same
        # sample every day would silently drift weights without data.
        n_w = update_weights(cur) if n_op else 0
        conn.commit()
        print(
            f"evaluate: {fills} paper fills, {n_op} opinion evals, "
            f"{n_dec} decision evals, {n_w} weight updates"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
