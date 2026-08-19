"""移動知識ログの語彙（2026-07-30）。

★ここには**言葉の定義だけ**を置く。判定は `observer.py`、保存は `repository.py`。

⚠ 文字列を各所に散らさない。`"right"` を直書きすると、
  綴りを間違えたときに**静かに別の方向として保存される**。
"""

from __future__ import annotations

import dataclasses
import enum


class Direction(str, enum.Enum):
    """移動方向（指示書 4.1）。"""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"

    @property
    def delta(self) -> tuple[int, int]:
        return _DELTA[self]

    @property
    def opposite(self) -> "Direction":
        return _OPPOSITE[self]

    @classmethod
    def parse(cls, value) -> "Direction | None":
        """文字列から。読めなければ **None**（推測しない）。"""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return None

    @classmethod
    def from_delta(cls, dx: int, dy: int) -> "Direction | None":
        """座標の差から。**隣の1マスでなければ None**。

        ★斜めや2マス以上は「歩いた」とみなさない。
          倍速で1回の観測を飛ばした場合や、ワープの場合があるため。
        """
        for direction, (ddx, ddy) in _DELTA.items():
            if (dx, dy) == (ddx, ddy):
                return direction
        return None


_DELTA = {
    Direction.UP: (0, -1),
    Direction.DOWN: (0, 1),
    Direction.LEFT: (-1, 0),
    Direction.RIGHT: (1, 0),
}
_OPPOSITE = {
    Direction.UP: Direction.DOWN,
    Direction.DOWN: Direction.UP,
    Direction.LEFT: Direction.RIGHT,
    Direction.RIGHT: Direction.LEFT,
}


class ActionType(str, enum.Enum):
    """辺の種類（指示書 4.1）。同一マップ内の通常移動は `WALK`。"""

    WALK = "walk"
    DOOR = "door"
    STAIRS = "stairs"
    WARP = "warp"
    SHIP = "ship"
    UNKNOWN = "unknown"


class Confidence(str, enum.Enum):
    """確からしさ（指示書 4.1 / 4.2）。"""

    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    PROVISIONAL = "provisional"

    @property
    def rank(self) -> int:
        """強さの順（大きいほど確か）。★比べるときは必ずこれを使う。

        ⚠⚠ **順番の表を写さない。** 以前 `graph.py` と
          `location_resolver.py` に同じ表が2つあった。写すと、
          片方だけ直したときに**同じ確度が別の強さになる**。
        """
        return _CONFIDENCE_RANK[self]

    @classmethod
    def parse(cls, value, default=None):
        """文字列から。読めなければ `default`（**勝手に上げない**）。

        ⚠⚠ **`isinstance` の確認を先に置くこと。** ★これを落として実際に踏んだ。
          `Confidence` は `str` を継承しているが、`Enum.__str__` が
          `str.__str__` を上書きするので `str(Confidence.PROBABLE)` は
          `"Confidence.PROBABLE"` になり、**member を渡すと None が返る**。
          `Direction` / `TransitionType` / `LandmarkKind` の `parse` も同じ形。
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


_CONFIDENCE_RANK = {
    Confidence.PROVISIONAL: 0,
    Confidence.PROBABLE: 1,
    Confidence.CONFIRMED: 2,
}


class Classification(str, enum.Enum):
    """通れなかった理由（指示書 4.2）。

    ★★ **初回は必ず `UNKNOWN_BLOCK`。** ★★
      失敗1回で「壁」と決めない（指示書 2.4）。
      壁・NPC・扉・イベント・入力取りこぼし・会話中・メニュー中など、
      同じ「動かなかった」に化ける原因がいくつもある。
    """

    UNKNOWN_BLOCK = "unknown_block"
    WALL = "wall"
    DOOR = "door"
    NPC = "npc"
    EVENT_BLOCK = "event_block"
    MAP_BOUNDARY = "map_boundary"
    TEMPORARY = "temporary"


class TransitionType(str, enum.Enum):
    """マップ遷移の種類（指示書 4.3）。初回は `UNKNOWN` でよい。

    ★観測からは種類が分からない（画面から階段か扉かは判定できない）。
      **人が直す**ための入口が `repository.set_transition_type`。
    """

    ENTRANCE = "entrance"
    EXIT = "exit"
    STAIRS_UP = "stairs_up"
    STAIRS_DOWN = "stairs_down"
    DOOR = "door"
    WARP = "warp"
    PITFALL = "pitfall"
    SHIP_BOARD = "ship_board"
    SHIP_DISEMBARK = "ship_disembark"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value) -> "TransitionType | None":
        """文字列から。読めなければ **None**（`UNKNOWN` に丸めない）。

        ⚠ `UNKNOWN` に丸めると「まだ判定していない」と
          「綴りを間違えた」が同じ値になり、区別できなくなる。
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return None


#: 画面に出す名前。★英語の値をそのまま出さない
TRANSITION_LABELS = {
    TransitionType.ENTRANCE: "入口",
    TransitionType.EXIT: "出口",
    TransitionType.STAIRS_UP: "上り階段",
    TransitionType.STAIRS_DOWN: "下り階段",
    TransitionType.DOOR: "扉",
    TransitionType.WARP: "旅の扉",
    TransitionType.PITFALL: "落とし穴",
    TransitionType.SHIP_BOARD: "船に乗る",
    TransitionType.SHIP_DISEMBARK: "船を降りる",
    TransitionType.UNKNOWN: "種類未判定",
}

#: `Ctrl+矢印` で付けられる種類（マッパー仕様 フェーズ4）。
#
# ⚠⚠ **どのキーがどの種類かは仕様書に書かれていない。**
#   仕様は「Ctrl+矢印で遷移種別を手動修正」までしか言っていないので、
#   下の割り当ては**こちらの判断**:
#     上下は階層が動くもの（上り／下り階段）。★階層の推定が使う値
#     左右は階層が動かないもの（出口／入口）
#   合わないなら変えてください（この表だけ直せば画面もキーも変わります）。
ARROW_TRANSITIONS = {
    "up": TransitionType.STAIRS_UP,
    "down": TransitionType.STAIRS_DOWN,
    "left": TransitionType.EXIT,
    "right": TransitionType.ENTRANCE,
}


class LandmarkKind(str, enum.Enum):
    """目印の種類（マッパー仕様 フェーズ6）。

    ★★ **種類が決まっているものだけ目印にする。** ★★
      決まっているから、あとで「宝箱まで自動で行く」に使える。
      自由文の気づきは `MapNote`（メモ）のほう。

    ⚠ ここに無い種類を文字列で直書きしない。綴り違いが
      **静かに別の種類として保存される**。
    """

    TREASURE = "treasure"
    STAIRS = "stairs"
    DOOR = "door"
    SHOP = "shop"
    INN = "inn"
    CHURCH = "church"
    KING = "king"
    NPC = "npc"
    WARP = "warp"
    DEAD_END = "dead_end"
    OTHER = "other"

    @classmethod
    def parse(cls, value) -> "LandmarkKind | None":
        """文字列から。読めなければ **None**（`OTHER` に丸めない）。

        ⚠ 丸めると、綴りを間違えた目印が「その他」として静かに増える。
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return None


#: 画面に出す名前。★英語の値をそのまま出さない
LANDMARK_LABELS = {
    LandmarkKind.TREASURE: "宝箱",
    LandmarkKind.STAIRS: "階段",
    LandmarkKind.DOOR: "扉",
    LandmarkKind.SHOP: "店",
    LandmarkKind.INN: "宿屋",
    LandmarkKind.CHURCH: "教会",
    LandmarkKind.KING: "王様",
    LandmarkKind.NPC: "人",
    LandmarkKind.WARP: "旅の扉",
    LandmarkKind.DEAD_END: "行き止まり",
    LandmarkKind.OTHER: "その他",
}


class SessionMode(str, enum.Enum):
    MANUAL_OBSERVATION = "manual_observation"
    AUTO_NAVIGATION = "auto_navigation"
    EXPLORATION = "exploration"


class SessionResult(str, enum.Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclasses.dataclass
class Place:
    """「どのマップのどこ」。★`map_ptr` まで含めて1つの場所とする。

    ⚠ `map_id` だけでは足りない（同じ ID で別の階がある）。
    """

    map_id: int
    map_ptr: int
    x: int
    y: int

    @property
    def key(self) -> tuple:
        return (self.map_id, self.map_ptr, self.x, self.y)

    @property
    def map_key(self) -> tuple:
        return (self.map_id, self.map_ptr)


@dataclasses.dataclass
class PendingMove:
    """「その方向へ進もうとしている」という保留中の観測（指示書 5.2）。

    ★★ **すぐ DB に書かない。** ★★
      押した瞬間に書くと「押した記録」になってしまう。
      座標が変わったか／変わらなかったかを見てから、**結果**を書く。
    """

    place: Place
    direction: Direction
    input_frame: int
    deadline_frame: int

    def expired(self, frame: int) -> bool:
        return frame >= self.deadline_frame


@dataclasses.dataclass(frozen=True)
class Observation:
    """1回の観測で分かったこと（Observer が返す。テストが読む）。"""

    moved: bool = False
    blocked: bool = False
    transition: bool = False
    skipped: str | None = None
    """記録しなかった理由。**None 以外なら記録していない。**"""
    direction: Direction | None = None
    place: Place | None = None
    to_place: Place | None = None

    @property
    def recorded(self) -> bool:
        return bool(self.moved or self.blocked or self.transition)
