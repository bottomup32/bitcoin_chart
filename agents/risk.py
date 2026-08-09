"""Risk Agent — concentration, volatility, drawdown, correlation (PLAN.md §1 [3]).

Veto role: a sell/trim from this agent blocks buy/add decisions in the
orchestrator (rule R1). Not scored on direction in v1 (PLAN.md §4) — its job
is avoiding drawdowns, not predicting returns.
"""

from agents.base import DISCLAIMER
from agents.memory import merge

NAME = "risk"

SYSTEM = f"""{DISCLAIMER}

You are the Risk Agent. You guard the portfolio against concentration,
volatility, and correlated drawdowns. You do not predict returns.

Read the provided portfolio weights, per-ticker volatility, drawdown from
recent highs, and the correlation matrix, and give one opinion per HELD ticker:

- trim/sell = reduce exposure: position weight above ~20%, extreme volatility,
  deep drawdown with high correlation to the rest of the book, or several
  highly correlated positions (>0.8) that behave as one oversized bet.
- hold = risk posture acceptable.
- Never recommend buy/add — reducing or accepting risk is your whole mandate.

Guidelines:
- timeframe: "weeks" or "months".
- confidence = how clearly the risk metrics support the action (0-1), not a
  market prediction.
- Cite the specific numbers (weight_pct, vol, correlation) in each rationale.
"""


def build_context(
    cur, market: dict, portfolio: dict, correlations: dict, memory: dict | None = None
) -> dict:
    return merge(
        {
            "task": "Assess risk for each held ticker; trim/sell reduces exposure, "
                    "hold accepts it.",
            "portfolio": portfolio,
            "correlation_matrix_63d": correlations,
            **market,
        },
        memory,
    )
