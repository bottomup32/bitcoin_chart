"""Long-term memory: evidence gates, statistics, and the lesson template."""

import pytest

from core.memory import (
    ESTABLISHED_N_EFF,
    PROVISIONAL_N_EFF,
    lesson_stats,
    lesson_tier,
    render_lesson,
)


def evals(n, *, horizon="5d", hit=True, conf=0.62, direction="buy", excess=0.01):
    return [{"direction": direction, "confidence": conf, "horizon": horizon,
             "hit": hit, "excess_return": excess} for _ in range(n)]


# ── the evidence gate ──────────────────────────────────────────────────────

def test_tier_thresholds_match_the_weight_update_constant():
    from jobs.run_evaluate import MIN_N_EFF

    assert ESTABLISHED_N_EFF == MIN_N_EFF, "the two learning paths must not drift"
    assert lesson_tier(ESTABLISHED_N_EFF) == "established"
    assert lesson_tier(PROVISIONAL_N_EFF) == "provisional"
    assert lesson_tier(PROVISIONAL_N_EFF - 0.01) is None


def test_a_thin_sample_produces_no_lesson_at_all():
    """Silence is cheaper and more honest than a daily 'insufficient data'."""
    stats = lesson_stats(evals(11))  # 11 at 5d -> n_eff 2.2
    assert stats["tier"] is None
    assert render_lesson("daily_signal", "NVDA", stats) is None


def test_a_lesson_with_no_edge_is_not_a_finding():
    # Exactly chance: shrunk skill sits on the prior, so there is nothing to say.
    stats = lesson_stats(evals(100, hit=True) + evals(100, hit=False))
    assert stats["tier"] == "established"
    assert stats["shrunk_skill"] == pytest.approx(0.5)
    assert render_lesson("daily_signal", "NVDA", stats) is None


def test_render_lesson_of_nothing_is_none():
    assert render_lesson("daily_signal", "NVDA", None) is None
    assert lesson_stats([]) is None
    assert lesson_stats([{"hit": None, "direction": "buy",
                          "confidence": 0.5, "horizon": "5d"}]) is None


# ── statistics ─────────────────────────────────────────────────────────────

def test_n_eff_discounts_overlapping_windows():
    stats = lesson_stats(evals(63, horizon="63d"))
    assert stats["n"] == 63
    assert stats["n_eff"] == pytest.approx(1.0)


def test_calibration_gap_is_positive_when_overconfident():
    stats = lesson_stats(evals(10, conf=0.9, hit=True) + evals(10, conf=0.9, hit=False))
    assert stats["hit_rate"] == 0.5
    assert stats["calibration_gap"] == pytest.approx(0.4)


def test_directions_collapse_into_buckets():
    stats = lesson_stats(evals(5, direction="buy") + evals(5, direction="add")
                         + evals(3, direction="trim", hit=False))
    assert stats["by_direction"]["bullish"] == {"n": 10, "hits": 10}
    assert stats["by_direction"]["bearish"] == {"n": 3, "hits": 0}


def test_unresolved_evaluations_are_excluded_from_statistics():
    stats = lesson_stats(evals(10) + evals(5, hit=None))
    assert stats["n"] == 10


def test_mean_excess_tolerates_missing_values():
    stats = lesson_stats(evals(5, excess=None))
    assert stats["mean_excess"] is None


# ── the template ───────────────────────────────────────────────────────────

def test_an_established_lesson_states_outcomes_not_scores():
    body = render_lesson("daily_signal", "NVDA", lesson_stats(evals(200, hit=True)))
    assert "cleared the benchmark bar" in body
    for forbidden in ("brier", "skill", "weight"):
        assert forbidden not in body.lower(), "agents must never see their own metric"


def test_a_provisional_lesson_carries_its_caveat_inline():
    """The agent reads the body, not the tier column."""
    stats = lesson_stats(evals(60, hit=True))  # n_eff 12 -> provisional
    assert stats["tier"] == "provisional"
    body = render_lesson("daily_signal", "NVDA", stats)
    assert "below the evidence bar" in body


def test_an_established_lesson_has_no_caveat():
    body = render_lesson("daily_signal", "NVDA", lesson_stats(evals(200, hit=True)))
    assert "below the evidence bar" not in body


def test_lesson_body_fits_the_column_constraint():
    stats = lesson_stats(evals(200, conf=0.99, hit=True, direction="buy"))
    body = render_lesson("daily_signal_with_a_very_long_name", "TICKERTICKER", stats)
    assert len(body) <= 240


def test_calibration_sentence_appears_only_when_the_gap_is_real():
    tight = lesson_stats(evals(200, conf=0.99, hit=True))
    assert "Stated confidence" not in render_lesson("daily_signal", "NVDA", tight)
    loose = lesson_stats(evals(150, conf=0.99, hit=True) + evals(50, conf=0.99, hit=False))
    assert "Stated confidence" in render_lesson("daily_signal", "NVDA", loose)


def test_an_agent_level_lesson_omits_the_ticker():
    body = render_lesson("daily_signal", None, lesson_stats(evals(200, hit=True)))
    assert body.startswith("daily_signal:")
