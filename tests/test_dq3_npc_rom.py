"""ROM の NPC 記録の parser（RX3-0053）。

★文法の検査は作った記録で（ROM なし）。★ROM とセーブがあるときは 11/11 の一致まで見る。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3.testing import npc_rom as R

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"
# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()


def _rec(*bs):
    raw = bytes(bs)
    return {"addr": 0x8000, "raw": raw, "flags": raw[0]}


def test_単純形は昼にxのbit7が固定():
    # flags 0x18 = 昼も夜も居る / [1] 見た目 0x1E(向き 2=down) / [2] 0x0B / x 0x88 (bit7) / y 0x90
    got = R.expand([_rec(0x18, 0x1E, 0x0B, 0x88, 0x90)], night=False)
    assert got == [{"addr": 0x8000, "raw": "18 1e 0b 88 90", "flags": 0x18, "x": 8, "y": 16,
                    "appearance_id": 0x1C, "facing": "down", "fixed": True, "extended": False,
                    "talk_id_candidate": 0x0B, "talk_id": 0x00B}]


def test_会話idはflagsの上位2bitと2バイト目():
    # ★$F507 の写し。★実機: 宿屋 18 1e 0b → 0x00B / 道具屋 5f 1e ff → 0x1FF（2026-09-02）
    assert R.talk_id(bytes.fromhex("18 1e 0b 88 90"), night=False) == 0x00B
    assert R.talk_id(bytes.fromhex("5f 1e ff 85 84 89 52 03 10"), night=False) == 0x1FF
    assert R.talk_id(bytes.fromhex("d0 17 c2 98 17"), night=False) == 0x3C2
    # ★夜: flags & 0x02 なら 上位 = (flags & 0x20) >> 5、下位は $F4C3[flags & 3] = (2,2,5,6)
    assert R.talk_id(bytes.fromhex("5f 1e ff 85 84 89 52 03 10"), night=True) == 0x052
    assert R.talk_id(bytes.fromhex("18 1e 0b 88 90"), night=True) == 0x00B


def test_昼だけの記録は夜に居ない():
    assert R.expand([_rec(0x10, 0x1E, 0x00, 0x08, 0x10)], night=True) == []
    assert len(R.expand([_rec(0x10, 0x1E, 0x00, 0x08, 0x10)], night=False)) == 1


def test_夜の拡張形は別の位置と見た目():
    # 5f = 夜(08)+昼(10)+bit0(見た目は[5])+bit1+bit2 → 長さ 9 / x は $F4BB[7] = [7]
    rec = _rec(0x5F, 0x1E, 0xFF, 0x85, 0x84, 0x89, 0x52, 0x03, 0x10)
    day = R.expand([rec], night=False)[0]
    night = R.expand([rec], night=True)[0]
    assert (day["x"], day["y"], day["appearance_id"], day["fixed"]) == (5, 4, 0x1C, True)
    assert night["extended"] is True
    assert (night["x"], night["y"], night["appearance_id"]) == (3, 16, 0x88)
    assert night["fixed"] is True          # ★[4] = 0x84 の bit7


def test_動くNPCはxのbit7が落ちている():
    got = R.expand([_rec(0x10, 0x11, 0x45, 0x0A, 0x0D)], night=False)[0]
    assert got["fixed"] is False and got["facing"] == "right"


def test_記録の長さはflagsの下3bit():
    assert R.REC_LEN == (5, 6, 6, 7, 7, 8, 8, 9)


def test_RAMの表はslot4から():
    ram = bytearray(0x800)
    ram[0x0110:0x0114] = bytes([8, 16, 5, 0x92])
    ram[0x0114:0x0118] = bytes([0xFF, 0xFF, 0xFF, 0xFF])
    got = R.ram_slots(bytes(ram))
    assert got == [{"slot": 4, "x": 8, "y": 16, "appearance_slot": 5, "state": 0x92,
                    "facing": "down", "fixed": True}]


def test_突合は動くNPCの座標違いを許す():
    rom = [{"x": 3, "y": 10, "appearance_id": 0x2C, "facing": "up", "fixed": False},
           {"x": 8, "y": 16, "appearance_id": 0x1C, "facing": "down", "fixed": True}]
    slots = [{"x": 0, "y": 8, "appearance_id": 0x2C, "facing": "left", "fixed": False},
             {"x": 8, "y": 16, "appearance_id": 0x1C, "facing": "down", "fixed": True}]
    c = R.compare(rom, slots)
    assert c["ok"] == 2 and c["same_position"] == 1


@pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
def test_アリアハンは11体でRAMと一致():
    from retroux.core.bgmap import savestate as ss

    checked = 0
    for name in ("DQ3_J.fc0", "DQ3_J.fc5", "DQ3_J.fc8"):
        path = FCS / name
        if not path.exists():
            continue
        st = ss.load(path)
        ram, wram = st.chunks["RAM"], st.chunks["WRAM"]
        if ram[0x8B] != 9 or ram[0x2F] != 1:
            continue
        rom = R.npcs_for_map(9, R.is_night(ram[R.TIME_ADDR]))
        c = R.compare(rom, R.ram_slots(ram, wram))
        assert c["rom_count"] == 11, name
        assert c["ok"] == 11, (name, c)
        assert c["same_appearance"] == 11 and c["same_fixed"] == 11, name
        checked += 1
    if checked == 0:
        pytest.skip("アリアハンのセーブが無い")


@pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
def test_台帳の原型():
    led = R.ledger(9)
    assert led["npc_count"] == 11
    assert led["status"]["talk_id"] == "OBSERVED" and led["status"]["night"] == "HYPOTHESIS"
    inn = [n for n in led["npcs"] if (n["initial_x"], n["initial_y"]) == (8, 16)][0]
    assert inn["movement"] == "fixed" and inn["talk_id"] == 0x00B      # ★実機 2026-09-02 と同じ値


# ---------------------------------------------------------------------------
# ★全 map（RX3-0054）
# ---------------------------------------------------------------------------

def test_記録が個体で昼夜は同じnpc_id():
    recs = [_rec(0x18, 0x1E, 0x0B, 0x88, 0x90),                     # 昼夜同じ
            _rec(0x10, 0x11, 0x45, 0x0A, 0x0D),                     # 昼だけ / 動く
            _rec(0x5F, 0x1E, 0xFF, 0x85, 0x84, 0x89, 0x52, 0x03, 0x10)]  # 夜は別の位置と見た目
    ind = R.record_individuals(recs)
    assert [i["npc_id"] for i in ind] == [0, 1, 2]
    assert ind[1]["present"] == {"day": True, "night": False} and ind[1]["night"] is None
    assert ind[1]["day"]["movement"] == "random"
    assert (ind[2]["day"]["initial_x"], ind[2]["night"]["initial_x"]) == (5, 3)
    day, night = R.map_ledger(9, recs, False), R.map_ledger(9, recs, True)
    assert [n["npc_id"] for n in day["npcs"]] == [0, 1, 2] and [n["slot"] for n in day["npcs"]] == [4, 5, 6]
    # ★夜は昼だけの個体が抜けて slot が詰まる（⚠ npc_id は変わらない）
    assert [n["npc_id"] for n in night["npcs"]] == [0, 2] and [n["slot"] for n in night["npcs"]] == [4, 5]


def test_差し替えのあるmapはUNKNOWN():
    v = R.variants()
    ids = {m["map_id"] for m in v["maps"]}
    assert {0x0E, 0x7D, 0x23, 0x47, 0x6B, 0x17, 0x8A, 0x72, 0x75, 0x06, 0x01, 0x4A, 0x61}.issubset(ids)
    assert all(x["condition_status"] == "HYPOTHESIS" for m in v["maps"] for x in m["variants"])
    assert R.effective_table_id(0x0E) == (0x0E, "UNKNOWN") and R.effective_table_id(9) == (9, "DEFAULT")


def test_runtime_viewはRAMを優先する():
    master = R.map_ledger(9, [_rec(0x18, 0x1E, 0x0B, 0x88, 0x90), _rec(0x10, 0x11, 0x45, 0x0A, 0x0D)], False)["npcs"]
    slots = [{"slot": 4, "x": 8, "y": 16, "appearance_slot": 5, "state": 0x92, "facing": "down", "fixed": True},
             {"slot": 5, "x": 12, "y": 13, "appearance_slot": 6, "state": 0x41, "facing": "right", "fixed": False}]
    rows = R.runtime_view(master, slots)
    assert (rows[0]["current_x"], rows[0]["moved_from_initial"], rows[0]["consistent"]) == (8, False, True)
    assert (rows[1]["current_x"], rows[1]["moved_from_initial"], rows[1]["walking"]) == (12, True, True)
    rows = R.runtime_view(master, slots[:1])
    assert rows[1]["runtime"] is None and rows[1]["current_x"] == 10


def test_validateは形式ごとの実例と範囲を見る():
    prg = bytearray(16 * 0x4000)
    # ★資源 #$FF → bank 13 / 索引 1 → $8002 → $8100 → データ $8110
    prg[15 * 0x4000 + (R.RES_BANK_NIBBLES - 0xC000) + (0xFF >> 1)] = 0x0D
    prg[15 * 0x4000 + (R.RES_INDEX - 0xC000) + 0xFF] = 1
    b13 = 13 * 0x4000
    prg[b13 + 2:b13 + 4] = (0x8100).to_bytes(2, "little")
    prg[b13 + 0x100:b13 + 0x102] = (0x8110).to_bytes(2, "little")
    data = bytes.fromhex("00") + bytes.fromhex("18 1e 0b 88 90") + bytes.fromhex("19 45 5c 97 86 47") + bytes.fromhex("00")
    prg[b13 + 0x110:b13 + 0x110 + len(data)] = data
    got = R.validate(bytes(prg), sizes={1: (10, 10)})
    assert got["records"] == 2 and got["format_counts"] == {0: 1, 1: 1}
    assert got["format_examples"]["1"]["length"] == 6
    # ★(8,16) と (23,6) は 10x10 に入らない → out_of_bounds に出る
    assert got["in_bounds"] == {"day": 0, "night": 0} and len(got["out_of_bounds"]) == 4


@pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
def test_全mapの台帳():
    day, night = R.all_maps(False), R.all_maps(True)
    # ⚠⚠ 2026-09-06（RX3-0088）: `LIST_COUNT` を 208 → 250 にして 15 本増えた（142 → 157）。
    #    ★うち 8 本は **本物の map**（216 233 235 236 237 238 239 / ★area map がある）で、
    #    ⚠ その NPC は今まで**1 体も見えていませんでした**。残り 7 本は 0xF3〜0xF9 の差し替え先。
    assert sum(1 for l in R.parse_lists(R._prg(None)) if l) == 157
    assert (day["map_count"], day["npc_total"]) == (153, 830)
    assert (night["map_count"], night["npc_total"]) == (147, 689)
    ari = [m for m in day["maps"] if m["map_id"] == 9][0]
    assert ari["npc_count"] == 11 and ari["npcs"][1]["talk_id"] == 0x00B
    val = R.validate()
    assert val["records"] == 878 and set(val["format_counts"]) == set(range(8))
    # ⚠ 15 map は展開した y が area map の高さを超える（★原因は未解明 / UNKNOWN 扱い）。★増えたら気づく
    #   ⚠ 14 → 15 に増えたのは map 239（★208 で切っていて見えていなかった map）。
    assert len(val["exception_maps"]) == 15 and val["in_bounds"]["day"] == 619


@pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
def test_差し替え先の表を全部読めている():
    """⚠⚠ RX3-0088: `LIST_COUNT = 208` が表を途中で切っていた。

    ★`variants()` は差し替え先として `0xF3`〜`0xF9`（= 243〜249）を挙げているのに、
    ⚠ その表は**一度も読まれていませんでした**（★見張る対象を足し忘れると素通りする）。
    """
    lists = R.parse_lists(R._prg(None))
    want = sorted({v["npc_table_id"] for m in R.variants()["maps"] for v in m["variants"]})
    missing = [t for t in want if t >= len(lists)]
    assert not missing, "⚠ 差し替え先が読めていない: %s" % ["0x%02X" % t for t in missing]
    # ★0xF3 と 0xF9 には実際に記録がある（⚠ 空の表を数えただけでは通ってしまう）
    assert len(lists[0xF3]) == 11 and len(lists[0xF9]) == 11


@pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
def test_表の終わりは250():
    """⚠⚠ 250 から先は**別のデータ**。★数ではなく `flags` の散らばりで決めた。

    ```text
    表   0〜249  flags & 0xF8 が決まった 9〜13 種類しか出ない（★同じ文法）
    表 250〜     32 種類すべてが均等に出る（= ★別のデータ）
    ```
    ⚠ 実際 300 まで読むと、46 軒しか無いのに店番号 48 / 49 が出る。
    """
    import collections

    prg = R._prg(None)
    assert R.LIST_COUNT == 250
    kinds = []
    for lo, hi in ((0, 250), (250, 300)):
        c = collections.Counter()
        for recs in R.parse_lists(prg, limit=hi)[lo:hi]:
            for rec in recs:
                c[rec["flags"] & 0xF8] += 1
        kinds.append(len(c))
    assert kinds[0] <= 16, "⚠ 250 の手前に別のデータが混ざっている: %d 種" % kinds[0]
    assert kinds[1] >= 30, "⚠ 250 から先が別のデータに見えない: %d 種" % kinds[1]


@pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
def test_208から先に居るのは本物のmapと差し替え先():
    """⚠⚠ RX3-0088: 208 で切っていたせいで、★本物の map の NPC まで消えていた。

    ```text
    216 233 235 236 237 238 239  ★area map がある = 本物の map（⚠ NPC が 1 体も見えていなかった）
    243〜249（0xF3〜0xF9）        ★variants() の差し替え先
    225                          ⚠ area map も差し替え先も無い（★正体は未確認）
    ```
    """
    lists = R.parse_lists(R._prg(None))
    sizes = R.map_sizes()
    var = {v["npc_table_id"] for m in R.variants()["maps"] for v in m["variants"]}
    got = [t for t in range(208, R.LIST_COUNT) if lists[t]]
    assert got == [216, 225, 233, 235, 236, 237, 238, 239, 243, 244, 245, 246, 247, 248, 249]
    assert [t for t in got if t in sizes] == [216, 233, 235, 236, 237, 238, 239]
    assert [t for t in got if t in var] == [243, 244, 245, 246, 247, 248, 249]
    assert [t for t in got if t not in sizes and t not in var] == [225], "⚠ 正体不明が増えた"
