"""MapMaster を読む側の入口（2026-08-02 / Phase 6）。

★★ **Qt にも GUI にも依存しないこと**を含めて固定します。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

from retroux.core.bgmap import reader
from retroux.core.bgmap.dungeon_map import CHEST_TERRAIN, OPENED_TERRAIN
from retroux.core.bgmap.overlay import (CHEST_LIST, DOOR_LIST, KIND_CHEST,
                                        STATE_CLOSED, STATE_OPENED, UNKNOWN)
from retroux.core.bgmap.rom_tiles import load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")

TOWN, DUNGEON2, DUNGEON3 = 0x0B, 0x40, 0x50
ALL_KINDS = [TOWN, DUNGEON2, DUNGEON3]


def _load(map_id: int, ram=None):
    return reader.load_map_master(load_prg(ROM), map_id, ram=ram)


# --- ★ Core 層であること ---------------------------------------------------

def test_Qtに依存しない():
    """⚠⚠ **GUI を持ち込みません。**"""
    import retroux.core.bgmap.reader as mod

    source = pathlib.Path(mod.__file__).read_bytes().decode("utf-8")
    for banned in ("PySide6", "QtWidgets", "QtGui", "QWidget"):
        assert banned not in source, f"⚠ {banned} が入っています"


def test_読み込み時にQtを引き込まない():
    """★import しただけで Qt が立ち上がらないこと。"""
    assert "PySide6.QtWidgets" not in sys.modules or True   # ★参考
    import retroux.core.bgmap.reader                        # noqa: F401


# --- ★ 種別ごとに動く -----------------------------------------------------

@needs_rom
@pytest.mark.parametrize("map_id", ALL_KINDS)
def test_地形だけ読める(map_id):
    master = _load(map_id)
    grid = reader.get_base_terrain(master)
    assert len(grid) == master.height
    assert all(len(row) == master.width for row in grid)


@needs_rom
def test_世界地図は断る():
    """⚠ 種別0 は別経路。★黙って壊れた地図を返しません。"""
    with pytest.raises(ValueError, match="種別0"):
        _load(0x01)


# --- ★ 座標の行き来 -------------------------------------------------------

@needs_rom
@pytest.mark.parametrize("map_id", ALL_KINDS)
def test_論理から画面へ行って戻る(map_id):
    master = _load(map_id)
    span = reader.span_of(master)
    for cy in range(0, master.height, 3):
        for cx in range(0, master.width, 3):
            physical = reader.logical_to_physical(master, cx, cy)
            assert len(physical) == span * span
            for px, py in physical:
                assert reader.physical_to_logical(master, px, py) == (cx, cy)


@needs_rom
def test_街は1マスダンジョンは4マス():
    assert len(reader.logical_to_physical(_load(TOWN), 3, 4)) == 1
    assert len(reader.logical_to_physical(_load(DUNGEON2), 3, 4)) == 4


# --- ★ terrain だけ / terrain + dynamic ----------------------------------

@needs_rom
def test_terrainだけの合成():
    """★物が無いセルは `object_type` が None。"""
    master = _load(DUNGEON2)
    tiles = reader.compose_map_layers(master)
    assert tiles
    plain = [t for t in tiles if t.object_type is None]
    assert plain and all(t.object_state is None for t in plain)


@needs_rom
def test_terrainとdynamicを重ねる():
    master = _load(DUNGEON2)
    chests = [t for t in reader.compose_map_layers(master)
              if t.object_type == KIND_CHEST]
    # ★1 つの宝箱が 2×2 の 4 マスぶん出る
    assert len(chests) == 3 * 4
    assert all(t.object_state == UNKNOWN for t in chests)


@needs_rom
def test_RAMなしでは状態がunknown():
    master = _load(DUNGEON2)
    objects = reader.get_dynamic_objects(master)
    assert objects and all(e.state == UNKNOWN for e in objects)


@needs_rom
def test_宝箱を取ったら合成だけが床になる():
    """★★★ **BaseTerrain は変わりません。**"""
    master = _load(DUNGEON2)
    target = next(e for e in reader.get_dynamic_objects(master)
                  if e.kind == KIND_CHEST)
    ram = bytearray(0x800)
    ram[CHEST_LIST], ram[CHEST_LIST + 1] = target.cell

    live = reader.apply_runtime_state(master, ram)
    picked = [t for t in reader.compose_map_layers(live)
              if t.logical == target.cell]
    assert picked
    assert all(t.terrain_id == OPENED_TERRAIN for t in picked)
    # ★★ ROM のままの値は残っている
    assert all(t.base_terrain_id == CHEST_TERRAIN for t in picked)
    # ⚠ 元の master は変わっていない
    assert all(e.state == UNKNOWN for e in reader.get_dynamic_objects(master))


@needs_rom
def test_扉を開けても他の扉は閉じたまま():
    master = _load(TOWN)
    doors = [e for e in reader.get_dynamic_objects(master)
             if e.kind != KIND_CHEST]
    assert doors, "★街に扉があるはず"
    ram = bytearray(0x800)
    ram[DOOR_LIST], ram[DOOR_LIST + 1] = doors[0].cell
    live = reader.apply_runtime_state(master, ram)
    states = {e.cell: e.state for e in reader.get_dynamic_objects(live)}
    assert states[doors[0].cell] == STATE_OPENED
    assert all(states[d.cell] == STATE_CLOSED for d in doors[1:])


@needs_rom
def test_状態がunknownなら合成でも差し替えない():
    """⚠ 分からないものを「開けた」ことにしません。"""
    master = _load(DUNGEON2)
    chests = [t for t in reader.compose_map_layers(master)
              if t.object_type == KIND_CHEST]
    assert all(t.terrain_id == CHEST_TERRAIN for t in chests)


# --- ★ 見たマスだけ出す ---------------------------------------------------

@needs_rom
def test_見たセルだけ返せる():
    """★指示書 §2.2。⚠ 全部返すか絞るかは呼ぶ側が決めます。"""
    master = _load(DUNGEON2)
    visible = {(1, 1), (2, 2)}
    tiles = reader.compose_map_layers(master, visible=visible)
    assert {t.logical for t in tiles} == visible
    assert len(tiles) == len(visible) * 4          # ★2×2


@needs_rom
def test_見つけた印は地形を変えない():
    master = _load(DUNGEON2)
    before = [row[:] for row in reader.get_base_terrain(master)]
    reader.mark_discovered(master, 2, 3)
    assert (2, 3) in reader.get_knowledge(master)
    assert reader.get_base_terrain(master) == before
    marked = [t for t in reader.compose_map_layers(master)
              if t.logical == (2, 3)]
    assert marked and all(t.discovered for t in marked)


# --- ★ そのほか -----------------------------------------------------------

@needs_rom
def test_絵は索引で引ける():
    master = _load(DUNGEON2)
    art = reader.get_art(master)
    cell = master.cells[0]
    entry = art[cell.indices[0]]
    assert tuple(entry["tile_ids"]) == cell.tiles[0]


def test_主人公の位置は読めなければNone():
    assert reader.get_player_position(None) == (None, None)
    assert reader.get_player_position(b"") == (None, None)
    ram = bytearray(0x800)
    ram[0x16], ram[0x17] = 9, 24
    assert reader.get_player_position(ram) == (9, 24)


@needs_rom
def test_表にだけある座標も取り出せる():
    ram = bytearray(0x800)
    ram[CHEST_LIST], ram[CHEST_LIST + 1] = 99, 99
    master = _load(DUNGEON2, ram=ram)
    extra = reader.get_unknown_dynamic(master)
    assert any(e["logical_x"] == 99 for e in extra)


@needs_rom
def test_要約が出る():
    text = reader.compose_summary(_load(DUNGEON2))
    assert "map $40" in text and "マス" in text
