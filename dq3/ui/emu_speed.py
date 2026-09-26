"""FCEUX の速度を外から変える（RX3-0059 / EmulatorSpeedController）。

## ★方式（`docs/research/fceux-speed-control.md` / RX-0107 の PoC を製品側へ薄く移した）

```text
メニュー命令（WM_COMMAND）を PostMessage で送る。⚠ キー送信ではない（FCEUX のホットキーは DirectInput 読み）
Normal Speed（100%）を錨にして Speed Up を n 回 → 150 / 200 / 300 / 400%
★最小化していても効く。⚠ fps_scale は fceux.cfg に保存されない（★起動し直せば 100%）
```

⚠ Turbo（`emu.speedmode`）の入切とは別の責務。★聞き込みの処理には倍率を埋め込まない（指示書 §7）。

## ★元へ戻す（指示書 §6）

`restore()` は必ず Normal を送る。★画面を閉じるとき / OFF にしたとき / Python の終了時（atexit）に呼ぶ。
"""
from __future__ import annotations

import atexit
import sys

WM_COMMAND = 0x0111
#: ★`src/drivers/win/resource.h`（FCEUX 2.6.6）。⚠ 版が変わったら要確認
CMD_NORMAL, CMD_UP, CMD_DOWN = 40268, 40265, 40266
#: ★Speed Up の回数 → 実効速度（実測 / RX-0107）
STEPS = {1.0: 0, 1.5: 1, 2.0: 2, 3.0: 3, 4.0: 4}


def _user32():
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.WinDLL("user32", use_last_error=True)


def find_fceux() -> int:
    """★題名が FCEUX で始まる見える窓。⚠ 無ければ 0。"""
    u = _user32()
    if u is None:
        return 0
    import ctypes
    import ctypes.wintypes as wt

    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(hwnd, _l):
        n = u.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith("FCEUX") and u.IsWindowVisible(hwnd):
                found.append(hwnd)
        return True

    u.EnumWindows(visit, 0)
    return found[0] if found else 0


class EmulatorSpeedController:
    def __init__(self, sender=None, finder=None) -> None:
        self._send = sender or self._post
        self._find = finder or find_fceux
        self.current = 1.0            #: ★最後に頼んだ倍率（⚠ FCEUX 側の真値ではない）
        self.hold = False             #: ★聞き込みなどが「終わるまで戻すな」と握っている印（★管理画面を閉じても戻さない）
        self.last_error: str | None = None
        self.sent: list[int] = []
        atexit.register(self._atexit)

    def reassert(self) -> bool:
        """★いまの倍率をもう一度送る（⚠ Lua の `emu.speedmode` などで FCEUX 側が戻っても取り返す）。"""
        if self.current == 1.0:
            return True
        return self.set_speed(self.current)

    def _post(self, cmd: int) -> bool:
        u = _user32()
        hwnd = self._find()
        if u is None or not hwnd:
            self.last_error = "⚠ FCEUX の窓が見つかりません"
            return False
        ok = u.PostMessageW(hwnd, WM_COMMAND, cmd, 0)
        if not ok:
            self.last_error = "⚠ 送れませんでした（%d）" % cmd
        return bool(ok)

    def connected(self) -> bool:
        return bool(self._find())

    def set_speed(self, factor: float) -> bool:
        """★Normal を送ってから Speed Up を n 回（★絶対の錨があるので何度呼んでも同じ）。"""
        if factor not in STEPS:
            raise ValueError("⚠ 出せる倍率は %s" % sorted(STEPS))
        self.last_error = None
        if not self._send(CMD_NORMAL):
            return False
        self.sent.append(CMD_NORMAL)
        for _ in range(STEPS[factor]):
            if not self._send(CMD_UP):
                return False
            self.sent.append(CMD_UP)
        self.current = factor
        return True

    def restore(self) -> bool:
        """★通常速度へ（⚠ 失敗しても例外にしない）。"""
        ok = self.set_speed(1.0)
        self.current = 1.0
        return ok

    def _atexit(self) -> None:
        if self.current != 1.0:
            try:
                self.restore()
            except Exception:                                   # noqa: BLE001
                pass
