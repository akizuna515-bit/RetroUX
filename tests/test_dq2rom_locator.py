"""表の探索（指示書 §19-4「ROMアドレスを固定値にしない」）。

★★ 2種類のテストがある ★★

  1. **疑似データのテスト**（常に走る / 指示書 4.4）
     自作の偽ROMに署名を埋めて、探索と裏取りが正しく動くか見る。
     ⚠ 特に「候補が複数あるときに**選ばない**」ことを固定する。
     過去に、候補を1つ選んで敵の対応づけを間違えた事故がある。

  2. **本物のROMのテスト**（`DQ2_ROM_PATH` があるときだけ / 指示書 16.2）
     実測して分かった位置（PRG 0x110FD / 0x08000）を金型として固定する。
     ROM はリポジトリに入れない。
"""

from __future__ import annotations

import os
import pathlib

import pytest

from dq2rom import ines, locator
from dq2rom.provenance import Confidence, Evidence, Finding, weakest

from test_dq2rom_ines import make_rom


# --- 疑似データ --------------------------------------------------------


def plant(prg: bytearray, base: int, stride: int, rows: list[tuple[int, ...]],
          filler: int = 0x00) -> None:
    """`base` から `stride` 間隔で `rows` を書き込む。"""
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            prg[base + i * stride + j] = value
        for j in range(len(row), stride):
            prg[base + i * stride + j] = filler


def fake_rom_with_monster_table(base: int, *, entries: int = 0x54) -> ines.Rom:
    """索引表を1か所だけ埋めた偽ROM。

    ★ポインタは**筋の通った値**（$8000-$BFFF、パレットは単調増加）にする。
      裏取りが通る状態を先に作り、あとで壊してみる。
    """
    data = bytearray(make_rom(prg_banks=8, fill=0xEE))
    prg = memoryview(data)[16:]
    prg = bytearray(prg)
    counts = locator._MONSTER_GFX_COUNT_SIGNATURE
    for i in range(entries):
        o = base + i * locator.MONSTER_GFX_ENTRY_SIZE
        prg[o] = counts[i] if i < len(counts) else 0x01
        gfx = 0x8000 + (i * 3)
        pal = 0x9000 + (i * 4)
        prg[o + 1] = gfx & 0xFF
        prg[o + 2] = gfx >> 8
        prg[o + 3] = pal & 0xFF
        prg[o + 4] = pal >> 8
    return ines.parse(bytes(data[:16]) + bytes(prg))


def test_finds_the_monster_table():
    rom = fake_rom_with_monster_table(0x110FD)
    got = locator.locate_monster_graphics_table(rom)
    assert got.prg_offset == 0x110FD
    assert got.bank == 4
    assert got.cpu_address == 0x90FD


def test_reports_the_bank_and_cpu_address():
    rom = fake_rom_with_monster_table(0x08000)
    got = locator.locate_monster_graphics_table(rom)
    assert (got.bank, got.cpu_address) == (2, 0x8000)


def test_refuses_when_there_are_two_candidates():
    """★★ 候補が複数あるときは**選ばない**。

    選ぶと必ず間違える。過去に、確率の署名だけで敵をひも付けて
    1つのIDに2つの名前を割り当てた事故がある（playbook #57）。
    """
    data = bytearray(make_rom(prg_banks=8, fill=0xEE))
    prg = bytearray(data[16:])
    counts = locator._MONSTER_GFX_COUNT_SIGNATURE
    for base in (0x02000, 0x110FD):
        plant(prg, base, locator.MONSTER_GFX_ENTRY_SIZE,
              [(c, 0x00, 0x80, 0x00, 0x90) for c in counts])
    rom = ines.parse(bytes(data[:16]) + bytes(prg))
    with pytest.raises(locator.LocateError, match="候補が 2 個"):
        locator.locate_monster_graphics_table(rom)


def test_reports_when_nothing_matches():
    rom = ines.parse(make_rom(prg_banks=8, fill=0xEE))
    with pytest.raises(locator.LocateError, match="見つかりません"):
        locator.locate_monster_graphics_table(rom)


def test_reads_the_whole_table():
    rom = fake_rom_with_monster_table(0x110FD)
    entries = locator.read_monster_graphics_table(rom, 0x110FD)
    assert len(entries) == locator.MONSTER_GFX_ENTRIES
    assert entries[0].monster_id == 0
    assert entries[1].graphics_addr == 0x8003


def test_marks_ids_the_game_never_processes():
    """★コードは `cmp #$53 / bcc` で $53 以上を弾く。捨てずに印を付けて残す。"""
    rom = fake_rom_with_monster_table(0x110FD)
    entries = locator.read_monster_graphics_table(rom, 0x110FD)
    assert entries[locator.MONSTER_GFX_MAX_ID].in_range
    assert not entries[locator.MONSTER_GFX_MAX_ID + 1].in_range


def test_refuses_to_read_past_the_end():
    rom = fake_rom_with_monster_table(0x110FD)
    with pytest.raises(locator.LocateError, match="はみ出します"):
        locator.read_monster_graphics_table(rom, len(rom.prg) - 10)


# --- 裏取り -----------------------------------------------------------


def test_verification_passes_on_sane_pointers():
    rom = fake_rom_with_monster_table(0x110FD)
    entries = locator.read_monster_graphics_table(rom, 0x110FD)
    assert locator.verify_monster_graphics_table(entries) == []


def test_verification_catches_pointers_outside_the_window():
    """★★ わざと壊して赤くなることを確かめる。

    探索は count 列だけを見ている。ポインタ列がでたらめでも
    「見つかった」と言えてしまうので、別の列で必ず裏を取る。
    """
    rom = fake_rom_with_monster_table(0x110FD)
    entries = locator.read_monster_graphics_table(rom, 0x110FD)
    broken = list(entries)
    broken[5] = type(entries[5])(
        monster_id=5, count=1, graphics_addr=0x1234, palette_addr=0x9014,
        in_range=True)
    problems = locator.verify_monster_graphics_table(broken)
    assert any("$8000-$BFFF" in p for p in problems)


def test_verification_catches_duplicate_palettes():
    rom = fake_rom_with_monster_table(0x110FD)
    entries = locator.read_monster_graphics_table(rom, 0x110FD)
    broken = list(entries)
    broken[5] = type(entries[5])(
        monster_id=5, count=1, graphics_addr=0x8010,
        palette_addr=entries[6].palette_addr, in_range=True)
    problems = locator.verify_monster_graphics_table(broken)
    assert any("重複" in p for p in problems)


# --- confidence -------------------------------------------------------


def test_confidence_never_gets_stronger_than_its_weakest_part():
    """★「表の位置は confirmed、展開結果は tentative」なら全体は tentative。"""
    assert weakest(Confidence.CONFIRMED, Confidence.TENTATIVE) is Confidence.TENTATIVE
    assert weakest(Confidence.PROBABLE, Confidence.CONFIRMED) is Confidence.PROBABLE
    assert weakest() is Confidence.UNKNOWN


def test_evidence_serialises_addresses_as_hex():
    e = Evidence(type="byte_signature", note="test", bank=4,
                 cpu_address=0x90FD, rom_offset=0x110FD)
    got = e.to_json()
    assert got["cpu_address"] == "0x90FD"
    assert got["rom_offset"] == "0x110FD"


def test_finding_carries_its_evidence():
    f = Finding(name="x", confidence=Confidence.PROBABLE,
                evidence=(Evidence(type="t", note="n"),))
    got = f.to_json()
    assert got["confidence"] == "probable"
    assert got["evidence"][0]["note"] == "n"


# --- 本物のROM（あるときだけ / 指示書 16.2）----------------------------

ROM_PATH = os.environ.get("DQ2_ROM_PATH") or "work/rom/DQ2_J.nes"
_has_rom = pathlib.Path(ROM_PATH).exists()
needs_rom = pytest.mark.skipif(
    not _has_rom,
    reason=f"ROM がありません（{ROM_PATH}）。DQ2_ROM_PATH で指定できます")


@pytest.fixture(scope="module")
def real_rom():
    return ines.load(ROM_PATH)


@needs_rom
def test_real_rom_is_unrom_not_mmc1(real_rom):
    """★指示書 2.2 の「Mapper 1 (MMC1)」は北米版の値。実物は UNROM(2)。"""
    assert real_rom.mapper == ines.MAPPER_UNROM
    assert real_rom.prg_banks == 8
    assert real_rom.chr_banks == 0
    assert real_rom.uses_chr_ram


@needs_rom
def test_real_rom_hashes_match_the_instruction_document(real_rom):
    assert real_rom.crc32 == "7b3d483f"
    assert real_rom.md5 == "5c908061c1ebdabc5a5ea1782f83a2cd"
    assert real_rom.sha1 == "036f96215c102475e9ff7c4b89fe744cee069d9e"


@needs_rom
def test_real_rom_monster_table_position(real_rom):
    """★実測した位置を金型として固定する。"""
    got = locator.locate_monster_graphics_table(real_rom)
    assert got.prg_offset == 0x110FD
    assert (got.bank, got.cpu_address) == (4, 0x90FD)


@needs_rom
def test_real_rom_monster_table_survives_verification(real_rom):
    """★探索に使っていない列（ポインタ）で裏を取る。"""
    got = locator.locate_monster_graphics_table(real_rom)
    entries = locator.read_monster_graphics_table(real_rom, got.prg_offset)
    assert locator.verify_monster_graphics_table(entries) == []


@needs_rom
def test_real_rom_color_swaps_share_one_picture(real_rom):
    """★★ 指示書 §8 の疑問5への回答。**82体の絵は38枚しかない。**

    ⚠ 数え方を間違えやすいので範囲を明示する:
      ・ID $00 は `$8000` を指す null エントリ（実体なし）
      ・ID $53 以上はコードが `cmp #$53 / bcc` で弾く
    数えるのは **ID $01〜$52 の82体**。
    """
    got = locator.locate_monster_graphics_table(real_rom)
    entries = locator.read_monster_graphics_table(real_rom, got.prg_offset)
    real = [e for e in entries if e.in_range and e.monster_id != 0]
    assert len(real) == 82
    assert len(set(e.graphics_addr for e in real)) == 38
    assert len(set(e.palette_addr for e in real)) == 82


@needs_rom
def test_real_rom_map_header_table_position(real_rom):
    got = locator.locate_map_header_table(real_rom)
    assert got.prg_offset == 0x08000
    assert (got.bank, got.cpu_address) == (2, 0x8000)


@needs_rom
def test_real_rom_map_headers_are_sane(real_rom):
    """★探索は (境界タイル, 幅, 高さ) の24組だけ。残り85マップで裏を取る。"""
    got = locator.locate_map_header_table(real_rom)
    headers = locator.read_map_header_table(real_rom, got.prg_offset)
    assert len(headers) == locator.MAP_HEADER_ENTRIES
    # map 01 はワールドマップで width/height が $FF（別扱い）
    normal = [h for h in headers if h.width != 0xFF]
    assert all(1 <= h.width <= 0x40 and 1 <= h.height <= 0x40 for h in normal)

    # ★map $41 / $42 はポインタが $0000 の空エントリ。
    #   北米版の表でも同じ位置が `00 00` だったので、探索のずれではなく
    #   **元から使われていないマップ**（`work/dq2-disasm` bank2.asm の該当行）。
    empty = [h.map_id for h in normal if h.data_addr == 0]
    assert empty == [0x41, 0x42]
    assert all(0x8000 <= h.data_addr <= 0xBFFF
               for h in normal if h.data_addr != 0)
