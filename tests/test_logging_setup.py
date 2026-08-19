"""Python 側ログ基盤のテスト（MVP2 Phase 1 / 指示書 6.2）。

守りたい契約:
  1. 1回のログが**ファイルと GUI バッファの両方**へ出る
  2. 書式に日時・レベル・モジュールと、あれば battle_id / event_type が入る
  3. GUI は「前回の続き」だけを取れる（全件読み直さない）
  4. 輪バッファが溢れても**黙って飛ばさない**（読める最古から返る）
  5. ローテーションが実際に起きてもログが続く
     ★ここが本命。Lua が同じファイルを開きっぱなしにしていたため
       Python がローテートすると壊れる、という地雷を潰した回帰テスト。
"""

from __future__ import annotations

import logging

import pytest

from retroux.core.logging_setup import GuiLogBuffer, get_logger, setup_logging


@pytest.fixture
def handle(tmp_path):
    h = setup_logging(tmp_path / "retroux.log", use_queue=False)
    yield h
    h.shutdown()


def test_child_logger_is_formatted(handle, tmp_path):
    """★回帰テスト: **子ロガー**から出しても書式が壊れないこと。

    実際の呼び出しは `get_logger("gui")`（= retroux.gui）で、親ではない。
    フィルタを Logger に付けていたときは、親のフィルタを通らないため
    `KeyError: 'short_name'` になり、**ログが1行も出なかった**。
    テストが親ロガーだけを叩いていたので素通りし、GUI を起動して初めて出た。
    """
    get_logger("gui").info("子ロガーからの1行")

    text = (tmp_path / "retroux.log").read_text(encoding="utf-8")
    assert "子ロガーからの1行" in text
    assert "[INFO] gui" in text        # short_name が効いている

    lines, _ = handle.buffer.snapshot()
    assert len(lines) == 1


def test_writes_to_file_and_gui(handle, tmp_path):
    handle.logger.info("回復を確認しました")

    text = (tmp_path / "retroux.log").read_text(encoding="utf-8")
    assert "回復を確認しました" in text

    lines, _ = handle.buffer.snapshot()
    assert len(lines) == 1
    assert "回復を確認しました" in lines[0]


def test_format_contains_time_level_and_context(handle):
    handle.logger.info("敵を倒した", extra={"battle_id": 12, "event_type": "battle_end"})
    lines, _ = handle.buffer.snapshot()
    line = lines[0]

    assert line.startswith("20")            # 日時（Lua の行と同じ形）
    assert "[INFO]" in line
    assert "battle=12" in line
    assert "event=battle_end" in line


def test_context_is_optional(handle):
    """battle_id を渡さなくても書式が壊れない。"""
    handle.logger.warning("ROM が一致しません")
    lines, _ = handle.buffer.snapshot()
    assert "battle=" not in lines[0]
    assert "ROM が一致しません" in lines[0]


def test_snapshot_returns_only_new_lines(handle):
    handle.logger.info("1件目")
    lines, cursor = handle.buffer.snapshot()
    assert len(lines) == 1

    handle.logger.info("2件目")
    lines, cursor2 = handle.buffer.snapshot(cursor)
    assert [l.split()[-1] for l in lines] == ["2件目"]
    assert cursor2 > cursor

    # 新しい行が無ければ空
    assert handle.buffer.snapshot(cursor2)[0] == []


def test_overflow_returns_oldest_available():
    """溢れたぶんは飛ばされるが、**読める最古から**返る（黙って欠けない）。"""
    buf = GuiLogBuffer(capacity=3)
    for i in range(5):
        buf.append(f"line{i}")

    lines, cursor = buf.snapshot(since=0)
    assert lines == ["line2", "line3", "line4"]   # 0,1 は溢れた
    assert cursor == 5
    assert buf.dropped == 2


def test_rotation_keeps_logging(tmp_path):
    """★回帰テスト: ローテーションしてもログが続く。

    Lua が同じファイルを**開きっぱなし**にしていたため、
    ここで rename が起きると Lua の書き込みが新しいファイルへ出なくなる。
    Lua 側は書くたびに開き直す形へ直した（bridge.lua の Bridge:log）。
    Python 側がローテーション後も書けることをここで押さえる。
    """
    path = tmp_path / "retroux.log"
    handle = setup_logging(path, max_bytes=200, backup_count=2, use_queue=False)
    try:
        for i in range(40):
            handle.logger.info("長めのメッセージで確実にローテーションさせる %d", i)
    finally:
        handle.shutdown()

    assert path.exists()
    assert (tmp_path / "retroux.log.1").exists()      # 世代ができている
    # 最新のファイルに最後のほうの行が入っている
    assert "39" in path.read_text(encoding="utf-8")


def test_queue_mode_delivers(tmp_path):
    """既定（別スレッド）でも最終的に届く。shutdown で取りこぼさない。"""
    handle = setup_logging(tmp_path / "retroux.log", use_queue=True)
    handle.logger.info("非同期でも届く")
    handle.shutdown()      # listener を止めると残りが書き出される

    assert "非同期でも届く" in (tmp_path / "retroux.log").read_text(encoding="utf-8")


def test_logger_is_isolated_from_root(handle, caplog):
    """ルートロガーへ伝播しない（二重出力を防ぐ）。"""
    assert handle.logger.propagate is False
    assert logging.getLogger("retroux").propagate is False
