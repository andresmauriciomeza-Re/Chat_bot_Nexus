"""Indicador «escribiendo/pensando» para operaciones que tardan (consultas a las fuentes)."""
from __future__ import annotations

import asyncio
import logging
import time

from telegram.constants import ChatAction

log = logging.getLogger(__name__)
SLOW_TEXT = "🤔 Dame un segundito, estoy mirando precios…"


async def with_typing(bot, chat_id: int, coro, slow_after: float = 6.0, slow_text: str | None = SLOW_TEXT,
                      interval: float = 4.0):
    """Ejecuta `coro` mostrando «escribiendo…»; si tarda mucho avisa una sola vez que sigue pensando."""
    task = asyncio.ensure_future(coro)
    start, warned = time.monotonic(), False
    try:
        while True:
            try:
                await bot.send_chat_action(chat_id, ChatAction.TYPING)
            except Exception:
                pass
            done, _ = await asyncio.wait({task}, timeout=interval)
            if done:
                return task.result()
            if slow_text and not warned and time.monotonic() - start >= slow_after:
                warned = True
                try:
                    await bot.send_message(chat_id=chat_id, text=slow_text)
                except Exception:
                    pass
    finally:
        if not task.done():
            task.cancel()
