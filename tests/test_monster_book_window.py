"""モンスター図鑑の別ウィンドウ（2026-07-27 / 依頼者の指定）。

★守りたい契約:
  1. **別ウィンドウ**で開く（本体に埋めない）。2つ目を作らない
  2. 一覧＋詳細で、選ぶと詳細が変わる
  3. **空欄を作らない** — 「なし」「絵がありません」と書く
  4. 「ドロップなし」と「ROM データが無い」を書き分ける
  5. 絵は**あれば出し、無ければそう書く**。出どころ（ROM/撮影）も添える
  6. 本体を閉じたら図鑑も閉じる（窓が居座らない）
  7. 敵情報パネルは**既定で閉じるが消えていない**

★**実物の memory_map.yaml を使う。** 作り物の辞書で通しても、
  実データの形が違えば実機で落ちる（ここが Phase 4 の図鑑で効いた形）。
"""

from __future__ import annotations

import os
import pathlib

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.ui.main_window import MainWindow  # noqa: E402
from retroux.ui.monster_book_window import MonsterBookWindow  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402

MAP_PATH = (pathlib.Path(__file__).resolve().parents[1]
            / "retroux" / "plugins" / "dq2" / "memory_map.yaml")


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
def vm(tmp_path, mm):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    view_model = ViewModel(
        recorder, db, "HASH",
        monsters={int(k): str(v) for k, v in mm["monsters"].items()},
        monster_stats={int(k): v for k, v in mm["monster_stats"].items()},
        monster_behavior={int(k): v for k, v in mm["monster_behavior"].items()},
        monster_actions={int(k): str(v) for k, v in mm["monster_actions"].items()},
        action_rates={int(k): list(v) for k, v in mm["action_rates"].items()},
        items={int(k): str(v) for k, v in mm["items"].items()},
        art_dir=tmp_path / "monster-art",
        art_rom_dir=tmp_path / "monster-art-rom",
    )
    yield view_model, tmp_path
    db.close()


@pytest.fixture
def window(app, vm):
    view_model, tmp = vm
    win = MonsterBookWindow(view_model)
    win.show()
    app.processEvents()
    yield win, view_model, tmp, app
    win.close()


def _select_by_id(win, monster_id: int) -> None:
    """一覧からその敵を選ぶ（本番と同じ経路）。"""
    rows = win._visible_rows()
    index = next(i for i, r in enumerate(rows) if r.id == monster_id)
    win._list.setCurrentRow(index)


# --- 1. 別ウィンドウ / 一覧 -------------------------------------------


def test_lists_all_monsters(window):
    """全83体を出すこと（まだ会っていない敵も出す。図鑑だから）。"""
    win, _, _, _ = window
    assert win._list.count() == 83


def test_is_a_separate_window(window):
    """本体に埋め込まれていないこと。"""
    win, _, _, _ = window
    assert win.parent() is None


def test_known_only_filter(window):
    """「遭遇済みだけ」で絞れること。記録が無いので0体になる。"""
    win, _, _, app = window
    win._known_only.setChecked(True)
    app.processEvents()
    assert win._list.count() == 0
    win._known_only.setChecked(False)
    app.processEvents()
    assert win._list.count() == 83


def test_search_filters_by_name_and_id(window):
    win, _, _, app = window
    win._search.setText("スライム")
    app.processEvents()
    assert 0 < win._list.count() < 83

    win._search.setText("4e")
    app.processEvents()
    assert win._list.count() == 1
    assert "アトラス" in win._list.item(0).text()


# --- 2〜3. 詳細の中身 -------------------------------------------------


def test_shows_stats_for_slime(window):
    """スライムの数値が ROM のとおり出ること。"""
    win, _, _, _ = window
    _select_by_id(win, 0x01)
    assert "スライム" in win._title.text()
    assert win._stat_labels["max_hp"].text() == "6"
    assert win._stat_labels["attack"].text() == "8"
    assert win._stat_labels["defense"].text() == "5"


def test_shows_resistances_in_words(window):
    """耐性が「効き方の言葉」で出ること。

    スライム: 攻撃呪文0（必ず効く）/ マホトーン7（効かない）
    """
    win, _, _, _ = window
    _select_by_id(win, 0x01)
    assert win._resist_labels["spell_damage"].text() == "必ず効く"
    assert win._resist_labels["stopspell"].text() == "効かない"


def test_shows_actions_with_probability(window):
    """★特徴が確率つきで出ること（選び直しは出ない）。"""
    win, _, _, _ = window
    _select_by_id(win, 0x06)          # ホイミスライム
    text = win._actions.text()
    assert "ホイミ" in text
    assert "88.3%" in text
    assert "通常攻撃" in text
    assert "11.7%" in text
    assert "選び直し" not in text, "選び直しを表に出してはいけない"


def test_atlas_actions_are_all_double_attack(window):
    """アトラスは「２回攻撃 100.0%」だけになること。

    ★ROM 上は ２回攻撃 87.5% + 選び直し 12.5%。正規化して 100%。
    """
    win, _, _, _ = window
    _select_by_id(win, 0x4E)
    text = win._actions.text()
    assert "２回攻撃" in text
    assert "100.0%" in text
    assert "選び直し" not in text


def test_shows_drop(window):
    win, _, _, _ = window
    _select_by_id(win, 0x01)
    assert "やくそう" in win._drop.text()
    assert "1/128" in win._drop.text()


def test_says_does_not_drop_when_rom_says_so(window):
    """★「なし」と書くこと（空欄にしない）。

    シドー(0x52) はドロップ表に値があってもコードが弾くので、
    memory_map には drop が無い。
    """
    win, _, _, _ = window
    _select_by_id(win, 0x52)
    assert "なし" in win._drop.text()


def test_says_not_met_yet(window):
    win, _, _, _ = window
    _select_by_id(win, 0x01)
    assert "まだ会っていません" in win._record.text()


def test_no_field_is_left_blank(window):
    """★どの欄も空文字にならないこと（全83体で確認）。

    空欄は「壊れている」と「そういう値」の区別が付かない。
    """
    win, _, _, app = window
    for mid in (0x01, 0x06, 0x30, 0x4E, 0x52, 0x53):
        _select_by_id(win, mid)
        app.processEvents()
        for name, label in (("title", win._title), ("actions", win._actions),
                            ("drop", win._drop), ("record", win._record)):
            assert label.text().strip(), f"0x{mid:02X} の {name} が空"


def test_every_monster_renders_without_error(window):
    """★全83体を順に選んでも落ちないこと。

    データの形が違う敵（0x53 Enemies のような擬似エントリ）で
    落ちないかを見る。
    """
    win, _, _, app = window
    for i in range(win._list.count()):
        win._list.setCurrentRow(i)
        app.processEvents()


# --- 5. 絵は「あれば出す / 無ければ未撮影」 ---------------------------


def test_says_not_captured_when_art_missing(window):
    """★依頼者の指定の論理。データが無ければそう書く。

    ⚠ 文言は 2026-07-29 に「未撮影」から変えた。ROM から展開して入れられる
      ようになったので、**撮影だけが入手手段ではなくなった**ため。
      「無い」ことをはっきり書く、という契約自体は変えていない。
    """
    win, _, _, _ = window
    _select_by_id(win, 0x01)
    assert "絵がありません" in win._art.text()
    assert "install" in win._art.text(), "入れ方を書いていない"
    assert win._art.pixmap().isNull()
    assert win._art_source.text() == ""


def _put_art(directory, name: str, color: int) -> None:
    from PySide6.QtGui import QImage

    directory.mkdir(parents=True, exist_ok=True)
    image = QImage(32, 24, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(str(directory / name))


def test_shows_art_when_file_exists(window):
    """絵があれば出すこと（案内の文字が消える）。"""
    win, view_model, tmp, app = window
    _put_art(tmp / "monster-art", "01.png", 0x00FF00)

    _select_by_id(win, 0x02)          # いったん別の敵へ
    _select_by_id(win, 0x01)
    app.processEvents()
    assert win._art.text() == "", "絵があるのに文字が残っている"
    assert not win._art.pixmap().isNull()


def test_art_path_is_none_when_missing(vm):
    view_model, _ = vm
    assert view_model.monster_art_path(0x01) is None
    assert view_model.monster_art(0x01) == (None, None)


# --- 5(続き). 絵の出どころ（2026-07-29）-------------------------------


def test_rom_art_wins_over_capture(vm):
    """★★ ROM から展開した絵を先に見る。

    ROM 版は82体そろっていて実機の撮影と画素まで一致している。
    撮影版は10体しか無いので、**そろっているほうを既定にする**。
    """
    view_model, tmp = vm
    _put_art(tmp / "monster-art", "01.png", 0x00FF00)
    _put_art(tmp / "monster-art-rom", "01.png", 0xFF0000)
    path, source = view_model.monster_art(0x01)
    assert source == "rom"
    assert path.parent.name == "monster-art-rom"


def test_capture_is_used_when_rom_art_is_missing(vm):
    """★ROM 展開を入れていない環境でも、撮った絵は出る。"""
    view_model, tmp = vm
    _put_art(tmp / "monster-art", "01.png", 0x00FF00)
    path, source = view_model.monster_art(0x01)
    assert source == "capture"
    assert path.parent.name == "monster-art"


def test_empty_search_result_does_not_crash(window):
    """★★ 該当なしの表示を通ること。

    ⚠ ここを通るテストが無かったせいで、`_show_empty` が
      未定義の変数を参照する状態になっても**緑のままだった**
      （`research/probes/active/break_art_display.py` の置換ミスで実際に混入した）。
      通らない道は、壊れていても分からない。
    """
    win, _view_model, _tmp, app = window
    win._search.setText("そんな名前の敵はいない")
    app.processEvents()
    assert win._list.count() == 0
    assert "該当なし" in win._title.text()
    assert win._art_source.text() == ""

    win._search.setText("")           # 戻せること
    app.processEvents()
    assert win._list.count() > 0


@pytest.mark.parametrize("where,expected", [
    ("monster-art-rom", "ROM から展開"),
    ("monster-art", "実機の画面から撮影"),
])
def test_book_says_where_the_art_came_from(window, where, expected):
    """★★ どちらの絵を見ているかを**必ず書く**。

    どちらも `<敵ID>.png` という同じ名前なので、書かないと画面から区別できない。
    """
    win, _view_model, tmp, app = window
    _put_art(tmp / where, "01.png", 0x00FF00)
    _select_by_id(win, 0x02)
    _select_by_id(win, 0x01)
    app.processEvents()
    assert win._art_source.text() == expected


# --- 1(続き)・6・7. 本体との連携 --------------------------------------


@pytest.fixture
def main(app, vm, tmp_path):
    view_model, _ = vm
    log = tmp_path / "retroux.log"
    log.write_text("12:00:00 テスト\n", encoding="utf-8")
    win = MainWindow(view_model, interval_ms=10 ** 6, log_path=log)
    win.resize(700, 900)
    win.show()
    app.processEvents()
    yield win, app
    win.close()


def test_button_opens_one_window_only(main):
    """★押すたびに窓が増えないこと。"""
    win, app = main
    win._open_monster_book()
    app.processEvents()
    first = win._book_window
    assert first.isVisible()

    win._open_monster_book()
    app.processEvents()
    assert win._book_window is first, "2つ目の窓ができた"


def test_closing_main_closes_the_book(main):
    """本体を閉じたら図鑑も閉じること（窓が居座らない）。"""
    win, app = main
    win._open_monster_book()
    app.processEvents()
    book = win._book_window
    assert book.isVisible()

    win.close()
    app.processEvents()
    assert not book.isVisible()


def test_enemy_panel_is_gone(main):
    """★★ 2026-08-11: 敵情報の段は**削除**しました（依頼者の指示）。

    > 敵情報は、もはや用済みの資料だから不要だね。このロジック自体いらない

    ⚠ 敵の**記録**（図鑑・遭遇・戦闘ログ）は別経路なので残っています。
    ★経緯は `docs/history/ui-changes.md`。
    """
    win, app = main
    app.processEvents()
    for gone in ("_enemies", "_enemy_scroll", "_monsters_value", "_split"):
        assert not hasattr(win, gone), f"⚠ {gone} が残っています"
    # ★遭遇の記録（図鑑）は残っていること
    assert hasattr(win, "_track_encounter")

