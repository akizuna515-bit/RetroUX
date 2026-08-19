"""黒い窓を出さずに起動する（仕様書 4.1）。

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

# --- コンソール無し（仕様書 4.1）---------------------------------------

def test_writing_without_a_console_does_not_raise(monkeypatch):
    """★★ `pythonw.exe` では `sys.stdout` が `None` になりうる。 ★★

    ⚠ そこで `print` を直に呼ぶと `AttributeError` で落ち、
      GUI が起動直後に終了して**利用者から見て「何も起きない」**になる
      （仕様書 5.1 が禁じている状態）。
    """
    from retroux.core import console

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert console.usable(None) is False
    assert console.has_console() is False
    # ★落ちずに False を返すこと
    assert console.write("これは出ない") is False


def test_say_always_logs_even_without_a_console(monkeypatch, caplog):
    """★画面に出せなくても**ログには残す**（あとから調べられる）。"""
    import logging

    from retroux.core import console

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    logger = logging.getLogger("test.console")
    with caplog.at_level(logging.INFO, logger="test.console"):
        console.say("記録は残る", logger=logger)
    assert "記録は残る" in caplog.text


def test_a_closed_stream_is_not_usable(tmp_path):
    from retroux.core import console

    handle = (tmp_path / "x.txt").open("w", encoding="utf-8")
    assert console.usable(handle) is True
    handle.close()
    assert console.usable(handle) is False


def test_the_gui_entry_point_has_no_bare_prints():
    """⚠ `pythonw.exe` で動く入口に `print` を残さない。

    ★`say` を通せば、画面に出せなくてもログに残る。
    """
    text = (PROJECT_ROOT / "retroux" / "gui.py").read_text(encoding="utf-8")
    assert "print(" not in text, "gui.py に print が残っている（say を使う）"


def test_both_entry_points_take_a_session_id():
    """★起動スクリプトが渡す。**今回起動した子プロセス**を見分ける鍵。

    ⚠⚠ **子の出力の文字コードを決め打ちしない。**
      `--help` の説明文は日本語で、子プロセスの標準出力はふつう
      **コンソールのコードページ（日本語 Windows なら cp932）**になる。
      これを utf-8 として読むと `UnicodeDecodeError` が読み取りスレッドで起き、
      `proc.stdout` が **None** になって「`--session` が無い」に見える
      ＝**環境によって落ちるテスト**になっていた（2026-07-30 に踏んだ）。

    ★対策は2つ重ねる:
      1. `PYTHONIOENCODING` で子に utf-8 で書かせる
      2. `errors="replace"` で、それでも読めない字があっても None にしない
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for module in ("retroux.gui", "retroux.tools.savestate_backup"):
        proc = subprocess.run([sys.executable, "-m", module, "--help"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             env=env, cwd=PROJECT_ROOT)
        # ★None のまま assert すると原因が分からないので、先に出す
        assert proc.stdout is not None, f"{module} の出力が読めませんでした"
        assert "--session" in proc.stdout, module
