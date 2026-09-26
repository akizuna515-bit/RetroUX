"""倒したかは、経験値が落ち着いてから決める（RX3-0303 / 2026-09-20）。

⚠⚠ 依頼者「バラモスを倒した時、勇者メモから消えない(save9)」。

★実測（依頼者の記録）:

```text
会った 109 種 / 倒した 108 種
⚠⚠ 「会ったが倒していない」は **132（バラモス）ただ 1 匹**
T017 バラモス討伐  active のまま（★だから勇者会議から消えない）
```

→ ★戦闘フラグが落ちた**瞬間**に 1 回だけ経験値を見て、⚠ まだ書かれていなかった。

⚠ 「会った」は今までどおり**すぐ**覚えます（★取りこぼさない）。
★「倒した」だけ、⚠ **しばらく待って**から決めます。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.ui import view_model as VM                            # noqa: E402

BOSS = 132          #: ★バラモス（⚠ 実データで確かめた番号）


class _Book:
    """★敵の記録の代わり（⚠ 本物の記録には触らない）。"""

    def __init__(self) -> None:
        self.met: set = set()
        self.defeated: set = set()
        self.saves = 0

    def record_battle(self, groups, won: bool) -> int:
        added = 0
        for g in groups or ():
            key = g.get("id")
            if key is None:
                continue
            key = int(key)
            if key not in self.met:
                self.met.add(key)
                added += 1
            if won and key not in self.defeated:
                self.defeated.add(key)
                added += 1
        return added

    def save(self, force: bool = False) -> bool:
        self.saves += 1
        return True


class _VM:
    """★戦闘の記録に要る口だけを持つ見本（⚠ 実機も本物の記録も要らない）。

    ⚠ `Dq3ViewModel` を継承しません（★`enemy_names` は property で差し替えられない）。
    ★見たいのは「いつ倒したと決めるか」だけなので、★本物の**判断の関数を借りて**きます。
    """

    BATTLE_SETTLE_TICKS = VM.Dq3ViewModel.BATTLE_SETTLE_TICKS
    _note_battle_start = VM.Dq3ViewModel._note_battle_start
    _note_battle_groups = VM.Dq3ViewModel._note_battle_groups
    _note_battle_end = VM.Dq3ViewModel._note_battle_end
    _settle_battle = VM.Dq3ViewModel._settle_battle
    _finish_battle = VM.Dq3ViewModel._finish_battle

    def __init__(self) -> None:                                # noqa: D107
        self.enemy_names = _Book()
        self.exp = 0
        self._pending_battle = None
        self._battle_settle = None
        self.overlays = 0

    def _total_exp(self) -> int:
        return self.exp

    def write_enemy_overlay(self):
        self.overlays += 1
        return None

    def _note_spells(self) -> None:
        pass


@pytest.fixture()
def vm():
    return _VM()


def _fight(vm, exp_before=1000):
    """★戦闘に入る（⚠ 群が届いたところまで）。"""
    vm.exp = exp_before
    vm._note_battle_start()
    vm._note_battle_groups([{"id": BOSS, "n": 1}])


# --- ★今までどおり -------------------------------------------------------

def test_その場で経験値が増えていれば倒した(vm):
    _fight(vm)
    vm.exp = 1000 + 9000                       # ★もう書かれている
    vm._note_battle_end()
    assert BOSS in vm.enemy_names.defeated


def test_逃げたら倒したにしない(vm):
    """⚠ 経験値が増えないまま待ちが尽きる（★逃げた・全滅した）。"""
    _fight(vm)
    vm._note_battle_end()
    assert BOSS in vm.enemy_names.met, "⚠ 会ったことは覚える"
    assert BOSS not in vm.enemy_names.defeated
    for _ in range(vm.BATTLE_SETTLE_TICKS + 2):
        vm._settle_battle()
    assert BOSS not in vm.enemy_names.defeated, "⚠⚠ 逃げたのに倒したことにした"
    assert vm._battle_settle is None, "⚠ いつまでも見張っている"


# --- ★これが直したかったこと ---------------------------------------------

def test_経験値が遅れて届いても倒したにする(vm):
    """★★ 依頼者のバラモスの場面（⚠ フラグが落ちた時点では 0）。"""
    _fight(vm)
    vm._note_battle_end()                      # ⚠ まだ経験値が書かれていない
    assert BOSS in vm.enemy_names.met
    assert BOSS not in vm.enemy_names.defeated
    vm._settle_battle()                        # ★まだ届かない
    assert BOSS not in vm.enemy_names.defeated
    vm.exp = 1000 + 9000                       # ★ここで届いた
    vm._settle_battle()
    assert BOSS in vm.enemy_names.defeated, "⚠⚠ 遅れて届いた経験値を見ていない"


def test_待ちが尽きる直前でも間に合う(vm):
    """⚠ 最後の 1 回でも拾う（★`_note_battle_end` 自身も 1 回数えている）。"""
    _fight(vm)
    vm._note_battle_end()
    while vm._battle_settle and vm._battle_settle[2] > 1:
        vm._settle_battle()
    assert vm._battle_settle is not None, "⚠ もう見張っていない（★この検査が空回り）"
    vm.exp = 1000 + 1
    vm._settle_battle()
    assert BOSS in vm.enemy_names.defeated


def test_待ちが尽きたあとは拾わない(vm):
    """⚠ いつまでも見張らない（★次の戦闘と混ざる）。"""
    _fight(vm)
    vm._note_battle_end()
    for _ in range(vm.BATTLE_SETTLE_TICKS + 1):
        vm._settle_battle()
    vm.exp = 99999
    vm._settle_battle()
    assert BOSS not in vm.enemy_names.defeated


def test_会ったのはすぐ覚える(vm):
    """⚠ 「倒した」を待つせいで、★「会った」まで遅れないこと。"""
    _fight(vm)
    vm._note_battle_end()
    assert BOSS in vm.enemy_names.met


def test_2度記録しても壊れない(vm):
    """★`_finish_battle` は 2 度呼ばれる（⚠ 集合に足すだけ）。"""
    _fight(vm)
    vm._note_battle_end()
    vm.exp = 1000 + 5
    vm._settle_battle()
    assert vm.enemy_names.defeated == {BOSS} and vm.enemy_names.met == {BOSS}


def test_次の戦闘が始まったら前の見張りは残らない(vm):
    """⚠⚠ 前の戦闘の見張りが残っていると、★次の戦闘の経験値で前の敵を倒したことにする。"""
    _fight(vm)
    vm._note_battle_end()
    assert vm._battle_settle is not None
    # ★次の戦闘（⚠ 別の敵）
    vm.exp = 2000
    vm._note_battle_start()
    vm._note_battle_groups([{"id": 5, "n": 3}])
    vm.exp = 2000 + 40
    vm._note_battle_end()
    assert 5 in vm.enemy_names.defeated
    assert BOSS not in vm.enemy_names.defeated, (
        "⚠⚠ 前の戦闘の見張りが、★次の経験値で誤って当たった")
