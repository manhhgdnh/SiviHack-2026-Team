"""Environment configuration.

The variable names are the contract; read once at import, exposed as module constants.
Load a .env locally with `uv run --env-file .env ...`; in Docker, compose passes it.
"""

import os


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _flag(key: str, default: str) -> bool:
    return env(key, default).strip().lower() == "true"


LLM_PROVIDER = env("LLM_PROVIDER", "ollama")
OLLAMA_URL = env("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = env("OLLAMA_MODEL", "qwen2.5:7b")
# Ollama defaults to a 4k context; the scoring prompt alone is ~4k tokens, so without this
# the *input* gets truncated silently and the model answers a document it never saw.
OLLAMA_NUM_CTX = int(env("OLLAMA_NUM_CTX", "16384"))
REMOTE_BASE_URL = env("REMOTE_BASE_URL").rstrip("/")
REMOTE_API_KEY = env("REMOTE_API_KEY")
REMOTE_MODEL = env("REMOTE_MODEL")

TEMPERATURE = float(env("LLM_TEMPERATURE", "0"))  # 0 for run-to-run consistency
# Thinking tokens count against this on Gemini 2.5, so it must be generous or the JSON is
# cut before it starts. finish_reason is checked on every call regardless.
MAX_OUTPUT_TOKENS = int(env("LLM_MAX_OUTPUT_TOKENS", "16384"))
# reasoning_effort sent to OpenAI-compatible endpoints ("" = do not send). The schema and
# the call boundaries already fix the reasoning order, so scoring can run on low effort;
# coverage / constraint checks keep medium because they are where a wrong verdict hurts.
REASONING_EFFORT = env("LLM_REASONING_EFFORT", "low")
REASONING_EFFORT_COVERAGE = env("LLM_REASONING_EFFORT_COVERAGE", "medium")
# auto = split scoring into parallel calls on the remote provider (latency ≈ 2a + max(2b)),
# one merged call on local Ollama (one GPU serialises calls and re-evaluates the prompt each
# time, so four calls are slower than one). true / false force it.
SPLIT_CALLS = env("LLM_SPLIT_CALLS", "auto").strip().lower()

DROP_UNGROUNDED = _flag(
    "DROP_UNGROUNDED", "true"
)  # true = drop unverified quotes; false = keep + flag
USE_CACHE = _flag("USE_CACHE", "true")  # cache every LLM call on disk (data/cache)
