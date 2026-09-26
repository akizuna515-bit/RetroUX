"""勇者メモ（直近 N 件）（RX3-0019 / 2026-08-29）。

★指示書 §7 / §9。MAP の下に置きます（⚠ MAP は別ウィンドウ）。

## ⚠⚠ 「すべて」画面は外しました（RX3-0354 / 2026-09-21）

★依頼者「勇者メモ『すべて』ボタン他と被るので不要」。
⚠ [メモ]（`memo_detail.MemoDetailDialog`）が**同じ一覧を検索つきで**出すので、
★役目が重なっていました。→ ⚠ ボタンも `MemoListDialog` も消しました。

## ⚠ 大きさを変えない

指示書 §2「戦闘開始・終了でメインウィンドウサイズを変えない」と同じ考えで、
★**件数が 0 でも場所は確保**します。⚠ 増えたり減ったりで窓が動くと使いにくい。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout)

from . import icon_button

#: ★1 行の高さ（⚠ 件数が変わっても場所を動かさないため固定する）
ROW_PX = 20


class MemoPanel(QFrame):
    """MAP の下に出す「勇者メモ」（★直近 N 件）。"""

    def __init__(self, view_model, *, limit: int = 3, pick=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self.limit = max(1, int(limit))
        # ★★ ⚠⚠ 「どのメモを出すか」を差し替えられるようにする
        #   （RX3-0024 × RX3-0016 の接続 / 2026-08-30）★★
        #
        #   ⚠ 地図を選ぶ画面でも **全体の直近**が出ていました。
        #     ★「その地図のメモが下に出る」が、実は繋がっていませんでした。
        #
        #   ⚠⚠ 絞り込みそのものは `MemoBook` が持っています。
        #     ★ここは「どれを呼ぶか」を受け取るだけにします（二重に持たない）。
        self._pick = pick
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("勇者メモ")
        title.setStyleSheet("font-weight: bold;")
        head.addWidget(title)
        head.addStretch(1)
        self._count = QLabel("")
        self._count.setStyleSheet("color: #888;")
        head.addWidget(self._count)
        root.addLayout(head)

        # ★★ ⚠⚠ ボタンは**見出しと別の行**にする（RX3-0308 / 依頼者 2026-09-20）★★
        #
        #   > 勇者会議のボタンは、勇者メモの欄にしたい。MAP が少し横に伸びてしまった
        #
        #   ★地図の窓の既定は **360 px**。⚠ ボタンを横に並べるほど最小幅がそれを超え、
        #     Qt が窓を押し広げます（★実測: 勇者会議を下の行へ置いた時点で 378 px）。
        #   → ★同じ行に足さず、**ボタンだけの行**にして右へ寄せます（⚠ 高さは 1 行分だけ増える）。
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch(1)
        # ⚠⚠ 2026-09-21（RX3-0354）: **「すべて」ボタンを外しました**。
        #   ★依頼者「勇者メモ『すべて』ボタン他と被るので不要」。
        #   ⚠ [メモ]（メモ詳細）が同じ一覧を**検索つき**で出すので、★役目が重なっていました。
        #   → ⚠ `MemoListDialog` も一緒に消しました（★押す口が無ければ死んだ画面）。
        # ★聞き込みの会話を時系列 / MAP で読む（RX3-0058 §17）。⚠ 短い名前（既存の並びを崩さない）
        #   ★★ 2026-09-20（RX3-0325）: アイコン＋「メモ」に（依頼者「表示ラベル：メモ」）。
        #     ⚠ 正式な名前（「メモ詳細」）はツールチップの 1 行目に残します。
        self._detail = icon_button.make(
            "memo", "メモ",
            "メモ詳細" + chr(10) + "聞き込みで聞いた話を時系列で読む" + chr(10) + "★MAP で絞れます",
            on_click=self.open_detail)
        buttons.addWidget(self._detail)
        # ★★ 勇者会議（RX3-0302 → RX3-0308 で勇者メモの欄へ）
        #   ⚠ 中身は変えていません（★押すと地図の窓の `open_council` を呼ぶだけ）。
        #   ★★ 2026-09-20（RX3-0325）: アイコン＋「会議」に（依頼者「表示ラベル：会議」）。
        #     ⚠ 正式な名前（「勇者会議」）はツールチップの 1 行目に残します。
        self.council_button = icon_button.make(
            "council", "会議",
            "勇者会議" + chr(10)
            + "★聞いた会話から「次にやること」と「最近動いた話」を整理します" + chr(10)
            + "⚠ 攻略の Topic は人が精査した Guide Master（input/）。★LLM は使いません",
            on_click=self.open_council)
        buttons.addWidget(self.council_button)
        # ⚠⚠ 2026-09-25（RX3-0431）: 公開版に **Guide Master を同梱しません**
        #   （★第三者の攻略サイト由来のため / `docs/00-project-policy.md` §4）。
        #   → ⚠ 無い環境では**押せる入口を出しません**。★空の窓を見せるより自然。
        #   ★開発機には input/ にあるので、いままでどおり出ます。
        if not self._guide_available():
            self.council_button.setVisible(False)
        root.addLayout(buttons)

        self._council = None            #: ★開いている勇者会議の窓（⚠ 2 つ開かない）

        # ⚠⚠ 件数で高さを変えない（★0 件でも同じ場所を占める）
        #
        # ★★ ⚠⚠ **文の長さで窓の幅を変えない**（2026-08-31 / 依頼者）★★
        #
        #   > メッセージが長いと MAP 画面の大きさが変わってしまう。
        #   > 基本は画面の大きさを内容で自動的に変えるのは NG
        #   > （ユーザーが調整した場合のみ）
        #
        #   ⚠ `QLabel` は既定で「中身が収まる幅」を求めるので、
        #     ★長いメモが入るたびに窓が横に伸びていました。
        #   → ⚠ 幅を求めさせない（`Ignored`）＋ ★入らない分は「…」で省く。
        #     ⚠ 全文はヒントで読めるようにします（★切り捨てない）。
        self._rows: list[QLabel] = []
        self._texts: list[str] = ["" for _ in range(self.limit)]
        for _ in range(self.limit):
            row = QLabel("")
            row.setFixedHeight(ROW_PX)
            row.setSizePolicy(QSizePolicy.Policy.Ignored,
                              QSizePolicy.Policy.Fixed)
            row.setMinimumWidth(0)
            row.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            root.addWidget(row)
            self._rows.append(row)

        self.refresh()

    def resizeEvent(self, event):                       # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        """★入らない分を「…」にする（⚠ 窓を広げない）。"""
        for row, text in zip(self._rows, self._texts):
            if not text:
                continue
            width = max(0, row.width() - 2)
            if width <= 0:
                continue
            row.setText(row.fontMetrics().elidedText(
                text, Qt.TextElideMode.ElideRight, width))

    def refresh(self) -> None:
        """★直近 N 件を出し直す。⚠ 0 件でも行は消さない。"""
        memos = (self._pick(self.limit) if self._pick is not None
                 else self.vm.recent_memos(self.limit))
        for i, row in enumerate(self._rows):
            if i < len(memos):
                # ⚠ 整形は `Memo.line` の 1 か所（★3 ビューで同じ字面 / RX3-0118）
                self._texts[i] = "・" + memos[i].line
                row.setStyleSheet("")
                row.setToolTip(memos[i].line)     # ★全文はここで読める
            else:
                # ★まだ無い（⚠ 「壊れている」と見えないように、そう書く）
                self._texts[i] = "・（まだありません）" if i == 0 else ""
                row.setStyleSheet("color: #888;")
                row.setToolTip("")
            row.setText(self._texts[i])
        self._elide()
        # ⚠ 絞り込んでいるときは、★その絞り込みの件数を出す
        total = (len(self._pick(10 ** 9)) if self._pick is not None
                 else len(self.vm.memos))
        self._count.setText("%d 件" % total)

    @staticmethod
    def _guide_available() -> bool:
        """★攻略の Topic（Guide Master）があるか（RX3-0431）。

        ⚠ 読み込みまではしません（★起動を重くしない）。在り処だけ見ます。
        """
        try:
            from dq3.knowledge import guide_master

            return guide_master.resolve_path() is not None
        except Exception:                                   # noqa: BLE001
            # ⚠ 見に行けないなら「無い」に倒す（★起動を止めない）
            return False

    def open_council(self) -> None:
        """★勇者会議を開く（RX3-0308 / ⚠ もとは地図の窓の下の行にあった）。

        ⚠ 2 つ開かない（★既に開いていれば前へ出す）。
        """
        got = self._council
        if got is None:
            from .council_window import Dq3CouncilWindow

            got = self._council = Dq3CouncilWindow(self.vm)
        else:
            got.reload()            # ★開くたびに評価し直す（⚠ 毎フレームではない / 指示書 §25）
        got.show()
        got.raise_()

    def open_detail(self) -> None:
        """★勇者メモ詳細（RX3-0058 §18）。⚠ 2 つ開かない。"""
        got = getattr(self, "_detail_dialog", None)
        if got is None:
            from ..knowledge.town_service import TownService
            from .memo_detail import MemoDetailDialog

            got = self._detail_dialog = MemoDetailDialog(self.vm, TownService(), parent=self)
        got.reload_maps()
        got.refresh()
        got.show()
        got.raise_()
        return got                  # ★「行ってみる？」から元メモへ戻るとき使う（RX3-0310）
