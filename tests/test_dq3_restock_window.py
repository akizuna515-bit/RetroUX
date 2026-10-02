"""補充の設定（RX3-0212 / RX3-0222 / RX3-0258）。★「アイテム」「保持数」の表 → 管理画面と［…］の窓で同じ置き場へ。

★RX3-0258（2026-09-14 依頼者「DQ3 管理画面UI見直し・リストック設定改修」）: ラジオのマトリクス → 表。
  約 5 行 / 6 件目からは表の中だけスクロール / 保持数 0〜9 / 0 = 対象外 / ⚠ 名前の自由入力は無い / 名前は ROM の道具辞書から。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                     # noqa: E402

pytest.importorskip("PySide6")

from dq3.knowledge import item_info as II          # noqa: E402

pytestmark = pytest.mark.skipif(not II.available(), reason="ROM が無い（★品の名前は ROM から）")


def _settings(tmp_path, text=None):
    from dq3.ui.ui_settings import UiSettings

    settings = UiSettings(tmp_path / "ui.json")
    if text is not None:
        settings.set("admin", "restock_wants", text)
    return settings


def _table(tmp_path, text=None):
    from PySide6.QtWidgets import QApplication

    from dq3.ui.restock_window import RestockTable

    QApplication.instance() or QApplication([])
    settings = _settings(tmp_path, text)
    return RestockTable(settings), settings


def _window(tmp_path, text=None):
    from PySide6.QtWidgets import QApplication

    from dq3.ui.restock_window import RestockWindow

    QApplication.instance() or QApplication([])
    settings = _settings(tmp_path, text)
    return RestockWindow(settings), settings


def _values(table) -> dict:
    return {k: table.value(k) for k in table.spins}


def test_既定の目標で開く(tmp_path):
    """★RX3-0482（2026-10-02 依頼者）: やくそう 3 / どくけしそう 1 / キメラのつばさ 1（★保存が無いとき / 他は 0）。"""
    table, _settings = _table(tmp_path)
    assert _values(table) == {101: 3, 102: 1, 104: 1, 108: 0, 103: 0, 116: 0, 115: 0, 86: 0}


def test_先頭5件の順_名前は道具辞書から(tmp_path):
    """★RX3-0258 §3: やくそう → どくけしそう → キメラのつばさ → まんげつそう → せいすい（★名前は ROM から）。"""
    from dq3.ui.restock_window import RESTOCK_ITEMS

    table, _settings = _table(tmp_path)
    names = [table.item(row, 0).text() for row in range(table.rowCount())]
    assert names[:5] == ["やくそう", "どくけしそう", "キメラのつばさ", "まんげつそう", "せいすい"], names
    assert names == [II.info(i).name for i in RESTOCK_ITEMS], "⚠ 名前を道具辞書から引いていない"
    assert [table.horizontalHeaderItem(c).text() for c in range(2)] == ["アイテム", "保持数"]


def test_約5行で_6件目からは表の中だけスクロール(tmp_path):
    from PySide6.QtWidgets import QApplication

    from dq3.ui.restock_window import VISIBLE_ROWS

    table, _settings = _table(tmp_path)
    assert table.rowCount() > VISIBLE_ROWS == 5
    assert table.height() == table.rows_height(5), "⚠ 表の高さが約 5 行でない"
    assert table.height() < table.rows_height(table.rowCount()), "⚠⚠ 表が全部の行ぶん伸びた（★画面全体が縦に伸びる）"
    table.show()
    QApplication.processEvents()
    bar = table.verticalScrollBar()
    assert bar.maximum() > 0, "⚠ 6 件目以降へ表の中でスクロールできない"
    # ⚠⚠ 数の欄も名前と一緒に動く（★2026-09-14 画面の外で撮った絵で、名前だけ動いて数が上の品のままに見えた）
    bar.setValue(bar.maximum())
    QApplication.processEvents()
    from dq3.ui.restock_window import RESTOCK_ITEMS

    last_row = len(RESTOCK_ITEMS) - 1
    cell = table.visualRect(table.model().index(last_row, 1))
    last = table.spins[RESTOCK_ITEMS[-1]]
    assert table.viewport().rect().contains(cell.center()), "⚠ 最後の品の行が見えていない"
    assert cell.contains(last.geometry().center()), "⚠⚠ スクロールしても数の欄が名前の行と一緒に動かない"
    first = table.spins[RESTOCK_ITEMS[0]]
    assert not table.viewport().rect().contains(first.geometry().center()), "⚠⚠ 上の品の数の欄が残っている"
    table.close()


def test_数を変えると同じ欄へ保存し_補充の計画が読む(tmp_path):
    from dq3.ui import town_bar as TB

    table, settings = _table(tmp_path)
    table.spins[103].setValue(3)                     # ★せいすい 3 個
    text = settings.get("admin", "restock_wants")
    assert "せいすい:3" in text and "やくそう:3" in text, text
    assert (103, 3) in TB.restock_wants(settings) and (101, 3) in TB.restock_wants(settings), \
        "⚠ 補充の計画が読む値と表の値がずれている"


def test_保持数0は対象外(tmp_path):
    from dq3.ui import town_bar as TB

    table, settings = _table(tmp_path)
    table.spins[101].setValue(0)
    assert "やくそう" not in settings.get("admin", "restock_wants")
    assert 101 not in dict(TB.restock_wants(settings)), "⚠⚠ 0 にしたのに買う"


def test_保存を開き直しても同じ数(tmp_path):
    from PySide6.QtWidgets import QApplication

    from dq3.ui.restock_window import RestockTable
    from dq3.ui.ui_settings import UiSettings

    table, _settings = _table(tmp_path)
    table.spins[108].setValue(4)
    again = RestockTable(UiSettings(tmp_path / "ui.json"))             # ★再起動したのと同じ（ファイルから読む）
    QApplication.processEvents()
    assert again.value(108) == 4 and again.value(101) == 3


def _other_item():
    """★表に並べていない道具を 1 つ（★名前は ROM から / ⚠ 決め打ちにすると表に足した日に素通りする）。"""
    from dq3.ui.restock_window import RESTOCK_ITEMS

    return next(II.info(i).name for i in range(100, 128)
                if i not in RESTOCK_ITEMS and II.info(i) is not None and II.info(i).name)


def test_表に無い品は出さないが残す(tmp_path):
    """★旧い文字の欄で足した品は表に出さない。⚠ ただし保存からは消さない（旧い設定の互換）。"""
    other = _other_item()
    table, settings = _table(tmp_path, "やくそう:6,%s:3" % other)
    names = [table.item(row, 0).text() for row in range(table.rowCount())]
    assert other not in names, "⚠ 表に無い品を出した"
    table.spins[102].setValue(1)
    text = settings.get("admin", "restock_wants")
    assert "%s:3" % other in text and "どくけしそう:1" in text, "⚠ 旧い設定の品を消した: %s" % text


def test_旧い設定の数はそのまま読む(tmp_path):
    """★RX3-0258 §5・§8: 旧い形（名前:数 の文字）をそのまま読む / 既存の値を優先（★旧い既定 キメラ 1 のまま）。"""
    table, _settings = _table(tmp_path, "やくそう:6,どくけしそう:2,キメラのつばさ:1")
    assert _values(table) == {101: 6, 102: 2, 104: 1, 108: 0, 103: 0, 116: 0, 115: 0, 86: 0}


def test_上限より多い数は触らなければ残す(tmp_path):
    table, settings = _table(tmp_path, "やくそう:12,どくけしそう:2")
    assert table.value(101) == 9, "★表の上では上限の 9"
    table.spins[102].setValue(3)
    assert "やくそう:12" in settings.get("admin", "restock_wants"), "⚠ 触っていない品の数を 9 に縮めた"


def test_全部0は既定に戻らない(tmp_path):
    from dq3.ui import town_bar as TB

    table, settings = _table(tmp_path)
    for spin in table.spins.values():
        spin.setValue(0)
    assert settings.get("admin", "restock_wants") == "なし"
    assert TB.restock_wants(settings) == [], "⚠⚠ 全部 0 にしたのに既定の目標で買う"


def test_既定に戻す(tmp_path):
    from dq3.ui import town_bar as TB
    from dq3.ui.restock_window import default_text

    win, settings = _window(tmp_path, "なし")
    assert _values(win.table)[101] == 0
    win.reset()
    assert settings.get("admin", "restock_wants") == default_text()
    assert TB.restock_wants(settings) == list(TB.DEFAULT_WANTS)
    # ★RX3-0482: 既定は やくそう 3・どくけしそう 1・キメラのつばさ 1（★まんげつそうは 0）
    assert _values(win.table) == {101: 3, 102: 1, 104: 1, 108: 0, 103: 0, 116: 0, 115: 0, 86: 0}


def test_数の欄は0から9で数字しか入らない(tmp_path):
    """★不正な字は入力できない（§4）。⚠ 画面に出していない欄へ `QTest.keyClicks` すると Python ごと落ちた → 欄の検証で見る。"""
    from PySide6.QtGui import QValidator

    from dq3.ui.restock_window import MAX_COUNT

    table, _settings = _table(tmp_path)
    spin = table.spins[102]
    assert (spin.minimum(), spin.maximum()) == (0, MAX_COUNT) == (0, 9)
    state = lambda text: spin.validate(text, 0)[0]            # noqa: E731
    assert state("5") == QValidator.State.Acceptable
    assert state("あ") == QValidator.State.Invalid and state("x") == QValidator.State.Invalid, "⚠⚠ 数字でない字が入る"
    assert state("-1") == QValidator.State.Invalid and state("12") == QValidator.State.Invalid, "⚠ 0〜9 の外が入る"
    assert spin.minimumWidth() >= 64, "⚠ 数の欄が狭すぎる"


def test_名前の自由入力もコンボも無い(tmp_path):
    from PySide6.QtWidgets import QComboBox, QLineEdit, QSpinBox

    win, _settings = _window(tmp_path)
    free = [e for e in win.findChildren(QLineEdit) if not isinstance(e.parentWidget(), QSpinBox)]
    assert not free and not win.findChildren(QComboBox), "⚠⚠ 名前を打つ欄が残っている"


def test_選んでいない数の欄のホイールは表のスクロールへ回す(tmp_path):
    """★§7: ホイールで画面全体が意図せず動かない / ⚠ スクロール中に触れただけで数が変わらない。"""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    table, settings = _table(tmp_path)
    spin = table.spins[101]
    event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    spin.wheelEvent(event)
    assert spin.value() == 3 and not event.isAccepted(), "⚠⚠ 選んでいない数の欄がホイールで変わった"


def test_窓も管理画面と同じ表で_1920x1080に収まる(tmp_path):
    from dq3.ui.restock_window import RestockTable

    win, _settings = _window(tmp_path)
    assert isinstance(win.table, RestockTable)
    hint = win.sizeHint()
    assert hint.height() <= 600 and hint.width() <= 1600, "⚠ 窓が大きすぎる: %s" % hint
