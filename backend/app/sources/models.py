from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class GameInfo:
    title: str
    steam_appid: int | None = None
    game_id: str | None = None          # id de CheapShark
    thumb: str | None = None
    image: str | None = None            # imagen grande (Steam header)
    sale_usd: float | None = None
    normal_usd: float | None = None
    discount_pct: int = 0
    historic_low_usd: float | None = None
    price_cop: int | None = None        # precio REAL de Steam (cc=CO)
    normal_cop: int | None = None
    is_free: bool = False
    deal_url: str | None = None
    store_name: str | None = None
    metacritic: int | None = None
    rating_pct: int | None = None
    genres: list[str] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    description: str | None = None
    tags: list[str] = field(default_factory=list)   # del catalogo curado
    reason: str | None = None


@dataclass(slots=True)
class FreeGame:
    title: str
    source: str
    url: str | None = None
    image: str | None = None
    ends: str | None = None
    upcoming: bool = False
