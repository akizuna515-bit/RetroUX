"""戦略の設定と解決（2026-08-10 / UI整理 Phase 2）。

★★ **保存するのは「どの戦略か」だけ。** ★★

  AUTO 戦略の重みは Mission が持ち、FIXED の固定行動は
  `UserStrategyProfile` が持つ。ここはその2つへ橋渡しする。

⚠ 例外を投げません（`core/mission` と同じ流儀）。読めなければ既定
  （ダンジョン攻略）で動き、理由を返します。
"""

from __future__ import annotations

import dataclasses
import pathlib

from ..mission.settings import Mission, MissionSettings, Risk
from .models import (MISSION_TO_STRATEGY, STRATEGY_MISSION, STRATEGY_TYPES,
                     Strategy, StrategyType)

SCHEMA_VERSION = 1
#: ★保存先。`config/mission.yaml` を引き継ぐ（旧 `mission:` も読める）
USER_PATH = pathlib.Path("config/mission.yaml")


@dataclasses.dataclass(frozen=True)
class StrategySettings:
    """いまの戦略。★既定は「ダンジョン攻略」＝これまでと同じ挙動。"""

    strategy: Strategy = Strategy.DUNGEON
    #: 不確実戦術の許容度（★Mission へ引き継ぐ。Phase 8 で効く）
    risk: Risk = Risk.NORMAL

    @property
    def type(self) -> StrategyType:
        return STRATEGY_TYPES[self.strategy]

    @property
    def mission(self) -> Mission | None:
        """AUTO 戦略が使う Mission。⚠ FIXED/MANUAL は `None`。"""
        return STRATEGY_MISSION.get(self.strategy)

    @property
    def auto_enabled(self) -> bool:
        """AUTO を既定で入れてよいか。

        ★手動だけ False。⚠ FIXED は「固定行動を流す」ので自動側です
          （人が毎ターン押すわけではない）。
        """
        return self.type is not StrategyType.MANUAL

    def as_mission_settings(self) -> MissionSettings:
        """AUTO 戦略を、既存の `MissionSettings` に落とす。

        ★★ ここが「薄い被せもの」の要。既存の Lua 配線
          （`lua_bridge` が MissionSettings を渡す）を**そのまま使う**。

        ⚠ FIXED / MANUAL では Mission が無い。★手動に一番近い
          `BOSS_MANUAL`（auto_enabled=False）を使う。FIXED の実際の行動は
          Phase 4 で別経路（固定行動）から流す。
        """
        mission = self.mission or Mission.BOSS_MANUAL
        return MissionSettings(mission=mission, risk=self.risk)

    def to_yaml_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "strategy": self.strategy.value,
            "risk": self.risk.value,
        }


def from_dict(data, base: StrategySettings | None = None):
    """辞書から戦略設定を作る。戻り値は `(設定, 気づいたことの一覧)`。

    ★★ **旧 `mission:` からの移行**（指示書§14）★★
      新しい保存は `strategy:` だが、古い `config/mission.yaml`
      （`mission: dungeon` など）も壊さず読む。⚠ `boss_manual` は
      `manual` へ畳む（`parse` の default に任せると `dungeon` になる）。

    ⚠ 例外を投げません。
    """
    base = base or StrategySettings()
    notes: list = []
    if not isinstance(data, dict):
        return base, ["設定が辞書ではないので既定で動きます"]

    if "strategy" in data:
        strat = Strategy.parse(data.get("strategy"))
        if strat is None:
            notes.append(
                f"知らない戦略 {data.get('strategy')!r} なので"
                "ダンジョン攻略にします")
            strat = base.strategy
    elif "mission" in data:
        # ★旧ファイルからの移行
        raw = str(data.get("mission"))
        strat = MISSION_TO_STRATEGY.get(raw)
        if strat is None:
            notes.append(f"旧い目的 {raw!r} を移行できないので既定にします")
            strat = base.strategy
        elif raw == "boss_manual":
            notes.append("旧「ボス戦・手動主体」を「手動」に移行しました")
    else:
        strat = base.strategy

    risk = Risk.parse(data.get("risk"), base.risk)
    return StrategySettings(strategy=strat, risk=risk), notes
