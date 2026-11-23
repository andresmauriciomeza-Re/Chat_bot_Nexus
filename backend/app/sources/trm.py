"""TRM (COP por USD): datos.gov.co, con respaldo open.er-api.com. Sin dato -> None (no se inventa)."""
from __future__ import annotations

from .http import Http

TRM_URL = "https://www.datos.gov.co/resource/32sa-8pi3.json"
ER_URL = "https://open.er-api.com/v6/latest/USD"


class Trm:
    def __init__(self, http: Http):
        self.http = http

    async def cop_per_usd(self) -> float | None:
        data = await self.http.get_json(TRM_URL, {"$limit": 1, "$order": "vigenciadesde DESC"}, ttl=6 * 3600)
        try:
            v = float(data[0]["valor"])
            if v > 500:
                return v
        except (TypeError, KeyError, IndexError, ValueError):
            pass
        data = await self.http.get_json(ER_URL, ttl=6 * 3600)
        try:
            v = float(data["rates"]["COP"])
            if v > 500:
                return v
        except (TypeError, KeyError, ValueError):
            pass
        return None
