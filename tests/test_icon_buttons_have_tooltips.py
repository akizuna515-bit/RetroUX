"""アイコンだけのボタンには**必ず説明を付ける**（2026-08-09 / 依頼者の指示）。

    > アイコンのボタンには全部ツールチップで説明つけて

## ⚠⚠ なぜ守らないといけないか

  4区画（左・中・右・下）に収めるため、ボタンの文字をアイコン1文字へ
  縮めました。⚠ **文字が消えたぶん、何のボタンか分かる手がかりが
  ツールチップしかありません**。付け忘れると、押すまで分からない
  ボタンが並びます。

## ★ここで固定すること

  1. 表示が短い（記号・1文字）ボタンには `toolTip()` がある
  2. その1行目が**何のボタンか**を言っている（空行や記号で始まらない）
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


#: ★ここより短い表示なら「アイコンだけ」とみなす
SHORT = 2


def _icon_buttons(widget):
    from PySide6.QtWidgets import QPushButton

    out = []
    for button in widget.findChildren(QPushButton):
        text = (button.text() or "").strip()
        # ★短い文字のボタン、または**画像アイコンだけ**のボタン（RX-0071）。
        #   ⚠ アイコン化してテキストを空にしても、説明（ツールチップ）は要る。
        icon_only = (not text) and (not button.icon().isNull())
        if (text and len(text) <= SHORT) or icon_only:
            out.append(button)
    return out


def _check(widget, where: str) -> int:
    found = _icon_buttons(widget)
    for button in found:
        label = ((button.text() or "").strip()
                 or button.objectName() or "（画像アイコン）")
        tip = (button.toolTip() or "").strip()
        assert tip, f"{where}: アイコン「{label}」に説明が無い"
        first = tip.splitlines()[0].strip()
        assert len(first) >= 3, (
            f"{where}: アイコン「{label}」の1行目が短すぎます"
            f"（{first!r}）。★何のボタンかを書くこと")
    return len(found)


def test_the_main_window_icon_buttons_are_explained(qapp):
    """本体（右）のアイコン: 📖 🗺 ⚔ 💊 ⊞ A T ✕ 📄 📁 🩺"""
    from retroux.gui import build_view_model
    from retroux.ui.main_window import MainWindow

    vm, _db = build_view_model(read_only=True)
    window = MainWindow(vm, interval_ms=100000, heartbeat=None)
    try:
        count = _check(window, "本体")
        # ⚠ 1つも見つからないなら、テストが素通りしています
        assert count >= 8, f"アイコンのボタンが少なすぎます（{count}）"
    finally:
        window.close()


def test_the_map_window_icon_buttons_are_explained(qapp):
    """見た地図のアイコン: ✎（名前・階層）／📝（メモ）"""
    from retroux.gui import build_view_model
    from retroux.ui.map_window import MapWindow

    vm, _db = build_view_model(read_only=True)
    window = MapWindow(vm)
    try:
        assert _check(window, "見た地図") >= 2
    finally:
        window.close()


def test_the_toggle_buttons_say_whether_they_are_on(qapp):
    """⚠⚠ 入切のボタンは、**いま入っているか**も書くこと。

    ★アイコン1文字だと押し込みの見た目しか手がかりがありません。
      「押した結果は必ず画面に出す」と同じ考え方で、言葉でも伝えます。
    """
    from retroux.gui import build_view_model
    from retroux.ui.main_window import MainWindow

    vm, _db = build_view_model(read_only=True)
    window = MainWindow(vm, interval_ms=100000, heartbeat=None)
    try:
        for button, name in ((window._auto_button, "AUTO"),
                             (window._turbo_button, "高速化")):
            tip = button.toolTip()
            assert tip.startswith(f"{name}: "), tip
            assert ("入" in tip.splitlines()[0]
                    or "切" in tip.splitlines()[0]), tip
    finally:
        window.close()


def test_the_toggle_icons_survive_a_sync_from_the_emulator(qapp):
    """⚠⚠ **実機の値に合わせるときにアイコンを書き潰さない**（2026-08-11）。

    依頼者の画面で、ボタンが `TO (` `強化 (` のように見えていました。

    ★原因: `_sync_toggle()` が `setText("AUTO ON")` / `setText("高速化 OFF")`
      と書いており、ボタンは `setFixedWidth(38)`（アイコン1文字ぶん）なので
      **両端が切れて**いました。

    ⚠ 人が押す道（`_on_auto_toggled`）は、はじめからツールチップだけを
      直していました。★**合わせる道だけ**が古いままでした。

    ⚠ 上の `_check` は「表示が2文字以下」のボタンだけを見るので、
      文字が長くなったこのボタンは**検査の対象から外れて**いました
      （★だから緑のまま気づけなかった）。
    """
    from retroux.gui import build_view_model
    from retroux.ui.main_window import MainWindow

    vm, _db = build_view_model(read_only=True)
    window = MainWindow(vm, interval_ms=100000, heartbeat=None)
    try:
        for button, label in ((window._auto_button, "AUTO"),
                              (window._turbo_button, "高速化")):
            # ★command.json は書かない（★ここで見たいのは見た目だけ）
            window._sync_toggle(button, False, label, lambda _want: None)
            # ★★ 2026-08-19: 画像アイコン化（RX-0071）。sync で**文字を
            #   書き込まない**こと（書くと 38px で両端が切れる）。
            #   ⚠ 画像アイコンも消えないこと。
            assert button.text() == "", (
                f"⚠ アイコンボタンに文字「{button.text()}」が書き込まれました"
                "（★38px に収まらず両端が切れます）")
            assert not button.icon().isNull(), "⚠ 画像アイコンが消えました"
            assert not button.isChecked()
            # ★入切は言葉でも伝わっていること
            assert button.toolTip().splitlines()[0] == f"{label}: 切"
    finally:
        window.close()
