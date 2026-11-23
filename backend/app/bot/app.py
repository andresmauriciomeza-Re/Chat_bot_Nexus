from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from ..config import Settings
from ..core.orchestrator import Orchestrator
from ..core.risk_guard import RiskGuard
from ..core.safety import Safety
from ..games.pipeline import GamePipeline
from ..games.service import GameService
from ..llm.budget import BudgetedLLM, TokenBudget
from ..llm.groq_provider import GroqProvider
from ..sources.http import Http
from ..core.safety import GUARD_SOFT
from .send import send_text

log = logging.getLogger(__name__)

HELP = ("🎮 <b>NEXUS-IA</b>: te ayudo a elegir videojuegos y a ver si el precio vale la pena.\n\n"
        "Prueba cosas como:\n"
        "• «recomiéndame un juego de aventura»\n"
        "• «tengo 100.000 pesos»  /  «algo de 20 dólares»\n"
        "• «cuánto cuesta Hades»  /  «ficha de Journey»\n"
        "• «Hades vs Celeste»\n"
        "• /gratis para ver lo que está gratis hoy")


def build_services(s: Settings):
    budget = TokenBudget(s.groq_budget_enabled, s.groq_daily_token_budget, s.groq_user_daily_tokens,
                         path=s.data_path() / "groq_budget.json")
    llm = BudgetedLLM(GroqProvider(s.groq_api_key.get_secret_value(), s.groq_model, s.llm_timeout_s), budget)
    orch = Orchestrator(llm, s.system_prompt(), history_limit=s.history_limit, max_tokens=s.llm_max_tokens)
    svc = GameService(Http(), enabled={"cheapshark": s.cheapshark_enabled, "steam": s.steam_enabled,
                                       "epic": s.epic_enabled, "trm": s.trm_enabled})
    pipe = GamePipeline(svc, orch, s.budget_sanity_max_cop, s.budget_sanity_max_usd)
    safety = Safety(RiskGuard(), orch, enabled=s.risk_guard_enabled)
    return budget, orch, svc, pipe, safety


def build_application(s: Settings) -> Application:
    app = Application.builder().token(s.telegram_bot_token.get_secret_value()).build()
    budget, orch, svc, pipe, safety = build_services(s)
    app.bot_data.update(settings=s, budget=budget, orch=orch, svc=svc, pipe=pipe, safety=safety)

    def guarded(fn):
        """Durante la guardia de riesgo, los comandos solo devuelven texto de apoyo."""
        async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            if update.effective_user and safety.active(update.effective_user.id):
                await send_text(update.effective_message, GUARD_SOFT)
                return
            await fn(update, ctx)
        return wrapper

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await send_text(update.effective_message, "¡Quiubo, parcero! 🎮 Soy <b>NEXUS-IA</b>, tu asistente de videojuegos.\n\n" + HELP)

    async def help_(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await send_text(update.effective_message, HELP)

    async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        orch.reset(str(update.effective_user.id))
        await send_text(update.effective_message, "Listo, empezamos de cero 🧹")

    async def gratis(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        r = await pipe.free_today()
        await send_text(update.effective_message, r.text)

    async def text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        uid = update.effective_user.id
        v = safety.check(uid, msg.text or "")          # PRIORIDAD ABSOLUTA: antes de todo lo demas
        if v.kind in ("risk", "released"):
            await send_text(msg, v.text)
            return
        if v.kind == "guard":
            await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
            await send_text(msg, await safety.guard_reply(uid, msg.text or ""))
            return
        await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
        r = await pipe.handle(str(uid), msg.text or "")
        await send_text(msg, r.text)

    async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        # solo el tipo de error: nunca el contenido de mensajes
        log.error("error en handler: %s", type(ctx.error).__name__)
        try:
            if isinstance(update, Update) and update.effective_message:
                await update.effective_message.reply_text("Uy, se me cruzaron los cables. Intenta de nuevo 🙏")
        except Exception:
            pass

    app.add_handler(CommandHandler("start", guarded(start)))
    app.add_handler(CommandHandler("help", guarded(help_)))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("gratis", guarded(gratis)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    app.add_error_handler(on_error)
    return app
