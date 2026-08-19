"""大目的（2026-08-05 / 戦闘AI再設計 Phase 3）。

指示書 §4:

    メイン画面では、ユーザーが大目的をラジオボタン等で選択できるようにする。
      ・レベル上げ・稼ぎ
      ・ダンジョン攻略
      ・ボス戦・手動主体

★★ **大目的から戦術を直接固定してはならない**（指示書 §5）★★

    誤: レベル上げ -> 常に速攻 -> 常にMP温存しない
    正: レベル上げ -> **時間の価値が高く、MP の価値が低い**

⚠ 同じ「レベル上げ」でも、明らかな劣勢なら防御・回復・AUTO解除を
  選べること。★ここは**価値基準**であって命令ではありません。
"""

from .settings import (
    MISSION_LABELS,
    RISK_LABELS,
    MissionSettings,
    Mission,
    Risk,
)
from .repository import load, save

__all__ = [
    "MISSION_LABELS", "RISK_LABELS", "MissionSettings", "Mission", "Risk",
    "load", "save",
]
