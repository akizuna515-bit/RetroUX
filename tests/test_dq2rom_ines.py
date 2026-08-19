"""iNES 解析とバンク↔オフセット変換（指示書 16.1）。

★★ ROM は使わない。**自作の極小疑似データだけ**（指示書 4.4）★★

★守りたい契約:
  1. マッパー番号は**ヘッダから読む**（指示書の「Mapper 1」を信じない）
  2. UNROM の `$C000-$FFFF` は**最終バンク固定**。バンク番号を渡されても無視する
  3. 壊れた入力では**黙って変な値を返さず例外**にする
"""

from __future__ import annotations

import pytest

from dq2rom import ines


def make_rom(prg_banks: int = 2, chr_banks: int = 0, mapper: int = 2,
             flags6_extra: int = 0x01, fill: int | None = None) -> bytes:
    """iNES として最小限まともなバイト列を組み立てる。"""
    flags6 = ((mapper & 0x0F) << 4) | flags6_extra
    flags7 = mapper & 0xF0
    header = bytes([0x4E, 0x45, 0x53, 0x1A, prg_banks, chr_banks,
                    flags6, flags7]) + bytes(8)
    prg = bytearray()
    for bank in range(prg_banks):
        value = bank if fill is None else fill
        prg += bytes([value & 0xFF]) * ines.PRG_BANK_SIZE
    chr_data = bytes(chr_banks * ines.CHR_BANK_SIZE)
    return header + bytes(prg) + chr_data


# --- 1. ヘッダから読む -------------------------------------------------


def test_reads_mapper_from_header_not_from_a_constant():
    """★指示書は「Mapper 1 (MMC1)」と書いているが、実物は UNROM(2) だった。

    ここで固定値を返す実装にすると、変換式が全部ずれる。
    """
    assert ines.parse(make_rom(mapper=2)).mapper == 2
    assert ines.parse(make_rom(mapper=1)).mapper == 1
    assert ines.parse(make_rom(mapper=4)).mapper == 4


def test_chr_zero_means_chr_ram():
    rom = ines.parse(make_rom(chr_banks=0))
    assert rom.uses_chr_ram
    assert rom.chr == b""


def test_chr_present_is_not_chr_ram():
    rom = ines.parse(make_rom(chr_banks=1))
    assert not rom.uses_chr_ram
    assert len(rom.chr) == ines.CHR_BANK_SIZE


def test_mirroring():
    assert ines.parse(make_rom(flags6_extra=0x01)).mirroring == "vertical"
    assert ines.parse(make_rom(flags6_extra=0x00)).mirroring == "horizontal"
    assert ines.parse(make_rom(flags6_extra=0x08)).mirroring == "four_screen"


def test_hashes_cover_the_whole_file_including_the_header():
    """★出力メタデータに残すハッシュ（指示書 2.1）。

    ヘッダを含めるか外すかで値が変わるので、どちらかに決めて固定する。
    指示書が挙げた既知ハッシュは**ヘッダ込み**なので、それに合わせる。
    """
    import hashlib
    data = make_rom()
    rom = ines.parse(data)
    assert rom.sha1 == hashlib.sha1(data).hexdigest()


# --- 2. 変換 -----------------------------------------------------------


def test_switchable_window_uses_the_given_bank():
    rom = ines.parse(make_rom(prg_banks=8))
    assert rom.prg_offset(0, 0x8000) == 0x00000
    assert rom.prg_offset(1, 0x8000) == 0x04000
    assert rom.prg_offset(4, 0x90FD) == 0x110FD      # 実測した索引表の位置
    assert rom.prg_offset(2, 0x8000) == 0x08000      # 実測したマップヘッダ表


def test_fixed_window_ignores_the_bank_on_unrom():
    """★★ UNROM では `$C000-$FFFF` は**最終バンク固定**。

    ここでバンク番号を素直に使うと、bank 0 の $C000 を読んだつもりで
    実際には bank 7 のデータを見ているコードと食い違う。
    """
    rom = ines.parse(make_rom(prg_banks=8))
    last = (8 - 1) * ines.PRG_BANK_SIZE
    assert rom.prg_offset(0, 0xC000) == last
    assert rom.prg_offset(3, 0xC000) == last
    assert rom.prg_offset(7, 0xFFFF) == last + 0x3FFF


def test_round_trip():
    rom = ines.parse(make_rom(prg_banks=8))
    for offset in (0, 1, 0x3FFF, 0x4000, 0x110FD, 0x1FFFF):
        bank, cpu = rom.cpu_address(offset)
        assert rom.prg_offset(bank, cpu) == offset


def test_file_offset_adds_the_header():
    rom = ines.parse(make_rom())
    assert rom.file_offset(0) == 16
    assert rom.file_offset(0x110FD) == 0x110FD + 16


# --- 3. 壊れた入力 -----------------------------------------------------


def test_rejects_short_file():
    with pytest.raises(ines.InesError):
        ines.parse(b"NES\x1a")


def test_rejects_wrong_magic():
    data = bytearray(make_rom())
    data[0] = 0x00
    with pytest.raises(ines.InesError):
        ines.parse(bytes(data))


def test_rejects_truncated_prg():
    """★ヘッダが「2バンクある」と言っているのに実体が足りない場合。

    黙って短い prg を返すと、後の検索が「見つからない」で終わり、
    原因が ROM の破損だと分からなくなる。
    """
    data = make_rom(prg_banks=2)[:16 + ines.PRG_BANK_SIZE]
    with pytest.raises(ines.InesError, match="PRG が足りません"):
        ines.parse(data)


def test_rejects_zero_prg_banks():
    with pytest.raises(ines.InesError):
        ines.parse(make_rom(prg_banks=0))


@pytest.mark.parametrize("bank,addr", [(-1, 0x8000), (99, 0x8000)])
def test_rejects_bank_out_of_range(bank, addr):
    rom = ines.parse(make_rom(prg_banks=2))
    with pytest.raises(ines.InesError):
        rom.prg_offset(bank, addr)


@pytest.mark.parametrize("addr", [0x0000, 0x7FFF, 0x10000])
def test_rejects_cpu_address_outside_rom(addr):
    rom = ines.parse(make_rom(prg_banks=2))
    with pytest.raises(ines.InesError):
        rom.prg_offset(0, addr)


def test_rejects_prg_offset_out_of_range():
    rom = ines.parse(make_rom(prg_banks=2))
    with pytest.raises(ines.InesError):
        rom.cpu_address(len(rom.prg))


def test_trainer_is_skipped():
    """トレーナ付き（512バイト）でも PRG の先頭を取り違えないこと。"""
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 1, 0, (2 << 4) | 0x04, 0]) + bytes(8)
    trainer = bytes([0xEE]) * 512
    prg = bytes([0xAB]) * ines.PRG_BANK_SIZE
    rom = ines.parse(header + trainer + prg)
    assert rom.has_trainer
    assert rom.prg[0] == 0xAB
