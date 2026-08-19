"""GUI 本体。1920×1080 を基準にした統合レイアウト（MVP2 Phase 1 / 指示書 5.2）。

```text
┌ ヘッダー: ROM / 状態 / 倍速 / 取り込み ────────────────────────┐
├───────────────────────────┬────────────────────────────────────┤
│ エミュレータ画面の置き場   │ 敵情報（Phase 2 で中身が入る）      │
│ （FCEUX をここへ整列）     │ 現在モンスター / 警告               │
├───────────────────────────┼────────────────────────────────────┤
│ パーティ状態（Phase 2）    │ 戦闘ログ / System Log              │
└───────────────────────────┴────────────────────────────────────┘
```

★Phase 1 の受入条件は「**1920×1080で重要情報が同時に見える**」こと。
  中身（敵個体・AI判断・パーティHP）は Phase 2 で入るので、
  ここでは**枠と、いま出せる情報**を置く。枠だけの場所には
  「Phase 2 で入る」と書いておく。空白のまま置くと不具合に見える。

★エミュレータ画面は**埋め込まない**（指示書 5.3 / core/window_align.py の説明）。
  埋め込みは入力フォーカスとジョイパッドを壊す危険がある。
  ここには枠だけを置き、FCEUX ウィンドウをその位置へ**整列**する。

表示ロジックは ViewModel 側にある。ここは描画に徹する。
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QRadioButton,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.humanize import compact_duration, duration
from ..core.logging_setup import get_logger
from ..version import title as version_title
from .panels import AiPanel, PartyPanel
from .view_model import UiState, ViewModel
from . import view_model as vm_tone

# ★「ドロップ」は**落としうるもの**（ROM の表）。実際に落ちたものではない
#   （何を拾ったかは記録していない / 検知手段が未特定）。
_LOG_COLUMNS = ["時刻", "モンスター", "ドロップ（可能性）", "初遭遇", "倍率",
                "実時間", "短縮"]

#: ★伸縮させる列（残りは内容に合わせる / リリース調整 仕様書 7.5）。
#   ⚠ ドロップ候補は長くなるので**内容に合わせない**。
#     合わせると横に伸びて、1366×768 で右端（短縮）が見切れる。
#     溢れたら省略し、全文はツールチップで出す。
_STRETCH_COLUMNS = {"モンスター", "ドロップ（可能性）"}

# 起動時に System Log へ出す行数（それ以前は work/retroux.log を見る）
INITIAL_LOG_LINES = 200

_PLACEHOLDER_STYLE = (
    "color:#8a8a8a; border:1px dashed #5a5a5a; border-radius:4px; padding:12px;"
)

#: ★上部ステータスの文字（2026-08-07 / 依頼者報告「上画面の文字は薄い」）。
#
# ⚠⚠⚠ **色を決め打ちしない**（2026-08-07 に2回間違えた）★★★
#
#   1回目: `#c8c8c8` → `#e8e8e8` と**明るく**した。
#          ⚠ ところが画面は**白背景（ライトテーマ）**だったので、
#            ★さらに読めなくなりました。暗いテーマ前提で直していた。
#   2回目: 画面を組んで色を測ったが、★**背景を見ていなかった**。
#          ⚠ `#e8e8e8` という値だけ確かめて「直った」と言った。
#
# ★色は**テーマに任せます**。⚠ 明るい背景でも暗い背景でも読めます。
#   薄く見せたいものは色ではなく**大きさ**で差をつけます。
_STATUS_TEXT = "font-size:12px;"

#: ★★ 「調子」から色への対応（2026-08-01 / 指示書 §7.2）★★
#   ViewModel は**意味**（ok / caution など）だけを返し、色はここで決める。
#   ⚠ 配色を変えるときに直すのは**この表だけ**。
#     以前は各所に `#ffb84d` が直書きされており、1つ変えるのに探し回った。
_TONE_COLORS = {
    vm_tone.TONE_OK: "#8fd18f",        # 思ったとおりに動いている
    vm_tone.TONE_INFO: "#8ad1ff",      # ふだんと違うが問題ではない
    vm_tone.TONE_MUTED: "#9a9a9a",     # とくに言うことがない
    vm_tone.TONE_CAUTION: "#ffb84d",   # ⚠ 止まっている・解除されている
    vm_tone.TONE_DANGER: "#ff8a8a",    # ⚠⚠ 本当に危ない
}


def _color(tone: str) -> str:
    """調子を stylesheet の色にする。

    ⚠ 知らない調子は**灰色に倒す**。落とさない代わりに、
      画面が「とくに言うことがない」ように見えるだけで済む。
    """
    return f"color:{_TONE_COLORS.get(tone, _TONE_COLORS[vm_tone.TONE_MUTED])};"


def _section(title: str) -> QLabel:
    label = QLabel(title)
    font = QFont()
    font.setBold(True)
    label.setFont(font)
    return label


def _button_icon(kind: str, color, size: int = 18):
    """下段ボタンの**画像アイコン**を描く（2026-08-19 / RX-0071）。

    ★★ 文字・絵文字に頼らない（実機で絵文字の字形が化けた経緯 / RX-0071）★★
      ⚠ 同梱画像も持たず、`QPainter` で描く。フォント・外部ファイルに依存しない。
    ★色は呼び出し側から渡す（テーマの文字色）。明暗どちらでも見える。
    """
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import (QBrush, QColor, QIcon, QPainter, QPen,
                               QPixmap, QPolygonF)

    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))                         # ★透明
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    col = QColor(color)
    pen = QPen(col)
    pen.setWidthF(max(1.4, size * 0.09))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    m = size * 0.16

    if kind == "align":
        # ★4区画（窓の並び）。2×2 の枠
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        gap = size * 0.12
        cell = (size - 2 * m - gap) / 2
        for r in range(2):
            for c in range(2):
                x = m + c * (cell + gap)
                y = m + r * (cell + gap)
                p.drawRoundedRect(QRectF(x, y, cell, cell), 1.5, 1.5)
    elif kind == "auto":
        # ★ロボットの顔（AIに任せる）。丸角の頭＋アンテナ＋目2つ
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        top = m + size * 0.14
        head = QRectF(m, top, size - 2 * m, size - m - top)
        p.drawRoundedRect(head, size * 0.18, size * 0.18)
        cx = size / 2
        p.drawLine(QPointF(cx, top), QPointF(cx, m * 0.5))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(col))
        er = size * 0.085
        ey = top + (size - m - top) * 0.42
        p.drawEllipse(QPointF(size * 0.38, ey), er, er)
        p.drawEllipse(QPointF(size * 0.62, ey), er, er)
    elif kind == "turbo":
        # ★早送り（倍速）。二重の三角
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(col))
        w = size - 2 * m
        p.drawPolygon(QPolygonF([
            QPointF(m, m), QPointF(m + w * 0.5, size / 2),
            QPointF(m, size - m)]))
        p.drawPolygon(QPolygonF([
            QPointF(m + w * 0.5, m), QPointF(m + w, size / 2),
            QPointF(m + w * 0.5, size - m)]))
    elif kind == "exit":
        # ★電源記号（終了）。上に隙間のある弧＋縦棒
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(m, m + size * 0.08, size - 2 * m, size - 2 * m)
        p.drawArc(rect, 70 * 16, 320 * 16)             # ★上に隙間
        p.drawLine(QPointF(size / 2, m * 0.5),
                   QPointF(size / 2, size * 0.5))
    p.end()
    return QIcon(pm)


class ElidedLabel(QLabel):
    """入りきらないとき、**末尾を「…」にする**1行のラベル。

    ★**黙って切らない**（QLabel は狭いと省略記号も出さずに切ります）。
    ★行数は増やしません。全文はマウス（ツールチップ）で読めます。

    ⚠ 全文は `full_text` に持ちます。**画面に出ている字を読み返さないこと**
      （切れた後の字が返ってきます）。
    ★経緯は `docs/history/ui-changes.md`。
    """

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.full_text = text
        self._show_elided()

    def setText(self, text: str) -> None:            # noqa: N802 (Qt の名前)
        self.full_text = text
        self._show_elided()

    def resizeEvent(self, event) -> None:            # noqa: N802 (Qt の名前)
        super().resizeEvent(event)
        self._show_elided()

    def _show_elided(self) -> None:
        from PySide6.QtGui import QFontMetrics

        width = self.width()
        if width <= 0:
            # ★まだ大きさが決まっていない（並べる前）。そのまま出す
            super().setText(self.full_text)
            return
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(
            self.full_text, Qt.TextElideMode.ElideRight, width))


class MainWindow(QWidget):
    INITIAL_LOG_LINES = INITIAL_LOG_LINES

    def __init__(self, view_model: ViewModel, *, interval_ms: int = 500,
                 heartbeat: "Callable[[], None] | None" = None,
                 log_buffer: Any = None,
                 gui_config: Any = None,
                 log_path: Any = None,
                 names_config: Any = None,
                 user_config: Any = None,
                 # ★地図を標準で出すか（2026-08-01 の指示書 §8）。
                 #   ⚠ テストでは既定で出さない（窓が増えると計測が濁る）。
                 show_map: bool = False) -> None:
        super().__init__()
        # ★名前は設定から。ゲーム内の名前は RAM から読めていない（panels.py 参照）
        self._names_config = names_config
        self.vm = view_model
        # 記録プロセスの二重起動を防ぐための心拍。更新のたびに叩く。
        self._heartbeat = heartbeat
        # ★低頻度の仕事を最後にやった時刻（2026-08-07 / 軽量化指示書 §6）
        self._slow_job_at: dict[str, float] = {}
        # ★人が頼んだ値と、頼んだ時刻（2026-08-07 / 軽量化指示書 §7.3）。
        #   ⚠ Lua が追いつくまで、ここの値を画面に出し続けます。
        self._pending_toggle: dict[str, tuple[bool, float]] = {}
        self._log_buffer = log_buffer
        self._log_cursor = 0
        # ★System Log は**共有ログファイル**を追う（MVP2 Phase 1）。
        #
        #   GUI Handler（log_buffer）には Python が書いた行しか入らない。
        #   実際のログは 3002 行のうち **Python 8 行 / Lua 2994 行**で、
        #   買い物・回復・警戒リストといった中身はすべて Lua 側にある。
        #   バッファだけを映すと、画面には数行しか出ず「動いていない」ように見える。
        #
        #   Python も同じファイルへ書いているので、**ファイルを追えば全部入る**。
        #   log_path が無いときだけバッファへ落ちる（テスト・埋め込み用）。
        self._log_path = pathlib.Path(log_path) if log_path else None
        # ★★ 画面に出す段階の下限（2026-08-13 / 製品版ログ整理）★★
        #   ⚠ `gui_level` は「画面に出す下限」と書いてあるのに**効いていなかった**。
        #     `_log_path` があるとファイルを直接読む道へ入り、
        #     `GuiLogHandler`（＝`gui_level` を見る側）を通らないため。
        #   ★ここで行の段階を見て絞る。読めない行は出す（`_show_in_gui`）。
        self._gui_level_rank = None
        if user_config is not None:
            try:
                want = user_config.logging.resolved()["gui_level"]
                self._gui_level_rank = int(want)
            except Exception:                          # noqa: BLE001
                # ⚠ 設定が読めなくても画面は動かす（★全部出るだけ）
                self._gui_level_rank = None
        self._rows_cache: list = []
        self._log_tailer = None
        # ★表示直後に一度だけログを一番下へ送るためのフラグ（showEvent を参照）。
        #   showEvent は最小化からの復帰などで何度も呼ばれるため、
        #   毎回送ると上へ戻って読んでいる利用者を引きずり降ろす。
        self._log_scrolled_on_show = False
        # ★自分がスクロールさせている間だけ真。利用者の操作と区別するため
        #   （区別しないと追従とチェックの付け外しが往復する）。
        self._scrolling_log = False
        # 図鑑の窓（開かれるまで None）と、直近に遭遇した敵種の集合。
        # ★集合を覚えておくのは「変わったときだけ」出すため。
        #   毎回出し直すと、利用者が別の敵を見ようと押しても戻される。
        self._book_window = None
        # 地図の窓（開かれるまで None）。★図鑑と同じく1つだけ作る
        self._map_window = None
        # ★同じマスに何度も居るので、**変わったときだけ**記録する。
        #   1マス歩くのに十数フレームかかるため、毎回書くと無駄が多い。
        self._last_position: tuple | None = None
        # ★この戦闘で出会った種（順を保つ）。**倒しても減らさない。**
        #   戦闘の入口で空にし、以後は足すだけ（`_track_encounter` を参照）。
        self._battle_species: list[int] = []
        self._encounter_active: bool | None = None
        # ⚠⚠ **`gui_config` と `user_config` は別物**（2026-07-30 に取り違えた）。
        #   `gui_config` = `user_cfg.gui`（幅・高さ・列など画面の設定）
        #   `user_config` = `UserConfig` 全体（`path()` を持つのはこちら）
        #
        #   ★`gui_config.path(...)` は **AttributeError** になる。
        #     それを `except Exception` で拾って既定へ落としていたため、
        #     **プログラムの間違いが「不明」に化けて隠れていた**
        #     （診断情報の「ログ: 不明」と、ログを開くボタンが無反応の原因）。
        self._cfg = gui_config
        self._user_cfg = user_config
        # ★セーブステート保護の状態を読む場所（仕様書 6.1）。
        #   ⚠ 設定が無いときも落ちないよう既定へ落とす。
        self._backup_lock_path = self._config_path(
            "backup_lock", "work/savestate_backup.lock")
        # ★版をタイトルに出す（仕様書 14章）。問い合わせで最初に聞かれる
        self.setWindowTitle(f"{version_title()} — ドラゴンクエストII")
        # 1920×1080 を基準にする。画面が小さい環境でも縮んで収まるよう
        # 固定サイズにはしない（指示書 5.1「比率を維持して縮小」）。
        width = getattr(gui_config, "width", 1920)
        height = getattr(gui_config, "height", 1080)
        self.resize(int(width * 0.9), int(height * 0.9))

        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ★★ 2026-08-11: 右列を FCEUX 2倍に近い高さへ圧縮（依頼者の指示）★★
        #   並び（上から）: 危険バナー / パーティ状態 / 戦略 / 新AIの判定 /
        #     ボタン列1（図鑑ほか）/ ボタン列2（整列・Auto・Turbo・終了）/
        #     セーブ保護（細い1行）。
        #   ⚠ 状態・速度・AUTO・版・いまどこは**出さない**（ボタン・ゲーム画面・
        #     タイトルバー・地図で分かる）。値を書く部品は `_build_header` が
        #     隠しで残す（`_render` の書き込み先が消えると直す範囲が広がるため）。
        self._warning = self._build_warning()
        root.addWidget(self._warning)

        # ★★ 縦の並び（2026-08-11 / 依頼者の指定）★★
        #
        #   1 セーブステート保護 / 2 戦略 / 3 パーティ状態
        #   4 ボタン列1（戦術ほか） / 5 ボタン列2（整列ほか） / 6 戦況
        #
        #   ★狙いは「**高さの変わるものを上に置かない**」。この並びなら、
        #     この画面に**中身で高さが変わる段はありません**。
        #   ⚠ 順番を変えるときは、上から下へ「固定 → 可変」を崩さないこと。
        #   ★これまでの並びの変遷は `docs/history/ui-changes.md`。
        root.addWidget(self._build_header())          # 1 セーブステート保護
        root.addLayout(self._build_strategy_row())    # 2 戦略
        root.addWidget(self._build_party_panel())     # 3 パーティ状態

        from .log_window import LogWindow

        # ★★ 下段（2026-08-09 / 依頼者の指示）★★
        #
        #   上 : 出会った敵（戦闘中にいちばん見たいもの）
        #   下 : System Log
        #
        #   ⚠ 戦闘ログの表は**廃止**しました。記録された戦闘は
        #     `_log_new_battles` が System Log へ1行で流します。
        #   ⚠ 図鑑は「開く」ボタンだけの中身だったので、右（この画面）へ
        #     アイコンで移しました。
        #   ★中身が1つになったのでタブはありません。
        self._log_window = LogWindow(
            top=self._build_encounter_panel(),
            panels=[("System Log", self._build_system_log_panel())])

        # ★★ 操作パネルは**この画面（右）**へ（2026-08-09 / 依頼者の指示）★★
        #   ⚠ `_build_monster_book_panel` という名前ですが、中身は図鑑ボタン
        #     だけではありません（地図・戦術・まんたん・目的・作戦）。
        #     ★依頼者の「名前が適切でない」はこのことです。
        #   ⚠ ここは下段のタブに置く中身ではなく、**いつでも押したい操作**です。
        root.addWidget(self._build_monster_book_panel())   # 4 ボタン列1
        # ★★ **前回の場所を戻してから出します**（2026-08-09）★★
        #   ⚠ 戻さないと毎回きまった大きさ（1264×216）で左上に出ます。
        #     依頼者「起動するときに、前回の位置、サイズをなるべく再現してほしい」
        #   ⚠⚠ **背が低いので下限を下げて渡す**（2026-08-11 に発覚）★★
        #     ログ窓は横長で ~150px。主画面向けの下限（240px）だと毎回はじかれ、
        #     ★「下のログ画面だけ場所が保持されない」状態だった（依頼者の報告）。
        _log_saved = self._window_state().get("log")
        _log_ok = self._window_state().apply_to(
            "log", self._log_window, min_height=120)
        get_logger("gui").debug(
            "窓の復元 log: 試み=%s → %s",
            (f"{_log_saved.get('x')},{_log_saved.get('y')} "
             f"{_log_saved.get('w')}×{_log_saved.get('h')}"
             if _log_saved else "記録なし"),
            "適用" if _log_ok else "既定")
        #   ⚠ 本体の `showEvent` まで待つと、それまで中のパネルが
        #     `isVisible() == False` のままになります。★見えていないパネルへ
        #     書き込んでも画面には出ないので、更新の確認ができません。
        self._log_window.show()

        root.addWidget(self._build_emulator_area())        # 5 ボタン列2
        root.addWidget(self._build_reasoning_row())        # 6 戦況
        # ★縦の余りは**最下部**に集める（上の段を詰めるため）。
        root.addStretch(1)

        # ⚠ 戦闘の記録の要約は下段のログ窓が担うので、右列には出さない（隠し）。
        #   ★値を書く経路は残す（`_render` が書きに来る）。
        self._summary = QLabel("-")
        self._summary.setWordWrap(True)
        self._summary.setVisible(False)

        # ★メイン画面の図鑑が使う行を先に用意する（戦闘の入口で DB を触らない）
        self._load_encounter_rows()

        # ★★ 前回の位置とサイズを戻す（仕様書 8章）★★
        #   ⚠ **中身を組み立てたあとに呼ぶ**。前に呼ぶとレイアウトが
        #     組まれるときに上書きされる。
        self._win_state = None
        self.restore_window_state()

        # ★画面更新の所要時間を測る道具（既定は無効 / 指示書 §10.3）
        from .perf import Probe
        self._perf = Probe.from_env(logger=get_logger("gui"))

        # ★★ 窓と OS の世話係（2026-08-01 のリファクタ §5.2）★★
        #   ⚠ この画面から Windows API を呼ばない。呼ぶと画面のテストが
        #     Win32 を必要とし、窓の探し方がボタンごとに散らばる。
        from .window_manager import WindowManager
        self.windows = WindowManager(self._user_config,
                                     logger=get_logger("gui"))

        # ★★ アクション層（2026-08-01 の指示書 §11）★★
        #   ボタン・キーボード・（将来の）ゲームパッドが**同じ入口**を通る。
        #   ⚠ フォーカスの後始末はここが1か所で行う（§10.3）。
        self._build_actions()

        # ★作戦リストへ現在値を入れる（2026-08-04 / 指示書 §4）。
        #   ⚠ `refresh()` の前に一度だけ。★毎回作り直すと、開いている
        #     リストが閉じたり、選ぼうとした瞬間に中身が入れ替わります。
        self.reload_tactics_picker()
        # ★目的のラジオへ現在値を入れる（2026-08-05 / Phase 3）
        self.reload_mission_buttons()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(interval_ms)
        self.refresh()

        # ★★ 地図は**標準で出す**（2026-08-01 の指示書 §8）★★
        #   RetroUX の主要機能なので、毎回ボタンを押させない。
        #   ⚠ **フォーカスは奪わない**（出しただけでゲームの操作を取らない）。
        #   ⚠ 落ちても本体は止めない（地図が無くても遊べる）。
        if show_map:
            try:
                self._ensure_map_window().show()
            except Exception as exc:                   # noqa: BLE001
                get_logger("gui").warning("地図を開けませんでした: %s", exc)

    # --- 構築 --------------------------------------------------------

    def _build_header(self) -> QFrame:
        """常時表示（2026-08-11 / 依頼者の指示で圧縮）。

        ★★ 右列を FCEUX 2倍に近い高さへ。**重複を消す** ★★
          ・状態 / 速度 / AUTO … ボタンとゲーム画面で分かるので出さない
          ・版                 … タイトルバーで分かるので出さない
          ・いまどこ            … 地図で分かるので出さない
          ・取り込み / 戦術     … 戦略ドロップダウンと下段ログで分かるので出さない
        ★残すのは「見て分からない安全表示」だけ：セーブステート保護（6.1）。

        ⚠⚠ **消した表示の部品は残す。** `_render` がこれらに値を書きに来る。
          参照を消すと更新側も直す必要が広がるので、★画面には出さず（hidden）
          部品だけ frame に隠して持つ。
        """
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        box = QVBoxLayout(frame)
        box.setContentsMargins(6, 2, 6, 2)
        box.setSpacing(2)

        # ⚠ 画面に出さない部品（値は _render が書きに来る）。★frame を親にして
        #   隠す（親なしだと単独ウィンドウとして開いてしまう）。
        self._state_value = QLabel("-", frame)
        self._speed_value = QLabel("-", frame)
        self._auto_value = QLabel("-", frame)
        self._version_label = QLabel(version_title(), frame)
        self._where = QLabel("いまどこ: —", frame)
        self._mode_value = QLabel("-", frame)
        self._tactics_label = QLabel("戦術: —", frame)
        for hidden in (self._state_value, self._speed_value, self._auto_value,
                       self._version_label, self._where, self._mode_value,
                       self._tactics_label):
            hidden.setVisible(False)

        # ★★ セーブステート保護（仕様書 6.1 / 公開時の訴求機能）★★
        self._backup_label = QLabel("セーブステート保護: —")
        self._backup_label.setStyleSheet(_STATUS_TEXT)
        self._backup_label.setMinimumWidth(1)
        box.addWidget(self._backup_label)
        return frame

    def _build_strategy_row(self) -> "QHBoxLayout":
        """戦略ドロップダウン（利用者が触るのは原則これだけ / 指示書§2）。

        ★2026-08-11: パーティ状態のすぐ下へ（依頼者の並び）。中身の作り自体は
          以前と同じ（`_strategy_picker` / `activated` は人の操作だけ）。
        """
        strategy_row = QHBoxLayout()
        strategy_row.addWidget(QLabel("戦略"))
        self._strategy_picker = QComboBox()
        self._strategy_picker.setToolTip(
            "どう遊ぶかを1つだけ選びます。★中の細かい判断は AI に任せます。\n"
            "⚠ 反映は次のターンからです（いま入力済みの行動は変わりません）。")
        for value, text, note in self.vm.strategy_choices():
            self._strategy_picker.addItem(text, value)
            if note:
                self._strategy_picker.setItemData(
                    self._strategy_picker.count() - 1, note,
                    Qt.ItemDataRole.ToolTipRole)
        self._strategy_picker.activated.connect(
            lambda i: self._on_strategy_picked(
                self._strategy_picker.itemData(i)))
        strategy_row.addWidget(self._strategy_picker, stretch=1)
        return strategy_row

    def _build_reasoning_row(self) -> QFrame:
        """新AIの判定（戦況・役割）を**固定行のマトリクス**で出す。

        ★★ 2026-08-11: 依頼者「行の増減が出ないように」★★
          以前は折り返しで、内容によって 1〜3 行に伸び縮みしていた（戦闘のたびに
          高さが変わって落ち着かない）。★**折り返さず1行**にして、行数を固定する。
          はみ出すぶんはマウスで全文（ツールチップ）。読む順は 戦況 → 役割。
        """
        from PySide6.QtWidgets import QGridLayout

        frame = QFrame()
        grid = QGridLayout(frame)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(2)
        grid.setHorizontalSpacing(6)

        # ★★ 見出しは「戦況」（2026-08-11 / 依頼者の指定）★★
        #
        #   ⚠ ここは「AIが戦況を見て判断しています」という**文**でした。
        #     ★他の段（パーティ状態・敵情報）と同じ**見出し**にそろえます。
        #   ⚠⚠ ただし「**まだ効かせていない**」ことは消しません（省資源なのに
        #     MP を使って見える、という誤解の元）。★そのときだけ見出しに
        #     「⚠ 試験中」を足し、詳しい説明はツールチップに入れます。
        #   ★行数を増やさないため、見出しは**いつも1行**です。
        self._battle_engine_label = _section("戦況")
        self._battle_engine_label.setWordWrap(False)
        grid.addWidget(self._battle_engine_label, 0, 0, 1, 2)

        # ★★ 2026-08-12: **縦4行**へ（依頼者の指示 §2・§4）★★
        #
        #   ⚠ これまでは戦況・推定ターン・戦術・役割を**横に詰め込んで**
        #     いたので、幅が狭いと黙って切れていました。
        #   ★縦は4行使えるので、1行1項目に開きます。
        #
        #       優勢・短期
        #       撃破 0.5T / 崩壊 4.2T
        #       戦術 省資源 5.5/+1.5
        #       役割 ロ:攻3.0 サ:道1.3 ム:道1.3
        #
        #   ⚠⚠ **見出し列（「戦況」「役割」）は置きません。**
        #     行の中に「戦術」「役割」と書いてあり、いちばん上は
        #     グループ見出し「戦況」で分かるためです（指示 §2・§3.1）。
        #   ★入りきらないぶんは末尾が「…」（行数は増やさない）。
        self._assessment_rows = []
        for r in range(4):
            label = ElidedLabel("—")
            label.setStyleSheet(_STATUS_TEXT)
            label.setWordWrap(False)                   # ★折り返さない＝行数固定
            grid.addWidget(label, r + 1, 0, 1, 2)
            self._assessment_rows.append(label)
        grid.setColumnStretch(1, 1)
        for label in frame.findChildren(QLabel):
            label.setMinimumWidth(1)
        # ★★ ツールチップは**欄ぜんぶ**に付ける（指示 §18）★★
        #   ⚠ 4行それぞれに別々に付けると、マウスの位置で内容が変わって
        #     読みにくくなります。★どこに乗せても同じレビューが出ます。
        self._reasoning_frame = frame
        return frame

    @staticmethod
    def _set_label(label, text: str) -> None:
        """見出しを書き換える。★全文をツールチップにも入れる（2026-08-09）。

        ⚠ 狭い窓では QLabel は**黙って切れます**（省略記号も出ません）。
          ★2026-08-11: 戦況・役割は `ElidedLabel` にして、
            **入りきらないときは末尾が「…」**になるようにしました。
        ★どちらの場合も、マウスを乗せれば全文が読めます。
        """
        label.setText(text)
        label.setToolTip(text)

    def _update_reasoning(self, game) -> None:
        """推論の4段を書き換える（2026-08-07 / Phase 9）。

        ⚠⚠ **「届いていない」と「0」を分ける。**
          ★`—` は材料が無いこと、数字は測った結果です。
          両方を 0 で出すと、⚠ **測れていないことに永久に気づけません**。
        """
        # ★★ 変わったときだけ書き直す（2026-08-07 / 軽量化指示書 §5.6）★★
        #   ⚠ 4行とツールチップは毎回文字列を組み立てます。
        #     ★戦況は1ターン変わらないので、0.2秒ごとに組み直す意味がありません。
        #   ★★ 2026-08-12: 鍵に**レビューの版**も入れます（指示 §20）。
        #     ⚠ 入れないと、ターンが進んでもツールチップが古いままです。
        rows = self.vm.assessment_rows()
        engine = getattr(game, "battle_engine", None)
        key = (engine, tuple(rows), self.vm.battle_review_revision())
        if key == getattr(self, "_last_reasoning_key", None):
            return
        self._last_reasoning_key = key

        # ★★ 2026-08-11: 初見の人に分かる言葉へ（依頼者の指摘）★★
        #   ⚠ 「新AI」「説明のみ・従来どおり」は開発用の言い回しで、初めての
        #     人には意味が伝わらない。★AI が戦っていること＋下の戦況分析が
        #     **試験中**（判断にはまだ使っていない）ことを平易に書く。
        #   ★★ 2026-08-11: 見出しは「戦況」に固定し、engine の説明は
        #     ツールチップへ（依頼者の指定）。⚠ 「試験中」だけは見出しに出す。
        if engine is None:
            note = "⚠ まだ届いていません（FCEUX が動いていないかもしれません）"
            self._battle_engine_label.setText("戦況")
        elif engine == "layered":
            note = "AIが戦況を見て判断しています"
            self._battle_engine_label.setText("戦況")
        else:
            note = ("AIが戦っています"
                    "（下の戦況分析は試験中で、判断にはまだ使っていません）")
            self._battle_engine_label.setText("戦況　⚠ 試験中")
        self._battle_engine_label.setToolTip(note)

        # ★★ 4行を書き換える（2026-08-12 / 指示 §4）★★
        #   ⚠ 行数は常に4です。狭くても1行へ畳みません（指示 §4 の末尾）。
        for label, text in zip(self._assessment_rows, rows):
            label.setText(text)

        # ★★ ツールチップ = 根拠（全ターンのレビュー / 指示 §6・§7）★★
        #   ⚠ 4行それぞれではなく、**欄ぜんぶ**に同じものを付けます（§18）。
        review = self.vm.battle_review_tooltip()
        self._reasoning_frame.setToolTip(review)
        for label in self._assessment_rows:
            label.setToolTip(review)

    def _refresh_backup_status(self) -> None:
        """セーブステート保護の稼働表示（仕様書 6.1）。

        ★★ **止まっていることが分かるようにする。** ★★
          止まっていると、上書き事故から守られていない。
          ⚠ 黙って止まるのが一番困る（守られていると思って遊んでしまう）。
        """
        from ..core import backup_status

        try:
            status = backup_status.read(self._backup_lock_path)
        except Exception:                              # noqa: BLE001
            # ⚠ 表示のための処理で本体を止めない
            return
        text = status.label
        if status.running and status.last_backup:
            text += f"（最新 {status.last_backup}）"
        if status.generations is not None:
            text += f" / {status.generations}世代"
        self._backup_label.setText(text)
        self._backup_label.setToolTip(status.tooltip())
        self._backup_label.setStyleSheet(
            "color:#ffb84d; font-weight:bold;" if status.is_warning
            else "color:#8fd18f;")

    def _build_warning(self) -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setVisible(False)
        label.setStyleSheet(
            "background:#5a1d1d; color:#ffd9d9; padding:8px; border-radius:4px;"
        )
        return label

    def _build_encounter_panel(self) -> QWidget:
        """出会った敵の図鑑を**メイン画面に**置く（2026-07-27 / 依頼者の要望）。

        > モンスターと出会ったときのモンスター図鑑は、メイン画面に出したい。
        > 敵モンスターパーティーは全部まとめて出したい。

        ★別ウィンドウは残す（83体の一覧はここに入らない）が、
          **遭遇時に勝手に開くのはやめた**。メインに出るならその必要が無く、
          窓が飛び出す副作用（フォーカス・並びの乱れ）も無くなる。
        """
        from .encounter_panel import EncounterPanel

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        # ★★ 2026-08-09: 見出しは出しません（依頼者の指示「いらない」）★★
        #   ⚠ 下段の上段はここ専用なので、何の欄かは置き場所で分かります。
        #     1行ぶんの高さを札に回します。
        self._encounter = EncounterPanel(self.vm)
        layout.addWidget(self._encounter, stretch=1)
        return panel

    def _build_party_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        # ★★ パーティ状態の見出しに **G（所持ゴールド）** を並べる ★★
        #   （2026-07-31 / 依頼者の要望）
        #   ⚠ ゴールドは**パーティ共通**なので、人ごとの表には入れない。
        #     見出しの行に置くと「誰の値でもない」ことが形で伝わる。
        head = QHBoxLayout()
        head.addWidget(_section("パーティ状態"))
        head.addStretch(1)
        head.addWidget(QLabel("G"))
        self._gold_value = QLabel("-")
        big = QFont()
        big.setBold(True)
        self._gold_value.setFont(big)
        head.addWidget(self._gold_value)
        # ⚠ 紋章はまだ出せない。**在り処が分かっていない**ので枠も作らない
        #   （空欄を並べると「持っていない」に見える / playbook）。
        layout.addLayout(head)

        self._party = PartyPanel(names=getattr(self, "_names_config", None))
        layout.addWidget(self._party)

        # ★★ 2026-08-11: パーティ状態の縦を詰める（依頼者「半分くらいいけそう」）★★
        #   ⚠ 敵情報を畳むと、その高さがこの段（split の最後）へ回り、3行の表の
        #     下に大きな空白になっていた。★この入れ物の**最大の高さを内容ぶんに
        #     縛る**と、split は余りをここへ積めなくなる（余りは最下部の伸縮へ）。
        #   ⚠ 実際の上限は `_render` が表の高さから毎回付け直す（人数で変わる）。
        from PySide6.QtWidgets import QSizePolicy

        panel.setSizePolicy(QSizePolicy.Policy.Preferred,
                            QSizePolicy.Policy.Maximum)
        self._party_container = panel

        # ★★ 2026-08-09: AI判断は **System Log へ**（依頼者の指示）★★
        #   ⚠ 「選択／理由」の表が縦を大きく取り、右列（510px）に
        #     パーティ状態と同居できませんでした。
        #   ★部品は作ります（更新の経路を変えないため）。⚠ 画面には出しません。
        #     中身は `_log_ai_decision` が変化したときだけ1行で流します。
        self._ai = AiPanel(names=self._names_config)
        self._ai.setVisible(False)
        return panel

    def _build_emulator_area(self) -> QWidget:
        """FCEUX を並べる案内。**埋め込まないので画面は映らない。**"""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)

        note = QLabel(
            "FCEUX は<b>この画面の左隣</b>に並べます（GUI の中には埋め込みません）。"
            "埋め込むと入力フォーカスとジョイパッドを壊す危険があるためです。"
        )
        # ★★ 2026-08-09: **画面には出しません**（依頼者の指摘）★★
        #   > メッセージが邪魔している？
        #   ⚠ そのとおりでした。折り返して2〜3行を占め、右列の高さを
        #     食っていました。★1回読めば足りる説明なので、ボタンの
        #     ツールチップへ回します（`整列` の説明と同じ場所）。
        note.setVisible(False)
        self._emulator_note_text = note.text()

        # ★★ 2026-08-09: ボタンは **2行2列**（4区画の右列は 362px）★★
        #   ⚠ 横一列だとボタンだけで 412px 要り、窓が細くなれませんでした。
        row = QGridLayout()
        # ⚠ 以前は「FCEUX を左隣へ整列」だったが、**3つとも動かす**ので嘘だった
        #   （Lua Script は左 / FCEUX は真ん中 / この画面は右）。
        # ★★ 標準レイアウトに戻す（2026-08-01 の指示書 §7.1）★★
        #   ⚠ 確認ダイアログは出さない。**元に戻す操作**なので、
        #     押し間違えても失うのは「自分で動かした配置」だけ。
        # ★★ 2026-08-19: 画像アイコンにする（RX-0071 / 依頼者）★★
        #   ⚠ 文字・絵文字は実機で字形が化けたので、`QPainter` で描く
        #     （フォント・外部ファイルに依存しない / `_button_icon`）。
        #   ★色はテーマの文字色。明暗どちらでも見える。
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QPalette

        _icon_color = self.palette().color(QPalette.ColorRole.ButtonText)
        _icon_size = QSize(18, 18)

        # ★2026-08-09: アイコンに（説明は下のツールチップに全部あります）
        self._align_button = QPushButton()
        self._align_button.setIcon(_button_icon("align", _icon_color))
        self._align_button.setIconSize(_icon_size)
        self._align_button.setFixedWidth(38)
        # ★★ 2026-08-09: 並びが4区画に変わったので**説明も直す** ★★
        #   ⚠ ここは「下左 : 見た地図」のままでした。ラベルを短くするなら、
        #     せめて説明は実際の動きと合っていないと嘘になります。
        self._align_button.setToolTip(
            "整列する\n"
            "覚えている配置を捨てて、標準の並びへ戻します\n"
            "  左   : 見た地図\n"
            "  中央 : FCEUX（ゲーム画面）\n"
            "  右   : この画面\n"
            "  下   : ログ（戦闘ログ／System Log／図鑑）\n"
            "  最小化: Lua Script（閉じると Lua が止まるので閉じません）\n"
            "⚠ 画面が狭いときは従来の並び（FCEUX の下に見た地図）へ落ちます\n"
            "★終わったらゲーム画面へ操作が戻ります\n"
            "★キーボードの Ctrl+Shift+R でも実行できます")
        self._align_button.clicked.connect(
            lambda: self.run_action("reset_layout"))
        row.addWidget(self._align_button, 0, 0)

        # ★★ **AUTO と 高速化 は別のトグル**（2026-07-31 の指示書 §6）★★
        #
        #   | ボタン | 答える問い |
        #   | --- | --- |
        #   | AUTO | **誰が操作するか**（AIに任せる / 自分で操作する） |
        #   | 高速化 | **どの速度で動かすか**（倍速 / 等速） |
        #
        #   ⚠⚠ 一度は1つのボタンにまとめたが、それだと
        #     「等速で AUTO」「高速化を保ったまま手動へ」が選べなかった。
        #     **2つの問いを1つのスイッチに載せない。**
        # ★2026-08-09: アイコンは「A」（依頼者の指定）。
        #   ⚠ 入切は押し込みの見た目で分かりますが、それだけでは弱いので
        #     **ツールチップの1行目に必ず状態を書きます**（`_apply_toggle_tip`）。
        self._auto_button = QPushButton()
        self._auto_button.setIcon(_button_icon("auto", _icon_color))
        self._auto_button.setIconSize(_icon_size)
        self._auto_button.setFixedWidth(38)
        self._auto_button.setCheckable(True)
        self._auto_button.setChecked(True)
        self._auto_tip = (
            "AI に戦闘の操作を任せるかを切り替えます\n"
            "★速度は変わりません（速度は「高速化」のほうです）\n"
            "★**キーボードの A キー**でも切り替わります\n"
            "　（ゲームパッドの A ボタンではありません）\n"
            "★手動で回復したあと A を押すと、"
            "そのときの速度設定のまま AUTO へ戻ります")
        self._auto_button.toggled.connect(self._on_auto_toggled)
        row.addWidget(self._auto_button, 0, 1)

        # ★★ **高速化の入切**（2026-07-31 / 依頼者の要望）★★
        #   ⚠ AI の動きを見たいときに倍速だと**読む前に終わる**。
        #     倍速を使わない遊び方もあるので、その場で切れるようにする。
        #   ★入れっぱなしが今までどおりなので、**既定は入**。
        # ★2026-08-09: アイコンは「T」（依頼者の指定 / turbo）。
        self._turbo_button = QPushButton()
        self._turbo_button.setIcon(_button_icon("turbo", _icon_color))
        self._turbo_button.setIconSize(_icon_size)
        self._turbo_button.setFixedWidth(38)
        self._turbo_button.setCheckable(True)
        self._turbo_button.setChecked(True)
        self._turbo_tip = (
            "戦闘速度だけを切り替えます\n"
            "★AUTO の ON/OFF には影響しません\n"
            "★切ると戦闘は等速になります（AI の判断を目で追えます）\n"
            "⚠ まんたん等の自動操作の速さは変わりません（戦闘だけです）")
        self._apply_toggle_tip(self._auto_button, self._auto_tip,
                               "AUTO", True)
        self._apply_toggle_tip(self._turbo_button, self._turbo_tip,
                               "高速化", True)
        self._turbo_button.toggled.connect(self._on_turbo_toggled)
        row.addWidget(self._turbo_button, 0, 2)

        # ★終了ボタン。押し間違えると**ゲームが閉じる**ので、
        #   ここだけ確認ダイアログを出す（他のボタンには出していない）。
        #   ⚠ 以前は「保存して終了」だったが、ダイアログで
        #     **保存せずに終了も選べる**ので嘘だった。
        self._exit_button = QPushButton()
        self._exit_button.setIcon(_button_icon("exit", _icon_color))
        self._exit_button.setIconSize(_icon_size)
        self._exit_button.setFixedWidth(38)
        self._exit_button.setToolTip(
            "終了する\n"
            "FCEUX・バックアップ・この画面を終了します\n"
            "★押したあとに「保存して終了」か「保存せずに終了」を選べます")
        self._exit_button.clicked.connect(self._on_exit_clicked)
        # ★★ 2026-08-09: ⊞ A T ✕ は**1列に並べる**（依頼者の指示）★★
        #   > 窓整理、A,T,☓ はそのボタン群の下に一列でもっていける
        #   ⚠ アイコンにしたので 4つでも 170px ほど。1行に収まります。
        row.addWidget(self._exit_button, 0, 3)
        row.setColumnStretch(4, 1)

        self._align_status = QLabel("")
        self._align_status.setWordWrap(True)
        # ★狭い窓でも畳めるように（2026-08-09）。⚠ 行いっぱいを使う
        self._align_status.setMinimumWidth(1)
        row.addWidget(self._align_status, 1, 0, 1, 5)
        layout.addLayout(row)
        return frame

    # --- 終了 --------------------------------------------------------

    def _on_exit_clicked(self) -> None:
        """セーブステートを保存してから、RetroUX 一式を終了する。

        ★★ 押し間違いが**取り返しのつかない事故**になりうる ★★
          ・セーブステートのスロットは**上書き**される
          ・ゲームが閉じる
          だから、**何をするかを書いた確認**を必ず出す。
          「はい/いいえ」ではなく、やることを3択にして選ばせる。

        ★終了のさせ方（強制終了しない）:
          FCEUX     … ウィンドウに「閉じて」と伝える（× と同じ）。
                      強制終了すると設定ファイルを書かずに落ちる。
          バックアップ … 停止ファイルで伝える。コピーの途中で殺すと
                      **壊れた世代**が「戻れる状態」の顔をして残る。
        """
        from PySide6.QtWidgets import QMessageBox

        from ..core.config import user_config as user_config_mod

        cfg, _ = user_config_mod.load()
        slot = cfg.shutdown.save_slot

        box = QMessageBox(self)
        box.setWindowTitle("RetroUX を終了します")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("RetroUX 一式（FCEUX / バックアップ / この画面）を終了します。")

        # ★★ **できないことは、押す前に言う**（2026-08-01 / 実機で判明）★★
        #
        #   ⚠⚠ 閲覧専用のときは保存を頼めない（`CommandService` が断る）。
        #     それなのに「保存して終了」を押せてしまい、失敗すると
        #     **終了を中止**するので、利用者は**終われなくなっていた**。
        #     実機のログに 13:47:50 / 13:48:02 / 13:49:45 と3回残っている。
        #   ★押せるが失敗する、が一番たちが悪い。押せなくして理由を書く。
        read_only = bool(getattr(self.vm, "read_only", False))
        if read_only:
            box.setInformativeText(
                "⚠ <b>いまは閲覧専用</b>なので、セーブステートを保存できません。<br>"
                "別の RetroUX が記録役になっています"
                "（そちらで保存するか、先に終了してください）。<br>"
                "この画面は「保存せずに終了」で閉じられます。"
            )
        else:
            box.setInformativeText(
                f"「保存して終了」を選ぶと、セーブステートの<b>スロット {slot}</b> へ"
                "保存してから終了します。<br>"
                f"⚠ スロット {slot} の内容は<b>上書き</b>されます"
                "（直前の内容は世代バックアップに残るので戻せます）。"
            )

        save_btn = box.addButton("保存して終了", QMessageBox.ButtonRole.AcceptRole)
        plain_btn = box.addButton("保存せずに終了", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("やめる", QMessageBox.ButtonRole.RejectRole)
        if read_only:
            save_btn.setEnabled(False)
            save_btn.setToolTip("閲覧専用なので保存できません")
        box.setDefaultButton(cancel_btn)      # ★既定は「やめる」
        box.exec()

        clicked = box.clickedButton()
        if clicked is cancel_btn:
            return
        self._shutdown(cfg, save=(clicked is save_btn))

    def _shutdown(self, cfg, *, save: bool) -> None:
        from ..core.logging_setup import get_logger

        log = get_logger("gui")
        self._exit_button.setEnabled(False)

        if save:
            self._align_status.setText(
                f"セーブステートをスロット {cfg.shutdown.save_slot} へ保存しています…")
            # ★描画を進めてから待つ（押した直後に固まったように見せない）
            from PySide6.QtWidgets import QApplication

            QApplication.processEvents()
            if not self._request_savestate(cfg, log):
                # ★保存を確認できないまま閉じない。
                #   閉じてしまうと「保存したつもり」で進行が消える。
                # ⚠ **なぜ駄目だったかを書く**（2026-08-01）。
                #   理由なしに「中止します」とだけ出ていたため、
                #   利用者は何度も押し直すことになった（実機のログに3回）。
                why = getattr(self, "_save_problem", None)
                self._align_status.setText(
                    "セーブステートの保存を確認できませんでした。終了を中止します。"
                    + (f"（{why}）" if why else "")
                    + "　★「保存せずに終了」なら閉じられます。")
                self._exit_button.setEnabled(True)
                return

        log.info("RetroUX を終了します（保存%s）", "あり" if save else "なし")

        # ★closeEvent が「終了ボタン経由か外部クローズか」を書けるように印を残す
        #   （2026-08-19 / RX-0077）。⚠ フラグが無い＝×/Alt+F4/セッション終了。
        self._closing_via_exit_button = True
        self.close()          # ★後始末は `closeEvent` が1か所で行う

    def _teardown(self) -> None:
        """★★ **どの閉じ方でも同じ後始末をする**（2026-08-18 / RX-0058）★★

        ⚠⚠ ここは長らく `_shutdown()`（「終了」ボタン）の中だけにあった。
          ★つまり **× ボタンで閉じた人には FCEUX が残った**。

            「終了」ボタン … ★FCEUX も止まる
            ⚠ × ボタン    … ⚠ **止まらない**（子窓を閉じるだけ）

        ★`closeEvent` は**すべての終了経路が通る**ので、ここへ移す。

        ⚠ 2回呼ばれる（ボタン → `close()` → `closeEvent`）ので、
          ★1度だけ動くようにする。
        """
        if getattr(self, "_torn_down", False):
            return
        self._torn_down = True

        # ★ゲームパッドの巡回を止める（RX-0076）。⚠ 無い構成もある。
        timer = getattr(self, "_gamepad_timer", None)
        if timer is not None:
            # ★止める前に「全部離す」を1回書く（bridge に押しっぱなしを残さない）
            self._write_gamepad_nes(0)
            timer.stop()

        # ⚠ import は関数の中（★この計画の作法）。
        #   ⚠⚠ ここを忘れて `NameError` を作った（2026-08-18 / 検査が捕まえた）。
        from ..core.config import user_config as user_config_mod
        from ..core.logging_setup import get_logger

        log = get_logger("gui")
        cfg, _ = user_config_mod.load()

        # FCEUX に「閉じて」と伝える（★強制終了しない）
        try:
            if self.windows.ask_emulator_to_close():
                log.debug("%s に終了を伝えました",
                          cfg.emulator.window_title_contains)
        except Exception as exc:                      # noqa: BLE001
            # ⚠ 後始末で落ちても、閉じること自体は続ける
            log.warning("FCEUX へ終了を伝えられませんでした: %s", exc)

        # バックアップに停止の合図（コピーの途中で殺さないため）
        try:
            stop_path = cfg.path("backup_lock").with_suffix(".stop")
            stop_path.write_text("stop", encoding="utf-8")
            log.debug("セーブステートのバックアップに停止を伝えました")
        except OSError as exc:
            log.warning("バックアップへ停止を伝えられませんでした: %s", exc)

    def _savestate_file(self, cfg, slot: int):
        """そのスロットのセーブステートのファイル。★無ければ None。

        FCEUX は `<fcs>/<ROM名>.fc<スロット>` に書く（例 `DQ2_J.fc1`）。
        置き場は `retroux/tools/savestate_backup.py` が見張っているのと同じ場所。
        """
        try:
            from ..tools.savestate_backup import DEFAULT_SRC

            stem = pathlib.Path(cfg.path("rom")).stem
            return pathlib.Path(DEFAULT_SRC) / f"{stem}.fc{int(slot)}"
        except Exception:                              # noqa: BLE001
            return None

    # --- AUTO と 高速化（独立した2軸 / 2026-07-31 の指示書 §6）-----------
    #
    # ★★ **状態を持っているのは Lua 側** ★★
    #   AUTO も 高速化 も、画面のボタンと**キーボードの A キー**の両方が
    #   書き手になりうる。ボタンが自分の値を覚えていると食い違うので、
    #   毎回 state.json からもらって合わせる。
    #
    # ⚠ 2軸で処理が同じなので、**1組の関数**にまとめてある。
    #   別々に書くと、片方だけ直したときに動きが食い違う
    #   （それがこの機能で実際に起きた壊れ方）。

    # ★★★ 頼んだ値が Lua に届くまでの猶予（秒）。
    #
    # ⚠⚠ **依頼者の報告「高速化ONOFFボタンを押しても利かない時がある」の正体**
    #   （2026-08-07 に実測して分かりました）:
    #
    #       押す         ボタンは即 ON になる
    #        ↓ 0.2秒     画面が state.json を読む -> Lua はまだ OFF
    #                    ★ここでボタンが **OFF に戻る**（押しても効かないように見える）
    #        ↓ 0.5秒     Lua が command.json を読んで ON にする
    #        ↓ 0.2秒     ボタンがまた ON に戻る
    #
    #   ★押していないのに勝手に往復するので、「効かない」と読めます。
    #   ⚠ 実際には**効いていました**（ただ 0.7 秒ほど表示が嘘をついていた）。
    #
    # → ★軽量化指示書 §7.3 の `requested` / `active` を分けます。
    #   ⚠ 猶予つき。★返事が来ないまま黙って居座ると、今度は**逆の嘘**になります。
    TOGGLE_CONFIRM_SECONDS = 2.0

    def _badge_with_request(self, badge, label: str):
        """押した直後の表示（2026-08-08 / 依頼者の指摘）。

            > AUTOと高速化ボタンが、エミュで動作したら始めて色が変わる。
            > 知らない人は反応してないのかな？と思う

        ⚠ ボタンの文字はその場で変わりますが、★上の見出しの
          「AUTO: ON」の**色**は state.json 由来なので、
          FCEUX が受け取るまで（0.2〜0.7秒）変わりませんでした。

        ★★ **押したことは押した瞬間に出す。⚠ ただし「届いた」とは言わない。**
          `docs/` の作法どおり、⚠ 確かめていないことを確かめたように書きません。
          → `ON …（反映待ち）` と出し、色は「気づいてほしい」側にします。

        ⚠ 届いた時点で `_pending_toggle` から消えるので、★自然に通常表示へ戻ります。
        """
        pending = self._pending_toggle.get(label)
        if pending is None:
            return badge
        want, _asked_at = pending
        # ⚠ 欄ごとに言葉を変える（★「速度」の欄に「ON」と出しても読めない）
        if label == "高速化":
            text = "Turbo へ" if want else "等速へ"
        else:
            text = "ON" if want else "OFF"
        return vm_tone.Badge(text + "（反映待ち）", vm_tone.TONE_CAUTION)

    def _remember_request(self, label: str, want: bool) -> None:
        """人が頼んだ値を覚える（★届くまで表示を守るため / §7.2）。

        ⚠ 覚えるのは**人が押したとき**だけ。★`_sync_toggle` からの
          書き戻しで覚えると、Lua の値を「人の希望」と取り違えます。
        """
        import time

        self._pending_toggle[label] = (bool(want), time.monotonic())

    def _sync_toggle(self, button, enabled, label: str, writer,
                     tip: str = "") -> None:
        """Lua の状態にトグルを合わせる。

        `tip` はそのボタンの説明（★入切はその1行目に出します / 2026-08-11）。

        ⚠⚠ `blockSignals` が要る。合わせるだけのつもりで `setChecked` すると
          `toggled` が飛び、押下の処理が command.json を書き返して
          **A キーで切った直後に入り直す**（書き手が2人いる典型的な壊れ方）。

        ⚠ 届いていないとき（None）は**触らない**。0 と不明を混ぜない。
        """
        if enabled is None:
            return
        want = bool(enabled)

        # ★★ 頼んだ値が届くまでは、Lua の古い値で押し戻さない（§7.3）★★
        import time

        pending = self._pending_toggle.get(label)
        if pending is not None:
            requested, asked_at = pending
            if want == requested:
                # ★届いた。⚠ ここから先は Lua が正
                self._pending_toggle.pop(label, None)
            elif time.monotonic() - asked_at < self.TOGGLE_CONFIRM_SECONDS:
                return                       # ★返事待ち。表示は頼んだ値のまま
            else:
                # ⚠⚠ **黙って戻さない**（★戻った理由が分からないのが一番困る）
                self._pending_toggle.pop(label, None)
                get_logger("gui").warning(
                    "%s の切り替えが %.0f 秒で届きませんでした（実機の値に戻します）",
                    label, self.TOGGLE_CONFIRM_SECONDS)
                self._align_status.setText(
                    f"⚠ {label} の切り替えが届きませんでした"
                    "（FCEUX 側の値に戻しました）")

        if button.isChecked() == want:
            return
        blocked = button.blockSignals(True)
        try:
            button.setChecked(want)
        finally:
            button.blockSignals(blocked)
        # ★★ **アイコンの字は書き換えない**（ボタンは 38px の1文字）★★
        #   ⚠ ここで `setText` すると両端が切れます（`TO (` `強化 (`）。
        #   ★入切は「押し込みの見た目」＋「ツールチップの1行目」で伝えます。
        #   ★経緯は `docs/history/ui-changes.md`。
        self._apply_toggle_tip(button, tip, label, want)

        # ★★ **command.json も追従させる**（これが無いと次の1回が効かない）★★
        #   Lua は command.json の値が**変わったとき**だけ効かせる（戻り防止）。
        #   ⚠ ファイルを古い値のまま放置すると:
        #       A キーで切る → ファイルは true のまま
        #       → 利用者がボタンを押して「入」にする → ファイルは true のまま
        #       → **変化が無いので Lua は無視する**（ボタンが効かない）
        #   ここで書き戻しておけば、次の押下が必ず「変化」になる。
        writer(want)

    # ★★ **command.json へは `CommandService` 経由でしか書かない**
    #   （2026-08-01 のリファクタ指示書 §5.2・受入条件4）。
    #   ⚠ ここに `write_command` を書き戻さないこと。書くと
    #     JSON のキー名と request_id の規則が画面側へ漏れる。

    def _write_turbo_command(self, on: bool):
        return self.commands.set_turbo(on)

    def _write_auto_command(self, on: bool):
        return self.commands.set_auto(on)

    def _sync_turbo_button(self, enabled) -> None:
        self._sync_toggle(self._turbo_button, enabled, "高速化",
                          self._write_turbo_command, self._turbo_tip)

    def _sync_auto_button(self, enabled) -> None:
        self._sync_toggle(self._auto_button, enabled, "AUTO",
                          self._write_auto_command, self._auto_tip)

    def _on_turbo_toggled(self, on: bool) -> None:
        """高速化の入切を Lua へ伝える。

        ★★ **効くのは戦闘の速度だけ。** ★★
          AUTO には影響しない。まんたん等の自動操作の速さも変えない
          （そちらは待ち時間の短縮そのもの）。

        ⚠ 押した結果は**必ず画面に出す**。届いたか分からない操作にしない。
        """
        # ★アイコンは「T」のまま。⚠ 入切はツールチップの1行目で伝えます
        self._apply_toggle_tip(self._turbo_button, self._turbo_tip,
                               "高速化", on)
        self._remember_request("高速化", on)
        # ★★ **押したことを残す**（2026-08-07 / 依頼者報告「効かない時がある」）★★
        #   ⚠⚠ 最初は Lua 側に警告を入れましたが、**毎ポーリング**通る道
        #     だったので 195件出てログが埋まりました（★鳴りすぎも壊れ方）。
        #   ★知りたいのは「押した瞬間」なので、**押した側**で1回だけ残します。
        get_logger("gui").debug("高速化ボタン: %s を書きます", "ON" if on else "OFF")
        problem = self._write_turbo_command(on)
        if problem is not None:
            self._align_status.setText(f"⚠ {problem}")
            return
        self._align_status.setText(
            "高速化: " + ("ON（戦闘は倍速）" if on else "OFF（戦闘も等速）")
            + "  ★次の戦闘から効きます")

    def _on_auto_toggled(self, on: bool) -> None:
        """AUTO の入切を Lua へ伝える。

        ★★ **効くのは「誰が操作するか」だけ。** ★★
          速度は変えない（速度は高速化のほう）。
        """
        # ★アイコンは「A」のまま。⚠ 入切はツールチップの1行目で伝えます
        self._apply_toggle_tip(self._auto_button, self._auto_tip, "AUTO", on)
        self._remember_request("AUTO", on)
        get_logger("gui").debug("AUTOボタン: %s を書きます", "ON" if on else "OFF")
        problem = self._write_auto_command(on)
        if problem is not None:
            self._align_status.setText(f"⚠ {problem}")
            return
        self._align_status.setText(
            "AUTO: " + ("ON（AI が操作します）" if on
                        else "OFF（自分で操作します）")
            + "  ★速度は変わりません")

    def _request_savestate(self, cfg, log) -> bool:
        """Lua へ保存を頼み、**ファイルが実際に書かれるまで**待つ。

        ★返事を待つ。頼んだだけで閉じると、FCEUX が先に終わって
          **保存されないまま**になりうる。

        ⚠⚠ **Lua の返事だけでは足りない**（2026-07-31 / 実機で判明）。

          `savestate.save(savestate.object(1))` は例外を出さずに成功を返すのに、
          **ディスクには何も書かれていなかった**。実測:

          | ファイル | 更新時刻 |
          | --- | --- |
          | `DQ2_J.fc0`（手動セーブ） | 13:24:**28** |
          | `DQ2_J.fc1`（ここで保存したはず） | **5日前のまま** |

          13:24:35 の「保存しました」の時点で**どのファイルも変わっていない**。
          つまり返事は「Lua が API を呼べた」ことしか意味していなかった。
          ★利用者から見ると**「保存した」と言われたのに古い状態が出てくる**
            ＝いちばんやってはいけない嘘。

        ★だから**ファイルの更新時刻が進むまで**を合格とする。
          ⚠ 進まなければ**閉じない**（呼び出し側が終了を中止する）。
        """
        import time

        # ★要求の前に返事を消す。前回の返事が残っていると
        #   「保存できた」と誤解して、保存されないまま閉じてしまう。
        self.vm.recorder.stats.savestate_saved = None

        slot = cfg.shutdown.save_slot
        # ★★ **頼む前にファイルの時刻を控える。** ★★
        #   これと比べて進んだかどうかが、唯一の確かな合格条件。
        target = self._savestate_file(cfg, slot)
        before = None
        if target is not None:
            try:
                before = target.stat().st_mtime
            except OSError:
                before = None                          # ★まだ無いのは正常
            log.debug("保存先を見張ります: %s（今: %s）", target.name,
                     "無し" if before is None else "あり")

        # ★★ `request_id` の採番は `CommandService` の仕事（指示書 §5.2）★★
        #   ⚠ 呼ぶ側で採ると、規則が画面のあちこちに散らばる。
        problem = self.commands.save_state(slot)
        if problem is not None:
            log.warning("保存を頼めませんでした: %s", problem)
            # ★★ **理由を画面にも出す**（2026-08-01）★★
            #   ⚠ ログにしか書いていなかったため、利用者からは
            #     「終了できない」としか見えなかった。
            self._save_problem = problem
            return False
        self._save_problem = None

        from PySide6.QtWidgets import QApplication

        def written() -> bool:
            """ファイルが新しくなったか。★見張れないときは判定しない。"""
            if target is None:
                return False
            try:
                now = target.stat().st_mtime
            except OSError:
                return False
            return before is None or now > before

        acked = False
        deadline = time.monotonic() + cfg.shutdown.save_timeout_seconds
        while time.monotonic() < deadline:
            QApplication.processEvents()
            self.vm.recorder.poll()
            saved = self.vm.recorder.stats.savestate_saved
            if saved is not None and not acked:
                if not saved.get("ok"):
                    log.error("セーブステートの保存に失敗しました（スロット%s）",
                              saved.get("slot"))
                    return False
                # ★Lua は「呼べた」と言っている。**まだ信じない**
                acked = True

            if written():
                log.info("セーブステートを保存しました（スロット%s / %s）",
                         slot, target.name)
                return True
            time.sleep(0.1)

        # --- ここから下は「保存できていない」---------------------------
        if target is None:
            log.error("セーブステートの保存先が分からないため確認できません")
        elif acked:
            # ⚠⚠ **この形がいちばん危ない。**「保存した」と言われて信じると、
            #   古い状態に戻される。実機で起きたのはこれ（2026-07-31）。
            log.error(
                "Lua は保存したと言いましたが、ファイルが変わっていません: %s"
                "（%s秒待ちました）。スロット番号の対応か、"
                "FCEUX の書き出しの仕方を疑ってください",
                target, cfg.shutdown.save_timeout_seconds)
        else:
            log.error("セーブステートの保存を確認できませんでした（%s秒待ちました）",
                      cfg.shutdown.save_timeout_seconds)
        return False

    # --- ⚠ 敵情報の段は削除しました（2026-08-11 / 依頼者）-----------------
    #
    #   > 敵情報は、もはや用済みの資料だから不要だね。このロジック自体いらない
    #
    #   ★消したのは**画面**だけです。敵の記録（図鑑・遭遇・戦闘ログ）は
    #     別経路なので残っています（`_track_encounter`）。
    #   ★経緯は `docs/history/ui-changes.md`。

    def _build_battle_log_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_section("戦闘ログ"))
        self._table = self._build_table()
        # ★行を選べるようにする（選ぶと下に出来事が出る / 指示書 5.4 B）
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_battle_selected)
        layout.addWidget(self._table, stretch=2)

        self._events = QPlainTextEdit()
        self._events.setReadOnly(True)
        self._events.setMaximumBlockCount(500)
        self._events.setPlaceholderText(
            "戦闘の行を選ぶと、その戦闘の出来事が出ます（記録がある戦闘のみ）")
        layout.addWidget(self._events, stretch=1)
        return panel

    def _on_battle_selected(self) -> None:
        """選ばれた戦闘の出来事を出す（Phase 3）。

        ★記録が無い戦闘もある（この機能より前の戦闘）。
          そのときは**無いと書く**。空欄にすると壊れて見える。
        """
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        index = rows[0].row()
        if index >= len(self._rows_cache):
            return
        row = self._rows_cache[index]
        events = self.vm.battle_events(row.battle_id)

        self._events.clear()
        header = f"{row.started_at[11:19]}  {row.monsters}"
        self._events.appendPlainText(header)
        if not events:
            self._events.appendPlainText(
                "  （この戦闘の出来事は記録されていません）")
            return
        for e in events:
            kind = e["kind"]
            if kind == "turn":
                self._events.appendPlainText(f"  --- ターン{e['turn_no']} ---")
            elif kind == "action":
                self._events.appendPlainText(
                    f"    [AI] {e['actor']} → {e['target']}: {e['action_name']}"
                    + (f"（{e['reason']}）" if e["reason"] else ""))
            elif kind == "enemy_defeated":
                self._events.appendPlainText(f"    {e['actor']} を倒した")
            else:
                label = {"party_hp": "HP", "party_mp": "MP",
                         "enemy_hp": "敵HP"}.get(kind, kind)
                self._events.appendPlainText(
                    f"    {e['actor']} {label} {e['value_before']} → "
                    f"{e['value_after']}（{e['delta']:+d}）")

        # ★こちらは**先頭**へ戻す（System Log とは逆）。
        #   選んだ戦闘の出来事は「1ターン目から」読むものなので、
        #   追記したままだと末尾（最後のターン）が見えて先頭が隠れる。
        #   同じ「ログ」でも、追うものと読むもので送り先が違う。
        self._events.moveCursor(QTextCursor.MoveOperation.Start)
        self._events.verticalScrollBar().setValue(0)

    def _build_monster_book_panel(self) -> QWidget:
        """図鑑は**別ウィンドウ**にし、ここにはボタンだけ置く（2026-07-27）。

        依頼者の指定:
        > モンスター図鑑は入りきれないので、ボタン押下で別ウィンドウが開く形が良い

        ★実際そうだった。この GUI は FCEUX の右隣に置く縦長のパネルなので、
          83体 × 15項目の表は横にも縦にも入らない。
        """
        panel = QWidget()
        # ★★ 2026-08-09: **縦積み**にします（右列は 362px）★★
        #   ⚠ 横一列だと、ボタンをアイコンにしても最小幅 756px でした
        #     （目的の枠と作戦の選択が横に並ぶため）。★実測して分かりました。
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        # ★アイコンのボタンだけ横一列（4つで 152px）
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        layout.addLayout(buttons)

        # ★★ 2026-08-09: ボタンはアイコンだけ（依頼者の指示）★★
        #   ⚠ 右列は 362px しかなく、「〜を開く」が4つ並ぶと入りません。
        #   ★何のボタンかはツールチップの**1行目に必ず書きます**。
        self._book_button = QPushButton("📖")
        self._book_button.setFixedWidth(38)
        self._book_button.setToolTip(
            "モンスター図鑑を開く\n"
            "別ウィンドウで開きます（一覧＋詳細）。\n"
            "名前・HP・攻撃・守備・耐性・落とす道具・特徴（行動と確率）を見られます。")
        self._book_button.clicked.connect(self._open_monster_book)
        buttons.addWidget(self._book_button)

        # ⚠ 「見た地図を開く」ボタンは廃止（2026-08-11 / 依頼者）。
        #   ★地図は起動時に標準で開く（`show_map`）ので、ボタンは要らない。
        #   ⚠ `_open_map_window` はコマンド・ホットキーからは引き続き呼べる。

        # ⚠ 戦略ドロップダウンは `_build_strategy_row()` へ移動（2026-08-11 /
        #   依頼者の並び: パーティ状態のすぐ下）。ここはボタン列だけを持つ。

        # --- いまの戦略の中身を見る（⚔ / UI整理 Phase 5）------------------
        self._tactics_button = QPushButton("⚔")
        self._tactics_button.setFixedWidth(38)
        self._tactics_button.setToolTip(
            "いまの戦略の作戦を開く\n"
            "別ウィンドウで開きます。\n"
            "　レベル上げ／ダンジョン探索：AI の作戦を**編集**できます\n"
            "　亀の子戦術：キャラごとの固定行動（読むだけ／編集不可）")
        self._tactics_button.clicked.connect(self._open_strategy_detail_window)
        buttons.addWidget(self._tactics_button)

        # --- まんたん設定（2026-08-02 / 指示書 §5）------------------------
        #
        # ★戦術プロフィールの隣に置く。どちらも「方針を設計する」画面で、
        #   最低残存MPを介してつながっているため（指示書 §5.2）。
        self._mantan_settings_button = QPushButton("💊")
        self._mantan_settings_button.setFixedWidth(38)
        self._mantan_settings_button.setToolTip(
            "まんたん設定を開く\n"
            "別ウィンドウで開きます。\n"
            "★どのHPまで回復するか、やくそうを呪文より先に使うか、"
            "サマルトリアとムーンブルクのMPをどう配るかを決められます。\n"
            "⚠ 最低残存MPの数値は戦術プロフィール側です（二重管理にしません）。")
        self._mantan_settings_button.clicked.connect(
            self._open_mantan_settings_window)
        buttons.addWidget(self._mantan_settings_button)
        # ★主要操作（図鑑・地図・戦術・まんたん）と、調査用（ログ・診断）の
        #   あいだに余白を入れる（仕様書 7.4「同列に置かない」を見た目で守る）
        buttons.addSpacing(16)

        # ⚠ 「いまどこ」と「戦術」は**上部ステータスへ移した**
        #   （リリース調整 仕様書 7.3: 常時見る情報は上にまとめる）。
        #   ここに置くとボタンの行が長くなり、1366×768 で押せなくなる。

        layout.addStretch(1)

        # --- 診断・ログの導線（仕様書 13章）--------------------------------
        #
        # ★★ 公開後の問い合わせ対応で効く。 ★★
        #   「ログを見せてください」と言っても、場所が分からないと届かない。
        #
        # ⚠ 主要操作（マップ・図鑑・戦術）と**同列に置かない**（仕様書 7.4）。
        #   右端に寄せて、開発・調査のためのものだと分かるようにする。
        # ★2026-08-09: アイコンだけにしました（依頼者の指示）。
        #   ⚠ 何のボタンかはツールチップの**1行目**に必ず書きます。
        for label, tip, slot in (
            ("📄", "ログを開く\n"
                   "work\\retroux.log をテキストエディタで開きます", self.open_log),
            ("📁", "ログのフォルダを開く\n"
                   "★retroux.log を選択した状態で開きます\n"
                   "（work は作業用で 336 個以上のファイルがあるため）",
             self.open_log_folder),
            ("🩺", "診断情報をコピーする\n"
                   "マシン情報（OS・版・FCEUX 等）とログの直近20行を、"
                   "問い合わせに貼れる形でコピーします\n"
                   "★ROM本体や個人のパスは含めません", self.copy_diagnostics),
        ):
            button = QPushButton(label)
            button.setFixedWidth(38)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            # ★★ 2026-08-09: まんたん設定の右へ（依頼者の指示）★★
            #   ⚠ 縦に積むと3行ぶん取っていました。★同じアイコンの列に並べます。
            #   ⚠ 主要操作と同列に見えないよう、間に余白を入れてあります。
            buttons.addWidget(button)

        buttons.addStretch(1)

        self._diag_status = QLabel("")
        self._diag_status.setStyleSheet("color:#8a8a8a;")
        self._diag_status.setWordWrap(True)
        self._diag_status.setMinimumWidth(1)
        layout.addWidget(self._diag_status)
        return panel

    # --- ログ導線（仕様書 13章）------------------------------------------

    def _user_config(self):
        """`path()` を持つ設定を返す。**渡されていなければ読み直す。**

        ⚠⚠ ここを `self._cfg`（= `user_cfg.gui`）で済ませていたのが
          2026-07-30 の不具合の原因。`GuiConfig` に `path()` は無い。
        """
        if self._user_cfg is not None:
            return self._user_cfg
        from ..core.config import user_config as user_config_mod

        # ★読み直しは1回だけにする（ボタンを押すたびに読まない）
        self._user_cfg, _ = user_config_mod.load()
        return self._user_cfg

    def _config_path(self, name: str, fallback: str):
        """`paths` の項目を絶対パスで返す。★取れなければ既定へ落ちる。

        ⚠ 落ちたことを**黙って捨てない**（`_config_problems` に残す）。
          黙って既定を使うと、**たまたま既定と同じで動いてしまい**、
          間違いに気づけない（実際 `backup_lock` はそれで通っていた）。
        """
        try:
            return pathlib.Path(self._user_config().path(name))
        except Exception as exc:                       # noqa: BLE001
            if not hasattr(self, "_config_problems"):
                self._config_problems: list = []
            self._config_problems.append(f"{name}: {exc}")
            return pathlib.Path(fallback)

    def _log_file(self):
        # ★起動時に渡された実パスがあればそれを使う（いちばん確実）
        if self._log_path is not None:
            return self._log_path
        return self._config_path("log", "work/retroux.log")

    def open_log(self) -> None:
        """最新ログを開く。★開けなかったら**理由を出す**。"""
        path = self._log_file()
        if not path.exists():
            self._diag_status.setText(f"⚠ ログがまだありません: {path.name}")
            return
        if not self._reveal(path):
            self._diag_status.setText(f"⚠ 開けませんでした: {path}")
            return
        self._diag_status.setText(f"ログを開きました: {path.name}")

    def open_log_folder(self) -> None:
        """ログのフォルダを開く。★**ログを選択した状態で**開く。

        ⚠⚠ `work/` は作業用のフォルダで、**336 個以上のファイルがある**
          （解析スクリプト・わざと壊す道具・検証ログなど）。
          ただ開くだけだと、その中から `retroux.log` を目で探すことになる。
          ★だから Explorer の `/select` で**選択した状態**にする。
        """
        log = self._log_file()
        if self._reveal(log.parent, select=log if log.exists() else None):
            where = log.name if log.exists() else log.parent.name
            self._diag_status.setText(f"フォルダを開きました（{where}）")
            return
        self._diag_status.setText(f"⚠ 開けませんでした: {log.parent}")

    def _reveal(self, path, select=None) -> bool:
        """OS の関連付けで開く。★**落ちない**（開けなければ False）。

        `select` にファイルを渡すと、そのファイルを**選択した状態**で開く。

        ★★ Explorer を起こすのは `WindowManager` の仕事（リファクタ §5.2）★★
          ⚠ ここから `subprocess` を呼ばない。
        ★開けなければ Qt の関連付けへ落ちる（そちらは画面の層でよい）。
        """
        target = pathlib.Path(path).resolve()
        if select is not None:
            # ⚠ `explorer /select` は**成功しても終了コード 1** を返すので、
            #   戻り値で成否を判定しない（開くのに「開けません」と出る）。
            if self.windows.reveal_in_explorer(select) is None:
                return True
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))))
        except Exception:                              # noqa: BLE001
            return False

    def copy_diagnostics(self) -> None:
        """診断情報をクリップボードへ（仕様書 13章）。

        ⚠ **ROM本体や個人のパスを含めない。** 集める側
          （`core/diagnostics.py`）がパスを相対化している。
        """
        from ..core import diagnostics

        try:
            # ⚠ ここに `self._cfg`（= `user_cfg.gui`）を渡していたため
            #   「ログ: 不明」になり、DB と ROMファイルの行が**消えていた**。
            info = diagnostics.collect(
                user_cfg=self._user_config(),
                rom_hash=getattr(self.vm, "rom_hash", None),
                read_only=getattr(self.vm, "read_only", None),
                warnings=[w.get("message", str(w)) if isinstance(w, dict) else str(w)
                          for w in (self.vm.recorder.stats.warnings or [])],
                tactics=(self.vm.active_tactics().name
                         if getattr(self.vm, "tactics", None)
                         and self.vm.active_tactics() else None),
                # ★マシン情報に加えてログの直近20行も入れる（2026-08-11 / 依頼者）
                log_tail=20)
            text = diagnostics.as_text(info)
        except Exception as exc:                       # noqa: BLE001
            self._diag_status.setText(f"⚠ 診断情報を作れませんでした: {exc}")
            return
        try:
            from PySide6.QtWidgets import QApplication

            board = QApplication.clipboard()
            if board is None:
                raise RuntimeError("クリップボードが無い")
            board.setText(text)
            self._diag_status.setText(
                f"診断情報をコピーしました（{len(text)} 文字）。問い合わせに貼れます。")
        except Exception:                              # noqa: BLE001
            # ⚠ クリップボードが使えなくても詰まらせない。ログへ出す
            get_logger("gui").debug("診断情報:\n%s", text)
            self._diag_status.setText(
                "⚠ クリップボードへ入れられませんでした（ログに出しました）。")

    # --- アクション層（2026-08-01 の指示書 §11）------------------------

    def _focus_emulator(self) -> None:
        """ゲーム画面へ操作を返す。★実際の前面化は `WindowManager` の仕事。"""
        self.windows.focus_emulator()


    def _build_actions(self) -> None:
        """アクションに実装を結び付ける（指示書 §11.2）。

        ★★ ここが**唯一の対応表**。ボタンもキーもここを通る。 ★★
          ⚠ ボタンの `clicked` へ処理を直接つながない。つなぐと
            同じことをキーからやりたくなったとき2か所になる。

        ⚠ `open_settings` は未実装なので**登録しない**。
          登録しないと「この版では使えません」と出る（黙って無反応にしない）。
        """
        from ..application.action_dispatcher import ActionDispatcher
        from ..application.command_service import CommandService
        from ..core.keybindings import load as load_keybindings

        # ★★ **command.json を書くのはこの人だけ**（指示書 §5.2）★★
        #   ⚠ 画面が `write_command` を直に呼ぶのをやめた（Phase 1）。
        #     JSON のキー名も request_id の採番も画面は知らない。
        self.commands = CommandService(
            command_path=self.vm.recorder.command_path,
            encountered=lambda: self.vm.recorder.stats.current_monsters or [],
            read_only=self.vm.read_only, logger=get_logger("gui"))

        self._actions = ActionDispatcher(
            focus_emulator=self._focus_emulator, logger=get_logger("gui"))
        for name, handler in (
                ("toggle_auto", lambda: self._auto_button.toggle()),
                ("toggle_turbo", lambda: self._turbo_button.toggle()),
                ("emergency_manual", self._on_emergency_manual),
                ("open_map", self._open_map_window),
                ("toggle_map_follow", self._toggle_map_follow),
                ("open_tactics_profile", self._open_tactics_window),
                ("open_keybinding_settings", self._open_keybinding_window),
                ("reset_layout", self._on_reset_layout),
                ("focus_emulator", lambda: None),   # ★属性側で戻る
                ("show_lua_window", self._show_lua_window)):
            self._actions.register(name, handler)

        # ★キー割り当て。⚠ 壊れていても起動する（既定値へ落ちる / §14.4）
        self.keybindings = load_keybindings()
        for problem in self.keybindings.problems:
            get_logger("gui").warning("キーバインド: %s", problem)

        # ★ゲームパッド（XBOX / XInput）。⚠ 無くても起動する（RX-0076）。
        self._setup_gamepad()

    def _setup_gamepad(self) -> None:
        """XInput でパッドを読み、RetroUX 機能へ橋渡しする（RX-0076）。

        ★★ **NES ボタン（十字・A・B・Start・Select）は FCEUX が読む。** ★★
          ここで読むのは FCEUX が扱えない LB/RB/LT/RT/X/Y だけ。

        ⚠ 無効化は環境変数 `RETROUX_NO_GAMEPAD`。閲覧専用でも動かさない
          （操作は command.json を書くため）。パッド未接続でも無害に休む。
        """
        import os

        from PySide6.QtCore import Qt, QTimer

        from ..application.gamepad import GamepadRouter, XInputReader
        from ..core.config import user_config as user_config_mod

        self._gamepad_reader = None
        self._gamepad_seen = False
        log = get_logger("gui")

        cfg, _ = user_config_mod.load()
        # ★無効化: 環境変数 RETROUX_NO_GAMEPAD か config の gamepad.enabled=false。
        if os.environ.get("RETROUX_NO_GAMEPAD") or not cfg.gamepad.enabled:
            log.info("ゲームパッド: 使いません"
                     "（RETROUX_NO_GAMEPAD / gamepad.enabled=false）")
            return
        if self.vm.read_only:
            log.debug("ゲームパッド: 閲覧専用なので使いません")
            return

        reader = XInputReader()
        if not reader.available:
            # ⚠ 1回だけ。★XInput が無い環境（DLL 不在）でも起動は続ける。
            log.warning("ゲームパッド: XInput が使えません（キーボードで操作できます）")
            return

        # ★保存/読込のスロットは終了時の保存と同じ（対で使う）。
        self._gamepad_slot = int(cfg.shutdown.save_slot)
        # ★検証モード（RX-0078）: NES 入力を FCEUX へ**注入するか**。
        #   False なら NES は FCEUX 本体のパッド割当に任せる（独自機能は常に有効）。
        self._gamepad_inject_nes = bool(cfg.gamepad.inject_nes_input)
        # ★切り分け用 DEBUG（フォーカス・押したボタン）。config か環境変数で ON。
        self._gamepad_debug = bool(
            cfg.gamepad.debug or os.environ.get("RETROUX_GAMEPAD_DEBUG"))
        self._gamepad_dbg_last_mask = -1

        self._gamepad_reader = reader
        self._gamepad_router = GamepadRouter()
        # ★NES ボタン（十字/A/B/Start/Select）の状態を渡すファイル（bridge が毎
        #   フレーム読む）。command.json と同じフォルダに置く。★依頼者 2026-08-19:
        #   FCEUX 側の割当を不要にし「挿すだけ」で基本操作も効くようにする。
        self._gamepad_input_path = (
            pathlib.Path(self.vm.recorder.command_path).parent
            / "gamepad_input.txt")
        self._gamepad_seq = 0
        self._gamepad_last_mask = None
        # ★応答性のため 60Hz（NES の歩行を渡すため）。独自機能のエッジも同じ間隔。
        #   ⚠ PreciseTimer にして 16ms に近づける（既定の CoarseTimer は粗い）。
        #   ★それでも refresh の重い更新中はメインスレッドが塞がるので、ブリッジ側は
        #     数百ms 書けなくても入力を保持する（GAMEPAD_STALE_LIMIT）。
        self._gamepad_timer = QTimer(self)
        self._gamepad_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._gamepad_timer.timeout.connect(self._poll_gamepad)
        self._gamepad_timer.start(16)
        mode = ("NES注入ON（挿すだけ）" if self._gamepad_inject_nes
                else "NES注入OFF（NESはFCEUX本体へ / 検証モード）")
        log.info("ゲームパッド: 開始 — %s。★独自機能(LB/RB/LT/RT/X/Y)は常に有効", mode)
        # ★注入OFF のときは、前回の残り（押しっぱなし）を即 0 で解除しておく。
        if not self._gamepad_inject_nes:
            self._write_gamepad_nes(0)

    def _poll_gamepad(self) -> None:
        """パッドを1回読み、独自機能は**押した瞬間**、NES ボタンは**状態**を渡す。"""
        reader = getattr(self, "_gamepad_reader", None)
        if reader is None:
            return
        state = reader.read()
        if state is not None and state.connected and not self._gamepad_seen:
            self._gamepad_seen = True
            get_logger("gui").info("ゲームパッドを検出しました（XBOX/XInput）")
        # ★独自機能（ロード/セーブ/Auto/Turbo/X/Y）は立ち上がりで1回だけ。
        #   ⚠ 注入 OFF でも**必ず**処理する（独自機能は常に有効）。
        for event in self._gamepad_router.poll(state):
            self._on_gamepad_event(event)
        # ★NES ボタン（十字/A/B/Start/Select）は**毎フレームの状態**を bridge へ。
        #   ⚠ seq を毎回進める。bridge は seq が止まったら「RetroUX 停止」とみなし
        #     押しっぱなしを解除する（ボタンが刺さらないように）。
        # ★検証モード（RX-0078）: 注入 OFF なら NES は送らない（常に 0）。
        from ..application.gamepad import nes_mask
        mask = nes_mask(state) if getattr(self, "_gamepad_inject_nes", True) else 0
        self._write_gamepad_nes(mask)
        if getattr(self, "_gamepad_debug", False):
            self._gamepad_debug_log(state, mask)

    def _write_gamepad_nes(self, mask: int) -> None:
        """`<seq> <mask>` を1行で書く（bridge が毎フレーム読む）。

        ⚠ 原子置換（temp→os.replace）は使わない。60Hz で bridge が読んでいる
          最中に置換すると Windows では「使用中」で失敗しうる。★小さな1行なので
          インプレースで書き、bridge 側は半端読みを弾いて次フレームで読み直す。
        """
        path = getattr(self, "_gamepad_input_path", None)
        if path is None:
            return
        self._gamepad_seq = (self._gamepad_seq + 1) & 0x7FFFFFFF
        try:
            path.write_text(f"{self._gamepad_seq} {int(mask)}\n",
                            encoding="ascii")
        except OSError:
            # ⚠ 書けなくても止めない（次の tick で書ければよい）。
            pass

    def _on_gamepad_event(self, event: str) -> None:
        """パッドの1操作を既存の入口へ流す（★配線はここだけ）。

        ★★ どれも「ボタン/キーと同じ入口」を通す（ActionDispatcher /
          CommandService）。⚠ ここに独自処理を書かない（§6.2）。
        """
        from ..application.gamepad import (
            EVENT_LOAD, EVENT_MANTAN, EVENT_SAVE, EVENT_TALK,
            EVENT_TOGGLE_AUTO, EVENT_TOGGLE_TURBO,
        )

        if getattr(self, "_gamepad_debug", False):
            get_logger("gui").info(
                "[GAMEPAD DEBUG] focus=%s retroux_event=%s",
                self.windows.foreground_window_title() or "(不明)", event)

        slot = getattr(self, "_gamepad_slot", 1)
        if event == EVENT_TOGGLE_AUTO:
            self.run_action("toggle_auto")
        elif event == EVENT_TOGGLE_TURBO:
            self.run_action("toggle_turbo")
        elif event == EVENT_TALK:
            self._gamepad_command("R（どうぐや/ふくびき）",
                                  self.commands.request, "talk")
        elif event == EVENT_MANTAN:
            self._gamepad_command("M（まんたん）",
                                  self.commands.request, "mantan")
        elif event == EVENT_SAVE:
            self._gamepad_command(f"セーブ（スロット{slot}）",
                                  self.commands.save_state, slot)
        elif event == EVENT_LOAD:
            self._gamepad_command(f"ロード（スロット{slot}）",
                                  self.commands.load_state, slot)

    def _gamepad_command(self, label: str, func, *args) -> None:
        """CommandService 経由の1操作を頼み、結果を画面に出す。

        ★押した結果は必ず出す（届いたか分からない操作にしない）。
        """
        problem = func(*args)
        if problem is not None:
            self._align_status.setText(f"⚠ {problem}")
        else:
            self._align_status.setText(f"パッド: {label}")

    # --- 切り分け検証用の DEBUG（RX-0078）--------------------------------
    #   ⚠ 既定 OFF（config gamepad.debug / 環境変数 RETROUX_GAMEPAD_DEBUG）。
    #     製品版に恒久的な大量ログは残さない。

    def _gamepad_debug_log(self, state, mask: int) -> None:
        """NES マスクが変わったときだけ、フォーカスと押下を1行残す。

        ⚠ 60Hz で毎回出すと埋まるので、**変化したときだけ**。
        """
        last = getattr(self, "_gamepad_dbg_last_mask", -1)
        if mask == last:
            return
        self._gamepad_dbg_last_mask = mask
        names = []
        if state is not None and state.connected:
            from ..application.gamepad import (
                NES_A, NES_B, NES_DOWN, NES_LEFT, NES_RIGHT, NES_SELECT,
                NES_START, NES_UP,
            )
            for bit, name in ((NES_UP, "↑"), (NES_DOWN, "↓"), (NES_LEFT, "←"),
                              (NES_RIGHT, "→"), (NES_A, "A"), (NES_B, "B"),
                              (NES_START, "Start"), (NES_SELECT, "Select")):
                if mask & bit:
                    names.append(name)
        inject = "ON" if getattr(self, "_gamepad_inject_nes", True) else "OFF"
        get_logger("gui").info(
            "[GAMEPAD DEBUG] focus=%s nes=[%s] inject=%s",
            self.windows.foreground_window_title() or "(不明)",
            " ".join(names) or "-", inject)

    def _run_requested_action(self, game) -> None:
        """Lua がキーで受け取ったアクションを実行する（2026-08-01）。

        ★★ **通し番号で見る。** ★★
          ⚠ 名前だけで比べると、同じキーを2回押したときに
            「変わっていない」と判断して**2回目を取りこぼす**。

        ⚠ 起動直後に**溜まっていたものを実行しない**。
          state.json は上書きなので、前回の終了時の値が残っている。
          最初に見た番号を「済み」として覚えるだけにする。
        """
        seq = getattr(game, "requested_action_seq", 0) or 0
        name = getattr(game, "requested_action", None)
        seen = getattr(self, "_requested_seq", None)
        if seen is None:
            # ★初回は覚えるだけ（古い要求を蒸し返さない）
            self._requested_seq = seq
            return
        if seq == seen or not name:
            return
        self._requested_seq = seq
        self.run_action(name)

    def run_action(self, name: str) -> None:
        """アクションを実行し、結果を画面へ出す。

        ★押した結果は**必ず画面に出す**。届いたか分からない操作にしない。
        """
        result = self._actions.dispatch(name)
        # ⚠⚠⚠ **`None でない = 失敗` ではありません**（2026-08-07 に踏んだ）★★★
        #   `dispatch()` は**成功しても結果を返します**。そのため
        #   成功のたびに、状態バーへ中身がそのまま出ていました:
        #
        #     ⚠ ActionResult(success=True, message='', restore_focus=None)
        #
        #   ★依頼者の画面写真で気づきました。⚠ 内部の表現を人に見せない。
        if result is None or getattr(result, "success", True):
            return
        # ★理由が空でも「何ができなかったか」は出す（⚠ 空欄にしない）
        self._align_status.setText(
            "⚠ " + (getattr(result, "message", "") or f"{name} を実行できません"))

    def _on_emergency_manual(self) -> None:
        """いますぐ手動へ戻す（AUTO を切る）。

        ★危ないと感じたときに1つの操作で主導権を取り返すためのもの。
        ⚠ 既に切ってあるときは何もしない（押した結果は出す）。
        """
        if self._auto_button.isChecked():
            self._auto_button.setChecked(False)
        else:
            self._align_status.setText("AUTO は既に OFF です（手動のままです）")

    # --- ★★ 作戦の切替（2026-08-04 / 指示書 §4.2）------------------------

    def reload_tactics_picker(self) -> None:
        """★2026-08-10（UI整理 Phase 3）: 作戦は戦略に統合。

        ⚠ 名前は残して `reload_strategy_picker()` へ委譲する。戦術プロフィールの
          窓・目的変更・起動時など、多くの場所から呼ばれるため、呼び出し元を
          一度に直さずに済ませる。
        """
        self.reload_strategy_picker()

    def reload_strategy_picker(self) -> None:
        """戦略ドロップダウンを、いまの状態に合わせる（2026-08-10）。

        ★AUTO の入切（画面が持つ）＋ 目的から、いまの戦略を導く。
        ⚠ 差し替え中はイベントを鳴らさない（二重の歯止め）。
        """
        picker = getattr(self, "_strategy_picker", None)
        if picker is None:
            return
        auto_btn = getattr(self, "_auto_button", None)
        auto_on = auto_btn.isChecked() if auto_btn is not None else True
        current = self.vm.current_strategy(auto_on)
        picker.blockSignals(True)
        try:
            index = picker.findData(current)
            if index >= 0:
                picker.setCurrentIndex(index)
        finally:
            picker.blockSignals(False)
        label = getattr(self, "_tactics_label", None)
        if label is not None:
            label.setText(self.vm.tactics_label())

    def _on_strategy_picked(self, value) -> None:
        """人が戦略を選んだとき（★`activated` = 人の操作だけ）。"""
        result = self.vm.set_strategy(value, source="main_window")
        if not result.ok:
            self._align_status.setText(result.message)
            self.reload_strategy_picker()
            return
        # ★AUTO の入切を戦略に合わせる（手動＝OFF / それ以外＝ON）。
        #   ⚠⚠ 戦闘中は勝手に切り替えない（入力済みの行動が乱れる）。
        #     ★切替は「まだ戦闘に入っていないとき」だけ。
        want_auto = getattr(result, "auto_enabled", True)
        state = self.vm.poll()
        not_in_battle = state is None or not state.in_battle
        auto_msg = ""
        if not_in_battle and self._auto_button.isChecked() != want_auto:
            # ★setChecked が toggled を起こし、実処理（コマンド書き込み）が走る
            self._auto_button.setChecked(want_auto)
            auto_msg = "\n★AUTO を " + ("ON" if want_auto else "OFF") + "にしました"
        self._align_status.setText(result.message + auto_msg)
        self._tactics_label.setText(self.vm.tactics_label())
        self.reload_strategy_picker()
        # ★開いている戦術プロフィールの窓があれば合わせる
        window = getattr(self, "_tactics_window", None)
        if window is not None and window.isVisible():
            window.reload()
        # ★「いまの戦略の中身」窓も、開いていれば新しい戦略に合わせる
        detail = getattr(self, "_strategy_detail_window", None)
        if detail is not None and detail.isVisible():
            auto_on = self._auto_button.isChecked()
            detail.show_for(self.vm.current_strategy(auto_on))

    # --- ★★ 大目的（2026-08-05 / Phase 3）--------------------------------

    def reload_mission_buttons(self) -> None:
        """★2026-08-10（UI整理 Phase 3）: 目的は戦略に統合。

        ⚠ 名前は残して `reload_strategy_picker()` へ委譲（呼び出し元を
          一度に直さない）。
        """
        self.reload_strategy_picker()

    def _on_strategy_changed_elsewhere(self, message: str) -> None:
        """戦術プロフィールの窓で作戦が変わったときの同期（§5.2）。"""
        self.reload_tactics_picker()
        self._tactics_label.setText(self.vm.tactics_label())
        if message:
            self._align_status.setText(message)

    def _ensure_tactics_window(self):
        """戦術プロフィールの窓を1つだけ用意する（図鑑・地図と同じ作り）。"""
        from .tactics_profile_window import TacticsProfileWindow

        if getattr(self, "_tactics_window", None) is None:
            self._tactics_window = TacticsProfileWindow(self.vm)
            # ★前回の場所を戻す（2026-08-09 / 地図・ログと同じ理由）。
            #   ⚠ 遅延生成なので起動時の復元ループには載りません。
            self._window_state().apply_to("tactics", self._tactics_window)
            # ★[OK] は保存できたら窓を閉じる（2026-07-31 の指示書 §9）。
            #   ⚠ 閉じた窓に結果を書いても読まれないので、こちらで出す。
            self._tactics_window.applied.connect(self._align_status.setText)
            # ★★ 向こうで作戦が変わったら、こちらのリストも合わせる ★★
            #   （2026-08-04 / 指示書 §4.2-3・§5.2-2・§19 受入条件3）
            #   ⚠ どちらの画面から変えても**同じ状態**を指すこと。
            self._tactics_window.strategy_changed.connect(
                self._on_strategy_changed_elsewhere)
        return self._tactics_window

    def _ensure_mantan_settings_window(self):
        """まんたん設定の窓を1つだけ用意する（2026-08-02 / 指示書 §5）。"""
        from .mantan_settings_window import MantanSettingsWindow

        if getattr(self, "_mantan_settings_window", None) is None:
            window = MantanSettingsWindow()
            window.applied.connect(self._align_status.setText)
            # ★「戦術プロフィールを開く」から飛べるようにする（指示書 §5.2）
            window.open_tactics.connect(self._open_tactics_window)
            self._mantan_settings_window = window
        return self._mantan_settings_window

    def _open_mantan_settings_window(self) -> None:
        window = self._ensure_mantan_settings_window()
        # ⚠ 開きっぱなしの窓は古い値のまま。開くたびに読み直す
        if window.isVisible():
            window.reload()
        window.show()
        window.raise_()
        window.activateWindow()

    def _open_tactics_window(self) -> None:
        if getattr(self.vm, "tactics", None) is None:
            # ★押しても何も起きない、をやらない（理由を出す）
            self._tactics_label.setText(
                "戦術: —（プロフィール機能が無効です。config の tactics.enabled）")
            return
        window = self._ensure_tactics_window()
        if window.isVisible():
            window.reload()
        window.show()
        window.raise_()
        window.activateWindow()

    # --- 戦略の中身（読むだけ / 2026-08-11 / UI整理 Phase 5）--------------

    def _ensure_strategy_detail_window(self):
        """「いまの戦略の中身」を見せる窓を1つだけ用意する。

        ★⚔ の主導線はこの読むだけの窓。作戦の自作・読み込みは
          [上級設定を開く] から従来の作戦プロフィール窓へ渡す。
        """
        from .strategy_detail_window import StrategyDetailWindow

        if getattr(self, "_strategy_detail_window", None) is None:
            # ★亀の子（読むだけ）専用。「上級設定を開く」は廃止（2026-08-11）。
            self._strategy_detail_window = StrategyDetailWindow(self.vm)
        return self._strategy_detail_window

    def _open_strategy_detail_window(self) -> None:
        """⚔: いまの戦略に紐づく作戦を開く（2026-08-11 / 依頼者の構想）。

        ★★ AUTO（レベル上げ／ダンジョン探索）は、その作戦プロフィールを
          **編集で**開く（上級設定は不要になった）。
        ★★ 亀の子（固定行動）は**編集不可**なので、読むだけの窓を出す。
        """
        if getattr(self.vm, "tactics", None) is None:
            self._tactics_label.setText(
                "戦術: —（プロフィール機能が無効です。config の tactics.enabled）")
            return
        auto_btn = getattr(self, "_auto_button", None)
        auto_on = auto_btn.isChecked() if auto_btn is not None else True
        strat = self.vm.current_strategy(auto_on)
        if strat == "custom_1":
            # ★亀の子: 固定行動は編集しない。読むだけの窓
            window = self._ensure_strategy_detail_window()
            window.show_for(strat)
            window.show()
            window.raise_()
            window.activateWindow()
            return
        # ★AUTO: その戦略の作戦プロフィールを編集で開く
        tid = self.vm._STRATEGY_TACTICS.get(strat)
        self._open_tactics_for(tid)

    def _open_tactics_for(self, profile_id) -> None:
        """指定の作戦プロフィールを編集で開く（⚔ の AUTO 用 / 2026-08-11）。"""
        if getattr(self.vm, "tactics", None) is None:
            self._tactics_label.setText(
                "戦術: —（プロフィール機能が無効です。config の tactics.enabled）")
            return
        window = self._ensure_tactics_window()
        if profile_id is not None:
            window.reload(select=profile_id)
        elif window.isVisible():
            window.reload()
        window.show()
        window.raise_()
        window.activateWindow()

    def _ensure_map_window(self):
        from .map_window import MapWindow

        if getattr(self, "_map_window", None) is None:
            self._map_window = MapWindow(self.vm)
            # ★★ **作った直後に標準の場所へ置く**（2026-08-07 / 依頼者報告）★★
            #
            #   > 最初のウィンドウがいろいろ重なる（標準レイアウトボタン押すと直る）
            #   > MAPが画面の下に置きたいが、外面に重なっている
            #
            # ⚠⚠ 起動スクリプトは並べ替えを呼びますが、★**その時点で
            #   地図の窓がまだ存在しません**。後から開くと、並べる相手が
            #   居なかったぶん**任意の場所**に出て重なります。
            # ★「標準レイアウトに戻す」が効くのは、あちらが**先に地図を
            #   開いてから**並べるからです。同じことを開いた時にもします。
            #
            # ⚠⚠⚠ **並べるのは `show()` の後**（2026-08-07 に踏んだ）★★★
            #   ここで並べても効きませんでした。★Qt は `show()` するまで
            #   **ウィンドウを作りません**。窓が無いので飛ばされます。
            #   → `_open_map_window` が出したあとに呼びます。
            #
            # ★★ 2026-08-09: **前回の場所を先に戻す**（依頼者の指示）★★
            #
            #   > 起動するときに、前回の位置、サイズをなるべく再現してほしい。
            #   > 毎回直すのが大変なので。
            #
            #   ⚠⚠ 起動時の復元ループ（`_restore_window_state`）は、
            #     **その時点で存在する窓しか戻せません**。地図は開くまで
            #     作られないので、対象外のまま「任意の場所」に出ていました。
            #   ★覚えているならそれを使い、覚えていないときだけ標準へ置きます。
            self._map_needs_placing = not self._window_state().apply_to(
                "map", self._map_window)
        return self._map_window

    def _place_map_window(self) -> None:
        """地図を標準の場所（エミュレータの真下）へ置く。

        ⚠⚠ **測り方をここに書き写さない。** ★作業領域も FCEUX の実寸も
          `WindowManager.arrange()` が既に持っています。書き写すと
          二重管理になり、片方だけ直したときに静かにずれます。

        ⚠ 失敗しても地図は開きます。★場所が合わないことより、
          「開かない」ことのほうが害が大きいためです。
        """
        try:
            self.windows.arrange()
        except Exception as exc:             # pragma: no cover
            get_logger("gui").warning("地図の初期位置を決められません: %s", exc)

    def _open_map_window(self) -> None:
        """ボタンで地図を開く（2つ目を作らない / 図鑑と同じ作り）。"""
        window = self._ensure_map_window()
        if window.isVisible():
            window.reload()
        window.show()
        # ★★ **出したあとに並べる**（⚠ 出す前だと窓が無くて飛ばされる）。
        #   ⚠ 1回だけ。★毎回並べ直すと、利用者が動かした位置を奪います。
        if getattr(self, "_map_needs_placing", False):
            self._map_needs_placing = False
            self._place_map_window()
        window.raise_()
        window.activateWindow()

    def _toggle_map_follow(self) -> None:
        """地図の「いまの場所を追う」を切り替える（指示書 §11.2）。

        ⚠ 地図を開いていなければ**開いてから**切り替える。
          「押しても何も起きない」をやらない。
        """
        window = self._ensure_map_window()
        if not window.isVisible():
            window.show()
        checkbox = getattr(window, "_follow", None)
        if checkbox is None:
            self._align_status.setText("⚠ 地図の追従を切り替えられません")
            return
        checkbox.setChecked(not checkbox.isChecked())
        self._align_status.setText(
            "地図の追従: " + ("ON" if checkbox.isChecked() else "OFF"))

    def _open_keybinding_window(self) -> None:
        """キーバインド設定を開く（指示書 §13）。"""
        from .keybinding_window import KeybindingWindow

        if getattr(self, "_keybinding_window", None) is None:
            self._keybinding_window = KeybindingWindow(self)
            # ★保存できたら実行中の割り当てを差し替える（再起動不要 / §13.6）
            self._keybinding_window.applied.connect(self._on_keybindings_applied)
        self._keybinding_window.reload()
        self._keybinding_window.show()
        self._keybinding_window.raise_()
        self._keybinding_window.activateWindow()

    def _on_keybindings_applied(self, message: str) -> None:
        from ..core.keybindings import load as load_keybindings

        self.keybindings = load_keybindings()
        self._align_status.setText(message)

    def _show_lua_window(self) -> None:
        """Lua Script ウィンドウを出す（障害調査用の逃げ道 / 指示書 §9.2）。

        ★普段は小さくして避けているが、**再表示手段は必ず残す**。
        """
        title = self._user_config().emulator.lua_window_title
        if not self.windows.available:
            self._align_status.setText("⚠ この環境では窓を操作できません")
        elif self.windows.show_lua_window():
            self._align_status.setText(f"{title} を表示しました")
        else:
            self._align_status.setText(f"⚠ {title} が見つかりません")


    def _on_reset_layout(self) -> None:
        """標準レイアウトに戻す（指示書 §7.1）。

        ⚠ 確認ダイアログは出さない（指示書 §7.1）。**元に戻す操作**なので、
          押し間違えても失うのは「自分で動かした配置」だけ。
        """
        # ★地図は標準で出す（並べる前に開く / 指示書 §8）
        self._ensure_map_window().show()

        # ★覚えている配置を捨てて並べ直すのは `WindowManager` の仕事
        state = self._window_state()
        moved, messages = self.windows.reset_layout(
            forget_window_state=getattr(state, "forget", None))

        # ★★ 下段を前面へ（2026-08-09 / 依頼者の報告「ログ画面がない」）★★
        #   ⚠ ログ窓はフォーカスを奪わない設定なので、他の窓と重なると
        #     **裏に隠れたまま出てきません**。「消えた」と見えます。
        #   ★`raise_()` は前面に出すだけでフォーカスは奪いません
        #     （ゲームの操作を取り上げないこと）。
        log_window = getattr(self, "_log_window", None)
        if log_window is not None and log_window.isVisible():
            log_window.raise_()

        # ★★ 後始末は**次のイベントループへ遅らせる**（2026-08-19 / RX-0062）★★
        #
        #   ⚠⚠ `reset_layout` は `SetWindowPos`（Win32）で OS 窓を並べます。
        #     ★Qt の `geometry` がそれを取り込むのは**次のイベントループ**で、
        #     同じ呼び出しの中では `self.width()` が**古い幅のまま**です
        #     （実測: 整列で 546 にしたのに `self.width()` は 823 を返す）。
        #   ⚠ そのまま `_trim_blank_bottom()` が `self.resize(self.width(), …)`
        #     を呼ぶと、★**古い幅（823）を Qt 側から再適用**してしまい、
        #     整列した 546 を潰します。⚠ 本体だけ右へはみ出していた正体がこれ。
        #     （地図は `_trim` の対象外なので 546 のまま残っていました。）
        #   → ★Qt が整列後の幅を取り込んでから、余白詰めと保存をする。
        from PySide6.QtCore import QTimer

        def _after_arranged() -> None:
            # ★並べ直した直後だけ、下の余白を詰める（2026-08-11）
            #   ⚠ 遊んでいる最中は呼びません（窓の縁が動くとチカチカします）
            self._trim_blank_bottom()
            # ★新しい位置を覚える（★整列後の幅で保存する。RX-0062）
            self.save_window_state()

        QTimer.singleShot(0, _after_arranged)
        self._align_status.setText(
            f"標準レイアウトに戻しました（{moved}個）"
            if moved else "⚠ " + "／".join(messages[:1] or ["並べられません"]))


    def _ensure_book_window(self):
        """図鑑の窓を1つだけ用意する（無ければ作る）。"""
        from .monster_book_window import MonsterBookWindow

        if getattr(self, "_book_window", None) is None:
            # ★親を渡さない。渡すと本体の中に閉じ込められる場合がある
            self._book_window = MonsterBookWindow(self.vm)
            # ★前回の場所を戻す（2026-08-09 / 地図・ログと同じ理由）。
            #   ⚠ 遅延生成なので起動時の復元ループには載りません。
            self._window_state().apply_to("book", self._book_window)
        return self._book_window

    def _open_monster_book(self) -> None:
        """ボタンで図鑑を開く（2つ目を作らない）。

        ★押すたびに新しい窓が増えると、どれが最新か分からなくなる。
          既にあるものを前面に出し、**開いているあいだに増えた記録を読み直す**。

        ★**ボタンで開いたときだけフォーカスを取る**。
          利用者が自分で押したのだから、前に出て操作できるのが正しい。
          遭遇による自動表示（`_show_encounter`）とはここが違う。
        """
        window = self._ensure_book_window()
        if window.isVisible():
            # 既に開いているなら中身を新しくする（戦闘が増えているかもしれない）
            window.reload()
        window.show()
        window.raise_()
        window.activateWindow()

    # --- 遭遇したら図鑑を出す（依頼者の要望 / 2026-07-27）------------------

    def _track_encounter(self, game) -> None:
        """新しい戦闘に入ったらメイン画面の図鑑を出し直す。

        ★★ **戦闘が終わっても消さない**（2026-07-27 / 依頼者の指摘）★★

          > オート戦闘だとすぐ消えちゃうので、次の戦闘まで残すようにしてもらえる？

          倍速（約35倍）だと戦闘が一瞬で終わり、**読む前に消えていた**。
          次の戦闘が始まるまで残す。

        ⚠ **残すなら「いつのものか」を書く。** 書かないと、フィールドを
          歩いている最中の表示を「いま戦っている敵」と読み違える
          （0 と 不明 を混ぜないのと同じ話）。
          → `set_active()` で「いま戦っている敵 / 直前の戦闘の敵」を出し分ける。

        ★**種の集合が変わったときだけ**中身を作り直す。0.5秒ごとに作り直すと
          描画がちらつく（PartyPanel と同じ理由）。

        ★戦闘が始まってから DB を読み直さない。全戦闘を走査するので重く、
          戦闘の入口で 0.5 秒止まると倍速の意味が無くなる。
          ROM 由来の値（HP・耐性・行動・ドロップ）は**動かない事実**なので、
          読み直さなくても正しい。増えるのは遭遇回数だけ。
          → 行は起動時に一度だけ渡してある（`_load_encounter_rows`）。
        """
        # --- ★★ 戦闘まるごと1回を見逃す問題（2026-07-29）★★ ---------------
        #
        # 依頼者の指摘:
        #   > 偶に出会った敵で切り替わらない場合がある。
        #   > オート戦闘だからタイミング障害かもだが
        #
        # **そのとおりだった。** この画面は 0.5 秒ごとに state.json を見るが、
        # 倍速（約35倍）だと**戦闘の始まりから終わりまでが 0.5 秒に収まる**
        # ことがあり、`in_battle=True` を一度も見ないまま次のフィールドになる。
        # 見ていない戦闘は「新しい戦闘」と気づけず、前の敵が出たままになる。
        #
        # → **Lua が数えた戦闘の通し番号を使う。** 番号が変わっていれば、
        #   戦闘中の瞬間を見ていなくても切り替える。
        #   種の集合も Lua が溜めているので、そのまま使える。
        seq = game.battle_seq
        if seq is not None and seq != getattr(self, "_battle_seq", None):
            self._battle_seq = seq
            self._battle_species = list(game.battle_species)
            if self._battle_species:
                self._encounter.update_encounter(self._battle_species)
                window = getattr(self, "_book_window", None)
                if window is not None and window.isVisible():
                    window.follow_encounter(self._battle_species)

        now_ids: list[int] = []
        if game.in_battle:
            # ★グループの並び順を保つ（画面の並びと合う）。重複は除く
            now_ids = list(dict.fromkeys(g.id for g in game.enemy_groups if g.id))
            if not now_ids:
                # グループがまだ読めていないときは個体から拾う（保険）
                now_ids = list(dict.fromkeys(e.id for e in game.enemies if e.id))

        # ★★ 下段の帯（2026-08-09 / 依頼者の指示）★★
        #   > 下の窓の上段に戦うモンスターを表示させる
        self._refresh_battle_strip(game, now_ids)

        # --- 戦闘の入口で**溜める箱を空にする**（依頼者の指定）--------------
        #
        # > 次の戦いで初期化して表示する形が良いかと思う
        #
        # ⚠ Lua の通し番号が来ない古い環境のための受け皿として残す。
        #   番号が来ていれば上で既に空にしてある。
        was = getattr(self, "_encounter_active", None)
        if game.in_battle and not was and game.battle_seq is None:
            self._battle_species: list[int] = []

        # --- いつのものかの表示（軽いので条件を付けない）--------------------
        if game.in_battle != was:
            self._encounter_active = game.in_battle
            self._encounter.set_active(game.in_battle)
            window = getattr(self, "_book_window", None)
            if window is not None and window.isVisible():
                window.set_encounter_active(game.in_battle)

        # --- ⚠⚠ この戦闘で見た種は**足すだけ。減らさない** ⚠⚠ -------------
        #
        # ★依頼者の指摘: 「敵を倒しちゃうと消えるのは渋い」
        #
        #   原因は `enemy_groups` が**生き残りしか映さない**こと。
        #   倒すとその種が消えるので、種の集合が変わり、出し直して枠が消えていた。
        #   **戦闘終了だけを守っていて、戦闘途中の撃破を見落としていた。**
        #
        # ★だから「いま出ている敵」ではなく「**この戦闘で出会った敵**」を出す。
        #   倒しても残るし、「仲間を呼ぶ」で増えた種も足せる（0x1C の行動）。
        #
        # ⚠ 戦闘の最初の数フレームは `enemy_groups` がまだ読めないことがある。
        #   足すだけの作りなら、読めた時点で入るので取りこぼさない。
        if not game.in_battle:
            return          # ★戦闘が終わったら触らない（次の戦闘まで残す）

        seen = getattr(self, "_battle_species", [])
        added = [i for i in now_ids if i not in seen]
        if not added:
            return
        seen = seen + added
        self._battle_species = seen

        self._encounter.update_encounter(seen)

        # ★別ウィンドウが**すでに開いている**なら、そちらも追わせる。
        #   ⚠ 開いていないなら開かない。メインに出るので開く必要が無く、
        #     窓が勝手に飛び出す副作用（フォーカス・並びの乱れ）も避けられる。
        window = getattr(self, "_book_window", None)
        if window is not None and window.isVisible():
            window.follow_encounter(seen)

    def _load_encounter_rows(self) -> None:
        """メイン画面の図鑑が使う行を用意する（起動時に一度だけ）。

        ★ここで一度引いておけば、戦闘の入口で DB を触らずに済む。
        ⚠ 遭遇回数は古くなるが、メイン画面に出すのは**ROM 由来の値だけ**
          （HP・攻撃・守備・耐性・行動・ドロップ）なので影響しない。
        """
        try:
            self._encounter.set_rows(self.vm.monster_book())
        except Exception:
            # ★図鑑が引けなくても本体は動かす（表示用の処理で本体を止めない）
            pass

    def _refresh_battle_strip(self, game, now_ids) -> None:
        """戦っている敵の帯を更新する（2026-08-09 / 下段の上段）。

        ★グループが読めていれば**体数つき**（`スライム×2`）で出します。
        ⚠ まだ読めていない数フレームは ID の並びで作ります。★どちらでも
          切り捨てません（入らないぶんは横スクロール）。

        ⚠ 表示用の処理なので、ここで失敗しても本体は止めません
          （`_load_encounter_rows` と同じ扱い）。
        """
        window = getattr(self, "_log_window", None)
        if window is None:
            return
        from . import battle_monsters as bm

        try:
            names = getattr(self.vm, "monsters", {}) or {}
            art = self.vm.monster_art_path
            groups = getattr(game, "enemy_groups", None) or ()
            cards = (bm.cards_from_groups(groups, names, art)
                     if game.in_battle and groups
                     else bm.cards_from_ids(now_ids, names, art))
            window.set_monsters(cards)
        except Exception:                       # noqa: BLE001
            # ★帯が出ないだけに留める。⚠ 戦闘中に本体を止めるほうが害が大きい
            pass

    def _log_close_reason(self) -> None:
        """閉じた経路を INFO で1行残す（2026-08-19 / RX-0077）。

        ⚠ 「急に終了した」を後から追えるように。終了ボタンは `_shutdown` で
          印（`_closing_via_exit_button`）を立てる。印が無ければ外部
          （×/Alt+F4/セッション終了）で、その場合は**ゲームのセーブステート
          保存を通っていない**（closeEvent は窓の位置しか保存しない）。
        """
        from ..core.logging_setup import get_logger
        if getattr(self, "_closing_via_exit_button", False):
            get_logger("gui").info("終了ボタンから閉じました")
        else:
            get_logger("gui").info(
                "ウィンドウが外部から閉じられました"
                "（×ボタン / Alt+F4 / セッション終了。終了ボタンを経由していません）")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt の命名)
        """本体を閉じたら別ウィンドウも閉じ、位置を覚える。

        ★閉じないと図鑑だけが残り、**本体が終わったのに窓が居座る**。
          「保存して終了」を押したのにアプリが終わらないように見える。

        ★★ 窓の位置を覚える（リリース調整 仕様書 8章）★★
          ⚠ **閉じる前に取る**。閉じたあとでは geometry が取れない。
          ★★ ゲームを保存したかに関係なく、ここで必ず保存する（依頼者 /
            2026-08-11）。「保存せずに終了」でも窓の配置は残す。全終了経路は
            `self.close()` を通るので、ここが1か所の保存点。
        """
        # ★★ **どの経路で閉じたかを1行残す**（2026-08-19 / RX-0077）★★
        self._log_close_reason()

        self.save_window_state(reason="終了")
        # ★★ ⚠⚠ **× ボタンでも FCEUX を止める**（2026-08-18 / RX-0058）★★
        #   ⚠ ここへ移すまで、後始末は「終了」ボタンの中にしか無かった。
        self._teardown()
        for name in ("_book_window", "_map_window", "_tactics_window",
                     "_log_window"):
            window = getattr(self, name, None)
            if window is not None:
                window.close()
        super().closeEvent(event)

    # --- 移動・リサイズ後の保存（2026-08-01 の指示書 §5.2）---------------
    #
    # ★★ **動かしている最中には保存しない。** ★★
    #   `moveEvent` はドラッグ中に**毎ピクセル**飛んでくる。そのたびに
    #   ⚠ ファイルを書くと、窓を動かすだけでディスクを叩き続けることになる。
    #   ★最後の変化から一定時間だけ待ってから1回書く（デバウンス）。

    #: 最後の移動・リサイズから待つ時間（ミリ秒 / 指示書 §5.2 の推奨値）
    LAYOUT_SAVE_DELAY_MS = 750

    def _schedule_layout_save(self) -> None:
        """保存を予約する。★途中でまた動いたら**予約を取り直す**。"""
        timer = getattr(self, "_layout_timer", None)
        if timer is None:
            timer = self._layout_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.save_window_state)
        timer.start(self.LAYOUT_SAVE_DELAY_MS)

    def moveEvent(self, event) -> None:       # noqa: N802 (Qt の命名)
        super().moveEvent(event)
        self._schedule_layout_save()

    def resizeEvent(self, event) -> None:     # noqa: N802 (Qt の命名)
        super().resizeEvent(event)
        self._schedule_layout_save()

    # --- 窓の位置（仕様書 8章）------------------------------------------

    def _window_state(self):
        """状態の入れ物を1つだけ作る。"""
        from .window_state import WindowState

        if getattr(self, "_win_state", None) is None:
            self._win_state = WindowState()
        return self._win_state

    def restore_window_state(self) -> None:
        """位置とサイズを戻す（起動時に呼ぶ）。

        ★★ **画面外に保存されていたら主画面へ戻す** ★★
          （`window_state.clamp_to_screens` が判断する）。
          ⚠ これが無いと、外付けモニタを外したときに
            窓が見えない場所に開き、**利用者からは「起動しない」**に見える。
        """
        from ..core.logging_setup import get_logger

        log = get_logger("gui")
        state = self._window_state()

        # ★★ どの窓を、どんな記録で、どう戻したかをログに残す（依頼者の要望）★★
        #   ⚠ 「試み（記録の中身）」と「結果（適用したか／既定に落ちたか）」を
        #     分けて書く。★戻らないときに、記録が無いのか・小さすぎたのか・
        #     画面外だったのかを切り分けられるようにする。
        def _restore(key, widget, splitter=None):
            saved = state.get(key)
            before = len(state.problems)
            applied = state.apply_to(key, widget, splitter=splitter)
            note = "；".join(state.problems[before:]) if len(
                state.problems) > before else ""
            if not saved:
                log.debug("窓の復元 %s: 記録なし → 既定で開く", key)
            else:
                log.debug(
                    "窓の復元 %s: 試み=%s,%s %s×%s → %s%s", key,
                    saved.get("x"), saved.get("y"),
                    saved.get("w"), saved.get("h"),
                    "適用" if applied else "既定に戻す",
                    f"（{note}）" if note else "")

        # ⚠ 2026-08-11: 本体の split（敵情報＋パーティ）の配分は**復元しない**。
        #   パーティ表は内容ぶんに縛るので配分を保存する意味が無く、大きい配分を
        #   戻すと表の下に空白ができていた（依頼者の指摘）。位置・サイズは戻す。
        _restore("main", self)
        for name, key in (("_map_window", "map"),
                          ("_book_window", "book"),
                          ("_tactics_window", "tactics")):
            window = getattr(self, name, None)
            if window is not None:
                _restore(key, window)

        # ★戻した直後だけ、下の余白を詰める（2026-08-11）
        #   ⚠ 記録が大きすぎたときの空白を消すのがここの役目。
        #     ★遊んでいる最中は呼びません（窓の縁が動くとチカチカします）。
        self._trim_blank_bottom()

        # ★戻せなかった理由は黙って捨てない（画面に出す）
        #   ⚠ 設定のパスが取れなかったこと（`_config_path` が既定へ落ちた）も
        #     ここで出す。**黙って既定を使うと、たまたま合っていて気づけない**
        #     （実際 `backup_lock` はそれで通り、`log` だけ壊れていた）。
        problems = list(state.problems)
        problems += [f"設定のパスが読めません（{p}）"
                     for p in getattr(self, "_config_problems", [])]
        if problems:
            self._diag_status.setText("／".join(problems[-2:]))

    def reopen_remembered_windows(self) -> None:
        """前回開いていた窓を開き直す（2026-08-09 / 依頼者の指示）。

            > 起動するときに、前回の位置、サイズをなるべく再現してほしい。
            > 毎回直すのが大変なので。

        ⚠⚠ **`restore_window_state()` からは呼びません。** ★あちらは
          「窓の形を戻す」処理で、**開閉は起動時だけの関心事**です。
          混ぜると、`MainWindow` を作るだけのテストでも窓が開いてしまいます
          （実際 `test_closed_separate_window_is_not_touched` が落ちました）。
        ★起動の道（`gui.py`）だけが呼びます。

        ⚠ 開く処理そのもの（`_open_*`）を使います。`show()` だけ呼ぶと、
          中身の読み直しや配置の後始末が飛びます。
        """
        state = self._window_state()
        # ⚠ 図鑑は**開き直しません**（2026-08-09 / 依頼者の指示
        #   「モンスター図鑑は初期表示しないでいい」）。
        #   ★調べたいときに開く窓なので、起動のたびに出ると邪魔になります。
        for key, opener in (("map", self._open_map_window),
                            ("tactics", self._open_tactics_window)):
            if not (state.get(key) or {}).get("open"):
                continue
            try:
                opener()
            except Exception:                           # noqa: BLE001
                # ⚠ 開けなくても起動は続ける。★理由は画面に出す
                self._diag_status.setText(f"⚠ {key} を開き直せませんでした")

    def save_window_state(self, reason: str = "") -> bool:
        """窓の位置・サイズ・スプリッタの配分を保存する。

        ★★ **ゲームを保存したかに関係なく保存する**（2026-08-11 / 依頼者）★★
          「保存せずに終了」でも窓の配置は残したい。★終了の道（`_shutdown`）と
          移動・リサイズのデバウンス、`closeEvent` の**すべて**がここを通る。

        ⚠ 何を保存したかをログに残す（依頼者の要望）。★毎回の移動でも呼ばれる
          ので DEBUG（画面には出さない / ログボタンで後から追える）。
        """
        from ..core.logging_setup import get_logger

        state = self._window_state()
        # ⚠ 本体の split の配分は保存しない（復元もしない / 2026-08-11）。
        state.capture_from("main", self,
                           extra={"follow_log": bool(
                               self._follow_log.isChecked())})
        for name, key in (("_map_window", "map"),
                          ("_book_window", "book"),
                          ("_tactics_window", "tactics")):
            window = getattr(self, name, None)
            if window is not None:
                # ★開いていたかも覚える（2026-08-09）。⚠ 閉じた窓の位置は
                #   覚えたままにする（次に開いたとき同じ場所へ出すため）。
                state.capture_from(key, window,
                                   extra={"open": bool(window.isVisible())})
        # ★下段の窓は境界も覚える（ログの高さは人によって好みが違う）
        log_window = getattr(self, "_log_window", None)
        if log_window is not None:
            state.capture_from("log", log_window,
                               splitter=log_window.splitter())
        ok = state.save()

        # ★何を保存したかを1行で残す（後から追えるように / 依頼者）。
        summary = "／".join(
            f"{k} {v.get('x')},{v.get('y')} {v.get('w')}×{v.get('h')}"
            for k, v in sorted(state.data.items()) if isinstance(v, dict))
        get_logger("gui").debug(
            "窓の状態を保存%s%s: %s",
            f"（{reason}）" if reason else "",
            "" if ok else " ★書けませんでした",
            summary or "（対象なし）")
        return ok

    def _build_system_log_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(_section("System Log"))
        # ★追従しているかを**画面に出す**（playbook #35）。
        #   黙って追従を止めるのが元の不具合だったので、状態を見せる。
        #   上へスクロールすると自動で外れ、一番下へ戻すと自動で戻る。
        self._follow_log = QCheckBox("最新に追従")
        self._follow_log.setChecked(True)
        self._follow_log.setToolTip(
            "新しいログが来たら自動で一番下まで送ります。\n"
            "上へスクロールすると自動で外れ（過去のログが読めます）、\n"
            "一番下へ戻すと自動で戻ります。")
        self._follow_log.toggled.connect(self._on_follow_toggled)
        row.addWidget(self._follow_log)
        row.addStretch(1)
        layout.addLayout(row)

        self._system_log = QPlainTextEdit()
        self._system_log.setReadOnly(True)
        self._system_log.setMaximumBlockCount(1000)
        self._system_log.setPlaceholderText("（まだ出力はありません）")
        self._system_log.verticalScrollBar().valueChanged.connect(
            self._on_log_scrolled)
        layout.addWidget(self._system_log, stretch=1)
        return panel

    def _build_table(self) -> QTableWidget:
        from PySide6.QtWidgets import QHeaderView

        table = QTableWidget(0, len(_LOG_COLUMNS))
        table.setHorizontalHeaderLabels(_LOG_COLUMNS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        # ★★ 列幅（2026-07-30 / リリース調整 仕様書 7.5）★★
        #
        #   > 幅が足りない場合:
        #   >   ドロップ候補をツールチップまたは詳細表示へ
        #   >   長い敵名を省略表示し、ツールチップで全文
        #   >   横スクロールより重要列固定を優先
        #
        # ⚠ 以前は「モンスター名だけ Stretch、残りは内容に合わせる」だったが、
        #   **ドロップ候補が長い**（「やくそう / どくけしそう / …」）ため
        #   内容に合わせると横に伸び、1366×768 では右端が見切れた。
        #
        # → ドロップ候補も**伸縮**にして、溢れたら省略＋ツールチップにする
        #   （中身は `_fill_table` がツールチップへ入れている）。
        header = table.horizontalHeader()
        for i, name in enumerate(_LOG_COLUMNS):
            if name in _STRETCH_COLUMNS:
                mode = QHeaderView.ResizeMode.Stretch
            else:
                mode = QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(i, mode)
        # ★★ **横スクロールより重要列固定**（仕様書 7.5）★★
        #   横スクロールにすると「時刻」が流れて、どの戦闘の行か分からなくなる。
        header.setStretchLastSection(False)
        table.setHorizontalScrollMode(
            QTableWidget.ScrollMode.ScrollPerPixel)
        # ★溢れた文字は省略する（… で切る）。全文はツールチップ
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.setWordWrap(False)
        return table

    # --- 操作 --------------------------------------------------------


    # --- ★ 何を何秒ごとにやるか（2026-08-07 / 軽量化指示書 §6）------------
    #
    # ⚠⚠ **全部を 0.2 秒周期に載せない。**
    #   ★仕事の性質ごとに間隔を変えます。指示書 §6 の表がそのまま根拠です。
    #
    # ⚠ 数字の根拠（★勝手に縮めないこと）:
    #
    #   心拍       1.0秒  … 期限は 10 秒（`single_instance.HEARTBEAT_STALE_SECONDS`）
    #   保護の状態 1.5秒  … 期限は 20 秒（`backup_status.STALE_SECONDS`）
    #   ログ       0.5秒  … Lua が state を書くのと同じ間隔
    #   敵の絵     2.0秒  … 図鑑に出るのが数秒遅れても困らない
    #
    # ⚠ どれも「期限の 1/6 以下」に収めてあります。★間隔を期限に近づけると、
    #   1回取りこぼしただけで「止まっている」と表示されます。
    SLOW_JOBS = {
        "心拍": 1.0,
        "保護の状態": 1.5,
        "SystemLog更新": 0.5,
        "敵の絵の切り出し": 2.0,
        # ⚠ 選んだ作戦はファイルから読みます（★人が触ったときは別途すぐ直す）
        "戦術の表示": 1.0,
    }

    def _due(self, name: str) -> bool:
        """`name` の仕事をやる番か。★初回は必ず true。"""
        import time

        every = self.SLOW_JOBS[name]
        last = self._slow_job_at.get(name)
        now = time.monotonic()
        # ⚠ 時計が巻き戻ることはない（`monotonic`）。★止まる心配をしなくてよい
        if last is not None and now - last < every:
            return False
        self._slow_job_at[name] = now
        return True

    def refresh(self) -> None:
        # ★区間ごとに測る（2026-07-31 の指示書 §10.3）。
        #   ⚠ 既定は無効。`RETROUX_PERF=1` で入る（`ui/perf.py`）。
        probe = self._perf
        with probe.section("全体更新"):
            # ★★ 心拍は「死活確認」であって状態更新ではありません（§6.1）★★
            #   ⚠ 0.2 秒ごとにファイルを書き直す必要はありません。
            if self._heartbeat is not None and self._due("心拍"):
                with probe.section("心拍"):
                    self._heartbeat()
            with probe.section("state読込"):
                state = self.vm.poll()
            self._render(state)
            if self._due("SystemLog更新"):
                with probe.section("SystemLog更新"):
                    self._drain_system_log()
            # ★撮ったままの画面から敵の絵を切り出す（**新しいものだけ**）。
            #   実機が撮ったら、次の更新で図鑑に出る。
            #   ⚠ 失敗しても本体は止めない（ViewModel 側で握っている）。
            if self._due("敵の絵の切り出し"):
                with probe.section("敵の絵の切り出し"):
                    self._trim_and_show_art()

    def _trim_and_show_art(self) -> None:
        """撮った画面から絵を切り出し、★出来たらその場で図鑑に出す。

        ⚠⚠ **依頼者の報告「１回モンスターグラフィックが出ない場面があった」**
        （2026-08-08）。

          ★図鑑の絵は `_track_encounter` が **戦闘が変わったときだけ**
            並べ直します。⚠ 切り出しはそのあとに走るので、
            **その戦闘の絵は間に合いません**。
            ⚠ そして次に並べ直されるのは**次の戦闘**なので、
              初めて見た敵の絵は「1戦ぶん遅れて」出ていました。

          ⚠ 2026-08-07 の軽量化で切り出しを 2 秒ごとにしたため、
            ★間に合わない幅が広がっていました。

        → ★切り出せたら、**その場で並べ直します**。
          ⚠ 何も出来ていないときは触りません（★無駄な描き直しをしない）。
        """
        made = self.vm.trim_new_art()
        if not made:
            return
        species = getattr(self, "_battle_species", None)
        if species:
            self._encounter.update_encounter(species)
        window = getattr(self, "_book_window", None)
        if window is not None and window.isVisible() and species:
            window.follow_encounter(species)

    def _track_position(self, game) -> None:
        """いまの場所を記録し、1行の表示と地図を更新する（2026-07-29）。

        ★★ **変わったときだけ書く** ★★
          同じマスに十数フレーム居るので、毎回 DB を叩くと無駄が多い。

        ⚠ 表示のための処理で本体を止めない。
        """
        self._where.setText(self.vm.where_am_i(game))
        # ★いま効いている戦術（AI操作OFF の人も出す）
        # ⚠ `tactics_label()` は**選んだ作戦のファイルを読みます**。
        #   ★0.2 秒ごとに読む必要はありません（2026-08-07 / 軽量化指示書 §6）。
        #   ⚠ 人が切り替えたときは `reload_tactics_picker()` が即座に直すので、
        #     ★待たされるのは「画面の外で変わったとき」だけです。
        if self._due("戦術の表示"):
            self._tactics_label.setText(self.vm.tactics_label())

        key = (game.map_id, game.map_data_pointer, game.map_x, game.map_y)
        if key != self._last_position:
            self._last_position = key
            self.vm.note_position(game)

        window = getattr(self, "_map_window", None)
        if window is not None and window.isVisible():
            window.follow(game.map_id, game.map_data_pointer,
                          game.map_x, game.map_y)

    # ★スクロールが「一番下にいる」と見なす余裕（ピクセル）。
    #   ぴったり maximum でなければ追従しない作りにすると、
    #   行の高さの端数で判定が外れて**追従しなくなる**。
    SCROLL_STICKY_SLACK = 4

    @staticmethod
    def _is_at_bottom(widget, slack: int = SCROLL_STICKY_SLACK) -> bool:
        bar = widget.verticalScrollBar()
        # ★スクロールバーが不要なとき（maximum == 0）も「一番下」と見なす。
        #   ここを false にすると、ログが1画面に収まっている間は追従しない。
        return bar.value() >= bar.maximum() - slack

    def _scroll_to_bottom(self, widget) -> None:
        """最新行が見えるところまで送る。

        ★スクロールバーとテキストカーソルの**両方**を末尾へ送る。
          バーだけ動かすと、キーボードで下を押した瞬間に
          カーソルの居る場所（途中）へ飛び戻る。

        ⚠ 自分が動かしたぶんで「利用者が手で動かした」と誤判定しないよう、
          フラグを立てている（`_on_log_scrolled` を参照）。
        """
        self._scrolling_log = True
        try:
            cursor = widget.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            widget.setTextCursor(cursor)
            bar = widget.verticalScrollBar()
            bar.setValue(bar.maximum())
        finally:
            self._scrolling_log = False

    def _append_log_lines(self, widget, lines) -> None:
        """ログを追記し、「最新に追従」が入っていれば最新行まで送る。

        ★★ 不具合の中身（2026-07-27 / 依頼者の報告
          「右側のログが、カーソルが下になくて、下押さないと見れない」）★★

          `QPlainTextEdit.appendPlainText` が自動で追従するのは
          **追記の直前にスクロールバーが最大値にいたときだけ**。
          そのため **一度でも表示が一番下から離れると、以後どれだけ
          追記しても二度と追従しない。**

          実測（`research/probes/archived/probe_scroll.py`）— 表示が途中に移った直後から
          value が 0 のまま max だけ増え続ける:

              本文の途中へ移った状態   value=  0 max=236
                そのあと追記           value=  0 max=241
                さらに追記             value=  0 max=246

          この状態から抜ける手段が画面に無かったため、
          利用者は毎回手で一番下まで送る必要があった。

        ⚠ **常に一番下へ送る**のも不具合になる。0.5秒ごとに送ると、
          上へ戻って読んでいる最中に引きずり降ろされて過去のログが読めない。
          「追従」と「固定」は別のこと。

        ★そこで**追従しているかどうかを画面に出す**（チェックボックス）。
          黙って追従を止めるのが元の不具合だったので、状態を見せて、
          外れたら**チェックを外して見せる / 一番下へ戻したら自動で戻す**。
        """
        appended = False
        for line in lines:
            if not self._show_in_gui(line):
                continue
            widget.appendPlainText(line)
            appended = True
        if appended and self._follow_log.isChecked():
            self._scroll_to_bottom(widget)

    #: 画面に出す段階の下限（★数字が大きいほど重い）
    _LEVEL_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40,
                   "CRITICAL": 50}

    def _show_in_gui(self, line: str) -> bool:
        """この行を System Log に出すか（2026-08-13 / 製品版ログ整理）。

        ## ⚠⚠ なぜ要るか

          `user_config.yaml` の `logging.gui_level` は
          「画面に出す下限」と書いてあります。★しかし **効いていませんでした**。

          `GuiLogHandler` は `gui_level` を見ますが、⚠ `_log_path` が
          設定されていると `_drain_system_log` は **ファイルを直接読む**道へ
          入り、Handler を通りません（`_drain_log_file`）。
          ★つまり画面にはファイルの中身（＝`level` の下限）が出ていました。

        ## ★ 段階は行の形から取る

          Python も Lua も `日時 [段階] 名前 本文` に揃えたので、
          ★1本の規則で読めます。

        ⚠ 段階が読めない行は**出します**（★消すより出すほうが安全。
          読めないのはこちらの都合で、利用者の問題ではない）。
        """
        want = getattr(self, "_gui_level_rank", None)
        if want is None:
            return True
        # ★`2026-08-13 09:00:00 [INFO] name 本文`
        head = line[20:34] if len(line) > 20 else ""
        if not head.startswith("["):
            return True
        name = head[1:head.find("]")] if "]" in head else ""
        rank = self._LEVEL_RANK.get(name)
        if rank is None:
            return True
        return rank >= want

    def _on_log_scrolled(self, _value: int) -> None:
        """利用者が手でスクロールしたら、追従の入り切りを合わせる。

        ★端末やログビューアと同じ挙動:
          上へ動かしたら追従をやめ（チェックが外れる＝**見て分かる**）、
          一番下へ戻したら追従が復活する（チェックが戻る）。

        ⚠ 自分が `_scroll_to_bottom` で動かしたぶんは無視する。
          区別しないと、追従で下へ送った直後に「利用者が動かした」と
          読んで自分でチェックを付け直す無意味な往復になる。
        """
        if self._scrolling_log:
            return
        self._follow_log.setChecked(self._is_at_bottom(self._system_log))

    def _on_follow_toggled(self, checked: bool) -> None:
        """チェックを入れ直したら、その場で最新行まで送る。

        ★入れただけで何も起きないと「効いていない」と受け取られる
          （次の行が来るまで動かないため）。押した結果をすぐ見せる。
        """
        if checked:
            self._scroll_to_bottom(self._system_log)

    def _drain_system_log(self) -> None:
        """新しく増えたログ行だけを追記する。

        ★全件を読み直さない（指示書の禁止事項）。位置を覚えて続きだけ読む。
        """
        if self._log_path is not None:
            self._drain_log_file()
            return
        if self._log_buffer is None:
            return
        lines, cursor = self._log_buffer.snapshot(self._log_cursor)
        self._log_cursor = cursor
        self._append_log_lines(self._system_log, lines)

    def _drain_log_file(self) -> None:
        from ..core.bridge.reader import JsonlTailer

        if self._log_tailer is None:
            # ★初回は**末尾だけ**を出す。3000行を流し込むと、
            #   起動のたびに描画で固まるし、いま起きていることが埋もれる。
            try:
                existing = self._log_path.read_text(
                    encoding="utf-8", errors="replace").splitlines()
                size = self._log_path.stat().st_size
            except OSError:
                existing, size = [], 0
            # ★初回の流し込みも段階で絞る（⚠ ここを忘れると、起動直後だけ
            #   DEBUG がどっと出て、以後は出ない、という**ちぐはぐ**になる）
            shown = [ln for ln in existing if self._show_in_gui(ln)]
            for line in shown[-self.INITIAL_LOG_LINES:]:
                self._system_log.appendPlainText(line)
            # ★初回は**必ず**一番下へ送る（「いたかどうか」を見ない）。
            #   ここが起点なので、下に置いてから追従を始める。
            #
            # ⚠ この時点ではまだウィンドウが表示されていないことがある
            #   （`__init__` の最後の refresh() から呼ばれる）。
            #   実測（research/probes/archived/probe_scroll.py）では **value=0 / maximum=199** で、
            #   スクロールバーの上では「一番下にいない」状態だった。
            #   offscreen の Qt は show の時点で value を maximum に揃えたが、
            #   **それに頼らず自分で送る**（環境で変わる挙動を前提にしない）。
            self._scroll_to_bottom(self._system_log)
            self._log_tailer = JsonlTailer(self._log_path, start_offset=size)
            return

        self._append_log_lines(
            self._system_log,
            (line for line in self._log_tailer.read_new_lines() if line))

    def showEvent(self, event) -> None:  # noqa: N802 (Qt の命名)
        """表示された直後に、もう一度ログを一番下へ送る。

        ★起動時の流し込みは**表示前**に走る（`__init__` の最後の refresh）。
          表示でレイアウトが確定するとスクロールバーの maximum が変わるため、
          ここでもう一度そろえておく。

        ⚠ **これが依頼者の報告の原因だと断定はできていない。**
          offscreen の Qt では show の時点で Qt 自身が value を maximum に
          揃えており、この経路だけでは不具合が再現しなかった
          （`research/probes/archived/probe_scroll.py`）。**再現したのは「一度一番下から離れると
          二度と追従しない」ほう**で、そちらの対策が
          `_append_log_lines` と追従チェックボックスにある。
          ここは「表示の前後で位置がずれない」ための念押し。

        ★1度だけ送る。最小化からの復帰などで showEvent は何度も呼ばれるので、
          毎回送ると上へ戻って読んでいる利用者を引きずり降ろす。
        """
        super().showEvent(event)
        if not self._log_scrolled_on_show:
            self._log_scrolled_on_show = True
            self._scroll_to_bottom(self._system_log)

    # --- ⚠ 敵情報の段は削除しました（2026-08-11 / 依頼者）------------------
    #
    #   「既定で畳む」「スプリッタで開く」の仕組みも一緒に消えています。
    #   ★経緯は `docs/history/ui-changes.md`。

    def _trim_blank_bottom(self) -> None:
        """窓が内容より高いとき、内容ぶんの高さへ縮める（2026-08-11 / 依頼者）。

        ★下の余分な空白を出さない。⚠ `maxHeight` で縛ると折り返しラベルの
          都合で内容を切ることがあったので、**縮めるだけ**にする（幅は変えない）。

        ★★ **並べ直し・復元のときだけ**呼びます ★★

          ⚠ `_render`（0.2 秒ごと）から呼ぶと、中身が変わるたびに窓の縁が
            動きます（依頼者「目がチカチカしてみづらい」）。
          ★経緯と実測は `docs/history/ui-changes.md`。
        """
        want = self.sizeHint().height()
        if want > 0 and self.height() > want + 8:
            self.resize(self.width(), want)

    def _render(self, state: UiState) -> None:
        self._state_value.setText(state.state_label)
        # 危険状態は倍速が解除される局面。色で区別できるようにする。
        # ★赤くするのは**本当に危ないときだけ**。
        #   タイトル画面でパーティを読めないのは「危険」ではなく「まだ読めていない」。
        #   実際、タイトル画面で赤い『危険状態』が出っぱなしになり、
        #   壊れているように見えた（安全側へ正しく倒れていただけ）。
        # ★★ **何を出すかは ViewModel、色にするのはここ**（指示書 §7.2）★★
        #   ⚠ 分割前はここで文言と色を同時に組み立てていた。文言を1つ
        #     確かめるのに画面を建てる必要があり、AUTO の5分岐は
        #     **1件もテストされていなかった**（2026-08-01 に実測）。
        self._state_value.setStyleSheet(_color(state.state_tone))

        speed = self._badge_with_request(state.speed_badge, "高速化")
        self._speed_value.setText(speed.text)
        self._speed_value.setStyleSheet(_color(speed.tone))

        self._gold_value.setText(state.gold_text)

        auto = self._badge_with_request(state.auto_badge, "AUTO")
        self._auto_value.setText(auto.text)
        self._auto_value.setStyleSheet(_color(auto.tone))
        game = state.game

        # ★★ 2つのトグルを **Lua の状態に合わせる**（2026-07-31）★★
        #   キーボード A でも AUTO が切り替わるので、ボタンが自分の押した値
        #   だけを覚えていると**表示が嘘になる**（A で切ったのに ON のまま）。
        #   ⚠ 2軸を別々に渡す。片方から他方を推測しない。
        self._sync_auto_button(getattr(game, "auto_enabled", None))
        self._sync_turbo_button(getattr(game, "turbo_enabled", None))
        # ★推論の4段（2026-08-07 / Phase 9）。⚠ 落ちても画面を止めない。
        self._update_reasoning(game)

        # ★★ キーで頼まれたアクションを実行する（2026-08-01）★★
        #   ⚠ キーを拾えるのは Lua だけ（遊んでいる間フォーカスは FCEUX）。
        #     Lua が「押された」と書き、ここで実行する。
        self._run_requested_action(game)

        # セーブステート保護（仕様書 6.1）
        # ⚠ ファイルを読むので 1.5 秒ごと（★軽量化指示書 §6。期限は 20 秒）
        if self._due("保護の状態"):
            with self._perf.section("保護の状態"):
                self._refresh_backup_status()

        # ★パーティと AI 判断は state.json（Lua が書く現在値）から
        probe = self._perf
        with probe.section("パーティ表示"):
            self._party.update_party(state.game.party, actor=state.game.actor)
            # ★★ パーティ状態を上詰めにし、余りは下段へ（2026-08-11 / 依頼者）★★
            #   ⚠ 入れ物を表の高さに縛るだけでは、split（敵情報＋パーティ）の
            #     区画がまだ大きいと、表の下に空白が残る（依頼者の3人時の指摘）。
            #   ★split 全体の**最大の高さ**も、いまの中身
            #     （畳んだ敵情報の高さ ＋ パーティ表の高さ）に縛る。これで
            #     区画が中身ぴったりになり、窓の余りは root 末尾の伸縮＝下へ行く。
            container = getattr(self, "_party_container", None)
            if container is not None:
                container.setMaximumHeight(container.sizeHint().height())
            # ⚠ ここで「その場の高さ」を上限にしない（★堂々巡りになる）。
            #   経緯は `docs/history/ui-changes.md`。
        with probe.section("AI判断表示"):
            self._ai.update_state(state.game)
            self._log_ai_decision(state.game)
        with probe.section("遭遇の記録"):
            self._track_encounter(state.game)
        with probe.section("現在地・地図"):
            self._track_position(state.game)
        self._mode_value.setText(state.mode_text)

        warning = state.warning_text
        self._warning.setText(warning or "")
        self._warning.setVisible(warning is not None)

        with probe.section("戦闘ログ表"):
            self._fill_table(state)

        if state.battles_recorded:
            # ★中心指標なので秒のままにしない。31285.7秒 では実感できない。
            self._summary.setText(
                f"記録した戦闘 {state.battles_recorded} 件 ／ "
                f"平均 ×{state.average_speed:.2f} ／ "
                f"削減できた待ち時間 {duration(state.saved_seconds_total)}"
            )
        else:
            self._summary.setText("まだ戦闘の記録がありません。")

    @staticmethod
    def _apply_toggle_tip(button, base: str, name: str, on: bool) -> None:
        """入切のボタンの状態を**ツールチップの1行目**に書く（2026-08-09）。

        ⚠⚠ アイコン1文字にすると、押し込みの見た目だけが手がかりになります。
          ★それだけでは弱いので、必ず言葉でも伝えます
            （「押した結果は必ず画面に出す」と同じ考え方）。
        """
        button.setToolTip(f"{name}: {'入' if on else '切'}\n{base}")

    def _log_ai_decision(self, game) -> None:
        """AI の選択と理由を System Log へ流す（2026-08-09 / 依頼者の指示）。

        ⚠⚠ **変わったときだけ**書きます。0.5秒ごとに書くと、同じ行が
          ログを埋めて他が読めなくなります。
        ⚠ 戦闘していないときは書きません（選択が無いので）。
        """
        if not getattr(game, "in_battle", False):
            self._last_ai_line = None
            return
        parts = []
        for actor in (getattr(game, "party", None) or ()):
            choice = getattr(actor, "ai_choice", None)
            if not choice:
                continue
            reason = getattr(actor, "ai_reason", None)
            name = getattr(actor, "display_name", None) or getattr(
                actor, "name", "?")
            parts.append(f"{name}:{choice}" + (f"（{reason}）" if reason else ""))
        if not parts:
            return
        line = " / ".join(parts)
        if line == getattr(self, "_last_ai_line", None):
            return
        self._last_ai_line = line
        get_logger("ai").debug("判断: %s", line)

    def _log_new_battles(self, rows) -> None:
        """記録された戦闘を1件1行で System Log へ流す（2026-08-09）。

            > 戦闘ログは戦闘前、後（楽なタイミングで）Systemログに出力して
            > 画面からは削除

        ★「楽なタイミング」＝**記録が増えたとき**にしました。戦闘の入口や
          出口を別に捕まえるより確実で、⚠ 取りこぼしがありません
          （倍速だと戦闘が一瞬で終わり、入口の検出が飛ぶことがあります）。

        ⚠ 起動直後に既存の記録を全部流さないこと。★初回は「いま何件あるか」
          を覚えるだけにします（過去50件がログに溢れると読めません）。
        """
        seen = getattr(self, "_logged_battles", None)
        first_time = seen is None
        if first_time:
            seen = self._logged_battles = set()
        log = get_logger("battle")
        for row in rows:
            key = getattr(row, "battle_id", None)
            if key is None or key in seen:
                continue
            seen.add(key)
            if first_time:
                continue        # ★起動時にあった分は流さない（覚えるだけ）
            marks = []
            if row.is_first_encounter:
                marks.append("初遭遇")
            if row.is_boss:
                marks.append("ボス")
            parts = [row.monsters or "―"]
            if marks:
                parts.append("・".join(marks))
            if row.speed_applied:
                parts.append(f"×{row.speed_applied:.2f}")
            if row.duration_seconds is not None:
                parts.append(compact_duration(row.duration_seconds))
            if row.saved_seconds:
                parts.append(f"短縮 {compact_duration(row.saved_seconds)}")
            if row.drops and row.drops not in ("-", ""):
                parts.append(f"ドロップ {row.drops}")
            log.info("戦闘: %s", " / ".join(parts))
            # ★★ ターンごとの出来事は DEBUG（2026-08-09 / 依頼者の指示）★★
            #
            #   > 画面にはださないが、ログボタンで見るとあとからわかる。
            #   > 当然ログDBには吐いてる。そういう作りにしたい。
            #
            #   ⚠ 1戦闘で数十行になるので画面（INFO）には出しません。
            #   ★これが「選んだ戦闘の出来事」の代わりです。表を消したぶん、
            #     AI の判断を後から追う道をログに残します。
            for line in self._battle_event_lines(row):
                log.debug("  %s", line)

    def _battle_event_lines(self, row) -> list:
        """1戦闘ぶんの出来事を行の並びにする（2026-08-09）。

        ⚠ 記録が無い戦闘もあります（この機能より前のもの）。
          ★そのときは**無いと書きます**。空にすると壊れて見えます。
        """
        try:
            events = self.vm.battle_events(row.battle_id)
        except Exception:                               # noqa: BLE001
            return ["（出来事を読めませんでした）"]
        if not events:
            return ["（この戦闘の出来事は記録されていません）"]
        out = []
        for e in events:
            kind = e["kind"]
            if kind == "turn":
                out.append(f"--- ターン{e['turn_no']} ---")
            elif kind == "action":
                out.append(
                    f"  [AI] {e['actor']} → {e['target']}: {e['action_name']}"
                    + (f"（{e['reason']}）" if e["reason"] else ""))
            elif kind == "enemy_defeated":
                out.append(f"  {e['actor']} を倒した")
            else:
                label = {"party_hp": "HP", "party_mp": "MP",
                         "enemy_hp": "敵HP"}.get(kind, kind)
                out.append(f"  {e['actor']} {label} "
                           f"{e['value_before']} → {e['value_after']}")
        return out

    def _fill_table(self, state: UiState) -> None:
        # ★★ **中身が変わっていなければ作り直さない**（2026-07-31 の指示書 §10.4）★★
        #   ⚠ 表を毎回全部作り直すと、`QTableWidgetItem` を 50×8 = 400 個
        #     捨てて作り直すことになる（実測 1.1ms を毎回）。
        #   ★戦闘の一覧が変わるのは**戦闘が記録されたとき**だけ。
        #     ViewModel 側が同じリスト（同一オブジェクト）を返すので、
        #     `is` で比べれば足りる（中身の比較すら要らない）。
        if state.rows is getattr(self, "_rows_cache", None):
            return
        # ★選択中の戦闘を覚えておく（更新のたびに選択が外れないように）
        self._rows_cache = state.rows
        # ★★ 2026-08-09: 戦闘ログは **System Log へ書き出します**（依頼者の指示）
        #   ⚠ 表そのものは画面から消しました。★記録（DB）は残します。
        #     統計（「記録した戦闘 N 件 / 平均 ×… / 削減できた待ち時間」）は
        #     こちらとは別に DB から出しているので影響ありません。
        self._log_new_battles(state.rows)
        table = getattr(self, "_table", None)
        if table is None:
            return
        self._table.setRowCount(len(state.rows))
        for r, row in enumerate(state.rows):
            marks = []
            if row.is_first_encounter:
                marks.append("初")
            if row.is_boss:
                marks.append("ボス")
            values = [
                # 稼働中に見るログなので日付は省き、時刻だけ出す
                row.started_at.replace("T", " ")[11:19],
                row.monsters,
                row.drops,
                "・".join(marks) or "-",
                f"×{row.speed_applied:.2f}" if row.speed_applied else "-",
                # ★1行あたりは短い形（列幅を食うとモンスター名が押し出される）
                compact_duration(row.duration_seconds)
                if row.duration_seconds is not None else "-",
                ("-" + compact_duration(row.saved_seconds))
                if row.saved_seconds else "-",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                # ★★ 省略された文字は**ツールチップで全文**（仕様書 7.5）★★
                #   ⚠ 「モンスター」と「ドロップ候補」は伸縮列なので、
                #     幅が足りないと … で切れる。切れたまま読めないと、
                #     どの敵と戦ったのか分からなくなる。
                if _LOG_COLUMNS[c] in _STRETCH_COLUMNS and value not in ("", "-"):
                    item.setToolTip(value)
                self._table.setItem(r, c, item)
