"""旧版からデータを引き継ぐ窓（RX3-0471 / 2026-10-01）。

```text
[旧版からデータを引き継ぎますか？]
  移行元: [ C:\\...\\RetroUX-DQ3-1.1.0 ] [参照...]
  [引き継ぐ]  [引き継がず開始]
      ↓ 引き継ぐ
[確認]  ★migrate.summary() をそのまま出す
  [実行] [キャンセル]
      ↓ 実行
[結果]  ★完了 / 一部完了 / 失敗 ＋ 次にすること ＋ 記録の場所
```

## ⚠⚠ この窓が持っていないもの

★**コピーする対象の一覧を持っていません。**
⚠ 判断も文も `dq3/migrate.py` と `dq3/ownership.py` にあります
（依頼者 2026-10-01 §1「★GUI に別のコピー対象一覧を持たせないでください」）。

```text
★窓がするのは 3 つだけ
  ① フォルダを 1 つ選んでもらう
  ② migrate.probe() / migrate.conflicts() / migrate.summary() を見せる
  ③ migrate.run() を呼んで、⚠ 結果をそのまま出す
```

## ⚠ 利用者が選ぶのは「旧ルートフォルダ 1 つだけ」

★中の `work/dq3-knowledge/` などを個別に選ばせません（依頼者の指示）。

## ⚠⚠ 検査での扱い

★`QFileDialog` は**モーダル**なので、検査では `ask_folder` を差し替えます
（⚠ 窓を開かない / `RX3-0258` で画面外 Qt の穴を踏んでいるため）。
⚠ 実際のフォルダ選択ダイアログと画面操作は**最終実機確認**に残します（依頼者の了承済み）。
"""
from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from dq3 import migrate as MG

TITLE = "旧版からデータを引き継ぐ"

#: ★最初の問いかけ（⚠ 内部のフォルダ名を出さない）
ASK_TEXT = ("★以前の RetroUX DQ3 のデータを引き継げます。\n"
            "⚠ 引き継ぐのは**あなたのデータだけ**です"
            "（プログラムと生成データは新しい版のものを使います）。\n\n"
            "★旧版の **RetroUX DQ3 のフォルダ**（`DQ3.cmd` がある場所）を選んでください。")

#: ⚠⚠ 旧版を触らないことを、窓でも言う（★不安を残さない）
SAFETY_TEXT = "⚠ 旧版のフォルダは**読むだけ**です（★削除も移動も書き換えもしません）。"


def ask_folder(parent=None, start: str = "") -> str:
    """★フォルダを 1 つ選んでもらう（⚠ 検査ではここを差し替えます）。"""
    return QFileDialog.getExistingDirectory(
        parent, "旧版の RetroUX DQ3 のフォルダを選ぶ", start)


class MigrateDialog(QDialog):
    """★引き継ぎの窓（⚠ 判断は `dq3.migrate` / 一覧は `dq3.ownership`）。"""

    def __init__(self, parent=None, *, dst=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self._dst = pathlib.Path(dst) if dst is not None else None
        #: ★最後の結果（⚠ 呼ぶ側が読む / まだなら None）
        self.result_of_run: MG.Result | None = None
        #: ★利用者が引き継がずに始めたか
        self.declined = False
        #: ⚠ 選び直しが要る設定（★`stale_references()` の結果）
        self.stale: tuple = ()

        root = QVBoxLayout(self)
        ask = QLabel(ASK_TEXT)
        ask.setWordWrap(True)
        ask.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(ask)

        row = QHBoxLayout()
        row.addWidget(QLabel("移行元:"))
        self.edit = QLineEdit("")
        self.edit.setMinimumWidth(380)
        self.edit.setPlaceholderText(r"例 D:\Games\RetroUX-DQ3-1.1.0")
        row.addWidget(self.edit, 1)
        self.b_browse = QPushButton("参照...")
        self.b_browse.clicked.connect(self._on_browse)
        row.addWidget(self.b_browse)
        root.addLayout(row)

        safety = QLabel(SAFETY_TEXT)
        safety.setWordWrap(True)
        root.addWidget(safety)

        #: ★選んだフォルダの見立て（⚠ 足りないものは名指しで出る）
        self.view = QPlainTextEdit("")
        self.view.setReadOnly(True)
        self.view.setMinimumHeight(190)
        root.addWidget(self.view, 1)

        buttons = QDialogButtonBox()
        self.b_migrate = buttons.addButton(
            "引き継ぐ", QDialogButtonBox.ButtonRole.AcceptRole)
        self.b_skip = buttons.addButton(
            "引き継がず開始", QDialogButtonBox.ButtonRole.RejectRole)
        self.b_migrate.setEnabled(False)
        self.b_migrate.clicked.connect(self._on_migrate)
        self.b_skip.clicked.connect(self._on_skip)
        root.addWidget(buttons)

        self.edit.textChanged.connect(self._on_path_changed)

    # --- ★見立て -----------------------------------------------------

    def _on_browse(self) -> None:
        got = ask_folder(self, self.edit.text())
        if got:
            self.edit.setText(got)

    def _on_path_changed(self, text: str) -> None:
        """★道が変わるたびに見立て直す（⚠ 1 バイトも書きません）。"""
        text = (text or "").strip().strip('"')
        if not text:
            self.view.setPlainText("")
            self.b_migrate.setEnabled(False)
            return
        src = MG.probe(text, self._dst)
        blocked = MG.conflicts(text, self._dst) if src.ok else []
        stale = MG.stale_references(text, self._dst) if src.ok else []
        self.view.setPlainText(MG.summary(src, blocked, stale))
        self.b_migrate.setEnabled(src.ok)

    # --- ★実行 -------------------------------------------------------

    def _on_migrate(self) -> None:
        """★確認 → 実行 → 結果（⚠ 文は `migrate` のものをそのまま）。"""
        text = self.edit.text().strip().strip('"')
        src = MG.probe(text, self._dst)
        if not src.ok:
            return                                  # ⚠ ボタンは無効のはず（★二重の守り）
        blocked = MG.conflicts(text, self._dst)
        stale = MG.stale_references(text, self._dst)
        body = MG.summary(src, blocked, stale)
        if self.confirm(body) != QMessageBox.StandardButton.Ok:
            return                                  # ★キャンセル（⚠ 何も書かない）
        got = MG.run(text, self._dst)
        self.result_of_run = got
        self.stale = tuple(stale)
        self.show_result(got, stale)
        self.accept()

    def _on_skip(self) -> None:
        """★引き継がずに始める（⚠ 覚えておいて、次からは聞かない）。"""
        self.declined = True
        MG.record_decision(MG.DONE_DECLINED, root=self._dst)
        self.reject()

    # --- ★窓を出すところだけ分ける（⚠ 検査から差し替えられるように）----

    def confirm(self, body: str):
        """★実行していいか聞く（⚠ 検査ではここを差し替えます）。"""
        box = QMessageBox(self)
        box.setWindowTitle("引き継ぎの確認")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("この内容で引き継ぎます。")
        box.setInformativeText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok
                               | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Ok).setText("実行")
        box.button(QMessageBox.StandardButton.Cancel).setText("キャンセル")
        return box.exec()

    def show_result(self, got: MG.Result, stale=()) -> None:
        """⚠⚠ **完了 / 一部完了 / 失敗を同じ顔で出さない**（依頼者 §3）。"""
        box = QMessageBox(self)
        box.setWindowTitle("引き継ぎ: " + got.outcome)
        box.setIcon(QMessageBox.Icon.Information if got.outcome == MG.OUT_OK
                    else QMessageBox.Icon.Warning)
        box.setText("引き継ぎ: %s" % got.outcome)
        box.setInformativeText(result_text(got, stale))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()


#: ★設定の欄の名前を、利用者の言葉にする（⚠ `migrate.OUTSIDE_KEYS` と対でずらさない）
STALE_LABELS = {"dq3_rom": "DQ3 の ROM", "rom": "DQ2 の ROM", "fceux": "FCEUX"}


def _reference_alive(raw: str) -> bool:
    """★その参照先が**いま**在るか（⚠ 無ければ「使えません」と言う）。"""
    try:
        return pathlib.Path(raw).exists()
    except OSError:                                      # pragma: no cover
        return False


def exit_code_for(dlg) -> int:
    """★★ 窓の結末を **launcher へ返す終了コード**にする（RX3-0481）★★

    ⚠⚠ **数字の意味は `dq3.migrate` の 1 か所だけ**です（★ここでは組み立てるだけ）。

    ```text
    ★窓を出さなかった        → EXIT_NOT_NEEDED（0）
    ★［引き継がず開始］      → EXIT_DECLINED（11）
    ★引き継いだ              → 結果ごとに 10 / 13 / 14
    ⚠ × で閉じた             → EXIT_CANCELLED（12 / ★次回も聞く）
    ```

    ⚠ 「確認の窓でキャンセル」は**ここに来ません**。★窓は開いたままで、
      移行元を選び直せます（`MigrateDialog._on_run` が `return` するだけ）。
      → ⚠⚠ 「選び直す」と「引き継ぎをやめる」を**取り違えないため**です。
    """
    if dlg is None:
        return MG.EXIT_NOT_NEEDED
    if getattr(dlg, "declined", False):
        return MG.EXIT_DECLINED
    got = getattr(dlg, "result_of_run", None)
    if got is None:
        return MG.EXIT_CANCELLED
    return MG.EXIT_BY_OUTCOME.get(got.outcome, MG.EXIT_FAILED)


def result_text(got: MG.Result, stale=()) -> str:
    """★結果の本文（⚠ 画面と CLI が**同じ数字**を出す / 依頼者 §3 の 6 項目）。"""
    lines = [
        "コピーできた      : %d 件 / %s bytes" % (got.copied, format(got.size, ",")),
        "引き継げなかった  : %d 件" % len(got.skipped),
    ]
    for rel in got.skipped[:8]:
        lines.append("    ・%s（★新版に同じものが既にあった）" % rel)
    if len(got.skipped) > 8:
        lines.append("    ・…ほか %d 件" % (len(got.skipped) - 8))
    lines.append("失敗              : %d 件" % len(got.failed))
    for why in got.failed[:8]:
        lines.append("    ・" + why)
    stale = list(stale)
    if stale:
        lines.append("")
        lines.append("⚠⚠ 旧版のフォルダの中を指している設定があります（%d 件）:"
                     % len(stale))
        for key, raw, why in stale:
            lines.append("    ・%s（%s）" % (STALE_LABELS.get(key, key), key))
            lines.append("        いまの参照先: %s" % raw)
            # ⚠ 「いま使えるか」で言うことが変わる（依頼者 2026-10-02 §4）
            lines.append("        いまは %s" % (
                "★使えます（⚠ ただし旧版を消すと使えなくなります）"
                if _reference_alive(raw) else
                "⚠⚠ **使えません**（★新版で場所を選び直してください）"))
            lines.append("        %s" % why)
        lines.append("    ⚠⚠ RetroUX は設定を**書き換えていません**"
                     "（★選び直すのは利用者です）。")
    lines.append("")
    lines.append("結果              : %s" % got.outcome)
    lines.append("次にすること      : %s" % got.next_step())
    lines.append("詳しい記録        : %s" % (got.journal or "(無し)"))
    return "\n".join(lines)


def offer_if_first_run(parent=None, *, dst=None) -> MigrateDialog | None:
    """★初回起動のときだけ誘う（⚠ 一度決めたら聞かない / `should_offer()`）。

    戻り値は出した窓（⚠ 出さなかったときは None）。
    ★あとから呼ぶときは `MigrateDialog` を直に作ってください（⚠ 誘いの条件を見ません）。
    """
    if not MG.should_offer(dst):
        return None
    dlg = MigrateDialog(parent, dst=dst)
    dlg.exec()
    return dlg


__all__ = ["TITLE", "ASK_TEXT", "SAFETY_TEXT", "STALE_LABELS", "ask_folder",
           "MigrateDialog", "result_text", "offer_if_first_run",
           "exit_code_for"]
