"""マップ間・ロケーション間のグラフ（マッパー仕様 フェーズ7 / 25章）。

★★ **確かめたいことの中心** ★★

  1. 3つの高さを混ぜない
       マス `(x,y)` … 1つのマップの中を歩く
       マップ `(map_id, map_ptr)` … どの階を経由するか（★自動移動が使う）
       ロケーション … どの町を通るか（人に見せる段）
  2. ⚠⚠ **`map_id` だけを鍵にしない**（同じ ID で別の階がある）
  3. ⚠⚠ **遷移は片方向**。「AからBへ行けた」は「BからAへ戻れる」ではない
  4. 道が無いときに「近いところ」を返さない（**None**）
  5. 辞書に無いマップを近いロケーションに寄せない（数えて出す）
  6. 同じロケーションの中の階段は、ロケーションの段では辺にしない
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.db.database import Database
from retroux.core.navigation.graph import (
    LocationGraph, MapGraph, WorldGraph,
)
from retroux.core.navigation.location_resolver import LocationDictionary
from retroux.core.navigation.models import (
    Confidence, Direction, LandmarkKind, Place, TransitionType,
)
from retroux.core.navigation.repository import NavigationRepository

DATA = (pathlib.Path(__file__).resolve().parents[1]
        / "retroux" / "plugins" / "dq2" / "data")

WORLD = 0x01          # 世界地図
MIDENHALL_1F = 0x03   # ローレシア 1F
MIDENHALL_2F = 0x02   # ローレシア 2F
MIDENHALL_B1 = 0x04   # ローレシア B1
LIANPORT = 0x0B       # ルプガナ
PTR = 0x8000


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    return NavigationRepository(db, "HASH")


@pytest.fixture
def dictionary():
    return LocationDictionary.load(DATA)


def move(repo, source, target, kind=TransitionType.UNKNOWN, *,
         from_xy=(1, 1), to_xy=(2, 2), times=1):
    """`source` から `target` へ移った、という記録を作る。

    ★`source` / `target` は `(map_id, map_ptr)`。
    """
    for _ in range(times):
        repo.record_transition(
            Place(source[0], source[1], from_xy[0], from_xy[1]),
            Place(target[0], target[1], to_xy[0], to_xy[1]), None, kind)


# --- マップ間 ---------------------------------------------------------

def test_a_transition_becomes_a_link(repo):
    move(repo, (WORLD, PTR), (MIDENHALL_1F, 0x8E83))
    graph = WorldGraph.load(repo)
    assert graph.neighbors((WORLD, PTR)) == [(MIDENHALL_1F, 0x8E83)]
    assert (graph.node_count, graph.link_count) == (2, 1)


def test_a_link_remembers_where_to_stand(repo):
    """★どこに立てば移れるかが分からないと歩けない。"""
    move(repo, (WORLD, PTR), (MIDENHALL_1F, 0x8E83),
         from_xy=(50, 80), to_xy=(9, 20))
    link = WorldGraph.load(repo).links_between(
        (WORLD, PTR), (MIDENHALL_1F, 0x8E83))[0]
    assert (link.from_xy, link.to_xy) == ((50, 80), (9, 20))


def test_going_one_way_does_not_create_the_way_back(repo):
    """⚠⚠ **落とし穴・一方通行の階段がある。** 戻り道を勝手に作らない。"""
    move(repo, (MIDENHALL_1F, PTR), (MIDENHALL_B1, 0x9000),
         TransitionType.PITFALL)
    graph = WorldGraph.load(repo)
    assert graph.neighbors((MIDENHALL_1F, PTR)) == [(MIDENHALL_B1, 0x9000)]
    assert graph.neighbors((MIDENHALL_B1, 0x9000)) == []


def test_the_way_back_appears_once_it_is_walked(repo):
    move(repo, (MIDENHALL_1F, PTR), (MIDENHALL_B1, 0x9000))
    move(repo, (MIDENHALL_B1, 0x9000), (MIDENHALL_1F, PTR))
    graph = WorldGraph.load(repo)
    assert graph.neighbors((MIDENHALL_B1, 0x9000)) == [(MIDENHALL_1F, PTR)]


def test_the_same_map_id_on_a_different_pointer_is_a_different_node(repo):
    """⚠⚠ **`map_id` だけを鍵にしない。** 混ぜると別の階へ行こうとする。"""
    move(repo, (WORLD, PTR), (MIDENHALL_1F, 0x8E83))
    move(repo, (WORLD, PTR), (MIDENHALL_1F, 0x9999))
    graph = WorldGraph.load(repo)
    assert set(graph.neighbors((WORLD, PTR))) == {
        (MIDENHALL_1F, 0x8E83), (MIDENHALL_1F, 0x9999)}
    assert graph.node_count == 3


def test_a_route_across_two_maps(repo):
    move(repo, (MIDENHALL_1F, PTR), (WORLD, 0x8001))
    move(repo, (WORLD, 0x8001), (LIANPORT, 0x8002))
    route = WorldGraph.load(repo).route((MIDENHALL_1F, PTR), (LIANPORT, 0x8002))
    assert route == [(MIDENHALL_1F, PTR), (WORLD, 0x8001), (LIANPORT, 0x8002)]


def test_a_route_to_yourself_is_just_yourself(repo):
    assert WorldGraph.load(repo).route((WORLD, PTR), (WORLD, PTR)) == \
        [(WORLD, PTR)]


def test_no_route_returns_none_not_a_partial_path(repo):
    """★★ **途中までの道順を返さない。** 着いたと思われる。"""
    move(repo, (MIDENHALL_1F, PTR), (WORLD, 0x8001))
    assert WorldGraph.load(repo).route(
        (MIDENHALL_1F, PTR), (LIANPORT, 0x8002)) is None


def test_a_route_from_an_unknown_map_is_none(repo):
    assert WorldGraph.load(repo).route((0x7F, PTR), (WORLD, PTR)) is None


def test_the_route_is_the_shortest_one(repo):
    """★遠回りの記録があっても短いほうを返す（幅優先）。"""
    move(repo, (WORLD, PTR), (0x10, PTR))
    move(repo, (0x10, PTR), (0x11, PTR))
    move(repo, (0x11, PTR), (LIANPORT, PTR))
    move(repo, (WORLD, PTR), (LIANPORT, PTR))
    route = WorldGraph.load(repo).route((WORLD, PTR), (LIANPORT, PTR))
    assert route == [(WORLD, PTR), (LIANPORT, PTR)]


def test_a_detour_is_not_returned_when_a_shorter_way_exists(repo):
    """★★ **幅優先であること。** ★★

    ⚠ 深さ優先だと、短い道があるのに**遠回りを返す**。
      直接つながっている相手を先に調べてしまうと差が出ないので、
      「2手で着く道」と「3手で着く道」を作って確かめる。

        世界地図 -> 短い側 -> ゴール          （2手）
        世界地図 -> 長い側 -> 途中 -> ゴール  （3手）
    """
    short, long_, middle, goal = 0x10, 0x11, 0x12, 0x13
    move(repo, (WORLD, PTR), (short, PTR), from_xy=(1, 1))
    move(repo, (WORLD, PTR), (long_, PTR), from_xy=(2, 2))
    move(repo, (short, PTR), (goal, PTR))
    move(repo, (long_, PTR), (middle, PTR))
    move(repo, (middle, PTR), (goal, PTR))
    route = WorldGraph.load(repo).route((WORLD, PTR), (goal, PTR))
    assert route == [(WORLD, PTR), (short, PTR), (goal, PTR)]


def test_a_loop_does_not_hang_the_search(repo):
    """⚠ 行き来（ローレシア 1F ⇄ 2F）は普通にある。**止まらなくならない**こと。"""
    move(repo, (WORLD, PTR), (0x10, PTR))
    move(repo, (0x10, PTR), (WORLD, PTR))
    assert WorldGraph.load(repo).route((WORLD, PTR), (0x7F, PTR)) is None


def test_a_bigger_loop_also_terminates(repo):
    """★輪が長いと、1回ぶんの取りこぼしでは止まらなくならない。長い輪で試す。"""
    ring = [(0x10 + i, PTR) for i in range(6)]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        move(repo, a, b, from_xy=(a[0] % 20, 1))
    assert WorldGraph.load(repo).route(ring[0], (0x7F, PTR)) is None


def test_every_transition_is_kept_by_default(repo):
    """⚠ 1回しか見ていない遷移も「そこは通れた」という観測。**捨てない**。"""
    move(repo, (WORLD, PTR), (MIDENHALL_1F, PTR))
    graph = WorldGraph.load(repo)
    assert graph.link_count == 1
    link = graph.links[(WORLD, PTR)][0]
    assert link.confidence is Confidence.PROVISIONAL


def test_transitions_can_be_filtered_by_confidence(repo):
    """★絞りたい側が絞る（既定では絞らない）。"""
    move(repo, (WORLD, PTR), (MIDENHALL_1F, PTR), times=2)   # -> confirmed
    move(repo, (WORLD, PTR), (LIANPORT, PTR), from_xy=(9, 9))  # -> provisional
    strict = WorldGraph.load(repo, Confidence.CONFIRMED)
    assert strict.neighbors((WORLD, PTR)) == [(MIDENHALL_1F, PTR)]
    assert WorldGraph.load(repo).link_count == 2


def test_an_unreadable_confidence_does_not_become_confirmed(repo):
    """★★ **読めない確度で勝手に上げない。** ★★

    上げてしまうと、1回しか見ていない遷移が「確か」として
    絞り込みを通り抜ける。
    """
    move(repo, (WORLD, PTR), (MIDENHALL_1F, PTR))
    repo._conn.execute("UPDATE MapTransition SET confidence = 'とても確か'")
    repo.db._commit()
    link = WorldGraph.load(repo).links[(WORLD, PTR)][0]
    assert link.confidence is Confidence.PROVISIONAL
    assert WorldGraph.load(repo, Confidence.CONFIRMED).link_count == 0


def test_a_row_missing_a_column_is_skipped_not_filled_in(repo):
    """⚠ 列が欠けた行を **(0,0) などで埋めない**（嘘のつながりができる）。"""
    class Partial:
        def transitions(self):
            return [
                {"from_map_id": WORLD},                       # 途中まで
                {"from_map_id": WORLD, "from_map_ptr": PTR,
                 "from_x": 1, "from_y": 1, "to_map_id": None,
                 "to_map_ptr": PTR, "to_x": 2, "to_y": 2},    # to が None
                {"from_map_id": WORLD, "from_map_ptr": PTR,
                 "from_x": 1, "from_y": 1, "to_map_id": MIDENHALL_1F,
                 "to_map_ptr": PTR, "to_x": 2, "to_y": 2},    # まとも
            ]

    graph = WorldGraph.load(Partial())
    assert graph.link_count == 1
    assert graph.neighbors((WORLD, PTR)) == [(MIDENHALL_1F, PTR)]


def test_a_broken_repository_gives_an_empty_graph():
    class Broken:
        def transitions(self):
            raise RuntimeError("DB が壊れている")

    graph = WorldGraph.load(Broken())
    assert graph.link_count == 0
    assert graph.route((1, 1), (2, 2)) is None
    assert LocationGraph.load(Broken(), object()).link_count == 0


# --- ロケーション間 ---------------------------------------------------

def test_maps_are_grouped_into_locations(repo, dictionary):
    move(repo, (MIDENHALL_1F, PTR), (WORLD, 0x8001))
    move(repo, (WORLD, 0x8001), (LIANPORT, 0x8002))
    graph = LocationGraph.load(repo, dictionary)
    assert graph.neighbors("midenhall") == ["world_map"]
    assert graph.route("midenhall", "lianport") == \
        ["midenhall", "world_map", "lianport"]


def test_stairs_inside_one_location_are_not_a_link(repo, dictionary):
    """★「ローレシア → ローレシア」は道順として意味が無い。"""
    move(repo, (MIDENHALL_1F, PTR), (MIDENHALL_2F, 0x9000))
    move(repo, (MIDENHALL_1F, PTR), (MIDENHALL_B1, 0x9001))
    graph = LocationGraph.load(repo, dictionary)
    assert graph.link_count == 0
    assert graph.neighbors("midenhall") == []


def test_maps_missing_from_the_dictionary_are_counted_not_guessed(repo,
                                                                 dictionary):
    """⚠⚠ **近いロケーションに寄せない。** 数えて画面に出す。"""
    move(repo, (0x7F, PTR), (WORLD, 0x8001))
    move(repo, (WORLD, 0x8001), (0x7E, 0x8002))
    graph = LocationGraph.load(repo, dictionary)
    assert graph.unknown_maps == 2
    assert graph.link_count == 0


def test_no_dictionary_gives_an_empty_location_graph(repo):
    graph = LocationGraph.load(repo, None)
    assert graph.node_count == 0
    assert graph.route("midenhall", "lianport") is None


def test_a_route_to_the_same_location_is_just_itself(repo, dictionary):
    graph = LocationGraph.load(repo, dictionary)
    assert graph.route("midenhall", "midenhall") == ["midenhall"]


def test_no_location_route_returns_none(repo, dictionary):
    move(repo, (MIDENHALL_1F, PTR), (WORLD, 0x8001))
    graph = LocationGraph.load(repo, dictionary)
    assert graph.route("midenhall", "lianport") is None


def test_several_maps_of_one_location_share_its_links(repo, dictionary):
    """★ローレシアのどの階から出ても、ロケーションの段では1つにまとまる。"""
    move(repo, (MIDENHALL_1F, PTR), (WORLD, 0x8001))
    move(repo, (MIDENHALL_2F, 0x9000), (WORLD, 0x8001), from_xy=(5, 5))
    graph = LocationGraph.load(repo, dictionary)
    assert graph.neighbors("midenhall") == ["world_map"]
    assert graph.link_count == 1, "同じつながりを2本にしている"


# --- マスの段（前からある。混ざっていないことの確認）------------------

def test_the_tile_graph_is_separate_from_the_map_graph(repo):
    """★マスの段とマップの段を混ぜない（節の形が違う）。"""
    repo.record_edge(Place(MIDENHALL_1F, PTR, 1, 1), Direction.RIGHT, 2, 1)
    move(repo, (MIDENHALL_1F, PTR), (WORLD, 0x8001))
    tiles = MapGraph.load(repo, MIDENHALL_1F, PTR)
    world = WorldGraph.load(repo)
    assert tiles.neighbors((1, 1)) == [((2, 1), 1.0)]
    assert world.neighbors((MIDENHALL_1F, PTR)) == [(WORLD, 0x8001)]
    # ★マスの辺はマップ間のグラフに入っていない
    assert world.link_count == 1


def test_the_tile_graph_needs_probable_before_it_calls_a_wall_a_wall(repo):
    """★★ **失敗1回では「通れない」と言わない**（指示書 2.4）。

    ⚠ 確度の順を写して書くと（`_ORDER` を使わずに）ここがずれる。
      ずれると1回の失敗で永久にその方向を避ける。
    """
    place = Place(MIDENHALL_1F, PTR, 1, 1)
    repo.record_blocked(place, Direction.UP)
    graph = MapGraph.load(repo, MIDENHALL_1F, PTR)
    assert graph.is_blocked((1, 1), Direction.UP) is False
    # provisional 以上なら True（確度そのものは記録されている）
    assert graph.is_blocked((1, 1), Direction.UP, Confidence.PROVISIONAL) is True

    for _ in range(2):
        repo.record_blocked(place, Direction.UP)      # 合計3回 -> probable
    graph = MapGraph.load(repo, MIDENHALL_1F, PTR)
    assert graph.is_blocked((1, 1), Direction.UP) is True
    assert graph.is_blocked((1, 1), Direction.UP, Confidence.CONFIRMED) is False


# --- 確度の順（★表を1箇所に寄せたので、そこを直接試す）-----------------

def test_the_confidence_order_lives_in_one_place():
    """★★ **順番の表を写さない。** ★★

    以前 `graph.py` と `location_resolver.py` に同じ表が2つあった。
    写すと、片方だけ直したときに**同じ確度が別の強さになる**。
    """
    assert Confidence.PROVISIONAL.rank < Confidence.PROBABLE.rank
    assert Confidence.PROBABLE.rank < Confidence.CONFIRMED.rank


def test_an_unreadable_confidence_falls_back_and_is_not_raised():
    """★読めない値で**勝手に上げない**（既定へ落とす）。"""
    assert Confidence.parse("confirmed") is Confidence.CONFIRMED
    assert Confidence.parse("とても確か") is None
    assert Confidence.parse("とても確か", Confidence.PROVISIONAL) is (
        Confidence.PROVISIONAL)
    assert Confidence.parse(None, Confidence.PROVISIONAL) is (
        Confidence.PROVISIONAL)


@pytest.mark.parametrize("cls", [
    Confidence, Direction, LandmarkKind, TransitionType,
])
def test_parse_accepts_a_member_not_only_a_string(cls):
    """⚠⚠ **`str` を継承した enum の落とし穴。** ★実際に踏んだ。

    `Enum.__str__` が `str.__str__` を上書きするので
    `str(Confidence.PROBABLE)` は `"Confidence.PROBABLE"`（値ではない）。
    → `parse` の先頭に `isinstance` の確認が無いと、**member を渡すと
      None が返る**。4つの `parse` すべてで確かめる。
    """
    member = list(cls)[1]
    assert cls.parse(member) is member
    assert str(member) != member.value, (
        "この落とし穴が無くなったなら、この試験も要らない")


# --- 画面（つながりを出す）--------------------------------------------

@pytest.fixture
def window(repo, dictionary):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6", reason="PySide6 が無い環境")
    from PySide6.QtWidgets import QApplication

    from retroux.core.navigation.floor_estimator import FloorEstimator
    from retroux.core.navigation.location_resolver import LocationResolver
    from retroux.core.recorder import Recorder
    from retroux.ui.map_window import MapWindow
    from retroux.ui.view_model import ViewModel

    app = QApplication.instance() or QApplication([])
    events = repo.db.path.parent / "events.jsonl"
    events.write_text("", encoding="utf-8")
    resolver = LocationResolver(dictionary)

    class Observer:
        pass

    Observer.repo = repo
    vm = ViewModel(
        Recorder(repo.db, "HASH", events, repo.db.path.parent / "cmd.json"),
        repo.db, "HASH", map_meta={}, navigation=Observer(),
        location_resolver=resolver,
        floor_estimator=FloorEstimator(repo, dictionary))
    repo.db.mark_visited("HASH", MIDENHALL_1F, PTR, 1, 1)
    win = MapWindow(vm)
    win.show()
    app.processEvents()
    yield win, vm
    win.close()


def test_the_window_says_when_there_are_no_connections_yet(window):
    """★「たぶんつながっている」は出さない。

    ⚠ 地形は読めるようになりましたが（2026-08-02〜03）、**どの階段が
      どこへ繋がるか**は ROM から分かりません。★通った記録だけを出します。
    """
    win, _vm = window
    assert "まだ記録がありません" in win._links.text()


def test_the_window_lists_where_you_could_go(window, repo):
    win, _vm = window
    move(repo, (MIDENHALL_1F, PTR), (WORLD, 0x8001),
         TransitionType.EXIT, from_xy=(9, 20))
    win._draw()
    text = win._links.text()
    assert "（9, 20）出口 → 世界地図" in text


def test_the_window_shows_the_kind_in_japanese(window, repo):
    win, _vm = window
    move(repo, (MIDENHALL_1F, PTR), (MIDENHALL_B1, 0x9000),
         TransitionType.STAIRS_DOWN)
    win._draw()
    assert "下り階段" in win._links.text()


def test_an_unjudged_transition_says_so_instead_of_guessing(window, repo):
    """⚠ 種類がまだ分からない遷移を「階段」などと決めつけない。

    ★2026-08-19 更新（RX-0074 の取りこぼし修正）: 種類が未判定（unknown）の
      ときは「種類未判定 →」の語を**出さない**（常時の注記を減らす依頼）。
      ⚠ ただし要点は「**階段などと決めつけない**」ことなので、そこを検査する。
      綴り違い（読めない種類）は別で「⚠不明(...)」と出す（別テスト）。
    """
    win, _vm = window
    move(repo, (MIDENHALL_1F, PTR), (WORLD, 0x8001))
    win._draw()
    text = win._links.text()
    assert "世界地図" in text                       # ★行き先は出す
    # ⚠ 種類を決めつけない（階段・扉・落とし穴などの語を出さない）
    for guessed in ("階段", "下り階段", "上り階段", "扉", "落とし穴"):
        assert guessed not in text


def test_many_connections_are_cut_short_with_a_count(window, repo):
    win, _vm = window
    for i in range(8):
        move(repo, (MIDENHALL_1F, PTR), (0x40 + i, 0x9000 + i),
             from_xy=(i, i))
    win._draw()
    assert "ほか 2 件" in win._links.text()


def test_the_view_model_returns_nothing_without_a_repository(tmp_path,
                                                            dictionary):
    from retroux.core.recorder import Recorder
    from retroux.ui.view_model import ViewModel

    db = Database(tmp_path / "x.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "e.jsonl"
    events.write_text("", encoding="utf-8")
    vm = ViewModel(Recorder(db, "HASH", events, tmp_path / "c.json"), db,
                   "HASH", navigation=None)
    assert vm.world_graph() is None
    assert vm.location_graph() is None
    assert vm.connections(MIDENHALL_1F, PTR) == []
