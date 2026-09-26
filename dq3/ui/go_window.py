"""「行ってみる？」の管理（RX3-0310 → RX3-0313 / 2026-09-20）。

★ここで**2 種類**をまとめて面倒を見ます。

```text
自分で足した分  ★勇者メモから人が選んだ文（★台帳に残る / id と DONE がある）
自動で出た分    ★勇者が知っていて、まだ行っていない場所（`reachable.collect`）
                ⚠⚠ 毎回計算する派生なので、★状態を持てません
```

## ⚠⚠ 依頼者 2026-09-20

> 勇者会議 行ってみるで既に完了している部分は、「自分で足した分」ボタンを「管理」ボタンに変えて、
> 別画面で終了したのは消し込みたい。

→ ★どちらも [行った] で一覧から消えます。⚠ どちらも**データは消しません**。

```text
自分で足した分  status = DONE（★completed_at が入る）
自動で出た分    ★「消した」という人の判断だけを覚える（`GoList.dismissed`）
```

★[済んだ分も見る] で見返せます（⚠ 間違えたら [戻す]）。

## ⚠ 名前しか無い行は消せません

★消した印は**場所の id**（`L9` など）で持ちます。
⚠ 名前しか無い行を名前で消すと、★同じ名前の別の場所まで巻き込みます。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

EMPTY = "（まだありません。★勇者メモ詳細で文を選んで足せます）"
EMPTY_DONE = "（済んだものはまだありません）"
#: ★節の見出し（⚠ 押せない行）
HEAD_MINE = "── 自分で足した分 ──"
HEAD_AUTO = "── 自動で出た分 ──"
#: ⚠ 消せない行に添える字（★理由を出す / 黙って押せなくしない）
NO_ID = "（場所が決まっていないので消せません）"


def source_line(item, place_of=None) -> str:
    """★出典の 1 行（★場所・元のメモ）。⚠ 分からないものは**書きません**。"""
    bits = []
    if item.source_location_id:
        name = None
        if place_of is not None:
            try:
                name = place_of(item.source_location_id)
            except Exception:                                  # noqa: BLE001
                name = None
        bits.append(name or item.source_location_id)
    if item.source_memo_id is not None:
        bits.append("勇者メモ #%d" % int(item.source_memo_id))
    if item.target_location_id:
        bits.append("行き先 %s" % item.target_location_id)
    return "・".join(bits)


def auto_line(row) -> str:
    """★自動で出た 1 行（★`Reachable`）。"""
    why = getattr(row, "why_text", "") or ""
    return "%s%s" % (row.name, "（%s）" % why if why else "")


class Dq3GoWindow(QDialog):
    """★「行ってみる？」の管理（⚠ 判断はしない。★出して、終えるだけ）。"""

    def __init__(self, vm, parent=None, place_of=None, auto_rows=()) -> None:
        super().__init__(parent)
        self.vm = vm
        self.place_of = place_of
        self.auto_rows = list(auto_rows or ())
        self.setWindowTitle("行ってみる？ — RetroUX DQ3")
        self.resize(440, 460)
        # ⚠ フォーカスを奪わない（★奪うとゲームを操作できなくなる / DQ2 の知見）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        root = QVBoxLayout(self)
        head = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#8a93a5;")
        head.addWidget(self.count_label, 1)
        self.show_done = QCheckBox("済んだ分も見る")
        self.show_done.toggled.connect(lambda _on: self.refresh())
        head.addWidget(self.show_done)
        root.addLayout(head)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        # ★項目（出典を含む）をクリックしたら元の勇者メモへ（依頼者 §8）
        #   ⚠ 1 回のクリックで窓が飛び出すとうるさいので、★ダブルクリックにします。
        self.list.itemDoubleClicked.connect(lambda _i: self.open_source_memo())
        self.list.currentRowChanged.connect(lambda _i: self._sync_buttons())
        # ★四角を押したら [行った] と同じ（RX3-0353 / ⚠ `refresh` の最中は無視する）
        self._refreshing = False
        self.list.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.list, 1)

        row = QHBoxLayout()
        # ★★ あとから文を直す（RX3-0317 / 2026-09-20）
        #   ⚠⚠ 依頼者「メモの一部を選択したいが、メモを全部追加しか出来ない
        #     → 全部追加してから、メンテできる機能があってもいい」。
        #   ★出典（元のメモ・場所）は**そのまま**です。
        self.edit_button = QPushButton("文を直す")
        self.edit_button.setToolTip(
            "★一覧に出る文を書き直します" + chr(10)
            + "★メモをまるごと足したあと、要る所だけ残せます" + chr(10)
            + "⚠ 元の勇者メモは変わりません（★出典も残ります）")
        self.edit_button.clicked.connect(self.edit_current)
        row.addWidget(self.edit_button)
        self.memo_button = QPushButton("元のメモ")
        self.memo_button.setToolTip("★この話を聞いた勇者メモを出します（⚠ メモ詳細が開きます）")
        self.memo_button.clicked.connect(self.open_source_memo)
        row.addWidget(self.memo_button)
        row.addStretch(1)
        self.done_button = QPushButton("行った")
        self.done_button.setToolTip("★一覧から消します（⚠ 記録は残ります / あとで見返せます）")
        self.done_button.clicked.connect(self.complete_current)
        row.addWidget(self.done_button)
        root.addLayout(row)

        self.refresh()

    # ------------------------------------------------------------------
    def current_item(self):
        """★いま選んでいるもの（★`GoItem` か `Reachable` / ⚠ 見出しの行は `None`）。"""
        got = self.list.currentItem()
        return None if got is None else got.data(Qt.ItemDataRole.UserRole)

    def _add(self, text, payload=None, tip=None, *, checked=None) -> None:
        """★1 行足す。`checked` を渡すと**本物の四角**になります（RX3-0353）。

        ⚠⚠ 2026-09-21 依頼者「行ってみる？の四角をチェックしても消せない」。
          ★以前の □ / ☑ は**ただの文字**で、押しても何も起きませんでした。
          → ★押せる四角にして、⚠ 押したら [行った] と同じことをします。
        """
        item = QListWidgetItem(text)
        if tip:
            item.setToolTip(tip)
        # ⚠⚠ **先に一覧へ入れてから**印を付けます。★そうすると `itemChanged` が鳴るので、
        #   ⚠ `_refreshing` の歯止めが**本当に要る**状態になります
        #   （★2026-09-21 の壊す実験: 入れる前に付けていたため、歯止めを外しても
        #    検査が緑のままでした = **効いていない歯止め**でした）。
        self.list.addItem(item)
        if payload is None:
            item.setFlags(Qt.ItemFlag.NoItemFlags)      # ⚠ 見出し・案内は選べない
            return
        item.setData(Qt.ItemDataRole.UserRole, payload)
        if checked is not None and self._can_finish(payload):
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked
                               else Qt.CheckState.Unchecked)
        else:
            # ⚠⚠ Qt の既定の旗には `ItemIsUserCheckable` が**入っています**。
            #   ★消せない行に四角を出さないよう、⚠ ここで落とします
            #   （★四角そのものは `CheckStateRole` を置いたときだけ出ますが、
            #    ⚠ 旗も落としておかないと「押せる」と読めてしまいます）。
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)

    def _on_item_changed(self, item) -> None:
        """★四角を押した（RX3-0353）。⚠ [行った] / [戻す] と**同じ道**を通します。

        ⚠⚠ `refresh()` の最中にも鳴るので、★そのあいだは無視します
          （⚠ そうしないと、一覧を作り直すたびに勝手に消し込みます）。
        """
        if self._refreshing:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if payload is None or not self._can_finish(payload):
            return
        want_done = item.checkState() == Qt.CheckState.Checked
        back = self.show_done.isChecked()
        # ⚠ 「済んだ分も見る」では ☑ が既定なので、★外したときが「戻す」
        if want_done == (not back):
            self._finish(payload, back=back)
        else:
            self.refresh()                               # ⚠ 何もしない押し方 → 見た目を戻す

    def refresh(self) -> None:
        self._refreshing = True                          # ⚠ 作り直しの間は四角の合図を無視
        try:
            self._refresh()
        finally:
            self._refreshing = False
        self._sync_buttons()

    def _refresh(self) -> None:
        self.list.clear()
        done = self.show_done.isChecked()
        book = self.vm.go_list
        mine = self.vm.go_items(done=done)
        auto = (book.dropped_rows(self.auto_rows) if done
                else book.keep_rows(self.auto_rows))

        self.count_label.setText(
            ("済んだ %d 件" % (len(mine) + len(auto))) if done
            else ("行ってみる？ %d 件" % (len(mine) + len(auto))))

        # ★四角は**本物**です（RX3-0353 / ⚠ 押したら [行った] と同じ）
        if mine:
            self._add(HEAD_MINE)
            for item in mine:
                where = source_line(item, self.place_of)
                text = item.display_text
                if where:
                    text += "\n　　%s" % where
                self._add(text, item, tip=where or None, checked=not item.active)
        if auto:
            self._add(HEAD_AUTO)
            for r in auto:
                text = auto_line(r)
                if r.location_id is None:
                    text += "\n　　%s" % NO_ID
                self._add(text, r, checked=done,
                          tip="⚠ 自動で出ている分です（★消すと出なくなります）")
        if not mine and not auto:
            self._add(EMPTY_DONE if done else EMPTY)
        self.done_button.setText("戻す" if done else "行った")

    def _sync_buttons(self) -> None:
        got = self.current_item()
        self.memo_button.setEnabled(hasattr(got, "source_memo_id"))
        # ⚠ 自動で出た分は直せません（★毎回計算しているので、直しても次で戻る）
        self.edit_button.setEnabled(hasattr(got, "id") and got.active)
        self.done_button.setEnabled(got is not None and self._can_finish(got))

    @staticmethod
    def _can_finish(got) -> bool:
        """⚠ 名前しか無い自動の行は消せない（★場所の id が要る）。"""
        if hasattr(got, "id"):
            return True                                   # ★自分で足した分
        return getattr(got, "location_id", None) is not None

    def _finish(self, got, *, back: bool) -> bool:
        """★消し込む / 戻す（⚠ ボタンと四角の**共通の道** / RX3-0353）。"""
        if hasattr(got, "id"):                            # ★自分で足した分
            ok = self.vm.reopen_go_item(got.id) if back else self.vm.complete_go_item(got.id)
        else:                                             # ★自動で出た分
            ok = self.vm.dismiss_reachable(got.location_id, restore=back)
        if ok:
            self.refresh()
        return ok

    def complete_current(self) -> bool:
        """★[行った]（⚠ 済んだ分を見ているときは [戻す]）。"""
        got = self.current_item()
        if got is None or not self._can_finish(got):
            return False
        return self._finish(got, back=self.show_done.isChecked())

    #: ⚠ 検査では窓を出さない（★`exec` は画面外でも待つ）
    ASK = True

    def ask_text(self, current: str):
        """★文を書き直す窓（⚠ 大きな編集画面は作らない / `NameDialog` と同じ作法）。"""
        if not self.ASK:
            return None
        from PySide6.QtWidgets import QInputDialog

        got, ok = QInputDialog.getText(self, "文を直す", "行ってみる？に出す文",
                                       text=current)
        return got if ok else None

    def edit_current(self) -> bool:
        """★[文を直す]（⚠ 自分で足した分だけ / 自動で出た分は元が計算なので直せない）。"""
        got = self.current_item()
        if got is None or not hasattr(got, "id"):
            return False
        text = self.ask_text(got.display_text)
        if text is None:
            return False
        if not self.vm.edit_go_item(got.id, text):
            return False
        self.refresh()
        return True

    def memo_view(self):
        """★勇者メモ詳細の窓を探す。

        ```text
        ★この窓を開いたのが メモ詳細        → ⚠ それ自身（`select_memo` を持っている）
        ★開いたのが 勇者会議・地図の窓など   → ★相手の `open_detail()` に開いてもらう
        ```
        ⚠ どちらでもなければ `None`（★ボタンは押せるが何も起きない）。
        """
        parent = self.parent()
        if hasattr(parent, "select_memo"):
            return parent
        opener = getattr(parent, "open_detail", None)
        return opener() if callable(opener) else None

    def open_source_memo(self):
        """★元の勇者メモを出す（⚠ 見つからなくても落ちない / 依頼者 §14 可能なら）。"""
        got = self.current_item()
        if got is None or not hasattr(got, "source_memo_id"):
            return None                                   # ⚠ 自動で出た分に元メモは無い
        dialog = self.memo_view()
        if dialog is None:
            return None
        dialog.show()
        dialog.raise_()
        if got.source_memo_id is not None:
            try:
                dialog.select_memo(int(got.source_memo_id))
            except Exception:                              # noqa: BLE001 ★出せないだけ
                pass
        return dialog


__all__ = ["Dq3GoWindow", "source_line", "auto_line", "EMPTY", "EMPTY_DONE",
           "HEAD_MINE", "HEAD_AUTO", "NO_ID"]
