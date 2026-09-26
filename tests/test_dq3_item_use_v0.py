"""item_use_v0（フィールドで道具を使う Lua）を実機なしで動かす（RX3-0159 / 2026-09-11）。

★足場は `research/probes/active/dq3_item_use_v0_test.lua`。
⚠⚠ **「すてる」は取り返しがつきません。** ★ここで固定するのは、
「カーソルが目当ての名前を指しているときだけ A」「見つからなければ押さずに止まる」です。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_item_use_v0_test.lua"
TARGET = ROOT / "dq3" / "phase0" / "item_use_v0.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists() and TARGET.exists()),
    reason="Lua を動かせない環境")


@pytest.fixture(scope="module")
def result() -> str:
    done = subprocess.run([sys.executable, str(RUNNER), str(HARNESS)], cwd=str(ROOT),
                          capture_output=True, timeout=180, text=True,
                          encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, "⚠⚠ 落ちました" + chr(10) + both
    return both


def test_最後まで走って合格する(result):
    assert "すべて合格" in result, result


def test_OKが減っていない(result):
    n = sum(1 for line in result.splitlines() if re.match(r"^OK\b", line))
    assert n >= 7, "⚠ OK が %d 件しかありません%s%s" % (n, chr(10), result)


def test_すてるを押さないことを動かして確かめている(result):
    """⚠⚠ 「どうする？」のカーソルが すてる にあっても、★つかう へ寄せ直してから A。"""
    assert "カーソルが すてる にあっても" in result, result


def test_誰の鍵かを動かして確かめている(result):
    """★依頼者「誰がどの鍵を持っているかの把握も必要」（2026-09-11）。"""
    assert "2 人目の袋から鍵を使う" in result, result


def test_戦闘中は押さない(result):
    assert "戦闘中は 1 つも押さない" in result, result
