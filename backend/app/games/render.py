"""Presentacion de juegos en HTML de Telegram. Todo dato dinamico se escapa."""
from __future__ import annotations

from ..sources.cheapshark import ATTRIBUTION
from ..sources.models import FreeGame, GameInfo
from ..telegram_utils import TG_CAPTION_LIMIT, TG_MESSAGE_LIMIT, esc, truncate
from .service import effective_cop, price_verdict


def fmt_cop(n: float | int) -> str:
    return "$" + f"{int(round(n)):,}".replace(",", ".")


def price_line(g: GameInfo, trm: float | None) -> str:
    if g.is_free:
        return "💵 <b>Gratis</b>"
    parts = []
    if g.sale_usd is not None:
        s = f"USD {g.sale_usd:.2f}"
        if g.discount_pct > 0:
            s += f" (-{g.discount_pct}%)"
        if g.store_name and g.store_name != "Steam":
            s += f" en {esc(g.store_name)}"
        parts.append(s)
    if g.price_cop is not None:
        parts.append(f"COP {fmt_cop(g.price_cop)} <i>(Steam)</i>")
    elif g.sale_usd is not None and trm:
        parts.append(f"≈ COP {fmt_cop(round(g.sale_usd * trm, -2))}")
    if not parts:
        return "💵 Sin precio disponible ahora mismo"
    return "💵 " + " · ".join(parts)


def render_game(g: GameInfo, trm: float | None, caption: bool = False) -> str:
    lines = [f"🎮 <b>{esc(g.title)}</b>", price_line(g, trm)]
    if g.historic_low_usd is not None and not g.is_free:
        lines.append(f"📉 Mínimo histórico: USD {g.historic_low_usd:.2f}")
    lines.append("🧾 " + esc(price_verdict(g)))
    if g.reason:
        lines.append("💡 " + esc(g.reason))
    if g.store_name:
        lines.append(f"🏬 Tienda: {esc(g.store_name)}")
    txt = "\n".join(lines)
    return truncate(txt, TG_CAPTION_LIMIT - 10) if caption else txt


def render_sheet(g: GameInfo, trm: float | None) -> str:
    lines = [f"📖 <b>{esc(g.title)}</b>"]
    if g.description:
        lines.append(esc(truncate(g.description, 380)))
    lines.append("🏷 Géneros: " + (esc(", ".join(g.genres)) if g.genres else "sin dato"))
    lines.append("👥 Modos: " + (esc(", ".join(g.modes)) if g.modes else "sin dato"))
    plats = list(g.platforms)
    lines.append("🕹 Plataformas (Steam): " + (esc(", ".join(plats)) if plats else "sin dato"))
    extra = []
    if g.metacritic:
        extra.append(f"Metacritic {g.metacritic}")
    if g.rating_pct:
        extra.append(f"{g.rating_pct}% reseñas positivas")
    if extra:
        lines.append("⭐ " + " · ".join(extra))
    lines.append("")
    lines.append(render_game(g, trm))
    lines.append(f"\n<i>{ATTRIBUTION}</i>")
    return truncate("\n".join(lines), TG_MESSAGE_LIMIT)


def render_free(epic: list[FreeGame] | None, giveaways: list[GameInfo]) -> str:
    lines = ["🆓 <b>Gratis hoy</b>"]
    now = [x for x in (epic or []) if not x.upcoming]
    soon = [x for x in (epic or []) if x.upcoming]
    if epic is None:
        lines.append("No pude consultar Epic ahorita; intenta más tarde.")
    elif now:
        lines.append("\n<b>Epic Games (esta semana)</b>")
        for x in now:
            end = f" · hasta {esc(x.ends)}" if x.ends else ""
            link = f' — <a href="{esc(x.url)}">ver</a>' if x.url else ""
            lines.append(f"• {esc(x.title)}{end}{link}")
    else:
        lines.append("\nEn Epic no veo juegos gratis activos ahorita.")
    if soon:
        lines.append("\n<b>Próximamente en Epic</b>")
        for x in soon:
            lines.append(f"• {esc(x.title)}" + (f" · desde {esc(x.ends)}" if x.ends else ""))
    if giveaways:
        lines.append("\n<b>Otras tiendas (vía CheapShark)</b>")
        for g in giveaways[:5]:
            link = f' — <a href="{esc(g.deal_url)}">ver</a>' if g.deal_url else ""
            lines.append(f"• {esc(g.title)} (antes USD {g.normal_usd:.2f}){link}")
    lines.append(f"\n<i>Epic: endpoint público no oficial · {ATTRIBUTION}</i>")
    return truncate("\n".join(lines), TG_MESSAGE_LIMIT)


def total_line(games: list[GameInfo], trm: float | None) -> str | None:
    vals = [effective_cop(g, trm) for g in games]
    if len(games) < 2 or any(v is None for v in vals):
        return None
    return f"🧮 Los {len(games)} juntos suman ≈ COP {fmt_cop(sum(vals))}"  # type: ignore[arg-type]
