"""敵の能力が「渡す側」から「読む側」へ届く（2026-08-07）。

## ⚠⚠⚠ 実機で発覚した食い違い

    [敵] キラーマシーン×1
    戦闘で まどうしのつえ を使います   ← ⚠ 呪文が効かない敵なのに

`enemy_instances()` はこう返していました:

    { index, id, name, hp, max_hp, status }   ← ⚠ stats を捨てていた

読む側（`_item_context`）はこう読むつもりでした:

    resist = e.stats.resist                   ← ⚠ 常に nil

★`max_hp` だけ抜き出して `stats` を捨てていたため、耐性が**一度も
届いていませんでした**。⚠ 「効くかもしれない」として撃っていました。

⚠⚠ **偽データでは `monster_stats` を直接渡していたので、検査は全部
通っていました。** ★実機でしか出ない食い違いです。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
           / "enemy_stats_handoff_test.lua")
DQ2 = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "dq2.lua"


@pytest.fixture(scope="module")
def result():
    if not (RUNNER.exists() and HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_ハーネスが全部通る(result):
    assert "NG 0 件" in result, result


def test_検査の数が足りている(result):
    m = re.search(r"OK (\d+) 件", result)
    assert m and int(m.group(1)) >= 7, result


def test_能力を渡している(result):
    """★★★ **ここが捨てられていました**。"""
    assert _ok(result, "★★★ stats を渡している"), result
    assert _ok(result, "★★★ resist まで届いている"), result


def test_読む側が効かないと判定できる(result):
    """⚠⚠ **渡っているだけでは足りません。** ★判定まで通します。"""
    assert _ok(result, "★★★ 杖を使わないと判定できる"), result


def test_図鑑に無い敵では封じない(result):
    """★★ **読めないことを理由に封じると、未知の敵に何もできません。**"""
    assert _ok(result, "⚠ 表に無い敵は stats が nil"), result


def test_渡す側が能力を落としていない():
    """⚠ `max_hp` だけ抜き出して `stats` を捨てる形へ戻らないこと。"""
    source = DQ2.read_bytes().decode("utf-8")
    start = source.index("function DQ2:enemy_instances")
    body = source[start:start + 3500]
    assert "stats  = stats," in body or "stats = stats," in body, (
        "⚠⚠ enemy_instances が stats を返していません")
