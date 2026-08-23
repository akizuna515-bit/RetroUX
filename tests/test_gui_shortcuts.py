"""修飾キー付きのショートカットに、画面側の受け口があること（RX-0102 / 2026-08-23）。

⚠⚠ **これが無くて、公開版で3つのキーが死んでいました。**

    Ctrl+Shift+R  標準レイアウトに戻す
    Ctrl+K        キー割り当ての設定
    Ctrl+Shift+L  Lua ウィンドウを出す

  README は効くと案内し、アクションの実装も登録済み。⚠ なのに**呼ぶ人が居ない**。
  単独キーは Lua が拾いますが、修飾キー付きは Lua へ渡していないためです。

★ここでは **実際に鳴らして**、アクションが動くところまで見ます。
  ⚠ 「登録されているか」だけの検査は、今回それで**押しても無反応のまま緑**でした。
"""

from __future__ import annotations

import pytest

from retroux.core import keybindings as kb
from retroux.ui import shortcuts as shortcuts_mod


def _bindings(mapping: dict):
    return kb.Keybindings(keys={k: list(v) for k, v in mapping.items()})


# --- 選び方（Qt が無くても確かめられる部分）---------------------------

def test_修飾キー付きだけを画面が受ける():
    """★単独キーは **Lua の担当**。⚠ 両方で拾うと二重に実行される。"""
    got = shortcuts_mod.gui_pairs(
        _bindings({"reset_layout": ["Ctrl+Shift+R"],
                   "toggle_auto": ["A"],
                   "open_map": ["G"]}),
        registered={"reset_layout", "toggle_auto", "open_map"})
    assert got == [("reset_layout", "Ctrl+Shift+R")]


def test_実装の無いアクションには作らない():
    """⚠ 受け口だけ作ると「押しても無反応」になる。★それが一番困る。"""
    got = shortcuts_mod.gui_pairs(
        _bindings({"reset_layout": ["Ctrl+Shift+R"]}), registered=set())
    assert got == []


def test_同じアクションに複数の割り当てがあれば全部受ける():
    got = shortcuts_mod.gui_pairs(
        _bindings({"open_keybinding_settings": ["Ctrl+K", "Ctrl+Alt+K", "F9"]}),
        registered={"open_keybinding_settings"})
    assert got == [("open_keybinding_settings", "Ctrl+K"),
                   ("open_keybinding_settings", "Ctrl+Alt+K")]


def test_同梱の既定に3つとも入っている():
    """★README が案内している3つが、既定の割り当てに実在すること。

    ⚠ ここが空でも上の検査は緑になる（作り方は正しいので）。
      ★「案内している物が本当にある」は別に見る。
    """
    bound = kb.load()
    for action, key in (("reset_layout", "Ctrl+Shift+R"),
                        ("open_keybinding_settings", "Ctrl+K"),
                        ("show_lua_window", "Ctrl+Shift+L")):
        assert key in bound.keys_for(action), (action, bound.keys_for(action))


# --- 実際に鳴らす ------------------------------------------------------

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtCore import Qt                       # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        created = QApplication([])
    except Exception as exc:                          # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")
    yield created


def test_鳴らすとアクションが実行される(app):
    """★★ **ここが要**。⚠ 「作った」で終わらせない。 ★★"""
    called = []
    widget = QWidget()
    made = shortcuts_mod.install(
        widget, _bindings({"reset_layout": ["Ctrl+Shift+R"]}),
        {"reset_layout"}, called.append)

    assert len(made) == 1
    made[0].activated.emit()
    assert called == ["reset_layout"]


def test_どの窓を触っていても効く(app):
    """⚠ 窓ごとの受け口だと「地図を触っているときだけ効かない」になる。

    ★いちばん困るのは「たまに効く」なので、アプリ全体で受ける。
    """
    widget = QWidget()
    made = shortcuts_mod.install(
        widget, _bindings({"reset_layout": ["Ctrl+Shift+R"]}),
        {"reset_layout"}, lambda _n: None)

    assert made[0].context() == Qt.ShortcutContext.ApplicationShortcut


def test_読めない表記は飛ばして理由を残す(app):
    """⚠ 黙って落とさない。★設定したのに効かない、を説明できるように。"""

    class _Log:
        def __init__(self):
            self.warnings = []

        def warning(self, fmt, *args):
            self.warnings.append(fmt % args)

    log = _Log()
    widget = QWidget()
    made = shortcuts_mod.install(
        widget, _bindings({"reset_layout": ["Ctrl+"]}),
        {"reset_layout"}, lambda _n: None, logger=log)

    assert made == []
    assert log.warnings and "reset_layout" in log.warnings[0]


def test_作り直しても二重にならない(app):
    """⚠⚠ 同じキーが2つあると Qt は **どちらも呼ばなくなる**（ambiguous）。

    ★割り当ての変更を反映するたびに作り直すので、ここは実際に踏む道。
    """
    called = []
    widget = QWidget()
    bound = _bindings({"reset_layout": ["Ctrl+Shift+R"]})

    made = shortcuts_mod.install(widget, bound, {"reset_layout"},
                                 called.append)
    shortcuts_mod.clear(made)
    made2 = shortcuts_mod.install(widget, bound, {"reset_layout"},
                                  called.append)

    alive = [c for c in widget.children() if c in made + made2]
    assert alive == made2, "★古い受け口が残っている"
    made2[0].activated.emit()
    assert called == ["reset_layout"]
