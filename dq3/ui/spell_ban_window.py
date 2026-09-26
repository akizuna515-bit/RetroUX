"""使わない呪文を作戦ごとに選ぶ（RX3-0370 / 2026-09-22）。

```text
┌ 使う呪文 ─────────────────────────────┐
│ 作戦  [リソース節約 ▼]                          │
│                                                 │
│ ── 攻撃 ──                                      │
│ ☑ ギガデイン          MP 30   勇                │
│ ☑ イオラ              MP 12   魔                │
│ ── 回復 ──                                      │
│ ☑ ベホイミ            MP  5   僧                │
│                                                 │
│ ⚠ チェックを外した呪文は、この作戦では使いません │
│                    [全部使う]        [閉じる]   │
└─────────────────────────────────────────────────┘
```

## ⚠⚠ 依頼者 2026-09-22

> 勇者がギガデインを使いすぎる。AI 判断は難しいので、**使わない呪文をモード毎に設定**
> するのが良い（★別画面、呪文・消費 MP を表示してチェックボックスで選択。
> ★AI が使わない呪文はそもそも表示しない）。

## ★決まりは 1 か所にしかありません

「AI が使う呪文」の分け方は `dq3/phase0/ai/roles.lua` にあり、
★`dq3/battle_ai/spell_picker.py` が**そこから読み出します**（⚠ 写しません）。

## ⚠ 覚えている呪文だけを出します

★全 50 種を並べても選べません。⚠ 転職・レベルアップで増えたら、
次に開いたときに増えます（★除外は「使わない ID」で持つので、増えた分は自動で「使う」側）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from ..battle_ai import settings as S
from ..battle_ai import spell_picker as SP

TITLE = "使う呪文"
#: ⚠ 出せるものが無いとき（★パーティが届いていない / ROM が読めない）
EMPTY = "（呪文が読めません。★戦闘に入るか、少し待ってからもう一度どうぞ）"
#: ★節の見出し（⚠ 押せない行）
HEAD = "── %s ──"
NOTE = "⚠ チェックを外した呪文は、この作戦では AI が使いません（★他の作戦には効きません）"


def line(row: SP.Row, names=None) -> str:
    """★1 行の文（★呪文名・消費 MP・覚えている人）。"""
    who = []
    for slot in row.who:
        got = (names or {}).get(slot)
        who.append(str(got) if got else slot)
    return "%-8s MP %3d   %s" % (row.name, row.mp, "・".join(who))


class SpellBanWindow(QDialog):
    """★作戦ごとに「使わない呪文」を選ぶ窓。"""

    def __init__(self, hub, parent=None) -> None:
        super().__init__(parent)
        self.hub = hub
        self.setWindowTitle(TITLE)
        self.resize(420, 480)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("作戦"))
        self.strategy = QComboBox()
        for name in S.STRATEGIES:
            self.strategy.addItem(S.STRATEGY_LABELS[name], name)
        self.strategy.currentIndexChanged.connect(self._strategy_changed)
        top.addWidget(self.strategy, 1)
        root.addLayout(top)

        self.list = QListWidget()
        # ⚠⚠ 作り直しの間は四角の合図を無視する（★`go_window` と同じ歯止め / RX3-0353）
        self._refreshing = False
        self.list.itemChanged.connect(self._item_changed)
        root.addWidget(self.list, 1)

        self.note = QLabel(NOTE)
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        buttons = QHBoxLayout()
        self.all_on = QPushButton("全部使う")
        self.all_on.setToolTip("★この作戦の除外をすべて戻します")
        self.all_on.clicked.connect(self._use_all)
        buttons.addWidget(self.all_on)
        buttons.addStretch(1)
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.strategy.setCurrentIndex(max(S.STRATEGIES.index(hub.value.strategy), 0)
                                      if hub.value.strategy in S.STRATEGIES else 0)
        self.refresh()

    # ------------------------------------------------------------------

    def current_strategy(self) -> str:
        got = self.strategy.currentData()
        return got if got in S.STRATEGIES else S.ECONOMY

    def rows(self) -> list:
        """★出す行（⚠ 読めなければ空）。"""
        try:
            return SP.rows_for(self.hub.members_for_view(),
                               getattr(self.hub, "rom_path", None))
        except Exception:                                  # noqa: BLE001 ★画面は落とさない
            return []

    def refresh(self) -> None:
        self._refreshing = True
        try:
            self._refresh()
        finally:
            self._refreshing = False

    def _refresh(self) -> None:
        self.list.clear()
        rows = self.rows()
        if not rows:
            self._add(EMPTY)
            self.all_on.setEnabled(False)
            return
        strategy = self.current_strategy()
        bans = self.hub.value.bans_of(strategy)
        self.all_on.setEnabled(bool(bans))
        names = self.hub.names() if hasattr(self.hub, "names") else {}
        bucket = None
        for row in rows:
            if row.bucket != bucket:
                bucket = row.bucket
                self._add(HEAD % row.bucket_label)
            self._add(line(row, names), payload=row.spell_id,
                      checked=row.spell_id not in bans)

    def _add(self, text, payload=None, *, checked=None) -> None:
        """★1 行足す。⚠ **先に `addItem` してから**旗と印を置きます。

        ⚠⚠ 逆にすると `_refreshing` の歯止めが**効かない状態**で合図が飛びます
          （★`RX3-0353` で実際に起きた）。
        """
        item = QListWidgetItem(text)
        self.list.addItem(item)
        if payload is None or checked is None:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
                          & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(self.palette().mid())
            return
        item.setData(Qt.ItemDataRole.UserRole, int(payload))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _item_changed(self, item) -> None:
        if self._refreshing:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        if sid is None:
            return
        banned = item.checkState() != Qt.CheckState.Checked
        strategy = self.current_strategy()
        # ★保存 → 生成 → `ai_reload` は hub が 1 か所でやる（⚠ ここでは組まない）
        self.hub.update(self.hub.value.with_ban(strategy, int(sid), banned))
        self.all_on.setEnabled(bool(self.hub.value.bans_of(strategy)))

    def _strategy_changed(self, *_args) -> None:
        self.refresh()

    def _use_all(self) -> None:
        strategy = self.current_strategy()
        self.hub.update(self.hub.value.without_bans(strategy))
        self.refresh()
