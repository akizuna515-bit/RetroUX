"""RetroUX DQ2 / DQ3 の製品間排他（RX-0152 / 依頼者 2026-10-03「DQ2 / DQ3 の同時起動はサポートしない」）。

★DQ2 と DQ3 は**同時に 1 製品だけ**動かします（⚠ 同時に使えることは要件にしない）。
★DQ3 側に同じものの写しがあります（`dq3/product_lock.py` / D-42: コードは共有しない）。
  ⚠ 名前（下の定数）は**両方で同じでなければ排他になりません** → `tests/test_product_lock.py` が突き合わせます。

## ★仕組み（⚠ OS の Mutex。ファイルのロックではない）

```text
Local\\RetroUX_Product          ★排他: 動いている製品の GUI プロセスが**所有**する
Local\\RetroUX_Product_DQ2      ★名札: DQ2 の GUI が開いている間だけ存在する（どの製品が動いているか）
Local\\RetroUX_Product_DQ3      ★名札: DQ3 の GUI が開いている間だけ存在する
Local\\RetroUX_ProductLaunch    ★起動の順番待ち: 起動スクリプトが「起動の手順」の間だけ所有する（launcher-common.ps1）
```

★Mutex は**プロセスが死ねば OS が解放する**ので、異常終了しても古いロックで永久に起動できなくなることがありません
（★stale の扱いは OS に任せる / 解放されずに死んだ所有は WAIT_ABANDONED として取れる）。
⚠ ファイルの心拍で見る形は、残骸と生存の区別に PID・心拍・札が要り、確認と取得の間に隙間ができます。

## ★取り方（⚠ 確認 → 取得の 2 段にしない）

```text
1 自分の名札を作る（★先に作る = 負けた側が必ず相手の名札を見られる）
2 排他を所有しにいく（★WaitForSingleObject(0) = OS が 1 つにしか渡さない）
  取れた                       → 起動してよい
  取れない ＋ 相手の名札がある   → ★拒否（相手の名前を言って終わる）
  取れない ＋ 相手の名札が無い   → ★同じ製品が動いている（既存の二重起動の扱いへ。⚠ ここでは拒否しない）
```

⚠ FCEUX の有無では判定しません（★他の用途の FCEUX・前回の残り（orphan）を「相手が起動中」と誤らない）。
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

#: ★名前（⚠ DQ3 の写しと同じでなければ排他にならない）
PRODUCTS = ("DQ2", "DQ3")
LABELS = {"DQ2": "RetroUX DQ2", "DQ3": "RetroUX DQ3"}
DEFAULT_PREFIX = "Local\\RetroUX_Product"
EXCLUSIVE_SUFFIX = ""
LAUNCH_SUFFIX = "Launch"
#: ★検査は本物の名前を使わない（⚠ 遊んでいる製品と取り合わない / conftest が立てる）
PREFIX_ENV = "RETROUX_PRODUCT_LOCK_PREFIX"

WAIT_OBJECT_0 = 0x0
WAIT_ABANDONED = 0x80
WAIT_TIMEOUT = 0x102
SYNCHRONIZE = 0x00100000


def current_prefix() -> str:
    import os

    return os.environ.get(PREFIX_ENV) or DEFAULT_PREFIX


def exclusive_name(prefix: str = DEFAULT_PREFIX) -> str:
    return prefix + EXCLUSIVE_SUFFIX


def identity_name(product: str, prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}_{product}"


def launch_name(prefix: str = DEFAULT_PREFIX) -> str:
    return prefix + LAUNCH_SUFFIX


def busy_message(me: str, other: str) -> str:
    """★依頼者の文面（2026-10-03 §4）。"""
    return (f"{LABELS[other]} が起動中です。\n"
            f"{other}を終了してから{LABELS[me]}を起動してください。")


class Win32Mutex:
    """★Win32 の Mutex（⚠ Windows 以外では使えない → `available()` が False）。"""

    def __init__(self) -> None:
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
        if self._k32 is not None:
            self._k32.CreateMutexW.restype = ctypes.c_void_p
            self._k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            self._k32.OpenMutexW.restype = ctypes.c_void_p
            self._k32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
            self._k32.WaitForSingleObject.restype = ctypes.c_uint32
            self._k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            self._k32.CloseHandle.argtypes = [ctypes.c_void_p]
            self._k32.ReleaseMutex.argtypes = [ctypes.c_void_p]

    def available(self) -> bool:
        return self._k32 is not None

    def create(self, name: str):
        handle = self._k32.CreateMutexW(None, False, name)
        if not handle:
            raise OSError(ctypes.get_last_error(), f"CreateMutexW に失敗しました: {name}")
        return handle

    def try_own(self, handle) -> bool:
        """★所有を試す（待たない）。⚠ 前の持ち主が解放せずに死んでいたら WAIT_ABANDONED = 取れた。"""
        return self._k32.WaitForSingleObject(handle, 0) in (WAIT_OBJECT_0, WAIT_ABANDONED)

    def exists(self, name: str) -> bool:
        handle = self._k32.OpenMutexW(SYNCHRONIZE, False, name)
        if not handle:
            return False
        self._k32.CloseHandle(handle)
        return True

    def release(self, handle) -> None:
        self._k32.ReleaseMutex(handle)

    def close(self, handle) -> None:
        self._k32.CloseHandle(handle)


@dataclass(frozen=True)
class Result:
    ok: bool                     #: ★起動してよいか
    primary: bool = False        #: ★排他を所有したか（⚠ False で ok = 同じ製品が既に動いている）
    other: str | None = None     #: ★拒否の理由になった相手の製品


class ProductLock:
    """★1 製品分の排他。★プロセスが生きている間、取った Mutex を握り続ける（⚠ 解放は OS 任せ）。"""

    def __init__(self, me: str, *, prefix: str = DEFAULT_PREFIX, api=None) -> None:
        if me not in PRODUCTS:
            raise ValueError(f"知らない製品: {me}")
        self.me = me
        self.prefix = prefix
        self.api = api or Win32Mutex()
        self._handles: list = []
        self.result: Result | None = None

    def acquire(self) -> Result:
        if not self.api.available():
            # ⚠ Windows 以外（★検査環境など）。排他の仕組みが無いので止めない
            self.result = Result(ok=True, primary=False)
            return self.result
        ident = self.api.create(identity_name(self.me, self.prefix))
        self._handles.append(ident)
        excl = self.api.create(exclusive_name(self.prefix))
        self._handles.append(excl)
        if self.api.try_own(excl):
            self.result = Result(ok=True, primary=True)
            return self.result
        for other in PRODUCTS:
            if other != self.me and self.api.exists(identity_name(other, self.prefix)):
                self.close()
                self.result = Result(ok=False, other=other)
                return self.result
        # ★同じ製品が既に動いている（★既存の二重起動の扱いに任せる）
        self.result = Result(ok=True, primary=False)
        return self.result

    def close(self) -> None:
        """★握っているものを手放す（⚠ ふつうは呼ばない = プロセスの終わりに OS が解放する）。"""
        primary = self.result is not None and self.result.primary
        for i, handle in enumerate(self._handles):
            if primary and i == 1:
                try:
                    self.api.release(handle)
                except Exception:                      # noqa: BLE001
                    pass
            self.api.close(handle)
        self._handles.clear()


def other_running(me: str, *, prefix: str = DEFAULT_PREFIX, api=None) -> str | None:
    """★相手の製品が動いているか（名札で見る / ⚠ 判定の補助。正本は `ProductLock.acquire()`）。"""
    api = api or Win32Mutex()
    if not api.available():
        return None
    for other in PRODUCTS:
        if other != me and api.exists(identity_name(other, prefix)):
            return other
    return None


def show_busy(me: str, other: str, *, log=None, box=None) -> None:
    """★拒否の理由を出す（★Qt を立てる前でも出せるよう Win32 の MessageBox / pythonw でも見える）。"""
    text = busy_message(me, other)
    if log is not None:
        log.warning("%s", text.replace("\n", " "))
    if box is not None:
        box(text)
        return
    if sys.platform == "win32":
        try:
            MB_ICONWARNING = 0x30
            ctypes.windll.user32.MessageBoxW(None, text, LABELS[me], MB_ICONWARNING)
        except Exception:                              # noqa: BLE001
            pass
    else:
        print(text, file=sys.stderr)


def guard(me: str, *, log=None, box=None, prefix: str | None = None, api=None) -> ProductLock | None:
    """★GUI の入口で呼ぶ。拒否なら理由を出して None（★呼ぶ側は何も始めずに終わる）。

    ★戻り値の ProductLock はプロセスが終わるまで持っておく（⚠ 捨てても handle は閉じないが、意図を残すため）。
    """
    lock = ProductLock(me, prefix=prefix or current_prefix(), api=api)
    result = lock.acquire()
    if not result.ok:
        show_busy(me, result.other, log=log, box=box)
        return None
    return lock


def main(argv: list[str] | None = None) -> int:
    """★検査・診断用: `python -m retroux.core.product_lock --hold DQ2 --prefix X --seconds 2`。"""
    import argparse
    import os
    import time

    ap = argparse.ArgumentParser(description="RetroUX 製品間排他（診断・検査用）")
    ap.add_argument("--hold", choices=PRODUCTS, help="この製品として排他を取り、--seconds だけ握る")
    ap.add_argument("--check", choices=PRODUCTS, help="この製品から見て、相手が動いているかを出す")
    ap.add_argument("--prefix", default=DEFAULT_PREFIX)
    ap.add_argument("--seconds", type=float, default=0.0)
    args = ap.parse_args(argv)
    if args.check:
        other = other_running(args.check, prefix=args.prefix)
        print(f"OTHER={other}" if other else "FREE", flush=True)
        return 0
    if args.hold:
        lock = ProductLock(args.hold, prefix=args.prefix)
        result = lock.acquire()
        # ★本当のプロセス番号も出す（⚠ venv の python.exe は子に本体を起こすので、親を止めても握ったまま）
        word = ("ACQUIRED" if result.primary else "SAME") if result.ok else f"REFUSED={result.other}"
        print(f"{word} pid={os.getpid()}", flush=True)
        if result.ok and args.seconds:
            time.sleep(args.seconds)
        return 0 if result.ok else 3
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
