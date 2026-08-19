"""FCEUX ウィンドウを所定の位置・大きさへ動かす（MVP2 Phase 1 / 指示書 5.3）。

指示書の優先順位は「①埋め込み ②自動整列 ③キャプチャ表示」。
**このモジュールは ② だけを実装する。** 理由:

  ・埋め込み（Win32 の `SetParent`）は、親子関係を作った時点で
    **入力フォーカスとメッセージの流れが変わる**。FCEUX はゲームパッドと
    キーボードを自前で拾っているため、ここが崩れると
    「ホットキーが効かない」「パッドが効かない」という形で出る。
    指示書自身が「不安定なら無理に採用しない」「入力フォーカスを壊さない」
    「ジョイパッド入力を阻害しない」と釘を刺している。
  ・整列（`SetWindowPos`）は**位置と大きさを変えるだけ**で、
    ウィンドウの所有者を変えない。失敗しても元のまま動く。

  MVP2 は「RetroUXウィンドウとFCEUXウィンドウを1920×1080内で自動整列」でも可、
  と明記されているので、まず安全な方を出す。

★Windows 依存はこのファイルに閉じる（指示書「Windows依存の埋め込み処理は抽象化する」）。
  他のOSでは `available()` が False を返し、呼び出し側は何もしない。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    x: int
    y: int
    width: int
    height: int


class WindowAlignError(RuntimeError):
    """整列できなかった。**呼び出し側は握りつぶさずに画面へ出すこと。**"""


def available() -> bool:
    """この環境で整列できるか。"""
    return sys.platform == "win32"


def foreground_title() -> str:
    """いま最前面のウィンドウのタイトル。★フォーカスの確認用（RX-0078）。

    ⚠ Win32 依存はこのファイルに閉じる方針（画面から直に ctypes を呼ばない）。
      取れなければ空文字（Windows 以外・失敗）。
    """
    if not available():
        return ""
    import ctypes

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:                                  # noqa: BLE001
        return ""


def title_matches(window_title: str, needle: str, match: str = "contains") -> bool:
    """タイトルの照合。**Win32 に触らないのでテストできる。**

    ここだけ切り出してあるのは、事故の原因が照合の1行だったため
    （"含む" で探して無関係なウィンドウを動かした / find_windows の説明）。
    """
    hay, needle = window_title.lower(), needle.lower()
    if match == "prefix":
        return hay.startswith(needle)
    if match == "exact":
        return hay == needle
    return needle in hay


def find_windows(title: str, match: str = "contains") -> list[WindowInfo]:
    """タイトルが一致する可視ウィンドウを列挙する。

    ★完全一致では見つからない。FCEUX のタイトルは
      「FCEUX 2.6.6 - ドラゴンクエストII…」のようにROM名とバージョンが付く。

    ★★ match は既定を "contains" にしてあるが、**動かす用途では "prefix" を使う** ★★

      実際に踏んだ事故（2026-07-26）: "RetroUX" を**含む**ウィンドウを探したところ、
      **フォルダ名に RetroUX を含むエクスプローラー**
      （「…260721_RetroUX とその他 1 のタブ - エクスプローラー」）が一致し、
      利用者のウィンドウを勝手に動かしてしまった。

      前方一致なら、探したいウィンドウ（`RetroUX — ドラゴンクエストII` /
      `FCEUX 2.6.6 - …`）だけが当たり、パスを含むだけの別ウィンドウは外れる。
      **他人のウィンドウを動かす機能は、当たりすぎる側に倒してはいけない。**
    """
    if not available():
        return []

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[WindowInfo] = []
    title_needle = title

    enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        found_title = buf.value
        if not title_matches(found_title, title_needle, match):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        found.append(WindowInfo(
            handle=int(hwnd), title=found_title,
            x=rect.left, y=rect.top,
            width=rect.right - rect.left, height=rect.bottom - rect.top,
        ))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return found


def close_window(title: str, match: str = "prefix") -> bool:
    """ウィンドウに「閉じてください」と伝える（× を押すのと同じ）。

    ★**強制終了しない。** `Stop-Process` で殺すと、FCEUX は設定ファイルを
      書かずに落ちる（音量・キー割り当て・最近使ったROMなどが失われうる）。
      `WM_CLOSE` なら通常の終了処理が走る。

    ⚠ 保存の確認ダイアログが出るアプリでは、閉じずに待つことがある。
      呼び出し側は「閉じた」と決めつけず、消えたかどうかを見ること。
    """
    if not available():
        return False
    found = find_windows(title, match=match)
    if not found:
        return False

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    WM_CLOSE = 0x0010
    return bool(user32.PostMessageW(found[0].handle, WM_CLOSE, 0, 0))


def work_area(handle: int | None = None) -> "tuple[int, int, int, int] | None":
    """作業領域（タスクバーを除いた範囲）を `(left, top, width, height)` で返す。

    ★★ **画面の大きさではなく「作業領域」を使う**（2026-07-31 の指示書 §7.3）★★

      画面の高さで並べると、⚠ 下端がタスクバーに隠れる。
      タスクバーは上や左に置いている人もいるので、**上端も 0 とは限らない**。

    ★`handle` を渡すと、**そのウィンドウが載っているモニタ**の作業領域を返す。
      複数モニタで、主画面ではないほうに出ているときに効く。
      渡さなければ主モニタの作業領域。

    ⚠ 取れないときは `None`（Windows 以外・API 失敗）。
      **0 で埋めない。** 呼ぶ側が「取れなかった」と分かるようにする。
    """
    if not available():
        return None

    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class _RECT(ctypes.Structure):
        _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                    ("right", wt.LONG), ("bottom", wt.LONG)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", wt.DWORD)]

    try:
        if handle:
            MONITOR_DEFAULTTONEAREST = 2
            monitor = user32.MonitorFromWindow(wt.HWND(handle),
                                               MONITOR_DEFAULTTONEAREST)
        else:
            MONITOR_DEFAULTTOPRIMARY = 1
            monitor = user32.MonitorFromWindow(wt.HWND(0),
                                               MONITOR_DEFAULTTOPRIMARY)
        if not monitor:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
    except OSError:
        return None

    r = info.rcWork
    return (int(r.left), int(r.top),
            int(r.right - r.left), int(r.bottom - r.top))


def primary_bounds() -> "tuple[int, int, int, int] | None":
    """**主モニタだけ**の範囲を `(left, top, width, height)` で返す。

    ★★ **画面を撮るときはこれを使う**（2026-08-01 / 依頼者の環境）★★

      ⚠⚠ 仮想デスクトップ全体を撮ると、**別のモニタで開いている
        関係のない作業まで写る**。依頼者の環境は3画面で、
        2番・3番は別の作業に使っている（原点は -900,0）。

      ★主モニタは定義上 (0,0) から始まるが、**そこに頼らない**。
        `GetMonitorInfo` の `rcMonitor` を読んで範囲をはっきりさせる。
    """
    if not available():
        return None

    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class _RECT(ctypes.Structure):
        _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                    ("right", wt.LONG), ("bottom", wt.LONG)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", wt.DWORD)]

    try:
        MONITOR_DEFAULTTOPRIMARY = 1
        monitor = user32.MonitorFromWindow(wt.HWND(0), MONITOR_DEFAULTTOPRIMARY)
        if not monitor:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
    except OSError:
        return None

    r = info.rcMonitor
    return (int(r.left), int(r.top),
            int(r.right - r.left), int(r.bottom - r.top))


def focus(title: str, match: str = "contains") -> bool:
    """そのウィンドウを前面に出す。戻り値は**できたか**。

    ★★ **並べ終わったら操作先をゲームへ返す**（2026-07-31 の指示書 §8）★★
      整列そのものはフォーカスを奪わない（`SWP_NOACTIVATE`）が、
      ⚠ 起動の途中で Lua Script や GUI が前に出てしまうことがある。
      そのまま渡すと**キーを押してもゲームが動かない**。

    ⚠ `SetForegroundWindow` は Windows の制約で拒否されることがある
      （前面のプロセスが別のとき）。**失敗しても黙って False を返す**。
      ここで例外を投げると、並べ終わったのに整列が失敗扱いになる。
    """
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
    """そのウィンドウを最小化する。戻り値は**できたか**。

    ★★ Lua Script ウィンドウ用（2026-08-01 の指示書 §9）★★
      閉じると Lua が止まるので**閉じない**。最小化なら処理は続く。

    ⚠ 隠す（`SW_HIDE`）ではなく最小化にする。隠すとタスクバーからも消え、
      利用者が**戻す手段を失う**。
    """
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
    """最小化したウィンドウを戻す（障害調査用 / 指示書 §9.2）。

    ★**再表示手段を必ず残す**。戻せない機能は入れない。
    """
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
    """最初に見つかったウィンドウを動かす。戻り値は移動後の情報。

    ★既定は**前方一致**。「含む」で探すと関係のないウィンドウを動かす
      （find_windows の説明にある実際の事故を参照）。

    ⚠ `SetWindowPos` は**フォーカスを奪わない**フラグで呼ぶ。
      奪うと、整列した瞬間にゲームの入力が RetroUX 側へ移ってしまう。
    """
    if not available():
        raise WindowAlignError("この環境ではウィンドウ整列に対応していません（Windows のみ）")

    windows = find_windows(title, match=match)
    if not windows:
        raise WindowAlignError(
            f"「{title}」で始まるウィンドウが見つかりません。"
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
