"""道具屋・武器屋（RX3-0084 / 0086 / 2026-09-06）— ★「いま装備しているものと比べていくら得か」。

```text
┌─ お店 — RetroUX DQ3 ───────────────────────────────────────────┐
│ お店 [アリアハン の ぶきや・ぼうぐや ▼]              所持金 383 G │
├───────────────────────────────┬────────────────────────────────┤
│ 品            性能      値段   │ どうのつるぎ                     │
│ ひのきのぼう   攻撃  2     5 G  │ これは   武器 / 攻撃 12          │
│ こんぼう      攻撃  7    30 G  │ 値段     100 G（買える）         │
│ どうのつるぎ   攻撃 12   100 G  │ 売ると   75 G                   │
│ …                             │ 装備できる 勇 僧 賢 戦 商 武 遊   │
│                               │ あかり  こんぼう  → ★+5          │
└───────────────────────────────┴────────────────────────────────┘
```

## ⚠⚠ ここで守ること

```text
⚠ 判断しない          ★`item_info` が出した値を描くだけ
⚠ 買わない            ★見せるだけ（自動購入は別 WI）
⚠ 名前を持たない       ★実行時に ROM から
⚠ 行っていない街は出さない ★No-Spoiler（依頼者 2026-09-06）
★列を揃える           ⚠⚠ 等幅フォント ＋ 空白では**揃いません**（下の注記）
```

## ⚠⚠ 列は「桁」ではなく**列**で揃える（2026-09-06 / 依頼者の指摘）

★はじめは 1 行を 1 本の文字列にして、等幅フォントで空白を詰めていました。
⚠ 日本語は全角で、⚠⚠ **等幅フォントに日本語の字が無い**ため別のフォントへ落ち、
★文字数で詰めても**ガタガタ**になります（依頼者の画面で実際にそう見えた）。
→ ★`QTreeWidget` の**3 列**にしました（⚠ フォントに関係なく揃います）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QScrollArea, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import icon_button, icons, theme

#: ★窓の既定（**論理**）。⚠ 実際は人が変えられる
WINDOW_W, WINDOW_H = 820, 560
LIST_SHARE = 0.46

MUTED = "color:#8a93a5; font-size:11px;"

#: ★一覧の列（⚠ 名前 / 性能 / 値段）
COLUMNS = ("品", "性能", "値段")

#: ★★ 商品の検索（RX3-0254 / 依頼者の小WI「お店画面の商品検索」/ 正本 `docs/requests/260913_dq3-shop-search.md`）
#:
#:   ```text
#:   検索：[________]   種別：[ すべて ▼ ]     ★商品名の部分一致 AND 種別 / 入力のたびに絞る（実行ボタンなし）
#:   ```
#:   ⚠ 表示だけを絞る（★品揃え・値段・所持金・装備の比べ方は触らない）。
#:   ★種別は既存の分類（`item_info` の category）で決める（⚠ 名前から推測しない）。名前は分類の見出し（`CATEGORY_LABEL`）。
#:   ★実データ（2026-09-13 / 全部の店の品）: 武器 50・よろい 45・かぶと 11・たて 14・どうぐ 110。
#:     ⚠ 分類できない品（unknown）は店に 1 つも無い → 「その他」は置かない（★指示書 §5「実データ確認後に判断」）。
ALL_KINDS = "すべて"
#: ★種別 → その種別に入る分類（★どうぐ は職業のどうぐも含める）
KIND_CATEGORIES = (("weapon", ("weapon",)), ("armor", ("armor",)), ("shield", ("shield",)),
                   ("helm", ("helm",)), ("accessory", ("accessory",)), ("item", ("item", "tool_class")))
NO_MATCH = "条件に一致する商品はありません"

#: ★★ お店を横断して探す（RX3-0274 / 依頼者 2026-09-14「お店横断で装備を調べられるようにしたい → お店全て、条件一致に街も」）
#:
#:   ```text
#:   お店 [ お店すべて ▼ ]   → 行った街の全部の店の品を、同じ検索・種別で絞る / 一致した品に「街・店」を添える
#:   ```
#:   ⚠ 「すべて」も**行った街の店だけ**（★No-Spoiler / 1 軒ずつのときと同じ `visited_shops`）。
#:   ★同じ品を売る店が 2 軒あれば 2 行（★どこで買えるかを比べるため / 並びは店の順のまま）。
ALL_SHOPS = "お店すべて"
ALL_SHOPS_KEY = "*all-shops*"
#: ★「お店すべて」のときだけ出す列
WHERE_COLUMN = "街・店"


def all_shop_rows(shops, shop_for) -> list[tuple]:
    """★行った街の全部の店の品を `(品, 街・店)` で（★店の順 → 店の中の順 / ⚠ 同じ品も店ごとに 1 行）。"""
    rows: list[tuple] = []
    for shop in shops or ():
        for info in shop_for(list(shop.items)):
            rows.append((info, shop.label))
    return rows


def kinds() -> list[tuple[str, tuple | None]]:
    """★種別のプルダウン（★見出しは既存の分類の名前 / 先頭は「すべて」）。"""
    from dq3.knowledge import item_info as II

    return [(ALL_KINDS, None)] + [(II.CATEGORY_LABEL.get(key, key), cats) for key, cats in KIND_CATEGORIES]


def matches(info, word: str, categories) -> bool:
    """★1 品が条件に合うか（★商品名の部分一致 AND 種別 / ⚠ 名前から種別を推測しない）。"""
    if categories is not None and info.category not in categories:
        return False
    word = (word or "").strip()
    return not word or word in info.label


def filter_infos(infos, word: str, categories) -> list:
    """★表示する品だけ（⚠ 元の並びも中身も変えない / 新しい並びを返す）。"""
    return [info for info in infos if matches(info, word, categories)]


# --- ★★ 並べ替え（RX3-0285 / 2026-09-18 依頼者「性能順でソートするWIをつくりたい」）-----
#
# ⚠⚠ **画面の文字では並べない。**
#   ★「性能」の欄は `攻撃 12` `守備 30` `—` という**文字**なので、文字順だと `9 > 12` になる。
#   ★「値段」も `⚠ 1200 G` の飾りつき。→ ⚠ 並べるのは **中身（数）**。
#
# ⚠ 並べ替えるのは**番号だけ**（`_infos` の位置）。
#   ★品・街/店（`_shown` / `_shown_where`）は同じ並びを前提に持っているので、
#   ⚠⚠ 3 つを別々に並べ替えると**品と店の対応がずれる**。

#: ★押せる列（⚠ 「街・店」は並べ替えない / ★同じ品が散らばるだけで意味が無い）
SORTABLE_COLUMNS = (0, 1, 2)

#: ⚠ 最初に押したときの向き（★性能・値段は「強い順・高い順」から / 品はあいうえお順から）
FIRST_DESC = {0: False, 1: True, 2: True}

#: ★同じ値のときの並び（⚠ 武器と防具で `12` が同じでも、分類でまとまるように）
CATEGORY_ORDER = ("weapon", "armor", "shield", "helm", "accessory",
                  "tool_class", "item", "unknown")


def sort_value(info, column: int):
    """★その列の**中身**（⚠ 無い品は `None` = いつも最後）。"""
    if column == 1:
        return info.pri_stat                    # ⚠ どうぐは None
    if column == 2:
        return info.buy_price or None           # ⚠ 0（売っていない品）は「無し」と同じ
    return info.label


def sort_keep(infos, keep, column: int, desc: bool = False) -> list:
    """★並べ替えた `keep`（= `infos` の番号の並び）。⚠ Qt を使わない = 画面なしで検査できる。

    ```text
    ★値の無い品        いつも最後（⚠ 向きに関わらず / 上に来ると邪魔）
    ★同じ値            分類 → 元の順（= 店の順）で安定（⚠ 同じ品が散らばらない）
    ★文字の列（品）    辞書順（⚠ 逆順でも同値の元順は崩さない）
    ```
    """
    if column not in SORTABLE_COLUMNS:
        return list(keep)
    values = {k: sort_value(infos[k], column) for k in keep}
    # ★値を順位に直してから並べる（⚠ 文字は負にできないので、順位にしてから向きを決める）
    ranks = {v: i for i, v in enumerate(sorted({v for v in values.values() if v is not None}))}

    def key(pair):
        order, k = pair
        value = values[k]
        if value is None:
            return (1, 0, 0, order)             # ⚠ 無いものは最後・元の順
        rank = ranks[value]
        category = infos[k].category
        cat = CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else len(CATEGORY_ORDER)
        return (0, -rank if desc else rank, cat, order)

    return [k for _order, k in sorted(enumerate(keep), key=key)]


def row_cells(info, gold: int | None) -> tuple:
    """★一覧の 1 行を**列ごと**に（⚠ Qt を使わない = 画面なしで検査できる）。"""
    price = "%d G" % info.buy_price if info.buy_price else "—"
    if gold is not None and info.buy_price and gold < info.buy_price:
        price = "⚠ " + price
    return (info.label, info.stat_label or "—", price)


def detail_lines(info, members, gold: int | None, where: str | None = None) -> list[tuple[str, str]]:
    """★右側の詳細（★誰がいくら得をするか）。★`where` は「お店すべて」で選んだ行の街・店（RX3-0274）。"""
    from dq3.knowledge import item_info as II

    rows: list[tuple[str, str]] = []
    if where:
        rows.append(("売っている店", where))
    rows.append(("これは", "%s / %s" % (info.category_label, info.stat_label or "—")))
    if info.buy_price:
        line = "%d G" % info.buy_price
        if gold is not None:
            line += "（所持金 %d G / %s）" % (gold, "買える" if gold >= info.buy_price else "⚠ 足りない")
        rows.append(("値段", line))
        rows.append(("売ると", "%d G" % info.sell_price))
    else:
        rows.append(("値段", "⚠ 売っていない品"))
    if info.equip_classes:
        got = " ".join(II.class_labels(info.equip_classes))
        if info.female_only:
            got += "（⚠ 女性のみ）"
        rows.append(("装備できる", got))
    if info.flags:
        rows.append(("印", " / ".join(II.flag_labels(info.flags))))
    if info.equip_buff is not None:
        rows.append(("特別な効果", "⚠ 装備しているだけで効く（★中身は未解析）"))

    if info.is_gear and members:
        lines = []
        best = II.best_for(info.item_id, members)
        for m, c in zip(members, II.compare_party(info.item_id, members)):
            mark = "★" if (best is not None and c is best and c.delta > 0) else "　"
            lines.append("%s%s：%s → %s"
                         % (mark, m.get("name") or "？", c.current_name or "なし", c.delta_label))
        rows.append(("いま装備しているものとの差", "\n".join(lines)))
    elif info.is_gear:
        rows.append(("いま装備しているものとの差", "⚠ パーティの装備が読めません"))
    return rows


class Dq3ShopWindow(QWidget):
    """お店の窓（⚠ 見せるだけ。★買いません）。"""

    def __init__(self, view_model=None, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self._infos: list = []
        #: ★いま一覧に出している品（★検索で絞ったもの / RX3-0254）。⚠ `_infos`（店の品揃え）は変えない
        self._shown: list = []
        #: ★品ごとの街・店（★「お店すべて」のときだけ中身がある / RX3-0274）。`_infos` / `_shown` と同じ並び
        self._where: list = []
        self._shown_where: list = []
        #: ★いまの並べ替え `(列, 高い順か)`。⚠ `None` = 店の順（★開いたときは今までどおり）
        self._sort: tuple | None = None
        self._members: list = []
        self._shops: list = []
        self.setWindowTitle("お店 — RetroUX DQ3")
        self.setWindowFlag(Qt.WindowType.Window, True)
        # ⚠ フォーカスを奪わない（★奪うとゲームを操作できなくなる）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(WINDOW_W, WINDOW_H)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        cap = QLabel("お店")
        cap.setStyleSheet(MUTED)
        top.addWidget(cap)
        self.shop_select = QComboBox()
        self.shop_select.currentIndexChanged.connect(self._shop_changed)
        top.addWidget(self.shop_select, 1)
        self.gold_label = QLabel("")
        self.gold_label.setStyleSheet(MUTED)
        top.addWidget(self.gold_label)
        root.addLayout(top)

        # ★★ 商品の検索（RX3-0254）: 商品一覧の上に常設（★入力のたびに絞る / 実行ボタンは置かない）
        search = QHBoxLayout()
        search.addWidget(QLabel("検索："))
        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)          # ★小さな × で空にできる（★専用のクリアは置かない）
        # ★虫眼鏡は欄の中（⚠ ボタンにしない / `memo_detail.py` と同じ作法 / RX3-0325）
        self.search_edit.addAction(
            icons.icon("search", theme.MUTED, icon_button.ICON_PX),
            QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.textChanged.connect(self._refilter)
        search.addWidget(self.search_edit, 1)
        search.addWidget(QLabel("種別："))
        self.kind_select = QComboBox()
        for label, cats in kinds():
            self.kind_select.addItem(label, cats)
        self.kind_select.currentIndexChanged.connect(self._refilter)
        search.addWidget(self.kind_select)
        root.addLayout(search)
        self.no_match = QLabel(NO_MATCH)
        self.no_match.setStyleSheet(MUTED)
        self.no_match.setVisible(False)
        root.addWidget(self.no_match)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split, 1)

        # ★★ 列で揃える（⚠ 空白で詰めると日本語でガタガタになる）
        self.list = QTreeWidget()
        self.list.setColumnCount(len(COLUMNS) + 1)
        self.list.setHeaderLabels(list(COLUMNS) + [WHERE_COLUMN])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setAlternatingRowColors(True)
        head = self.list.header()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.list.setColumnHidden(3, True)                  # ★「お店すべて」のときだけ出す（RX3-0274）
        # ★★ 見出しを押して並べ替え（RX3-0285）。
        #   ⚠⚠ `setSortingEnabled(True)` は使わない（★Qt が**画面の文字**で並べてしまう =
        #     「性能」で 9 > 12、「値段」が飾りで崩れる）。★自分で番号を並べ替える。
        head.setSectionsClickable(True)
        head.setSortIndicatorShown(True)
        head.sectionClicked.connect(self.sort_by)
        self.list.currentItemChanged.connect(self._picked)
        self.split.addWidget(self.list)

        self.detail = QScrollArea()
        self.detail.setWidgetResizable(True)
        self.detail.setFrameShape(QFrame.Shape.NoFrame)
        self._body = QWidget()
        self._body_box = QVBoxLayout(self._body)
        self._body_box.setContentsMargins(10, 4, 10, 8)
        self.detail.setWidget(self._body)
        self.split.addWidget(self.detail)
        self.split.setSizes([int(WINDOW_W * LIST_SHARE), WINDOW_W - int(WINDOW_W * LIST_SHARE)])

        self.reload()

    # --- ★中身 -----------------------------------------------------------

    def gold(self):
        """★所持金（⚠ `vm.gold` は**メソッド**のことがある / 2026-09-06 に実機で踏んだ）。"""
        if self.vm is None:
            return None
        try:
            got = getattr(self.vm, "gold", None)
            if callable(got):
                got = got()
            return int(got) if got is not None else None
        except Exception:                                    # noqa: BLE001
            return None

    def members(self):
        try:
            return self.vm.equip_members() if self.vm is not None else []
        except Exception:                                    # noqa: BLE001
            return []

    def shops(self):
        """★行った街の店だけ（⚠ 依頼者 2026-09-06）。"""
        from dq3.knowledge import item_info as II

        try:
            book = self.vm.location_book if self.vm is not None else None
        except Exception:                                    # noqa: BLE001
            book = None
        try:
            return II.visited_shops(book)
        except Exception:                                    # noqa: BLE001
            return []

    def reload(self) -> None:
        """★品揃えを読み直す（⚠ ROM が無ければ「使えません」と出す）。"""
        from dq3.knowledge import item_info as II

        self._members = self.members()
        g = self.gold()
        self.gold_label.setText("所持金 %d G" % g if g is not None else "")
        self._shops = self.shops()
        keep = self.shop_select.currentIndex()
        self.shop_select.blockSignals(True)
        self.shop_select.clear()
        if self._shops:
            # ★先頭に「お店すべて」（RX3-0274）。⚠ 開いたときは今までどおり最初の店（★1 番）
            self.shop_select.addItem(ALL_SHOPS, ALL_SHOPS_KEY)
        for shop in self._shops:
            self.shop_select.addItem(shop.label, list(shop.items))
        self.shop_select.blockSignals(False)
        if not self._shops:
            self.list.clear()
            self._render_detail(None)
            self.shop_select.addItem(
                "⚠ アイテムの性能を読めません（%s）" % (II.last_error or "")
                if not II.available() else "⚠ まだ店のある街へ行っていません")
            return
        self.shop_select.setCurrentIndex(keep if 0 <= keep <= len(self._shops) else 1)
        self._shop_changed(self.shop_select.currentIndex())

    def all_shops_selected(self) -> bool:
        return self.shop_select.currentData() == ALL_SHOPS_KEY

    def _shop_changed(self, index: int) -> None:
        from dq3.knowledge import item_info as II

        data = self.shop_select.itemData(index)
        if data == ALL_SHOPS_KEY:
            rows = all_shop_rows(self._shops, II.shop_for)
            self._infos = [info for info, _where in rows]
            self._where = [where for _info, where in rows]
        else:
            self._infos = II.shop_for(data or [])
            self._where = [None] * len(self._infos)
        self.list.setColumnHidden(3, data != ALL_SHOPS_KEY)
        self._refilter()

    def _refilter(self, *_args) -> None:
        """★検索の条件で一覧を作り直す（RX3-0254 / ⚠ 店の品揃え `_infos` は変えない / 条件は店を替えても残す）。"""
        word = self.search_edit.text() if hasattr(self, "search_edit") else ""
        cats = self.kind_select.currentData() if hasattr(self, "kind_select") else None
        keep = [k for k, info in enumerate(self._infos) if matches(info, word, cats)]
        # ★並べ替え（RX3-0285）。⚠ 番号だけを並べ替えて、品と街・店を**同じ並び**で作る
        if self._sort is not None:
            column, desc = self._sort
            keep = sort_keep(self._infos, keep, column, desc)
        self._shown = [self._infos[k] for k in keep]
        self._shown_where = [self._where[k] if k < len(self._where) else None for k in keep]
        # ★0 件は空欄だけにしない（★条件はそのまま残す / 指示書 §6）
        if hasattr(self, "no_match"):
            self.no_match.setVisible(bool(self._infos) and not self._shown)
        g = self.gold()
        self.list.blockSignals(True)
        self.list.clear()
        for info, where in zip(self._shown, self._shown_where):
            cells = row_cells(info, g)
            item = QTreeWidgetItem(list(cells) + [where or ""])
            # ⚠ 数字は右へ寄せる（★桁が揃って読みやすい）
            right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            item.setTextAlignment(1, right)
            item.setTextAlignment(2, right)
            if g is not None and info.buy_price and g < info.buy_price:
                for col in range(len(COLUMNS) + 1):
                    item.setForeground(col, Qt.GlobalColor.gray)
            self.list.addTopLevelItem(item)
        self.list.blockSignals(False)
        if self.list.topLevelItemCount():
            self.list.setCurrentItem(self.list.topLevelItem(0))
        else:
            self._render_detail(None)

    def sort_by(self, column: int) -> None:
        """★見出しを押した（RX3-0285）。⚠ 同じ列をもう一度押すと向きが変わる。

        ★最初の 1 回は「性能」「値段」なら**高い順**（⚠ 強いものを探しているので）。
        ⚠ 並べ替えは覚えません（★開き直すと店の順から / WI の Scope）。
        """
        if column not in SORTABLE_COLUMNS:
            return
        if self._sort is not None and self._sort[0] == column:
            self._sort = (column, not self._sort[1])
        else:
            self._sort = (column, FIRST_DESC.get(column, False))
        head = self.list.header()
        head.setSortIndicator(
            column, Qt.SortOrder.DescendingOrder if self._sort[1] else Qt.SortOrder.AscendingOrder)
        self._refilter()

    def sort_state(self) -> tuple | None:
        """★いまの並べ替え（⚠ 検査と証跡のため）。"""
        return self._sort

    def current(self):
        # ★一覧に出している品（★検索で絞ったもの）から引く（RX3-0254 / ⚠ `_infos` の番号で引くと別の品になる）
        i = self.list.indexOfTopLevelItem(self.list.currentItem())
        return self._shown[i] if 0 <= i < len(self._shown) else None

    def current_where(self) -> str | None:
        """★選んだ行の街・店（★「お店すべて」のときだけ / RX3-0274）。"""
        i = self.list.indexOfTopLevelItem(self.list.currentItem())
        return self._shown_where[i] if 0 <= i < len(self._shown_where) else None

    def _picked(self, *_args) -> None:
        self._render_detail(self.current(), self.current_where())

    def _render_detail(self, info, where: str | None = None) -> None:
        box = self._body_box
        while box.count():
            item = box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if info is None:
            box.addWidget(QLabel("左の一覧から品を選ぶと、ここに中身が出ます"))
            box.addStretch(1)
            return
        title = QLabel(info.label)
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        box.addWidget(title)
        for label, text in detail_lines(info, self._members, self.gold(), where):
            cap = QLabel(label)
            cap.setStyleSheet(MUTED)
            box.addWidget(cap)
            body = QLabel(text)
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(body)
        box.addStretch(1)
