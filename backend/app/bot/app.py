from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from ..config import Settings
from ..core.orchestrator import Orchestrator
from ..llm.groq_provider import GroqProvider
from ..telegram_utils import split_text

log = logging.getLogger(__name__)


def build_orchestrator(s: Settings) -> Orchestrator:
    llm = GroqProvider(s.groq_api_key.get_secret_value(), s.groq_model, s.llm_timeout_s)
    return Orchestrator(llm, s.system_prompt(), history_limit=s.history_limit, max_tokens=s.llm_max_tokens)


def build_application(s: Settings) -> Application:
    app = Application.builder().token(s.telegram_bot_token.get_secret_value()).build()
    orch = build_orchestrator(s)
    app.bot_data["orch"] = orch

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("¡Quiubo! Soy NEXUS-IA. Escríbeme.")

    async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        orch.reset(str(update.effective_chat.id))
        await update.effective_message.reply_text("Listo, empezamos de cero.")

    async def text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        answer = await orch.handle(str(update.effective_chat.id), msg.text or "")
        for part in split_text(answer):
            await msg.reply_text(part)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    return app
