"""三層構造の受け皿（2026-08-04 / 戦闘AI再設計 Phase 1）。

指示書 Phase 1 の完了条件:

  1. 新データ構造が追加されている
  2. **現行AIの結果を新構造で表現できる**
  3. 戦闘結果は Phase 0 と同じ（★`test_battle_ai_baseline.py` が見張る）
  4. 新旧ロジックの切り替えフラグを用意する

★★ **Phase 1 では受け皿があるだけで、判断はまだ legacy のままです。** ★★
  ⚠ ここで挙動を変えると、Phase 0 の基準と比べる意味が無くなります。

## ⚠⚠ この段階で入れた「0 と不明を混ぜない」

推計ターンが**出せない**ときに 0 を返すと、
★「0ターンで倒せる」＝**最高の戦況**として扱われます。
だから `nil` を入れ、`unknown` に理由を積みます。

同じ理由で `Balance.UNKNOWN` を `EVEN`（均衡）と別に持ちます。
⚠ 材料が無いのに「互角だから攻める」と判断させないためです。
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
           / "battle_types_test.lua")
MODULE = (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
          / "battle_types.lua")
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
    """⚠ ハーネスの桁揃えに頼らず、行の中に文言があるかで見る。"""
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_ハーネスが全部通る(result):
    assert "NG 0 件" in result, result


def test_検査の数が足りている(result):
    m = re.search(r"OK (\d+) 件", result)
    assert m and int(m.group(1)) >= 40, result


# --- ★ Phase 1 完了条件1: データ構造がある ------------------------------

def test_列挙が揃っている(result):
    assert _ok(result, "戦況の3分類がある")
    assert _ok(result, "戦闘長の3分類")
    assert _ok(result, "大目的の3つ")
    assert _ok(result, "不確実戦術の許容度4段階")


def test_指示書の構造をすべて持っている():
    """★指示書 Phase 1 が名指ししたもの。"""
    source = MODULE.read_bytes().decode("utf-8")
    for name in ("battle_assessment", "mission_profile", "battle_directive",
                 "actor_contribution", "party_plan", "threat_vector",
                 "protection_value"):
        assert f"function Types.{name}" in source, f"⚠ {name} が無い"


# --- ★★ 0 と「分からない」を混ぜない -----------------------------------

def test_分からないと均衡は別物(result):
    """★★★ **このプロジェクトの原則**。

    ⚠ 材料が無いのに「均衡」と言うと、
      「互角だから攻める」という判断が通ってしまいます。
    """
    assert _ok(result, "★★『分からない』と『均衡』は別物")
    assert _ok(result, "既定は『分からない』")


def test_推計ターンは出せなければnil(result):
    """⚠⚠ 0 を返すと「0ターンで倒せる」＝最高の戦況になります。"""
    assert _ok(result, "★推計ターンは nil（0 ではない）")
    assert _ok(result, "⚠ HP が分からなければ nil のまま（0 にしない）")


def test_知らない値を黙って通さない(result):
    """★設定の打ち間違いが黙って別の意味にならないこと。"""
    assert _ok(result, "⚠ 知らない値は nil")
    assert _ok(result, "★呼ぶ側の既定へ落ちる")


# --- ★ Phase 1 完了条件4: 切り替えフラグ --------------------------------

def test_フォールバックはlegacy(result):
    """★未指定・設定が読めない環境は legacy（安全側）。★同梱の明示値とは別。"""
    assert _ok(result, "★★ 既定は legacy（触らなければ従来どおり）")
    assert _ok(result, "同梱の設定は layered")


def test_同梱の設定がlayeredになっている():
    """⚠ ハーネスとは別経路で見る（生成物ではなく yaml を直接）。

    ★2026-08-20 依頼者の指定で既定を layered へ（RX-0089）。
      拒否層は実装済みで作者が常用。フォールバック（未指定/不明名）は legacy のまま。
    """
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    assert (config.get("auto_input") or {}).get("engine") == "layered"


def test_知らないエンジン名は警告してlegacyへ(result):
    """⚠⚠ **黙って別のエンジンで戦わせない。**

    ★設定の打ち間違いは「効かない」ではなく「気づける」が正解です
      （`_resolve_battle_priority` が知らない行動名を警告するのと同じ）。
    """
    assert _ok(result, "⚠ 知らない名前は legacy へ")
    assert _ok(result, "★黙って落とさず警告する")
    source = BRIDGE.read_bytes().decode("utf-8")
    assert "知らない判断エンジン" in source


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


# --- ★ Phase 1 完了条件2: 現行AIの結果を表現できる -----------------------

def test_現行の判断を新構造で表せる(result):
    """★いまの `_plan_battle_heal` の答えを `ActorContribution` にできる。"""
    assert _ok(result, "★回復として表せる")
    assert _ok(result, "★自己回復として表せる")
    assert _ok(result, "★攻撃も表せる")
    assert _ok(result, "★理由が残る")


def test_理由をどの層でも残せる(result):
    """★指示書 §17「全層で理由を残す」。"""
    assert _ok(result, "理由が積める")
    assert _ok(result, "★分からないことがあると確信できない")


# --- ★ 指示書 §21 の禁止事項 --------------------------------------------

def test_総当たりしない(result):
    """⚠ §21「全員分の全行動組み合わせを総当たりしない」。"""
    assert _ok(result, "★上位3件だけ（総当たりしない）")


def test_見積もれない手を捨てない(result):
    """⚠⚠ 捨てると**未知の敵に何もできなくなります**。

    ★点数が出せない手も候補に残し、順番だけ後ろにします。
    """
    assert _ok(result, "★見積もれない手も候補に残す")


def test_行動の許可は空なら全部許可(result):
    """★★ 空を「何も許さない」にすると、指示を書き忘れた瞬間に
    全員が何もしなくなります。⚠ 安全側は「これまでどおり動く」。
    """
    assert _ok(result, "★空なら許可（書き忘れで固まらない）")
    assert _ok(result, "★禁止が最優先")


def test_作戦を名前ひとつで表さない(result):
    """★§10。⚠ 「亀の子」とだけ持つと、誰を守るのかが失われます。"""
    assert _ok(result, "★守る相手を持てる")
    assert _ok(result, "⚠ 眠らせた敵は狙わない")


# --- ★ Core と同じ流儀 ---------------------------------------------------

def test_RAMもメニューも知らない(result):
    """★`damage_estimate.lua` と同じ。⚠ 知ると実機が要ります。"""
    assert _ok(result, "⚠ memory%.read を使っていない")
    source = MODULE.read_bytes().decode("utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("--"))
    for banned in ("memory.read", "joypad", "emu.", "gui."):
        assert banned not in code, f"⚠ {banned} が入っています"


def test_予約はターンをまたがない設計になっている(result):
    """⚠ §7「前ターン・前作戦の予約情報を持ち越さない」。

    ★`PartyPlan` は `turn` を持ち、ターンごとに作り直す前提です。
    """
    source = MODULE.read_bytes().decode("utf-8")
    assert "p.turn = p.turn" in source
    assert "予約はターンをまたがない" in source
    assert _ok(result, "★即死の予約（重ねて撃たない / §15.3）")
    assert _ok(result, "★眠っている敵（§15.4）")



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ **4つのファイル**（test_actor_roles / test_battle_types /
#   test_battle_layers / test_tactics_selector）が、そろって
#
#       assert "if not self:_use_layered() then return nil end" in src
#
#   と書いていました。★同じ主張を4回、しかも**字面で**です。
#   ⚠ `battle_engine` の決め方をひとつ変えれば、この行はそのままで
#     **既定が layered になります**（＝触っていない人の戦い方が変わる）。
#
# ★ここに1本だけ置いて、4ファイルぶんの主張をまとめて確かめます。
# =====================================================================

_ENGINE_HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
                   / "engine_default_test.lua")
_ENGINE_RUNNER = (PROJECT_ROOT / "research" / "probes" / "reusable"
                  / "lua_run.py")


@pytest.fixture(scope="module")
def engine_lua():
    if not (_ENGINE_RUNNER.exists() and _ENGINE_HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(_ENGINE_RUNNER), str(_ENGINE_HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _eng_ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_本物のbridgeでエンジンの既定が全部通る(engine_lua):
    assert "すべて合格" in engine_lua, engine_lua


def test_エンジンの検査の数が足りている(engine_lua):
    count = sum(1 for line in engine_lua.splitlines()
                if line.startswith("OK "))
    assert count >= 17, f"OK が {count} 件しかありません\n{engine_lua}"


def test_既定はlegacy(engine_lua):
    """★★ **触らなければ、これまでとまったく同じ戦い方**。"""
    assert _eng_ok(engine_lua, "★指定が無ければ legacy"), engine_lua
    assert _eng_ok(engine_lua, "★既定では層の判断を使わない"), engine_lua


def test_打ち間違いは警告してlegacy(engine_lua):
    """⚠⚠ **黙って別のエンジンで戦わせない。**

    ★設定の打ち間違いは「効かない」ではなく「**気づける**」が正解です。
    """
    assert _eng_ok(engine_lua, "★打ち間違い（layerd）は legacy"), engine_lua
    assert _eng_ok(engine_lua, "⚠⚠ 打ち間違いは**警告する**"), engine_lua
    assert _eng_ok(engine_lua, "★大文字違いも legacy"), engine_lua


def test_正しい名前では警告しない(engine_lua):
    """⚠ 鳴りすぎも壊れ方（★本当の警告が埋もれます）。"""
    assert _eng_ok(engine_lua, "★正しい名前では警告しない"), engine_lua


def test_legacyのあいだは指示が効かない(engine_lua):
    """★これが「まだ効かせていない」の**実体**です。

    ⚠ 指示（directive）があっても、legacy なら nil を返します。
    """
    assert _eng_ok(engine_lua, "★legacy なら指示は nil"), engine_lua
    assert _eng_ok(engine_lua, "layered なら指示が出る"), engine_lua


def test_型が読めない環境でもlegacyに落ちる(engine_lua):
    """⚠ モジュールが無い環境でも落ちず、安全側（legacy）へ。"""
    assert _eng_ok(engine_lua, "⚠ 型が無ければ legacy（落ちない）"), engine_lua
