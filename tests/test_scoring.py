import math

import pytest

from core.scoring import (
    HORIZON_DAYS,
    TIMEFRAME_HORIZON,
    brier,
    direction_hit,
    ema,
    excess_return,
    hold_band,
    n_effective,
    shrunk_skill,
    simple_return,
)


def test_simple_and_excess_return():
    assert simple_return(100, 110) == pytest.approx(0.10)
    assert excess_return(0.10, 0.04) == pytest.approx(0.06)
    with pytest.raises(ValueError):
        simple_return(0, 100)


def test_direction_hit_buy_sell():
    assert direction_hit("buy", 0.02, 5)
    assert not direction_hit("buy", -0.02, 5)
    assert direction_hit("add", 0.001, 1)
    assert direction_hit("sell", -0.02, 5)
    assert direction_hit("trim", -0.001, 21)
    assert not direction_hit("sell", 0.02, 5)


def test_hold_band_scales_with_horizon():
    assert hold_band(1) == pytest.approx(0.01)
    assert hold_band(21) == pytest.approx(0.01 * math.sqrt(21))
    # ±2% excess at 21d sits inside the scaled band but outside a flat ±1%
    assert direction_hit("hold", 0.02, 21)
    assert not direction_hit("hold", 0.02, 1)


def test_direction_hit_rejects_unknown():
    with pytest.raises(ValueError):
        direction_hit("yolo", 0.0, 1)


def test_brier():
    assert brier(0.9, True) == pytest.approx(0.01)
    assert brier(0.9, False) == pytest.approx(0.81)
    assert brier(0.5, True) == pytest.approx(0.25)
    with pytest.raises(ValueError):
        brier(1.5, True)


def test_n_effective_corrects_overlap():
    # 63 daily decisions scored at 21d ≈ 3 independent samples
    assert n_effective(63, 21) == pytest.approx(3.0)
    assert n_effective(10, 1) == pytest.approx(10.0)


def test_shrinkage_pulls_small_samples_to_prior():
    # tiny sample: stays near prior even with perfect skill
    assert shrunk_skill(1.0, n_eff=1, prior_skill=0.5, prior_n=30) == pytest.approx(
        (30 * 0.5 + 1 * 1.0) / 31
    )
    # large sample: approaches raw skill
    big = shrunk_skill(0.8, n_eff=1000, prior_skill=0.5, prior_n=30)
    assert abs(big - 0.8) < 0.01


def test_ema_dampens_updates():
    assert ema(0.5, 1.0, alpha=0.1) == pytest.approx(0.55)
    assert ema(0.5, 0.0, alpha=0.1) == pytest.approx(0.45)


def test_timeframe_horizon_mapping_complete():
    assert set(TIMEFRAME_HORIZON.values()) <= set(HORIZON_DAYS)
    assert set(TIMEFRAME_HORIZON) == {"days", "weeks", "months", "quarters"}
