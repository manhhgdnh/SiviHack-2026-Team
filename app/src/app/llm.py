"""LLM provider switch + validated JSON caller.

Ollama in test mode, any OpenAI-compatible chat endpoint (Gemini compat, OpenRouter, Groq)
in prod. Every call is structured: a JSON schema is *always* sent, the model name is pinned
by env, temperature defaults to 0, the output budget is explicit and the finish reason is
checked. `call_json` validates against the Pydantic model; a cut or malformed answer is
first salvaged with json_repair, then retried once with the errors appended and the schema
tightened to strict mode.
"""

import copy
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, NamedTuple

import httpx
import json_repair
from pydantic import BaseModel, ValidationError

from app import config

log = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
CODE_OWNED_FIELDS = {"grounding"}  # set by the grounding pass; never asked of the model

type JsonSchema = dict[str, Any]

# Tests inject an httpx.MockTransport here; None = real network.
_transport: httpx.AsyncBaseTransport | None = None
# Optional request features some OpenAI-compatible servers reject with HTTP 400. Remembered
# per process so we pay the failed request once, not on every call.
REMOTE_FEATURES = ("json_schema", "reasoning_effort")
_remote_disabled: set[str] = set()


class Completion(NamedTuple):
    text: str
    truncated: bool  # the server stopped at the output budget (finish_reason == length)


@dataclass
class CallStats:
    attempts: int = 0
    truncated: int = 0
    repaired: int = 0

    def add(self, other: "CallStats") -> None:
        self.attempts += other.attempts
        self.truncated += other.truncated
        self.repaired += other.repaired


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
    """OpenAI strict-mode shape: every property required, no additional properties, no
    numeric bounds or defaults (Pydantic still validates the bounds afterwards)."""
    out = copy.deepcopy(schema)
    _tighten(out)
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


class RemoteProvider(LlmProvider):
    """OpenAI-compatible chat endpoint (Gemini OpenAI-compat / OpenRouter / Groq)."""

    name = "remote"

    def __init__(self) -> None:
        self.model = config.REMOTE_MODEL

    def _body(
        self,
        prompt: str,
        schema: JsonSchema,
        temperature: float,
        strict: bool,
        reasoning: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": config.MAX_OUTPUT_TOKENS,
        }
        if "json_schema" not in _remote_disabled:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.get("title", "response"),
                    "schema": strict_schema(schema) if strict else schema,
                    "strict": strict,
                },
            }
        else:
            body["response_format"] = {"type": "json_object"}
        if reasoning and "reasoning_effort" not in _remote_disabled:
            body["reasoning_effort"] = reasoning
        return body

    async def complete(
        self,
        prompt: str,
        schema: JsonSchema,
        temperature: float,
        strict: bool = False,
        reasoning: str | None = None,
    ) -> Completion:
        if not config.REMOTE_BASE_URL or not config.REMOTE_API_KEY or not self.model:
            raise RuntimeError(
                "REMOTE_* env not configured (REMOTE_BASE_URL, REMOTE_API_KEY, REMOTE_MODEL)"
            )
        headers = {"Authorization": f"Bearer {config.REMOTE_API_KEY}"}
        url = f"{config.REMOTE_BASE_URL}/chat/completions"
        async with _client(180) as c:
            while True:
                body = self._body(prompt, schema, temperature, strict, reasoning)
                r = await c.post(url, json=body, headers=headers)
                if r.status_code == 400 and self._disable_feature(body, r.text):
                    continue  # one feature fewer; try again
                r.raise_for_status()
                choice = r.json()["choices"][0]
                return Completion(
                    choice["message"]["content"], choice.get("finish_reason") == "length"
                )

    @staticmethod
    def _disable_feature(body: dict[str, Any], error_text: str) -> bool:
        """On HTTP 400, switch off the optional feature the error names (or the first one
        still on). Returns False when nothing is left to switch off."""
        used = [
            f
            for f in REMOTE_FEATURES
            if f not in _remote_disabled
            and (f in body or body.get("response_format", {}).get("type") == f)
        ]
        if not used:
            return False
        low = error_text.lower()
        culprit = next((f for f in used if f.replace("_", "") in low.replace("_", "")), used[0])
        _remote_disabled.add(culprit)
        log.warning("remote rejected %s (%s); disabled for this process", culprit, error_text[:200])
        return True


def get_provider() -> LlmProvider:
    return RemoteProvider() if config.LLM_PROVIDER == "remote" else OllamaProvider()


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
    value, err = _parse(c2, model_cls, stats)
    if value is not None:
        return value, stats
    assert err is not None
    raise err
