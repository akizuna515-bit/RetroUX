"""敵データ表の行動・耐性・ドロップ（RX3-0039 / 2026-09-01）。

## ⚠⚠ ここで守ること

★「それらしい値が出た」で確定しない（`RX3-0033` の HP/DEF 誤認の教訓）。
⚠ **正候補なら成立し、別候補では成立しない**根拠を検査にする。

```text
★識別性のある根拠   64〜127 の値が 1 つも無い（⚠ 6bit + 旗でなければ説明できない）
★識別性のある根拠   zoma_freeze_beam を持つ敵が 2 体だけで、最強個体と一致
★識別性のある根拠   1/2048 のドロップが表の末尾に固まる
```
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"


def _rom_ready() -> bool:
    try:
        from dq3rom import profile as dq3

        dq3.load_and_identify(ROM_PATH)
    except Exception:
        return False
    return True


needs_rom = pytest.mark.skipif(not _rom_ready(), reason="DQ3 の ROM が読めない")


@pytest.fixture(scope="module")
def detail():
    from dq3rom import enemies as en
    from dq3rom import enemy_detail as det
    from dq3rom import profile as dq3

    ident = dq3.load_and_identify(ROM_PATH)
    return det.read_all(en.read_all(ident))


# --- ★表そのもの（⚠ ROM が無くても見られる）--------------------------------


def test_行動IDは64種で重複しない():
    """★`_bs_emove_fptr_stage1_tbl` が 64 エントリだったことに合わせる。"""
    from dq3rom import enemy_detail as det

    assert len(det.MOVE_NAMES) == 64
    assert len(set(det.MOVE_NAMES)) == 64, "⚠ 名前が重複している"
    assert det.MOVE_ID_MASK == 0x3F, "⚠⚠ `AND #$3F` と食い違っている"


def test_耐性は14個で場所が重ならない():
    """★`sub_6B994` の `Y = 0x12 + i/3` とマスク `$C0,$30,$0C` に合わせる。"""
    from dq3rom import enemy_detail as det

    assert len(det.RESISTANCES) == 14
    seen = set()
    for index, off, shift, name, confidence in det.RESISTANCES:
        assert off == 0x12 + index // 3, "⚠ offset の式が違う（%s）" % name
        assert shift == 6 - 2 * (index % 3), "⚠ シフト量が違う（%s）" % name
        assert (off, shift) not in seen, "⚠⚠ 場所が重なっている（%s）" % name
        seen.add((off, shift))
        assert confidence in ("confirmed", "high-confidence",
                             "inferred", "unresolved")


def test_下位2bitを耐性として読んでいない():
    """★★★ ⚠⚠ **検査 B4** ★★★

    `+18..21` の下位 2 bit は GOLD/ATK/DEF/HP の上位ビットで、
    ⚠ **耐性ではありません**。★シフト 0 を使っていないことで見ます。
    """
    from dq3rom import enemy_detail as det

    for index, off, shift, name, _ in det.RESISTANCES:
        assert shift >= 2, "⚠⚠ %s が下位 2 bit を読んでいる" % name


def test_ドロップ率は式ではなく表():
    """⚠⚠ 2026-09-01 に**式で書いて間違えました**（★`odds=6` が `1/1` になった）。

    ★しきい値 `A` は確率ではありません。⚠ 逆アセンブルの表を写します。
    """
    from dq3rom import enemy_detail as det

    assert det.DROP_RATE[0] == "always"
    assert det.DROP_RATE[1] == "1/8"
    assert det.DROP_RATE[6] == "1/256"
    assert det.DROP_RATE[7] == "1/2048", "⚠ ボスの二段判定が反映されていない"
    assert sorted(det.DROP_RATE) == list(range(8))


def test_品なしを品として出さない():
    """★★★ ⚠⚠ `0x7F` は「品なし」（`ITEM_SWORD_HORNED` の流用）★★★

    ⚠ 実データ 139 体には 1 体もありませんが、★規則が無いと
      「品 127」という**存在しない品**を出してしまいます。
      （⚠ 「いま出ていない」は「正しい」ではありません。）
    """
    from dq3rom import enemy_detail as det

    raw = bytearray(23)
    raw[det.DROP_ITEM_OFFSET] = det.NO_ITEM_ID
    got = det.drop_of(bytes(raw))
    assert got["item_id"] is None and got["has_item"] is False

    raw[det.DROP_ITEM_OFFSET] = 0x80 | det.NO_ITEM_ID   # ⚠ 装備の旗つき
    assert det.drop_of(bytes(raw))["item_id"] is None

    raw[det.DROP_ITEM_OFFSET] = 0x65
    got = det.drop_of(bytes(raw))
    assert got["item_id"] == 0x65 and got["has_item"] is True


def test_耐性のしきい値が逆アセンブルの表と同じ():
    from dq3rom import enemy_detail as det

    assert det.RESIST_THRESHOLD == (0x00, 0x4D, 0xB3, 0xFF)
    assert det.DAMAGE_SCALE == (0xFF, 0xCC, 0x99, 0x80)


# --- ★★ 検査 A（行動）------------------------------------------------------


@needs_rom
def test_A1_全部の行動IDが既知の範囲に収まる(detail):
    """★★★ ⚠⚠ **識別性のある根拠** ★★★

    ⚠ 実データに **64〜127 の値が 1 つも無い**。★もし 1 バイト全部が
    行動 ID なら、この空白は説明できません。
    """
    from dq3rom import enemy_detail as det

    seen = set()
    for x in detail:
        for a in x.actions:
            seen.add(a["raw"])
            assert 0 <= a["move_id"] < 64
            assert not a["name"].startswith("unknown_")
    gap = sorted(v for v in seen if 64 <= v < 128)
    assert gap == [], "⚠⚠ 6bit + 旗 の読み方が崩れている: %s" % gap
    assert all((v & 0x40) == 0 for v in seen), "⚠ bit6 が立った（★未使用のはず）"


@needs_rom
def test_A2_複数の敵で意味のある行動になる(detail):
    """⚠ 全部が同じ行動なら、読み方が間違っています。"""
    import collections

    names = collections.Counter(a["name"] for x in detail for a in x.actions)
    assert names.most_common(1)[0][0] == "regular_attack", (
        "⚠⚠ 最多が通常攻撃でない（★読み方が疑わしい）")
    assert len(names) >= 20, "⚠ 行動の種類が少なすぎる: %d" % len(names)


@needs_rom
def test_A3_特殊行動が正しい敵に付いている(detail):
    """★★★ ⚠⚠ **これが本命の根拠** ★★★

    `zoma_freeze_beam`（0x2B）は、逆アセンブルで
    「ゾーマの指先から冷気」と名前が付いた行動です。
    ★これを持つ敵が**表のいちばん強い個体だけ**なら、
    ⚠ 行動 ID の対応が正しいことの、強い裏付けになります。
    """
    holders = [x.enemy_id for x in detail
               if any(a["name"] == "zoma_freeze_beam" for a in x.actions)]
    assert holders, "⚠⚠ 誰も持っていない（★対応がずれている）"
    assert len(holders) <= 3, "⚠⚠ %d 体も持っている（★多すぎる）" % len(holders)
    assert min(holders) > 120, (
        "⚠⚠ 表の前のほうの敵が持っている: %s" % holders)


@needs_rom
def test_A4_通常攻撃だけの敵と特殊持ちを区別できる(detail):
    plain = [x for x in detail
             if {a["name"] for a in x.actions} <= {"regular_attack", "assessing"}]
    fancy = [x for x in detail
             if any(a["category"] in ("heal", "spell_status", "breath")
                    for a in x.actions)]
    assert plain, "⚠ 通常攻撃だけの敵が 1 体も無い"
    assert fancy, "⚠ 特殊行動を持つ敵が 1 体も無い"
    assert not ({x.enemy_id for x in plain} & {x.enemy_id for x in fancy})


@needs_rom
def test_8枠は単純な8択ではない(detail):
    """⚠⚠ **bit7 は 4 つの 2bit 値を作っています**（★`sub_6B974`）。

    ⚠ どれかが常に 0 なら、読み方が疑わしい。
    """
    import collections

    for name, _, _, _ in __import__(
            "dq3rom.enemy_detail", fromlist=["x"]).CONTROL_FIELDS:
        got = collections.Counter(x.control[name]["value"] for x in detail)
        assert len(got) >= 2, "⚠⚠ %s が 1 種類しか無い: %s" % (name, dict(got))
        assert set(got) <= {0, 1, 2, 3}


# --- ★★ 検査 B（耐性）------------------------------------------------------


@needs_rom
def test_B1_敵ごとに耐性のrawが違う(detail):
    """⚠ 全員同じなら、そこは耐性ではありません。"""
    for name in detail[0].resistances:
        levels = {x.resistances[name]["level"] for x in detail}
        assert len(levels) >= 2, "⚠⚠ %s が全員同じ: %s" % (name, levels)


@needs_rom
def test_B3_耐性の方向が名前と合っている(detail):
    """★スライム（敵 0）は弱い敵なので、⚠ 眠りに強いはずがない。

    ⚠⚠ 1 体だけでは根拠になりません。★分布でも見ます。
    """
    slime = detail[0]
    assert slime.resistances["sleep"]["level"] == 0, (
        "⚠⚠ いちばん弱い敵がラリホーに耐性を持っている")
    # ★終盤の敵はラリホーが効きにくいはず
    late = [x.resistances["sleep"]["level"] for x in detail[-10:]]
    assert sum(late) / len(late) > 1.0, "⚠ 終盤の敵に眠り耐性が無い: %s" % late


#: ★★ 耐性を判定する呼び出し元（RX3-0266 / JP bank 4）: `LDA #耐性 / JSR $A3EF` の 5 バイトが ROM にそのままある
CALLERS = {0x9DB6: 6, 0x9E78: 7, 0x9EF7: 9, 0x9F57: 11, 0x9BA4: 12, 0xA735: 10, 0xA81B: 8}
#: ★攻撃呪文は呪文の番号で耐性 0〜3 を選ぶ（`$A4BF`: 0〜8 → 0 / 9〜12 → 1 / 13〜15 → 2 / 16〜 → 3）
ATTACK_PICK = bytes.fromhex("A549C909900CC90D900CC910900CA903D00AA900F006A901D002A90220EFA3")


def _bank4(addr: int) -> int:
    """★JP bank 4（$8000-$BFFF）の CPU 番地 → PRG の位置。"""
    return 4 * 0x4000 + (addr - 0x8000)


@needs_rom
def test_耐性の名前は呼び出し元で確かめたもの(detail):
    """⚠⚠ **分からないものを分かったことにしない**（指示書 §27）→ ★RX3-0266 で 14 個とも呼び出し元を確かめた。

    ⚠ 以前は北米版のファイルで近くにあった処理名から付けていて、5 つ外れていた
      （unknown_1 / numboff / unknown_3 / pc_damage_8 / damage_reduction の説明）。
    ★名前ではなく **ROM の命令**で確かめる: 耐性の番号を積んで `$A3EF` を呼ぶ 5 バイトがその番地にある。
    """
    from dq3.testing.npc_rom import _prg
    from dq3rom import enemy_detail as det

    got = detail[0].resistances
    for old in ("unknown_1", "unknown_3", "pc_damage_8", "numboff"):
        assert old not in got, "⚠⚠ 外れていた名前が残っている: %s" % old
    by_index = {i: name for i, _off, _sh, name, _c in det.RESISTANCES}
    assert (by_index[1], by_index[2], by_index[3], by_index[8]) == (
        "ice_spells", "wind_spells", "lightning_spells", "sap")
    assert all(conf == "confirmed" for *_x, conf in det.RESISTANCES)
    prg = _prg(None)
    for addr, index in CALLERS.items():
        at = _bank4(addr)
        assert prg[at:at + 5] == bytes([0xA9, index, 0x20, 0xEF, 0xA3]), (
            "⚠⚠ $%04X は耐性 %d の判定を呼んでいない: %s" % (addr, index, prg[at:at + 5].hex()))
    at = _bank4(0xA4BF)
    assert prg[at:at + len(ATTACK_PICK)] == ATTACK_PICK, "⚠⚠ 攻撃呪文の耐性の選び方が違う"
    # ★攻撃呪文は効く / 効かないの二択（`BCS $A4E6` = ダメージを入れる）。⚠ 倍率はブレス（`$98C7` の表 $98F3）だけ
    at = _bank4(0xA4DE)
    assert prg[at:at + 2] == bytes([0xB0, 0x06])
    at = _bank4(0x98F3)
    assert tuple(prg[at:at + 4]) == det.DAMAGE_SCALE


@needs_rom
def test_耐性10はマホトラ(detail):
    """★RX3-0260（2026-09-14）: 索引 10 はマホトラ（JP bank 4 $A735 `LDA #$0A`）。⚠ 以前は `pc_damage_10`（inferred）。

    ★ROM の表とも合う: 最大 MP 0 の敵は、ほぼ全部この耐性が 3（決して効かない）。
    """
    from dq3rom import spells as SP

    got = detail[0].resistances
    assert got["robmagic"]["confidence"] == "confirmed" and "pc_damage_10" not in got
    assert SP.RESIST_FIELD[23] == "robmagic", "⚠ マホトラ（呪文 23）の耐性が呪文の表に無い"
    no_mp = [x for x in detail if x.base.mp == 0] if hasattr(detail[0], "base") else []
    if no_mp:
        never = sum(1 for x in no_mp if x.resistances["robmagic"]["level"] == 3)
        assert never >= len(no_mp) - 1, "⚠ 最大 MP 0 の敵の多くがマホトラの耐性 3 でない: %d / %d" % (never, len(no_mp))


# --- ★★ 検査 C（ドロップ）--------------------------------------------------


@needs_rom
def test_C1_ドロップ品がitem_idへ繋がる(detail):
    """★`+9` は `AND #$7F` で item、bit7 は装備の旗（⚠ `_b4_s17`）。"""
    ids = {x.drop["item_id"] for x in detail}
    assert all(0 <= i < 128 for i in ids)
    assert len(ids) >= 20, "⚠ ドロップ品の種類が少なすぎる: %d" % len(ids)
    assert any(x.drop["equip_bit"] for x in detail), "⚠ 装備の旗が 1 件も無い"


@needs_rom
def test_C3_ドロップ率で敵を区別できる(detail):
    """★★★ ⚠⚠ **識別性のある根拠** ★★★

    ★`odds=7` は二段判定（1/2048）で、⚠ **めったに使われないはず**です。
    ★いちばん強い敵がそこに入っていれば、`+22` の下位 3 bit の読み方の裏付け
    になります。

    ## ⚠⚠ 逆アセンブルの註釈は当たっていませんでした

      註釈は「`seems to be used only for big bosses (at the end of the
      enemy list)`」と書いています。⚠ ですが日本版の実データでは、
      **9 体のうち 2 体（敵 75 / 138）が HP 60・順位 76 位と 78 位**でした。

      ★註釈は `seems to` という**推定**なので、⚠ 事実のほうを採ります。
      （★これは逆アセンブル資料の記述を**鵜呑みにしない**という指示書 §2 の実例。）
    """
    import collections

    rates = collections.Counter(x.drop["rate"] for x in detail)
    assert len(rates) >= 4, "⚠ 率が分かれていない: %s" % dict(rates)
    boss = [x.enemy_id for x in detail if x.drop["rate"] == "1/2048"]
    assert boss, "⚠ 二段判定の敵が 1 体も無い"
    assert len(boss) <= 15, "⚠⚠ %d 体もある（★めったに使わないはず）" % len(boss)
    # ★いちばん強い 2 体は必ず入っている（⚠ これが識別性のある根拠）
    from dq3rom import enemies as en
    from dq3rom import profile as dq3

    rows = en.read_all(dq3.load_and_identify(ROM_PATH))
    strongest = [e.enemy_id for e in sorted(rows, key=lambda e: -e.hp)[:2]]
    assert set(strongest) <= set(boss), (
        "⚠⚠ 最強の 2 体が二段判定でない（★読み方がずれている）%s / %s"
        % (strongest, boss))


# --- ★raw を失わない --------------------------------------------------------


@needs_rom
def test_rawを必ず持っている(detail):
    """⚠⚠ 解釈が訂正されても、★ROM を読み直さなくてよいこと（指示書 §17）。"""
    from dq3rom import enemies as en

    for x in detail[:5]:
        js = x.to_json()
        assert len(js["actions_raw"]) == 8
        assert len(js["resistance_raw"]) == 5
        assert len(js["drop_raw"]) == 2
        assert len(x.raw) == en.ENTRY_SIZE
        # ★raw から decoded を作り直せる
        from dq3rom import enemy_detail as det
        again = det.EnemyDetail.from_raw(x.enemy_id, x.raw)
        assert again.to_json() == js


@needs_rom
def test_139体すべて解ける(detail):
    assert len(detail) == 139
    for x in detail:
        assert len(x.actions) == 8
        assert len(x.resistances) == 14
        assert x.drop["rate"]


# --- ★★ 攻撃呪文の行動 → 唱える呪文（RX3-0224 / 2026-09-12）-----------------------


#: ★北米版の表の並び（行動 0x13〜0x1E）を北米版 `spell_ids.inc` の番号にしたもの（★= 我々の呪文 ID）
NA_ATTACK_SPELLS = (0x00, 0x01, 0x02, 0x09,            # BLAZE BLAZEMORE BLAZEMOST ICEBOLT
                    0x03, 0x04, 0x08, 0x0A, 0x0B,      # FIREBAL FIREBANE EXPLODET SNOWBLAST SNOWSTORM
                    0x0D, 0x0E, 0x0F)                  # INFERNOS INFERMORE INFERMOST
DISASM = ROOT / "work" / "research" / "dq3-disasm" / "disassembly"


@pytest.fixture(scope="module")
def prg():
    from dq3rom import profile as dq3

    return dq3.load_and_identify(ROM_PATH).rom.prg


def _fake_prg(*, single_ref=True, party_ref=True, table=NA_ATTACK_SPELLS) -> bytes:
    """★表と、それを読むコードだけを置いた PRG（⚠ ROM は要らない / 歯止めが鳴るかを見る）。"""
    from dq3rom import enemy_detail as det

    prg = bytearray(0x40000)
    start = det.ATTACK_SPELL_TABLE["file"]
    prg[start:start + len(table)] = bytes(table)
    bank = start // 0x4000 * 0x4000
    cpu = 0x8000 + start % 0x4000
    if single_ref:
        prg[bank + 0x100:bank + 0x107] = bytes([0x38, 0xE9, 0x13, 0xAA, 0xBD, cpu & 0xFF, cpu >> 8])
    if party_ref:
        cpu += 4
        prg[bank + 0x200:bank + 0x207] = bytes([0x38, 0xE9, 0x17, 0xAA, 0xBD, cpu & 0xFF, cpu >> 8])
    return bytes(prg)


def test_攻撃呪文の表は行動の範囲とちょうど同じ長さ():
    from dq3rom import enemy_detail as det

    spec = det.ATTACK_SPELL_TABLE
    assert det.MOVE_CATEGORY["spell_damage"] == tuple(
        range(spec["first_move"], spec["first_move"] + spec["count"]))
    assert spec["party_move"] - spec["first_move"] == 4, "⚠ 1 体向けの表は 4 つ（0x13..0x16）"


def test_攻撃呪文の表は裏が取れたときだけ引く():
    """⚠⚠ 歯止めが**鳴る**こと（★コードが指していない / 値が重複・範囲外 → None）。ROM は要らない。"""
    import types

    from dq3rom import enemy_detail as det

    good = _fake_prg()
    assert det.spell_of_move(good, 0x13) == 0x00
    assert det.spell_of_move(good, 0x17) == 0x03
    assert det.attack_spells(good) == dict(zip(range(0x13, 0x1F), NA_ATTACK_SPELLS))
    assert det.spell_of_move(types.SimpleNamespace(rom=types.SimpleNamespace(prg=good)), 0x1E) == 0x0F
    assert det.spell_of_move(_fake_prg(single_ref=False), 0x17) is None, "⚠ コードが指していないのに読んだ"
    assert det.spell_of_move(_fake_prg(party_ref=False), 0x13) is None
    assert det.spell_of_move(_fake_prg(table=(0,) * 12), 0x13) is None, "⚠ 重複した値を通した"
    assert det.spell_of_move(_fake_prg(table=(0x40,) + NA_ATTACK_SPELLS[1:]), 0x14) is None, "⚠ 呪文 ID の外"
    assert det.spell_of_move(b"", 0x13) is None
    assert det.spell_of_move(None, 0x13) is None
    assert det.attack_spells(b"") == {}
    for move_id in (0x0A, 0x12, 0x1F, 0x31):
        assert det.spell_of_move(good, move_id) is None, "⚠ 攻撃呪文でない行動 %02X に呪文が付いた" % move_id


def test_北米版の表と注釈は同じ並び():
    """★手で写した `NA_ATTACK_SPELLS` の裏取り: 逆アセンブルの表と `MOVE_NAMES` の「★注釈」。

    ⚠ 逆アセンブル（`work/research/dq3-disasm/`）が無い環境では skip します。
    """
    import re

    inc = DISASM / "spell_ids.inc"
    if not inc.exists():
        pytest.skip("⚠ 逆アセンブルが手元に無い")
    ids = {m.group(1): int(m.group(2), 16) for m in re.finditer(
        r"^SPELL_(\w+) = \$([0-9A-Fa-f]+)", inc.read_text(encoding="utf-8"), re.M)}
    bank = (DISASM / "bank04.inc").read_text(encoding="utf-8", errors="replace")
    body = bank.split("_bs_attackspell_single_tbl:", 1)[1].split("_bs_heal_single_tbl:", 1)[0]
    assert tuple(ids[n] for n in re.findall(r"#SPELL_(\w+)", body)) == NA_ATTACK_SPELLS

    src = (ROOT / "dq3rom" / "enemy_detail.py").read_text(encoding="utf-8")
    notes = re.findall(r"# 0x(1[3-9A-E]) ★注釈: (\w+)", src)
    assert [int(h, 16) for h, _ in notes] == list(range(0x13, 0x1F))
    assert tuple(ids[n] for _, n in notes) == NA_ATTACK_SPELLS


@needs_rom
def test_攻撃呪文の表はROMに1件だけ(prg):
    """★北米版の並び（呪文の定数を番号にしたもの）で ROM 全体を探して 1 件だけ、しかも ROM のコードが指す番地。"""
    from dq3rom import enemy_detail as det

    want = bytes(NA_ATTACK_SPELLS)
    first = prg.find(want)
    assert first == det.ATTACK_SPELL_TABLE["file"], hex(first)
    assert prg.find(want, first + 1) == -1, "⚠ 2 か所目がある"
    assert det.attack_spell_table(prg) == want


@needs_rom
def test_攻撃呪文はROMの呪文になる(prg):
    """★0x13 = 呪文 0（メラ）/ 0x17 = 呪文 3（ギラ）/ 12 個すべてが北米版の注釈の順。"""
    from dq3.knowledge import rom_names
    from dq3rom import enemy_detail as det

    got = det.attack_spells(prg)
    assert got == dict(zip(range(0x13, 0x1F), NA_ATTACK_SPELLS))
    assert got[0x13] == 0 and rom_names.spell(0) == "メラ"
    assert got[0x17] == 3 and rom_names.spell(3) == "ギラ"
    assert all(rom_names.spell(sid) for sid in got.values()), "⚠ 名前が引けない呪文がある"
