"""Interpretacion de montos en lenguaje natural (COP/USD). Todo por reglas de codigo."""
from __future__ import annotations

import re
from dataclasses import dataclass

NUM = r"(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_PAT = re.compile(
    rf"(?P<sign>us\$|u\$s|\$)?\s*{NUM}\s*(?P<mult>millones|millón|millon|palos?|mil|lucas?|k)?(?![a-záéíóúñ0-9])"
    rf"\s*(?P<cur>pesos|cop|d[oó]lar(?:es)?|usd|dls|usdt)?(?![a-záéíóúñ])",
    re.IGNORECASE)
_CUE = re.compile(r"\b(tengo|presupuesto|hasta|m[aá]ximo|gastar|pagar|cuento con|dispongo|me alcanza|con)\b", re.I)
_USD_WORDS = re.compile(r"d[oó]lar|usd|dls|us\$|u\$s", re.I)


@dataclass(slots=True)
class Amount:
    value: float
    currency: str           # "COP" | "USD"
    needs_confirm: bool = False


def _to_float(s: str) -> float:
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):          # separadores de miles
        return float(re.sub(r"[.,]", "", s))
    m = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})+)[.,](\d{1,2})", s)  # miles + decimales
    if m:
        return float(re.sub(r"[.,]", "", m.group(1)) + "." + m.group(2))
    return float(s.replace(",", "."))


def parse_amount(text: str, max_cop: float = 1_000_000, max_usd: float = 300) -> Amount | None:
    text = re.sub(r"\s+", " ", text or "")
    cue = bool(_CUE.search(text))
    for m in _PAT.finditer(text):
        sign, mult, cur = m.group("sign"), (m.group("mult") or "").lower(), (m.group("cur") or "").lower()
        try:
            value = _to_float(m.group(2))
        except ValueError:
            continue
        explicit = bool(sign or mult or cur)
        if not explicit and not (cue and value >= 1000):
            continue
        if mult in ("millones", "millón", "millon", "palo", "palos"):
            value *= 1_000_000
        elif mult in ("lucas", "luca"):
            value *= 1000
        elif mult in ("mil", "k"):
            if value < 1000:        # regla de redundancia: «100.000 mil pesos» = 100.000
                value *= 1000
        usd = bool(re.match(r"d[oó]lar|usd|dls|usdt", cur)) or (sign or "").lower() in ("us$", "u$s") \
            or (not cur and bool(_USD_WORDS.search(text)) and bool(sign))
        currency = "USD" if usd else "COP"
        if value <= 0:
            continue
        limit = max_usd if usd else max_cop
        return Amount(value, currency, needs_confirm=value > limit)
    return None


def to_cop(a: Amount, trm: float | None) -> float | None:
    if a.currency == "COP":
        return a.value
    return a.value * trm if trm else None


def to_usd(a: Amount, trm: float | None) -> float | None:
    if a.currency == "USD":
        return a.value
    return a.value / trm if trm else None
