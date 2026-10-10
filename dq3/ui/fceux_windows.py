"""DQ3 が自分の FCEUX の窓だけに働きかける（RX3-0504 / ★DQ2 共存安全化 / D-42 J2）。

⚠⚠ これは DQ3 の機能追加ではありません。★DQ2 と同時に動かしたときに、
  DQ3 が **DQ2 の FCEUX** を閉じる・動かす・最小化する・前へ出す・速度を変える・音を消すのを止めるための最小変更です
  （依頼者 2026-10-03 の判断 J2 / 調査 `docs/research/261003_dq2-separation-phase-plan.md` §3 Q3）。

## ⚠ 何が起きていたか

`retroux/core/window_align.py` は**題名だけ**で窓を探し、見つかった最初の 1 枚に働きかけます。
⚠ DQ2 の FCEUX も題名は「FCEUX …」で、DQ2 の Lua 窓も「Lua Script」です。

## ★DQ3 の FCEUX の見分け方（★FocusGate と同じ / `dq3/ui/gamepad_link.py`）

窓を持っているプロセスが次のどちらか:

```text
① このプロセス自身
② コマンドラインに **この DQ3 の** `dq3/phase0/dev.lua` がある（★起動スクリプトが `-lua` に絶対パスで渡す）
```

⚠ コマンドラインが読めないプロセスは DQ3 のものと見なさない（★分からないときは触らない、が安全側）。
⚠ 利用者向けの挙動（ボタン・画面・倍率・終了の問い）は変えません。★対象の窓を絞るだけです。

★`window_align` は DQ2 の部品なので変えません。★変えていない部品（作業領域・カーソル・題名の照合）は借ります。
"""

from __future__ import annotations

import os

from retroux.core import window_align as _wa
from retroux.core.window_align import (  # noqa: F401 ★変えていない部品はそのまま借りる
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
    from .gamepad_link import command_line_of as read

    return read(pid)


def lua_marker() -> str:
    """★この DQ3 の FCEUX だけが持つ印（`dq3/phase0/dev.lua` の絶対パス）。"""
    from .gamepad_link import default_lua_marker

    return default_lua_marker()


def is_dq3_command_line(line: str | None, marker: str | None = None) -> bool:
    """★コマンドラインが DQ3 の FCEUX のものか。⚠ None（読めない）は False。"""
    if not line:
        return False
    mark = marker if marker is not None else lua_marker()
    return bool(mark) and _fold(mark) in _fold(line)


def is_dq3_window(handle: int) -> bool:
    pid = owner_pid(handle)
    if pid is None:
        return False
    if pid == os.getpid():
        return True
    return is_dq3_command_line(command_line_of(pid))


def find_windows(title: str, match: str = "contains") -> list[WindowInfo]:
    """★題名が一致し、**DQ3 のプロセスが持つ**可視の窓。

    ⚠ 探すのは `window_align.find_windows`（★検査では conftest がそこを「この検査の窓だけ」に絞る）。
    """
    return [w for w in _wa.find_windows(title, match=match) if is_dq3_window(w.handle)]


# --- ★働きかけ（`window_align` の同名の関数の写し。探す口だけ DQ3 に絞った）-------------

def close_window(title: str, match: str = "prefix") -> bool:
    """DQ3 の窓に「閉じてください」と伝える（★強制終了しない）。"""
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
    """DQ3 の窓を前面に出す（⚠ Windows に拒否されても例外にしない）。"""
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
    """DQ3 の窓を最小化する（★Lua Script 用。閉じない・隠さない）。"""
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


def align(title: str, x: int, y: int,
          width: int | None = None, height: int | None = None,
          match: str = "prefix") -> WindowInfo:
    """最初に見つかった **DQ3 の**窓を動かす（★フォーカスを奪わない）。"""
    if not available():
        raise WindowAlignError("この環境ではウィンドウ整列に対応していません（Windows のみ）")

    windows = find_windows(title, match=match)
    if not windows:
        raise WindowAlignError(
            f"「{title}」で始まる DQ3 のウィンドウが見つかりません。"
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
