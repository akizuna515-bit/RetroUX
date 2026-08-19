"""区画（部屋）データ（2026-08-03 / Phase 4）。

★★ **これは地形ではありません。**「そのマスが見えるか」の判定です。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap import region_map as R
from retroux.core.bgmap.rom_tiles import load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")

TOWN, DUNGEON2, DUNGEON3 = 0x0B, 0x40, 0x50


# --- ★ 展開規則 -----------------------------------------------------------

def test_マスクは種別で変わる():
    """★`$E04A: LDA #$3F`（種別<2）/ `$E04E: LDA #$0F`（種別>=2）。"""
    assert R.mask_for_kind(0) == R.MASK_TOWN
    assert R.mask_for_kind(1) == R.MASK_TOWN
    assert R.mask_for_kind(2) == R.MASK_DUNGEON
    assert R.mask_for_kind(3) == R.MASK_DUNGEON


def test_マスクの幅だけ右シフトする():
    """★`$E09C: LSR / LSR $0F / BNE $E09C` の回数。"""
    assert R._shift_of(R.MASK_DUNGEON) == 4      # $0F → 4 ビット
    assert R._shift_of(R.MASK_TOWN) == 6         # $3F → 6 ビット


@needs_rom
def test_ROMの命令列が変わっていない():
    """⚠ 番地と実バイトを結びつけます。"""
    prg = load_prg(ROM)
    at = lambda a: 7 * 0x4000 + a - 0xC000       # noqa: E731
    # $E089: AND $0F / SEC / ADC $0E / STA $0E
    assert prg[at(0xE089):at(0xE089) + 6] == bytes(
        [0x25, 0x0F, 0x38, 0x65, 0x0E, 0x85, 0x0E])[:6]
    # $E099: TXA / AND #$7F / LSR / LSR $0F / BNE
    assert prg[at(0xE099):at(0xE099) + 6] == bytes(
        [0x8A, 0x29, 0x7F, 0x4A, 0x46, 0x0F])
    # $E07A: LDA ($25),Y / BMI  ★行の終わりは bit7
    assert prg[at(0xE07A):at(0xE07A) + 3] == bytes([0xB1, 0x25, 0x30])


# --- ★★ 全マップで面積が合う ---------------------------------------------

@needs_rom
def test_区画データを持つ60マップを全部展開できる():
    """★★★ **これが Phase 4 の到達点。**

    ⚠ 「読めた」だけでなく、**マスの数がマップの面積と一致する**ことを見ます。
      1 マスでも読み落とすと合いません。
    """
    prg = load_prg(ROM)
    have = [m for m in range(109) if R.load(prg, m).has_data]
    assert len(have) == 60
    for map_id in have:
        region_map = R.load(prg, map_id)
        grid = region_map.grid()
        read = sum(1 for row in grid for v in row if v is not None)
        assert read == region_map.width * region_map.height, (
            f"⚠ map ${map_id:02X}: {read} != "
            f"{region_map.width * region_map.height}")


@needs_rom
def test_区画データが無いマップもある():
    """⚠ 世界地図は持ちません（`$E052: LDA $25 / ORA $26`）。"""
    prg = load_prg(ROM)
    assert not R.load(prg, 0x01).has_data
    assert R.load(prg, 0x01).region_at(0, 0) is None


@needs_rom
def test_範囲外はNone():
    """⚠ 0（通路）と混ぜません。"""
    prg = load_prg(ROM)
    region_map = R.load(prg, DUNGEON2)
    assert region_map.region_at(-1, 0) is None
    assert region_map.region_at(region_map.width, 0) is None
    assert region_map.region_at(0, region_map.height) is None


# --- ★ 中身が部屋らしい ---------------------------------------------------

@needs_rom
def test_ダンジョンは複数の区画に分かれる():
    """★map `$40` は 8 区画。"""
    prg = load_prg(ROM)
    regions = R.load(prg, DUNGEON2).regions()
    assert len(regions) == 8
    assert R.CORRIDOR in regions, "★通路（区画0）があるはず"
    # ★どの区画も 1 マス以上
    assert all(cells for cells in regions.values())


def _components(cells) -> int:
    """★4 近傍で繋がったかたまりの数。"""
    remaining = set(cells)
    count = 0
    while remaining:
        count += 1
        stack = [remaining.pop()]
        while stack:
            x, y = stack.pop()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) in remaining:
                    remaining.discard((nx, ny))
                    stack.append((nx, ny))
    return count


@needs_rom
def test_区画番号は離れた部屋で使い回される():
    """★★★ 2026-08-03 に分かったこと。

    ⚠⚠ map `$40` の区画 7 は `(0,0)(1,0)(0,1)` と `(0,10)(1,10)` の
      **2 か所**に分かれています。番号がダンジョンで 3 ビット（0-7）
      しかないため、離れた部屋で使い回されています。

    ★「1 つの部屋」が欲しいときは `rooms()`（連結成分）を使ってください。

    ⚠ 私は最初「囲む四角の半分以上を占めるはず」で見ようとして
      L 字の部屋（44%）で落ち、次に「ひとつながりのはず」で見て
      ここで落ちました。★どちらも**私の思い込み**で、規則は正しい。
    """
    prg = load_prg(ROM)
    regions = R.load(prg, DUNGEON2).regions()
    assert _components(regions[7]) == 2, "★番号 7 は 2 か所に分かれている"


@needs_rom
def test_roomsは1件が1つながり():
    """★`rooms()` なら 1 件 = 1 部屋になります。

    ⚠ 通路（区画0）はまとめません（分かれていて当たり前）。
    """
    prg = load_prg(ROM)
    for region_id, cells in R.load(prg, DUNGEON2).rooms():
        if region_id == R.CORRIDOR:
            continue
        assert _components(cells) == 1, (
            f"⚠ 区画 {region_id} のかたまりが割れています")


@needs_rom
def test_roomsは全マスを漏らさない():
    """⚠ 分けたときに落とさないこと。"""
    prg = load_prg(ROM)
    region_map = R.load(prg, DUNGEON2)
    total = sum(len(c) for _, c in region_map.rooms())
    assert total == region_map.width * region_map.height


@needs_rom
@pytest.mark.parametrize("map_id,kind,least", [
    (TOWN, 1, 1), (DUNGEON2, 2, 2), (DUNGEON3, 3, 2)])
def test_種別ごとに区画が取れる(map_id, kind, least):
    prg = load_prg(ROM)
    region_map = R.load(prg, map_id)
    assert region_map.kind == kind
    assert len(region_map.regions()) >= least


@needs_rom
def test_街は区画が少ない():
    """⚠ 街のマスクは `$3F` なので、区画番号は 1 ビット（0-1）だけ。"""
    prg = load_prg(ROM)
    for map_id in range(0x00, 0x2B):
        region_map = R.load(prg, map_id)
        if not region_map.has_data:
            continue
        assert set(region_map.regions()) <= {0, 1}, f"⚠ map ${map_id:02X}"


# --- ★ 受け渡しの形 -------------------------------------------------------

@needs_rom
def test_受け渡しの形が指定どおり():
    prg = load_prg(ROM)
    rows = R.to_dict(R.load(prg, DUNGEON2))
    assert rows
    row = rows[0]
    assert set(row) == {"region_id", "cells", "visibility", "source",
                        "confidence"}
    assert set(row["visibility"]) == {"current", "visited", "revealed"}
    assert row["confidence"] == "confirmed"


@needs_rom
def test_今どこにいるか分からなければNone():
    """⚠⚠ **False と混ぜません。**"""
    prg = load_prg(ROM)
    rows = R.to_dict(R.load(prg, DUNGEON2))
    assert all(r["visibility"]["current"] is None for r in rows)
    assert all(r["visibility"]["visited"] is None for r in rows)


@needs_rom
def test_今いる区画を渡すと分かれる():
    prg = load_prg(ROM)
    rows = R.to_dict(R.load(prg, DUNGEON2), current=3, visited={1, 3})
    current = [r for r in rows if r["visibility"]["current"]]
    assert len(current) == 1 and current[0]["region_id"] == 3
    visited = {r["region_id"] for r in rows if r["visibility"]["visited"]}
    assert visited == {1, 3}
    # ⚠ まだ「見せてよい」とは言っていない
    assert all(r["visibility"]["revealed"] is False for r in rows)


# --- ⚠ 地形を壊さない -----------------------------------------------------

@needs_rom
def test_区画は地形に触らない():
    """★★ `BaseTerrain` とは別物です。"""
    from retroux.core.bgmap.dungeon_map import DungeonMap

    prg = load_prg(ROM)
    dmap = DungeonMap(prg, DUNGEON2)
    before = [[dmap.cell(x, y) for x in range(dmap.width)]
              for y in range(dmap.height)]
    R.load(prg, DUNGEON2).grid()
    after = [[dmap.cell(x, y) for x in range(dmap.width)]
             for y in range(dmap.height)]
    assert before == after
