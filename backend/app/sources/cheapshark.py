"""CheapShark: ofertas, precio historico minimo, miniatura. Atribucion obligatoria."""
from __future__ import annotations

from .http import Http
from .models import GameInfo

BASE = "https://www.cheapshark.com/api/1.0"
ATTRIBUTION = "Ofertas: CheapShark.com"
STEAM_STORE_ID = "1"


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def redirect(deal_id: str) -> str:
    return f"https://www.cheapshark.com/redirect?dealID={deal_id}"


class CheapShark:
    def __init__(self, http: Http):
        self.http = http

    async def stores(self) -> dict[str, str]:
        data = await self.http.get_json(f"{BASE}/stores", ttl=86400) or []
        return {s["storeID"]: s["storeName"] for s in data if isinstance(s, dict) and "storeID" in s}

    @staticmethod
    def _from_deal(d: dict) -> GameInfo:
        sale, normal = _f(d.get("salePrice")), _f(d.get("normalPrice"))
        return GameInfo(
            title=d.get("title") or "?", steam_appid=_i(d.get("steamAppID")), game_id=d.get("gameID"),
            thumb=d.get("thumb"), sale_usd=sale, normal_usd=normal,
            discount_pct=int(round(_f(d.get("savings")) or 0)),
            historic_low_usd=None, is_free=(sale == 0.0),
            deal_url=redirect(d["dealID"]) if d.get("dealID") else None,
            metacritic=_i(d.get("metacriticScore")) or None, rating_pct=_i(d.get("steamRatingPercent")) or None)

    async def deals(self, title: str | None = None, upper: float | None = None, on_sale: bool = True,
                    limit: int = 10, sort: str = "Deal Rating") -> list[GameInfo]:
        p: dict = {"storeID": STEAM_STORE_ID, "pageSize": limit, "sortBy": sort, "onSale": 1 if on_sale else 0}
        if title:
            p["title"] = title
        if upper is not None:
            p["upperPrice"] = upper
        data = await self.http.get_json(f"{BASE}/deals", p, ttl=600)
        return [self._from_deal(d) for d in data if isinstance(d, dict)] if isinstance(data, list) else []

    async def giveaways(self) -> list[GameInfo]:
        data = await self.http.get_json(f"{BASE}/deals", {"upperPrice": 0, "onSale": 1, "pageSize": 15}, ttl=900)
        out = []
        for d in data if isinstance(data, list) else []:
            g = self._from_deal(d)
            if g.sale_usd == 0.0 and (g.normal_usd or 0) > 0:
                out.append(g)
        return out

    async def lookup(self, title: str) -> GameInfo | None:
        """Mejor coincidencia por titulo, con minimo historico y mejor oferta actual."""
        res = await self.http.get_json(f"{BASE}/games", {"title": title, "limit": 5}, ttl=1800)
        if not isinstance(res, list) or not res:
            return None
        t = title.lower().strip()
        best = next((r for r in res if r.get("external", "").lower() == t), res[0])
        info = await self.http.get_json(f"{BASE}/games", {"id": best["gameID"]}, ttl=900)
        g = GameInfo(title=best.get("external") or title, steam_appid=_i(best.get("steamAppID")),
                     game_id=best.get("gameID"), thumb=best.get("thumb"), sale_usd=_f(best.get("cheapest")))
        if isinstance(info, dict):
            g.historic_low_usd = _f((info.get("cheapestPriceEver") or {}).get("price"))
            deals = info.get("deals") or []
            if deals:
                d = min(deals, key=lambda x: _f(x.get("price")) or 1e9)
                g.sale_usd, g.normal_usd = _f(d.get("price")), _f(d.get("retailPrice"))
                g.discount_pct = int(round(_f(d.get("savings")) or 0))
                g.deal_url = redirect(d["dealID"]) if d.get("dealID") else None
                g.store_name = (await self.stores()).get(d.get("storeID"))
        g.is_free = g.sale_usd == 0.0
        return g
