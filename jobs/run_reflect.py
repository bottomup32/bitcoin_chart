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
from core.scoring import HORIZON_DAYS, TIMEFRAME_HORIZON, ema, shrunk_skill
from db.client import get_conn
from jobs.run_evaluate import (
    MAX_STEP_SMALL_SAMPLE as MAX_STEP,
    MIN_N_EFF,
    SCORABLE_AGENTS,
    WEIGHT_CEIL,
    WEIGHT_FLOOR,
)

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


def update_source_weights(cur, as_of: date) -> int:
    """Learn which endorsed philosophies actually help. Same shape as weights.

    Deliberately mirrors jobs/run_evaluate.py:update_weights and reuses
    core/scoring.py unchanged, so the two learning paths cannot diverge.

    This is statistically hopeless for months and the code should say so: with
    two tickers and roughly two scorable opinions a day, a single source needs
    ~75 sessions to reach n_eff 30 at the 5d horizon. Until then shrunk_skill
    correctly returns the credibility_prior. The plumbing exists so evidence
    accrues; knowledge_candidates() still ignores these weights until the gate
    passes, so nothing here can bias retrieval in the meantime.
    """
    cur.execute(
        """
        select c.source_id, o.ticker, e.brier, e.horizon, e.eval_trade_date,
               s.credibility_prior
        from opinion_knowledge_refs k
        join knowledge_chunks c on c.id = k.chunk_id
        join sources s on s.id = c.source_id
        join agent_opinions o on o.id = k.opinion_id
        join sim_evaluations e on e.opinion_id = o.id
        where k.cited
          and o.agent = any(%s)
          and e.brier is not null
          and e.eval_trade_date is not null
          and e.eval_trade_date <= %s
        """,
        (list(SCORABLE_AGENTS), as_of),
    )
    samples: dict[tuple[int, str | None], list[tuple]] = {}
    for source_id, ticker, brier, horizon, eval_date, prior in cur.fetchall():
        row = (float(brier), horizon, eval_date, float(prior))
        samples.setdefault((source_id, ticker), []).append(row)
        samples.setdefault((source_id, None), []).append(row)  # source-level rollup

    written = 0
    for (source_id, ticker), rows in sorted(
        samples.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
    ):
        prior = rows[0][3]
        frontier_date = max(d for _, _, d, _ in rows)

        cur.execute(
            """
            select weight, sample_n, as_of_trade_date from source_weights
            where source_id = %s and ticker is not distinct from %s
            order by effective_from desc limit 1
            """,
            (source_id, ticker),
        )
        row = cur.fetchone()
        # Unchanged evidence must not move the weight. Without this the EMA
        # creeps toward the posterior a little every run, silently drifting the
        # weight — and writing a row a day — on no new information at all.
        if row is not None and row[1] == len(rows) and row[2] == frontier_date:
            continue

        raw_skill = 1.0 - sum(b for b, _, _, _ in rows) / len(rows)
        n_eff = sum(1.0 / HORIZON_DAYS[h] for _, h, _, _ in rows)
        posterior = shrunk_skill(raw_skill, n_eff, prior_skill=prior)
        previous = float(row[0]) if row else prior

        new = ema(previous, posterior)
        if n_eff < MIN_N_EFF:
            new = max(previous - MAX_STEP, min(previous + MAX_STEP, new))
        new = max(WEIGHT_FLOOR, min(WEIGHT_CEIL, new))

        if row is not None and abs(new - previous) <= 1e-4:
            continue
        cur.execute(
            """
            insert into source_weights
                (source_id, ticker, weight, sample_n, n_eff, as_of_trade_date)
            values (%s, %s, %s, %s, %s, %s)
            """,
            (source_id, ticker, round(new, 4), len(rows), round(n_eff, 2), frontier_date),
        )
        written += 1
    return written


def report_knowledge_exposure(cur) -> None:
    """Per-source exposure and citation rate.

    Both extremes mean the attribution signal is worthless: a citation rate near
    zero means nothing is being attributed, near one means the agents cite
    whatever they are shown. Reported as a rate so either is visible early.
    """
    cur.execute(
        """
        select s.name, count(*) as shown, count(*) filter (where k.cited) as cited,
               max(w.n_eff) as n_eff
        from opinion_knowledge_refs k
        join knowledge_chunks c on c.id = k.chunk_id
        join sources s on s.id = c.source_id
        left join source_weights w on w.source_id = s.id and w.ticker is null
        group by s.name order by s.name
        """
    )
    rows = cur.fetchall()
    if not rows:
        return
    print(f"\n{'source':<32} {'shown':>6} {'cited':>6} {'rate':>6} {'n_eff':>7}")
    for name, shown, cited, n_eff in rows:
        rate = cited / shown if shown else 0.0
        flag = ""
        if shown >= 20 and (rate < 0.02 or rate > 0.98):
            flag = "  <- degenerate citation rate; attribution is uninformative"
        print(f"{name:<32} {shown:>6} {cited:>6} {rate:>6.2f} "
              f"{float(n_eff or 0):>7.1f}{flag}")
    print(f"source weights stay advisory until n_eff >= {MIN_N_EFF}")


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
        sources = update_source_weights(cur, as_of)
        conn.commit()
        print(f"reflect {as_of}: {written} lessons written, "
              f"{considered} (agent, ticker) pairs considered, "
              f"{sources} source weights updated")
        if written == 0 and considered:
            print("no lesson cleared the evidence bar — expected until n_eff builds up")
        report_flip_rates(cur, as_of)
        report_knowledge_exposure(cur)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
