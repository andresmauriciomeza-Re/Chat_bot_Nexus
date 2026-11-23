from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """Error base del proveedor LLM."""


class LLMRateLimitError(LLMError): ...
class LLMTimeoutError(LLMError): ...
class LLMUnavailableError(LLMError): ...


@dataclass(slots=True)
class LLMResult:
    text: str
    tokens: int = 0


class LLMProvider(Protocol):
    async def complete(self, messages: list[dict], max_tokens: int = 350) -> LLMResult: ...
