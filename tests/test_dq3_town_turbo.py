"""聞き込み・街移動の Turbo と右画面（RX3-0170 / 2026-09-11 依頼者「聞き込み・街移動 Auto Turbo化」）。

## ★ここで守るもの

```text
倍率の送り直し   Lua が normal を送るたび（speed_normal_count が増えるたび）に人の倍率を送り直す
                 ⚠ 0.5 秒ごとの「ターボ ON → OFF」だけ見ると、NPC の間の短い Turbo を見逃す
中断             右画面が前にあるときは D / B で止める（★ゲームの B と同じキー / 新しいキーは増やさない）
閉じる           途中で右画面を閉じたら止める（⚠ Turbo・無音のまま FCEUX を残さない）
設定             管理画面があればそのチェック、無ければ保存値（★既定 ON）
戦闘の「タ」      ⚠ 街の Turbo では緑にしない（★state の turbo_enabled に街の Turbo を入れない）
```
"""
from __future__ import annotations

import os
import pathlib
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Speed:
    def __init__(self):
        self.sent = 0

    def reassert(self):
        self.sent += 1
        return True


def _bare_window():
    from PySide6.QtWidgets import QApplication, QWidget

    from dq3.ui.main_window import Dq3MainWindow

    QApplication.instance() or QApplication([])
    win = Dq3MainWindow.__new__(Dq3MainWindow)
    QWidget.__init__(win)
    win.speed = _Speed()
    return win


# ----------------------------------------------------------------------
# ★倍率の送り直し
# ----------------------------------------------------------------------
def test_normalの回数が増えるたびに倍率を送り直す():
    win = _bare_window()
    assert win._note_turbo(False, 5) is False          # ★最初（前が分からない）
    assert win._note_turbo(False, 6) is True           # ★Lua が normal を送った（⚠ turbo は False のまま見えた）
    assert win._note_turbo(False, 6) is False          # ⚠ 同じ回数なら送らない
    assert win._note_turbo(True, 6) is False
    assert win._note_turbo(False, 7) is True
    assert win.speed.sent == 2


def test_回数が来ていればターボの切れ目では二重に送らない():
    win = _bare_window()
    win._note_turbo(True, 1)
    assert win._note_turbo(False, 1) is False, "⚠ 回数が増えていないのに送った（★normal を送っていない）"
    assert win.speed.sent == 0


def test_Luaを読み直して回数が戻っても送らない():
    win = _bare_window()
    win._note_turbo(False, 9)
    assert win._note_turbo(False, 1) is False
    assert win._note_turbo(False, 2) is True


# ----------------------------------------------------------------------
# ★中断（D / B）と、閉じたときの停止
# ----------------------------------------------------------------------
class _Ctl:
    def __init__(self, busy=True):
        self._busy = busy
        self.stopped = 0

    def busy(self):
        return self._busy

    def stop(self):
        self.stopped += 1
        self._busy = False


class _Bar:
    def __init__(self, ctl):
        self.ctl = ctl
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


def _key(key):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


def test_動いている間はDとBで止める():
    from PySide6.QtCore import Qt

    for key in (Qt.Key.Key_D, Qt.Key.Key_B):
        win = _bare_window()
        win.town_bar = _Bar(_Ctl(busy=True))
        win.keyPressEvent(_key(key))
        assert win.town_bar.ctl.stopped == 1, key
        assert win.town_bar.refreshed == 1


def test_動いていなければDでもBでも何もしない():
    from PySide6.QtCore import Qt

    win = _bare_window()
    win.town_bar = _Bar(_Ctl(busy=False))
    win.keyPressEvent(_key(Qt.Key.Key_D))
    assert win.town_bar.ctl.stopped == 0


def test_ほかのキーでは止めない():
    from PySide6.QtCore import Qt

    win = _bare_window()
    win.town_bar = _Bar(_Ctl(busy=True))
    for key in (Qt.Key.Key_A, Qt.Key.Key_T, Qt.Key.Key_F, Qt.Key.Key_M):
        win.keyPressEvent(_key(key))
    assert win.town_bar.ctl.stopped == 0, "⚠⚠ A / T / F / M で街の作業を止めた（★既存のキー）"


def test_途中で閉じたら止める():
    class _W:
        def close(self):
            pass

    win = _bare_window()
    win.town_bar = _Bar(_Ctl(busy=True))
    win.map_window = win.battle_window = _W()
    win.speed = None
    win.close()
    assert win.town_bar.ctl.stopped == 1, "⚠⚠ Turbo・無音のまま FCEUX を残す"


# ----------------------------------------------------------------------
# ★設定の読み方（⚠ RX3-0259 で「高速実行」のチェックを外した → いつも高速）
# ----------------------------------------------------------------------
def test_高速実行を切る口は無い():
    """★RX3-0259: メインウィンドウは「高速実行するか」を管理画面にも保存値にも聞かない（⚠ 残っていると切れたままの人が出る）。"""
    from dq3.ui.main_window import Dq3MainWindow

    assert not hasattr(Dq3MainWindow, "_auto_env_enabled"), "⚠ 外した設定の読み口が残っている"


def test_メインウィンドウは高速実行を切る口を渡さない(monkeypatch):
    """★RX3-0259: 聞き込み・街移動・補充はいつも高速（⚠ `enabled` を渡すと、保存に false が残っている人は切れたまま）。

    ★実際に `_build_town_bar` を呼ぶ（⚠ FCEUX・ROM・設定ファイルに触る部品は偽物に差し替える）。
    """
    from dq3.knowledge import town_service
    from dq3.ui import auto_env, emu_speed, game_focus, mute, town_bar, ui_settings
    from dq3.ui.main_window import Dq3MainWindow

    got = {}

    class _Env:
        def __init__(self, *args, **kwargs):
            got.update(kwargs)

    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(auto_env, "AutoOperationEnvironment", _Env)
    for mod, name in ((emu_speed, "EmulatorSpeedController"), (game_focus, "GameFocus"), (mute, "MuteController"),
                      (town_service, "TownService"), (town_bar, "TownBar"), (ui_settings, "UiSettings")):
        monkeypatch.setattr(mod, name, _Dummy)
    win = _bare_window()
    win.vm, win.commands = object(), object()
    Dq3MainWindow._build_town_bar(win)
    assert isinstance(win.auto_env, _Env), "⚠ 自動操作の環境を作っていない"
    assert got.get("enabled") is None, "⚠⚠ 高速実行を切る口（enabled）を渡している: %r" % got.get("enabled")


# ----------------------------------------------------------------------
# ★戦闘の「タ」と混ぜない / ログの置き場
# ----------------------------------------------------------------------
def test_戦闘のturbo_enabledに街のTurboを入れない():
    """⚠ 依頼者 §3: 右画面の「タ」は Auto 中の戦闘の速さ。★街の Turbo は別の欄（town_speed）で渡す。"""
    text = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    got = re.search(r"turbo_enabled = (.+)", text)
    assert got is not None
    assert got.group(1).strip().rstrip(",") == "HOST.speed.manual or HOST.speed.wanted", got.group(1)
    assert "town_speed = town_speed.status()" in text
    assert "speed_normal_count = HOST.speed.normal_count" in text


def test_ログは作業場のdq3_probeに書く(tmp_path, monkeypatch):
    from dq3.ui import auto_env as AE

    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    AE.town_speed_log("[HEARING] START")
    AE.town_speed_log("[SPEED] NORMAL -> TURBO source=HEARING")
    got = (tmp_path / "work" / "dq3-probe" / AE.LOG_NAME).read_text(encoding="utf-8").splitlines()
    assert [line.split(" ", 1)[1] for line in got] == ["[HEARING] START",
                                                     "[SPEED] NORMAL -> TURBO source=HEARING"]


# ----------------------------------------------------------------------
# ★Turbo 中は state.json を読めない瞬間がある（★Lua は消してから置き換える）
# ----------------------------------------------------------------------
def test_state_jsonが一瞬無くても前回の値を返す(tmp_path):
    """⚠⚠ 実機（2026-09-11 / 全区間 Turbo）: 読めない瞬間に {} を返し、聞き込みが「場所が読めません」で止まった。"""
    import json

    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(json.dumps({"frame": 10, "loc_kind": 1, "map_id": 9, "map_x": 3, "map_y": 4}),
                     encoding="utf-8")
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                      memo_path=tmp_path / "m.jsonl", seen_path=tmp_path / "seen.json")
    assert vm._raw()["frame"] == 10
    state.unlink()                                    # ★Lua が消した瞬間
    assert vm._raw()["frame"] == 10, "⚠⚠ 読めない瞬間に空を返した"
    assert vm.position() == (1, 9, 3, 4)
    state.write_text("{", encoding="utf-8")           # ★書きかけ
    assert vm._raw()["frame"] == 10
    state.write_text(json.dumps({"frame": 11}), encoding="utf-8")
    assert vm._raw()["frame"] == 11, "★読めたら新しい値"


def test_一度も読めていなければ空を返す(tmp_path):
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel(state_path=tmp_path / "none.json", knowledge_path=tmp_path / "k.json",
                      memo_path=tmp_path / "m.jsonl", seen_path=tmp_path / "seen.json")
    assert vm._raw() == {}
