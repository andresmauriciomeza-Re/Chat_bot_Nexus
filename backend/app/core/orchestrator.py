from __future__ import annotations

import logging

from ..llm.base import LLMError, LLMProvider, LLMRateLimitError, LLMTimeoutError
from ..llm.budget import LLMBudgetError
from .memory import ConversationMemory

log = logging.getLogger(__name__)

MSG_RATE = "Uy, estoy con muchas consultas ahorita. Dame un ratico y me escribes de nuevo."
MSG_TIMEOUT = "Me demoré demasiado pensando. ¿Me lo repites?"
MSG_DOWN = "Ahorita no puedo conectarme con mi cerebro. Intenta en unos minutos; los precios y ofertas sí te los puedo mirar."
MSG_EMPTY = "Escríbeme algo y te ayudo."
MSG_QUOTA_USER = ("Hoy ya gastaste tu cupo de charla conmigo 😅. Mañana se renueva. Mientras tanto sigo con precios y "
                  "ofertas: dime el nombre de un juego o usa /gratis.")
MSG_QUOTA_GLOBAL = ("Hoy ya llegué a mi límite de charla con el cerebro 🤖. Los precios, ofertas y /gratis siguen "
                    "funcionando; la charla vuelve mañana.")
MSG_COOLDOWN = "Estoy recuperando el aliento (muchas consultas a la vez). Prueba otra vez en un momentico."


class Orchestrator:
    def __init__(self, llm: LLMProvider, system_prompt: str, memory: ConversationMemory | None = None,
                 history_limit: int = 12, max_tokens: int = 350):
        self.llm, self.system_prompt = llm, system_prompt
        self.memory = memory or ConversationMemory()
        self.history_limit, self.max_tokens = history_limit, max_tokens

    async def ask(self, key: str, text: str, facts: str | None = None, store: bool = True,
                  max_tokens: int | None = None) -> tuple[str | None, str | None]:
        """(respuesta, mensaje_fijo). Exactamente uno de los dos es None."""
        text = (text or "").strip()
        if not text:
            return None, MSG_EMPTY
        sys_msgs = [{"role": "system", "content": self.system_prompt}]
        if facts:
            sys_msgs.append({"role": "system", "content": "DATOS VERIFICADOS (no inventes otros):\n" + facts})
        msgs = [*sys_msgs, *self.memory.get(key, self.history_limit), {"role": "user", "content": text}]
        try:
            res = await self.llm.complete(msgs, max_tokens=max_tokens or self.max_tokens, user=key)
        except LLMBudgetError as e:
            return None, {"user": MSG_QUOTA_USER, "global": MSG_QUOTA_GLOBAL}.get(e.reason, MSG_COOLDOWN)
        except LLMRateLimitError:
            return None, MSG_RATE
        except LLMTimeoutError:
            return None, MSG_TIMEOUT
        except LLMError:
            return None, MSG_DOWN
        if store:
            self.memory.add(key, "user", text)
            self.memory.add(key, "assistant", res.text)
        return res.text, None

    async def handle(self, key: str, text: str, facts: str | None = None) -> str:
        ans, msg = await self.ask(key, text, facts)
        return ans if ans is not None else (msg or MSG_DOWN)

    async def narrate(self, key: str, instruction: str, facts: str) -> str | None:
        """Redaccion corta sobre datos ya calculados. None si el modelo no esta disponible."""
        ans, _ = await self.ask(key, instruction, facts=facts, store=False, max_tokens=160)
        return ans

    def reset(self, key: str) -> None:
        self.memory.clear(key)
