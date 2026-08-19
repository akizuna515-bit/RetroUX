"""杖は呪文と同じ効果なので、耐性を見る（2026-08-07 / 依頼者の実機指摘）。

    > キラーマシーン単体と戦闘。魔道士の杖を使っている？

## ⚠⚠ 「片側だけ」だった

まどうしのつえ＝ギラ、いかづちのつえ＝バギ。
★攻撃呪文の側（`attack_plan.lua`）は「効かない敵には撃たない」を
守っていたのに、⚠ **道具だけ素通り**していました。

⚠⚠⚠ **判定は呪文とまったく同じ規則**を使います。
★ここで別の式を書くと、片方だけ直したときに静かに食い違います。
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
           / "wand_resist_test.lua")
COND = (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
        / "item_conditions.lua")
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"


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
    assert m and int(m.group(1)) >= 19, result


def test_呪文が効かない敵だけなら使わない(result):
    """★★★ **これが指摘そのもの**。"""
    assert _ok(result, "★★★ 呪文が効かない敵だけなら使わない"), result


def test_理由が読んで分かる(result):
    """⚠ 「使わなかった」だけでは、壊れているのか正しいのか分かりません。"""
    assert _ok(result, "★理由が読んで分かる"), result


# --- ⚠⚠⚠ 「敵が居ない」と「効かない敵しか居ない」を混ぜない -----------

def test_敵が居ないときは別の理由にする(result):
    """★★★ **実機ログで発覚**（2026-08-07）。

    起動直後の**戦闘外**で「呪文が効かない敵しか居ません」と出ていました。
    ⚠ 敵は**0体**です。★理由が嘘だと、次に追うとき迷わせます。

    ⚠⚠ 「0 と不明を混ぜない」と何度も書きながら、今日3回目です。
    """
    assert _ok(result, "★★★ 「敵が居ません」と言う"), result
    assert _ok(result, "★全員倒れていても「敵が居ません」"), result
    assert _ok(result, "★★ 生きた「効かない敵」なら別の理由"), result


# --- ⚠⚠ **封じすぎない**（★これが無いと別の壊れ方）--------------------

@pytest.mark.parametrize("label", [
    "★★ 効く敵には使う",
    "★★ 1体でも効く敵が居れば使う",
    "★半分しか効かない敵にも使う",
    "★★★ 耐性が読めない敵には使う",
])
def test_封じすぎない(result, label):
    assert _ok(result, label), result


def test_倒れた敵は数えない(result):
    assert _ok(result, "★倒れた「効く敵」を当てにしない"), result
    assert _ok(result, "★倒れた「効かない敵」で封じない"), result


# --- ★★★ 呪文と同じ規則か（⚠ 2か所に別の式を持たない）---------------

@pytest.mark.parametrize("resist", [0, 3, 6, 7])
def test_呪文と同じ答えになる(result, resist):
    """⚠⚠ **食い違うと片方だけ直ります**（★今日それで何度も踏んだ）。"""
    assert _ok(result, f"★耐性 {resist} で呪文と同じ答え"), result


def test_本物の見積もりを差している():
    """★規則を2か所に持たないため、`bridge` が差し込んでいること。"""
    source = BRIDGE.read_bytes().decode("utf-8")
    assert "self.item_conditions.use(self.damage_estimate)" in source, (
        "⚠⚠ 道具に呪文と同じ規則を差していません")


def test_設定に条件がある(result):
    # ⚠ 2026-08-08 に文言が変わりました（★ へ移したため）。
    #   中身（呪文が効かない敵には使わない）は同じです。
    assert _ok(result, "★まどうしのつえ が「呪文が効かない敵」を避ける"), result
    assert _ok(result, "★いかづちのつえ が「呪文が効かない敵」を避ける"), result
    assert _ok(result, "⚠ 杖を2つとも見つけた"), result


def test_知らない条件を黙って通さない():
    """⚠ 綴り違いで**毎ターン使い続ける**ほうが困ります。"""
    source = COND.read_bytes().decode("utf-8")
    assert "知らない条件です" in source
