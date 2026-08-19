"""戦況の見立て（2026-08-05 / 戦闘AI再設計 Phase 4）。

指示書 §18 Phase 4 の完了条件:

  1. 代表ケースで人間の感覚と大きく外れない
  2. **高火力・低HP敵が優先される**
  3. **高HP・低火力敵が後回しになる**
  4. 主火力・回復役の保護価値が算出される
  5. 理由ログに推計値が出る

## ★★ 「脅威度順」ではありません（指示書 §7）

    攻撃優先度 = その敵を残した場合の損失 × **今排除できる可能性**

⚠ 単純な脅威度順にすると、★「固くて痛い敵」を延々殴ることになります。
  倒しやすさを掛けるから「高火力・低HP」が先に来ます。

⚠⚠ 指示書 §7 末尾:
  > 「ヒーラーは常に最優先」といった固定ルールにはしない。

## ⚠⚠ Phase 4 では**判断を変えていません**

見立てるだけです。★`engine: legacy` のままなら、これまでと同じ動きです。
戦術の自動選択は Phase 5、実際に狙う順へ効かせるのはその後です。
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
           / "assessment_test.lua")
MODULE = (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
          / "battle_assessment.lua")
CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"
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
    assert m and int(m.group(1)) >= 25, result


# --- ★★★ 完了条件2・3: 狙う順 -------------------------------------------

def test_高火力低HPの敵を先に狙う(result):
    """★★★ **Phase 4 の一番の要求**。"""
    assert _ok(result, "★★ 高火力・低HP を先に狙う"), result
    assert _ok(result, "★★ 高耐久・低火力は後回し"), result


def test_ヒーラーを常に最優先にしない(result):
    """⚠⚠ 指示書 §7 末尾:

    > 「ヒーラーは常に最優先」といった固定ルールにはしない。

    ★固いヒーラーより、1ターンで倒せる高火力敵が先になります。
    """
    assert _ok(result, "★★ 固いヒーラーより、すぐ倒せる高火力が先"), result
    # ★ただし同じ強さなら回復する敵が先
    assert _ok(result, "★★ 同じ強さなら回復する敵が先"), result


# --- ★ 完了条件1・5: 推計と理由 -------------------------------------------

def test_推計ターンと戦況が出る(result):
    assert _ok(result, "★敵撃破の推計が出る"), result
    assert _ok(result, "★★ 優勢と分かる"), result
    assert _ok(result, "★★ 劣勢と分かる"), result


def test_理由ログに推計値が出る(result):
    """★完了条件5。⚠ 数字が出ないと、なぜそう見立てたか追えません。"""
    assert _ok(result, "★★ 理由ログに推計値が出る"), result


def test_戦闘の長さを分類する(result):
    assert _ok(result, "★短期戦"), result
    assert _ok(result, "★長期戦"), result


# --- ★ 完了条件4: 保護価値 -----------------------------------------------

def test_保護価値が算出される(result):
    assert _ok(result, "★★ HPが低い人ほど危ない"), result
    assert _ok(result, "★主火力のほうが失う損が大きい"), result


# --- ⚠⚠ 0 と「分からない」を混ぜない ------------------------------------

def test_材料が無いのに均衡と言わない(result):
    """★★★ **このプロジェクトの原則**。

    ⚠ 図鑑に無い敵しか居ないのに「均衡」と言うと、
      「互角だから攻める」という判断が通ってしまいます。
    """
    assert _ok(result, "★★ 材料が無いのに均衡と言わない"), result
    assert _ok(result, "★分からないことを持っている"), result


def test_見立てられない敵を捨てない(result):
    """⚠⚠ 捨てると**初見の敵に何もできなくなります**。

    ★点数は `nil`（0 ではない）で、順番だけ後ろへ回します。
    """
    assert _ok(result, "★見立てられない敵も候補に残る"), result
    assert _ok(result, "⚠ 点数は nil（0 ではない）"), result


# --- ★ 指示書 §20: 係数を設定へ ------------------------------------------

def test_係数がコードに散っていない():
    """★指示書 §20「係数をコードへ散在させない」。"""
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    got = (config.get("auto_input") or {}).get("assessment") or {}
    for key in ("party_damage_per_turn", "enemy_damage_ratio",
                "balance_margin", "short_turns", "long_turns"):
        assert key in got, f"⚠ {key} が設定にありません"
    assert (got.get("threat") or {}).get("healer_weight")


def test_境目に幅がある():
    """⚠⚠ **戦術振動を防ぐため**（§10 IT-007）。

    ★`balance_margin` が 0 だと、HPが1減るたびに優勢と劣勢を往復します。
    """
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    margin = ((config.get("auto_input") or {}).get("assessment")
              or {}).get("balance_margin")
    assert margin and margin > 0, "⚠ 境目に幅がないと毎ターン往復します"


# --- ★ Core と同じ流儀 ---------------------------------------------------

def test_RAMもメニューも知らない(result):
    assert _ok(result, "⚠ memory%.read を使っていない"), result
    code = "\n".join(
        line for line in MODULE.read_bytes().decode("utf-8").splitlines()
        if not line.strip().startswith("--"))
    for banned in ("memory.read", "joypad", "emu.", "gui."):
        assert banned not in code, f"⚠ {banned} が入っています"


# --- ⚠⚠ Phase 4 では判断を変えていない ----------------------------------

def test_見立てを狙う順にはまだ使っていない():
    """★★ **見立ては狙う順にはまだ効かせていません**。

    ⚠ Phase 10A で効かせたのは `attack_spell` の**拒否だけ**です。
      ★狙う順（`target_order`）へ効かせるのはこの先です。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    # ★★★ **Phase 10A で意図的に1か所だけ効かせました**（2026-08-07）。
    #   ⚠ 以前ここは「0か所であること」を見張っていました。
    #   ★拒否点は1か所だけ（⚠ 増やすと行動の途中で拒否して事故ります）。
    code = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("--"))
    assert code.count("self:_may_act(") == 1, (
        "⚠⚠ 拒否点が1か所ではありません。★行動の途中で拒否すると事故ります")
    # ⚠ 狙う順（`_claim_target_selection`）が見立てを使っていないこと
    start = source.index("function Bridge:_claim_target_selection")
    # ⚠ 次の関数の手前までを見る（★`\nend\n` は改行コードに依存する）
    end = source.find("function Bridge:", start + 10)
    region = source[start:end if end > 0 else len(source)]
    assert "target_order" not in region, (
        "⚠⚠ 狙う順に見立てを使っています。★それは Phase 5 以降です")


def test_1つの数値にまとめていない():
    """★指示書 §7「敵脅威度は一つの固定値にまとめすぎない」。

    ⚠ 「脅威度 8」では、なぜ優先するのかが説明できません。
    """
    source = MODULE.read_bytes().decode("utf-8")
    assert "threat_vector" in source
    for field in ("direct_damage", "healing", "disable", "durability"):
        assert field in source, f"⚠ {field} を分けて持っていません"
