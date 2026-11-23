"""Modo inline: @bot nombre del juego. Con limites, sin LLM y con riesgo/guardia => sin resultados."""
from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle,
                      InlineQueryResultsButton, InputTextMessageContent, Update)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, InlineQueryHandler

from ..analysis.analyzer import analyze
from ..games.render import fmt_cop, render_game
from ..sources.cheapshark import ATTRIBUTION
from ..telegram_utils import esc, truncate

log = logging.getLogger(__name__)
MIN_Q, MAX_Q = 2, 60


class RateLimiter:
    def __init__(self, per_minute: int, clock=time.monotonic):
        self.n, self.clock = per_minute, clock
        self._d: dict[int, deque] = defaultdict(deque)

    def allow(self, user: int) -> bool:
        now, q = self.clock(), self._d[user]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.n:
            return False
        q.append(now)
        return True


def desc_line(g, trm) -> str:
    bits = []
    if g.sale_usd is not None:
        bits.append("Gratis" if g.sale_usd == 0 else f"USD {g.sale_usd:.2f}")
        if g.sale_usd and trm:
            bits.append(f"≈ COP {fmt_cop(round(g.sale_usd * trm, -2))}")
    if g.discount_pct:
        bits.append(f"-{g.discount_pct}%")
    return " · ".join(bits) or "Sin precio ahora"


def install_inline(app: Application, h) -> None:
    s, svc, safety = h.s, h.svc, h.safety
    limiter = RateLimiter(s.inline_rate_per_min)
    btn = InlineQueryResultsButton(text="Abrir NEXUS-IA", start_parameter="inline")

    async def on_inline(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.inline_query
        uid = q.from_user.id
        text = " ".join((q.query or "").split())[:MAX_Q]

        async def reply(results, cache=30):
            try:
                await q.answer(results, cache_time=cache, is_personal=False, button=btn)
            except TelegramError as e:
                log.warning("inline answer fallo (%s)", type(e).__name__)

        if (len(text) < MIN_Q or s.maintenance_mode or safety.active(uid) or analyze(text).risky
                or not limiter.allow(uid)):
            await reply([], cache=5)                 # sin resultados; el apoyo emocional solo va en privado
            return
        deals = await svc._safe(svc.cs.deals(title=text, on_sale=False, limit=s.inline_max_results * 2)) \
            if s.cheapshark_enabled else []
        trm = await svc.cop_per_usd()
        results, seen = [], set()
        for g in deals or []:
            if g.title in seen:
                continue
            seen.add(g.title)
            body = render_game(g, trm) + f"\n\n<i>{ATTRIBUTION}</i>"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Ver oferta", url=g.deal_url)]]) if g.deal_url else None
            rid = hashlib.md5(f"{g.game_id or g.title}".encode()).hexdigest()[:24]
            results.append(InlineQueryResultArticle(
                id=rid, title=truncate(g.title, 60), description=desc_line(g, trm),
                thumbnail_url=g.thumb if g.thumb and g.thumb.startswith("https://") else None,
                input_message_content=InputTextMessageContent(body, parse_mode=ParseMode.HTML,
                                                              link_preview_options=None),
                reply_markup=kb))
            if len(results) >= s.inline_max_results:
                break
        await reply(results)

    if s.inline_enabled:
        app.add_handler(InlineQueryHandler(on_inline))
    h.on_inline = on_inline
