"""DQ3 のコントローラー（RX3-0486 / 2026-10-02）。★偽のパッドの状態を流して確かめる。

⚠ 実機のパッドは読みません（★`XInputReader` は使わない / マウスも動かさない）。
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from retroux.application import gamepad as GP     # noqa: E402

from dq3.ui import gamepad_link as GL              # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def pad(buttons=0, lt=0, rt=0, lx=0, ly=0, rx=0, ry=0, connected=True):
    return GP.PadState(connected=connected, buttons=buttons, left_trigger=lt, right_trigger=rt,
                       thumb_lx=lx, thumb_ly=ly, thumb_rx=rx, thumb_ry=ry)


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _logic(tmp_path, battle=False, **settings):
    clock = _Clock()
    moves, clicks = [], []
    state = {"battle": battle}
    logic = GL.PadLogic(GL.PadSettings(**settings), GL.PadFileWriter(tmp_path / GL.PAD_FILE_NAME),
                        mouse_move=lambda dx, dy: moves.append((dx, dy)),
                        mouse_button=clicks.append, in_battle=lambda: state["battle"], clock=clock)
    # ★起動直後は「全部離すまで」待つので、1 回離しておく
    logic.step(pad(), True)
    return logic, clock, moves, clicks, state


def _mask_on_disk(tmp_path) -> int:
    body = (tmp_path / GL.PAD_FILE_NAME).read_bytes()
    return int(body.split()[1])


# ======================================================================
# ★割り当て（依頼者 2026-10-02 §1）
# ======================================================================

@pytest.mark.parametrize("state, want", [
    (pad(lt=200), "auto"),          # ★LT = 戦闘 AI（⚠ キーボードの A・ゲームの A とは別）
    (pad(rt=200), "turbo"),         # ★RT = ターボ
    (pad(GP.BTN_Y), "mantan"),      # ★Y = まんたん
    (pad(GP.BTN_LB), "load_state"),  # ★LB = 読込（ステート 0）
    (pad(GP.BTN_RB), "save_state"),  # ★RB = 保存（ステート 0）
    (pad(GP.BTN_X), GL.INN),        # ★X（短く / 戦闘外）= 宿屋に移動（DQ3-000156）
])
def test_支援操作の割り当て(tmp_path, state, want):
    logic, *_ = _logic(tmp_path)
    assert logic.step(state, True) == [want]
    assert logic.step(state, True) == [], "⚠⚠ 押しっぱなしで 2 回出た（★押した瞬間だけ）"


def test_ゲーム操作はNESのビットで_swap_abが既定(tmp_path):
    logic, *_ = _logic(tmp_path)
    logic.step(pad(GP.BTN_DPAD_UP | GP.BTN_B | GP.BTN_START), True)
    # ★swap_ab（既定）: XBOX の B = ゲームの A
    assert _mask_on_disk(tmp_path) == GP.NES_UP | GP.NES_A | GP.NES_START
    logic2, *_ = _logic(tmp_path / "x", swap_ab=False)
    logic2.step(pad(GP.BTN_B | GP.BTN_BACK), True)
    assert _mask_on_disk(tmp_path / "x") == GP.NES_B | GP.NES_SELECT
    # ★左スティックでも歩ける
    logic.step(pad(lx=-30000), True)
    assert _mask_on_disk(tmp_path) == GP.NES_LEFT


def test_支援操作のボタンはゲームへ渡さない(tmp_path):
    logic, *_ = _logic(tmp_path)
    logic.step(pad(GP.BTN_X | GP.BTN_Y | GP.BTN_LB | GP.BTN_RB, lt=255, rt=255), True)
    assert _mask_on_disk(tmp_path) == 0, "⚠⚠ 支援操作がゲームの入力になった"


def test_ゲームのBを押した瞬間に取り消しを出す(tmp_path):
    logic, *_ = _logic(tmp_path)
    # ★swap_ab: XBOX の A = ゲームの B
    assert logic.step(pad(GP.BTN_A), True) == [GL.CANCEL]
    assert logic.step(pad(GP.BTN_A), True) == []


def test_X長押しは戦闘中だけ_成立したら短押しを出さず_離すと戻す(tmp_path):
    logic, clock, *_rest, state = _logic(tmp_path, battle=True)
    assert logic.step(pad(GP.BTN_X), True) == [], "⚠ 戦闘中の X の短押しで宿屋へ向かった"
    clock.t += 0.6
    assert logic.step(pad(GP.BTN_X), True) == [GL.FORCE_BEGIN]
    clock.t += 0.1
    assert logic.step(pad(), True) == [GL.FORCE_END], "⚠⚠ 離しても戻さない"
    assert GL.INN not in logic.step(pad(), True), "⚠⚠ 長押しが成立したのに離したら短押しが出た"


def test_X長押しの途中で戦闘が終わったら戻す(tmp_path):
    logic, clock, *_rest, state = _logic(tmp_path, battle=True)
    logic.step(pad(GP.BTN_X), True)
    clock.t += 0.6
    assert logic.step(pad(GP.BTN_X), True) == [GL.FORCE_BEGIN]
    state["battle"] = False
    assert logic.step(pad(GP.BTN_X), True) == [GL.FORCE_END]


def test_セーブとロードは続けざまに出さない(tmp_path):
    logic, clock, *_ = _logic(tmp_path)
    assert logic.step(pad(GP.BTN_RB), True) == ["save_state"]
    logic.step(pad(), True)
    clock.t += 0.5
    assert logic.step(pad(GP.BTN_RB), True) == [], "⚠⚠ 連打で 2 回保存した"
    logic.step(pad(), True)
    clock.t += GL.STATE_COOLDOWN
    assert logic.step(pad(GP.BTN_LB), True) == ["load_state"]


def test_右スティックでマウス_R3でクリック(tmp_path):
    logic, _clock, moves, clicks, _ = _logic(tmp_path)
    for _ in range(5):
        logic.step(pad(rx=32767), True)
    assert moves and all(dx > 0 and dy == 0 for dx, dy in moves)
    logic.step(pad(GP.BTN_RIGHT_THUMB), True)
    logic.step(pad(), True)
    assert clicks == ["down", "up"]
    logic3, _c, moves3, clicks3, _ = _logic(tmp_path / "m", mouse=False)
    logic3.step(pad(GP.BTN_RIGHT_THUMB, rx=32767), True)
    assert moves3 == [] and clicks3 == [], "⚠ mouse: false でも動かした"


# ======================================================================
# ★フォーカス・切断・終了（依頼者 2026-10-02 §3）
# ======================================================================

def test_対象外の窓へ移ると全部離し_長押しを解き_列を捨てる合図を先に出す(tmp_path):
    logic, clock, moves, clicks, state = _logic(tmp_path, battle=True)
    logic.step(pad(GP.BTN_X | GP.BTN_DPAD_UP | GP.BTN_RIGHT_THUMB), True)
    clock.t += 0.6
    assert GL.FORCE_BEGIN in logic.step(pad(GP.BTN_X | GP.BTN_DPAD_UP | GP.BTN_RIGHT_THUMB), True)
    assert _mask_on_disk(tmp_path) != 0
    out = logic.step(pad(GP.BTN_X | GP.BTN_DPAD_UP | GP.BTN_RIGHT_THUMB), False)
    # ⚠⚠ RELEASED（列を捨てる）が先、END（戻す頼み）が後
    assert out == [GL.RELEASED, GL.FORCE_END], out
    assert _mask_on_disk(tmp_path) == 0, "⚠⚠ 対象外の窓へ移ってもゲーム入力を送り続けた"
    assert clicks[-1] == "up", "⚠⚠ マウスボタンが刺さったまま"


def test_戻ったとき押したままなら何もしない_離してからまた効く(tmp_path):
    logic, *_ = _logic(tmp_path)
    logic.step(pad(GP.BTN_Y), True)
    logic.step(pad(GP.BTN_Y), False)                       # ★他のアプリへ
    assert logic.step(pad(GP.BTN_Y), True) == [], "⚠⚠ 戻った瞬間にまんたんが出た（暴発）"
    logic.step(pad(GP.BTN_DPAD_UP), True)
    assert _mask_on_disk(tmp_path) == 0, "⚠ 全部離す前にゲーム入力を渡した"
    logic.step(pad(), True)
    assert logic.step(pad(GP.BTN_Y), True) == ["mantan"]


def test_抜くと全部離し_挿し直しても押したままなら何もしない(tmp_path):
    logic, *_ = _logic(tmp_path)
    logic.step(pad(GP.BTN_DPAD_LEFT), True)
    assert logic.step(None, True)[0] == GL.RELEASED
    assert _mask_on_disk(tmp_path) == 0
    assert logic.step(pad(GP.BTN_LB), True) == [], "⚠⚠ 挿し直した瞬間にロードした"


def test_止めると全部離してファイルを閉じる(tmp_path):
    class Reader:
        available = True

        def read(self):
            return pad(GP.BTN_DPAD_DOWN)

    class Focus:
        def is_target(self):
            return True

    logic, *_ = _logic(tmp_path)
    link = GL.GamepadLink(logic, reader=Reader(), focus=Focus())
    assert link.start()
    import time

    time.sleep(0.1)
    link.stop()
    assert _mask_on_disk(tmp_path) == 0, "⚠⚠ 押したまま終わった"
    assert GL.RELEASED in link.drain()
    assert logic.writer._fh is None


def test_フォーカスはDQ3のFCEUXかこのRetroUXだけ(tmp_path):
    exe = tmp_path / "fceux" / "fceux64.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    other = tmp_path / "dq2" / "fceux64.exe"
    procs = {10: str(exe), 20: str(other), 30: r"C:\Windows\explorer.exe"}
    now = {"pid": 10}
    gate = GL.FocusGate(lambda: exe, own_pid=99, foreground=lambda: now["pid"],
                        exe_of=lambda pid: procs.get(pid))
    assert gate.is_target() is True
    now["pid"] = 20
    assert gate.is_target() is False, "⚠⚠ DQ2 の FCEUX（別の exe）にも効いた"
    now["pid"] = 30
    assert gate.is_target() is False
    now["pid"] = 99
    assert gate.is_target() is True, "★RetroUX DQ3 自身の窓"
    now["pid"] = None
    assert gate.is_target() is False


def test_同じexeから起こした別のFCEUXはコマンドラインで外す(tmp_path):
    """★依頼者 2026-10-02（DQ3-000156）: 実行ファイルのパスだけで別の FCEUX と混同しない。"""
    exe = tmp_path / "fceux64.exe"
    exe.write_bytes(b"")
    marker = r"D:\RX-B\RetroUX-DQ3-1.1.0\dq3\phase0\dev.lua"
    lines = {10: '"%s" -lua "D:/RX-B/RetroUX-DQ3-1.1.0/dq3/phase0/dev.lua" "rom.nes"' % exe,
             20: '"%s" -lua "D:\\DQ2\\retroux\\emulator\\fceux\\bridge.lua" "dq2.nes"' % exe,
             30: None}
    now = {"pid": 10}
    gate = GL.FocusGate(lambda: exe, own_pid=99, foreground=lambda: now["pid"],
                        exe_of=lambda pid: str(exe), marker=lambda: marker,
                        cmdline_of=lambda pid: lines.get(pid))
    assert gate.is_target() is True, "★DQ3 の dev.lua で起こした FCEUX（★/ と \\ の違いも同じとみなす）"
    now["pid"] = 20
    assert gate.is_target() is False, "⚠⚠ 同じ exe の DQ2 の FCEUX にも効いた"
    now["pid"] = 30
    assert gate.is_target() is True and gate.unverified == 1, "⚠ 読めないときは exe で決めて数える"


def test_コマンドラインを実際に読める():
    """★`NtQueryInformationProcess` で自分自身のコマンドラインが読める（★Windows だけ）。"""
    if os.name != "nt":
        pytest.skip("Windows だけ")
    got = GL.command_line_of(os.getpid())
    assert got and "python" in got.lower()
    assert GL.command_line_of(0x7FFFFFF0) is None


# ======================================================================
# ★入力ファイル（★DQ2 と同じ形）
# ======================================================================

def test_入力ファイルはDQ2と同じ形で開いたまま上書きする(tmp_path):
    w = GL.PadFileWriter(tmp_path / "pad.txt")
    w.put(GP.NES_A)
    body = (tmp_path / "pad.txt").read_bytes()
    assert body == b"1 16".ljust(23) + b"\n" and len(body) == 24
    w.put(GP.NES_A)
    assert (tmp_path / "pad.txt").read_bytes().startswith(b"2 16"), "⚠ 押している間は毎回書く（★生きている印）"
    w.put(0)
    for _ in range(GL.IDLE_HEARTBEAT - 2):
        w.put(0)
    assert w.writes == 3, "⚠ 何も押していない間に毎回書いた（★音の途切れ / RX-0083）"
    w.zero()
    assert int((tmp_path / "pad.txt").read_bytes().split()[1]) == 0
    w.close()


def test_入力ファイルは引き継がない生成物(tmp_path):
    from dq3 import ownership as OW

    got = [o for o in OW.DERIVED if o.rel == "work/dq3-gamepad.txt"]
    assert got and got[0].kind == OW.KIND_DERIVED, "⚠⚠ ownership に無い（★分類外になる / 引き継がれる）"


# ======================================================================
# ★設定（★DQ3 だけ / ⚠ DQ2 の user_config.yaml の gamepad: とは別）
# ======================================================================

class _Settings:
    def __init__(self, body=None):
        self.body = body or {}

    def get(self, section, key, default=None):
        return self.body.get(section, {}).get(key, default)


def test_設定の既定と読み方():
    got = GL.PadSettings.from_settings(None)
    assert (got.enabled, got.swap_ab, got.mouse) == (True, True, True)
    got = GL.PadSettings.from_settings(_Settings({"gamepad": {"state_slot": 3, "enabled": False}}))
    assert got.enabled is False
    assert not hasattr(got, "state_slot"), "⚠⚠ 設定の番号を読んでいる（★LB / RB はステート 0 固定）"
    assert GL.PAD_STATE_SLOT == 0
    got = GL.PadSettings.from_settings(_Settings({"gamepad": {"mouse_speed": "速い"}}))
    assert got.mouse_speed == 900.0, "⚠ 読めない値で落ちた"
    assert GL.SECTION == "gamepad"


# ======================================================================
# ★頼みの列（依頼者 §5: 取消・停止を先に / 古い頼みを後で出さない）
# ======================================================================

class _Writer:
    def __init__(self):
        self.seq = 0
        self.sent = []

    def send(self, action, **params):
        self.seq += 1
        self.sent.append((self.seq, action, params))
        return self.seq


def test_列は前の頼みが届いてから次を出す():
    writer, stages = _Writer(), {}
    clock = _Clock()
    q = GL.CommandQueue(writer, lambda seq, action: stages.get(seq, "unsent"), clock=clock)
    q.push("auto")
    q.push("turbo")
    q.tick()
    q.tick()
    assert [a for _s, a, _p in writer.sent] == ["auto"], "⚠⚠ 置き場 1 つなのに続けて書いた（★前が消える）"
    stages[1] = "received"
    q.tick()
    assert [a for _s, a, _p in writer.sent] == ["auto", "turbo"]


def test_止める頼みは先に_同じ頼みは積み増さない_捨てられる():
    writer, clock = _Writer(), _Clock()
    q = GL.CommandQueue(writer, lambda seq, action: "unsent", clock=clock)
    q.push("mantan")
    q.push("mantan")
    q.push("nav_stop")
    assert [p["action"] for p in q.pending] == ["nav_stop", "mantan"]
    q.clear("検査")
    q.tick()
    assert writer.sent == [], "⚠⚠ 捨てたはずの頼みを出した"


def test_追い越されたら新しい番号で出し直し_上限で諦める():
    writer, clock = _Writer(), _Clock()
    q = GL.CommandQueue(writer, lambda seq, action: "lost", clock=clock)
    q.push("save_state", slot=1)
    for _ in range(10):
        q.tick()
    assert len(writer.sent) == GL.QUEUE_MAX_TRIES and q.dropped == ["save_state"]
    assert writer.sent[0][2] == {"slot": "1"}


def test_届かなければ時間で出し直す():
    writer, clock = _Writer(), _Clock()
    q = GL.CommandQueue(writer, lambda seq, action: "unsent", clock=clock)
    q.push("auto")
    q.tick()
    clock.t += GL.QUEUE_RESEND_AFTER + 0.1
    q.tick()
    q.tick()
    assert len(writer.sent) == 2


# ======================================================================
# ★配線（⚠ 作っても呼ばれていなければ効かない）
# ======================================================================

def test_本物の起動だけがパッドを始める_窓を作っただけでは始めない():
    app = (ROOT / "dq3" / "ui" / "app.py").read_text(encoding="utf-8")
    assert "window.start_gamepad()" in app
    tree = ast.parse((ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8"))
    init = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assert "start_gamepad" not in ast.unparse(init), "⚠⚠ 検査で窓を作るたびに実機のパッドを読む"


def test_閉じるときにパッドを止める():
    tree = ast.parse((ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8"))
    close = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "closeEvent")
    assert "stop_gamepad" in ast.unparse(close)


def test_保存の頼みはLuaが受け取る():
    from dq3.ui.commands import ACTIONS

    assert "save_state" in ACTIONS and "load_state" in ACTIONS
    dev = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert 'HOST.wants("save_state")' in dev and "dq3-gamepad.txt" in dev
    assert "HOST.buttons.pad = pad_reader.tick" in dev
    nav = (ROOT / "dq3" / "phase0" / "nav_v0.lua").read_text(encoding="utf-8")
    assert 'HOST.wants("load_state")' in nav, "⚠ LB の読込は既存の入口（nav_v0）を使う"


def test_共通部品の操作名をDQ3が自分で結ぶ_DQ2の割り当ては共通部品に無い():
    """★X を宿屋にしても DQ2 の X（店・くじ）が変わらないこと（依頼者 §2）。"""
    assert GL.DQ3_ACTIONS[GP.EVENT_TALK] == GL.INN
    tree = ast.parse((ROOT / "retroux" / "application" / "gamepad.py").read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    for text in literals:
        assert "/" not in text and ".txt" not in text, "⚠ 共通部品にパスが入っている: %r" % text
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert all("retroux" not in (getattr(n, "module", "") or "") for n in imports), \
        "⚠ 共通部品が DQ2 の他の部品を読み込んでいる"


# ======================================================================
# ★画面側の操作（主スレッド）
# ======================================================================

class _Bar:
    def __init__(self, mode=None, enabled=True, busy=False):
        class Ctl:
            pass

        self.ctl = Ctl()
        self.ctl.mode = mode
        self.ctl.busy = lambda: busy
        self.stopped = 0
        self.ctl.stop = lambda: setattr(self, "stopped", self.stopped + 1)
        self.moved = []

        class Button:
            def isEnabled(self_inner):
                return enabled

        # ★［宿］ボタン（★押せるかは town_bar.refresh が決める = 面識のある宿屋・動作中でない）
        self.move_buttons = {"inn": Button()}

    def _on_move(self, role):
        self.moved.append(role)

    def refresh(self):
        pass


def _window(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from dq3.ui.main_window import Dq3MainWindow
    from dq3.ui.view_model import Dq3ViewModel

    QApplication.instance() or QApplication([])
    win = Dq3MainWindow(Dq3ViewModel(state_path=tmp_path / "state.json"),
                        command_path=tmp_path / "cmd.json", show_map=False, show_battle=False)
    # ⚠ 古い設定に番号が残っていても読まない（★LB / RB はステート 0 固定）
    win.settings = _Settings({"gamepad": {"state_slot": 2}})
    win.pad_queue = GL.CommandQueue(_Writer(), lambda s, a: "unsent", on_sent=win._pad_sent)
    win._pad_force = win._pad_restore = win._pad_wait = None
    return win


def test_画面側_X短押しは宿ボタンと同じ入口_戦闘中と押せないときは動かない(tmp_path):
    win = _window(tmp_path)
    win.town_bar = _Bar()
    win._on_pad(GL.INN, {"in_battle": False})
    assert win.town_bar.moved == ["inn"], "★［宿］ボタンと同じ `_on_move('inn')`"
    win._on_pad(GL.INN, {"in_battle": True})
    assert win.town_bar.moved == ["inn"], "⚠⚠ 戦闘中に宿屋へ向かった"
    win.town_bar = _Bar(enabled=False)                     # ★知らない宿屋 / 町の外 / 聞き込み中
    win._on_pad(GL.INN, {"in_battle": False})
    assert win.town_bar.moved == [], "⚠⚠ ［宿］が押せないのに移動を始めた"
    assert "宿屋へ移動できません" in win._status.text()
    win.close()


def test_画面側_LBRBはステート0固定_LBは街の自動を止めてから_Bは止める(tmp_path):
    win = _window(tmp_path)
    win.town_bar = _Bar(mode="hearing", busy=True)
    win._on_pad("load_state", {})
    assert win.town_bar.stopped == 1
    assert [(p["action"], p["params"]) for p in win.pad_queue.pending] == [("load_state", {"slot": "0"})]
    win._on_pad(GL.CANCEL, {})
    assert win.town_bar.stopped == 2
    win._on_pad("save_state", {})
    assert win.pad_queue.pending[-1] == {"action": "save_state", "params": {"slot": "0"}}
    win.close()


def test_画面側_ステート0の結果は実際の結果を出し_頼んだだけでは成功と言わない(tmp_path):
    win = _window(tmp_path)
    win._on_pad("save_state", {})
    assert "結果待ち" in win._status.text() and "しました" not in win._status.text()
    win.pad_queue.tick()                                   # ★番号が付く（_pad_sent）
    seq = win._pad_wait["seq"]
    win._pad_result({"pad": {"saved": {"seq": seq - 1, "ok": True}}})
    assert "結果待ち" in win._status.text(), "⚠⚠ 前の番号の結果で成功と言った"
    win._pad_result({"pad": {"saved": {"seq": seq, "ok": True, "slot": 0}}})
    assert win._status.text() == "★RB: ステート 0 に保存しました"
    # ★読込の失敗
    win._on_pad("load_state", {})
    win.pad_queue.inflight = None
    win.pad_queue.tick()
    seq = win._pad_wait["seq"]
    win._pad_result({"nav": {"loaded": {"seq": seq, "ok": False, "why": "⚠ 読み込みに失敗: x"}}})
    assert "ステート 0 の読込に失敗しました" in win._status.text()
    # ⚠ 結果が来ない
    win._on_pad("save_state", {})
    win._pad_wait["at"] -= 11.0
    win._pad_result({})
    assert "確かめられませんでした" in win._status.text()
    win.close()


def test_管理画面にパッドの枠は無い_古い番号は消さない(tmp_path):
    pytest.importorskip("PySide6")
    import json

    import test_dq3_admin_window as T

    (tmp_path / "ui.json").write_text(json.dumps({"gamepad": {"state_slot": 4}}), encoding="utf-8")
    w, *_ = T._window(tmp_path)
    assert not hasattr(w, "sp_pad_slot"), "⚠ 番号を選ぶ欄が残っている"
    body = json.loads((tmp_path / "ui.json").read_text(encoding="utf-8"))
    assert body["gamepad"]["state_slot"] == 4, "⚠ 設定を初期化した"


def test_画面側_強制オートは開始前へ揃える_元から入っていたものは触らない(tmp_path):
    win = _window(tmp_path)
    # ★オートは元から入っていた / ターボ（人のもの）は入っていない（⚠ 戦闘の自動の高速化 wanted は数えない）
    before = {"auto_enabled": True, "turbo_enabled": True, "turbo_manual": False}
    win._on_pad(GL.FORCE_BEGIN, before)
    assert [p["action"] for p in win.pad_queue.pending] == ["turbo"], "⚠ もう入っていたオートを反転した"
    win.pad_queue.tick()                                   # ★ターボの頼みを出した
    win._on_pad(GL.FORCE_END, {"auto_enabled": True, "turbo_manual": True})
    assert win._pad_restore == {"turbo": False, "since": win._pad_restore["since"],
                                "last": win._pad_restore["last"]}
    win.pad_queue.inflight = None
    # ⚠ state.json がまだ追いついていない（★ターボが入っていないように見える）→ 何もしないが見張りは続ける
    win._pad_reconcile({"auto_enabled": True, "turbo_manual": False})
    assert not win.pad_queue.pending and win._pad_restore is not None
    # ★入ったのが映った → 戻す（⚠ オートは触らない）
    win._pad_reconcile({"auto_enabled": True, "turbo_manual": True})
    assert [p["action"] for p in win.pad_queue.pending] == ["turbo"]
    win.close()


def test_画面側_離す前に出していなかった頼みは取り消す(tmp_path):
    win = _window(tmp_path)
    win._on_pad(GL.FORCE_BEGIN, {"auto_enabled": False, "turbo_manual": False})
    assert [p["action"] for p in win.pad_queue.pending] == ["auto", "turbo"]
    win._on_pad(GL.FORCE_END, {"auto_enabled": False, "turbo_manual": False})
    assert not win.pad_queue.pending, "⚠ 出していない「入れる」頼みを後で出す"
    win._on_pad(GL.RELEASED, {})
    win.close()


def test_画面側_通常終了でも強制オートを開始前へ戻す(tmp_path):
    win = _window(tmp_path)
    sent, waited = [], []

    class Link:
        def stop(self):
            pass

        def drain(self):
            return []

    class Commands:
        def send(self, action):
            sent.append(action)
            return len(sent)

    class Waiter:
        def wait(self, seq, action, **kw):
            waited.append((seq, action, kw.get("want")))

    win.gamepad = Link()
    win.commands = Commands()
    win._pad_waiter = Waiter()
    win._pad_force = {"auto": True, "turbo": True, "before": {"auto": False, "turbo": False}}
    win.vm._raw = lambda: {"auto_enabled": True, "turbo_manual": True}
    win.stop_gamepad()
    assert sent == ["auto", "turbo"], "⚠⚠ 終わるときに入れたまま残した"
    assert all(w[2] == "received" for w in waited), "★届くまで少し待つ（置き場は 1 つ）"
    win.close()
