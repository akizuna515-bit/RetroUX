"""移動知識の保存（2026-07-30 / 指示書 4章）。

★★ **守りたい一番大事な契約** ★★

    同じ情報は UPSERT で集約する。**同じ道を何度通っても行は増えない。**

★ほかに守ること:
  1. 通れたら `confirmed`（実測なので）
  2. **失敗1回で壁と確定しない**（初回は `unknown_block` + `provisional`）
  3. 何度も失敗して初めて確度を上げる
  4. ★**一度でも通れた方向は、何度失敗しても確度を上げない**
  5. 通れたときも「通れなかった」の行を**消さない**（観測は事実）
"""

from __future__ import annotations

import pytest

from retroux.core.db.database import Database
from retroux.core.navigation.models import (
    Classification, Confidence, Direction, Place, TransitionType,
)
from retroux.core.navigation.repository import NavigationRepository, Thresholds

HASH = "HASH"
TOWN = (0x07, 0x8E83)


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "n.sqlite3")
    db.register_rom(HASH, "テストROM", "JP", mapper=2)
    yield NavigationRepository(db, HASH)
    db.close()


def at(x: int, y: int) -> Place:
    return Place(TOWN[0], TOWN[1], x, y)


# --- 1. 通れた ---------------------------------------------------------


def test_edge_is_recorded(repo):
    assert repo.record_edge(at(10, 5), Direction.RIGHT, 11, 5) is True
    rows = repo.edges(*TOWN)
    assert len(rows) == 1
    assert rows[0]["direction"] == "right"
    assert rows[0]["success_count"] == 1
    assert rows[0]["action_type"] == "walk"
    # ★実際に通れたのだから confirmed
    assert rows[0]["confidence"] == Confidence.CONFIRMED.value


def test_same_edge_does_not_add_rows(repo):
    """★★ 同じ道を10回通っても**1行**。回数だけ増える。"""
    for _ in range(10):
        repo.record_edge(at(10, 5), Direction.RIGHT, 11, 5)
    rows = repo.edges(*TOWN)
    assert len(rows) == 1
    assert rows[0]["success_count"] == 10
    assert rows[0]["first_seen"] <= rows[0]["last_seen"]


def test_only_the_first_pass_is_new(repo):
    assert repo.record_edge(at(1, 1), Direction.UP, 1, 0) is True
    assert repo.record_edge(at(1, 1), Direction.UP, 1, 0) is False


def test_opposite_direction_is_a_different_edge(repo):
    """★A→B が通れても B→A を勝手に登録しない（指示書 6章）。

    一方通行・落とし穴・イベントがあるため、**逆は逆で観測してから**。
    """
    repo.record_edge(at(10, 5), Direction.RIGHT, 11, 5)
    rows = repo.edges(*TOWN)
    assert len(rows) == 1, "逆方向まで登録している"
    repo.record_edge(at(11, 5), Direction.LEFT, 10, 5)
    assert len(repo.edges(*TOWN)) == 2


def test_edges_are_scoped_to_the_map(repo):
    """★同じ座標でも別マップなら別の知識（`map_ptr` まで鍵に含める）。"""
    repo.record_edge(at(10, 5), Direction.RIGHT, 11, 5)
    repo.record_edge(Place(0x07, 0x9999, 10, 5), Direction.RIGHT, 11, 5)
    assert len(repo.edges(*TOWN)) == 1
    assert len(repo.edges(0x07, 0x9999)) == 1


# --- 2. 通れなかった ---------------------------------------------------


def test_blocked_starts_as_unknown(repo):
    """★★ **失敗1回で壁と決めない**（指示書 2.4）。"""
    assert repo.record_blocked(at(10, 5), Direction.UP) is True
    rows = repo.blocked(*TOWN)
    assert len(rows) == 1
    assert rows[0]["classification"] == Classification.UNKNOWN_BLOCK.value
    assert rows[0]["confidence"] == Confidence.PROVISIONAL.value
    assert rows[0]["blocked_count"] == 1


def test_blocked_is_aggregated(repo):
    """★同じ方向で3回失敗 -> 1行 / 回数3 / 確度は probable へ。"""
    for _ in range(3):
        repo.record_blocked(at(10, 5), Direction.UP)
    rows = repo.blocked(*TOWN)
    assert len(rows) == 1
    assert rows[0]["blocked_count"] == 3
    assert rows[0]["confidence"] == Confidence.PROBABLE.value


def test_threshold_is_configurable(tmp_path):
    """★閾値はコードに散らさず設定から変えられること（指示書 4.2）。"""
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom(HASH, "t", "JP", mapper=2)
    repo = NavigationRepository(db, HASH, Thresholds(blocked_probable=5))
    try:
        for _ in range(4):
            repo.record_blocked(at(1, 1), Direction.UP)
        assert repo.blocked(*TOWN)[0]["confidence"] == Confidence.PROVISIONAL.value
        repo.record_blocked(at(1, 1), Direction.UP)
        assert repo.blocked(*TOWN)[0]["confidence"] == Confidence.PROBABLE.value
    finally:
        db.close()


def test_passing_later_clears_the_wall_suspicion(repo):
    """★★ 一度通れたら壁の疑いを外す（指示書 5.3 / 11.5）。

    ⚠ ただし**行は消さない**。「一度は通れなかった」も観測した事実で、
      消すと「扉が閉まっていた」「NPCが居た」という情報まで失う。
    """
    for _ in range(3):
        repo.record_blocked(at(10, 5), Direction.UP)
    assert repo.blocked(*TOWN)[0]["confidence"] == Confidence.PROBABLE.value

    repo.record_edge(at(10, 5), Direction.UP, 10, 4)
    repo.clear_blocked(at(10, 5), Direction.UP)
    row = repo.blocked(*TOWN)[0]
    assert row["success_count"] == 1
    assert row["confidence"] == Confidence.PROVISIONAL.value
    assert row["classification"] == Classification.UNKNOWN_BLOCK.value
    assert row["blocked_count"] == 3, "失敗した観測まで消している"


def test_once_passable_never_becomes_probable(repo):
    """★★ 一度でも通れた方向は、何度失敗しても確度を上げない。

    扉やNPCのように「開くときもある」ものを壁にしないため。
    """
    repo.record_blocked(at(10, 5), Direction.UP)
    repo.clear_blocked(at(10, 5), Direction.UP)
    for _ in range(10):
        repo.record_blocked(at(10, 5), Direction.UP)
    row = repo.blocked(*TOWN)[0]
    assert row["confidence"] == Confidence.PROVISIONAL.value
    assert row["blocked_count"] == 11


# --- 3. 遷移 -----------------------------------------------------------


def test_transition_is_recorded(repo):
    src = Place(0x01, 0x8000, 100, 100)
    dst = Place(0x07, 0x8E83, 11, 22)
    assert repo.record_transition(src, dst, Direction.UP) is True
    rows = repo.transitions()
    assert len(rows) == 1
    r = rows[0]
    assert (r["from_map_id"], r["from_x"], r["from_y"]) == (0x01, 100, 100)
    assert (r["to_map_id"], r["to_x"], r["to_y"]) == (0x07, 11, 22)
    assert r["transition_type"] == TransitionType.UNKNOWN.value
    assert r["direction_hint"] == "up"
    assert r["confidence"] == Confidence.PROVISIONAL.value


def test_same_transition_does_not_add_rows(repo):
    """★同じ遷移を通っても行は増えず、回数だけ増える（指示書 11.7）。"""
    src = Place(0x01, 0x8000, 100, 100)
    dst = Place(0x07, 0x8E83, 11, 22)
    for _ in range(5):
        repo.record_transition(src, dst)
    rows = repo.transitions()
    assert len(rows) == 1
    assert rows[0]["observed_count"] == 5
    # ★2回以上見たので confirmed
    assert rows[0]["confidence"] == Confidence.CONFIRMED.value


def test_different_destination_is_a_different_transition(repo):
    src = Place(0x01, 0x8000, 100, 100)
    repo.record_transition(src, Place(0x07, 0x8E83, 11, 22))
    repo.record_transition(src, Place(0x09, 0x9103, 5, 5))
    assert len(repo.transitions()) == 2


# --- 4. 集計とセッション -----------------------------------------------


def test_counts(repo):
    repo.record_edge(at(1, 1), Direction.RIGHT, 2, 1)
    repo.record_blocked(at(1, 1), Direction.UP)
    repo.record_transition(Place(0x01, 0x8000, 1, 1), Place(0x07, 0x8E83, 2, 2))
    assert repo.counts() == {"edges": 1, "blocked": 1, "transitions": 1,
                            # ★人が入れるもの（フェーズ6）は観測とは別に数える
                            "notes": 0, "landmarks": 0}


def test_session_records_only_start_and_end(repo):
    """★各歩行ステップは入れない。開始・終了・結果だけ（指示書 4.4）。"""
    sid = repo.start_session("manual_observation", at(1, 1))
    repo.finish_session(sid, "completed", at(5, 5), steps=42, transitions=3)
    row = repo._conn.execute(
        "SELECT * FROM NavigationSession WHERE id = ?", (sid,)).fetchone()
    assert row["mode"] == "manual_observation"
    assert row["result"] == "completed"
    assert (row["start_x"], row["start_y"]) == (1, 1)
    assert (row["end_x"], row["end_y"]) == (5, 5)
    assert row["steps_moved"] == 42
    assert row["transitions"] == 3
    assert row["ended_at"] is not None


# --- 5. グラフへの変換（次フェーズの入口）------------------------------


def test_graph_from_saved_edges(repo):
    from retroux.core.navigation.graph import MapGraph

    repo.record_edge(at(1, 1), Direction.RIGHT, 2, 1)
    repo.record_edge(at(2, 1), Direction.RIGHT, 3, 1)
    repo.record_edge(at(2, 1), Direction.DOWN, 2, 2)
    graph = MapGraph.load(repo, *TOWN)
    assert graph.neighbors((1, 1)) == [((2, 1), 1.0)]
    assert sorted(graph.neighbors((2, 1))) == [((2, 2), 1.0), ((3, 1), 1.0)]
    assert graph.neighbors((9, 9)) == []
    assert graph.edge_count == 3
    assert graph.node_count == 4


def test_graph_ignores_one_off_blocks(repo):
    """★★ 1回失敗しただけ（`provisional`）では「通れない」と言わない。"""
    from retroux.core.navigation.graph import MapGraph

    repo.record_blocked(at(1, 1), Direction.UP)
    graph = MapGraph.load(repo, *TOWN)
    assert graph.is_blocked((1, 1), Direction.UP) is False

    for _ in range(2):
        repo.record_blocked(at(1, 1), Direction.UP)
    graph = MapGraph.load(repo, *TOWN)
    assert graph.is_blocked((1, 1), Direction.UP) is True


def test_graph_only_knows_observed_paths(repo):
    """★知らない道は通らない（未観測のマスへは行けない）。安全側の挙動。"""
    from retroux.core.navigation.graph import MapGraph

    repo.record_edge(at(1, 1), Direction.RIGHT, 2, 1)
    graph = MapGraph.load(repo, *TOWN)
    assert graph.neighbors((1, 1)) == [((2, 1), 1.0)]
    assert graph.neighbors((1, 2)) == []
