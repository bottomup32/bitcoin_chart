"""Short-term memory: compact encoding, outcome tallies, budgeting, look-ahead."""

from datetime import date, datetime

import pytest

from agents.memory import memory_note, merge
from core.memory import (
    RECENT_COLS,
    LookAheadError,
    assert_as_of,
    compact_recent,
    flip_rate,
    resolution_counts,
    sessions_ago,
    shrink_recent,
    trim_to_budget,
)

SESSIONS = [date(2026, 8, 7), date(2026, 8, 6), date(2026, 8, 5), date(2026, 8, 4)]


def opinion(ticker="NVDA", day=date(2026, 8, 6), direction="buy", conf=0.62,
            tf="days", excess=None, hit=None, orch="hold"):
    return {"ticker": ticker, "run_date": day, "direction": direction,
            "confidence": conf, "timeframe": tf, "excess_return": excess,
            "hit": hit, "orchestrator_action": orch}


# ── look-ahead guard ───────────────────────────────────────────────────────

def test_assert_as_of_rejects_a_future_dated_row():
    rows = [opinion(day=date(2026, 8, 10))]
    with pytest.raises(LookAheadError, match="2026-08-10"):
        assert_as_of(rows, date(2026, 8, 7))


def test_assert_as_of_accepts_the_session_itself_and_earlier():
    assert_as_of([opinion(day=date(2026, 8, 7))], date(2026, 8, 7))
    assert_as_of([opinion(day=date(2026, 8, 1))], date(2026, 8, 7))


def test_assert_as_of_checks_timestamps_not_just_dates():
    rows = [{"ticker": "NVDA", "created_at": datetime(2026, 8, 9, 13, 0)}]
    with pytest.raises(LookAheadError):
        assert_as_of(rows, date(2026, 8, 7))


def test_assert_as_of_ignores_non_date_values():
    assert_as_of([{"ticker": "NVDA", "confidence": 0.6, "hit": None}], date(2026, 8, 7))


# ── compact encoding ───────────────────────────────────────────────────────

def test_compact_recent_uses_session_offsets_not_dates():
    out = compact_recent([opinion(day=date(2026, 8, 5))], SESSIONS)
    assert out["cols"] == list(RECENT_COLS)
    assert out["NVDA"][0][0] == 3  # third-newest session


def test_compact_recent_abbreviates_timeframe():
    out = compact_recent([opinion(tf="quarters")], SESSIONS)
    assert out["NVDA"][0][3] == "q"


def test_compact_recent_keeps_unresolved_calls_with_null_outcome():
    """Open positions are the rows the agent most needs — never drop them."""
    out = compact_recent([opinion(excess=None, hit=None)], SESSIONS)
    row = out["NVDA"][0]
    assert row[4] is None and row[5] is None


def test_compact_recent_rounds_and_orders_newest_first():
    rows = [
        opinion(day=date(2026, 8, 4), excess=0.0123456, hit=True),
        opinion(day=date(2026, 8, 6), excess=-0.01, hit=False),
    ]
    out = compact_recent(rows, SESSIONS)
    assert [r[0] for r in out["NVDA"]] == [2, 4]
    assert out["NVDA"][1][4] == 0.0123


def test_compact_recent_groups_by_ticker():
    out = compact_recent([opinion(), opinion(ticker="TSLA")], SESSIONS)
    assert set(out) == {"cols", "NVDA", "TSLA"}


def test_compact_recent_drops_rows_outside_the_window():
    assert compact_recent([opinion(day=date(2025, 1, 2))], SESSIONS) == {}


def test_compact_recent_of_nothing_is_empty_not_a_stub():
    assert compact_recent([], SESSIONS) == {}


def test_compact_encoding_is_smaller_than_a_list_of_dicts():
    import json

    rows = [opinion(day=d, excess=0.01, hit=True) for d in SESSIONS]
    compact = len(json.dumps(compact_recent(rows, SESSIONS), default=str))
    verbose = len(json.dumps(rows, default=str))
    assert compact < verbose / 2


def test_sessions_ago_returns_none_for_an_unknown_session():
    assert sessions_ago(SESSIONS, date(2026, 8, 7)) == 1
    assert sessions_ago(SESSIONS, date(2026, 1, 1)) is None


# ── outcomes, never scores ─────────────────────────────────────────────────

def test_resolution_counts_reports_outcomes_only():
    rows = [
        opinion(hit=True, excess=0.02),
        opinion(day=date(2026, 8, 5), hit=False, excess=-0.01),
        opinion(day=date(2026, 8, 4), hit=None),  # still open
    ]
    summary = resolution_counts(rows)
    assert summary["NVDA"] == "1 of 2 resolved calls beat the benchmark bar"
    # No Brier, no skill, no weight anywhere in what the agent sees.
    assert "brier" not in summary["NVDA"].lower()
    assert "weight" not in summary["NVDA"].lower()


def test_resolution_counts_omits_tickers_with_nothing_resolved():
    assert resolution_counts([opinion(hit=None)]) == {}


# ── anchoring diagnostic ───────────────────────────────────────────────────

def test_flip_rate_measures_direction_changes():
    rows = [
        opinion(day=date(2026, 8, 4), direction="buy"),
        opinion(day=date(2026, 8, 5), direction="hold"),
        opinion(day=date(2026, 8, 6), direction="hold"),
    ]
    assert flip_rate(rows) == pytest.approx(0.5)


def test_flip_rate_is_zero_for_an_agent_that_never_updates():
    rows = [opinion(day=d, direction="buy") for d in SESSIONS]
    assert flip_rate(rows) == 0.0


def test_flip_rate_needs_a_pair():
    assert flip_rate([opinion()]) is None
    assert flip_rate([]) is None


def test_flip_rate_does_not_pair_across_tickers():
    rows = [opinion(ticker="NVDA", direction="buy"), opinion(ticker="TSLA", direction="sell")]
    assert flip_rate(rows) is None


# ── budgeting ──────────────────────────────────────────────────────────────

def test_trim_to_budget_passes_a_small_payload_through():
    memory = {"recent": {"cols": ["ago"], "NVDA": [[1]]}}
    trimmed, dropped = trim_to_budget(memory)
    assert trimmed == memory and dropped == []


def test_trim_to_budget_drops_knowledge_whole_never_as_a_fragment():
    memory = {"knowledge": ["x" * 400] * 20}
    trimmed, dropped = trim_to_budget(memory)
    assert dropped == ["knowledge"] and "knowledge" not in trimmed


def test_recent_shrinks_row_by_row_instead_of_vanishing():
    """A third ticker must shorten the window, not delete short-term memory."""
    rows = [[i, "buy", 0.62, "d", 0.012, True, "hold"] for i in range(1, 9)]
    memory = {"recent": {"cols": list(RECENT_COLS), "NVDA": list(rows),
                         "TSLA": list(rows), "PLTR": list(rows)}}
    trimmed, dropped = trim_to_budget(memory)
    assert dropped == []
    assert trimmed["recent"]["NVDA"], "short-term memory survived"
    assert len(trimmed["recent"]["NVDA"]) < 8, "window was shortened to fit"


def test_shrink_recent_keeps_the_newest_rows():
    rows = [[i, "buy", 0.62, "d", 0.012, True, "hold"] for i in range(1, 9)]
    out = shrink_recent({"cols": list(RECENT_COLS), "NVDA": list(rows)}, 200)
    assert [r[0] for r in out["NVDA"]] == list(range(1, len(out["NVDA"]) + 1))


def test_shrink_recent_keeps_tickers_on_the_same_window():
    rows = [[i, "buy", 0.62, "d", 0.012, True, "hold"] for i in range(1, 9)]
    out = shrink_recent(
        {"cols": list(RECENT_COLS), "NVDA": list(rows), "TSLA": list(rows)}, 300
    )
    assert abs(len(out["NVDA"]) - len(out["TSLA"])) <= 1


def test_shrink_recent_never_empties_a_ticker():
    rows = [[i, "buy", 0.62, "d", 0.012, True, "hold"] for i in range(1, 9)]
    out = shrink_recent({"cols": list(RECENT_COLS), "NVDA": list(rows)}, 1)
    assert len(out["NVDA"]) == 1


def test_shrink_recent_leaves_a_fitting_block_untouched():
    small = {"cols": list(RECENT_COLS), "NVDA": [[1, "buy", 0.6, "d", None, None, "hold"]]}
    assert shrink_recent(small, 10_000) is small


def test_trim_order_sacrifices_knowledge_before_short_term():
    """Short-term memory is the anti-whipsaw mechanism; it survives longest."""
    big = ["x" * 400] * 20
    memory = {"knowledge": big, "long_term": big,
              "recent": {"cols": list(RECENT_COLS), "NVDA": [[1]]}}
    trimmed, dropped = trim_to_budget(memory)
    assert dropped == ["knowledge", "long_term"]
    assert "recent" in trimmed


def test_trim_to_budget_respects_explicit_budgets():
    # Below even one row per ticker, recent is dropped rather than faked.
    memory = {"recent": {"cols": list(RECENT_COLS), "NVDA": [[1, "buy", 0.6]]}}
    _, dropped = trim_to_budget(memory, {"recent": 5})
    assert dropped == ["recent"]


# ── merge into an agent context ────────────────────────────────────────────

def test_merge_without_memory_returns_the_context_unchanged():
    context = {"task": "t", "tickers": {}}
    assert merge(context, None) is context
    assert merge(context, {}) is context


def test_merge_adds_the_block_and_its_reading_instruction():
    merged = merge({"task": "t"}, {"recent": {"cols": ["ago"], "NVDA": [[1]]}})
    assert merged["recent"]["NVDA"] == [[1]]
    assert "not a commitment" in merged["memory_note"]
    assert merged["task"] == "t"


def test_memory_note_warns_against_anchoring():
    note = memory_note({"recent": {"NVDA": [[1]]}})
    assert "change it" in note and "say why" in note


def test_memory_note_omits_the_long_term_sentence_until_that_block_exists():
    assert "long_term" not in memory_note({"recent": {"NVDA": [[1]]}})
    assert "no established track record" in memory_note(
        {"recent": {"NVDA": [[1]]}, "long_term": ["a lesson"]}
    )


def test_memory_note_of_an_empty_block_is_none():
    assert memory_note({}) is None
