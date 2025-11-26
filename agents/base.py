from typing import Any, Dict, List

import requests

from llm_config import (
    VLLM_API_KEY,
    VLLM_TIMEOUT,
    VLLM_BASE_URL,
    CHAT_MODEL_NAME,
)

class OpenAIStyleClient:
    """Low-level HTTP client for OpenAI-style /v1/chat/completions."""

    def __init__(self, base_url: str, model_name: str):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name

    def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if VLLM_API_KEY:
            headers["Authorization"] = f"Bearer {VLLM_API_KEY}"

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 256),
            "stream": False,
        }

        url = self.base_url + "/v1/chat/completions"
        resp = requests.post(url, headers=headers, json=payload, timeout=VLLM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        # Standard OpenAI-style result
        return data["choices"][0]["message"]["content"]
    

