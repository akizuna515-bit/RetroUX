"""攻撃呪文の候補づくり（2026-08-03 / 「ガンガン行こうぜ」Phase 1）。

★★ **本物の Lua を走らせる。** ★★

## ⚠⚠ ここで守りたいこと

    「ガンガン行こうぜ」では**回復行動を考慮しない**（指示書 §5）

★回復呪文が攻撃候補に**混ざらない**ことを、ここで固定します。
⚠ 混ざると「攻撃するつもりでホイミを唱える」ことになります。

あわせて、唱えない指定（メガンテ・パルプンテ）と
威力が分かっていない呪文も落ちることを見ます。
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
           / "attack_candidates_test.lua")
MODULE = (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
          / "attack_candidates.lua")


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


def test_ハーネスが全部通る(result):
    assert "不合格 0" in result, result


def test_検査の数が足りている(result):
    m = re.search(r"合計 (\d+) 項目", result)
    assert m and int(m.group(1)) >= 25, result


# --- ⚠⚠ 混ざってはいけないもの（§5・§6）---------------------------------

def test_回復呪文が攻撃候補に混ざらない(result):
    """★★★ **指示書 §5 の要求**。⚠ これが一番大事。"""
    assert "OK   ⚠⚠ 回復呪文は候補にしない -> false" in result, result


def test_メガンテは候補にしない(result):
    """⚠⚠ **唱えた本人が死にます。**"""
    assert "OK   ⚠⚠ メガンテは候補にしない -> false" in result, result


def test_威力が分からない呪文は候補にしない(result):
    """⚠ **推測で埋めません。**"""
    assert "OK   ⚠ 威力が分からない呪文は候補にしない -> false" in result, result


def test_未習得や位置不明は候補にしない(result):
    assert "OK   ⚠ 呪文リストに位置が無ければ候補にしない -> false" in result


# --- ★ MP（§4.1）--------------------------------------------------------

def test_MP不足なら候補にしない(result):
    assert "OK   ⚠ MP 不足なら候補にしない -> false" in result, result


def test_予約MPを守る(result):
    """★ルーラ・リレミトのぶんと、最低残存MPを残します。"""
    assert "OK   ⚠ 5 - 2 = 3 < 4 なのでギラも使えない -> 0" in result, result


def test_MPが読めないときは使わない(result):
    """⚠ 分からないときは**唱えない**側へ倒します（安全側）。"""
    assert "OK   ⚠ MP が読めない -> 使えない -> false" in result, result


# --- ★ 封じ ---------------------------------------------------------------

def test_マホトーンで封じられていたら候補にしない(result):
    assert "OK   ⚠ 封じられていたら候補にしない -> false" in result, result


# --- ★ 落としたものを黙って消さない ---------------------------------------

def test_落とした理由が残る(result):
    """⚠ 「なぜ唱えないのか」が分からないと直しようがありません。"""
    assert "OK   ⚠ 落としたのは 3 つ -> 3" in result, result
    assert "威力が分かっていない（マホトーン）" in result, result
    assert "回復呪文（この作戦では使わない）（ホイミ）" in result, result
    assert "唱えた本人が死ぬ（メガンテ）" in result, result


def test_同じ理由はまとめて出す(result):
    """★7 個並ばないように。"""
    assert "OK   ★同じ理由はまとまる -> true" in result, result


# --- ⚠ 壊れた入力 ---------------------------------------------------------

def test_壊れた入力でも落ちない(result):
    """⚠⚠ 戦闘中に落ちると、ゲームが止まります。"""
    assert "OK   ⚠ 一覧が nil -> 0" in result, result
    assert "OK   ⚠ 呪文表が nil -> 0" in result, result
    assert "OK   ⚠ opts が nil -> 0" in result, result


# --- ★ Core と同じ流儀 ----------------------------------------------------

def test_RAMを読まない():
    """★RAM から拾うのは `bridge.lua` の仕事です。"""
    source = MODULE.read_bytes().decode("utf-8")
    for banned in ("memory.read", "joypad", "emu.", "gui."):
        assert banned not in source, f"⚠ {banned} が入っています"
