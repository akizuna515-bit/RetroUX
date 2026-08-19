"""戦術の自動選択（2026-08-06 / 戦闘AI再設計 Phase 5）。

指示書 §9:

    > 戦術は「戦況タグと大目的への適合度」を返すものとして実装する。
    > ★**ユーザーが全組み合わせを手動で紐づける方式にはしない。**

## ★★ §18 Phase 5 の完了条件（★この6つがそのまま検査です）

    弱い雑魚                -> 通常速攻
    ローレシア危険          -> 主力維持
    ダンジョン道中・低脅威  -> 省資源
    高火力紙装甲            -> 脅威除去
    単体強敵                -> 亀の子
    マヌーサ中              -> 呪文攻勢

## ⚠⚠ Phase 5 でも `engine: legacy` なら判断は変わりません

★選んだ戦術を**ログに出すだけ**です。実際に効かせるのは
`engine: layered` にしたときだけ。⚠ Phase 0 の基準（新旧36通り一致）も
そのまま通ります。
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
           / "tactics_selector_test.lua")
MODULE = (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
          / "tactics_selector.lua")
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
    assert m and int(m.group(1)) >= 20, result


# --- ★★★ §18 Phase 5 の完了条件（6つ）----------------------------------

@pytest.mark.parametrize("label", [
    "★1 弱い雑魚 -> 通常速攻",
    "★2 ローレシア危険 -> 主力維持",
    "★3 ダンジョン道中・低脅威 -> 省資源",
    "★4 放置が痛い敵が居る -> 脅威除去",
    "★5 単体強敵・長期戦 -> 亀の子",
    "★6 マヌーサ中 -> 呪文攻勢",
])
def test_代表ケースで正しい戦術が選ばれる(result, label):
    """★★★ **これが Phase 5 の完了条件そのもの**。"""
    assert _ok(result, label), result


def test_守る相手が指示に入る(result):
    """★戦術を名前ひとつで表さない（§10）。"""
    assert _ok(result, "★★ 守る相手が「ローレシア」になる"), result


# --- ★★ 戦術振動を防ぐ（§10 IT-007）------------------------------------

def test_振動よけが効く(result):
    """★★★ **指示書 §10 IT-007**。

    ⚠⚠ 対策が無いと、優勢・均衡の境目で**毎ターン往復**します。
      「通常速攻 → 主力維持 → 通常速攻 …」を繰り返し、
      ★どちらの戦術も中途半端に終わります。
    """
    assert _ok(result, "★★ 振動よけで切り替えが減る"), result


def test_振動テストが空振りしていない(result):
    """⚠⚠ **「どちらも 0 回」を合格にしない**（2026-08-06 に踏んだ）。

    最初の HP（70/62）では境界をまたがず、★**なし 0 / あり 0** でした。
    どちらも切り替わっていないので、**何も確かめていません**。
    → 実際にまたぐ値（75/55）に直しました。
    """
    assert _ok(result, "★★ 振動よけなしでは実際に往復する"), result
    m = re.search(r"振動よけなし (\d+) / あり (\d+)", result)
    assert m, result
    plain, sticky = int(m.group(1)), int(m.group(2))
    assert plain > 0, "⚠ 対策なしで往復していないなら、試せていません"
    assert sticky < plain, f"⚠ 減っていません（{plain} -> {sticky}）"


def test_明確な戦況変化なら切り替わる(result):
    """⚠ 振動よけが強すぎて**何があっても切り替わらない**のは別の壊れ方。"""
    assert _ok(result, "★★ 主力が瀕死なら切り替わる"), result


# --- ⚠⚠ 分からないなら選ばない ------------------------------------------

def test_戦況が分からないなら戦術を決めない(result):
    """★★ **材料が無いのに「通常速攻」と決めると、初見の敵に突っ込みます。**"""
    assert _ok(result, "★★ 分からないのに戦術を決めない"), result


# --- ★ 目的が効く（§5）--------------------------------------------------

def test_目的で選ばれる戦術が変わる(result):
    """★指示書 §5「大目的は判断時の価値基準と制約を変更する」。

    ⚠ 同じ戦況でも、レベル上げなら速攻、ダンジョンなら省資源。
    """
    assert _ok(result, "★★ 目的で選ばれる戦術が変わる"), result


# --- ★ 説明できること（§17）---------------------------------------------

def test_理由と次点が残る(result):
    assert _ok(result, "★理由が残る"), result
    assert _ok(result, "★6つ全部を点数化している"), result
    assert _ok(result, "★次点との差が出せる"), result


def test_できないことを書いてある(result):
    """★★ **通っていないのに「通った」ことにしない。**

    ⚠ 亀の子は**防御が未実装**（Phase 6）なので、指示にその旨が入ります。
    """
    assert _ok(result, "⚠ 防御が未実装だと書いてある"), result


# --- ★ 指示書 §20・§21 ---------------------------------------------------

def test_係数が設定にある():
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    got = (config.get("auto_input") or {}).get("tactics_selector") or {}
    assert got.get("stickiness"), "⚠ 振動よけの大きさが設定にありません"


def test_戦術名で分岐していない():
    """⚠ 指示書 §21「戦術名一つだけで全指示を表現しない」。

    ★各戦術が `score` と `build_directive` を持つ形になっていること。
    """
    source = MODULE.read_bytes().decode("utf-8")
    assert "Selector.PLANS" in source
    for plan_id in ("quick", "protect", "conserve", "threat", "turtle",
                    "spellfire"):
        assert f'plan("{plan_id}"' in source, f"⚠ {plan_id} がありません"


def test_目的を渡さないと中立になることを固定してある(result):
    """⚠⚠ **実機で 24戦中22戦が「通常速攻」でした**（2026-08-06）。

    ★戦術がおかしいのではなく、モンキー用の作戦に**大目的が入って
      いなかった**だけです（`_mission()` が nil → 重みが全部 0.5）。
    ⚠ 振る舞い自体は正しい（0 と不明を混ぜない）ので、
      ★**黙って変わらないようにここへ固定**します。
    """
    assert _ok(result, "★目的ありなら省資源"), result
    assert _ok(result, "⚠ 目的なしだと通常速攻に寄る"), result


def test_モンキー用の作戦に大目的を載せている():
    """⚠⚠ **上の偏りの直接の原因**。★載せ忘れると実機の確認が空振りします。"""
    source = (PROJECT_ROOT / "research" / "probes" / "reusable"
              / "make_tactics_variants.py").read_bytes().decode("utf-8")
    assert source.count("mission=default_mission") == 2, (
        "⚠ 大目的を渡していない render があります")


def test_RAMもメニューも知らない(result):
    assert _ok(result, "⚠ memory%.read を使っていない"), result
    code = "\n".join(
        line for line in MODULE.read_bytes().decode("utf-8").splitlines()
        if not line.strip().startswith("--"))
    for banned in ("memory.read", "joypad", "emu.", "gui."):
        assert banned not in code, f"⚠ {banned} が入っています"


# --- ⚠⚠ Phase 5 でも既定の挙動を変えていない ----------------------------

def test_三層を使う場所を増やしていない():
    """★★★ **Phase 10A で意図的に1か所だけ効かせました**（2026-08-07）。

    ⚠ 以前ここは「0か所であること」を見張っていました。
      ★`engine: layered` のときだけ攻撃呪文を拒否する経路を1本つないだので、
        **0 ではなく 1** が正しい状態です。

    ⚠⚠ **増やさないことが大事です**（★相談回答の最重要指摘）:

        > layered の拒否判定は「行動開始前」だけ行う。

      呪文は「メニュー移動 -> 一覧 -> カーソル -> A -> 敵選択 -> A」と
      **複数フレームにまたがります**。★2か所目を足すと、
      ⚠ 行動の途中で拒否して別の claim が入力する事故が起きます。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    # ⚠ 注釈の中の記述は数えない（★説明で名前を出すのは構わない）
    code = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("--"))
    calls = code.count("self:_may_act(")
    assert calls == 1, (
        f"⚠⚠ 拒否点が {calls} か所あります。★1か所だけにしてください"
        "（行動の途中で拒否すると事故ります）")


def test_既定では挙動を変えていない():
    """⚠⚠ **`engine: legacy` のままなら従来どおり**。

    ★拒否は `_current_directive()` が nil を返すことで止まります。
      ⚠ ここが崩れると、設定を変えていない利用者の挙動が勝手に変わります。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    assert "if not self:_use_layered() then return nil end" in source, (
        "⚠⚠ legacy で指示を返さない仕掛けがありません")


