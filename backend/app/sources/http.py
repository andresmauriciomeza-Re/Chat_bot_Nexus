"""Cliente HTTP compartido: User-Agent ASCII, cache TTL, reintentos con backoff y degradacion."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "NEXUS-IA/1.0 (telegram videogame bot)"  # SOLO ASCII
assert USER_AGENT.isascii()


class Http:
    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 8.0, retries: int = 2,
                 backoff: float = 0.4):
        self._client = client
        self.timeout, self.retries, self.backoff = timeout, retries, backoff
        self._cache: dict[str, tuple[float, Any]] = {}

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                                             timeout=self.timeout, follow_redirects=True)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def get_json(self, url: str, params: dict | None = None, ttl: float = 300.0,
                       retries: int | None = None) -> Any | None:
        """JSON o None si falla. Con TTL cachea; si falla devuelve el dato vencido si existe."""
        key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and ttl > 0 and now - hit[0] < ttl:
            return hit[1]
        n = self.retries if retries is None else retries
        for attempt in range(n + 1):
            try:
                r = await self.client().get(url, params=params, headers={"User-Agent": USER_AGENT})
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError("retry", request=r.request, response=r)
                r.raise_for_status()
                data = r.json()
                if ttl > 0:
                    self._cache[key] = (now, data)
                return data
            except (httpx.HTTPError, ValueError) as e:
                log.warning("fuente %s fallo (%s) intento %d", url.split("/")[2], type(e).__name__, attempt + 1)
                if attempt < n:
                    await asyncio.sleep(self.backoff * (2 ** attempt))
        return hit[1] if hit else None
