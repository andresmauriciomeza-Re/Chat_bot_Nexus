"""Gamificacion minima + gustos en SQLite (stdlib). Todo lo del usuario se borra con /borrar_datos."""
from __future__ import annotations

import logging
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)
BOGOTA = timezone(timedelta(hours=-5))

LEVELS = [(0, "Novato 🎮"), (50, "Jugador 🕹"), (150, "Veterano 🛡"), (300, "Experto ⚔️"), (600, "Maestro 👑"),
          (1200, "Leyenda 🌟")]
ACHIEVEMENTS = {
    "first_search": ("Primera búsqueda", "🔎"),
    "hunter": ("Cazador de ofertas (10 búsquedas)", "🏹"),
    "free_hunter": ("Cazador de gratis", "🆓"),
    "trivia_5": ("Cerebro gamer (5 aciertos)", "🧠"),
    "streak_3": ("Constante (3 días seguidos)", "🔥"),
    "streak_7": ("Imparable (7 días seguidos)", "⚡"),
    "first_chest": ("Primer cofre", "🎁"),
    "likes_3": ("Gustos claros (3 géneros)", "💜"),
}
QUERY_XP, TRIVIA_XP = 3, 10
CHEST_XP = (15, 20, 25, 30, 40)


@dataclass(slots=True)
class Events:
    xp: int = 0
    new: list[str] = field(default_factory=list)       # claves de logros nuevos


@dataclass(slots=True)
class Profile:
    xp: int
    level: str
    next_at: int | None
    streak: int
    achievements: list[str]
    likes: list[str]


class Store:
    def __init__(self, path: Path | str, enabled: bool = True, query_cap: int = 30, trivia_cap: int = 50,
                 clock=time.time, rng: random.Random | None = None):
        self.enabled, self.query_cap, self.trivia_cap = enabled, query_cap, trivia_cap
        self.clock, self.rng = clock, rng or random.Random()
        self.ok = True
        try:
            if str(path) != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(path), check_same_thread=False)
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, xp INTEGER NOT NULL DEFAULT 0,
                    streak INTEGER NOT NULL DEFAULT 0, last_day TEXT, chest_day TEXT);
                CREATE TABLE IF NOT EXISTS daily(user_id INTEGER, day TEXT, kind TEXT, xp INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id, day, kind));
                CREATE TABLE IF NOT EXISTS counters(user_id INTEGER, key TEXT, n INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id, key));
                CREATE TABLE IF NOT EXISTS achievements(user_id INTEGER, key TEXT, ts REAL, PRIMARY KEY(user_id, key));
                CREATE TABLE IF NOT EXISTS likes(user_id INTEGER, genre TEXT, PRIMARY KEY(user_id, genre));
            """)
            self.db.commit()
        except (sqlite3.Error, OSError) as e:
            log.error("SQLite no disponible (%s): gamificacion y gustos desactivados", type(e).__name__)
            self.ok, self.db = False, None

    # ---------- utilidades ----------
    def today(self) -> str:
        return datetime.fromtimestamp(self.clock(), BOGOTA).strftime("%Y-%m-%d")

    def _yesterday(self) -> str:
        return (datetime.fromtimestamp(self.clock(), BOGOTA) - timedelta(days=1)).strftime("%Y-%m-%d")

    def _user(self, uid: int) -> sqlite3.Row | tuple:
        self.db.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (uid,))
        return self.db.execute("SELECT xp, streak, last_day, chest_day FROM users WHERE user_id=?", (uid,)).fetchone()

    def _count(self, uid: int, key: str, inc: int = 0) -> int:
        if inc:
            self.db.execute("INSERT INTO counters(user_id,key,n) VALUES (?,?,?) "
                            "ON CONFLICT(user_id,key) DO UPDATE SET n=n+?", (uid, key, inc, inc))
        r = self.db.execute("SELECT n FROM counters WHERE user_id=? AND key=?", (uid, key)).fetchone()
        return r[0] if r else 0

    def _achieve(self, uid: int, key: str) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO achievements(user_id,key,ts) VALUES (?,?,?)", (uid, key, self.clock()))
        return cur.rowcount > 0

    def _award(self, uid: int, kind: str, amount: int, cap: int | None) -> int:
        day = self.today()
        used = (self.db.execute("SELECT xp FROM daily WHERE user_id=? AND day=? AND kind=?", (uid, day, kind)).fetchone() or (0,))[0]
        grant = amount if cap is None else max(0, min(amount, cap - used))
        if grant <= 0:
            return 0
        self.db.execute("INSERT INTO daily(user_id,day,kind,xp) VALUES (?,?,?,?) "
                        "ON CONFLICT(user_id,day,kind) DO UPDATE SET xp=xp+?", (uid, day, kind, grant, grant))
        self.db.execute("UPDATE users SET xp=xp+? WHERE user_id=?", (grant, uid))
        return grant

    def _touch(self, uid: int, ev: Events) -> None:
        _, streak, last, _c = self._user(uid)
        today = self.today()
        if last == today:
            return
        streak = streak + 1 if last == self._yesterday() else 1
        self.db.execute("UPDATE users SET streak=?, last_day=? WHERE user_id=?", (streak, today, uid))
        if streak >= 3 and self._achieve(uid, "streak_3"):
            ev.new.append("streak_3")
        if streak >= 7 and self._achieve(uid, "streak_7"):
            ev.new.append("streak_7")

    def _run(self, fn, *a) -> Events:
        ev = Events()
        if not (self.ok and self.enabled):
            return ev
        try:
            fn(*a, ev)
            self.db.commit()
        except sqlite3.Error as e:
            log.error("SQLite fallo (%s)", type(e).__name__)
        return ev

    # ---------- eventos ----------
    def on_search(self, uid: int) -> Events:
        def f(uid, ev):
            self._touch(uid, ev)
            n = self._count(uid, "search", 1)
            ev.xp = self._award(uid, "query", QUERY_XP, self.query_cap)
            if n >= 1 and self._achieve(uid, "first_search"):
                ev.new.append("first_search")
            if n >= 10 and self._achieve(uid, "hunter"):
                ev.new.append("hunter")
        return self._run(f, uid)

    def on_free(self, uid: int) -> Events:
        def f(uid, ev):
            self._touch(uid, ev)
            if self._achieve(uid, "free_hunter"):
                ev.new.append("free_hunter")
        return self._run(f, uid)

    def on_trivia(self, uid: int, correct: bool) -> Events:
        def f(uid, ev):
            self._touch(uid, ev)
            if correct:
                n = self._count(uid, "trivia_ok", 1)
                ev.xp = self._award(uid, "trivia", TRIVIA_XP, self.trivia_cap)
                if n >= 5 and self._achieve(uid, "trivia_5"):
                    ev.new.append("trivia_5")
        return self._run(f, uid)

    def open_chest(self, uid: int) -> tuple[bool, Events]:
        """(abierto, eventos). Una vez por dia (hora de Bogota)."""
        if not (self.ok and self.enabled):
            return False, Events()
        ev = Events()
        try:
            self._touch(uid, ev)
            if self._user(uid)[3] == self.today():
                self.db.commit()
                return False, ev
            ev.xp = self._award(uid, "chest", self.rng.choice(CHEST_XP), None)
            self.db.execute("UPDATE users SET chest_day=? WHERE user_id=?", (self.today(), uid))
            if self._achieve(uid, "first_chest"):
                ev.new.append("first_chest")
            self.db.commit()
            return True, ev
        except sqlite3.Error as e:
            log.error("SQLite fallo (%s)", type(e).__name__)
            return False, ev

    def chest_available(self, uid: int) -> bool:
        if not (self.ok and self.enabled):
            return False
        try:
            return self._user(uid)[3] != self.today()
        except sqlite3.Error:
            return False

    # ---------- perfil ----------
    def profile(self, uid: int) -> Profile | None:
        if not self.ok:
            return None
        try:
            xp, streak, last, _ = self._user(uid)
            self.db.commit()
            level, nxt = LEVELS[0][1], None
            for i, (need, name) in enumerate(LEVELS):
                if xp >= need:
                    level = name
                    nxt = LEVELS[i + 1][0] if i + 1 < len(LEVELS) else None
            if last not in (self.today(), self._yesterday()):
                streak = 0                       # racha rota
            ach = [r[0] for r in self.db.execute("SELECT key FROM achievements WHERE user_id=? ORDER BY ts", (uid,))]
            return Profile(xp, level, nxt, streak, ach, self.likes(uid))
        except sqlite3.Error:
            return None

    # ---------- gustos ----------
    def likes(self, uid: int) -> list[str]:
        if not self.ok:
            return []
        try:
            return sorted(r[0] for r in self.db.execute("SELECT genre FROM likes WHERE user_id=?", (uid,)))
        except sqlite3.Error:
            return []

    def toggle_like(self, uid: int, genre: str) -> tuple[bool, list[str]]:
        """(ahora_marcado, logros_nuevos)"""
        new: list[str] = []
        if not self.ok:
            return False, new
        try:
            had = self.db.execute("SELECT 1 FROM likes WHERE user_id=? AND genre=?", (uid, genre)).fetchone()
            if had:
                self.db.execute("DELETE FROM likes WHERE user_id=? AND genre=?", (uid, genre))
            else:
                self.db.execute("INSERT INTO likes(user_id, genre) VALUES (?,?)", (uid, genre))
                if self.enabled and len(self.likes(uid)) >= 3 and self._achieve(uid, "likes_3"):
                    new.append("likes_3")
            self.db.commit()
            return (not had), new
        except sqlite3.Error:
            return False, new

    # ---------- banderas por usuario y uso de voz ----------
    def get_flag(self, uid: int, key: str) -> bool:
        if not self.ok:
            return False
        try:
            return self._count(uid, "flag_" + key) > 0
        except sqlite3.Error:
            return False

    def set_flag(self, uid: int, key: str, value: bool) -> None:
        if not self.ok:
            return
        try:
            self.db.execute("INSERT INTO counters(user_id,key,n) VALUES (?,?,?) "
                            "ON CONFLICT(user_id,key) DO UPDATE SET n=?", (uid, "flag_" + key, int(value), int(value)))
            self.db.commit()
        except sqlite3.Error:
            pass

    def voice_used(self, uid: int) -> int:
        if not self.ok:
            return 0
        try:
            r = self.db.execute("SELECT xp FROM daily WHERE user_id=? AND day=? AND kind='voice'", (uid, self.today())).fetchone()
            return r[0] if r else 0
        except sqlite3.Error:
            return 0

    def voice_use(self, uid: int) -> None:
        if not self.ok:
            return
        try:
            self.db.execute("INSERT INTO daily(user_id,day,kind,xp) VALUES (?,?, 'voice', 1) "
                            "ON CONFLICT(user_id,day,kind) DO UPDATE SET xp=xp+1", (uid, self.today()))
            self.db.commit()
        except sqlite3.Error:
            pass

    # ---------- privacidad ----------
    def delete_user(self, uid: int) -> None:
        if not self.ok:
            return
        try:
            for t in ("users", "daily", "counters", "achievements", "likes"):
                self.db.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
            self.db.commit()
        except sqlite3.Error as e:
            log.error("SQLite fallo al borrar (%s)", type(e).__name__)
