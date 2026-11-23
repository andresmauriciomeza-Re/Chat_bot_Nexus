import json
import random
from types import SimpleNamespace as NS

from app.bot import callbacks as cbm
from app.config import BACKEND_DIR
from app.features.install import install_features
from app.features.mood import MOODS, MoodStore
from app.features.store import CHEST_XP, QUERY_XP, Store
from app.features.trivia import Trivia, load_questions
from app.games.filters import Filters

from .test_ui import FakeBot, FakeMsg, make_handlers, upd

DAY = 86400.0


class Clk:
    t = 1_700_000_000.0

    def __call__(self):
        return self.t


def store(clk=None, **kw):
    return Store(":memory:", clock=clk or Clk(), rng=random.Random(3), **kw)


# ---------- animo (solo RAM, 2 h) ----------
def test_mood_ttl_and_filters():
    clk = Clk()
    m = MoodStore(clock=clk)
    assert m.set(1, "feliz") and m.get(1).key == "feliz" and m.set(1, "no_existe") is None
    clk.t += 2 * 3600 + 1
    assert m.get(1) is None
    assert all(isinstance(x.filters(), Filters) for x in MOODS.values())
    m.set(2, "triste")
    m.clear(2)
    assert m.get(2) is None


# ---------- XP, racha, cofre, logros ----------
def test_xp_daily_cap_and_first_search():
    s = store(query_cap=30)
    ev = s.on_search(1)
    assert ev.xp == QUERY_XP and "first_search" in ev.new
    total = ev.xp
    for _ in range(30):
        total += s.on_search(1).xp
    assert total == 30                                     # tope diario
    assert s.profile(1).xp == 30


def test_xp_cap_resets_next_day_and_hunter_achievement():
    clk = Clk()
    s = store(clk, query_cap=6)
    for _ in range(10):
        s.on_search(1)
    assert s.profile(1).xp == 6 and "hunter" in s.profile(1).achievements
    clk.t += DAY
    assert s.on_search(1).xp == QUERY_XP


def test_streak_and_break():
    clk = Clk()
    s = store(clk)
    for _ in range(3):
        s.on_search(1)
        clk.t += DAY
    p = s.profile(1)
    assert p.streak == 3 and "streak_3" in p.achievements
    clk.t += 3 * DAY
    assert s.profile(1).streak == 0                         # racha rota
    s.on_search(1)
    assert s.profile(1).streak == 1


def test_daily_chest_once_per_day():
    clk = Clk()
    s = store(clk)
    ok, ev = s.open_chest(1)
    assert ok and ev.xp in CHEST_XP and "first_chest" in ev.new
    ok2, ev2 = s.open_chest(1)
    assert not ok2 and ev2.xp == 0 and not s.chest_available(1)
    clk.t += DAY
    assert s.chest_available(1) and s.open_chest(1)[0]


def test_trivia_xp_cap_and_achievement():
    s = store(trivia_cap=25)
    gained = sum(s.on_trivia(1, True).xp for _ in range(6))
    assert gained == 25 and "trivia_5" in s.profile(1).achievements
    assert s.on_trivia(1, False).xp == 0


def test_likes_toggle_and_delete_everything():
    s = store()
    assert s.toggle_like(1, "accion")[0] is True
    s.toggle_like(1, "rpg")
    _, new = s.toggle_like(1, "indie")
    assert "likes_3" in new and s.likes(1) == ["accion", "indie", "rpg"]
    assert s.toggle_like(1, "rpg")[0] is False
    s.on_search(1)
    s.open_chest(1)
    s.delete_user(1)
    for t in ("users", "daily", "counters", "achievements", "likes"):
        assert s.db.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id=1").fetchone()[0] == 0
    assert s.profile(1).xp == 0


def test_gamification_disabled_still_keeps_likes():
    s = Store(":memory:", enabled=False)
    assert s.on_search(1).xp == 0 and s.open_chest(1)[0] is False
    assert s.toggle_like(1, "accion")[0] is True


def test_sqlite_unavailable_degrades(tmp_path):
    s = Store(tmp_path / "no" / "x" / ".." / ".." / "..\\<>:\"|?*bad.db")
    if not s.ok:
        assert s.on_search(1).xp == 0 and s.profile(1) is None and s.likes(1) == []


# ---------- trivia.json ----------
def test_trivia_file_has_30_questions_all_flagged():
    raw = json.loads((BACKEND_DIR / "config" / "trivia.json").read_text(encoding="utf-8"))["questions"]
    assert len(raw) == 30 and all(q["revisar"] is True for q in raw)
    qs = load_questions()
    assert len(qs) == 30 and all(len(q.options) == 4 and 0 <= q.answer < 4 for q in qs)
    t = Trivia(qs, random.Random(1))
    a, _ = t.pick(1)
    b, _ = t.pick(1)
    assert a != b and t.check(a, qs[a].answer)[0] and not t.check(a, (qs[a].answer + 1) % 4)[0]
    assert t.check(999, 0) is None


# ---------- flujos completos por handlers ----------
def cbq(data, uid=7, bot=None, msg=None):
    msg = msg or FakeMsg("x", 1)
    msg.message_id = 55
    edits = []

    async def edit_text(text, **kw):
        edits.append(text)
        return msg
    msg.edit_text = edit_text
    msg.get_bot = lambda: bot

    class Q:
        pass
    q = Q()
    q.data, q.from_user, q.message = data, NS(id=uid), msg
    q.get_bot = lambda: bot

    async def answer(*a, **k):
        pass
    q.answer = answer
    u = NS(callback_query=q, effective_user=NS(id=uid), effective_chat=NS(id=1, type="private"), get_bot=lambda: bot)
    return u, edits


async def test_flow_trivia_chest_profile_and_erase(tmp_path):
    h, A = make_handlers(tmp_path)
    install_features(A, h)
    bot = FakeBot()
    # trivia: pregunta -> respuesta correcta -> XP -> no se puede repetir
    u, edits = cbq(cbm.make("v", 7, "trivia"), bot=bot)
    await h.on_callback(u, NS(bot=bot))
    assert edits and "Trivia" in edits[0]
    qid = A["trivia"]._last[7]
    right = A["trivia"].questions[qid].answer
    u, edits = cbq(cbm.make("tq", 7, f"{qid}:{right}"), bot=bot)
    msg = u.callback_query.message
    await h.on_callback(u, NS(bot=bot))
    assert "Correcto" in edits[0] and "+10 XP" in edits[0]
    u2, edits2 = cbq(cbm.make("tq", 7, f"{qid}:{right}"), bot=bot, msg=msg)
    await h.on_callback(u2, NS(bot=bot))
    assert not edits2                                           # segunda respuesta: sin XP doble
    assert A["store"].profile(7).xp == 10
    # cofre
    u, edits = cbq(cbm.make("ch", 7), bot=bot)
    await h.on_callback(u, NS(bot=bot))
    assert "Abriste el cofre" in edits[0]
    u, edits = cbq(cbm.make("v", 7, "chest"), bot=bot)
    await h.on_callback(u, NS(bot=bot))
    assert "Ya abriste" in edits[0]
    # perfil
    u, edits = cbq(cbm.make("v", 7, "profile"), bot=bot)
    await h.on_callback(u, NS(bot=bot))
    assert "Primer cofre" in edits[0] and "Nivel" in edits[0]
    # borrar datos
    u, edits = cbq(cbm.make("bx", 7), bot=bot)
    await h.on_callback(u, NS(bot=bot))
    assert A["store"].profile(7).xp == 0 and A["moods"].get(7) is None


async def test_flow_mood_and_likes(tmp_path):
    h, A = make_handlers(tmp_path)
    install_features(A, h)
    bot = FakeBot()
    u, edits = cbq(cbm.make("md", 7, "estresado"), bot=bot)
    await h.on_callback(u, NS(bot=bot))
    assert A["moods"].get(7).key == "estresado" and "Respira" in edits[0]
    u, edits = cbq(cbm.make("lk", 7, "accion"), bot=bot)
    await h.on_callback(u, NS(bot=bot))
    assert A["store"].likes(7) == ["accion"]
    u, edits = cbq(cbm.make("v", 7, "likes"), bot=bot)
    await h.on_callback(u, NS(bot=bot))
    markup_texts = []
    v = await A["panel"].build("likes", NS(user_id=7, chat_id=1, arg="", app=A))
    markup_texts = [b.text for r in v.rows for b in r]
    assert "✅ Acción" in markup_texts


async def test_likes_feed_recommendations_and_flags_off(tmp_path):
    h, A = make_handlers(tmp_path, gamification_enabled=False, mood_enabled=False)
    install_features(A, h)
    A["store"].toggle_like(7, "terror")
    seen = {}

    async def fake_rec(f):
        seen["genres"] = set(f.genres)
        return []
    A["svc"].recommend = fake_rec
    await A["pipe"].recommend("7", Filters())
    assert seen["genres"] == {"terror"}                          # gustos aplicados por codigo
    ctx = NS(user_id=7, chat_id=1, arg="", app=A)
    assert "apagada" in (await A["panel"].build("mood", ctx)).text
    assert "apagada" in (await A["panel"].build("profile", ctx)).text


async def test_no_xp_or_panels_during_risk(tmp_path):
    h, A = make_handlers(tmp_path)
    install_features(A, h)
    bot = FakeBot()
    u, m = upd("me quiero morir", bot=bot)
    await h.on_text(u, NS(bot=bot))
    cb, edits = cbq(cbm.make("ch", 7), bot=bot)
    await h.on_callback(cb, NS(bot=bot))
    assert not edits and A["store"].profile(7).xp == 0
