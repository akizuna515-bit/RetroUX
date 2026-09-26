"""モンスター図鑑（RX3-0040 / 2026-09-01）。

★`RX3-0035`（絵）・`RX3-0036`（性能）・`RX3-0039`（行動・耐性・ドロップ）が
揃ったので、⚠ **1 か所で全部見られる**ようにします。

```text
┌─ 図鑑 — RetroUX DQ3 ──────────────────────────────┐
│ スライム   │ [ 絵 ]  HP 8  MP 0  攻 9  守 5 …      │
│ おおがらす │                                        │
│ さそりばち │ 行動   通常攻撃 x6 / 逃げる x2          │
│ …          │ 耐性   ラリホー 効く / マホトーン 効かない│
│            │ 落とす ○○○○ ― 1/64                    │
└────────────────────────────────────────────────────┘
```

## ⚠⚠ 出してよいものだけ出す

★判断は `dq3/knowledge/monster_book.py` の 1 か所に置いてあります。
⚠ ここ（画面）では**判断しません**。★渡されたものを描くだけです。

```text
会っていない   ⚠ 一覧に出さない
会った         ★名前・絵・基本性能
倒した         ★＋ 行動・耐性・ドロップ
```

## ⚠ 窓の大きさを中身で変えません

`docs/design/dq3-ui-v0.md` の決まりです。★入らなければスクロール。
⚠ `RX3-0037` で下の窓が「人がつまんで変える」形になったので、★ここも同じにします。

## ⚠⚠ `retroux/` は変えません（`RX3-0011`）

★DQ2 にも `monster_book_window.py` があります。⚠⚠ **2026-09-01 訂正**:
以前ここに「あちらに行動・耐性・ドロップはありません」と書きましたが、
★**誤りでした**（DQ2 の図鑑には `resist_label` / `action_breakdown` /
`format_drop` があり、節ごとに出しています）。

⚠ 作りが違うのは**中の値**のほうです（★DQ2 は耐性 0..7 の 6 種、
DQ3 は 0..3 の 14 種）。→ ★見せ方は DQ2 に寄せ、⚠ 中身は DQ3 側で持ちます。

★DQ2 から借りた作法:
```text
一覧 ＋ 詳細の 2 枚          ⚠ 1 つの表に詰めない
節の見出しで分ける            ★ROM 由来と「あなたの記録」を混ぜない
空欄を作らない                ★「なし」「絵がありません」と書く
絵の背景は黒                  ⚠ FC の戦闘画面が黒
絵の出どころを書く            ⚠ どれを見ているか分からない状態にしない
耐性は格子で整列              ⚠ 1 行にべた書きしない
耐性は「効く確率」            ⚠⚠ raw の 0..3 を見せない
```
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QScrollArea,
                               QSplitter, QVBoxLayout, QWidget)

#: ★一覧の幅（⚠ 絵と名前が入る程度）
LIST_WIDTH = 210

#: ★一覧に出す小さな絵の枠（⚠ 大きすぎると 1 画面に入らない）
ICON_W, ICON_H = 40, 32

#: ★絵の枠（⚠ いちばん大きい敵は 10 列 x 8 行 = 80x64）
ART_W, ART_H = 80, 64

#: ★絵を出すときの最大の倍率（⚠ 大きすぎるとドットが荒れて見えるだけ）
ART_MAX_SCALE = 3

#: ★窓の既定（**論理**）。⚠ 実際は人が変えられる
WINDOW_W, WINDOW_H = 760, 580

#: ★一覧が取る割合（⚠ 中身のほうを広く）
LIST_SHARE = 0.28


#: ★詳細に出す絵の枠（⚠ いちばん大きい敵 80x64 を 3 倍にした大きさ）
DETAIL_W, DETAIL_H = ART_W * ART_MAX_SCALE, ART_H * ART_MAX_SCALE

#: ★絵の下に書く「出どころ」の高さ（⚠ ここを見込まないと絵に重なる）
SOURCE_H = 18


def art_scale(pix: QPixmap, box_w: int = DETAIL_W,
              box_h: int = DETAIL_H) -> int:
    """★枠に収まる**整数倍**（⚠ 滑らかに拡大しない / ドットが溶ける）。

    ## ⚠⚠ 2026-09-01: ここが**1 倍の箱**で計算していました

      ★枠は 3 倍（240x192）なのに、⚠ 既定が `ART_W x ART_H`（80x64）
      だったため、**80x64 の敵は倍率 1 のまま**でした。
      → ⚠ ゾーマが黒枠の中で小さく出ていました（★画面を撮って気づいた）。

    ★いちばん大きい敵（80x64）が**ちょうど 3 倍で枠に収まる**ので、
    ⚠ 実質すべて 3 倍になります。**敵ごとの大小はそのまま残ります**
    （★16x16 のスライムは 48x48。⚠ 引き伸ばして同じ大きさにしない）。
    """
    if pix.isNull():
        return 1
    return max(1, min(ART_MAX_SCALE,
                      box_h // max(pix.height(), 1),
                      box_w // max(pix.width(), 1)))


def summary_lines(entry) -> list[tuple[str, str]]:
    """★右側に出す行を組み立てる（⚠ Qt を使わない = 画面なしで検査できる）。

    ⚠⚠ **倒していない敵には、行動・耐性・ドロップの見出しごと出しません。**
      ★「まだ出せません」とだけ書きます（⚠ 空欄にすると「無い」に見えます）。
    """
    rows: list[tuple[str, str]] = []
    if entry.master:
        rows.append(("性能", " / ".join(
            "%s %s" % (label, value) for label, value in entry.master
            if value is not None)))
    # ★あなたが唱えた結果（RX3-0271 / ⚠ 観測だけ / 会った敵なら倒していなくても出す）
    tries = getattr(entry, "tries", ()) or ()
    if tries:
        rows.append(("試した", " / ".join("%s %d回中%d回 効いた" % (label, n, k) for label, n, k in tries)))
    if entry.locked:
        rows.append(("中身", "⚠ まだ倒していないので出しません"))
        return rows
    if entry.actions:
        rows.append(("行動", " / ".join(
            "%s x%d" % (name, n) if n > 1 else name
            for name, n in entry.actions)))
    if entry.resistances:
        # ★5 つのまとまりで（RX3-0269 / 依頼者の表）。⚠ まとまりが無い（古い呼び方）ときは今までどおり
        groups = getattr(entry, "resistance_groups", ()) or ()
        if groups:
            text = " / ".join("%s: %s" % (group, " ".join("%s%s" % (label, symbol)
                                                          for label, _c, _lv, symbol, _w in items))
                              for group, items in groups)
        else:
            text = " / ".join("%s %s" % (label, note) for label, level, note in entry.resistances)
        rows.append(("耐性", text))
    if entry.drop:
        # ⚠ 名前は覚えていれば出し、★知らなければ分類 ＋ 番号で出す
        #   （`dq3rom/items.py` / 原作テキストを同梱しない方針）
        rows.append(("落とす", "%s ― %s"
                     % (entry.drop_label, entry.drop.get("rate"))))
    return rows


def _clear_layout(layout) -> None:
    """★レイアウトの中身を、入れ子のレイアウトまで降りて全部外す（⚠ `takeAt` だけでは入れ子の部品が残る）。"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif child is not None:
            _clear_layout(child)
            child.deleteLater()


class Dq3MonsterBookWindow(QWidget):
    """会った敵を一覧で見る窓。"""

    def __init__(self, view_model, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self.setWindowTitle("図鑑 — RetroUX DQ3")
        self.setWindowFlag(Qt.WindowType.Window, True)
        # ⚠ フォーカスを奪わない（★奪うとゲームを操作できなくなる）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(WINDOW_W, WINDOW_H)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#8a93a5; font-size:11px;")
        root.addWidget(self.count_label)

        # ★人がつまんで変えられる（⚠ `RX3-0037` と同じ決まり）
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split, 1)

        self.list = QListWidget()
        self.list.setMinimumWidth(LIST_WIDTH)
        self.list.currentRowChanged.connect(self._picked)
        self.split.addWidget(self.list)

        self.detail = QScrollArea()
        self.detail.setWidgetResizable(True)
        self.detail.setFrameShape(QFrame.Shape.NoFrame)
        self._body = QWidget()
        self._body_box = QVBoxLayout(self._body)
        self._body_box.setContentsMargins(8, 4, 8, 8)
        # ⚠⚠ `setAlignment(AlignTop)` は使いません。★2026-09-01 に、
        #   高さが足りないとき**部品が重なって**描かれました（画面を撮って発見）。
        #   → ★DQ2 と同じく、最後に `addStretch(1)` で上へ寄せます。
        self.detail.setWidget(self._body)
        self.split.addWidget(self.detail)
        self.split.setSizes([int(WINDOW_W * LIST_SHARE),
                             WINDOW_W - int(WINDOW_W * LIST_SHARE)])

        #: ★いま出している並び（⚠ 選び直しのために持つ）
        self._entries: list = []
        self.reload()

    # --- ★中身 -----------------------------------------------------------

    def _book(self):
        """⚠ 図鑑の元（★view_model が持っていなければ None）。

        ⚠ `view_model` 側の名前は `enemy_names` です（★`EnemyBook` が入る）。
          `enemy_book` も受けます（⚠ 検査で差し替えやすいように）。
        """
        for name in ("enemy_book", "enemy_names"):
            got = getattr(self.vm, name, None)
            if got is not None and hasattr(got, "knows_details"):
                return got
        return None

    def reload(self) -> None:
        """★一覧を作り直す（⚠ 選んでいた敵はできるだけ保つ）。"""
        from dq3.knowledge import monster_book as mb

        book = self._book()
        keep = self.current_id()
        self._entries = mb.entries(book) if book is not None else []
        got = mb.counts(book) if book is not None else {"met": 0, "defeated": 0}
        # ⚠⚠ 全体数は出さない（★まだ会っていない数が分かってしまう）
        self.count_label.setText(
            "会った %d 体 / 倒した %d 体" % (got["met"], got["defeated"]))

        self.list.blockSignals(True)
        self.list.clear()
        # ★一覧も絵を主役にする（⚠ 指示書 §8。★DQ2 は文字だけだが、
        #   DQ3 は全種ぶんの絵が揃っているので**こちらのほうが探しやすい**）
        # ⚠⚠ 全体数は書かない（★`test_件数に全体数を出さない` が見ています）
        self.list.setIconSize(QSize(ICON_W, ICON_H))
        for entry in self._entries:
            mark = "" if entry.defeated else "  ⚠"
            item = QListWidgetItem(entry.name + mark)
            item.setData(Qt.ItemDataRole.UserRole, entry.enemy_id)
            icon = self._icon_of(entry)
            if icon is not None:
                item.setIcon(icon)
            self.list.addItem(item)
        self.list.blockSignals(False)

        if not self._entries:
            self._show(None)
            return
        row = 0
        for i, entry in enumerate(self._entries):
            if entry.enemy_id == keep:
                row = i
                break
        self.list.setCurrentRow(row)

    def _icon_of(self, entry):
        """★一覧に出す小さな絵（⚠ 無ければ `None`。**代わりの絵を当てない**）。"""
        if entry.art is None:
            return None
        pix = QPixmap(str(entry.art))
        if pix.isNull():
            return None
        scale = max(1, min(ICON_H // max(pix.height(), 1),
                           ICON_W // max(pix.width(), 1)))
        return QIcon(pix.scaled(pix.width() * scale, pix.height() * scale,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.FastTransformation))

    def current_id(self):
        """★いま選んでいる敵（⚠ 何も無ければ None）。"""
        item = self.list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _picked(self, row: int) -> None:
        if 0 <= row < len(self._entries):
            self._show(self._entries[row])

    # --- ★節（⚠ DQ2 の図鑑と同じ「見出しで分ける」作り）------------------

    # ★★ 色は「白地で読めること」を先に見る（RX3-0040 / 2026-09-03）★★
    #
    #   ⚠⚠ 2026-09-03 の実機で、**題（敵の名前）が読めませんでした**。
    #     ★窓は OS の明るいパレット（白地）なのに、
    #     ⚠ 文字色が暗い背景向け（`#e6e9ef` / `#c8cdd8`）のままだったためです。
    #     ★地の色を敷いているのは**絵の枠だけ**（`background:#000000`）。
    #
    #   ⚠ DQ2 の図鑑（`retroux/ui/monster_book_window.py`）は
    #     **本文の色を決め打ちしません**（★地に合わせて黒で出る）。
    #
    #   → ★`tests/test_dq3_ui.py` が、白地との明暗差を見ています。
    #     ⚠ 暗い背景向けの色へ戻すと**赤くなります**。

    def _heading(self, text: str) -> QLabel:
        got = QLabel(text)
        font = QFont()
        font.setBold(True)
        got.setFont(font)
        got.setStyleSheet("color:#2f5d9e; margin-top:6px;")
        return got

    def _line(self, text: str, dim: bool = False) -> QLabel:
        got = QLabel(text)
        got.setWordWrap(True)
        got.setStyleSheet("color:%s; font-size:12px;"
                          % ("#6a7080" if dim else "#2a2f3a"))
        return got

    def _art_widget(self, entry) -> QWidget:
        """★絵と、その出どころ（⚠ DQ2 と同じく**空けない**）。"""
        box = QVBoxLayout()
        art = QLabel()
        art.setFixedSize(DETAIL_W, DETAIL_H)
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.setFrameShape(QFrame.Shape.StyledPanel)
        # ★背景は黒（⚠ FC の戦闘画面が黒。DQ2 で同じ判断をしている）
        art.setStyleSheet("color:#8a8a8a; background:#000000;"
                          " border:1px solid #3a4150; border-radius:4px;")
        pix = QPixmap(str(entry.art)) if entry.art is not None else QPixmap()
        source = "ROM から起こした絵"
        if pix.isNull():
            # ⚠ 無いものは描かない（★似た敵の絵を当てない）
            art.setText("絵がありません")
            source = "⚠ まだ絵がありません"
        else:
            scale = art_scale(pix)
            art.setPixmap(pix.scaled(
                pix.width() * scale, pix.height() * scale,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation))
        box.addWidget(art)
        # ★出どころを必ず書く（⚠ どれを見ているか分からない状態にしない）
        note = QLabel(source)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet("color:#6a7080; font-size:10px;")
        box.addWidget(note)
        box.setContentsMargins(0, 0, 0, 0)
        holder = QWidget()
        holder.setLayout(box)
        # ⚠⚠ 2026-09-01: ここを固定しないと**縦に潰され**、
        #   ★「出どころ」の文字が絵に**重なって**描かれました（画面を撮って発見）。
        holder.setFixedSize(DETAIL_W, DETAIL_H + SOURCE_H)
        return holder

    def _stats_widget(self, entry) -> QWidget:
        """★性能を 2 列に並べる（⚠ DQ2 と同じ格子）。"""
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        if not entry.master:
            grid.addWidget(self._line("⚠ 読めませんでした", dim=True), 0, 0)
        for i, (label, value) in enumerate(entry.master):
            cap = QLabel(str(label))
            cap.setStyleSheet("color:#8a93a5; font-size:11px;")
            val = QLabel("-" if value is None else str(value))
            val.setFont(QFont("Consolas"))
            val.setStyleSheet("color:#1f2430; font-size:12px;")
            grid.addWidget(cap, i // 2, (i % 2) * 2)
            grid.addWidget(val, i // 2, (i % 2) * 2 + 1)
        grid.setColumnStretch(4, 1)
        holder = QWidget()
        holder.setLayout(grid)
        return holder

    def _resist_widget(self, entry) -> QWidget:
        """★耐性を 5 つのまとまりで格子に（RX3-0269 / 依頼者の表 / ⚠ 1 行にべた書きしない / 指示書 §13）。

        ```text
        攻撃呪文      メラ・ギラ・イオ  ヒャド  バギ  デイン
                      × 効かない        ◎ よく効く …
        眠り・混乱    ラリホー …
        ```

        ⚠⚠ **raw の 0〜3・index は出しません。** ★「◎ よく効く / ○ 効く / △ 効きにくい / × 効かない」。
        """
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        per_row = 4                                   # ★いちばん多いまとまり（攻撃呪文・眠り・混乱）が 4 つ
        row = 0
        for group, items in getattr(entry, "resistance_groups", ()) or ():
            head = QLabel(str(group))
            head.setStyleSheet("color:#5a6275; font-size:11px; font-weight:bold;")
            grid.addWidget(head, row, 0)
            for i, (label, _char, level, symbol, word) in enumerate(items):
                r, col = row + (i // per_row) * 2, 1 + i % per_row
                cap = QLabel(str(label))
                cap.setStyleSheet("color:#8a93a5; font-size:11px;")
                # ⚠ 等幅の英字フォント（Consolas）にしない: ○ × が細く小さく出て ○ が「o」に見えた（★実画面で見た）
                val = QLabel("%s %s" % (symbol, word))
                # ★効きにくい・効かないものを目立たせる（⚠ 戦うときに知りたいのはこちら）
                val.setStyleSheet("color:%s; font-size:12px;"
                                  % ("#c2560b" if level >= 2 else "#2e7d32"))
                grid.addWidget(cap, r, col)
                grid.addWidget(val, r + 1, col)
            row += 2 * max(1, (len(items) + per_row - 1) // per_row)
        grid.setColumnStretch(per_row + 1, 1)
        holder = QWidget()
        holder.setLayout(grid)
        return holder

    def _show(self, entry) -> None:
        """★右側を描き直す。⚠ 中身だけ入れ替える（窓は動かさない）。

        ## ★並べる順（指示書 §10 / ⚠ 解析の順ではない）

        ```text
        1 名前  2 絵  3 基本性能  4 行動  5 耐性  6 ドロップ  7 あなたの記録
        ```

        ⚠⚠ **空欄を作りません**（★DQ2 の図鑑と同じ決まり）。
          「なし」「まだ出せません」と書きます。
        """
        # ⚠⚠ 2026-09-02 依頼者「図鑑の表示が重なって見える」: ★`head` は入れ子の QHBoxLayout なので、
        #   `item.widget()` が None になり、その中の絵・名前・性能が**消えずに残って**次の敵と重なっていた。
        #   → ★入れ子の中まで降りて部品を外す（`_clear_layout`）。
        _clear_layout(self._body_box)
        if entry is None:
            self._body_box.addWidget(self._line("まだ 1 体も会っていません",
                                                dim=True))
            return

        # --- 1 名前 / 2 絵 / 3 基本性能 ---------------------------------
        head = QHBoxLayout()
        head.addWidget(self._art_widget(entry))
        right = QVBoxLayout()
        title = QLabel(entry.name)
        big = QFont()
        big.setPointSize(14)
        big.setBold(True)
        title.setFont(big)
        title.setStyleSheet("color:#1f2430;")
        right.addWidget(title)
        right.addWidget(self._stats_widget(entry))
        right.addStretch(1)
        head.addLayout(right, 1)
        # ⚠ `QWidget` で包むと縦に潰れる（★2026-09-01 に踏んだ）
        self._body_box.addLayout(head)

        if entry.locked:
            # ⚠ 見出しごと出さない（★空欄にすると「無い」に見える）
            self._body_box.addWidget(self._heading("行動 / 耐性 / 落とすもの"))
            self._body_box.addWidget(
                self._line("⚠ まだ倒していないので出しません", dim=True))
        else:
            # --- 4 行動 ------------------------------------------------
            self._body_box.addWidget(self._heading("行動"))
            if entry.actions:
                from dq3.knowledge.monster_book import slot_text

                for name, count in entry.actions:
                    self._body_box.addWidget(
                        self._line("・%s%s" % (name, slot_text(count))))
                self._body_box.addWidget(self._line(
                    "★（N枠）は 8 つの枠のうち何個かで、⚠ 確率ではありません",
                    dim=True))
            else:
                self._body_box.addWidget(self._line("なし", dim=True))

            # --- 5 耐性 ------------------------------------------------
            self._body_box.addWidget(self._heading("耐性"))
            if entry.resistances:
                from dq3.knowledge.monster_book import RESIST_LEGEND

                self._body_box.addWidget(self._resist_widget(entry))
                # ★凡例（★「7 割ほど」はここにだけ / ⚠ 数字を前に出すと「70% 丁度」に読める）
                #   ⚠ 短い行ごとに置く（★長い 1 行は測った後に折り返して高さが足りなくなる）
                for text in RESIST_LEGEND:
                    self._body_box.addWidget(self._line(text, dim=True))
            else:
                self._body_box.addWidget(self._line("なし", dim=True))

            # --- 6 ドロップ --------------------------------------------
            self._body_box.addWidget(self._heading("落とすもの"))
            self._body_box.addWidget(self._line(
                "%s ― %s" % (entry.drop_label, entry.drop.get("rate"))
                if entry.drop else "なし"))

        # --- 7 あなたの記録（⚠ ROM 由来と分けて置く / DQ2 と同じ）-------
        self._body_box.addWidget(self._heading("あなたの記録"))
        self._body_box.addWidget(self._line(
            "会った ― %s" % ("はい" if entry.met else "いいえ")
            + "　/　倒した ― %s" % ("はい" if entry.defeated else "まだ")))
        # ★唱えた結果（RX3-0271 / ⚠ 観測だけ = ROM の耐性とは別）
        for label, tried, ok in getattr(entry, "tries", ()) or ():
            self._body_box.addWidget(self._line("・%s ― %d回中%d回 効いた" % (label, tried, ok)))
        if getattr(entry, "tries", ()):
            self._body_box.addWidget(self._line("⚠ 1 回効かなかっただけでは、効かない敵とは言えません",
                                                dim=True))
        self._body_box.addStretch(1)      # ★上へ寄せる（⚠ 重なりを防ぐ）
        self._fit()

    def _fit(self) -> None:
        """⚠⚠ **中身が入りきる高さを、明示して渡す**（★2026-09-01）。

        ⚠ `QScrollArea(widgetResizable=True)` は、中身を作り直しても
          **窓の高さのまま**にしてしまいました（★実測: 必要 520 / 実際 433）。
          → ⚠ 入りきらないぶんが潰され、**部品が重なって**描かれました。

        ★画面を撮って初めて分かりました（⚠ 検査は全部緑のままでした）。

        ⚠⚠ 2026-09-14（RX3-0269）: ここで測ると、作り直したばかりの部品は**まだ見えていない**
          （★Qt は次の一回りで出す）ので、⚠ 高さ 0 と数えられていました（★実測: 測った値 12 / 本当は 711）。
          ★いままで重ならなかったのは、中身が窓の高さ（655）に**たまたま収まっていた**から
          （★耐性を 5 つのまとまりにして溢れ、`test_詳細で部品が重ならない` が初めて赤くなった）。
          → ★いま測り、⚠ 部品が見えた後（次の一回り）でもう一度測る。
        """
        self._body.setMinimumHeight(self._body_box.sizeHint().height())
        # ★窓が先に消えたら呼ばない（★第 2 引数の窓に結びつける）
        QTimer.singleShot(0, self, self._fit_later)

    def _fit_later(self) -> None:
        """★部品が見えた後の高さで、もう一度渡す（★`_fit` の註）。"""
        try:
            self._body.setMinimumHeight(self._body_box.sizeHint().height())
        except RuntimeError:                            # pragma: no cover ⚠ 窓がもう無い
            pass

    def refresh(self) -> None:
        """⚠ 戦闘のたびに増えるので、★開いている間は作り直す。"""
        self.reload()
