"""遭遇したら図鑑を出す（2026-07-27 / 依頼者の要望）。

> TASみたいに、モンスターに遭遇すると対象モンスターの図鑑が表示されるのを想定。
> モンスターと出会ったときのモンスター図鑑は、メイン画面に出したい。
> 敵モンスターパーティーは全部まとめて出したい。

★★ **メイン画面に出す**（2026-07-27 に方針変更）★★
  最初は別ウィンドウを自動で開く形にしたが、依頼者の指定でメイン画面へ移した。
  → **遭遇で窓が勝手に開くことは無くなった**（フォーカスの心配ごと消えた）。
    別ウィンドウは残るが「83体の一覧を見るもの」で、開くのはボタンだけ。

★守りたい契約:
  1. 戦闘に入ると、**メイン画面に出ている全種**の図鑑が出る
  2. **敵種が変わったときだけ**出し直す（0.5秒ごとに作り直さない）
  3. 戦闘が終わったら案内に戻る
  4. ⚠ **遭遇で別ウィンドウを開かない**（メインに出るので開く必要が無い）
  5. ただし**すでに開いている**別ウィンドウは追従する
  6. 戦闘の入口で DB を読み直さない（倍速の意味が無くなる）
"""

from __future__ import annotations

import os
import pathlib

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.bridge.state_reader import Enemy, EnemyGroup, GameState  # noqa: E402
from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.ui.main_window import MainWindow  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402

MAP_PATH = (pathlib.Path(__file__).resolve().parents[1]
            / "retroux" / "plugins" / "dq2" / "memory_map.yaml")

SLIME, HEALER, COBRA = 0x01, 0x06, 0x0C


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        created = QApplication([])
    except Exception as exc:                      # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")
    yield created


@pytest.fixture(scope="module")
def mm() -> dict:
    from conftest import load_memory_map_with_enemies  # ★敵の表は ROM 由来（RX-0090）
    return load_memory_map_with_enemies()


@pytest.fixture
def win(app, tmp_path, mm):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    vm = ViewModel(
        Recorder(db, "HASH", events, tmp_path / "command.json"), db, "HASH",
        monsters={int(k): str(v) for k, v in mm["monsters"].items()},
        monster_stats={int(k): v for k, v in mm["monster_stats"].items()},
        monster_behavior={int(k): v for k, v in mm["monster_behavior"].items()},
        monster_actions={int(k): str(v) for k, v in mm["monster_actions"].items()},
        action_rates={int(k): list(v) for k, v in mm["action_rates"].items()},
        items={int(k): str(v) for k, v in mm["items"].items()},
        art_dir=tmp_path / "art",
        art_rom_dir=tmp_path / "art-rom",
    )
    log = tmp_path / "retroux.log"
    log.write_text("12:00:00 テスト\n", encoding="utf-8")
    window = MainWindow(vm, interval_ms=10 ** 6, log_path=log)
    window.show()
    app.processEvents()
    yield window, app
    window.close()
    db.close()


def _battle(*ids: int) -> GameState:
    """その敵種で戦闘中の状態を作る（本番と同じ形）。"""
    return GameState(
        in_battle=True, fresh=True,
        enemy_groups=[EnemyGroup(id=i, count=1) for i in ids],
        enemies=[Enemy(index=n, id=i) for n, i in enumerate(ids)],
    )


def _field() -> GameState:
    return GameState(in_battle=False, fresh=True)


def _selected_id(book):
    rows = book._visible_rows()
    index = book._list.currentRow()
    return None if index < 0 or index >= len(rows) else rows[index].id


def _shown_species(window) -> list[str]:
    """メイン画面の図鑑に出ている種の見出し（見えている枠だけ）。"""
    return [b["head"].text() for b in window._encounter._blocks
            if b["frame"].isVisible()]


# --- 1. メイン画面に全種まとめて出る ----------------------------------


def test_encounter_shows_in_main_window(win):
    window, app = win
    window._track_encounter(_battle(SLIME))
    app.processEvents()

    shown = _shown_species(window)
    assert len(shown) == 1
    assert "スライム" in shown[0]
    # ★案内は消えること
    assert not window._encounter._idle.isVisible()
    # ★★ 2026-08-09: 凡例は**ツールチップへ**（依頼者の指示）★★
    #   ⚠ 下段は 132px しかなく、凡例1行が札の高さを削っていました。
    #   ★消してはいません。記号の意味は札に触れば読めます。
    from retroux.ui.encounter_panel import LEGEND_TEXT
    assert LEGEND_TEXT in window._encounter._blocks[0]["frame"].toolTip()


def test_all_species_shown_together(win):
    """★「全部まとめて出したい」。切り替えボタンではなく全種を並べる。"""
    window, app = win
    window._track_encounter(_battle(SLIME, HEALER, COBRA))
    app.processEvents()

    shown = _shown_species(window)
    assert len(shown) == 3, shown
    assert any("スライム" in s for s in shown)
    assert any("ホイミスライム" in s for s in shown)
    assert any("キングコブラ" in s for s in shown)


def test_duplicate_species_counted_once(win):
    """同じ種が3体でも枠は1つ（種の話なので）。"""
    window, app = win
    window._track_encounter(_battle(SLIME, SLIME, SLIME))
    app.processEvents()
    assert len(_shown_species(window)) == 1


def test_shows_rom_data_for_each_species(win):
    """各枠に HP・特徴・耐性・ドロップが出ること（空欄を作らない）。"""
    window, app = win
    window._track_encounter(_battle(HEALER))
    app.processEvents()
    block = window._encounter._blocks[0]

    assert "HP 25" in block["stats"].text()
    assert "賢さ1" in block["stats"].text()
    assert "ホイミ" in block["actions"].text()
    assert "88%" in block["actions"].text()
    # ★2026-08-09: 耐性はツールチップ、ドロップは画面に残す
    assert "耐性" in block["frame"].toolTip()
    assert "ドロップ" in block["resist"].text()
    for key in ("stats", "actions", "resist"):
        assert block[key].text().strip(), f"{key} が空"


def test_does_not_show_reroll_action(win):
    """★「選び直し」を表に出さないこと（アトラスは２回攻撃100%）。"""
    window, app = win
    window._track_encounter(_battle(0x4E))
    app.processEvents()
    text = window._encounter._blocks[0]["actions"].text()
    assert "２回攻撃" in text
    assert "選び直し" not in text


def test_says_does_not_drop(win):
    """★「落とさない」と書くこと（空欄にしない）。シドーは落とさない。"""
    window, app = win
    window._track_encounter(_battle(0x52))
    app.processEvents()
    assert "ドロップ なし" in window._encounter._blocks[0]["resist"].text()


# --- 2. 敵種が変わったときだけ ----------------------------------------


def test_same_battle_does_not_rebuild(win, monkeypatch):
    """★同じ戦闘のあいだは**出し直さない**こと（0.5秒ごとのちらつきを避ける）。

    ⚠ 「枠の widget が同じか」では**捕まえられなかった**（枠は使い回すので、
      毎回 update しても同じオブジェクトのまま）。
      **update_encounter が呼ばれた回数**を数えるのが正しい検査。
      壊しても緑だったことで気づいた（playbook #55）。
    """
    window, app = win
    calls = []
    real = window._encounter.update_encounter
    monkeypatch.setattr(window._encounter, "update_encounter",
                        lambda ids: calls.append(tuple(ids)) or real(ids))

    window._track_encounter(_battle(SLIME, HEALER))
    app.processEvents()
    assert len(calls) == 1, calls

    for _ in range(5):
        window._track_encounter(_battle(SLIME, HEALER))
        app.processEvents()
    assert len(calls) == 1, f"同じ戦闘で {len(calls)} 回出し直した"


def test_new_battle_replaces_species(win):
    window, app = win
    window._track_encounter(_battle(SLIME))
    app.processEvents()
    window._track_encounter(_field())
    app.processEvents()
    window._track_encounter(_battle(COBRA))
    app.processEvents()

    shown = _shown_species(window)
    assert len(shown) == 1
    assert "キングコブラ" in shown[0]


def test_defeated_species_stay_shown(win):
    """★★ 戦闘中に倒しても消えないこと ★★

    依頼者の指摘:
      > 敵を倒しちゃうと消えるのは渋い。

    原因は `enemy_groups` が**生き残りしか映さない**こと。
    倒すとその種が消えるので、種の集合が変わって出し直され、枠が消えていた。
    **戦闘終了だけを守っていて、戦闘途中の撃破を見落としていた。**

    → 「いま出ている敵」ではなく「**この戦闘で出会った敵**」を出す。
    """
    window, app = win
    window._track_encounter(_battle(SLIME, HEALER, COBRA))
    app.processEvents()
    assert len(_shown_species(window)) == 3

    # スライムとキングコブラを倒した（生き残りは ホイミスライム だけ）
    window._track_encounter(_battle(HEALER))
    app.processEvents()
    shown = _shown_species(window)
    assert len(shown) == 3, f"倒した敵が消えた: {shown}"

    # 最後の1体も倒した（グループが空になる瞬間）
    window._track_encounter(_battle())
    app.processEvents()
    assert len(_shown_species(window)) == 3, "全滅させたら消えた"


def test_summoned_species_are_added(win):
    """「仲間を呼ぶ」で増えた種は足すこと（0x1C の行動）。

    ★減らさないだけでなく、**増えたぶんは足す**。
    """
    window, app = win
    window._track_encounter(_battle(SLIME))
    app.processEvents()
    assert len(_shown_species(window)) == 1

    window._track_encounter(_battle(SLIME, HEALER))
    app.processEvents()
    shown = _shown_species(window)
    assert len(shown) == 2, shown
    assert any("ホイミスライム" in s for s in shown)


def test_next_battle_starts_from_scratch(win):
    """★次の戦闘では**初期化して**その敵だけにすること（依頼者の指定）。

    > 次の戦いで初期化して表示する形が良いかと思う
    """
    window, app = win
    window._track_encounter(_battle(SLIME, HEALER, COBRA))
    app.processEvents()
    assert len(_shown_species(window)) == 3

    window._track_encounter(_field())
    app.processEvents()
    assert len(_shown_species(window)) == 3, "戦闘が終わったら消えた"

    window._track_encounter(_battle(0x30))       # 次の戦闘
    app.processEvents()
    shown = _shown_species(window)
    assert len(shown) == 1, f"前の戦闘の敵が残っている: {shown}"
    assert "メタルスライム" in shown[0]


def test_groups_not_readable_at_first_frame(win):
    """★戦闘の最初の数フレームでグループが読めなくても取りこぼさないこと。

    足すだけの作りなので、読めた時点で入る。
    """
    window, app = win
    window._track_encounter(_battle())          # まだ読めていない
    app.processEvents()
    assert _shown_species(window) == []

    window._track_encounter(_battle(SLIME, HEALER))
    app.processEvents()
    assert len(_shown_species(window)) == 2


# --- 3. ★戦闘が終わっても次の戦闘まで残す ----------------------------
#
# 依頼者の指摘:
#   > オート戦闘だとすぐ消えちゃうので、次の戦闘まで残すようにしてもらえる？
#
# ★倍速（約35倍）だと戦闘が一瞬で終わり、**読む前に消えていた**。


def test_battle_end_keeps_the_display(win):
    """★これが元の不具合。戦闘が終わっても消えないこと。"""
    window, app = win
    window._track_encounter(_battle(SLIME, HEALER))
    app.processEvents()
    before = _shown_species(window)

    window._track_encounter(_field())
    app.processEvents()

    assert _shown_species(window) == before, "戦闘が終わったら消えた"
    assert not window._encounter._idle.isVisible(), "案内文に戻ってしまった"
    from retroux.ui.encounter_panel import LEGEND_TEXT
    assert LEGEND_TEXT in window._encounter._blocks[0]["frame"].toolTip(), \
        "凡例が消えた"


def test_still_shown_after_many_field_updates(win):
    """フィールドを歩いている間ずっと残ること（0.5秒ごとの更新で消えない）。"""
    window, app = win
    window._track_encounter(_battle(COBRA))
    app.processEvents()
    for _ in range(10):
        window._track_encounter(_field())
        app.processEvents()
    shown = _shown_species(window)
    assert len(shown) == 1 and "キングコブラ" in shown[0]


def test_marks_whether_it_is_the_current_battle(win):
    """⚠ **残すなら「いつのものか」を書く。**

    書かないと、フィールドを歩いている最中の表示を
    「いま戦っている敵」と読み違える。
    """
    window, app = win
    window._track_encounter(_battle(SLIME))
    app.processEvents()
    # ★★ 2026-08-09: 「いつの戦闘か」は**札のツールチップへ**★★
    #   ⚠ 依頼者の指示で行としては消しました（下段が 132px しかないため）。
    #   ⚠⚠ ただし 2026-07-27 の経緯どおり、**情報は残します**。
    #     書かないと、歩いている最中の表示を「いま戦っている敵」と
    #     読み違えます。★触れば分かる場所には必ず置きます。
    tip = window._encounter._blocks[0]["frame"].toolTip()
    assert "いま戦っている" in tip, tip

    window._track_encounter(_field())
    app.processEvents()
    tip = window._encounter._blocks[0]["frame"].toolTip()
    assert "直前" in tip, tip


def test_next_battle_marks_current_again(win):
    """次の戦闘に入ったら「いま戦っている」に戻ること。"""
    window, app = win
    window._track_encounter(_battle(SLIME))
    app.processEvents()
    window._track_encounter(_field())
    app.processEvents()
    window._track_encounter(_battle(COBRA))
    app.processEvents()
    assert "いま戦っている" in window._encounter._when.text()


def test_nothing_is_marked_before_any_battle(win):
    """★一度も戦っていないときは何も書かない（案内文と二重にならない）。"""
    window, app = win
    window._track_encounter(_field())
    app.processEvents()
    assert not window._encounter._when.isVisible()
    assert window._encounter._idle.isVisible()


# --- 4〜5. 別ウィンドウとの関係 ---------------------------------------


def test_encounter_does_not_open_the_separate_window(win):
    """★遭遇で別ウィンドウを開かないこと（メインに出るので不要）。

    ⚠ 勝手に窓が飛び出すと、フォーカスや並びを乱す。
      最初はこれをやっていたが、メイン表示に移したので必要が無くなった。
    """
    window, app = win
    window._track_encounter(_battle(SLIME))
    app.processEvents()
    assert window._book_window is None, "遭遇で別ウィンドウが開いた"


def test_open_separate_window_follows_the_encounter(win):
    """★すでに開いている別ウィンドウは追従すること。"""
    window, app = win
    book = window._ensure_book_window()
    book.show()
    app.processEvents()

    window._track_encounter(_battle(COBRA))
    app.processEvents()
    assert _selected_id(book) == COBRA
    assert book._encounter_bar.isVisible()


def test_open_window_clears_filter_that_would_hide_the_monster(win):
    """★開いている窓が追従するとき、絞り込みで隠れていたら解くこと。

    「遭遇済みだけ」を入れた状態で初めて会った敵に遭遇すると一覧に居ない。
    追従は明示的な要求なので、そのときは絞り込みを解く。
    """
    window, app = win
    book = window._ensure_book_window()
    book.show()
    book._known_only.setChecked(True)      # 記録が無いので0体になる
    app.processEvents()
    assert book._list.count() == 0

    window._track_encounter(_battle(SLIME))
    app.processEvents()
    assert not book._known_only.isChecked(), "絞り込みが解かれていない"
    assert _selected_id(book) == SLIME


def test_open_window_clears_search_that_would_hide_the_monster(win):
    window, app = win
    book = window._ensure_book_window()
    book.show()
    book._search.setText("zzzz-該当なし")
    app.processEvents()
    assert book._list.count() == 0

    window._track_encounter(_battle(HEALER))
    app.processEvents()
    assert book._search.text() == "", "検索語が消されていない"
    assert _selected_id(book) == HEALER


def test_closed_separate_window_is_not_touched(win):
    """閉じている別ウィンドウは開かないこと。"""
    window, app = win
    book = window._ensure_book_window()   # 作るだけ（show しない）
    window._track_encounter(_battle(SLIME))
    app.processEvents()
    assert not book.isVisible(), "閉じている窓が開かれた"


def test_open_window_keeps_the_bar_after_battle(win):
    """★開いている窓の帯も**消さない**（言葉だけ変える）。

    倍速だと戦闘が一瞬で終わるので、消すと読む前に消える。
    """
    window, app = win
    book = window._ensure_book_window()
    book.show()
    window._track_encounter(_battle(SLIME))
    app.processEvents()
    assert book._encounter_bar.isVisible()
    assert "遭遇中" in book._encounter_label.text()

    window._track_encounter(_field())
    app.processEvents()
    assert book._encounter_bar.isVisible(), "帯が消えた"
    assert "直前" in book._encounter_label.text(), book._encounter_label.text()
    assert book.isVisible(), "窓が閉じられた（見ている途中かもしれない）"
    assert _selected_id(book) == SLIME, "選択まで消された"


def test_button_still_takes_focus(win, monkeypatch):
    """★ボタンで開いたときは前に出ること（自分で押したのだから）。"""
    window, app = win
    book = window._ensure_book_window()
    called = []
    monkeypatch.setattr(book, "raise_", lambda: called.append("raise"))
    monkeypatch.setattr(book, "activateWindow",
                        lambda: called.append("activate"))

    window._open_monster_book()
    app.processEvents()
    assert "raise" in called and "activate" in called


def test_separate_window_still_does_not_steal_focus(win):
    """窓側の `WA_ShowWithoutActivating` は残しておくこと（保険）。"""
    window, _ = win
    book = window._ensure_book_window()
    assert book.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


# --- 6. 戦闘の入口で DB を読み直さない --------------------------------


def test_does_not_query_db_on_encounter(win, monkeypatch):
    """★戦闘の入口で図鑑を引き直さないこと。

    全戦闘を走査するので、そこで 0.5 秒止まると倍速の意味が無くなる。
    行は起動時に一度だけ渡してある。
    """
    window, app = win
    calls = []
    monkeypatch.setattr(window.vm, "monster_book",
                        lambda *a, **k: calls.append(1) or [])

    window._track_encounter(_battle(SLIME))
    app.processEvents()
    assert calls == [], "戦闘の入口で DB を引いた"


# --- 保険: 壊れた状態で落ちない ---------------------------------------


def test_unknown_monster_id_does_not_crash(win):
    """図鑑に無いIDでも落ちず、**データが無いと書く**こと。"""
    window, app = win
    window._track_encounter(_battle(0xFE))
    app.processEvents()
    shown = _shown_species(window)
    assert len(shown) == 1
    assert "ROM データがありません" in window._encounter._blocks[0]["stats"].text()


def test_battle_without_groups_falls_back_to_instances(win):
    """グループがまだ読めていないときは個体から拾うこと（保険）。"""
    window, app = win
    state = GameState(in_battle=True, fresh=True, enemy_groups=[],
                      enemies=[Enemy(index=0, id=HEALER)])
    window._track_encounter(state)
    app.processEvents()
    assert any("ホイミスライム" in s for s in _shown_species(window))


def test_more_species_than_the_limit_is_capped(win):
    """上限を超える種が来ても画面が伸び続けないこと。"""
    from retroux.ui.encounter_panel import MAX_SPECIES

    window, app = win
    window._track_encounter(_battle(0x01, 0x02, 0x03, 0x04, 0x05, 0x06))
    app.processEvents()
    assert len(_shown_species(window)) == MAX_SPECIES


# --- 8. 敵の絵をメイン画面に出す（2026-07-29）-------------------------


def _put_art(directory, name: str, color: int) -> None:
    from PySide6.QtGui import QImage

    directory.mkdir(parents=True, exist_ok=True)
    image = QImage(24, 16, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(str(directory / name))


def _art_labels(window) -> list:
    return [b["art"] for b in window._encounter._blocks
            if b["frame"].isVisible()]


def test_encounter_shows_the_picture(win, tmp_path):
    """★出会った敵の絵をメイン画面に出すこと。"""
    window, app = win
    _put_art(tmp_path / "art-rom", "01.png", 0x00FF00)
    window._track_encounter(_battle(0x01))
    app.processEvents()
    labels = _art_labels(window)
    assert len(labels) == 1
    assert not labels[0].pixmap().isNull(), "絵があるのに出ていない"
    assert labels[0].text() == ""


def test_encounter_says_when_there_is_no_picture(win):
    """⚠ 絵が無いときは**そう書く**。空欄にすると壊れて見える。"""
    window, app = win
    window._track_encounter(_battle(0x01))
    app.processEvents()
    labels = _art_labels(window)
    assert labels[0].text() == "絵なし"
    assert labels[0].pixmap().isNull()


def test_encounter_picture_is_small_enough_for_the_narrow_panel(win, tmp_path):
    """★このパネルは幅が狭い。絵で3行の情報を押し出さないこと。"""
    from retroux.ui.encounter_panel import ART_H, ART_W

    window, app = win
    _put_art(tmp_path / "art-rom", "01.png", 0x00FF00)
    window._track_encounter(_battle(0x01))
    app.processEvents()
    label = _art_labels(window)[0]
    assert label.width() == ART_W and label.height() == ART_H
    pix = label.pixmap()
    assert pix.width() <= ART_W and pix.height() <= ART_H


def test_encounter_picture_follows_the_species(win, tmp_path):
    """★次の戦闘で絵も入れ替わること（前の敵の絵が残らない）。"""
    window, app = win
    _put_art(tmp_path / "art-rom", "01.png", 0x00FF00)
    window._track_encounter(_battle(0x01))
    app.processEvents()
    assert not _art_labels(window)[0].pixmap().isNull()

    window._track_encounter(_field())
    window._track_encounter(_battle(0x02))     # 絵を用意していない敵
    app.processEvents()
    assert _art_labels(window)[0].text() == "絵なし", "前の敵の絵が残っている"


def test_broken_picture_does_not_break_the_panel(win, tmp_path):
    """⚠ 表示のための処理で本体を止めない（playbook の原則10）。"""
    window, app = win
    (tmp_path / "art-rom").mkdir(parents=True, exist_ok=True)
    (tmp_path / "art-rom" / "01.png").write_bytes(b"not a png at all")
    window._track_encounter(_battle(0x01))
    app.processEvents()
    assert _art_labels(window)[0].text() == "読めず"
    assert _shown_species(window), "パネルごと落ちている"


# --- 9. ★倍速で戦闘まるごと1回を見逃しても切り替わる（2026-07-29）-------
#
# 依頼者の指摘:
#   > 偶に出会った敵で切り替わらない場合がある。オート戦闘だからタイミング障害かも
#
# 原因: この画面は 0.5 秒ごとに state.json を見る。倍速（約35倍）だと
#       戦闘の始まりから終わりまでが 0.5 秒に収まり、`in_battle=True` を
#       **一度も見ないまま**次のフィールドになることがある。


def _field_after(seq: int, *ids: int) -> GameState:
    """戦闘が終わったあとのフィールド。★Lua は番号と種を持ち続ける。"""
    return GameState(in_battle=False, fresh=True,
                     battle_seq=seq, battle_species=list(ids))


def test_switches_even_if_the_battle_was_never_seen(win):
    """★★ これが本命。**戦闘中を一度も見なくても**切り替わること。"""
    window, app = win
    window._track_encounter(_battle(SLIME))
    app.processEvents()

    # 倍速で戦闘が丸ごと過ぎ、次に見たときはもうフィールド
    window._track_encounter(_field_after(2, COBRA))
    app.processEvents()
    shown = _shown_species(window)
    assert len(shown) == 1, shown
    assert "キングコブラ" in shown[0], "見逃した戦闘で切り替わっていない"


def test_same_battle_number_does_not_rebuild(win, monkeypatch):
    """★同じ番号のあいだは出し直さない（ちらつかせない）。"""
    window, app = win
    calls = []
    real = window._encounter.update_encounter
    monkeypatch.setattr(window._encounter, "update_encounter",
                        lambda ids: calls.append(tuple(ids)) or real(ids))

    for _ in range(5):
        window._track_encounter(_field_after(3, SLIME, HEALER))
        app.processEvents()
    assert len(calls) == 1, f"同じ番号で {len(calls)} 回出し直した"


def test_battle_number_survives_several_missed_battles(win):
    """★続けて見逃しても、最後の戦闘の敵が出ること。"""
    window, app = win
    for seq, mid in ((1, SLIME), (2, HEALER), (3, COBRA)):
        window._track_encounter(_field_after(seq, mid))
        app.processEvents()
    assert "キングコブラ" in _shown_species(window)[0]


def test_empty_species_does_not_blank_the_panel(win):
    """⚠ 種が空の番号（読めなかった戦闘）で、前の表示を消さないこと。"""
    window, app = win
    window._track_encounter(_field_after(1, SLIME))
    app.processEvents()
    window._track_encounter(_field_after(2))          # 種が読めていない
    app.processEvents()
    assert _shown_species(window), "空の番号で表示を消してしまった"


def test_works_without_the_battle_number(win):
    """★番号が来ない古い FCEUX 側でも、これまでどおり動くこと。"""
    window, app = win
    window._track_encounter(_battle(SLIME))
    app.processEvents()
    window._track_encounter(_field())
    window._track_encounter(_battle(COBRA))
    app.processEvents()
    assert "キングコブラ" in _shown_species(window)[0]
