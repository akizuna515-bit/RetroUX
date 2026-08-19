"""地図の窓（一覧と表示）。

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
    return yaml.safe_load(MAP_PATH.read_text(encoding="utf-8"))


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

# --- 4. 地図の窓 --------------------------------------------------------


@pytest.fixture
def window(app, vm):
    view_model, tmp = vm
    win = MapWindow(view_model)
    win.show()
    app.processEvents()
    yield win, view_model, app
    win.close()


def test_says_when_nothing_has_been_walked(window):
    """★空でも「壊れている」に見せない。"""
    win, _vm, _app = window
    assert "まだ見た記録がありません" in win._summary.text()


def test_lists_walked_maps(window):
    win, view_model, app = window
    view_model.note_position(field(x=1, y=1))
    view_model.note_position(field(map_id=0x59, ptr=0xA48B, x=2, y=2))
    win.reload()
    app.processEvents()
    assert win._list.count() == 2
    assert "行ったマップ 2 件" in win._summary.text()


def test_uses_the_real_map_size_from_rom(window):
    """★枠の大きさは ROM の値（北米版と109/109一致した表）。"""
    win, view_model, app = window
    view_model.note_position(field(x=1, y=1))
    win.reload()
    app.processEvents()
    assert win._view.width_tiles == 23
    assert win._view.height_tiles == 23
    # ★★ 2026-08-09: 見出しは地名と出どころだけ（依頼者の指示）★★
    #   ⚠ 大きさ・データ位置・マス数はツールチップへ移しました。
    assert "23×23" in win._title.toolTip()


def test_falls_back_when_the_size_is_unknown(window):
    """★大きさが分からないマップでは、歩いた範囲に合わせる（推測しない）。"""
    win, view_model, app = window
    view_model.note_position(field(map_id=0x77, ptr=0x8888, x=3, y=4))
    win.reload()
    app.processEvents()
    assert win._view.width_tiles is None
    assert win._view.bounds() == (4, 5)
    assert "大きさ不明" in win._title.toolTip()


def test_says_what_the_map_shows(window):
    """★★ 何を出していて、何を出していないかを**書く**。

    ⚠⚠ 2026-08-11 に**この検査が古い主張を固定していました**。
      「⚠ 壁・扉・階段は出ません。マップ形式が未解読のため」と画面に出す、
      という内容でしたが、2026-08-09（街・ダンジョン）と 2026-08-11
      （世界地図）に **ROM の地形で描くようになって嘘**になっていました。
      ★依頼者の「いまとなっては解決できているものは？」で気づきました。

    ★いま画面に出すのは:
      - 見た範囲だけであること（★探索を潰さないため）
      - 地形は ROM の絵であること
    """
    win, _vm, _app = window
    text = win._note.text()
    assert "見た範囲" in text, "★見た範囲だけ、は画面に出したままにすること"
    assert "ROM" in text
    # ⚠ 詳しいことは隠さない。★ツールチップで読める
    tip = win._note.toolTip()
    assert "ROM" in tip
    assert "行っていない所は出しません" in tip, (
        "★ROM から読めても開示しないこと（指示書 §2.2）を書いておく")

def test_follow_moves_to_the_current_map(window):
    win, view_model, app = window
    view_model.note_position(field(x=1, y=1))
    view_model.note_position(field(map_id=0x59, ptr=0xA48B, x=2, y=2))
    win.reload()
    win._list.setCurrentRow(0)
    app.processEvents()

    win.follow(0x59, 0xA48B, 2, 2)
    app.processEvents()
    assert win._keys[win._list.currentRow()] == (0x59, 0xA48B)
    assert win._view.here == (2, 2)


def test_follow_can_be_turned_off(window):
    win, view_model, app = window
    view_model.note_position(field(x=1, y=1))
    view_model.note_position(field(map_id=0x59, ptr=0xA48B, x=2, y=2))
    win.reload()
    win._list.setCurrentRow(0)
    win._follow.setChecked(False)
    app.processEvents()

    win.follow(0x59, 0xA48B, 2, 2)
    app.processEvents()
    assert win._keys[win._list.currentRow()] == (0x07, 0x8E83), "追従を切っても動いた"


def test_new_map_appears_without_pressing_reload(window):
    """★歩いている最中に新しいマップへ入っても出ること。"""
    win, view_model, app = window
    view_model.note_position(field(x=1, y=1))
    win.reload()
    app.processEvents()
    assert win._list.count() == 1

    view_model.note_position(field(map_id=0x59, ptr=0xA48B, x=2, y=2))
    win.follow(0x59, 0xA48B, 2, 2)
    app.processEvents()
    assert win._list.count() == 2
