"""自動移動に「街の入口へ」（[入]）を足す（RX3-0291 / 2026-09-18）。

⚠⚠ 依頼者「自動移動に街の入口に移動を追加したい。文字は『入』かな。」

## ★先に分かったこと — 町の出入口は ROM に升が無い

```text
世界地図へ出る出口   `world_edge`（★端から歩いて出る）→ ⚠ x, y が None
入った升             ⚠ `map_graph.arrival_cell` の註「町に入った升は表に無い」
```

→ ★**入ってきた升を覚える**（⚠ 推測で別の所へ行かない / 覚えていなければ押せない）。
→ ★着いたら**手前で止まる**（⚠ 升を踏むと町を出てしまう / ★出るかは人が決める）。
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
from dq3.ui import town_bar as TB                             # noqa: E402
from test_dq3_town_ui import _Commands, _Service, _VM         # noqa: E402


def _ctl(tmp_path):
    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    ctl = TB.TownNavController(vm, svc, cmd, clock=lambda: 0.0,
                               action_log=AL.ActionLog(clock=lambda: 0.0))
    return vm, svc, cmd, ctl


# --- ★入ってきた升を覚える ---------------------------------------------------

def test_mapが変わった升を覚える(tmp_path):
    vm, _svc, _cmd, ctl = _ctl(tmp_path)
    vm.pos = (1, 9, 8, 18)                                    # ★町 9 に入った
    ctl.note_entry()
    assert ctl.entry_cell(9) == (8, 18)


def test_同じmapで歩いても上書きしない(tmp_path):
    """⚠ 入口は「入ってきた升」であって「いま居る升」ではない。"""
    vm, _svc, _cmd, ctl = _ctl(tmp_path)
    vm.pos = (1, 9, 8, 18)
    ctl.note_entry()
    for cell in ((8, 17), (8, 16), (3, 3)):
        vm.pos = (1, 9) + cell
        ctl.note_entry()
    assert ctl.entry_cell(9) == (8, 18)


def test_世界地図へ出たら忘れて入り直すと覚え直す(tmp_path):
    vm, _svc, _cmd, ctl = _ctl(tmp_path)
    vm.pos = (1, 9, 8, 18)
    ctl.note_entry()
    vm.pos = (0, None, 100, 100)                              # ★世界地図
    ctl.note_entry()
    vm.pos = (1, 9, 2, 2)                                     # ★別の口から入り直した
    ctl.note_entry()
    assert ctl.entry_cell(9) == (2, 2)


def test_知らない町は覚えていない(tmp_path):
    _vm, _svc, _cmd, ctl = _ctl(tmp_path)
    assert ctl.entry_cell(9) is None and ctl.entry_cell(None) is None


# --- ★候補・移動 -------------------------------------------------------------

def test_覚えていなくて出口も無ければ候補に出ない(tmp_path):
    """⚠⚠ 2026-09-21 訂正（RX3-0341）: ここは「覚えていなければ**必ず**出ない」でした。

    ★いまは覚えが無くても**歩ける端**を探します（⚠ 依頼者の save3 で押せなかったため）。
    → ⚠ この偽 service は `plan_to_exit` を持たないので、★「端も無い」場合として通ります。
      ⚠ 覚えが無くても出る側は `tests/test_dq3_town_exit.py` が見ています。
    """
    _vm, svc, _cmd, ctl = _ctl(tmp_path)
    assert not hasattr(svc, "plan_to_exit"), "⚠ 前提が変わった（★偽 service に端の道が増えた）"
    assert ctl.candidates(TB.ENTRANCE_ROLE) == []
    assert not ctl.start_move(TB.ENTRANCE_ROLE)


def test_覚えていれば入口へ歩ける(tmp_path):
    vm, _svc, cmd, ctl = _ctl(tmp_path)
    vm.pos = (1, 9, 8, 18)
    ctl.note_entry()
    vm.pos = (1, 9, 8, 15)                                    # ★町の奥へ歩いた
    got = ctl.candidates(TB.ENTRANCE_ROLE)
    assert len(got) == 1 and got[0]["label"] == TB.ENTRANCE_LABEL
    assert ctl.start_move(TB.ENTRANCE_ROLE)
    action, params = cmd.sent[-1]
    assert action == "navigate"
    # ⚠⚠ 話しかけない（★入口は人ではない / 窓も開かない）
    assert params["talk"] == "0" and params["close"] == "0", params
    assert "stop_at" not in params, "⚠ 施設の止め方（RX3-0241）を入口に使っている"
    assert ctl.target_label == TB.ENTRANCE_LABEL


def test_入口に居るときは押せない(tmp_path):
    """⚠ もうそこに居るなら候補にしない（★0 歩の移動を始めない）。"""
    vm, _svc, _cmd, ctl = _ctl(tmp_path)
    vm.pos = (1, 9, 8, 18)
    ctl.note_entry()
    assert ctl.candidates(TB.ENTRANCE_ROLE) == []


def test_施設の候補は変わらない(tmp_path):
    """⚠ [入] を足したことで、宿屋などの候補が増減しないこと。"""
    vm, svc, _cmd, ctl = _ctl(tmp_path)
    svc.heard.record(9, 1, 11, at="t")
    vm.pos = (1, 9, 8, 18)
    ctl.note_entry()
    vm.pos = (1, 9, 8, 15)
    assert [f["role"] for f in ctl.facilities() if f["role"] != TB.ENTRANCE_ROLE] == ["inn"]


# --- ★画面 -------------------------------------------------------------------

def test_ボタンは入の1文字で説明が出る(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    vm, _svc, _cmd = _VM(), _Service(tmp_path), _Commands()
    bar = TB.TownBar(vm, _Service(tmp_path), _Commands())
    button = bar.move_buttons[TB.ENTRANCE_ROLE]
    assert button.text() == "入"
    assert "入ってきた所" in button.toolTip(), button.toolTip()
    # ★覚えたら押せて、説明も変わる
    bar.ctl.vm.pos = (1, 9, 8, 18)
    bar.poll()                                                # ★毎回の見回りで覚える
    bar.ctl.vm.pos = (1, 9, 8, 15)
    bar.poll()
    assert bar.ctl.entry_cell(9) == (8, 18)
    assert button.isEnabled()
    assert "手前" in button.toolTip() and "町は出ません" in button.toolTip()
    bar.close()


def test_ROMに升が無いことを註に残す():
    """⚠ 「なぜ覚えるのか」を消さない（★次の人が ROM を探し直さないように）。"""
    src = (ROOT / "dq3" / "ui" / "town_bar.py").read_text(encoding="utf-8")
    assert "world_edge" in src and "ROM に升がありません" in src
