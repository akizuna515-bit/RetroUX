"""差し替えのある map でも、実機の NPC の表が既定の表と一致すれば聞き込みできる（RX3-0175 / 2026-09-11）。

⚠⚠ 依頼者「ロマリアで聞き込みがきかない（save3）」。
★ロマリア（map 1）は ROM 上で「`$60B7` bit6 なら表 0xAD」に差し替わる map で、⚠ 条件の意味が未確定
（HYPOTHESIS）なので、安全側に倒して候補を**空**にしていた → 聞き込みが即「0 人」で終わる。
→ ★実機の表（$0110〜）が既定の表と**全員**一致（動く/動かない・動かない人の位置）すれば既定の表を使う。
⚠ 1 人でもずれる / 差し替え先の表とも一致する / 差し替え先の表と一致する → 今までどおり空。

★見本の表は依頼者の save3（ロマリア・昼 / 時間帯 0x59）の $0110〜$0177 を写したもの
（⚠ セーブは撮り直されるので、セーブを名指しで読まない / 教訓「セーブを番号で名指しすると壊れる」）。
"""
from __future__ import annotations

import pytest

from dq3.knowledge import npc_master as NM

#: ★ロマリア・昼の実機の NPC の表（save3 / 2026-09-11 22:26 / 18 人）
ROMARIA_DAY = ("0f2e0481122e0480172305820f180495031b06901d1c0400091bf755110a04820e0108021a0608010c08"
               "0503121e09100523058209230582052708020f2905001e270700202d0480"
               + "ff" * 28 + "fc000000")
TIME_DAY = 0x59


def _ready() -> bool:
    try:
        return len(NM._lists()) > 1
    except Exception:                                            # noqa: BLE001
        return False


needs_rom = pytest.mark.skipif(not _ready(), reason="DQ3 の ROM が読めない")


def _table(npcs) -> str:
    """★表の NPC から実機の形（1 人 4 バイト / FF FF で終わり）を作る。"""
    rows = sorted(npcs, key=lambda n: n["slot"])
    out = bytearray()
    for n in rows:
        fixed = n["movement"] == "fixed"
        out += bytes([n["initial_x"] or 0, n["initial_y"] or 0, 0, 0x80 if fixed else 0x00])
    out += b"\xff\xff\xff\xff"
    return out.hex()


@needs_rom
def test_ロマリアは差し替えのあるmapで表が無ければ空のまま():
    assert NM.variant_status(1) == "UNKNOWN"
    got = NM.master_for(1, TIME_DAY)
    assert got["status"] == "UNKNOWN" and got["npcs"] == []


@needs_rom
def test_実機の表が既定の表と一致すれば既定の表を使う():
    got = NM.master_for(1, TIME_DAY, ROMARIA_DAY)
    assert got["status"] == "DEFAULT", "⚠⚠ ロマリアで聞き込みの候補が空のまま（依頼者の save3）"
    assert got.get("confirmed_by") == "runtime"
    assert len(got["npcs"]) == 18 and all(n.get("talk_id") for n in got["npcs"])


@needs_rom
def test_動かない人が数人ずれても_ほかに候補が無ければ使う():
    """⚠⚠ 2026-09-18 訂正（RX3-0288）: ここは「1 人でもずれたら空のまま」を固定していました。

    ★依頼者「サマンオサの城でも同様（save0）」で前提が崩れました。
    ⚠ **イベントで「動かない人」が動く**ことがあります（★城の門番 2 人が 1 升ずつ外へ寄り、
      表 244 と「位置だけ」食い違って、どの表とも一致せず候補 0 になっていた）。

    → ★人数と動き方で**候補がちょうど 1 つ**なら、位置がずれていても使う
      （⚠ 位置は RAM のほうが正しい / `merged` は現在位置に RAM を使う）。
    ⚠ ずれている人のほうが多ければ、今までどおり使わない（★下の検査）。
    """
    raw = bytearray.fromhex(ROMARIA_DAY)
    # ★最初の「動かない人」（slot 4 = 先頭）の x を 1 ずらす
    assert raw[3] & 0x80
    raw[0] = (raw[0] + 1) % 0xFF
    got = NM.master_for(1, TIME_DAY, raw.hex())
    assert got["status"] == "DEFAULT", "⚠ 1 人ずれただけで候補 0 に戻っている"
    assert got.get("confirmed_by") == "runtime-moved" and got.get("moved") == 1


@needs_rom
def test_ずれている人のほうが多ければ空のまま():
    """★どれだけ緩めるかの境目（⚠ 別の人の並びを「同じ表」と言わないため）。"""
    raw = bytearray.fromhex(ROMARIA_DAY)
    moved = 0
    for i in range(0, len(raw) - 3, 4):
        if raw[i] == 0xFF:
            break
        if raw[i + 3] & 0x80:                                # ★動かない人
            raw[i] = (raw[i] + 1) % 0xFF
            moved += 1
    assert moved >= 2, "⚠ 動かない人が少なすぎて、この検査が何も見ていない"
    got = NM.master_for(1, TIME_DAY, raw.hex())
    assert got["status"] == "UNKNOWN" and got["npcs"] == []


@needs_rom
def test_差し替え先の表と一致すれば既定の番号に直して使う():
    """★RX3-0231: 差し替え先の表の npc_id は既定の表とぶつかる → ★既定の表の同じ人の番号へ直して使う。

    ⚠ 2026-09-13 まではここで「空のまま」を固定していた（★直したら赤くなる形で書き換えた）。
    """
    lists = NM._lists()
    variant = NM._rom.map_ledger(1, lists[0xAD], False)["npcs"]
    default_ids = {n["npc_id"] for n in NM._rom.map_ledger(1, lists[1], False)["npcs"]}
    got = NM.master_for(1, TIME_DAY, _table(variant))
    assert got["status"] == "DEFAULT" and got.get("table_id") == 0xAD
    assert {n["npc_id"] for n in got["npcs"]} == default_ids, "⚠ 既定の表の番号に直していない"


@needs_rom
def test_差し替えの無いmapは今までどおり():
    """★アリアハン（map 9）は表が無くても既定（⚠ 実機の表を渡しても変わらない）。"""
    assert NM.variant_status(9) == "DEFAULT"
    assert NM.master_for(9, 0)["status"] == "DEFAULT"
    assert NM.master_for(9, 0, ROMARIA_DAY)["status"] == "DEFAULT"


@needs_rom
def test_ロマリアで聞き込みの候補が出て聞いた記録も残る(tmp_path):
    from dq3.knowledge import npc_heard as H
    from dq3.knowledge.town_service import TownService

    svc = TownService(heard=H.HeardLedger(tmp_path))
    counts = svc.counts(1, TIME_DAY, ROMARIA_DAY)
    assert counts["status"] == "DEFAULT" and counts["talkable"] == 18 and counts["heard"] == 0
    npc = NM.master_for(1, TIME_DAY, ROMARIA_DAY)["npcs"][0]
    rec = svc.record_heard(1, TIME_DAY, npc["slot"], npc["talk_id"], "テスト", npc_tbl_hex=ROMARIA_DAY)
    assert rec is not None and rec["match"], "⚠⚠ 聞いた記録が残らない（★候補と同じ表で引いていない）"
    assert svc.heard.is_heard(1, npc["npc_id"])
    assert svc.counts(1, TIME_DAY, ROMARIA_DAY)["heard"] == 1


# ======================================================================
# ★イベントで消えた人（(0x80,0x80)）が居ても既定の表を使う（RX3-0228 / RX3-0230 / 2026-09-13）
# ======================================================================
#
# ⚠⚠ 依頼者「save1 バハラタで、個別に村人に会話したら表示が？になった」
#        「save１ 聞き込みが途中できかなくなって、街移動もできない」
# ★老人と話すとグプタ（map 14 / slot 10）が (0x80,0x80) に移り、表が既定の表と 1 人ずれ → UNKNOWN（候補 0）。
# ★見本は fixture `town_map14_save1`（★セーブを番号で名指ししない）。

BAHARATA = 14
SAVE1_FIXTURE = "town_map14_save1"
TIME_ADDR = 0x06DF          # ★`dev.lua` の time_byte と同じ番地
FACING_ADDR = 0x0644        # ★profile `location.facing`


def _n(slot, x, y, movement="fixed"):
    return {"slot": slot, "movement": movement, "initial_x": x, "initial_y": y}


def _s(slot, x, y, fixed=True):
    return {"slot": slot, "x": x, "y": y, "fixed": fixed}


NPCS = [_n(4, 1, 2), _n(5, 3, 4), _n(6, 5, 6, "moving")]


def test_消えた人は表のその人と一致したとみなす():
    slots = {4: _s(4, 1, 2), 5: _s(5, 0x80, 0x80), 6: _s(6, 9, 9, fixed=False)}
    assert NM._table_matches(NPCS, slots)


def test_消えていない人がずれたら一致しない():
    slots = {4: _s(4, 1, 3), 5: _s(5, 0x80, 0x80), 6: _s(6, 9, 9, fixed=False)}
    assert not NM._table_matches(NPCS, slots)


def test_全員消えていたら一致しない():
    """⚠ 全員消えた表は何とも比べられない（★どの表とも「一致」になってしまう）。"""
    slots = {i: _s(i, 0x80, 0x80) for i in (4, 5, 6)}
    assert not NM._table_matches(NPCS, slots)


def test_消えた印は0x80と0x80ちょうどだけ():
    """⚠ x だけ $80（`_npc_hndlD` の形）は扱わない（★UNCONFIRMED の決まりを広げない）。"""
    slots = {4: _s(4, 1, 2), 5: _s(5, 0x80, 4), 6: _s(6, 9, 9, fixed=False)}
    assert not NM._table_matches(NPCS, slots)


def test_mergedは消えた人を入れない():
    base = {"initial_facing": "up", "movement": "fixed", "appearance_id": 1, "talk_id": 5}
    master = {"npcs": [dict(base, npc_id=0, slot=4, initial_x=1, initial_y=2),
                       dict(base, npc_id=1, slot=5, initial_x=3, initial_y=4)]}
    slots = [{"slot": 4, "x": 1, "y": 2, "facing": "up", "state": 0x80, "fixed": True},
             {"slot": 5, "x": 0x80, "y": 0x80, "facing": "up", "state": 0x80, "fixed": True}]
    rows = NM.merged(master, slots)
    assert [r["npc_id"] for r in rows] == [0], "⚠⚠ (128,128) の人を目指す / 正面の人に数える"


def _hide(tbl_hex: str, slots) -> str:
    raw = bytearray.fromhex(tbl_hex)
    for s in slots:
        o = (s - NM._rom.NPC_FIRST_SLOT) * 4
        raw[o:o + 2] = bytes(NM.HIDDEN_XY)
    return raw.hex()


def _baharata(tid: int = BAHARATA):
    return NM._rom.map_ledger(BAHARATA, NM._lists()[tid], False)["npcs"]


@needs_rom
def test_バハラタの既定の表で1人消えていても既定の表を使う():
    got = NM.master_for(BAHARATA, 0, _hide(_table(_baharata()), [10]))
    assert got["status"] == "DEFAULT" and got.get("confirmed_by") == "runtime"


@needs_rom
def test_バハラタの既定の表で全員消えていたら空のまま():
    default = _baharata()
    got = NM.master_for(BAHARATA, 0, _hide(_table(default), [n["slot"] for n in default]))
    assert got["status"] == "UNKNOWN" and got["npcs"] == []


@needs_rom
@pytest.mark.parametrize("tid, want", [(0xC0, 0xC0), (0xC2, 0xC2)])
def test_バハラタの差し替え先の表は既定の番号に直せるときだけ使う(tid, want):
    """★RX3-0231: 0xC0 は 15 人とも既定の表の人へ直せる → 使う。

    ★2026-09-13（RX3-0243 / 依頼者「save8 バハラタにはいったとき、自動移動がオフになっているときがある」）:
      ⚠ 以前は「0xC2 は 1 人決まらない → 空のまま」を固定していた。★その 1 人は既定の表に居ない**新しく出てきた人**
      （★2 人以上に当たるのではない）→ 表ごとの番号で別人として扱い、0xC2 も使う（→ `test_dq3_npc_variant_table.py`）。
    ⚠ 1 人消えていても同じ（★既定の表にはしない / 差し替え先の表として扱う）。
    """
    variant = _baharata(tid)
    for tbl in (_table(variant), _hide(_table(variant), [variant[0]["slot"]])):
        got = NM.master_for(BAHARATA, 0, tbl)
        assert got.get("table_id") == want
        assert got["status"] == ("DEFAULT" if want else "UNKNOWN")


@pytest.fixture(scope="module")
def save1():
    """★依頼者の save1（バハラタ / 老人の真上 (13,25) で下向き / グプタが (0x80,0x80)）。"""
    from dq3.testing import fixtures as FX
    from retroux.tools.ram import read_savestate

    try:
        fx = FX.get(SAVE1_FIXTURE)
    except FX.FixtureChanged:
        raise                                            # ⚠⚠ 中身が変わった fixture は skip にしない（★赤くする）
    except FX.FixtureError as err:
        pytest.skip("⚠ fixture が使えない: %s" % err)
    ram = read_savestate(fx.path)
    return {"npc_tbl": bytes(ram[0x0110:0x0178]).hex(), "time_byte": ram[TIME_ADDR],
            "facing": ram[FACING_ADDR], "pos": tuple(fx.expected["local_pos"])}


@pytest.fixture
def svc(tmp_path, monkeypatch):
    from dq3.knowledge import npc_heard as H
    from dq3.knowledge import town_service as TSV

    # ⚠ 本物の work/ の記録を読まない（★会話の記録 → 話しかけない相手 / heard）
    monkeypatch.setattr(TSV, "CONVERSATIONS_PATH", tmp_path / "npc-conversations.json")
    return TSV.TownService(heard=H.HeardLedger(tmp_path))


@needs_rom
def test_save1のバハラタは既定の表として読める(save1):
    got = NM.master_for(BAHARATA, save1["time_byte"], save1["npc_tbl"])
    assert got["status"] == "DEFAULT", "⚠⚠ バハラタで候補が空（依頼者の save1）"
    assert got.get("confirmed_by") == "runtime"
    assert len(got["npcs"]) == 17                      # ★ROM の既定の表（Master）はグプタも含む


@needs_rom
def test_save1で消えたグプタは候補に入らない(save1, svc):
    t, tbl = save1["time_byte"], save1["npc_tbl"]
    cur = svc.current_npcs(BAHARATA, t, tbl)
    assert cur["status"] == "DEFAULT" and len(cur["npcs"]) == 16
    assert 10 not in {n["slot"] for n in cur["npcs"]}
    assert all((n["x"], n["y"]) != NM.HIDDEN_XY for n in cur["npcs"])
    cands = svc.unheard_reachable_npcs(BAHARATA, t, tbl, save1["pos"])
    assert cands, "⚠⚠ 聞き込みの候補が 0 人（依頼者「聞き込みが途中できかなくなって」）"
    assert all(c["npc"]["slot"] != 10 for c in cands)


@needs_rom
def test_save1で老人の前に立つと相手は老人(save1, svc):
    assert save1["pos"] == (13, 25) and save1["facing"] == 2
    npc = svc.npc_in_front(BAHARATA, save1["time_byte"], save1["npc_tbl"], save1["pos"], save1["facing"])
    assert npc is not None, "⚠⚠ 勇者メモが「？」になる（依頼者の save1）"
    assert npc["slot"] == 11 and (npc["x"], npc["y"]) == (13, 26)
    assert svc.appearance_label(npc["appearance_id"]) == "老"


@needs_rom
def test_save1で老人と話した記録が残り目的地も出る(save1, svc):
    t, tbl, pos = save1["time_byte"], save1["npc_tbl"], save1["pos"]
    npc = svc.npc_in_front(BAHARATA, t, tbl, pos, save1["facing"])
    rec = svc.record_heard(BAHARATA, t, npc["slot"], npc["talk_id"], "テスト", npc_tbl_hex=tbl)
    assert rec is not None and rec["match"] and rec["label"] == "老", "⚠⚠ 老人と話した記録が残らない"
    assert svc.heard.is_heard(BAHARATA, npc["npc_id"])
    # ★道具屋と話したことにすれば目的地に出る（⚠ 以前は表が読めず「―――」で街移動できなかった）
    shop = next(n for n in svc.current_npcs(BAHARATA, t, tbl)["npcs"]
                if n["role"] == "item_shop" and n["role_status"] == "CONFIRMED")
    assert svc.record_heard(BAHARATA, t, shop["slot"], shop["talk_id"], "テスト", npc_tbl_hex=tbl)
    assert [f["role"] for f in svc.known_reachable_facilities(BAHARATA, t, tbl, pos)] == ["item_shop"]
