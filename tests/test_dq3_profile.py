"""DQ3 ROM の版識別と、bank/window つきの位置変換（RX3-0002 / 2026-08-23）。

★★ ここは ROM が無くても走る。★★
  合成した iNES バイト列で「構成違い」「既知の別版」「未知の版」を**断る**ことを見る。
  ⚠ 本物の Rev 0A を識別できるかは下の integration（ROM があるときだけ）。

⚠ skip の見張りは**材料の数**で書く（RX-0100 の教訓）。`exists()` では見ない。
"""

from __future__ import annotations

import pathlib
import zlib

import pytest

from dq2rom import ines
from dq3rom import profile as dq3

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"


def _ines(prg_banks=16, chr_banks=0, mapper=1, battery=True, fill=0x00) -> bytes:
    """合成 iNES。★中身は埋め草。hash は当然合わない。"""
    flags6 = ((mapper & 0x0F) << 4) | (0x02 if battery else 0)
    flags7 = mapper & 0xF0
    head = b"NES\x1a" + bytes([prg_banks, chr_banks, flags6, flags7]) + bytes(8)
    return head + bytes([fill]) * (prg_banks * 0x4000 + chr_banks * 0x2000)


# --- profile の中身 --------------------------------------------------------

def test_profile_は_rev0a_の識別情報を持つ():
    p = dq3.load_profile()
    assert p.game_id == "dq3_fc_jp_rev0a"
    assert p.data["payload_hashes"]["crc32"].lower() == "a49b48b8"
    assert p.data["mapper"] == 1
    assert p.data["rom_layout"]["prg_banks"] == 16
    assert p.data["rom_layout"]["chr_banks"] == 0


def test_profile_の表には全部_confidence_がある():
    """★確度を崩さない（指示書 §2.4）。⚠ 無い表は「推測で読んでよい」に見える。"""
    p = dq3.load_profile()
    for name, table in p.data["tables"].items():
        if name.startswith("_"):
            continue
        assert table.get("confidence") in (
            "confirmed", "high-confidence", "inferred", "unknown"), name


def test_後期版の_hash_が_unsupported_として登録されている():
    p = dq3.load_profile()
    assert "869501ca" in {k.lower() for k in p.data["known_other_revisions"]}


# --- 断り方 ----------------------------------------------------------------

def test_構成が違えば断る():
    """★UNROM の 8 バンク（DQ2 相当）を DQ3 として読ませない。"""
    rom = ines.parse(_ines(prg_banks=8, mapper=2, battery=False))
    with pytest.raises(dq3.UnsupportedRom, match="構成が違います"):
        dq3.identify(rom)


def test_構成は同じでも未知の_hash_なら断る():
    """⚠ 「mapper 1 / 256K / CHR 0」でも、hash が合わなければ版不明。"""
    rom = ines.parse(_ines())
    with pytest.raises(dq3.UnsupportedRom, match="未知の版"):
        dq3.identify(rom)


def test_既知の別版は_その旨を添えて断る(monkeypatch):
    """★後期版 `869501CA` を Rev 0A と誤認しない（指示書 §2.3）。

    ⚠ 合成 ROM の CRC を後期版の値に合わせるのは難しいので、
      `prg_crc32` を差し替えて「そう見える ROM」を作る。
    """
    rom = ines.parse(_ines())
    rom = rom.__class__(**{**rom.__dict__, "prg_crc32": "869501ca"})
    with pytest.raises(dq3.UnsupportedRom, match="既知の別版"):
        dq3.identify(rom)


# --- 位置の変換（bank/window つき）-------------------------------------------

@pytest.fixture
def fake_ident():
    """hash 照合を飛ばして、変換だけ試す入れ物。"""
    rom = ines.parse(_ines())
    return dq3.Identified(rom=rom, profile=dq3.load_profile())


def test_切替窓は_bank_を使う(fake_ident):
    # 指示書 §5: file = 0x10 + bank*0x4000 + (cpu - 0x8000)
    assert fake_ident.file_offset(5, 0x8000) == 0x10 + 5 * 0x4000
    assert fake_ident.file_offset(6, 0x852B) == 0x01853B      # 調査資料 §7.1 map 0


def test_固定窓は最終バンク(fake_ident):
    # 指示書 §5: file = 0x10 + 15*0x4000 + (cpu - 0xC000)
    assert fake_ident.file_offset(15, 0xC000) == 0x10 + 15 * 0x4000
    assert fake_ident.file_offset(None, 0xFFD8) == 0x10 + 15 * 0x4000 + 0x3FD8


def test_固定窓に切替バンクを指定したら断る(fake_ident):
    """⚠ 黙って無視しない（「bank 3 の $C000」は存在しない）。"""
    with pytest.raises(dq3.ProfileError, match="固定窓"):
        fake_ident.file_offset(3, 0xC000)


def test_範囲外の_bank_と窓の外は断る(fake_ident):
    with pytest.raises(dq3.ProfileError):
        fake_ident.file_offset(16, 0x8000)
    with pytest.raises(dq3.ProfileError):
        fake_ident.file_offset(0, 0x7FFF)


def test_世界地図の式は_bank5_の切替窓と同じ(fake_ident):
    """調査資料 §6.1: `file_offset = cpu_pointer + 0xC010` は bank 5 の一般式。"""
    for ptr in (0x8000, 0x8212, 0xBFFF):
        assert fake_ident.file_offset(5, ptr) == ptr + 0xC010


def test_窓は_16KB(fake_ident):
    assert len(fake_ident.window(6)) == 0x4000
    with pytest.raises(dq3.ProfileError):
        fake_ident.window(16)


def test_profile_に無い表は断る(fake_ident):
    with pytest.raises(dq3.ProfileError, match="表がありません"):
        fake_ident.table("no_such_table")


# --- integration（ROM があるときだけ）---------------------------------------

def _rom_ready() -> bool:
    """★「ある」ではなく「読めて 256K の MMC1」か（RX-0100）。"""
    try:
        rom = ines.load(ROM_PATH)
    except Exception:                                  # noqa: BLE001
        return False
    return rom.mapper == 1 and rom.prg_banks == 16


needs_rom = pytest.mark.skipif(
    not _rom_ready(), reason=f"DQ3 Rev 0A の ROM が読めない（{ROM_PATH}）")


@needs_rom
def test_本物の_rev0a_を識別できる():
    ident = dq3.load_and_identify(ROM_PATH)
    assert ident.game_id == "dq3_fc_jp_rev0a"
    assert ident.rom.prg_crc32.lower() == "a49b48b8"
    assert ident.rom.prg_sha1 == "5759a9d658d253c8a6aaa38969c443d66e0f3349"


@needs_rom
def test_割り込みベクタが資料と一致する():
    """調査資料 §3.3。★固定バンク末尾から読む＝固定窓の変換が正しいことの裏取り。"""
    ident = dq3.load_and_identify(ROM_PATH)
    raw = ident.rom.raw
    at = ident.file_offset(None, 0xFFFA)
    nmi = int.from_bytes(raw[at:at + 2], "little")
    reset = int.from_bytes(raw[at + 2:at + 4], "little")
    irq = int.from_bytes(raw[at + 4:at + 6], "little")
    assert (nmi, reset, irq) == (0xC955, 0xFFD8, 0xEF11)


@needs_rom
def test_敵表の位置は_payload_の_crc_と同じ根拠で読める():
    """★敵表の先頭 23 bytes が「読めて、level が 0 でない」こと。

    ⚠ 値そのものは fixture に入れない（ROM 由来の転載を避ける）。
      ここでは**位置が ROM の中に収まり、形が崩れていない**ことだけ見る。
    """
    ident = dq3.load_and_identify(ROM_PATH)
    t = ident.table("enemies")
    start = ident.table_file("enemies")
    end = ident.table_file("enemies", "end_file_exclusive")
    assert end - start == t["count"] * t["entry_size"] == 3197
    entry0 = ident.rom.raw[start:start + 23]
    assert len(entry0) == 23 and entry0[0] != 0        # level
