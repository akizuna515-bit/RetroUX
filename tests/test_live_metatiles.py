"""遊んでいる最中に絵を用意する（2026-08-02 / 課題 #65）。

★★ 守りたい契約 ★★

  1. ⚠⚠ 見ていないマス（`_`）は作らない
  2. ⚠⚠ 黒観測は保存しない（指示書 §11.2）
  3. ⚠ まだ確かめていないマップは描かない（推測で埋めない）
  4. ★見送った数は必ず残る（黙って捨てない）
  5. ★同じ組み合わせは作り直さない
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.catalog import AssetStore
from retroux.core.bgmap.live import (
    CELL_CHARS, UNKNOWN_CELL, LiveMetatiles, Tally, parse_cells,
)
from retroux.core.bgmap.rom_assets import RomTileSource

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
PALETTE = PROJECT_ROOT / "tools" / "fceux" / "palettes" / "FCEUX.pal"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")


def _packed(cells, radius):
    """`{(dx,dy): "9文字"}` を並びにする。★無いところは読めない扱い。"""
    out = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            out.append(cells.get((dx, dy), UNKNOWN_CELL))
    return "".join(out)


def _live(tmp_path):
    from dq2rom.monsters.palette import load_nes_palette

    store = AssetStore(tmp_path)
    store.prepare()
    return LiveMetatiles(RomTileSource(ROM), store, load_nes_palette(PALETTE))


# --- 並びを解く --------------------------------------------------------

def test_1マスは9文字():
    assert CELL_CHARS == 9
    assert UNKNOWN_CELL == "_________"


def test_読めるマスだけ取り出す():
    packed = _packed({(0, 0): "A1A5A0A43"}, radius=1)
    got = parse_cells(packed, 1)
    # ⚠ 読めないマスは**入らない**。★「0 と不明を混ぜない」
    assert got == {(0, 0): ((0xA1, 0xA5, 0xA0, 0xA4), 3)}


def test_数が合わなければ使わない():
    """⚠ 形式が違うものを無理に読まない（ずれた絵を描くより何もしない）。"""
    assert parse_cells("A1A5A0A43", 1) == {}
    assert parse_cells(None, 1) == {}
    assert parse_cells("", 7) == {}


def test_16進でないものは捨てるが落ちない():
    packed = _packed({(0, 0): "ZZZZZZZZ0"}, radius=1)
    assert parse_cells(packed, 1) == {}


def test_パレット組は0から3():
    """⚠ 4 以上は変。★読めたことにしない。"""
    packed = _packed({(0, 0): "A1A5A0A49"}, radius=1)
    assert parse_cells(packed, 1) == {}


def test_並びの順は上から下_左から右():
    packed = _packed({(-1, -1): "909192931",
                      (1, 1): "A0A1A2A32"}, radius=1)
    got = parse_cells(packed, 1)
    assert got[(-1, -1)] == ((0x90, 0x91, 0x92, 0x93), 1)
    assert got[(1, 1)] == ((0xA0, 0xA1, 0xA2, 0xA3), 2)


# --- ★★ ROM から絵を作る ★★ -----------------------------------------

@needs_rom
def test_見たマスの絵をROMから作れる(tmp_path):
    """★★ **これで採取が要らなくなる。**"""
    live = _live(tmp_path)
    key = live.key_for(0x3F, (0xA1, 0xA5, 0xA0, 0xA4), 3)
    assert key is not None
    # ★PNG が倍率ぶんそろっている
    assert live.store.image_path(key, "1x") is not None
    assert live.store.image_path(key, "4x") is not None
    assert live.tally.made == 1


@needs_rom
def test_同じ組み合わせは作り直さない(tmp_path):
    live = _live(tmp_path)
    a = live.key_for(0x3F, (0xA1, 0xA5, 0xA0, 0xA4), 3)
    b = live.key_for(0x3F, (0xA1, 0xA5, 0xA0, 0xA4), 3)
    assert a == b
    assert live.tally.made == 1
    assert live.tally.reused == 1


@needs_rom
def test_城も描けるようになった(tmp_path):
    """★★ 2026-08-03 / Phase 1。

    ⚠ 以前は「城 `$07` は土台が分かっていない」ので描けませんでした。
      ★`$D0AB: LDA $1F / STA $0C / JSR $8000` を読んで、
        **種別がそのまま CHR 索引**と分かり、全109マップで描けます。
    """
    live = _live(tmp_path)
    assert live.key_for(0x07, (0xA1, 0xA5, 0xA0, 0xA4), 3) is not None
    assert live.tally.no_tileset == 0


@needs_rom
def test_表の外のmap_idは描かない(tmp_path):
    """⚠⚠ **推測で描かない。** ★理由は数に残る（黙って捨てない）。"""
    live = _live(tmp_path)
    assert live.key_for(0x99, (0xA1, 0xA5, 0xA0, 0xA4), 3) is None
    assert live.tally.no_tileset == 1
    # ★2回目も数に出る（見えなくならない）
    assert live.key_for(0x99, (0xA1, 0xA5, 0xA0, 0xA4), 3) is None
    assert live.tally.no_tileset == 2


@needs_rom
def test_黒観測は保存しない(tmp_path):
    """⚠⚠ 指示書 §11.2。★暗転中や未描画のものを地形にしない。"""
    live = _live(tmp_path)
    # ★$5F は「空白」。4枚とも空白なら地の色だけ
    assert live.key_for(0x3F, (0x5F, 0x5F, 0x5F, 0x5F), 0) is None
    assert live.tally.blank == 1
    # ⚠ 覚えない。★次に同じ場所が明るく見えたときに拾えるように
    assert not live._known


@needs_rom
def test_見えている範囲をまとめて作れる(tmp_path):
    live = _live(tmp_path)
    packed = _packed({(0, 0): "A1A5A0A43",
                      (1, 0): "A3A7A2A63"}, radius=1)
    got = live.keys_for_view(0x3F, packed, 1)
    assert set(got) == {(0, 0), (1, 0)}
    assert len(set(got.values())) == 2       # ★別の絵になる
    # ★読めなかった 7 マスも数に残る（黙って捨てない）
    assert live.tally.unreadable == 9 - 2


@needs_rom
def test_描けなかったマスは入らない(tmp_path):
    """⚠ 「入っていない」ことが「まだ描けない」の意。空で埋めない。"""
    live = _live(tmp_path)
    packed = _packed({(0, 0): "5F5F5F5F0"}, radius=1)   # ★黒観測
    assert live.keys_for_view(0x3F, packed, 1) == {}
    assert live.tally.blank == 1


# --- ★見送った数を残す -------------------------------------------------

def test_数え上げをまとめて言える():
    t = Tally(made=1, reused=2, blank=3, unreadable=4, no_tileset=5)
    text = t.summary()
    for n in ("1", "2", "3", "4", "5"):
        assert n in text
    other = Tally(made=1)
    t.merge(other)
    assert t.made == 2
