"""アイテムの性能を ROM から起こす（RX3-0082 §16 / §25）。

```text
5 つの表が JP ROM に 1 件ずつ / 全 125 件が正気か / 装備マスクが実データと合うか
分類は表ではなく ID の範囲 / 値段は ×10（⚠ ラベルは mul_9 だが中身は ×10）
```
"""
from __future__ import annotations

import pathlib

import pytest

from dq3rom import item_meta as IM

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
DISASM = ROOT / "work" / "dq3-disasm" / "disassembly"


def _rom_ready() -> bool:
    try:
        from dq3rom import profile as P

        P.load_and_identify(ROM_PATH)
    except Exception:                                      # noqa: BLE001
        return False
    return True


needs_rom = pytest.mark.skipif(not _rom_ready(), reason="DQ3 の ROM が読めない")


@pytest.fixture(scope="module")
def prg():
    from dq3rom import profile as P

    return P.load_and_identify(ROM_PATH).rom.prg


@pytest.fixture(scope="module")
def rows(prg):
    return IM.build(prg)


# --- ★表そのもの ---------------------------------------------------------------

@needs_rom
def test_5つの表がROMの中にある(prg):
    got = IM.read_tables(prg)
    assert set(got) == set(IM.TABLES)
    for key, data in got.items():
        assert len(data) == IM.TABLES[key]["count"], key


@needs_rom
def test_表の位置は北米版の逆アセンブルと1バイトも違わない(prg):
    """★★ これが位置の裏取り。⚠ 1 バイトずれたら**別の場所**に見つかる。

    ⚠ 逆アセンブル（`work/dq3-disasm/`）が無い環境では skip します。
    """
    import re

    if not DISASM.exists():
        pytest.skip("⚠ 逆アセンブルが手元に無い")

    def table_bytes(bank_file, symbol):
        text = (DISASM / bank_file).read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^%s:\r?\n((?:\s*\.BYTE.*\r?\n)+)" % re.escape(symbol), text, re.M)
        assert m, symbol
        out = []
        for line in m.group(1).splitlines():
            for tok in line.split(".BYTE", 1)[1].split(","):
                tok = tok.strip().lstrip("#")
                if tok.startswith("$"):
                    out.append(int(tok[1:], 16))
                elif tok.isdigit():
                    out.append(int(tok))
        return bytes(out)

    where = {"equip_mask": "bank00.inc", "use_mask": "bank00.inc", "use_effect": "bank00.inc",
             "effect_arg": "bank00.inc", "pri_stat": "bank09.inc"}
    for key, spec in IM.TABLES.items():
        want = table_bytes(where[key], spec["symbol"])
        assert len(want) == spec["count"], key
        start = spec["file"]
        assert prg[start:start + len(want)] == want, "⚠⚠ %s の位置がずれている" % key
        # ★ROM 全体で 1 件だけ（⚠ たまたま当たったのではない）
        hits = sum(1 for i in range(len(prg) - len(want)) if prg[i:i + len(want)] == want)
        assert hits == 1, "⚠ %s が %d 件見つかる" % (key, hits)


# --- ★分類（⚠ 表ではなく ID の範囲）-------------------------------------------------

@pytest.mark.parametrize("item_id, wanted", [
    (0x00, "weapon"), (0x1F, "weapon"), (0x20, "armor"), (0x37, "armor"),
    (0x38, "shield"), (0x3E, "shield"), (0x3F, "helm"), (0x46, "helm"),
    (0x47, "accessory"), (0x4B, "accessory"), (0x4C, "tool_class"), (0x4F, "tool_class"),
    (0x50, "item"), (0x7C, "item"), (0x7D, "unknown"), (0xFF, "unknown"),
])
def test_分類はIDの範囲で決まる(item_id, wanted):
    assert IM.category_of(item_id) == wanted


# --- ★値段（⚠ ラベルに騙されない）---------------------------------------------------

def test_値段は10倍ずつ():
    """⚠⚠ `_argC0_mul_9` は名前に反して **×10**（★ASL / 保存 / ASL / ASL / 足す）。"""
    assert IM.PRICE_STEP == 10


def test_売値は買値の4分の3():
    """★`_bD_s13`: 買値 − (買値 + 3) / 4。"""
    assert IM.sell_price(100) == 75
    assert IM.sell_price(0) == 0
    assert IM.sell_price(5) == 3
    assert all(IM.sell_price(b) <= b for b in range(0, 5000, 37))


@needs_rom
def test_実データで値段が合う(rows):
    """★店で買えるものを 4 件（⚠ 攻略サイトではなく、★ゲームの表から出した値）。

    ⚠⚠ ×9 だと 4 件とも外れます（★これが「×10 である」ことの裏取り）。
    """
    by_id = {r.item_id: r for r in rows}
    for item_id, wanted in ((0x00, 5), (0x01, 30), (0x02, 100), (0x20, 10), (0x38, 90)):
        assert by_id[item_id].buy_price == wanted, "id $%02X" % item_id


# --- ★★ 全 125 件の正気（指示書 §16）------------------------------------------------

@needs_rom
def test_全件が正気(rows):
    assert IM.check(rows) == []
    assert len(rows) == 125


def test_正気の検査そのものが鳴る():
    """⚠⚠ 検出器にも検査を書く（★2026-09-05: `check` を素通しに壊しても鳴らなかった）。

    ★「プログラムが動いた」だけで CONFIRMED にしない（指示書 §16）。
    """
    import dataclasses

    def one(**over):
        base = dict(item_id=0, category="weapon", pri_stat=5, equip_mask=0x01,
                    use_mask=None, use_effect=0, effect_arg=0, buy_price=10,
                    sell_price=7, flags=())
        base.update(over)
        return IM.ItemMeta(**base)

    # ★件数が違う
    assert any("125" in p for p in IM.check([one()]))
    # ★攻守が全部同じ
    same = [dataclasses.replace(one(item_id=i), pri_stat=5) for i in range(125)]
    assert any("攻守" in p for p in IM.check(same))
    # ★値段が全部同じ
    assert any("値段" in p for p in IM.check(same))
    # ★誰でも装備できる
    allmask = [dataclasses.replace(one(item_id=i), equip_mask=0xFF, pri_stat=i,
                                   buy_price=i * 3) for i in range(125)]
    assert any("装備" in p for p in IM.check(allmask))
    # ★分類が 0 件
    none_cat = [dataclasses.replace(one(item_id=i), category="weapon", pri_stat=i,
                                    buy_price=i * 3, equip_mask=i % 200) for i in range(125)]
    assert any("armor" in p for p in IM.check(none_cat))
    # ★ありえない値段
    crazy = [dataclasses.replace(one(item_id=i), category=IM.category_of(i), pri_stat=i,
                                 buy_price=999999 if i == 3 else i * 3,
                                 equip_mask=i % 200) for i in range(125)]
    assert any("ありえない" in p for p in IM.check(crazy))


@needs_rom
def test_分類の件数が偏っていない(rows):
    import collections

    got = collections.Counter(r.category for r in rows)
    # ⚠⚠ 武器が 33・装飾品が 4 なのは**わざと**（RX3-0284 / 2026-09-18）。
    #   ★おうごんのつめ（$4A）は ID の並びでは装飾品の範囲だが、
    #   ゲーム自身の分類（bank 0 `$9C43`）の先頭が `CMP #$4A / BEQ → 武器`。
    assert got["weapon"] == 33 and got["armor"] == 24
    assert got["shield"] == 7 and got["helm"] == 8
    assert got["accessory"] == 4 and got["item"] == 45
    assert IM.category_of(0x4A) == "weapon"


@needs_rom
def test_攻守は装備品だけに付く(rows):
    for r in rows:
        if r.item_id <= IM.GEAR_MAX:
            assert r.pri_stat is not None, r.item_id
        else:
            assert r.pri_stat is None, r.item_id
    gear = [r.pri_stat for r in rows if r.pri_stat is not None]
    assert len(set(gear)) >= 30, "⚠ 攻守が同じ値ばかり（★表の位置が違う）"


@needs_rom
def test_重要品は汎用の印で表せる(rows):
    """★「捨てられない」は **bit $10** という汎用属性（⚠ 個別分岐ではない）。"""
    flagged = [r for r in rows if not r.can_discard]
    assert 20 <= len(flagged) <= 60, len(flagged)
    # ★鍵とオーブは捨てられない側（⚠ id で見る。名前は書かない）
    for item_id in (0x58, 0x59, 0x5A):
        assert not next(r for r in rows if r.item_id == item_id).can_discard


@needs_rom
def test_呪いと消費も同じ印から取れる(rows):
    cursed = [r for r in rows if "cursed" in r.flags]
    consumed = [r for r in rows if "consumed" in r.flags]
    assert 1 <= len(cursed) <= 20 and 10 <= len(consumed) <= 60


# --- ★★ 実データで裏を取る（指示書 §18: static → hypothesis → dynamic）------------------

def _savestates():
    d = ROOT / "tools" / "fceux" / "fcs"
    return sorted(d.glob("DQ3_J*.fc[0-9]")) if d.exists() else []


@needs_rom
@pytest.mark.skipif(not _savestates(), reason="セーブステートが無い")
def test_実際に装備しているものは装備マスクを通る(rows):
    """★★ これが装備マスクの裏取り（2026-09-05: **146 / 146 一致**）。

    ⚠ マスクの読み方（`1 << class`）か表の位置が違えば、必ず不一致が出ます。
    """
    from retroux.tools.ram import read_savestate

    by_id = {r.item_id: r for r in rows}
    ok = bad = 0
    for path in _savestates():
        try:
            ram = read_savestate(path)
        except Exception:                                  # noqa: BLE001
            continue
        hp_max = [ram[0x0724 + 2 * i] | (ram[0x0725 + 2 * i] << 8) for i in range(4)]
        for member in range(4):
            if hp_max[member] == 0:
                continue                                   # ⚠ 居ない枠
            cls = ram[IM.CLASS_GENDER_ADDR + member] & IM.CLASS_MASK
            start = IM.INVENTORY_ADDR + 8 * member
            for raw in ram[start:start + 8]:
                if raw == 0xFF or not (raw & 0x80):
                    continue                               # ⚠ 空き / 装備していない
                meta = by_id.get(raw & 0x7F)
                assert meta is not None and meta.equip_mask is not None, hex(raw)
                if meta.equip_mask & (1 << cls):
                    ok += 1
                else:
                    bad += 1
    assert ok >= 100, "⚠ 装備品を %d 件しか見ていない" % ok
    assert bad == 0, "⚠⚠ 装備しているのにマスクが拒む: %d 件" % bad


@needs_rom
@pytest.mark.skipif(not _savestates(), reason="セーブステートが無い")
def test_袋の番地はJPでは076C():
    """⚠⚠ 北米版の `_players_inventory_list` は `$077C`。★JP は **16 バイト前**。

    ⚠ `dq3rom/items.py` は北米版の値のままでした（★検査でしか使っていないので実害なし）。
    """
    from dq3.knowledge import rom_names
    from retroux.tools.ram import read_savestate

    rom_names.reset()
    if rom_names._load() is None:
        pytest.skip("⚠ 名前辞書が使えない環境")
    # ★読むのは**動かない固定セーブ**を先に（2026-09-12）。⚠ 遊びのセーブは撮り直すたびに中身が変わる
    #   （★依頼者の新しいセーブで、下の比べ方がたまたま同じ数になり赤くなった）
    from dq3.testing import fixtures as FX

    try:
        src = FX.get("battle_ai_tower_walk").path
    except FX.FixtureError:
        src = _savestates()[0]
    ram = read_savestate(src)
    good = bad = 0
    raw = {}
    for addr, bucket in ((IM.INVENTORY_ADDR, "jp"), (0x077C, "us")):
        rows_ = [ram[addr + 8 * m:addr + 8 * (m + 1)] for m in range(4)]
        raw[bucket] = b"".join(bytes(r) for r in rows_)
        filled = sum(1 for r in rows_ for b in r if b != 0xFF)
        named = sum(1 for r in rows_ for b in r if b != 0xFF and rom_names.item(b))
        if bucket == "jp":
            good = (filled, named)
        else:
            bad = (filled, named)
    assert good[1] == good[0] and good[0] >= 8, "⚠ $076C の中身が品名に解けない"
    # ⚠⚠ 数の組（埋まっている数・名前の付く数）で比べると、**たまたま同じ数**で赤くなる（2026-09-12 に踏んだ /
    #   (22, 22) と (22, 22)）。★ずれの確認は**中身そのもの**で見る
    assert raw["jp"] != raw["us"], "⚠ $076C と $077C の中身が同じ（★ずれの確認になっていない）"


# --- ★★ 戦闘で使ったときの効果（RX3-0213 / 2026-09-12）-----------------------------------

def test_戦闘の効果は若いIDから数えた番号で引く():
    """★ROM と同じ数え方（`loc_6AEA2`）: d42 bit7 の品を若い順に数える。⚠ ROM は要らない。"""
    use = bytearray(IM.BATTLE_SCAN_END)
    for i in (3, 10, 11):
        use[i] = 0x80
    use[4] = 0x40                                          # ⚠ bit $40 だけでは数えない
    assert IM.battle_effect_index(bytes(use), 3) == 0
    assert IM.battle_effect_index(bytes(use), 10) == 1
    assert IM.battle_effect_index(bytes(use), 11) == 2
    assert IM.battle_effect_index(bytes(use), 11 | 0x80) == 2, "⚠ 装備の bit7 を落としていない"
    assert IM.battle_effect_index(bytes(use), 4) is None
    assert IM.battle_effect_index(bytes(use), 0x7F) is None


@needs_rom
def test_戦闘の効果の表はROMに1件だけ(prg):
    """★北米版 `_bs_item_effect_tbl` の先頭 12 個（呪文の定数を JP の番号にしたもの）で一意。"""
    table = IM.battle_effect_table(prg)
    assert len(table) == IM.BATTLE_EFFECT_TABLE["count"] == 40
    head = bytes([0x00, 0x05, 0x0A, 0x24, 0x30, 0x27, 0x07, 0x04, 0x0F, 0x2C, 0x0D, 0x1B])
    assert table[:len(head)] == head
    hits = sum(1 for i in range(len(prg) - len(head)) if prg[i:i + len(head)] == head)
    assert hits == 1, "⚠ 表の頭が %d 件見つかる" % hits


@needs_rom
def test_戦闘で使える品の数と表の長さが合う(prg):
    """⚠⚠ 数え方か表の位置が違えば、ここで数が合わなくなる（★黙って通さない）。"""
    got = IM.battle_effects(prg)
    assert len(got) == IM.BATTLE_EFFECT_TABLE["count"]
    assert all(IM.battle_effect(prg, i) == sid for i, sid in got.items())


@needs_rom
def test_まどうしのつえはメラで減らない(prg, rows):
    """★依頼者 save3（2026-09-12）。★id だけで見る（⚠ 名前は repo に持たない）。"""
    assert IM.battle_effect(prg, 0x07) == 0x00, "⚠ $07 が呪文 0（メラ）にならない"
    assert IM.battle_effect(prg, 0x87) == 0x00, "⚠ 装備中（bit7）の袋の値で引けない"
    assert IM.battle_effect(prg, 27) == 0x04, "⚠ $1B が呪文 4 にならない"
    assert IM.battle_effect(prg, 0x1F) == 0x0D
    assert IM.battle_effect(prg, 0x00) is None, "⚠ 戦闘で使えない武器に効果が付いた"
    wand = next(r for r in rows if r.item_id == 0x07)
    assert "battle_use" in wand.flags and "consumed" not in wand.flags, wand.flags
    assert wand.use_mask == 0xFF, "⚠ 全職業が使えるはず"
    # ★d44 は値段の基数（⚠ 効果の引数ではない / RX3-0213 で訂正）
    assert wand.effect_arg == 15 and wand.buy_price == 1500
