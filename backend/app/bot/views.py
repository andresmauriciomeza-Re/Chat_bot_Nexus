"""Vistas base del panel (las de fases posteriores se registran desde sus modulos)."""
from __future__ import annotations

from telegram import InlineKeyboardButton

from ..sources.cheapshark import ATTRIBUTION
from . import callbacks as cbm
from .panel import Panel, View, ViewCtx

HELP = ("🎮 <b>¿Qué puedo hacer por ti?</b>\n\n"
        "• «recomiéndame un juego de aventura»\n"
        "• «tengo 100.000 pesos» / «algo de 20 dólares»\n"
        "• «cuánto cuesta Hades» / «ficha de Journey»\n"
        "• «Hades vs Celeste»\n"
        "• /gratis para ver qué está gratis hoy\n\n"
        "Los precios y las cuentas las hace el código con datos de CheapShark, Steam y Epic; yo solo los cuento. "
        "Si no tengo un dato, te lo digo.\n\n"
        "Comandos: /menu /gratis /estado /reset /nexus /ajustes /ocultar_teclado")

ABOUT = ("🤖 <b>Soy NEXUS</b>, tu parcero gamer.\n\n"
         "Te ayudo a elegir videojuegos que valgan la pena y a no pagar de más. "
         "Los precios (USD y ≈COP) y los descuentos los calcula el código con datos reales; "
         "yo solo te los cuento, sin inventar.\n\n"
         f"<i>Fuentes: CheapShark, Steam (precio en COP) y Epic Games. {ATTRIBUTION}</i>")

GENRE_BUTTONS = [("⚔️ Acción", "accion"), ("🧭 Aventura", "aventura"), ("🧙 RPG", "rpg"), ("🎨 Indie", "indie"),
                 ("👻 Terror", "terror"), ("🧩 Puzzle", "puzzle"), ("☕ Relajados", "relajado"), ("👥 Con amigos", "coop")]
BUDGET_BUTTONS = [("$50.000", "c50000"), ("$100.000", "c100000"), ("$200.000", "c200000"),
                  ("$300.000", "c300000"), ("US$ 20", "u20"), ("US$ 50", "u50")]


def _grid(buttons: list[tuple[str, str]], action: str, owner: int, per_row: int = 2):
    btns = [InlineKeyboardButton(lbl, callback_data=cbm.make(action, owner, arg)) for lbl, arg in buttons]
    return [btns[i:i + per_row] for i in range(0, len(btns), per_row)]


async def v_menu(ctx: ViewCtx) -> View:
    return View("🎮 <b>NEXUS-IA</b>\n¿Qué hacemos hoy, parcero? Escoge una opción o escríbeme lo que buscas 👇", "welcome")


async def v_reco(ctx: ViewCtx) -> View:
    return View("🎮 <b>Recomiéndame</b>\nEscoge un plan y te traigo opciones con precio real. "
                "También puedes escribirme algo como «un juego de terror para jugar con amigos».", "excited",
                _grid(GENRE_BUTTONS, "rc", ctx.user_id))


async def v_budget(ctx: ViewCtx) -> View:
    return View("💰 <b>Por presupuesto</b>\nEscoge un tope o escríbeme el tuyo: «tengo 300 mil», «$1.500.000», "
                "«50 dólares». Yo hago las cuentas y te muestro lo que alcanza.", "thinking",
                _grid(BUDGET_BUTTONS, "bd", ctx.user_id, 3))


async def v_free(ctx: ViewCtx) -> View:
    r = await ctx.app["pipe"].free_today()
    return View(r.text, "gift")


async def v_about(ctx: ViewCtx) -> View:
    return View(ABOUT, "welcome")


async def v_help(ctx: ViewCtx) -> View:
    return View(HELP, "thinking")


async def v_settings(ctx: ViewCtx) -> View:
    s = ctx.app["settings"]
    on = lambda b: "✅" if b else "⬜"  # noqa: E731
    lines = ["🔊 <b>Voz y ajustes</b>",
             f"{on(s.main_keyboard_enabled)} Teclado fijo",
             f"{on(s.mascot_anim_enabled)} Mascota animada",
             "",
             "Con /ocultar_teclado quitas el teclado; con el botón de abajo lo vuelves a mostrar."]
    rows = [[InlineKeyboardButton("⌨️ Mostrar teclado", callback_data=cbm.make("kb", ctx.user_id))]]
    return View("\n".join(lines), "sleepy", rows)


def register_base_views(panel: Panel) -> None:
    for name, fn in (("menu", v_menu), ("reco", v_reco), ("budget", v_budget), ("free", v_free),
                     ("about", v_about), ("help", v_help), ("settings", v_settings)):
        panel.register(name, fn)
