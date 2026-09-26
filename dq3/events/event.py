"""共通 Event の型と、★決まった種別だけを通す関門（RX3-0154 / 2026-09-10）。

## ⚠⚠ ここが要 — producer は「文章」を作らない

★これまでは各 producer が**表示用の文章**をそのまま書いていました。

```text
⚠ NG   AUTO_V0_DONE 戦闘が終わった rounds=2 actions=8
★ 目標  emit("battle.end", "battle_auto", {"result": "win", "rounds": 2, "actions": 8})
```

→ ★人向けの文章にするのは `formatter` の仕事です（⚠ producer ではない）。

## ★種別は固定 ID（⚠ 自由文にしない）

```text
<domain>.<event>      battle.end / navigation.arrive / mantan.end
```

⚠⚠ **知らない種別は受け取りません**（★`ValueError`）。
★「UI に出したいから」という理由だけで種別を増やしません（依頼者 §8）。

## ⚠ 「turn」「手」は使いません（RX3-0153 の続き）

```text
★round   全員が 1 回動く区切り  → 日本語では「ターン」
★action  1 人 1 回の行動        → 日本語では「行動」
```
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import time

# ----------------------------------------------------------------------
# ★level（依頼者 §24）
# ----------------------------------------------------------------------
INFO = "info"
WARNING = "warning"
ERROR = "error"
DEBUG = "debug"
LEVELS = (INFO, WARNING, ERROR, DEBUG)

# ----------------------------------------------------------------------
# ★Event 種別（依頼者 §20 — PoC はこれだけ）
# ----------------------------------------------------------------------
BATTLE_START = "battle.start"
BATTLE_END = "battle.end"
NAVIGATION_START = "navigation.start"
NAVIGATION_ARRIVE = "navigation.arrive"
NAVIGATION_STOP = "navigation.stop"
MANTAN_START = "mantan.start"
MANTAN_END = "mantan.end"
#: ★呪文の結果（RX3-0271 / 依頼者「S10 は提案通りでOK」）。★戦闘の終わりに 1 回、(呪文, 敵) ごとの「試した / 効いた」
BATTLE_SPELL = "battle.spell"

#: ⚠⚠ **ここに無い種別は通しません。** ★増やすときは formatter と検査も一緒に。
#:   ★`battle.action` は Diagnostic 用途として**必要性を見てから**（依頼者 §20）。
#:   ★`battle.spell` は 1 行ずつではなく**戦闘ごとにまとめた** 1 件（RX3-0271 / ⚠ 行動履歴を埋めない）
TYPES = (
    BATTLE_START, BATTLE_END, BATTLE_SPELL,
    NAVIGATION_START, NAVIGATION_ARRIVE, NAVIGATION_STOP,
    MANTAN_START, MANTAN_END,
)

#: ★producer の名前（⚠ 表示には使いません）
SRC_BATTLE = "battle_auto"
SRC_NAVIGATION = "town_navigation"
SRC_MANTAN = "mantan"
#: ★呪文の結果の見張り（RX3-0271 / ⚠ Auto でも手でも同じ）
SRC_SPELL = "spell_watch"
SOURCES = (SRC_BATTLE, SRC_NAVIGATION, SRC_MANTAN, SRC_SPELL)

#: ★終わり方（⚠ `battle.end` / `mantan.end` / `navigation.stop` の `result`）
WIN = "win"
SUCCESS = "success"
STOPPED = "stopped"
CANCELLED = "cancelled"
#: ★Auto を切って人へ返した（窓の色・劣勢 / RX3-0225）。⚠ 勝ったのではない（RX3-0233）
HANDED = "handed"
RESULTS = (WIN, SUCCESS, STOPPED, CANCELLED, HANDED)


class UnknownEventType(ValueError):
    """⚠⚠ 表に無い種別（★勝手に増やさせない）。"""


def now_iso(clock=time.time) -> str:
    """★ISO8601 ＋ timezone（依頼者 §6）。

    ```text
    2026-09-10T16:12:31+09:00
    ```

    ⚠ epoch float や `HH:MM:SS` は **Event Writer より内側へ持ち込みません**。
    ★既存ログを読むときだけ、parser 側で吸収します。

    ⚠⚠ **`fromtimestamp(...).astimezone()` は落ちます**（2026-09-10 実測 / Windows）:

    ```text
    OSError: [Errno 22] Invalid argument      ★clock が 0.0（検査の固定時計）のとき
    ```

    ★naive な datetime に `astimezone()` を当てると、epoch 付近で OS の変換に落ちます。
    → ⚠ **先に UTC として読んでから**現地へ移します（★落ちません）。
    """
    try:
        got = _dt.datetime.fromtimestamp(clock(), _dt.timezone.utc).astimezone()
    except (OSError, OverflowError, ValueError):
        got = _dt.datetime.now().astimezone()          # ⚠ 時刻のために本体を止めない
    return got.replace(microsecond=0).isoformat()


def new_session_id(clock=time.time) -> str:
    """★1 回の起動を見分けるだけ（⚠ 厳密な session 管理は作りません / §7）。

    ```text
    20260910-161201
    ```
    """
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))


@dataclasses.dataclass(frozen=True)
class Event:
    """★「何が起きたか」だけ。⚠ 表示用の文章は持ちません。"""

    type: str
    source: str
    data: dict = dataclasses.field(default_factory=dict)
    level: str = INFO
    ts: str = ""
    session_id: str = ""

    def __post_init__(self) -> None:
        if self.type not in TYPES:
            raise UnknownEventType(
                "⚠⚠ 知らない Event 種別です: %r（★`dq3/events/event.py` の TYPES へ "
                "足してから使ってください）" % (self.type,))
        if self.level not in LEVELS:
            raise ValueError("⚠ 知らない level です: %r" % (self.level,))
        if not isinstance(self.data, dict):
            raise TypeError("⚠ data は dict です: %r" % (type(self.data),))

    # ------------------------------------------------------------------
    @property
    def domain(self) -> str:
        """★`battle.end` → `battle`。"""
        return self.type.split(".", 1)[0]

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def as_dict(self) -> dict:
        """★書き出す形（⚠ 依頼者 §5 の並びのまま）。"""
        return {"ts": self.ts, "session_id": self.session_id, "type": self.type,
                "source": self.source, "level": self.level, "data": dict(self.data)}


__all__ = [
    "Event", "UnknownEventType", "now_iso", "new_session_id",
    "INFO", "WARNING", "ERROR", "DEBUG", "LEVELS",
    "TYPES", "SOURCES", "RESULTS",
    "BATTLE_START", "BATTLE_END", "BATTLE_SPELL",
    "NAVIGATION_START", "NAVIGATION_ARRIVE", "NAVIGATION_STOP",
    "MANTAN_START", "MANTAN_END",
    "SRC_BATTLE", "SRC_NAVIGATION", "SRC_MANTAN", "SRC_SPELL",
    "WIN", "SUCCESS", "STOPPED", "CANCELLED", "HANDED",
]
