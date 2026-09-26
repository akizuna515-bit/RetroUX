"""DQ3 のエリアマップ 243 件（RX3-0005 / 2026-08-23）。

★★ DQ2 の MDEC デコーダを「16KB の窓」を受ける入口にした、最初の DQ2 共通化。 ★★
  ⚠ DQ2 を壊していないことは `tests/test_dq2rom_map_decoder.py`（22 件）が見る。
    ★`dq2rom.maps.decoder` は DQ2 の製品コードからは呼ばれていない
    （DQ2 の実地図は `retroux/core/bgmap/rom_map.py` の別実装）ので、
    退行の物差しはそのテストで足りる。

★ここでは:
  - ROM 不要: semantics の差（ヘッダ下位 5 bit・第 2 パスの合成）を合成データで見る
  - ROM 時  : 204 / 0 / 39、資料 §7.1〜7.2 の細部（map 0 の寸法・消費 byte・命令数）
"""

from __future__ import annotations

import pathlib

import pytest

from dq2rom import ines
from dq2rom.maps import decoder as mdec
from dq3rom import area_maps as am
from dq3rom import profile as dq3

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"


# --- ROM 不要: semantics ----------------------------------------------------

class _Bits:
    """MSB-first のビット列を組み立てる（テスト用の最小限）。"""

    def __init__(self):
        self.bits = []

    def put(self, value, n):
        for i in range(n - 1, -1, -1):
            self.bits.append((value >> i) & 1)
        return self

    def bytes(self):
        out = bytearray()
        for i in range(0, len(self.bits), 8):
            chunk = self.bits[i:i + 8] + [0] * (8 - len(self.bits[i:i + 8]))
            out.append(int("".join(map(str, chunk)), 2))
        return bytes(out)


def _map(width, height, tile_bits, low5, body: _Bits) -> bytes:
    """ヘッダ 3 byte + ビット列。`low5` はヘッダ下位 5 bit。"""
    flags = ((tile_bits - 2) << 6) | (low5 & 0x1F)
    return bytes([width, height, flags]) + body.bytes()


def _simple_body(tile_bits, fill, phase2_bits=0, phase2_value=0):
    """下地 `fill` で塗って終了。phase2 があれば 1 点だけ置いて終了。"""
    b = _Bits()
    b.put(fill, tile_bits)            # 下地
    b.put(0b00, 2).put(0, tile_bits)  # cmd 00: set block（tile 0）
    b.put(0b00, 2).put(1, 1)          # 続く 2bit=0 → 1bit=1 → フェーズ終了
    b.put(phase2_bits, 2)             # 第 2 フェーズのビット数（0 = 無し）
    if phase2_bits:
        coord = (2 * 2 - 1).bit_length()
        b.put(0b00, 2).put(phase2_value, phase2_bits)   # set block
        b.put(0b11, 2).put(0, coord)                    # 点 (index 0) に置く
        b.put(0b00, 2).put(0, phase2_bits).put(0b00, 2).put(1, 1)  # 終了
    return b


def test_DQ2_は下位5bitを無視し_下地が背景():
    """★従来どおり（退行なし）。"""
    data = _map(2, 2, 5, 0b10101, _simple_body(5, fill=7))
    d = mdec.decode_window(data, 0x8000, semantics=mdec.DQ2)
    assert d.background == 7 and d.fill_tile == 7
    assert d.unused_header_bits == 0b10101
    assert d.semantics == "dq2"


def test_DQ3_は下位5bitが背景で_下地は別に持つ():
    """★調査資料 §7.2: ヘッダ下位 5 bit = OOB/背景。下地はビット列先頭のまま。"""
    data = _map(2, 2, 5, 29, _simple_body(5, fill=8))
    d = mdec.decode_window(data, 0x8000, semantics=mdec.DQ3)
    assert d.background == 29          # ヘッダから
    assert d.fill_tile == 8            # ビット列から
    assert d.tiles == [[8, 8], [8, 8]]
    assert d.semantics == "dq3"


def test_第2パスの合成_DQ2は置き換え_DQ3はOR():
    """⚠ 同じビット列でも、合成の仕方で phase2 の値が変わる。

    DQ2: 上位 3 bit を**置き換え**（別レイヤ）
    DQ3: 上位 3 bit を **OR**（調査資料 §7.2。⚠ 実機未確認）
    ★ここでは「差し替えが効いている」ことだけを見る。正しさは Phase 6。
    """
    body = _simple_body(5, fill=0, phase2_bits=2, phase2_value=0b11)
    data = _map(2, 2, 5, 0, body)
    d2 = mdec.decode_window(data, 0x8000, semantics=mdec.DQ2)
    d3 = mdec.decode_window(data, 0x8000, semantics=mdec.DQ3)
    assert d2.has_phase2 and d3.has_phase2
    assert d2.phase2[0][0] == 0b11 and d3.phase2[0][0] == 0b11
    # ★地形はどちらも保たれる
    assert d2.tiles == d3.tiles == [[0, 0], [0, 0]]


def test_decode_map_は従来の呼び方のまま():
    """★DQ2 の薄い包み: PRG 全体を渡し、bank 2（offset 0x8000）を見る。"""
    data = _map(2, 2, 5, 0, _simple_body(5, fill=3))
    prg = bytes(0x8000) + data + bytes(0x4000 - len(data))
    d = mdec.decode_map(prg, 0x8000)
    assert d.background == 3 and d.prg_bank == 2 and d.prg_start == 0x8000


def test_窓の外は断る():
    with pytest.raises(mdec.MapDecodeError, match="窓の外"):
        mdec.decode_window(bytes(16), 0x8010)
    with pytest.raises(mdec.MapDecodeError, match="窓の外"):
        mdec.decode_window(bytes(16), 0xC000)


def test_bank_の決め方はtilesetで():
    """調査資料 §7.1: tileset >= 0x0C → bank 7 / 未満 → bank 6。未使用は None。"""
    assert am.Entry(0, 0x852B, 0x01).bank == 6
    assert am.Entry(0, 0x852B, 0x0B).bank == 6
    assert am.Entry(0, 0x852B, 0x0C).bank == 7
    assert am.Entry(0, 0x0000, 0x11).bank is None


# --- ROM 時 ------------------------------------------------------------------

def _rom_ready() -> bool:
    try:
        rom = ines.load(ROM_PATH)
    except Exception:                                  # noqa: BLE001
        return False
    return rom.mapper == 1 and rom.prg_banks == 16


needs_rom = pytest.mark.skipif(
    not _rom_ready(), reason=f"DQ3 Rev 0A の ROM が読めない（{ROM_PATH}）")


@pytest.fixture(scope="module")
def maps():
    return am.decode_all(dq3.load_and_identify(ROM_PATH))


@needs_rom
def test_204_0_39(maps):
    """★★ 指示書 §8 の完了条件。回帰テストとして固定。 ★★"""
    s = am.summary(maps)
    assert (s["decoded"], s["failed"], s["unused"]) == (204, 0, 39)


@needs_rom
def test_map0_の細部が資料と一致(maps):
    """調査資料 §7.2: 32×44、tile bits 5、coord bits 11、背景 29、第 2 パスあり、
    281 bytes、77 commands。★寸法だけでなく**消費 byte と命令数**まで合うこと。"""
    d = maps[0].decoded
    assert (d.width, d.height) == (32, 44)
    assert d.tile_id_bits == 5 and d.coord_bits == 11
    assert d.background == 29 and d.has_phase2
    assert d.bytes_consumed == 281 and d.commands == 77


@needs_rom
def test_先頭5件の寸法とfile_offsetが資料と一致(maps):
    want = {0: (0x01853B, 32, 44), 1: (0x018808, 34, 48), 2: (0x0189C8, 34, 43),
            3: (0x018E17, 42, 60), 4: (0x01AF6B, 19, 24)}
    for i, (fo, w, h) in want.items():
        m = maps[i]
        assert m.file_offset == fo and (m.decoded.width, m.decoded.height) == (w, h), i


@needs_rom
def test_最大は_48x64_3072(maps):
    big = max((m for m in maps if m.ok), key=lambda m: m.decoded.width * m.decoded.height)
    assert (big.decoded.width, big.decoded.height) == (48, 64)
    assert am.summary(maps)["max_cells"] == 3072


@needs_rom
def test_bank7_のマップも通る(maps):
    """⚠ bank 6 だけで 204 になっていないこと（tileset >= 0x0C の窓も使えている）。"""
    b7 = [m for m in maps if m.ok and m.entry.bank == 7]
    assert len(b7) > 0
    assert all(m.decoded.prg_bank == 7 for m in b7)


@needs_rom
def test_背景と下地が違うマップがある(maps):
    """★DQ3 semantics が効いている証拠。⚠ 全件同じなら差し替えが死んでいる。"""
    diff = [m for m in maps if m.ok and m.decoded.background != m.decoded.fill_tile]
    assert len(diff) > 50, len(diff)
