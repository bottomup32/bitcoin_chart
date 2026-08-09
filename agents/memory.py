"""Memory builders: SQL that feeds each agent its own past and its lessons.

Mirrors agents/context.py — SQL and code-computed facts here, pure encoding and
budgeting in core/memory.py. Every query is filtered to what was knowable on the
session being advised, so replaying an old session with FORCE_ADVISE=1 produces
the memory it would have had on the day.

Short-term memory needs no new tables: it is a query over agent_opinions,
orchestrator_decisions and sim_evaluations.
"""

from __future__ import annotations

import os
from datetime import date

from core.llm_log import LONG_TERM_KEY, SHORT_TERM_KEY
from core.memory import (
    assert_as_of,
    compact_recent,
    resolution_counts,
    trim_to_budget,
)
from core.scoring import TIMEFRAME_HORIZON

# Agents whose calls are direction-scored, so only these have outcomes to recall.
# risk and tax are excluded from Brier scoring by design (PLAN.md §4) — a tax
# sale is not a market prediction — so they get no short-term outcome memory.
SCORABLE_AGENTS = ("daily_signal", "allocation", "fundamental")

DEFAULT_SESSIONS = 8

# What each column in a compact `recent` row means. Sent once per prompt rather
# than as repeated JSON keys on every row.
RECENT_FIELD_DOC = (
    "ago = sessions ago",
    "dir = your direction",
    "conf = your confidence",
    "tf = timeframe (d/w/m/q)",
    "excess = realized return minus SPY",
    "hit = whether it cleared the bar",
    "orch = what the orchestrator decided",
)

# Built from TIMEFRAME_HORIZON so the mapping has exactly one definition
# (core/scoring.py) and the two learning paths cannot drift apart.
_HORIZON_CASE = "case o.timeframe " + " ".join(
    f"when '{tf}' then '{horizon}'" for tf, horizon in sorted(TIMEFRAME_HORIZON.items())
) + " end"


def memory_enabled() -> bool:
    return os.environ.get("MEMORY_ENABLED", "1").strip().lower() not in ("0", "false", "no")


def short_term_sessions() -> int:
    raw = os.environ.get("MEMORY_SHORT_TERM_SESSIONS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_SESSIONS


def recent_sessions(cur, as_of: date, limit: int) -> list[date]:
    """The last `limit` sessions strictly before as_of, newest first.

    Uses the benchmark's own price rows as the session calendar, the same way
    the rest of the system does — no external calendar lookup at replay time.
    """
    cur.execute(
        """
        select trade_date from prices
        where ticker = 'SPY' and trade_date < %s
        order by trade_date desc limit %s
        """,
        (as_of, limit),
    )
    return [row[0] for row in cur.fetchall()]


def recent_rows(
    cur, agent: str, tickers: list[str], as_of: date, since: date
) -> list[dict]:
    """This agent's own prior calls, with outcomes that had resolved by as_of.

    Four look-ahead points, each a real bug if it slips:

    1. `r.run_date < as_of` STRICTLY. Not <=. On the happy path today's opinion
       does not exist yet, but a FORCE_ADVISE re-run would otherwise let the
       agent read the answer it just gave.
    2. `e.eval_trade_date <= as_of`. sim_evaluations has no created_at to filter
       on, and does not need one: an evaluation whose horizon endpoint is on or
       before as_of derives entirely from adj_close values knowable then.
    3. `e.eval_trade_date is not null` — the column is nullable.
    4. Both evaluation filters live in the LEFT JOIN's ON clause, never in
       WHERE. In WHERE they silently demote the left join to an inner join and
       drop every unresolved call — precisely the open positions the agent most
       needs to see.
    """
    cur.execute(
        f"""
        select o.ticker, r.run_date, o.direction, o.confidence, o.timeframe,
               d.action as orchestrator_action, e.excess_return, e.hit
        from agent_opinions o
        join runs r on r.id = o.run_id
        left join orchestrator_decisions d
               on d.run_id = o.run_id and d.ticker = o.ticker
        left join sim_evaluations e
               on e.opinion_id = o.id
              and e.horizon = {_HORIZON_CASE}
              and e.eval_trade_date is not null
              and e.eval_trade_date <= %s
        where o.agent = %s
          and o.ticker = any(%s)
          and r.run_date < %s
          and r.run_date >= %s
        order by o.ticker, r.run_date desc
        """,
        (as_of, agent, list(tickers), as_of, since),
    )
    rows = [
        {"ticker": r[0], "run_date": r[1], "direction": r[2],
         "confidence": float(r[3]), "timeframe": r[4],
         "orchestrator_action": r[5],
         "excess_return": float(r[6]) if r[6] is not None else None,
         "hit": r[7]}
        for r in cur.fetchall()
    ]
    assert_as_of(rows, as_of, where=f"short_term[{agent}]")
    return rows


def memory_note(memory_block: dict) -> str | None:
    """The one instruction that keeps recall from becoming anchoring.

    Consistency is the point of short-term memory; inertia is its failure mode.
    An agent handed its own prior calls tends to reproduce them, which looks
    like stability on every metric except correctness.
    """
    parts: list[str] = []
    if memory_block.get(SHORT_TERM_KEY):
        parts.append(
            "`recent` lists your own prior calls for these tickers "
            f"[{'; '.join(RECENT_FIELD_DOC)}]. `excess` and `hit` are null while "
            "the horizon is still open. They are context for consistency, not a "
            "commitment — if today's data contradicts a prior call, change it "
            "and say why."
        )
    if LONG_TERM_KEY in memory_block:
        parts.append(
            "`long_term` holds lessons drawn from your resolved calls. A ticker "
            "with no entry means you have no established track record on it; do "
            "not speculate about one."
        )
    return " ".join(parts) or None


def merge(context: dict, memory_block: dict | None) -> dict:
    """Fold a memory block into an agent context, with its reading instruction."""
    if not memory_block:
        return context
    merged = {**context, **memory_block}
    note = memory_note(memory_block)
    if note:
        merged["memory_note"] = note
    return merged


def build_memory(cur, as_of: date, universe: list[str]) -> dict[str, dict]:
    """Per-agent memory blocks, ready to merge into each agent's context.

    Returns {agent_name: block}. Absent or empty blocks are omitted entirely
    rather than sent as nulls — an empty block costs tokens and teaches nothing.
    """
    if not memory_enabled() or not universe:
        return {}

    session_dates = recent_sessions(cur, as_of, short_term_sessions())
    if not session_dates:
        return {}

    memory: dict[str, dict] = {}
    for agent in SCORABLE_AGENTS:
        rows = recent_rows(cur, agent, universe, as_of, since=session_dates[-1])
        recent = compact_recent(rows, session_dates)
        if not recent:
            continue
        block: dict = {SHORT_TERM_KEY: recent}
        counts = resolution_counts(rows)
        if counts:
            block["recent_summary"] = counts
        trimmed, dropped = trim_to_budget(block)
        if dropped:
            print(f"memory[{agent}]: dropped over-budget blocks: {','.join(dropped)}")
        if trimmed:
            memory[agent] = trimmed
    return memory
