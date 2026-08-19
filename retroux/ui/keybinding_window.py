"""キーバインド設定画面（2026-08-01 の指示書 §13）。

★★ **第一弾は「YAML をそのまま編集する」形**（指示書 §13.1）★★
  キーごとの専用フォームは作らない。設定ファイルが唯一の出典なので、
  それを直接見せて直せるほうが**何が効いているか分かりやすい**。

## ⚠⚠ 守ること

  1. **エラーがある設定は保存しない**（指示書 §13.5）。
     保存してしまうと、次の起動で既定値へ落ちて
     「直したはずなのに効かない」になる。
  2. **アトミック置換**。一時ファイルへ書いて、読み直して確かめてから置き換える。
     途中で落ちても、元のファイルはそのまま残る。
  3. 検証は**まとめて**出す。1件ずつ直させない。
"""

from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ..core import keybindings as kb


class KeybindingWindow(QWidget):
    """キーバインド設定（別ウィンドウ）。"""

    #: 保存して反映できたときに出す（呼び出し元が実行中の設定を差し替える）
    applied = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent, )
        self.setWindowTitle("キーバインド設定")
        self.resize(720, 620)
        self._path = kb.USER_PATH
        self._saved_text = ""

        layout = QVBoxLayout(self)

        head = QLabel("現在の設定ファイル")
        head.setStyleSheet("font-weight:bold;")
        layout.addWidget(head)
        self._path_label = QLabel(str(self._path))
        # ★パスは選んでコピーできるようにする（外部エディタで開きたい人向け）
        self._path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._path_label)

        # ★使えるアクションを画面に出す。⚠ 名前を思い出すために
        #   ファイルを探させない（設定画面の役目はそこ）。
        from ..core.actions import ACTIONS
        names = QLabel("使えるアクション: "
                       + " / ".join(f"{a.name}（{a.label}）" for a in ACTIONS))
        names.setWordWrap(True)
        names.setStyleSheet("color:#9a9a9a;")
        layout.addWidget(names)

        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Consolas", 10))
        self._editor.setPlaceholderText("（設定を読み込んでいません）")
        layout.addWidget(self._editor, stretch=1)

        layout.addWidget(QLabel("検証結果"))
        self._result = QPlainTextEdit()
        self._result.setReadOnly(True)
        self._result.setMaximumHeight(140)
        layout.addWidget(self._result)

        row = QHBoxLayout()
        for label, slot, tip in (
                ("チェック", self.check,
                 "保存せずに、いま編集している内容だけを調べます"),
                ("保存して反映", self.save_and_apply,
                 "問題が無ければ保存し、実行中の RetroUX へ反映します\n"
                 "⚠ エラーがあるときは保存しません"),
                ("再読込", self.reload,
                 "保存済みのファイルを読み直します"),
                ("既定値に戻す", self.load_defaults,
                 "同梱の既定値をここへ出します\n"
                 "★まだ保存はしません（[保存して反映] で確定します）"),
                ("外部エディタで開く", self.open_externally,
                 "OS の既定のテキストエディタで開きます"),
                ("閉じる", self.close, "この画面を閉じます")):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)

        self.reload()

    # --- 読む -------------------------------------------------------

    def reload(self) -> None:
        """保存済みの設定を読み直す（指示書 §13.7）。

        ⚠ 未保存の編集があれば確かめる（黙って捨てない）。
        ★ファイルが無ければ既定値を出す（指示書 §13.3）。
          ⚠ ここでは**作らない**。利用者が保存した時点で作る。
        """
        if self._editor.toPlainText() and \
                self._editor.toPlainText() != self._saved_text:
            answer = QMessageBox.question(
                self, "キーバインド設定",
                "保存していない変更があります。読み直すと失われます。\n"
                "読み直しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            text = self._path.read_text(encoding="utf-8")
            note = ""
        except OSError:
            text = kb.default_text()
            note = ("★まだ設定ファイルがありません。既定値を出しています。\n"
                    "  [保存して反映] を押した時点で "
                    f"{self._path.name} が作られます。")
        self._editor.setPlainText(text)
        self._saved_text = text
        self._result.setPlainText(note)

    def load_defaults(self) -> None:
        """既定値をエディタへ出す（指示書 §13.8）。

        ⚠ **ここでは保存も反映もしない。** 誤操作で設定を失わないため。
        """
        self._editor.setPlainText(kb.default_text())
        self._result.setPlainText(
            "既定値をここへ出しました。\n"
            "★まだ保存していません（[保存して反映] を押すと確定します）。")

    # --- 調べる -----------------------------------------------------

    def _validate_text(self):
        """エディタの中身を調べる。戻り値: `(中身, [Issue])`。"""
        import yaml

        text = self._editor.toPlainText()
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return None, [kb.Issue("error", "YAML", f"書き方が正しくありません: {exc}")]
        if data is None:
            return None, [kb.Issue("error", "YAML", "中身が空です")]
        return data, kb.validate(data, source=self._path.name)

    def check(self) -> bool:
        """保存せずに調べる（指示書 §13.4）。戻り値は**問題が無いか**。"""
        data, issues = self._validate_text()
        errors = [i for i in issues if i.level == "error"]
        if not issues:
            self._result.setPlainText("問題はありません")
            return True
        self._result.setPlainText("\n\n".join(str(i) for i in issues))
        return not errors

    # --- 保存する ---------------------------------------------------

    def save_and_apply(self) -> bool:
        """検証 → 一時ファイル → 読み直して確認 → 置換（指示書 §13.5）。

        ★★ **直接上書きしない。** ★★
          途中で落ちても元のファイルが残る形にする
          （手で書いた設定は戻らない / 戦術プロフィールと同じ作法）。
        """
        data, issues = self._validate_text()
        errors = [i for i in issues if i.level == "error"]
        if errors:
            self._result.setPlainText(
                "⚠ エラーがあるので保存しませんでした。\n\n"
                + "\n\n".join(str(i) for i in issues))
            return False

        text = self._editor.toPlainText()
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            # ★書いたものを**読み直して**確かめる（書けたつもりを防ぐ）
            made = kb.load(user_path=tmp)
            if not made.used_user_file:
                self._result.setPlainText(
                    "⚠ 保存できましたが読み直せませんでした。元の設定のままです。\n"
                    + "\n".join(made.problems))
                tmp.unlink(missing_ok=True)
                return False
            tmp.replace(self._path)
        except OSError as exc:
            self._result.setPlainText(f"⚠ 保存できませんでした: {exc}")
            tmp.unlink(missing_ok=True)
            return False

        self._saved_text = text
        warnings = [str(i) for i in issues if i.level == "warning"]
        note = "保存して反映しました。"
        if warnings:
            note += "\n\n" + "\n\n".join(warnings)
        # ⚠ Lua 側は起動時にキーを読むので、そちらは再起動が要る（§13.6）
        note += ("\n\n⚠ FCEUX 内のキー（AUTO・高速化など）は、"
                 "Lua を読み直したあとに新しい割り当てになります。")
        self._result.setPlainText(note)
        self.applied.emit("キーバインドを保存して反映しました")
        return True

    def open_externally(self) -> None:
        """OS 既定のエディタで開く（指示書 §13.9）。

        ★ファイルが無ければ既定値をコピーして作ってから開く。
          ⚠ 「開いたのに何も無い」をやらない。
        """
        try:
            if not self._path.exists():
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(kb.default_text(), encoding="utf-8")
                self._saved_text = self._path.read_text(encoding="utf-8")
                self._editor.setPlainText(self._saved_text)
            # ★★ OS のアプリを起こすのは `WindowManager`（リファクタ §5.2）★★
            #   ⚠ ここから `subprocess` を呼ばない。コンソールを出さない旗も
            #     あちらが持つ（付け忘れると黒い窓が一瞬出る / R-1 の経緯）。
            from .window_manager import WindowManager
            from ..core.config import user_config as ucfg
            problem = WindowManager(lambda: ucfg.load()[0]).open_with_default_app(
                self._path)
            if problem is not None:
                self._result.setPlainText(f"⚠ {problem}")
                return
            self._result.setPlainText(
                f"{self._path} を開きました。\n"
                "★直したら [再読込] を押してください。")
        except Exception as exc:                       # noqa: BLE001
            self._result.setPlainText(f"⚠ 開けませんでした: {exc}")

    # --- 逃げ道 -----------------------------------------------------

    @property
    def path(self) -> pathlib.Path:
        return self._path

    def set_text(self, text: str) -> None:
        """テストから中身を差し込む。"""
        self._editor.setPlainText(text)
