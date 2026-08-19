"""ファイルと画面でログのレベルを分ける（2026-08-09 / 依頼者の指示）。

    > 画面にはださないが、ログボタンで見るとあとからわかる。
    > 当然ログDBには吐いてる。そういう作りにしたい。
    > ログは全体的にはそういう作りにしたい。ログレベル対応というか

## ⚠⚠ ここが壊れると気づけない

  DEBUG が**画面にも出る**ようになっても、画面が少し賑やかになるだけで
  エラーにはなりません。⚠ 逆に DEBUG が**ファイルにも残らない**と、
  「あとから追える」という前提が静かに失われます。
  ★どちらも見た目では分からないので、ここで固定します。
"""

from __future__ import annotations

import logging

from retroux.core.logging_setup import get_logger, setup_logging


def _read(path):
    return path.read_text(encoding="utf-8")


def test_debug_goes_to_the_file_but_not_to_the_screen(tmp_path):
    """★★ 本題。DEBUG はファイルだけ、INFO は両方。★★"""
    path = tmp_path / "retroux.log"
    handle = setup_logging(path, use_queue=False)
    try:
        log = get_logger("test")
        log.debug("これは細かい記録です")
        log.info("これは画面にも出る記録です")

        text = _read(path)
        assert "これは細かい記録です" in text, "★DEBUG がファイルに残っていない"
        assert "これは画面にも出る記録です" in text

        lines, _ = handle.buffer.snapshot()
        joined = "\n".join(lines)
        assert "これは画面にも出る記録です" in joined
        assert "これは細かい記録です" not in joined, (
            "⚠ DEBUG が画面に出ています（読みたい行が押し流されます）")
    finally:
        handle.shutdown()


def test_the_logger_itself_does_not_cut_debug(tmp_path):
    """⚠⚠ Logger の下限で切ると **Handler まで届きません**。

    ★2つのうち低いほうに合わせること。ここを間違えると
      `file_handler.setLevel(DEBUG)` が黙って効かなくなります。
    """
    path = tmp_path / "retroux.log"
    handle = setup_logging(path, level=logging.DEBUG,
                           gui_level=logging.INFO, use_queue=False)
    try:
        assert handle.logger.level == logging.DEBUG
    finally:
        handle.shutdown()


def test_the_screen_can_be_opened_up_on_purpose(tmp_path):
    """★全部見たい人は `gui_level` を下げられること（逃げ道を残す）。"""
    path = tmp_path / "retroux.log"
    handle = setup_logging(path, gui_level=logging.DEBUG, use_queue=False)
    try:
        get_logger("test").debug("細かい記録")
        lines, _ = handle.buffer.snapshot()
        assert any("細かい記録" in line for line in lines)
    finally:
        handle.shutdown()


def test_a_misspelled_level_does_not_kill_logging(tmp_path):
    """⚠ 設定ファイルから来る値なので、綴り違いで**落とさない**。

    ★読めなければ INFO に落として動かします（黙って全部止めない）。
    """
    path = tmp_path / "retroux.log"
    handle = setup_logging(path, level="でたらめ", gui_level="でたらめ",
                           use_queue=False)
    try:
        get_logger("test").info("動いています")
        assert "動いています" in _read(path)
    finally:
        handle.shutdown()
