"""現在地の追従とメイン画面との連携。

★2026-08-01 に `test_map_trail.py`（788 実質行）から切り出しました（指示書 §11.3）。
  ⚠ **内容は1件も減らしていません。**機械で切り、件数で確かめています。
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest
import yaml

# ★既定の倍率は**定数から読む**（数字を写さない / 2026-08-01）
from retroux.ui.map.canvas import TrailView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.bridge.state_reader import GameState, _parse  # noqa: E402
from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.ui.main_window import MainWindow  # noqa: E402
from retroux.ui.map_window import MapWindow, load_map_meta  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402

MAP_PATH = (pathlib.Path(__file__).resolve().parents[1]
            / "retroux" / "plugins" / "dq2" / "memory_map.yaml")


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        yield QApplication([])
    except Exception as exc:                          # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")


@pytest.fixture(scope="module")
def mm() -> dict:
    from conftest import load_memory_map_with_enemies  # ★敵の表は ROM 由来（RX-0090）
    return load_memory_map_with_enemies()


META = {
    0x07: {"map_id": 7, "type": "town", "width": 23, "height": 23,
           "border_tile": 1, "palette": 13, "data_pointer": "0x8E83"},
    0x59: {"map_id": 0x59, "type": "dungeon_b", "width": 11, "height": 11,
           "border_tile": 0x24, "palette": 0x5B, "data_pointer": "0xA48B"},
}


@pytest.fixture
def vm(tmp_path, mm):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    view_model = ViewModel(
        Recorder(db, "HASH", events, tmp_path / "command.json"), db, "HASH",
        monsters={int(k): str(v) for k, v in mm["monsters"].items()},
        monster_stats={int(k): v for k, v in mm["monster_stats"].items()},
        map_meta=META,
        view_radius=0,          # ★既定のテストは1マスだけ（範囲は別に試す）
    )
    yield view_model, tmp_path
    db.close()


def field(map_id=0x07, x=5, y=6, ptr=0x8E83, **kw) -> GameState:
    return GameState(in_battle=False, fresh=True, map_id=map_id,
                     map_x=x, map_y=y, map_data_pointer=ptr, **kw)

# --- 5. メイン画面との連携 ---------------------------------------------


@pytest.fixture
def main(app, vm, tmp_path):
    view_model, _ = vm
    log = tmp_path / "retroux.log"
    log.write_text("12:00:00 テスト\n", encoding="utf-8")
    win = MainWindow(view_model, interval_ms=10 ** 6, log_path=log)
    win.show()
    app.processEvents()
    yield win, view_model, app
    win.close()


def test_main_window_shows_where_you_are(main):
    win, _vm, app = main
    win._track_position(field(map_id=0x07, x=12, y=3))
    app.processEvents()
    text = win._where.text()
    assert "07" in text and "12, 3" in text


def test_main_window_says_when_position_is_unknown(main):
    """★分からないときは**そう書く**（空欄にしない）。"""
    win, _vm, app = main
    win._track_position(GameState(fresh=False))
    app.processEvents()
    assert "—" in win._where.text()

    win._track_position(GameState(fresh=True, in_battle=True))
    app.processEvents()
    assert "戦闘中" in win._where.text()


def test_main_window_records_only_when_the_tile_changes(main, monkeypatch):
    """★同じマスに居るあいだ DB を叩き続けないこと。"""
    win, view_model, app = main
    calls = []
    real = view_model.note_position
    monkeypatch.setattr(view_model, "note_position",
                        lambda s: calls.append(1) or real(s))

    for _ in range(5):
        win._track_position(field(x=2, y=2))
        app.processEvents()
    assert len(calls) == 1, f"{len(calls)} 回書いた"

    win._track_position(field(x=3, y=2))
    app.processEvents()
    assert len(calls) == 2


def test_map_button_opens_one_window_only(main):
    win, _vm, app = main
    win._open_map_window()
    app.processEvents()
    first = win._map_window
    assert first.isVisible()
    win._open_map_window()
    app.processEvents()
    assert win._map_window is first, "2つ目の窓ができた"
    first.close()
