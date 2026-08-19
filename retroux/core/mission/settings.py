"""大目的の値（2026-08-05 / 戦闘AI再設計 Phase 3）。

★★ **ここが唯一の出典です。** ★★
  画面・保存・Lua への受け渡しが、この1つの表を見ます。
  ⚠ 3か所に別々に書くと、片方だけ直したときに黙って食い違います。

## ⚠⚠ 係数をコードへ散らさない（指示書 §20）

  > 係数をコードへ散在させない / 設定ファイルから調整可能にする

  ★既定値はここに置きますが、`config/mission.yaml` で上書きできます。
"""

from __future__ import annotations

import dataclasses
import enum
import pathlib

#: 利用者の設定の置き場（`config/mantan.yaml` と同じ流儀）
USER_PATH = pathlib.Path("config/mission.yaml")

#: 設定の形式の版
SCHEMA_VERSION = 1


class Mission(str, enum.Enum):
    """大目的（指示書 §4）。"""

    GRINDING = "grinding"          # レベル上げ・稼ぎ
    DUNGEON = "dungeon"            # ダンジョン攻略
    BOSS_MANUAL = "boss_manual"    # ボス戦・手動主体

    @classmethod
    def parse(cls, value, default=None):
        """⚠ 知らない値には `default` を返す（黙って別の目的にしない）。"""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


MISSION_LABELS = {
    Mission.GRINDING: "レベル上げ・稼ぎ",
    Mission.DUNGEON: "ダンジョン攻略",
    Mission.BOSS_MANUAL: "ボス戦・手動主体",
}

#: 画面のツールチップに出す説明（★何が変わるかを書く）
MISSION_NOTES = {
    Mission.GRINDING:
        "戦闘時間を短くします。★MPの予約をゆるめ、雑魚戦を早く終わらせます。\n"
        "⚠ 宿屋までMPが持たないことがあります。",
    Mission.DUNGEON:
        "生き延びることを優先します。★MPと道具を手元に残します。\n"
        "軽い時間短縮より、宿屋まで持つことを優先します。",
    Mission.BOSS_MANUAL:
        "★★ AUTO を既定で OFF にします（自分で戦うため）。\n"
        "⚠ AUTO を入れれば戦えますが、想定外の状態では手動へ戻します。",
}


class Risk(str, enum.Enum):
    """不確実戦術の許容度（指示書 §16）。

    ⚠⚠ 名前は「状態異常使用度」ではありません。
      ★成功率100%の即死・停止は**不確実ではない**ので、
        `DISABLED` でも通常どおり評価します。
    """

    DISABLED = "disabled"
    CAUTIOUS = "cautious"
    NORMAL = "normal"
    BOLD = "bold"

    @classmethod
    def parse(cls, value, default=None):
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


RISK_LABELS = {
    Risk.DISABLED: "使用しない",
    Risk.CAUTIOUS: "慎重",
    Risk.NORMAL: "標準",
    Risk.BOLD: "大胆",
}

#: 目的ごとの価値基準（指示書 §18 Phase 3 の例）。
#
# ★★ **これは「命令」ではなく「重み」です**（指示書 §5）。 ★★
#   ⚠ 「レベル上げ = 常に速攻」ではありません。劣勢なら守りに回れること。
#
# ⚠⚠ **Phase 3 で実際に効くのは下の3つだけ**です:
#     ・`auto_enabled`      … ボス目的で AUTO を既定 OFF
#     ・`mp_reserve_scale`  … MPの予約をどれだけ尊重するか
#     ・`risk`              … 不確実戦術の許容度（★渡すだけ / Phase 8 で効く）
#   残りの重みは **Phase 4（戦況分析）以降**で使います。
#   ★いま渡しておくのは、Lua 側のログに出して確かめられるようにするためです。
MISSION_PRESETS = {
    Mission.GRINDING: {
        "time_value": 1.0,
        "survival_value": 0.5,
        "mp_value": 0.3,
        "item_value": 0.5,
        "post_battle_recovery_value": 0.3,
        "wipe_cost": 0.4,
        # ★MPの予約を**ゆるめる**（時間を優先する）
        #   ⚠ 0 にはしません。ルーラ・リレミトぶんまで使い切ると
        #     ★ダンジョンから出られなくなります。
        "mp_reserve_scale": 0.5,
        "auto_enabled": True,
    },
    Mission.DUNGEON: {
        "time_value": 0.5,
        "survival_value": 1.0,
        "mp_value": 1.0,
        "item_value": 1.0,
        "post_battle_recovery_value": 1.0,
        "wipe_cost": 1.0,
        # ★これまでどおり（★既定の目的なので、挙動を変えない）
        "mp_reserve_scale": 1.0,
        "auto_enabled": True,
    },
    Mission.BOSS_MANUAL: {
        "time_value": 0.3,
        "survival_value": 1.0,
        "mp_value": 0.2,
        "item_value": 0.2,
        "post_battle_recovery_value": 0.2,
        "wipe_cost": 1.0,
        # ★ボスでは温存しない（全力投入 / 指示書 §4.3）
        "mp_reserve_scale": 0.0,
        # ★★ **AUTO を既定 OFF**（指示書 Phase 3 完了条件）
        "auto_enabled": False,
    },
}

#: `mp_reserve_scale` の範囲。⚠ 1 を超えると予約が増えて呪文を使わなくなる
MP_SCALE_MIN, MP_SCALE_MAX = 0.0, 1.0


@dataclasses.dataclass(frozen=True)
class MissionSettings:
    """いまの大目的。★既定値のままで動きます。"""

    #: 大目的。★既定は「ダンジョン攻略」＝**これまでと同じ挙動**
    #
    # ⚠ `GRINDING` を既定にすると、触っていない人のMP温存が
    #   勝手にゆるみます（★既定は挙動を変えないほうを選ぶ）。
    mission: Mission = Mission.DUNGEON
    #: 不確実戦術の許容度（★Phase 8 で効きます。いまは渡すだけ）
    risk: Risk = Risk.NORMAL

    @property
    def preset(self) -> dict:
        """この目的の価値基準。"""
        return dict(MISSION_PRESETS[self.mission])

    @property
    def auto_enabled(self) -> bool:
        """AUTO を既定で入れてよいか（★ボス目的は False）。"""
        return bool(self.preset["auto_enabled"])

    @property
    def mp_reserve_scale(self) -> float:
        """MPの予約をどれだけ尊重するか（1.0 = そのまま）。"""
        return float(self.preset["mp_reserve_scale"])

    def to_yaml_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "mission": self.mission.value,
            "risk": self.risk.value,
        }

    def to_lua_dict(self) -> dict:
        """Lua が読む形。★名前はここだけで決めます。"""
        got = {"mission": self.mission.value, "risk": self.risk.value}
        got.update(self.preset)
        return got


def label(settings: MissionSettings) -> str:
    """画面に出す1行。"""
    name = MISSION_LABELS.get(settings.mission, settings.mission)
    risk = RISK_LABELS.get(settings.risk, settings.risk)
    return f"目的: {name}　不確実戦術: {risk}"
