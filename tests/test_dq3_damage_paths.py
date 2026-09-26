"""ダメージ床は、ほかに道があれば通らない（RX3-0277 / 2026-09-17）。

★RX3-0262 で判定（collision 0x05 = 2 / 0x06 = 15）は確定し、経路は変えていなかった。ここで経路を変える。

```text
★ほかに道がある   ダメージ床を通らない（⚠ 遠回りしてでも）
★道が無い         今までどおり通る（⚠ 行けなくなる場所を作らない）
★ダメージ床の無い地図  経路は 1 升も変わらない
```

⚠ 同じ規則を Lua（`nav_v0.lua` の `bfs`）にも書いた。★Lua 側は `test_dq3_nav_v0.py` の足場が見る。
"""
from __future__ import annotations

import os
import pathlib
import random

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.testing import passability as P                    # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")

#: ★tile 0 = 床 / 1 = 壁 / 2 = ダメージ床（2）/ 3 = ダメージ床（15）
TABLE = [0x00, 0x80, 0x05, 0x06] + [0x00] * 28


def _map(rows):
    tiles = [[ord(c) - ord("0") for c in row] for row in rows]
    return P.RomMap(map_id=1, tiles=tiles, table=TABLE, tileset=0)


#: ```text
#: 0 0 0 0 0
#: 0 1 2 1 0     ← ★(2,1) がダメージ床。まっすぐ下りれば 2 歩、回れば 6 歩
#: 0 0 0 0 0
#: ```
AROUND = ["00000", "01210", "00000"]


def _hurt(rom, start, path):
    return sum(rom.damage(*c) or 0 for c in rom.walk(start, path))


def test_回り道があればダメージ床を通らない():
    m = _map(AROUND)
    old = m.bfs((2, 0), (2, 2), avoid_damage=False)
    new = m.bfs((2, 0), (2, 2))
    assert old == ["down", "down"] and _hurt(m, (2, 0), old) == 2, "⚠ 前提: 今までは真ん中を通っていた"
    assert _hurt(m, (2, 0), new) == 0, "⚠⚠ 回り道があるのにダメージ床を通った: %s" % new
    assert len(new) == 6, new


def test_道が無ければダメージ床を通る():
    m = _map(["11011", "11311", "11011"])
    assert m.bfs((2, 0), (2, 2)) == ["down", "down"], "⚠⚠ ダメージ床しか無いのに行けなくなった"


def test_目的地がダメージ床なら着ける():
    m = _map(AROUND)
    assert m.bfs((2, 0), (2, 1)) == ["down"]


def test_鍵とふさがった升と一緒に使える():
    """★`blocked`（固定の NPC）と `keys`（扉）の規則は変わらない。"""
    m = _map(AROUND)
    got = m.bfs((2, 0), (2, 2), blocked=[(1, 0), (0, 0)])
    assert _hurt(m, (2, 0), got) == 0 and len(got) == 6, "★右回りで避ける: %s" % got
    got = m.bfs((2, 0), (2, 2), blocked=[(1, 0), (3, 0)])
    assert got == ["down", "down"], "★両側ふさがれたら通る: %s" % got


def test_ダメージ床の無い地図では経路が変わらない_偽の地図():
    m = _map(["00000", "01110", "00000", "01010"])
    for a in [(0, 0), (4, 3), (2, 2)]:
        for b in [(4, 0), (0, 3), (2, 0)]:
            assert m.bfs(a, b) == m.bfs(a, b, avoid_damage=False), (a, b)


def test_避けられなかったダメージ床を経路に添える():
    """★RX3-0277（2026-09-18 依頼者「save1 回り込まないが、毒沼超えしか道はない」）。

    ⚠ 黙って踏むと「避ける仕組みが効いていない」ように見える。★避けられなかったぶんを `damage` で返し、人に見せる。
    """
    from dq3.testing import navigation as NAV

    m = _map(AROUND)
    around = NAV.plan(m, (2, 0), (2, 3))          # ★回り込める（★沼を通らない）
    assert around is not None and around["damage"] == 0 and around["damage_cells"] == []
    only = _map(["11011", "11311", "11011", "11011"])
    forced = NAV.plan(only, (2, 0), (2, 3))       # ⚠ 沼しか道が無い
    assert forced is not None and forced["damage"] == 15 and forced["damage_cells"] == [[2, 1]]


def test_毒の床を通る相手は後回しにする(tmp_path):
    """★RX3-0277（2026-09-18 依頼者「毒の沼を超えて聞き込みにいく」）。

    ⚠⚠ 実測（テドンの夜）: 沼の向こうの 1 人へ**行き 24 / 帰り 22 = 46** 減っていた。
    ★近い順だけで並べると途中で渡り、次の人のために戻ってもう一度渡る。→ ★渡る相手を最後にする。
    """
    from dq3.knowledge.town_service import TownService

    svc = TownService.__new__(TownService)
    svc._rom_maps = {}
    plans = {1: {"steps": 30, "damage": 0}, 2: {"steps": 5, "damage": 24}, 3: {"steps": 12, "damage": 0}}
    svc.plan_to = lambda m, s, n, o=(), **kw: dict(plans[n["npc_id"]], goal=[n["x"], n["y"]])
    svc.current_npcs = lambda *a, **k: {"status": "DEFAULT", "npcs": [
        {"npc_id": i, "x": i, "y": 0, "talk_id": 10 + i, "movement": "fixed"} for i in (1, 2, 3)]}
    svc.heard_now = lambda *a, **k: False
    got = svc.unheard_reachable_npcs(21, None, None, (0, 0))
    assert [r["npc"]["npc_id"] for r in got] == [3, 1, 2], "⚠⚠ 毒の床を通る 2 番目が先頭に来た"
    assert [r["damage"] for r in got] == [0, 0, 24]


def test_町の仲介も毒の床を落とさず渡す(tmp_path):
    """⚠ `navigation.plan` → `TownService.plan_to` → 画面 の**途中で落ちない**こと（RX3-0277）。"""
    from dq3.knowledge.town_service import TownService

    svc = TownService.__new__(TownService)                 # ★ROM も記録も要らない（★`rom_map` だけ差し替える）
    svc._rom_maps = {1: _map(["11011", "11311", "11011", "11011"])}
    got = svc.plan_to(1, (2, 0), {"x": 2, "y": 3})
    assert got is not None and got["damage"] == 15 and got["damage_cells"] == [[2, 1]]


def test_町のUIは避けられない毒の床を文と記録に出す(tmp_path):
    """⚠ 依頼者が「避けたのか / 避けられなかったのか」を区別できるように（RX3-0277）。"""
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from test_dq3_town_ui import _Commands, _Env, _Service, _VM       # noqa: E402

    from dq3 import action_log as AL
    from dq3.ui.town_bar import TownNavController

    class _EnvLine(_Env):
        """★本物の環境と同じく `line`（記録の 1 行）を持つ。⚠ `_Env` だけだと `_env_line` が黙って何もしない。"""

        def __init__(self):
            super().__init__()
            self.lines = []

        def line(self, text):
            self.lines.append(text)

    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    ctl = TownNavController(vm, svc, cmd, clock=lambda: 0.0, action_log=AL.ActionLog(clock=lambda: 0.0))
    ctl.env_hook = _EnvLine()
    svc._plan = lambda n: {"goal": [n["x"], n["y"] + 2], "face": "up", "keys": ["up"] * 3,
                           "cells": [[8, 17], [8, 16], [8, 15]], "steps": 3, "doors": [],
                           "damage": 22, "damage_cells": [[8, 16]]}
    assert ctl.start_hearing()
    assert "毒の床 22" in ctl.message, ctl.message
    assert any("DAMAGE_FLOOR hp=22" in ln for ln in ctl.env_hook.lines), ctl.env_hook.lines


def test_Luaの地図ではダメージ床をHで書く():
    from dq3.knowledge.town_service import TownService

    m = _map(AROUND)
    got = TownService.grid_text(m).splitlines()
    # ★H はダメージ床の升だけ（⚠ 両隣の壁は、この小さな地図ではカウンター K に見える = 別の規則）
    assert [(x, y) for y, row in enumerate(got[1:]) for x, c in enumerate(row) if c == "H"] == [(2, 1)], got
    assert m.to_text().splitlines()[2][2] == "P", "⚠ `to_text` は P のまま（★probe・検査が前提にしている）"


# ----------------------------------------------------------------------
# ★ROM あり
# ----------------------------------------------------------------------
def _maps():
    got = []
    for map_id in range(256):
        try:
            got.append(P.from_rom(map_id, ROM_PATH))
        except Exception:                                   # noqa: BLE001 ★表に無い map
            continue
    return got


@pytest.fixture(scope="module")
def maps():
    return _maps()


def _pairs(rom, rng, n):
    floor = [(x, y) for y in range(rom.height) for x in range(rom.width)
             if rom.klass(x, y) in (P.PASS, P.CHEST)]
    return [tuple(rng.sample(floor, 2)) for _ in range(n)] if len(floor) >= 2 else []


@needs_rom
def test_ダメージ床の無い地図では経路が1升も変わらない(maps):
    """★RX3-0277 Tests「今までの経路が変わっていないこと」（★2026-09-17 実測: 5335 組すべて同じ）。"""
    rng = random.Random(277)
    checked = 0
    for rom in maps:
        cells = [(x, y) for y in range(rom.height) for x in range(rom.width)]
        if any(rom.damage(*c) is not None for c in cells):
            continue
        for a, b in _pairs(rom, rng, 10):
            assert rom.bfs(a, b) == rom.bfs(a, b, avoid_damage=False), (rom.map_id, a, b)
            checked += 1
    assert checked > 1000, "⚠ 比べた組が少ない（★この検査は空回り）: %d" % checked


@needs_rom
def test_ダメージ床のある地図で減るHPが増えない(maps):
    rng = random.Random(277)
    changed = 0
    damaged = [rom for rom in maps if any(rom.damage(x, y) is not None
                                          for y in range(rom.height) for x in range(rom.width))]
    assert len(damaged) == 14, "⚠ ダメージ床のある地図の数が変わった: %d" % len(damaged)
    for rom in damaged:
        for a, b in _pairs(rom, rng, 20):
            old = rom.bfs(a, b, avoid_damage=False)
            if old is None:
                assert rom.bfs(a, b) is None, "⚠⚠ 行けなかった所へ行けるようになった"
                continue
            new = rom.bfs(a, b)
            assert new is not None, "⚠⚠ 行けなくなった: map %d %s → %s" % (rom.map_id, a, b)
            assert _hurt(rom, a, new) <= _hurt(rom, a, old), (rom.map_id, a, b)
            changed += new != old
    assert changed > 0, "⚠ 1 組も変わらない（★避ける仕組みが効いていない）"


@needs_rom
def test_テドンの沼を避ける(maps):
    """★map 21（2 ダメージの床が 74 升）: (4,3) → (4,38) は 22 減る道から、2 歩遠回りの減らない道へ。"""
    rom = next(r for r in maps if r.map_id == 21)
    old = rom.bfs((4, 3), (4, 38), avoid_damage=False)
    new = rom.bfs((4, 3), (4, 38))
    assert (len(old), _hurt(rom, (4, 3), old)) == (45, 22)
    assert (len(new), _hurt(rom, (4, 3), new)) == (47, 0)
