"""Token accounting: character measurement, usage extraction, cost estimate."""

from types import SimpleNamespace

import pytest

from core.llm_log import (
    CallRecord,
    Usage,
    measure_chars,
    system_text,
    usage_line,
)
from jobs.show_costs import estimate_cost


def test_usage_from_response_reads_all_four_counters():
    response = SimpleNamespace(usage=SimpleNamespace(
        input_tokens=100, output_tokens=20,
        cache_creation_input_tokens=1000, cache_read_input_tokens=500,
    ))
    assert Usage.from_response(response) == Usage(100, 20, 1000, 500)


def test_usage_from_response_tolerates_missing_usage_and_fields():
    assert Usage.from_response(SimpleNamespace()) == Usage()
    # An SDK that omits the cache counters must log zeros, not blow up the run.
    partial = SimpleNamespace(usage=SimpleNamespace(input_tokens=7, output_tokens=None))
    assert Usage.from_response(partial) == Usage(7, 0, 0, 0)


def test_system_text_flattens_content_blocks():
    assert system_text("plain") == "plain"
    blocks = [{"type": "text", "text": "core"}, {"type": "text", "text": "-role"}]
    assert system_text(blocks) == "core-role"


def test_measure_chars_counts_system_plus_context():
    chars = measure_chars("sys", {"a": 1})
    assert chars["total"] == len("sys") + len('{"a": 1}')
    assert chars["knowledge"] == chars["short_term"] == chars["long_term"] == 0


def test_measure_chars_isolates_each_memory_block():
    context = {
        "tickers": ["NVDA"],
        "knowledge": [{"id": 1, "body": "size down"}],
        "recent": {"cols": ["ago"], "NVDA": [[1]]},
        "long_term": ["a lesson"],
    }
    chars = measure_chars("", context)
    assert chars["knowledge"] == len('[{"id": 1, "body": "size down"}]')
    assert chars["short_term"] == len('{"cols": ["ago"], "NVDA": [[1]]}')
    assert chars["long_term"] == len('["a lesson"]')
    # Blocks are part of the total, never larger than it.
    assert chars["total"] > chars["knowledge"] + chars["short_term"] + chars["long_term"]


def test_measure_chars_adds_system_side_knowledge():
    plain = measure_chars("sys", {})
    with_core = measure_chars("sys", {}, system_knowledge_chars=400)
    assert with_core["knowledge"] == plain["knowledge"] + 400


def test_measure_chars_handles_unserializable_values():
    from datetime import date

    chars = measure_chars("", {"as_of": date(2026, 8, 7)})
    assert chars["total"] > 0


def test_measure_chars_treats_empty_blocks_as_absent():
    # An empty list must not be billed as a memory block.
    assert measure_chars("", {"knowledge": [], "recent": {}})["knowledge"] == 0


def test_call_record_defaults_are_zero_and_ok():
    record = CallRecord()
    assert record.usage == Usage()
    assert record.chars == {}
    assert record.ok is True


def test_usage_line_reports_counts_only():
    line = usage_line(Usage(1840, 430, 0, 1200))
    assert line == "tokens in=1840 out=430 cache_write=0 cache_read=1200"


def test_estimate_cost_prices_output_at_five_times_input():
    only_input = estimate_cost(1_000_000, 0, 0, 0, 3.0, 15.0)
    only_output = estimate_cost(0, 1_000_000, 0, 0, 3.0, 15.0)
    assert only_input == pytest.approx(3.0)
    assert only_output == pytest.approx(15.0)


def test_estimate_cost_applies_cache_multipliers():
    # Cache writes bill at 1.25x input, reads at 0.1x.
    assert estimate_cost(0, 0, 1_000_000, 0, 3.0, 15.0) == pytest.approx(3.75)
    assert estimate_cost(0, 0, 0, 1_000_000, 3.0, 15.0) == pytest.approx(0.30)


def test_estimate_cost_of_a_cached_run_beats_an_uncached_one():
    """The economics behind putting shared knowledge in a cached system block.

    Four agents, 1200 shared tokens each: uncached pays 4x, cached pays
    1.25x once plus 0.1x three times.
    """
    uncached = estimate_cost(4 * 1200, 0, 0, 0, 3.0, 15.0)
    cached = estimate_cost(0, 0, 1200, 3 * 1200, 3.0, 15.0)
    assert cached < uncached
    assert cached / uncached == pytest.approx(1.55 / 4.0)
