"""Codec y validacion de botones inline: solo el dueno puede usarlos y vencen (2 h; 30 min los de resultados)."""
from __future__ import annotations

import time
from dataclasses import dataclass

PANEL_TTL = 2 * 3600
RESULT_TTL = 30 * 60
RESULT_ACTIONS = {"fx", "sm", "cp", "fa", "sg", "tts", "ta"}       # botones de tarjetas / ultimo resultado
EXPIRED_MSG = "Ese botón ya venció 😅. Ábrelo de nuevo con /menu"
NOT_OWNER_MSG = "Ese botón es de otra persona 🙈. Abre el tuyo con /menu"


@dataclass(slots=True)
class CB:
    action: str
    owner: int
    minute: int
    arg: str = ""


def make(action: str, owner: int, arg: str = "", clock=time.time) -> str:
    data = f"{action}|{owner}|{int(clock() // 60)}|{arg}"
    assert len(data.encode()) <= 64, "callback_data demasiado largo"
    return data


def parse(data: str | None) -> CB | None:
    try:
        a, o, m, arg = (data or "").split("|", 3)
        return CB(a, int(o), int(m), arg)
    except ValueError:
        return None


def check(cb: CB | None, user_id: int, clock=time.time) -> str | None:
    """None si es valido; si no, el aviso amable para el usuario."""
    if cb is None:
        return EXPIRED_MSG
    if cb.owner != user_id:
        return NOT_OWNER_MSG
    ttl = RESULT_TTL if cb.action in RESULT_ACTIONS else PANEL_TTL
    if clock() - cb.minute * 60 > ttl + 60:
        return EXPIRED_MSG
    return None
