from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from ..config import Settings
from ..core.orchestrator import Orchestrator
from ..core.risk_guard import RiskGuard
from ..core.safety import Safety
from ..games.pipeline import GamePipeline
from ..games.service import GameService
from ..llm.budget import BudgetedLLM, TokenBudget
from ..llm.groq_provider import GroqProvider
from ..sources.http import Http
from ..tools.last_result import LastResults
from .handlers import BotHandlers
from .mascot import Mascot
from .panel import Panel
from .views import register_base_views

log = logging.getLogger(__name__)

COMMANDS = [
    ("start", "🎮 Empezar con NEXUS"), ("menu", "🏠 Abrir el menú"), ("help", "❓ Cómo usarme"),
    ("estado", "📡 Estado del bot"), ("reset", "🧹 Reiniciar la charla"), ("nexus", "🤖 Conocer a NEXUS"),
    ("animo", "😊 Mi ánimo"), ("gratis", "🆓 Juegos gratis hoy"), ("gustos", "💜 Mis gustos"),
    ("trivia", "🧠 Trivia gamer"), ("perfil", "🏆 Mi perfil"), ("cofre", "🎁 Cofre diario"),
    ("borrar_datos", "🗑 Borrar mis datos"), ("ajustes", "🔊 Voz y ajustes"),
    ("ocultar_teclado", "🙈 Ocultar el teclado"),
]


def build_services(s: Settings) -> dict:
    budget = TokenBudget(s.groq_budget_enabled, s.groq_daily_token_budget, s.groq_user_daily_tokens,
                         path=s.data_path() / "groq_budget.json")
    llm = BudgetedLLM(GroqProvider(s.groq_api_key.get_secret_value(), s.groq_model, s.llm_timeout_s), budget)
    orch = Orchestrator(llm, s.system_prompt(), history_limit=s.history_limit, max_tokens=s.llm_max_tokens)
    svc = GameService(Http(), enabled={"cheapshark": s.cheapshark_enabled, "steam": s.steam_enabled,
                                       "epic": s.epic_enabled, "trm": s.trm_enabled})
    pipe = GamePipeline(svc, orch, s.budget_sanity_max_cop, s.budget_sanity_max_usd)
    safety = Safety(RiskGuard(), orch, enabled=s.risk_guard_enabled)
    mascot = Mascot(s.mascot_dir(), enabled=s.main_panel_enabled, anim_enabled=s.mascot_anim_enabled,
                    store_path=s.data_path() / "mascot_ids.json")
    return dict(settings=s, llm=llm, budget=budget, orch=orch, svc=svc, pipe=pipe, safety=safety, mascot=mascot,
                last=LastResults(), panel=Panel(mascot, s.main_panel_enabled))


def build_application(s: Settings) -> Application:
    async def post_init(app: Application) -> None:
        try:
            await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
        except Exception as e:
            log.warning("set_my_commands fallo (%s)", type(e).__name__)

    app = Application.builder().token(s.telegram_bot_token.get_secret_value()).post_init(post_init).build()
    A = build_services(s)
    app.bot_data.update(A)
    register_base_views(A["panel"])
    h = BotHandlers(A, A["panel"])
    app.bot_data["handlers"] = h
    install_extensions(app, h)

    cmd = app.add_handler
    cmd(CommandHandler("start", h.cmd_start))
    cmd(CommandHandler("menu", h.cmd_menu))
    cmd(CommandHandler("help", h.cmd_help))
    cmd(CommandHandler("estado", h.cmd_estado))
    cmd(CommandHandler("reset", h.cmd_reset))
    cmd(CommandHandler("gratis", h.cmd_gratis))
    cmd(CommandHandler("ocultar_teclado", h.cmd_hide_keyboard))
    cmd(CommandHandler("borrar_datos", h.cmd_delete_data))
    for name, view in (("nexus", "about"), ("animo", "mood"), ("gustos", "likes"), ("trivia", "trivia"),
                       ("perfil", "profile"), ("cofre", "chest"), ("ajustes", "settings")):
        cmd(CommandHandler(name, h.view_cmd(view)))
    cmd(CallbackQueryHandler(h.on_callback))
    cmd(MessageHandler(filters.TEXT & ~filters.COMMAND, h.on_text))
    app.add_error_handler(h.on_error)
    return app


def install_extensions(app: Application, h: BotHandlers) -> None:
    """Punto de enganche para modulos de fases posteriores (mascota que habla)."""
    from ..features.install import install_features
    install_features(h.A, h)
    from ..voice.install import install_voice
    install_voice(app, h)
    from .inline import install_inline
    install_inline(app, h)
