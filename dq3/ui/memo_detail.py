"""勇者メモ詳細（RX3-0058 §17-21 / RX3-0118）: 勇者メモを MAP で絞って読む。

★出すのは**遊んで得たこと**だけ。⚠ ROM の未会話の情報は出さない。

## ⚠⚠ 2026-09-08: ここだけ別のものを見ていました（RX3-0118）

```text
MAP の 3 行    MemoBook  ★新しい順
[すべて]       MemoBook  ★新しい順
[メモ詳細]     ⚠⚠ 会話の台帳（npc-conversations.json） / ⚠⚠ **古い順**
```

→ ⚠ NPC の会話**だけ**が出て、★場所を知ったメモなどが入りませんでした。
→ ⚠ 先頭が他の 2 画面と違いました。

★いまは 3 つとも `MemoBook.newest()` を見ます。
⚠ 会話の台帳は**一次証跡**として残し、★「何回聞いたか / いつ初めて聞いたか」
だけを添えます（⚠ 表示の正本にはしない）。
"""
from __future__ import annotations

import functools

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QTextEdit, QVBoxLayout)

from . import icon_button, icons, theme

ALL = "すべて"

#: ★本文の欄の高さ（⚠ 小さいと「選ぶ所」だと分からない / RX3-0317）
#:
#:   ⚠⚠ 依頼者「メモの一部を選択したいが、メモを全部追加しか出来ない」。
#:   ★選ぶ仕組みそのものは動いていました（⚠ 画面外の検査で取れる）。
#:   → ★3 行ぶんの高さと枠と見出しを付けて、**選ぶ所だと分かる**ようにします。
BODY_PX = 66


def place_name(vm, map_id: int) -> str:
    """★訪れて名前を知っていればそれ、⚠ 知らなければ番号だけ。

    ⚠ 地名は `Dq3ViewModel.place_name()` だけから取ります（★入口を 1 本に / RX3-0094）。
    """
    try:
        got = vm.place_name(map_id)
    except Exception:                                    # noqa: BLE001
        got = None
    return got or ("map %d" % map_id)


def body_of(text) -> str:
    """★かぎかっこの中だけ（⚠ 突き合わせ用。★話者や `＊` を落とす）。

    ★RX3-0253: 記録（`＊「…＊「…」`）から切るので、続きの段の `＊` は先に落とす（★台帳の側も同じ関数で揃う）。
    """
    from .models import strip_speech_marks

    got = strip_speech_marks((text or "").strip())
    cut = got.find("「")
    if cut >= 0:
        got = got[cut + 1:]
    return got.rstrip("」")


def speaker_of(service, memo) -> str:
    """★誰の話か。⚠ 分からなければ `？`（⚠⚠ `＊` にしない / RX3-0118）。

    ```text
    1 メモに残っている話者          ★聞き込みはここで決まる
    2 (map, npc) → 見た目のラベル   ★古い記録の救済
    3 ？                            ⚠ 分からないことを分かるように出す
    ```
    """
    from .models import UNKNOWN_SPEAKER

    got = memo.speaker_label
    if got != UNKNOWN_SPEAKER:
        return got
    if memo.map_id is None or memo.npc_id is None:
        return UNKNOWN_SPEAKER
    try:
        from dq3.knowledge import npc_master

        map_id, npc_id = int(memo.map_id), int(memo.npc_id)
        for kind in (None, 0x90):
            master = npc_master.master_for(map_id, kind)
            npc = next((n for n in master.get("npcs", []) if n["npc_id"] == npc_id), None)
            if npc is not None:
                return service.appearance_label(npc["appearance_id"])
    except Exception:                                    # noqa: BLE001
        pass                                             # ⚠ 分からないだけ。★落とさない
    return UNKNOWN_SPEAKER


def _evidence(service, map_ids=None) -> dict:
    """★会話の台帳（一次証跡）を `(map, npc, 本文)` で引ける形に。

    ⚠ 読めなくても構いません（★空で返す）。表示の正本ではないので。
    """
    out: dict = {}
    try:
        for r in service.heard_timeline(map_ids):
            out.setdefault((int(r["map_id"]), int(r["npc_id"]), body_of(r["text"])), r)
    except Exception:                                    # noqa: BLE001
        return {}
    return out


def timeline_rows(service, vm, map_ids=None) -> list[dict]:
    """★詳細画面の行。

    ⚠⚠ **並びは `MemoBook.newest()`（新しい順）**。★他の 2 画面と同じ 1 本です。
    ⚠ ここで `sorted(...)` を書かないこと（RX3-0118 で食い違いの元になった）。
    """
    memos = vm.memos.newest()
    if map_ids is not None:
        want = set(map_ids)
        memos = [m for m in memos if m.map_id in want]
    seen = _evidence(service, map_ids)
    rows = []
    for m in memos:
        # ★突き合わせは記録（`m.text`）で（RX3-0253 / ⚠ 表示の行は「」を出さないので、かぎかっこで切れない）
        body = body_of(m.text)
        got = seen.get((int(m.map_id), int(m.npc_id), body)) if (
            m.map_id is not None and m.npc_id is not None) else None
        rows.append({
            "order": m.order, "map_id": m.map_id, "npc_id": m.npc_id,
            "source": m.source, "text": m.line, "body": body,
            "label": speaker_of(service, m),
            "place": place_name(vm, m.map_id) if m.map_id is not None else "",
            # ★証跡（⚠ 無ければ空。★「0 回」とは書かない）
            "talk_id": (got or {}).get("talk_id"),
            "count": (got or {}).get("count"),
            "first_heard_at": (got or {}).get("first_heard_at") or "",
        })
    return rows


# --- ★★ 自由文言の検索（RX3-0289 / 2026-09-18 依頼者「grep のように」）------
#
#   ★探す先は **本文 ＋ 話した相手 ＋ 場所**（⚠ 「どこで聞いたか」でも探せるように）。
#   ★スペース区切りは**すべて含む（AND）**（⚠ grep をパイプでつなぐつもりで打てる）。
#   ⚠ **正規表現は使いません**（★打ち間違いで 0 件になるより、部分一致のほうが素直）。
#   ⚠ Qt を使わない = 画面なしで確かめられる（★`row_cells` と同じ作法 / RX3-0254）。

#: ★探す先の欄（⚠ ここに無い欄は当たらない）
SEARCH_FIELDS = ("text", "body", "label", "place")

#: ★0 件のときに出す文（⚠ 空欄にしない）
NO_MATCH = "条件に一致するメモはありません"


@functools.lru_cache(maxsize=4096)
def _norm(text: str) -> str:
    """★探すための正規化（RX3-0295 / 2026-09-18）。

    ⚠⚠ DQ3 の文字表は**カタカナの「リ」を持たず、ひらがなの「り」の絵を使い回します**。
      ★だから画面から読んだ名前は `…り…`（ひらがな）になります（⚠ 化けではない）。

    ```text
    記録   ＊「… <カタカナの名前の「リ」が「り」で入っている> …
    検索   <カタカナの名前>   ⚠⚠ 小文字にそろえるだけでは 1 件も出ない
    ```

    ⚠⚠ **見本に原作の台詞と人名を書きません**（RX3-0433 / 2026-10-01）。
      ★`docs/00-project-policy.md` §3 / ⚠ この docstring は配布物に入ります。

    ★`concepts.fold`（カタカナ → ひらがな ＋ 飾りを落とす）を通します。
    ⚠⚠ これは「ROM 自身が表ではひらがな・会話ではカタカナと綴りを変える」ために
      既にあるものです（★新しい規則を作らない）。
    ⚠ **探す語と探される文字の両方**を通すこと（★片側だけだと必ず割れる）。
    """
    from ..knowledge import concepts

    return concepts.fold(str(text or "")).lower()


def haystack(row: dict) -> str:
    """★1 行ぶんの「探される文字」（⚠ かなを畳んで小文字にそろえる）。"""
    return _norm(" ".join(str(row.get(k) or "") for k in SEARCH_FIELDS))


def matches(row: dict, word: str) -> bool:
    """★スペース区切りの語を**すべて**含むか（⚠ 空なら全部通す）。"""
    # ⚠ 区切りは**畳む前**に切る（★`fold` はスペースを落とす）
    # ★畳むと空になる語（`「」` など飾りだけ）は落とす。
    #   ⚠⚠ これは**絞り込みの結果を変えません**（★空文字はどの行にも含まれるので、
    #     残しても同じ答えになる。★壊す実験で確かめた）。
    #     ⚠ 効くのは「条件が 1 つも無い」と分かって、★探される文字を作らずに済むことだけ。
    words = [w for w in (_norm(w) for w in (word or "").split()) if w]
    if not words:
        return True
    hay = haystack(row)
    return all(w in hay for w in words)


def filter_rows(rows, word: str) -> list:
    """★絞ったあとの行（⚠ 並びは変えない / ★新しい順のまま / RX3-0118）。"""
    return [r for r in rows if matches(r, word)]


class MemoDetailDialog(QDialog):
    def __init__(self, vm, service, parent=None) -> None:
        super().__init__(parent)
        self.vm = vm
        self.service = service
        self.setWindowTitle("勇者メモ詳細 — RetroUX DQ3")
        self.resize(520, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("MAP"))
        self.map_select = QComboBox()
        self.map_select.currentIndexChanged.connect(lambda _i: self.refresh())
        top.addWidget(self.map_select, 1)
        self.here_only = QCheckBox("今いるMAP")
        self.here_only.toggled.connect(self._on_here_toggled)
        top.addWidget(self.here_only)
        root.addLayout(top)

        # ★★ 自由文言の検索（RX3-0289）。⚠ 実行ボタンは置かない（★打つそばから絞る / RX3-0254）
        find = QHBoxLayout()
        find.addWidget(QLabel("検索"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("本文・相手・場所（スペースで AND）")
        self.search_edit.setClearButtonEnabled(True)
        # ★虫眼鏡は**欄の中**に置きます（RX3-0325）。
        #   ⚠⚠ ボタンにはしません（★押す物が増えると「押さないと絞れない」と誤解されるため /
        #     `RX3-0254` の「実行ボタンは置かない」を守る）。
        self.search_edit.addAction(
            icons.icon("search", theme.MUTED, icon_button.ICON_PX),
            QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.setToolTip(
            "★本文・話した相手・場所から探します" + chr(10)
            + "★スペースで区切ると**すべて含む**もの（AND）" + chr(10)
            + "⚠ 正規表現は使えません（★部分一致です）")
        self.search_edit.textChanged.connect(lambda _t: self.refresh())
        find.addWidget(self.search_edit, 1)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#8a93a5;")
        find.addWidget(self.count_label)
        root.addLayout(find)

        self.list = QListWidget()
        self.list.setWordWrap(True)                      # ★本文は折り返す（§18-1）
        self.list.currentRowChanged.connect(lambda _i: self._show_body())
        root.addWidget(self.list, 1)

        # ★★ 選んだメモの本文（★ここだけ**マウスで文字を選べる** / RX3-0310）★★
        #
        #   ⚠⚠ 一覧（`QListWidget`）では**一部分だけ**を選べません。
        #   ⚠ MAP の下の勇者メモは「…」で省略した字なので、★そこからも取れません。
        #   → ★選んだ 1 件の**全文**をここに出し、⚠ この欄から選んでもらいます。
        #
        #   ⚠⚠ 2026-09-20（RX3-0317）依頼者「メモの一部を選択したいが、メモを全部追加しか出来ない」。
        #     ★選ぶ仕組みは動いていました（⚠ 画面外の検査で取れる）。
        #     → ⚠ **この欄が小さくて、選ぶ所だと分からなかった**のが実際の所です。
        #       ★見出しを付け、⚠ 高さを 3 行ぶんにして、枠で囲みました。
        self.body_cap = QLabel("★ここで文の一部をマウスで選べます")
        self.body_cap.setStyleSheet("color:#8a93a5; font-size:11px;")
        root.addWidget(self.body_cap)

        # ⚠⚠ 2026-09-20（RX3-0319）依頼者「テキスト範囲選択みたいなのができない」（★2 度目の報告）。
        #   ★`QLabel` ＋ `TextSelectableByMouse` は**環境によって渋い**（⚠ 画面外の検査では取れていた）。
        #   → ★**読み取り専用の `QTextEdit`** に替えます。
        #     ★文字カーソルが出て、⚠ 「なぞれる所」だとひと目で分かります。
        #     ★長い文は自分でスクロールします（⚠ 欄の高さで切れない）。
        self.body = QTextEdit()
        self.body.setReadOnly(True)                 # ⚠ 直せない（★記録は変えない）
        self.body.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                          | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.body.setStyleSheet(
            "color:#c8d0df; border:1px solid #3a4150; border-radius:4px;")
        self.body.setMinimumHeight(BODY_PX)
        self.body.setMaximumHeight(BODY_PX * 2)
        root.addWidget(self.body)

        go = QHBoxLayout()
        self.go_hint = QLabel("★文の一部を選んで足せます（⚠ 選んでいなければ 1 件まるごと）")
        self.go_hint.setStyleSheet("color:#8a93a5; font-size:11px;")
        go.addWidget(self.go_hint, 1)
        self.go_button = QPushButton("行ってみる？に追加")
        self.go_button.setToolTip(
            "★選んだ文を「行ってみる？」に足します" + chr(10)
            + "⚠ 元の勇者メモは変わりません（★記録はそのまま残ります）")
        self.go_button.clicked.connect(self.add_to_go_list)
        go.addWidget(self.go_button)
        self.go_list_button = QPushButton("一覧")
        self.go_list_button.setToolTip("★足した「行ってみる？」の一覧を開きます")
        self.go_list_button.clicked.connect(self.open_go_list)
        go.addWidget(self.go_list_button)
        root.addLayout(go)

        self.reload_maps()
        self.refresh()

    # ------------------------------------------------------------------
    def current_map_id(self):
        at = self.vm.position()
        from dq3.knowledge.seen_map import is_local

        if at is None or at[1] is None or not is_local(at[0]):
            return None
        return int(at[1])

    def reload_maps(self) -> None:
        self.map_select.blockSignals(True)
        self.map_select.clear()
        self.map_select.addItem(ALL, None)
        # ⚠ 「会話のある MAP」ではなく★**メモのある MAP**（RX3-0118）
        for m in self.vm.memos.maps():
            self.map_select.addItem(place_name(self.vm, m), m)
        self.map_select.blockSignals(False)

    def _on_here_toggled(self, on: bool) -> None:
        self.map_select.setEnabled(not on)              # ★ON のときは MAP 選択を使わない（§19-2）
        self.refresh()

    def selected_maps(self):
        if self.here_only.isChecked():
            here = self.current_map_id()
            return {here} if here is not None else set()
        chosen = self.map_select.currentData()
        return None if chosen is None else {chosen}

    def search_word(self) -> str:
        return self.search_edit.text() if hasattr(self, "search_edit") else ""

    def refresh(self) -> None:
        self.list.clear()
        found = timeline_rows(self.service, self.vm, self.selected_maps())
        # ★文言で絞る（RX3-0289 / ⚠ 並びは変えない）
        rows = filter_rows(found, self.search_word())
        if hasattr(self, "count_label"):
            # ⚠ 絞っているときだけ「◯/◯ 件」（★素のときは件数だけ）
            self.count_label.setText(
                ("%d / %d 件" % (len(rows), len(found))) if self.search_word().strip()
                else ("%d 件" % len(found)))
        for r in rows:
            # ⚠ 本文は `Memo.line` のまま（★他の 2 画面と同じ字面 / RX3-0118）
            text = r["text"] + ("　― %s" % r["place"] if r["place"] else "")
            item = QListWidgetItem(text)
            item.setToolTip(self._tip(r))
            # ★行 → 元のメモ（RX3-0310 / ⚠ 「行ってみる？」が出典を失わないため）
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.list.addItem(item)
        if not rows:
            # ⚠ 「まだ無い」と「探したが無い」を混ぜない（★条件はそのまま残す / RX3-0254 §6）
            self.list.addItem(QListWidgetItem(
                NO_MATCH if (found and self.search_word().strip()) else "（まだありません）"))
        self._show_body()

    # --- ★★ 行ってみる？へ足す（RX3-0310）---------------------------------

    def current_row(self) -> dict | None:
        """★いま選んでいるメモの行（⚠ 「（まだありません）」の行は `None`）。"""
        item = self.list.currentItem()
        if item is None:
            return None
        got = item.data(Qt.ItemDataRole.UserRole)
        return got if isinstance(got, dict) else None

    def _show_body(self) -> None:
        """★選んだメモの全文を、⚠ **省略せずに**下の欄へ出す。"""
        if not hasattr(self, "body"):
            return
        row = self.current_row()
        if row is None:
            self.body.setPlainText("")
            self.go_button.setEnabled(False)
            return
        where = "　― %s" % row["place"] if row["place"] else ""
        self.body.setPlainText(row["text"] + where)
        self.go_button.setEnabled(True)

    def selected_text(self) -> str:
        """★いま**なぞっている**文（⚠ 何も選んでいなければ空）。

        ⚠ `QTextEdit` の選択は `textCursor().selectedText()`。
        ★行を折り返すと ` `（段落の区切り）が混ざるので、⚠ 空白へ直します。
        """
        body = getattr(self, "body", None)
        if body is None:
            return ""
        got = body.textCursor().selectedText()
        return " ".join(str(got or "").replace(" ", " ").split())

    def go_text(self) -> str:
        """★足す文（★選んでいればその部分 / ⚠ 選んでいなければ 1 件まるごと）。"""
        picked = self.selected_text()
        if picked:
            return picked
        row = self.current_row()
        return (row or {}).get("body") or (row or {}).get("text") or ""

    #: ★確認の窓を出すか（⚠ 検査では False にして止まらないようにする）
    CONFIRM = True

    def _confirm_add(self, text: str) -> bool:
        """★足す前の**簡易確認**（依頼者 §4）。

        ```text
        「その先に小さな村があるらしい。」
        [追加] [キャンセル]
        ```
        ⚠ 大きな編集の窓は出しません（★依頼者 §4）。
        """
        if not self.CONFIRM:
            return True
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("行ってみる？に追加")
        box.setText("「%s」" % text)
        add = box.addButton("追加", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(add)
        box.exec()
        return box.clickedButton() is add

    def add_to_go_list(self) -> object:
        """★「行ってみる？に追加」。⚠ 元の勇者メモは**変えません**（依頼者 §2-1）。"""
        row = self.current_row()
        if row is None:
            return None
        from dq3.knowledge import go_list as GL

        text = GL.clean_text(self.go_text())
        if not text:
            return None
        if not self._confirm_add(text):
            self.go_hint.setText("⚠ やめました")
            return None
        got = self.vm.add_go_item(
            text, source_memo_id=row.get("order"),
            source_location_id=self._location_id_of(row.get("map_id")))
        if got is not None:
            self.go_hint.setText("★「%s」を足しました" % got.display_text)
        return got

    def open_go_list(self):
        """★「行ってみる？」の一覧を開く（⚠ 2 つ開かない）。"""
        got = getattr(self, "_go_window", None)
        if got is None:
            from .go_window import Dq3GoWindow

            got = self._go_window = Dq3GoWindow(self.vm, parent=self)
        got.refresh()
        got.show()
        got.raise_()
        return got

    def select_memo(self, order: int) -> bool:
        """★その勇者メモの行を選ぶ（★一覧から元メモへ戻る道 / 依頼者 §8）。

        ⚠ 絞り込みで隠れていることがあるので、★見つからなければ**条件を外して**もう一度探す。
        """
        if self._pick_row(order):
            return True
        # ⚠ 検索と MAP の絞りを外す（★隠れているだけのことが多い）
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.here_only.blockSignals(True)
        self.here_only.setChecked(False)
        self.here_only.blockSignals(False)
        self.map_select.blockSignals(True)
        self.map_select.setCurrentIndex(0)
        self.map_select.setEnabled(True)
        self.map_select.blockSignals(False)
        self.refresh()
        return self._pick_row(order)

    def _pick_row(self, order: int) -> bool:
        for i in range(self.list.count()):
            got = self.list.item(i).data(Qt.ItemDataRole.UserRole)
            if isinstance(got, dict) and got.get("order") == order:
                self.list.setCurrentRow(i)
                return True
        return False

    def _location_id_of(self, map_id):
        """★聞いた場所（⚠ 分からなければ `None`。★無理に結び付けない / 依頼者 §7）。"""
        if map_id is None:
            return None
        try:
            return self.vm.location_book.location_id_of(int(map_id))
        except Exception:                                  # noqa: BLE001 ★出典が無いだけ
            return None

    @staticmethod
    def _tip(r: dict) -> str:
        """★ヒント。⚠ 分からない証跡は**書かない**（★「0 回」と嘘を出さない）。"""
        bits = ["話した相手: %s" % r["label"]]
        if r["first_heard_at"]:
            bits.append("初めて聞いた: %s" % r["first_heard_at"])
        if r["count"]:
            bits.append("%d 回" % r["count"])
        if r["talk_id"] is not None:
            bits.append("talk %s" % r["talk_id"])
        return " / ".join(bits)
