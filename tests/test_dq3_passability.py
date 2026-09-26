"""ROM から通行可否を推定し、実機の edge と突き合わせる（RX3-0051）。

★ROM を読む部分は conftest の ROM が要る（⚠ 無ければ skip）。
★突合（`edges.py`）は偽の地図と偽の行で検査する。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from dq3.testing import edges as E
from dq3.testing import passability as P

ROM = pathlib.Path(__file__).resolve().parents[1] / "work" / "rom" / "DQ3_J.nes"


# --- ★分類 -----------------------------------------------------------------

def test_collisionの分類():
    assert P.classify(0x80) == (P.BLOCK, "HYPOTHESIS")
    assert P.classify(0x00) == (P.PASS, "HYPOTHESIS")
    assert P.classify(0x01) == (P.SPECIAL, "CONFIRMED")
    assert P.classify(0x0A)[0] == P.SPECIAL and P.classify(0x0F)[0] == P.SPECIAL
    # ★2026-09-07（RX3-0014）: 扉のニブルは日本版 ROM で確定した
    #   （⚠ bank12 `$982E` が `CMP #$0D / #$0C / #$0B` で**直接**見ている）
    assert P.classify(0x8B) == (P.DOOR, "CONFIRMED")
    assert P.classify(0x03) == (P.CHEST, "CONFIRMED")
    assert P.classify(0x90)[0] == P.BLOCK, "⚠ bit4-6（壁の形）が立っていても bit7 で見る"


def _fake():
    """★3x3 の偽の地図: 真ん中の行が床、上下が壁、右下が階段。

    ```text
    B B B      tile 0 = collision 0x80
    P P P      tile 1 = 0x00
    B B S      tile 2 = 0x01
    ```
    """
    tiles = [[0, 0, 0], [1, 1, 1], [0, 0, 2]]
    table = [0x80, 0x00, 0x01] + [0x80] * 29
    return P.RomMap(9, tiles, table, tileset=5)


def test_升の分類と外():
    m = _fake()
    assert m.klass(1, 1) == P.PASS and m.klass(1, 0) == P.BLOCK and m.klass(2, 2) == P.SPECIAL
    assert m.klass(-1, 1) == P.SPECIAL, "⚠ 地図の外は出口（SPECIAL）"


def test_textは1升1文字():
    text = _fake().to_text().splitlines()
    assert text[0] == "3 3" and text[1] == "BBB" and text[2] == "PPP" and text[3] == "BBS"


def test_bfsは床だけを通る():
    m = _fake()
    assert m.bfs((0, 1), (2, 1)) == ["right", "right"]
    assert m.bfs((0, 1), (2, 2)) == ["right", "right", "down"], "⚠ 目的地は SPECIAL でも着いてよい"
    assert m.bfs((0, 1), (0, 0)) == ["up"], "⚠ 目的地が BLOCK でも隣まで行けば 1 歩で着く扱い"
    assert m.bfs((0, 1), (0, 1)) == []
    assert m.walk((0, 1), ["right", "right"]) == [(1, 1), (2, 1)]


def test_bfsは階段を通り抜けない():
    """⚠⚠ 階段を踏むと地図が変わる。★途中の升には使わない。"""
    tiles = [[1, 2, 1]]
    m = P.RomMap(9, tiles, [0x80, 0x00, 0x01] + [0x80] * 29, 5)
    assert m.bfs((0, 0), (2, 0)) is None


# --- ★実機の edge との突合 ------------------------------------------------------

def _row(fx, fy, d, *, ok, x=None, y=None, delivered=None, map_id=9, kind=1, step=1):
    r = {"step": step, "ok": ok, "input": d, "from_x": fx, "from_y": fy,
         "from_kind": 1, "from_map_id": 9, "kind": kind, "map_id": map_id,
         "x": x if x is not None else fx, "y": y if y is not None else fy,
         "_run": "r", "_seed": 1}
    if delivered is not None:
        r["delivered"] = delivered
    return r


def test_実測の読み方():
    """⚠⚠ 壁の証拠は「直後に同じ升から動けた」（対照）。`$16` は壁と区別できない。"""
    control = _row(1, 1, "right", ok=True, x=2, y=1, step=2)
    assert E.actual_of(_row(0, 1, "right", ok=True, x=1, y=1), 9) == P.PASS
    assert E.actual_of(_row(1, 1, "up", ok=False), 9, control) == P.BLOCK
    assert E.actual_of(_row(1, 1, "up", ok=False), 9) is None, "⚠⚠ 対照が無いのに壁にした"
    dead = dict(_row(1, 1, "up", ok=False), input_dead=True)
    assert E.actual_of(dead, 9, control) is None, "⚠⚠ 入力が死んでいる時間を壁にした"
    other = _row(5, 5, "right", ok=True, x=6, y=5, step=2)
    assert E.actual_of(_row(1, 1, "up", ok=False), 9, other) is None, "⚠ 別の升の動きを対照にした"
    assert E.actual_of(_row(2, 1, "down", ok=True, x=6, y=4, map_id=109), 9) == P.SPECIAL
    assert E.actual_of(_row(2, 1, "down", ok=True, x=6, y=4), 9) == P.SPECIAL, "⚠ 座標が飛んだ"


def test_混同行列と不一致():
    m = _fake()
    rows = [_row(0, 1, "right", ok=True, x=1, y=1),                 # ★PASS/PASS
            _row(1, 1, "up", ok=False, step=2),                      # ★BLOCK/BLOCK（対照は次の行）
            _row(1, 1, "down", ok=False, step=3),                    # ★BLOCK/BLOCK（対照は次の行）
            _row(1, 1, "right", ok=False, step=4),                   # ⚠ PASS/BLOCK（NPC?）
            _row(1, 1, "right", ok=True, x=2, y=1, step=5)]          # ★同じ edge が今度は通った（対照）
    got = E.compare(rows, m)
    rep = got["report"]
    assert rep["matrix"]["PASS/PASS"] == 2 and rep["matrix"]["BLOCK/BLOCK"] == 2
    assert rep["matrix"]["PASS/BLOCK"] == 1 and rep["mismatches"] == 1
    assert rep["edges_verified"] == 4 and rep["edges_total"] == 36
    mm = got["mismatches"][0]
    assert (mm["x"], mm["y"], mm["direction"], mm["rom_tile"]) == (1, 1, "right", 1)
    assert mm["neighbourhood"][1][1] == 1
    assert rep["flaky_edges"] == [{"x": 1, "y": 1, "direction": "right",
                                   "results": {"BLOCK": 1, "PASS": 1}}], "⚠ ぶれた edge を拾っていない"


def test_階段に着いた1歩は一致とみなす():
    """★warp は「着いた升」で起きるので、⚠ 階段へ動けた 1 歩は PASS として記録される。"""
    m = _fake()
    rows = [_row(1, 2, "right", ok=True, x=2, y=2),                  # ★階段 (2,2) へ着いた
            _row(2, 2, "up", ok=True, x=6, y=4, map_id=109, step=2)]  # ⚠ 次の 1 歩で地図が変わる
    got = E.compare(rows, m)
    assert got["report"]["mismatches"] == 0, got["mismatches"]


def test_NPCが塞いでいたかをOAMで見る(tmp_path):
    m = _fake()
    rows = [dict(_row(1, 1, "right", ok=False), frame=1000),
            _row(1, 1, "up", ok=True, x=1, y=0, step=2)]
    # ★frame 1000 のころ、升 (2,1) に NPC が居た（主人公 (1,1) が画面 (128,107)）
    oam = [{"frame": 990, "kind": 1, "map_id": 9, "px": 1, "py": 1,
            "s": [[107, 4, 0, 128], [107, 5, 0, 136], [115, 6, 0, 128], [115, 7, 0, 136],
                  [107, 0x96, 0, 144], [107, 0x96, 0, 152], [115, 0x98, 0, 144], [115, 0x97, 0, 152]]}]
    got = E.compare(rows, m, oam_by_run={"r": oam})
    assert got["mismatches"][0]["npc_at_target"] is True
    got2 = E.compare(rows, m, oam_by_run={"r": []})
    assert got2["mismatches"][0]["npc_at_target"] is None


@pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
def test_ROMからアリアハンを起こす():
    m = P.from_rom(9)
    assert (m.width, m.height, m.tileset) == (26, 26, 5)
    body = m.to_json()
    assert body["counts"]["PASS"] > 400 and body["counts"]["BLOCK"] > 150
    assert m.klass(5, 21) == P.SPECIAL, "⚠ 実機で階段だった (5,21) が SPECIAL でない"
    assert m.klass(8, 18) == P.PASS, "⚠ セーブ 0 の立ち位置が床でない"
