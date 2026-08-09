"""Shared agent infrastructure: opinion schema, Claude call, DB persistence.

Each agent = one Claude API call with a role system prompt and a compact JSON
context. Structured output is enforced via client.messages.parse() with a
Pydantic schema, so opinions arrive validated — no hand parsing.

confidence is prompted as the PROBABILITY of the scored event (the position
beating — or for sell/trim, trailing — SPY over the stated timeframe), which
is what makes the Brier score in core/scoring.py a proper score (PLAN.md §4).
"""

from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import BaseModel, Field

from core.llm_log import CallRecord, Usage, measure_chars

DEFAULT_MODEL = "claude-sonnet-5"  # PLAN.md §3; override with MODEL_ID env
PROMPT_VERSION = "v1"

DISCLAIMER = (
    "You are one analysis agent inside a personal, informational-only advisory "
    "system. Your output is never investment advice; the user makes all decisions."
)

CONFIDENCE_RULE = (
    "confidence must be your calibrated probability (0-1) that this call scores "
    "a hit: for buy/add, the ticker outperforms SPY over the timeframe; for "
    "sell/trim, it underperforms SPY; for hold, it stays within a small band of "
    "SPY. Do not default to high confidence — your Brier score is tracked and "
    "overconfidence lowers your weight."
)


class Opinion(BaseModel):
    ticker: str = Field(description="Ticker symbol, uppercase")
    direction: Literal["buy", "hold", "sell", "trim", "add"]
    confidence: float = Field(ge=0, le=1)
    timeframe: Literal["days", "weeks", "months", "quarters"]
    rationale: str = Field(description="2-4 sentences, grounded in the provided data only")
    suggested_size_pct: float | None = Field(
        default=None, ge=0, le=100, description="Optional target portfolio weight in percent"
    )


class OpinionSet(BaseModel):
    opinions: list[Opinion]


def model_id() -> str:
    return os.environ.get("MODEL_ID") or DEFAULT_MODEL


def run_agent(
    system_prompt: str | list[dict],
    context: dict,
    *,
    system_knowledge_chars: int = 0,
) -> tuple[list[Opinion], CallRecord]:
    """One structured-output call; SDK retries transient errors itself.

    system_prompt may be a plain string or a list of content blocks — the latter
    is what lets the shared knowledge block carry a cache_control breakpoint
    while the per-agent role text follows it uncached.

    Returns the opinions alongside the call's token accounting, so the caller
    can log the cost without the agent module needing a DB handle.
    """
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model_id(),
        max_tokens=16000,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": json.dumps(context, default=str, ensure_ascii=False),
            }
        ],
        output_format=OpinionSet,
    )
    parsed = response.parsed_output
    record = CallRecord(
        usage=Usage.from_response(response),
        chars=measure_chars(
            system_prompt, context, system_knowledge_chars=system_knowledge_chars
        ),
        ok=parsed is not None,
    )
    return (parsed.opinions if parsed else []), record


def save_opinions(cur, run_id: int, agent: str, opinions: list[Opinion]) -> int:
    for op in opinions:
        cur.execute(
            """
            insert into agent_opinions
                (run_id, agent, ticker, direction, confidence, timeframe,
                 rationale, suggested_size_pct)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id, agent, ticker) do update
                set direction = excluded.direction,
                    confidence = excluded.confidence,
                    timeframe = excluded.timeframe,
                    rationale = excluded.rationale,
                    suggested_size_pct = excluded.suggested_size_pct
            """,
            (run_id, agent, op.ticker.upper(), op.direction, op.confidence,
             op.timeframe, op.rationale, op.suggested_size_pct),
        )
    return len(opinions)
