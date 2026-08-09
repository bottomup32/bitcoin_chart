"""Reflection: distil resolved outcomes into durable lessons (memory plan §4).

Zero LLM calls. The daily "were the predictions right" check already exists —
that is jobs/run_evaluate.py. What was missing is turning its accumulated
output into something an agent can read, which is a template over statistics
the code already computes.

Runs daily rather than weekly because it costs nothing and "write only when the
evidence moved" is a strictly better trigger than a calendar — the same rule
run_evaluate already applies to weights. It appends to agent_lessons only when
the rendered body actually changes, so idle days leave no rows behind.

Position in the workflow: ingest -> advise -> evaluate -> reflect. Its output
feeds TOMORROW's advise. Note that the ordering is a convenience, not the
safety mechanism: the as_of filters are what prevent look-ahead, so a same-day
FORCE_ADVISE re-run after reflect is still correct.
"""

from __future__ import annotations

from datetime import date

from core.memory import flip_rate, lesson_stats, render_lesson
from core.scoring import TIMEFRAME_HORIZON
from db.client import get_conn

SCORABLE_AGENTS = ("daily_signal", "allocation", "fundamental")
MAX_SAMPLE = 200


def frontier(cur) -> date | None:
    """The newest evaluation date — the knowledge frontier lessons may use."""
    cur.execute("select max(eval_trade_date) from sim_evaluations")
    return cur.fetchone()[0]


def evaluations_for(cur, agent: str, as_of: date) -> dict[str | None, list[dict]]:
    """Resolved, timeframe-matching evaluations per ticker, up to as_of.

    Only the horizon matching each opinion's own timeframe is used, mirroring
    the rule that makes Brier meaningful in core/scoring.py — the other horizons
    are diagnostic and would double-count the same call.
    """
    cur.execute(
        """
        select o.ticker, o.direction, o.confidence, o.timeframe,
               e.horizon, e.hit, e.excess_return
        from sim_evaluations e
        join agent_opinions o on o.id = e.opinion_id
        where o.agent = %s
          and e.hit is not null
          and e.eval_trade_date is not null
          and e.eval_trade_date <= %s
        order by e.eval_trade_date desc
        limit %s
        """,
        (agent, as_of, MAX_SAMPLE),
    )
    by_ticker: dict[str | None, list[dict]] = {}
    for ticker, direction, confidence, timeframe, horizon, hit, excess in cur.fetchall():
        if TIMEFRAME_HORIZON.get(timeframe) != horizon:
            continue
        row = {"direction": direction, "confidence": float(confidence),
               "horizon": horizon, "hit": hit,
               "excess_return": float(excess) if excess is not None else None}
        by_ticker.setdefault(ticker, []).append(row)
        by_ticker.setdefault(None, []).append(row)  # agent-level rollup
    return by_ticker


def latest_body(cur, agent: str, ticker: str | None, as_of: date) -> str | None:
    cur.execute(
        """
        select body from agent_lessons
        where agent = %s and ticker is not distinct from %s and as_of_trade_date <= %s
        order by as_of_trade_date desc limit 1
        """,
        (agent, ticker, as_of),
    )
    row = cur.fetchone()
    return row[0] if row else None


def write_lessons(cur, as_of: date) -> tuple[int, int]:
    """Append changed lessons. Returns (written, considered)."""
    import json

    written = considered = 0
    for agent in SCORABLE_AGENTS:
        for ticker, evaluations in evaluations_for(cur, agent, as_of).items():
            considered += 1
            stats = lesson_stats(evaluations)
            body = render_lesson(agent, ticker, stats)
            if body is None:  # below the evidence bar — say nothing at all
                continue
            if body == latest_body(cur, agent, ticker, as_of):
                continue  # evidence did not move; do not accumulate a row a day
            cur.execute(
                """
                insert into agent_lessons
                    (agent, ticker, as_of_trade_date, n, n_eff, tier, stats, body)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (agent, ticker, as_of_trade_date) do update
                    set n = excluded.n, n_eff = excluded.n_eff, tier = excluded.tier,
                        stats = excluded.stats, body = excluded.body
                """,
                (agent, ticker, as_of, stats["n"], stats["n_eff"], stats["tier"],
                 json.dumps(stats), body),
            )
            written += cur.rowcount
    return written, considered


def report_flip_rates(cur, as_of: date) -> None:
    """The anchoring diagnostic — memory's one failure mode that looks like success.

    An agent handed its own prior calls can stop updating and simply repeat
    yesterday. Decisions get more 'consistent' and every other metric improves,
    so this needs its own number watched across the memory rollout.
    """
    for agent in SCORABLE_AGENTS:
        cur.execute(
            """
            select o.ticker, r.run_date, o.direction
            from agent_opinions o join runs r on r.id = o.run_id
            where o.agent = %s and r.run_date <= %s
            order by r.run_date desc limit %s
            """,
            (agent, as_of, MAX_SAMPLE),
        )
        rows = [{"ticker": t, "run_date": d, "direction": x}
                for t, d, x in cur.fetchall()]
        rate = flip_rate(rows)
        if rate is not None:
            print(f"flip_rate[{agent}]: {rate:.2f} over {len(rows)} opinions")


def main() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        as_of = frontier(cur)
        if as_of is None:
            print("no evaluations yet; nothing to reflect on")
            return 0

        written, considered = write_lessons(cur, as_of)
        conn.commit()
        print(f"reflect {as_of}: {written} lessons written, "
              f"{considered} (agent, ticker) pairs considered")
        if written == 0 and considered:
            print("no lesson cleared the evidence bar — expected until n_eff builds up")
        report_flip_rates(cur, as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
