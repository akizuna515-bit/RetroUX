"""差し替え先の表に替わった町でも、既定の表の番号に直して聞き込み・街移動を動かす（RX3-0231 / 2026-09-13）。

⚠⚠ 依頼者「save4 バハラタで、街移動がアクティブになっていない。聞き込みで表が読めません。と出る。」
★グプタのイベントのあと、バハラタ（map 14）の町の人は差し替え先の表 0xC0（15 人）に替わる。
⚠ 差し替え先の表の npc_id（記録の順）は既定の表とぶつかる → ★既定の表の同じ人の番号へ直して使う。
⚠ 直せない（1 人でも決まらない）/ 2 つの表と一致する → 今までどおり空（安全側）。
"""
from __future__ import annotations

import pytest

from dq3.knowledge import npc_heard as H
from dq3.knowledge import npc_master as NM
from dq3.knowledge.town_service import TownService, hearing_target

BAHARATA = 14
SAVE4_FIXTURE = "town_map14_save4"
TIME_ADDR = 0x06DF          # ★`dev.lua` の time_byte と同じ番地


def _ready() -> bool:
    try:
        return len(NM._lists()) > 1
    except Exception:                                            # noqa: BLE001
        return False


needs_rom = pytest.mark.skipif(not _ready(), reason="DQ3 の ROM が読めない")


def _ledger(tid: int, map_id: int = BAHARATA):
    return NM._rom.map_ledger(map_id, NM._lists()[tid], False)["npcs"]


def _table(npcs) -> str:
    """★表の NPC から実機の形（1 人 4 バイト / FF FF で終わり）を作る。"""
    out = bytearray()
    for n in sorted(npcs, key=lambda n: n["slot"]):
        out += bytes([n["initial_x"] or 0, n["initial_y"] or 0, 0, 0x80 if n["movement"] == "fixed" else 0x00])
    return (out + b"\xff\xff\xff\xff").hex()


def _hide(tbl_hex: str, slots) -> str:
    raw = bytearray.fromhex(tbl_hex)
    for s in slots:
        o = (s - NM._rom.NPC_FIRST_SLOT) * 4
        raw[o:o + 2] = bytes(NM.HIDDEN_XY)
    return raw.hex()


# --- ★表を選ぶ -----------------------------------------------------------------

@needs_rom
def test_バハラタの差し替え先0xC0と一致すれば既定の番号で使う():
    default = {n["npc_id"]: n for n in _ledger(BAHARATA)}
    got = NM.master_for(BAHARATA, 0, _table(_ledger(0xC0)))
    assert got["status"] == "DEFAULT" and got.get("table_id") == 0xC0, "⚠⚠ バハラタの表が読めない（依頼者の save4）"
    ids = [n["npc_id"] for n in got["npcs"]]
    assert len(ids) == 15 and len(set(ids)) == 15 and set(ids) <= set(default)
    for n in got["npcs"]:
        assert NM._person_key(n) == NM._person_key(default[n["npc_id"]]), "⚠ 別人の番号に直している"
    # ⚠ 差し替え先の表の番号のままだと取り違える人がいる（★直す意味がある）
    assert any(n["npc_id"] != n["table_npc_id"] for n in got["npcs"])


@needs_rom
def test_2つの差し替え先と一致するなら空のまま():
    """⚠ 0xC0 と 0xC2 の違いは slot 6 の 1 人だけ。★その人が消えていたら、どちらの表か決められない。"""
    variant = _ledger(0xC0)
    tbl = _hide(_table(variant), [variant[2]["slot"]])
    slots = {s["slot"]: s for s in NM.runtime_slots(tbl)}
    assert NM._table_matches(_ledger(0xC0), slots) and NM._table_matches(_ledger(0xC2), slots)
    assert NM.runtime_variant_table(BAHARATA, 0, tbl) is None
    got = NM.master_for(BAHARATA, 0, tbl)
    assert got["status"] == "UNKNOWN" and got["npcs"] == []


@needs_rom
def test_1人でも既定の表の人に決まらなければ直さない():
    default, variant = _ledger(BAHARATA), _ledger(0xC0)
    assert NM.renumber(variant, default) is not None
    moved = [dict(n) for n in variant]
    moved[0]["appearance_id"] = 0xEE                       # ★既定の表に居ない見た目
    assert NM.renumber(moved, default) is None
    twice = [dict(n) for n in variant] + [dict(variant[0])]  # ★同じ人が 2 人
    assert NM.renumber(twice, default) is None


# --- ★聞いた人 ----------------------------------------------------------------

@needs_rom
def test_台詞が替わった人はもう一度聞く(tmp_path):
    """★グプタのイベントの前（既定の表）に全員から聞いていても、⚠ 台詞が替わった人はまだ聞いていない。"""
    svc = TownService(heard=H.HeardLedger(tmp_path))
    for n in _ledger(BAHARATA):
        svc.heard.record(BAHARATA, n["npc_id"], n["talk_id"], text="イベントの前")
    svc.heard.save()                                       # ⚠ `current_npcs` は台帳をファイルから読み直す（RX3-0059）
    tbl = _table(_ledger(0xC0))
    master = {n["npc_id"]: n for n in NM.master_for(BAHARATA, 0, tbl)["npcs"]}
    rows = svc.current_npcs(BAHARATA, 0, tbl)["npcs"]
    changed = [n for n in rows if master[n["npc_id"]]["default_talk_id"] != n["talk_id"]]
    same = [n for n in rows if master[n["npc_id"]]["default_talk_id"] == n["talk_id"]]
    assert len(changed) == 1 and len(same) == 14
    assert all(n["variant"] for n in rows)
    assert not svc.heard_now(BAHARATA, changed[0]), "⚠⚠ 台詞が替わったのに聞いたことにしている"
    assert all(svc.heard_now(BAHARATA, n) for n in same), "⚠ 同じ台詞の人まで聞き直させている"
    want = sum(1 for n in same if hearing_target(n))
    assert svc.counts(BAHARATA, 0, tbl)["heard"] == want


@needs_rom
def test_既定の表の人は台詞の番号を見ない(tmp_path):
    """⚠ 差し替えの無い町・既定の表の人は今までどおり（★台詞の番号が違う記録でも済み）。"""
    svc = TownService(heard=H.HeardLedger(tmp_path))
    npc = {"npc_id": 3, "talk_id": 0x123, "variant": False}
    svc.heard.record(9, 3, 0x456)
    assert svc.heard_now(9, npc)
    assert not svc.heard.is_heard(9, 3, talk_id=0x123)
    assert svc.heard.is_heard(9, 3, talk_id=0x456)


# --- ★依頼者の save4 ------------------------------------------------------------

@pytest.fixture(scope="module")
def save4():
    """★依頼者の save4（バハラタ / 差し替え先の表 0xC0 が効いている / 15 人）。"""
    from dq3.testing import fixtures as FX
    from retroux.tools.ram import read_savestate

    try:
        fx = FX.get(SAVE4_FIXTURE)
    except FX.FixtureChanged:
        raise                                            # ⚠⚠ 中身が変わった fixture は skip にしない（★赤くする）
    except FX.FixtureError as err:
        pytest.skip("⚠ fixture が使えない: %s" % err)
    ram = read_savestate(fx.path)
    pos = (fx.expected or {}).get("local_pos")
    return {"npc_tbl": bytes(ram[0x0110:0x0178]).hex(), "time_byte": ram[TIME_ADDR],
            "pos": tuple(pos) if pos else None}


@needs_rom
def test_依頼者のsave4で聞き込みの候補と目的地がある(save4, tmp_path):
    if save4["pos"] is None:
        pytest.skip("⚠ fixture に位置が無い")
    svc = TownService(heard=H.HeardLedger(tmp_path))
    args = (BAHARATA, save4["time_byte"], save4["npc_tbl"])
    cur = svc.current_npcs(*args)
    assert cur["status"] == "DEFAULT" and cur["table_id"] == 0xC0, "⚠⚠ 「この町の人の表が読めません」のまま"
    assert len(cur["npcs"]) == 15
    assert svc.unheard_reachable_npcs(*args, save4["pos"]), "⚠⚠ 聞き込みの候補が 0 人"
    # ★施設の人を聞いたことにすれば、街移動の目的地が出る
    for n in cur["npcs"]:
        if n.get("role") and n.get("role_status") == "CONFIRMED":
            svc.heard.record(BAHARATA, n["npc_id"], n["talk_id"])
    svc.heard.save()                                       # ⚠ `current_npcs` は台帳をファイルから読み直す（RX3-0059）
    got = svc.known_reachable_facilities(*args, save4["pos"])
    assert {f["role"] for f in got} >= {"inn", "item_shop"}
    assert got, "⚠⚠ 街移動の目的地が空（ボタンが押せない）"


# --- ★依頼者の save8（RX3-0243）---------------------------------------------------
#
#   ⚠⚠ 2026-09-13 依頼者「save8 バハラタにはいったとき、自動移動がオフになっているときがある。フラグ管理の問題か？」
#   ★フラグではなく町の人の表: 実機の表は差し替え先の表 0xC2 と全員一致。15 人中 14 人は既定の表の人へ決まり、
#     slot 6 の 1 人（(5,24) / 見た目 20 / talk 385）だけ既定の表に居ない（★新しく出てきた人）→ 以前は表ごと空だった。
#   ★下の表は save8（2026-09-13 16:32）の RAM $0110〜 の 0x68 バイト（写しから読んだ実機の値 / map 14 / 昼 / (0,12)）。
SAVE8_NPC_TBL = ("11070480060405820518068019110783040f0491010c081405140781011b07800b0f04820d160982101609820f170a8016"
                 "0607010e1d0882101d0682" + "ff" * 40 + "fc000000")
SAVE8_TIME, SAVE8_POS = 1, (0, 12)


@needs_rom
def test_依頼者のsave8で0xC2の表が読め街移動の目的地が出る(tmp_path):
    assert len(bytes.fromhex(SAVE8_NPC_TBL)) == 0x68
    assert NM.runtime_variant_table(BAHARATA, SAVE8_TIME, SAVE8_NPC_TBL) == 0xC2, "⚠ 前提: save8 は 0xC2 と一致する"
    svc = TownService(heard=H.HeardLedger(tmp_path))
    args = (BAHARATA, SAVE8_TIME, SAVE8_NPC_TBL)
    cur = svc.current_npcs(*args)
    assert cur["status"] == "DEFAULT" and cur["table_id"] == 0xC2, "⚠⚠ save8 のバハラタの表が読めない（街移動が押せない）"
    assert len(cur["npcs"]) == 15
    default = {n["npc_id"]: n for n in _ledger(BAHARATA)}
    new = [n for n in cur["npcs"] if n["npc_id"] not in default]
    assert [n["npc_id"] for n in new] == [NM.variant_npc_id(0xC2, 2)], "⚠ 新しく出てきた人は slot 6 の 1 人だけのはず"
    assert new[0]["talk_id"] == 385 and new[0]["variant"], new[0]
    roles = {n["role"]: n["npc_id"] for n in cur["npcs"] if n.get("role")}
    assert roles == {"inn": 0, "church": 1, "item_shop": 11}, "⚠⚠ 施設の人が既定の表の番号でない（面識を取り違える）: %s" % roles
    for n in cur["npcs"]:
        if n.get("role") and n.get("role_status") == "CONFIRMED":
            svc.heard.record(BAHARATA, n["npc_id"], n["talk_id"])
    svc.heard.save()                                       # ⚠ `current_npcs` は台帳をファイルから読み直す（RX3-0059）
    got = svc.known_reachable_facilities(*args, SAVE8_POS)
    assert {f["role"] for f in got} >= {"inn", "item_shop"}, "⚠⚠ 街移動の目的地が空（依頼者の save8）: %s" % got
    assert not svc.heard_now(BAHARATA, new[0]), "⚠ 新しく出てきた人を聞いたことにしている"


@needs_rom
def test_新しく出てきた人は表ごとの番号で_取り違えそうなら直さない():
    """★RX3-0243: 表番号を渡したときだけ、どの人にも当たらない人を表ごとの番号にする。

    ⚠ 2 人以上に当たる・同じ人に 2 度当たる → 今までどおり None（★取り違えない / RX3-0231）。
    """
    default, variant = _ledger(BAHARATA), _ledger(0xC2)
    assert NM.renumber(variant, default) is None, "★表番号が無ければ今までどおり（RX3-0231）"
    got = NM.renumber(variant, default, 0xC2)
    assert got is not None and len(got) == 15
    ids = [n["npc_id"] for n in got]
    assert len(set(ids)) == 15 and NM.variant_npc_id(0xC2, 2) in ids
    assert all(i < 64 for i in ids if i != NM.variant_npc_id(0xC2, 2)), "⚠ 決まる人まで表ごとの番号にした"
    assert NM.variant_npc_id(0xC2, 2) != NM.variant_npc_id(0xC0, 2), "⚠ 表が違えば別の番号"
    twice = [dict(n) for n in variant] + [dict(variant[0])]  # ★同じ人に 2 度当たる
    assert NM.renumber(twice, default, 0xC2) is None


# --- ★依頼者の save3（RX3-0250）---------------------------------------------------
#
#   ⚠⚠ 2026-09-13 依頼者「地図の外にいる人を、聞き込みの数に入れないようにしてよいですか → OK」
#   ★ジパング（map 23 = 39 x 63）の npc 4・5 は (18,92)・(18,93) = 地図の外（★卑弥呼の奥 / 立てる升 0）→ 「未完 2 人」が出続けた。
#   ★下の表は save3（2026-09-13 21:05）の RAM $0110〜 の 0x68 バイト（写しから読んだ実機の値 / 昼 / (14,8)）。
SAVE3_NPC_TBL = ("2605040010140481123b0582113b0680125c0781125d0480131404831b120483120708a31e2a0982203a0981"
                 "09050492090709161005041b1b0b0903132604821a2904030e340a00122d09830a290b01052c0982063206821d330a02"
                 "fffffffffffffffffe800000")
SAVE3_TIME, SAVE3_POS = 19, (14, 8)
JIPANG = 23


@needs_rom
def test_依頼者のsave3で地図の外の2人を数えない(tmp_path):
    assert len(bytes.fromhex(SAVE3_NPC_TBL)) == 0x68
    svc = TownService(heard=H.HeardLedger(tmp_path))
    rom = svc.rom_map(JIPANG)
    assert (rom.width, rom.height) == (39, 63), "⚠ 前提: ジパングの地図の大きさ"
    cur = svc.current_npcs(JIPANG, SAVE3_TIME, SAVE3_NPC_TBL)
    assert cur["status"] == "DEFAULT"
    assert sorted(cur["off_map"]) == [4, 5], "⚠⚠ 地図の外の人を外していない: %s" % cur["off_map"]
    ids = {n["npc_id"] for n in cur["npcs"]}
    assert not ids & {4, 5} and len(cur["npcs"]) == 21, sorted(ids)
    assert svc.counts(JIPANG, SAVE3_TIME, SAVE3_NPC_TBL)["talkable"] == 20, "⚠⚠ 話せる人に地図の外の 2 人を数えた"
    got = svc.unheard_reachable_npcs(JIPANG, SAVE3_TIME, SAVE3_NPC_TBL, SAVE3_POS)
    assert got and not {c["npc"]["npc_id"] for c in got} & {4, 5}


def test_地図が読めなければ誰も外さない(tmp_path):
    svc = TownService(heard=H.HeardLedger(tmp_path))
    svc.rom_map = lambda map_id: None
    rows = [{"npc_id": 1, "x": 200, "y": 200}]
    assert svc._on_map(1, rows) == (rows, []), "⚠ 地図が分からないのに外した"
