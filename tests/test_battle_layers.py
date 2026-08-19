"""責務の分離（2026-08-04 / 戦闘AI再設計 Phase 2）。

指示書 §18 Phase 2 の完了条件:

  1. 現行AIと判断結果が原則一致
     ★`test_battle_ai_baseline.py::test_新旧の判断が一致する` が担保
  2. **巨大な条件分岐が責務別クラスへ分割されている**  ← ここ
  3. 現行設定ファイルとの互換性を維持
  4. 現行戦術切り替え機能を壊さない

## ⚠⚠ bridge.lua は「減った」のではなく「増えた」

指示書 §21「現行AIを一度に削除しない」に従い、**旧実装を控えとして
残している**ためです。★これは意図した状態で、新旧を比べる期間が
終わったら Phase 10 で控えを消します。

⚠ それまでは**両方を同じハーネスが見張ります**（片方だけ直すと落ちます）。
"""

from __future__ import annotations

import pathlib

import pytest

FCEUX = (pathlib.Path(__file__).resolve().parents[1]
         / "retroux" / "emulator" / "fceux")

#: Phase 2 で切り出したモジュールと、指示書での名前
LAYERS = {
    "actor_decision.lua": "ActorDecisionEngine",
    "party_coordinator.lua": "PartyCoordinator",
    "tactics_commander.lua": "TacticsCommander",
    "battle_assessment.lua": "BattleSituationAnalyzer",
}


def _read(name: str) -> str:
    path = FCEUX / name
    if not path.exists():
        pytest.fail(f"⚠ {name} がありません")
    return path.read_bytes().decode("utf-8")


def _code_only(source: str) -> str:
    """★注意書き（--）を除いたコード行だけ。"""
    return "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("--"))


# --- ★ 完了条件2: 責務別に分かれている ----------------------------------

@pytest.mark.parametrize("name", sorted(LAYERS))
def test_モジュールが存在する(name):
    assert (FCEUX / name).exists(), f"⚠ {name} が無い"


@pytest.mark.parametrize("name", sorted(LAYERS))
def test_指示書のどの役割か書いてある(name):
    """★どの `~Engine` に当たるかを、読めば分かるようにする。"""
    source = _read(name)
    assert LAYERS[name] in source, f"⚠ {name} に役割が書かれていない"


@pytest.mark.parametrize("name", sorted(LAYERS))
def test_RAMもメニューも知らない(name):
    """★★ **これが分離の意味**。⚠ 知ると実機なしで試せなくなります。

    `damage_estimate.lua` / `attack_plan.lua` と同じ流儀です。
    """
    code = _code_only(_read(name))
    for banned in ("memory.read", "joypad", "emu.", "gui."):
        assert banned not in code, f"⚠ {name} に {banned} が入っています"


@pytest.mark.parametrize("name", sorted(LAYERS))
def test_ファイルが大きくなりすぎていない(name):
    """⚠ 分けたのに1つが巨大なら、分けた意味がありません。"""
    lines = len(_read(name).splitlines())
    assert lines < 300, f"⚠ {name} が {lines} 行あります"


# --- ★ 完了条件3・4: 壊していない ---------------------------------------

def test_設定の読み方はbridgeに残っている():
    """★★ **境目をはっきりさせる。**

    ⚠ 判断側がプロフィールの形を知ると、判断を1つ試すのに
      設定ファイルの用意が要ります。
    ★`_healing_policy` が「設定の読み方」を知る唯一の場所です。
    """
    bridge = _read("bridge.lua")
    assert "function Bridge:_healing_policy" in bridge
    # ⚠ 判断側は `_tactic_*` を呼ばないこと
    for name in ("actor_decision.lua", "party_coordinator.lua",
                 "battle_assessment.lua"):
        code = _code_only(_read(name))
        assert "_tactic_" not in code, f"⚠ {name} が設定を直接読んでいます"


def test_旧実装の控えを消してある():
    """★★★ **2026-08-08 に「残す」から「消す」へ変えました**（Phase 10）。

    ## ⚠ もとの意図（指示書 §21「現行AIを一度に削除しない」）は果たしました

      ★Phase 2 で切り出したとき、`bridge.lua` の中に旧実装を控えとして
        残しました。⚠ 移し替えで挙動が変わっていないか比べるためです。

    ## ⚠⚠ しかし、その控えは **production では一度も動きませんでした**

      `load_module` は読み込めないと `error()` を投げます。★nil を返しません。
      だから `if self.actor_decision ~= nil then ... else <控え> end` の
      `else` には**到達できません**。

      ⚠ 同じ規則が2か所にある状態が続くと、★片方だけ直したときに
        黙って食い違います（実際、回復の強化でハーネスが4つ同時に落ちました）。

    ★消してよい根拠と、消したあとの安全網は
      `tests/test_legacy_removal.py` にまとめてあります。
    """
    bridge = _code_only(_read("bridge.lua"))
    for guard in ("if self.actor_decision ~= nil then",
                  "if self.party_coordinator == nil then"):
        assert guard not in bridge, (
            f"⚠ 控えへの分岐が戻っています: {guard}"
            "（★動かないコードなので、消したままにしてください）")


def test_棚卸しに新しい関数が載っている():
    """⚠⚠ 分類漏れがあると「戦闘AIの行数」が黙って減ります。

    ★実際、Phase 2 で足した5関数が「戦闘以外」に数えられていました
      （棚卸しツールの検査が捕まえました）。
    """
    from research.probes.reusable import bridge_inventory as inv

    owner = inv.owners()
    for name in ("_healing_policy", "_actor_in", "_assess_battle",
                 "_resolve_engine", "_use_layered"):
        assert name in owner, f"⚠ {name} が分類されていません"


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
    source = _read("bridge.lua")
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
    source = _read("bridge.lua")
    assert "if not self:_use_layered() then return nil end" in source, (
        "⚠⚠ legacy で指示を返さない仕掛けがありません")


