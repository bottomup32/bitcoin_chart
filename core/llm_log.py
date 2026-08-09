"""Token accounting for every LLM call (memory plan, 증분 0).

Two jobs, kept apart from the agents themselves so both agents/base.py and
core/orchestrator.py can share them:

  measure_chars()  — exact, free, computed at prompt-assembly time. Gives the
                     denominator for attributing input tokens across memory
                     blocks (knowledge / short-term / long-term).
  record_call()    — one llm_calls row per API call, including failures: a
                     refusal still costs input tokens, and a run whose failed
                     calls are invisible under-reports its own bill.

Nothing here stores prompt or response content. The repo is public and the
prompts are holdings-derived, so the table holds counts only (PLAN.md §6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# Context keys that carry memory. `recent` is short-term memory's key (the
# compact columns+rows encoding); `knowledge` and `long_term` are literal.
SHORT_TERM_KEY = "recent"
KNOWLEDGE_KEY = "knowledge"
LONG_TERM_KEY = "long_term"


@dataclass(frozen=True)
class Usage:
    """The four token counters the Messages API reports back."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_response(cls, response) -> Usage:
        """Tolerant of missing fields — a stub or an older SDK still logs zeros."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return cls()
        return cls(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )


@dataclass(frozen=True)
class CallRecord:
    """What one API call cost, plus how its prompt was composed."""

    usage: Usage = field(default_factory=Usage)
    chars: dict[str, int] = field(default_factory=dict)
    ok: bool = True


def _dumps(value) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def system_text(system: str | list[dict]) -> str:
    """Flatten a system prompt given either as a string or as content blocks."""
    if isinstance(system, str):
        return system
    return "".join(block.get("text", "") for block in system)


def measure_chars(
    system: str | list[dict],
    context: dict,
    *,
    system_knowledge_chars: int = 0,
) -> dict[str, int]:
    """Serialized character counts for the whole prompt and its memory blocks.

    Characters, not tokens, because they are exact and cost nothing to compute.
    The response's input_tokens is the ground truth for the total; llm_cost_daily
    splits that total across blocks in proportion to these counts.

    system_knowledge_chars covers the shared `core` knowledge block that lives in
    the system prompt rather than in the context dict.
    """

    def block(key: str) -> int:
        value = context.get(key)
        return len(_dumps(value)) if value else 0

    return {
        "total": len(system_text(system)) + len(_dumps(context)),
        "knowledge": block(KNOWLEDGE_KEY) + system_knowledge_chars,
        "short_term": block(SHORT_TERM_KEY),
        "long_term": block(LONG_TERM_KEY),
    }


def usage_line(usage: Usage) -> str:
    """One-line summary for job logs — counts only, never content."""
    return (
        f"tokens in={usage.input_tokens} out={usage.output_tokens} "
        f"cache_write={usage.cache_creation_input_tokens} "
        f"cache_read={usage.cache_read_input_tokens}"
    )


def record_call(
    cur,
    *,
    run_id: int | None,
    purpose: str,
    model_id: str,
    prompt_version: str | None,
    record: CallRecord,
) -> None:
    """Insert one llm_calls row. Caller owns the transaction."""
    chars = record.chars
    cur.execute(
        """
        insert into llm_calls
            (run_id, purpose, model_id, prompt_version,
             input_tokens, output_tokens,
             cache_creation_input_tokens, cache_read_input_tokens,
             chars_total, chars_knowledge, chars_short_term, chars_long_term, ok)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            run_id, purpose, model_id, prompt_version,
            record.usage.input_tokens, record.usage.output_tokens,
            record.usage.cache_creation_input_tokens, record.usage.cache_read_input_tokens,
            chars.get("total", 0), chars.get("knowledge", 0),
            chars.get("short_term", 0), chars.get("long_term", 0),
            record.ok,
        ),
    )
