"""DQ3 World Model の整合性（RX3-0008 / 2026-08-24）。

★ここは「データ全体の辻褄」を見る（指示 §20）。単体の関数より、
  **193 件が互いに矛盾しないこと**のほうが壊れを見つけやすい。

⚠ skip の見張りは材料の数で書く（RX-0100 の教訓）。
"""

from __future__ import annotations

import pathlib

import pytest

from dq2rom import ines
from dq3rom import chests as chests_mod

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"


# --- ROM 不要: 中身の読み方 ---------------------------------------------

def test_中身の符号を読み分ける():
    """⚠ 意味が未確定の値をアイテムに押し込まない（指示 §7）。"""
    r = chests_mod.Reward.from_byte(0xFF)
    assert r.type == "empty" and r.item_id is None
    for v in (0xFE, 0xFD):
        assert chests_mod.Reward.from_byte(v).type == "mimic"
    g = chests_mod.Reward.from_byte(0x82)
    assert g.type == "gold" and g.amount == 2 * 8
    assert chests_mod.Reward.from_byte(0x7F).type == "gold"
    i = chests_mod.Reward.from_byte(0x59)
    assert i.type == "item" and i.item_id == 0x59


def test_raw_を必ず残す():
    """★意味づけが後で変わっても、元の 1 バイトから読み直せるように。"""
    for v in (0x00, 0x59, 0x7F, 0x80, 0xFD, 0xFE, 0xFF):
        assert chests_mod.Reward.from_byte(v).to_json()["raw"] == f"0x{v:02X}"


def test_object_id_の作り方():
    c = chests_mod.Chest(global_index=7, map_id=42, local_index=3, x=1, y=2,
                         reward=chests_mod.Reward.from_byte(0), confidence="confirmed")
    assert c.object_id == "chest_0042_003"


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
def model():
    from dq3rom import profile as dq3
    from dq3rom import world_model as wm

    return wm.build(dq3.load_and_identify(ROM_PATH))


@needs_rom
def test_整合性の検査が全部通る(model):
    """★★ これが要（指示 §20）。⚠ 1 件でも矛盾があれば赤。"""
    from dq3rom import world_model as wm

    assert wm.check(model) == []


@needs_rom
def test_宝箱は193件で座標はほぼ全部つく(model):
    """⚠ 2026-08-24: 「全部つく」ではなくなった。

    ★以前は「その map で個数が合うタイル」をデータから当てていたので全件に
    座標が付いていた。⚠ 当てた 4 map は偶然でも一致してしまう置き方だった。
    いまは実機と同じ collision 判定だけで拾い、**足りないぶんは埋めない**。
    詳しくは `dq3rom/chests.py` の表。

    ⚠ `<=` で書く。★等号で固定すると、直したときに赤くなってしまう。
    """
    cs = [o for o in model["objects"] if o["type"] == "chest"]
    assert len(cs) == 193
    missing = [o for o in cs if o["x"] is None or o["y"] is None]
    assert len(missing) <= 5
    assert all(o["confidence"] == "unresolved" for o in missing)
    assert {o["map_id"] for o in missing} <= {23, 98, 117, 235}


@needs_rom
def test_個数表と地図の宝箱数が一致する(model):
    """★★ 内部整合の検算。⚠ collision の組み立てが違えばここで落ちる。

    ⚠ 2026-08-24 修正: 以前はモデルの宝箱を map ごとに数えていたが、
    ★モデルは個数表のぶんだけ必ず作るので、**何を変えても必ず緑**だった。
    数えるのは**地図の上で実際に見つかったマス**にする。
    """
    from dq3rom import profile as dq3

    ident = dq3.load_and_identify(ROM_PATH)
    pairs, _ = chests_mod.read_tables(ident)
    want = {mid: n for mid, n in pairs if n}
    got: dict = {}
    for o in model["objects"]:
        if o["type"] == "chest" and o["x"] is not None:
            got[o["map_id"]] = got.get(o["map_id"], 0) + 1
    diff = {mid for mid in set(want) | set(got) if want.get(mid) != got.get(mid)}
    assert diff <= {23, 98, 117, 235}, f"新しく合わなくなった map: {sorted(diff)}"


@needs_rom
def test_中身の内訳が妥当(model):
    """golden（辻褄）: 空・ミミック・ゴールド・道具が全部ある。

    ⚠ 値の表は写さない（ROM 由来の転載を避ける / 指示 §9）。
    """
    import collections

    kinds = collections.Counter(o["reward"]["type"] for o in model["objects"]
                                if o["type"] == "chest")
    assert set(kinds) == {"item", "gold", "mimic", "empty"}
    assert kinds["item"] > 50          # ★道具が主
    assert 10 < kinds["mimic"] < 60    # ミミックはそこそこ居る


@needs_rom
def test_ゴールドは8の倍数(model):
    """符号 `(v & 0x7F) * 8` の裏取り。"""
    golds = [o["reward"]["amount"] for o in model["objects"]
             if o["type"] == "chest" and o["reward"]["type"] == "gold"]
    assert golds and all(g % 8 == 0 for g in golds)
    assert max(golds) <= 0x7F * 8


@needs_rom
def test_場所名は付けない(model):
    """⚠ 推測した地名を confirmed にしない（指示 §4・§19）。"""
    assert all(loc["name"] is None for loc in model["locations"])


@needs_rom
def test_アイテムに北米版の名前を入れない(model):
    """⚠ 指示 §12。`key` は ID から機械的に作る。"""
    assert all(i["name"] is None for i in model["items"])
    assert all(i["key"] == f"item_{i['item_id']:02x}" for i in model["items"])


@needs_rom
def test_確度と出典が全部のオブジェクトに付く(model):
    for o in model["objects"]:
        assert o["confidence"] in ("confirmed", "high-confidence",
                                   "inferred", "unresolved"), o["object_id"]
        assert o["source"] in ("jp_rom", "jp_savestate",
                               "north_america_disassembly", "derived")
