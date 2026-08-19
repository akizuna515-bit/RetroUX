"""攻撃呪文の選び方（2026-08-03 / 「ガンガン行こうぜ」Phase 1）。

★★ **本物の Lua を走らせる。** ★★

## ⚠⚠ この日に踏んだ取り違え（3 回目 / 記録）

比べる関数を `better(a, b)` と書いたため、**引数の意味が曖昧**でした。
同点のとき `a`（新しい候補）を返していたので「**後に見たほうが勝つ**」。

★設定に書いた順と、選ばれる呪文が食い違います。
→ `pick_better(challenger, champion)` に名前を変え、
  **同点なら `champion`（先に見たほう）を残す**ようにしました。

★引数に意味のある名前を付けるだけで、読んだときに気づけます。
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
           / "attack_plan_test.lua")
MODULE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "attack_plan.lua"


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
    assert m and int(m.group(1)) >= 20, result


# --- ★★ 指示書 §7 の 3 ケース ---------------------------------------------

def test_ムーン単独で倒せるならサマルは重ねない(result):
    """★★★ **これが指示書の一番の要求**（§7.1 ケースB）。"""
    assert "OK   ★★ サマルは攻撃呪文を使わない -> nil" in result, result
    assert "★ムーン単独で倒しきれるので、サマルは別行動へ" in result, result


def test_2人なら倒せる場合は両方が攻撃呪文(result):
    """★§7.1 ケースA。"""
    assert "OK   ★サマルも攻撃呪文を使う -> ギラ" in result, result
    assert "OK   ★ムーンも攻撃呪文を使う -> バギ" in result, result


def test_2人でも倒せない場合も最善手を打つ(result):
    """★§7.1 ケースC。⚠ 諦めて殴るのではなく、期待効果の高い手。"""
    assert "OK   ⚠ それでも両方が最善手を打つ -> true" in result, result


# --- ★ 比べる順（§7.2）----------------------------------------------------

def test_多く倒せるほうが勝つ(result):
    """★MP が高くても、確定撃破の数が多いほうを採ります。"""
    assert "OK   ★多く倒せるほうが勝つ（MP が高くても） -> バギ" in result, result


def test_同点ならMPの安いほう(result):
    """★§7.2 の最後の軸。"""
    assert "OK   ★★ MP 2 のギラを使う -> ギラ" in result, result
    assert "MP の安いサマル（2）を使う" in result, result


def test_同点なら設定に書いた順が効く(result):
    """⚠⚠ 3 回目の取り違え。★後勝ちだと設定と食い違います。"""
    assert "OK   ★どちらでも同じなら先に見たほう -> バギ" in result, result


# --- ⚠ 安全側 -------------------------------------------------------------

def test_使えない候補は選ばない(result):
    """⚠ MP 不足・封じ・拒否指定は呼ぶ側が `usable` で伝えます。"""
    assert "OK   ⚠ usable=false は選ばれない -> nil" in result, result


def test_威力が分からない呪文は選ばない(result):
    """⚠⚠ **推測で埋めません。**"""
    assert "OK   ⚠ 威力が無ければ候補にならない -> nil" in result, result


def test_誰も使えないときは誰も唱えない(result):
    assert "OK   ⚠ 誰も唱えない -> true" in result, result
    assert "⚠ 使える攻撃呪文がありません" in result, result


def test_呪文が効かない敵には唱えず殴る(result):
    """★★★ **依頼者の実機指摘で見つかった**（2026-08-03）。

        「呪文が効かない相手に呪文を使っている？」

    ⚠⚠ キラーマシーン（`spell_damage: 7`）にイオナズンを撃っていました。
      MP を捨てるだけなので、★**殴ったほうがまし**です。
    """
    assert "OK   ★★ 誰も呪文を唱えない -> none" in result, result
    assert "OK   ⚠⚠ 効き目 0 の呪文は候補にしない -> nil" in result, result


def test_効く敵と効かない敵が混ざっていても正しく数える(result):
    """★イオナズンで、効く敵だけ倒せる数に入ること。"""
    assert "OK   ★効く敵だけ倒せる数に入る -> 1" in result, result
    assert "OK   ★効かない敵は immune で数える -> 1" in result, result


# --- ★ ログ（§14）--------------------------------------------------------

def test_理由が人に読める形で出る(result):
    """★誰が何を唱え、なぜかが分かること。"""
    assert "OK   ★誰が何を唱えるか書いてある -> true" in result, result
    assert "対象 2体 / 期待実効" in result, result


# --- ★ Core と同じ流儀 ----------------------------------------------------

def test_RAMもメニューも知らない():
    """★`damage_estimate.lua` と同じ。⚠ 知ると実機が要ります。"""
    source = MODULE.read_bytes().decode("utf-8")
    for banned in ("memory.read", "joypad", "emu.", "gui."):
        assert banned not in source, f"⚠ {banned} が入っています"


def test_回復を扱わない():
    """★指示書 §5。⚠ 回復は既存の安全停止に任せます。"""
    source = MODULE.read_bytes().decode("utf-8")
    for banned in ("heal", "ホイミ", "ベホイミ"):
        # ★注意書きの中の言及は数えない（コード行だけ見る）
        for line in source.split("\n"):
            if line.strip().startswith("--"):
                continue
            assert banned not in line, f"⚠ {banned} が入っています: {line}"
