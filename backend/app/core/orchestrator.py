from __future__ import annotations

import logging

from ..llm.base import LLMError, LLMProvider, LLMRateLimitError, LLMTimeoutError
from .memory import ConversationMemory

log = logging.getLogger(__name__)

MSG_RATE = "Uy, estoy con muchas consultas ahorita. Dame un ratico y me escribes de nuevo."
MSG_TIMEOUT = "Me demoré demasiado pensando. ¿Me lo repites?"
MSG_DOWN = "Ahorita no puedo conectarme con mi cerebro. Intenta en unos minutos."
MSG_EMPTY = "Escríbeme algo y te ayudo."


class Orchestrator:
    def __init__(self, llm: LLMProvider, system_prompt: str, memory: ConversationMemory | None = None,
                 history_limit: int = 12, max_tokens: int = 350):
        self.llm, self.system_prompt = llm, system_prompt
        self.memory = memory or ConversationMemory()
        self.history_limit, self.max_tokens = history_limit, max_tokens

    async def handle(self, key: str, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return MSG_EMPTY
        msgs = [{"role": "system", "content": self.system_prompt},
                *self.memory.get(key, self.history_limit),
                {"role": "user", "content": text}]
        try:
            res = await self.llm.complete(msgs, max_tokens=self.max_tokens)
        except LLMRateLimitError:
            return MSG_RATE
        except LLMTimeoutError:
            return MSG_TIMEOUT
        except LLMError:
            return MSG_DOWN
        self.memory.add(key, "user", text)
        self.memory.add(key, "assistant", res.text)
        return res.text

    def reset(self, key: str) -> None:
        self.memory.clear(key)
