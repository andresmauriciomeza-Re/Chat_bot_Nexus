from __future__ import annotations

import httpx
import openai
from openai import AsyncOpenAI

from .base import LLMRateLimitError, LLMResult, LLMTimeoutError, LLMUnavailableError

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider:
    """Groq via cliente OpenAI-compatible."""

    def __init__(self, api_key: str, model: str, timeout: float = 25.0,
                 http_client: httpx.AsyncClient | None = None, base_url: str = GROQ_BASE_URL):
        if not model:
            raise LLMUnavailableError("Falta GROQ_MODEL")
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout,
                                   max_retries=0, http_client=http_client)

    async def complete(self, messages: list[dict], max_tokens: int = 350, user: str | None = None) -> LLMResult:
        try:
            r = await self._client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=max_tokens, temperature=0.6)
        except openai.RateLimitError as e:
            raise LLMRateLimitError(str(type(e).__name__)) from None
        except openai.APITimeoutError:
            raise LLMTimeoutError("timeout") from None
        except (openai.APIConnectionError, openai.APIStatusError):
            raise LLMUnavailableError("no disponible") from None
        text = (r.choices[0].message.content or "").strip() if r.choices else ""
        if not text:
            raise LLMUnavailableError("respuesta vacia")
        tokens = getattr(getattr(r, "usage", None), "total_tokens", 0) or 0
        return LLMResult(text=text, tokens=tokens)
