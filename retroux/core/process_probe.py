"""そのプロセスが**まだ生きているか**を、殺さずに確かめる（RX-0064 / 2026-08-22）。

## ⚠⚠ なぜ PID だけでは足りないか

Windows は PID を**使い回す**。落ちた RetroUX の PID が、あとで無関係の
プロセス（メモ帳でも何でも）に割り当てられていることがある。
★PID だけを見て「まだ動いている」と判断すると、**他人の窓を理由に**
こちらが閲覧専用へ落ちる。逆に掃除をする実装なら、⚠ **無関係のプロセスを
殺しかねない**（`README §219` がまさにこれを理由に保留にした）。

★そこでロックには **PID と実行ファイル名**を書き、両方が一致したときだけ
「同じ役目のプロセスが生きている」と判断する。
⚠ **ここでは何も殺さない。** 見るだけ（`terminate` は置かない）。

## 使えないときは「分からない」と言う

Windows 以外・API が呼べない環境では `None` を返す（`True` にも `False` にも
しない）。呼ぶ側は「分からないなら従来どおり心拍で判断する」。
"""

from __future__ import annotations

import os
import sys

#: `OpenProcess` に渡す権限。★情報を読むだけ（終了させる権限は取らない）。
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


def current_image_name() -> str:
    """いまのプロセスの実行ファイル名（`pythonw.exe` など）。"""
    return os.path.basename(sys.executable) if sys.executable else ""


def _windows_image_name(pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None                     # ★開けない＝居ないか、権限が無い
    try:
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            if code.value != _STILL_ACTIVE:
                return None             # ★終了済み
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""                   # ★生きてはいるが名前が読めない
        return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)


def alive(pid: int | None, image_name: str | None = None) -> bool | None:
    """その PID が生きているか。⚠ 分からなければ `None`（★0 や False と混ぜない）。

    `image_name` を渡すと、実行ファイル名が一致したときだけ `True`。
    ⚠ PID の使い回しで**別のプロセスを掴まない**ための照合。
    """
    if not pid or pid <= 0:
        return None
    if not sys.platform.startswith("win"):
        return None                     # ★この計画は Windows 前提。他では判断しない
    try:
        got = _windows_image_name(int(pid))
    except Exception:                                   # noqa: BLE001
        return None                     # ⚠ API を呼べない。分からないと言う
    if got is None:
        return False                    # ★居ない（終了済み）
    if image_name and got and got.lower() != image_name.lower():
        return False                    # ⚠ PID は同じだが**別のプロセス**
    return True
