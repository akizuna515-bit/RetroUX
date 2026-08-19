"""メモと目印（マッパー仕様 フェーズ6 / 25章）。

★★ **確かめたいことの中心** ★★

  1. メモは**人の言葉**。観測が上書きしない
  2. ⚠ 空のメモは残さない（**消す**）。中身の無いメモが地図に並ばない
  3. 目印は**種類が決まっているものだけ**。読めない種類は `other` に丸めない
  4. 同じマスに書き直しても**行は増えない**（UPSERT）
  5. 人が決めた名前・階層は**辞書より強い**
  6. ⚠ いま立っているマスが分からないとメモを置かない（(0,0) に置いたりしない）
  7. 保存に失敗しても窓を閉じない（書いた文が消えるほうが痛い）
"""

from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.db.database import Database  # noqa: E402
from retroux.core.navigation.location_resolver import (  # noqa: E402
    LocationResolver,
)
from retroux.core.navigation.models import (  # noqa: E402
    LANDMARK_LABELS, LandmarkKind, Place,
)
from retroux.core.navigation.repository import NavigationRepository  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.ui.map_edit_dialog import (  # noqa: E402
    FLOOR_UNSET, MapEditDialog, NoteDialog,
)
from retroux.ui.map_window import MapWindow  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402

DATA = (pathlib.Path(__file__).resolve().parents[1]
        / "retroux" / "plugins" / "dq2" / "data")
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
    """`(view_model, repository)` を用意する。"""
    from retroux.core.navigation.floor_estimator import FloorEstimator

    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    repo = NavigationRepository(db, "HASH")
    resolver = LocationResolver.load(DATA)

    class Observer:
        pass

    Observer.repo = repo
    vm = ViewModel(
        Recorder(db, "HASH", events, tmp_path / "command.json"), db, "HASH",
        map_meta={}, navigation=Observer(), location_resolver=resolver,
        floor_estimator=FloorEstimator(repo, resolver.dictionary))
    return vm, repo


def at(x=3, y=4, map_id=MIDENHALL_B1):
    return Place(map_id, PTR, x, y)


# --- メモ -------------------------------------------------------------

def test_a_note_is_saved_and_read_back(bundle):
    vm, repo = bundle
    assert vm.set_note(at(), "右の階段は行き止まり")
    assert vm.note(at())["body"] == "右の階段は行き止まり"


def test_rewriting_a_note_does_not_add_a_row(bundle):
    """★同じマスに何度書いても行は増えない（UPSERT）。"""
    vm, repo = bundle
    vm.set_note(at(), "1回目")
    vm.set_note(at(), "2回目")
    assert vm.note(at())["body"] == "2回目"
    count = repo._conn.execute("SELECT COUNT(*) FROM MapNote").fetchone()[0]
    assert count == 1


def test_an_empty_note_is_deleted_not_stored(bundle):
    """⚠⚠ **中身の無いメモを残さない。** 地図に空のメモが並ぶ。"""
    vm, repo = bundle
    vm.set_note(at(), "いちど書く")
    vm.set_note(at(), "   ")
    assert vm.note(at()) is None
    count = repo._conn.execute("SELECT COUNT(*) FROM MapNote").fetchone()[0]
    assert count == 0


def test_a_note_is_trimmed_but_the_inside_is_left_alone(bundle):
    vm, _repo = bundle
    vm.set_note(at(), "  上と  下  \n")
    assert vm.note(at())["body"] == "上と  下"


def test_notes_are_listed_per_map_in_reading_order(bundle):
    vm, _repo = bundle
    vm.set_note(at(5, 1), "うしろ")
    vm.set_note(at(1, 1), "まえ")
    vm.set_note(at(1, 9, map_id=0x03), "別のマップ")
    bodies = [r["body"] for r in vm.notes(MIDENHALL_B1, PTR)]
    assert bodies == ["まえ", "うしろ"]


def test_set_note_returns_whether_it_was_new(bundle):
    _vm, repo = bundle
    assert repo.set_note(at(), "はじめて") is True
    assert repo.set_note(at(), "書き直し") is False


def test_a_note_on_a_different_pointer_is_a_different_place(bundle):
    """★同じ map_id でも階が違えば別の地図（データ位置も鍵）。"""
    vm, _repo = bundle
    vm.set_note(Place(MIDENHALL_B1, 0x8000, 1, 1), "1階ぶん")
    vm.set_note(Place(MIDENHALL_B1, 0x9000, 1, 1), "別の階")
    assert vm.note(Place(MIDENHALL_B1, 0x8000, 1, 1))["body"] == "1階ぶん"
    assert vm.note(Place(MIDENHALL_B1, 0x9000, 1, 1))["body"] == "別の階"


# --- 目印 -------------------------------------------------------------

def test_a_landmark_is_saved_with_its_kind(bundle):
    vm, _repo = bundle
    assert vm.set_landmark(at(), LandmarkKind.TREASURE, "鉄の槍")
    rows = vm.landmarks(MIDENHALL_B1, PTR)
    assert [(r["kind"], r["label"]) for r in rows] == [("treasure", "鉄の槍")]


def test_an_unreadable_kind_is_refused_not_rounded_to_other(bundle):
    """★★ **`other` に丸めない。** 綴り違いが静かに増えると絞れなくなる。"""
    vm, repo = bundle
    assert vm.set_landmark(at(), "たからばこ") is False
    assert vm.landmarks(MIDENHALL_B1, PTR) == []
    count = repo._conn.execute("SELECT COUNT(*) FROM MapLandmark").fetchone()[0]
    assert count == 0


def test_landmarks_can_be_filtered_by_kind(bundle):
    vm, _repo = bundle
    vm.set_landmark(at(1, 1), LandmarkKind.TREASURE)
    vm.set_landmark(at(2, 2), LandmarkKind.STAIRS)
    assert len(vm.landmarks(MIDENHALL_B1, PTR, LandmarkKind.TREASURE)) == 1
    assert len(vm.landmarks(MIDENHALL_B1, PTR)) == 2


def test_filtering_by_an_unreadable_kind_returns_nothing_not_everything(bundle):
    """⚠ 全件返すと「宝箱だけ探したのに全部出た」ことに気づけない。"""
    vm, _repo = bundle
    vm.set_landmark(at(1, 1), LandmarkKind.TREASURE)
    assert vm.landmarks(MIDENHALL_B1, PTR, "たからばこ") == []


def test_two_kinds_can_share_one_tile(bundle):
    """★階段と扉が同じマスにあることはある。種類まで鍵にしている。"""
    vm, _repo = bundle
    vm.set_landmark(at(), LandmarkKind.STAIRS)
    vm.set_landmark(at(), LandmarkKind.DOOR)
    assert len(vm.landmarks(MIDENHALL_B1, PTR)) == 2


def test_the_same_kind_on_the_same_tile_is_updated_not_duplicated(bundle):
    vm, repo = bundle
    vm.set_landmark(at(), LandmarkKind.TREASURE, "まえの名前")
    vm.set_landmark(at(), LandmarkKind.TREASURE, "あとの名前")
    rows = vm.landmarks(MIDENHALL_B1, PTR)
    assert len(rows) == 1
    assert rows[0]["label"] == "あとの名前"


def test_a_landmark_can_be_deleted(bundle):
    vm, _repo = bundle
    vm.set_landmark(at(), LandmarkKind.TREASURE)
    assert vm.delete_landmark(at(), LandmarkKind.TREASURE)
    assert vm.landmarks(MIDENHALL_B1, PTR) == []


def test_every_kind_has_a_japanese_label():
    """★英語の値をそのまま画面に出さない。"""
    assert set(LANDMARK_LABELS) == set(LandmarkKind)
    assert all(LANDMARK_LABELS[k] for k in LandmarkKind)


def test_landmark_kind_parse_returns_none_for_junk():
    assert LandmarkKind.parse("treasure") is LandmarkKind.TREASURE
    assert LandmarkKind.parse(LandmarkKind.SHOP) is LandmarkKind.SHOP
    assert LandmarkKind.parse("宝箱") is None
    assert LandmarkKind.parse(None) is None


# --- 人が決めた名前・階層 ---------------------------------------------

def test_a_manual_name_beats_the_dictionary(bundle):
    vm, _repo = bundle
    assert vm.map_label(MIDENHALL_B1, PTR) == "ローレシア B1 [$04]"
    assert vm.set_map_override(MIDENHALL_B1, PTR, display_name="ローレシアの地下牢")
    assert vm.map_label(MIDENHALL_B1, PTR) == "ローレシアの地下牢 B1 [$04]"


def test_clearing_the_manual_name_goes_back_to_the_dictionary(bundle):
    vm, _repo = bundle
    vm.set_map_override(MIDENHALL_B1, PTR, display_name="別の名前")
    assert vm.clear_map_override(MIDENHALL_B1, PTR)
    assert vm.map_label(MIDENHALL_B1, PTR) == "ローレシア B1 [$04]"


def test_a_manual_name_and_floor_are_saved_together(bundle):
    vm, _repo = bundle
    vm.set_map_override(MIDENHALL_B1, PTR, display_name="ここ", floor_index=-5)
    assert vm.map_label(MIDENHALL_B1, PTR) == "ここ B5 [$04]"
    assert vm.floor_of_map(MIDENHALL_B1, PTR).index == -5


def test_the_reason_note_survives_editing_the_name(bundle):
    """★なぜそう決めたかは窓で編集しないので**持ち越す**。"""
    vm, repo = bundle
    repo.set_floor_override(MIDENHALL_B1, PTR, -5, "B5", note="実際に数えた")
    vm.set_map_override(MIDENHALL_B1, PTR, display_name="ここ", floor_index=-5)
    assert repo.map_override(MIDENHALL_B1, PTR)["note"] == "実際に数えた"


def test_setting_only_the_name_clears_a_floor_the_person_removed(bundle):
    """★窓で階層を「指定しない」に戻したら、指定が**消える**こと。

    ⚠ 前の値を残すと、指定を取り消せないことになる。
    """
    vm, _repo = bundle
    vm.set_map_override(MIDENHALL_B1, PTR, floor_index=-5)
    vm.set_map_override(MIDENHALL_B1, PTR, display_name="ここ")
    got = vm.floor_of_map(MIDENHALL_B1, PTR)
    assert (got.index, got.source) == (-1, "binding"), "指定を取り消せていない"


def test_the_repository_keeps_missing_fields_when_asked(bundle):
    """★`keep_missing=True` は「渡さなかった項目は残す」。"""
    _vm, repo = bundle
    repo.set_map_override(MIDENHALL_B1, PTR, floor_index=-5, floor_label="B5")
    repo.set_map_override(MIDENHALL_B1, PTR, display_name="ここ")
    row = repo.map_override(MIDENHALL_B1, PTR)
    assert (row["floor_index"], row["display_name"]) == (-5, "ここ")


# --- 窓（メモ）--------------------------------------------------------

@pytest.fixture
def note_dialog(app, bundle):
    vm, repo = bundle
    dialog = NoteDialog(vm, at(), place_label="ローレシア B1（3, 4）")
    yield dialog, vm, repo
    dialog.close()


def test_the_note_dialog_loads_what_is_already_there(app, bundle):
    vm, _repo = bundle
    vm.set_note(at(), "前に書いた文")
    dialog = NoteDialog(vm, at())
    assert dialog._body.toPlainText() == "前に書いた文"
    dialog.close()


def test_saving_the_note_dialog_stores_the_text(note_dialog):
    dialog, vm, _repo = note_dialog
    dialog._body.setPlainText("階段は右奥")
    dialog._save()
    assert vm.note(at())["body"] == "階段は右奥"


def test_a_landmark_can_be_added_and_removed_from_the_dialog(note_dialog):
    dialog, vm, _repo = note_dialog
    dialog._kind.setCurrentIndex(
        dialog._kind.findData(LandmarkKind.TREASURE.value))
    dialog._label.setText("鉄の槍")
    dialog._add_landmark()
    assert dialog._marks.count() == 1
    assert "宝箱" in dialog._marks.item(0).text()

    dialog._marks.setCurrentRow(0)
    dialog._remove_landmark()
    assert dialog._marks.count() == 0
    assert vm.landmarks(MIDENHALL_B1, PTR) == []


def test_the_dialog_shows_an_unreadable_kind_so_it_can_be_deleted(app, bundle):
    """⚠ 読めない種類を**黙って隠さない**（隠すと消せなくなる）。"""
    vm, repo = bundle
    repo._conn.execute(
        "INSERT INTO MapLandmark (rom_hash, map_id, map_ptr, x, y, kind,"
        " source, confidence, created_at, updated_at)"
        " VALUES ('HASH', ?, ?, 3, 4, 'たからばこ', 'manual', 'confirmed',"
        " '2026-07-30', '2026-07-30')", (MIDENHALL_B1, PTR))
    repo.db._commit()
    dialog = NoteDialog(vm, at())
    assert dialog._marks.count() == 1
    assert "不明な種類" in dialog._marks.item(0).text()
    dialog.close()


def test_the_dialog_refuses_to_work_without_a_place(app, bundle):
    """⚠⚠ **場所が分からないまま (0,0) に置かない。**"""
    from PySide6.QtWidgets import QDialog

    vm, repo = bundle
    dialog = NoteDialog(vm, None)
    assert "場所が読めていない" in dialog._status.text()
    assert dialog._body.isReadOnly()
    assert not dialog._add.isEnabled()
    dialog._save()
    # ★保存しようとせず**そのまま閉じる**（できないことを試みない）。
    #   ⚠ 試みてから「保存できませんでした」と出すのは違う。
    #     場所が無いのは失敗ではなく、そもそも書ける状態ではない。
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert "保存できませんでした" not in dialog._status.text()
    count = repo._conn.execute("SELECT COUNT(*) FROM MapNote").fetchone()[0]
    assert count == 0
    dialog.close()


def test_the_dialog_stays_open_when_saving_fails(app, bundle):
    """★★ **書いた文が消えるほうが痛い。** 失敗しても閉じない。"""
    vm, _repo = bundle
    dialog = NoteDialog(vm, at())
    dialog._body.setPlainText("消えたら困る文")
    vm.navigation = None            # 記録を無効にする（保存できない状態）
    dialog._save()
    from PySide6.QtWidgets import QDialog
    assert dialog.result() != QDialog.DialogCode.Accepted, "閉じてしまっている"
    assert dialog._body.toPlainText() == "消えたら困る文"
    assert "保存できませんでした" in dialog._status.text()
    dialog.close()


# --- 窓（名前と階層）--------------------------------------------------

@pytest.fixture
def edit_dialog(app, bundle):
    vm, repo = bundle
    dialog = MapEditDialog(vm, MIDENHALL_B1, PTR)
    yield dialog, vm, repo
    dialog.close()


def test_the_edit_dialog_shows_what_is_being_used_now(edit_dialog):
    dialog, _vm, _repo = edit_dialog
    assert "ローレシア" in dialog._current.text()
    assert "B1" in dialog._current.text()


def test_the_edit_dialog_saves_a_name_and_a_floor(edit_dialog):
    dialog, vm, _repo = edit_dialog
    dialog._name.setText("ローレシアの地下牢")
    dialog._floor.setValue(-2)
    dialog._save()
    assert vm.map_label(MIDENHALL_B1, PTR) == "ローレシアの地下牢 B2 [$04]"


def test_zero_means_not_specified_because_there_is_no_floor_zero(edit_dialog):
    """★0 階は無いので、0 を「指定しない」に使っている。"""
    dialog, vm, _repo = edit_dialog
    dialog._floor.setValue(FLOOR_UNSET)
    dialog._save()
    got = vm.floor_of_map(MIDENHALL_B1, PTR)
    assert (got.index, got.source) == (-1, "binding")


def test_the_edit_dialog_explains_what_will_be_saved(edit_dialog):
    dialog, _vm, _repo = edit_dialog
    dialog._floor.setValue(-3)
    assert "B3" in dialog._floor_note.text()
    dialog._floor.setValue(FLOOR_UNSET)
    assert "指定しなければ" in dialog._floor_note.text()


def test_the_edit_dialog_can_take_back_the_manual_values(edit_dialog):
    dialog, vm, _repo = edit_dialog
    dialog._name.setText("別の名前")
    dialog._floor.setValue(-7)
    dialog._save()
    dialog._clear()
    assert dialog._name.text() == ""
    assert dialog._floor.value() == FLOOR_UNSET
    assert vm.map_label(MIDENHALL_B1, PTR) == "ローレシア B1 [$04]"


def test_the_edit_dialog_stays_open_when_saving_fails(app, bundle):
    vm, _repo = bundle
    dialog = MapEditDialog(vm, MIDENHALL_B1, PTR)
    dialog._name.setText("消えたら困る名前")
    vm.navigation = None
    dialog._save()
    assert dialog._name.text() == "消えたら困る名前"
    assert "保存できませんでした" in dialog._status.text()
    dialog.close()


# --- 地図の窓 ---------------------------------------------------------

@pytest.fixture
def window(app, bundle):
    vm, repo = bundle
    vm.db.mark_visited("HASH", MIDENHALL_B1, PTR, 3, 4)
    win = MapWindow(vm)
    win.show()
    app.processEvents()
    yield win, vm, repo
    win.close()


def test_the_window_says_there_are_no_marks_yet(window):
    """★★ 2026-08-09: メモは「あることだけ」画面に出します ★★

    > MAP内のテキストはツールチップに。

    ⚠ 無いときは**何も出しません**（1行ぶんの高さを地図へ回すため）。
    ★詳しい文言はツールチップに残っています。
    """
    win, _vm, _repo = window
    assert win._marks.text() == "", "無いときは何も出さない"
    assert "まだありません" in win._marks.toolTip()


def test_the_window_summarises_notes_and_landmarks(window):
    win, vm, _repo = window
    vm.set_note(at(3, 4), "ここに宝箱があった")
    vm.set_landmark(at(3, 4), LandmarkKind.TREASURE)
    vm.set_landmark(at(1, 1), LandmarkKind.TREASURE)
    win._draw(here=(3, 4))
    # ★あるときは印を出す（気づけるように）。⚠ 中身はツールチップ
    assert win._marks.text(), "メモ・目印があるのに何も出ていない"
    text = win._marks.toolTip()
    assert "宝箱×2" in text
    assert "メモ 1 件" in text
    assert "ここに宝箱があった" in text


def test_the_window_summary_shows_an_unreadable_kind(window):
    """⚠ 読めない種類を要約から**落とさない**（あることに気づけない）。"""
    win, _vm, repo = window
    repo._conn.execute(
        "INSERT INTO MapLandmark (rom_hash, map_id, map_ptr, x, y, kind,"
        " source, confidence, created_at, updated_at)"
        " VALUES ('HASH', ?, ?, 3, 4, 'たからばこ', 'manual', 'confirmed',"
        " '2026-07-30', '2026-07-30')", (MIDENHALL_B1, PTR))
    repo.db._commit()
    win._draw(here=(3, 4))
    assert "⚠不明" in win._marks.toolTip()


def test_the_window_shortens_a_long_note(window):
    win, vm, _repo = window
    vm.set_note(at(3, 4), "あ" * 60)
    win._draw(here=(3, 4))
    assert "…" in win._marks.toolTip()


def test_the_note_button_is_off_until_the_current_tile_is_known(window):
    """⚠ どのマスか分からないのにメモを置かせない。"""
    win, _vm, _repo = window
    win._draw(here=None)
    assert not win._note_button.isEnabled()
    win._draw(here=(3, 4))
    assert win._note_button.isEnabled()


def test_the_place_for_a_note_is_the_tile_you_are_standing_on(window):
    win, _vm, _repo = window
    win._draw(here=(7, 9))
    place = win._here_place()
    assert (place.map_id, place.map_ptr, place.x, place.y) == \
        (MIDENHALL_B1, PTR, 7, 9)


def test_the_window_shows_a_manual_name_in_the_list(window):
    win, vm, _repo = window
    vm.set_map_override(MIDENHALL_B1, PTR, display_name="ローレシアの地下牢")
    win.reload()
    labels = [win._list.item(i).text() for i in range(win._list.count())]
    assert any("ローレシアの地下牢" in t for t in labels)
