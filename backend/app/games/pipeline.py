"""Enrutador de intenciones por REGLAS. Datos y cuentas por codigo; el modelo solo redacta."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from ..core.orchestrator import Orchestrator
from ..sources.cheapshark import ATTRIBUTION
from ..sources.models import GameInfo
from ..telegram_utils import esc
from .budget import to_cop
from .filters import Filters, parse_filters
from .. import personality as persona_mod
from .render import fmt_cop, render_free, render_game, render_sheet, total_line
from .service import GameService, effective_cop

log = logging.getLogger(__name__)

_SHEET = re.compile(r"^(?:(?:dame|mu[eé]strame)\s+)?(?:la\s+)?ficha\s+(?:de|del)\s+(?P<n>.+)$|"
                    r"^(?:h[aá]blame|cu[eé]ntame|dime)\s+(?:de|sobre|del)\s+(?P<n2>.+)$|"
                    r"^de qu[eé] (?:trata|va)\s+(?P<n3>.+)$|^qu[eé] tal es\s+(?P<n4>.+)$", re.I)
_PRICE = re.compile(r"(?:cu[aá]nto\s+(?:cuesta|vale|est[aá]|sale)|precio\s+(?:de|del)|a\s+c[uú]anto\s+est[aá]|"
                    r"vale\s+la\s+pena|est[aá]\s+barato|conviene\s+comprar|oferta\s+(?:de|del))\s+(?:el\s+|la\s+|comprar\s+)?(?P<n>.+)", re.I)
_COMPARE = re.compile(r"^(?:compara(?:r|me)?\s+)?(?P<a>.+?)\s+(?:vs\.?|versus|contra|frente a)\s+(?P<b>.+)$|"
                      r"^compara(?:r|me)?\s+(?P<a2>.+?)\s+(?:con|y)\s+(?P<b2>.+)$", re.I)
_RECO = re.compile(r"recomi[eé]nd|recomienda|sugi[eé]r|qu[eé] (?:juego|jugar)|busco|quiero jugar|alg[uú]n juego|"
                   r"juegos? (?:de|para|con|que)|algo (?:para|de) jugar|qu[eé] me (?:compro|recomiendas)", re.I)
_FREE_TODAY = re.compile(r"^(?:qu[eé] hay |hay |dame |mu[eé]strame )?(?:juegos? )?(?:gratis|gratuitos?|regalados?)(?: hoy| esta semana| ahora)?\??$|"
                         r"qu[eé] (?:hay|juegos? hay) gratis|juegos? gratis (?:hoy|de hoy|esta semana)|gratis hoy", re.I)
_SIMILAR = re.compile(r"(?:juegos?\s+)?(?:parecid\w+|similares?)\s+(?:a|al|a la|a lo)\s+(?P<n>.+)", re.I)
_YES = re.compile(r"^\s*(s[ií]|sii+|dale|confirmo|correcto|claro|as[ií] es|ok)\b", re.I)
_NO = re.compile(r"^\s*(no|nel|cancel\w*|mejor no)\b", re.I)
PENDING_TTL = 300


@dataclass(slots=True)
class Reply:
    kind: str                      # chat | games | free | sheet | compare | confirm | info
    text: str                      # mensaje completo en HTML
    intro: str = ""
    games: list[GameInfo] = field(default_factory=list)
    footer: str = ""
    summary: str = ""          # texto posterior a las tarjetas (totales, veredicto, atribucion)
    trm: float | None = None
    filters: Filters | None = None
    event: str = ""            # momento clave para la mascota (greet, thanks, ...)


def clean_name(s: str) -> str | None:
    s = re.sub(r"[?!¿¡.]+$", "", s.strip())
    s = re.sub(r"\b(en oferta|hoy|ahora|por favor|porfa)\b", "", s, flags=re.I).strip(" ,")
    return s if 1 <= len(s) <= 60 else None


class GamePipeline:
    def __init__(self, service: GameService, orch: Orchestrator, max_cop: float = 1_000_000, max_usd: float = 300,
                 clock=time.time):
        self.svc, self.orch, self.max_cop, self.max_usd, self.clock = service, orch, max_cop, max_usd, clock
        self._pending: dict[str, tuple[Filters, float]] = {}
        self.persona = False         # personalidad de NEXUS (Fase 7): charla casual sin gastar tokens
        self.prefs = None            # callable(user)->set[str] de generos favoritos (Fase 4)

    # ---- entrada principal ----
    async def handle(self, user: str, text: str) -> Reply:
        text = re.sub(r"\s+", " ", text or "").strip()
        pend = self._pending.get(user)
        if pend:
            del self._pending[user]
            if self.clock() - pend[1] < PENDING_TTL:
                if _YES.match(text):
                    return await self.recommend(user, pend[0], confirmed=True)
                if _NO.match(text):
                    return Reply("info", "Listo, lo dejamos así. Dime otro presupuesto cuando quieras 😉")
        try:
            return await self._route(user, text)
        except Exception:
            log.exception("error en pipeline")
            return Reply("info", "Se me enredó algo consultando los datos. Intenta de nuevo en un momento 🙏")

    async def _route(self, user: str, text: str) -> Reply:
        if _FREE_TODAY.search(text):
            return await self.free_today()
        if m := _COMPARE.match(text.rstrip("?! .")):
            a, b = clean_name(m.group("a") or m.group("a2")), clean_name(m.group("b") or m.group("b2"))
            if a and b:
                return await self.compare(a, b)
        if m := _SIMILAR.search(text.rstrip("?! .")):
            n = clean_name(m.group("n"))
            if n:
                return await self.similar(n)
        if m := _SHEET.match(text.rstrip("?! .")):
            n = clean_name(next(x for x in m.groups() if x))
            if n:
                return await self.sheet(n)
        if m := _PRICE.search(text):
            n = clean_name(m.group("n"))
            if n:
                return await self.price(n, advice=self.persona and persona_mod.wants_advice(text))
        f = parse_filters(text, self.max_cop, self.max_usd)
        minutes = persona_mod.minutes_available(text) if self.persona else None
        if minutes:
            if minutes <= 60:
                f.tags.add("corto")
            return await self.recommend(user, f, lead=persona_mod.time_line(minutes))
        if f.amount or _RECO.search(text) or (f.genres and not f.empty and len(text.split()) <= 8 and "juego" in text.lower()):
            return await self.recommend(user, f)
        if self.persona and (st := persona_mod.small_talk(text)):
            return Reply("chat", esc(st.text), event=st.event)
        return await self.chat(user, text)

    # ---- acciones ----
    async def chat(self, user: str, text: str) -> Reply:
        ans = await self.orch.handle(user, text)
        return Reply("chat", esc(ans))

    async def free_today(self) -> Reply:
        epic, giv = await self.svc.free_today()
        return Reply("free", render_free(epic, giv))

    async def price(self, name: str, advice: bool = False) -> Reply:
        g, trm = await asyncio.gather(self.svc.get_game(name), self.svc.cop_per_usd())
        if not g:
            return Reply("info", f"No encontré «{esc(name)}». ¿Lo escribes tal cual aparece en Steam? 🔎")
        tip = persona_mod.advice_line(g) if advice else ""
        summary = (esc(tip) + "\n\n" if tip else "") + f"<i>{ATTRIBUTION}</i>"
        return Reply("games", render_game(g, trm) + "\n\n" + summary, games=[g], trm=trm,
                     footer=ATTRIBUTION, summary=summary)

    async def similar(self, name: str) -> Reply:
        g, trm = await asyncio.gather(self.svc.get_game(name), self.svc.cop_per_usd())
        if not g:
            return Reply("info", f"No encontré «{esc(name)}». ¿Lo escribes tal cual aparece en Steam? 🔎")
        games = await self.svc.similar_games(g)
        if not games:
            return Reply("info", f"Todavía no tengo parecidos curados para «{esc(g.title)}» 🤷. "
                                 "Dime un género y te recomiendo.")
        intro = f"Si te gustó {g.title}, mira estos 🔁"
        parts = [esc(intro), *(render_game(x, trm) for x in games), f"<i>{ATTRIBUTION}</i>"]
        return Reply("games", "\n\n".join(parts), intro=intro, games=games, trm=trm, footer=ATTRIBUTION,
                     summary=f"<i>{ATTRIBUTION}</i>")

    async def sheet(self, name: str) -> Reply:
        g, trm = await asyncio.gather(self.svc.get_game(name), self.svc.cop_per_usd())
        if not g:
            return Reply("info", f"No encontré «{esc(name)}». ¿Lo escribes tal cual aparece en Steam? 🔎")
        if not g.reason:
            from .service import build_reason
            g.reason = build_reason(g)
        return Reply("sheet", render_sheet(g, trm), games=[g], trm=trm)

    async def compare(self, a: str, b: str) -> Reply:
        ga, gb, trm = await asyncio.gather(self.svc.get_game(a), self.svc.get_game(b), self.svc.cop_per_usd())
        if not ga or not gb:
            miss = a if not ga else b
            return Reply("info", f"No encontré «{esc(miss)}», así que no puedo compararlos. 🔎")
        return self.compare_objs(ga, gb, trm)

    @staticmethod
    def compare_objs(ga: GameInfo, gb: GameInfo, trm: float | None) -> Reply:
        ca, cb = effective_cop(ga, trm), effective_cop(gb, trm)
        if ca is None or cb is None:
            verdict = "No tengo precio de alguno de los dos ahorita, así que no te digo cuál sale más barato."
        elif ca == cb:
            verdict = "Valen lo mismo ahorita."
        else:
            cheap, dear, diff = (ga, gb, cb - ca) if ca < cb else (gb, ga, ca - cb)
            verdict = f"💸 Más barato ahora: <b>{esc(cheap.title)}</b> (≈ {fmt_cop(diff)} COP menos que {esc(dear.title)})."
        text = render_game(ga, trm) + "\n\n" + render_game(gb, trm) + "\n\n" + verdict + f"\n\n<i>{ATTRIBUTION}</i>"
        return Reply("compare", text, games=[ga, gb], trm=trm, footer=ATTRIBUTION,
                     summary=verdict + f"\n\n<i>{ATTRIBUTION}</i>")

    async def recommend(self, user: str, f: Filters, confirmed: bool = False, lead: str = "") -> Reply:
        if self.prefs and not (f.genres or f.tags):          # sin detalles: usa sus gustos (por codigo)
            liked = self.prefs(user)
            if liked:
                f.genres = set(liked)
        trm = await self.svc.cop_per_usd()
        if f.amount and f.amount.needs_confirm and not confirmed:
            self._pending[user] = (f, self.clock())
            cur = f"{fmt_cop(f.amount.value)} COP" if f.amount.currency == "COP" else f"USD {f.amount.value:,.0f}"
            return Reply("confirm", f"Ojo, ¿seguro que tu presupuesto es <b>{esc(cur)}</b>? Es bastante 😅. "
                                    "Respóndeme «sí» para seguir o dime el monto correcto.")
        if f.amount and f.amount.currency == "USD" and trm is None:
            pass  # se compara en USD directo con los precios de CheapShark
        elif f.amount and to_cop(f.amount, trm) is None:
            return Reply("info", "Ahorita no pude traer la TRM del dólar, así que no puedo convertir. "
                                 "Dime el tope en pesos o en dólares directamente.")
        games = await self.svc.recommend(f)
        if not games:
            return Reply("info", "No encontré juegos que cumplan con eso con los datos que tengo ahorita. "
                                 "Prueba subiendo el tope o quitando algún filtro 🙏", filters=f, trm=trm)
        facts = "; ".join(
            f"{g.title}" + (f" (USD {g.sale_usd:.2f})" if g.sale_usd is not None else "") for g in games)
        if lead:                       # frase de NEXUS calculada por reglas (p. ej. «tengo 30 minutos»): sin gastar tokens
            intro = lead
        else:
            intro = await self.orch.narrate(
                user, "Escribe UNA o DOS frases cortas y parceras presentando estas recomendaciones, sin repetir precios.",
                f"Filtros del usuario: {f.describe() or 'ninguno'}. Juegos: {facts}.")
            intro = intro or "Mira lo que encontré para ti 🎮"
        parts = [esc(intro), *(render_game(g, trm) for g in games)]
        tl = total_line(games, trm)
        if tl:
            parts.append(tl)
        parts.append(f"<i>{ATTRIBUTION}</i>")
        summary = (tl + "\n\n" if tl else "") + f"<i>{ATTRIBUTION}</i>"
        return Reply("games", "\n\n".join(parts), intro=intro, games=games, trm=trm, footer=ATTRIBUTION,
                     filters=f, summary=summary)
