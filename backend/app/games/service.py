"""Servicio de juegos: combina fuentes, calcula precios/veredictos/filtros por CODIGO."""
from __future__ import annotations

import asyncio
import json
import logging
import random
from pathlib import Path

from ..config import BACKEND_DIR
from ..sources.cheapshark import CheapShark
from ..sources.epic import Epic
from ..sources.http import Http
from ..sources.models import FreeGame, GameInfo
from ..sources.steam import Steam
from ..sources.trm import Trm
from .budget import to_cop, to_usd
from .filters import GENRE_LABEL, Filters

log = logging.getLogger(__name__)
CATALOG_PATH = BACKEND_DIR / "config" / "catalog.json"


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))["games"]
    except (OSError, ValueError, KeyError):
        log.warning("catalogo no disponible; se usara solo CheapShark")
        return []


# ---------- calculos (codigo, nunca el modelo) ----------
def effective_cop(g: GameInfo, trm: float | None) -> float | None:
    if g.is_free and g.sale_usd in (None, 0.0):
        return 0.0
    if g.price_cop is not None:
        return float(g.price_cop)
    if g.sale_usd is not None and trm:
        return g.sale_usd * trm
    return None


def affordable(g: GameInfo, cap, trm: float | None) -> bool:
    """cap: Amount. True si el juego cabe en el tope; False si no cabe o no se puede calcular."""
    if cap.currency == "USD" and g.sale_usd is not None:
        return g.sale_usd <= cap.value
    cop = effective_cop(g, trm)
    capc = to_cop(cap, trm)
    return cop is not None and capc is not None and cop <= capc


def price_verdict(g: GameInfo) -> str:
    if g.is_free:
        return "🆓 Es gratis"
    p, low = g.sale_usd, g.historic_low_usd
    if p is None:
        return "Sin precio disponible ahora mismo"
    if low is None:
        return "No tengo su mínimo histórico para comparar"
    if p <= low * 1.02 + 0.001:
        return "🔥 Está en su mínimo histórico"
    if p <= low * 1.25:
        return f"👍 Buen precio, muy cerca de su mínimo (USD {low:.2f})"
    if p <= low * 1.6:
        return f"🤔 Aceptable, pero ha llegado a USD {low:.2f}"
    return f"⏳ Mejor espera una oferta: su mínimo fue USD {low:.2f}"


def build_reason(g: GameInfo, f: Filters | None = None) -> str | None:
    bits: list[str] = []
    if f and f.genres:
        match = [GENRE_LABEL[x] for x in sorted(f.genres) if x in (g.tags or []) or x in _genre_keys(g)]
        if match:
            bits.append(f"encaja con lo que pediste ({', '.join(match)})")
    if g.discount_pct >= 20:
        bits.append(f"tiene {g.discount_pct}% de descuento")
    if g.sale_usd is not None and g.historic_low_usd is not None and g.sale_usd <= g.historic_low_usd * 1.02 + 0.001 and not g.is_free:
        bits.append("está en su mínimo histórico")
    if g.rating_pct and g.rating_pct >= 80:
        bits.append(f"{g.rating_pct}% de reseñas positivas en Steam")
    if g.metacritic and g.metacritic >= 75:
        bits.append(f"Metacritic {g.metacritic}")
    if g.is_free:
        bits.append("es gratis")
    return ("Te lo recomiendo porque " + ", ".join(bits[:3])) if bits else None


def _genre_keys(g: GameInfo) -> set[str]:
    keys = set()
    inv = {"acción": "accion", "aventura": "aventura", "rpg": "rpg", "rol": "rpg", "estrategia": "estrategia",
           "indie": "indie", "simulación": "simulacion", "carreras": "carreras", "deportes": "deportes"}
    for x in g.genres:
        k = inv.get(x.lower())
        if k:
            keys.add(k)
    return keys


class GameService:
    def __init__(self, http: Http | None = None, catalog: list[dict] | None = None, rng: random.Random | None = None,
                 enabled: dict[str, bool] | None = None):
        self.enabled = {"cheapshark": True, "steam": True, "epic": True, "trm": True, **(enabled or {})}
        self.http = http or Http()
        self.cs, self.steam, self.epic, self.trm = CheapShark(self.http), Steam(self.http), Epic(self.http), Trm(self.http)
        self.catalog = load_catalog() if catalog is None else catalog
        self.rng = rng or random.Random()
        self._sem = asyncio.Semaphore(6)

    async def cop_per_usd(self) -> float | None:
        if not self.enabled["trm"]:
            return None
        return await self._safe(self.trm.cop_per_usd())

    # ---------- obtencion ----------
    async def get_game(self, query: str, appid: int | None = None) -> GameInfo | None:
        cs, st = None, None
        async with self._sem:
            if self.enabled["cheapshark"]:
                cs = await self._safe(self.cs.lookup(query))
            aid = appid or (cs.steam_appid if cs else None)
            if self.enabled["steam"]:
                if not aid:
                    aid = await self._safe(self.steam.find_appid(query))
                if aid:
                    st = await self._safe(self.steam.details(aid))
        if not cs and not st:
            return None
        g = cs or GameInfo(title=query)
        if st:
            g.title = st.title or g.title
            g.steam_appid = st.steam_appid
            g.image, g.description = st.image, st.description
            g.genres, g.modes, g.platforms = st.genres, st.modes, st.platforms
            g.price_cop, g.normal_cop = st.price_cop, st.normal_cop
            g.metacritic = g.metacritic or st.metacritic
            g.is_free = g.is_free or st.is_free
            if g.sale_usd is None:
                g.discount_pct = st.discount_pct
            g.deal_url = g.deal_url or st.deal_url
        cat = self.catalog_entry(g.title) or self.catalog_entry(query)
        if cat:
            g.tags = list(cat.get("tags", []))
        return g

    def catalog_entry(self, title: str) -> dict | None:
        t = title.lower().strip()
        return next((c for c in self.catalog if c["title"].lower() == t), None)

    async def free_today(self) -> tuple[list[FreeGame] | None, list[GameInfo]]:
        async def none():
            return None
        epic, giv = await asyncio.gather(self._safe(self.epic.free_games()) if self.enabled["epic"] else none(),
                                         self._safe(self.cs.giveaways()) if self.enabled["cheapshark"] else none())
        return epic, giv or []

    @staticmethod
    async def _safe(coro):
        try:
            return await coro
        except Exception:
            log.exception("fuente fallo")
            return None

    # ---------- recomendacion ----------
    def candidates(self, f: Filters) -> list[dict]:
        out = []
        for c in self.catalog:
            if f.genres and not (f.genres & set(c["genres"])):
                continue
            ctags = set(c.get("tags", []))
            if "coop" in ctags:
                ctags.add("multijugador")
            if f.tags and not f.tags <= ctags:
                continue
            if f.platforms and not f.platforms & set(c.get("platforms", [])):
                continue
            if f.free and "f2p" not in c.get("tags", []):
                continue
            out.append(c)
        return out

    async def recommend(self, f: Filters, limit: int = 3) -> list[GameInfo]:
        trm = await self.cop_per_usd()
        cands = self.candidates(f)
        self.rng.shuffle(cands)
        results: list[GameInfo] = []
        pool = cands[: limit * 3 + 3]
        games = await asyncio.gather(*(self.get_game(c["title"], c.get("appid")) for c in pool), return_exceptions=True)
        for g in games:
            if not isinstance(g, GameInfo):
                continue
            if f.on_sale and g.discount_pct <= 0:
                continue
            if f.free and not g.is_free:
                continue
            if f.amount and not affordable(g, f.amount, trm):
                continue
            g.reason = build_reason(g, f)
            results.append(g)
        if len(results) < limit and (f.empty or f.on_sale or f.amount) and not (f.genres or f.tags or f.platforms):
            results += await self._from_deals(f, trm, limit - len(results), {r.title for r in results})
        return results[:limit]

    async def _from_deals(self, f: Filters, trm: float | None, n: int, seen: set[str]) -> list[GameInfo]:
        upper = None
        if f.amount:
            upper = to_usd(f.amount, trm)
        if not self.enabled["cheapshark"]:
            return []
        deals = await self._safe(self.cs.deals(upper=upper, limit=15, on_sale=True)) or []
        deals = [d for d in deals if (d.rating_pct or 0) >= 75 and d.title not in seen]
        out = []
        for d in deals[: n * 2]:
            full = await self.get_game(d.title, d.steam_appid)
            g = full or d
            if g.sale_usd is None:
                g.sale_usd, g.discount_pct = d.sale_usd, d.discount_pct
            if f.amount and not affordable(g, f.amount, trm):
                continue
            g.reason = build_reason(g, f)
            out.append(g)
            if len(out) >= n:
                break
        return out

    def similar(self, g: GameInfo) -> list[dict]:
        cat = self.catalog_entry(g.title)
        if not cat:
            return []
        gs, ts = set(cat["genres"]), set(cat.get("tags", []))
        scored = [(len(gs & set(c["genres"])) * 2 + len(ts & set(c.get("tags", []))), c) for c in self.catalog
                  if c["title"] != cat["title"]]
        scored = [s for s in scored if s[0] >= 2]
        scored.sort(key=lambda s: -s[0])
        return [c for _, c in scored[:5]]
