"""下段の窓 ― ログ（RX3-0019 / 2026-08-29）。

依頼者 2026-08-29:

    戦闘、モンスター のラベルはいらない。戦闘中のラベルもいらない
    （右上の画面でやる）※2 行節約
    ログ選択タブはいらない → 1 行節約
    全てのログを色分けさせる感じで表示する

## ★★ 左に札・右にログ 1 本（RX3-0276 / 2026-09-15 依頼者「案１でいこう」）

依頼者 2026-09-15:

    今のログ画面のモンスター表示は、空きが目立つのでもう少し整理する案を作ってほしい。
    ログ出力がいま横２列になっているが、一つの出力に集約したい
    ※本稼働ではデバッグログ出力が減るので、問題ないと思う
    詳しいログ表示のON/OFFは管理画面に逃がして。これで1行とるのもったいない。

```text
┌─ ログ — RetroUX DQ3 ─────────────────────────────────────────────────────┐
│ ┌札────────┐┌札────────┐┌札────────┐ │ AI: turn=4 均衡 …（1 行固定）       │
│ │[絵] 名前   ││[絵] 名前   ││[絵] 名前   │ │ 07:48 [呪文の結果] 完了 …           │
│ │     HP  速 ││     HP  速 ││     HP  速 │ │ 07:49 [自動戦闘] 完了：勝利 …       │
│ │ 耐性 …     ││ 耐性 …     ││ 耐性 …     │ │   [戦闘] AUTO_V0 turn=1 …（灰）    │
│ │ 特技 …     ││ 特技 …     ││ 特技 …     │ │   … ★窓の高さいっぱい               │
│ └──────────┘└──────────┘└──────────┘ │                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

⚠⚠ 下段の窓は**高さが足りない**（`layout.BOTTOM_H` = 226）。★上下に割ると帯 120 ＋ ログ約 88（4 行）だった。
→ ★左右に分け、札もログも窓の高さいっぱいを使う（★ログは約 2 倍の行）。⚠ 仕切りは人がつまんで変えられる。
★札は小さく固定（272 × 100）で、帯の高さに入るだけ段を積む（★2 段 × 2 列 = 敵 4 群）。帯の既定の幅は 2 列ぶん。

## ★ログは 1 本（⚠ RX3-0111 の「行動履歴と詳しいログを分ける」を依頼者の判断で改めた）

```text
行動履歴の行   時刻 ＋［種類］＋ 結果          ★濃く（完了 緑 / 一部 橙 / 失敗 赤）
詳しいログの行 ［出どころ］＋ 本文              ★灰で小さめ（⚠⚠ ⚠ ★ の色分けはそのまま）
```

★届いた順に 1 本へ。★「詳しいログ」の入り切りは**管理画面**（`admin_window` / ⚠ ログ画面に行を取らない）。
  ⚠ 切っている間も詳しいログは覚えておく（★入れ直すと、覚えた分から描き直す）。

## ⚠⚠ ログは「画面が組み立てる」のではなく「Lua が書いたものを読む」

★DQ2 の `battle_review` にある註釈と同じ問題があります:

    ⚠ 倍速だと、戦闘まるごと 1 回が 0.2 秒に収まって**画面が見逃す**。

★Lua は起きたことをその場でファイルへ書いています（`dq3/ui/log_tail.py`）。

## ★色分けの決め方

**行動履歴** … `ActionSummary.status`（★完了 / 中断 / 停止）で決めます。

**詳しいログ** … 行の**印**で決めます（⚠ ログの書き方そのものが印を持っている）。

```text
⚠⚠ を含む … 赤   （★見逃してはいけない）
⚠  を含む … 橙
★  を含む … 緑
それ以外   … 灰
```

⚠ 出どころ（戦闘 / 満タン / 本体）は**行頭の札**で分けます。

## ⚠⚠ 戦闘の開始・終了で大きさを変えない（指示書 §2）

★モンスターの帯は、戦闘外でも**隠さず、中身を空に**します。
⚠ 出し入れすると窓が動きます。
"""

from __future__ import annotations

import collections
import html
import pathlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QLabel, QSizePolicy, QSplitter, QTextBrowser, QVBoxLayout,
                               QWidget)

from dq3 import action_log as _AL
from dq3.ui import theme as _T
from retroux.ui.battle_monsters import BattleMonsterStrip  # noqa: F401 ★帯の枠組み（`Dq3MonsterStrip` の基底）

from .log_tail import LogTail

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROBE = paths.lazy_work("dq3-probe")

#: ★窓の大きさ（**論理**）。⚠ 実際の高さは `layout` が決める
WINDOW_W, WINDOW_H = 1920, 210


#: ★★ モンスターの帯の高さ。⚠ **帯そのものが決めます**。
#:
#:   ## ⚠⚠ 2026-09-01: ここが札を潰していました
#:
#:     ★もとは DQ2 と同じ `60`〜`88` を直書きしていました。
#:     ⚠ 帯を 104 にしたのに **88 で頭打ち**になり、
#:       依頼者の画面で性能と名前が切れていました。
#:     → ★数字を 2 か所に置かず、`Dq3MonsterStrip` から取ります。
def _strip_height() -> int:
    from dq3.ui.monster_panel import STRIP_HEIGHT

    return STRIP_HEIGHT


def _strip_width_min() -> int:
    """★帯の幅の下限 = 札 1 列 ＋ 余白（RX3-0276 / ⚠ 札を切らない）。⚠ 数字は帯の側から取る。"""
    from dq3.ui.monster_panel import STRIP_SIDE, card_size

    return card_size()[0] + STRIP_SIDE


def _strip_width_default() -> int:
    """★帯の既定の幅 = 札 `DEFAULT_COLUMNS` 列（★2 段 × 2 列 = DQ3 の敵 4 群が全部見える / RX3-0276）。"""
    from dq3.ui.monster_panel import DEFAULT_COLUMNS, STRIP_SIDE, card_size

    return DEFAULT_COLUMNS * card_size()[0] + (DEFAULT_COLUMNS - 1) * 6 + STRIP_SIDE


#: ★ログの最低（高さ）。⚠ ここを削ると 0 行になる
LOG_MIN = 72

#: ★ログの幅の最低（RX3-0276）。⚠ ここより狭いと 1 行が短すぎて読めない
LOG_W_MIN = 320

#: ★仕切りの厚み（⚠ つまめる幅。★細すぎると掴めない）
HANDLE_H = 6

#: ★窓の内側の余白（⚠ `root.setContentsMargins` と揃える）
MARGIN_H = 4 + 6
MARGIN_W = 6 + 6

#: ★ログに残す行数（⚠ 高速 AUTO でも後から追えるように / 指示書 §14）
MAX_LOG_LINES = 5000

#: ⚠ 戦闘中に敵が来ないとき、何回まで待つか（★0.5 秒に 1 回なので約 3 秒）
EMPTY_PATIENCE = 6

#: ★★ 読むログ（⚠ タブは作らない。依頼者 2026-08-29「タブはいらない」）
#:   `(札, 場所, 札の色)`
SOURCES = (
    ("戦闘", PROBE / "auto_v0.log", "#2b5fa8"),
    ("満タン", PROBE / "mantan_v0.log", "#6a3fa0"),
    ("本体", PROBE / "dev.log", "#6b7280"),
)

#: ★★ 白地の配色（RX3-0111 / 2026-09-07 依頼者「派手にしすぎない」）。
#:   ⚠⚠ 色は `dq3/ui/theme.py` が正本です（★同じ窓にモンスターの帯が並ぶため、
#:     2 か所に書きません / RX3-0112）。
PAPER = _T.PAPER           #: ★ごく薄いグレー（⚠ 真っ白は目が疲れる）
BORDER = _T.BORDER
INK = _T.INK               #: ★通常の Action

#: ★行の印 → 色（⚠ 印は行の**どこにあっても**拾う）
#:   ⚠ 2026-09-07: 黒地の明るい色は白地で**読めません**（★彩度を落として濃く）
LEVEL_COLORS = (
    ("⚠⚠", "#b3261e"),
    ("⚠", "#8a5a00"),
    ("★", "#1f6f3f"),
)
PLAIN_COLOR = _T.MUTED

#: ★行動履歴の色（⚠ `ActionSummary.status` で決める）
STATUS_COLORS = {
    "SUCCESS": "#1f6f3f",
    "PARTIAL": "#8a5a00",
    "FAILED": "#b3261e",
    "CANCELLED": "#5b6270",
}

#: ★ログの行の種類（RX3-0276）。★詳しいログだけを入り切りする
ACTION, DETAIL = "action", "detail"

#: ★字の大きさ（px / 論理）。★行動履歴は読みやすく、詳しいログは小さめ（RX3-0276）
#:   ⚠ `font-size:small` は Qt の文書では効かなかった（★撮って気づいた）→ px で書く
ACTION_PX, DETAIL_PX = 13, 11
#: ★詳しいログの行の見た目（★灰で小さめ / 字の幅がそろう字）
DETAIL_STYLE = "font-family:'Consolas','MS Gothic',monospace; font-size:%dpx;" % DETAIL_PX

#: ★「詳しいログ」の入り切りの置き場（`work/dq3-ui-settings.json` / 管理画面が書く）
SETTING_SECTION, SETTING_KEY = "log", "show_detail"


#: ★戦闘 AI の理由の行（`AI turn=…` / `AI p1 役割=…`）の色（RX3-0126）
AI_COLOR = "#2b4c9b"
AI_PREFIX = "AI "


def colour_of(line: str) -> str:
    """★その行の色。⚠ **強いほうから**見る（`⚠⚠` は `⚠` を含むため）。"""
    for mark, colour in LEVEL_COLORS:
        if mark in line:
            return colour
    if line.startswith(AI_PREFIX):
        return AI_COLOR
    return PLAIN_COLOR


#: ★設定が無いときの「詳しいログ」（★RX3-0482 / 依頼者 2026-10-02: 新規利用は**オフ**）
#:   ⚠ 保存があれば保存を優先（★入れた人・切った人はそのまま）
SHOW_DETAIL_DEFAULT = False


def show_detail_of(settings) -> bool:
    """★「詳しいログ」を出すか（⚠ 設定が無ければ `SHOW_DETAIL_DEFAULT` = 出さない）。"""
    if settings is None:
        return SHOW_DETAIL_DEFAULT
    try:
        return bool(settings.get(SETTING_SECTION, SETTING_KEY, SHOW_DETAIL_DEFAULT))
    except Exception:                                    # noqa: BLE001 ★読めなければ既定
        return SHOW_DETAIL_DEFAULT


class Dq3BattleWindow(QWidget):
    """下段に置く「ログ」の窓。"""

    def __init__(self, view_model, parent=None, *, action_log=None, settings=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        # ★窓の名前（RX3-0306 / 依頼者「下：ログ」）
        self.setWindowTitle("ログ")
        self.setWindowFlag(Qt.WindowType.Window, True)
        # ⚠⚠ **Qt の論理座標**で置く（★物理を渡すと 150% の画面で 1.5 倍になる）
        from . import layout as layout_mod
        self.setGeometry(
            *layout_mod.default_sizes(layout_mod.qt_area()).bottom.as_tuple())
        # ⚠ フォーカスを奪わない（★奪うとゲームを操作できなくなる / DQ2 の知見）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 6)
        root.setSpacing(2)

        # --- ★★ 帯とログの仕切り（RX3-0037 / ★RX3-0276 で左右へ）-----------
        #   依頼者 2026-09-01:「モンスター画面はちゃんと**デフォルトでなるべく表示**させたい」
        #   → ★配分は `layout.bottom_split` が決め、⚠ **人がつまんで変えられる**。
        #   ⚠⚠ `setCollapsible(False)`: ★どちらも 0 にはさせません
        #     （ログが消える／帯が消える、のどちらも「黙って減らす」ため）。
        #   ★RX3-0276: 上下 → 左右（★下段の窓は高さが足りない / 幅はある）。
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(HANDLE_H)
        root.addWidget(self.split, 1)

        # --- ★モンスターの帯（⚠ 見出しは付けない。依頼者 2026-08-29）------
        #   ⚠ 戦闘外は**隠さず、空にする**（★出し入れで窓が動かないように）
        #   ⚠⚠ `retroux/` は変えません（`RX3-0011`）。★DQ3 側で継承します。
        from dq3.ui.monster_panel import Dq3MonsterStrip

        self.monsters = Dq3MonsterStrip()
        # ⚠ 高さは帯が決めます（★ここで上書きしない / 上の註）。★幅は札 1 枚を切らない
        self.monsters.setMinimumWidth(_strip_width_min())
        self.split.addWidget(self.monsters)

        # --- ★★ ログは 1 本（RX3-0276）。⚠ タブは作らない（依頼者 2026-08-29）------
        self.log = QTextBrowser()
        self.log.setOpenExternalLinks(False)
        self.log.document().setMaximumBlockCount(MAX_LOG_LINES)
        self.log.setStyleSheet(
            "QTextBrowser { background: %s; border: 1px solid %s; color: %s;"
            " font-family: 'Meiryo','Yu Gothic UI','MS Gothic',sans-serif; font-size: %dpx; }"
            % (PAPER, BORDER, INK, ACTION_PX))
        self.log.setToolTip(
            "★RetroUX が代わりに実行したこと（行動履歴）と、詳しいログ（灰）を届いた順に出します" + chr(10)
            + "★詳しいログの入り切りは管理画面の「状態」")
        # ★戦闘 AI の「いまの戦況」を 1 行だけ上に固定する（RX3-0126）。
        #   ⚠ 行数は増やさない（★DQ2 の「戦況」の行と同じ狙い）。中身は詳しいログの `AI turn=` 行。
        log_box = QWidget()
        log_col = QVBoxLayout(log_box)
        log_col.setContentsMargins(0, 0, 0, 0)
        log_col.setSpacing(2)
        self.ai_line = QLabel("AI: （まだ判断していません）")
        self.ai_line.setStyleSheet("color: %s;" % AI_COLOR)
        self.ai_line.setToolTip("★戦闘 AI v1 が最後に見立てた戦況（⚠ 全文はマウスで）")
        self.ai_line.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        log_col.addWidget(self.ai_line)
        log_col.addWidget(self.log, stretch=1)
        self.log.setMinimumHeight(0)
        log_box.setMinimumHeight(LOG_MIN)
        log_box.setMinimumWidth(LOG_W_MIN)
        self.split.addWidget(log_box)

        #: ★届いた行（`(種類, html)`）。⚠ 詳しいログを切っている間も覚える（★入れ直したら描き直す）
        self._rows: collections.deque = collections.deque(maxlen=MAX_LOG_LINES)
        #: ★「詳しいログ」を出すか（★管理画面が `set_show_detail` で変える）
        self.show_detail = show_detail_of(settings)

        #: ⚠ 既定の配分は**1 度だけ**当てる（★人が変えたぶんを戻さない）
        self._split_applied = False
        self.apply_default_split()

        self._tails = [(tag, LogTail(path), colour)
                       for tag, path, colour in SOURCES]
        #: ★行動履歴は「引きに来る」（⚠ subscribe だと窓を閉じたときに困る）
        self.action_log = action_log if action_log is not None else _AL.shared()
        self._seen_actions = len(self.action_log.rows)

    # --- ★配分 ----------------------------------------------------------

    def split_sizes(self, total_w: int | None = None) -> tuple[int, int]:
        """★`(帯, ログ)` の既定の**幅**（RX3-0276）。

        ★帯は札 2 列（★2 段 × 2 列 = DQ3 の敵 4 群が全部見える）、ログは残り全部。
        ⚠ 帯は札 1 列、ログは `LOG_W_MIN` を割らない（★足りなければ帯を先に満たす / `layout.bottom_split` と同じ考え）。
        """
        if total_w is None:
            total_w = self.width()
        inner = max(0, int(total_w) - MARGIN_W - HANDLE_H)
        low = _strip_width_min()
        if inner <= low + LOG_W_MIN:
            strip = min(low, inner)
        else:
            strip = max(low, min(_strip_width_default(), inner - LOG_W_MIN))
        return int(strip), int(inner - strip)

    def apply_default_split(self) -> None:
        """⚠ 既定の配分を当てる（★1 度だけ。人が変えたら二度と触らない）。"""
        if self._split_applied:
            return
        self._split_applied = True
        self.split.setSizes(list(self.split_sizes()))

    # --- ★ログ ----------------------------------------------------------

    def _visible(self, kind: str) -> bool:
        return kind != DETAIL or self.show_detail

    def _append_rows(self, rows) -> int:
        """★届いた行を覚え、見せる行だけ足す（⚠ 人が上へスクロールして読んでいたら飛ばさない）。"""
        if not rows:
            return 0
        self._rows.extend(rows)
        shown = [text for kind, text in rows if self._visible(kind)]
        if not shown:
            return 0
        bar = self.log.verticalScrollBar()
        stick = bar.value() >= bar.maximum() - 4
        for text in shown:
            self.log.append(text)
        if stick:
            bar.setValue(bar.maximum())
        return len(shown)

    def set_show_detail(self, on: bool) -> None:
        """★「詳しいログ」の入り切り（★管理画面から / RX3-0276）。⚠ 覚えた行から描き直す。"""
        on = bool(on)
        if on == self.show_detail:
            return
        self.show_detail = on
        self.log.clear()
        for kind, text in self._rows:
            if self._visible(kind):
                self.log.append(text)
        bar = self.log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _pump_logs(self) -> int:
        """★詳しいログの増えたぶん（⚠ 全部読み直さない）。★AI の 1 行は入り切りに関係なく更新する。"""
        rows: list[tuple[str, str]] = []
        for tag, tail, tag_colour in self._tails:
            for line in tail.read_new():
                if line.startswith(AI_PREFIX + "turn="):
                    self.ai_line.setText("AI: " + line[len(AI_PREFIX):])
                    self.ai_line.setToolTip(line)
                rows.append((DETAIL,
                             '<span style="%s"><span style="color:%s">[%s]</span> '
                             '<span style="color:%s">%s</span></span>'
                             % (DETAIL_STYLE, tag_colour, html.escape(tag), colour_of(line),
                                html.escape(line))))
        return self._append_rows(rows)

    def _pump_actions(self) -> int:
        """★行動履歴の増えたぶん（⚠ 1 回ぶんに 1 行 / 濃く）。"""
        got, self._seen_actions = self.action_log.since(self._seen_actions)
        rows = []
        for row in got:
            colour = STATUS_COLORS.get(row.status, INK)
            rows.append((ACTION,
                         '<span style="color:%s">%s</span> '
                         '<span style="color:%s">%s</span>'
                         % (PLAIN_COLOR, html.escape(row.stamped().split(" ", 1)[0]),
                            colour, html.escape(row.line()))))
        return self._append_rows(rows)

    def log_rows(self, kind: str | None = None) -> list[str]:
        """★覚えている行の文字（★検査と証跡用 / ⚠ html は外す）。"""
        from PySide6.QtGui import QTextDocumentFragment

        return [QTextDocumentFragment.fromHtml(text).toPlainText()
                for k, text in self._rows if kind is None or k == kind]

    def refresh(self) -> None:
        # ★届いた順（★Lua の詳しいログ → それをまとめた行動履歴）
        self._pump_logs()
        self._pump_actions()
        # ⚠⚠ 大きさは変えない。★中身だけ入れ替える（指示書 §2）
        #
        # ★★ 戦闘が終わっても、直近の敵を出したままにする（RX3-0025）。
        #   依頼者 2026-08-30:「戦闘が終わると消えちゃうので、
        #   戦闘が終わっても直近のモンスター情報を表示させたい」
        #   ⚠⚠ ただし「終わったもの」を「いま戦っている」と見せない。
        #   ★覚えるのは `battle_view` の中でやる（⚠ ここで呼び忘れない）
        groups, fighting = self.vm.battle_view()
        if not groups:
            if not fighting:
                self.monsters.set_cards([])
                self.monsters.setToolTip("")
            return
        self._show_enemies(groups, fighting)

    def _show_enemies(self, groups, fighting: bool) -> None:
        """★敵の札を並べる（⚠ **種ごとに 1 枚** / 指示書 §15・§20）。

        ## ⚠⚠ 匹数は出しません

          > モンスターの匹数は不要。表示単位は個体ではなく、モンスター種。

          ★同じ `monster_id` が 2 群に分かれていても **1 枚**にまとめます。

        ## ★性能は ROM の値をそのまま出します（指示書 §2.2）

          ⚠ `RX3-0021` の「倒した敵だけ中身を出す」とは**別の判断**です。
        """
        from dq3.ui.monster_panel import Dq3MonsterCard

        cards, seen = [], set()
        for group in groups:
            key = group.get("id")
            if key is None or int(key) in seen:
                continue                  # ⚠ 同じ種は 1 枚だけ
            seen.add(int(key))
            name = group.get("name") or ("？（敵 %s）" % key)
            # ★2026-09-02 依頼者: 札の名前に「（直近）」は付けない（★帯の見出し / ヒントで分かる）
            extras = self._extras_of(int(key))
            cards.append(Dq3MonsterCard(monster_id=int(key), name=name,
                                        art=self._art_of(int(key)),
                                        stats=self._stats_of(int(key)),
                                        resist=extras["resist"], special=extras["special"],
                                        legend=extras["legend"], tip=extras.get("tip", "")))
        self.monsters.set_cards(cards)
        # ★ヒント（★「いま戦っている敵 / 直近の戦闘の敵」の見出しと中身）。
        #   ⚠⚠ 2026-09-02: この 1 行が `_stats_of` の `return` の**後ろ**に置かれていて、一度も実行されていなかった
        self.monsters.setToolTip(self._enemy_tip(groups, fighting))

    def _art_of(self, monster_id: int):
        """★絵（⚠ 置き場から引くだけ。作り方は持たない / 指示書 §22）。"""
        from dq3.knowledge import monster_art

        return monster_art.path_of(monster_id)

    def _extras_of(self, monster_id: int) -> dict:
        """★耐性・特技（RX3-0060）。★DQ2 の札と同じく、会っている敵はそのまま出す（⚠ 図鑑の No-Spoiler とは別）。"""
        try:
            from dq3.knowledge import monster_book as mb

            return mb.card_extras(mb._detail_of(monster_id))
        except Exception:                                # noqa: BLE001 ★ROM が無い / 読めない
            return {"resist": "", "special": "", "legend": "", "tip": ""}

    def _stats_of(self, monster_id: int) -> tuple:
        """★ROM の値をそのまま（⚠ 丸めない・隠さない / 指示書 §2.2）。"""
        from dq3.knowledge.enemies_seen import master_of

        got = master_of(monster_id)
        return tuple(got) if got else ()

    def _enemy_tip(self, groups, fighting: bool) -> str:
        """★ヒントに中身を出す。⚠⚠ **倒した敵だけ**（No-Spoiler）。"""
        from dq3.knowledge.enemies_seen import details_of

        rows = ["いま戦っている敵" if fighting else "★直近の戦闘の敵"]
        for group in groups:
            key = group.get("id")
            name = group.get("name") or ("敵 %s" % key)
            rows.append("")
            rows.append("%s ー %d ひき" % (name, group.get("n") or 0))
            if not group.get("known"):
                # ⚠ 知らないことを、知らないと出す
                rows.append("  ⚠ まだ倒していないので、中身は出しません")
                continue
            got = details_of(key)
            if not got:
                rows.append("  ⚠ ROM から引けませんでした")
                continue
            rows.append("  " + " / ".join(
                "%s %s" % (label, value) for label, value in got
                if value is not None))
        return chr(10).join(rows)
