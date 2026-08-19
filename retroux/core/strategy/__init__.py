"""戦略（利用者が選ぶ唯一の概念 / 2026-08-10 / UI整理 Phase 2）。

設計: `docs/design/strategy-unification-design.md`

★この層は UI・Lua とも配線済みです（Phase 3・4 完了）。
  UI: `ui/strategy_detail_window.py` `ui/view_model.py` / Lua: `command.json` 経由。

⚠ 2026-08-12 訂正: ここには「**まだ配線していません**」と書いてありました。
"""

from .models import (ActorFixedAction, FixedAction, MISSION_TO_STRATEGY,
                     STRATEGY_LABELS, STRATEGY_MISSION, STRATEGY_NOTES,
                     STRATEGY_TYPES, Strategy, StrategyType,
                     UserStrategyProfile)
from .settings import StrategySettings, from_dict

__all__ = [
    "Strategy", "StrategyType", "FixedAction", "ActorFixedAction",
    "UserStrategyProfile", "StrategySettings", "from_dict",
    "STRATEGY_LABELS", "STRATEGY_NOTES", "STRATEGY_TYPES",
    "STRATEGY_MISSION", "MISSION_TO_STRATEGY",
]
