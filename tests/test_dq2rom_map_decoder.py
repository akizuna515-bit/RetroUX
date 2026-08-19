"""マップのビット列デコーダ（指示書 §21-4「疑似データで単体実装」）。

★★ ⚠ **このデコーダは日本版ROMには通用しない** ⚠ ★★

  北米版 `bank2.asm` の仕様どおりに実装したものだが、
  日本版のマップデータには当たらないことが実測で分かっている
  （`docs/rom-analysis-notes.md` 4章）。理由の要点:

    ・北米版は展開結果を **`$7800`（WRAM）** に置く
    ・日本版のセーブステートには **WRAM のチャンクが無い**
      （RAM 2KB / CHR-RAM 8KB / ネームテーブル 2KB だけ）＝ UNROM で WRAM を持たない
    ・つまり日本版は「マップ全体を展開して置いておく」ことができない

  それでも残しているのは、指示書 §21-4 が
  「疑似データで単体実装」を明示して求めているのと、
  **形式の理解を形にして残す**ため。日本版の形式が分かったときの土台になる。

★だからテストは**自作の疑似データだけ**（本物のROMは使わない）。
"""

from __future__ import annotations

import pytest

from dq2rom.maps.decoder import (
    MapDecodeError, consumed_end_addr, decode_map,
)

BANK2 = 0x8000


class BitWriter:
    """MSB ファーストでビットを積む（デコーダと同じ向き）。"""

    def __init__(self) -> None:
        self.bits: list[int] = []

    def w(self, value: int, count: int) -> "BitWriter":
        for i in range(count - 1, -1, -1):
            self.bits.append((value >> i) & 1)
        return self

    def bytes(self) -> bytes:
        pad = (-len(self.bits)) % 8
        bits = self.bits + [0] * pad
        return bytes(int("".join(str(b) for b in bits[i:i + 8]), 2)
                     for i in range(0, len(bits), 8))


def build(width: int, height: int, tile_bits: int, body: BitWriter,
          unused: int = 0) -> bytes:
    """3バイトのヘッダ＋ビット列。"""
    flags = ((tile_bits - 2) << 6) | (unused & 0x1F)
    return bytes([width, height, flags]) + body.bytes()


def prg_with(data: bytes, at: int = BANK2) -> bytes:
    buf = bytearray(0x20000)
    buf[at:at + len(data)] = data
    return bytes(buf)


def end_phase(b: BitWriter, tile_bits: int) -> BitWriter:
    """`00` を出してフェーズを終える（タイルID → 2ビット 0 → 1ビット 1）。"""
    return b.w(0, 2).w(0, tile_bits).w(0, 2).w(1, 1)


def no_phase2(b: BitWriter) -> BitWriter:
    return b.w(0, 2)


# --- 1. ヘッダ ---------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [(0, 2), (1, 3), (2, 4), (3, 5)])
def test_tile_id_bits_come_from_the_top_two_bits(raw, expected):
    body = BitWriter().w(0, expected)            # 背景タイル
    end_phase(body, expected)
    no_phase2(body)
    data = bytes([4, 4, raw << 6]) + body.bytes()
    got = decode_map(prg_with(data), 0x8000)
    assert got.tile_id_bits == expected


def test_size_and_coordinate_bits():
    body = BitWriter().w(0, 4)
    end_phase(body, 4)
    no_phase2(body)
    got = decode_map(prg_with(build(5, 5, 4, BitWriter())[:3] + body.bytes()), 0x8000)
    assert (got.width, got.height) == (5, 5)
    assert got.coord_bits == 5              # 25マス -> 0..24 -> 5ビット


def test_unused_header_bits_are_kept_not_dropped():
    """★意味の分からないビットは**捨てずに残す**（推測で埋めない）。"""
    body = BitWriter().w(0, 2)
    end_phase(body, 2)
    no_phase2(body)
    data = bytes([4, 4, 0x15]) + body.bytes()
    assert decode_map(prg_with(data), 0x8000).unused_header_bits == 0x15


@pytest.mark.parametrize("w,h", [(0, 4), (4, 0)])
def test_zero_size_is_rejected(w, h):
    assert_raises = pytest.raises(MapDecodeError)
    with assert_raises:
        decode_map(prg_with(bytes([w, h, 0])), 0x8000)


def test_pointer_outside_the_window_is_rejected():
    with pytest.raises(MapDecodeError, match="窓の外"):
        decode_map(prg_with(b""), 0x4000)


# --- 2. 下地 -----------------------------------------------------------


def test_background_fills_the_whole_map():
    body = BitWriter().w(3, 3)                   # 背景 = 3
    end_phase(body, 3)
    no_phase2(body)
    got = decode_map(prg_with(build(4, 3, 3, body)), 0x8000)
    assert got.background == 3
    assert got.tiles == [[3] * 4 for _ in range(3)]


# --- 3. 命令 -----------------------------------------------------------


def point_map(tile: int, index: int, width=8, height=8, bits=3):
    """`00`（1x1・タイル指定）→ `11`（1点）→ 終了。"""
    b = BitWriter().w(0, bits)                   # 背景 0
    b.w(0, 2).w(tile, bits)                      # 00: タイル
    b.w(3, 2)                                    # ★続く2ビットが 0 以外 = 次の命令
    b.w(index, 6)                                # 11: 座標（8x8 -> 6ビット）
    end_phase(b, bits)
    no_phase2(b)
    return decode_map(prg_with(build(width, height, bits, b)), 0x8000)


def test_point_command_writes_one_tile():
    got = point_map(tile=5, index=8 * 2 + 3)
    assert got.tiles[2][3] == 5
    assert got.tiles[0][0] == 0


def test_set_block_passes_the_next_code_through():
    """★★ `00` の直後の2ビットが 0 以外なら**それが次の命令**。

    ここを「`00` に戻る」と読むと、以降のビットが全部ずれる。
    """
    got = point_map(tile=7, index=0)
    assert got.tiles[0][0] == 7


def test_2x2_block_reads_three_more_tiles():
    bits = 3
    b = BitWriter().w(0, bits)
    b.w(0, 2).w(1, bits)                         # 00: 1枚目
    b.w(0, 2).w(0, 1)                            # 2ビット 0 → 1ビット 0 = 2x2
    b.w(2, bits).w(3, bits).w(4, bits)           # あと3枚
    b.w(3, 2).w(0, 6)                            # 11: 左上に置く
    end_phase(b, bits)
    no_phase2(b)
    got = decode_map(prg_with(build(8, 8, bits, b)), 0x8000)
    assert got.tiles[0][0] == 1
    assert got.tiles[0][1] == 2
    assert got.tiles[1][0] == 3
    assert got.tiles[1][1] == 4


def test_rect_command_fills_between_two_points():
    bits = 3
    b = BitWriter().w(0, bits)
    b.w(0, 2).w(6, bits)
    b.w(1, 2)                                    # 01: 矩形
    b.w(8 * 1 + 1, 6)                            # 始点 (1,1)
    b.w(8 * 3 + 4, 6)                            # 終点 (4,3)
    end_phase(b, bits)
    no_phase2(b)
    got = decode_map(prg_with(build(8, 8, bits, b)), 0x8000)
    for y in range(1, 4):
        for x in range(1, 5):
            assert got.tiles[y][x] == 6, (x, y)
    assert got.tiles[0][1] == 0
    assert got.tiles[1][5] == 0


def test_line_command_walks_and_turns():
    """`10`: 向き 1（右）に3歩、時計回りに回して（下へ）2歩。"""
    bits = 3
    b = BitWriter().w(0, bits)
    b.w(0, 2).w(2, bits)
    b.w(2, 2)                                    # 10: 線
    b.w(8 * 1 + 1, 6)                            # 始点 (1,1)
    b.w(1, 2)                                    # 向き 1 = 右
    for _ in range(3):
        b.w(0, 1)                                # そのまま進む
    b.w(1, 1).w(0, 2)                            # 時計回り（右→下）して進む
    b.w(0, 1)                                    # もう1歩
    b.w(1, 1).w(3, 2).w(1, 1)                    # pop（底なので終わり）
    end_phase(b, bits)
    no_phase2(b)
    got = decode_map(prg_with(build(8, 8, bits, b)), 0x8000)
    for x in range(1, 5):
        assert got.tiles[1][x] == 2, f"横に引けていない x={x}"
    assert got.tiles[2][4] == 2 and got.tiles[3][4] == 2, "縦に引けていない"


def test_line_push_and_pop_is_lifo():
    """⚠★ 指示書には FIFO と書かれた箇所があるが、**LIFO が正しい**。

    push した位置に戻れないと、枝分かれした通路が繋がらない。
    """
    bits = 3
    b = BitWriter().w(0, bits)
    b.w(0, 2).w(4, bits)
    b.w(2, 2)
    b.w(8 * 4 + 4, 6)                            # 始点 (4,4)
    b.w(0, 2)                                    # 向き 0 = 上
    b.w(0, 1)                                    # (4,3) へ
    b.w(1, 1).w(2, 2).w(0, 1)                    # push して時計回り（上→右）
    b.w(0, 1)                                    # (6,3)
    b.w(1, 1).w(3, 2).w(1, 1)                    # pop -> (4,3) 向き上 に戻る
    b.w(0, 1)                                    # (4,2) 戻れていれば縦に伸びる
    b.w(1, 1).w(3, 2).w(1, 1)                    # もう一度 pop -> 底なので終了
    end_phase(b, bits)
    no_phase2(b)
    got = decode_map(prg_with(build(8, 8, bits, b)), 0x8000)
    assert got.tiles[2][4] == 4, "pop で元の位置に戻れていない（LIFO でない）"
    assert got.tiles[3][5] == 4 and got.tiles[3][6] == 4, "枝が引けていない"


# --- 4. 第2フェーズ（屋根 / 視界）--------------------------------------


def test_phase2_writes_the_top_bits_and_keeps_the_terrain():
    """★★ 第2フェーズは**同じマスの上位3ビット**。地形を消さない。"""
    bits = 3
    b = BitWriter().w(1, bits)                   # 背景 = 1
    end_phase(b, bits)
    b.w(2, 2)                                    # 第2フェーズあり / 値は2ビット
    b.w(0, 2).w(3, 2)                            # 00: 値 3
    b.w(3, 2).w(0, 6)                            # 11: (0,0) へ
    b.w(0, 2).w(0, 2).w(0, 2).w(1, 1)            # 終了
    got = decode_map(prg_with(build(8, 8, bits, b)), 0x8000)
    assert got.has_phase2 and got.phase2_bits == 2
    assert got.phase2[0][0] == 3
    assert got.tiles[0][0] == 1, "地形を消している"
    assert got.phase2[1][1] == 0


def test_no_phase2_when_the_two_bits_are_zero():
    bits = 3
    b = BitWriter().w(0, bits)
    end_phase(b, bits)
    no_phase2(b)
    got = decode_map(prg_with(build(4, 4, bits, b)), 0x8000)
    assert not got.has_phase2
    assert got.phase2 == [[0] * 4 for _ in range(4)]


def test_phase2_is_a_separate_layer_in_json():
    """★指示書 §10「tiles と visibility_regions は別レイヤーにする」。

    ⚠ 名前は決め打ちしない（逆アセンブルは "roofing"、指示書は "visibility"）。
    """
    bits = 3
    b = BitWriter().w(0, bits)
    end_phase(b, bits)
    no_phase2(b)
    got = decode_map(prg_with(build(4, 4, bits, b)), 0x8000).to_json()
    assert "tiles" in got and "phase2_layer" in got
    assert "visibility_regions" not in got, "断定した名前を使っている"


# --- 5. 壊れたデータ ---------------------------------------------------


def test_runaway_command_stream_is_stopped():
    """★止まらないデータで無限ループしないこと。"""
    # `11`（1点）を延々と繰り返すビット列
    b = BitWriter().w(0, 3)
    b.w(0, 2).w(1, 3).w(3, 2)
    for _ in range(30000):
        b.w(0, 6).w(3, 2)
    with pytest.raises(MapDecodeError):
        decode_map(prg_with(build(8, 8, 3, b)), 0x8000)


def test_running_off_the_end_is_reported():
    data = bytes([8, 8, 0]) + bytes(2)
    with pytest.raises(MapDecodeError):
        decode_map(prg_with(data, at=0xC000 - 5), 0xBFFB)


# --- 6. 消費バイト数（裏取りに使う手） ---------------------------------


def test_consumed_end_is_reported():
    """★「次のマップの位置でぴったり終わる」を確かめるための値。"""
    bits = 3
    b = BitWriter().w(0, bits)
    end_phase(b, bits)
    no_phase2(b)
    data = build(4, 4, bits, b)
    got = decode_map(prg_with(data), 0x8000)
    assert got.bytes_consumed == len(data)
    assert consumed_end_addr(got) == 0x8000 + len(data)
