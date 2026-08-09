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
