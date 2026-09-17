"""Environment configuration (BACKEND.md §3/§7).

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
REMOTE_BASE_URL = env("REMOTE_BASE_URL").rstrip("/")
REMOTE_API_KEY = env("REMOTE_API_KEY")
REMOTE_MODEL = env("REMOTE_MODEL")
TEMPERATURE = float(env("LLM_TEMPERATURE", "0.1"))
DROP_UNGROUNDED = _flag("DROP_UNGROUNDED", "false")  # false = keep + flag; true = drop
USE_CACHE = _flag("USE_CACHE", "true")  # cache RFP extraction on disk
