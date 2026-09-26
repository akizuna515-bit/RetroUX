"""覚えが無くても町の出口へ行ける（RX3-0341 / 2026-09-21）。

⚠⚠ 依頼者「save3 自動移動で出口に出れない。街に入ったらデフォルトで入る座標が
あるかと思うが、そこを使えないか？」

## ★調べて分かったこと

```text
⚠ 入った升は ROM の表に**無い**（★`world_in` の `to_x/to_y` は全部 None / 62 件とも）
★町は**端から歩いて出る**（`map_graph` の `world_edge` は x, y が None）
→ ★「出口」＝ **外周のうち歩ける升**。⚠ 地図だけで出せる
```

## ⚠ 今までの困りごと

`town_bar.note_entry` は**動かしている間しか覚えません**。
⚠ 町の中でセーブを読むと入口が分からず、★[入] のボタンが出ませんでした。
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from dq3 import action_log as AL                              # noqa: E402
from dq3.knowledge import town_service as TS                  # noqa: E402
from dq3.ui import town_bar as TB                             # noqa: E402
from test_dq3_town_ui import _Commands, _Service, _VM         # noqa: E402

ROM = ROOT / "input" / "Dragon Quest 3 (J).nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="⚠ ROM が読めない環境")


# ======================================================================
# ★1. ROM の地図から「出口の升」が出る
# ======================================================================
@needs_rom
def test_町には歩ける端がある(tmp_path):
    """★町は端から出るので、⚠ 外周に歩ける升があるはず。"""
    svc = TS.TownService(tmp_path)
    for map_id in (9, 14, 17):
        cells = svc.exit_cells(map_id)
        assert cells, "⚠ map %d に歩ける端が無い（★町なのに出られない）" % map_id
        rom = svc.rom_map(map_id)
        for x, y in cells:
            assert x in (0, rom.width - 1) or y in (0, rom.height - 1), (
                "⚠ 端でない升が混ざっている: (%d, %d)" % (x, y))


@needs_rom
def test_屋内には出口が無い(tmp_path):
    """⚠⚠ 城の中は端が全部壁（★階段で出る）。→ ★候補を出してはいけない。"""
    svc = TS.TownService(tmp_path)
    rom = svc.rom_map(88)
    assert rom is not None, "⚠ map 88 を読めない（★この検査が何も見ていない）"
    # ⚠⚠ **中の升**から見ること（★端の升そのものから始めると 0 歩で「着いて」しまう /
    #   2026-09-21 に実際に踏んだ）。
    start = (8, 10)
    assert rom.klass(*start) == "PASS", "⚠ 前提が崩れた（★中の升が歩けない）"
    assert svc.exit_cells(88), "⚠ 端に歩ける升が無い（★この検査は「行けない」を見たい）"
    assert svc.plan_to_exit(88, start) is None, "⚠⚠ 屋内なのに出口への道が出た"


@needs_rom
def test_もう出口に居るならその升は選ばない(tmp_path):
    """⚠ 自分が立っている升を「行き先」にしない（★0 歩の道を返さない）。

    ⚠⚠ 2026-09-21 の壊す実験で、★この行（`tuple(start) == cell` で飛ばす）を外しても
      **緑のまま**でした。→ ★端に立った場面を足しました。
    """
    svc = TS.TownService(tmp_path)
    cells = svc.exit_cells(9)
    assert cells, "⚠ 前提が崩れた（★端が無い）"
    here = cells[0]
    plan = svc.plan_to_exit(9, here)
    assert plan is None or tuple(plan["cell"]) != tuple(here), (
        "⚠⚠ いま立っている升を出口として返した: %s" % (plan and plan["cell"]))
    if plan is not None:
        assert plan["steps"] > 0, "⚠ 0 歩の道を返した（★動かないのに『行ける』と出る）"


@needs_rom
def test_一番近い出口を選ぶ(tmp_path):
    """★端が複数あるとき、⚠ **歩数が一番少ない**ものを選ぶ。"""
    svc = TS.TownService(tmp_path)
    plan = svc.plan_to_exit(9, (13, 13))
    assert plan is not None, "⚠ 出口への道が出ない"
    cells = svc.exit_cells(9)
    best = None
    for cell in cells:
        got = svc.plan_to(9, (13, 13), {"x": cell[0], "y": cell[1]})
        if got is not None and (best is None or got["steps"] < best):
            best = got["steps"]
    assert plan["steps"] == best, (
        "⚠ 一番近い出口ではない: %d 歩（★最短は %d 歩）" % (plan["steps"], best))
    assert tuple(plan["cell"]) in set(cells), "⚠ 出口でない升を返した"


# ======================================================================
# ★2. 画面側（★覚えが無くても [入] が出る）
# ======================================================================
class _ExitService(_Service):
    """★偽の service に「出口への道」を足す（⚠ 本物の BFS は上で見ている）。"""

    def __init__(self, tmp, *, exit_cell=(5, 0)):
        super().__init__(tmp)
        self.exit_cell = exit_cell
        self.exit_calls = 0

    def plan_to_exit(self, map_id, start, others=(), *, keys=(), avoid=()):
        self.exit_calls += 1
        if self.exit_cell is None:
            return None                                   # ⚠ 屋内
        return {"goal": list(self.exit_cell), "face": "up", "keys": ["up"],
                "cells": [list(self.exit_cell)], "steps": 4, "doors": [],
                "cell": list(self.exit_cell)}


class _Book:
    """★場所の台帳の口だけ（RX3-0355 / ⚠ 本物の台帳は読まない）。"""

    def __init__(self, towns=(9,)):
        self.towns = set(towns)

    def is_town_like(self, map_id):
        return int(map_id) in self.towns


def _ctl(tmp_path, *, towns=(9,), **kw):
    vm, svc, cmd = _VM(), _ExitService(tmp_path, **kw), _Commands()
    # ★端を探すのは「町だと分かっている」ときだけ（RX3-0355）
    vm.location_book = _Book(towns)
    ctl = TB.TownNavController(vm, svc, cmd, clock=lambda: 0.0,
                               action_log=AL.ActionLog(clock=lambda: 0.0))
    return vm, svc, cmd, ctl


def test_覚えが無くても出口が候補に出る(tmp_path):
    """⚠⚠ ここが依頼者の症状（★save3 で押せなかった）。"""
    vm, svc, _cmd, ctl = _ctl(tmp_path)
    vm.pos = (1, 9, 13, 13)                               # ★町 9 の真ん中（⚠ 覚えは無い）
    assert ctl.entry_cell(9) is None, "⚠ 前提が崩れた（★覚えがある）"

    got = [f for f in ctl.facilities() if f["role"] == TB.ENTRANCE_ROLE]
    assert len(got) == 1, "⚠⚠ 覚えが無いと出口が出ない（★依頼者の症状のまま）"
    assert (got[0]["npc"]["x"], got[0]["npc"]["y"]) == (5, 0)
    assert svc.exit_calls >= 1, "⚠ 出口を探す道を通っていない（★別の理由で出た）"


def test_覚えが無いときは出口だと名乗る(tmp_path):
    """⚠⚠ 依頼者「save8 入ボタンで街から出てしまう」（RX3-0349 / 2026-09-21）。

    ★`RX3-0341` では「端に立っても町からは出ない」と書きましたが、⚠ **誤りでした**。
    → ★依頼者「別に出てもいいので、ツールチップを直してもOK」
      ⚠ 動きは変えず、**名前を実態に合わせます**。
    """
    vm, _svc, _cmd, ctl = _ctl(tmp_path)
    vm.pos = (1, 9, 13, 13)
    got = [f for f in ctl.facilities() if f["role"] == TB.ENTRANCE_ROLE]
    assert len(got) == 1
    assert got[0]["label"] == TB.ENTRANCE_EXIT_LABEL, (
        "⚠⚠ 町を出るのに「入口」と名乗っている: %s" % got[0]["label"])
    assert "出" in got[0]["label"], "⚠ 出ることが名前に出ていない"


def test_覚えがあればそちらを使う(tmp_path):
    """★今までどおり（⚠ 端より「入ってきた升」が正しい）。"""
    vm, svc, _cmd, ctl = _ctl(tmp_path)
    vm.pos = (1, 9, 8, 18)
    ctl.note_entry()                                      # ★入ってきた升を覚える
    vm.pos = (1, 9, 13, 13)

    got = [f for f in ctl.facilities() if f["role"] == TB.ENTRANCE_ROLE]
    assert len(got) == 1
    # ★行き先は「入ってきた升」そのもの（⚠ `plan` の `goal` はその手前）
    assert (got[0]["npc"]["x"], got[0]["npc"]["y"]) == (8, 18), got[0]["npc"]
    assert svc.exit_calls == 0, "⚠ 覚えがあるのに端を探した（★遠回り）"
    # ★こちらは町を出ません（⚠ 名前も「入口」のまま / RX3-0349）
    assert got[0]["label"] == TB.ENTRANCE_LABEL, got[0]["label"]


# ======================================================================
# ★★ ダンジョンでは端を探さない（RX3-0355 / 2026-09-21）
#
#   ⚠⚠ 依頼者「特にダンジョンはこの機能は一旦凍結させたい」。
#     ★ダンジョンでは端まで歩いても出口とは限らず、⚠ **迷い込ませるだけ**です。
# ======================================================================
def test_ダンジョンでは端を探さない(tmp_path):
    vm, svc, _cmd, ctl = _ctl(tmp_path, towns=())          # ⚠ どの map も町ではない
    vm.pos = (1, 9, 13, 13)
    assert [f for f in ctl.facilities() if f["role"] == TB.ENTRANCE_ROLE] == [], (
        "⚠⚠ ダンジョンで出口を探した（★迷い込ませる）")
    assert svc.exit_calls == 0, "⚠ 端を探す道を通ってしまった"


def test_町だと分からないときも出さない(tmp_path):
    """⚠ 「分からない = 出さない」（★推測で町だと決めない / 安全側）。"""
    vm, svc, _cmd, ctl = _ctl(tmp_path, towns=(17,))       # ★map 9 は分からない
    vm.pos = (1, 9, 13, 13)
    assert [f for f in ctl.facilities() if f["role"] == TB.ENTRANCE_ROLE] == []
    assert svc.exit_calls == 0


def test_台帳が無ければ出さない(tmp_path):
    """⚠ 台帳を読めない環境でも、★勝手に端へ連れて行かない。"""
    vm, svc, _cmd, ctl = _ctl(tmp_path)
    vm.location_book = None
    vm.pos = (1, 9, 13, 13)
    assert [f for f in ctl.facilities() if f["role"] == TB.ENTRANCE_ROLE] == []
    assert svc.exit_calls == 0


def test_覚えている升はダンジョンでも使える(tmp_path):
    """★①（入ってきた升）は**実際に通った升**なので確かです（⚠ 凍結の対象外）。"""
    vm, svc, _cmd, ctl = _ctl(tmp_path, towns=())
    vm.pos = (1, 40, 8, 18)
    ctl.note_entry()
    vm.pos = (1, 40, 13, 13)
    got = [f for f in ctl.facilities() if f["role"] == TB.ENTRANCE_ROLE]
    assert len(got) == 1, "⚠⚠ 覚えている升まで止めた（★凍結しすぎ）"
    assert got[0]["label"] == TB.ENTRANCE_LABEL
    assert svc.exit_calls == 0


def test_屋内では出口を出さない(tmp_path):
    """⚠ どの端へも行けないなら、★ボタンを出さない（RX3-0291 の約束を守る）。"""
    vm, _svc, _cmd, ctl = _ctl(tmp_path, exit_cell=None)
    vm.pos = (1, 88, 8, 10)
    assert [f for f in ctl.facilities() if f["role"] == TB.ENTRANCE_ROLE] == []
