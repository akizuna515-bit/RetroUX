"""窓の位置の保存と画面外からの復帰（仕様書 8章）。

★2026-08-01 に `test_release_prep.py`（848 実質行）から切り出しました（指示書 §11.1）。
  ⚠ **内容は1件も減らしていません。**機械で切り、件数で確かめています。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _code_lines(text: str) -> list:
    """コメントと空行を落とした行を返す。

    ★★ **「その語がソースにある」だけの検査は穴になる。** ★★
      説明のコメントに同じ語が書いてあると、**実装を消しても緑**のままになる。
      実際に `MessageBox` と `MsgBox` の検査がこれで通り抜けた（2026-07-30）。

    ⚠ PowerShell は `#`、VBS と `.cmd` は `'` / `rem` がコメント。
    """
    made = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "'", "rem ", "REM ")):
            continue
        made.append(stripped)
    return made

# --- ウィンドウ位置（仕様書 8章）---------------------------------------

SCREEN = [(0, 0, 1920, 1040)]


@pytest.mark.parametrize(("x", "y", "moved"), [
    (100, 100, False),        # 画面内
    (3000, 100, True),        # 右の外（モニタを外した）
    (-2000, -900, True),      # 左上の外
    (0, 0, False),            # 左上ぴったり
    (1919, 500, True),        # 1画素だけ重なる（掴めない）
])
def test_a_window_outside_every_screen_is_brought_back(x, y, moved):
    """★★ **これが無いと「起動しない」ように見える。** ★★

    外付けモニタを外すと窓が見えない場所に開き、
    利用者には直しようがない（窓が見えないので動かせない）。
    """
    from retroux.ui.window_state import clamp_to_screens

    nx, ny, did = clamp_to_screens(x, y, 800, 600, SCREEN, SCREEN[0])
    assert did is moved
    if moved:
        assert 0 <= nx < 1920 and 0 <= ny < 1040


def test_a_window_spanning_two_screens_is_left_alone():
    """⚠ 「完全に収まっているか」で判断すると、意図した配置を壊す。"""
    from retroux.ui.window_state import clamp_to_screens

    screens = [(0, 0, 1920, 1040), (1920, 0, 1920, 1040)]
    _x, _y, moved = clamp_to_screens(1600, 100, 800, 600, screens, screens[0])
    assert moved is False


def test_no_screen_information_means_do_not_move():
    """★推測で動かさない。"""
    from retroux.ui.window_state import clamp_to_screens

    assert clamp_to_screens(9999, 9999, 800, 600, [], None) == (9999, 9999, False)


def test_window_state_survives_a_round_trip(tmp_path):
    from retroux.ui.window_state import WindowState

    state = WindowState(tmp_path / "w.json")
    state.put("main", {"x": 10, "y": 20, "w": 800, "h": 600})
    assert state.save()
    again = WindowState(tmp_path / "w.json")
    assert again.get("main")["w"] == 800


def test_a_broken_window_state_file_is_reported_not_fatal(tmp_path):
    """⚠ 位置を思い出せないだけ。ゲームは遊べる。"""
    from retroux.ui.window_state import WindowState

    path = tmp_path / "w.json"
    path.write_text("これは JSON ではない {{{", encoding="utf-8")
    state = WindowState(path)
    assert state.data == {}
    assert state.problems


def test_an_unwritable_location_does_not_raise(tmp_path):
    from retroux.ui.window_state import WindowState

    blocker = tmp_path / "blocked"
    blocker.mkdir()
    state = WindowState(blocker)          # ★フォルダを渡す（書けない）
    state.put("main", {"x": 1, "y": 1, "w": 800, "h": 600})
    assert state.save() is False


def test_a_tiny_saved_size_is_ignored(tmp_path):
    """⚠ 0×0 で保存されると、開いても何も見えない＝「起動しない」に見える。"""
    from retroux.ui.window_state import MIN_HEIGHT, MIN_WIDTH, WindowState

    state = WindowState(tmp_path / "w.json")
    state.put("main", {"x": 0, "y": 0, "w": 1, "h": 1})

    class FakeWindow:
        applied = None

        def setGeometry(self, *a):        # noqa: N802 (Qt の命名)
            self.applied = a

        def isMaximized(self):            # noqa: N802
            return False

        def showMaximized(self):          # noqa: N802
            pass

    window = FakeWindow()
    assert state.apply_to("main", window) is False
    assert window.applied is None
    assert any("小さすぎる" in p for p in state.problems)
    assert MIN_WIDTH >= 320 and MIN_HEIGHT >= 240


def test_背の低いログ窓は下限を下げれば戻せる(tmp_path):
    """★★ 2026-08-11: 「下のログ画面だけ場所が保持されない」不具合 ★★

    ⚠ ログ窓は横長で背が低い（~150px）。主画面向けの下限（240px）だと毎回
      はじかれ、既定位置（左上）に開いていた。★窓ごとに下限を下げて渡せる。
    """
    from retroux.ui.window_state import WindowState

    state = WindowState(tmp_path / "w.json")
    state.put("log", {"x": 13, "y": 549, "w": 1255, "h": 147})

    class FakeWindow:
        applied = None

        def setGeometry(self, *a):        # noqa: N802
            self.applied = a

        def isMaximized(self):            # noqa: N802
            return False

        def showMaximized(self):          # noqa: N802
            pass

    # ★既定の下限（240）でははじかれる
    assert state.apply_to("log", FakeWindow()) is False
    # ★下限を下げれば戻せる（背の低い窓向け）
    win = FakeWindow()
    assert state.apply_to("log", win, min_height=120) is True
    assert win.applied == (13, 549, 1255, 147)


class _FakeWindow:
    """`apply_to` に渡す最小限の窓。★Qt を起こさずに試すため。"""

    def __init__(self) -> None:
        self.applied = None

    def setGeometry(self, *a):                # noqa: N802 (Qt の命名)
        self.applied = a

    def isMaximized(self):                    # noqa: N802
        return False

    def showMaximized(self):                  # noqa: N802
        pass


class _FakeSplitter:
    """段の数を偽れるスプリッター。"""

    def __init__(self, count: int) -> None:
        self._count = count
        self.applied = None

    def count(self) -> int:
        return self._count

    def sizes(self) -> list:
        return [100] * self._count

    def setSizes(self, sizes):                # noqa: N802
        self.applied = list(sizes)


def test_a_splitter_layout_with_a_different_number_of_panes_is_ignored(tmp_path):
    """★★ **段の数が変わっていたら、保存した配分を当てない。** ★★

    ⚠ Qt は数が合わない配分を渡されると**黙って詰める**。
      画面の構成を変えた版で起動したとき、片方の段が
      **幅 0 に潰れて見えなくなる**（利用者からは「消えた」）。

    ⚠ この分岐は `research/probes/active/break_release.py` で見つかった穴で、
      条件を `if True:` に壊しても**テストは緑だった**（2026-07-30）。
    """
    from retroux.ui.window_state import WindowState

    state = WindowState(tmp_path / "w.json")
    state.put("main", {"x": 0, "y": 0, "w": 800, "h": 600,
                       "splitter": [300, 500]})       # ★2段ぶん保存

    # --- 段の数が合っているとき: 当てる ---
    same = _FakeSplitter(2)
    assert state.apply_to("main", _FakeWindow(), splitter=same) is True
    assert same.applied == [300, 500]

    # --- 段の数が変わったとき: 当てない ---
    changed = _FakeSplitter(3)
    assert state.apply_to("main", _FakeWindow(), splitter=changed) is True
    assert changed.applied is None, \
        "段の数が違うのに保存した配分を当てている（Qt が黙って詰める）"
