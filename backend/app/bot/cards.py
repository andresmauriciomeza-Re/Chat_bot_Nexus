"""Tarjetas gamer: foto + titulo + precio USD/COP + descuento + veredicto + botones."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError

from ..games.pipeline import Reply
from ..games.render import render_game
from ..sources.models import GameInfo
from ..telegram_utils import esc
from . import callbacks as cbm
from .send import _retry, send_text

log = logging.getLogger(__name__)


def card_markup(owner: int, idx: int, g: GameInfo) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton("📖 Ficha", callback_data=cbm.make("fx", owner, str(idx)))]
    if g.deal_url:
        row1.append(InlineKeyboardButton("🛒 Ver oferta", url=g.deal_url))
    row2 = [InlineKeyboardButton("🔁 Similares", callback_data=cbm.make("sm", owner, str(idx))),
            InlineKeyboardButton("⚖️ Comparar", callback_data=cbm.make("cp", owner, str(idx)))]
    return InlineKeyboardMarkup([row1, row2])


async def send_card(bot, chat_id: int, owner: int, idx: int, g: GameInfo, trm: float | None) -> None:
    caption = render_game(g, trm, caption=True)
    markup = card_markup(owner, idx, g)
    photo = g.image or g.thumb
    if photo:
        try:
            await _retry(bot.send_photo, chat_id=chat_id, photo=photo, caption=caption,
                         parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        except (BadRequest, TelegramError) as e:      # foto invalida / caida: la tarjeta sale como texto
            log.warning("tarjeta sin foto (%s)", type(e).__name__)
    await send_text(bot, render_game(g, trm), chat_id=chat_id, reply_markup=markup)


async def send_reply(bot, chat_id: int, owner: int, reply: Reply, last, private: bool = True) -> None:
    """Responde con tarjetas en chats privados; en grupos, texto simple."""
    if reply.kind not in ("games", "compare") or not reply.games or not private:
        await send_text(bot, reply.text, chat_id=chat_id)
        return
    last.save(owner, chat_id, reply.kind, reply.games, reply.trm)
    if reply.intro:
        await send_text(bot, esc(reply.intro), chat_id=chat_id)
    for i, g in enumerate(reply.games):
        await send_card(bot, chat_id, owner, i, g, reply.trm)
    if reply.summary:
        await send_text(bot, reply.summary, chat_id=chat_id)
