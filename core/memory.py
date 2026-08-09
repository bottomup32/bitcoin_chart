"""Pure memory functions: encoding, budgeting, and the look-ahead guard.

Everything here is a pure function of code-computed state, in the same spirit as
core/indicators.py and core/conflict_rules.py — statistics and selection happen
in code, the LLM only judges. That keeps memory retrieval auditable, replayable
and testable without a database.

Two rules run through the whole module:

1. Nothing derived from a date later than the session's own trade date may ever
   reach a prompt. assert_as_of() enforces it at runtime, because the SQL that
   feeds these functions is the risky surface and it has no DB tests.
2. Agents see OUTCOMES, never SCORES. Brier is a proper scoring rule only while
   the agent is trying to be accurate rather than trying to look calibrated;
   showing it the metric turns it into a target (agents/base.py:28-34).
"""

from __future__ import annotations

from datetime import date, datetime

from core.llm_log import SHORT_TERM_KEY

# Short-term memory columns, in the order they appear in each compact row.
RECENT_COLS = ("ago", "dir", "conf", "tf", "excess", "hit", "orch")

# timeframe → the single letter used in compact rows, to save tokens.
TIMEFRAME_CODE = {"days": "d", "weeks": "w", "months": "m", "quarters": "q"}

# Hard caps, in serialized characters. Roughly 4 chars/token for prose and ~3
# for this date- and digit-heavy JSON, so these sit a little under the token
# budgets in the plan. Trim order matters — see trim_to_budget.
DEFAULT_BUDGETS = {
    "knowledge": 1200,
    "recent": 1000,
    "long_term": 600,
}

# Knowledge is the largest and most speculative block; long-term is usually
# empty (below the evidence gate) and high-evidence when present; short-term is
# the cheapest per unit of decision relevance and is the entire anti-whipsaw
# mechanism. So sacrifice them in that order.
TRIM_ORDER = ("knowledge", "long_term", SHORT_TERM_KEY)


class LookAheadError(AssertionError):
    """Raised when memory would hand an agent information from the future."""


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def assert_as_of(rows, as_of: date, *, where: str = "memory") -> None:
    """Fail loudly if any row carries a date after the session being advised.

    A belt-and-braces runtime guard rather than a test-only invariant: the date
    filters live in hand-written SQL, and the classic mistake (putting the
    eval_trade_date filter in WHERE instead of the LEFT JOIN's ON clause) fails
    silently in the other direction. This catches the loud direction.
    """
    for row in rows:
        values = row.values() if isinstance(row, dict) else row
        for value in values:
            day = _as_date(value)
            if day is not None and day > as_of:
                raise LookAheadError(
                    f"{where}: row carries {day}, which is after the session {as_of}"
                )


def sessions_ago(session_dates: list[date], run_date: date) -> int | None:
    """How many completed sessions back run_date sits, counting from the newest.

    Cheaper than an ISO date in the prompt (one small integer versus ten
    characters) and more decision-relevant: "3 sessions ago" is what the agent
    actually reasons about.
    """
    try:
        return session_dates.index(run_date) + 1
    except ValueError:
        return None


def compact_recent(rows: list[dict], session_dates: list[date]) -> dict:
    """Encode prior opinions as columns + per-ticker rows.

    The whole context is json.dumps'd into one user message (agents/base.py),
    so every repeated JSON key is paid once per row. A list of dicts costs
    ~40 tokens/row; this costs ~15.

    Each row is [ago, direction, confidence, timeframe, excess, hit, orchestrator
    action]. `excess` and `hit` are null while the horizon is still open — that
    is deliberate: unresolved calls are exactly the ones the agent most needs to
    see, and hiding them is the silent bug this encoding is designed around.

    Deliberately omits `rationale`: it is the single most expensive field and
    its content is largely recoverable from direction plus outcome.
    """
    out: dict[str, list] = {}
    for row in rows:
        ago = sessions_ago(session_dates, row["run_date"])
        if ago is None:
            continue
        excess = row.get("excess_return")
        out.setdefault(row["ticker"], []).append([
            ago,
            row["direction"],
            round(float(row["confidence"]), 2),
            TIMEFRAME_CODE.get(row["timeframe"], row["timeframe"]),
            round(float(excess), 4) if excess is not None else None,
            row.get("hit"),
            row.get("orchestrator_action"),
        ])
    if not out:
        return {}
    for rows_for_ticker in out.values():
        rows_for_ticker.sort(key=lambda r: r[0])
    return {"cols": list(RECENT_COLS), **out}


def resolution_counts(rows: list[dict]) -> dict[str, str]:
    """Per-ticker plain-language tally of how prior calls actually turned out.

    Counts and outcomes only — no Brier, no skill score, no agent weight. This
    is factual feedback about the world, which the agent should update on; a
    score would be feedback about the metric, which it must not optimise.
    """
    tally: dict[str, list[int]] = {}
    for row in rows:
        seen, hits = tally.setdefault(row["ticker"], [0, 0])
        if row.get("hit") is None:
            continue
        tally[row["ticker"]] = [seen + 1, hits + (1 if row["hit"] else 0)]
    return {
        ticker: f"{hits} of {seen} resolved calls beat the benchmark bar"
        for ticker, (seen, hits) in tally.items()
        if seen
    }


def flip_rate(rows: list[dict]) -> float | None:
    """Fraction of consecutive same-ticker opinions that changed direction.

    The diagnostic for memory's worst failure mode: an agent that stops updating
    on new evidence and just repeats yesterday. That looks like success on every
    other metric — decisions get more "consistent" — so it needs its own number.
    A collapse toward 0 after memory ships means responsiveness was traded for
    the appearance of consistency.
    """
    by_ticker: dict[str, list[tuple[date, str]]] = {}
    for row in rows:
        by_ticker.setdefault(row["ticker"], []).append((row["run_date"], row["direction"]))

    pairs = flips = 0
    for series in by_ticker.values():
        series.sort()
        for (_, before), (_, after) in zip(series, series[1:]):
            pairs += 1
            flips += before != after
    return flips / pairs if pairs else None


# ── knowledge retrieval ────────────────────────────────────────────────────

# Every tag corresponds to something core/indicators.py, agents/context.py or
# core/wash_sale.py already computes, so retrieval is a deterministic function
# of code-computed state — auditable, replayable, and testable without a DB.
#
# This is why retrieval is tag matching rather than embeddings or full-text.
# pgvector would mean a second vendor (Anthropic ships no embedding API), an
# extra key and a per-chunk cost to do approximate nearest-neighbour over a
# corpus of 50-300 chunks, where a GIN-indexed scan is exact and sub-millisecond.
# Full-text needs a text query, but the trigger here is numeric market state;
# manufacturing a query string out of it is just tag matching with a stemmer in
# the way.
DRAWDOWN_PCT = -0.10
HIGH_VOL = 0.40
HIGH_VOL_VS_BENCHMARK = 1.5
CONCENTRATION_PCT = 20.0
HIGH_CORRELATION = 0.8
MOMENTUM_EXCESS = 0.05
THIN_DATA_SESSIONS = 63

# Tags with no computable trigger: always eligible, never forced.
UNTRIGGERED_TAGS = frozenset({"position_sizing", "cash_reserve", "time_horizon"})

# Which horizons each agent is actually scored on. The guard is load-bearing:
# daily_signal is Brier-scored at 5 sessions (core/scoring.py), so handing it a
# "our favourite holding period is forever" principle does not merely waste
# tokens, it degrades a call that will be scored next week.
AGENT_HORIZONS = {
    "daily_signal": {"days", "weeks"},
    "allocation": {"months", "quarters"},
    "risk": {"weeks", "months"},
    "tax": {"days", "weeks", "months"},
}

MAX_CHUNKS = 3
SOURCE_SCORE_COEFFICIENT = 0.25


def situation_tags(
    market: dict,
    portfolio: dict | None = None,
    correlations: dict | None = None,
    taxes: dict | None = None,
) -> set[str]:
    """Which knowledge tags today's code-computed state makes relevant. Pure."""
    tags: set[str] = set(UNTRIGGERED_TAGS)
    portfolio = portfolio or {}
    taxes = taxes or {}

    for summary in (market.get("tickers") or {}).values():
        if not summary:
            continue
        drawdown = summary.get("pct_below_63d_high")
        if drawdown is not None and drawdown <= DRAWDOWN_PCT:
            tags.add("drawdown")

        vol = summary.get("vol_21d_annualized")
        bench_vol = (market.get("benchmark") or {}).get("vol_21d_annualized")
        if vol is not None and (
            vol >= HIGH_VOL
            or (bench_vol and vol >= bench_vol * HIGH_VOL_VS_BENCHMARK)
        ):
            tags.add("high_volatility")

        short, medium = summary.get("excess_vs_spy_5d"), summary.get("excess_vs_spy_21d")
        if medium is not None and abs(medium) >= MOMENTUM_EXCESS:
            tags.add("momentum")
        if short is not None and medium is not None and short * medium < 0:
            tags.add("mean_reversion")

        sessions = summary.get("sessions_of_data")
        if sessions is not None and sessions < THIN_DATA_SESSIONS:
            tags.add("thin_data")

    for position in portfolio.get("positions") or []:
        weight = position.get("weight_pct")
        if weight is not None and weight >= CONCENTRATION_PCT:
            tags.add("concentration")

    for ticker, row in (correlations or {}).items():
        for other, value in (row or {}).items():
            if other != ticker and value is not None and abs(value) >= HIGH_CORRELATION:
                tags.add("correlation")

    for lot in taxes.get("lots") or []:
        pnl = lot.get("unrealized_pnl")
        if pnl is not None and pnl < 0:
            tags.add("unrealized_loss")
        days = lot.get("days_to_longterm")
        if days is not None and 0 < days <= 45:
            tags.add("holding_period")
    if taxes.get("wash_sale_risk"):
        tags.add("wash_sale")

    return tags


def rank_chunks(
    candidates: list[dict],
    situation: set[str],
    agent: str,
    *,
    budget_chars: int,
    max_chunks: int = MAX_CHUNKS,
    exposure: dict[int, int] | None = None,
) -> list[dict]:
    """Pick the chunks worth this agent's tokens today.

    candidates: {id, source_id, body, tags, agents, horizons, char_len}.

    Tag-match count dominates the score and the source's own weight is only a
    0.25-coefficient tiebreak. That ordering is deliberate: letting a learned
    weight drive retrieval creates a runaway — ranked high, so shown more, so
    cited more, so ranked higher. The exploration slot is the other half of
    that defence, guaranteeing under-exposed chunks keep entering the sample.
    """
    horizons = AGENT_HORIZONS.get(agent, set())
    eligible = []
    for chunk in candidates:
        allowed = set(chunk.get("agents") or ())
        if allowed and agent not in allowed:
            continue
        chunk_horizons = set(chunk.get("horizons") or ())
        if chunk_horizons and horizons and not (chunk_horizons & horizons):
            continue
        overlap = set(chunk.get("tags") or ()) & situation
        if not overlap:
            continue
        eligible.append((len(overlap), chunk))

    def score(entry) -> tuple:
        overlap, chunk = entry
        return (-(overlap + SOURCE_SCORE_COEFFICIENT * float(chunk.get("source_score", 0.5))),
                chunk["id"])

    picked: list[dict] = []
    used_sources: set[int] = set()
    spent = 0
    for _, chunk in sorted(eligible, key=score):
        if len(picked) >= max_chunks:
            break
        if chunk["source_id"] in used_sources:  # diversity: one chunk per source
            continue
        size = chunk.get("char_len") or len(chunk["body"])
        if spent + size > budget_chars:
            continue
        picked.append(chunk)
        used_sources.add(chunk["source_id"])
        spent += size

    # Exploration: one extra seat for the least-exposed eligible chunk, so the
    # attribution sample never collapses onto whatever ranked well early. It is
    # additional to max_chunks rather than competing for those slots — ranking
    # would otherwise fill every slot and the seat would never be used — and
    # the char budget still caps what it can actually cost.
    if exposure is not None:
        chosen = {c["id"] for c in picked}
        rest = [c for _, c in eligible if c["id"] not in chosen]
        if rest:
            least = min(rest, key=lambda c: (exposure.get(c["id"], 0), c["id"]))
            size = least.get("char_len") or len(least["body"])
            if spent + size <= budget_chars:
                picked.append(least)
    return picked


# ── long-term memory ───────────────────────────────────────────────────────

# Same constant, same meaning as jobs/run_evaluate.py:MIN_N_EFF, so the two
# learning paths cannot drift apart.
ESTABLISHED_N_EFF = 30.0
PROVISIONAL_N_EFF = 10.0

# A lesson must also say something: a shrunk skill sitting on the 0.5 prior is
# not a finding, it is the absence of one.
MIN_SKILL_EDGE = 0.05

DIRECTION_BUCKETS = {
    "buy": "bullish", "add": "bullish",
    "sell": "bearish", "trim": "bearish",
    "hold": "hold",
}


def lesson_tier(n_eff: float) -> str | None:
    """Which evidence tier this sample supports, or None for 'stay silent'.

    Below the bar we emit nothing at all. Silence is cheaper and more honest
    than paying daily for an "insufficient data" string.
    """
    if n_eff >= ESTABLISHED_N_EFF:
        return "established"
    if n_eff >= PROVISIONAL_N_EFF:
        return "provisional"
    return None


def lesson_stats(evaluations: list[dict]) -> dict | None:
    """Fold an agent's resolved calls on one ticker into auditable statistics.

    evaluations: {direction, confidence, hit, excess_return, horizon}. Nothing
    finer than agent x ticker x direction bucket — with a two-ticker universe,
    regime buckets fragment n to nothing and every 'lesson' becomes noise
    dressed as insight.
    """
    from core.scoring import HORIZON_DAYS, shrunk_skill

    scored = [e for e in evaluations if e.get("hit") is not None]
    if not scored:
        return None

    n = len(scored)
    n_eff = sum(1.0 / HORIZON_DAYS[e["horizon"]] for e in scored)
    hits = sum(1 for e in scored if e["hit"])
    hit_rate = hits / n
    mean_conf = sum(float(e["confidence"]) for e in scored) / n

    buckets: dict[str, list[int]] = {}
    for e in scored:
        bucket = DIRECTION_BUCKETS.get(e["direction"], e["direction"])
        seen, won = buckets.setdefault(bucket, [0, 0])
        buckets[bucket] = [seen + 1, won + (1 if e["hit"] else 0)]

    excesses = [float(e["excess_return"]) for e in scored
                if e.get("excess_return") is not None]

    return {
        "n": n,
        "n_eff": round(n_eff, 2),
        "hit_rate": round(hit_rate, 3),
        "mean_confidence": round(mean_conf, 3),
        # Positive means overconfident: claimed more certainty than it earned.
        "calibration_gap": round(mean_conf - hit_rate, 3),
        "mean_excess": round(sum(excesses) / len(excesses), 4) if excesses else None,
        "by_direction": {k: {"n": v[0], "hits": v[1]} for k, v in sorted(buckets.items())},
        "shrunk_skill": round(shrunk_skill(hit_rate, n_eff), 4),
        "tier": lesson_tier(n_eff),
    }


def render_lesson(agent: str, ticker: str | None, stats: dict | None) -> str | None:
    """Turn statistics into the one short paragraph the agent reads.

    A template, not an LLM call: deterministic, free, unit-testable, and
    consistent with how every other statistic in this codebase is produced.
    An LLM tier is only worth adding once some (agent, ticker) clears the
    established bar, which is months of data away.

    Returns None when the evidence does not support saying anything.
    """
    if not stats:
        return None
    tier = stats.get("tier")
    if tier is None:
        return None
    if abs(stats["shrunk_skill"] - 0.5) < MIN_SKILL_EDGE:
        return None

    scope = f"{agent} / {ticker}" if ticker else agent
    best = max(stats["by_direction"].items(), key=lambda kv: kv[1]["n"], default=None)
    parts = [f"{scope}:"]
    if best:
        name, counts = best
        parts.append(
            f"your {name} calls cleared the benchmark bar "
            f"{counts['hits']} of {counts['n']} times."
        )
    gap = stats["calibration_gap"]
    if abs(gap) >= 0.05:
        direction = "above" if gap > 0 else "below"
        parts.append(
            f"Stated confidence has averaged {stats['mean_confidence']:.2f}, "
            f"{direction} the {stats['hit_rate']:.2f} rate you actually achieved."
        )
    if tier == "provisional":
        # The agent reads the body, not the tier column, so the caveat has to
        # live inside the sentence it qualifies.
        parts.append(f"(n_eff {stats['n_eff']} — below the evidence bar; treat as weak.)")
    body = " ".join(parts)
    return body[:240]


def _size(value) -> int:
    import json

    return len(json.dumps(value, default=str, ensure_ascii=False))


def shrink_recent(recent: dict, budget_chars: int) -> dict:
    """Drop the oldest rows, ticker by ticker, until `recent` fits its budget.

    Short-term memory is the one block that degrades gracefully rather than
    disappearing. Truncating it is safe precisely because the `ago` column makes
    the window self-describing — an agent shown 4 sessions instead of 8 can see
    that, whereas a sliced-off knowledge chunk reads as if it were whole.

    The budget is a fixed character count, so the window shortens automatically
    as the universe grows instead of the block silently falling off a cliff at
    the third ticker.
    """
    if not recent or _size(recent) <= budget_chars:
        return recent

    trimmed = {k: (list(v) if isinstance(v, list) else v) for k, v in recent.items()}
    tickers = [k for k in trimmed if k != "cols"]
    while _size(trimmed) > budget_chars:
        # Always cut the oldest row still held by any ticker, so the tickers
        # stay aligned on the same window rather than one going stale first.
        widest = max(tickers, key=lambda t: len(trimmed[t]), default=None)
        if widest is None or len(trimmed[widest]) <= 1:
            break
        trimmed[widest].pop()
    return trimmed


def trim_to_budget(
    memory: dict,
    budgets: dict[str, int] | None = None,
) -> tuple[dict, list[str]]:
    """Fit each memory block inside its budget, never fail the run.

    Returns the trimmed memory and the names of blocks that were dropped whole.
    `recent` shrinks row by row; the other blocks are dropped whole rather than
    truncated, because half a knowledge chunk or a sliced lesson is worse than
    its absence — the agent cannot tell it is reading a fragment.
    """
    budgets = budgets or DEFAULT_BUDGETS
    trimmed = dict(memory)
    dropped: list[str] = []
    for key in TRIM_ORDER:
        value = trimmed.get(key)
        if not value:
            continue
        budget = budgets.get(key, DEFAULT_BUDGETS.get(key, 0))
        if key == SHORT_TERM_KEY:
            value = shrink_recent(value, budget)
            trimmed[key] = value
        if _size(value) > budget:
            trimmed.pop(key)
            dropped.append(key)
    return trimmed, dropped
