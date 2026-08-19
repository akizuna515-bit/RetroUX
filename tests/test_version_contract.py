"""版番号の約束（仕様書 14章）。

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

# --- バージョン（仕様書 14章）------------------------------------------

def test_the_version_comes_from_one_place():
    """★タイトル・About・診断・ログが別々に持たない。"""
    from retroux import version

    assert version.VERSION == version.get_version()
    assert version.VERSION != version.UNKNOWN, "版が読めていない"
    assert version.title().startswith("RetroUX ")


def test_the_version_matches_pyproject():
    """⚠ 数字を写していないこと（写すと必ずずれる）。"""
    import re

    from retroux import version

    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    found = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert found is not None
    assert version.VERSION == found.group(1)


def test_an_unreadable_version_does_not_lie():
    """★読めないときに数字を作らない。"""
    from retroux import version

    assert "unknown" in version.UNKNOWN
