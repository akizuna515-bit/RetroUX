"""人が地図に書き込む窓（2026-07-30 / マッパー仕様 フェーズ6）。

★★ **ここに入るのは人の言葉。観測が上書きしない。** ★★

| 窓 | 出し方 | 何を入れるか |
| --- | --- | --- |
| `NoteDialog` | `Ctrl+M` | いま立っているマスへのメモ（自由文）と目印 |
| `MapEditDialog` | `Ctrl+Shift+M` | そのマップの名前と階層 |

## メモと目印の違い

    メモ  … 自由文。**人が読むためのもの**（「ここの婆さんが鍵の話をする」）
    目印  … 種類が決まっている。**機械が使えるもの**（宝箱・階段・店…）

★種類が決まっているから、あとで「宝箱まで自動で行く」に使える。
  自由文からは種類を取れないので、両方ある。

## 名前と階層の違い（大事）

    名前  … 表示だけ。間違っていても経路の判断は壊れない
    階層  … **自動移動が使う**。間違えると別の階へ行こうとする

⚠ だから階層のほうは、ROM 由来の値と食い違ったら画面に出す
  （`map_window.py` の `_floor_text`）。

## 落ちないこと

⚠ 保存に失敗しても窓を閉じない。何が起きたかを窓の中に書いて、
  やり直せるようにする（書いた文が消えるほうが痛い）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..core.navigation.floor_estimator import label_for
from ..core.navigation.models import LANDMARK_LABELS, LandmarkKind

#: 階層に入れられる範囲。★ROM のコメントに出てくる最大は 8F / B8
FLOOR_MIN = -12
FLOOR_MAX = 12
#: 「階層は分からない」を表す値。★0 階は無いので 0 を「未指定」に使う
FLOOR_UNSET = 0


class NoteDialog(QDialog):
    """いま立っているマスにメモと目印を置く（`Ctrl+M`）。"""

    def __init__(self, view_model, place, *, place_label: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self.place = place
        self.setWindowTitle("メモを書く — RetroUX")
        self.resize(520, 420)

        root = QVBoxLayout(self)
        where = place_label or (
            f"マップ {place.map_id:02X}（{place.x}, {place.y}）"
            if place is not None else "（場所が読めていません）")
        head = QLabel(f"ここ: {where}")
        head.setWordWrap(True)
        root.addWidget(head)

        root.addWidget(QLabel("メモ（自由文。あなたが読むためのものです）"))
        self._body = QPlainTextEdit()
        self._body.setPlaceholderText(
            "例: 右の階段は行き止まり。婆さんが鍵の話をする")
        root.addWidget(self._body, stretch=1)

        # --- 目印 ---
        root.addWidget(QLabel("目印（種類が決まっているもの。あとで探せます）"))
        row = QHBoxLayout()
        self._kind = QComboBox()
        for kind in LandmarkKind:
            self._kind.addItem(LANDMARK_LABELS[kind], kind.value)
        row.addWidget(self._kind)
        self._label = QLineEdit()
        self._label.setPlaceholderText("名前（省略できます）")
        row.addWidget(self._label, stretch=1)
        self._add = QPushButton("ここに置く")
        self._add.clicked.connect(self._add_landmark)
        row.addWidget(self._add)
        root.addLayout(row)

        self._marks = QListWidget()
        self._marks.setMaximumHeight(110)
        root.addWidget(self._marks)
        self._remove = QPushButton("選んだ目印を消す")
        self._remove.clicked.connect(self._remove_landmark)
        root.addWidget(self._remove)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#8a8a8a; font-size:11px;")
        root.addWidget(self._status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load()

    # --- 中身 --------------------------------------------------------

    def _load(self) -> None:
        if self.place is None:
            self._status.setText(
                "⚠ 場所が読めていないので保存できません"
                "（エミュレータが動いていないか、戦闘中です）。")
            self._body.setReadOnly(True)
            self._add.setEnabled(False)
            return
        row = self.vm.note(self.place)
        if row:
            self._body.setPlainText(str(row.get("body") or ""))
        self._refresh_marks()

    def _refresh_marks(self) -> None:
        self._marks.clear()
        if self.place is None:
            return
        here = (self.place.x, self.place.y)
        for row in self.vm.landmarks(self.place.map_id, self.place.map_ptr):
            if (row.get("x"), row.get("y")) != here:
                continue
            kind = LandmarkKind.parse(row.get("kind"))
            # ⚠ 読めない種類は**そのまま出す**（黙って隠すと消せなくなる）
            name = (LANDMARK_LABELS[kind] if kind is not None
                    else f"⚠ 不明な種類 `{row.get('kind')}`")
            label = row.get("label")
            item = f"{name}" + (f" — {label}" if label else "")
            self._marks.addItem(item)
            self._marks.item(self._marks.count() - 1).setData(
                Qt.ItemDataRole.UserRole, row.get("kind"))

    def _add_landmark(self) -> None:
        if self.place is None:
            return
        kind = self._kind.currentData()
        if not self.vm.set_landmark(self.place, kind,
                                    self._label.text().strip() or None):
            self._status.setText("⚠ 目印を置けませんでした（記録が無効です）。")
            return
        self._label.clear()
        self._status.setText(f"目印を置きました: {self._kind.currentText()}")
        self._refresh_marks()

    def _remove_landmark(self) -> None:
        item = self._marks.currentItem()
        if item is None or self.place is None:
            return
        kind = item.data(Qt.ItemDataRole.UserRole)
        if not self.vm.delete_landmark(self.place, kind):
            self._status.setText("⚠ 目印を消せませんでした。")
            return
        self._status.setText("目印を消しました。")
        self._refresh_marks()

    def _save(self) -> None:
        if self.place is None:
            self.reject()
            return
        # ★空にして保存＝メモを消す（`set_note` が消す）
        if self.vm.set_note(self.place, self._body.toPlainText()):
            self.accept()
            return
        # ⚠ 失敗しても閉じない。書いた文が消えるほうが痛い
        self._status.setText(
            "⚠ 保存できませんでした。記録が無効か、DB が書けない状態です。"
            "文はそのまま残してあります。")


class MapEditDialog(QDialog):
    """そのマップの名前と階層を人が決める（`Ctrl+Shift+M`）。

    ★★ **ファイル（`locations.yaml`）は触らない。** ★★
      DB に「人がこう言った」として置く。ファイルを書き換えると
      生成し直したときに消えるし、どれが人の手直しか分からなくなる。
    """

    def __init__(self, view_model, map_id: int, map_ptr: int,
                 parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self.map_id = int(map_id)
        self.map_ptr = int(map_ptr)
        self.setWindowTitle("マップの名前と階層 — RetroUX")
        self.resize(560, 300)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            f"マップ ID ${self.map_id:02X}"
            f"（データ位置 0x{self.map_ptr:04X}）"))

        form = QFormLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("空にすると辞書の名前に戻ります")
        form.addRow("名前", self._name)

        self._floor = QSpinBox()
        self._floor.setRange(FLOOR_MIN, FLOOR_MAX)
        # ★0 = 未指定。ゲームに0階は無いので、この値を「分からない」に使う
        self._floor.setSpecialValueText("（指定しない）")
        self._floor_note = QLabel("")
        self._floor_note.setStyleSheet("color:#8a8a8a; font-size:11px;")
        floor_box = QWidget()
        floor_row = QVBoxLayout(floor_box)
        floor_row.setContentsMargins(0, 0, 0, 0)
        floor_row.addWidget(self._floor)
        floor_row.addWidget(self._floor_note)
        form.addRow("階層", floor_box)
        self._floor.valueChanged.connect(self._show_floor)
        root.addLayout(form)

        self._current = QLabel("")
        self._current.setWordWrap(True)
        self._current.setStyleSheet("color:#8a8a8a; font-size:11px;")
        root.addWidget(self._current)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#8a8a8a; font-size:11px;")
        root.addWidget(self._status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Reset
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).setText(
            "あなたの指定を取り消す")
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(
            self._clear)
        root.addWidget(buttons)

        self._load()

    # --- 中身 --------------------------------------------------------

    def _load(self) -> None:
        override = self.vm.map_override(self.map_id, self.map_ptr) or {}
        self._name.setText(str(override.get("display_name") or ""))
        index = override.get("floor_index")
        self._floor.setValue(FLOOR_UNSET if index is None else int(index))
        self._show_floor()

        # ★いま何が使われているかを書く（人が判断できるように）
        resolved = self.vm.location_of_map(self.map_id)
        estimate = self.vm.floor_of_map(self.map_id, self.map_ptr)
        lines = []
        if resolved is not None and resolved.registered:
            lines.append(f"辞書の名前: {resolved.location.name}"
                         f"（出どころ {resolved.source}）")
        else:
            lines.append("辞書にこのマップの名前はありません。")
        if estimate is not None:
            lines.append(f"いま使っている階層: {estimate.display}"
                         f"（出どころ {estimate.source}）")
        self._current.setText("　/　".join(lines))

    def _show_floor(self) -> None:
        value = self._floor.value()
        if value == FLOOR_UNSET:
            self._floor_note.setText(
                "★指定しなければ ROM 由来の値（または上下移動からの推定）を使います。")
            return
        self._floor_note.setText(
            f"→ {label_for(value)} として保存します"
            "（★あなたの指定がいちばん強くなります）")

    def _save(self) -> None:
        value = self._floor.value()
        index = None if value == FLOOR_UNSET else value
        name = self._name.text().strip() or None
        if self.vm.set_map_override(self.map_id, self.map_ptr,
                                    floor_index=index, display_name=name):
            self.accept()
            return
        self._status.setText(
            "⚠ 保存できませんでした。記録が無効か、DB が書けない状態です。")

    def _clear(self) -> None:
        if not self.vm.clear_map_override(self.map_id, self.map_ptr):
            self._status.setText("⚠ 取り消せませんでした。")
            return
        self._name.clear()
        self._floor.setValue(FLOOR_UNSET)
        self._load()
        self._status.setText("あなたの指定を取り消しました（辞書の値に戻ります）。")
