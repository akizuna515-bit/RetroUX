"""DQ3 は自分の FCEUX の窓だけに働きかける（RX3-0504 / DQ2 共存安全化 / D-42 J2）。

⚠ 以前は題名だけで探していて、DQ2 と同時に動かすと DQ3 が **DQ2 の FCEUX** を閉じる・動かす・
  Lua 窓を最小化する・前へ出す・速度を変える・音を消すことがありえた（調査 §3 Q3）。

★本物の窓には触りません（★窓・プロセス番号・コマンドラインはすべて偽物を差し込む）。
"""

from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from dq3.ui import fceux_windows as F
from retroux.core.window_align import WindowInfo

ROOT = Path(__file__).resolve().parents[1]

MARK = r"C:\RetroUX-DQ3\dq3\phase0\dev.lua"
DQ3_FCEUX = r'"C:\RetroUX-DQ3\tools\fceux\fceux64.exe" -lua "C:\RetroUX-DQ3\dq3\phase0\dev.lua" "C:\RetroUX-DQ3\work\rom\DQ3_J.nes"'
OTHER_DQ3 = r'"D:\old\tools\fceux\fceux64.exe" -lua "D:\old\dq3\phase0\dev.lua" "D:\old\work\rom\DQ3_J.nes"'
DQ2_FCEUX = r'"C:\RetroUX\tools\fceux\fceux64.exe" -lua "C:\RetroUX\retroux\emulator\fceux\run.lua" "C:\RetroUX\work\rom\DQ2_J.nes"'


@pytest.mark.parametrize("line, expected", [
    (DQ3_FCEUX, True),
    (DQ3_FCEUX.replace("\\", "/").upper(), True),
    (DQ2_FCEUX, False),
    (OTHER_DQ3, False),                         # ★別の場所の DQ3（★FocusGate と同じく、この DQ3 の dev.lua だけ）
    (None, False),                              # ⚠ 読めないものは DQ3 と見なさない
])
def test_コマンドラインでDQ3のFCEUXを見分ける(line, expected) -> None:
    assert F.is_dq3_command_line(line, marker=MARK) is expected


WINDOWS = {
    11: ("FCEUX 2.6.6: DQ2_J", 201, DQ2_FCEUX),     # ★DQ2 を先に並べる = 題名だけなら最初に当たる
    12: ("FCEUX 2.6.6: DQ3_J", 202, DQ3_FCEUX),
    21: ("Lua Script", 201, DQ2_FCEUX),
    22: ("Lua Script", 202, DQ3_FCEUX),
}


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch):
    def find(title, match="contains"):
        return [WindowInfo(handle=h, title=t, x=0, y=0, width=10, height=10)
                for h, (t, _p, _l) in WINDOWS.items() if F.title_matches(t, title, match)]

    pid_of = {h: pid for h, (_t, pid, _l) in WINDOWS.items()}
    line_of = {pid: line for _h, (_t, pid, line) in WINDOWS.items()}
    monkeypatch.setattr(F._wa, "find_windows", find)
    monkeypatch.setattr(F, "owner_pid", lambda handle: pid_of.get(handle))
    monkeypatch.setattr(F, "command_line_of", lambda pid: line_of.get(pid))
    monkeypatch.setattr(F, "lua_marker", lambda: MARK)
    monkeypatch.setattr(F, "available", lambda: True)

    class User32:
        calls: list = []

        def PostMessageW(self, h, msg, w, lp):
            self.calls.append(("close", h)); return 1

        def SetForegroundWindow(self, h):
            self.calls.append(("focus", h)); return 1

        def ShowWindow(self, h, cmd):
            self.calls.append(("show", h)); return 1

        def SetWindowPos(self, h, after, x, y, w, hh, flags):
            self.calls.append(("move", h)); return 1

    user32 = User32()
    user32.calls = []
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: user32)
    return user32


def test_探すとDQ3の窓だけ返る(fake) -> None:
    assert [w.handle for w in F.find_windows("FCEUX", match="prefix")] == [12]
    assert [w.handle for w in F.find_windows("Lua Script")] == [22]


def test_閉じる最小化並べる前へ出すはDQ3の窓だけ(fake) -> None:
    F.close_window("FCEUX")
    F.minimize("Lua Script")
    F.align("FCEUX", 1, 2)
    F.focus("FCEUX")
    assert {h for _k, h in fake.calls} == {12, 22}


def test_DQ3の窓が無ければ何もしない(fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(F, "lua_marker", lambda: r"Z:\nowhere\dq3\phase0\dev.lua")
    assert F.close_window("FCEUX") is False
    assert F.focus("FCEUX") is False
    with pytest.raises(F.WindowAlignError):
        F.align("FCEUX", 0, 0)
    assert fake.calls == []


def test_画面はDQ3の写しを使う() -> None:
    from dq3.ui import main_window

    assert main_window.window_align is F


def test_省力操作の終わりに前へ出すのはDQ3のFCEUX(fake) -> None:
    from dq3.ui import game_focus

    assert game_focus._default_focus("FCEUX") is True
    assert fake.calls == [("focus", 12)]


def test_速度と音はDQ3のFCEUXだけを探す(fake, monkeypatch: pytest.MonkeyPatch) -> None:
    """★速度（WM_COMMAND）と音（プロセス番号）は `emu_speed.find_fceux` から相手を決める。

    ★本物の窓の列挙を偽物に差し替えて、**DQ2 の FCEUX を先に**見せる。
    ⚠ 検査中の `find_fceux` は conftest が「この検査の窓だけ」に絞っているので、元の関数（`__wrapped__`）を呼ぶ。
    """
    from dq3.ui import emu_speed

    titles = {h: t for h, (t, _p, _l) in WINDOWS.items()}

    class Enum:
        def EnumWindows(self, visit, _lparam):
            for h in titles:
                visit(h, 0)
            return True

        def GetWindowTextLengthW(self, h):
            return len(titles[int(h)])

        def GetWindowTextW(self, h, buf, n):
            buf.value = titles[int(h)]
            return n

        def IsWindowVisible(self, h):
            return True

    monkeypatch.setattr(emu_speed, "_user32", lambda: Enum())
    original = getattr(emu_speed.find_fceux, "__wrapped__", emu_speed.find_fceux)
    assert original() == 12
