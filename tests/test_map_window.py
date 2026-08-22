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


# --- 世界地図の見せ方（RX-0094 / 2026-08-21）-------------------------------
#
# ★依頼者「maps.json が無かった公開版の見え方（歩いた範囲）のほうが見やすい。
#   config で切り替えたい」。既定は walked、full で 256×256 固定。
#   ⚠ 変わるのは描き方だけ。記録（`map_size`）は両方とも 256×256 のまま。

def _walk_world(view_model, app, win):
    # ★世界地図の種別と大きさ（gui.py では maps.json と config.yaml から入る）
    view_model.map_meta[0x01] = {"map_id": 1, "type": "overworld",
                                 "width": None, "height": None, "data_pointer": "0x8000"}
    view_model.overworld_size = (256, 256)
    view_model.note_position(field(map_id=0x01, ptr=0x8000, x=120, y=130))
    win.reload()
    app.processEvents()


def test_world_map_defaults_to_the_walked_extent(window):
    win, view_model, app = window
    assert view_model.overworld_view == "walked"
    _walk_world(view_model, app, win)
    assert win._view.width_tiles is None, "★walked では大きさを渡さない"
    assert not win._view.is_overworld, "★walked では街と同じ描き方（枠に収める）"
    assert win._view.bounds() == (121, 131)
    # ⚠ 記録側の大きさは変わらない
    assert view_model.map_size(0x01) == (256, 256)


def test_world_map_full_view_is_fixed_256(window):
    win, view_model, app = window
    view_model.overworld_view = "full"
    _walk_world(view_model, app, win)
    assert win._view.width_tiles == 256
    assert win._view.is_overworld
    assert win._view.bounds() == (256, 256)


def test_unknown_overworld_view_falls_back_to_walked(vm):
    """⚠ 綴り違いを黙って full にしない。"""
    view_model, _tmp = vm
    from retroux.ui.view_model import ViewModel
    bad = ViewModel(view_model.recorder, view_model.db, "HASH", overworld_view="typo")
    assert bad.overworld_view == "walked"


# --- いまの部屋（RX-0053 / 2026-08-21）-------------------------------------
#
# ★DQ2 のダンジョンは「入った区画だけ見える」。ROM の区画表（region_map.py）を
#   現在地の論理セルで引き、見出しの下に1行出す（依頼者: 案 a）。

ROM_PATH = pathlib.Path(__file__).resolve().parents[1] / "work" / "rom" / "DQ2_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="ROM が無い")


def _live(tmp_path):
    from dq2rom.monsters.palette import load_nes_palette
    from retroux.core.bgmap.catalog import AssetStore
    from retroux.core.bgmap.live import LiveMetatiles, RomTileSource
    palette = (pathlib.Path(__file__).resolve().parents[1]
               / "tools" / "fceux" / "palettes" / "FCEUX.pal")
    return LiveMetatiles(RomTileSource(ROM_PATH), AssetStore(tmp_path / "art"),
                         load_nes_palette(palette))


@needs_rom
def test_the_room_line_names_the_room_you_stand_in(window, tmp_path):
    """★map $40（区画 10 部屋）。論理 (0,2) は区画 1 の 136 マスの部屋、
    (16,2) は通路。物理座標は論理 ×2（span）。"""
    win, view_model, app = window
    view_model.live_metatiles = _live(tmp_path)
    view_model.map_meta[0x40] = {"map_id": 0x40, "type": "dungeon_a",
                                 "width": 18, "height": 20, "data_pointer": "0xA293"}
    view_model.note_position(field(map_id=0x40, ptr=0xA293, x=0, y=4))
    win.reload()
    win._draw(here=(0, 4))
    app.processEvents()
    assert win._room_note.text() == "🚪 いまの部屋: 1 番（136 マス）"
    assert win._room_note.isVisible()
    win._draw(here=(32, 4))                 # 論理 (16,2) = 通路
    assert win._room_note.text() == "🚪 いまの部屋: 通路"


def test_the_room_line_hides_when_there_is_no_room_data(window):
    """⚠ 世界地図・区画表の無いマップ・現在地不明では行ごと消す（空欄を作らない）。"""
    win, view_model, app = window
    view_model.note_position(field(x=1, y=1))          # 街 0x07（live_metatiles 無し）
    win.reload()
    win._draw(here=(1, 1))
    assert win._room_note.text() == ""
    assert not win._room_note.isVisible()
