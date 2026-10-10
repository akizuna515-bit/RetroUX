"""勇者会議（RX3-0074 / 2026-09-04）— 「次にやること」と「最近動いた話」を見る独立した窓。

```text
┌─ 勇者会議 — RetroUX DQ3 ───────────────────────────────────────┐
│ 次にやること                                        [更新]      │
│                                                                 │
│   まずは旅立ちの準備を整え、鍵を探そう                          │
│   旅立ちと盗賊の鍵 ・ メイン ・ 手がかり 1 件                    │
│   ・その品を手に入れたかと尋ねられた（○○○）                     │
├───────────────────────────┬─────────────────────────────────────┤
│ 最近動いた話               │ 旅立ちと盗賊の鍵                    │
│  NEW  旅立ちと盗賊の鍵     │ 目的  アリアハンを出発し…            │
│       メイン / 対応中 / 09/04│ 状態 対応中（更新 1 回 / 最後 09/04）│
│ ── まだ動いていない話 ──   │ 関連する場所  アリアハン / レーベ…  │
│       魔法の玉と旅の扉     │ 関連 Fact                            │
│ ── 完了した話 ──           │   item:88 obtain_hint（○○○）         │
│                            │   ▸ 聞いた文（詳細で開く）           │
└───────────────────────────┴─────────────────────────────────────┘
```

## ⚠⚠ ここで守ること

```text
⚠ 判断しない          ★`council.py` が決めた view を**描くだけ**
⚠ 作文しない          ★Head の文は Guide Master の `ui_head_hint` そのまま（§15）
⚠ Fact を並べない     ★一覧は Topic 単位（§20）。Fact は詳細でだけ
⚠ resolved を消さない ★「完了した話」に畳んで残す（§24）
⚠ 常設パネルに押し込まない ★独立した窓（§18）。図鑑と同じ作法（2 つ開かない / フォーカスを奪わない）
⚠ 毎フレーム評価しない ★開いたときと [更新] のとき（§25）
```
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea,
                               QSplitter, QVBoxLayout, QWidget)

#: ★窓の既定（**論理**）。⚠ 実際は人が変えられる
WINDOW_W, WINDOW_H = 860, 620
LIST_SHARE = 0.42

#: ★一覧の区切り行（⚠ 選べない）
SEPARATOR = "__separator__"

#: ★見出しの色（⚠ 既存の窓と同じ調子）
MUTED = "color:#8a93a5; font-size:11px;"

#: ★「行ってみる？」の管理を開くボタンの字（RX3-0313）
#:
#:   ⚠ 2 か所（作るときと描き直すとき）で使うので、★1 つにまとめます
#:     （⚠ 別々に書くと、片方を直しても画面は変わりません）。
GO_BUTTON = "管理"
HEAD_BG = "background:#f4f6fa; border:1px solid #d5dae3; border-radius:6px;"


def list_rows(view) -> list[tuple[str, str, dict | None]]:
    """★一覧に出す行（⚠ Qt を使わない = 画面なしで検査できる）。

    返す 1 行 = (kind, text, card)。kind は `topic` / `separator`。
    ★並びは council が決めたまま（priority DESC → 更新 DESC / §21）。
    """
    if getattr(view, "scenarios", None):
        return scenario_rows(view)
    rows: list[tuple[str, str, dict | None]] = []
    for card in view.recent:
        rows.append(("topic", _row_text(card), card))
    if view.unknown:
        rows.append(("separator", "── まだ動いていない話（%d）──" % len(view.unknown), None))
        for card in view.unknown:
            rows.append(("topic", _row_text(card), card))
    if view.resolved:
        rows.append(("separator", "── 完了した話（%d）──" % len(view.resolved), None))
        for card in view.resolved:
            rows.append(("topic", _row_text(card), card))
    return rows


def scenario_rows(view) -> list[tuple[str, str, dict | None]]:
    """★勇者メモの scenario で束ねた一覧（RX3-0434）。

    ```text
    ■ ゾーマ城への道                       ← scenario（⚠ 選べない）
      ── 気になっていること ──
      NEW 雨雲の杖を手に入れる
      ── 分かったこと ──
      ✓ 太陽の石を手に入れる
    ■ オーブを集める — いまは気になることはない   ← quiet
      ...
    ── ほかに気になっていること ──          ← scenario の無いカード
    ── 片づいた話 ──
    ```

    ⚠⚠ 並びは `scenario_view.build` が決めたまま（★id 順・YAML の順は使わない）。
    ⚠ 件数・分母・未発見のカードは**出しません**（★view にそもそも無い）。
    """
    from dq3.knowledge.scenario_view import QUIET, QUIET_TEXT

    rows: list[tuple[str, str, dict | None]] = []
    for group in view.scenarios:
        head = "■ %s" % group.title
        if group.state == QUIET:
            head += " — %s" % QUIET_TEXT
        rows.append(("separator", head, None))
        if group.open_cards:
            rows.append(("separator", "   ── 気になっていること ──", None))
            for card in group.open_cards:
                rows.append(("topic", _row_text(card, indent="   "), card))
        if group.done_cards:
            rows.append(("separator", "   ── 分かったこと ──", None))
            for card in group.done_cards:
                rows.append(("topic", _row_text(card, indent="   ", done=True), card))
    loose_open = [c for c in view.recent if not c.get("scenario_id")]
    loose_done = [c for c in view.resolved if not c.get("scenario_id")]
    if loose_open:
        rows.append(("separator", "── ほかに気になっていること ──", None))
        for card in loose_open:
            rows.append(("topic", _row_text(card), card))
    if loose_done:
        rows.append(("separator", "── 片づいた話 ──", None))
        for card in loose_done:
            rows.append(("topic", _row_text(card, done=True), card))
    return rows


def _row_text(card: dict, indent: str = "", done: bool = False) -> str:
    badge = "✓" if done else (card["badge"] or "   ")
    when = card["last_updated_label"] if card["last_updated_at"] else ""
    # ⚠ ✓ の行に「完了」を重ねない（★scenario の「完了」と読まれないように / RX3-0434）
    status = "" if done else card["status_label"]
    tail = " / ".join(p for p in (card["category_label"], status, when) if p)
    tree = "  └ " if card["parent_topic_id"] else ""
    # ★片づいたカードに `done:` の文があれば、題名の代わりにそれを出す（RX3-0437）
    title = (card.get("done_text") or card["title"]) if done else card["title"]
    return "%s%-3s %s%s\n%s      %s" % (indent, badge, tree, title, indent, tail)


def _scenario_title(card: dict, view) -> str:
    """★そのカードが属する scenario の題名（⚠ 無ければ空 / RX3-0445）。"""
    want = card.get("scenario_id") or ""
    if not want:
        return ""
    for group in getattr(view, "scenarios", ()) or ():
        if group.scenario_id == want:
            return group.title
    return ""


def detail_lines(card: dict, view) -> list[tuple[str, str]]:
    """★右側の詳細（⚠ 原文は最後の「聞いた文」だけ / §23）。"""
    rows = [("目的", card["objective"] or "—")]
    if card.get("done_text"):
        # ★片づいたときに分かったこと（`done:` / RX3-0437 / ⚠ 片づいたカードにしか入っていない）
        rows.append(("分かったこと", card["done_text"]))
    if card["completion_hint"]:
        rows.append(("片づく目安", card["completion_hint"]))
    state = card["status_label"]
    if card["update_count"]:
        # ⚠ 言葉は `council.update_text` の 1 か所（★画面でベタ書きしない / RX3-0123）
        from dq3.knowledge.council import update_text

        state += "（%s）" % update_text(card["update_count"], card["last_updated_label"])
    rows.append(("状態", state))
    # ⚠⚠ 2026-09-28（RX3-0445）: ここは「分類 探索 / priority 50」を出していました。
    #   ★勇者メモ経路では `category` と `priority` は**全カード同じ固定値**で
    #     （`hero_memo.compile_leads`）、⚠ 旧 Guide Master の列の名残でした。
    #   → ★代わりに「何の話か」（scenario の題名）を出します。⚠ 無ければ行ごと出しません。
    title = _scenario_title(card, view)
    if title:
        rows.append(("何の話", title))
    if card["related_locations"]:
        # ★解けた場所には「（L9 / 行った）」が付く（⚠ 解けていない名前はそのまま / RX3-0076）
        rows.append(("関連する場所", " / ".join(card["related_locations"])))
    if card.get("nav_target"):
        # ★[ここへ向かう] の受け口（⚠ ボタンはまだ付けない / §26）
        # ★RX3-0248: 「L23」だけでは意味が分からない → 名前を添える（⚠ 知らなければ「不明（L23）」）
        rows.append(("行き先候補", card.get("nav_target_label") or card["nav_target"]))
    if card["parent_topic_id"]:
        rows.append(("親の話", card["parent_topic_id"]))
    if card["children"]:
        rows.append(("子の話", " / ".join(card["children"])))
    if card["matched_fact_ids"]:
        lines = []
        for fact_id in card["matched_fact_ids"]:
            fact = view.facts.get(fact_id) or {}
            name = fact.get("name")
            # ★同じ知識を何人から聞いたか（⚠ 行は 1 つ / 論理 Fact / RX3-0436）
            count = int(fact.get("count") or 1)
            lines.append("%s %s%s%s" % (fact.get("subject", fact_id), fact.get("predicate", ""),
                                        "（%s）" % name if name else "",
                                        "  ×%d 回" % count if count > 1 else ""))
        rows.append(("関連 Fact", "\n".join(lines)))
        texts = [view.facts[f]["text"] for f in card["matched_fact_ids"]
                 if f in view.facts and view.facts[f].get("text")]
        if texts:
            rows.append(("聞いた文", "\n".join(texts)))
    else:
        rows.append(("関連 Fact", "まだありません"))
    return rows


class Dq3CouncilWindow(QWidget):
    """勇者会議の窓（⚠ 独立した窓 / §18）。"""

    def __init__(self, view_model=None, council=None, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self._council = council
        self.view = None
        self._cards: dict[str, dict] = {}
        self.setWindowTitle("勇者会議 — RetroUX DQ3")
        self.setWindowFlag(Qt.WindowType.Window, True)
        # ⚠ フォーカスを奪わない（★奪うとゲームを操作できなくなる）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(WINDOW_W, WINDOW_H)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- ★上段: 次にやること ----------------------------------------
        head_box = QFrame()
        # ⚠ 名前で絞る（★絞らないと**中の QLabel まで枠が付く**。2026-09-04 に画面で見た）
        head_box.setObjectName("councilHead")
        head_box.setStyleSheet("#councilHead { %s }" % HEAD_BG)
        head = QVBoxLayout(head_box)
        head.setContentsMargins(12, 8, 12, 10)
        head.setSpacing(3)
        top = QHBoxLayout()
        cap = QLabel("次にやること")
        cap.setStyleSheet(MUTED)
        top.addWidget(cap)
        top.addStretch(1)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(MUTED)
        top.addWidget(self.status_label)
        # ★冒険ログ（RX3-0150）。⚠ 生成 AI へは繋がない（★人が貼る）
        self.copy_button = QPushButton("冒険ログをコピー")
        self.copy_button.setToolTip(
            "★これまでの記録を 1 本のテキストにして、クリップボードへ入れます\n"
            "⚠ 生成 AI へは送りません（★貼り付け先はご自分で）")
        self.copy_button.clicked.connect(self.copy_adventure_log)
        top.addWidget(self.copy_button)

        self.refresh_button = QPushButton("更新")
        self.refresh_button.setToolTip("聞いた会話から攻略の進み具合を評価し直す\n⚠ 開いたときにも 1 回やっています")
        self.refresh_button.clicked.connect(self.reload)
        top.addWidget(self.refresh_button)
        head.addLayout(top)

        self.head_message = QLabel("")
        self.head_message.setWordWrap(True)
        font = QFont()
        font.setPointSize(15)
        font.setBold(True)
        self.head_message.setFont(font)
        head.addWidget(self.head_message)

        self.head_sub = QLabel("")
        self.head_sub.setStyleSheet(MUTED)
        head.addWidget(self.head_sub)

        self.head_reasons = QLabel("")
        self.head_reasons.setWordWrap(True)
        self.head_reasons.setStyleSheet("font-size:12px;")
        head.addWidget(self.head_reasons)
        root.addWidget(head_box)

        # --- ★下段: 一覧 ＋ 詳細（★人がつまんで変えられる）-------------------
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split, 1)

        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_cap = QLabel("最近動いた話")
        left_cap.setStyleSheet(MUTED)
        left_box.addWidget(left_cap)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.currentRowChanged.connect(self._picked)
        left_box.addWidget(self.list, 1)
        self.split.addWidget(left)

        self.detail = QScrollArea()
        self.detail.setWidgetResizable(True)
        self.detail.setFrameShape(QFrame.Shape.NoFrame)
        self._body = QWidget()
        self._body_box = QVBoxLayout(self._body)
        self._body_box.setContentsMargins(10, 4, 10, 8)
        self.detail.setWidget(self._body)
        self.split.addWidget(self.detail)
        self.split.setSizes([int(WINDOW_W * LIST_SHARE), WINDOW_W - int(WINDOW_W * LIST_SHARE)])

        # --- ★行ってみる？（RX3-0113）------------------------------------
        #   ⚠⚠ **0 件なら節ごと消します**（★空の箱を置かない）。
        #
        #   ⚠ 下の 1 行は**自動で出る**もの（`reachable.collect` / ★保存しない・DONE が無い）。
        #   ★人が勇者メモから選んで足した台帳は**別**で、右のボタンから開きます（RX3-0310）。
        cap_row = QHBoxLayout()
        cap_row.setContentsMargins(0, 0, 0, 0)
        self.reachable_cap = QLabel("行ってみる？")
        self.reachable_cap.setStyleSheet(MUTED)
        cap_row.addWidget(self.reachable_cap, 1)
        # ⚠⚠ 2026-09-20（RX3-0313）依頼者「『自分で足した分』ボタンを『管理』ボタンに変えて、
        #   別画面で終了したのは消し込みたい」→ ★自動で出た分も、この窓から消せます。
        self.go_button = QPushButton(GO_BUTTON)
        self.go_button.setToolTip(
            "★「行ってみる？」をまとめて面倒を見ます" + chr(10)
            + "★自分で足した分（勇者メモから）と、下の 1 行（自動で出る分）の両方" + chr(10)
            + "★[行った] で一覧から消えます（⚠ 記録は消しません / 戻せます）")
        self.go_button.clicked.connect(self.open_go_list)
        cap_row.addWidget(self.go_button)
        root.addLayout(cap_row)
        self.reachable_line = QLabel("")
        self.reachable_line.setWordWrap(True)
        self.reachable_line.setToolTip(
            "★勇者が知っていて、まだ行っていない場所\n"
            "⚠ 話に出た場所と、追っている話に出てくる場所だけです")
        root.addWidget(self.reachable_line)

        self.reload()

    # --- ★評価 -----------------------------------------------------------

    def _make_council(self):
        if self._council is not None:
            return self._council
        from dq3.knowledge.council import Council

        # ★2026-09-27（RX3-0432 / RX3-0434）: 人が書いた勇者メモ（`data/dq3/hero-memo.yaml`）で動かす。
        #   ⚠ 第三者由来の Guide Master（input/）は窓からは読みません。
        self._council = Council()
        return self._council

    def open_go_list(self):
        """★「行ってみる？」の管理を開く（RX3-0310 → RX3-0313 / ⚠ 2 つ開かない）。

        ★自動で出た分（`view.reachable`）も渡します（⚠ 消し込めるように）。
        """
        rows = self._auto_rows()
        got = getattr(self, "_go_window", None)
        if got is None:
            from .go_window import Dq3GoWindow

            got = self._go_window = Dq3GoWindow(self.vm, parent=self,
                                                place_of=self._place_name,
                                                auto_rows=rows)
        else:
            got.auto_rows = rows                 # ★開くたびに最新へ
        got.refresh()
        got.show()
        got.raise_()
        return got

    def _auto_rows(self) -> list:
        """★自動で出た「行ってみる？」（⚠ 消し込みで省く前の**全部**）。"""
        return list(getattr(getattr(self, "view", None), "reachable", ()) or ())

    def _place_name(self, location_id):
        """★`L9` → 場所の名前（⚠ 分からなければ `None` / ★そのまま id を出す）。"""
        book = getattr(self.vm, "location_book", None)
        loc = getattr(book, "locations", {}).get(location_id) if book is not None else None
        return loc.name() if loc is not None else None

    def reload(self) -> None:
        """★評価し直して描く（⚠ 開いたときと [更新] のときだけ / §25）。"""
        keep = self.current_id()
        self.view = self._make_council().evaluate()
        self.render(self.view, keep=keep)

    def render(self, view, keep: str | None = None) -> None:
        """★view を描く（⚠ 判断しない）。"""
        self.view = view
        if not view.ok:
            self.head_message.setText("⚠ 勇者メモ（hero-memo.yaml）を読めません")
            self.head_sub.setText("")
            self.head_reasons.setText(view.error)
            self.status_label.setText("")
            self.list.clear()
            self._render_detail(None)
            return

        head = view.head
        if head is None:
            self.head_message.setText("まだ対応中の話がありません")
            self.head_sub.setText("会話を聞くと、ここに次の目安が出ます")
            self.head_reasons.setText("")
        else:
            self.head_message.setText(head["message"])
            self.head_sub.setText("%s ・ %s ・ 手がかり %d 件" % (
                head["title"], _category_label(head["category"]), head["clue_count"]))
            self.head_reasons.setText("\n".join("・" + r for r in head["reasons"]))
        self.status_label.setText("Topic %d 件 / Fact %d 件" % (view.topic_count, view.fact_count))

        self.list.blockSignals(True)
        self.list.clear()
        self._cards = {}
        pick = 0
        for i, (kind, text, card) in enumerate(list_rows(view)):
            item = QListWidgetItem(text)
            if kind == "separator":
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setData(Qt.ItemDataRole.UserRole, SEPARATOR)
            else:
                item.setData(Qt.ItemDataRole.UserRole, card["topic_id"])
                self._cards[card["topic_id"]] = card
                if keep and card["topic_id"] == keep:
                    pick = i
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(pick)
        else:
            self._render_detail(None)
        self._render_reachable(view)

    def copy_adventure_log(self) -> str:
        """★冒険ログを clipboard へ（RX3-0150）。⚠ 送信はしません。

        戻り値は入れたテキスト（★検査が中身を見られるように）。
        """
        from dq3.knowledge import adventure_log as AL

        try:
            text = AL.build()
        except Exception as err:                           # noqa: BLE001 - ★画面は落とさない
            text = "⚠ 冒険ログを作れませんでした: %s" % err
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(text)
            self.copy_button.setText("コピーしました")
            QTimer.singleShot(1800, lambda: self.copy_button.setText("冒険ログをコピー"))
        except Exception:                                  # noqa: BLE001
            pass
        return text

    def _render_reachable(self, view) -> None:
        """★「行ってみる？」の 1 行（⚠ 0 件なら節ごと消す / RX3-0113）。"""
        rows = list(getattr(view, "reachable", ()) or ())
        # ★★ 人が「もう済んだ」と消し込んだ分は出さない（RX3-0313）
        mine = 0
        try:
            rows = self.vm.go_list.keep_rows(rows)
            mine = len(self.vm.go_items())
        except Exception:                                  # noqa: BLE001 ★台帳が無いだけ
            mine = 0
        show = bool(rows)
        # ★自分で足した分（RX3-0310）が 1 件でもあれば、⚠ 見出しとボタンは残す
        #   （★自動の 1 行が 0 件でも、人が足した一覧へ行けなくなると困る）
        total = mine + len(rows)
        self.go_button.setText(("%s %d" % (GO_BUTTON, total)) if total else GO_BUTTON)
        self.reachable_cap.setVisible(show or bool(mine))
        self.go_button.setVisible(show or bool(mine))
        self.reachable_line.setVisible(show)
        if not show:
            return
        self.reachable_line.setText(
            " ／ ".join("%s（%s）" % (r.name, r.why_text) for r in rows))

    # --- ★詳細 -----------------------------------------------------------

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        if item is None:
            return None
        got = item.data(Qt.ItemDataRole.UserRole)
        return None if got == SEPARATOR else got

    def _picked(self, _row: int) -> None:
        self._render_detail(self._cards.get(self.current_id() or ""))

    def _render_detail(self, card: dict | None) -> None:
        box = self._body_box
        while box.count():
            item = box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if card is None or self.view is None:
            box.addWidget(QLabel("左の一覧から話を選ぶと、ここに中身が出ます"))
            box.addStretch(1)
            return
        title = QLabel(card["title"])
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        title.setWordWrap(True)
        box.addWidget(title)
        for label, text in detail_lines(card, self.view):
            cap = QLabel(label)
            cap.setStyleSheet(MUTED)
            box.addWidget(cap)
            body = QLabel(text)
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(body)
        box.addStretch(1)


def _category_label(category: str) -> str:
    from dq3.knowledge.council import CATEGORY_LABEL

    return CATEGORY_LABEL.get(category, category)
