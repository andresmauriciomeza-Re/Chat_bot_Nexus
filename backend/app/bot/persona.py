"""Instala Fase 7: la mascota habla (charla, consejos con datos, reacciones en momentos clave, 💡 Consejo)."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton

from .. import personality as P
from ..games.render import render_game
from ..sources.cheapshark import ATTRIBUTION
from ..telegram_utils import esc
from . import callbacks as cbm
from .panel import View, ViewCtx

log = logging.getLogger(__name__)


def install_persona(app, h) -> None:
    A, s = h.A, h.s
    reactions = P.Reactions()
    A["reactions"] = reactions
    h.erasers.append(reactions.forget)
    A["pipe"].persona = s.mascot_voice_enabled

    async def react(update, event: str) -> None:
        """Mascota con una frase corta; solo eventos clave, con enfriamiento, nunca con riesgo, y solo si hay archivo."""
        if not (s.mascot_voice_enabled and event):
            return
        uid, chat = update.effective_user.id, update.effective_chat.id
        if A["safety"].active(uid) or not h.is_private(update):
            return
        mascot = A["mascot"]
        name = P.EVENT_MASCOT.get(event)
        if not name or mascot.resolve(name) is None:
            return                                   # sin imagen: el texto ya habló, no hacemos ruido extra
        if not reactions.should(uid, event):
            return
        await mascot.send(update.get_bot(), chat, name, P.EVENT_CAPTION[event])
    h.react = react

    # logros -> reaccion
    prev_announce = h.announce

    async def announce(bot, chat: int, ev) -> None:
        await prev_announce(bot, chat, ev)
        if ev.new and s.mascot_voice_enabled and not A["safety"].active(chat):
            mascot = A["mascot"]
            if mascot.resolve("trophy") and reactions.should(chat, "achievement"):
                await mascot.send(bot, chat, "trophy", P.EVENT_CAPTION["achievement"])
    h.announce = announce

    # ---- boton «💡 Consejo de NEXUS» ----
    async def v_tip(ctx: ViewCtx) -> View:
        if not s.mascot_voice_enabled:
            return View("Esta función está apagada por ahora 💤", "sleepy")
        svc = A["svc"]
        deals = await svc._safe(svc.cs.deals(limit=12, on_sale=True)) if s.cheapshark_enabled else None
        good = [d for d in (deals or []) if (d.rating_pct or 0) >= 85 and d.discount_pct >= 30 and d.sale_usd]
        if good:
            d = max(good, key=lambda x: x.discount_pct)
            g = await svc.get_game(d.title, d.steam_appid) or d
            if g.sale_usd is None:
                g.sale_usd, g.discount_pct, g.deal_url = d.sale_usd, d.discount_pct, d.deal_url
            trm = await svc.cop_per_usd()
            txt = ("💡 <b>Consejo de NEXUS</b>\nMira esta oferta que encontré ahorita:\n\n"
                   + render_game(g, trm) + "\n\n" + esc(P.advice_line(g)) + f"\n\n<i>{ATTRIBUTION}</i>")
            return View(txt, "excited" if P.is_low_price(g) else "happy")
        return View("💡 <b>Consejo de NEXUS</b>\n" + esc(P.idle_tip()) + "\n<i>(No pude traer ofertas ahorita, "
                    "así que este es un consejo general.)</i>", "thinking")
    A["panel"].register("tip", v_tip)
