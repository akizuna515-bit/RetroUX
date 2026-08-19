"""ウィンドウ整列のテスト（MVP2 Phase 1 / 指示書 5.3）。

Win32 を叩く部分はテストできないが、**事故の原因になった照合**は切り出してある。

★実際に踏んだ事故（2026-07-26）:
  "RetroUX" を**含む**ウィンドウを探したところ、フォルダ名に RetroUX を含む
  **エクスプローラー**が一致し、利用者のウィンドウを勝手に動かした。
  他人のウィンドウを動かす機能は、当たりすぎる側に倒してはいけない。
"""

from __future__ import annotations

import pytest

from retroux.core.window_align import title_matches

EXPLORER = r"F:\Projects\260721_RetroUX とその他 1 のタブ - エクスプローラー"
GUI = "RetroUX — ドラゴンクエストII"
FCEUX = "FCEUX 2.6.6 - DQ2_J.nes"


@pytest.mark.parametrize("title,needle,expected", [
    # ★本命: 前方一致なら**エクスプローラーは当たらない**
    (EXPLORER, "RetroUX", False),
    (GUI, "RetroUX", True),
    (FCEUX, "FCEUX", True),
    (FCEUX, "RetroUX", False),
])
def test_prefix_does_not_catch_unrelated_windows(title, needle, expected):
    assert title_matches(title, needle, "prefix") is expected


def test_contains_catches_too_much():
    """「含む」だと事故が起きることを、テストとしても残しておく。"""
    assert title_matches(EXPLORER, "RetroUX", "contains") is True


def test_case_insensitive():
    assert title_matches(FCEUX, "fceux", "prefix") is True


def test_exact():
    assert title_matches(GUI, GUI, "exact") is True
    assert title_matches(GUI, "RetroUX", "exact") is False


# --- 作業領域（2026-07-31 の指示書 §7.3）--------------------------------

def test_the_work_area_excludes_the_taskbar():
    """★★ **画面の大きさではなく作業領域を使う。** ★★

    ⚠ 画面の高さで並べると下端がタスクバーに隠れる。
      タスクバーを上や左に置いている人もいるので、**上端も 0 とは限らない**。

    ⚠ Windows 以外では取れない。そのときは `None`（0 で埋めない）。
    """
    from retroux.core import window_align

    area = window_align.work_area()
    if not window_align.available():
        assert area is None, "使えない環境なのに値を返している"
        return

    assert area is not None, "Windows なのに作業領域が取れない"
    left, top, width, height = area
    assert width > 0 and height > 0
    # ★作業領域は画面より小さいか同じ。大きいことはありえない
    import ctypes
    user32 = ctypes.WinDLL("user32")
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    assert width <= screen_w and height <= screen_h


def test_the_work_area_is_none_without_win32(monkeypatch):
    """⚠ 取れないときは **None**。0 と「取れなかった」を混ぜない。"""
    from retroux.core import window_align

    monkeypatch.setattr(window_align, "available", lambda: False)
    assert window_align.work_area() is None
