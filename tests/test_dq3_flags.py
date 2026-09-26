"""DQ3 のイベントフラグ領域（RX3-0012 / 2026-08-30）。

★ここで見張りたいのは 2 つ。

  1. **式が ROM のコードと同じ**であること（⚠ 写し間違いは静かに効く）
  2. ★独立に見つかっていた 2 件と、式が**同じ番地で合流**すること

⚠ 「1 例だけの検査はすり抜ける」の教訓から、合流の検査は 2 件とも書く。
"""

from __future__ import annotations

import pathlib

import pytest

from dq2rom import ines
from dq3rom import flags

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"


# --- ROM 不要: 式そのもの ------------------------------------------------

def test_在り処はバイトとビットに分かれる():
    """★ルーチンは `LSR ×3` と `AND #$07` でしか分けていない。"""
    assert flags.address_of(0).address == flags.FLAG_BASE
    assert flags.address_of(0).bit == 0
    loc = flags.address_of(9)
    assert (loc.address, loc.bit, loc.mask) == (flags.FLAG_BASE + 1, 1, 0x02)
    assert flags.address_of(255).address == flags.FLAG_BASE + 31


def test_独立に見つかっていた2件と合流する():
    """⚠ どちらか片方だけだと、偶然の一致とを見分けられない。

    ★宝箱のコード（`RX3-0011`）は、この式を使わずに次を見つけていた。
    """
    assert (flags.address_of(23).address, flags.address_of(23).bit) == (0x60B7, 7)
    assert (flags.address_of(197).address, flags.address_of(197).bit) == (0x60CD, 5)


def test_退避先に当たる番号を見分けられる():
    """⚠ `$60C0` / `$60C1` はルーチン自身が使う。★立てると壊れる。"""
    on = [n for n in range(256) if flags.address_of(n).on_scratch]
    assert on == list(range(88, 104))
    assert not flags.address_of(87).on_scratch
    assert not flags.address_of(104).on_scratch


def test_番号の範囲を黙って丸めない():
    for bad in (-1, 256):
        with pytest.raises(ValueError):
            flags.address_of(bad)


# --- ROM 時 ------------------------------------------------------------

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
    from dq3rom import profile as dq3

    return dq3.load_and_identify(ROM_PATH)


@needs_rom
def test_ルーチンの中身が想定どおり(ident):
    """⚠ 「その番地に何かある」ではなく**バイト列**を見る。"""
    assert flags.verify(ident) == []


@needs_rom
def test_ビット表が並びのとおり(ident):
    off = ident.prg_offset(flags.SETTER_BANK, flags.BIT_TABLE_ADDR)
    assert ident.rom.prg[off:off + 8] == flags.BIT_TABLE


@needs_rom
def test_呼び出しを取りこぼしていない(ident):
    """★拾えた数と拾えなかった数を両方見る（⚠ 片方だと漏れが見えない）。"""
    t = flags.scan_totals(ident)
    assert t["calls"] == t["with_literal"] + t["without_literal"]
    assert t["calls"] > 0
    assert t["without_literal"] == 0


@needs_rom
def test_呼び出しはbank13だけ(ident):
    """⚠ `$BF94` は切り替え窓。★他のバンクからは届かない。

    ⚠ bank4 にも同じ 3 バイトはある（別のルーチン）。拾っていないことを見る。
    """
    calls = flags.set_calls(ident)
    assert calls, "1 件も拾えていない（★見張りが空回りしている）"
    assert {c.bank for c in calls} == {flags.SETTER_BANK}


@needs_rom
def test_bank4の同じ3バイトは別物(ident):
    """★偽物のほうも実在することを、テストで固定しておく。

    ⚠ ここが「無い」に変わったら、`set_calls` の bank 絞りは
      **要らなくなったのではなく、探し方が変わった**ということ。
    """
    prg = ident.rom.prg
    start = ident.prg_offset(4, 0x8000)
    end = start + len(ident.window(4))
    hits = []
    i = start
    while True:
        i = prg.find(bytes((0x20, 0x94, 0xBF)), i, end)
        if i < 0:
            break
        hits.append(i)
        i += 1
    assert len(hits) == 3
    # ★bank4 の $BF94 は `LDX $51`（$A6 $51）で始まる別のルーチン
    assert prg[ident.prg_offset(4, 0xBF94):][:2] == bytes((0xA6, 0x51))


@needs_rom
def test_立てている番号が既知の2件を含む(ident):
    """★flag 23 は「読む側」を宝箱のコードから先に見つけていたもの。"""
    numbers = {c.number for c in flags.set_calls(ident)}
    assert 23 in numbers
    assert min(numbers) >= 0 and max(numbers) <= 255


@needs_rom
def test_退避先に当たる番号は立てられていない(ident):
    """⚠ 見えた範囲での話。★増えたら気づけるように固定する。"""
    for c in flags.set_calls(ident):
        assert not flags.address_of(c.number).on_scratch, \
            f"フラグ {c.number} は退避先に当たる（b{c.bank}:${c.address:04X}）"


@needs_rom
def test_world_model_のflagsに載る(ident):
    from dq3rom import world_model as wm

    model = wm.build(ident)
    assert wm.check(model) == []
    fl = model["flags"]
    assert fl, "flags が空（★載せたつもりで載っていない）"
    assert {f["flag_id"] for f in fl} == {
        flags.address_of(c.number).flag_id for c in flags.set_calls(ident)}
    for f in fl:
        assert f["set_by"], f"{f['flag_id']}: set_by が空"
        assert f["confidence"] == "confirmed"
