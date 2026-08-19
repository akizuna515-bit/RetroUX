"""戦略（利用者が選ぶ唯一の概念）の型（2026-08-10 / UI整理 Phase 2）。

設計は `docs/design/strategy-unification-design.md`。

## ★★ 何をする層か

  いままで利用者は **目的（Mission）** と **作戦（戦術プロファイル）** を
  別々に選んでいた。それを **1つの「戦略」** に畳む。★利用者が触るのは戦略だけ。

    戦略        type    委譲先
    レベル上げ   AUTO    Mission.GRINDING（重み）
    ダンジョン攻略 AUTO    Mission.DUNGEON（重み・既定）
    ユーザー指定1 FIXED   UserStrategyProfile（毎ターン固定行動）
    手動        MANUAL  AI を通さない

## ⚠⚠ ここは「薄い被せもの」

  Mission（重み）・`tactics_selector`・Lua 配線は**温存**する
  （指示書§15「大規模リライトを避ける」）。この層は「4つのどれか」と
  「type」だけを持ち、AUTO なら Mission を、FIXED なら固定行動を指す。

## ⚠ DQ2 固有を Core に持ち込まない（指示書§13）

  `UserStrategyProfile` は**構造だけ**をここに置く。★「ちからのたて」等の
  既定データは DQ2 プラグインが持つ（Core にアイテム名・キャラ名を入れない）。
"""

from __future__ import annotations

import dataclasses
import enum

from ..mission.settings import Mission


class StrategyType(str, enum.Enum):
    """戦略の種別（指示書§6）。"""

    AUTO = "auto"      # ★AI が戦況を見て判断する（Mission×tactics）
    FIXED = "fixed"    # ★キャラごとの固定行動を毎ターン流す
    MANUAL = "manual"  # ★AI を通さない（人が操作する）

    @classmethod
    def parse(cls, value, default=None):
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


class Strategy(str, enum.Enum):
    """利用者が選ぶ戦略（指示書§2）。★安全探索は設けない（§2）。"""

    LEVELING = "leveling"    # レベル上げ
    DUNGEON = "dungeon"      # ダンジョン攻略（既定）
    CUSTOM_1 = "custom_1"    # ユーザー指定1（将来 custom_2, custom_3 を足せる）
    MANUAL = "manual"        # 手動

    @classmethod
    def parse(cls, value, default=None):
        """⚠ 知らない値には `default`（黙って別の戦略にしない）。"""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


#: 画面に出す名前。★英語の値をそのまま出さない
#: ⚠ 2026-08-11: 手動は**画面から外した**（依頼者「3戦略だけ」）。手動で
#:   遊びたいときは AUTO ボタンを OFF にする。★enum の MANUAL は旧設定の
#:   移行のために残すが、ドロップダウンには出さない。
STRATEGY_LABELS = {
    Strategy.LEVELING: "レベル上げ",
    Strategy.DUNGEON: "ダンジョン探索",
    Strategy.CUSTOM_1: "亀の子戦術",
    Strategy.MANUAL: "手動",
}

#: ツールチップ（★何が変わるかを書く）
STRATEGY_NOTES = {
    Strategy.LEVELING:
        "戦闘効率を優先します。★敵を早く倒し、攻撃呪文やMPも比較的積極的に"
        "使います。\n⚠ 宿屋までMPが持たないことがあります。",
    Strategy.DUNGEON:
        "継戦能力を優先します。★MPと消耗品を温存し、長く探索できる状態を"
        "保ちます（既定）。",
    Strategy.CUSTOM_1:
        "キャラクターごとの固定行動（亀の子）。★ローレシア＝たたかう／"
        "サマル・ムーン＝ちからのたて（無ければ防御）。満HPでも道具を使います。",
    Strategy.MANUAL:
        "AI を止めて、自分で操作します（AUTO ボタン OFF と同じ）。",
}

#: 各戦略の種別（指示書§6）
STRATEGY_TYPES = {
    Strategy.LEVELING: StrategyType.AUTO,
    Strategy.DUNGEON: StrategyType.AUTO,
    Strategy.CUSTOM_1: StrategyType.FIXED,
    Strategy.MANUAL: StrategyType.MANUAL,
}

#: AUTO 戦略が委譲する Mission（重みの持ち主）。★FIXED/MANUAL は持たない
STRATEGY_MISSION = {
    Strategy.LEVELING: Mission.GRINDING,
    Strategy.DUNGEON: Mission.DUNGEON,
}

#: ⚠⚠ **旧 `mission` 値からの移行**（指示書§14）。
#
#   2軸を畳む前は `config/mission.yaml` に `mission:` が入っていた。
#   ★新しい保存は `strategy:` だが、古いファイルも壊さず読む。
#   ⚠ `boss_manual` は **`manual` へ**畳む（依頼者の判断 / §3.4）。
#     `parse` の default に任せると `dungeon` になり挙動が変わるため、
#     ここで明示的に移す。
MISSION_TO_STRATEGY = {
    "grinding": Strategy.LEVELING,
    "dungeon": Strategy.DUNGEON,
    "boss_manual": Strategy.MANUAL,
}


# --- ユーザー指定（FIXED）用の型（指示書§5.2）------------------------------
#
# ★構造だけ。既定データ（ちからのたて）は DQ2 プラグインが持つ（§13）。

class FixedAction(str, enum.Enum):
    """固定行動の種類。★当面は2種。将来 spell 等を足せる（§8.2）。"""

    ATTACK = "attack"    # たたかう
    ITEM = "item"        # 道具を使う（`item` に ID/名前）

    @classmethod
    def parse(cls, value, default=None):
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


@dataclasses.dataclass(frozen=True)
class ActorFixedAction:
    """1キャラクターの固定行動。"""

    action: FixedAction = FixedAction.ATTACK
    #: `action == ITEM` のときの道具（★ID か名前。DQ2 プラグインが解決する）
    item: str | None = None

    def to_dict(self) -> dict:
        out: dict = {"action": self.action.value}
        if self.item is not None:
            out["item"] = self.item
        return out

    @classmethod
    def from_dict(cls, data) -> "ActorFixedAction":
        if not isinstance(data, dict):
            return cls()
        action = FixedAction.parse(data.get("action"), FixedAction.ATTACK)
        item = data.get("item")
        return cls(action=action,
                   item=str(item) if item is not None else None)


@dataclasses.dataclass(frozen=True)
class UserStrategyProfile:
    """ユーザー指定戦略の中身（キャラごとの固定行動）。

    ⚠ AI の判断（AutoStrategyProfile）とは**別モデル**（指示書§5）。
    """

    id: str = "custom_1"
    name: str = "ユーザー指定1"
    #: `{character_id: ActorFixedAction}`
    actors: dict = dataclasses.field(default_factory=dict)

    def action_for(self, character_id: str) -> ActorFixedAction:
        """その人の固定行動。★未設定なら「たたかう」。"""
        return self.actors.get(character_id) or ActorFixedAction()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "actors": {cid: a.to_dict() for cid, a in self.actors.items()},
        }

    @classmethod
    def from_dict(cls, data) -> "UserStrategyProfile":
        if not isinstance(data, dict):
            return cls()
        actors = {}
        for cid, spec in (data.get("actors") or {}).items():
            actors[str(cid)] = ActorFixedAction.from_dict(spec)
        return cls(id=str(data.get("id") or "custom_1"),
                   name=str(data.get("name") or "ユーザー指定1"),
                   actors=actors)
