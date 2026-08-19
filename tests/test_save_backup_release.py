"""セーブステートの世代バックアップ（仕様書 6.1）。

★2026-08-01 に `test_release_prep.py`（848 実質行）から切り出しました（指示書 §11.1）。
  ⚠ **内容は1件も減らしていません。**機械で切り、件数で確かめています。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _code_lines(text: str) -> list:
    """コメントと空行を落とした行を返す。

    ★★ **「その語がソースにある」だけの検査は穴になる。** ★★
      説明のコメントに同じ語が書いてあると、**実装を消しても緑**のままになる。
      実際に `MessageBox` と `MsgBox` の検査がこれで通り抜けた（2026-07-30）。

    ⚠ PowerShell は `#`、VBS と `.cmd` は `'` / `rem` がコメント。
    """
    made = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "'", "rem ", "REM ")):
            continue
        made.append(stripped)
    return made

# --- セーブステート保護（仕様書 6.1）-----------------------------------

def test_a_fresh_heartbeat_means_running(tmp_path):
    from retroux.core import backup_status

    lock = tmp_path / "backup.lock"
    lock.write_text("1234", encoding="utf-8")
    backup_status.write(lock, running=True, generations=10,
                        watching=tmp_path, destination=tmp_path,
                        interval=1.0, last_backup="09:14:32")
    status = backup_status.read(lock)
    assert status.running
    assert status.label == "セーブステート保護: 稼働中"
    assert status.is_warning is False
    assert "最新バックアップ: 09:14:32" in status.detail_lines()
    assert "保持世代: 10" in status.detail_lines()


def test_a_stale_heartbeat_means_stopped_even_if_the_file_says_running(tmp_path):
    """★★ **「動いているか」は心拍で見る。** ★★

    ⚠ 異常終了すると状態ファイルの `running: true` が残る。
      中身を信じると「動いている」と嘘を出す。
    """
    from retroux.core import backup_status

    lock = tmp_path / "backup.lock"
    lock.write_text("1234", encoding="utf-8")
    backup_status.write(lock, running=True, generations=10)
    # ⚠⚠ **`STALE_SECONDS` から古さを計算しない。**
    #   そうすると定数がどんな値になってもテストが追従してしまい、
    #   「20秒 -> 10億秒」に壊しても**緑のまま**だった（2026-07-30 に判明）。
    #   ★絶対の秒数で古くする。2分前の心拍は、どう考えても止まっている。
    old = time.time() - 120
    os.utime(lock, (old, old))

    status = backup_status.read(lock)
    assert status.running is False
    assert status.label == "セーブステート保護: 停止"
    assert status.is_warning is True
    assert any("守られていません" in line for line in status.detail_lines())


def test_the_staleness_limit_is_a_sane_number_of_seconds():
    """★定数そのものを見張る。

    ⚠ 上のテストは古さを絶対秒で作るようにしたが、それでも
      **定数が極端な値になっていないこと**は別に確かめる必要がある。
      大きすぎる: 止まっても「稼働中」と出続ける（保護されていると誤解する）
      小さすぎる: 動いているのに「停止」と点滅する（信用されなくなる）
    """
    from retroux.core import backup_status

    assert 5 <= backup_status.STALE_SECONDS <= 60, \
        f"心拍の期限が極端です: {backup_status.STALE_SECONDS}"


def test_no_status_file_says_not_started_not_stopped(tmp_path):
    """⚠ 「一度も動いていない」と「止まった」を区別する。"""
    from retroux.core import backup_status

    status = backup_status.read(tmp_path / "backup.lock")
    assert status.running is False
    assert status.known is False
    assert status.label == "セーブステート保護: 未起動"


def test_a_broken_status_file_does_not_raise(tmp_path):
    from retroux.core import backup_status

    lock = tmp_path / "backup.lock"
    backup_status.status_path(lock).parent.mkdir(parents=True, exist_ok=True)
    backup_status.status_path(lock).write_text("こわれている {{{",
                                              encoding="utf-8")
    status = backup_status.read(lock)
    assert status.known is False


def test_a_last_error_is_shown_as_a_warning(tmp_path):
    from retroux.core import backup_status

    lock = tmp_path / "backup.lock"
    lock.write_text("1", encoding="utf-8")
    backup_status.write(lock, running=True, last_error="書き込めません")
    status = backup_status.read(lock)
    assert status.is_warning is True
    assert any("最後のエラー" in line for line in status.detail_lines())


def test_the_status_writer_never_leaves_a_temp_file(tmp_path):
    from retroux.core import backup_status

    lock = tmp_path / "backup.lock"
    backup_status.write(lock, running=True)
    assert list(tmp_path.glob("*.tmp")) == []


def test_the_status_file_is_valid_json(tmp_path):
    from retroux.core import backup_status

    lock = tmp_path / "backup.lock"
    backup_status.write(lock, running=True, generations=7, session="abc")
    raw = json.loads(backup_status.status_path(lock).read_text(encoding="utf-8"))
    assert raw["generations"] == 7
    assert raw["session"] == "abc"
    assert raw["pid"] == os.getpid()
