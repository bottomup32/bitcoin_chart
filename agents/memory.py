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

from core.llm_log import KNOWLEDGE_KEY, LONG_TERM_KEY, SHORT_TERM_KEY
from core.memory import (
    AGENT_HORIZONS,
    DEFAULT_BUDGETS,
    ESTABLISHED_N_EFF,
    assert_as_of,
    compact_recent,
    rank_chunks,
    resolution_counts,
    situation_tags,
    trim_to_budget,
)
from core.scoring import TIMEFRAME_HORIZON

# Agents whose calls are direction-scored, so only these have outcomes to recall.
# risk and tax are excluded from Brier scoring by design (PLAN.md §4) — a tax
# sale is not a market prediction — so they get no short-term outcome memory.
SCORABLE_AGENTS = ("daily_signal", "allocation", "fundamental")

DEFAULT_SESSIONS = 8

# Glosses for the compact `recent` columns — only the ones whose names are not
# self-explanatory. `cols` already carries the field names, and this text ships
# on every call, so anything obvious from the name is pure overhead.
RECENT_FIELD_DOC = (
    "ago=sessions back",
    "excess=return minus SPY",
    "hit=cleared the bar",
    "orch=orchestrator's decision",
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


def knowledge_candidates(cur, tags: set[str]) -> list[dict]:
    """Approved situational chunks whose tags overlap today's market state.

    Filters on `approved` hard: an unreviewed chunk is a permanent daily token
    cost and a permanent bias in every future decision.

    source_score is the source's credibility_prior until that source has enough
    evidence to have earned a learned weight — the gate is n_eff >= 30, which is
    months away per source, and until then shrunk_skill would just return the
    prior anyway.
    """
    if not tags:
        return []
    cur.execute(
        """
        select c.id, c.source_id, c.body, c.tags, c.agents, c.horizons, c.char_len,
               coalesce(w.weight, s.credibility_prior) as source_score
        from knowledge_chunks c
        join sources s on s.id = c.source_id
        left join lateral (
            select weight from source_weights
            where source_id = c.source_id and ticker is null
              and coalesce(n_eff, 0) >= %s
            order by coalesce(as_of_trade_date, effective_from::date) desc limit 1
        ) w on true
        where c.approved and c.layer = 'situational' and c.tags && %s
        """,
        (ESTABLISHED_N_EFF, list(tags)),
    )
    return [
        {"id": r[0], "source_id": r[1], "body": r[2], "tags": r[3], "agents": r[4],
         "horizons": r[5], "char_len": r[6], "source_score": float(r[7])}
        for r in cur.fetchall()
    ]


def chunk_exposure(cur) -> dict[int, int]:
    """How often each chunk has been shown — the exploration counter."""
    cur.execute("select chunk_id, count(*) from opinion_knowledge_refs group by chunk_id")
    return {chunk_id: count for chunk_id, count in cur.fetchall()}


def core_knowledge(cur) -> list[str]:
    """The shared, agent-agnostic principles that go in the system prompt.

    Byte-identical across all four agents, which is what makes a cache_control
    breakpoint worthwhile later: 1.25x once plus 0.1x three times beats 4x. That
    is only wired up once the block clears Sonnet's 1024-token minimum cacheable
    prefix — below it the marker is silently ignored.
    """
    cur.execute(
        "select body from knowledge_chunks where approved and layer = 'core'"
        " order by id"
    )
    return [row[0] for row in cur.fetchall()]


def with_core_knowledge(role_prompt: str, core: list[str]) -> str | list[dict]:
    """Prefix the agent's role prompt with the shared core principles.

    The core block comes FIRST and is byte-identical across agents, so it forms
    a shared prefix. Anything volatile — dates, tickers, per-agent text — must
    sit after it, which is exactly why short-term and long-term memory live in
    the user context dict rather than here: putting them in `system` would
    invalidate the prefix on every call.
    """
    if not core:
        return role_prompt
    principles = "\n".join(f"- {body}" for body in core)
    return [
        {"type": "text",
         "text": "Investment principles this user endorses, which apply to every "
                 f"call you make:\n{principles}"},
        {"type": "text", "text": role_prompt},
    ]


def lesson_rows(cur, agent: str, tickers: list[str], as_of: date) -> list[str]:
    """This agent's durable lessons as they stood on as_of.

    Supersede semantics come free from the as-of ordering: the newest row per
    (agent, ticker) that was knowable on the session. agent_lessons is
    append-only and has no superseded_at column by design — see 0005.
    """
    cur.execute(
        """
        select distinct on (ticker) ticker, body, as_of_trade_date
        from agent_lessons
        where agent = %s
          and (ticker is null or ticker = any(%s))
          and as_of_trade_date <= %s
        order by ticker, as_of_trade_date desc
        """,
        (agent, list(tickers), as_of),
    )
    rows = cur.fetchall()
    assert_as_of(
        [{"as_of": r[2]} for r in rows], as_of, where=f"long_term[{agent}]"
    )
    return [r[1] for r in rows]


def memory_note(memory_block: dict) -> str | None:
    """The one instruction that keeps recall from becoming anchoring.

    Consistency is the point of short-term memory; inertia is its failure mode.
    An agent handed its own prior calls tends to reproduce them, which looks
    like stability on every metric except correctness.
    """
    parts: list[str] = []
    if memory_block.get(SHORT_TERM_KEY):
        parts.append(
            f"`recent` = your own prior calls ({', '.join(RECENT_FIELD_DOC)}); "
            "null excess/hit means that horizon is still open. Context for "
            "consistency, not a commitment — if today's data contradicts a "
            "prior call, change it and say why."
        )
    if LONG_TERM_KEY in memory_block:
        parts.append(
            "`long_term` = lessons from your resolved calls. No entry for a "
            "ticker means no established track record; do not invent one."
        )
    if memory_block.get(KNOWLEDGE_KEY):
        parts.append(
            "`knowledge` = investment principles this user endorses, selected "
            "for today's market state. Apply them to the numbers you were "
            "given, or ignore them if they do not fit. List the `n` of any "
            "principle that actually changed a call in used_knowledge_ids — "
            "leave it empty if none did."
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


def knowledge_budget() -> int:
    raw = os.environ.get("MEMORY_KNOWLEDGE_BUDGET_CHARS", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_BUDGETS[KNOWLEDGE_KEY]


def build_memory(
    cur,
    as_of: date,
    universe: list[str],
    *,
    market: dict | None = None,
    portfolio: dict | None = None,
    correlations: dict | None = None,
    taxes: dict | None = None,
) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Per-agent memory blocks, plus the chunks shown to each agent.

    Returns ({agent: block}, {agent: shown_chunks}). The second value is what
    save_opinions needs to turn an opinion's ordinals back into chunk ids.

    Absent or empty blocks are omitted entirely rather than sent as nulls — an
    empty block costs tokens and teaches nothing.
    """
    if not memory_enabled() or not universe:
        return {}, {}

    session_dates = recent_sessions(cur, as_of, short_term_sessions())
    tags = situation_tags(market or {}, portfolio, correlations, taxes)
    candidates = knowledge_candidates(cur, tags) if market else []
    exposure = chunk_exposure(cur) if candidates else {}

    memory: dict[str, dict] = {}
    shown: dict[str, list[dict]] = {}
    for agent in AGENT_HORIZONS:
        block: dict = {}

        if agent in SCORABLE_AGENTS and session_dates:
            rows = recent_rows(cur, agent, universe, as_of, since=session_dates[-1])
            recent = compact_recent(rows, session_dates)
            if recent:
                block[SHORT_TERM_KEY] = recent
                counts = resolution_counts(rows)
                if counts:
                    block["recent_summary"] = counts

            lessons = lesson_rows(cur, agent, universe, as_of)
            if lessons:
                block[LONG_TERM_KEY] = lessons

        picked = rank_chunks(candidates, tags, agent,
                             budget_chars=knowledge_budget(), exposure=exposure)
        if picked:
            # Local ordinals, not DB ids: fewer tokens, and nothing to
            # hallucinate. save_opinions maps ordinal N back to picked[N-1].
            block[KNOWLEDGE_KEY] = [
                {"n": i, "principle": chunk["body"]}
                for i, chunk in enumerate(picked, start=1)
            ]
            shown[agent] = picked

        if not block:
            continue
        trimmed, dropped = trim_to_budget(block)
        if dropped:
            print(f"memory[{agent}]: dropped over-budget blocks: {','.join(dropped)}")
            if KNOWLEDGE_KEY in dropped:
                shown.pop(agent, None)  # never log an exposure the agent never saw
        if trimmed:
            memory[agent] = trimmed
    return memory, shown
