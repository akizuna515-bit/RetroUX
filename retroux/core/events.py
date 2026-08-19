"""Lua ブリッジが出力するイベントの定義と解析。

Lua -> Python は `work/events.jsonl` への JSON Lines 追記（D-3 / DEV-3）。
LuaSocket が FCEUX に同梱されていないためファイルベースにしてある。

Lua 側は JSON ライブラリを持たないため手書きのシリアライズをしている。
壊れた行が混ざりうるので、解析側は**1行の失敗で全体を止めない**こと。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

# Lua 側が出力するイベント種別
SESSION_START = "session_start"
WARNING = "warning"
BATTLE_START = "battle_start"
BATTLE_END = "battle_end"
SPEED_CHANGE = "speed_change"
DANGER_ENTER = "danger_enter"
DANGER_EXIT = "danger_exit"
# 終了ボタンからの保存要求に対する Lua の返事（MVP2 Phase 1）
SAVESTATE_SAVED = "savestate_saved"
# 行動単位ログ（MVP2 Phase 3）
BATTLE_TURN = "battle_turn"
BATTLE_ACTION = "battle_action"
BATTLE_OBSERVATION = "battle_observation"


@dataclass(frozen=True)
class Event:
    """ブリッジからの1イベント。"""

    type: str
    frame: int
    data: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def enemy_ids(self) -> list[int]:
        value = self.data.get("enemy_ids") or []
        return [int(v) for v in value]


def parse_line(line: str) -> Event | None:
    """JSON Lines の1行を Event にする。解析できない行は None を返す。

    None を返すのは、Lua 側が手書きでJSONを組み立てており、
    書き込み途中の行や壊れた行が混ざりうるため。呼び出し側は読み飛ばす。
    """
    line = line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    event_type = payload.pop("type", None)
    if not isinstance(event_type, str):
        return None
    frame = payload.pop("frame", 0)
    try:
        frame = int(frame)
    except (TypeError, ValueError):
        frame = 0

    return Event(type=event_type, frame=frame, data=payload)


def parse_lines(lines: Iterator[str]) -> Iterator[Event]:
    """解析できた行だけを Event として流す。"""
    for line in lines:
        event = parse_line(line)
        if event is not None:
            yield event
