import json
import os
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .errors import ReviewError

T = TypeVar("T", bound=BaseModel)


class JsonProvider(Protocol):
    model: str

    def generate(self, schema: type[T], system: str, payload: dict) -> T: ...


def parse_output[T: BaseModel](
    schema: type[T], text: str | None, finish_reason: str | None = "STOP"
) -> T:
    if finish_reason != "STOP" or not text:
        raise ReviewError(
            "incomplete_response", "The model did not return a complete review.", 502, True
        )
    try:
        return schema.model_validate_json(text)
    except ValidationError as exc:
        raise ReviewError(
            "invalid_model_output", "The model response failed schema validation.", 502, True
        ) from exc


class GeminiProvider:
    def __init__(self):
        key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "").strip()
        if not key or not self.model:
            raise ReviewError(
                "configuration_error", "Set GEMINI_API_KEY and GEMINI_MODEL on the backend.", 503
            )
        try:
            from google import genai
            from google.genai import types

            timeout_ms = int(os.getenv("GEMINI_TIMEOUT_MS", "90000"))
            if not 1000 <= timeout_ms <= 300000:
                raise ValueError("Invalid timeout")
            self.client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(
                    timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=1)
                ),
            )
        except (ImportError, ValueError) as exc:
            raise ReviewError(
                "configuration_error", "Check the AI dependencies and timeout configuration.", 503
            ) from exc

    def close(self):
        self.client.close()

    def generate(self, schema: type[T], system: str, payload: dict) -> T:
        import httpx
        from google.genai import errors

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=json.dumps(payload, ensure_ascii=False),
                config={
                    "system_instruction": system,
                    "temperature": 0,
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "max_output_tokens": 24576,
                },
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise ReviewError(
                "model_timeout", "The model timed out. Please retry.", 504, True
            ) from exc
        except errors.APIError as exc:
            raise ReviewError(
                "model_api_error",
                "The model service could not complete the request.",
                502,
                getattr(exc, "code", 0) in (429, 500, 502, 503, 504),
            ) from exc
        except Exception as exc:
            raise ReviewError(
                "model_api_error", "Could not reach the model service.", 502, True
            ) from exc
        candidate = response.candidates[0] if response.candidates else None
        finish = getattr(getattr(candidate, "finish_reason", None), "value", None)
        return parse_output(schema, response.text, finish)
