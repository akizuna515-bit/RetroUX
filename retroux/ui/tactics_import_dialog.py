"""戦術プロフィールを貼り付けて読み込む窓（2026-07-30 / 仕様書 12.2）。

★★ **もらったテキストは信じない。** ★★
  読み込みの安全は `retroux/core/tactics/import_export.py` が持っている
  （`yaml.safe_load` のみ・サイズ上限・深さ上限）。ここは画面だけ。

## 順番（仕様書 12.3）

    貼る -> [検証] -> 下見を見せる -> [インポート] -> 保存

⚠ **検証せずにインポートさせない。** 押した瞬間に保存すると、
  何が入ったのか分からないまま自分の戦術が増える。

## 未知項目（仕様書 12.5）

  > 勝手に無視しない。

→ 未知項目があると [インポート] は押せない。
  「未知項目を無視して読み込む」を**明示的に選んだときだけ**押せる。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QRadioButton, QVBoxLayout,
)

from ..core.tactics.import_export import (
    CONFLICT_OVERWRITE, CONFLICT_RENAME, read_profile_text, resolve_conflict,
)


class TacticsImportDialog(QDialog):
    """YAML を貼り付けてプロフィールを読み込む。"""

    def __init__(self, repository, parent=None) -> None:
        super().__init__(parent)
        self.repo = repository
        #: 読み込めたプロフィール（`accept` したときだけ入る）
        self.imported = None
        self._preview = None

        self.setWindowTitle("戦術プロフィールを読み込む — RetroUX")
        self.resize(680, 620)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("プロフィールYAMLを貼り付けてください"))

        self._text = QPlainTextEdit()
        self._text.setPlaceholderText(
            "schema_version: 1\n"
            "profile:\n"
            "  id: my_plan\n"
            "  name: わたしの作戦\n"
            "characters:\n"
            "  lorasia:\n"
            "    ...")
        root.addWidget(self._text, stretch=3)

        row = QHBoxLayout()
        self._check_button = QPushButton("検証")
        self._check_button.clicked.connect(self.check)
        row.addWidget(self._check_button)
        self._paste_button = QPushButton("クリップボードから貼る")
        self._paste_button.clicked.connect(self.paste)
        row.addWidget(self._paste_button)
        self._file_button = QPushButton("ファイルから読む")
        self._file_button.clicked.connect(self.pick_file)
        row.addWidget(self._file_button)
        row.addStretch(1)
        root.addLayout(row)

        root.addWidget(QLabel("下見（保存する前の中身）"))
        self._preview_view = QPlainTextEdit()
        self._preview_view.setReadOnly(True)
        root.addWidget(self._preview_view, stretch=2)

        # --- 未知項目（仕様書 12.5）---
        # ★★ **既定は OFF。** 勝手に無視しない。
        self._allow_unknown = QCheckBox(
            "⚠ 知らない項目を無視して読み込む"
            "（新しい版の RetroUX で作られた可能性があります）")
        self._allow_unknown.setChecked(False)
        self._allow_unknown.toggled.connect(self._refresh_buttons)
        root.addWidget(self._allow_unknown)

        # --- 重複したとき（仕様書 12.6）---
        # ★★ **既定は別名保存。** 上書きで自分の戦術を消させない。
        self._conflict_box = QLabel("同じ名前・同じIDがあったとき:")
        root.addWidget(self._conflict_box)
        conflict = QHBoxLayout()
        self._rename = QRadioButton("別名で保存（推奨）")
        self._rename.setChecked(True)
        self._overwrite = QRadioButton("上書き")
        conflict.addWidget(self._rename)
        conflict.addWidget(self._overwrite)
        conflict.addStretch(1)
        root.addLayout(conflict)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#8a8a8a; font-size:11px;")
        root.addWidget(self._status)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "インポート")
        self._buttons.accepted.connect(self._do_import)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        self._refresh_buttons()

    # --- 入れる -----------------------------------------------------

    def set_text(self, text: str) -> None:
        self._text.setPlainText(text or "")
        self._preview = None
        self._preview_view.setPlainText("")
        self._refresh_buttons()

    def paste(self) -> None:
        """クリップボードから貼る（仕様書 12.1）。"""
        try:
            from PySide6.QtWidgets import QApplication

            board = QApplication.clipboard()
            self.set_text(board.text() if board is not None else "")
            self._status.setText("クリップボードから貼りました。[検証] を押してください。")
        except Exception:                              # noqa: BLE001
            # ⚠ クリップボードが使えない環境でも窓は使える（手で貼れる）
            self._status.setText("⚠ クリップボードを読めませんでした（手で貼ってください）。")

    def pick_file(self) -> None:
        """ファイルから読む（仕様書 12.1）。"""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "戦術プロフィールを選ぶ", "", "YAML (*.yaml *.yml)")
        if not path:
            return
        try:
            import pathlib

            self.set_text(pathlib.Path(path).read_text(encoding="utf-8"))
            self._status.setText(f"{path} を読みました。[検証] を押してください。")
        except (OSError, UnicodeDecodeError) as exc:
            self._status.setText(f"⚠ 読めませんでした: {exc}")

    # --- 検証・インポート -------------------------------------------

    def check(self):
        """検証して下見を出す（仕様書 12.3 の 1〜9）。"""
        self._preview = read_profile_text(self._text.toPlainText(),
                                         repository=self.repo)
        self._preview_view.setPlainText("\n".join(self._preview.lines()))
        result = self._preview.result
        if self._preview.profile is None:
            self._status.setText("✗ 読み込めません。上の下見にある理由を直してください。")
        elif result.unknowns:
            self._status.setText(
                f"？ 知らない項目が {len(result.unknowns)} 件あります。"
                "無視して読み込むなら下のチェックを入れてください。")
        elif result.warnings:
            self._status.setText(
                f"⚠ 読み込めますが、いま効かない項目が {len(result.warnings)} 件あります"
                "（値は保存され、対応したときに効きます）。")
        else:
            self._status.setText("✓ 読み込めます。")
        self._refresh_buttons()
        return self._preview

    def _refresh_buttons(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        # ★★ **検証していないうちは押せない**（仕様書 12.3）。
        can = (self._preview is not None
               and self._preview.can_import(self._allow_unknown.isChecked()))
        ok.setEnabled(bool(can))
        if self._preview is None:
            ok.setToolTip("先に [検証] を押してください")
        elif not can:
            ok.setToolTip("下見にある問題を直してください")
        else:
            ok.setToolTip("")

    def _do_import(self) -> None:
        preview = self._preview
        if preview is None or preview.profile is None:
            self._status.setText("⚠ 先に [検証] を押してください。")
            return
        how = CONFLICT_OVERWRITE if self._overwrite.isChecked() \
            else CONFLICT_RENAME
        resolved = resolve_conflict(preview.profile, self.repo, how)
        if resolved is None:
            self.reject()
            return
        if not self.repo.save(resolved):
            # ⚠ 失敗しても窓を閉じない（貼ったテキストが消えるほうが痛い）
            self._status.setText(
                "⚠ 保存できませんでした。置き場が書けない状態かもしれません。"
                "貼ったテキストはそのまま残してあります。")
            return
        self.imported = resolved
        self.accept()
