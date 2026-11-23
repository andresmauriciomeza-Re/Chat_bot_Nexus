"""Steam: appdetails con cc=CO (precio real en COP) y busqueda por nombre."""
from __future__ import annotations

from .http import Http
from .models import GameInfo

DETAILS = "https://store.steampowered.com/api/appdetails"
SEARCH = "https://store.steampowered.com/api/storesearch/"

MODE_NAMES = {"Un jugador": "Un jugador", "Un solo jugador": "Un jugador", "Multijugador": "Multijugador",
              "Cooperativo": "Cooperativo", "JcJ": "JcJ", "Cooperativo en línea": "Coop en línea",
              "Cooperativo local": "Coop local", "Multijugador local": "Multijugador local"}


class Steam:
    def __init__(self, http: Http):
        self.http = http

    async def find_appid(self, name: str) -> int | None:
        data = await self.http.get_json(SEARCH, {"term": name, "cc": "CO", "l": "spanish"}, ttl=3600)
        items = data.get("items") if isinstance(data, dict) else None
        if not items:
            return None
        n = name.lower().strip()
        best = next((i for i in items if i.get("name", "").lower() == n), items[0])
        return best.get("id")

    async def details(self, appid: int) -> GameInfo | None:
        data = await self.http.get_json(DETAILS, {"appids": appid, "cc": "CO", "l": "spanish"}, ttl=1800)
        entry = data.get(str(appid)) if isinstance(data, dict) else None
        if not entry or not entry.get("success") or not isinstance(entry.get("data"), dict):
            return None
        d = entry["data"]
        g = GameInfo(title=d.get("name") or "?", steam_appid=appid, image=d.get("header_image"),
                     description=d.get("short_description"), is_free=bool(d.get("is_free")))
        g.genres = [x.get("description") for x in d.get("genres", []) if x.get("description")]
        cats = [x.get("description") for x in d.get("categories", []) if x.get("description")]
        g.modes = list(dict.fromkeys(MODE_NAMES[c] for c in cats if c in MODE_NAMES))
        pl = d.get("platforms") or {}
        g.platforms = [n for k, n in (("windows", "PC (Windows)"), ("mac", "Mac"), ("linux", "Linux")) if pl.get(k)]
        po = d.get("price_overview")
        if po and po.get("currency") == "COP":
            g.price_cop = int(po["final"]) // 100        # Steam entrega centavos
            g.normal_cop = int(po["initial"]) // 100
            g.discount_pct = int(po.get("discount_percent") or 0)
        g.metacritic = (d.get("metacritic") or {}).get("score")
        g.deal_url = f"https://store.steampowered.com/app/{appid}"
        return g
