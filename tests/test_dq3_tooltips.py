"""選んでいない窓でもボタンの説明を出す（RX3-0345 / 2026-09-21）。

⚠⚠ 依頼者「ボタンにツールチップがでない（そこの窓がアクティブでないと効かない）」。

## ★Qt の決まり

```text
⚠ 既定        選ばれていない窓のツールチップは**出さない**
★直し方       WA_AlwaysShowToolTips
⚠⚠ 立てる先   **窓**（★ボタンに立てても効かない / Qt 文書 "it must be set on the window"）
```

## ⚠ なぜ効かなかったか

★RetroUX は窓が何枚も並び、⚠ ふだん選ばれているのは **FCEUX** です。
→ ★RetroUX の窓は「選ばれていない窓」なので、⚠ 説明が 1 つも出ませんでした。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _attr():
    from PySide6.QtCore import Qt

    return Qt.WidgetAttribute.WA_AlwaysShowToolTips


def test_あとから出した窓にも立つ():
    """★これが依頼者の症状（⚠ 窓を選んでいなくても説明が出る）。"""
    from PySide6.QtWidgets import QWidget

    from dq3.ui import app as A

    app = _app()
    watcher = A._show_tooltips_when_inactive(app)
    assert watcher is not None, "⚠ 見張りを返していない（★捨てられて効かなくなる）"

    w = QWidget()
    try:
        assert not w.testAttribute(_attr()), "⚠ 前提が崩れた（★はじめから立っている）"
        w.show()
        assert w.testAttribute(_attr()), (
            "⚠⚠ 窓に WA_AlwaysShowToolTips が立っていない（★選ばないと説明が出ないまま）")
    finally:
        w.close()
        w.deleteLater()


def test_もう出ている窓にも立つ():
    """⚠ 見張りを入れる**前**に作られた窓（★取り残さない）。"""
    from PySide6.QtWidgets import QWidget

    from dq3.ui import app as A

    app = _app()
    w = QWidget()
    try:
        w.show()
        w.setAttribute(_attr(), False)          # ⚠ わざと落としておく
        assert not w.testAttribute(_attr()), "⚠ 前提が崩れた"
        A._show_tooltips_when_inactive(app)
        assert w.testAttribute(_attr()), "⚠⚠ 先に出ていた窓が取り残された"
    finally:
        w.close()
        w.deleteLater()


def test_窓でない部品には立てない():
    """⚠ 中のボタンに立てても Qt は見ません（★無駄な印を増やさない）。"""
    from PySide6.QtWidgets import QPushButton, QWidget

    from dq3.ui import app as A

    app = _app()
    A._show_tooltips_when_inactive(app)
    parent = QWidget()
    try:
        button = QPushButton("あ", parent)
        button.setToolTip("説明")
        parent.show()
        assert parent.testAttribute(_attr()), "⚠ 窓に立っていない"
        assert not button.testAttribute(_attr()), (
            "⚠ 窓でない部品にまで立てた（★Qt はここを見ない / 印の意味がぼやける）")
    finally:
        parent.close()
        parent.deleteLater()


def test_本番の起動でも入れている():
    """⚠⚠ 「関数はあるが誰も呼んでいない」を防ぐ（★RX3-0121 の教訓）。"""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "dq3" / "ui" / "app.py"
    text = src.read_text(encoding="utf-8")
    body = text.split("def main(", 1)[1]
    assert "_show_tooltips_when_inactive(app)" in body, (
        "⚠⚠ 起動の道で呼んでいない（★検査だけ緑になる）")
