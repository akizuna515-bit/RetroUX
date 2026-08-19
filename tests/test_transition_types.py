"""遷移の種類を人が直す（マッパー仕様 フェーズ4 / 25章）。

★★ **確かめたいことの中心** ★★

  1. 観測は種類を `unknown` で入れる（画面から階段か扉かは**判定できない**）
  2. 人が直した値は `confirmed` になり、**階層の推定に使われる**
  3. ⚠ 読めない種類は入れない（`unknown` に丸めない）
  4. ⚠ 同じマスから2本以上出ていることがある。**1本だけ直して「直した」と言わない**
  5. ⚠ 遷移の記録が無いマスで押したら「無い」と言う（作らない）
  6. 遷移タイルの写真は**人が押したときだけ**（気づいたときには画面が変わっている）
"""

from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.db.database import Database  # noqa: E402
from retroux.core.navigation.floor_estimator import FloorEstimator  # noqa: E402
from retroux.core.navigation.location_resolver import (  # noqa: E402
    LocationResolver,
)
from retroux.core.navigation.models import (  # noqa: E402
    ARROW_TRANSITIONS, TRANSITION_LABELS, Confidence, Place, TransitionType,
)
from retroux.core.navigation.repository import NavigationRepository  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.ui.map_window import MapWindow  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402

DATA = (pathlib.Path(__file__).resolve().parents[1]
        / "retroux" / "plugins" / "dq2" / "data")
MIDENHALL_1F = 0x03
MIDENHALL_B1 = 0x04
PTR = 0x8000


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        yield QApplication([])
    except Exception as exc:                          # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")


@pytest.fixture
def bundle(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    command = tmp_path / "command.json"
    repo = NavigationRepository(db, "HASH")
    resolver = LocationResolver.load(DATA)

    class Observer:
        pass

    Observer.repo = repo
    vm = ViewModel(
        Recorder(db, "HASH", events, command), db, "HASH",
        map_meta={}, navigation=Observer(), location_resolver=resolver,
        floor_estimator=FloorEstimator(repo, resolver.dictionary))
    return vm, repo, command


def at(x=3, y=4, map_id=MIDENHALL_1F):
    return Place(map_id, PTR, x, y)


# --- 語彙 -------------------------------------------------------------

def test_every_kind_has_a_japanese_label():
    """★英語の値をそのまま画面に出さない。"""
    assert set(TRANSITION_LABELS) == set(TransitionType)
    assert all(TRANSITION_LABELS[k] for k in TransitionType)


def test_parse_returns_none_for_junk_instead_of_unknown():
    """⚠⚠ **`UNKNOWN` に丸めない。**

    丸めると「まだ判定していない」と「綴りを間違えた」が同じ値になる。
    """
    assert TransitionType.parse("stairs_up") is TransitionType.STAIRS_UP
    assert TransitionType.parse(TransitionType.DOOR) is TransitionType.DOOR
    assert TransitionType.parse("かいだん") is None
    assert TransitionType.parse(None) is None


def test_the_arrow_keys_cover_the_four_kinds_we_chose():
    """★どのキーがどの種類かは1箇所（`ARROW_TRANSITIONS`）にまとめてある。"""
    assert set(ARROW_TRANSITIONS) == {"up", "down", "left", "right"}
    # ★上下は**階層が動くもの**（階層の推定が使う値）
    assert ARROW_TRANSITIONS["up"] is TransitionType.STAIRS_UP
    assert ARROW_TRANSITIONS["down"] is TransitionType.STAIRS_DOWN
    # ★左右は階層が動かないもの
    assert ARROW_TRANSITIONS["left"] is TransitionType.EXIT
    assert ARROW_TRANSITIONS["right"] is TransitionType.ENTRANCE


# --- 直す -------------------------------------------------------------

def test_an_observed_transition_starts_as_unknown(bundle):
    """★画面から階段か扉かは判定できない。だから `unknown` で入る。"""
    _vm, repo, _cmd = bundle
    repo.record_transition(at(), Place(MIDENHALL_B1, 0x9000, 1, 1))
    row = repo.transitions_at(at())[0]
    assert row["transition_type"] == "unknown"


def test_a_person_can_set_the_kind_and_it_becomes_confirmed(bundle):
    _vm, repo, _cmd = bundle
    repo.record_transition(at(), Place(MIDENHALL_B1, 0x9000, 1, 1))
    row_id = repo.transitions_at(at())[0]["id"]
    assert repo.set_transition_type(row_id, TransitionType.STAIRS_DOWN)
    row = repo.transitions_at(at())[0]
    assert row["transition_type"] == "stairs_down"
    assert row["confidence"] == Confidence.CONFIRMED.value


def test_an_unreadable_kind_is_refused_and_leaves_the_row_alone(bundle):
    """⚠ 読めない種類で**上書きしない**（`unknown` にも戻さない）。"""
    _vm, repo, _cmd = bundle
    repo.record_transition(at(), Place(MIDENHALL_B1, 0x9000, 1, 1))
    row_id = repo.transitions_at(at())[0]["id"]
    repo.set_transition_type(row_id, TransitionType.DOOR)
    assert repo.set_transition_type(row_id, "かいだん") is False
    assert repo.transitions_at(at())[0]["transition_type"] == "door"


def test_setting_the_kind_of_a_missing_row_returns_false(bundle):
    _vm, repo, _cmd = bundle
    assert repo.set_transition_type(999, TransitionType.DOOR) is False


def test_all_transitions_from_one_tile_are_fixed_together(bundle):
    """⚠⚠ **1本だけ直して「直した」と言わない。**

    同じマスから2つ以上の遷移が出ていることはある（行き先が2つ）。
    """
    vm, repo, _cmd = bundle
    repo.record_transition(at(), Place(MIDENHALL_B1, 0x9000, 1, 1))
    repo.record_transition(at(), Place(MIDENHALL_B1, 0x9000, 5, 5))
    assert vm.set_transition_type_here(at(), TransitionType.STAIRS_DOWN) == 2
    kinds = {r["transition_type"] for r in repo.transitions_at(at())}
    assert kinds == {"stairs_down"}


def test_fixing_a_tile_with_no_transition_changes_nothing(bundle):
    """★無い所に作らない。**0 本**と返して、呼ぶ側が言えるようにする。"""
    vm, repo, _cmd = bundle
    assert vm.set_transition_type_here(at(), TransitionType.DOOR) == 0
    assert repo.transitions() == []


def test_only_transitions_from_that_exact_tile_are_fixed(bundle):
    vm, repo, _cmd = bundle
    repo.record_transition(at(3, 4), Place(MIDENHALL_B1, 0x9000, 1, 1))
    repo.record_transition(at(9, 9), Place(MIDENHALL_B1, 0x9000, 2, 2))
    vm.set_transition_type_here(at(3, 4), TransitionType.STAIRS_DOWN)
    assert repo.transitions_at(at(9, 9))[0]["transition_type"] == "unknown"


def test_a_fixed_kind_feeds_the_floor_estimate(bundle):
    """★★ **直した種類が階層の推定に効く。** ★★

    これが効かないと、直しても自動移動の判断は変わらない。
    """
    vm, repo, _cmd = bundle
    unknown_map = 0x7F
    repo.record_transition(Place(MIDENHALL_B1, PTR, 1, 1),
                           Place(unknown_map, PTR, 2, 2))
    assert vm.floor_of_map(unknown_map, PTR).index is None
    vm.set_transition_type_here(Place(MIDENHALL_B1, PTR, 1, 1),
                               TransitionType.STAIRS_DOWN)
    got = vm.floor_of_map(unknown_map, PTR)
    assert (got.index, got.source) == (-2, "inferred")


def test_a_read_only_view_model_cannot_fix_a_kind(tmp_path):
    db = Database(tmp_path / "r.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "e.jsonl"
    events.write_text("", encoding="utf-8")
    repo = NavigationRepository(db, "HASH")
    repo.record_transition(at(), Place(MIDENHALL_B1, 0x9000, 1, 1))

    class Observer:
        pass

    Observer.repo = repo
    vm = ViewModel(Recorder(db, "HASH", events, tmp_path / "c.json"), db,
                   "HASH", read_only=True, navigation=Observer())
    assert vm.set_transition_type_here(at(), TransitionType.DOOR) == 0
    assert repo.transitions_at(at())[0]["transition_type"] == "unknown"


# --- 写真 -------------------------------------------------------------

def test_asking_for_a_tile_photo_writes_a_command(bundle):
    """★頼むだけ。**撮るのは Lua**（座標も Lua が読む）。"""
    import json

    vm, _repo, command = bundle
    assert vm.request_tile_shot()
    body = json.loads(command.read_text(encoding="utf-8"))
    assert body["action"] == "capture_tile"
    assert body["request_id"] > 0


def test_two_photo_requests_get_different_ids(bundle):
    """⚠ 同じ `request_id` だと Lua が2回目を無視する（playbook）。"""
    import json
    import time

    vm, _repo, command = bundle
    vm.request_tile_shot()
    first = json.loads(command.read_text(encoding="utf-8"))["request_id"]
    time.sleep(0.01)
    vm.request_tile_shot()
    second = json.loads(command.read_text(encoding="utf-8"))["request_id"]
    assert second > first


def test_a_read_only_view_model_does_not_ask_for_a_photo(tmp_path):
    db = Database(tmp_path / "r.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "e.jsonl"
    events.write_text("", encoding="utf-8")
    command = tmp_path / "c.json"
    vm = ViewModel(Recorder(db, "HASH", events, command), db, "HASH",
                   read_only=True)
    assert vm.request_tile_shot() is False
    assert not command.exists()


# --- 画面 -------------------------------------------------------------

@pytest.fixture
def window(app, bundle):
    vm, repo, command = bundle
    vm.db.mark_visited("HASH", MIDENHALL_1F, PTR, 3, 4)
    win = MapWindow(vm)
    win.show()
    app.processEvents()
    yield win, vm, repo
    win.close()


def test_the_window_writes_the_key_assignments_on_screen(window):
    """★覚えていないと使えない。キーの割り当てを**読めるようにする**。

    ★★ 2026-08-09: 一覧は**ツールチップへ**移しました（依頼者の判断）★★

      ⚠ 4区画にすると、この窓の幅は 362px しかありません。
        キーの一覧は折り返しても3行を占め、地図そのものが潰れました。

      ⚠⚠ **消してはいません。** 画面には「キー: ?」を残し、
        マウスを乗せれば全文が出ます。★「覚えていないと使えない」という
        元の狙いは、読める場所があることで満たします。
    """
    win, _vm, _repo = window
    # ★画面には「ここにキーの説明がある」と分かるものを残す
    assert "キー" in win._keys_note.text()
    # ★★ 2026-08-19: よく使う2つだけ案内する（依頼者）。★★
    #   ⚠ Ctrl+P（写真）・Ctrl+矢印（遷移の種類）は上級操作なので案内しない。
    tip = win._keys_note.toolTip()
    assert "Ctrl+M" in tip and "Ctrl+Shift+M" in tip
    assert "Ctrl+↑" not in tip and "Ctrl+P" not in tip


def test_marking_a_transition_from_the_window(window):
    win, vm, repo = window
    repo.record_transition(at(3, 4), Place(MIDENHALL_B1, 0x9000, 1, 1))
    win._draw(here=(3, 4))
    win.mark_transition(TransitionType.STAIRS_DOWN)
    assert repo.transitions_at(at(3, 4))[0]["transition_type"] == "stairs_down"
    assert "下り階段" in win._action.text()


def test_the_window_says_when_there_is_no_transition_to_fix(window):
    """★黙って何もしない、をやらない（直ったと思われる）。"""
    win, _vm, _repo = window
    win._draw(here=(3, 4))
    win.mark_transition(TransitionType.DOOR)
    assert "遷移の記録がありません" in win._action.text()


def test_the_window_says_when_the_current_tile_is_unknown(window):
    win, _vm, _repo = window
    win._draw(here=None)
    win.mark_transition(TransitionType.DOOR)
    assert "分からない" in win._action.text()


def test_the_window_reports_that_the_photo_was_only_requested(window):
    """★「頼んだ」と「撮れた」は別。画面の文もそう書く。"""
    win, _vm, _repo = window
    win.capture_tile()
    assert "頼みました" in win._action.text()
    assert "撮れたかどうか" in win._action.text()


def test_the_connection_list_uses_the_shared_label_table(window):
    win, _vm, repo = window
    repo.record_transition(at(3, 4), Place(MIDENHALL_B1, 0x9000, 1, 1))
    row_id = repo.transitions_at(at(3, 4))[0]["id"]
    repo.set_transition_type(row_id, TransitionType.WARP)
    win._draw(here=(3, 4))
    assert "旅の扉" in win._links.text()


def test_an_unreadable_kind_in_the_database_is_shown_not_hidden(window):
    """⚠ 綴り違いを「種類未判定」に見せない（気づけなくなる）。"""
    win, _vm, repo = window
    repo.record_transition(at(3, 4), Place(MIDENHALL_B1, 0x9000, 1, 1))
    repo._conn.execute("UPDATE MapTransition SET transition_type = 'かいだん'")
    repo.db._commit()
    win._draw(here=(3, 4))
    assert "⚠不明(かいだん)" in win._links.text()
