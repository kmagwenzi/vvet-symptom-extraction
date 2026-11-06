"""A minimal, provider-agnostic chat client.

Any provider that speaks the OpenAI chat-completions shape works: DeepSeek,
Groq, OpenRouter, Together, Ollama, vLLM, OpenAI itself. That keeps the
provider a configuration value instead of an architectural commitment, which is
what "any provider is fine" should mean in code.

response_format is deliberately NOT sent. Several compatible providers accept
the field and then ignore it, and some reject it; the prompt already asks for
JSON and the parser is built to survive a model that wraps its answer in prose
or a code fence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


class LLMError(RuntimeError):
    """The model could not be reached, or refused to answer."""


@dataclass(frozen=True)
class LLMClient:
    base_url: str
    api_key: str
    model: str
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "LLMClient":
        return cls(
            base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.getenv("LLM_API_KEY", ""),
            model=os.getenv("LLM_MODEL", DEFAULT_MODEL),
            timeout=float(os.getenv("LLM_TIMEOUT", "30")),
        )

    def complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise LLMError(
                "LLM_API_KEY is not set. Set it, or run with EXTRACTOR=rule for "
                "the offline extractor."
            )
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                url, json=payload, headers=headers, timeout=self.timeout
            )
        except httpx.HTTPError as exc:  # network, DNS, timeout
            raise LLMError(f"could not reach the model: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(
                f"model returned HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            body = response.json()
            return body["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected response shape from the model: {exc}") from exc
