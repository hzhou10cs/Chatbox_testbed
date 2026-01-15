# llm_config.py
"""
Central configuration for LLM usage in the health assistant app.

- UI_TEST_MODE: if True, do not call any real LLM, return dummy outputs.
- LLM_PROVIDER: "vllm" (default) or "openai".
- LLM_BASE_URL: base URL of the selected provider.
- LLM_API_KEY: API key for the selected provider (optional for local vLLM).
- BASE_MODEL_NAME: name/path of the underlying base model.
- CHAT_MODEL_NAME: logical model name for the chat agent (by default same as base).
- EXTRACTOR_MODEL_NAME: logical model name for the extractor agent (by default same as base).
"""

import os


def _bool_env(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "y"}


# If True, do not call any real LLM and always return dummy outputs.
UI_TEST_MODE: bool = _bool_env("UI_TEST_MODE", "false")

# Provider selection: "vllm" or "openai"
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "vllm").strip().lower()

# Base URL for your vLLM / OpenAI-compatible server
VLLM_BASE_URL: str = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

# OpenAI platform API configuration
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY", None)

# Underlying base model name/path
BASE_MODEL_NAME: str = os.getenv(
    "BASE_MODEL_NAME", "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
)

# Logical model names for different agents (for future LoRA use)
if LLM_PROVIDER == "openai":
    CHAT_MODEL_NAME: str = os.getenv("CHAT_MODEL_NAME", "gpt-3.5-turbo")
    EXTRACTOR_MODEL_NAME: str = os.getenv("EXTRACTOR_MODEL_NAME", "gpt-3.5-turbo")
else:
    CHAT_MODEL_NAME = os.getenv("CHAT_MODEL_NAME", BASE_MODEL_NAME)
    EXTRACTOR_MODEL_NAME = os.getenv("EXTRACTOR_MODEL_NAME", BASE_MODEL_NAME)

# Optional API keys
VLLM_API_KEY: str | None = os.getenv("VLLM_API_KEY", None)

# Unified provider settings used by the clients
if LLM_PROVIDER == "openai":
    LLM_BASE_URL: str = OPENAI_BASE_URL
    LLM_API_KEY: str | None = OPENAI_API_KEY
else:
    LLM_BASE_URL = VLLM_BASE_URL
    LLM_API_KEY = VLLM_API_KEY

# HTTP timeout
try:
    VLLM_TIMEOUT: float = float(os.getenv("VLLM_TIMEOUT", "60"))
except ValueError:
    VLLM_TIMEOUT = 60.0

# Unified timeout used by clients
LLM_TIMEOUT: float = VLLM_TIMEOUT
