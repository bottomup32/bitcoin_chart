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

from core.claude_cli import run_structured, transport
from core.llm_log import CallRecord, Usage, measure_chars, system_text

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
    used_knowledge_ids: list[int] = Field(
        default_factory=list,
        description="Ordinals from the `knowledge` block that actually changed this "
                    "call; empty if none did. Do not cite a principle you merely read.",
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

    LLM_TRANSPORT=claude_cli routes the call through headless Claude Code
    (core/claude_cli.py) so it draws on the subscription instead of API
    billing; the default stays the SDK with tool-enforced structured output.
    """
    chars = measure_chars(
        system_prompt, context, system_knowledge_chars=system_knowledge_chars
    )
    prompt = json.dumps(context, default=str, ensure_ascii=False)

    if transport() == "claude_cli":
        parsed, usage = run_structured(
            system_text(system_prompt), prompt, OpinionSet, model_id()
        )
        record = CallRecord(usage=usage, chars=chars, ok=parsed is not None)
        return (parsed.opinions if parsed else []), record

    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model_id(),
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
        output_format=OpinionSet,
    )
    parsed = response.parsed_output
    record = CallRecord(
        usage=Usage.from_response(response),
        chars=chars,
        ok=parsed is not None,
    )
    return (parsed.opinions if parsed else []), record


def save_opinions(
    cur,
    run_id: int,
    agent: str,
    opinions: list[Opinion],
    shown_chunks: list[dict] | None = None,
) -> int:
    """Persist opinions and, when knowledge was shown, what it was used for.

    shown_chunks are the chunks this agent saw, in the order their ordinals were
    presented, so ordinal N maps to shown_chunks[N-1]. Small local ordinals are
    cheaper than DB ids in the prompt and remove the temptation to hallucinate
    plausible-looking large integers.
    """
    for op in opinions:
        cur.execute(
            """
            insert into agent_opinions
                (run_id, agent, ticker, direction, confidence, timeframe,
                 rationale, suggested_size_pct, ref_source_ids)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id, agent, ticker) do update
                set direction = excluded.direction,
                    confidence = excluded.confidence,
                    timeframe = excluded.timeframe,
                    rationale = excluded.rationale,
                    suggested_size_pct = excluded.suggested_size_pct,
                    ref_source_ids = excluded.ref_source_ids
            returning id
            """,
            (run_id, agent, op.ticker.upper(), op.direction, op.confidence,
             op.timeframe, op.rationale, op.suggested_size_pct,
             sorted(_cited_sources(op, shown_chunks))),
        )
        opinion_id = cur.fetchone()[0]
        _save_refs(cur, opinion_id, op, shown_chunks)
    return len(opinions)


def _cited_chunks(op: Opinion, shown_chunks: list[dict] | None) -> list[dict]:
    if not shown_chunks:
        return []
    return [
        shown_chunks[n - 1]
        for n in dict.fromkeys(op.used_knowledge_ids)  # dedupe, keep order
        if 1 <= n <= len(shown_chunks)
    ]


def _cited_sources(op: Opinion, shown_chunks: list[dict] | None) -> set[int]:
    return {c["source_id"] for c in _cited_chunks(op, shown_chunks)}


def _save_refs(cur, opinion_id: int, op: Opinion, shown_chunks: list[dict] | None) -> None:
    if not shown_chunks:
        return
    # A FORCE_ADVISE re-run may have retrieved a different set of chunks, so
    # clear before rewriting rather than leaving a stale union behind.
    cur.execute("delete from opinion_knowledge_refs where opinion_id = %s", (opinion_id,))
    cited = {c["id"] for c in _cited_chunks(op, shown_chunks)}
    for chunk in shown_chunks:
        cur.execute(
            """
            insert into opinion_knowledge_refs (opinion_id, chunk_id, shown, cited)
            values (%s, %s, true, %s)
            on conflict (opinion_id, chunk_id) do update set cited = excluded.cited
            """,
            (opinion_id, chunk["id"], chunk["id"] in cited),
        )
