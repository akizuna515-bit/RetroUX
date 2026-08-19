"""共通エンジンがゲーム固有のものを直接参照しない（Phase 10 / 2026-08-07）。

指示書 §18 Phase 10 の完了条件:

    ★共通エンジンがDQ2固有の敵名・呪文名を直接参照しない
    ★DQ2プラグインが、呪文・道具・敵能力を共通指標へ変換する
    ★将来DQ3、DQ4、Wizardryへ拡張可能な構造になる

## ⚠⚠ いまは**満たしています**。だから固定します

★満たしていない状態を直すより、⚠ **満たしている状態が崩れるのを
止めるほう**が安上がりです。次に誰かが「とりあえずここに書いておこう」
とした瞬間に落ちます。

## ⚠ RAM もメニューも共通層は知りません

★RAM を読むのは `bridge.lua`、意味づけは `plugins/dq2/`。
⚠ 共通層に `memory.read` が入ったら、他のゲームへ持っていけません。
"""

from __future__ import annotations

import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
FCEUX = PROJECT_ROOT / "retroux" / "emulator" / "fceux"

#: ★共通エンジン（⚠ `bridge.lua` は橋渡し役なので**含めません**）
COMMON = [
    "battle_types.lua",
    "battle_assessment.lua",
    "tactics_selector.lua",
    "actor_roles.lua",
    "actor_decision.lua",
    "party_coordinator.lua",
    "tactics_commander.lua",
    "attack_plan.lua",
    "damage_estimate.lua",
    "item_conditions.lua",
]

#: ⚠ DQ2 固有のもの。★増えたらここへ足す。
DQ2_SPECIFIC = [
    # キャラクター名
    "lorasia", "samaltria", "moonbrooke",
    # 敵の名前
    "キラーマシ", "スライム", "サイクロプス", "シルバーデビル",
    # 呪文の名前
    "ホイミ", "ギラ", "ベギラマ", "イオナズン", "マホトーン", "ザラキ",
    "Firebal", "Firebane", "Explodet", "Healmore", "Infernos",
    # 道具の名前
    "まどうしのつえ", "いかづちのつえ", "ちからのたて", "やくそう",
]


def _code_only(path: pathlib.Path) -> str:
    """注釈を落として**コードだけ**にする。

    ⚠ 説明のために名前を出すのは構いません。★禁じたいのは
      **判断がその名前に依存すること**です。
    """
    return "\n".join(
        line for line in path.read_bytes().decode("utf-8").splitlines()
        if not line.strip().startswith("--"))


@pytest.mark.parametrize("name", COMMON)
def test_共通エンジンがゲーム固有の名前を持たない(name):
    """★★★ **これが Phase 10 の完了条件そのもの**。"""
    path = FCEUX / name
    if not path.exists():
        pytest.skip(f"{name} がありません")
    code = _code_only(path)
    found = [w for w in DQ2_SPECIFIC if w in code]
    assert not found, (
        f"⚠⚠ {name} が DQ2 固有の名前を持っています: {found}\n"
        "★ゲーム固有のものは `plugins/dq2/` 側で共通指標へ直してください")


@pytest.mark.parametrize("name", COMMON)
def test_共通エンジンがRAMを読まない(name):
    """⚠⚠ **RAM を読んだら、他のゲームへ持っていけません。**

    ★読むのは `bridge.lua` の仕事です。
    """
    path = FCEUX / name
    if not path.exists():
        pytest.skip(f"{name} がありません")
    code = _code_only(path)
    for banned in ("memory.read", "memory.write", "joypad.", "emu.", "gui."):
        assert banned not in code, (
            f"⚠⚠ {name} が {banned} を使っています（★共通層は実機を知らない）")


def test_検査対象が減っていない():
    """⚠ ファイルを消して検査を通す、をさせない。

    ★「0件は通っていないだけ」と同じ形です。
    """
    live = [n for n in COMMON if (FCEUX / n).exists()]
    assert len(live) >= 10, (
        f"⚠⚠ 共通エンジンのファイルが減っています: {live}")


def test_固有の名前の一覧が痩せていない():
    """⚠⚠ **禁止語を減らして検査を通す**、をさせない。

    ★これも「0件は通っていないだけ」の一種です。
    """
    assert len(DQ2_SPECIFIC) >= 20, (
        "⚠ 禁止語が減っています。★増えることはあっても減りません")
