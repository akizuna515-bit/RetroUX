"""「命名」の窓（RX3-0080 §16 案 B / ⚠ 候補は RX3-0309 で外しました）。

★人が名前を**手で入れる**だけの窓です。

```text
[命名] → 名称入力 → [決定] [キャンセル]
```

## ⚠⚠ 2026-09-20: 名前の候補を出す機能を外しました（RX3-0309）

依頼者の指示:

> 塔・洞窟・ダンジョン等の命名時に、会話・ヒント等から候補名称を推定・提示する機能は、
> 精度や判断ロジックが複雑になりやすく、現時点では UX 上の効果に対して実装・保守コストが高い。
> 命名はシンプルな手動入力に一本化する。

★残すもの: 仮名（自動で付けた名前）/ 人が付けた名前 / 名前の付け直し / Location Master。
⚠ 外したもの: 候補の一覧・候補の推定（`dq3/knowledge/name_candidates.py`）。

★仮名（`未命名の塔` など）は、⚠ そのまま**欄の初めの値**に入ります（★直して使えます）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit,
                               QVBoxLayout)


class NameDialog(QDialog):
    """★場所の名前を手で付ける窓（⚠ 候補は出しません / RX3-0309）。"""

    def __init__(self, location_id: str, current: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("命名")
        root = QVBoxLayout(self)
        root.addWidget(QLabel("★%s の名前（⚠ いまは「%s」）" % (location_id, current or "名前なし")))
        root.addWidget(QLabel("名称を入力してください"))
        # ★いまの名前（仮名も）を初めの値に（⚠ そのまま直して使える）
        self.edit = QLineEdit(current or "")
        self.edit.selectAll()
        root.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("決定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def text(self) -> str:
        return self.edit.text().strip()

    @classmethod
    def ask(cls, location_id, current, parent=None):
        """★開いて待つ。戻り値: 決めた名前（⚠ やめたら None）。"""
        dialog = cls(location_id, current, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.text() or None


__all__ = ["NameDialog"]
