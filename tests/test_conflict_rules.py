from core.conflict_rules import OpinionInput, TaxFlags, decide
from core.orchestrator import flags_from_lots


def op(agent, direction, confidence=0.7, timeframe="weeks"):
    return OpinionInput(agent=agent, direction=direction, confidence=confidence,
                        timeframe=timeframe)


W = {}  # default weights


def test_agreeing_buys_yield_buy():
    d = decide("AAPL", [op("daily_signal", "buy"), op("allocation", "buy")], W)
    assert d.action == "buy"
    assert "weighted vote" in d.rationale


def test_disagreement_lands_on_hold():
    d = decide("AAPL", [op("daily_signal", "buy"), op("allocation", "sell")], W)
    assert d.action == "hold"


def test_strong_negative_vote_sells():
    d = decide("AAPL", [op("daily_signal", "sell", 0.9), op("allocation", "sell", 0.8)], W)
    assert d.action == "sell"


def test_weights_tilt_the_vote():
    ops = [op("daily_signal", "buy", 0.8), op("allocation", "sell", 0.8)]
    d = decide("AAPL", ops, {"daily_signal": 0.9, "allocation": 0.1})
    assert d.action in ("buy", "add")


def test_tax_agent_never_votes_on_direction():
    d = decide("AAPL", [op("tax", "sell", 0.95)], W)
    assert d.action == "hold"          # no direction votes at all
    assert d.confidence == 0.3


def test_r1_risk_veto_blocks_added_exposure():
    ops = [op("daily_signal", "buy", 0.9), op("allocation", "buy", 0.8),
           op("risk", "trim", 0.7)]
    d = decide("AAPL", ops, W)
    assert d.action == "hold"
    assert d.rules_applied == ["R1"]
    assert d.confidence <= 0.7


def test_risk_hold_does_not_veto():
    ops = [op("daily_signal", "buy", 0.9), op("allocation", "buy", 0.8),
           op("risk", "hold", 0.9)]
    assert decide("AAPL", ops, W).action == "buy"


def test_risk_agent_never_votes_on_direction():
    d = decide("AAPL", [op("risk", "sell", 0.95)], W)
    assert d.action == "hold" and d.confidence == 0.3


def test_t1_long_term_deferral():
    ops = [op("daily_signal", "sell", 0.8), op("tax", "hold", 0.9)]
    tax = TaxFlags(has_unrealized_gain=True, days_to_longterm=30)
    d = decide("AAPL", ops, W, tax)
    assert d.action == "hold"
    assert d.revisit_days == 30
    assert d.rules_applied == ["T1"]
    assert d.confidence == 0.9         # tax opinion's confidence takes over


def test_t1_not_applied_beyond_defer_window():
    ops = [op("daily_signal", "sell", 0.8), op("tax", "hold", 0.9)]
    tax = TaxFlags(has_unrealized_gain=True, days_to_longterm=200)
    assert decide("AAPL", ops, W, tax).action == "sell"


def test_t2_wash_sale_blocks_loss_sale():
    ops = [op("daily_signal", "sell", 0.9)]
    tax = TaxFlags(has_unrealized_loss=True, wash_sale_risk="recent purchase in window")
    d = decide("AAPL", ops, W, tax)
    assert d.action == "hold"
    assert d.rules_applied == ["T2"]


def test_t3_harvest_nudge_trims():
    ops = [op("daily_signal", "hold", 0.6), op("tax", "sell", 0.8)]
    tax = TaxFlags(has_unrealized_loss=True)
    d = decide("AAPL", ops, W, tax)
    assert d.action == "trim"
    assert d.rules_applied == ["T3"]


def test_t3_suppressed_by_wash_flag():
    ops = [op("daily_signal", "hold", 0.6), op("tax", "sell", 0.8)]
    tax = TaxFlags(has_unrealized_loss=True, wash_sale_risk="flagged")
    assert decide("AAPL", ops, W, tax).action == "hold"


def test_flags_from_lots():
    lots = [
        {"ticker": "AAPL", "unrealized_pnl": 500.0, "days_to_longterm": 40},
        {"ticker": "AAPL", "unrealized_pnl": 100.0, "days_to_longterm": 10},
        {"ticker": "AAPL", "unrealized_pnl": -50.0, "days_to_longterm": 300},
        {"ticker": "MSFT", "unrealized_pnl": None, "days_to_longterm": 0},
    ]
    flags = flags_from_lots(lots, {"NVDA": "recent buy"})
    assert flags["AAPL"].has_unrealized_gain and flags["AAPL"].has_unrealized_loss
    assert flags["AAPL"].days_to_longterm == 10
    assert flags["NVDA"].wash_sale_risk == "recent buy"
    assert not flags["MSFT"].has_unrealized_gain
