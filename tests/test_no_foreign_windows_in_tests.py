"""★検査は、よその窓（遊んでいる人の FCEUX）に触らない（RX-0138 / 2026-09-12）。

⚠⚠ 実際に起きた: 全件検査の最中に、依頼者が遊んでいた FCEUX が 2 回閉じた（14:50 / 14:51）。
★囮の窓（題名「FCEUX 2.6.6: DECOY」）を置いて全件を回すと、⚠ WM_CLOSE が 97 回届いた。
→ ★`conftest._よその窓に触らない` が、窓を探す口を「この検査のプロセスの窓だけ」に絞る。

⚠ ここでは**閉じる頼みを送らない**（★仕掛けが壊れていたら、この検査が人の FCEUX を閉じてしまう）。
★見るのは「探す口が何を返すか」だけ。
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

from dq3.ui import emu_speed, mute
from retroux.core import window_align

ROOT = pathlib.Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 の窓だけの話")


def _pid(hwnd) -> int:
    import ctypes
    import ctypes.wintypes as wt

    pid = wt.DWORD()
    ctypes.WinDLL("user32").GetWindowThreadProcessId(wt.HWND(int(hwnd)), ctypes.byref(pid))
    return int(pid.value)


def test_窓を探しても自分の窓しか返らない():
    original = getattr(window_align.find_windows, "__wrapped__", None)
    assert original is not None, "⚠⚠ 探す口が絞られていない（★conftest の仕掛けが外れた）"
    foreign = [w for w in original("", match="contains") if _pid(w.handle) != os.getpid()]
    if not foreign:
        pytest.skip("よその窓が 1 つも無い環境（★確かめようがない）")
    got = window_align.find_windows("", match="contains")
    leaked = [w.title for w in got if _pid(w.handle) != os.getpid()]
    assert not leaked, "⚠⚠ よその窓が見えている（★閉じる・動かす・前へ出すが届く）: %s" % leaked[:5]


def test_FCEUXを探しても見つからない():
    """★速度（WM_COMMAND）と音（プロセス番号）は、どちらもここから相手を決める。"""
    assert getattr(emu_speed.find_fceux, "__wrapped__", None) is not None, "⚠⚠ FCEUX を探す口が絞られていない"
    hwnd = emu_speed.find_fceux()
    assert hwnd == 0 or _pid(hwnd) == os.getpid(), "⚠⚠ よその FCEUX が見えている"
    assert mute.fceux_pid() in (0, os.getpid()), "⚠⚠ よその FCEUX の音を触れる"


def test_仕掛けがconftestにある():
    """⚠ 仕掛けが消えても、上の検査だけでは**理由**が分からない。"""
    src = (ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "def _よその窓に触らない" in src, "⚠⚠ よその窓を守る仕掛けが消えている"
    assert "autouse=True" in src and "GetWindowThreadProcessId" in src
