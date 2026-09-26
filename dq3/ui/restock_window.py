"""補充の設定の窓（RX3-0212 / RX3-0222 / 2026-09-12）— ★品ごとに「何個になるまで買うか」をマトリクスから選ぶ。

★依頼者「リストックの設定画面が欲しい やくそう、どくけしそう、キメラ、せいすい、あまつゆのいと、まんげつそうあたりか？」
★依頼者（RX3-0222）「GUIが縦に長く、1920x1080で見れない。 ２列にして、合わせて 自由分ではなく、マトリクス形式で指定できるようにしたい」

```text
         なし 1 2 3 4 5 6 7 8 9      なし 1 2 3 4 5 6 7 8 9
やくそう   ○  ○ ○ ○ ○ ○ ● ○ ○ ○   せいすい  ● ○ …
どくけし   ○  ○ ● ○ …              まんげつ  ● ○ …
キメラ     ○  ● ○ …                まだらく  ● ○ …
```

★保存は `admin.restock_wants`（★読むのは `town_bar.restock_wants` の 1 本だけ / 形は `やくそう:6,どくけしそう:2`）。
⚠ 表に無い品（★旧い文字の欄で足した品）は、**表示しない**が、触らなければ残す（★表で変えた品だけ書き換える）。
⚠ 全部 0 にしたら「なし」と書く（★空にすると既定の目標に戻ってしまう）。

## ★RX3-0258（2026-09-14 依頼者「DQ3 管理画面UI見直し・リストック設定改修」）

★ラジオのマトリクス → 「アイテム」「保持数」の 2 列の表（`RestockTable`）。★管理画面と［…］の窓で同じ部品を使う。
★約 5 行ぶんの高さ / 6 件目からは表の中だけスクロール / 保持数は 0〜9 の数（★0 = 対象外 / ⚠ ON/OFF は置かない）。
⚠ 名前の自由入力はしない（★品は下の道具番号 / 名前は ROM の道具辞書から）。
⚠ ホイールは、数の欄を選んでいないときは表のスクロールに回す（★スクロール中に触れただけで数が変わらない）。
★依頼者の「あまつゆのいと」は FC 版 DQ3 の道具表に無く、★まだらくもいと（116）のこと（2026-09-12 依頼者「まだらくもいとだね」）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from dq3.ui import town_bar as TB

#: ★表に並べる品（★ROM の道具番号 / 名前は実行時に ROM から / ⚠ UI に名前を書かない）
#:   ★先頭 5 件は依頼者の順（RX3-0258 §3）: やくそう 101 / どくけしそう 102 / キメラのつばさ 104 / まんげつそう 108 / せいすい 103
#:   ★6 件目から: まだらくもいと 116 / どくがのこな 115 / きえさりそう 86（★道具屋で売る消耗品の残り / ROM の品揃えで確かめた）
RESTOCK_ITEMS = (101, 102, 104, 108, 103, 116, 115, 86)
#: ★保持数の上限（★今までの窓と同じ 9 / ⚠ 持ちきれない分は補充の計画が買わない）
MAX_COUNT = 9
#: ★表の高さ（行 / RX3-0258 §2: 約 5 行 / 6 件目からは表の中だけスクロール）
VISIBLE_ROWS = 5
#: ★数の欄の最小の幅（px / ⚠ 狭すぎない / §7）
COUNT_WIDTH = 64
SECTION, KEY = "admin", "restock_wants"
#: ★表の上の一言（★管理画面と［…］の窓で同じ）
NOTE = "★店で、この数になるまで買います（0 = 買わない）。⚠ 持ちきれない分は買いません"
#: ★全部「なし」の印（⚠ `parse_wants` は知らない名前を飛ばす → 目標なし）
NOTHING = "なし"


def item_name(item_id: int) -> str:
    from dq3.knowledge import item_info as II

    got = II.info(item_id)
    return got.name if got is not None and got.name else "品 %d" % item_id


def current(settings) -> dict:
    """★いまの目標（item_id → 個数 / ⚠ 並びも保つ）。"""
    return dict(TB.restock_wants(settings))


def wants_text(counts: dict, order) -> str:
    """★`{101: 6, 102: 2}` → `やくそう:6,どくけしそう:2`（★0 個は書かない / 全部 0 なら「なし」）。"""
    parts = ["%s:%d" % (item_name(k), int(counts.get(k) or 0)) for k in order if int(counts.get(k) or 0) > 0]
    return ",".join(parts) or NOTHING


def default_text() -> str:
    """★既定に戻したときの保存（★`town_bar.DEFAULT_WANTS` / 名前は ROM から）。"""
    return wants_text(dict(TB.DEFAULT_WANTS), [k for k, _n in TB.DEFAULT_WANTS])


class CountBox(QSpinBox):
    """★保持数の欄（0〜9 / ⚠ 数字しか入らない）。

    ⚠ 選んでいないときのホイールは表のスクロールに回す（★スクロール中に触れただけで数が変わらない / §7）。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRange(0, MAX_COUNT)
        self.setMinimumWidth(COUNT_WIDTH)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)          # ⚠ ホイールで選ばれない

    def wheelEvent(self, event) -> None:                        # noqa: N802 (Qt の名前)
        if not self.hasFocus():
            event.ignore()                                      # ★表へ回す（表の中だけスクロール）
            return
        super().wheelEvent(event)


class RestockTable(QTableWidget):
    """★補充の目標の表（RX3-0258）: 「アイテム」「保持数」/ 約 5 行 / 6 件目からは表の中だけスクロール。

    ★数を変えたらすぐ保存（`admin.restock_wants`）。⚠ `refresh()` の並べ直しでは保存しない。
    """

    def __init__(self, settings, parent=None) -> None:
        super().__init__(len(RESTOCK_ITEMS), 2, parent)
        self.settings = settings
        self.setHorizontalHeaderLabels(["アイテム", "保持数"])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)              # ★長い名前は「…」（⚠ 表を広げない）
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        head = self.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.spins: dict = {}        #: item_id -> CountBox
        for row, item_id in enumerate(RESTOCK_ITEMS):
            name = QTableWidgetItem(item_name(item_id))
            name.setToolTip(item_name(item_id))
            self.setItem(row, 0, name)
            spin = CountBox()
            spin.setToolTip("%s: この数になるまで買う（0 = 買わない）" % item_name(item_id))
            spin.valueChanged.connect(lambda n, k=item_id: self._picked(k, n))
            self.setCellWidget(row, 1, spin)
            self.spins[item_id] = spin
        rows = self.verticalHeader()
        rows.setDefaultSectionSize(max(rows.defaultSectionSize(), spin.sizeHint().height() + 2))
        head.resizeSection(1, max(COUNT_WIDTH, spin.sizeHint().width()) + 8)
        self.refresh()
        self.setFixedHeight(self.rows_height(VISIBLE_ROWS))

    def rows_height(self, rows: int) -> int:
        """★見出し ＋ `rows` 行ぶんの高さ（★約 5 行 / ⚠ 表全体の高さにしない = 6 件目からは表の中だけスクロール）。"""
        return (self.horizontalHeader().sizeHint().height() + rows * self.verticalHeader().defaultSectionSize()
                + 2 * self.frameWidth())

    def value(self, item_id: int) -> int:
        """★いまの保持数（★検査・画面の読み取り用）。"""
        return self.spins[item_id].value()

    def refresh(self) -> None:
        counts = current(self.settings)
        for item_id, spin in self.spins.items():
            if spin.hasFocus():
                continue                       # ⚠ 打っている途中の欄は書き換えない
            spin.blockSignals(True)            # ⚠ 並べ直しでは保存しない
            spin.setValue(min(int(counts.get(item_id, 0)), MAX_COUNT))
            spin.blockSignals(False)

    def _picked(self, item_id: int, n: int) -> None:
        counts = current(self.settings)
        counts[item_id] = int(n)
        order = list(RESTOCK_ITEMS) + [k for k in counts if k not in RESTOCK_ITEMS]
        self.settings.set(SECTION, KEY, wants_text(counts, order))

    def reset(self) -> None:
        """★既定に戻す（★`town_bar.DEFAULT_WANTS`）。"""
        self.settings.set(SECTION, KEY, default_text())
        self.refresh()


class RestockWindow(QWidget):
    """★補充の設定の窓（町の行の［…］から）。⚠ 2 つ開かない（★開き方は町の行が持つ）。★中身は管理画面と同じ表。"""

    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("補充設定")
        root = QVBoxLayout(self)
        root.addWidget(QLabel(NOTE))
        self.table = RestockTable(settings)
        root.addWidget(self.table)
        buttons = QHBoxLayout()
        self.reset_button = QPushButton("既定に戻す")
        self.reset_button.setToolTip("★%s" % default_text())
        self.reset_button.clicked.connect(self.reset)
        close = QPushButton("閉じる")
        close.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def refresh(self) -> None:
        self.table.refresh()

    def reset(self) -> None:
        self.table.reset()


__all__ = ["RestockWindow", "RestockTable", "CountBox", "RESTOCK_ITEMS", "MAX_COUNT", "VISIBLE_ROWS", "NOTHING",
           "NOTE", "wants_text", "current", "item_name", "default_text"]
