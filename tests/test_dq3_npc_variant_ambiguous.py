"""差し替え表が 2 つあって見分けがつかないとき（RX3-0286 / 2026-09-18）。

⚠⚠ 依頼者「save8 サマンオサで聞き込みできない。イベント中だからか？」

★サマンオサ（map 6）の実機の表は、差し替え先の **243 と 249 の両方**と全員一致します。
⚠ 「2 つ以上と一致 → 決められない」で候補 0（`UNKNOWN`）になり、聞き込みが即終わっていました。

```text
表 243 と 249 の違い   ★11 人中 4 人の talk_id だけ（716/724・715/723・713/254・714/722）
同じもの               位置・見た目・動く/動かない・役割（教会 / 道具屋）
```

→ ★歩く・話しかける・施設を指すのに要る情報は同じなので、**いちばん小さい番号で進める**。
⚠ どちらの台詞かは分からない（★条件の意味は HYPOTHESIS のまま使わない / RX3-0231）ので、
  `confirmed_by` に「決まりきっていない」と残します。

⚠ セーブは名指ししません（★撮り直されると壊れる）。★表は **ROM から組み立てます**。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from dq3.knowledge import npc_master as NM                      # noqa: E402
from test_dq3_npc_variant_runtime import _table                 # noqa: E402

#: ★サマンオサ（map 6）と、その差し替え先の表
SAMANOSA = 6
TABLES = (243, 249)
TIME_DAY = 0x01


def _ready() -> bool:
    try:
        return len(NM._lists()) > max(TABLES)
    except Exception:                                            # noqa: BLE001
        return False


needs_rom = pytest.mark.skipif(not _ready(), reason="DQ3 の ROM が読めない")


def _runtime_table(table_id: int) -> str:
    """★その表どおりに並んでいる実機の表（⚠ ROM から組み立てる）。"""
    lists = NM._lists()
    return _table(NM._rom.map_ledger(SAMANOSA, lists[table_id], False)["npcs"])


# --- ★どんな状態だったか -----------------------------------------------------

@needs_rom
def test_サマンオサは2つの差し替え表と一致する():
    """⚠ これが「決められない」の正体（★依頼者の症状の根っこ）。"""
    tbl = _runtime_table(243)
    assert NM.runtime_variant_tables(SAMANOSA, TIME_DAY, tbl) == list(TABLES)
    assert NM.runtime_variant_table(SAMANOSA, TIME_DAY, tbl) is None, (
        "⚠ 1 つに決まってしまうなら、この検査は別の状態を見ている")


@needs_rom
def test_2つの表の違いは台詞だけ():
    lists = NM._lists()
    rows = [NM._rom.map_ledger(SAMANOSA, lists[t], False)["npcs"] for t in TABLES]
    assert len(rows[0]) == len(rows[1]) == 11
    changed = [(a.get("slot"), a.get("talk_id"), b.get("talk_id"))
               for a, b in zip(*rows) if a.get("talk_id") != b.get("talk_id")]
    assert len(changed) == 4, changed
    for a, b in zip(*rows):
        for key in NM.TABLE_KEYS:
            assert a.get(key) == b.get(key), (key, a.get("slot"))
    assert NM.talk_only_difference(SAMANOSA, TIME_DAY, TABLES)


@needs_rom
def test_違いが位置なら決めない():
    """⚠ 台詞以外が違う表どうしは選べない（★別の人の並びなので）。"""
    assert not NM.talk_only_difference(SAMANOSA, TIME_DAY, (SAMANOSA, 243))


# --- ★直したあと -------------------------------------------------------------

@needs_rom
def test_台詞だけの違いならいちばん小さい番号で進める():
    tbl = _runtime_table(243)
    assert NM.ambiguous_variant_table(SAMANOSA, TIME_DAY, tbl) == 243


@needs_rom
def test_どの表か決まりきっていないことを残す():
    """⚠ 黙って 1 つに決めない（★後から「なぜその台詞なのか」を追えるように）。"""
    tbl = _runtime_table(243)
    led = NM.master_for(SAMANOSA, TIME_DAY, tbl)
    assert led["status"] == "DEFAULT" and led["table_id"] == 243
    assert led["confirmed_by"] == "runtime-talk-ambiguous", led.get("confirmed_by")


@needs_rom
def test_聞き込みの候補が出る():
    """★依頼者の症状（★候補 0 で即終わり）が消えていること。"""
    from dq3.knowledge.town_service import TownService

    tbl = _runtime_table(243)
    svc = TownService()
    cur = svc.current_npcs(SAMANOSA, TIME_DAY, tbl)
    assert cur["status"] == "DEFAULT" and len(cur["npcs"]) == 11, cur["status"]
    got = svc.unheard_reachable_npcs(SAMANOSA, TIME_DAY, tbl, (3, 9))
    assert len(got) >= 5, "⚠⚠ 聞き込みの候補が出ない: %d 人" % len(got)
    # ★施設も指せる（⚠ 教会・道具屋はどちらの表でも同じ）
    roles = {n["npc"].get("role") for n in got} | {
        n.get("role") for n in cur["npcs"]}
    assert "church" in roles and "item_shop" in roles, roles


# --- ★★ 位置だけずれているとき（サマンオサの城 / RX3-0288）------------------

#: ★サマンオサの城（map 97）と、その差し替え先の表
CASTLE, CASTLE_TABLE = 97, 244
#: ★門番（見た目 8 / talk 396）が 1 升ずつ外へ寄る（★実機 save0 の実測）
GUARDS = {4: (16, 27), 5: (12, 27)}


def _castle_runtime(moved=True) -> str:
    """★城の実機の表（⚠ `moved=True` なら門番 2 人を 1 升ずらす）。"""
    lists = NM._lists()
    npcs = []
    for n in NM._rom.map_ledger(CASTLE, lists[CASTLE_TABLE], False)["npcs"]:
        n = dict(n)
        if moved and n.get("slot") in GUARDS:
            n["initial_x"], n["initial_y"] = GUARDS[n["slot"]]
        npcs.append(n)
    return _table(npcs)


@needs_rom
def test_門番が1升ずれていると全員一致にはならない():
    """⚠ これが城で候補 0 だった理由（★動かない人の位置まで一致を求めていた）。"""
    tbl = _castle_runtime()
    assert NM.runtime_variant_tables(CASTLE, TIME_DAY, tbl) == []
    assert NM.runtime_confirms_default(CASTLE, TIME_DAY, tbl) is False


@needs_rom
def test_人数と動き方で1つに決まれば位置はずれてよい():
    got = NM.moved_table(CASTLE, TIME_DAY, _castle_runtime())
    assert got == (CASTLE_TABLE, 2), got                     # ★表 244 / ずれた人 2
    led = NM.master_for(CASTLE, TIME_DAY, _castle_runtime())
    assert led["status"] == "DEFAULT" and led["table_id"] == CASTLE_TABLE
    assert led["confirmed_by"] == "runtime-moved" and led["moved"] == 2


@needs_rom
def test_ずれていなければ今までどおり全員一致で決まる():
    """⚠ 位置がそろっているのに「ずれている扱い」にしないこと。"""
    tbl = _castle_runtime(moved=False)
    assert NM.runtime_variant_tables(CASTLE, TIME_DAY, tbl) == [CASTLE_TABLE]
    led = NM.master_for(CASTLE, TIME_DAY, tbl)
    assert led["confirmed_by"] == "runtime", led.get("confirmed_by")


@needs_rom
def test_動き方が違えば決めない():
    """★人数と動き方は**必須**（⚠ ここまで緩めると別の表を選びうる）。"""
    lists = NM._lists()
    npcs = [dict(n) for n in NM._rom.map_ledger(CASTLE, lists[CASTLE_TABLE], False)["npcs"]]
    npcs[0]["movement"] = "random" if npcs[0]["movement"] == "fixed" else "fixed"
    assert NM.moved_table(CASTLE, TIME_DAY, _table(npcs)) is None


@needs_rom
def test_候補が2つなら位置がずれていても決めない():
    """⚠ サマンオサの町（表 2 つ）で位置がずれたら、★決めずに空へ（安全側）。"""
    lists = NM._lists()
    npcs = [dict(n) for n in NM._rom.map_ledger(SAMANOSA, lists[243], False)["npcs"]]
    for n in npcs:
        if n.get("movement") == "fixed":
            n["initial_x"] = (n.get("initial_x") or 0) + 1
            break
    assert NM.moved_table(SAMANOSA, TIME_DAY, _table(npcs)) is None


@needs_rom
def test_城でも聞き込みの候補が出る():
    """★依頼者「サマンオサの城でも同様（save0）」。"""
    from dq3.knowledge.town_service import TownService

    tbl = _castle_runtime()
    svc = TownService()
    cur = svc.current_npcs(CASTLE, TIME_DAY, tbl)
    assert cur["status"] == "DEFAULT" and len(cur["npcs"]) == 12, cur["status"]
    assert len(svc.unheard_reachable_npcs(CASTLE, TIME_DAY, tbl, (13, 24),
                                          include_heard=True)) >= 3


@needs_rom
def test_1つだけ一致するときは今までどおり():
    """⚠ 今回の直しで、★1 つに決まる map の答えを変えていないこと（RX3-0231）。"""
    lists = NM._lists()
    for m in NM._rom.variants()["maps"]:
        if m["map_id"] == SAMANOSA:
            continue
        tids = [v["npc_table_id"] for v in m["variants"]]
        if len(tids) != 1 or not (0 <= tids[0] < len(lists)):
            continue
        tbl = _table(NM._rom.map_ledger(m["map_id"], lists[tids[0]], False)["npcs"])
        if NM.runtime_confirms_default(m["map_id"], TIME_DAY, tbl):
            continue                                             # ★既定と同じ形の表は対象外
        assert NM.runtime_variant_table(m["map_id"], TIME_DAY, tbl) == tids[0]
        assert NM.ambiguous_variant_table(m["map_id"], TIME_DAY, tbl) is None
        return
    pytest.skip("⚠ 差し替え先が 1 つだけの map が見つからない")


# ======================================================================
# ★依頼者の save8 そのもので確かめる（RX3-0287 / 2026-09-20）
# ======================================================================
#
# ⚠⚠ 上の検査は ROM から**組み立てた**表で確かめています。
#   ★それだけだと「組み立て方が同じ勘違いをしている」場合に気づけません。
#   → ★依頼者が実際に詰まったセーブ（`save8`）を固定セーブにして、⚠ **そのまま**通します。
#
# ★固定セーブ `town_samanosa_hearing`（⚠ sha256 で見張る / RX3-0129）。

FIXTURE = "town_samanosa_hearing"


def _fixture_table():
    """★固定セーブの NPC の表と時間帯（⚠ 無ければ skip）。"""
    from retroux.core.bgmap import savestate as ss

    from dq3.testing import fixtures as FX

    try:
        fx = FX.get(FIXTURE)
    except Exception:                                            # noqa: BLE001
        pytest.skip("⚠ 固定セーブ %s がまだ無い" % FIXTURE)
    ram = ss.load(fx.path).chunks["RAM"]
    return bytes(ram[0x0110:0x0110 + 0x68]).hex(), ram[0x06DF], fx


@needs_rom
def test_依頼者のセーブでサマンオサの人が出る():
    """⚠⚠ 依頼者「save8 サマンオサで聞き込みできない」— ★そのセーブで確かめる。"""
    tbl, time_byte, fx = _fixture_table()
    assert fx.expected.get("map_id") == SAMANOSA, fx.expected
    from dq3.knowledge.town_service import TownService

    svc = TownService()
    cur = svc.current_npcs(SAMANOSA, time_byte, tbl)
    assert cur["status"] == "DEFAULT", "⚠⚠ また候補 0 に戻っている: %s" % cur["status"]
    assert len(cur["npcs"]) == 11, len(cur["npcs"])


@needs_rom
def test_依頼者のセーブで台詞だけの違いだと分かる():
    """★`runtime-talk-ambiguous` の道を通っていること（⚠ 黙って 1 つに決めていない）。"""
    tbl, time_byte, _fx = _fixture_table()
    assert NM.runtime_variant_table(SAMANOSA, time_byte, tbl) is None, (
        "⚠ 1 つに決まってしまっている（★2 つ一致のはず）")
    assert NM.ambiguous_variant_table(SAMANOSA, time_byte, tbl) is not None


@needs_rom
def test_依頼者のセーブで再聞き込みと施設が出る():
    """★依頼者の記録ではもう全員「聞いた」なので、⚠ ボタンは再聞き込みになる。"""
    tbl, time_byte, fx = _fixture_table()
    start = tuple(fx.expected["local_pos"])
    from dq3.knowledge.town_service import TownService

    svc = TownService()
    counts = svc.counts(SAMANOSA, time_byte, tbl)
    assert counts["npc_total"] == 11 and counts["talkable"] == 11, counts
    got = svc.unheard_reachable_npcs(SAMANOSA, time_byte, tbl, start, include_heard=True)
    assert len(got) >= 8, "⚠ 再聞き込みの候補が %d 人しかいない" % len(got)
    # ⚠⚠ `known_reachable_facilities` は「面識がある人」しか出しません。
    #   ★それは**依頼者の聞いた台帳**に依るので、⚠ 隔離された検査では空になります
    #   （★そちらが正しい / 検査が生の記録に頼らない）。
    #   → ★ここで見るのは「この町の施設の人を**見分けられている**か」だけ。
    roles = {n["role"] for n in svc.current_npcs(SAMANOSA, time_byte, tbl)["npcs"]}
    assert {"inn", "item_shop", "church"} <= roles, sorted(r for r in roles if r)
