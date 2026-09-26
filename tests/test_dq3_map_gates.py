"""map の中の「入った升 → 出口」に鍵の段位を載せる（RX3-0067 / 2026-09-17）。

★`map_graph.route(keys=, gates=, at=)` が、⚠ 歩いて着けない出口・鍵が足りない出口を通らなくなる。
⚠ `gates` を渡さなければ今までどおり（★既定の振る舞いを変えない）。
"""
from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.knowledge import map_gates as MG                    # noqa: E402
from dq3.knowledge.map_graph import Exit, MapGraph          # noqa: E402
from dq3.testing import passability as P                    # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")

#: ★tile 0 = 床 / 1 = 壁 / 2 = どの鍵でも / 3 = まほう / 4 = さいご / 5 = 入口（SPECIAL）
TABLE = [0x00, 0x80, 0x8B, 0x8C, 0x8D, 0x01] + [0x00] * 26


def _map(rows, map_id=1):
    tiles = [[ord(c) - ord("0") for c in row] for row in rows]
    return P.RomMap(map_id=map_id, tiles=tiles, table=TABLE, tileset=0)


#: ```text
#: 5 0 2 0 5     ← (0,0) 入口 A ／ (2,0) どの鍵でも ／ (4,0) 入口 B
#: 1 1 1 1 1
#: 5 0 3 0 5     ← (0,2) 入口 C ／ (2,2) まほうの扉 ／ (4,2) 入口 D
#: 1 1 1 1 1
#: 5 1 1 1 5     ← (0,4) 入口 E ／ (4,4) 入口 F（★どうやっても着けない）
#: ```
ROWS = ["50205", "11111", "50305", "11111", "51115"]


def test_段位を弱い鍵から順に決める():
    m = _map(ROWS)
    assert MG.rank_between(m, (0, 0), (4, 0)) == 0, "★とうぞくのかぎで通る"
    assert MG.rank_between(m, (0, 2), (4, 2)) == 1, "★まほうのかぎが要る"
    assert MG.rank_between(m, (0, 4), (4, 4)) is None, "⚠⚠ 着けないのに段位を付けた"
    assert MG.rank_between(m, (0, 0), (0, 0)) == MG.FREE
    assert MG.rank_between(_map(["50005"]), (0, 0), (4, 0)) == MG.FREE


def _graph():
    """★map 1 の 6 つの入口が、それぞれ別の map 11〜16 へ行く。"""
    cells = [(0, 0), (4, 0), (0, 2), (4, 2), (0, 4), (4, 4)]
    return MapGraph([Exit(from_map=1, x=x, y=y, to_map=11 + i, kind=0, band="load_map",
                          where="entrance", to_index=0) for i, (x, y) in enumerate(cells)]
                    + [Exit(from_map=11 + i, x=0, y=0, to_map=1, kind=i, band="load_map",
                            where="entrance", to_index=i) for i in range(6)])


def test_鍵が足りない出口と着けない出口を通らない():
    g = _graph()
    gates = MG.Gates.compute(g, lambda _m: _map(ROWS))
    assert gates.summary() == {"maps": 1, "pairs": 30, "free": 0, "keyed": 4, "unreachable": 26, "skipped": 0}
    assert g.reachable(1) == {1, 11, 12, 13, 14, 15, 16}, "★gates 無しは今までどおり"
    assert g.reachable(1, at=(0, 0), gates=gates) == {1, 11}, "⚠⚠ 鍵が無いのに扉の先へ行った"
    assert g.reachable(1, at=(0, 0), keys=[88], gates=gates) == {1, 11, 12}
    assert g.reachable(1, at=(0, 2), keys=[88], gates=gates) == {1, 13}, "⚠ とうぞくのかぎで まほうの扉を通った"
    assert g.reachable(1, at=(0, 2), keys=[89], gates=gates) == {1, 13, 14}
    assert g.reachable(1, at=(0, 4), keys=[90], gates=gates) == {1, 15}, "⚠⚠ 着けない出口を通った"
    assert g.route(1, 12, at=(0, 0), gates=gates) is None
    assert g.route(1, 12, at=(0, 0), keys=[88], gates=gates) == [1, 12]


def test_着いた升は行き先の入口の行から決まる():
    g = _graph()
    e = g.exit_at(11, 0, 0)                          # ★map 11 → map 1 の 0 番目の入口 = (0,0)
    assert g.arrival_cell(e) == (0, 0)
    assert g.arrival_cell(g.exit_at(14, 0, 0)) == (4, 2)
    gates = MG.Gates.compute(g, lambda _m: _map(ROWS))
    # ★map 11 から map 1 に入ると (0,0) に立つ → そこから 12 へは鍵が要る
    assert g.route(11, 12, gates=gates) is None
    assert g.route(11, 12, keys=[88], gates=gates) == [11, 1, 12]


def test_表に無い組は今までどおり通す():
    gates = MG.Gates()
    assert gates.rank(1, (0, 0), (9, 9)) == "unknown"
    assert gates.passable(1, (0, 0), (9, 9), -1) is True
    gates.put(MG.Gate(1, (0, 0), (9, 9), None))
    assert gates.passable(1, (0, 0), (9, 9), 3) is False, "⚠⚠ 着けない組を通した"
    gates.put(MG.Gate(1, (0, 0), (8, 8), 1))
    assert gates.passable(1, (0, 0), (8, 8), 0) is False and gates.passable(1, (0, 0), (8, 8), 1) is True


def test_地図を起こせないmapは黙って落とさない():
    def loader(_m):
        raise RuntimeError("表にありません")

    gates = MG.Gates.compute(_graph(), loader)
    assert gates.skipped == {1: "表にありません"} and gates.summary()["pairs"] == 0


# ----------------------------------------------------------------------
# ★ROM あり
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def rom_graph():
    from dq3rom import profile as dq3
    from dq3rom import world_entrances, world_model

    ident = dq3.load_and_identify(ROM_PATH)
    g = MapGraph.from_model(world_model.build(ident), world=world_entrances.world_links(ident))
    return g, MG.Gates.compute(g, lambda m: P.from_rom(m, ROM_PATH))


@needs_rom
def test_ROMの出口どうしの段位(rom_graph):
    """★2026-09-17 実測。⚠ 「着けない」780 組は欠陥ではない（★入った升で行ける出口が違う map が 42 ある）。"""
    _g, gates = rom_graph
    assert gates.summary() == {"maps": 107, "pairs": 1390, "free": 522, "keyed": 88,
                               "unreachable": 780, "skipped": 0}, gates.summary()


@needs_rom
def test_アリアハンから鍵で広がる(rom_graph):
    """★町の入口 (15,9)（城への升）に立った一行。⚠ 世界地図から入った map は升が決まらないので絞らない。

    ★とうぞくのかぎで map 236 / 238（塔の上の階）、まほうのかぎで map 212 / 213 が増える。
    """
    g, gates = rom_graph
    base = g.reachable(0, at=(15, 9), gates=gates)
    assert len(base) == 133 and len(g.reachable(0)) == 137, "⚠ gates 無しは 137 のまま"
    assert g.reachable(0, at=(15, 9), keys=[88], gates=gates) - base == {236, 238}
    assert g.reachable(0, at=(15, 9), keys=[89], gates=gates) - base == {212, 213, 236, 238}
    assert g.route(0, 212, at=(15, 9), keys=[88], gates=gates) is None, "⚠⚠ とうぞくのかぎで まほうの扉の先へ"
    assert g.route(0, 212, at=(15, 9), keys=[89], gates=gates) == [0, -1, 59, 209, 210, 211, 212]
    assert g.route(0, 71, at=(15, 9), gates=gates) == [0, 70, 71], "★城の中は鍵なしのまま"
