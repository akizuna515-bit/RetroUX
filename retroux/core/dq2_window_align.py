"""DQ2 の窓だけを探して動かす（RX-0145 / D-42 / 依頼者の判断 J1・J2）。

★`retroux/core/window_align.py` の「探す・閉じる・前へ出す・最小化・戻す・並べる」を、
  **DQ2 のプロセスが持つ窓だけ**に絞った写しです（⚠ 共有ではありません）。

## ⚠⚠ なぜ要るか（調査 `docs/research/261003_dq2-separation-phase-plan.md` §2 D3・D4）

`window_align` は**題名だけ**で窓を探し、見つかった最初の 1 枚に働きかけます。
⚠ DQ3 の FCEUX も題名は「FCEUX …」、DQ3 の画面も「RetroUX DQ3 …」で始まります。
→ ⚠ DQ2 を閉じると DQ3 の FCEUX に WM_CLOSE が届きうる（未セーブの進行を失う）。
→ ⚠ 整列が DQ3 の FCEUX・DQ3 の画面・DQ3 の「ログ」窓を動かす。

⚠ `window_align` は DQ3 も import しているので、DQ2 の都合では変えません（J1）。
★DQ2 はこの写しを使います。★変えていない部品（作業領域・カーソル・題名の照合など）はそのまま借ります。

## ★DQ2 の窓の見分け方（⚠ 題名では見分けない）

窓を持っているプロセスが次のどれか:

```text
① このプロセス自身（★GUI の中から並べる・閉じるとき）
② コマンドラインに `retroux\\emulator\\fceux\\run.lua` がある（★DQ2 の FCEUX = 起動スクリプトが `-lua` に渡す）
③ コマンドラインに `retroux.gui` がある（★DQ2 の画面 = `python -m retroux.gui`）
```

★DQ3 の FCEUX は `-lua …\\dq3\\phase0\\dev.lua`、DQ3 の画面は `-m dq3.ui.app` なので、どれにも当たりません。
⚠ コマンドラインが読めないプロセスは **DQ2 のものと見なさない**（★分からないときは触らない、が安全側。
  ⚠ 最悪でも「DQ2 の窓が並ばない・閉じない」だけで、相手の進行は失わない）。
"""

from __future__ import annotations

import os

from . import window_align as _wa
from .window_align import (  # noqa: F401 ★変えていない部品はそのまま借りる
    WindowAlignError,
    WindowInfo,
    available,
    foreground_title,
    mouse_left,
    move_cursor,
    primary_bounds,
    title_matches,
    work_area,
)

#: ★DQ2 の FCEUX の印（起動スクリプトが `-lua` に渡す Lua）
DQ2_LUA_MARKER = "retroux\\emulator\\fceux\\run.lua"
#: ★DQ2 の画面の印（`python -m retroux.gui`）
DQ2_GUI_MARKER = "retroux.gui"
MARKERS = (DQ2_LUA_MARKER, DQ2_GUI_MARKER)


def _fold(text: str) -> str:
    return str(text).replace("/", "\\").casefold()


def owner_pid(handle: int) -> int | None:
    """★窓を持っているプロセスの番号（⚠ 取れなければ None）。"""
    try:
        import ctypes
        import ctypes.wintypes as W

        pid = W.DWORD()
        ctypes.WinDLL("user32").GetWindowThreadProcessId(W.HWND(int(handle)), ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:                                        # noqa: BLE001 ★Windows 以外・取れないとき
        return None


def command_line_of(pid: int) -> str | None:
    """★プロセスのコマンドライン（⚠ 取れなければ None）。

    ★`NtQueryInformationProcess(ProcessCommandLineInformation = 60)`（Windows 8.1 以降）。
    ★DQ3 の `dq3/ui/gamepad_link.py::command_line_of` の写し（⚠ import しない / D-42）。
    """
    try:
        import ctypes
        import ctypes.wintypes as W

        k32 = ctypes.windll.kernel32
        ntdll = ctypes.windll.ntdll
        handle = k32.OpenProcess(0x1000, False, int(pid))    # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            need = W.ULONG(0)
            ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(need))
            if need.value <= 0 or need.value > 1 << 20:
                return None
            buf = ctypes.create_string_buffer(need.value)
            status = ntdll.NtQueryInformationProcess(handle, 60, buf, need.value, ctypes.byref(need))
            if status != 0:
                return None

            class _UnicodeString(ctypes.Structure):
                _fields_ = [("Length", W.USHORT), ("MaximumLength", W.USHORT),
                            ("Buffer", ctypes.c_void_p)]

            head = _UnicodeString.from_buffer(buf)
            if not head.Buffer or head.Length == 0:
                return None
            return ctypes.wstring_at(head.Buffer, head.Length // 2)
        finally:
            k32.CloseHandle(handle)
    except Exception:                                        # noqa: BLE001
        return None


def is_dq2_command_line(line: str | None) -> bool:
    """★コマンドラインが DQ2 のもの（FCEUX か画面）か。⚠ None（読めない）は False。"""
    if not line:
        return False
    folded = _fold(line)
    return any(_fold(mark) in folded for mark in MARKERS)


def is_dq2_process(pid: int | None, *, own_pid: int | None = None, cmdline_of=None) -> bool:
    """★DQ2 のプロセスか（① 自分 ② DQ2 の FCEUX ③ DQ2 の画面）。"""
    if pid is None:
        return False
    if pid == (own_pid if own_pid is not None else os.getpid()):
        return True
    return is_dq2_command_line((cmdline_of or command_line_of)(pid))


def is_dq2_window(handle: int, *, own_pid: int | None = None, pid_of=None, cmdline_of=None) -> bool:
    return is_dq2_process((pid_of or owner_pid)(handle), own_pid=own_pid, cmdline_of=cmdline_of)


def find_windows(title: str, match: str = "contains") -> list[WindowInfo]:
    """★題名が一致し、**DQ2 のプロセスが持つ**可視の窓。

    ⚠ 探すのは `window_align.find_windows`（★検査では conftest がそこを「この検査の窓だけ」に絞る）。
    """
    return [w for w in _wa.find_windows(title, match=match) if is_dq2_window(w.handle)]


# --- ★働きかけ（`window_align` の同名の関数の写し。探す口だけ DQ2 に絞った）-------------

def close_window(title: str, match: str = "prefix") -> bool:
    """DQ2 の窓に「閉じてください」と伝える（× を押すのと同じ / ★強制終了しない）。"""
    if not available():
        return False
    found = find_windows(title, match=match)
    if not found:
        return False

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    WM_CLOSE = 0x0010
    return bool(user32.PostMessageW(found[0].handle, WM_CLOSE, 0, 0))


def focus(title: str, match: str = "contains") -> bool:
    """DQ2 の窓を前面に出す（⚠ Windows に拒否されても例外にしない）。"""
    if not available():
        return False
    windows = find_windows(title, match=match)
    if not windows:
        return False

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        return bool(user32.SetForegroundWindow(windows[0].handle))
    except OSError:
        return False


def minimize(title: str, match: str = "contains") -> bool:
    """DQ2 の窓を最小化する（★Lua Script 用。閉じない・隠さない）。"""
    if not available():
        return False
    windows = find_windows(title, match=match)
    if not windows:
        return False

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    SW_MINIMIZE = 6
    try:
        user32.ShowWindow(windows[0].handle, SW_MINIMIZE)
        return True
    except OSError:
        return False


def restore(title: str, match: str = "contains") -> bool:
    """最小化した DQ2 の窓を戻す（★再表示手段を必ず残す）。"""
    if not available():
        return False
    windows = find_windows(title, match=match)
    if not windows:
        return False

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    SW_RESTORE = 9
    try:
        user32.ShowWindow(windows[0].handle, SW_RESTORE)
        user32.SetForegroundWindow(windows[0].handle)
        return True
    except OSError:
        return False


def align(title: str, x: int, y: int,
          width: int | None = None, height: int | None = None,
          match: str = "prefix") -> WindowInfo:
    """最初に見つかった **DQ2 の**窓を動かす（★フォーカスを奪わない）。"""
    if not available():
        raise WindowAlignError("この環境ではウィンドウ整列に対応していません（Windows のみ）")

    windows = find_windows(title, match=match)
    if not windows:
        raise WindowAlignError(
            f"「{title}」で始まる DQ2 のウィンドウが見つかりません。"
            "先に起動してから実行してください。")

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    target = windows[0]

    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010      # ★フォーカスを奪わない
    flags = SWP_NOZORDER | SWP_NOACTIVATE
    if width is None or height is None:
        SWP_NOSIZE = 0x0001
        flags |= SWP_NOSIZE
        width = target.width
        height = target.height

    ok = user32.SetWindowPos(target.handle, 0, int(x), int(y),
                             int(width), int(height), flags)
    if not ok:
        err = ctypes.get_last_error()
        raise WindowAlignError(f"ウィンドウを動かせませんでした（Win32 エラー {err}）")

    moved = find_windows(title, match=match)
    return moved[0] if moved else target
