"""System Log が最新行に追従することの回帰テスト。

★依頼者の報告（2026-07-27）:
    「右側のログが、カーソルが下になくて、下押さないと見れない」

★★ 不具合の中身（実測で確かめた / `research/probes/archived/probe_scroll.py`）★★

  `QPlainTextEdit.appendPlainText` が自動で追従するのは
  **追記の直前にスクロールバーが最大値にいたときだけ**。
  そのため **一度でも表示が一番下から離れると、以後どれだけ追記しても
  二度と追従しない。** value が 0 のまま maximum だけ増え続ける:

      本文の途中へ移った状態   value=  0 max=236
        そのあと追記           value=  0 max=241
        さらに追記             value=  0 max=246

  この状態から抜ける手段が画面に無かったため、利用者は毎回手で送っていた。

⚠ **最初の仮説は外れた。** 「表示前は maximum が 0 なので追従が始まらない」
  と考えて直したが、`research/probes/archived/probe_scroll.py` で測ると offscreen の Qt は
  show の時点で value を maximum に合わせており、**その経路では再現しない**。
  修正を外しても検査が緑のままだったことで気づいた
  （playbook「わざと壊して赤くなることを確かめる」がそのまま効いた）。

守りたい契約:
  1. **一度離れても、追従に戻せば必ず追いつく**（元の不具合の核心）
  2. 追従が入っている間は最新行が見えている
  3. ⚠ 上へ戻って読んでいる間は引きずり降ろされない（「追従」と「固定」は別）
  4. 追従しているかどうかが**画面に出ている**（黙って止まらない）
  5. 選んだ戦闘の出来事（`_events`）は逆に**先頭**を見せる

⚠ Qt のウィジェットを作るので、画面の無い環境では offscreen で動かす。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.ui.main_window import MainWindow  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402

# 1画面に収まらない量にする。収まってしまうと maximum が 0 のままで、
# ★「追従できているのか、スクロールが不要なだけか」を区別できない。
LINE_COUNT = 400


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        created = QApplication([])
    except Exception as exc:                      # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")
    yield created


@pytest.fixture
def window(app, tmp_path):
    log = tmp_path / "retroux.log"
    log.write_text(
        "".join(f"12:00:00 起動時のログ {i}\n" for i in range(LINE_COUNT)),
        encoding="utf-8")

    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    vm = ViewModel(recorder, db, "HASH", {1: "スライム"})

    # ★interval_ms を大きくして、タイマーが勝手に走らないようにする。
    #   テストの中で明示的に _drain_system_log() を呼ぶ（本番と同じ入口）。
    win = MainWindow(vm, interval_ms=10 ** 6, log_path=log)
    win.resize(600, 300)
    win.show()
    app.processEvents()
    yield win, log, app
    win.close()
    db.close()


def _bar(win):
    return win._system_log.verticalScrollBar()


def _append(window_tuple, count, tag):
    """ログへ追記して、本番と同じ入口（_drain_system_log）で取り込む。"""
    win, log, app = window_tuple
    with log.open("a", encoding="utf-8") as fh:
        for i in range(count):
            fh.write(f"{tag} {i}\n")
    win._drain_system_log()
    app.processEvents()


def _leave_bottom(window_tuple):
    """表示を一番下から離す（利用者が上へ戻った状態にする）。"""
    win, _, app = window_tuple
    _bar(win).setValue(0)
    app.processEvents()


# --- 前提の確認 --------------------------------------------------------


def test_scrollbar_actually_scrolls(window):
    """スクロールが必要な量が入っていること。

    ★これが無いと、以下の検査は「スクロール不要だから一番下」を
      「追従できている」と読み違える（playbook #43 と同じ形）。
    """
    win, _, _ = window
    assert _bar(win).maximum() > 0, (
        "1画面に収まってしまい、追従の検査に意味が無い（LINE_COUNT を増やす）")


# --- ★本題1: 一度離れても、追従に戻せば追いつく -------------------------


def test_can_recover_following_after_leaving_bottom(window):
    """★これが元の不具合そのもの。

    修正前は、一度一番下から離れると `appendPlainText` が二度と追従せず、
    **画面から戻す手段が無かった**（毎回手で送っていた）。
    """
    win, _, app = window
    _leave_bottom(window)
    _append(window, 30, "12:00:01 離れている間のログ")
    assert _bar(win).value() == 0, "前提: 離れている間は追従しない"

    # 追従に戻す（画面のチェックボックス。利用者が押せる手段）
    win._follow_log.setChecked(True)
    app.processEvents()

    bar = _bar(win)
    assert bar.value() >= bar.maximum() - win.SCROLL_STICKY_SLACK, (
        f"追従に戻したのに最新行まで来ない（value={bar.value()} / "
        f"max={bar.maximum()}）。これが「下を押さないと見れない」状態")


def test_keeps_following_after_recovery(window):
    """戻したあと、続けて来る行にも追従すること（1回だけ動くのでは足りない）。"""
    win, _, app = window
    _leave_bottom(window)
    _append(window, 10, "12:00:02 離脱中")
    win._follow_log.setChecked(True)
    app.processEvents()

    _append(window, 20, "12:00:03 復帰後のログ")
    bar = _bar(win)
    assert bar.value() >= bar.maximum() - win.SCROLL_STICKY_SLACK, "追従が続かない"
    assert "復帰後のログ 19" in win._system_log.toPlainText()


def test_scrolling_back_to_bottom_resumes_following(window):
    """スクロールバーを一番下へ戻すだけでも追従が復活すること。

    ★チェックボックスを知らなくても直せる経路を残す。
    """
    win, _, app = window
    _leave_bottom(window)
    assert not win._follow_log.isChecked(), "上へ戻ったらチェックが外れるべき"

    bar = _bar(win)
    bar.setValue(bar.maximum())
    app.processEvents()
    assert win._follow_log.isChecked(), "一番下へ戻したらチェックが戻るべき"

    _append(window, 20, "12:00:04 戻したあと")
    assert bar.value() >= bar.maximum() - win.SCROLL_STICKY_SLACK


# --- ★本題2: 追従中は最新行が見えている --------------------------------


def test_follows_new_lines(window):
    win, _, _ = window
    assert win._follow_log.isChecked(), "既定は追従"
    _append(window, 30, "12:00:05 あとから来たログ")

    bar = _bar(win)
    assert bar.value() >= bar.maximum() - win.SCROLL_STICKY_SLACK, (
        "追記したのに追従していない")
    # ★「追従した」ではなく「**最後の行が入っている**」ことまで見る
    assert "あとから来たログ 29" in win._system_log.toPlainText()


def test_cursor_moves_to_end_when_following(window):
    """**テキストカーソル**も末尾へ来ること。

    バーだけ動かすと、キーボードで下を押した瞬間にカーソルの居る場所へ
    飛び戻る。依頼者の言う「カーソルが下にない」はこれ。
    """
    win, _, _ = window
    _append(window, 5, "12:00:06 カーソル確認")
    doc_end = win._system_log.document().characterCount() - 1
    assert win._system_log.textCursor().position() == doc_end, (
        "テキストカーソルが末尾にない")


# --- ★本題3: 読んでいる間は引きずり降ろされない -------------------------


def test_does_not_drag_user_down_while_reading(window):
    """⚠ ここが「追従」と「固定」の違い。

    0.5秒ごとに一番下へ送る実装にすると過去のログが**読めなくなる**。
    不具合を直すついでに別の不具合を作らない。
    """
    win, _, _ = window
    _leave_bottom(window)
    _append(window, 30, "12:00:07 読んでいる間のログ")

    assert _bar(win).value() == 0, (
        f"上へ戻っているのに引きずり降ろされた（value={_bar(win).value()}）")
    # ★追従しないだけで、**行そのものは入っている**こと（取りこぼしと区別する）
    assert "読んでいる間のログ 29" in win._system_log.toPlainText()


# --- ★本題4: 状態が画面に出ている --------------------------------------


def test_following_state_is_visible(window):
    """追従しているかどうかがウィジェットに出ていること。

    ★黙って追従を止めるのが元の不具合。状態が見えないと
      利用者は「壊れた」と受け取る（playbook #35）。
    """
    win, _, _ = window
    # ★★ 2026-08-09: System Log は下段の窓にあります ★★
    #   ⚠ 窓を出さないと中身は `isVisible()` が偽になります。
    #   ★戦闘ログの表を廃止したので、下段の中身は System Log だけです
    #     （タブはありません）。
    win._log_window.show()
    assert win._follow_log.isVisible(), "追従の表示が画面に無い"
    assert win._follow_log.isChecked()

    _leave_bottom(window)
    assert not win._follow_log.isChecked(), (
        "追従が止まったのに画面の表示が変わらない")


def test_show_event_does_not_drag_down_on_second_show(window):
    """最小化からの復帰で引きずり降ろされないこと。"""
    win, _, app = window
    _leave_bottom(window)
    win.hide()
    win.show()
    app.processEvents()
    assert _bar(win).value() == 0, "2回目の表示で一番下へ送られた"


# --- ★本題5: 戦闘の出来事は先頭を見せる --------------------------------


def test_the_battle_log_table_is_no_longer_on_screen(window):
    """★★ 2026-08-09: 戦闘ログの表は画面から外しました（依頼者の指示）★★

        > 戦闘ログは戦闘前、後（楽なタイミングで）Systemログに出力して
        > 画面からは削除

    ⚠⚠ **一緒に「選んだ戦闘の出来事」も出なくなりました。** 表の行を選んで
      読む作りだったので、表が無いと開く道がありません。
      ★記録（DB）は残っているので、出したくなったら戻せます。

    ★ここでは「画面に無い」ことだけを固定します。⚠ 黙って消えたのか
      意図して消したのか、あとから分からなくなるのを避けるためです。
    """
    win, _, _app = window
    assert getattr(win, "_table", None) is None, "戦闘ログの表が残っている"
    assert getattr(win, "_events", None) is None, "出来事の欄が残っている"


# --- ★ 整列で System Log が畳まれない（2026-08-10 / 依頼者の報告）--------

def test_neither_the_monster_nor_the_log_collapses_when_arranged(window):
    """★★ 整列（下段 216px）で、上段（出会った敵）も System Log も消えない。★★

    ⚠ 依頼者の報告が2つ出た（シーソー）:
      1. System Log が畳まれる（敵カードが高さを取る）
      2. 逆に敵カードが消える（System Log を守った結果）
    ★縦スプリッタ＋`setChildrenCollapsible(False)` で、どちらも 0 にしない。
      整列で窓が縮んでも両方が残り、比率で配分される。
    """
    win, _, app = window
    from retroux.ui.log_window import SYSTEM_LOG_MIN, TOP_MIN

    lg = win._log_window
    split = lg.splitter()
    assert split is not None and split.count() == 2, "★縦スプリッタが無い"
    # ★上段が敵カードで高くなった状況を模擬
    split.widget(0).widget().setMinimumHeight(200)
    lg.resize(1264, 216)          # ★整列の標準サイズ
    app.processEvents()
    app.processEvents()

    top_h, bottom_h = split.sizes()
    assert top_h >= TOP_MIN - 4, f"★出会った敵が消えた: {top_h}px"
    assert bottom_h >= SYSTEM_LOG_MIN - 4, f"★System Log が畳まれた: {bottom_h}px"
