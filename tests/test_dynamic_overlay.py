"""動的差分の3層分離（2026-08-02 / Phase 3）。

★★ **「ある」と「開いている」と「見つけた」は別のことです。** ★★

⚠ `BaseTerrain`（`DungeonMap`）へは**書き込みません**。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.dungeon_map import CHEST_TERRAIN, DungeonMap
from retroux.core.bgmap.overlay import (CHEST_LIST, DOOR_LIST, KIND_CHEST,
                                        KIND_DOOR, OPENED_TERRAIN,
                                        STATE_CLOSED, STATE_OPENED, UNKNOWN,
                                        DynamicOverlay, KnowledgeState,
                                        ObjectDefinition, RuntimeState,
                                        build_dynamic, composed_terrain)
from retroux.core.bgmap.rom_tiles import load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")

#: ★街（種別1）/ ダンジョン（種別2）/ ダンジョン（種別3）
TOWN, DUNGEON2, DUNGEON3 = 0x0B, 0x40, 0x50


def _map(map_id: int) -> DungeonMap:
    return DungeonMap(load_prg(ROM), map_id)


# --- ★ 1. 定義（ROM だけ）------------------------------------------------

@needs_rom
@pytest.mark.parametrize("map_id", [TOWN, DUNGEON2, DUNGEON3])
def test_定義はROMだけで決まる(map_id):
    """★RAM を渡しても渡さなくても、**在り処は同じ**。"""
    dmap = _map(map_id)
    a = build_dynamic(dmap)
    b = build_dynamic(dmap, bytearray(0x800))
    assert [d.cell for d in a.definitions] == [d.cell for d in b.definitions]
    assert [d.kind for d in a.definitions] == [d.kind for d in b.definitions]


@needs_rom
def test_定義は状態を持たない():
    """⚠⚠ `ObjectDefinition` に「開いているか」を持たせません。"""
    fields = {f for f in ObjectDefinition.__dataclass_fields__}
    assert "state" not in fields
    assert "opened" not in fields


@needs_rom
@pytest.mark.parametrize("map_id", [TOWN, DUNGEON2, DUNGEON3])
def test_1論理セルにつき1件しか作らない(map_id):
    """⚠ 画面マスで回すと 2×2 の 4 件に増えます。"""
    overlay = build_dynamic(_map(map_id))
    cells = [d.cell for d in overlay.definitions]
    assert len(cells) == len(set(cells))


# --- ⚠ 2. 実行時の状態（RAM だけ）----------------------------------------

@needs_rom
@pytest.mark.parametrize("map_id", [TOWN, DUNGEON2, DUNGEON3])
def test_RAMが無ければ状態は決めつけない(map_id):
    """⚠⚠ **`closed` にしません。**"""
    overlay = build_dynamic(_map(map_id))
    assert overlay.has_ram is False
    assert all(e.state == UNKNOWN for e in overlay.elements)
    assert len(overlay.unresolved()) == len(overlay.definitions)


@needs_rom
def test_宝箱の取得済みを見分ける():
    dmap = _map(DUNGEON2)
    target = next(d for d in build_dynamic(dmap).definitions
                  if d.kind == KIND_CHEST)
    ram = bytearray(0x800)
    ram[CHEST_LIST], ram[CHEST_LIST + 1] = target.cell
    overlay = build_dynamic(dmap, ram)
    picked = next(e for e in overlay.elements if e.cell == target.cell)
    assert picked.state == STATE_OPENED
    others = [e for e in overlay.elements
              if e.kind == KIND_CHEST and e.cell != target.cell]
    assert others and all(e.state == STATE_CLOSED for e in others)


@needs_rom
def test_扉の開放済みを見分ける():
    """★扉は街にあります（`$0B` に 1 枚）。"""
    dmap = _map(TOWN)
    doors = [d for d in build_dynamic(dmap).definitions if d.kind == KIND_DOOR]
    assert doors, "★街に扉があるはず"
    ram = bytearray(0x800)
    ram[DOOR_LIST], ram[DOOR_LIST + 1] = doors[0].cell
    overlay = build_dynamic(dmap, ram)
    assert next(e for e in overlay.elements
                if e.cell == doors[0].cell).state == STATE_OPENED


@needs_rom
def test_宝箱の表と扉の表を取り違えない():
    """⚠ `$051A` は宝箱、`$052A` は扉。混ぜると別の物が消えます。"""
    dmap = _map(TOWN)
    defs = build_dynamic(dmap).definitions
    chest = next(d for d in defs if d.kind == KIND_CHEST)
    ram = bytearray(0x800)
    # ⚠ 宝箱の座標を**扉の表**へ入れる → 宝箱は開かないはず
    ram[DOOR_LIST], ram[DOOR_LIST + 1] = chest.cell
    overlay = build_dynamic(dmap, ram)
    assert next(e for e in overlay.elements
                if e.cell == chest.cell).state == STATE_CLOSED


@needs_rom
def test_表にだけある座標を捨てない():
    """⚠⚠ `unknown_dynamic` として残します（**黙って捨てない**）。"""
    ram = bytearray(0x800)
    ram[CHEST_LIST], ram[CHEST_LIST + 1] = 99, 99      # ⚠ ROM に無い
    overlay = build_dynamic(_map(DUNGEON2), ram)
    extra = overlay.unknown_dynamic()
    assert any(e["logical_x"] == 99 and e["logical_y"] == 99 for e in extra)
    assert all(e["confidence"] == UNKNOWN for e in extra)


def test_RAMを渡さないRuntimeStateは何も知らない():
    state = RuntimeState.from_ram(None)
    assert state.has_ram is False
    fake = ObjectDefinition(cell=(1, 1), kind=KIND_CHEST, terrain_id=0x14)
    assert state.state_of(fake) == UNKNOWN
    assert state.unmatched([fake]) == []


# --- ⚠ 3. 見つけたか -----------------------------------------------------

def test_見つけたかは別の層():
    """⚠ ROM からも RAM からも作れません。"""
    knowledge = KnowledgeState()
    fake = ObjectDefinition(cell=(3, 4), kind=KIND_CHEST, terrain_id=0x14)
    assert knowledge.is_discovered(fake) is False
    knowledge.discover((3, 4))
    assert knowledge.is_discovered(fake) is True


# --- ★★ BaseTerrain は変わらない -----------------------------------------

@needs_rom
def test_状態を当てても基礎地形は変わらない():
    """★★★ **これが Phase 3 の肝です。**"""
    dmap = _map(DUNGEON2)
    target = next(d for d in build_dynamic(dmap).definitions
                  if d.kind == KIND_CHEST)
    before = [[dmap.cell(x, y) for x in range(dmap.width)]
              for y in range(dmap.height)]

    ram = bytearray(0x800)
    ram[CHEST_LIST], ram[CHEST_LIST + 1] = target.cell
    overlay = build_dynamic(dmap, ram)
    px, py = target.cell[0] * 2, target.cell[1] * 2
    assert composed_terrain(dmap, px, py, overlay) == OPENED_TERRAIN

    after = [[dmap.cell(x, y) for x in range(dmap.width)]
             for y in range(dmap.height)]
    assert before == after, "⚠⚠ 基礎地形を書き換えてはいけません"
    assert dmap.cell(*target.cell) == CHEST_TERRAIN


@needs_rom
def test_apply_runtime_stateは新しい層を返す():
    """⚠ 元の層も書き換えません。"""
    dmap = _map(DUNGEON2)
    base = build_dynamic(dmap)
    target = next(d for d in base.definitions if d.kind == KIND_CHEST)
    ram = bytearray(0x800)
    ram[CHEST_LIST], ram[CHEST_LIST + 1] = target.cell

    applied = base.apply_runtime_state(ram)
    assert applied is not base
    assert applied.has_ram is True
    assert base.has_ram is False, "⚠ 元の層が変わっています"
    assert all(e.state == UNKNOWN for e in base.elements)


@needs_rom
def test_状態がunknownなら差し替えない():
    """⚠ 分からないものを「開けた」ことにしません。"""
    dmap = _map(DUNGEON2)
    overlay = build_dynamic(dmap)                 # ★RAM 無し
    target = next(d for d in overlay.definitions if d.kind == KIND_CHEST)
    px, py = target.cell[0] * 2, target.cell[1] * 2
    assert composed_terrain(dmap, px, py, overlay) == CHEST_TERRAIN


# --- ★ 2×2 の当たり判定 --------------------------------------------------

@needs_rom
def test_ダンジョンでは1つの宝箱が2x2の4マスに当たる():
    dmap = _map(DUNGEON2)
    overlay = build_dynamic(dmap)
    target = next(d for d in overlay.definitions if d.kind == KIND_CHEST)
    cx, cy = target.cell
    for dx in (0, 1):
        for dy in (0, 1):
            assert overlay.at(cx * 2 + dx, cy * 2 + dy) is not None


@needs_rom
def test_街では1つの宝箱が1マスだけに当たる():
    dmap = _map(TOWN)
    overlay = build_dynamic(dmap)
    assert overlay.span == 1
    target = next(d for d in overlay.definitions if d.kind == KIND_CHEST)
    cx, cy = target.cell
    assert overlay.at(cx, cy) is not None
    # ⚠ 隣は別のマス
    neighbour = overlay.at(cx + 1, cy)
    assert neighbour is None or neighbour.cell != target.cell


@needs_rom
def test_空の層でも落ちない():
    empty = DynamicOverlay()
    assert empty.elements == []
    assert empty.at(0, 0) is None
    assert empty.unknown_dynamic() == []
    assert "宝箱 0" in empty.summary()
