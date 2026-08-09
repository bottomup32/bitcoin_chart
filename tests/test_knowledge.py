"""Knowledge retrieval: situation tags, ranking, horizon guard, exploration."""

from agents.base import Opinion, _cited_chunks, _cited_sources
from agents.memory import with_core_knowledge
from core.memory import AGENT_HORIZONS, rank_chunks, situation_tags

MARKET = {
    "benchmark": {"vol_21d_annualized": 0.15},
    "tickers": {
        "NVDA": {"pct_below_63d_high": -0.03, "vol_21d_annualized": 0.30,
                 "excess_vs_spy_5d": 0.01, "excess_vs_spy_21d": 0.02,
                 "sessions_of_data": 200},
    },
}


def chunk(cid, *, source=1, tags=("momentum",), agents=(), horizons=(), body="rule"):
    return {"id": cid, "source_id": source, "body": body, "tags": list(tags),
            "agents": list(agents), "horizons": list(horizons),
            "char_len": len(body), "source_score": 0.5}


# ── situation tags ─────────────────────────────────────────────────────────

def test_a_calm_market_fires_only_the_untriggered_tags():
    calm = {"benchmark": {"vol_21d_annualized": 0.15},
            "tickers": {"NVDA": {"pct_below_63d_high": -0.01,
                                 "vol_21d_annualized": 0.16,
                                 "excess_vs_spy_5d": 0.001,
                                 "excess_vs_spy_21d": 0.002,
                                 "sessions_of_data": 200}}}
    tags = situation_tags(calm)
    assert "drawdown" not in tags and "high_volatility" not in tags
    assert "momentum" not in tags
    assert "position_sizing" in tags


def test_drawdown_and_volatility_thresholds():
    market = {"benchmark": {"vol_21d_annualized": 0.15},
              "tickers": {"NVDA": {"pct_below_63d_high": -0.12,
                                   "vol_21d_annualized": 0.45,
                                   "sessions_of_data": 200}}}
    tags = situation_tags(market)
    assert {"drawdown", "high_volatility"} <= tags


def test_volatility_fires_relative_to_the_benchmark_too():
    """0.30 is below the absolute bar but 2x SPY's 0.15."""
    assert "high_volatility" in situation_tags(MARKET)  # 0.30 >= 1.5 * 0.15


def test_mean_reversion_needs_opposite_signs():
    market = {"benchmark": {}, "tickers": {"NVDA": {
        "excess_vs_spy_5d": -0.02, "excess_vs_spy_21d": 0.06,
        "sessions_of_data": 200}}}
    tags = situation_tags(market)
    assert "mean_reversion" in tags and "momentum" in tags


def test_concentration_comes_from_portfolio_weights():
    portfolio = {"positions": [{"weight_pct": 24.0}, {"weight_pct": 5.0}]}
    assert "concentration" in situation_tags(MARKET, portfolio)
    assert "concentration" not in situation_tags(
        MARKET, {"positions": [{"weight_pct": 5.0}]}
    )


def test_correlation_ignores_a_tickers_correlation_with_itself():
    assert "correlation" not in situation_tags(MARKET, None, {"NVDA": {"NVDA": 1.0}})
    assert "correlation" in situation_tags(
        MARKET, None, {"NVDA": {"NVDA": 1.0, "TSLA": 0.85}}
    )


def test_tax_situation_tags():
    taxes = {"lots": [{"unrealized_pnl": -400.0, "days_to_longterm": 30}],
             "wash_sale_risk": {"NVDA": "recent purchase"}}
    tags = situation_tags(MARKET, None, None, taxes)
    assert {"unrealized_loss", "holding_period", "wash_sale"} <= tags


def test_thin_data_fires_on_a_short_history():
    market = {"benchmark": {}, "tickers": {"NEW": {"sessions_of_data": 20}}}
    assert "thin_data" in situation_tags(market)


def test_situation_tags_tolerate_missing_fields():
    assert situation_tags({"tickers": {"X": {}}}) >= {"position_sizing"}
    assert situation_tags({}) >= {"position_sizing"}


# ── ranking ────────────────────────────────────────────────────────────────

def test_a_chunk_with_no_tag_overlap_is_not_retrieved():
    picked = rank_chunks([chunk(1, tags=("wash_sale",))], {"momentum"},
                         "daily_signal", budget_chars=1000)
    assert picked == []


def test_more_tag_overlap_ranks_higher():
    picked = rank_chunks(
        [chunk(1, tags=("momentum",), source=1),
         chunk(2, tags=("momentum", "drawdown"), source=2)],
        {"momentum", "drawdown"}, "daily_signal", budget_chars=1000, max_chunks=1,
    )
    assert [c["id"] for c in picked] == [2]


def test_the_horizon_guard_keeps_long_horizon_rules_from_the_daily_agent():
    """daily_signal is Brier-scored at 5 sessions; a 'hold forever' rule
    actively degrades that call rather than merely wasting tokens."""
    long_rule = chunk(1, horizons=("months", "quarters"))
    assert rank_chunks([long_rule], {"momentum"}, "daily_signal", budget_chars=1000) == []
    assert rank_chunks([long_rule], {"momentum"}, "allocation", budget_chars=1000)


def test_an_untagged_horizon_applies_everywhere():
    anytime = chunk(1, horizons=())
    for agent in AGENT_HORIZONS:
        assert rank_chunks([anytime], {"momentum"}, agent, budget_chars=1000)


def test_the_agent_filter_is_respected():
    only_risk = chunk(1, agents=("risk",))
    assert rank_chunks([only_risk], {"momentum"}, "daily_signal", budget_chars=1000) == []
    assert rank_chunks([only_risk], {"momentum"}, "risk", budget_chars=1000)


def test_one_chunk_per_source_keeps_the_selection_diverse():
    same_source = [chunk(1, source=7), chunk(2, source=7), chunk(3, source=9)]
    picked = rank_chunks(same_source, {"momentum"}, "daily_signal", budget_chars=1000)
    assert sorted(c["source_id"] for c in picked) == [7, 9]


def test_selection_respects_max_chunks_and_the_char_budget():
    many = [chunk(i, source=i, body="x" * 100) for i in range(1, 10)]
    assert len(rank_chunks(many, {"momentum"}, "daily_signal", budget_chars=1000)) == 3
    assert len(rank_chunks(many, {"momentum"}, "daily_signal",
                           budget_chars=150, max_chunks=3)) == 1


def test_tag_overlap_outranks_the_source_weight():
    """Otherwise a well-rated source is shown more, cited more, rated higher."""
    weak_but_relevant = {**chunk(1, tags=("momentum", "drawdown"), source=1),
                         "source_score": 0.05}
    strong_but_less_relevant = {**chunk(2, tags=("momentum",), source=2),
                                "source_score": 0.95}
    picked = rank_chunks([strong_but_less_relevant, weak_but_relevant],
                         {"momentum", "drawdown"}, "daily_signal",
                         budget_chars=1000, max_chunks=1)
    assert picked[0]["id"] == 1


def test_the_exploration_slot_seats_the_least_shown_chunk():
    candidates = [chunk(1, source=1), chunk(2, source=2), chunk(3, source=3)]
    picked = rank_chunks(candidates, {"momentum"}, "daily_signal",
                         budget_chars=1000, max_chunks=2,
                         exposure={1: 50, 2: 40, 3: 0})
    assert 3 in [c["id"] for c in picked], "under-exposed chunk never enters the sample"


def test_exploration_does_not_exceed_the_char_budget():
    candidates = [chunk(i, source=i, body="x" * 90) for i in range(1, 5)]
    picked = rank_chunks(candidates, {"momentum"}, "daily_signal",
                         budget_chars=100, max_chunks=3, exposure={})
    assert sum(c["char_len"] for c in picked) <= 100


# ── attribution ────────────────────────────────────────────────────────────

def opinion(used):
    return Opinion(ticker="NVDA", direction="buy", confidence=0.6, timeframe="days",
                   rationale="r", used_knowledge_ids=used)


def test_ordinals_map_back_to_the_chunks_that_were_shown():
    shown = [chunk(11, source=3), chunk(22, source=4), chunk(33, source=3)]
    assert [c["id"] for c in _cited_chunks(opinion([1, 3]), shown)] == [11, 33]
    assert _cited_sources(opinion([1, 3]), shown) == {3}


def test_out_of_range_and_duplicate_ordinals_are_ignored():
    shown = [chunk(11, source=3)]
    assert _cited_chunks(opinion([0, 2, 99, -1]), shown) == []
    assert len(_cited_chunks(opinion([1, 1, 1]), shown)) == 1


def test_citing_nothing_is_a_valid_answer():
    assert _cited_sources(opinion([]), [chunk(11)]) == set()
    assert _cited_chunks(opinion([1]), None) == []


# ── the shared system block ────────────────────────────────────────────────

def test_without_core_knowledge_the_system_prompt_is_unchanged():
    assert with_core_knowledge("role", []) == "role"


def test_core_knowledge_precedes_the_role_prompt():
    """The shared prefix must come first, or there is nothing to cache."""
    blocks = with_core_knowledge("role text", ["margin of safety", "size to conviction"])
    assert [b["type"] for b in blocks] == ["text", "text"]
    assert "margin of safety" in blocks[0]["text"]
    assert blocks[1]["text"] == "role text"
