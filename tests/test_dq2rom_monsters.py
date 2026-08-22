"""敵の絵の展開・描画・照合（2026-07-29）。

★★ 守りたい契約 ★★

  1. **ブロックの区切り**を間違えない（1バイトずれると以降が全部崩れる）
  2. **4通りの反転**を取り違えない（上下反転はプレーンをまたがない）
  3. **ビットマップの向き**を間違えない（先に読むバイトが下位）
  4. パレット番号 0 は**透明**
  5. 分かっていないことは `confidence` を下げる（推測で埋めない）
  6. 照合は**色ではなくパレット番号**で行う

★疑似データのテストは常に走る。ROM を使うものは `DQ2_ROM_PATH`（既定
  `work/rom/DQ2_J.nes`）があるときだけ（指示書 4.4 / 16.2）。
"""

from __future__ import annotations

import dataclasses
import os
import pathlib

import pytest

from dq2rom import ines, locator
from dq2rom.monsters import png, validator
from dq2rom.monsters.decoder import (
    BANK1_PRG_BASE, DecodeError, OTHER_Y_BIAS, consumed_end, decode_block,
    decode_monster, flip_bits, make_variants,
)
from dq2rom.monsters.palette import (
    MonsterPalettes, PaletteError, load_nes_palette, read_monster_palettes,
)
from dq2rom.monsters.renderer import render, tile_indices
from dq2rom.provenance import Confidence

# --- 道具 -------------------------------------------------------------


def fake_prg(pieces: dict[int, bytes], size: int = 0x20000) -> bytes:
    """PRG を作る。`pieces` は {PRG オフセット: バイト列}。"""
    buf = bytearray(size)
    for off, data in pieces.items():
        buf[off:off + len(data)] = data
    return bytes(buf)


def block_bytes(records: list[bytes], fill: int | None, bitmap: int | None,
                payload: bytes) -> bytes:
    """1ブロックぶんのバイト列を組み立てる（テスト用）。"""
    out = bytearray()
    for r in records:
        out += r
    if bitmap is not None:
        if fill is not None:
            out.append(fill)
        out.append(bitmap & 0xFF)          # ★先に読むほうが下位
        out.append(bitmap >> 8)
    out += payload
    return bytes(out)


SOLID = bytes(range(0x10, 0x20))           # 16バイトの分かりやすいタイル


# --- 1. ブロックの区切り ------------------------------------------------


def test_literal_block_reads_16_bytes():
    """最後の記録の bit3=0 なら 16バイトそのまま。"""
    data = block_bytes([bytes([0xC0, 0x11])], None, None, SOLID)
    prg = fake_prg({BANK1_PRG_BASE: data})
    b = decode_block(prg, 0x8000)
    assert b.literal
    assert b.variants[0] == SOLID
    assert b.prg_end - b.prg_start == len(data)


def test_bitmap_block_fills_the_zero_bits():
    """bit3=1・bit0=1 なら「埋める値」を1バイト読み、16ビットで読む場所を決める。"""
    # 上位から 1,0,1,0,... -> 8バイトだけ読む
    data = block_bytes([bytes([0xC9, 0x11])], 0xAA, 0b1010101010101010,
                       bytes(range(0x30, 0x38)))
    prg = fake_prg({BANK1_PRG_BASE: data})
    b = decode_block(prg, 0x8000)
    assert not b.literal
    assert b.fill == 0xAA
    assert b.variants[0] == bytes([0x30, 0xAA, 0x31, 0xAA, 0x32, 0xAA, 0x33, 0xAA,
                                   0x34, 0xAA, 0x35, 0xAA, 0x36, 0xAA, 0x37, 0xAA])


def test_bitmap_without_fill_byte_uses_zero():
    """bit3=1・bit0=0 なら「埋める値」は読まず $00。"""
    data = block_bytes([bytes([0xC8, 0x11])], None, 0b1000000000000000,
                       bytes([0x77]))
    prg = fake_prg({BANK1_PRG_BASE: data})
    b = decode_block(prg, 0x8000)
    assert b.variants[0] == bytes([0x77]) + bytes(15)


def test_bitmap_byte_order():
    """⚠★ 16ビットは**先に読むバイトが下位**。逆にすると絵が崩れる。"""
    # bitmap=0x0001 -> 上位から見ると最後の1ビットだけ 1
    raw = bytearray()
    raw += bytes([0xC8, 0x11])
    raw += bytes([0x01, 0x00])             # 下位=$01, 上位=$00
    raw += bytes([0x99])
    prg = fake_prg({BANK1_PRG_BASE: bytes(raw)})
    b = decode_block(prg, 0x8000)
    assert b.bitmap == 0x0001
    assert b.variants[0] == bytes(15) + bytes([0x99])


def test_record_with_bit6_clear_has_two_extra_bytes():
    """bit6=0 は続き2バイト、bit6=1 は続き1バイト。ここを間違えると全部ずれる。"""
    data = block_bytes([bytes([0x00, 0x10, 0x50]), bytes([0xC0, 0x23])],
                       None, None, SOLID)
    prg = fake_prg({BANK1_PRG_BASE: data})
    b = decode_block(prg, 0x8000)
    assert len(b.placements) == 2
    assert b.placements[0].raw == (0x10, 0x50)
    assert b.placements[1].raw == (0x23,)
    assert b.prg_end - b.prg_start == len(data)


def test_blocks_chain_without_gaps():
    two = (block_bytes([bytes([0xC0, 0x11])], None, None, SOLID)
           + block_bytes([bytes([0xC0, 0x22])], None, None, SOLID))
    prg = fake_prg({BANK1_PRG_BASE: two})
    blocks = decode_monster(prg, 0x8000, 2)
    assert blocks[0].prg_end == blocks[1].prg_start
    assert consumed_end(blocks) == 0x8000 + len(two)


def test_records_that_never_end_are_rejected():
    """★終端ビットが来ない壊れたデータで無限ループしないこと。"""
    prg = fake_prg({BANK1_PRG_BASE: bytes([0x40, 0x00]) * 300})
    with pytest.raises(DecodeError, match="256"):
        decode_block(prg, 0x8000)


def test_pointer_outside_the_window_is_rejected():
    prg = fake_prg({})
    with pytest.raises(DecodeError, match="窓の外"):
        decode_block(prg, 0x4000)


def test_running_past_bank1_is_rejected():
    """★bank 1 の外を読み始めたら止める（黙って隣のバンクを読まない）。"""
    data = block_bytes([bytes([0xC0, 0x11])], None, None, SOLID)
    prg = fake_prg({0x8000 - 4: data})
    with pytest.raises(DecodeError, match="bank 1 の外"):
        decode_block(prg, 0xBFFC)


def test_zero_count_is_rejected():
    prg = fake_prg({BANK1_PRG_BASE: block_bytes([bytes([0xC0, 0x11])],
                                                None, None, SOLID)})
    with pytest.raises(DecodeError):
        decode_monster(prg, 0x8000, 0)


# --- 2. 4通りの反転 ----------------------------------------------------


def test_flip_bits():
    assert flip_bits(0b1000_0000) == 0b0000_0001
    assert flip_bits(0b1010_0000) == 0b0000_0101
    assert flip_bits(0xFF) == 0xFF
    assert flip_bits(0x00) == 0x00


def test_variants_are_normal_h_v_hv():
    tile = bytes(range(16))
    normal, h, v, hv = make_variants(tile)
    assert normal == tile
    assert h == bytes(flip_bits(b) for b in tile)
    # ★上下反転は「8バイトずつ」逆順。プレーンをまたいではいけない
    assert v == bytes([7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8])
    assert hv == bytes(flip_bits(b) for b in v)


def test_vertical_flip_does_not_cross_the_planes():
    """⚠ 16バイトを丸ごと逆順にすると、色が入れ替わって別の絵になる。"""
    tile = bytes([0xFF] * 8 + [0x00] * 8)      # 全部パレット1
    _n, _h, v, _hv = make_variants(tile)
    assert v == tile, "プレーンをまたいで逆順にしている"


def test_variants_reject_wrong_length():
    with pytest.raises(DecodeError):
        make_variants(bytes(15))


# --- 3. 置き方 ---------------------------------------------------------


def test_grid_placement_is_row_then_column():
    data = block_bytes([bytes([0xC0, 0x53])], None, None, SOLID)
    prg = fake_prg({BANK1_PRG_BASE: data})
    p = decode_block(prg, 0x8000).placements[0]
    assert p.on_grid
    assert (p.x, p.y) == (3 * 8, 5 * 8)


def test_pixel_placement_subtracts_the_bias():
    """⚠★ 期待値に `OTHER_Y_BIAS` を使わない。

    最初この行を `0x57 - OTHER_Y_BIAS` と書いたら、**下駄を変えても緑のまま**
    だった（`research/probes/active/break_gfx.py` が捕まえた）。定数で定数を検算しても意味がない。
    下駄 $38 は撮影から割り出した値なので、**実測値を直に書く**。
    """
    data = block_bytes([bytes([0x80, 0x09, 0x57])], None, None, SOLID)
    prg = fake_prg({BANK1_PRG_BASE: data})
    p = decode_block(prg, 0x8000).placements[0]
    assert not p.on_grid
    assert (p.x, p.y) == (0x09, 0x1F)      # 0x57 - 0x38
    assert OTHER_Y_BIAS == 0x38


@pytest.mark.parametrize("head,expected", [
    (0xC0, 0), (0xC2, 1), (0xC4, 2), (0xC6, 3), (0xC9, 0), (0xCA, 1),
])
def test_variant_comes_from_bits_1_and_2(head, expected):
    data = block_bytes([bytes([head, 0x11])], None,
                       0xFFFF if head & 0x08 else None,
                       SOLID)
    if head & 0x08:
        data = block_bytes([bytes([head, 0x11])], 0x00, 0xFFFF, SOLID)
    prg = fake_prg({BANK1_PRG_BASE: data})
    assert decode_block(prg, 0x8000).placements[0].variant == expected


# --- 4. 色と透明 -------------------------------------------------------


def test_tile_indices_reads_both_planes():
    tile = bytes([0b1010_0000] + [0] * 7 + [0b1100_0000] + [0] * 7)
    px = tile_indices(tile)
    assert px[0][:4] == [3, 2, 1, 0]


def pal_file(tmp_path) -> pathlib.Path:
    """64色の .pal を作る（i 番目 = (i, i*2, i*3)）。"""
    p = tmp_path / "t.pal"
    p.write_bytes(bytes(v & 0xFF for i in range(64)
                        for v in (i, i * 2, i * 3)))
    return p


def test_index_zero_is_transparent(tmp_path):
    """★0 番は透明。図鑑に貼れるようにする（指示書 6.1）。"""
    tile = bytes([0b1000_0000] + [0] * 15)     # 左上だけ 1、他は 0
    data = block_bytes([bytes([0xC0, 0x00])], None, None, tile)
    prg = fake_prg({BANK1_PRG_BASE: data})
    blocks = decode_monster(prg, 0x8000, 1)
    nes = load_nes_palette(pal_file(tmp_path))
    got = render(blocks, MonsterPalettes(0x10, (), ((5, 6, 7),)), nes)
    assert got.rows[0][0][3] == 255
    assert got.rows[0][1] == (0, 0, 0, 0)


def test_grid_layer_uses_the_high_group(tmp_path):
    """★実測: 格子のタイルは高位グループの色で描かれている。"""
    tile = bytes([0xFF] + [0] * 15)            # 全部パレット1
    data = block_bytes([bytes([0xC0, 0x00])], None, None, tile)
    prg = fake_prg({BANK1_PRG_BASE: data})
    blocks = decode_monster(prg, 0x8000, 1)
    nes = load_nes_palette(pal_file(tmp_path))
    got = render(blocks, MonsterPalettes(0x11, ((1, 2, 3),), ((9, 10, 11),)), nes)
    assert got.rows[0][0][:3] == nes.rgb(9)


def test_missing_palette_skips_instead_of_guessing(tmp_path):
    """★宣言されていないレイヤーは**推測で色を作らず**描かない。"""
    tile = bytes([0xFF] + [0] * 15)
    data = block_bytes([bytes([0x80, 0x00, OTHER_Y_BIAS])], None, None, tile)
    prg = fake_prg({BANK1_PRG_BASE: data})
    blocks = decode_monster(prg, 0x8000, 1)
    nes = load_nes_palette(pal_file(tmp_path))
    got = render(blocks, MonsterPalettes(0x10, (), ((5, 6, 7),)), nes)
    assert got.skipped == 1
    assert got.confidence is Confidence.TENTATIVE


def test_placement_picks_its_palette_by_head_bits(tmp_path):
    """★2026-08-22（RX-0051）: 複数パレットは置き方の bit4-5 で選ぶ。

    ⚠ 以前は「どれを使うか未解明」として先頭を当て、確度を PROBABLE に落としていた。
      いまは根拠（bit4-5 が複数パレットの体でだけ立ち、値はパレット数未満）があるので
      確度は落とさず、注記だけ残す。宣言より大きい番号は描かない（推測しない）。
    """
    tile = bytes([0xFF] + [0] * 15)
    # 2 枚: bit4-5 = 0 と 1（head 0x40 | 0x10 = 0x50）
    data = block_bytes([bytes([0x40, 0x00]), bytes([0xD0, 0x01])], None, None, tile)
    prg = fake_prg({BANK1_PRG_BASE: data})
    blocks = decode_monster(prg, 0x8000, 1)
    assert [p.palette for p in blocks[0].placements] == [0, 1]
    nes = load_nes_palette(pal_file(tmp_path))
    many = render(blocks, MonsterPalettes(0x20, (), ((1, 2, 3), (4, 5, 6))), nes)
    assert many.confidence is Confidence.CONFIRMED
    assert any("bit4-5" in n for n in many.notes)
    # ★1 枚目はパレット 1（色 1..3）、2 枚目はパレット 2（色 4..6）で描かれている
    assert many.rows[0][0] != many.rows[0][8]
    # ⚠ 宣言が 1 本しか無いのに番号 1 を指すタイルは描かない（推測で先頭へ丸めない）
    single = render(blocks, MonsterPalettes(0x10, (), ((1, 2, 3),)), nes)
    assert single.skipped == 1 and single.confidence is Confidence.TENTATIVE


# --- 5. パレット表 -----------------------------------------------------


def test_palette_header_nibbles():
    body = bytes([0x21]) + bytes([1, 2, 3]) + bytes([4, 5, 6]) + bytes([7, 8, 9])
    prg = fake_prg({0x10000: body})
    got = read_monster_palettes(prg, 0x8000)
    assert got.low == ((1, 2, 3),)                    # 低位ニブル = 1個
    assert got.high == ((4, 5, 6), (7, 8, 9))         # 高位ニブル = 2個
    assert got.ambiguous


def test_palette_with_no_low_group():
    prg = fake_prg({0x10000: bytes([0x10]) + bytes([1, 2, 3])})
    got = read_monster_palettes(prg, 0x8000)
    assert got.low == ()
    assert got.for_layer(on_grid=False) is None
    assert got.for_layer(on_grid=True) == (1, 2, 3)


def test_palette_file_must_exist(tmp_path):
    with pytest.raises(PaletteError, match="ありません"):
        load_nes_palette(tmp_path / "nope.pal")


def test_palette_file_must_be_long_enough(tmp_path):
    p = tmp_path / "short.pal"
    p.write_bytes(bytes(10))
    with pytest.raises(PaletteError, match="短すぎ"):
        load_nes_palette(p)


def test_screenshot_scaling_is_separate(tmp_path):
    """★FCEUX の撮影は色を 255/252 倍している。**表そのものは変えない**。"""
    nes = load_nes_palette(pal_file(tmp_path))
    shot = nes.as_screenshot()
    assert nes.rgb(63)[0] == 63
    assert shot.rgb(63)[0] == round(63 * 255 / 252)


# --- 6. PNG ------------------------------------------------------------


def test_png_round_trip(tmp_path):
    rows = [[(255, 0, 0, 255), (0, 255, 0, 255)],
            [(0, 0, 255, 255), (0, 0, 0, 0)]]
    path = png.write(tmp_path / "a.png", rows)
    w, h, got = validator.read_png_rgb(path)
    assert (w, h) == (2, 2)
    assert got[0][0] == (255, 0, 0)
    assert got[1][0] == (0, 0, 255)


def test_png_scale_is_nearest(tmp_path):
    rows = [[(10, 20, 30, 255), (40, 50, 60, 255)]]
    path = png.write(tmp_path / "b.png", rows, factor=3)
    w, h, got = validator.read_png_rgb(path)
    assert (w, h) == (6, 3)
    assert got[0][0] == got[0][2] == (10, 20, 30)
    assert got[0][3] == (40, 50, 60)
    assert got[2][0] == (10, 20, 30)


def test_png_rejects_ragged_rows():
    with pytest.raises(ValueError):
        png.encode([[(0, 0, 0, 0)], [(0, 0, 0, 0), (1, 1, 1, 1)]])


def test_png_reader_rejects_non_png(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"not a png at all")
    with pytest.raises(validator.ValidateError):
        validator.read_png_rgb(p)


# --- 7. 照合 -----------------------------------------------------------


def test_blank_cells_count_as_matching():
    """★★ タイルが置かれていない格子は背景のまま = 撮影では真っ黒。

    これを不一致と数えると、**正しいのに落ちる**（ID 0F で実際に起きた）。
    """
    black = (0, 0, 0)
    white = (255, 255, 255)
    shot = [[black] * 8 for _ in range(8)]
    got = validator.compare({validator.BLANK}, 8, 8, shot)
    assert got.judged == 0 or got.matched == got.judged
    # 色が1種だけなら判定しない（情報が無い）
    shot[0][0] = white
    got = validator.compare({validator.BLANK}, 8, 8, shot)
    assert got.judged >= 0


def test_cells_with_extra_colors_are_skipped_and_counted():
    """★★ 判定から外したマスの数を**必ず報告する**（黙って捨てない）。"""
    black, a, b, c, d = ((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0))
    shot = [[black] * 16 for _ in range(8)]
    for y in range(8):
        for x in range(8, 16):
            shot[y][x] = (a, b, c, d)[(x + y) % 4]      # 5色目が混ざる
    got = validator.compare({validator.BLANK}, 16, 8, shot)
    assert got.skipped >= 1


# --- 8. 本物の ROM（あるときだけ）--------------------------------------

ROM_PATH = os.environ.get("DQ2_ROM_PATH") or "work/rom/DQ2_J.nes"
PAL_PATH = pathlib.Path("tools/fceux/palettes/FCEUX.pal")
CAPTURES = pathlib.Path("work/monster-art")
#: ⚠ **フォルダの有無で見張らないこと**（RX-0100 / 2026-08-22）。
#:   遊ぶと `work/monster-art/raw/` だけが先に作られるので、
#:   `CAPTURES.exists()` は真になるのに**絵は0枚**という状態が起きる。
#:   ★開発機には83枚あるので、この穴は一度も表に出なかった。
_SHOTS = sorted(CAPTURES.glob("*.png")) if CAPTURES.exists() else []
needs_shots = pytest.mark.skipif(not _SHOTS, reason="撮影した絵が1枚も無い")

needs_rom = pytest.mark.skipif(
    not pathlib.Path(ROM_PATH).exists(),
    reason=f"ROM がありません（{ROM_PATH}）")


@pytest.fixture(scope="module")
def real():
    rom = ines.load(ROM_PATH)
    table = locator.locate_monster_graphics_table(rom)
    entries = locator.read_monster_graphics_table(rom, table.prg_offset)
    return rom, entries


@pytest.fixture(scope="module")
def validated(real):
    """撮影との照合を **1回だけ** 行う（2026-08-02）。

    ★★ **測って分かったこと** ★★
      テスト全体 650 秒のうち **616 秒（95%）がこの照合3回**だった:
        211.68s test_most_captures_can_actually_be_judged
        207.45s test_real_matches_the_captures
        197.34s test_a_full_match_is_never_called_insufficient
      残る 1344 件は合計 34 秒。

    ⚠ 3件とも `validator.validate_dir(...)` に**同じ引数**を渡して
      同じ計算をやり直していた。★ここで1回にまとめる。

    ⚠ 並列化（pytest-xdist）では解けない。重いのが3件しかないので
      3コアまでしか使えず、212 秒止まりになる。
    """
    rom, entries = real
    return validator.validate_dir(rom.prg, entries, CAPTURES, decode_monster)


@needs_rom
def test_real_every_picture_ends_exactly_where_the_next_begins(real):
    """★★ これが区切り方の裏取り。**索引表は展開に使っていない**。

    ⚠ count は敵ごとに違う。同じ絵でも**色違いの上位種のほうが多い**ので、
      その絵を使う敵の**最大 count** で読む。
    """
    rom, entries = real
    live = [e for e in entries if e.in_range and e.monster_id != 0]
    by_addr: dict[int, list] = {}
    for e in live:
        by_addr.setdefault(e.graphics_addr, []).append(e)
    addrs = sorted(by_addr)
    assert len(addrs) == 38

    for addr, nxt in zip(addrs, addrs[1:]):
        count = max(e.count for e in by_addr[addr])
        blocks = decode_monster(rom.prg, addr, count)
        assert consumed_end(blocks) == nxt, (
            f"${addr:04X} の展開が ${consumed_end(blocks):04X} で終わった"
            f"（次の絵は ${nxt:04X}）")


@needs_rom
def test_real_every_monster_decodes(real):
    rom, entries = real
    live = [e for e in entries if e.in_range and e.monster_id != 0]
    assert len(live) == 82
    for e in live:
        blocks = decode_monster(rom.prg, e.graphics_addr, e.count)
        assert len(blocks) == e.count
        assert any(p.on_grid for b in blocks for p in b.placements), (
            f"ID {e.monster_id:02X} に格子タイルが1枚も無い")


@needs_rom
def test_real_all_palettes_are_readable(real):
    rom, entries = real
    live = [e for e in entries if e.in_range and e.monster_id != 0]
    ambiguous = 0
    for e in live:
        p = read_monster_palettes(rom.prg, e.palette_addr)
        assert p.high, f"ID {e.monster_id:02X} に高位グループが無い"
        assert all(0 <= c < 64 for grp in (p.low, p.high) for e2 in grp
                   for c in e2)
        ambiguous += p.ambiguous
    # ★複数パレットを持つのは6体だけ。増えていたら前提が変わっている
    assert ambiguous == 6


@needs_rom
@pytest.mark.skipif(not PAL_PATH.exists(), reason="FCEUX の .pal が無い")
def test_real_every_monster_renders(real, tmp_path):
    rom, _entries = real
    from dq2rom.monsters import extractor

    nes = load_nes_palette(PAL_PATH)
    results = extractor.extract(rom, tmp_path, nes)
    assert len(results) == 82
    assert all(r.ok for r in results), [r.reason for r in results if not r.ok]
    assert all(r.rendered.width > 0 and r.rendered.height > 0 for r in results)
    sheet = extractor.contact_sheet(results, tmp_path / "sheet.png")
    assert sheet.exists()


@needs_rom
@pytest.mark.parametrize("mid,raw,expected", [
    # ★撮影から割り出した位置（`research/probes/archived/probe_gfx4.py`）。
    #   撮影の切り抜きの中でタイルが実際に出ていた場所を、
    #   格子の原点（列0・行0 = 画素 (0,0)）に戻した値。
    (0x0F, (0x08, 0x64), (8, 44)),
    (0x17, (0x08, 0x64), (8, 44)),
    (0x12, (0x09, 0x57), (9, 31)),
    (0x12, (0x11, 0x57), (17, 31)),
])
def test_real_pixel_layer_lands_where_the_capture_shows_it(real, mid, raw, expected):
    """★画素で置くタイル（bit6=0）の位置。**撮影で見えた場所**と合うこと。

    ⚠ この層だけは格子ほど確かではない（撮影3枚から式を作った）。
      だからこそ、その3枚を金型として固定しておく。
    """
    rom, entries = real
    e = entries[mid]
    blocks = decode_monster(rom.prg, e.graphics_addr, e.count)
    spots = [(p.x, p.y) for b in blocks for p in b.placements
             if not p.on_grid and p.raw == raw]
    assert spots, f"ID {mid:02X} に記録 {raw} が無い"
    assert expected in spots, f"{raw} -> {spots}（期待 {expected}）"


@needs_rom
@needs_shots
def test_real_matches_the_captures(validated):
    """★★ 実機で撮った絵と、隠れていないマスが**全部**一致すること。

    ## ⚠⚠ このテストは**遊ぶたびに材料が変わります**

    `work/monster-art/` は、遊んでいる最中に増えます。
    2026-08-01 に敵ID 0x30 の絵が撮れ、**判定できたマスが4つ**しかない
    まま2つ合わずに、テスト全体が赤くなりました（他の敵は 9〜28 マス）。

    ★4マスでは「展開が間違っている」とも「撮影が悪い」とも言えません。
      材料不足を「合わない」に混ぜると、遊ぶたびに赤くなります。

    ★★ **3つに分けます**（合う / 合わない / 材料不足）★★
      ⚠ 黙って除外しません。材料不足は**件数を出します**。
    """
    got = validated
    assert got, "照合できる撮影が1枚も無い"

    thin = [c for c in got if not c.enough]
    # ★★ ⚠⚠ **形が完全一致なら、それが決定的**（2026-08-14）★★
    #
    #   `ok`（タイルの集合との突き合わせ）は `on_grid` のレイヤーしか
    #   見ないので、⚠ **別レイヤーが重なったマスを「合わない」と言う**。
    #
    #   実測（シドー 0x52）:
    #       タイルの集合   34/37 マス      ⚠ 3マスが不一致
    #       形             6072/6072 画素  ★完全一致
    #
    #   ★合わなかった3マスは、どれも「ROM の形＋別レイヤーの画素」だった。
    #     ⚠ 展開は正しく、**比べ方が足りていなかった**。
    overlap = [c for c in got if c.enough and not c.ok and c.shape_ok]
    bad = [c for c in got if c.enough and not c.ok and not c.shape_ok]

    # ★材料不足は**黙って捨てない**。何枚あるかを必ず出す。
    print(f"\n照合 {len(got)} 枚: 一致 {len(got) - len(thin) - len(bad)} / "
          f"不一致 {len(bad)} / 材料不足 {len(thin)}"
          f"（判定できたマスが {validator.MIN_JUDGED} 未満）")
    print(f"  ★形が完全一致: {sum(1 for c in got if c.shape_ok)}/{len(got)}")
    for c in thin:
        print(f"  材料不足 ID {c.monster_id:02X}: "
              f"{c.matched}/{c.judged} マス ★撮り直すと判定できます")
    for c in overlap:
        # ★黙って通さない。**なぜ通したか**を必ず出す。
        print(f"  ★ID {c.monster_id:02X}: タイルの集合では {c.matched}/{c.judged} だが、"
              f"形は {c.shape_matched}/{c.shape_total} で完全一致"
              "（⚠ 別レイヤーが重なったマス）")

    assert not bad, [(f"{c.monster_id:02X}", c.matched, c.judged) for c in bad]


@needs_rom
@needs_shots
def test_形は撮影と1画素も違わない(validated):
    """★★★ **展開が正しいことの決定的な裏取り**（2026-08-14）★★★

    ## ⚠ なぜタイルの集合では足りないか

      実機の画面は**2つのレイヤーが重なった姿**。
      `placed_tiles()` は `on_grid` の側しか集めないので、
      ⚠ 重なったマスは「ROM に無いタイル」に見える。

    ## ★ 形なら色にもレイヤーにも左右されない

      色はレイヤーごとのパレットの当て方で変わる
      （⚠ シドーでは 448 画素で桃色と鮭色が入れ替わっていた）。
      ★形は変わらない。

    ## 実測（2026-08-14 / 79 枚）

        ★形が完全一致  76 枚 / 残り 3 枚（30 / 4B / 4E）は検査器の限界（下の注記。★別の検査で色まで一致）

    ⚠ **合わない枚数が増えたら赤くする。** ★減るぶんには構わない。
    """
    got = validated
    fit = [c for c in got if c.shape_ok]
    off = [c for c in got if not c.shape_ok]
    print(f"\n★形が完全一致: {len(fit)}/{len(got)}")
    for c in off:
        print(f"  ⚠ ID {c.monster_id:02X}: {c.shape_matched}/{c.shape_total}"
              f"（{100 * c.shape_rate:.1f}%）"
              f" 撮影 {c.shot_size} / ROM {c.expected_size}")
    # ★★ 2026-08-22（RX-0052）: 既知の 3 枚（30 / 4B / 4E）は、この検査器（validator）の
    #   **モデルの限界**で合わない: 黒を透明とみなす（体の中の黒い画素を形から外す）・
    #   色は 7 種まで（4E はパレット 3 本で 9 色）。★生の画面に ROM の絵を当てはめる
    #   色込みの突き合わせ（下の test_既知3枚は生画面と色まで完全一致する）では 3 体とも
    #   **1 画素も違わない**。ここでは件数の歯止めだけ残す。
    known = {0x30, 0x4B, 0x4E}
    surprise = [c for c in off if c.monster_id not in known]
    assert not surprise, [f"{c.monster_id:02X}" for c in surprise]
    assert len(off) <= len(known), [f"{c.monster_id:02X}" for c in off]


@needs_rom
@pytest.mark.skipif(not (CAPTURES / "52.png").exists(),
                    reason="シドーの撮影が無い")
def test_形の突き合わせは重なりに強い(real):
    """⚠⚠ ★上の逃がし方が**広すぎない**ことを確かめる。

    ★1画素でも違えば `shape_ok` が False になること。
      ⚠ ここが緩いと、本当の展開ミスを見逃す。
    """
    rom, entries = real
    entry = entries[0x52]
    blocks = decode_monster(rom.prg, entry.graphics_addr, entry.count)
    mask = validator.silhouette(blocks)
    w, h, shot = validator.read_png_rgb(CAPTURES / "52.png")
    same, total, off = validator.compare_shape(shot, mask)
    assert (same, total) == (6072, 6072), (same, total)

    # ⚠ わざと1画素だけ塗る → ★必ず合わなくなる
    broken = [row[:] for row in shot]
    broken[0][0] = (1, 2, 3) if broken[0][0] == (0, 0, 0) else (0, 0, 0)
    same2, total2, _ = validator.compare_shape(broken, mask)
    assert same2 < total2, "★1画素変えても一致のまま（歯止めが効いていない）"


@needs_rom
@needs_shots
def test_most_captures_can_actually_be_judged(validated):
    """⚠ 「材料不足」が増えすぎたら、それ自体が異常。

    ★★ 逃げ道を作ったまま放置しない ★★
      材料不足を許した以上、**それが多数派になっていないか**を見張る。
      半分以上が判定できないなら、撮り方か展開のどちらかが壊れている。
    """
    got = validated
    thin = [c for c in got if not c.enough]
    assert len(thin) * 2 < len(got), (
        f"{len(got)} 枚中 {len(thin)} 枚が材料不足。"
        "撮り方か展開のどちらかが壊れています")


@needs_rom
@needs_shots
def test_a_full_match_is_never_called_insufficient(validated):
    """★★ **成功は成功。失敗したときだけ材料の量を問う。** ★★

    ⚠⚠ 2026-08-01 に一度これを間違えました。「judged が少なければ
      材料不足」と書いたところ、13枚がそちらへ落ち、**うち12枚は
      6/6・7/7 で完全に一致**していました。
      前は合格だったものを、こちらの都合で判定不能に落としたのです。

    ★逃げ道を作るときは、**それが必要な場合にだけ効く**ことを確かめる。
    """
    got = validated
    wrong = [c for c in got if c.ok and c.verdict != "match"]
    assert not wrong, [
        (f"{c.monster_id:02X}", c.matched, c.judged, c.verdict) for c in wrong]


# --- 色まで含めた突き合わせ（RX-0051 / 2026-08-22）----------------------------
#
# ★形は 1 画素も違わなかったが、シドーは **色が 448 画素（7.4%）入れ替わっていた**。
#   原因: パレットを複数持つ体（6 体）で、置き方の先頭バイト bit4-5 がどのパレットを
#   使うかを指しているのに、renderer は先頭のパレットを全タイルに当てていた。
#   ★bit4-5 が 0 以外になるのはその 6 体だけで、値は常にパレット数未満（根拠）。

def _placement_palette_bits_only_for_multi_palette_monsters(rom, entries):
    from dq2rom.monsters import decoder as dec
    from dq2rom.monsters.palette import read_monster_palettes
    out = {}
    for e in entries:
        if e.monster_id == 0 or not e.in_range:
            continue
        try:
            pal = read_monster_palettes(rom.prg, e.palette_addr)
            blocks = dec.decode_monster(rom.prg, e.graphics_addr, e.count)
        except Exception:                               # noqa: BLE001
            continue
        used = {p.palette for b in blocks for p in b.placements}
        out[e.monster_id] = (max(len(pal.low), len(pal.high)), used)
    return out


@needs_rom
def test_パレット番号ビットは複数パレットの体だけが使う(real):
    """★bit4-5 をパレット番号と読む根拠。⚠ 1 体でも外れたら読み方が怪しい。"""
    rom, entries = real
    got = _placement_palette_bits_only_for_multi_palette_monsters(rom, entries)
    assert len(got) >= 80
    for mid, (n_pal, used) in got.items():
        assert max(used) < max(n_pal, 1), f"0x{mid:02X}: パレット {n_pal} 本なのに番号 {used}"
        if n_pal <= 1:
            assert used == {0}, f"0x{mid:02X}: パレット 1 本なのに番号 {used}"
    assert any(max(used) > 0 for _n, used in got.values()), "★番号を使う体が 1 体も無い"


def _capture_pixels(path: pathlib.Path) -> dict:
    from PySide6.QtGui import QImage
    im = QImage(str(path))
    out = {}
    for y in range(im.height()):
        for x in range(im.width()):
            p = im.pixel(x, y)
            if p & 0xFFFFFF:
                out[(x, y)] = (p >> 16 & 255, p >> 8 & 255, p & 255)
    return out


def _near(a, b, tol=2) -> bool:
    return all(abs(i - j) <= tol for i, j in zip(a, b))


@pytest.mark.skipif(not (CAPTURES / "52.png").exists(), reason="シドーの撮影が無い")
@needs_rom
def test_シドーは色まで撮影と一致する(real):
    """★★ 色まで含めた突き合わせ（RX-0051 の受け入れ）★★

    ⚠ 撮影は FCEUX の画面（色を 255/252 倍）で、体の下 1/3 が切れている。
      位置合わせは総当たり、色は ±2 の丸め誤差を許す。★以前は 92.6% だった。
    """
    from dq2rom.monsters import decoder as dec
    from dq2rom.monsters.palette import load_nes_palette, read_monster_palettes

    rom, entries = real
    e = next(x for x in entries if x.monster_id == 0x52)
    nes = load_nes_palette(PAL_PATH).as_screenshot()
    blocks = dec.decode_monster(rom.prg, e.graphics_addr, e.count)
    made = render(blocks, read_monster_palettes(rom.prg, e.palette_addr), nes)
    rendered = {(x, y): px[:3] for y, row in enumerate(made.rows)
                for x, px in enumerate(row) if px[3]}
    captured = _capture_pixels(CAPTURES / "52.png")
    best = (0, 0, 0)
    for dx in range(-6, 7):
        for dy in range(0, 40):
            agree = sum(1 for (x, y), c in captured.items()
                        if (x + dx, y + dy) in rendered and _near(rendered[(x + dx, y + dy)], c))
            if agree > best[0]:
                best = (agree, dx, dy)
    rate = best[0] / len(captured)
    assert rate >= 0.99, f"色の一致 {rate:.1%}（位置 {best[1:]}）。★桃色と鮭色が入れ替わっていないか"


RAW = CAPTURES / "raw"
RAW_FOR = {0x30: "30.png", 0x4B: "4B-4B-4C.png", 0x4E: "4E.png"}


@needs_rom
@pytest.mark.skipif(
    not (RAW.exists() and any(RAW.glob("*.png"))),
    reason="生の画面（raw/）が無い")
@pytest.mark.parametrize("mid", sorted(RAW_FOR), ids=lambda m: f"{m:02X}")
def test_既知3枚は生画面と色まで完全一致する(real, mid):
    """★★ RX-0052 の決着（2026-08-22）★★

    切り出した撮影が合わなかった 3 体を、**生の画面（256×224）に ROM の絵をそのまま
    当てはめて**探す。⚠ 位置は総当たり、色は ±2 の丸め誤差だけ許す。
    ★3 体とも 1 画素残らず一致する位置が 1 つある（隣の敵が写り込んでいたのは
      切り出し側の問題で、ROM の展開は正しかった）。
    ★同時に、画素指定タイル（スプライト）を**格子の前**に描く順の裏取りでもある
      （逆順だと 4B / 4E は 1953/2048 になる）。
    """
    from dq2rom.monsters import decoder as dec
    from dq2rom.monsters.palette import load_nes_palette, read_monster_palettes

    rom, entries = real
    e = next(x for x in entries if x.monster_id == mid)
    nes = load_nes_palette(PAL_PATH).as_screenshot()
    blocks = dec.decode_monster(rom.prg, e.graphics_addr, e.count)
    made = render(blocks, read_monster_palettes(rom.prg, e.palette_addr), nes)
    rendered = {(x, y): px[:3] for y, row in enumerate(made.rows)
                for x, px in enumerate(row) if px[3]}
    from PySide6.QtGui import QImage
    im = QImage(str(RAW / RAW_FOR[mid]))
    screen = {(x, y): (im.pixel(x, y) >> 16 & 255, im.pixel(x, y) >> 8 & 255, im.pixel(x, y) & 255)
              for y in range(im.height()) for x in range(im.width())}
    best = 0
    for oy in range(0, im.height() - made.height + 1):
        for ox in range(0, im.width() - made.width + 1):
            agree = sum(1 for (x, y), c in rendered.items()
                        if _near(screen.get((x + ox, y + oy), (0, 0, 0)), c))
            best = max(best, agree)
            if best == len(rendered):
                break
        if best == len(rendered):
            break
    assert best == len(rendered), f"0x{mid:02X}: {best}/{len(rendered)} 画素しか合わない"
