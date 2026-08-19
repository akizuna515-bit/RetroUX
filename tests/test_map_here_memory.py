"""戦闘中も現在地の印を消さない（2026-08-02 / 依頼者の報告）。

⚠⚠ 依頼者「現在位置表示が出ない時があるのも気になる」

★実測しました（`state.json` を 0.2 秒ごとに 69 回）:

    現在地が出ない 3 回 → **3 回とも `in_battle`**

  Lua は「戦闘中に歩いてはいないので嘘の足跡を残さない」ため、
  戦闘中に座標を出しません。★それは正しい。
  ⚠ でも**表示まで消す**必要はありません。戦闘は数十秒あります。

★★ ここで固定する契約 ★★

  1. ★座標が来ない間は、直前に居た場所を出したままにする
  2. ⚠⚠ **別のマップを選んでいるときは出さない**（嘘になる）
  3. ⚠ 「いまの場所を追う」を切っているときは、これまでどおり出さない
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


class _Window:
    """★`follow()` と `_remembered_here()` だけを取り出して試す。

    ⚠ 本物の窓は DB も Qt も要る。ここで見たいのは**覚え方の筋**だけ。
    """

    from retroux.ui.map.window import MapWindow

    follow = MapWindow.follow
    _remembered_here = MapWindow._remembered_here

    def __init__(self, keys, current=0, following=True):
        self._keys = list(keys)
        self._row = current
        self.drawn = []

        class _Check:
            def __init__(self, on):
                self._on = on

            def isChecked(self):
                return self._on

        self._follow = _Check(following)

    def _current_key(self):
        if 0 <= self._row < len(self._keys):
            return self._keys[self._row]
        return None

    def reload(self):
        pass

    def _draw(self, here=None):
        self.drawn.append(here)

    # ★本物の `follow` が触る Qt の部品を差し替える
    class _List:
        def __init__(self, outer):
            self._outer = outer

        def currentRow(self):
            return self._outer._row

        def setCurrentRow(self, i):
            self._outer._row = i

        def blockSignals(self, _flag):
            pass

    @property
    def _list(self):
        return self._List(self)


KEY_A = (0x3D, 0x9E2B)      # ★ロンダルキアへの洞窟 4F
KEY_B = (0x3E, 0x9F00)      # ★5F


def test_ふつうは今の座標を出す():
    w = _Window([KEY_A])
    w.follow(0x3D, 0x9E2B, 7, 3)
    assert w.drawn == [(7, 3)]


def test_戦闘中も直前の場所を出したままにする():
    """★★ **これが依頼者の訴えへの答え**。"""
    w = _Window([KEY_A])
    w.follow(0x3D, 0x9E2B, 7, 3)
    # ⚠ 戦闘に入ると Lua は座標を出さない
    w.follow(None, None, None, None)
    assert w.drawn[-1] == (7, 3), "★印が消えてしまっている"
    # ★戦闘が終わって座標が戻れば、そちらが優先
    w.follow(0x3D, 0x9E2B, 8, 3)
    assert w.drawn[-1] == (8, 3)


def test_別のマップを選んでいるときは出さない():
    """⚠⚠ **ここを確かめないと嘘になる。**

    ★別の階の同じ座標に印が出てしまう。
    """
    w = _Window([KEY_A, KEY_B])
    w.follow(0x3D, 0x9E2B, 7, 3)
    w._row = 1                       # ★人が別の階を選んだ
    w.follow(None, None, None, None)
    assert w.drawn[-1] is None


def test_まだ一度も居場所が分からないときは出さない():
    """⚠ 覚えていないものを出さない（推測で埋めない）。"""
    w = _Window([KEY_A])
    w.follow(None, None, None, None)
    assert w.drawn[-1] is None


def test_追いかけを切っているときは出さない():
    """★人が「追う」を外したなら、印も出さない。"""
    w = _Window([KEY_A], following=False)
    w.follow(0x3D, 0x9E2B, 7, 3)
    assert w.drawn[-1] is None
    w.follow(None, None, None, None)
    assert w.drawn[-1] is None


def test_座標だけが欠けても覚えは壊さない():
    """⚠ map_id はあるが x/y が無い、という中途半端な場合。"""
    w = _Window([KEY_A])
    w.follow(0x3D, 0x9E2B, 7, 3)
    w.follow(0x3D, 0x9E2B, None, None)
    # ★このときは None を出す（今まさに分からないため）
    assert w.drawn[-1] is None
    # ⚠ ただし覚えは残っていて、次の戦闘中には使える
    w.follow(None, None, None, None)
    assert w.drawn[-1] == (7, 3)
