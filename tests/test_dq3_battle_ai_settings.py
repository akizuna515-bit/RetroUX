"""戦闘 AI の設定の形（RX3-0198 / 2026-09-12）。

★画面の名前は「最短撃破」（⚠ 内部の語 leveling は保つ / RX3-0198 → RX3-0327）/ 作戦の意味の表 /
★MP制約の名前 / 人が決めた役割は第1・第2 を別々に（`battle_ai.v2`・`v1` から移し替え）。
"""
from __future__ import annotations

from dq3.battle_ai import settings as S


def test_作戦の名前は最短撃破_内部の語は保つ():
    assert S.STRATEGY_LABELS == {S.LEVELING: "最短撃破", S.ECONOMY: "リソース節約", S.SURVIVAL: "生存優先"}
    assert S.LEVELING == "leveling", "⚠ 内部の語を変えると保存した設定と Lua が読めなくなる"
    shown = list(S.STRATEGY_LABELS.values()) + list(S.STRATEGY_NOTES.values()) + list(S.MP_LABELS.values())
    assert not [t for t in shown if "レベル上げ" in t]


def test_MP制約の名前():
    assert [S.MP_LABELS[p] for p in S.MP_POLICIES] == ["おまかせ", "半分程度残す", "使用禁止"]
    assert (S.MP_AUTO, S.MP_SAVE, S.MP_FORBID) == ("auto", "save", "forbid"), "⚠ 内部の語は保つ"
    assert set(S.MP_NOTES) == set(S.MP_POLICIES)


def test_作戦の意味の表は3作戦とも5行():
    assert S.BEHAVIOR_ROWS == ("攻撃魔法", "回復", "支援", "MP消費", "狙う敵")
    assert set(S.STRATEGY_BEHAVIOR) == set(S.STRATEGIES)
    assert all(len(v) == len(S.BEHAVIOR_ROWS) for v in S.STRATEGY_BEHAVIOR.values())
    assert S.STRATEGY_BEHAVIOR[S.ECONOMY][0] == "必要な時だけ", "⚠ リソース節約は「魔法禁止」ではない"


def test_欄ごとに人が決めて往復する():
    v = S.BattleAiSettings().with_tier("p2", S.FIRST, S.HEAL)
    assert v.is_touched("p2", S.FIRST) and not v.is_touched("p2", S.SECOND) and v.is_touched("p2")
    data = v.to_json()
    assert data["touched"] == {"p2": ["first"]}
    back = S.BattleAiSettings.from_json(data)
    assert back == v


def test_v1の枠は両方の欄を人が決めたとみなす():
    """⚠ v1 は第1・第2 をまとめて覚えていた（`with_role` が両方書いた）。"""
    back = S.BattleAiSettings.from_json({"strategy": "leveling", "roles": {"p1": ["physical", "defend"]},
                                         "touched": ["p1", "zz"]})
    assert back.touched == (("p1", "first"), ("p1", "second"))
    assert back.strategy == S.LEVELING


def test_v2が無ければv1から読み_書くのはv2(tmp_path):
    from dq3.ui.ui_settings import UiSettings

    us = UiSettings(tmp_path / "ui.json")
    us.set(S.SECTION, "v1", {"strategy": "survival", "mp_policy": "save",
                             "roles": {"p1": ["heal", "support"]}, "touched": ["p1"]})
    got = S.load(UiSettings(tmp_path / "ui.json"))
    assert got.strategy == S.SURVIVAL and got.is_touched("p1", S.SECOND)
    S.save(us, got.without_tier("p1", S.SECOND))
    again = UiSettings(tmp_path / "ui.json")
    assert again.get(S.SECTION, "v1")["touched"] == ["p1"], "⚠ 古い版に戻したときの v1 を消した"
    assert S.load(again).touched == (("p1", "first"),)


def test_提案と人の値を欄ごとに合わせる(monkeypatch):
    monkeypatch.setattr(S, "suggest_roles", lambda members, rom_path=None: {
        "p1": S.RolePref(S.HEAL, S.SUPPORT), "p2": S.RolePref(S.MAGIC, S.HEAL)})
    v = S.BattleAiSettings().with_tier("p1", S.FIRST, S.PHYSICAL).with_tier("p2", S.SECOND, S.DEFEND)
    got = S.effective_roles(v, [{"slot": "p1"}, {"slot": "p2"}])
    assert got["p1"] == S.RolePref(S.PHYSICAL, S.SUPPORT), "⚠ 触っていない第2 が提案に付いていかない"
    assert got["p2"] == S.RolePref(S.MAGIC, S.DEFEND)
    assert got["p3"] == S.RolePref(S.PHYSICAL, S.DEFEND), "⚠ 提案が無い枠の既定"


def test_人が決めていない欄の値は使わない(monkeypatch):
    """⚠ 保存に値が残っていても、touched に無い欄は提案（★手で直した設定・古い形でも Lua とずれない）。"""
    monkeypatch.setattr(S, "suggest_roles", lambda members, rom_path=None: {
        "p1": S.RolePref(S.HEAL, S.SUPPORT)})
    v = S.BattleAiSettings.from_json({"roles": {"p1": ["physical", "defend"]},
                                      "touched": {"p1": ["first"]}})
    assert S.effective_roles(v, [{"slot": "p1"}])["p1"] == S.RolePref(S.PHYSICAL, S.SUPPORT)


def test_欄を戻す_全員を戻す():
    v = S.BattleAiSettings().with_role("p1", S.PHYSICAL, S.DEFEND)
    one = v.without_tier("p1", S.FIRST)
    assert one.touched == (("p1", "second"),) and one.role_of("p1") == S.RolePref(None, S.DEFEND)
    none = one.without_tier("p1", S.SECOND)
    assert none.touched == () and "p1" not in none.roles
    assert v.without_roles() == S.BattleAiSettings()
    assert v.with_tier("p9", S.FIRST, S.HEAL) == v and v.with_tier("p1", "third", S.HEAL) == v


# ======================================================================
# ★実効の MP 制約（RX3-0327 / 依頼者 §3）
# ======================================================================
def test_最短撃破ではMP制約を渡さない():
    """★依頼者「最短撃破では おまかせ / 半分程度残す / 使用禁止 を無視する」。"""
    for policy in S.MP_POLICIES:
        assert S.effective_mp(S.LEVELING, policy) == S.MP_AUTO, policy


def test_ほかの作戦ではMP制約をそのまま渡す():
    for strategy in (S.ECONOMY, S.SURVIVAL):
        for policy in S.MP_POLICIES:
            assert S.effective_mp(strategy, policy) == policy


def test_保存値は書き換えない():
    """⚠⚠ 渡す値だけ差し替える（★作戦を往復しても人の選択が消えない / 依頼者 §3-1）。"""
    value = S.BattleAiSettings().with_strategy(S.LEVELING).with_mp(S.MP_FORBID)
    assert value.mp_policy == S.MP_FORBID, "⚠ 保存値まで書き換えている"
    assert S.effective_mp(value.strategy, value.mp_policy) == S.MP_AUTO
    # ★戻したら元どおり
    back = value.with_strategy(S.ECONOMY)
    assert S.effective_mp(back.strategy, back.mp_policy) == S.MP_FORBID


def test_MP制約の欄を触れるかは1か所で決める():
    assert not S.mp_is_used(S.LEVELING)
    assert S.mp_is_used(S.ECONOMY) and S.mp_is_used(S.SURVIVAL)
    assert S.MP_FREE_STRATEGIES == (S.LEVELING,)
