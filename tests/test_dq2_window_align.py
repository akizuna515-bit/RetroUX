"""DQ2 の窓だけを探して動かす（RX-0145 / D-42）。

⚠ 以前は題名だけで探していて、DQ2 を閉じると DQ3 の FCEUX に WM_CLOSE が届きえた（調査 D3）。
⚠ 整列が DQ3 の FCEUX・「RetroUX DQ3」・DQ3 の「ログ」窓を動かした（調査 D4）。

★ここでは本物の窓に触りません（★窓・プロセス番号・コマンドラインはすべて偽物を差し込む）。
"""

from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from retroux.core import dq2_window_align as W
from retroux.core.window_align import WindowInfo

ROOT = Path(__file__).resolve().parents[1]

DQ2_FCEUX = r'"C:\RetroUX\tools\fceux\fceux64.exe" -lua "C:\RetroUX\retroux\emulator\fceux\run.lua" "C:\RetroUX\work\rom\DQ2_J.nes"'
DQ3_FCEUX = r'"C:\RetroUX\tools\fceux\fceux64.exe" -lua "C:\RetroUX\dq3\phase0\dev.lua" "C:\RetroUX\work\rom\DQ3_J.nes"'
DQ2_GUI = r'"C:\RetroUX\.venv\Scripts\pythonw.exe" -m retroux.gui --session abc123'
DQ3_GUI = r'"C:\RetroUX\runtime\python\pythonw.exe" -m dq3.ui.app'


@pytest.mark.parametrize("line, expected", [
    (DQ2_FCEUX, True),
    (DQ2_FCEUX.replace("\\", "/"), True),           # ★区切りが / でも
    (DQ2_FCEUX.upper(), True),                      # ★大文字小文字を問わない（Windows のパス）
    (DQ2_GUI, True),
    (DQ3_FCEUX, False),
    (DQ3_GUI, False),
    ("notepad.exe FCEUX.txt", False),
    (None, False),                                  # ⚠ 読めないものは DQ2 と見なさない
    ("", False),
])
def test_コマンドラインでDQ2を見分ける(line, expected) -> None:
    assert W.is_dq2_command_line(line) is expected


def test_自分のプロセスはコマンドラインを読まずにDQ2() -> None:
    def boom(pid):
        raise AssertionError("⚠ 自分のプロセスでコマンドラインを読んだ")

    assert W.is_dq2_process(4242, own_pid=4242, cmdline_of=boom) is True
    assert W.is_dq2_process(None, own_pid=4242, cmdline_of=boom) is False


# --- 窓を探す --------------------------------------------------------------------

#: 偽の窓（★DQ3 の窓を先に並べる = 題名だけで探すと最初に当たる並び）
WINDOWS = {
    11: ("FCEUX 2.6.6: DQ3_J", 101, DQ3_FCEUX),
    12: ("FCEUX 2.6.6: DQ2_J", 102, DQ2_FCEUX),
    21: ("Lua Script", 101, DQ3_FCEUX),
    22: ("Lua Script", 102, DQ2_FCEUX),
    31: ("RetroUX DQ3 1.1.0", 103, DQ3_GUI),
    32: ("RetroUX 1.1.0 — ドラゴンクエストII", 104, DQ2_GUI),
    41: ("FCEUX 2.6.6: 不明", 105, None),           # ⚠ コマンドラインが読めない
}


@pytest.fixture()
def fake_windows(monkeypatch: pytest.MonkeyPatch) -> dict:
    def find(title, match="contains"):
        return [WindowInfo(handle=h, title=t, x=0, y=0, width=10, height=10)
                for h, (t, _pid, _line) in WINDOWS.items()
                if W.title_matches(t, title, match)]

    pid_of = {h: pid for h, (_t, pid, _line) in WINDOWS.items()}
    line_of = {pid: line for _h, (_t, pid, line) in WINDOWS.items()}
    monkeypatch.setattr(W._wa, "find_windows", find)
    monkeypatch.setattr(W, "owner_pid", lambda handle: pid_of.get(handle))
    monkeypatch.setattr(W, "command_line_of", lambda pid: line_of.get(pid))
    monkeypatch.setattr(W, "available", lambda: True)
    return WINDOWS


@pytest.mark.parametrize("title, expected", [
    ("FCEUX", [12]),
    ("Lua Script", [22]),
    ("RetroUX", [32]),
])
def test_探すとDQ2の窓だけ返る(fake_windows, title, expected) -> None:
    got = [w.handle for w in W.find_windows(title, match="prefix")]
    assert got == expected


class _FakeUser32:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def PostMessageW(self, handle, msg, wparam, lparam):
        self.calls.append(("close", handle, msg))
        return 1

    def SetForegroundWindow(self, handle):
        self.calls.append(("focus", handle))
        return 1

    def ShowWindow(self, handle, cmd):
        self.calls.append(("show", handle, cmd))
        return 1

    def SetWindowPos(self, handle, after, x, y, w, h, flags):
        self.calls.append(("move", handle, x, y))
        return 1


@pytest.fixture()
def user32(monkeypatch: pytest.MonkeyPatch, fake_windows) -> _FakeUser32:
    fake = _FakeUser32()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: fake)
    return fake


def test_閉じる頼みはDQ2のFCEUXにだけ届く(user32: _FakeUser32) -> None:
    assert W.close_window("FCEUX") is True
    assert W.close_window("Lua Script") is True
    assert user32.calls == [("close", 12, 0x0010), ("close", 22, 0x0010)]


def test_前へ出す最小化戻す並べるもDQ2の窓だけ(user32: _FakeUser32) -> None:
    W.focus("FCEUX", match="prefix")
    W.minimize("Lua Script")
    W.restore("Lua Script")
    W.align("RetroUX", x=5, y=6)
    handles = {call[1] for call in user32.calls}
    assert handles == {12, 22, 32}


def test_DQ2の窓が無ければ何もしない(monkeypatch: pytest.MonkeyPatch, user32: _FakeUser32) -> None:
    only_dq3 = {h: v for h, v in WINDOWS.items() if v[2] in (DQ3_FCEUX, DQ3_GUI)}
    monkeypatch.setattr(W._wa, "find_windows", lambda title, match="contains": [
        WindowInfo(handle=h, title=t, x=0, y=0, width=10, height=10)
        for h, (t, _p, _l) in only_dq3.items() if W.title_matches(t, title, match)])
    assert W.close_window("FCEUX") is False
    assert W.focus("FCEUX") is False
    with pytest.raises(W.WindowAlignError):
        W.align("RetroUX", x=0, y=0)
    assert user32.calls == []


# --- DQ2 の呼び出し側がこの写しを使う -------------------------------------------

def test_窓の窓口と整列はDQ2の写しを使う() -> None:
    from retroux.tools import align_windows
    from retroux.ui import window_manager

    assert window_manager.window_align is W
    assert align_windows.window_align is W


def test_DQ3の窓の道具は変えていない() -> None:
    """★`window_align` は DQ3 が import する（J1）。⚠ 題名だけで探す元の動きはそのまま。"""
    from retroux.core import window_align

    assert window_align.find_windows is not W.find_windows
    assert not hasattr(window_align, "is_dq2_window")


def test_起動スクリプトはDQ2のFCEUXだけを数える() -> None:
    text = (ROOT / "scripts" / "start-dq2.ps1").read_text(encoding="utf-8-sig")
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    line = next(ln for ln in code if "$fceuxRunning = " in ln)
    assert r"*retroux\emulator\fceux\run.lua*" in line
    assert 'Get-Process -Name "fceux*"' not in line
