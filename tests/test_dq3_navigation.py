"""固定 NPC への Navigation（RX3-0052 §8 §9 §12）。"""

from __future__ import annotations

import json

from dq3.testing import navigation as N
from dq3.testing import passability as P


def _town():
    """★5x5: 外周が壁、真ん中が床。NPC を (2,1) に置く想定。

    ```text
    B B B B B
    B P P P B
    B P P P B
    B P P S B     (3,3) = 階段
    B B B B B
    ```
    """
    tiles = [[0] * 5, [0, 1, 1, 1, 0], [0, 1, 1, 1, 0], [0, 1, 1, 2, 0], [0] * 5]
    return P.RomMap(9, tiles, [0x80, 0x00, 0x01] + [0x80] * 29, 5)


def test_隣接升は床だけ():
    got = N.adjacent_goals(_town(), (2, 1))
    cells = {tuple(g["goal"]): g["final_face"] for g in got}
    assert cells == {(1, 1): "right", (3, 1): "left", (2, 2): "up"}, cells
    assert all(g["via"] == "adjacent" for g in got)
    assert (2, 0) not in cells, "⚠ 壁の升を goal にした"


def test_カウンター越しの候補():
    """⚠ HYPOTHESIS: 通れないが壁の形が無い升（collision 0x80）を挟んだ 2 升先。"""
    tiles = [[1], [3], [1]]                       # ★NPC (0,0) / カウンター (0,1) / 床 (0,2)
    m = P.RomMap(9, tiles, [0x80, 0x00, 0x01, 0x80] + [0x80] * 28, 5)
    assert N.is_counter(m, 0, 1) is True
    assert N.is_counter(m, 0, 0) is False, "⚠ 床をカウンターにした"
    got = N.adjacent_goals(m, (0, 0))
    assert [g for g in got if g["via"] == "counter"][0]["goal"] == [0, 2]
    assert got[0]["final_face"] == "up"
    # ⚠ 壁の形がある壁（0x90）はカウンターではない
    m2 = P.RomMap(9, tiles, [0x80, 0x00, 0x01, 0x90] + [0x80] * 28, 5)
    assert N.adjacent_goals(m2, (0, 0)) == []


def test_RAMのNPC表を読む():
    ram = bytearray(0x800)
    # ⚠ 2026-09-02: 表は $0110 から（RX3-0053）。★$0114 から読むと 1 体目を落とす
    ram[0x110:0x110 + 12] = bytes([8, 16, 5, 0x92, 5, 4, 5, 0x82, 0xFF, 0xFF, 0xFF, 0xFF])
    got = N.npcs_from_ram(bytes(ram))
    assert [(g["x"], g["y"], g["sprite_id"]) for g in got] == [(8, 16, 5), (5, 4, 5)]
    assert got[0]["sprite_status"] == "HYPOTHESIS" and got[0]["talk_id"] is None
    ledger = N.npc_ledger(9, bytes(ram))
    assert ledger["position_status"] == "OBSERVED" and len(ledger["npcs"]) == 2


def test_他のNPCの升は避ける():
    got = N.adjacent_goals(_town(), (2, 1), others=[(2, 2)])
    assert all(tuple(g["goal"]) != (2, 2) for g in got)


def test_階段は隣接升にしない():
    got = N.adjacent_goals(_town(), (3, 2))
    assert all(tuple(g["goal"]) != (3, 3) for g in got), "⚠⚠ 階段に立たせようとした"


def test_最短の隣接升を選ぶ():
    plan = N.plan(_town(), (1, 3), (2, 1))
    assert plan is not None
    assert plan["goal"] in ([2, 2], [1, 1])
    assert len(plan["path"]) == 2
    assert plan["cells"][-1] == plan["goal"]
    assert plan["npc"] == [2, 1]


def test_着けなければNone():
    tiles = [[1, 0, 1]]
    m = P.RomMap(9, tiles, [0x90, 0x00] + [0x80] * 30, 5)      # ⚠ 0x90 = 壁の形あり（カウンターではない）
    assert N.plan(m, (0, 0), (2, 0)) is None


def test_会話の窓が無ければ開いていない():
    assert N.conversation_open({})["open"] is False
    assert N.conversation_open({"screen": ""})["open"] is False


def test_固定NPCの一覧(tmp_path):
    body = {"npc_candidates": [
        {"id": "npc-000", "observed": 100, "map_id": 9,
         "cells": [{"x": 8, "y": 16, "seen": 90}, {"x": 8, "y": 17, "seen": 10}]},
        {"id": "npc-001", "observed": 100, "map_id": 9,
         "cells": [{"x": 5, "y": 5, "seen": 20}, {"x": 6, "y": 5, "seen": 20}]},
    ]}
    p = tmp_path / "npc_candidates.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    got = N.fixed_npcs(p)
    assert got[0]["kind"] == "fixed" and got[0]["x"] == 8
    assert got[1]["kind"] == "moving"
    assert all(g["status"] == "OBSERVED" for g in got), "⚠ OAM の観測を CONFIRMED にしている"
    assert N.fixed_npcs(tmp_path / "無い.json") == []
