"""ROM のアドレスと表の値を固定する（2026-08-02 / Phase 4・5）。

★★ **文書に書いた番地が、本当にその命令かを確かめます。** ★★

⚠ 解析結果を文章だけで持つと、いつのまにか食い違います。
  ★ここで ROM の実バイトに結びつけておきます。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.rom_tiles import load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")

BANK7 = 7 * 0x4000
BANK0 = 0


def _at7(address: int) -> int:
    """★bank7（`$C000`-`$FFFF`）の PRG オフセット。"""
    return BANK7 + address - 0xC000


def _bytes7(address: int, count: int) -> bytes:
    prg = load_prg(ROM)
    off = _at7(address)
    return prg[off:off + count]


# --- ★ 経路の分かれ目 -----------------------------------------------------

@needs_rom
def test_種別0だけが壁補正の側へ行く():
    """★`$DDD6: LDA $1F / BEQ $DDDD` / `$DDDA: JMP $DF7D`。

    ⚠⚠ ここが崩れると、街・ダンジョンに世界地図の処理が混ざります。
    """
    assert _bytes7(0xDDD6, 4) == bytes([0xA5, 0x1F, 0xF0, 0x03])
    assert _bytes7(0xDDDA, 3) == bytes([0x4C, 0x7D, 0xDF])


@needs_rom
def test_種別2以上だけ座標を半分にする():
    """★`$DD9D: LDA $1F / CMP #$02 / BCC` と `$DDA9: LSR $0C / LSR $0E`。

    ★分岐先は `$DD9D + 6 + $18 = $DDBB`（範囲チェック）。
    """
    assert _bytes7(0xDD9D, 6) == bytes([0xA5, 0x1F, 0xC9, 0x02, 0x90, 0x18])
    assert 0xDD9D + 6 + 0x18 == 0xDDBB
    assert _bytes7(0xDDA9, 4) == bytes([0x46, 0x0C, 0x46, 0x0E])


@needs_rom
def test_象限はANDしてORする():
    """★`$DDB4: AND #$03` / `$DDB6: ORA $0C`。⚠ 加算ではありません。"""
    assert _bytes7(0xDDB4, 6) == bytes([0x29, 0x03, 0x05, 0x0C, 0x85, 0x0C])


@needs_rom
def test_地形IDの取り出しは種別で違う():
    """★`$DFE1: AND #$1F`（街）と `$DFEA: AND #$E0 / LSR ×3`（ダンジョン）。"""
    # $DFDB: LDA $1F / CMP #$02 / BCS $DFE8
    assert _bytes7(0xDFDB, 6) == bytes([0xA5, 0x1F, 0xC9, 0x02, 0xB0, 0x07])
    # $DFE1: LDA $0C / AND #$1F / JMP $DFEF
    assert _bytes7(0xDFE1, 7) == bytes([0xA5, 0x0C, 0x29, 0x1F, 0x4C, 0xEF, 0xDF])
    # $DFE8: LDA $0C / AND #$E0 / LSR / LSR / LSR
    assert _bytes7(0xDFE8, 7) == bytes([0xA5, 0x0C, 0x29, 0xE0, 0x4A, 0x4A, 0x4A])


@needs_rom
def test_索引は5倍するだけでマスクしない():
    """★`$DD68: LDA $0C / ASL / ASL / ADC $0C`。⚠ `AND` がありません。"""
    got = _bytes7(0xDD68, 6)
    assert got == bytes([0xA5, 0x0C, 0x0A, 0x0A, 0x65, 0x0C])
    assert 0x29 not in got, "⚠ AND が入っています"


@needs_rom
def test_幅はヘッダ値プラス1():
    """★`$DFAE: LDA $21 / STA $0C / INC $0C`。"""
    assert _bytes7(0xDFAE, 6) == bytes([0xA5, 0x21, 0x85, 0x0C, 0xE6, 0x0C])


@needs_rom
def test_範囲外は境界タイルIDを返す():
    """★`$DDC9: LDA $20 / STA $0C / RTS`。⚠ 0 ではありません。"""
    assert _bytes7(0xDDC9, 5) == bytes([0xA5, 0x20, 0x85, 0x0C, 0x60])


# --- ★ 宝箱・扉 -----------------------------------------------------------

@needs_rom
def test_宝箱と扉の判定値():
    """★`$DFF1: CMP #$14` と `$E015/$E019/$E01D: CMP #$18/#$19/#$1A`。"""
    assert _bytes7(0xDFF1, 2) == bytes([0xC9, 0x14])
    assert _bytes7(0xE015, 2) == bytes([0xC9, 0x18])
    assert _bytes7(0xE019, 2) == bytes([0xC9, 0x19])
    assert _bytes7(0xE01D, 2) == bytes([0xC9, 0x1A])


@needs_rom
def test_動的差分の表の番地と件数():
    """★`$DFF9: CMP $051A,Y` / `$E025: CMP $052A,Y` / `CPY #$10`。"""
    assert _bytes7(0xDFF9, 3) == bytes([0xD9, 0x1A, 0x05])
    assert _bytes7(0xE025, 3) == bytes([0xD9, 0x2A, 0x05])
    assert _bytes7(0xE00F, 2) == bytes([0xC0, 0x10])      # ★8 組
    assert _bytes7(0xE006, 4) == bytes([0xA9, 0x00, 0x85, 0x0C])  # ★床にする


@needs_rom
def test_動的差分の表は32バイトまとめて初期化される():
    """★`$E368: TXA / STA $051A,X / INX / CPX #$20`。"""
    assert _bytes7(0xE368, 7) == bytes([0x8A, 0x9D, 0x1A, 0x05, 0xE8, 0xE0, 0x20])


# --- ★ Phase 4: `$1C` -----------------------------------------------------

@needs_rom
def test_PPUバッファへ3バイト積んで件数を増やす():
    """★`$C0FC` の写し。`$DD5B` と打ち消し合うことの根拠です。"""
    assert _bytes7(0xC114, 4) == bytes([0xE6, 0x01, 0x86, 0x02])


@needs_rom
def test_DD5Bは直前の1件を取り消す():
    """★★ `DEC $02` ×3 と `DEC $01`。⚠ ここが `$1C` の意味の決め手です。"""
    assert _bytes7(0xDD5B, 9) == bytes([0xC6, 0x02, 0xC6, 0x02, 0xC6, 0x02,
                                        0xC6, 0x01, 0x60])


@needs_rom
def test_1Cのビットは4枚に対応する():
    """★bit0/1/2/3 → 左上・右上・左下・右下。"""
    assert _bytes7(0xDCF4, 3) == bytes([0xA5, 0x1C, 0x4A])          # bit0
    assert _bytes7(0xDD04, 4) == bytes([0xA5, 0x1C, 0x29, 0x02])    # bit1
    assert _bytes7(0xDD20, 4) == bytes([0xA5, 0x1C, 0x29, 0x04])    # bit2
    assert _bytes7(0xDD31, 4) == bytes([0xA5, 0x1C, 0x29, 0x08])    # bit3


@needs_rom
def test_1CのFFとFEはフィルタで使ったら0に戻る():
    """★`$DCC9`-`$DCE3`。⚠ ビットと同時には使えません。"""
    assert _bytes7(0xDCC9, 4) == bytes([0xA5, 0x1C, 0xC9, 0xFF])
    assert _bytes7(0xDCD6, 2) == bytes([0xC9, 0xFE])
    assert _bytes7(0xDCE1, 4) == bytes([0xA9, 0x00, 0x85, 0x1C])


# --- ★ Phase 5: 部屋の見え方 ----------------------------------------------

@needs_rom
def test_同じ区画なら差し替えない():
    """★`$DCA1: LDA $1D / CMP $0D / BEQ $DCC9`。"""
    assert _bytes7(0xDCA1, 6) == bytes([0xA5, 0x1D, 0xC5, 0x0D, 0xF0, 0x22])


@needs_rom
def test_隠すタイルは20と24():
    """★`$DCC1: LDA #$20` / `$DCC5: LDA #$24`。"""
    assert _bytes7(0xDCC1, 2) == bytes([0xA9, 0x20])
    assert _bytes7(0xDCC5, 4) == bytes([0xA9, 0x24, 0x85, 0x0C])


@needs_rom
def test_区画データのポインタはヘッダの25と26():
    """★★ `$E052: LDA $25 / ORA $26 / BNE`。

    ⚠ ずっと `unknown` だったヘッダ byte5/byte6 の正体です。
    """
    assert _bytes7(0xE052, 5) == bytes([0xA5, 0x25, 0x05, 0x26, 0xD0])
    assert _bytes7(0xE07A, 4) == bytes([0xB1, 0x25, 0x30, 0xF6])  # BMI で行送り


@needs_rom
def test_区画のマスクは種別で違う():
    """★種別 < 2 は `$3F`、種別 >= 2 は `$0F`（`$E046`-`$E050`）。"""
    assert _bytes7(0xE046, 4) == bytes([0xA5, 0x1F, 0xC9, 0x02])
    assert _bytes7(0xE04A, 2) == bytes([0xA9, 0x3F])
    assert _bytes7(0xE04E, 2) == bytes([0xA9, 0x0F])


@needs_rom
def test_区画データを持つマップの数():
    """★60 マップが持っています。⚠ 世界地図は持ちません。"""
    from retroux.core.bgmap.dungeon_map import map_kind
    from retroux.core.bgmap.rom_tiles import MAP_HEADER, MAP_HEADER_SIZE

    prg = load_prg(ROM)
    have = [m for m in range(109)
            if (prg[MAP_HEADER + m * MAP_HEADER_SIZE + 5]
                | (prg[MAP_HEADER + m * MAP_HEADER_SIZE + 6] << 8))]
    assert len(have) == 60
    assert 0x01 not in have, "⚠ 世界地図は区画データを持たないはず"
    assert all(map_kind(m) != 0 for m in have)


# --- ★ 変換表 -------------------------------------------------------------

@needs_rom
def test_変換表のポインタ():
    """★`$DC6F` の実データ。"""
    from retroux.core.bgmap.dungeon_map import TERRAIN_TABLES

    prg = load_prg(ROM)
    off = _at7(0xDC6F)
    for kind, expected in TERRAIN_TABLES.items():
        got = prg[off + kind * 2] | (prg[off + kind * 2 + 1] << 8)
        assert got == expected, f"⚠ 種別{kind}: ${got:04X} != ${expected:04X}"
