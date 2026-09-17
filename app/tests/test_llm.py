"""LLM layer: schema shaping, output budget + finish reason, json_repair salvage,
retry-with-strict, the Gemini wire shape."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from google.genai import errors
from pydantic import ValidationError

from app import config, llm
from app.llm import (
    CallStats,
    Completion,
    GeminiProvider,
    LlmProvider,
    OllamaProvider,
    TokenUsage,
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
    assert set(schema["$defs"]["Citation"]["properties"]) == {"source", "section", "quote"}
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


def _gemini(
    monkeypatch: pytest.MonkeyPatch, handler, model: str = "gemini-pinned"
) -> GeminiProvider:
    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(config, "GEMINI_MODEL", model)
    monkeypatch.setattr(config, "MAX_OUTPUT_TOKENS", 12345)
    return GeminiProvider()


def _answer(finish: str = "STOP") -> httpx.Response:
    # a thought summary precedes the answer, as it will once include_thoughts is switched on
    parts = [{"text": "weighing the requirements", "thought": True}, {"text": _TEXT}]
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 40,
                "thoughtsTokenCount": 25,
                "totalTokenCount": 165,
            },
        },
    )


def test_gemini_sends_schema_budget_and_thinking_level(monkeypatch: pytest.MonkeyPatch):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return _answer("MAX_TOKENS" if len(seen) == 2 else "STOP")

    p = _gemini(monkeypatch, handler)
    c = asyncio.run(p.complete("hi", llm_schema(RfpExtraction), 0.0, reasoning="low"))
    assert c.truncated is False and json.loads(c.text) == EXTRACT  # the thought stays out
    assert c.usage == TokenUsage(prompt=100, output=40, thinking=25, cached=0)
    req = seen[0]
    assert req.url.path.endswith("/models/gemini-pinned:generateContent")
    assert req.headers["x-goog-api-key"] == "k"
    body = json.loads(req.content)
    assert body["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]
    gen = body["generationConfig"]
    assert gen["temperature"] == 0.0 and gen["maxOutputTokens"] == 12345
    assert gen["responseMimeType"] == "application/json"
    assert gen["thinkingConfig"] == {"thinking_level": "LOW"}
    schema = gen["responseJsonSchema"]
    assert schema["propertyOrdering"] == ["requirements", "constraints", "suggestedWeights"]
    assert "default" not in json.dumps(schema) and "additionalProperties" not in schema

    c2 = asyncio.run(p.complete("hi", llm_schema(RfpExtraction), 0.0, strict=True))
    assert c2.truncated is True
    gen2 = json.loads(seen[1].content)["generationConfig"]
    assert gen2["responseJsonSchema"]["additionalProperties"] is False
    assert "thinkingConfig" not in gen2


def test_gemini_25_takes_a_thinking_budget(monkeypatch: pytest.MonkeyPatch):
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return _answer()

    p = _gemini(monkeypatch, handler, model="gemini-2.5-flash")
    asyncio.run(p.complete("hi", llm_schema(RfpExtraction), 0.0, reasoning="medium"))
    assert seen[0]["generationConfig"]["thinkingConfig"] == {"thinking_budget": 8192}


def test_gemini_retries_a_rate_limit_then_gives_up(monkeypatch: pytest.MonkeyPatch):
    hits: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(1)
        return (
            httpx.Response(429, json={"error": {"message": "quota"}})
            if len(hits) < 2
            else _answer()
        )

    monkeypatch.setattr(
        llm,
        "RETRY",
        llm.gt.HttpRetryOptions(
            attempts=2, initial_delay=0.001, max_delay=0.002, jitter=0.001, http_status_codes=[429]
        ),
    )
    p = _gemini(monkeypatch, handler)
    c = asyncio.run(p.complete("hi", llm_schema(RfpExtraction), 0.0))
    assert len(hits) == 2 and json.loads(c.text) == EXTRACT

    hits.clear()
    always = _gemini(monkeypatch, lambda req: (hits.append(1), httpx.Response(429, json={}))[1])
    with pytest.raises(errors.APIError):
        asyncio.run(always.complete("hi", llm_schema(RfpExtraction), 0.0))
    assert len(hits) == 2  # bounded: the original request plus one retry


def test_gemini_requires_a_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(RuntimeError):
        asyncio.run(GeminiProvider().complete("hi", {}, 0.0))


def test_gemini_reports_a_blocked_prompt(monkeypatch: pytest.MonkeyPatch):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    p = _gemini(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="SAFETY"):
        asyncio.run(p.complete("hi", llm_schema(RfpExtraction), 0.0))
