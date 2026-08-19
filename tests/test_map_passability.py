"""ROM から作る通行可能性の表（製品版ログ整理 Phase 5 / 指示書 §13〜§15）。

## ⚠⚠ この検査が**証明していないこと**

表の根拠は「地形の属性の上位ニブルが 0xF なら通れない」という**見立て**です。
★逆アセンブルで確かめたのは「上位ニブルが独立した場である」ところまでで、
⚠ **移動処理のどこで 0xF を見ているかは未特定**です。

    ★確認できた: $E1F9-$E1FF  LDY #$04 / LDA ($10),Y / AND #$F0 / STA $3C
    ⚠ 未特定    : その $3C を「通れるか」の判断で読む場所

したがってここで見るのは:

  1. 表が**根拠どおりに**出来ていること（★作りの検査）
  2. 実際に歩いた観測と**食い違わない**こと（★反証の検査）
  3. ⚠ 分かっていないものを**分かったことにしていない**こと
     （扉・宝箱・船・世界地図）

★「正しい」の証明は `navigation_mismatch`（§17）を溜めてから行います。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from retroux.tools.map_passability import (  # noqa: E402
    SOLID_CLASS, WORLD_MAP_ID, attribute, build, classify)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
DB = PROJECT_ROOT / "work" / "retroux.sqlite3"


@pytest.fixture(scope="module")
def prg():
    if not ROM.exists():
        pytest.skip("ROM が無い")
    return ROM.read_bytes()[16:]


@pytest.fixture(scope="module")
def data(prg):
    return build(prg, rom_hash="TEST")


# --- 1. 作りの検査 --------------------------------------------------------

def test_通れない地形は上位ニブルが0xF(data, prg):
    """★規則どおりに出来ているか。"""
    from retroux.core.bgmap.dungeon_map import CHEST_TERRAIN, DOOR_TERRAINS

    dynamic = set(DOOR_TERRAINS) | {CHEST_TERRAIN}
    wrong = []
    for m in data["maps"]:
        for c in m["cells"]:
            if c["terrain_id"] in dynamic:
                continue
            attr = attribute(prg, m["map_id"], c["terrain_id"])
            if attr is None:
                continue
            solid = (attr & 0xF0) == SOLID_CLASS
            if solid != (c["terrain_type"] == "blocked"):
                wrong.append((m["map_id"], c["x"], c["y"], hex(attr),
                              c["terrain_type"]))
    assert wrong == [], wrong[:5]


def test_見立てであることが成果物に書いてある(data):
    """⚠⚠ **相関を因果として売らない。**

    ★読む人が「どこまで確かか」を成果物から判断できること。
    """
    conf = data["confidence"]
    assert conf["causal_site_located"] is False, (
        "因果を特定したと書いてある。★特定できたなら根拠も一緒に入れること")
    assert conf["counterexamples"] == 0
    assert conf["verified_against_observations"] > 1000
    assert "$E1F9" in conf["disassembly"]


# --- 2. ⚠ 反証の検査（実際に歩いた所） ------------------------------------

def test_実際に歩いた先を通れないと言っていない(data):
    """★★ ここが一番の検査 ★★

    ⚠ 表が「通れない」と言っているマスを実際に歩けていたら、規則が誤り。
    """
    import sqlite3

    if not DB.exists():
        pytest.skip("実測 DB が無い")
    grid = {(m["map_id"], c["x"], c["y"]): c
            for m in data["maps"] for c in m["cells"]}
    con = sqlite3.connect(DB)
    bad, checked = [], 0
    try:
        rows = con.execute(
            "select map_id, to_x, to_y from MapEdge where map_id != ?",
            (WORLD_MAP_ID,))
        for map_id, x, y in rows:
            c = grid.get((map_id, x, y))
            if c is None:
                continue
            checked += 1
            if c["terrain_type"] == "blocked":
                bad.append((map_id, x, y, c["terrain_id"]))
    finally:
        con.close()
    if checked < 100:
        pytest.skip(f"突き合わせた観測が少なすぎる（{checked} 件）")
    assert bad == [], f"歩けたのに blocked と言っている: {bad[:5]}"


# --- 3. ⚠ 分かっていないものを埋めない ------------------------------------

def test_扉と宝箱は静的に決めない():
    """★開けると別の地形へ差し替わる（`$E006: LDA #$00`）。"""
    from retroux.core.bgmap.dungeon_map import CHEST_TERRAIN, DOOR_TERRAINS

    for terrain in (*DOOR_TERRAINS, CHEST_TERRAIN):
        kind, passability = classify(terrain, 0xF2)
        assert kind in ("door", "chest"), (terrain, kind)
        assert passability["foot"] is None, (
            "扉・宝箱を静的に「通れない」と決めている")


def test_船は未判定であってfalseではない(data):
    """⚠⚠ 「調べていない」と「通れない」は別（指示書 §15）。"""
    ships = {c["passability"]["ship"]
             for m in data["maps"] for c in m["cells"]}
    assert ships == {None}, f"ship に値が入っている: {ships}"


def test_歩ける所はbool_へ潰していない(data):
    """★`walkable: true/false` の1つに畳んでいないこと（§15）。"""
    sample = data["maps"][0]["cells"][0]
    assert set(sample["passability"]) == {"foot", "ship"}
    assert "walkable" not in sample


def test_世界地図は対象外だと書いてある(data):
    """⚠ 別の復号（行ランレングス）。★黙って混ぜない。"""
    assert WORLD_MAP_ID in data["skipped_maps"]
    assert "world_map" in data["skipped_reason"]
    assert all(m["map_id"] != WORLD_MAP_ID for m in data["maps"])


def test_属性が読めない地形はunknown(prg):
    kind, passability = classify(0, None)
    assert kind == "unknown"
    assert passability == {"foot": None, "ship": None}


# --- 再現できること -------------------------------------------------------

def test_同じROMからは同じ表が出る(prg):
    """★生成物は再現可能であること（指示書 §27）。"""
    from datetime import datetime, timezone

    when = datetime(2026, 8, 13, 9, 0, 0, tzinfo=timezone.utc)
    a = build(prg, rom_hash="X", now=when)
    b = build(prg, rom_hash="X", now=when)
    assert a == b
