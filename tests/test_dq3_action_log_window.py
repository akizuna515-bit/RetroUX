"""ログの窓（RX3-0111 / 2026-09-07 → ★RX3-0276 / 2026-09-15 で「左に札・右にログ 1 本」）。

依頼者 2026-09-07:

    現在の黒背景ログ画面は白背景へ変更する。
    今回の共通 Summary Log を、将来的にこの領域の主役にする。
    デバッグログの垂れ流しにはしない。
    派手にしすぎない。

依頼者 2026-09-15（RX3-0276）:

    ログ出力がいま横２列になっているが、一つの出力に集約したい
    案１でいこう。詳しいログ表示のON/OFFは管理画面に逃がして。これで1行とるのもったいない。

★行動履歴と詳しいログを**届いた順に 1 本**へ（⚠ RX3-0111 の「分ける」を依頼者の判断で改めた）。
★詳しいログは灰で小さめ・入り切りは管理画面（⚠ ログ画面に行を取らない）。
★下段の窓は高さが足りない（226）→ ★札とログを**左右**に分け、どちらも高さいっぱいを使う。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3 import action_log as AL                   # noqa: E402
from dq3.ui import battle_window as BW             # noqa: E402


class _VM:
    def battle_view(self):
        return [], False


class _Tail:
    """★Lua のログの代わり（⚠ 本物の work/dq3-probe は読まない）。"""

    def __init__(self, lines):
        self.lines = list(lines)

    def read_new(self):
        got, self.lines = self.lines, []
        return got


class _Settings:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, section, key, default=None):
        return self.data.get(section, {}).get(key, default)


def _win(settings=None, log=None):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    log = log if log is not None else AL.ActionLog()
    win = BW.Dq3BattleWindow(_VM(), action_log=log, settings=settings)
    win._tails = []                                 # ⚠ 本物のログは読まない（★必要な検査だけ代わりを置く）
    return win, log


@pytest.fixture
def window():
    return _win()


# ----------------------------------------------------------------------
# ★配色（⚠ 「白背景へ」）
# ----------------------------------------------------------------------
def _luma(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def test_背景は白でインクは濃い(window):
    """⚠ 「黒背景を白へ」。★色名ではなく**明るさ**で見る（配色を変えても壊れない）。"""
    win, _ = window
    assert _luma(BW.PAPER) > 0.9, BW.PAPER
    assert _luma(BW.INK) < 0.3, BW.INK
    assert BW.PAPER in win.log.styleSheet(), win.log.styleSheet()


def test_白地で読める濃さの色だけ使う():
    """⚠⚠ 黒地の明るい色（`#8bd450` など）は白地では**読めません**。"""
    colours = [c for _m, c in BW.LEVEL_COLORS] + list(BW.STATUS_COLORS.values()) \
        + [BW.PLAIN_COLOR, BW.INK]
    for c in colours:
        assert _luma(c) < 0.62, "⚠ 白地で薄すぎる: %s" % c


def test_終わり方ごとに色が違う():
    """★完了 / 部分 / 中断 / 停止 が見分けられること（⚠ 派手にはしない）。"""
    got = set(BW.STATUS_COLORS.values())
    assert len(got) == 4, BW.STATUS_COLORS
    assert set(BW.STATUS_COLORS) == set(AL.STATUSES)


# ----------------------------------------------------------------------
# ★★ 左に札・右にログ 1 本（RX3-0276）
# ----------------------------------------------------------------------
def test_札とログを左右に並べログは1本(window):
    """★依頼者「一つの出力に集約したい」「案１」。⚠ タブにもしない（`test_ログはタブを作らず色分けする`）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTextBrowser

    win, _ = window
    assert win.split.orientation() == Qt.Orientation.Horizontal, "⚠⚠ 上下のまま（★高さが足りない）"
    assert win.split.count() == 2 and win.split.widget(0) is win.monsters
    assert len(win.findChildren(QTextBrowser)) == 1, "⚠⚠ ログが 2 本ある"
    # ⚠ `actions` は QWidget がもともと持つ関数の名前（★2 列目の入れ物ではないことを型で見る）
    assert not hasattr(win, "logs_row") and not isinstance(getattr(win, "actions", None), QTextBrowser), (
        "⚠ 2 列の入れ物が残っている")


def test_行動履歴と詳しいログが届いた順に1本へ出る():
    # ★詳しいログを入れた人の画面（⚠ 既定はオフ / RX3-0482）
    win, log = _win(settings=_Settings({BW.SETTING_SECTION: {BW.SETTING_KEY: True}}))
    win._tails = [("戦闘", _Tail(["AUTO_V0 turn=1 slot=p1 action=attack", "★勝った"]), "#2b5fa8")]
    log.begin("battle").completed("勝利 / 1ターン")
    win.refresh()
    lines = win.log.toPlainText().split(chr(10))
    assert lines[0] == "[戦闘] AUTO_V0 turn=1 slot=p1 action=attack", lines
    assert lines[1] == "[戦闘] ★勝った"
    assert lines[2].endswith("[自動戦闘] 完了：勝利 / 1ターン") and lines[2][2] == ":", lines
    assert win.log_rows(BW.ACTION) == [lines[2]] and len(win.log_rows(BW.DETAIL)) == 2


def test_詳しいログは灰で小さく行動履歴は濃い():
    """★行動履歴が主役（RX3-0111）/ 詳しいログは灰で小さめ（RX3-0276）。"""
    win, log = _win()
    win._tails = [("本体", _Tail(["なにか"]), "#6b7280")]
    log.begin("move").completed("到着")
    win.refresh()
    kinds = {k: t for k, t in win._rows}
    assert BW.DETAIL_PX < BW.ACTION_PX
    assert "font-size:%dpx" % BW.DETAIL_PX in kinds[BW.DETAIL] and BW.PLAIN_COLOR in kinds[BW.DETAIL]
    assert BW.STATUS_COLORS["SUCCESS"] in kinds[BW.ACTION] and "font-size" not in kinds[BW.ACTION]
    assert "font-size: %dpx" % BW.ACTION_PX in win.log.styleSheet(), "★行動履歴の字の大きさは窓の既定"


def test_詳しいログを切ると行動履歴だけで入れ直すと戻る():
    """★入り切りは管理画面（`set_show_detail`）。⚠ 切っている間の分も覚えていて、入れ直すと出る。"""
    win, log = _win()
    win._tails = [("戦闘", _Tail(["前の詳しいログ"]), "#2b5fa8")]
    log.begin("move").completed("前の行動")
    win.refresh()
    win.set_show_detail(False)
    assert "前の詳しいログ" not in win.log.toPlainText() and "前の行動" in win.log.toPlainText()
    win._tails[0][1].lines = ["切っている間の詳しいログ"]
    log.begin("move").completed("切っている間の行動")
    win.refresh()
    text = win.log.toPlainText()
    assert "切っている間の行動" in text and "切っている間の詳しいログ" not in text
    win.set_show_detail(True)
    text = win.log.toPlainText()
    assert text.index("前の詳しいログ") < text.index("前の行動") < text.index("切っている間の詳しいログ"), text


def test_設定で切っていれば最初から出さない():
    win, log = _win(settings=_Settings({BW.SETTING_SECTION: {BW.SETTING_KEY: False}}))
    assert win.show_detail is False
    win._tails = [("戦闘", _Tail(["詳しい"]), "#2b5fa8")]
    log.begin("move").completed("行動")
    win.refresh()
    assert win.log.toPlainText().endswith("[自動移動] 完了：行動") and "詳しい" not in win.log.toPlainText()


def test_設定が無ければ詳しいログを出さない(window):
    """★RX3-0482（2026-10-02 依頼者）: 新規利用の既定は**オフ**。⚠ 保存があれば保存を優先。"""
    win, _ = window
    assert win.show_detail is False
    assert BW.show_detail_of(None) is False and BW.show_detail_of(_Settings()) is False
    assert BW.show_detail_of(_Settings({BW.SETTING_SECTION: {BW.SETTING_KEY: True}})) is True, \
        "⚠⚠ 入れた人の設定を既定で上書きした"


def test_切っていてもAIの戦況の1行は変わる():
    win, _ = _win(settings=_Settings({BW.SETTING_SECTION: {BW.SETTING_KEY: False}}))
    win._tails = [("戦闘", _Tail(["AI turn=3 戦況=均衡"]), "#2b5fa8")]
    win.refresh()
    assert win.ai_line.text() == "AI: turn=3 戦況=均衡"


def test_同じ行を二度出さない(window):
    win, log = window
    log.begin("move").completed("到着")
    win.refresh()
    win.refresh()
    assert win.log.toPlainText().count("到着") == 1


def test_時刻が頭に付く(window):
    win, log = window
    log.begin("battle").completed("1戦 / 2ターン")
    win.refresh()
    head = win.log.toPlainText().split(" ")[0]
    assert len(head) == 5 and head[2] == ":", head


def test_窓を作る前の行も出る():
    """⚠ ログの窓を開くのは後かもしれない（★それまでの分を落とさない）。"""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    log = AL.ActionLog()
    log.begin("move").completed("先に起きたこと")
    win, _ = _win(log=log)
    # ⚠ 窓は「今から」を見るので、★開く前の分は出ません（歴史はログに残っています）
    win.refresh()
    assert win.log.toPlainText() == ""
    log.begin("move").completed("開いた後のこと")
    win.refresh()
    assert "開いた後のこと" in win.log.toPlainText()


# ----------------------------------------------------------------------
# ★場所の配分（★左右 / RX3-0276）
# ----------------------------------------------------------------------
def test_横の配分はどちらも潰れない(window):
    win, _ = window
    for width in (700, 1283, 1920, 2560):
        strip, log = win.split_sizes(width)
        assert strip >= BW._strip_width_min() or strip + log < BW._strip_width_min() + BW.LOG_W_MIN, (width, strip)
        assert log >= BW.LOG_W_MIN or strip + log < BW._strip_width_min() + BW.LOG_W_MIN, (width, log)
        assert strip + log <= width


def test_既定で敵4群が全部見えログは残り全部(window):
    """★依頼者 2026-09-01「モンスター画面はちゃんとデフォルトでなるべく表示」→ ★札 2 列（2 段 × 2 列 = 敵 4 群）。

    ★150% の画面（論理 1283）でも 2 列が入り、ログは残り全部（★RX3-0276「空きが目立つ」）。
    """
    from dq3.ui.monster_panel import CARD_WIDTH, DEFAULT_COLUMNS

    win, _ = window
    for width in (1283, 1920):
        strip, log = win.split_sizes(width)
        assert strip == BW._strip_width_default() and strip >= DEFAULT_COLUMNS * CARD_WIDTH, (width, strip)
        assert log == width - BW.MARGIN_W - BW.HANDLE_H - strip and log >= BW.LOG_W_MIN, (width, log)
