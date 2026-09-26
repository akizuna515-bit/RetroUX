"""手で話した会話も「聞いた」に数える（RX3-0282 / 2026-09-18）。

⚠⚠ 依頼者「聞き込みで、自前で聞き込みしたのが考慮されないのは直せないか？」

★`RX3-0185`（2026-09-12）は「台帳へ書くと**聞き込み済み**になる」ので**書かない**と決めていた。
→ ★依頼者の求めで判断を変えた。⚠ そのかわり、書く条件を絞る（下の検査）。

## ⚠⚠ 2026-09-18 の NG（★この検査は 1 度すり抜けた）

依頼者「話にいっている。ログも 2 つでている」。⚠ 実機では **1 件も記録されなかった**。
穴は 2 つあり、★どちらも「片側だけ見る検査」では捕まらなかった:

```text
① 橋渡しが無い   main_window は town_bar.note_manual_talk() を呼ぶが、
                 中身は TownNavController にあった。⚠ hasattr で守ってあったので素通り
                 → ★検査: 実物の TownBar が持っているか / main_window が呼ぶ名前が全部あるか
② 相手の取り方   `last_talk`（$828B の見張り）は**手で話したときは立たない**
                 → ★検査: `last_talk` が None のまま記録できること（⚠ 実機と同じ条件）
```
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from dq3 import action_log as AL                                  # noqa: E402
from dq3.ui.town_bar import TownBar, TownNavController            # noqa: E402
from test_dq3_town_ui import _Commands, _Service, _VM             # noqa: E402


class _Env:
    def __init__(self):
        self.lines = []

    def line(self, text):
        self.lines.append(text)


class _Memo:
    """★勇者メモが渡す形（★相手は `npc_id` で決まっている / RX3-0133）。"""

    def __init__(self, text="＊「こんにちは。", npc_id=1, map_id=9, order=1, source="conversation"):
        self.text, self.npc_id, self.map_id, self.order, self.source = text, npc_id, map_id, order, source


@pytest.fixture
def world(tmp_path):
    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    ctl = TownNavController(vm, svc, cmd, clock=lambda: 0.0, action_log=AL.ActionLog(clock=lambda: 0.0))
    ctl.env_hook = _Env()
    # ⚠⚠ **`last_talk` は立てない。** ★実機の手の会話がこの状態だった（2026-09-18）
    vm.talk = None
    return vm, svc, ctl


def test_手で話したら聞いたに数える(world):
    """⚠ `last_talk` が None のままでも書けること（★これが実機の条件）。"""
    vm, svc, ctl = world
    assert vm.last_talk() is None
    got = ctl.note_manual_talk(_Memo())
    assert got is not None and got["npc_id"] == 1, got
    assert svc.heard.is_heard(9, 1), "⚠⚠ 手で話しても聞き込みが繰り返す"
    assert any("MANUAL map=9 npc=1" in ln for ln in ctl.env_hook.lines), ctl.env_hook.lines


def test_同じメモで2度は書かない(world):
    _vm, svc, ctl = world
    assert ctl.note_manual_talk(_Memo(order=1)) is not None
    assert ctl.note_manual_talk(_Memo(order=1)) is None, "⚠⚠ 同じメモで 2 度書いた"
    # ★もう一度話しかけたら（別のメモ）書く
    assert ctl.note_manual_talk(_Memo(order=2)) is not None


def test_本文が無ければ書かない(world):
    _vm, svc, ctl = world
    assert ctl.note_manual_talk(_Memo(text=None)) is None
    assert ctl.note_manual_talk(_Memo(text="")) is None
    assert not svc.heard.is_heard(9, 1), "⚠⚠ 「A を押した」だけで済みにした"
    assert any("MANUAL-SKIP why=no_text" in ln for ln in ctl.env_hook.lines), ctl.env_hook.lines


def test_自動の聞き込み中は書かない(world):
    _vm, svc, ctl = world
    assert ctl.start_hearing()                                    # ★mode = hearing
    assert ctl.note_manual_talk(_Memo()) is None, "⚠⚠ 二重に書いた"


def test_相手が決まっていなければ書かない(world):
    """⚠ 勇者メモが相手を決められなかった会話（`？「…`）は済みにしない。"""
    _vm, svc, ctl = world
    assert ctl.note_manual_talk(_Memo(npc_id=None)) is None
    assert not svc.heard.is_heard(9, 1)
    assert any("MANUAL-SKIP why=no_npc" in ln for ln in ctl.env_hook.lines), ctl.env_hook.lines


def test_別の場所へ移った後のメモは書かない(world):
    """⚠ メモは窓が閉じてから流れてくる（★その間に場所が変わっていたら書かない）。"""
    _vm, svc, ctl = world
    assert ctl.note_manual_talk(_Memo(map_id=77)) is None
    assert any("MANUAL-SKIP why=moved" in ln for ln in ctl.env_hook.lines), ctl.env_hook.lines


def test_表に居ない相手は書かない(world):
    _vm, svc, ctl = world
    assert ctl.note_manual_talk(_Memo(npc_id=999)) is None
    assert any("MANUAL-SKIP why=not_in_table" in ln for ln in ctl.env_hook.lines), ctl.env_hook.lines


# --- ★本物の TownService（⚠ 偽物だけで緑にしない） ---------------------------

def test_本物のserviceも実セーブでnpc_idから書ける(tmp_path):
    """⚠⚠ 上の検査は偽の service を使う。★本物が同じ形で動くことを実データで見る。

    ⚠ 偽物にだけメソッドを足して緑になると、実機でまた素通りする（★2026-09-18 の穴）。
    """
    from retroux.core.bgmap import savestate as SS

    from dq3.knowledge import npc_heard as H
    from dq3.knowledge.town_service import TownService
    from dq3.testing import fixtures as FX

    try:
        fx = FX.get("town_map14_save1")
    except FX.FixtureChanged:
        raise
    except FX.FixtureError as err:
        pytest.skip("⚠ fixture が使えない: %s" % err)
    path = pathlib.Path(fx.path)
    if not path.exists():
        pytest.skip("⚠ セーブが無い")
    ram = SS.load(path).chunks["RAM"]
    cond = FX.conditions_of(path)
    map_id, time_byte = cond["map_id"], cond.get("time_byte")
    npc_tbl = ram[0x0110:0x0110 + 0x100].hex()

    svc = TownService()
    svc.heard = H.HeardLedger(tmp_path)                           # ⚠ 本物の記録を汚さない
    cur = svc.current_npcs(map_id, time_byte, npc_tbl)
    if cur["status"] != "DEFAULT" or not cur["npcs"]:
        pytest.skip("⚠ この fixture では NPC 表が読めない")
    npc_id = int(cur["npcs"][0]["npc_id"])

    assert not svc.heard.is_heard(map_id, npc_id)
    got = svc.record_heard_npc(map_id, time_byte, npc_id, "＊「てすと。", npc_tbl_hex=npc_tbl)
    assert got is not None and int(got["npc_id"]) == npc_id
    assert svc.heard.is_heard(map_id, npc_id), "⚠⚠ 書いたのに済みにならない"
    # ⚠ 表に居ない相手は断る（★slot ではなく npc_id で引いている証拠）
    assert svc.record_heard_npc(map_id, time_byte, 9999, "＊「てすと。", npc_tbl_hex=npc_tbl) is None


# --- ★★ 橋渡し（⚠ ここが 2026-09-18 にすり抜けた） ---------------------------

def test_画面が呼ぶ名前は実物のTownBarにある():
    """⚠⚠ `main_window` が `town_bar` に呼ぶメソッドが**全部実在**すること。

    ★`note_manual_talk` は `TownNavController` にしか無く、⚠ `hasattr` で守ってあったので
    **エラーも出ずに素通り**していた（実機で 1 件も記録されなかった）。
    """
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    called = set(re.findall(r"\b(?:bar|bar_now|self\.town_bar)\.(\w+)\(", src))
    assert "note_manual_talk" in called, "⚠ 画面から呼んでいない"
    missing = [name for name in sorted(called) if not hasattr(TownBar, name)]
    assert not missing, "⚠⚠ TownBar に無いものを呼んでいる（★素通りする）: %s" % missing


def test_TownBarは受けた会話をControllerへ渡す(tmp_path):
    """★橋が本当につながっているか（⚠ 名前があるだけでは足りない）。"""
    from dq3.ui.town_bar import TownBar as _TB

    class _Bar(_TB):
        def __init__(self):                                       # ⚠ Qt の窓は作らない
            pass

    bar = _Bar()
    seen = []
    bar.ctl = type("C", (), {"note_manual_talk": lambda _self, made: seen.append(made) or {"npc_id": 1}})()
    memo = _Memo()
    assert bar.note_manual_talk(memo) == {"npc_id": 1}
    assert seen == [memo], "⚠⚠ メモが Controller へ届いていない（★本文だけ渡していないか）"


def test_画面は本文だけでなくメモを渡す():
    """⚠ `note_manual_talk(made.text)` に戻すと、相手（npc_id）が落ちて何も書けない。"""
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    call = re.search(r"note_manual_talk\(([^)]*)\)", src)
    assert call is not None and call.group(1).strip() == "made", (
        "⚠⚠ メモそのものを渡していない: %s" % (call.group(1) if call else None))
