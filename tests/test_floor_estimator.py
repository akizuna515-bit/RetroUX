"""階層の決め方（マッパー仕様 フェーズ5 / 25章）。

★★ **確かめたいことの中心** ★★

  1. 出どころの強さの順（人の指定 > ROM 由来 > 上下移動からの推定）
  2. ⚠⚠ **食い違いを黙って片方に丸めない**（`conflict` に入れて画面へ出す）
  3. 分からない階層を **1F で埋めない**
  4. 階段・落とし穴以外からは階層を推定しない（町の出口が何階かは言えない）
  5. 推定は**1段だけ**（推定から推定へ渡さない。間違いが広がる）
  6. DB が壊れていても落ちない

⚠ 階層は自動移動が使う情報。静かに間違えると**別の階へ行こうとする**。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.db.database import Database
from retroux.core.navigation.floor_estimator import (
    FloorEstimator, label_for,
)
from retroux.core.navigation.location_resolver import LocationDictionary
from retroux.core.navigation.models import Confidence, Place, TransitionType
from retroux.core.navigation.repository import NavigationRepository

DATA = (pathlib.Path(__file__).resolve().parents[1]
        / "retroux" / "plugins" / "dq2" / "data")

# 同梱の対応表にある実際の値（★ROM 由来なので確か）
MIDENHALL_B1 = 0x04      # ローレシア B1  -> -1
MIDENHALL_1F = 0x03      # ローレシア 1F  -> +1
LAKE_CAVE_B1 = 0x2C      # 湖の洞窟 B1    -> -1
LAKE_CAVE_B2 = 0x2D      # 湖の洞窟 B2    -> -2
SEA_CAVE_B2 = 0x2F       # 海底洞窟 B2    -> -2（同じ階の別マップ）
LIANPORT = 0x0B          # ルプガナ（階層なし）
PTR = 0x8000


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    return NavigationRepository(db, "HASH")


@pytest.fixture
def dictionary():
    return LocationDictionary.load(DATA)


@pytest.fixture
def estimator(repo, dictionary):
    return FloorEstimator(repo, dictionary)


def transition(repo, from_map, to_map, kind, *, times=1, at=1):
    """`from_map` から `to_map` へ `kind` で入った、という記録を作る。

    ★`at` は座標。同じ座標を繰り返すと UPSERT で1行にまとまり
      `observed_count` が増える。**別の座標にすると別の行になる**。
    """
    for _ in range(times):
        repo.record_transition(Place(from_map, PTR, at, at),
                              Place(to_map, PTR, at + 1, at + 1), None)
    repo._conn.execute(
        "UPDATE MapTransition SET transition_type = ?"
        " WHERE from_map_id = ? AND to_map_id = ?",
        (kind.value, from_map, to_map))
    repo.db._commit()


# --- ラベル -----------------------------------------------------------

@pytest.mark.parametrize(("index", "expected"), [
    (-2, "B2"), (-1, "B1"), (1, "1F"), (7, "7F"), (None, None),
])
def test_the_label_matches_how_the_game_writes_it(index, expected):
    assert label_for(index) == expected


def test_floor_zero_is_shown_as_odd_not_rounded_to_1f():
    """⚠ 0階は無いはず。**勝手に 1F へ丸めない**（間違いが見えなくなる）。"""
    assert label_for(0) == "0?"


# --- ROM 由来 ---------------------------------------------------------

def test_the_rom_table_gives_the_floor(estimator):
    got = estimator.estimate(MIDENHALL_B1, PTR)
    assert (got.index, got.label) == (-1, "B1")
    assert got.source == "binding"
    assert got.confidence is Confidence.PROBABLE
    assert not got.has_conflict


def test_a_map_without_a_floor_says_so_instead_of_guessing(estimator):
    """★★ **分からない階層を 1F で埋めない。** ★★"""
    got = estimator.estimate(LIANPORT, PTR)
    assert got.index is None
    assert not got.known
    assert got.source == "unknown"
    assert got.display == "階層不明"


def test_an_unknown_map_id_has_no_floor(estimator):
    got = estimator.estimate(0x7F, PTR)
    assert got.index is None
    assert got.source == "unknown"


# --- 人の指定がいちばん強い -------------------------------------------

def test_a_manual_value_wins_over_the_rom_table(repo, estimator):
    repo.set_floor_override(MIDENHALL_B1, PTR, -3, "B3", note="実際に数えた")
    got = estimator.estimate(MIDENHALL_B1, PTR)
    assert (got.index, got.source) == (-3, "manual")
    assert got.confidence is Confidence.CONFIRMED


def test_a_manual_value_that_differs_is_reported_as_a_conflict(repo, estimator):
    """⚠⚠ **黙って人の値だけ出さない。**ROM の値と違うことを画面に出す。"""
    repo.set_floor_override(MIDENHALL_B1, PTR, -3)
    got = estimator.estimate(MIDENHALL_B1, PTR)
    assert got.has_conflict
    assert ("binding", -1) in got.conflict
    assert "食い違い" in got.display
    assert "binding:B1" in got.display


def test_a_manual_value_that_agrees_is_not_a_conflict(repo, estimator):
    repo.set_floor_override(MIDENHALL_B1, PTR, -1)
    got = estimator.estimate(MIDENHALL_B1, PTR)
    assert not got.has_conflict
    assert got.source == "manual"


def test_clearing_the_manual_value_goes_back_to_the_rom_table(repo, estimator):
    repo.set_floor_override(MIDENHALL_B1, PTR, -3)
    repo.clear_floor_override(MIDENHALL_B1, PTR)
    got = estimator.estimate(MIDENHALL_B1, PTR)
    assert (got.index, got.source) == (-1, "binding")


def test_setting_the_manual_value_twice_updates_it(repo):
    repo.set_floor_override(MIDENHALL_B1, PTR, -3)
    repo.set_floor_override(MIDENHALL_B1, PTR, -4, "B4")
    row = repo.floor_override(MIDENHALL_B1, PTR)
    assert (row["floor_index"], row["floor_label"]) == (-4, "B4")
    rows = repo._conn.execute("SELECT COUNT(*) FROM MapOverride").fetchone()
    assert rows[0] == 1, "同じマップで行が増えている"


def test_a_manual_value_of_none_does_not_count_as_a_value(repo, estimator):
    """★「階層は分からない」と人が入れた場合、ROM の値に譲る。"""
    repo.set_floor_override(MIDENHALL_B1, PTR, None, note="自信がない")
    got = estimator.estimate(MIDENHALL_B1, PTR)
    assert (got.index, got.source) == (-1, "binding")


# --- 上下移動からの推定 -----------------------------------------------

def test_going_down_stairs_puts_you_one_floor_lower(repo):
    """★ROM の表に無いマップでも、階段を下りてきたなら1つ下と言える。"""
    estimator = FloorEstimator(repo, LocationDictionary.load(DATA))
    transition(repo, MIDENHALL_B1, 0x7F, TransitionType.STAIRS_DOWN)
    got = estimator.estimate(0x7F, PTR)
    assert (got.index, got.label) == (-2, "B2")
    assert got.source == "inferred"
    assert got.confidence is Confidence.PROVISIONAL
    assert "下りて" in got.reason


def test_going_up_stairs_puts_you_one_floor_higher(repo, estimator):
    transition(repo, MIDENHALL_1F, 0x7F, TransitionType.STAIRS_UP)
    got = estimator.estimate(0x7F, PTR)
    assert (got.index, got.label) == (2, "2F")
    assert "上がって" in got.reason


def test_falling_through_a_pitfall_puts_you_one_floor_lower(repo, estimator):
    transition(repo, LAKE_CAVE_B1, 0x7F, TransitionType.PITFALL)
    got = estimator.estimate(0x7F, PTR)
    assert got.index == -2


@pytest.mark.parametrize("kind", [
    TransitionType.ENTRANCE, TransitionType.EXIT, TransitionType.DOOR,
    TransitionType.WARP, TransitionType.UNKNOWN, TransitionType.SHIP_BOARD,
])
def test_other_transitions_do_not_say_anything_about_the_floor(repo, estimator,
                                                               kind):
    """★町の出口が何階かは、上下移動ではないので**言えない**。"""
    transition(repo, MIDENHALL_B1, 0x7F, kind)
    assert estimator.estimate(0x7F, PTR).index is None


def test_an_unreadable_transition_type_is_not_treated_as_stairs(repo, estimator):
    transition(repo, MIDENHALL_B1, 0x7F, TransitionType.STAIRS_DOWN)
    repo._conn.execute("UPDATE MapTransition SET transition_type = 'かいだん'")
    repo.db._commit()
    assert estimator.estimate(0x7F, PTR).index is None


def test_the_estimate_only_follows_one_step(repo, estimator):
    """★★ **推定から推定へ渡さない。** ★★

    ROM の表に無い 0x7D へ B1 から下りて（-2 と推定できる）、
    さらに 0x7E へ下りても、0x7E は**分からないままにする**。
    推定を鎖にすると、途中の1つの間違いが全部に広がる。
    """
    transition(repo, MIDENHALL_B1, 0x7D, TransitionType.STAIRS_DOWN)
    transition(repo, 0x7D, 0x7E, TransitionType.STAIRS_DOWN)
    assert estimator.estimate(0x7D, PTR).index == -2
    assert estimator.estimate(0x7E, PTR).index is None


def test_a_manual_value_on_the_source_map_feeds_the_estimate(repo, estimator):
    """★人が決めた階からは推定できる（人の値は確かなので鎖にしてよい）。"""
    repo.set_floor_override(0x7D, PTR, -5)
    transition(repo, 0x7D, 0x7E, TransitionType.STAIRS_DOWN)
    assert estimator.estimate(0x7E, PTR).index == -6


def test_the_most_observed_answer_wins(repo, estimator):
    """★変な遷移が1回混ざっても引っ張られない。"""
    transition(repo, LAKE_CAVE_B1, 0x7F, TransitionType.STAIRS_DOWN, times=1)
    transition(repo, LAKE_CAVE_B2, 0x7F, TransitionType.STAIRS_DOWN, times=5,
               at=5)
    got = estimator.estimate(0x7F, PTR)
    assert got.index == -3, "回数の多いほう（B2 の下）を採っていない"


def test_votes_add_up_across_different_transition_rows(repo, estimator):
    """★★ **別の行の観測も足し合わせる。** ★★

    ⚠ 足さずに「最後に見た行」だけを見ると、次のような場面で間違える:

        B2 の2つのマップから下りてきた（-3 が2票）
        B1 の1つのマップから下りてきた（-2 が1票）

      足せば -3。足さないとどちらも1票で、同数の決め方（地上に近いほう）が
      効いて **-2** になってしまう。
    """
    transition(repo, LAKE_CAVE_B2, 0x7F, TransitionType.STAIRS_DOWN, at=1)
    transition(repo, SEA_CAVE_B2, 0x7F, TransitionType.STAIRS_DOWN, at=3)
    transition(repo, LAKE_CAVE_B1, 0x7F, TransitionType.STAIRS_DOWN, at=5)
    got = estimator.estimate(0x7F, PTR)
    assert got.index == -3, "別の行の観測を足していない"


def test_the_rom_table_beats_the_estimate_and_the_difference_is_shown(repo,
                                                                     estimator):
    """⚠ ROM の表と推定が食い違ったら**両方見せる**。"""
    transition(repo, MIDENHALL_B1, LAKE_CAVE_B2, TransitionType.STAIRS_DOWN)
    got = estimator.estimate(LAKE_CAVE_B2, PTR)
    assert (got.index, got.source) == (-2, "binding")
    assert got.conflict == (), "同じ値なので食い違いではない"

    transition(repo, LAKE_CAVE_B2, LAKE_CAVE_B1, TransitionType.STAIRS_DOWN)
    got = estimator.estimate(LAKE_CAVE_B1, PTR)
    assert (got.index, got.source) == (-1, "binding")
    assert ("inferred", -3) in got.conflict


def test_conflicts_lists_only_the_maps_that_disagree(repo, estimator):
    repo.set_floor_override(MIDENHALL_B1, PTR, -9)
    found = estimator.conflicts([(MIDENHALL_B1, PTR), (MIDENHALL_1F, PTR),
                                 (LIANPORT, PTR)])
    assert [e.map_id for e in found] == [MIDENHALL_B1]


def test_conflicts_needs_the_pointer_to_find_a_manual_value(repo, estimator):
    """⚠ 人の指定は `(map_id, map_ptr)` が鍵。ID だけだと**見落とす**。"""
    repo.set_floor_override(MIDENHALL_B1, PTR, -9)
    assert estimator.conflicts([MIDENHALL_B1]) == []
    assert estimator.conflicts([(MIDENHALL_B1, PTR)])


# --- 無くても落ちない -------------------------------------------------

def test_it_works_with_no_repository_at_all(dictionary):
    estimator = FloorEstimator(None, dictionary)
    assert estimator.estimate(MIDENHALL_B1, PTR).index == -1


def test_it_works_with_no_dictionary_at_all(repo):
    estimator = FloorEstimator(repo, None)
    got = estimator.estimate(MIDENHALL_B1, PTR)
    assert got.index is None
    assert got.source == "unknown"


def test_a_broken_repository_does_not_raise(dictionary):
    """⚠ 階層が出ないだけで、ゲームと画面は動くこと。"""
    class Broken:
        def floor_override(self, *a, **k):
            raise RuntimeError("DB が壊れている")

        def transitions_into(self, *a, **k):
            raise RuntimeError("DB が壊れている")

    got = FloorEstimator(Broken(), dictionary).estimate(MIDENHALL_B1, PTR)
    assert got.index == -1, "ROM 由来の値まで捨てている"


def test_an_old_database_gets_the_new_table(tmp_path):
    """★★ 依頼者の DB は**もう存在している**。開くだけで表が足りること。

    ⚠ 列を足したときは `_migrate` が要ったが、**表**は
      `CREATE TABLE IF NOT EXISTS` で足りる。ここでそれを確かめる。
    """
    import sqlite3

    path = tmp_path / "old.sqlite3"
    # ★いまの DB を作ってから、新しい表だけ落として「前の版」を作る。
    #   手で古いスキーマを書くと、そちらが古びて嘘になる。
    old = Database(path)
    old.register_rom("HASH", "テストROM", "JP", mapper=2)
    old._conn.execute("DROP TABLE MapOverride")
    old._conn.commit()
    old.close()
    with sqlite3.connect(path) as check:
        names = {r[0] for r in check.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "MapOverride" not in names, "前の版を作れていない"

    db = Database(path)
    repo = NavigationRepository(db, "HASH")
    repo.set_floor_override(MIDENHALL_B1, PTR, -1)
    assert repo.floor_override(MIDENHALL_B1, PTR)["floor_index"] == -1


# --- 画面（食い違いを隠さない）---------------------------------------

@pytest.fixture
def map_window(tmp_path, dictionary):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6", reason="PySide6 が無い環境")
    from PySide6.QtWidgets import QApplication

    from retroux.core.recorder import Recorder
    from retroux.ui.map_window import MapWindow
    from retroux.ui.view_model import ViewModel

    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "w.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    navigation_repo = NavigationRepository(db, "HASH")

    class Observer:
        """`ViewModel.set_map_floor` が触るのは `repo` だけ。"""

        repo = navigation_repo

    vm = ViewModel(
        Recorder(db, "HASH", events, tmp_path / "command.json"), db, "HASH",
        map_meta={}, navigation=Observer(),
        floor_estimator=FloorEstimator(navigation_repo, dictionary))
    for map_id in (MIDENHALL_B1, LIANPORT):
        db.mark_visited("HASH", map_id, PTR, 1, 1)
    win = MapWindow(vm)
    win.show()
    app.processEvents()
    yield win, vm, navigation_repo
    win.close()


def select(win, map_id):
    win._list.setCurrentRow([k[0] for k in win._keys].index(map_id))


def test_the_window_does_not_say_the_floor_came_from_the_rom(map_window):
    """★2026-08-19 依頼者: ROM 由来（確か）の根拠文言は**出さない**（タイトルと被る）。

    ⚠ 以前は「ROM 由来」と出す検査で、仕様変更後も赤のまま残っていた（RX-0085）。
      ★階層そのものは捨てない（編集ダイアログが `.text()` を読む）。
    """
    win, _vm, _repo = map_window
    select(win, MIDENHALL_B1)
    assert "階層: B1" in win._floor_note.text()
    assert "ROM 由来" not in win._floor_note.text()
    assert not win._floor_note.isVisible(), "★食い違い(warn)のときだけ見せる"


def test_the_window_says_when_the_floor_is_unknown(map_window):
    """★分からない階層を 1F で埋めず、「不明」と書くこと。"""
    win, _vm, _repo = map_window
    select(win, LIANPORT)
    assert "階層: 不明" in win._floor_note.text()


def test_the_window_shows_a_conflict_and_asks_the_person_to_decide(map_window):
    """⚠⚠ **食い違いを隠さない。**どちらが正しいかはこちらで決めない。"""
    win, vm, _repo = map_window
    assert vm.set_map_floor(MIDENHALL_B1, PTR, -3, note="実際に数えた")
    select(win, LIANPORT)          # いったん別のマップへ
    select(win, MIDENHALL_B1)
    text = win._floor_note.text()
    assert "食い違い" in text
    assert "binding:B1" in text
    assert "指定してください" in text
    # ★色も変える（読み流されないように）
    assert "#e0a030" in win._floor_note.styleSheet()


def test_a_read_only_view_model_does_not_write_a_floor(tmp_path, dictionary):
    """⚠ 閲覧専用のときは書かない（別プロセスと二重に書かない）。

    ★守っているのは `ViewModel.__init__` の
      `self.navigation = None if read_only else navigation`。
      **観測役ごと切る**ので、書き込みの入口が1つも残らない。
    """
    from retroux.core.recorder import Recorder
    from retroux.ui.view_model import ViewModel

    db = Database(tmp_path / "r.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    repo = NavigationRepository(db, "HASH")

    class Observer:
        pass

    Observer.repo = repo
    vm = ViewModel(
        Recorder(db, "HASH", events, tmp_path / "command.json"), db, "HASH",
        read_only=True, navigation=Observer(),
        floor_estimator=FloorEstimator(repo, dictionary))
    assert vm.navigation is None, "閲覧専用なのに観測役が生きている"
    assert vm.set_map_floor(MIDENHALL_B1, PTR, -3) is False
    assert repo.floor_override(MIDENHALL_B1, PTR) is None


def test_no_observer_means_no_write(tmp_path, dictionary):
    """★観測役が無ければ書かない（記録機能を切っている環境）。"""
    from retroux.core.recorder import Recorder
    from retroux.ui.view_model import ViewModel

    db = Database(tmp_path / "n.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    repo = NavigationRepository(db, "HASH")
    vm = ViewModel(
        Recorder(db, "HASH", events, tmp_path / "command.json"), db, "HASH",
        navigation=None, floor_estimator=FloorEstimator(repo, dictionary))
    assert vm.set_map_floor(MIDENHALL_B1, PTR, -3) is False
    assert repo.floor_override(MIDENHALL_B1, PTR) is None


def test_a_transition_always_has_a_source_map(repo):
    """★`from_map_id` は NOT NULL。だから推定側で None を気にしなくてよい。

    ⚠ この前提が崩れたら（列を書き換えたら）ここが赤くなる。
    """
    import sqlite3

    transition(repo, MIDENHALL_B1, 0x7F, TransitionType.STAIRS_DOWN)
    with pytest.raises(sqlite3.IntegrityError):
        repo._conn.execute("UPDATE MapTransition SET from_map_id = NULL")
