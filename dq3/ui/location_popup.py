"""MAP の地点情報ポップアップ（RX3-0019 / 2026-08-29）。

★指示書 §5。**今回の主要実装**です。⚠ 大きな詳細画面は作りません。

```text
┌──────────────────────┐
│ レーベ               │
│ 訪問済み             │
├──────────────────────┤
│ メモ      3件        │
│ 聞いた話  5件        │
│ 発見      4件        │
├──────────────────────┤
│ ・魔法の玉の話       │
│ ・老人が鍵について… │
│           [詳細]     │
└──────────────────────┘
```

## ⚠⚠ ここで守ること（指示書 §10）

    RetroUX 内部で知っていること  ≠  UI へ出してよいこと

★この窓は `LocationView` しか受け取りません。⚠ ROM のデータには触れません。
`LocationView` を作れるのは `dq3/ui/view_model.py` だけです。

⚠ 訪れていない地点は、**名前も出しません**（★「？」と出す）。
DQ3 の ROM に地名の平文は無く（`RX3-0013`）、訪れて初めて分かるためです。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

#: ★出す情報の上限（指示書 §5.1「直近または重要な情報を 1〜3 件」）
MAX_HIGHLIGHTS = 3


def _row(label: str, value: str) -> QHBoxLayout:
    box = QHBoxLayout()
    left = QLabel(label)
    left.setStyleSheet("color: #888;")
    left.setFixedWidth(72)
    box.addWidget(left)
    box.addWidget(QLabel(value))
    box.addStretch(1)
    return box


class LocationPopup(QFrame):
    """小型ポップアップ（★窓ではなく浮かせる枠）。"""

    def __init__(self, view, *, on_detail=None, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        self._on_detail = on_detail
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setWindowFlags(Qt.WindowType.ToolTip)
        # ⚠ フォーカスを奪わない（★奪うとゲームの操作が取られる / DQ2 の知見）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # ⚠ `QFrame { ... }` だけだと**中の文字にも枠が付く**（★実際に付いた）。
        #   ★この窓そのものだけに当てる。
        self.setObjectName("locationPopup")
        self.setStyleSheet(
            "QFrame#locationPopup { background: #22262e; "
            "border: 1px solid #4a5160; border-radius: 4px; }"
            "QFrame#locationPopup QLabel { color: #e6e9ef; border: none; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        name = QLabel(view.display_name)
        name.setStyleSheet("font-weight: bold; font-size: 14px;")
        root.addWidget(name)

        state = QLabel(view.label)
        state.setStyleSheet("color: #8bd450;" if view.is_known else "color: #888;")
        root.addWidget(state)

        # ⚠ 知らない地点は、ここから先を出さない（★中身を漏らさない）
        if not view.is_known:
            hint = QLabel("⚠ まだ訪れていません")
            hint.setStyleSheet("color: #888;")
            root.addWidget(hint)
            return

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(line)

        # ★情報が無い項目は出さない（指示書 §5.1）
        for label, n in (("メモ", view.memo_count),
                         ("聞いた話", view.heard_count),
                         ("発見", view.found_count)):
            if n > 0:
                root.addLayout(_row(label, "%d 件" % n))

        if view.highlights:
            line2 = QFrame()
            line2.setFrameShape(QFrame.Shape.HLine)
            root.addWidget(line2)
            for text in view.highlights[:MAX_HIGHLIGHTS]:
                root.addWidget(QLabel("・" + _clip(text)))

        foot = QHBoxLayout()
        foot.addStretch(1)
        detail = QPushButton("詳細")
        # ⚠ 今回は本格実装しない（指示書 §6）。★繋ぎ先が無ければ押せなくする
        detail.setEnabled(self._on_detail is not None)
        if self._on_detail is not None:
            detail.clicked.connect(lambda: self._on_detail(self.view))
        else:
            detail.setToolTip("⚠ 詳細画面はこれから（RX3-0019 の TODO）")
        foot.addWidget(detail)
        root.addLayout(foot)


def _clip(text: str, width: int = 22) -> str:
    """⚠ 長い文でポップアップを広げない（★小型のままにする）。"""
    return text if len(text) <= width else text[:width - 1] + "…"


def show_location_popup(view, at, *, on_detail=None, parent=None) -> LocationPopup:
    """★地点をクリックしたときに出す。

    ⚠ `at` は画面の座標（`QPoint`）。★地図の升ではない。
    """
    popup = LocationPopup(view, on_detail=on_detail, parent=parent)
    popup.adjustSize()
    popup.move(at)
    popup.show()
    return popup
