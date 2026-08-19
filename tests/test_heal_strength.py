"""戦闘の回復を「9割まで戻す」ようにする（2026-08-08 / 依頼者の指摘）。

    > 戦闘時の回復が弱い。９割（満タン設定）を狙うようにしたい。
    > 残り３０なのにホイミを使ったりしている

## ⚠⚠ 原因は**2つ**あった（★片方だけ直しても弱いまま）

1. ⚠ 不足HPを「最大HP × **しきい値**（50%）− 現在HP」で測っていた。
   ★つまり **50% まで戻せば足り**ることになっていた。
2. ⚠⚠ そのうえ呪文は **config の並び順**（ホイミ -> Healmore）で、
   ★唱えられた最初のものを使っていた。不足がいくつでもホイミが先。

## ★ 実機ログ（`work/retroux.log` 2026-08-08 08:20:15）

    回復を確認: moonbrooke の Healmore -> samaltria のHP 29 -> 81（+52）

★HP 29/152 で戻ったのは 81（53%）。⚠ 9割（136）には遠い。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
           / "heal_strength_test.lua")
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"
CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"


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
    assert m and int(m.group(1)) >= 24, result


# --- ★★★ 依頼者の報告そのもの ------------------------------------------

def test_不足が大きいときは強い呪文を選ぶ(result):
    """★★★ **HP 29/152・目標90% -> 不足 107 -> Healmore**。"""
    assert _ok(result, "★★★ 不足 107 なら Healmore が先"), result


def test_足りるときは無駄打ちしない(result):
    """⚠ いつも強い呪文にすると、今度は MP を無駄にします。"""
    assert _ok(result, "★不足 20 ならホイミで足りる"), result
    assert _ok(result, "★不足 32 はホイミで足りる"), result
    assert _ok(result, "★不足 33 は足りないので Healmore"), result


def test_分からない回復量を0と混ぜない(result):
    """⚠⚠ **期待回復が書かれていない呪文を「回復量 0」にしない。**"""
    assert _ok(result, "★★ 分からないものは、足りないと分かっているものより前"), result


def test_不足が分からなければ従来どおり(result):
    """⚠ 推測で並べ替えない（★材料が無いなら設定順）。"""
    assert _ok(result, "⚠ 不足が nil なら設定順のまま"), result


def test_黙って並べ替えない(result):
    """★実機ログで効いているか分かること（⚠ 出ないと確かめようがない）。"""
    assert _ok(result, "★不足量を書く"), result
    assert _ok(result, "⚠ 同じ人・同じ戦闘では繰り返さない"), result
    assert _ok(result, "★設定順のままなら何も出さない"), result


def test_作っただけになっていない(result):
    """⚠⚠ Phase 6 で「部品は通るのに実機で0件」を踏んだ形（引き継ぎ §5 の1番）。"""
    assert _ok(result, "★★★ 回復の計画が並べ替えを通している"), result
    assert _ok(result, "★★ 目標の割合を使っている"), result


# --- ★ 目標は「まんたん」と同じ数字を使う -------------------------------

def test_目標をまんたんの設定から取る(result):
    """⚠ 測り方を2か所に書かない（★依頼者の言葉も「満タン設定」）。"""
    assert _ok(result, "★90% 設定が効く"), result
    assert _ok(result, "⚠ 設定が無ければ 9割"), result
    assert _ok(result, "⚠ 範囲外の設定は既定へ落とす"), result


def test_回復のしきい値と目標が別物であること():
    """★★ **「いつ回復するか」と「どこまで戻すか」は別の数**。

    ⚠ ここを1つの数で兼ねていたのが、回復が弱かった原因の半分です。

    ⚠⚠ **2026-08-12: ここは字面でしか見ていませんでした**（F-089）。
      ★「関数の中に heal_threshold と書いていない」だけなので、
        別の場所から混ぜても**字面は通ります**。
      → 下の `test_しきい値を変えても目標は動かない` が**実際に動かして**
        確かめます。この関数は「配線が消えていない」見張りとして残します。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    assert "function Bridge:_heal_goal_ratio" in source
    # ⚠ 目標が `heal.threshold` から来ていないこと
    at = source.index("function Bridge:_heal_goal_ratio")
    body = source[at:at + 700]
    assert "heal_threshold" not in body, (
        "⚠⚠ 目標に回復開始のしきい値を使っています（★別の数です）")
    assert "target_hp_percent" in body


def test_しきい値を変えても目標は動かない(result):
    """★★ **実際に動かして**、2つの数が独立していることを見ます。

    ⚠ しきい値（25%）を入れても目標は 90% のまま。
      ★逆に、しきい値と同じ値（0.9）を入れても、目標は設定どおり 60%。
    """
    assert _ok(result, "★★ しきい値を変えても目標は動かない（別の数）"), result
    assert _ok(result, "★しきい値が目標と同じ値でも、目標は設定どおり"), result
    assert _ok(result, "⚠ しきい値があっても、目標の既定は 9割"), result


def test_開始のしきい値を勝手に変えていない():
    """⚠ 目標を上げたついでに「いつ回復するか」まで変えない。

    ★変えると 89% で毎ターン回復に動き、⚠ 攻撃しなくなります。
    """
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    heal = (config.get("auto_input") or {}).get("heal") or {}
    assert heal.get("threshold") == 0.5, (
        "⚠ 回復開始のしきい値が変わっています（★依頼者の指示は「目標」のほう）")


# --- ⚠⚠ モンスターIDの門（★依頼者の画面写真 input/cap1.bmp）-------------

def test_IDの規則が読む側と書く側で同じ(result):
    """⚠⚠⚠ **起動のたびに「読めない行が 1 件」と出ていた原因**。

    ★読む側は `1..255` を求め、⚠ 書く側は**何も見ていなかった**。
      DB の空ID（`docs/30-command-log.md` 2026-07-22「188件中178件が空ID」）が
      Python 経由で流れ込み、`work/encountered.txt` の先頭が `0` になっていた。
    """
    assert _ok(result, "★★ 同じ規則を読む側・書く側の両方で使っている"), result
    assert _ok(result, "★壊れた行を書き直す"), result


def test_捨てたことを黙っていない():
    """★「黙って捨てない」（⚠ 何件落としたかは知りたい）。"""
    source = BRIDGE.read_bytes().decode("utf-8")
    assert "dropped out-of-range monster ids" in source
