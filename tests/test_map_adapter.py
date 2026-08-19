"""MapMaster と既存マッパーを繋ぐ層（2026-08-03 / Phase 3）。

★★ **既存の地図を壊さないこと**を固定します。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap import adapter
from retroux.core.bgmap.dungeon_map import CHEST_TERRAIN, OPENED_TERRAIN
from retroux.core.bgmap.overlay import (CHEST_LIST, DOOR_LIST, KIND_CHEST,
                                        STATE_CLOSED, STATE_OPENED, UNKNOWN)
from retroux.core.bgmap.rom_tiles import (MAP_HEADER, MAP_HEADER_SIZE,
                                          load_prg)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")

TOWN, DUNGEON2, DUNGEON3 = 0x0B, 0x40, 0x50


def _prg():
    return load_prg(ROM)


def _pointer(prg, map_id: int) -> int:
    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    return prg[off + 3] | (prg[off + 4] << 8)


# --- ★ Core 層であること ---------------------------------------------------

def test_Qtに依存しない():
    """⚠⚠ **GUI を持ち込みません。**"""
    source = pathlib.Path(adapter.__file__).read_bytes().decode("utf-8")
    for banned in ("PySide6", "QtWidgets", "QtGui", "QWidget"):
        assert banned not in source, f"⚠ {banned} が入っています"


def test_重ねる順が決まっている():
    """★依頼者の指定どおり。"""
    assert adapter.LAYER_ORDER == (
        "terrain", "art", "dynamic_definition", "runtime_state",
        "knowledge", "exploration_mask", "markers")


# --- ★ 種別ごとに使える ---------------------------------------------------

@needs_rom
@pytest.mark.parametrize("map_id,kind", [(TOWN, 1), (DUNGEON2, 2), (DUNGEON3, 3)])
def test_種別1から3まで使える(map_id, kind):
    view = adapter.build_view(_prg(), map_id)
    assert view.used_master
    assert view.map_type == kind
    assert view.tiles


# --- ⚠ 使えないときは理由を返す -------------------------------------------

@needs_rom
def test_世界地図は現行表示へ落ちる():
    """⚠ 黙って壊れた地図を出しません。★理由を言葉で返します。"""
    view = adapter.build_view(_prg(), 0x01)
    assert not view.used_master
    assert view.fallback["reason"] == adapter.REASON_WORLD_MAP
    assert view.fallback["use_observed"] is True
    assert "世界地図" in view.fallback["detail"]


@needs_rom
def test_ポインタが食い違えば使わない():
    """★★ 2026-07-30 の実データ由来。

    ⚠ `map_id`=01 なのに町のポインタ、という記録が 3 件ありました。
      **マップ切替の一瞬**に `$31` と `$23/$24` が食い違います。
    """
    prg = _prg()
    right = _pointer(prg, DUNGEON2)
    assert adapter.resolve_map_master(prg, DUNGEON2, right)
    wrong = adapter.resolve_map_master(prg, DUNGEON2, right + 1)
    assert not wrong
    assert wrong.reason == adapter.REASON_POINTER_MISMATCH


@needs_rom
def test_map_idが同じでもポインタが違えば別扱い():
    """★`map_id` だけでは足りません。"""
    prg = _prg()
    a = adapter.resolve_map_master(prg, DUNGEON2, _pointer(prg, DUNGEON2))
    b = adapter.resolve_map_master(prg, DUNGEON2, _pointer(prg, DUNGEON3))
    assert a.ok and not b.ok


@needs_rom
def test_範囲外のmap_idも落ちない():
    view = adapter.build_view(_prg(), 0xFF)
    assert not view.used_master
    assert view.fallback["reason"] == adapter.REASON_OUT_OF_RANGE


# --- ★★ BaseTerrain を壊さない -------------------------------------------

@needs_rom
def test_runtime状態でterrainを書き換えない():
    """★★★ **これが Phase 3 の肝です。**"""
    prg = _prg()
    plain = adapter.build_view(prg, DUNGEON2)
    target = next(o for o in plain.objects if o.kind == KIND_CHEST)

    ram = bytearray(0x800)
    ram[CHEST_LIST], ram[CHEST_LIST + 1] = target.cell
    live = adapter.build_view(prg, DUNGEON2, ram=ram)

    picked = [t for t in live.tiles if t.logical == target.cell]
    assert picked
    assert all(t.terrain_id == OPENED_TERRAIN for t in picked)
    # ★★ ROM のままの値は残っている
    assert all(t.base_terrain_id == CHEST_TERRAIN for t in picked)
    # ⚠ 別に組み立てた view は影響を受けない
    again = adapter.build_view(prg, DUNGEON2)
    assert all(o.state == UNKNOWN for o in again.objects)


@needs_rom
def test_未取得と取得済みを区別する():
    prg = _prg()
    chests = [o for o in adapter.build_view(prg, DUNGEON2).objects
              if o.kind == KIND_CHEST]
    assert len(chests) >= 2
    ram = bytearray(0x800)
    ram[CHEST_LIST], ram[CHEST_LIST + 1] = chests[0].cell
    view = adapter.build_view(prg, DUNGEON2, ram=ram)
    assert len(view.chests(STATE_OPENED)) == 1
    assert len(view.chests(STATE_CLOSED)) == len(chests) - 1


@needs_rom
def test_扉も区別する():
    prg = _prg()
    doors = [o for o in adapter.build_view(prg, TOWN).objects
             if o.kind != KIND_CHEST]
    assert doors, "★街に扉があるはず"
    ram = bytearray(0x800)
    ram[DOOR_LIST], ram[DOOR_LIST + 1] = doors[0].cell
    view = adapter.build_view(prg, TOWN, ram=ram)
    states = {o.cell: o.state for o in view.objects if o.kind != KIND_CHEST}
    assert states[doors[0].cell] == STATE_OPENED


@needs_rom
def test_RAMなしでは状態を決めつけない():
    view = adapter.build_view(_prg(), DUNGEON2)
    assert view.objects
    assert all(o.state == UNKNOWN for o in view.objects)
    # ⚠ 合成しても宝箱のまま（★「開けた」ことにしない）
    chest = view.chests()[0]
    picked = [t for t in view.tiles if t.logical == chest.cell]
    assert all(t.terrain_id == CHEST_TERRAIN for t in picked)


# --- ★ 「ある」と「見つけた」を分ける -------------------------------------

@needs_rom
def test_ROM上の存在と発見済みを分ける():
    prg = _prg()
    plain = adapter.build_view(prg, DUNGEON2)
    chest = plain.chests()[0]
    # ⚠ 何も見つけていなければ discovered は False
    assert all(not t.discovered for t in plain.tiles)
    # ★見つけたと伝えると、そのセルだけ True
    known = adapter.build_view(prg, DUNGEON2, knowledge=[chest.cell])
    marked = [t for t in known.tiles if t.logical == chest.cell]
    assert marked and all(t.discovered for t in marked)
    assert all(not t.discovered for t in known.tiles
               if t.logical != chest.cell)


# --- ★ 歩いたマスだけ見せる -----------------------------------------------

@needs_rom
def test_歩いたセルだけ返せる():
    """★指示書 §2.2。"""
    visited = {(1, 1), (2, 2), (3, 3)}
    view = adapter.build_view(_prg(), DUNGEON2, visited=visited)
    assert {t.logical for t in view.tiles} == visited


@needs_rom
def test_マスクを渡さなければ全部出る():
    """⚠ 全体表示はデバッグ用です。★既定にしないでください。"""
    view = adapter.build_view(_prg(), DUNGEON2)
    assert len(view.tiles) == view.physical_size[0] * view.physical_size[1]


# --- ★ 座標 ---------------------------------------------------------------

@needs_rom
@pytest.mark.parametrize("map_id", [TOWN, DUNGEON2, DUNGEON3])
def test_座標の行き来が戻ってくる(map_id):
    master = adapter.resolve_map_master(_prg(), map_id).master
    for cy in range(0, master.height, 3):
        for cx in range(0, master.width, 3):
            for px, py in adapter.logical_to_physical(master, cx, cy):
                assert adapter.physical_to_logical(master, px, py) == (cx, cy)


@needs_rom
def test_主人公の位置が地図の外か分かる():
    prg = _prg()
    ram = bytearray(0x800)
    ram[0x16], ram[0x17] = 4, 6
    view = adapter.build_view(prg, DUNGEON2, ram=ram)
    assert view.player["physical"] == (4, 6)
    assert view.player["logical"] == (2, 3)
    assert view.player["inside"] is True
    # ⚠ 地図の外（★飛ばずに False と分かること）
    ram[0x16], ram[0x17] = 250, 250
    outside = adapter.build_view(prg, DUNGEON2, ram=ram)
    assert outside.player["inside"] is False
    assert outside.player["physical"] == (250, 250)


@needs_rom
def test_RAMが無ければ主人公の位置もNone():
    view = adapter.build_view(_prg(), DUNGEON2)
    assert view.player["physical"] == (None, None)


# --- ⚠ 区画はまだ出せない -------------------------------------------------

@needs_rom
def test_区画が取れる():
    """★★ 2026-08-03 / Phase 4 で展開規則が確定しました。"""
    view = adapter.build_view(_prg(), DUNGEON2)
    assert view.region["confidence"] == "confirmed"
    assert len(view.region["regions"]) == 8
    assert view.region["rooms"]


@needs_rom
def test_RAMが無ければ今どこにいるかは分からない():
    """⚠⚠ **決めつけません。**"""
    view = adapter.build_view(_prg(), DUNGEON2)
    assert view.region["current"] is None
    assert all(r["visibility"]["current"] is None
               for r in view.region["regions"])


@needs_rom
def test_RAMがあれば今いる区画が分かる():
    ram = bytearray(0x800)
    ram[adapter.PLAYER_REGION] = 3
    view = adapter.build_view(_prg(), DUNGEON2, ram=ram)
    assert view.region["current"] == 3
    current = [r for r in view.region["regions"] if r["visibility"]["current"]]
    assert len(current) == 1 and current[0]["region_id"] == 3


@needs_rom
def test_区画が分かっても見せてよいとは言わない():
    """⚠⚠ 指示書 §2.2。★`revealed` は常に False。"""
    ram = bytearray(0x800)
    ram[adapter.PLAYER_REGION] = 3
    view = adapter.build_view(_prg(), DUNGEON2, ram=ram)
    assert all(r["visibility"]["revealed"] is False
               for r in view.region["regions"])


@needs_rom
def test_区画データが無いマップでも落ちない():
    prg = _prg()
    for map_id in range(0x2B, 0x44):
        view = adapter.build_view(prg, map_id)
        assert isinstance(view.region.get("regions"), list)


@needs_rom
def test_要約が出る():
    view = adapter.build_view(_prg(), DUNGEON2)
    assert "map $40" in view.summary()
    assert "⚠ 不明" in view.summary()
    world = adapter.build_view(_prg(), 0x01)
    assert "現行表示へ落ちました" in world.summary()
