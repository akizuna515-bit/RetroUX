"""まんたんの設定画面（2026-08-02 / 指示書 `input/260802_manatan.md` §5）。

★★ **ここで決めた方針を、まんたんがそのまま実行する。** ★★
  戦術プロフィール画面と同じ考え方です（AI が勝手に賢くなるのではなく、
  利用者が方針を設計する）。

## 画面（指示書 §5.2）

    まんたん完了HP                  [ 90 ]%
    やくそうの使用                  [ 呪文を優先する      ▼]
    どくけしそうの使用              [ キアリーを優先する  ▼]
    サマルトリア・ムーンブルクのMP配分 [ 残存MP率を揃える  ▼]
    ☑ 回復呪文を使用する
    ☑ 戦術プロフィールの最低残存MPを使用する
                                    [ 戦術プロフィールを開く ]

## ⚠ 最低残存MPの数値はここに置きません（指示書 §5.2）

  戦術プロフィール側と**二重管理**になるからです。
  ★使うか使わないかだけを決め、値は既存の `DQ2:reserved_mp()` を通します。

## ⚠⚠ 設定が壊れていても画面は開くこと（指示書 §4.2）

  読み込みで気づいたことは `problems` に入ってきます。
  ★**黙って直さず**、画面の上に出します。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.mantan import (
    ANTIDOTE_POLICY_LABELS, HP_PERCENT_MAX, HP_PERCENT_MIN,
    ITEM_POLICY_LABELS, MP_POLICY_LABELS, MantanSettings, load, save,
)


def _fill(combo: QComboBox, labels: dict) -> None:
    """表示名と内部値を **1か所** で結びつける。

    ⚠ 画面に文字列を直書きすると、設定ファイル側と食い違ったときに
      気づけません。★`settings.py` の対応表だけを使います。
    """
    for value, label in labels.items():
        combo.addItem(label, value)


def _select(combo: QComboBox, value: str) -> None:
    """内部値で選ぶ。⚠ 知らない値なら先頭のまま（落とさない）。"""
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


class MantanSettingsWindow(QWidget):
    """まんたん設定の窓。★保存すると設定生成をやり直します。"""

    #: 保存できた／できなかったことを本体の画面へ知らせる
    applied = Signal(str)
    #: 「戦術プロフィールを開く」が押された
    open_tactics = Signal()

    def __init__(self, parent=None, user_path=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("まんたん設定")
        self._user_path = user_path

        root = QVBoxLayout(self)

        # ★読み込みで気づいたことを出す場所（指示書 §4.2）
        self._problems = QLabel("")
        self._problems.setWordWrap(True)
        self._problems.setStyleSheet("color: #b36b00;")
        self._problems.hide()
        root.addWidget(self._problems)

        form = QFormLayout()

        self._percent = QSpinBox()
        self._percent.setRange(HP_PERCENT_MIN, HP_PERCENT_MAX)
        self._percent.setSuffix(" %")
        form.addRow("まんたん完了HP", self._percent)
        note = QLabel("生存している全員がこのHP割合以上になると、"
                      "まんたん完了とします。")
        note.setWordWrap(True)
        form.addRow("", note)

        self._herb = QComboBox()
        _fill(self._herb, ITEM_POLICY_LABELS)
        form.addRow("やくそうの使用", self._herb)

        self._antidote = QComboBox()
        _fill(self._antidote, ANTIDOTE_POLICY_LABELS)
        form.addRow("どくけしそうの使用", self._antidote)

        self._mp = QComboBox()
        _fill(self._mp, MP_POLICY_LABELS)
        form.addRow("サマルトリア・ムーンブルクのMP配分", self._mp)
        mp_note = QLabel("「残存MP率を揃える」では、最大MPに対する残り割合が"
                         "二人で近くなるように術者を選びます。")
        mp_note.setWordWrap(True)
        form.addRow("", mp_note)

        root.addLayout(form)

        box = QGroupBox("使うもの")
        box_layout = QVBoxLayout(box)
        self._spells = QCheckBox("回復呪文を使用する")
        box_layout.addWidget(self._spells)
        spell_note = QLabel("目標HPまで回復するための推定総消費MPが"
                            "少ない呪文を選びます。")
        spell_note.setWordWrap(True)
        box_layout.addWidget(spell_note)

        self._poison = QCheckBox("毒を治療する")
        box_layout.addWidget(self._poison)

        self._reserve = QCheckBox("戦術プロフィールの最低残存MPを使用する")
        box_layout.addWidget(self._reserve)
        reserve_note = QLabel(
            "⚠ 最低残存MPの数値はこの画面では変えられません"
            "（戦術プロフィールと二重管理にしないためです）。")
        reserve_note.setWordWrap(True)
        box_layout.addWidget(reserve_note)

        tactics_row = QHBoxLayout()
        tactics_row.addStretch(1)
        self._tactics_button = QPushButton("戦術プロフィールを開く")
        self._tactics_button.clicked.connect(self.open_tactics.emit)
        tactics_row.addWidget(self._tactics_button)
        box_layout.addLayout(tactics_row)
        root.addWidget(box)

        # --- ボタン（指示書 §5.3）------------------------------------
        buttons = QHBoxLayout()
        self._status = QLabel("")
        self._status.setWordWrap(True)
        buttons.addWidget(self._status, 1)

        self._defaults_button = QPushButton("既定値に戻す")
        self._defaults_button.clicked.connect(self.restore_defaults)
        buttons.addWidget(self._defaults_button)

        self._cancel_button = QPushButton("キャンセル")
        self._cancel_button.clicked.connect(self.close)
        buttons.addWidget(self._cancel_button)

        # ★★ 2026-08-11: 「保存」→「OK（保存して閉じる）」（依頼者）★★
        #   ⚠ 保存に失敗したら**閉じない**（直すべき入力を捨てない / 戦術窓と同じ作法）。
        self._save_button = QPushButton("OK")
        self._save_button.setToolTip("設定を保存して、この画面を閉じます\n"
                                     "★次のまんたんから反映されます\n"
                                     "⚠ 保存に失敗したときは閉じません")
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self.save_and_close)
        buttons.addWidget(self._save_button)
        root.addLayout(buttons)

        self.reload()

    # --- 読み書き -----------------------------------------------------

    def reload(self) -> None:
        """設定を読み直して画面へ入れる。⚠ 壊れていても開くこと。"""
        settings, problems, _used = load(user_path=self._user_path)
        self.set_settings(settings)
        if problems:
            self._problems.setText("⚠ 設定を読むときに気づいたこと:\n・"
                                   + "\n・".join(problems))
            self._problems.show()
        else:
            self._problems.hide()

    def set_settings(self, s: MantanSettings) -> None:
        self._percent.setValue(s.target_hp_percent)
        _select(self._herb, s.herb_policy)
        _select(self._antidote, s.antidote_policy)
        _select(self._mp, s.mp_policy)
        self._spells.setChecked(s.healing_spells_enabled)
        self._poison.setChecked(s.poison_cure_enabled)
        self._reserve.setChecked(s.use_tactics_reserve)

    def current_settings(self) -> MantanSettings:
        """画面の中身を設定にする。★内部値は combo のデータから取る。"""
        return MantanSettings(
            target_hp_percent=self._percent.value(),
            herb_policy=self._herb.currentData(),
            antidote_policy=self._antidote.currentData(),
            mp_policy=self._mp.currentData(),
            healing_spells_enabled=self._spells.isChecked(),
            poison_cure_enabled=self._poison.isChecked(),
            use_tactics_reserve=self._reserve.isChecked(),
        )

    def restore_defaults(self) -> None:
        """★画面を既定値へ戻すだけ。**保存はしない**（押し間違いを守る）。"""
        self.set_settings(MantanSettings())
        self._problems.hide()
        self._status.setText("既定値に戻しました（まだ保存していません）")

    def save_settings(self) -> bool:
        """保存して、Lua へ渡す設定を作り直す（指示書 §5.4・§13）。

        ⚠ 失敗を**黙って飲み込まない**。理由を画面に出します。
        """
        settings = self.current_settings()
        try:
            path = save(settings, user_path=self._user_path)
        except OSError as exc:
            self._status.setText(f"★保存できませんでした: {exc}")
            QMessageBox.warning(self, "まんたん設定",
                                f"保存できませんでした。\n{exc}")
            return False

        # ★保存しただけでは Lua に届かない。設定生成をやり直す（指示書 §13）
        regenerated, why = self._regenerate()
        if regenerated:
            msg = (f"保存しました（{path.name}）。"
                   "★次のまんたんから反映されます")
        else:
            msg = (f"保存しました（{path.name}）が、"
                   f"⚠ Lua への反映に失敗しました: {why}")
        self._status.setText(msg)
        self.applied.emit(msg)
        return True

    def save_and_close(self) -> None:
        """[OK] = 保存してから閉じる（2026-08-11 / 依頼者）。

        ⚠ 保存に失敗したら**閉じない**（理由を画面に残す）。★戦術窓と同じ作法。
        """
        if self.save_settings():
            self.close()

    def _regenerate(self):
        """`work/generated/config.lua` を作り直す。

        ⚠ ここが落ちても保存は済んでいます。**別のこととして扱う**。
        """
        try:
            from ..core.config.generate_lua import main as generate

            code = generate()
            if code != 0:
                return False, f"設定生成が {code} で終わりました"
            return True, ""
        except Exception as exc:                       # noqa: BLE001
            return False, str(exc)
