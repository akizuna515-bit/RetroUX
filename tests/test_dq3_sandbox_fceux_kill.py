"""実機スクリプトは依頼者の FCEUX を閉じない（2026-09-11）。

⚠⚠ 実機スクリプトは `taskkill /IM fceux64.exe` で**名前ごと全部**閉じていた。
★依頼者が遊んで確かめている最中の FCEUX まで閉じた（最後のセーブから後が消えうる）。
→ ★閉じるのは「隔離先の exe から起こしたもの」と「そのスクリプト自身が起こしたもの」だけ。
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess

from dq3.testing import sandbox as SB

ROOT = pathlib.Path(__file__).resolve().parents[1]
USER_EXE = r"C:\Projects\260721_RetroUX\tools\fceux\fceux64.exe"
SANDBOX_EXE = r"C:\Projects\260721_RetroUX\work\test-sandbox\20260911-1-x\fceux\fceux64.exe"


class _Runner:
    """★PowerShell と taskkill の偽物（⚠ 本物のプロセスには触らない）。"""

    def __init__(self, rows):
        self.rows = rows
        self.killed = []

    def __call__(self, cmd, **kw):
        if cmd[0] == "taskkill":
            self.killed.append(int(cmd[2]))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        out = "\n".join("%d|%d|%s" % (pid, ppid, path) for pid, path, ppid in self.rows)
        return subprocess.CompletedProcess(cmd, 0, out, "")


def test_依頼者のFCEUXは閉じない():
    r = _Runner([(100, USER_EXE, 4242), (200, SANDBOX_EXE, 4242), (300, USER_EXE, os.getpid())])
    assert sorted(SB.kill_sandbox_fceux(r)) == [200, 300]
    assert 100 not in r.killed, "⚠⚠ 依頼者の FCEUX を閉じた"


def test_依頼者のFCEUXを見分ける():
    r = _Runner([(100, USER_EXE, 4242), (200, SANDBOX_EXE, 4242), (300, USER_EXE, os.getpid())])
    assert SB.user_fceux(r) == [(100, USER_EXE)]


def test_置き場が分からなければ閉じない():
    r = _Runner([(100, "", 4242)])
    assert SB.kill_sandbox_fceux(r) == [] and r.killed == []


def test_依頼者のFCEUXが動いていたら速度や音を触るrunを始めない():
    import pytest

    with pytest.raises(SB.UserFceuxRunning):
        SB.refuse_if_user_fceux("テスト", _Runner([(100, USER_EXE, 4242)]))
    SB.refuse_if_user_fceux("テスト", _Runner([(200, SANDBOX_EXE, 4242)]))   # ★隔離先だけなら始めてよい


def test_名前ごと全部閉じるスクリプトが無い():
    """⚠ `taskkill /IM fceux64.exe` が戻ってきたら赤（★どのスクリプトでも）。"""
    bad = []
    for path in sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "dq3").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r'"taskkill",\s*"/IM",\s*"fceux64\.exe"', text):
            bad.append(str(path.relative_to(ROOT)))
    assert bad == [], "⚠⚠ 名前ごと全部閉じている（★依頼者の FCEUX まで閉じる）: %s" % bad
