"""map をまたぐつながり（RX3-0067 Phase B / 2026-09-07）。

## ★この検査が守るもの

```text
① ⚠⚠ つなぎが片道にならない（★入って出たら元の map）… `RX3-0067` の Tests そのもの
② ⚠ 行き先が決まらない升を「道」にしない
③ ★世界地図を張ると、かたまりが 55 → 11 になること（2026-09-16 / ★RX3-0081 の端から出る行で 56 → 55・12 → 11）
```

## ★世界地図は 2026-09-16 に繋ぎました（RX3-0067）

★入口表（bank6 `$B24C` / `dq3rom.world_entrances`）が見つかったので、
⚠ 以前の HYPOTHESIS（1 町の一致）ではなく**表**を土台に張ります。
★裏は「世界へ出る出口の着地点 25 件のうち 22 件が表の升」（★別の ROM の表）。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3.knowledge.map_graph import WORLD_NODES, Exit, MapGraph

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")

#: ⚠ 本当に片道の 2 件（★`docs/design/dq3-findings.md`: map 148 は入る側と出る側が違う）
KNOWN_ONE_WAY = {(43, 148), (44, 148)}
#: ⚠ 世界地図を張らないと 55 に分かれる（2026-09-07 実測 56 → RX3-0081 の端から出る行（70→0）で 55）
COMPONENTS_WITHOUT_WORLD = 55
#: ★世界地図を張ると 11（2026-09-16 実測 12 → RX3-0081 で 11 / ⚠ 残りは下の `test_世界地図を張っても残るかたまり`）
COMPONENTS = 11
MAIN, ALEF = WORLD_NODES["world_main"], WORLD_NODES["world_alefgard"]


@pytest.fixture(scope="module")
def ident():
    from dq3rom import profile as dq3

    return dq3.load_and_identify(ROM_PATH)


@pytest.fixture(scope="module")
def model(ident):
    from dq3rom import world_model

    return world_model.build(ident)


@pytest.fixture(scope="module")
def graph(ident, model):
    from dq3rom import world_entrances

    return MapGraph.from_model(model, world=world_entrances.world_links(ident))


@pytest.fixture(scope="module")
def bare_graph(model):
    """⚠ 世界地図を張らない形（★比べるためだけ）。"""
    return MapGraph.from_model(model)


def _components(g):
    seen, comps = set(), []
    for m in sorted({e.from_map for e in g.exits}):
        if m in seen:
            continue
        got = g.reachable(m)
        seen |= got
        comps.append(got)
    return comps


# ----------------------------------------------------------------------
# ★ROM 不要（⚠ 組み立てそのもの）
# ----------------------------------------------------------------------
def _tiny():
    """★2 つの map が行き来する、いちばん小さい形。"""
    return MapGraph([
        Exit(from_map=1, x=5, y=5, to_map=2, kind=0, band="load_map",
             where="entrance", to_index=0),
        Exit(from_map=2, x=9, y=9, to_map=1, kind=0, band="load_map",
             where="entrance", to_index=0),
    ])


def test_行って戻れる():
    g = _tiny()
    e = g.exit_at(1, 5, 5)
    assert e is not None and g.round_trip_ok(e) is True
    assert g.one_way() == []


def test_片道は見つかる():
    g = MapGraph([
        Exit(from_map=1, x=5, y=5, to_map=2, kind=0, band="load_map",
             where="entrance", to_index=0),
        Exit(from_map=2, x=9, y=9, to_map=3, kind=0, band="load_map",
             where="entrance", to_index=0),
    ])
    assert [e.from_map for e in g.one_way()] == [1]


def test_行き先が決まらない升は道にしない():
    g = MapGraph([
        Exit(from_map=1, x=5, y=5, to_map=2, kind=0xFE, band="band_fe", where="unknown"),
        Exit(from_map=1, x=6, y=6, to_map=None, kind=None, band=None, where="none"),
    ])
    assert g.neighbours(1) == []
    assert len(g.unknown_exits()) == 2
    assert g.route(1, 2) is None, "⚠⚠ 決まっていない行き先で道を作った"


def test_道順はmapの並びだけ():
    g = MapGraph([
        Exit(from_map=1, x=0, y=0, to_map=2, kind=0, band="load_map", where="entrance", to_index=0),
        Exit(from_map=2, x=0, y=0, to_map=3, kind=0, band="load_map", where="entrance", to_index=0),
        Exit(from_map=3, x=0, y=0, to_map=2, kind=0, band="load_map", where="entrance", to_index=0),
    ])
    assert g.route(1, 3) == [1, 2, 3]
    assert g.route(1, 1) == [1]
    assert g.route(3, 1) is None, "⚠ 3 → 2 → 1 は無い（★2 の出口は 3 だけ）"


def test_判定できないものはNone():
    """⚠ 「戻れない」と「判定できない」を混ぜない。"""
    g = MapGraph([Exit(from_map=1, x=0, y=0, to_map=2, kind=0xC0,
                       band="band_c0", where="world")])
    assert g.round_trip_ok(g.exits[0]) is None
    assert g.one_way() == []


def _tiny_world():
    """★町 1 と町 2 が世界地図の上にある形（⚠ `world_links()` と同じ形の辞書）。"""
    return {
        "entrances": [{"map_id": 1, "world": "world_main", "x": 10, "y": 10},
                      {"map_id": 2, "world": "world_main", "x": 20, "y": 20}],
        "unplaced": [],
        "entrance_cells": {"world_main": {(10, 10), (20, 20)},
                           "world_alefgard": {(5, 5)}},
        "sizes": {"world_main": (256, 256), "world_alefgard": (158, 138)},
    }


def _tiny_model(*conns):
    return {"locations": [{"connections": list(conns)}]}


def test_世界地図を通って町から町へ行ける():
    g = MapGraph.from_model(_tiny_model(), world=_tiny_world())
    assert g.route(1, 2) == [1, MAIN, 2]
    assert g.exit_at(MAIN, 20, 20).to_map == 2
    edge = [e for e in g.exits_of(1) if e.where == "world_edge"]
    assert len(edge) == 1 and (edge[0].x, edge[0].y) == (None, None), "⚠ 端から出る辺は升を持たない"
    assert g.route(1, 2) is not None and MapGraph.from_model(_tiny_model()).route(1, 2) is None


def test_世界へ出る出口は着いた升の世界へ付け替える():
    def conn(x, y, tx, ty):
        return {"from_map_id": 3, "x": x, "y": y, "to_map_id": 9, "kind": 0xC0,
                "kind_band": "band_c0",
                "arrival": {"where": "world", "x": tx, "y": ty}}

    g = MapGraph.from_model(_tiny_model(conn(0, 0, 20, 20), conn(1, 1, 5, 5),
                                        conn(2, 2, 200, 200), conn(3, 3, 60, 60)),
                            world=_tiny_world())
    got = {(e.x, e.y): (e.to_map, e.where, e.rom_dest) for e in g.exits_of(3)}
    assert got[(0, 0)] == (MAIN, "world", 9), "★入口の升 → その世界"
    assert got[(1, 1)] == (ALEF, "world", 9), "★アレフガルドの入口の升"
    assert got[(2, 2)] == (MAIN, "world", 9), "★アレフガルドの外 → 主世界"
    assert got[(3, 3)] == (None, "unknown", 9), "⚠⚠ 両方に収まる升を主世界に寄せた"


def test_足した辺は戻りの索引をずらさない():
    """⚠ `world_edge` を出口の並びに混ぜると、★`kind` の索引が別の行を指す。"""
    model = _tiny_model(
        {"from_map_id": 1, "x": 0, "y": 0, "to_map_id": 2, "kind": 1, "kind_band": "load_map",
         "arrival": {"where": "entrance", "to_index": 1}},
        {"from_map_id": 2, "x": 0, "y": 0, "to_map_id": 1, "kind": 0, "kind_band": "load_map",
         "arrival": {"where": "entrance", "to_index": 0}},
    )
    g = MapGraph.from_model(model, world=_tiny_world())
    e = g.exit_at(1, 0, 0)
    assert g.return_exit(e) is None, "⚠⚠ 足した world_edge を表の 2 行目として拾った"


# ----------------------------------------------------------------------
# ★ROM あり（⚠ 実データ）
# ----------------------------------------------------------------------
@needs_rom
def test_片道は既知の2件だけ(graph):
    """⚠⚠ `RX3-0067` の Tests「つなぎが片道にならない」。

    ★`docs/design/dq3-findings.md` が別の道（表の突き合わせ）で見つけた 2 件と
    **同じもの**が出ること。⚠ 増えていたら、★どこかで索引がずれています。
    """
    got = {(e.from_map, e.to_map) for e in graph.one_way()}
    assert got == KNOWN_ONE_WAY, got


@needs_rom
def test_ほとんどの出口は戻れる(graph):
    s = graph.summary()
    assert s["round_trip_checked"] >= 390, s
    assert s["one_way"] == 2, s


@needs_rom
def test_行き先が決まらない出口を数えている(graph):
    """★`RX3-0081` の「升と表が 1 つずれる 12 map」がここに出る。"""
    s = graph.summary()
    assert s["unknown"] == s["exits"] - s["usable"]
    assert 0 < s["unknown"] < 40, s
    # ⚠ 内訳（★`band_fe` は「表を引かない」道 / `None` は表の行が無い升）
    bands = {e.band for e in graph.unknown_exits() if e.rom_dest is None}
    assert bands <= {"band_fe", None}, bands
    # ⚠ 世界へ出るのに、着いた升の世界が決まらない出口（★map 162 の 1 件だけ）
    odd = [(e.from_map, e.to_x, e.to_y) for e in graph.unknown_exits() if e.rom_dest is not None]
    assert odd == [(162, 49, 93)], odd


@needs_rom
def test_世界地図を張るとかたまりが減る(graph, bare_graph):
    """★55 → 11。⚠ 数が変わったら、★どの辺が増えた/消えたかを確かめること。"""
    assert len(_components(bare_graph)) == COMPONENTS_WITHOUT_WORLD
    assert len(_components(graph)) == COMPONENTS


@needs_rom
def test_世界地図を張っても残るかたまり(graph):
    """⚠⚠ **欠陥ではなく、まだ分かっていないことの一覧**です（2026-09-16）。

    ```text
    アレフガルド   主世界から辿れない（★落ちる穴は表に無い）
    map 4         KNOWN_ODD（★表の升が入口の升でない）
    80..87 ほか   ⚠ 入る道が表に無い
    152 / 160..162 ⚠ 162 の着く升がどちらの世界か決まらない
    ```
    """
    main = graph.reachable(MAIN)
    alef = graph.reachable(ALEF)
    assert len(main) == 137, len(main)
    assert len(alef) == 40, len(alef)
    assert not (main & alef), "⚠ 主世界とアレフガルドが繋がった（★どの辺かを確かめる）"
    assert 4 not in main, "⚠ KNOWN_ODD の map 4 に道が付いた"


@needs_rom
def test_町から町へ世界地図を通って行ける(graph):
    """★アリアハン(0) ⇄ レーベ(9)。⚠ map の並びだけ（★世界地図の中の経路は見ない）。"""
    assert graph.route(0, 9) == [0, MAIN, 9]
    assert graph.route(9, 0) == [9, MAIN, 0]
    assert graph.exit_at(MAIN, 172, 218).to_map == 0


@needs_rom
def test_世界へ出る出口の着地点は入口表の升(graph, ident):
    """★★`world_edge` の裏（⚠ 入口表とは**別の ROM の表**＝着地点表）。

    ★世界へ出る出口 29 件（升 25 ＋ 端から歩き出る行 4 / RX3-0081）のうち 25 件が、入口表のどれかの升に着く。
    ⚠ 残り 4 件は表の外の map（147 / 151 / 162）へ向かう出口と、map 151 の端から出る行（★着く升 (163,200) は表に無い）。
    ★端から出る行の着地点: map 0 → (172,218) = 入口表の行 0（アリアハン）。⚠ 別々の表が同じ升を指す。
    """
    from dq3rom import world_entrances

    cells = set(world_entrances.by_cell(ident))
    outs = [e for e in graph.exits if e.rom_dest is not None]
    on_table = [e for e in outs if (e.to_x, e.to_y) in cells]
    assert len(outs) == 29, len(outs)
    assert len(on_table) == 25, len(on_table)
    assert sorted(e.rom_dest for e in outs if e not in on_table) == [0, 147, 151, 162]
    edge0 = [e for e in outs if e.x is None and e.from_map == 0]
    assert len(edge0) == 1 and (edge0[0].to_x, edge0[0].to_y) == (172, 218)


@needs_rom
def test_世界地図を張っても戻りの判定は変わらない(graph, bare_graph):
    """⚠ 足した辺が表の索引をずらしていないこと（★398 件・片道 2 件のまま）。"""
    a, b = graph.summary(), bare_graph.summary()
    assert a["round_trip_checked"] == b["round_trip_checked"] == 404   # ★398 + 端から出る行のうち entrance 種の 6（RX3-0081）
    assert a["one_way"] == b["one_way"] == 2


@needs_rom
def test_城の中はmapをまたいで辿れる(graph):
    """★同じかたまりの中なら、⚠ いま**そのまま使えます**（アリアハンの城）。"""
    assert graph.route(0, 71) == [0, 70, 71]
    assert 70 in graph.neighbours(0)


@needs_rom
def test_城から町へは端から歩き出る行で戻れる(graph):
    """★RX3-0081（2026-09-17）: 「升が見つからない 10 行」は**地図の端から歩き出たときの行き先**だった。

    ★map 70（アリアハンの城）の「map 0 へ戻る」行は升を持たない（`via = edge`）。
    ⚠ 2026-09-07〜16 はこの行が張れず、玉座（71）から町（0）への帰り道が遠回りだった。
    """
    assert 0 in graph.neighbours(70), "⚠⚠ 端から歩き出る行が張られていない（RX3-0081）"
    assert graph.route(71, 0) == [71, 70, 0]
    edge = [e for e in graph.exits_of(70) if e.x is None and e.to_map == 0]
    assert len(edge) == 1 and edge[0].where == "entrance" and edge[0].usable, edge


@needs_rom
def test_升から出口を引ける(graph):
    """★(map, x, y) で引けること（⚠ 自動移動が使う形）。"""
    got = [e for e in graph.exits_of(0) if e.to_map == 70]
    assert got, "⚠ map 0 → 70 の出口が無い"
    again = graph.exit_at(0, got[0].x, got[0].y)
    assert again == got[0]
    assert graph.exit_at(0, 99, 99) is None
