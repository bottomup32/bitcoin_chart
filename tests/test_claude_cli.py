"""Headless-transport plumbing: fence stripping, envelope parsing, schema note."""

import json

from agents.base import OpinionSet
from core.claude_cli import (
    extract_json,
    parse_envelope,
    schema_instruction,
    strip_fences,
    transport,
)
from core.llm_log import Usage


def test_transport_defaults_to_api(monkeypatch):
    monkeypatch.delenv("LLM_TRANSPORT", raising=False)
    assert transport() == "api"
    monkeypatch.setenv("LLM_TRANSPORT", "claude_cli")
    assert transport() == "claude_cli"


def test_strip_fences_handles_the_common_wrappers():
    body = '{"a": 1}'
    assert strip_fences(f"```json\n{body}\n```") == body
    assert strip_fences(f"```\n{body}\n```") == body
    assert strip_fences(body) == body


def test_extract_json_from_bare_fenced_and_embedded():
    body = {"opinions": []}
    text = json.dumps(body)
    assert extract_json(text) == body
    assert extract_json(f"```json\n{text}\n```") == body
    assert extract_json(f"Here you go:\n{text}\nHope that helps!") == body


def test_extract_json_rejects_non_objects_and_garbage():
    assert extract_json("[1, 2, 3]") is None
    assert extract_json("no json here") is None
    assert extract_json("{broken") is None


def envelope(**overrides) -> str:
    base = {
        "is_error": False,
        "result": '{"opinions": []}',
        "usage": {"input_tokens": 528, "output_tokens": 206,
                  "cache_creation_input_tokens": 10, "cache_read_input_tokens": 5},
    }
    base.update(overrides)
    return json.dumps(base)


def test_parse_envelope_returns_result_and_usage():
    text, usage = parse_envelope(envelope())
    assert text == '{"opinions": []}'
    assert usage == Usage(528, 206, 10, 5)


def test_parse_envelope_keeps_usage_on_error():
    """A failed call still costs input tokens — the bill must not hide it."""
    text, usage = parse_envelope(envelope(is_error=True))
    assert text is None
    assert usage.input_tokens == 528


def test_parse_envelope_survives_garbage():
    text, usage = parse_envelope("claude: command exploded")
    assert text is None and usage == Usage()


def test_schema_instruction_carries_the_actual_schema():
    note = schema_instruction(OpinionSet)
    assert "JSON Schema" in note
    for field in ("opinions", "direction", "confidence", "timeframe",
                  "used_knowledge_ids"):
        assert field in note
