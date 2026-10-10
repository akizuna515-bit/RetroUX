"""DQ2 の管理画面（RX-0171〜0174 / 2026-10-06）。

依頼者 2026-10-06「DQ2 管理画面再編」（★調査: `docs/research/261006_dq2-admin-screen-survey.md`）:

```text
管理
├─ 状態        版・build / ROM・FCEUX・データ保存場所（★表示だけ・コピーできる）/ セーブステート控え
├─ キー設定    ［キー設定を開く］→ 既存の KeybindingWindow（★Ctrl+K も残す / 中身は変えない）
└─ プレイデータ  保存場所・最新の退避・［プレイデータを退避］/ 移行の状態（★実行しない）
```

## ⚠⚠ やらないこと（依頼者の決定）

- ⚠ ROM・FCEUX の場所を画面から変えない（★変えるのは dq2_user_config.yaml）
- ⚠ 初期化・復元はしない（★起動中の DB は WAL / RX-0175）
- ⚠ 移行は実行しない（★状態と migrate-dq2.cmd の案内だけ）

★判定は `retroux/core/dq2_admin.py`（Qt を知らない）。ここは並べるだけ。
★押せないボタンは理由をツールチップで出す（`disabled_tips.watch_disabled` / BP-35）。
⚠ DQ2 LOCAL（★DQ3 はこのファイルを import しない）。
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from ..core import dq2_admin as A
from .disabled_tips import watch_disabled

#: ★色（本体の状態欄と同じ / main_window `_refresh_backup_status`）
OK_STYLE = "color:#8fd18f;"
WARN_STYLE = "color:#ffb84d; font-weight:bold;"


class PathRow(QWidget):
    """★長いパスを省略しない 1 行（read-only の欄 = 選んでコピーできる ＋［コピー］［開く］）。

    依頼者 2026-10-06: 「Windows の長いパスを扱うため、単なる QLabel で省略表示するだけにはしないでください」。
    """

    def __init__(self, path: str, *, can_open: bool = False, reveal=None, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(path)
        self.edit.setReadOnly(True)
        self.edit.setCursorPosition(0)
        self.edit.setToolTip(path)
        row.addWidget(self.edit, 1)
        self.copy_button = QPushButton("コピー")
        self.copy_button.setToolTip("この場所をクリップボードへコピーします")
        self.copy_button.clicked.connect(self.copy)
        row.addWidget(self.copy_button)
        self.open_button = None
        if can_open:
            self.open_button = QPushButton("開く")
            self.open_button.clicked.connect(self.open)
            row.addWidget(self.open_button)
        self._reveal = reveal
        self.set_path(path)

    def set_path(self, path: str) -> None:
        self.edit.setText(path)
        self.edit.setCursorPosition(0)
        self.edit.setToolTip(path)
        self.copy_button.setEnabled(bool(path))
        if not path:
            self.copy_button.setToolTip("場所が分からないため、コピーできません")
        if self.open_button is not None:
            ok = bool(path) and Path(path).exists() and self._reveal is not None
            self.open_button.setEnabled(ok)
            self.open_button.setToolTip(
                "エクスプローラで開きます" if ok else
                ("場所が分からないため、開けません" if not path else
                 "このフォルダはまだありません" if not Path(path).exists() else
                 "この画面からは開けません"))

    def copy(self) -> None:
        QApplication.clipboard().setText(self.edit.text())

    def open(self) -> str | None:
        if self._reveal is None:
            return "開けません"
        return self._reveal(self.edit.text())


class AdminWindow(QWidget):
    """★管理画面（独立した窓）。"""

    def __init__(self, parent=None, *, open_keybindings=None, reveal=None, cfg=None,
                 backup=None, latest=None, migration=None, places=None, backup_view=None) -> None:
        super().__init__(parent)
        # ★独立した窓（⚠ 無いと本体 364px の中に描かれる / RX-0103 と同じ）
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle("管理 — RetroUX DQ2")
        self.resize(680, 520)
        from .window_state import center_on_screen

        center_on_screen(self)
        self._cfg = cfg
        self._open_keybindings = open_keybindings
        self._reveal = reveal
        # ★検査で差し替える口（⚠ 既定は本物）
        self._backup_fn = backup
        self._latest_fn = latest
        self._migration_fn = migration or A.migration_view
        self._places_fn = places or (lambda: A.places(cfg))
        self._backup_view_fn = backup_view or (lambda: A.backup_view(cfg))
        self._backup_thread: threading.Thread | None = None
        self._backup_result: dict | None = None

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self._build_status(), "状態")
        self.tabs.addTab(self._build_keys(), "キー設定")
        self.tabs.addTab(self._build_playdata(), "プレイデータ")
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        refresh = QPushButton("最新にする")
        refresh.setToolTip("状態・最新の退避を読み直します")
        refresh.clicked.connect(self.refresh)
        bottom.addWidget(refresh)
        close = QPushButton("閉じる")
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.refresh()

    # --- 状態 ---------------------------------------------------------------

    def _build_status(self) -> QWidget:
        from ..core import dq2_version

        page = QWidget()
        box = QVBoxLayout(page)
        self.version_label = QLabel(dq2_version.stamp())
        self.version_label.setStyleSheet("font-weight:bold;")
        self.version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.version_label)
        self.runtime_label = QLabel("Python: " + A.runtime_kind())
        self.runtime_label.setStyleSheet("color:#9a9a9a;")
        box.addWidget(self.runtime_label)

        form = QFormLayout()
        self.path_rows: dict = {}
        self.path_notes: dict = {}
        for place in self._places_fn():
            row = PathRow(place.path, can_open=place.label == "データ保存場所", reveal=self._reveal)
            note = QLabel("")
            note.setStyleSheet(WARN_STYLE)
            holder = QVBoxLayout()
            holder.addWidget(row)
            holder.addWidget(note)
            form.addRow(place.label, holder)
            self.path_rows[place.label] = row
            self.path_notes[place.label] = note
        box.addLayout(form)
        hint = QLabel("★場所を変えるときは、このフォルダの dq2_user_config.yaml を書き換えてください（paths.rom / paths.fceux）。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9a9a9a;")
        box.addWidget(hint)

        group = QGroupBox("セーブステート控え")
        self.backup_form = QFormLayout(group)
        self.backup_state = QLabel("")
        self.backup_form.addRow("状態", self.backup_state)
        box.addWidget(group)
        box.addStretch(1)
        for row in self.path_rows.values():
            watch_disabled(row)
        return page

    def _refresh_status(self) -> None:
        for place in self._places_fn():
            row = self.path_rows.get(place.label)
            if row is None:
                continue
            row.set_path(place.path)
            self.path_notes[place.label].setText(place.note)
            self.path_notes[place.label].setVisible(bool(place.note))
        view = self._backup_view_fn()
        self.backup_state.setText(view.label)
        self.backup_state.setStyleSheet(WARN_STYLE if view.warning else OK_STYLE)
        while self.backup_form.rowCount() > 1:
            self.backup_form.removeRow(1)
        for key, value in view.lines:
            # ⚠ 監視先・保存先は長いパス → ★折り返せない文字で窓が横に伸びないよう、read-only の 1 行欄に
            field = QLineEdit(value)
            field.setReadOnly(True)
            field.setFrame(False)
            field.setCursorPosition(0)
            field.setToolTip(value)
            self.backup_form.addRow(key, field)

    # --- キー設定 -------------------------------------------------------------

    def _build_keys(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        text = QLabel("キーボードの割り当て（ショートカット）を変えます。\n"
                      "★本体で Ctrl+K を押しても同じ画面が開きます。\n"
                      "⚠ ゲームパッドの割り当ては変えられません（固定です）。")
        text.setWordWrap(True)
        box.addWidget(text)
        self.keys_button = QPushButton("キー設定を開く")
        if self._open_keybindings is None:
            self.keys_button.setEnabled(False)
            self.keys_button.setToolTip("この画面からはキー設定を開けません（★本体で Ctrl+K を押してください）")
        else:
            self.keys_button.setToolTip("キー設定の画面を開きます（Ctrl+K と同じ）")
            self.keys_button.clicked.connect(self._open_keybindings)
        box.addWidget(self.keys_button, 0, Qt.AlignmentFlag.AlignLeft)
        box.addStretch(1)
        watch_disabled(page)
        return page

    # --- プレイデータ -----------------------------------------------------------

    def _build_playdata(self) -> QWidget:
        from ..tools import playdata

        page = QWidget()
        box = QVBoxLayout(page)
        form = QFormLayout()
        data = next((p.path for p in self._places_fn() if p.label == "データ保存場所"), "")
        self.data_row = PathRow(data, can_open=True, reveal=self._reveal)
        form.addRow("保存場所", self.data_row)
        self.vault_row = PathRow(str(playdata.VAULT), can_open=True, reveal=self._reveal)
        form.addRow("退避の置き場", self.vault_row)
        self.latest_label = QLabel("")
        self.latest_label.setWordWrap(True)
        self.latest_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("最新の退避", self.latest_label)
        box.addLayout(form)

        self.backup_button = QPushButton("プレイデータを退避")
        self.backup_button.setToolTip(
            "遊んだ記録（DB・記録・ログ・地図の素材など）を退避の置き場へ写します。\n"
            "★何も消しません。⚠ ROM・セーブステートは入りません（セーブは控えが世代を残しています）")
        self.backup_button.clicked.connect(self.start_backup)
        box.addWidget(self.backup_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.backup_message = QLabel("")
        self.backup_message.setWordWrap(True)
        box.addWidget(self.backup_message)

        group = QGroupBox("旧い DQ2 のフォルダからの移行")
        mig = QVBoxLayout(group)
        self.migration_label = QLabel("")
        self.migration_label.setWordWrap(True)
        mig.addWidget(self.migration_label)
        self.migrate_button = QPushButton("migrate-dq2.cmd の場所を開く")
        self.migrate_button.clicked.connect(self._reveal_migrate)
        mig.addWidget(self.migrate_button, 0, Qt.AlignmentFlag.AlignLeft)
        box.addWidget(group)
        box.addStretch(1)
        for holder in (page, group, self.data_row, self.vault_row):
            watch_disabled(holder)
        return page

    def _migrate_cmd(self) -> Path:
        from ..core import dq2_paths

        return dq2_paths.program_root() / "migrate-dq2.cmd"

    def _refresh_playdata(self) -> None:
        from ..tools import playdata

        data = next((p.path for p in self._places_fn() if p.label == "データ保存場所"), "")
        self.data_row.set_path(data)
        self.vault_row.set_path(str(playdata.VAULT))
        got = (self._latest_fn or playdata.latest_backup)()
        if got is None:
            self.latest_label.setText("まだありません")
        else:
            when = str(got.get("created") or "")[:16].replace("T", " ") or got.get("name")
            self.latest_label.setText(f"{when}（{got.get('name')} / 退避は全部で {got.get('count')} 件）")
        view = self._migration_fn()
        cmd = self._migrate_cmd()
        text = view.text
        if view.can_migrate:
            text += ("\n★移すときは RetroUX（DQ2 と DQ3）を閉じてから、このフォルダの migrate-dq2.cmd を実行し、"
                     "旧いフォルダを渡してください（★旧いフォルダは変えません）。")
        self.migration_label.setText(text)
        ok = view.can_migrate and cmd.is_file() and self._reveal is not None
        self.migrate_button.setEnabled(ok)
        self.migrate_button.setToolTip(
            "migrate-dq2.cmd を選んだ状態でフォルダを開きます" if ok else
            (view.reason or ("migrate-dq2.cmd がありません（★配布 ZIP を展開したフォルダにあります）"
                             if not cmd.is_file() else "この画面からは開けません")))

    def _reveal_migrate(self) -> None:
        if self._reveal is not None:
            self._reveal(str(self._migrate_cmd()))

    # --- 退避（★別の糸 / ⚠ 画面を固めない）---------------------------------------

    def start_backup(self) -> bool:
        """★退避を始める（⚠ 2 重に走らせない）。戻り値: 始めたか。"""
        if self._backup_thread is not None and self._backup_thread.is_alive():
            return False
        from ..tools import playdata

        fn = self._backup_fn or playdata.backup
        self._backup_result = None

        def work():
            try:
                self._backup_result = fn()
            except Exception as exc:                   # noqa: BLE001 ★画面を落とさない
                self._backup_result = {"ok": False, "target": None, "saved": [],
                                       "error": f"退避できませんでした: {exc}"}

        self.backup_button.setEnabled(False)
        self.backup_button.setToolTip("退避しています…（終わるまでお待ちください）")
        self.backup_message.setText("退避しています…")
        self._backup_thread = threading.Thread(target=work, daemon=True)
        self._backup_thread.start()
        QTimer.singleShot(150, self._poll_backup)
        return True

    def _poll_backup(self) -> None:
        if self._backup_thread is not None and self._backup_thread.is_alive():
            QTimer.singleShot(150, self._poll_backup)
            return
        self.finish_backup()

    def finish_backup(self) -> None:
        got = self._backup_result or {"ok": False, "error": "結果がありません"}
        if got.get("ok"):
            self.backup_message.setText(f"★退避しました: {got.get('target')}（{len(got.get('saved') or [])} 件）")
            self.backup_message.setStyleSheet(OK_STYLE)
        else:
            self.backup_message.setText(f"⚠ {got.get('error')}")
            self.backup_message.setStyleSheet(WARN_STYLE)
        self.backup_button.setEnabled(True)
        self.backup_button.setToolTip(
            "遊んだ記録（DB・記録・ログ・地図の素材など）を退避の置き場へ写します。\n"
            "★何も消しません。⚠ ROM・セーブステートは入りません（セーブは控えが世代を残しています）")
        self._refresh_playdata()

    # --- 全体 -----------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_status()
        self._refresh_playdata()


__all__ = ["AdminWindow", "PathRow"]
