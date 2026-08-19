"""戦略の中身を見せる窓（2026-08-11 / UI整理 Phase 5）。

設計: docs/design/strategy-unification-design.md（§6 Phase 5「作戦設定画面整理」）

## ★★ 何の窓か

  利用者が触るのは**戦略だけ**（指示書§2）。この窓は、いま選んでいる戦略が
  **具体的にどう戦うか**を見せる**読むだけ**の画面。⚔ ボタンで開く。

    レベル上げ / ダンジョン攻略（AUTO） … プリセット作戦の要約を read-only（§8.1）
    ユーザー指定1（custom_1 / FIXED）   … キャラごとの固定行動を表示（§8.2 / 表示のみ）
    手動（MANUAL）                       … AI を通さない旨を表示

## ⚠ ここでは作戦を作り替えない

  新規/複製/切替は**主導線から隠す**（指示書§4）。設計判断を触りたい上級者は
  [上級設定を開く] で従来の作戦プロフィール窓へ。★エクスポート/コピーは残す。

## ⚠ フォーカスを奪わない

  図鑑・地図・戦術と同じく `WA_ShowWithoutActivating`。奪うとゲームを操作できない。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ..core.strategy.models import (STRATEGY_LABELS, STRATEGY_NOTES,
                                    STRATEGY_TYPES, Strategy, StrategyType)

NOTE_STYLE = "color:#8a8a8a; font-size:11px;"


class StrategyDetailWindow(QWidget):
    """いまの戦略の中身を read-only で見せる（Phase 5）。"""

    #: [上級設定を開く] で従来の作戦プロフィール窓へ（自作・読み込み用）
    open_advanced = Signal()

    def __init__(self, view_model, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self._strategy = Strategy.DUNGEON

        self.setWindowTitle("戦略の中身 — RetroUX")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(560, 620)

        root = QVBoxLayout(self)

        self._banner = QLabel("")
        bold = QFont()
        bold.setBold(True)
        bold.setPointSize(bold.pointSize() + 1)
        self._banner.setFont(bold)
        self._banner.setWordWrap(True)
        root.addWidget(self._banner)

        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(NOTE_STYLE)
        root.addWidget(self._note)

        # ★本文は選択・コピーできるように QTextEdit（読み取り専用）
        self._body = QTextEdit()
        self._body.setReadOnly(True)
        root.addWidget(self._body, stretch=1)

        root.addLayout(self._build_footer())
        self.reload()

    # --- 組み立て -------------------------------------------------------

    def _build_footer(self):
        row = QHBoxLayout()
        self._export_button = QPushButton("エクスポート")
        self._export_button.setToolTip(
            "いまの作戦をファイルへ書き出します（配布・共有用）\n"
            "★AUTO 戦略のときだけ使えます")
        self._export_button.clicked.connect(self.export_file)
        row.addWidget(self._export_button)

        copy_button = QPushButton("テキストをコピー")
        copy_button.setToolTip("画面の内容をそのままコピーします（貼って渡せます）")
        copy_button.clicked.connect(self.copy_text)
        row.addWidget(copy_button)

        row.addStretch(1)

        # ⚠ 2026-08-11: 「上級設定を開く」は廃止（依頼者「上級設定は不要」）。
        #   ⚔ の AUTO 戦略は作戦プロフィールを直接編集で開くようになった。
        #   この窓は**亀の子（固定行動 / 編集不可）専用の読むだけ**の窓。

        close = QPushButton("閉じる")
        close.clicked.connect(self.close)
        row.addWidget(close)

        box = QVBoxLayout()
        box.addLayout(row)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(NOTE_STYLE)
        box.addWidget(self._status)
        holder = QWidget()
        holder.setLayout(box)
        outer = QVBoxLayout()
        outer.addWidget(holder)
        return outer

    # --- 中身 -----------------------------------------------------------

    def show_for(self, strategy) -> None:
        """メイン画面から「いまの戦略」を渡して開く。"""
        self._strategy = Strategy.parse(strategy, Strategy.DUNGEON)
        self.reload()

    def reload(self) -> None:
        strat = self._strategy
        stype = STRATEGY_TYPES.get(strat, StrategyType.AUTO)
        self._banner.setText(f"いまの戦略：{STRATEGY_LABELS.get(strat, '—')}")
        self._note.setText(STRATEGY_NOTES.get(strat, ""))

        if stype is StrategyType.FIXED:
            self._body.setPlainText(self._fixed_body(strat))
            self._export_button.setEnabled(False)
        elif stype is StrategyType.MANUAL:
            self._body.setPlainText(self._manual_body())
            self._export_button.setEnabled(False)
        else:
            self._body.setPlainText(self._auto_body())
            self._export_button.setEnabled(True)

    def _auto_body(self) -> str:
        """AUTO 戦略：いま動いている作戦の要約（read-only / §8.1）。"""
        from ..core.tactics.import_export import profile_summary

        lines = ["この戦略では、AI が戦況を見て次のことを判断します。",
                 "★中身はプリセット（公開版では編集しません）。", ""]
        try:
            # ★`mission_label()` は既に「目的: …」を含むので前置きしない
            lines.append(self.vm.mission_label())
        except Exception:                                 # noqa: BLE001
            pass
        prof = self.vm.active_tactics() if self.vm.tactics is not None else None
        if prof is None:
            lines.append("")
            lines.append("⚠ 作戦を読めていません（プロフィール機能を確認してください）。")
            return "\n".join(lines)
        lines.append("")
        lines.append(profile_summary(prof))
        lines.append("")
        lines.append("⚠ 反映は次の戦闘からです。")
        return "\n".join(lines)

    def _fixed_body(self, strat: Strategy) -> str:
        """FIXED 戦略：キャラごとの固定行動（DQ2 プラグインから / §8.2）。"""
        from ..plugins.dq2 import user_strategy

        name = user_strategy.strategy_name(strat.value)
        rows = user_strategy.fixed_action_lines(strat.value)
        lines = [f"「{name}」— キャラクターごとに、毎ターンこの行動をします。",
                 "★AI の判断は通しません（固定）。満HPでも道具を使います。", ""]
        if not rows:
            lines.append("⚠ 固定行動のデータを読めていません。")
            return "\n".join(lines)
        for label, text in rows:
            lines.append(f"　{label}　→　{text}")
        lines.append("")
        lines.append("⚠ この画面は表示のみです（編集は今後のフェーズ）。")
        lines.append("⚠ 反映は次のターンからです。")
        return "\n".join(lines)

    @staticmethod
    def _manual_body() -> str:
        return ("AI を止めて、自分で操作します。\n"
                "★ボス戦など、任せたくない場面用です。\n\n"
                "・戦闘中の行動はすべて手入力になります。\n"
                "・まんたん設定・移動の補助など、戦闘以外の支援は働きます。\n\n"
                "⚠ ここには設定する項目はありません。")

    # --- 出す（支援用）-------------------------------------------------

    def export_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from ..core.tactics.import_export import write_profile_file

        prof = self.vm.active_tactics() if self.vm.tactics is not None else None
        if prof is None:
            self._status.setText("⚠ 書き出せる作戦がありません。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "作戦を書き出す", f"{prof.id}.yaml", "YAML (*.yaml)")
        if not path:
            return
        if write_profile_file(path, prof):
            self._status.setText(f"書き出しました: {path}")
        else:
            self._status.setText("⚠ 書き出せませんでした。")

    def copy_text(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = self._body.toPlainText()
        board = QApplication.clipboard()
        if board is None:
            self._status.setText("⚠ クリップボードが使えません。")
            return
        board.setText(text)
        self._status.setText(f"コピーしました（{len(text)} 文字）。")
