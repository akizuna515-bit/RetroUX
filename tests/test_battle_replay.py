"""AI回帰テスト（2026-08-08 / 資産化 指示書 §18 Phase 5・§14・§15）。

    > Replayable / Golden Case を AI エンジンへ投入し、
    > **ゲームを起動せずに**判定する。

## ★★★ ここが「AIを育てる」の中身です

ログを貯める → ケースになる → ★**このテストが劣化を見張る**。

## ⚠⚠ 再生できないもの（★正直に書きます）

「たたかう / 呪文 / 道具」の**最終的な選択**は再生できません。
★あれは `bridge.lua` の claim が RAM とメニューを見て決めます。
⚠ ここで「できる」ことにすると、**通っていない道を通ったことに**なります。

★再生できるのは、その手前の層です:

    BattleAssessment / BattleDirective / ActorRole /
    allowed・prohibited action types / 回復の狙い先 / 補助行動の候補

## ★ `Bridge.new` を通しません

⚠ あちらは `events.jsonl` と `retroux.log` を**開いて追記**します。
★このテストは読むだけなので、人が遊んでいる最中でも安全です。
"""

from __future__ import annotations

import json
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN_DIR = PROJECT_ROOT / "tests" / "data" / "battle_cases"

from retroux.tools import battle_replay as replay  # noqa: E402

#: ★実機の1件（⚠ 作り話ではありません / 2026-08-08 の b4_t3_samaltria）
REAL_STATE = {
    "turn": 3,
    "actor": "samaltria",
    "party": [
        {"id": "lorasia", "index": 0, "hp": 98, "max_hp": 188,
         "mp": 0, "max_mp": 0, "alive": True, "attack": 211},
        {"id": "samaltria", "index": 1, "hp": 70, "max_hp": 159,
         "mp": 112, "max_mp": 112, "alive": True, "attack": 75},
        {"id": "moonbrooke", "index": 2, "hp": 84, "max_hp": 146,
         "mp": 163, "max_mp": 163, "alive": True, "attack": 50},
    ],
    "enemies": [
        {"slot": 0, "monster_id": 76, "hp": 54},
        {"slot": 1, "monster_id": 76, "hp": 4},
    ],
    "monster_ids": [76, 76, 76],
}


def _case(**over) -> dict:
    case = {"schema_version": 1, "case_type": "replayable",
            "case_id": "test", "state": REAL_STATE,
            "strategy": {"engine": "layered"}, "expected": None}
    case.update(over)
    return case


@pytest.fixture(scope="module")
def base():
    got = replay.run_case(_case())
    if "error" in got:
        pytest.skip(f"Lua を動かせない環境: {got['error'][:120]}")
    return got


# --- ★ AI が実際に動くこと ----------------------------------------------


def test_ゲームを起動せずにAIが動く(base):
    """★★★ **これが Phase 5 の本題**（指示書 §14）。"""
    assert base.get("balance") not in (None, "unknown"), base
    assert base.get("plan"), base


def test_図鑑から敵の能力を補う(base):
    """★ケースには `monster_id` しか入っていません（指示書 §11.4）。

    ⚠ 補えないと戦況が「分からない」になります。
    """
    assert base.get("unknown_enemies") == "0", base


def test_再生できないものを黙っていない(base):
    """⚠⚠ **「できる」ことにしない。**

    ★最終的な行動の選択は RAM とメニューを見る claim の担当です。
    """
    assert "not_replayed" in base
    assert "最終的な行動の選択" in base["not_replayed"]


# --- ★★★ §14.2 禁止結果 -----------------------------------------------


def test_省資源は攻撃呪文を禁じる():
    """★★★ **Phase 10A で実際に効かせている唯一の拒否**。

    ⚠ ここが崩れると、MPを温存する意味が無くなります。
    """
    got = replay.run_case(_case(), {"plan": "conserve"})
    assert got.get("may_act.attack_spell") == "false", got
    # ★全部禁じては戦えません
    assert got.get("may_act.heal") == "true", got
    assert got.get("may_act.item") == "true", got


def test_他の戦術は攻撃呪文を禁じない():
    """⚠ 「いつも禁じている」なら、★省資源の意味がありません。

    ⚠⚠ **「0件は通っていないだけ」の逆**: 禁じる側だけ見ると、
      **常に禁じている**壊れ方に気づけません。
    """
    for plan in ("quick", "spellfire", "protect"):
        got = replay.run_case(_case(), {"plan": plan})
        assert got.get("may_act.attack_spell") == "true", (plan, got)


# --- ★★★ §14 target ----------------------------------------------------


def test_いちばん減っている人を回復する(base):
    """★この場面:

        lorasia    98/188 = 52%
        samaltria  70/159 = 44%   <- ★いちばん減っている
        moonbrooke 84/146 = 58%
    """
    assert base.get("heal_target") == "samaltria", base


# --- ★★★ §15 反実仮想（★戦術だけ変えて比べる）-------------------------


def test_戦術を変えると資源の方針が変わる():
    """★★ 指示書 §15「戦術差の確認に非常に有効」。

    ⚠⚠ **全部同じ答えなら、戦術を切り替える意味がありません。**
    """
    got = {}
    for plan in replay.PLANS:
        r = replay.run_case(_case(), {"plan": plan})
        got[plan] = r.get("resource_policy")
    # ★少なくとも3種類に分かれること
    assert len(set(got.values())) >= 3, got
    assert got["conserve"] == "preserve_mp", got
    assert got["spellfire"] == "allow_mp", got


def test_同じ場面で戦術を差し替えられる():
    """⚠ 差し替えが効かないと、★反実仮想テストが**空振り**します。"""
    a = replay.run_case(_case(), {"plan": "conserve"})
    b = replay.run_case(_case(), {"plan": "spellfire"})
    assert a.get("plan") == "conserve"
    assert b.get("plan") == "spellfire"
    assert a.get("resource_policy") != b.get("resource_policy")


def test_知らない戦術を黙って通さない():
    """⚠ 綴り違いで「効いているつもり」になるのが一番困ります。"""
    got = replay.run_case(_case(), {"plan": "なぞの戦術"})
    assert "error" in got or got.get("error"), got


# --- ★★ golden ケース（指示書 §13）--------------------------------------


def _golden_files() -> list:
    return sorted(GOLDEN_DIR.glob("*.json"))


def test_goldenがある():
    """★人が見て「これは正解」と決めたケース。"""
    assert _golden_files(), (
        f"⚠ golden がありません: {GOLDEN_DIR}")


@pytest.mark.parametrize("path", _golden_files(), ids=lambda p: p.name)
def test_goldenが通る(path):
    """★★★ **これが AI の劣化を見張ります**。"""
    case = json.loads(path.read_text(encoding="utf-8"))
    passed, problems = replay.check_case(case)
    if passed is None:
        pytest.skip(problems[0])
    assert passed, "\n".join(problems)


def test_goldenは人が決めたと分かる():
    """⚠⚠ **自動で作らない**（★原則1）。

    ★出どころに「人が見て決めた」印があること。
    """
    for path in _golden_files():
        case = json.loads(path.read_text(encoding="utf-8"))
        prov = case.get("provenance") or {}
        assert prov.get("promoted_by") == "human_review", (
            f"⚠ {path.name} に人が決めた印がありません"
            "（★実戦の行動を自動で正解にしていませんか）")
        assert case.get("note"), (
            f"⚠ {path.name} に**なぜ正解なのか**が書かれていません")


def test_判定が空振りしていない():
    """⚠⚠ **「0件は通っていないだけ」**（★このプロジェクトの作法3）。

    ★わざと嘘の期待値にして、**NG が出ること**を確かめます。
    """
    files = _golden_files()
    if not files:
        pytest.skip("golden が無い")
    case = json.loads(files[0].read_text(encoding="utf-8"))
    case.setdefault("expected", {})
    # ⚠ ありえない期待値
    case["expected"] = dict(case["expected"])
    case["expected"]["plan"] = "ありえない戦術"
    passed, problems = replay.check_case(case)
    assert passed is False, "⚠⚠ 嘘の期待値でも通っています（★検査が空振り）"
    assert problems


# --- ⚠ 人が遊んでいる最中でも安全 ----------------------------------------


def test_Bridgeを組み立てない():
    """⚠⚠ `Bridge.new` は `events.jsonl` と `retroux.log` を**開いて追記**し、
    `encountered.txt` を消して作り直します。

    ★このテストが集めているログを汚さないこと。
    """
    source = (PROJECT_ROOT / "research" / "probes" / "reusable"
              / "replay_case.lua").read_bytes().decode("utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("--"))
    assert "Bridge.new" not in code, (
        "⚠⚠ `Bridge.new` を通しています（★遊んでいる最中に回せません）")
    assert "bridge.lua" not in code
