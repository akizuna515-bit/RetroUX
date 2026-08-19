"""戦略の型と移行（2026-08-10 / UI整理 Phase 2）。

設計: docs/design/strategy-unification-design.md

★★ ここで固定すること ★★
  ・4戦略と種別（AUTO/FIXED/MANUAL）の対応
  ・AUTO 戦略が既存の Mission へ正しく委譲する
  ・旧 `mission:` からの移行（特に boss_manual → manual）
  ・FIXED（ユーザー指定）の固定行動の構造
"""

from __future__ import annotations

from retroux.core.mission.settings import Mission
from retroux.core.strategy import (ActorFixedAction, FixedAction, Strategy,
                                   StrategySettings, StrategyType,
                                   UserStrategyProfile, from_dict)


# --- 4戦略と種別 ------------------------------------------------------

def test_四戦略だけがある_安全探索は無い():
    """★指示書§2: 戦略は4種。安全探索は設けない。"""
    assert {s.value for s in Strategy} == {
        "leveling", "dungeon", "custom_1", "manual"}
    assert not any("safe" in s.value or "探索" in s.value for s in Strategy)


def test_種別の対応():
    """★指示書§6: AUTO / FIXED / MANUAL。"""
    assert StrategySettings(Strategy.LEVELING).type is StrategyType.AUTO
    assert StrategySettings(Strategy.DUNGEON).type is StrategyType.AUTO
    assert StrategySettings(Strategy.CUSTOM_1).type is StrategyType.FIXED
    assert StrategySettings(Strategy.MANUAL).type is StrategyType.MANUAL


def test_AUTO戦略は既存Missionへ委譲する():
    """★「薄い被せもの」。レベル上げ→grinding、ダンジョン→dungeon。"""
    assert StrategySettings(Strategy.LEVELING).mission is Mission.GRINDING
    assert StrategySettings(Strategy.DUNGEON).mission is Mission.DUNGEON
    # ⚠ FIXED / MANUAL は Mission を持たない
    assert StrategySettings(Strategy.CUSTOM_1).mission is None
    assert StrategySettings(Strategy.MANUAL).mission is None


def test_手動だけAUTOを入れない():
    """★手動は AI を通さない。⚠ FIXED は固定行動を流すので自動側。"""
    assert StrategySettings(Strategy.LEVELING).auto_enabled is True
    assert StrategySettings(Strategy.DUNGEON).auto_enabled is True
    assert StrategySettings(Strategy.CUSTOM_1).auto_enabled is True
    assert StrategySettings(Strategy.MANUAL).auto_enabled is False


def test_AUTOは既存のMissionSettingsに落ちる():
    """★既存の Lua 配線（MissionSettings を渡す）をそのまま使う。"""
    ms = StrategySettings(Strategy.DUNGEON).as_mission_settings()
    assert ms.mission is Mission.DUNGEON
    assert ms.auto_enabled is True
    # ⚠ 手動は auto_enabled=False の Mission（BOSS_MANUAL）に落ちる
    manual = StrategySettings(Strategy.MANUAL).as_mission_settings()
    assert manual.auto_enabled is False


# --- 保存と移行 -------------------------------------------------------

def test_新しい保存キーで往復する():
    s = StrategySettings(Strategy.LEVELING)
    got, notes = from_dict(s.to_yaml_dict())
    assert got.strategy is Strategy.LEVELING
    assert notes == []


def test_旧missionから移行する():
    """★指示書§14: 古い config/mission.yaml を壊さず読む。"""
    got, _ = from_dict({"mission": "grinding"})
    assert got.strategy is Strategy.LEVELING
    got, _ = from_dict({"mission": "dungeon"})
    assert got.strategy is Strategy.DUNGEON


def test_boss_manualは手動へ畳む_黙って畳まない():
    """★★ 依頼者の判断（§3.4）。⚠ default に任せると dungeon になる。★★

    ここが移行の肝。★何を移したかを notes に残す（黙って畳まない）。
    """
    got, notes = from_dict({"mission": "boss_manual"})
    assert got.strategy is Strategy.MANUAL, "★手動へ畳めていない"
    assert any("手動" in n for n in notes), "★移行したことを言っていない"


def test_知らない値は既定にして黙らない():
    got, notes = from_dict({"strategy": "でたらめ"})
    assert got.strategy is Strategy.DUNGEON
    assert notes, "★知らない戦略を黙って既定にしない"


def test_辞書でなくても落ちない():
    got, notes = from_dict(None)
    assert got.strategy is Strategy.DUNGEON
    assert notes


# --- ユーザー指定（FIXED）の構造 --------------------------------------

def test_固定行動の往復():
    prof = UserStrategyProfile(
        id="custom_1", name="ちからのたて",
        actors={
            "lorasia": ActorFixedAction(FixedAction.ATTACK),
            "samaltria": ActorFixedAction(FixedAction.ITEM, "chikara_no_tate"),
            "moonbrooke": ActorFixedAction(FixedAction.ITEM, "chikara_no_tate"),
        })
    got = UserStrategyProfile.from_dict(prof.to_dict())
    assert got.action_for("lorasia").action is FixedAction.ATTACK
    assert got.action_for("samaltria").action is FixedAction.ITEM
    assert got.action_for("samaltria").item == "chikara_no_tate"


def test_未設定のキャラはたたかう():
    """★固定行動が無いキャラは「たたかう」に落ちる（安全側）。"""
    prof = UserStrategyProfile()
    assert prof.action_for("moonbrooke").action is FixedAction.ATTACK


def test_Coreにdq2固有データを持たない():
    """⚠ 指示書§13: Core にアイテム名・キャラ名の**既定データ**を入れない。

    ★構造（空の UserStrategyProfile）だけで、ちからのたて等は持たない。
    """
    prof = UserStrategyProfile()
    assert prof.actors == {}, "★Core に既定の固定行動データを入れない"
