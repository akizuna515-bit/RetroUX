"""★終了したときの窓の位置を覚え、次の起動でその位置から始める（RX3-0200 / 2026-09-12）。

依頼者「終了した時、ウィンドウ位置を保存して再開時にその位置で始めてほしい ※今は毎回整列ボタンを押下している」。

★DQ2 の `WindowState`（`retroux/ui/window_state.py`）を使う。⚠ DQ2 の記録とは別のファイル。
★FCEUX は別プロセスなので、位置（論理）だけ覚えて `move_emulator` で戻す（⚠ 大きさは変えない）。
"""
from __future__ import annotations

import inspect
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QWidget          # noqa: E402

from dq3.ui import main_window as MW                         # noqa: E402
from retroux.core.window_align import WindowInfo             # noqa: E402
from retroux.ui.window_state import WindowState              # noqa: E402

FCEUX = [WindowInfo(handle=1, title="FCEUX 2.6.6: DQ3_J", x=300, y=50, width=512, height=480)]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Holder(QWidget):
    """★本物の右画面の「位置を覚える」部分だけを借りる入れ物（⚠ 画面全部は作らない）。"""

    _windows_to_remember = MW.Dq3MainWindow._windows_to_remember
    restore_window_positions = MW.Dq3MainWindow.restore_window_positions
    save_window_positions = MW.Dq3MainWindow.save_window_positions
    _remember_emulator = MW.Dq3MainWindow._remember_emulator
    restore_emulator_position = MW.Dq3MainWindow.restore_emulator_position

    def __init__(self):
        super().__init__()
        self.map_window = QWidget()
        self.battle_window = QWidget()
        self.moved = []

    def move_emulator(self, box):
        self.moved.append(box)
        return True


def _rects(holder) -> dict:
    return {k: w.geometry().getRect() for k, w in holder._windows_to_remember().items()}


def _placed(path, monkeypatch, fceux=()) -> Holder:
    """★人が窓を置いた状態（⚠ offscreen の画面は 800x600 なので、その中に置く）。"""
    monkeypatch.setattr(MW.window_align, "find_windows", lambda *a, **k: list(fceux))
    h = Holder()
    h.restore_window_positions(WindowState(path))
    for w in (h, h.map_window, h.battle_window):
        w.show()
    h.setGeometry(520, 20, 260, 500)
    h.map_window.setGeometry(10, 20, 400, 300)
    h.battle_window.setGeometry(10, 340, 760, 226)
    QApplication.processEvents()
    return h


def test_閉じて開き直すと同じ位置に出る(app, tmp_path, monkeypatch):
    path = tmp_path / "dq3-window-state.json"
    h = _placed(path, monkeypatch)
    want = _rects(h)
    assert h.save_window_positions() and path.exists(), "⚠ 位置を書けていない"
    again = Holder()
    got = again.restore_window_positions(WindowState(path))
    assert sorted(got) == sorted(want), "⚠ 戻せなかった窓がある: %s" % got
    assert _rects(again) == want, "⚠⚠ 開き直した位置が違う（★毎回整列を押すことになる）"


def test_記録が無ければ動かさない(app, tmp_path):
    h = Holder()
    before = _rects(h)
    assert h.restore_window_positions(WindowState(tmp_path / "none.json")) == []
    assert _rects(h) == before, "⚠ 記録が無いのに窓を動かした"


def test_FCEUXの位置も覚えて戻す(app, tmp_path, monkeypatch):
    path = tmp_path / "dq3-window-state.json"
    h = _placed(path, monkeypatch, FCEUX)
    assert h.save_window_positions()
    again = Holder()
    again.restore_window_positions(WindowState(path))
    assert again.restore_emulator_position() is True, "⚠ FCEUX を前回の位置へ戻していない"
    box = again.moved[-1]
    assert (box.x, box.y) == (300, 50), "⚠ FCEUX の位置が違う: %s" % (box,)
    assert again.restore_emulator_position() is False, "⚠⚠ 戻した後にもう一度動かした（★人が動かした位置を上書きする）"


def test_FCEUXの窓が出るまで待つ(app, tmp_path, monkeypatch):
    path = tmp_path / "dq3-window-state.json"
    h = _placed(path, monkeypatch, FCEUX)
    assert h.save_window_positions()
    again = Holder()
    again.restore_window_positions(WindowState(path))
    monkeypatch.setattr(MW.window_align, "find_windows", lambda *a, **k: [])
    assert again.restore_emulator_position() is False and again.moved == [], "⚠ 窓が無いのに動かそうとした"
    monkeypatch.setattr(MW.window_align, "find_windows", lambda *a, **k: list(FCEUX))
    assert again.restore_emulator_position() is True, "⚠ 窓が出た後の合図で戻していない"


def test_FCEUXが閉じた後でも前に覚えた位置を残す(app, tmp_path, monkeypatch):
    """★終了ボタンは FCEUX を閉じる前に覚え、⚠ そのあと閉じる窓の処理でもう一度書く。"""
    path = tmp_path / "dq3-window-state.json"
    h = _placed(path, monkeypatch, FCEUX)
    assert h.save_window_positions()
    monkeypatch.setattr(MW.window_align, "find_windows", lambda *a, **k: [])
    assert h.save_window_positions()
    assert WindowState(path).get(MW.WINDOW_KEYS["fceux"]).get("x") == 300, "⚠⚠ 閉じた後の書き直しで FCEUX の位置を消した"


def test_検査の入れ物では書かない():
    class Bare:
        save_window_positions = MW.Dq3MainWindow.save_window_positions

    assert Bare().save_window_positions() is False


def test_DQ2の記録とは分け検査は本物を使わない():
    assert all(k.startswith("dq3_") for k in MW.WINDOW_KEYS.values()), "⚠ DQ2 の鍵と混ざる"
    assert MW.WINDOW_STATE_PATH.name == "dq3-window-state.json"
    assert MW.WINDOW_STATE_PATH != MW.paths.work("dq3-window-state.json"), (
        "⚠⚠ 検査が本物の記録を読み書きする（★conftest の仕掛けが外れた）")


def test_起動で戻し閉じるときと終了ボタンで覚える():
    init = inspect.getsource(MW.Dq3MainWindow.__init__)
    assert "self.restore_window_positions()" in init and "self.restore_emulator_position" in init
    close = inspect.getsource(MW.Dq3MainWindow.closeEvent)
    assert close.index("self.save_window_positions()") < close.index("self.map_window.close()"), (
        "⚠ 別窓を閉じた後に覚えている（★閉じた窓は見えないので覚えない）")
    quit_src = inspect.getsource(MW.Dq3MainWindow.quit_all)
    assert quit_src.index("self.save_window_positions()") < quit_src.index("window_align.close_window"), (
        "⚠ FCEUX を閉じた後に覚えている（★測れない）")
