"""閉じた経路をログに残す（RX-0077 / 2026-08-19）。

★★ **「急に終了した」を後から追えるようにする。** ★★
  2026-08-19 の 18:30 の終了を調べたとき、INFO ログに経路が残っておらず、
  「終了ボタンか、×/Alt+F4 か」を痕跡から推測するしかなかった。1行あれば即断できる。

⚠ closeEvent 全体は teardown で実 work/ を触る（.stop 書き込み等）。ここは
  **ログ判定だけ**を取り出した `_log_close_reason` を直に見る（副作用なし）。
"""

from __future__ import annotations

import logging
import pathlib
import tempfile

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module", autouse=True)
def _app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder
    from retroux.ui.main_window import MainWindow
    from retroux.ui.view_model import ViewModel

    tmp = pathlib.Path(tempfile.mkdtemp())
    db = Database(tmp / "t.sqlite3")
    db.register_rom("H", "テストROM", "JP", mapper=2)
    (tmp / "events.jsonl").write_text("", encoding="utf-8")
    rec = Recorder(db, "H", tmp / "events.jsonl", tmp / "command.json")
    vm = ViewModel(rec, db, "H", {1: "スライム"})
    vm._mission_path = tmp / "mission.yaml"
    return MainWindow(vm, interval_ms=10 ** 6, log_path=tmp / "r.log")


class _Capture(logging.Handler):
    """`retroux.*` の記録を集める（★propagate=False なので自前で捕まえる）。"""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def capture():
    logger = logging.getLogger("retroux")
    handler = _Capture()
    handler.setLevel(logging.INFO)
    # ★テストでは logging 未設定のことがあり、既定 WARNING だと INFO が落ちる。
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)


def test_the_exit_button_path_is_logged(window, capture):
    """★終了ボタン経由（_shutdown が印を立てる）。"""
    window._closing_via_exit_button = True
    window._log_close_reason()
    assert any("終了ボタンから閉じました" in m for m in capture.messages)


def test_an_external_close_is_logged_as_such(window, capture):
    """★★ 印が無い＝×/Alt+F4/セッション終了。★これが今回の 18:30 の正体。"""
    # ★既定（印を立てていない）状態
    window._log_close_reason()
    joined = "\n".join(capture.messages)
    assert "外部から閉じられました" in joined
    assert "終了ボタンを経由していません" in joined
    # ⚠ 終了ボタンの文言は出ない（取り違えないこと）
    assert "終了ボタンから閉じました" not in joined
