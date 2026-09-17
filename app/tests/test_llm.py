"""LLM layer: schema shaping, output budget + finish reason, json_repair salvage,
retry-with-strict, provider feature fallback."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app import config, llm
from app.llm import (
    CallStats,
    Completion,
    LlmProvider,
    OllamaProvider,
    RemoteProvider,
    call_json,
    llm_schema,
    strict_schema,
)
from app.schema import GroupLlmOutput, RfpExtraction, ScoreLlmOutput

EXTRACT: dict[str, Any] = {
    "requirements": [{"id": "r1", "label": "x", "rfpQuote": "q", "section": None}],
    "constraints": [],
    "suggestedWeights": [],
}
_TEXT = json.dumps(EXTRACT)
GOOD = Completion("```json\n" + _TEXT + "\n```", False)
BAD = Completion('```json\n{"requirements": [{"id": 1', False)
# cut right after `"constraints": [` — json_repair closes it into a valid, shorter answer
CUT = Completion(_TEXT[: _TEXT.index('"constraints": [') + len('"constraints": [')], True)
# cut inside the first requirement — nothing json_repair produces will validate
HOPELESS = Completion('{"requirements": [{"id": "r1", "label": "x", "rfpQ', True)


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


# ---- schema shaping ----------------------------------------------------------------------


def test_llm_schema_hides_code_owned_fields_and_keeps_reasoning_order():
    schema = llm_schema(ScoreLlmOutput)
    for node in _walk(schema):
        assert "grounding" not in node.get("properties", {})
        assert "grounding" not in node.get("required", [])
    assert list(schema["properties"]) == ["coverage", "constraintViolations", "findings", "scores"]
    assert list(llm_schema(GroupLlmOutput)["properties"]) == ["findings", "scores"]
    cs = schema["$defs"]["CriterionScore"]
    assert "score" in cs["required"]  # required-but-nullable: the model must write null
    assert {"type": "null"} in cs["properties"]["score"]["anyOf"]
    # citations are section pointers, not sentences
    assert set(schema["$defs"]["Citation"]["properties"]) == {"source", "section"}
    cov = schema["$defs"]["CoverageItem"]["required"]
    assert {"proposalSection", "proposalQuote", "explanation", "fix"} <= set(cov)


def test_strict_schema_is_openai_strict_compatible():
    strict = strict_schema(llm_schema(ScoreLlmOutput))
    for node in _walk(strict):
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])
        for banned in ("default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            assert banned not in node
    assert "additionalProperties" not in llm_schema(ScoreLlmOutput)  # original untouched


# ---- call_json ---------------------------------------------------------------------------


class Scripted(LlmProvider):
    """Returns the scripted completions in order; records (prompt, strict, reasoning)."""

    name, model = "scripted", "scripted-model"

    def __init__(self, *completions: Completion):
        self.queue = list(completions)
        self.calls: list[tuple[str, bool, str | None]] = []

    async def complete(self, prompt, schema, temperature, strict=False, reasoning=None):
        self.calls.append((prompt, strict, reasoning))
        return self.queue.pop(0)


def test_call_json_passes_reasoning_and_reports_stats():
    p = Scripted(GOOD)
    out, stats = asyncio.run(call_json(p, "prompt", RfpExtraction, reasoning="low"))
    assert len(out.requirements) == 1 and stats == CallStats(attempts=1)
    assert p.calls == [("prompt", False, "low")]


def test_call_json_salvages_a_truncated_output_and_counts_it():
    p = Scripted(CUT)
    out, stats = asyncio.run(call_json(p, "prompt", RfpExtraction))
    assert len(out.requirements) == 1 and out.constraints == []
    assert stats == CallStats(attempts=1, truncated=1, repaired=1)
    assert len(p.calls) == 1  # no retry needed


def test_call_json_retries_once_with_strict_schema_then_raises():
    p = Scripted(BAD, GOOD)
    out, stats = asyncio.run(call_json(p, "prompt", RfpExtraction, reasoning="low"))
    assert len(out.requirements) == 1 and stats.attempts == 2
    assert [(s, r) for _, s, r in p.calls] == [(False, "low"), (True, "low")]
    assert "previous output was invalid" in p.calls[1][0] and p.calls[1][0].startswith("prompt")
    with pytest.raises(ValidationError):
        asyncio.run(call_json(Scripted(BAD, BAD), "prompt", RfpExtraction))


def test_unrepairable_truncation_retries_asking_for_brevity():
    p = Scripted(HOPELESS, GOOD)
    out, stats = asyncio.run(call_json(p, "prompt", RfpExtraction))
    assert len(out.requirements) == 1
    assert stats == CallStats(attempts=2, truncated=1, repaired=0)
    assert "cut off" in p.calls[1][0] and p.calls[1][1] is True


# ---- providers ---------------------------------------------------------------------------


def test_ollama_sends_schema_output_budget_and_context(monkeypatch: pytest.MonkeyPatch):
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"response": _TEXT, "done_reason": "length"})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(config, "OLLAMA_MODEL", "pinned:7b")
    monkeypatch.setattr(config, "OLLAMA_NUM_CTX", 8192)
    monkeypatch.setattr(config, "MAX_OUTPUT_TOKENS", 4096)
    c = asyncio.run(OllamaProvider().complete("hi", llm_schema(RfpExtraction), 0.0))
    assert c.truncated is True and json.loads(c.text) == EXTRACT
    body = seen[0]
    assert body["model"] == "pinned:7b" and body["stream"] is False
    assert body["options"] == {"temperature": 0.0, "num_ctx": 8192, "num_predict": 4096}
    assert body["format"]["properties"].keys() == {
        "requirements",
        "constraints",
        "suggestedWeights",
    }


def _remote(monkeypatch: pytest.MonkeyPatch, handler) -> RemoteProvider:
    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(llm, "_remote_disabled", set())
    monkeypatch.setattr(config, "REMOTE_BASE_URL", "http://llm.test/v1")
    monkeypatch.setattr(config, "REMOTE_API_KEY", "k")
    monkeypatch.setattr(config, "REMOTE_MODEL", "gemini-pinned")
    monkeypatch.setattr(config, "MAX_OUTPUT_TOKENS", 12345)
    return RemoteProvider()


def _ok(finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": _TEXT}, "finish_reason": finish}]}
    )


def test_remote_sends_budget_reasoning_and_json_schema(monkeypatch: pytest.MonkeyPatch):
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return _ok("length" if len(seen) == 2 else "stop")

    p = _remote(monkeypatch, handler)
    c = asyncio.run(p.complete("hi", llm_schema(RfpExtraction), 0.0, reasoning="low"))
    assert c.truncated is False and json.loads(c.text) == EXTRACT
    body = seen[0]
    assert body["model"] == "gemini-pinned" and body["temperature"] == 0.0
    assert body["max_tokens"] == 12345 and body["reasoning_effort"] == "low"
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is False
    assert "additionalProperties" not in rf["json_schema"]["schema"]

    c2 = asyncio.run(p.complete("hi", llm_schema(RfpExtraction), 0.0, strict=True))
    assert c2.truncated is True
    rf2 = seen[1]["response_format"]["json_schema"]
    assert rf2["strict"] is True and rf2["schema"]["additionalProperties"] is False
    assert "reasoning_effort" not in seen[1]


def test_remote_disables_the_rejected_feature_and_remembers_it(monkeypatch: pytest.MonkeyPatch):
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body)
        if "reasoning_effort" in body:
            return httpx.Response(
                400, json={"error": {"message": "Unknown parameter: reasoning_effort"}}
            )
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(
                400, json={"error": "response_format.json_schema is not supported"}
            )
        return _ok()

    p = _remote(monkeypatch, handler)
    c = asyncio.run(p.complete("hi", llm_schema(RfpExtraction), 0.0, reasoning="low"))
    assert json.loads(c.text) == EXTRACT
    assert [b["response_format"]["type"] for b in seen] == [
        "json_schema",
        "json_schema",
        "json_object",
    ]
    assert "reasoning_effort" in seen[0] and "reasoning_effort" not in seen[1]
    assert llm._remote_disabled == {"reasoning_effort", "json_schema"}
    # remembered: the next call is right first time
    asyncio.run(p.complete("again", llm_schema(RfpExtraction), 0.0, reasoning="low"))
    assert len(seen) == 4
    assert (
        seen[-1]["response_format"] == {"type": "json_object"}
        and "reasoning_effort" not in seen[-1]
    )


def test_remote_gives_up_on_a_400_it_cannot_explain(monkeypatch: pytest.MonkeyPatch):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "prompt too long"})

    p = _remote(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(p.complete("hi", llm_schema(RfpExtraction), 0.0, reasoning="low"))
    assert llm._remote_disabled == {"reasoning_effort", "json_schema"}  # tried both, then raised


def test_remote_requires_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "REMOTE_BASE_URL", "")
    with pytest.raises(RuntimeError):
        asyncio.run(RemoteProvider().complete("hi", {}, 0.0))
