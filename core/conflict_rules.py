"""Orchestrator decision rules (PLAN.md §1 [4]). Pure, deterministic, tested.

Explicit code rules decide; the LLM only narrates afterwards. Direction-scored
agents (daily_signal, allocation, later fundamental) vote with weight ×
confidence; the tax agent never votes on direction — it acts through the
override rules below, mirroring its exclusion from Brier scoring (PLAN.md §4).

Override rules:
- T1  Long-term deferral: a vote to sell/trim a position with gains that is
      within `defer_days` of long-term treatment, while tax says hold, becomes
      "hold, revisit in N days".
- T2  Wash-sale block: a vote to sell/trim a losing position whose ticker is
      wash-sale flagged becomes hold (selling now would disallow the loss).
- T3  Harvest nudge: tax recommends selling a losing position (harvest), the
      vote is hold, and no wash-sale flag exists → trim (partial harvest).
"""

from __future__ import annotations

from dataclasses import dataclass, field

DIRECTION_SCORE = {"buy": 1.0, "add": 0.5, "hold": 0.0, "trim": -0.5, "sell": -1.0}
VOTE_AGENTS = {"daily_signal", "allocation", "fundamental"}
DEFAULT_WEIGHT = 0.5
DEFER_DAYS = 45

# combined score thresholds → action
THRESHOLDS = [(0.6, "buy"), (0.2, "add"), (-0.2, "hold"), (-0.6, "trim")]


@dataclass
class OpinionInput:
    agent: str
    direction: str
    confidence: float
    timeframe: str


@dataclass
class TaxFlags:
    wash_sale_risk: str | None = None      # code-computed message when flagged
    days_to_longterm: int | None = None    # min among open lots with gains
    has_unrealized_loss: bool = False
    has_unrealized_gain: bool = False


@dataclass
class Decision:
    ticker: str
    action: str
    confidence: float
    rationale: str            # deterministic rule trace
    revisit_days: int | None = None
    rules_applied: list[str] = field(default_factory=list)


def _score_to_action(score: float) -> str:
    for threshold, action in THRESHOLDS:
        if score >= threshold:
            return action
    return "sell"


def decide(
    ticker: str,
    opinions: list[OpinionInput],
    weights: dict[str, float],
    tax: TaxFlags | None = None,
    defer_days: int = DEFER_DAYS,
) -> Decision:
    tax = tax or TaxFlags()
    votes = [o for o in opinions if o.agent in VOTE_AGENTS]
    tax_op = next((o for o in opinions if o.agent == "tax"), None)

    if votes:
        norm = sum(o.confidence * weights.get(o.agent, DEFAULT_WEIGHT) for o in votes)
        raw = sum(
            DIRECTION_SCORE[o.direction] * o.confidence * weights.get(o.agent, DEFAULT_WEIGHT)
            for o in votes
        )
        score = raw / norm if norm > 0 else 0.0
        confidence = sum(o.confidence for o in votes) / len(votes)
    else:
        score, confidence = 0.0, 0.3  # nothing to go on — weak hold

    action = _score_to_action(score)
    trace = [f"{o.agent}: {o.direction} ({o.confidence:.2f})" for o in opinions]
    trace.append(f"weighted vote score {score:+.2f} -> {action}")
    rules: list[str] = []
    revisit: int | None = None

    # T1 — hold for imminent long-term transition
    if (
        action in ("sell", "trim")
        and tax_op is not None
        and tax_op.direction == "hold"
        and tax.has_unrealized_gain
        and tax.days_to_longterm is not None
        and 0 < tax.days_to_longterm <= defer_days
    ):
        action = "hold"
        revisit = tax.days_to_longterm
        confidence = tax_op.confidence
        rules.append(f"T1: gains reach long-term treatment in {revisit}d — hold, then revisit")

    # T2 — never realize a loss into a wash sale
    if action in ("sell", "trim") and tax.has_unrealized_loss and tax.wash_sale_risk:
        action = "hold"
        rules.append(f"T2: wash-sale block ({tax.wash_sale_risk})")

    # T3 — partial harvest when tax wants it and the vote doesn't object
    if (
        action == "hold"
        and tax_op is not None
        and tax_op.direction in ("sell", "trim")
        and tax.has_unrealized_loss
        and not tax.wash_sale_risk
    ):
        action = "trim"
        confidence = tax_op.confidence
        rules.append("T3: tax-loss harvest nudge — partial trim")

    trace.extend(rules)
    return Decision(
        ticker=ticker,
        action=action,
        confidence=round(min(max(confidence, 0.0), 1.0), 3),
        rationale="; ".join(trace),
        revisit_days=revisit,
        rules_applied=[r.split(":")[0] for r in rules],
    )
