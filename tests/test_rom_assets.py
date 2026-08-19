"""ROM だけで地図の絵を用意する（2026-08-02 / 課題 #65）。

★★ **ここで確かめたい一番のこと** ★★

  ROM から組んだ絵が、実機から採った絵と **同じ鍵**になること。

  ⚠ 鍵が同じなら、これまでに作った PNG も DB の記録も**そのまま使えます**。
    鍵が違えば、同じ絵が二重に貯まり、地図がつながりません。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap import Capture, metatile_at
from retroux.core.bgmap.reconstruct import attribute_for
from retroux.core.bgmap.rom_assets import (
    ROM_PATTERN_HALF, MapTiles, RomTileSource,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
ASSETS = PROJECT_ROOT / "work" / "map-assets"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
needs_capture = pytest.mark.skipif(
    not (ASSETS / "capture-3.txt").exists(), reason="採取データが無い")

#: ★地形として採るマス行（ステータス窓より上）
CELL_ROWS, CELL_COLS = 10, 16


def _cells(cap: Capture):
    """採取データの、地形として採るマスを順に出す。

    ⚠⚠ **スクロールを通して読む**（2026-08-02 にここで間違えた）。
      ネームテーブルを素で読むと、`metatile_at` と**別のマス**を見てしまう。
      ★`nametable_index` は `character_at` が使っているものと同じ。

    ⚠ 文字タイル（`$90` 未満）は地形ではないので飛ばす。
    """
    from retroux.core.bgmap import reconstruct as R

    for cy in range(CELL_ROWS):
        for cx in range(CELL_COLS):
            col, row = cx * 2, cy * 2
            quad, groups = [], []
            for dy in (0, 1):
                for dx in (0, 1):
                    side, nc, nr = R.nametable_index(
                        col + dx, row + dy, cap.scroll_x, cap.scroll_y)
                    left = side == "left"
                    nt = cap.nametable_left if left else cap.nametable_right
                    at = cap.attr_left if left else cap.attr_right
                    quad.append(nt[nr * R.COLS + nc])
                    groups.append(attribute_for(at, nc, nr))
            if min(quad) < 0x90:
                continue
            # ⚠ 2×2 が属性の別区画にまたがると、1つの組では表せない。
            #   ★静止時のスクロールは 16 の倍数なので、普通は揃う。
            if len(set(groups)) != 1:
                continue
            yield cx, cy, tuple(quad), groups[0]


# --- ★★ 本題: 採ったものと同じ鍵になるか ★★ --------------------------

@needs_rom
@needs_capture
@pytest.mark.parametrize("slot,map_id,least", [
    (5, 0x0B, 160),      # ★街は 160 マス全部が地形
    (3, 0x3F, 48),       # ⚠ 洞窟は暗がりと窓で減る
    (7, 0x40, 102),
    (8, 0x40, 75),
])
def test_ROMから作った絵は採った絵と同じ鍵になる(slot, map_id, least):
    """★★ **これが成り立つから、採取が要らなくなる。**

    ⚠ 鍵は `<CHRハッシュ>:<タイルID>:<パレット署名>`。
      ROM の CHR とパレットが実機と同じなら、鍵も同じになるはず。
      ★「はず」で済ませず、1マスずつ突き合わせる。

    ⚠⚠ **突き合わせた数も固定する**（2026-08-02 の教訓）。
      「0件でも緑」では、飛ばしただけの空回りに気づけない。
      ★実測した数（160 / 48 / 102 / 75）をそのまま下限にする。
    """
    source = RomTileSource(ROM)
    tiles = source.for_map(map_id)
    assert tiles is not None, source.why_not(map_id)

    cap = Capture.load(ASSETS / f"capture-{slot}.txt")
    checked = 0
    for cx, cy, quad, group in _cells(cap):
        from_rom = tiles.metatile(quad, group, x=cx, y=cy)
        from_screen = metatile_at(cap, cx, cy, ROM_PATTERN_HALF)
        assert from_rom.key == from_screen.key, (
            f"({cx},{cy}) タイル "
            + "".join(f"{t:02X}" for t in quad) + f" 組{group}")
        checked += 1
    assert checked >= least, f"★{checked} マスしか突き合わせていない"


@needs_rom
@needs_capture
@pytest.mark.parametrize("slot", [5, 3, 7, 8])
def test_飛ばした理由が属性またぎではない(slot):
    """⚠ 2×2 が属性の別区画にまたがると、1つのパレット組では表せない。

    ★静止時のスクロールは **16 の倍数**（既測）なので、揃うはず。
      実測4件とも **またぎ 0 件**。⚠ ここが増えたら前提が崩れている。
    """
    from retroux.core.bgmap import reconstruct as R

    cap = Capture.load(ASSETS / f"capture-{slot}.txt")
    assert cap.scroll_x % 16 == 0 and cap.scroll_y % 16 == 0
    straddling = 0
    for cy in range(CELL_ROWS):
        for cx in range(CELL_COLS):
            groups = set()
            for dy in (0, 1):
                for dx in (0, 1):
                    side, nc, nr = R.nametable_index(
                        cx * 2 + dx, cy * 2 + dy, cap.scroll_x, cap.scroll_y)
                    at = (cap.attr_left if side == "left" else cap.attr_right)
                    groups.add(attribute_for(at, nc, nr))
            if len(groups) != 1:
                straddling += 1
    assert straddling == 0, f"★属性をまたぐマスが {straddling} 出た"


@needs_rom
@needs_capture
def test_絵そのものも一致する():
    """★鍵だけでなく、**画素**まで一致することを確かめる。

    ⚠ 鍵はハッシュなので、たまたま合うことは無いが、
      「鍵の作り方だけ合っていて絵が違う」という取り違えは起こりうる。
    """
    from dq2rom.monsters.palette import load_nes_palette

    nes = load_nes_palette(
        PROJECT_ROOT / "tools" / "fceux" / "palettes" / "FCEUX.pal")
    tiles = RomTileSource(ROM).for_map(0x3F)
    cap = Capture.load(ASSETS / "capture-3.txt")
    for cx, cy, quad, group in _cells(cap):
        a = tiles.metatile(quad, group).rgba(nes)
        b = metatile_at(cap, cx, cy, ROM_PATTERN_HALF).rgba(nes)
        assert a == b, f"({cx},{cy}) の絵が違う"
        break                    # ★1マス見れば足りる（残りは鍵で確認済み）


# --- ⚠ 分からないものは None ------------------------------------------

@needs_rom
def test_全109マップで絵の材料がそろう():
    """★★ 2026-08-03 / Phase 1 の到達点。

    ⚠ 以前は境界タイルIDで絞っていて 74 件しか取れませんでした。
      ★`$D0AB: LDA $1F / STA $0C / JSR $8000` を読んで、
        **種別がそのまま索引**と分かり 109 件になりました。
    """
    source = RomTileSource(ROM)
    missing = [m for m in range(109) if source.for_map(m) is None]
    assert not missing, f"⚠ 取れない map: {[f'${m:02X}' for m in missing]}"
    assert source.why_not(0x07) is None
    assert source.why_not(0x3F) is None


@needs_rom
def test_範囲外のmap_idはNoneで理由も言う():
    """⚠⚠ **黙って何もしない**のが一番困る。★理由を言葉で返す。"""
    source = RomTileSource(ROM)
    assert source.for_map(0x99) is None
    assert source.why_not(0x99)


@needs_rom
def test_同じマップを何度聞いても作り直さない():
    """★1マップ 8KB あるので、覚えておく。"""
    source = RomTileSource(ROM)
    first = source.for_map(0x3F)
    assert source.for_map(0x3F) is first
    # ⚠ 分からなかったことも覚える（毎回 ROM を引き直さない）
    assert source.for_map(0x99) is None
    assert 0x99 in source._cache


@needs_rom
def test_覚えたものが他のマップへ混ざらない():
    """⚠ 洞窟の絵で街を描いてしまわないこと。"""
    source = RomTileSource(ROM)
    cave = source.for_map(0x3F)
    town = source.for_map(0x0B)
    assert cave.chr_data != town.chr_data
    assert cave.palette != town.palette


def test_背景は前半のパターンテーブル():
    """★ROM から組んだ CHR は地形を `$0900` に置く。ずらさない。"""
    assert ROM_PATTERN_HALF == 0


@needs_rom
def test_タイル4枚を渡す形になっている():
    """⚠⚠ **左上だけでは足りない**（2026-08-02 実測）。

    残り3枚の決まり方はマップごとに違った:
      ダンジョン `(4, -1, 3)` / 街 `(2, -1, 1)`、しかも例外あり。
    ★規則を1つに決めると街の飾りで間違えるので、4枚を受け取る。
    """
    tiles = RomTileSource(ROM).for_map(0x3F)
    mt = tiles.metatile((0xA1, 0xA5, 0xA0, 0xA4), 3)
    assert mt.top_left.tile_id == 0xA1
    assert mt.top_right.tile_id == 0xA5
    assert mt.bottom_left.tile_id == 0xA0
    assert mt.bottom_right.tile_id == 0xA4
    # ★並びを取り違えると別の鍵になる（＝取り違えは鍵で気づける）
    other = tiles.metatile((0xA1, 0xA0, 0xA5, 0xA4), 3)
    assert mt.key != other.key


@needs_rom
def test_パレット組が違えば別の絵になる():
    """★同じタイルでも組が違えば色が違う。鍵も分かれる。"""
    tiles = RomTileSource(ROM).for_map(0x3F)
    quad = (0xA1, 0xA5, 0xA0, 0xA4)
    keys = {tiles.metatile(quad, g).key for g in range(4)}
    # ⚠ パレットによっては同じ4色になる組があり得るので「4通り」とは言わない
    assert len(keys) >= 2


def test_ROMが無ければ読むときに分かる(tmp_path):
    """⚠ 作る時点では落とさず、**使う時点**で理由の分かる形にする。"""
    source = RomTileSource(tmp_path / "ない.nes")
    with pytest.raises(FileNotFoundError):
        source.for_map(0x3F)


def test_道具として素で使える():
    """★`MapTiles` は ROM 抜きでも組み立てられる（試験しやすさ）。"""
    tiles = MapTiles(map_id=0x99, chr_data=bytes(0x2000),
                     palette=bytes(16))
    mt = tiles.metatile((0x90, 0x91, 0x92, 0x93), 0)
    assert mt.map_id == 0x99
    # ★中身が全部 0 なら「黒観測」。⚠ 地形として保存してはいけない
    assert mt.is_blank
