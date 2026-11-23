"""Epic Games: juegos gratis de la semana (endpoint publico NO oficial; puede cambiar o caerse)."""
from __future__ import annotations

from .http import Http
from .models import FreeGame

URL = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"


def _slug(e: dict) -> str | None:
    for m in e.get("offerMappings") or []:
        if m.get("pageSlug"):
            return m["pageSlug"]
    for m in (e.get("catalogNs") or {}).get("mappings") or []:
        if m.get("pageSlug"):
            return m["pageSlug"]
    return e.get("productSlug") or e.get("urlSlug")


class Epic:
    def __init__(self, http: Http):
        self.http = http

    async def free_games(self) -> list[FreeGame] | None:
        """None = fuente caida (distinto de lista vacia)."""
        data = await self.http.get_json(URL, {"locale": "es-CO", "country": "CO", "allowCountries": "CO"}, ttl=1800)
        try:
            els = data["data"]["Catalog"]["searchStore"]["elements"]
        except (TypeError, KeyError):
            return None
        out: list[FreeGame] = []
        for e in els:
            promo = e.get("promotions") or {}
            slug = _slug(e)
            url = f"https://store.epicgames.com/es-ES/p/{slug}" if slug and "/" not in slug else None
            img = next((k.get("url") for k in e.get("keyImages", [])
                        if k.get("type") in ("Thumbnail", "OfferImageWide")), None)
            for block, upcoming in ((promo.get("promotionalOffers"), False),
                                    (promo.get("upcomingPromotionalOffers"), True)):
                for b in block or []:
                    for o in b.get("promotionalOffers", []):
                        if (o.get("discountSetting") or {}).get("discountPercentage") == 0:
                            when = o.get("startDate") if upcoming else o.get("endDate")
                            out.append(FreeGame(e.get("title", "?"), "Epic Games", url, img,
                                                (when or "")[:10], upcoming))
        return out
