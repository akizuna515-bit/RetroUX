"""DQ3 のコントローラー（XBOX / XInput）をつなぐ（RX3-0486 / 2026-10-02）。

依頼者 2026-10-02（DQ3-000154）:

    案 A で実装する。DQ2 の入力部品を共通利用し、DQ3 側へ接続する。DQ2 の既存動作を維持。

## ★★ 共通部品は読むだけ（⚠ `retroux/` は 1 行も変えない）

```text
★借りる   retroux/application/gamepad.py   XInputReader / GamepadRouter / HoldRouter /
                                            nes_mask / mouse_velocity / MouseButton / should_write_pad
★借りる   retroux/core/window_align.py     move_cursor / mouse_left
★ここ     DQ3 の割り当て・フォーカス・入力ファイル・頼みの列
```

★共通部品が出すのは**操作の名前**（`talk` / `load` / `save` …）だけです。
⚠ それを何に結ぶかは画面側が決めます（★DQ2 は `retroux/ui/main_window.py`、DQ3 はここ）。
→ ★DQ3 で X を「聞き込み」に結んでも、DQ2 の X（店・くじ）は変わりません。

## ★割り当て（依頼者 2026-10-02 §1）

```text
十字 / 左スティック / A / B / START / BACK   ゲームの操作（★swap_ab: XBOX の B = ゲームの A）
右スティック / R3                            マウス移動 / 左クリック
LT / RT / Y                                  戦闘 AI（オート）/ ターボ / まんたん
X（短く）                                    宿屋に移動（★［宿］ボタンと同じ / 戦闘中は出さない）
X（戦闘中に長押し）                          強制オート ＋ 一時ターボ（★離すと開始前へ）
LB / RB                                      ★ステート 0 の読込 / 保存（⚠ 0 固定 / 依頼者 2026-10-02 DQ3-000156）
```

⚠ 2026-10-02（DQ3-000156）: X 短押しを「聞き込み」→「宿屋に移動」、LB / RB を「設定の番号」→「0 固定」に変えました。

## ⚠⚠ DQ3 だけの決まり（★DQ2 は変えない）

```text
★フォーカス   DQ3 の FCEUX か、この RetroUX の窓が前のときだけ効く（依頼者 §3）
              ⚠ 外れたら: ゲーム入力 0 / マウスボタンを離す / 長押しを解く / 頼みの列を捨てる
              ★戻ったら: **全部離すまで**何もしない（⚠ 押したまま戻って暴発しない）
★切断        同じ（★挿し直しても、全部離すまで何もしない）
★自動中      ゲーム入力は Lua の `B.tick` が渡さない（⚠ 自動を優先）。★B は Python で町の自動を止める
```
"""
from __future__ import annotations

import collections
import dataclasses
import os
import pathlib
import threading
import time

from retroux.application import gamepad as GP

#: ★`work/dq3-ui-settings.json` の置き場所（⚠ DQ2 の `user_config.yaml` の `gamepad:` とは別）
SECTION = "gamepad"
#: ★入力ファイル（⚠ `dq3/phase0/pad_input.lua` と同じ名前 / ownership では derived）
PAD_FILE_NAME = "dq3-gamepad.txt"
#: ★読む間隔（秒）＝ 約 60 Hz（★DQ2 と同じ）
TICK_SECONDS = 0.016
#: ★何も押していないときに書く間隔（回）（★DQ2 と同じ / 音の途切れ対策 RX-0083）
IDLE_HEARTBEAT = 30
#: ★1 行の幅（★DQ2 と同じ 23 文字 ＋ 改行 / 開いたまま上書きするので長さを揃える）
LINE_WIDTH = 23
#: ⚠ セーブ・ロードの続けざまを止める（秒）（依頼者 §4: 長押しや連打で繰り返さない）
STATE_COOLDOWN = 1.5

#: ★DQ3 で出す操作（⚠ 画面側の名前）
INN, CANCEL, RELEASED = "inn", "cancel", "released"
FORCE_BEGIN, FORCE_END = GP.EVENT_FORCE_AUTO_BEGIN, GP.EVENT_FORCE_AUTO_END

#: ★★ LB / RB が使うセーブステート（⚠ **0 固定** / 依頼者 2026-10-02 DQ3-000156）★★
#:   ⚠ 設定に番号が残っていても読みません（★DQ2 の `shutdown.save_slot` とは無関係）。
PAD_STATE_SLOT = 0

#: ★共通部品の操作名 → DQ3 の頼み（⚠ X だけは宿屋へ / 戦闘中は長押しのほう）
DQ3_ACTIONS = {
    GP.EVENT_LOAD: "load_state",
    GP.EVENT_SAVE: "save_state",
    GP.EVENT_TOGGLE_AUTO: "auto",
    GP.EVENT_TOGGLE_TURBO: "turbo",
    GP.EVENT_MANTAN: "mantan",
    GP.EVENT_TALK: INN,
}


@dataclasses.dataclass(frozen=True)
class PadSettings:
    """★DQ3 のパッドの設定（`work/dq3-ui-settings.json` の `gamepad`）。

    ⚠ スロットの番号は持ちません（★LB / RB は `PAD_STATE_SLOT` = 0 固定）。
      ★古い設定に `state_slot` が残っていても**読まないだけ**です（⚠ 設定は消さない / 初期化しない）。
    """

    enabled: bool = True
    swap_ab: bool = True
    mouse: bool = True
    mouse_speed: float = 900.0
    force_auto_hold_ms: float = GP.DEFAULT_HOLD_MS

    @classmethod
    def from_settings(cls, settings) -> "PadSettings":
        """⚠ 読めない値は既定へ（★落とさない）。"""
        base = cls()
        if settings is None:
            return base

        def got(key, kind):
            default = getattr(base, key)
            try:
                value = settings.get(SECTION, key, default)
                return kind(value) if value is not None else default
            except (TypeError, ValueError):
                return default
            except Exception:                                # noqa: BLE001 ★設定の不調で起動を止めない
                return default

        return cls(enabled=got("enabled", bool), swap_ab=got("swap_ab", bool),
                   mouse=got("mouse", bool), mouse_speed=max(0.0, got("mouse_speed", float)),
                   force_auto_hold_ms=max(0.0, got("force_auto_hold_ms", float)))


# ----------------------------------------------------------------------
# ★フォーカス（DQ3 の FCEUX か、この RetroUX か）
# ----------------------------------------------------------------------

def _foreground_pid() -> int | None:
    """★いま前にある窓のプロセス番号（⚠ 取れなければ None）。"""
    try:
        import ctypes
        import ctypes.wintypes as W

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:                                        # noqa: BLE001 ★Windows 以外・取れないとき
        return None


def _exe_of(pid: int) -> str | None:
    """★プロセスの exe の場所（⚠ 取れなければ None）。"""
    try:
        import ctypes
        import ctypes.wintypes as W

        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, int(pid))    # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            size = W.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            return buf.value
        finally:
            k32.CloseHandle(handle)
    except Exception:                                        # noqa: BLE001
        return None


def command_line_of(pid: int) -> str | None:
    """★プロセスのコマンドライン（⚠ 取れなければ None）。

    ★`NtQueryInformationProcess(ProcessCommandLineInformation = 60)`（Windows 8.1 以降）。
    ⚠ WMI / PowerShell は使いません（★60 Hz の読み取りの中で呼ぶため / 結果は pid ごとに覚える）。
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


def default_lua_marker() -> str:
    """★DQ3 の FCEUX だけが持つ印 = launcher が `-lua` に渡す `dq3/phase0/dev.lua` の場所。"""
    from dq3 import paths as P3

    return str(P3.program_root() / "dq3" / "phase0" / "dev.lua")


def _norm(path) -> str:
    try:
        return os.path.normcase(str(pathlib.Path(path).resolve()))
    except OSError:
        return os.path.normcase(str(path))


class FocusGate:
    """★DQ3 の FCEUX か、この RetroUX の窓が前にあるか（依頼者 2026-10-02 §3）。

    ★FCEUX は 2 つで見分けます（⚠ 題名では見分けません。★DQ2 の FCEUX も「FCEUX」で始まります）:
      ① exe が DQ3 の起動に使うもの（`dq3.paths.fceux()`）
      ② ★コマンドラインに **この DQ3 の `dq3/phase0/dev.lua`** がある（launcher が `-lua` に渡す）
         ⚠ 同じ exe から DQ2 や別の FCEUX を起こしても、②で外れます（依頼者 2026-10-02 DQ3-000156）
    ⚠ コマンドラインが読めないとき（★権限など）は①だけで決め、`unverified` に数えます。
    """

    def __init__(self, target_exe=None, own_pid: int | None = None,
                 foreground=None, exe_of=None, marker=None, cmdline_of=None) -> None:
        self._target = target_exe
        self._own = own_pid if own_pid is not None else os.getpid()
        self._foreground = foreground or _foreground_pid
        self._exe_of = exe_of or _exe_of
        self._marker = marker
        self._cmdline_of = cmdline_of or command_line_of
        self._cache: dict[int, bool] = {}
        self.unverified = 0

    @staticmethod
    def _fold(text: str) -> str:
        return str(text).replace("/", "\\").casefold()

    def marker(self) -> str | None:
        got = self._marker() if callable(self._marker) else self._marker
        return self._fold(got) if got else None

    def target(self) -> str | None:
        got = self._target() if callable(self._target) else self._target
        return _norm(got) if got else None

    def is_target(self) -> bool:
        pid = self._foreground()
        if pid is None:
            return False
        if pid == self._own:
            return True
        if pid in self._cache:
            return self._cache[pid]
        want = self.target()
        exe = self._exe_of(pid)
        ok = bool(want and exe and _norm(exe) == want)
        mark = self.marker()
        if ok and mark:
            line = self._cmdline_of(pid)
            if line is None:
                self.unverified += 1                         # ⚠ ①だけで決めた
            else:
                ok = mark in self._fold(line)
        if len(self._cache) > 64:                            # ★溜めすぎない
            self._cache.clear()
        self._cache[pid] = ok
        return ok


def _default_target_exe():
    from dq3 import paths as P3

    return P3.fceux()


# ----------------------------------------------------------------------
# ★入力ファイル（★DQ2 と同じ形 `"<seq> <mask>"` / 開いたまま上書き）
# ----------------------------------------------------------------------

class PadFileWriter:
    """★NES のボタンを Lua へ渡す（⚠ 原子置換ではなく、開いたまま上書き / DQ2 RX-0097）。"""

    def __init__(self, path) -> None:
        self.path = pathlib.Path(path)
        self.seq = 0
        self.last_mask = 0
        self._idle = 0
        self._fh = None
        self.writes = 0

    def _line(self, mask: int) -> bytes:
        self.seq += 1
        return ("%d %d" % (self.seq, int(mask))).ljust(LINE_WIDTH).encode("ascii") + b"\n"

    def _write(self, mask: int) -> None:
        try:
            if self._fh is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                mode = "r+b" if self.path.exists() else "w+b"
                self._fh = open(self.path, mode, buffering=0)   # noqa: SIM115 ★開いたまま持つ
            self._fh.seek(0)
            self._fh.write(self._line(mask))
            self.writes += 1
        except OSError:
            self.close()                                     # ⚠ 次の回で開き直す
        self.last_mask = int(mask)

    def put(self, mask: int) -> None:
        """★押している間は毎回、何も押していなければ間引いて書く（★DQ2 と同じ）。"""
        write, self._idle = GP.should_write_pad(int(mask), self.last_mask, self._idle, IDLE_HEARTBEAT)
        if write or self.writes == 0:                       # ★最初の 1 回は必ず（★Lua が 0 を読めるように）
            self._write(mask)

    def zero(self) -> None:
        """⚠ すぐに全部離す（★フォーカスが外れた・切断・終わるとき）。"""
        self._idle = 0
        self._write(0)

    def close(self) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass


# ----------------------------------------------------------------------
# ★頼みの列（⚠ 置き場は 1 つなので、前の頼みが届いてから次を書く / RX3-0130）
# ----------------------------------------------------------------------

#: ⚠ 届かないとみなすまでの秒 / 出し直す回数
QUEUE_RESEND_AFTER = 3.0
QUEUE_MAX_TRIES = 3
#: ★止める・取り消す頼みは先に出す（依頼者 §5）
PRIORITY_ACTIONS = ("nav_stop", "restock_stop", "walk_stop", "town_end")


class CommandQueue:
    """★パッドの頼みを 1 つずつ Lua へ渡す（⚠ 画面のボタンは今までどおり直に送る）。

    `writer` … `CommandWriter`（`send(action, **params)` が seq を返す）
    `stage`  … `stage(seq, action)` が `received` / `applied` / `lost` / `unsent` を返す
    """

    def __init__(self, writer, stage, clock=time.monotonic, log=None, on_sent=None) -> None:
        self.writer = writer
        self.stage = stage
        self.clock = clock
        self.log = log or (lambda _line: None)
        #: ★出した頼みの番号を知らせる先（★セーブ / ロードの結果を番号で突き合わせる）
        self.on_sent = on_sent or (lambda _action, _seq: None)
        self.pending: collections.deque = collections.deque()
        self.inflight: dict | None = None
        self.sent: list = []
        self.dropped: list = []

    def push(self, action: str, **params) -> None:
        item = {"action": action, "params": {k: str(v) for k, v in params.items()}}
        if action in PRIORITY_ACTIONS:
            self.pending.appendleft(item)
        elif any(p["action"] == action and p["params"] == item["params"] for p in self.pending):
            return                                           # ⚠ 同じ頼みを積み増さない
        else:
            self.pending.append(item)

    def clear(self, why: str = "") -> None:
        """⚠ まだ出していない頼みを捨てる（★終了・切断・フォーカスが外れたとき）。"""
        if self.pending:
            self.dropped.extend(p["action"] for p in self.pending)
            self.log("⚠ パッドの頼みを捨てました（%s）: %s"
                     % (why, ", ".join(p["action"] for p in self.pending)))
        self.pending.clear()

    def _send(self, item: dict) -> None:
        seq = self.writer.send(item["action"], **item["params"])
        self.inflight = dict(item, seq=seq, at=self.clock(), tries=item.get("tries", 0) + 1)
        self.sent.append(item["action"])
        self.on_sent(item["action"], seq)

    def tick(self) -> None:
        if self.inflight is not None:
            got = self.stage(self.inflight["seq"], self.inflight["action"])
            if got in ("received", "applied"):
                self.inflight = None
            elif got == "lost" or self.clock() - self.inflight["at"] > QUEUE_RESEND_AFTER:
                item = self.inflight
                self.inflight = None
                if item["tries"] < QUEUE_MAX_TRIES:
                    # ★新しい番号で出し直す（⚠ 前の番号は読まれていない = 二重にならない）
                    self.pending.appendleft({"action": item["action"], "params": item["params"],
                                             "tries": item["tries"]})
                else:
                    self.dropped.append(item["action"])
                    self.log("⚠⚠ パッドの頼み %s が届きませんでした（%d 回）"
                             % (item["action"], item["tries"]))
            else:
                return                                       # ★待つ
        if self.pending:
            self._send(self.pending.popleft())


# ----------------------------------------------------------------------
# ★本体（⚠ Qt もスレッドも知らない = 検査で偽の状態を流せる）
# ----------------------------------------------------------------------

def _all_released(state) -> bool:
    """★全部離したか（⚠ ボタン・トリガ・スティック）。"""
    if state is None or not state.connected:
        return True
    return (state.buttons == 0
            and state.left_trigger <= GP.TRIGGER_RELEASE
            and state.right_trigger <= GP.TRIGGER_RELEASE
            and abs(state.thumb_lx) <= GP.THUMB_DEADZONE
            and abs(state.thumb_ly) <= GP.THUMB_DEADZONE)


class PadLogic:
    """★1 回ぶん（約 16 ms）を進める。出すのは画面側でやること（操作名）の並び。

    `mouse_move(dx, dy)` / `mouse_button(edge)` … ⚠ 検査で差し替える
    `in_battle()` … ★戦闘中か（⚠ 画面側が state.json から入れる）
    """

    def __init__(self, settings: PadSettings, writer: PadFileWriter, *,
                 mouse_move=None, mouse_button=None, in_battle=None,
                 clock=time.monotonic) -> None:
        self.settings = settings
        self.writer = writer
        self.router = GP.GamepadRouter()
        self.hold = GP.HoldRouter(settings.force_auto_hold_ms)
        self.r3 = GP.MouseButton()
        self.mouse_move = mouse_move or (lambda dx, dy: None)
        self.mouse_button = mouse_button or (lambda edge: None)
        self.in_battle = in_battle or (lambda: False)
        self.clock = clock
        self.active = False         # ★前回「効く」状態だったか
        self.latched = True         # ⚠ 全部離すまで何もしない（★起動直後・戻った直後・挿し直し）
        self.last_state_op = -1e9   # ★最後にセーブ / ロードを出した時刻
        self._frac = [0.0, 0.0]
        self._b_down = False

    # --- ★解除 ---------------------------------------------------------
    def release(self) -> list[str]:
        """⚠ 全部離す（★ゲーム入力 0・マウスボタン・長押し）。出すのは解除で要る操作。"""
        # ⚠⚠ 順番: RELEASED（★まだ出していない頼みを捨てる）→ END（★開始前へ戻す頼み）。
        #   逆にすると、戻す頼みまで捨ててしまう。
        out: list[str] = [RELEASED]
        self.writer.zero()
        if self.r3.poll(None) == "up":
            self.mouse_button("up")
        out += self.hold.poll(None, False, self.clock())    # ★長押しを解く（END）
        self.router.poll(None)
        self._frac = [0.0, 0.0]
        self._b_down = False
        return out

    # --- ★1 回 ---------------------------------------------------------
    def step(self, state, focused: bool) -> list[str]:
        usable = state is not None and state.connected and focused
        if not usable:
            out: list[str] = []
            if self.active:
                out = self.release()
            else:
                self.writer.put(0)
            self.active = False
            self.latched = True
            return out
        if self.latched:
            # ⚠ 戻った直後は、全部離すまで何もしない（★押したまま戻って暴発しない）
            if not _all_released(state):
                self.writer.put(0)
                return []
            self.latched = False
            self.router.poll(state)                          # ★立ち上がりの基準だけ作る
        self.active = True
        out = []
        # ★ゲーム入力（⚠ 自動中に渡すかは Lua の B.tick が決める）
        mask = GP.nes_mask(state, swap_ab=self.settings.swap_ab)
        self.writer.put(mask)
        # ★B（ゲームの B）を押した瞬間 → 町の自動を止める（依頼者 §3: 取消・停止は受け付ける）
        b_now = bool(mask & GP.NES_B)
        if b_now and not self._b_down:
            out.append(CANCEL)
        self._b_down = b_now
        # ★マウス
        if self.settings.mouse:
            per_tick = self.settings.mouse_speed * TICK_SECONDS
            vx, vy = GP.mouse_velocity(state, max_speed=per_tick)
            if vx == 0.0 and vy == 0.0:
                self._frac = [0.0, 0.0]
            else:
                self._frac[0] += vx
                self._frac[1] += vy
                dx, dy = int(self._frac[0]), int(self._frac[1])
                self._frac[0] -= dx
                self._frac[1] -= dy
                if dx or dy:
                    self.mouse_move(dx, dy)
            edge = self.r3.poll(state)
            if edge is not None:
                self.mouse_button(edge)
        # ★長押し（⚠ 先に見る = 戦闘中の X の短押しを止めるため）
        now = self.clock()
        out += self.hold.poll(state, bool(self.in_battle()), now)
        for name in self.router.poll(state):
            action = DQ3_ACTIONS.get(name)
            if action is None:
                continue
            if action == INN and self.hold.suppress_talk():
                continue                                     # ★戦闘中の X は長押しだけ
            if action in ("load_state", "save_state"):
                if now - self.last_state_op < STATE_COOLDOWN:
                    continue                                 # ⚠ 連打で繰り返さない
                self.last_state_op = now
            out.append(action)
        return out


# ----------------------------------------------------------------------
# ★読み取りスレッド（★DQ2 と同じ約 60 Hz / 画面の操作は主スレッドへ渡す）
# ----------------------------------------------------------------------

class GamepadLink:
    """★スレッドで読み、画面でやることを `events` に積む（⚠ 画面側が主スレッドで取り出す）。"""

    def __init__(self, logic: PadLogic, reader=None, focus: FocusGate | None = None) -> None:
        self.logic = logic
        self.reader = reader if reader is not None else GP.XInputReader()
        self.focus = focus or FocusGate(_default_target_exe, marker=default_lua_marker)
        self.events: collections.deque = collections.deque()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.detected = False
        self.errors = 0

    @property
    def available(self) -> bool:
        return bool(getattr(self.reader, "available", False))

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                state = self.reader.read()
                if state is not None and state.connected:
                    self.detected = True
                for name in self.logic.step(state, self.focus.is_target()):
                    self.events.append(name)
            except Exception:                                # noqa: BLE001 ★1 回の失敗で止めない
                self.errors += 1
            self._stop.wait(max(0.0, TICK_SECONDS - (time.monotonic() - started)))

    def start(self) -> bool:
        if not self.available or self._thread is not None:
            return False
        self._thread = threading.Thread(target=self._loop, name="dq3-gamepad", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """★止めて、全部離す（⚠ 押したまま終わらない / 依頼者 §3）。"""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(0.5)
        try:
            for name in self.logic.release():
                self.events.append(name)
        finally:
            self.logic.writer.close()

    def drain(self) -> list[str]:
        out = []
        while self.events:
            out.append(self.events.popleft())
        return out


__all__ = ["PadSettings", "FocusGate", "PadFileWriter", "CommandQueue", "PadLogic",
           "GamepadLink", "SECTION", "PAD_FILE_NAME", "DQ3_ACTIONS", "INN", "CANCEL",
           "RELEASED", "FORCE_BEGIN", "FORCE_END", "STATE_COOLDOWN", "PAD_STATE_SLOT",
           "command_line_of", "default_lua_marker"]
