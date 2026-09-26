"""経路は固定の NPC の升を通らない（RX3-0176 / 2026-09-12）。

⚠⚠ 依頼者「ロマリアかくとうじょうで聞き込みがきかない（save4）」。
★格闘場（map 72）で受付（固定 / (6,14)）と話したあと、(6,15) から引いた経路が 7 人とも
**受付の升を通っていた** → 実機では 1 歩目で受付にぶつかり「経路ずれ」で 7 人とも飛ばされた。
→ ★経路探索は固定の NPC の升を通らない。
⚠ 動く NPC は避けない（★位置は歩くうちに変わる。塞がれたら Lua の replan に任せる）。

★見本の表は依頼者の save4 の 1 つ前（格闘場・時間帯 0x35）の $0110〜$0177 を写したもの
（⚠ セーブは撮り直されるので、セーブを名指しで読まない / 教訓「セーブを番号で名指しすると壊れる」）。
"""
from __future__ import annotations

import pytest

from dq3.knowledge import npc_heard as H
from dq3.knowledge import npc_master as NM
from dq3.knowledge import town_service as TS
from dq3.testing import navigation as NAV
from dq3.testing import passability as P

#: ★格闘場の実機の NPC の表（9 人 / 2026-09-12 08:06 / 受付の真下 (6,15)）
ARENA = ("020204010d020501060e0692040407820c0908970b0a09980e0c0683010c04a104190a82"
         + "ff" * 64 + "fe800000")
TIME = 0x35
ARENA_MAP = 72
START = (6, 15)
RECEPTION = (6, 14)

assert len(bytes.fromhex(ARENA)) == 0x68


def _ready() -> bool:
    try:
        return len(NM._lists()) > ARENA_MAP
    except Exception:                                            # noqa: BLE001
        return False


needs_rom = pytest.mark.skipif(not _ready(), reason="DQ3 の ROM が読めない")

PASS_TILE, WALL_TILE = 8, 2


def _rom(rows: list[str]) -> P.RomMap:
    """★文字の地図 → RomMap（`.` 床 / `#` 壁）。⚠ ROM を使わない。"""
    table = [0x00] * 32
    table[WALL_TILE] = 0x80 | 0x10                  # ★壁（⚠ カウンターに見えないよう壁の形の bit も立てる）
    tiles = [[WALL_TILE if c == "#" else PASS_TILE for c in row] for row in rows]
    return P.RomMap(999, tiles, table, 0)


# ----------------------------------------------------------------------
# ★bfs / plan（ROM なし）
# ----------------------------------------------------------------------

def test_bfsは避ける升を通らない():
    m = _rom(["...", "...", "..."])
    assert m.bfs((0, 1), (2, 1)) == ["right", "right"], "⚠ 既定の振る舞いが変わった"
    path = m.bfs((0, 1), (2, 1), blocked={(1, 1)})
    assert path is not None and len(path) == 4
    assert (1, 1) not in m.walk((0, 1), path), "⚠⚠ 避ける升を通った"


def test_bfsは避ける升で道が無ければNone():
    m = _rom([".....", "#####"])
    assert m.bfs((0, 0), (4, 0), blocked={(2, 0)}) is None


def test_planは避ける升を通らない():
    m = _rom(["...", "...", "..."])
    got = NAV.plan(m, (0, 2), (2, 0), avoid={(1, 1), (1, 2), (0, 1)})
    assert got is None or not {(1, 1), (1, 2), (0, 1)} & {tuple(c) for c in got["cells"]}
    got = NAV.plan(m, (0, 2), (2, 0), avoid={(1, 1)})
    assert got is not None and (1, 1) not in {tuple(c) for c in got["cells"]}


# ----------------------------------------------------------------------
# ★town_service: 固定は避ける / 動く人は避けない（ROM なし）
# ----------------------------------------------------------------------

def _corridor_service(tmp_path, blocker_movement: str) -> TS.TownService:
    """★1 本道: 自分 (0,1) → 真ん中 (2,1) に誰か → 奥 (4,1) に話す相手。"""
    m = _rom(["#####", ".....", "#####"])
    svc = TS.TownService(heard=H.HeardLedger(tmp_path), rom_maps={999: m})
    npcs = [
        {"npc_id": 0, "slot": 4, "x": 2, "y": 1, "movement": blocker_movement, "talk_id": 0,
         "appearance_id": 8, "role": None, "role_status": None},
        {"npc_id": 1, "slot": 5, "x": 4, "y": 1, "movement": "fixed", "talk_id": 100,
         "appearance_id": 8, "role": None, "role_status": None},
    ]
    svc.current_npcs = lambda *a, **k: {"map_id": 999, "time": "day", "status": "DEFAULT",
                                        "npcs": npcs, "runtime_count": 2}
    return svc


def test_固定のNPCが道を塞いでいたら候補にしない(tmp_path):
    svc = _corridor_service(tmp_path, "fixed")
    assert svc.unheard_reachable_npcs(999, TIME, None, (0, 1)) == [], \
        "⚠⚠ 固定の NPC の升を通る経路を出した（★実機ではぶつかって「経路ずれ」になる）"


def test_動くNPCの升は避けない(tmp_path):
    """★今の位置は歩くうちに変わる。⚠ 避けると、たまたま立っているだけで候補から消える。"""
    svc = _corridor_service(tmp_path, "random")
    got = svc.unheard_reachable_npcs(999, TIME, None, (0, 1))
    assert [c["npc"]["npc_id"] for c in got] == [1]


# ----------------------------------------------------------------------
# ★格闘場（ROM あり / 依頼者の save4 の表）
# ----------------------------------------------------------------------

@needs_rom
def test_格闘場の表は既定の表で読める():
    got = NM.master_for(ARENA_MAP, TIME, ARENA)
    assert NM.variant_status(ARENA_MAP) == "UNKNOWN", "★格闘場は差し替えのある map"
    assert got["status"] == "DEFAULT" and len(got["npcs"]) == 9


@needs_rom
def test_格闘場で受付の升を通らずに全員へ行ける(tmp_path):
    svc = TS.TownService(heard=H.HeardLedger(tmp_path))
    cur = svc.current_npcs(ARENA_MAP, TIME, ARENA)
    fixed = {(n["x"], n["y"]) for n in cur["npcs"] if n["movement"] == "fixed"}
    assert RECEPTION in fixed
    got = svc.unheard_reachable_npcs(ARENA_MAP, TIME, ARENA, START)
    ids = sorted(c["npc"]["npc_id"] for c in got)
    assert ids == [0, 1, 2, 3, 4, 5, 6, 7], "⚠⚠ 格闘場で届かない人がいる: %s" % ids
    for c in got:
        cells = {tuple(x) for x in c["plan"]["cells"]}
        assert RECEPTION not in cells, "⚠⚠ npc %d への経路が受付の升 (6,14) を通る" % c["npc"]["npc_id"]
        assert not cells & fixed, "⚠⚠ npc %d への経路が固定の NPC の升を通る: %s" % (
            c["npc"]["npc_id"], sorted(cells & fixed))
