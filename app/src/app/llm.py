"""LLM provider switch + validated JSON caller (BACKEND.md §10).

Ollama in test mode, any OpenAI-compatible chat endpoint in prod; `call_json` forces JSON,
validates against a Pydantic model and retries once with the validation errors appended.
"""

import json
import logging
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app import config

log = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

type JsonSchema = dict[str, Any]


class LlmProvider:
    name = "base"
    model = ""

    async def complete(
        self,
        prompt: str,
        temperature: float,
        json_mode: bool,
        schema: JsonSchema | None = None,
    ) -> str:
        raise NotImplementedError


class OllamaProvider(LlmProvider):
    name = "ollama"

    def __init__(self) -> None:
        self.model = config.OLLAMA_MODEL

    async def complete(
        self,
        prompt: str,
        temperature: float,
        json_mode: bool,
        schema: JsonSchema | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            # A JSON schema constrains decoding to the exact shape (Ollama structured
            # outputs); plain "json" only guarantees well-formed JSON.
            payload["format"] = schema or "json"
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"{config.OLLAMA_URL}/api/generate", json=payload)
            r.raise_for_status()
            return r.json()["response"]


class RemoteProvider(LlmProvider):
    """OpenAI-compatible chat endpoint (OpenRouter / Groq / Gemini compat)."""

    name = "remote"

    def __init__(self) -> None:
        self.model = config.REMOTE_MODEL

    async def complete(
        self,
        prompt: str,
        temperature: float,
        json_mode: bool,
        schema: JsonSchema | None = None,
    ) -> str:
        if not config.REMOTE_BASE_URL or not config.REMOTE_API_KEY or not self.model:
            raise RuntimeError(
                "REMOTE_* env not configured (REMOTE_BASE_URL, REMOTE_API_KEY, REMOTE_MODEL)"
            )
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {config.REMOTE_API_KEY}"}
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{config.REMOTE_BASE_URL}/chat/completions", json=body, headers=headers
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


def get_provider() -> LlmProvider:
    return RemoteProvider() if config.LLM_PROVIDER == "remote" else OllamaProvider()


def _strip(s: str) -> str:
    return _FENCE.sub("", s).strip()


async def call_json[T: BaseModel](
    provider: LlmProvider,
    prompt: str,
    model_cls: type[T],
    temperature: float | None = None,
) -> T:
    """Call the LLM, force JSON, validate against model_cls. Retry once on failure."""
    temp = config.TEMPERATURE if temperature is None else temperature
    schema = model_cls.model_json_schema()
    raw = await provider.complete(prompt, temp, json_mode=True, schema=schema)
    try:
        return model_cls.model_validate_json(_strip(raw))
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        log.warning(
            "LLM output for %s failed validation, retrying once: %s",
            model_cls.__name__,
            str(e)[:300],
        )
        retry = (
            prompt + "\n\nYour previous output was invalid. Return ONLY valid JSON "
            f"matching the schema. Do not add prose. Errors:\n{str(e)[:800]}"
        )
        raw2 = await provider.complete(retry, temp, json_mode=True, schema=schema)
        return model_cls.model_validate_json(_strip(raw2))
