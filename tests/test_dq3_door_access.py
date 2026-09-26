"""鍵を使って扉を開け、聞き込みを続ける（RX3-0159 / 2026-09-11）。

★依頼者の注意（2026-09-11）:

> まだ盗賊の鍵しかないが、扉の種類に応じて使う道具が異なるし、
> 誰がどの鍵を持っているかの把握も必要なので注意。

→ ★ここで固定するのは 3 つ:

```text
1 扉の種類 → 開けられる鍵（★ROM の判定のとおり / いちばん強い鍵 = 上位互換 / RX3-0244）
2 誰の袋の何番目か（★並びの前の人 / ⚠ 装備の印 bit7 を落とす）
3 聞き込みが「扉の手前で区切る → 鍵を使う → 同じ相手へ歩き直す」になる
```
"""
from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.knowledge import door_access as DA          # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
#: ★鍵の名前・タイル列は ROM（`item_info`）から引く（RX3-0159）
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")

THIEF, MAGIC, FINAL = 88, 89, 90
HERB = 101


def _bag(*items):
    return {"inventory": list(items) + [0xFF] * (8 - len(items))}


# ======================================================================
# ★誰がどの鍵を持っているか
# ======================================================================

@needs_rom
def test_鍵を持ち主と袋の位置つきで拾う():
    """★実機 slot 4 の袋そのまま（[2,48,101,69,56,88,34] の 6 番目）。"""
    got = DA.key_holders([_bag(2, 48, 101, 69, 56, 88, 34), _bag(HERB)])
    assert len(got) == 1
    k = got[0]
    assert (k.member, k.item_id, k.rank, k.bag_row) == (0, THIEF, 0, 5)
    assert k.name == "とうぞくのかぎ", "⚠ ROM の名前を引けていない"


def test_装備の印を落としてから見る():
    """⚠ bit7 は「装備中」（★鍵は装備しないが、印つきで来ても取りこぼさない）。"""
    got = DA.key_holders([_bag(HERB, THIEF | 0x80)])
    assert [(k.item_id, k.bag_row) for k in got] == [(THIEF, 1)]


def test_袋が読めなければ空():
    """⚠ 推測で「持っている」ことにしない。"""
    assert DA.key_holders(None) == []
    assert DA.key_holders([{"no": "inventory"}]) == []


# ======================================================================
# ★扉の種類で鍵を選ぶ（⚠ 依頼者の注意 1）
# ======================================================================

#: ⚠⚠ 2026-09-13（RX3-0244）依頼者「ドラクエ３はカギは上位互換 さいごのカギ＞まほうのカギ＞とうぞくのかぎ
#:   聞き込みのときも、そのように動かしたい」→ ★いちばん強い鍵を使う（⚠ 以前は「いちばん弱い鍵」を固定していた）。
@pytest.mark.parametrize("nibble, keys, want", [
    (0x0B, [THIEF], THIEF),                       # ★どの鍵でも
    (0x0C, [THIEF], None),                        # ⚠ とうぞくでは開かない
    (0x0C, [THIEF, MAGIC], MAGIC),
    (0x0C, [MAGIC, FINAL], FINAL),                # ★上位互換: いちばん強い鍵
    (0x0D, [THIEF, MAGIC], None),                 # ⚠ さいごのかぎだけ
    (0x0D, [THIEF, FINAL], FINAL),
    (0x0B, [FINAL, THIEF], FINAL),                # ★とうぞくの扉も さいごのかぎ で
    (0x0B, [THIEF, MAGIC], MAGIC),                # ★とうぞくの扉も まほうのかぎ で
])
def test_扉の種類で使う鍵が変わる(nibble, keys, want):
    holders = DA.key_holders([_bag(*keys)])
    got = DA.key_for_door(nibble, holders)
    assert (got.item_id if got else None) == want


def test_いまのパーティでは_とうぞくの扉も_まほうのかぎの持ち主が開ける():
    """★2026-09-13 の依頼者のパーティ（work/state.json）: p1 に まほうのかぎ / p4 に とうぞくのかぎ。

    ⚠ 以前は $0B の扉を p4 の とうぞくのかぎ で開けていた（★16:50 の記録）。★上位互換で p1 の まほうのかぎ。
    """
    bags = [_bag(185, MAGIC, 165, 133, 198), _bag(185, 102, 164, 116, 139, 198),
            _bag(132, 175, 189, 101, 101, 104, 197), _bag(176, 135, 102, 103, THIEF, 103, 197)]
    holders = DA.key_holders(bags)
    for nibble in (0x0B, 0x0C):
        got = DA.key_for_door(nibble, holders)
        assert (got.member, got.item_id, got.bag_row) == (0, MAGIC, 1), (nibble, got)
    assert DA.key_for_door(0x0D, holders) is None, "⚠ さいごのかぎ の扉は開かない"


def test_同じ鍵なら並びの前の人():
    holders = DA.key_holders([_bag(HERB), _bag(THIEF), _bag(THIEF)])
    got = DA.key_for_door(0x0B, holders)
    assert (got.member, got.bag_row) == (1, 0)


def test_扉でなければ鍵を選ばない():
    assert DA.key_for_door(None, DA.key_holders([_bag(THIEF)])) is None


# ======================================================================
# ★経路の上の扉
# ======================================================================

class _Rom:
    def __init__(self, doors): self.doors = doors
    def door_nibble(self, x, y): return self.doors.get((x, y))


def test_経路の最初の扉を見つける():
    rom = _Rom({(9, 3): 0x0B, (5, 3): 0x0C})
    got = DA.door_on_path(rom, [[10, 3], [9, 3], [8, 3], [5, 3]])
    assert got == (1, (9, 3), 0x0B)


def test_開けた扉は数えない():
    """★ROM の地図は扉のままなので、⚠ 開けた扉は自分で覚えて飛ばす。"""
    rom = _Rom({(9, 3): 0x0B, (5, 3): 0x0C})
    got = DA.door_on_path(rom, [[10, 3], [9, 3], [8, 3], [5, 3]], opened=[(9, 3)])
    assert got == (3, (5, 3), 0x0C)


@needs_rom
def test_Luaへ渡すのは語のタイルで行番号ではない():
    """⚠ 行番号を渡すと、並びが違ったときに**別の道具を使う**（補充と同じ約束）。"""
    hold = DA.key_holders([_bag(HERB), _bag(HERB, THIEF)])[0]
    got = DA.use_params(hold)
    assert got["member"] == "2", "⚠ 並びは 1 始まりで渡す"
    assert set(got) == {"member", "item", "choose"}, "⚠ 行番号を渡している"
    assert len(got["item"]) == 2 * len("とうそくのかき"), "⚠ 濁点は上の行（★基底の字だけ）"
    assert len(got["choose"]) == 2 * len(DA.USE_WORD)
    # ⚠⚠ `action` は `commands.send(action, **params)` と衝突する（2026-09-11 に踏んだ）
    assert "action" not in got


# ======================================================================
# ★聞き込みが扉を挟む（⚠ 依頼者「その動きで OK」）
# ======================================================================

@pytest.fixture
def door_world(tmp_path):
    from test_dq3_town_ui import _Commands, _Service, _VM

    from dq3 import action_log as AL
    from dq3.ui.town_bar import TownNavController

    class _DoorService(_Service):
        """★扉 (8,16) を通る経路（★2 歩目が扉）。"""

        def rom_map(self, map_id):
            return _Rom({(8, 16): 0x0B})

        def _plan(self, n):
            return {"goal": [8, 15], "face": "up", "keys": ["up"] * 3,
                    "cells": [[8, 17], [8, 16], [8, 15]], "steps": 3}

    class _DoorVM(_VM):
        def __init__(self):
            super().__init__()
            self.bags = [_bag(HERB), _bag(HERB, THIEF), _bag(), _bag()]
            self.item = None

        def equip_members(self): return self.bags
        def item_status(self): return self.item

    vm, svc, cmd = _DoorVM(), _DoorService(tmp_path), _Commands()
    svc.npcs = [svc.npcs[0]]
    clock = [0.0]
    ctl = TownNavController(vm, svc, cmd, clock=lambda: clock[0],
                            action_log=AL.ActionLog(clock=lambda: clock[0]))
    return vm, svc, cmd, ctl, clock


def _nav_done(vm, ctl, reason):
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": reason}
    ctl.poll()


def test_扉の手前で区切って向く(door_world):
    vm, svc, cmd, ctl, _ = door_world
    assert ctl.start_hearing()
    action, params = cmd.sent[-1]
    assert action == "navigate"
    assert params["keys"] == "up" and params["cells"] == "8:17", "⚠ 扉の手前で区切っていない"
    assert params["face"] == "up", "⚠ 扉を向いていない"
    assert params["talk"] == "0", "⚠⚠ 扉に話しかけようとしている"


@needs_rom
def test_着いたら持ち主の鍵を使う(door_world):
    """★依頼者「誰がどの鍵を持っているか」→ ★2 人目の袋の 2 番目。"""
    vm, svc, cmd, ctl, _ = door_world
    ctl.start_hearing()
    _nav_done(vm, ctl, "arrived")
    action, params = cmd.sent[-1]
    assert action == "use_item"
    assert params["member"] == "2", "⚠⚠ 鍵の持ち主を選べていない"


@needs_rom
def test_開いたら同じ相手へ歩き直す(door_world):
    vm, svc, cmd, ctl, _ = door_world
    ctl.start_hearing()
    _nav_done(vm, ctl, "arrived")
    vm.item = {"seq": ctl.item_seq, "phase": "done", "reason": "used"}
    ctl.poll()
    action, params = cmd.sent[-1]
    assert action == "navigate"
    assert params["keys"] == "up,up,up", "⚠ 扉の向こうまで歩いていない"
    assert params["talk"] == "1"
    assert ("opened" in str(ctl.log)), "⚠ 開けた扉を覚えていない"


@needs_rom
def test_開けられなければその人を飛ばす(door_world):
    vm, svc, cmd, ctl, _ = door_world
    ctl.start_hearing()
    _nav_done(vm, ctl, "arrived")
    vm.item = {"seq": ctl.item_seq, "phase": "done", "reason": "item_not_on_screen"}
    ctl.poll()
    assert ctl.mode is None, "⚠ 次の相手がいないのに終わっていない"
    assert any(r.get("reason") == "door_not_opened" for r in ctl.log)
    assert "扉を開けられず1" in ctl.action_log.rows[-1].line()


def test_鍵が袋に無ければ扉へ行かない(door_world):
    """⚠ 鍵つきで経路を引いたのに袋に無い（★袋が読めない）→ ★「鍵が要る」で飛ばす。"""
    vm, svc, cmd, ctl, _ = door_world
    vm.bags = [_bag(HERB), _bag(), _bag(), _bag()]
    assert ctl.start_hearing() is False
    assert not any(a == "use_item" for a, _p in cmd.sent), "⚠⚠ 鍵が無いのに使おうとした"
    assert "鍵が要る1" in ctl.action_log.rows[-1].line()


def test_止めたら扉の段も片づく(door_world):
    vm, svc, cmd, ctl, _ = door_world
    ctl.start_hearing()
    _nav_done(vm, ctl, "arrived")
    ctl.stop()
    assert ctl._door is None and ctl.mode is None
