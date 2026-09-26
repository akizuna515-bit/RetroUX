"""DQ3 の世界地図 RLE（RX3-0004 / 2026-08-23）。

★ROM 不要: 合成 byte 列で RLE の読み方と断り方を見る。
★ROM 時  : main 256/256・アレフガルド 138/138、四辺が海、番兵の位置。

⚠⚠ アレフガルドは **158 × 138**（調査資料 §6.2 の「139 行」は番兵を行と数えたもの）。
  2026-08-23 実測: 139 個目のポインタは 0x016403 を指し、その先は地形が入り乱れた
  別データ。行として読むと 160 tile に膨らむ。行 0 と行 137 が両方「全部海」。
"""

from __future__ import annotations

import pathlib

import pytest

from dq2rom import ines
from dq3rom import profile as dq3
from dq3rom import world_map as wm

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"


# --- ROM 不要: RLE -----------------------------------------------------------

def test_通常byteは_tile3bit_run5bit():
    # %TTTLLLLL: tile=1, run=3 → 0b001_00010
    tiles, consumed, sp = wm.decode_row(bytes([0b00100010]), 3)
    assert tiles == (1, 1, 1) and consumed == 1 and sp == 0


def test_E0からE7は_tile7の短いrun():
    """★「swamp 系 run」は同じ式に収まる（$E0 = tile 7 × 1、$E7 = tile 7 × 8）。"""
    tiles, _, sp = wm.decode_row(bytes([0xE7]), 8)
    assert tiles == (7,) * 8 and sp == 0


def test_E8以上は_special_1個():
    """⚠ 意味は未確定。ID は 8 + (byte - 0xE8) で仮に振り、名前は付けない。"""
    tiles, consumed, sp = wm.decode_row(bytes([0xE8, 0xFF]), 2)
    assert tiles == (8, 31) and consumed == 2 and sp == 2


def test_幅が足りなければ断る():
    with pytest.raises(wm.WorldMapError, match="幅が"):
        wm.decode_row(bytes([0x1F]), 256)          # 32 tile だけ


def test_幅を超えたら断る():
    """⚠ run が行をまたぐ形は想定しない（黙って切り詰めない）。"""
    with pytest.raises(wm.WorldMapError, match="超えました"):
        wm.decode_row(bytes([0x1F, 0x1F]), 40)     # 64 > 40


def test_仮色は_0から31_全部ある():
    pal = wm.logical_palette()
    assert set(pal) == set(range(32))
    # ★special（8..31）は灰系＝「未確定」と分かる色
    assert all(r == g == b for r, g, b in (pal[i] for i in range(8, 32)))


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
def ident():
    return dq3.load_and_identify(ROM_PATH)


@needs_rom
def test_メイン世界は_256x256_全行検証(ident):
    m = wm.decode(ident, "world_main")
    assert (m.width, m.height) == (256, 256)
    assert all(len(r.tiles) == 256 for r in m.rows)
    assert m.to_json()["rows_verified_by_next_pointer"] == 256


@needs_rom
def test_メインの番兵はアレフガルド表の先頭(ident):
    """★257 個目のポインタ = 行 255 の終端 = 次の表の先頭。"""
    m = wm.decode(ident, "world_main")
    ale = int(str(ident.table("world_alefgard")["pointer_table_file"]), 16)
    assert m.end_file == ale == 0x015AA9


@needs_rom
def test_アレフガルドは_158x138_全行検証(ident):
    m = wm.decode(ident, "world_alefgard")
    assert (m.width, m.height) == (158, 138)
    assert all(len(r.tiles) == 158 for r in m.rows)
    assert m.end_file == 0x016403


@needs_rom
@pytest.mark.parametrize("name", ["world_main", "world_alefgard"])
def test_四辺が海で閉じている(ident, name):
    """★地図として閉じていることの辻褄。⚠ 139 行で読むと下端が海でなくなる。"""
    m = wm.decode(ident, name)
    assert set(m.rows[0].tiles) == {0}
    assert set(m.rows[-1].tiles) == {0}
    assert {r.tiles[0] for r in m.rows} == {0}
    assert {r.tiles[-1] for r in m.rows} == {0}


@needs_rom
def test_海が過半数(ident):
    """golden（辻褄）: tile 0 が main の 6 割前後。⚠ 値の表は写さない。"""
    m = wm.decode(ident, "world_main")
    sea = sum(1 for r in m.tiles for t in r if t == 0)
    assert 0.55 < sea / (256 * 256) < 0.70


@needs_rom
def test_アレフガルドを_139行で読むと膨らむ(ident):
    """⚠⚠ 資料どおり 139 行にすると、139 行目が 160 tile になって断られる。

    ★この検査が「138 が正しい」ことの裏取り（逆に倒したら赤くなる）。
    """
    raw = ident.rom.raw
    start = 0x016403
    with pytest.raises(wm.WorldMapError, match="超えました"):
        wm.decode_row(raw[start:start + 64], 158)
