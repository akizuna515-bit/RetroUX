"""複数ターンの状態遷移（2026-08-05 / テスト高度化指示書 Test Phase B）。

指示書 §4.1:

    > 1ターン単位では妥当でも、複数ターンを通すと破綻する問題を検出する。

★★ **これが棚卸しで見つかった一番の穴です。** ★★
  ⚠ いままでの Lua テストは**すべて1ターンで完結**していました。
    ★通すと破綻するもの（回復と攻撃の振動 / 予約の持ち越し /
    撃破済みへの追撃）は**1件も検出できていませんでした**。

## 完了条件（指示書 §15 Test Phase B）

  1. エミュレータなしで複数ターンを再現できる
  2. 状態遷移不変条件を検査できる
  3. 異常時に再現データを保存できる

## ⚠ できないシナリオ（★それらしく作らない）

    IT-003 亀の子      防御が未実装（Phase 5・6）
    IT-004 マヌーサ    未実装（Phase 7）
    IT-007 戦術振動    戦術の自動選択が未実装（Phase 5）

  ★通っていないのに「通った」ことにするのが一番まずい形です。
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
           / "multi_turn_test.lua")
SIM = PROJECT_ROOT / "research" / "probes" / "reusable" / "battle_sim.lua"


@pytest.fixture(scope="module")
def result():
    if not (RUNNER.exists() and HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=180,
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
    assert m and int(m.group(1)) >= 15, result


# --- ★ 完了条件1: 実機なしで複数ターン ------------------------------------

def test_エミュレータなしで複数ターン進む(result):
    """★★ 実機もセーブステートも要らないこと。"""
    assert _ok(result, "★複数ターン進んだ"), result


def test_模擬環境はRAMもメニューも知らない():
    """⚠ 知ると実機が要ります（既存の判断層と同じ流儀）。"""
    code = "\n".join(
        line for line in SIM.read_bytes().decode("utf-8").splitlines()
        if not line.strip().startswith("--"))
    for banned in ("joypad", "emu.", "gui.", "savestate"):
        assert banned not in code, f"⚠ {banned} が入っています"


def test_AIは本物を呼んでいる():
    """★★★ **AI を模擬したら、何を試しているのか分からなくなります。**"""
    text = HARNESS.read_bytes().decode("utf-8")
    assert "Bridge._plan_battle_heal(b, m)" in text, "⚠ AI が偽物です"


# --- ★★ 完了条件2: 不変条件（指示書 §4.3）-------------------------------

def test_IT001_予約が次のターンへ残らない(result):
    """★★★ **指示書 §10 IT-001**。

    ⚠ 残ると、回復したつもりのHPで次のターンを判断します。
    """
    assert _ok(result, "★★ 次のターンに予約が残らない"), result
    assert _ok(result, "★★ 不変条件の違反なし"), result


def test_IT008_戦闘終了後に行動しない(result):
    """★★★ **棚卸しで「0件」だった穴**（指示書 §10 IT-008）。

    ⚠ 実機ログに `回復は間に合いませんでした（戦闘が先に終わった）` が
      9件出ており、戦闘終了付近は実際に穴があります。
    """
    assert _ok(result, "★戦闘が終わった"), result
    assert _ok(result, "★★ 戦闘終了後に動かそうとしたら気づく"), result
    assert _ok(result, "★理由が分かる"), result


def test_IT005_MP予約に到達したら呪文をやめる(result):
    """★指示書 §10 IT-005。⚠ 予約ぶんを使い切らないこと。"""
    assert _ok(result, "★★ 予約ぶんのMPを残している"), result


def test_止まらないことに気づく(result):
    """★§4.3「最大ターンを超える停滞を検出する」。"""
    assert _ok(result, "★★ 終わらないことに気づく"), result


def test_無駄な回復に気づく(result):
    """★§8.2「不要な二重回復をしない」の一種。

    ⚠ 満タンの人を回復したら、それは無駄撃ちです。
    """
    assert _ok(result, "★★ 無駄な回復に気づく"), result


# --- ★ 完了条件3: 再現データ（指示書 §13）--------------------------------

def test_異常時に再現データを残せる(result):
    assert _ok(result, "★★ 再現データを書き出せる"), result
    assert _ok(result, "★中身に理由が入っている"), result
    assert _ok(result, "★再実行の仕方が書いてある"), result


def test_異常が無ければ何も残さない(result):
    """⚠⚠ **書くと本物の異常が埋もれます。**"""
    assert _ok(result, "★★ 異常が無ければ何も残さない"), result


def test_再現データはGit管理外():
    """⚠ 調べるための材料で、コミットするものではありません。"""
    text = (PROJECT_ROOT / ".gitignore").read_bytes().decode("utf-8")
    assert "failures/" in text


# --- ⚠ できないシナリオを正直に記録する ----------------------------------

def test_未実装のシナリオを作ったふりをしない():
    """★★★ **通っていないのに「通った」ことにしない。**

    ⚠ 亀の子（IT-003）・マヌーサ（IT-004）・戦術振動（IT-007）は、
      Phase 5〜7 が未実装なので**書けません**。
    ★ハーネスにその旨が書いてあること（あとで読む人のため）。
    """
    text = HARNESS.read_bytes().decode("utf-8")
    for name in ("IT-003", "IT-004", "IT-007"):
        assert name in text, f"⚠ {name} に触れていません"
    assert "それらしく作らない" in text
