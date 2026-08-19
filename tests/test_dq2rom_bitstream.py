"""ビット列の読み出しと座標ビット数（指示書 16.1）。

★★ ビット順は**逆アセンブルで確かめた**（推測していない）★★
  北米版 `bank2.asm`「read 1 bit of map data into C」は `lda #$80` から
  `lsr` を繰り返す ＝ **bit7 から**。複数ビットは `rol` で組むので
  **最初に読んだビットが最上位**。

★守りたい契約:
  1. MSB ファーストが既定。LSB も選べる（指示書 16.1）
  2. 範囲外は**必ず例外**（黙って 0 を返さない）
  3. 座標ビット数 = ceil(log2(w*h))。**2の冪の境界を落とさない**
"""

from __future__ import annotations

import pytest

from dq2rom.bitstream import (
    BitReader, BitstreamError, coordinate_bits, index_to_xy,
)


# --- 1. ビット順 -------------------------------------------------------


def test_msb_first_is_the_default():
    r = BitReader(bytes([0b1011_0010]))
    assert [r.read_bit() for _ in range(8)] == [1, 0, 1, 1, 0, 0, 1, 0]


def test_lsb_first_when_asked():
    r = BitReader(bytes([0b1011_0010]), msb_first=False)
    assert [r.read_bit() for _ in range(8)] == [0, 1, 0, 0, 1, 1, 0, 1]


def test_multi_bit_value_puts_the_first_bit_at_the_top():
    """★`rol` で組むので、先に読んだビットが上位。ここを逆にすると全部壊れる。"""
    r = BitReader(bytes([0b1010_0000]))
    assert r.read(3) == 0b101


def test_reads_across_a_byte_boundary():
    r = BitReader(bytes([0b0000_0011, 0b1100_0000]))
    r.read(6)
    assert r.read(4) == 0b1111


def test_start_offset():
    r = BitReader(bytes([0xFF, 0b1000_0000]), start=1)
    assert r.read_bit() == 1
    assert r.byte_pos == 1


# --- 2. 範囲外は例外 ---------------------------------------------------


def test_running_off_the_end_raises():
    """⚠ 黙って 0 を返すと「それらしいが全部間違った地図」が出る。"""
    r = BitReader(bytes([0xFF]))
    r.read(8)
    with pytest.raises(BitstreamError, match="終端"):
        r.read_bit()


def test_start_beyond_the_data_raises():
    with pytest.raises(BitstreamError):
        BitReader(bytes([0x00]), start=5)


def test_negative_count_raises():
    with pytest.raises(BitstreamError):
        BitReader(bytes([0xFF])).read(-1)


def test_absurd_count_raises():
    """★ビット数の計算間違いをここで止める（無限ループ・巨大確保の予防）。"""
    with pytest.raises(BitstreamError):
        BitReader(bytes(100)).read(33)


def test_read_zero_bits_is_zero():
    assert BitReader(bytes([0xFF])).read(0) == 0


# --- 3. 位置とバイト数 -------------------------------------------------


def test_bytes_consumed_counts_a_partial_byte():
    """★指示書 4.3 のログ項目「消費バイト数・ビット数」。"""
    r = BitReader(bytes([0xFF, 0xFF, 0xFF]))
    assert r.bytes_consumed == 0
    r.read(1)
    assert r.bytes_consumed == 1
    r.read(7)
    assert r.bytes_consumed == 1
    r.read(1)
    assert r.bytes_consumed == 2
    assert r.bits_read == 9


def test_align_to_byte():
    r = BitReader(bytes([0xFF, 0xAA]))
    r.read(3)
    assert r.align_to_byte() == 5
    assert r.read_byte_aligned() == 0xAA


def test_align_when_already_aligned_skips_nothing():
    r = BitReader(bytes([0xFF, 0xAA]))
    assert r.align_to_byte() == 0
    assert r.read_byte_aligned() == 0xFF


def test_byte_aligned_read_refuses_mid_byte():
    """⚠ 半端な位置でバイトを読むと、以後すべてずれる。止める。"""
    r = BitReader(bytes([0xFF, 0xAA]))
    r.read(3)
    with pytest.raises(BitstreamError, match="バイト境界"):
        r.read_byte_aligned()


# --- 4. 座標ビット数 ---------------------------------------------------


@pytest.mark.parametrize("w,h,expected", [
    (1, 1, 0),
    (2, 1, 1),
    (4, 4, 4),       # ★2の冪ちょうど。0..15 なので 4 ビットで足りる
    (5, 5, 5),       # 25 -> 0..24 -> 5 ビット
    (0x17, 0x17, 10),  # 実際のマップ 23x23 = 529 -> 0..528 -> 10 ビット
    (32, 32, 10),
])
def test_coordinate_bits(w, h, expected):
    assert coordinate_bits(w, h) == expected


def test_coordinate_bits_boundary_is_exact():
    """★★ 2の冪の境界。ここを1ビット多く取ると全マップが崩れる。

    16マス（0..15）は 4 ビット。17マス（0..16）で初めて 5 ビットになる。
    """
    assert coordinate_bits(16, 1) == 4
    assert coordinate_bits(17, 1) == 5
    assert coordinate_bits(256, 1) == 8
    assert coordinate_bits(257, 1) == 9


@pytest.mark.parametrize("w,h", [(0, 4), (4, 0), (-1, 4)])
def test_coordinate_bits_rejects_bad_size(w, h):
    with pytest.raises(BitstreamError):
        coordinate_bits(w, h)


def test_index_to_xy():
    assert index_to_xy(0, 10) == (0, 0)
    assert index_to_xy(9, 10) == (9, 0)
    assert index_to_xy(10, 10) == (0, 1)
    assert index_to_xy(23, 10) == (3, 2)


def test_index_to_xy_rejects_bad_input():
    with pytest.raises(BitstreamError):
        index_to_xy(0, 0)
    with pytest.raises(BitstreamError):
        index_to_xy(-1, 10)
