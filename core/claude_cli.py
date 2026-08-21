"""Claude Code headless transport — LLM calls billed to the subscription.

The Anthropic API bills per token in cash; a Claude subscription bills a flat
fee and meters usage. `claude -p` (headless Claude Code) is the sanctioned way
to spend subscription quota programmatically — the same surface the official
GitHub Action uses — so this module shells out to it instead of the SDK when
LLM_TRANSPORT=claude_cli.

Two things make this viable that were not obvious up front:

- `--system-prompt` REPLACES Claude Code's own system prompt. Without it every
  invocation carries ~24K tokens of agent scaffolding; with it a call is ~500
  input tokens — lighter than the SDK path, not heavier.
- `--output-format json` wraps the result in an envelope that includes the
  full usage block, so llm_calls instrumentation keeps working unchanged.

What this transport cannot do is client.messages.parse()'s tool-enforced
structured output. The schema is stated in the system prompt instead, the
reply is validated with the same Pydantic model, and one retry carries the
validation error back. Weaker than the API guarantee — the retry and the
partial-failure policy in run_advise are the safety net.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from core.llm_log import Usage

CALL_TIMEOUT_S = 180
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def transport() -> str:
    """'api' (default) or 'claude_cli'."""
    return os.environ.get("LLM_TRANSPORT", "api").strip().lower()


def cli_available() -> bool:
    return shutil.which("claude") is not None


def strip_fences(text: str) -> str:
    """Models often wrap JSON in markdown fences despite instructions."""
    return _FENCE_RE.sub("", text.strip())


def extract_json(text: str) -> dict | None:
    """Best-effort: bare JSON, fenced JSON, or JSON embedded in prose."""
    for candidate in (text, strip_fences(text)):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def parse_envelope(stdout: str) -> tuple[str | None, Usage]:
    """(result_text, usage) from the --output-format json envelope."""
    envelope = extract_json(stdout)
    if not envelope:
        return None, Usage()
    usage_raw = envelope.get("usage") or {}
    usage = Usage(
        input_tokens=usage_raw.get("input_tokens", 0) or 0,
        output_tokens=usage_raw.get("output_tokens", 0) or 0,
        cache_creation_input_tokens=usage_raw.get("cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=usage_raw.get("cache_read_input_tokens", 0) or 0,
    )
    if envelope.get("is_error"):
        return None, usage
    result = envelope.get("result")
    return (result if isinstance(result, str) else None), usage


def schema_instruction(model_cls) -> str:
    """Schema stated in prose+JSON Schema, since there is no parse() here."""
    schema = json.dumps(model_cls.model_json_schema(), ensure_ascii=False)
    return (
        "\n\nRespond with ONLY a JSON object valid against this JSON Schema — "
        f"no prose, no markdown fences:\n{schema}"
    )


def _invoke(system_text: str, prompt: str, model: str) -> tuple[str | None, Usage]:
    proc = subprocess.run(
        ["claude", "-p", prompt,
         "--output-format", "json",
         "--model", model,
         "--system-prompt", system_text,
         "--disallowed-tools", "*",
         "--max-turns", "1"],
        capture_output=True, text=True, timeout=CALL_TIMEOUT_S,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        # stderr may carry auth guidance; keep it short and content-free.
        raise RuntimeError(f"claude CLI exited {proc.returncode}")
    return parse_envelope(proc.stdout)


def run_text(system_text: str, prompt: str, model: str) -> tuple[str | None, Usage]:
    return _invoke(system_text, prompt, model)


def run_structured(system_text: str, prompt: str, model_cls, model: str):
    """Returns (validated_model | None, Usage). One retry on bad JSON."""
    from pydantic import ValidationError

    system = system_text + schema_instruction(model_cls)
    total = Usage()

    def add(u: Usage) -> None:
        nonlocal total
        total = Usage(
            total.input_tokens + u.input_tokens,
            total.output_tokens + u.output_tokens,
            total.cache_creation_input_tokens + u.cache_creation_input_tokens,
            total.cache_read_input_tokens + u.cache_read_input_tokens,
        )

    attempt_prompt = prompt
    for _ in range(2):
        text, usage = _invoke(system, attempt_prompt, model)
        add(usage)
        payload = extract_json(text) if text else None
        if payload is not None:
            try:
                return model_cls.model_validate(payload), total
            except ValidationError as exc:
                error = str(exc)[:500]
        else:
            error = "response was not a JSON object"
        attempt_prompt = (
            f"{prompt}\n\nYour previous reply was rejected: {error}\n"
            "Reply again with ONLY the corrected JSON object."
        )
    return None, total
