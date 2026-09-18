"""LLM provider switch + validated JSON caller.

Gemini through the google-genai SDK by default, Ollama for offline tests. Every call is
structured: a JSON schema is *always* sent, the model name is pinned by env, temperature
defaults to 0, the output budget is explicit and the finish reason is checked. `call_json`
validates against the Pydantic model; a cut or malformed answer is first salvaged with
json_repair, then retried once with the errors appended and the schema tightened to strict
mode.
"""

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import json_repair
from google import genai
from google.genai import types as gt
from pydantic import BaseModel, ValidationError

from app import config

log = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
CODE_OWNED_FIELDS = {"grounding"}  # set by the grounding pass; never asked of the model

type JsonSchema = dict[str, Any]

# Tests inject an httpx.MockTransport here; None = real network.
_transport: httpx.AsyncBaseTransport | None = None


@dataclass
class TokenUsage:
    """Token counts as the provider reports them; thinking is billed as output."""

    prompt: int = 0
    output: int = 0
    thinking: int = 0
    cached: int = 0  # part of `prompt` served from cache, billed at the cached rate

    def add(self, other: "TokenUsage") -> None:
        self.prompt += other.prompt
        self.output += other.output
        self.thinking += other.thinking
        self.cached += other.cached


class Completion(NamedTuple):
    text: str
    truncated: bool  # the server stopped at the output budget (finish_reason == length)
    usage: TokenUsage | None = None


@dataclass
class CallStats:
    attempts: int = 0
    truncated: int = 0
    repaired: int = 0
    tokens: TokenUsage = field(default_factory=TokenUsage)

    def add(self, other: "CallStats") -> None:
        self.attempts += other.attempts
        self.truncated += other.truncated
        self.repaired += other.repaired
        self.tokens.add(other.tokens)


# ---- schema shaping ----------------------------------------------------------------------


def _strip_fields(node: Any, names: set[str]) -> None:
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            for n in names:
                props.pop(n, None)
            if "required" in node:
                node["required"] = [r for r in node["required"] if r not in names]
        for v in node.values():
            _strip_fields(v, names)
    elif isinstance(node, list):
        for v in node:
            _strip_fields(v, names)


def llm_schema(model_cls: type[BaseModel]) -> JsonSchema:
    """The Pydantic schema minus code-owned fields. Property order = field order."""
    schema = model_cls.model_json_schema()
    _strip_fields(schema, CODE_OWNED_FIELDS)
    return schema


_STRICT_BANNED = ("default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")


def _tighten(node: Any) -> None:
    if isinstance(node, dict):
        for k in _STRICT_BANNED:
            node.pop(k, None)
        props = node.get("properties")
        if isinstance(props, dict):
            node["additionalProperties"] = False
            node["required"] = list(props)
        for v in node.values():
            _tighten(v)
    elif isinstance(node, list):
        for v in node:
            _tighten(v)


def strict_schema(schema: JsonSchema) -> JsonSchema:
    """Strict shape for the retry: every property required, no additional properties, no
    numeric bounds or defaults (Pydantic still validates the bounds afterwards)."""
    out = copy.deepcopy(schema)
    _tighten(out)
    return out


def _for_gemini(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("default", None)
        if "$ref" in node:
            for k in [k for k in node if not k.startswith("$")]:
                del node[k]
        props = node.get("properties")
        if isinstance(props, dict):
            node["propertyOrdering"] = list(props)
        for v in node.values():
            _for_gemini(v)
    elif isinstance(node, list):
        for v in node:
            _for_gemini(v)


def gemini_schema(schema: JsonSchema) -> JsonSchema:
    """The schema as Gemini's JSON-schema subset takes it: no `default` (Pydantic applies
    defaults on validation anyway), nothing but `$` keys beside a `$ref`, and every object
    listing `propertyOrdering`, which is what keeps the answer in field order (findings
    before scores)."""
    out = copy.deepcopy(schema)
    _for_gemini(out)
    return out


# ---- providers ---------------------------------------------------------------------------


class LlmProvider:
    name = "base"
    model = ""

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema,
        temperature: float,
        strict: bool = False,
        reasoning: str | None = None,
    ) -> Completion:
        raise NotImplementedError


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=_transport)


class OllamaProvider(LlmProvider):
    name = "ollama"

    def __init__(self) -> None:
        self.model = config.OLLAMA_MODEL

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema,
        temperature: float,
        strict: bool = False,
        reasoning: str | None = None,
    ) -> Completion:
        # `format` = a JSON schema constrains decoding to the exact shape (and key order).
        # num_ctx: Ollama's default 4k context would silently truncate the *prompt*.
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "options": {
                "temperature": temperature,
                "num_ctx": config.OLLAMA_NUM_CTX,
                "num_predict": config.MAX_OUTPUT_TOKENS,
            },
        }
        async with _client(600) as c:
            r = await c.post(f"{config.OLLAMA_URL}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
            return Completion(data["response"], data.get("done_reason") == "length")


# Gemini 2.5 models take a token budget rather than a level; these are the budgets Google's
# OpenAI-compatible layer maps the same names to, so behaviour matches the previous provider.
_THINKING_BUDGET = {"minimal": 1024, "low": 1024, "medium": 8192, "high": 24576}

# A 429 in the middle of a demo is the failure that matters, and a rejected request costs
# no tokens: three bounded attempts with backoff, for rate limits and overload only.
RETRY = gt.HttpRetryOptions(
    attempts=3, initial_delay=2.0, max_delay=20.0, http_status_codes=[429, 503]
)


def _thinking(model: str, effort: str | None) -> gt.ThinkingConfig | None:
    if not effort:
        return None
    if effort not in _THINKING_BUDGET:
        raise ValueError(f"reasoning effort must be one of {list(_THINKING_BUDGET)}: {effort!r}")
    if model.startswith("gemini-2.5"):
        return gt.ThinkingConfig(thinking_budget=_THINKING_BUDGET[effort])
    return gt.ThinkingConfig(thinking_level=gt.ThinkingLevel[effort.upper()])


class GeminiProvider(LlmProvider):
    """Google Gemini through the google-genai SDK. The schema goes as the response JSON
    schema, the reasoning effort as the thinking level, and a cut answer is read off the
    finish reason. Thought summaries are not requested yet (`include_thoughts`); when they
    are, they arrive as parts flagged `thought` and stay out of the answer text below."""

    name = "gemini"

    def __init__(self) -> None:
        self.model = config.GEMINI_MODEL

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema,
        temperature: float,
        strict: bool = False,
        reasoning: str | None = None,
    ) -> Completion:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set (put it in .env)")
        cfg = gt.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=config.MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            response_json_schema=gemini_schema(strict_schema(schema) if strict else schema),
            thinking_config=_thinking(self.model, reasoning),
        )
        client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=gt.HttpOptions(
                timeout=180_000,
                retry_options=RETRY,
                async_client_args={"transport": _transport} if _transport else None,
            ),
        )
        try:
            r = await client.aio.models.generate_content(
                model=self.model, contents=prompt, config=cfg
            )
        finally:
            await client.aio.aclose()
        if not r.candidates:
            raise RuntimeError(f"Gemini returned no answer: {r.prompt_feedback}")
        cand = r.candidates[0]
        parts = (cand.content.parts if cand.content else None) or []
        text = "".join(p.text for p in parts if p.text and not p.thought)
        if cand.finish_reason == gt.FinishReason.MAX_TOKENS:
            log.warning(
                "gemini %s: answer cut at the output budget (%d tokens)",
                self.model,
                config.MAX_OUTPUT_TOKENS,
            )
        log.debug(
            "gemini %s: finish=%s, answer head: %s", self.model, cand.finish_reason, text[:300]
        )
        u = r.usage_metadata
        usage = (
            TokenUsage(
                prompt=u.prompt_token_count or 0,
                output=u.candidates_token_count or 0,
                thinking=u.thoughts_token_count or 0,
                cached=u.cached_content_token_count or 0,
            )
            if u
            else None
        )
        return Completion(text, cand.finish_reason == gt.FinishReason.MAX_TOKENS, usage)


def get_provider() -> LlmProvider:
    from app.replay import RecordingProvider, ReplayProvider  # replay imports this module

    if config.LLM_PROVIDER == "replay":
        return ReplayProvider()
    p = GeminiProvider() if config.LLM_PROVIDER == "gemini" else OllamaProvider()
    return RecordingProvider(p, Path(config.RECORD_DIR)) if config.RECORD_DIR else p


# ---- validated call ----------------------------------------------------------------------


def _strip(s: str) -> str:
    return _FENCE.sub("", s).strip()


def _parse[T: BaseModel](
    c: Completion, model_cls: type[T], stats: CallStats
) -> tuple[T | None, Exception | None]:
    text = _strip(c.text)
    if c.truncated:
        stats.truncated += 1
    try:
        return model_cls.model_validate_json(text), None
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        # Salvage: json_repair closes what was cut and fixes small syntax slips; the result
        # is a valid *prefix* of the answer. Validation still decides whether it is usable.
        try:
            repaired = json_repair.loads(text)
            value = model_cls.model_validate(repaired)
        except Exception:
            return None, e
        stats.repaired += 1
        return value, None


TRUNCATED_NOTE = (
    "\n\nYour previous output was cut off at the output limit. Return the same JSON but "
    "shorter: fewer words per field, quotes under 20 words, no repetition."
)
INVALID_NOTE = (
    "\n\nYour previous output was invalid. Return ONLY valid JSON matching the schema "
    "exactly. Do not add prose. Errors:\n{errors}"
)


async def call_json[T: BaseModel](
    provider: LlmProvider,
    prompt: str,
    model_cls: type[T],
    temperature: float | None = None,
    reasoning: str | None = None,
) -> tuple[T, CallStats]:
    """Call the LLM with model_cls's schema and validate. A cut or malformed answer is
    salvaged with json_repair when it still validates; otherwise retry once with the
    problem appended and the schema tightened to strict mode. Raises after the second."""
    temp = config.TEMPERATURE if temperature is None else temperature
    schema = llm_schema(model_cls)
    stats = CallStats()

    stats.attempts = 1
    c = await provider.complete(prompt, schema, temp, reasoning=reasoning)
    if c.usage:
        stats.tokens.add(c.usage)
    value, err = _parse(c, model_cls, stats)
    if value is not None:
        return value, stats

    log.warning(
        "LLM output for %s unusable (%s), retrying once (strict): %s",
        model_cls.__name__,
        "truncated" if c.truncated else "invalid",
        str(err)[:300],
    )
    note = TRUNCATED_NOTE if c.truncated else INVALID_NOTE.format(errors=str(err)[:800])
    stats.attempts = 2
    c2 = await provider.complete(prompt + note, schema, temp, strict=True, reasoning=reasoning)
    if c2.usage:
        stats.tokens.add(c2.usage)
    value, err = _parse(c2, model_cls, stats)
    if value is not None:
        return value, stats
    assert err is not None
    raise err
