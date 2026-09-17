"""Environment configuration.

The variable names are the contract; read once at import, exposed as module constants.
Load a .env locally with `uv run --env-file .env ...`; in Docker, compose passes it.
"""

import os


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _flag(key: str, default: str) -> bool:
    return env(key, default).strip().lower() == "true"


# gemini = Google Gemini through the google-genai SDK (the default); ollama = local test model.
LLM_PROVIDER = env("LLM_PROVIDER", "gemini")
OLLAMA_URL = env("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = env("OLLAMA_MODEL", "qwen2.5:7b")
# Ollama defaults to a 4k context; the scoring prompt alone is ~4k tokens, so without this
# the *input* gets truncated silently and the model answers a document it never saw.
OLLAMA_NUM_CTX = int(env("OLLAMA_NUM_CTX", "16384"))
# The key is the only value without a default: paste it into .env as GEMINI_API_KEY.
GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-3.8-flash")

TEMPERATURE = float(env("LLM_TEMPERATURE", "0"))  # 0 for run-to-run consistency
# Thinking tokens count against this on Gemini, so it must be generous or the JSON is
# cut before it starts. finish_reason is checked on every call regardless.
MAX_OUTPUT_TOKENS = int(env("LLM_MAX_OUTPUT_TOKENS", "16384"))
# Gemini thinking level: minimal / low / medium / high ("" = the model's default; Gemini 2.5
# models get the matching token budget instead). The schema and the call boundaries already
# fix the reasoning order, so scoring can run on low; coverage / constraint checks keep
# medium because they are where a wrong verdict hurts.
REASONING_EFFORT = env("LLM_REASONING_EFFORT", "low")
REASONING_EFFORT_COVERAGE = env("LLM_REASONING_EFFORT_COVERAGE", "medium")
# auto = split scoring into parallel calls on Gemini (latency ≈ 2a + max(2b)),
# one merged call on local Ollama (one GPU serialises calls and re-evaluates the prompt each
# time, so four calls are slower than one). true / false force it.
SPLIT_CALLS = env("LLM_SPLIT_CALLS", "auto").strip().lower()

DROP_UNGROUNDED = _flag(
    "DROP_UNGROUNDED", "true"
)  # true = drop unverified quotes; false = keep + flag
USE_CACHE = _flag("USE_CACHE", "true")  # cache every LLM call on disk (data/cache)
