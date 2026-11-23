"""Envio seguro a Telegram: HTML con respaldo a texto plano, RetryAfter y 'message is not modified'."""
from __future__ import annotations

import asyncio
import logging
import re

from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TelegramError

from ..telegram_utils import TG_MESSAGE_LIMIT, split_text

log = logging.getLogger(__name__)
_TAGS = re.compile(r"</?(?:b|i|u|s|a|code|pre|tg-spoiler)(?:\s[^>]*)?>")


def strip_html(s: str) -> str:
    import html
    return html.unescape(_TAGS.sub("", s))


async def _retry(fn, *a, **kw):
    for attempt in range(3):
        try:
            return await fn(*a, **kw)
        except RetryAfter as e:
            wait = min(float(getattr(e, "retry_after", 1)) + 0.5, 15)
            log.warning("RetryAfter %.0fs", wait)
            await asyncio.sleep(wait)
    return await fn(*a, **kw)


async def send_text(bot_or_msg, text: str, chat_id: int | None = None, reply_markup=None, **kw):
    """bot_or_msg: Message (usa reply_text) o Bot (con chat_id). Devuelve el ultimo mensaje enviado."""
    parts = split_text(text, TG_MESSAGE_LIMIT) or ["…"]
    last = None
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        call = (bot_or_msg.reply_text if chat_id is None else bot_or_msg.send_message)
        base = {} if chat_id is None else {"chat_id": chat_id}
        try:
            last = await _retry(call, part, parse_mode=ParseMode.HTML, reply_markup=markup,
                                disable_web_page_preview=True, **base, **kw)
        except BadRequest as e:
            if "parse" in str(e).lower() or "entities" in str(e).lower():
                last = await _retry(call, strip_html(part), reply_markup=markup, **base, **kw)
            else:
                raise
    return last


async def safe_edit(message, text: str, reply_markup=None) -> bool:
    """Edita un mensaje de texto; ignora 'message is not modified'. False si no se pudo."""
    try:
        await _retry(message.edit_text, text, parse_mode=ParseMode.HTML, reply_markup=reply_markup,
                     disable_web_page_preview=True)
        return True
    except BadRequest as e:
        s = str(e).lower()
        if "not modified" in s:
            return True
        if "parse" in s or "entities" in s:
            try:
                await _retry(message.edit_text, strip_html(text), reply_markup=reply_markup)
                return True
            except TelegramError:
                return False
        return False
    except TelegramError:
        return False
