"""DQ3 の敵データ表 139 体（RX3-0003 / 2026-08-23）。

★★ round-trip が要（指示書 §6）★★
  名前付きの値から 23 bytes を**組み立て直して**、元と 1 byte も違わないこと。
  ⚠ `raw` をそのまま返す実装だと、名前付きの値が raw と食い違っても緑になる。

⚠ golden は**少数の辻褄**だけ（敵 0 の level が 1・HP が 1 桁、末尾 2 体の並び）。
  値の表そのものを fixture に写さない（ROM 由来の転載を避ける）。

⚠ skip の見張りは**材料の数**で書く（RX-0100）。
"""

from __future__ import annotations

import pathlib

import pytest

from dq2rom import ines
from dq3rom import enemies
from dq3rom import profile as dq3

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"


# --- ROM 不要: model の往復 ---------------------------------------------

def test_23bytes_を往復しても欠けない():
    data = bytes(range(23))
    e = enemies.Enemy.from_bytes(7, data)
    assert e.to_bytes() == data
    assert e.raw == data


def test_未確定領域は名前を付けず_raw_で持つ():
    """★指示書 §6「未確定 bit を勝手に名前付けしない」。

    ## ⚠⚠ 2026-09-01: ここは **古い前提を固定していました**

      ★もとは「`gold` を出さない」でした。⚠ 上位 2 bit の在り処が
      **未確定だった**からです。`RX3-0033` で確定したので、
      ★いまは `gold` を出すのが正しく、⚠ 出さないほうが誤りです。

      ⚠ 見張るのは「**まだ分からない所**に名前を付けないこと」で、
      ★分かった所を隠すことではありません。
    """
    data = bytes(range(23))
    e = enemies.Enemy.from_bytes(0, data)
    assert e.raw_18_21 == bytes([18, 19, 20, 21])
    assert e.raw_22 == 22
    j = e.to_json()
    # ⚠ まだ分からない所は raw のまま（★名前を付けない）
    assert j["raw_18_21"] == "12131415"
    assert "resist" not in j and "drop_odds" not in j
    # ★確定した所は名前付きで出す（⚠ 下位 8 bit も残す）
    for key in ("gold", "attack", "defense", "hp"):
        assert key in j and key + "_raw" in j


def test_exp_は_little_endian():
    data = bytearray(23)
    data[1], data[2] = 0x34, 0x12
    assert enemies.Enemy.from_bytes(0, bytes(data)).exp == 0x1234


def test_長さが違えば断る():
    with pytest.raises(ValueError, match="23 bytes"):
        enemies.Enemy.from_bytes(0, bytes(22))


def test_csv_の列は_raw_を含む():
    rows = enemies.to_csv_rows([enemies.Enemy.from_bytes(0, bytes(23))])
    assert rows[0][-2:] == ["raw_18_21", "raw_22"]
    assert len(rows[1]) == len(rows[0])


# --- ROM 時 ----------------------------------------------------------------

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


@pytest.fixture(scope="module")
def table(ident):
    return enemies.read_all(ident)


@needs_rom
def test_139件_3197bytes(table):
    assert len(table) == 139
    assert sum(len(e.to_bytes()) for e in table) == 3197


@needs_rom
def test_全_3197bytes_を往復できる(ident, table):
    """★★ これが要。1 byte でも欠けたら赤。 ★★"""
    assert enemies.round_trip_ok(ident, table)


@needs_rom
def test_ID_が表の並び順(table):
    assert [e.enemy_id for e in table] == list(range(139))


@needs_rom
def test_先頭は序盤の敵の辻褄(table):
    """golden: 敵 0 は level 1・HP 1 桁・MP 0（スライム相当）。

    ⚠ 値の表を写さない。**辻褄**だけ見る。
    """
    e0 = table[0]
    assert e0.level == 1
    assert 1 <= e0.hp_raw < 10
    assert e0.mp == 0
    assert e0.exp < 10
    # ★先頭 3 体は level が単調非減少（序盤の並び）
    assert table[0].level <= table[1].level <= table[2].level


@needs_rom
def test_特殊な値はそのまま持つ(table):
    """⚠ 2026-08-23 実測: 5 体が level>99 または exp==65535（メタル系・ボス相当）。

    ★「+0 は level」という北米版 layout を**そのまま**当て、特殊値を加工しない。
      ⚠ ここで「100 以上は別の意味」と勝手に直すと、後で直せなくなる。
    """
    odd = [e for e in table if e.level > 99 or e.exp == 65535]
    assert 1 <= len(odd) <= 10, [e.enemy_id for e in odd]
    assert all(e.to_bytes() == e.raw for e in odd)


@needs_rom
def test_行動枠は_8_個で_0_255(table):
    for e in table:
        assert len(e.actions) == 8
        assert all(0 <= a <= 255 for a in e.actions)


# --- ★★ 上位 2 bit（RX3-0033 / 2026-08-31）------------------------------

def test_上位2bitの場所は下位の14先():
    """★北米版の逆アセンブルで確定した（`work/dq3-disasm/`）。

    ```text
    _bs_read_enemy_prop_HP:   LDY #7  … LDY #$15  AND #3
    _bs_load_enemy_prop_ATK:  LDY #5  … LDY #$13  AND #3
    _bs_load_enemy_prop_DEF:  LDY #6  … LDY #$14  AND #3
    （gold）                  LDY #4  … LDY #$12  AND #3
    ```

    ⚠ どれも「下位のある場所 **+14**」。★`AND #3` なので下位 2 bit だけ。
    """
    from dq3rom import enemies

    assert enemies.HIGH_OFFSET == 14
    assert enemies.HIGH_MASK == 0x03
    for low, high in ((4, 0x12), (5, 0x13), (6, 0x14), (7, 0x15)):
        assert low + enemies.HIGH_OFFSET == high, (low, high)


def test_wideは上位2bitだけを使う():
    """⚠⚠ 残り 6 bit は**別の意味**（★耐性など。未確定）。"""
    from dq3rom import enemies

    raw = bytearray(23)
    raw[7] = 0xFF
    raw[21] = 0xFF                    # ⚠ 8 bit 全部立てても…
    assert enemies.wide(raw, 7) == 0xFF + 3 * 256, "★下位 2 bit だけのはず"
    raw[21] = 0x02
    assert enemies.wide(raw, 7) == 0xFF + 2 * 256


@needs_rom
def test_実際の値がDQ3として辻褄が合う(table):
    """★★ ⚠⚠ **ここが規則の裏づけ**。

    ```text
    敵 0    HP 8 / gold 2 / atk 9 / def 5 / exp 4   ★スライム
    ★HP が 256 を超える敵が 14 体（⚠ 上位 bit 無しでは出せない）
    ★HP が 0 の敵は 0 体（⚠ でたらめな bit を拾っていない）
    ```
    """
    from dq3rom import enemies

    got = table
    first = got[0]
    assert enemies.wide(first.raw, 7) == 8, "★スライムの HP は 8"
    assert enemies.wide(first.raw, 4) == 2
    assert enemies.wide(first.raw, 5) == 9
    assert enemies.wide(first.raw, 6) == 5
    assert first.exp == 4

    hps = [enemies.wide(e.raw, 7) for e in got]
    assert min(hps) > 0, "⚠⚠ HP が 0 の敵がいる（★bit を取り違えている）"
    assert max(hps) == 1023, "★上限は 1023（⚠ 2 bit ぶん）"
    assert sum(1 for h in hps if h > 255) >= 10, (
        "⚠ 256 を超える敵が %d 体しかない（★上位 bit が効いていない）"
        % sum(1 for h in hps if h > 255))
