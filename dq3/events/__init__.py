"""共通 Event の出力経路（RX3-0154 / 2026-09-10 依頼者「ログ出力正規化 仕様案」）。

```text
各機能 ──► Event Writer ──► Product / Diagnostic / Action Summary / Adventure Log
```

★producer は**表示用の文章を作りません**。「何が起きたか」だけを通知します。

```python
from dq3 import events as EV

EV.emit(EV.BATTLE_END, EV.SRC_BATTLE,
        {"result": EV.WIN, "rounds": 2, "actions": 8})
```

⚠ 既存の Technical Log（`auto_v0.log` ほか）は**残します**（依頼者 §18）。
★移行期は parser で Event に変換する bridge 方式です（`ui/auto_watch.py`）。
"""
from __future__ import annotations

from .event import (
    BATTLE_END, BATTLE_SPELL, BATTLE_START, CANCELLED, DEBUG, ERROR, Event, HANDED, INFO, LEVELS,
    MANTAN_END, MANTAN_START, NAVIGATION_ARRIVE, NAVIGATION_START,
    NAVIGATION_STOP, SRC_BATTLE, SRC_MANTAN, SRC_NAVIGATION, SRC_SPELL, STOPPED, SUCCESS,
    SOURCES, TYPES, UnknownEventType, WARNING, WIN, new_session_id, now_iso,
)
from .formatter import counted, product_line, stamped, summary_of
from .writer import (
    DIAGNOSTIC, EventWriter, MODES, NORMAL, emit, reset_shared, shared,
)

__all__ = [
    "Event", "UnknownEventType", "now_iso", "new_session_id",
    "INFO", "WARNING", "ERROR", "DEBUG", "LEVELS", "TYPES", "SOURCES",
    "BATTLE_START", "BATTLE_END", "BATTLE_SPELL",
    "NAVIGATION_START", "NAVIGATION_ARRIVE", "NAVIGATION_STOP",
    "MANTAN_START", "MANTAN_END",
    "SRC_BATTLE", "SRC_NAVIGATION", "SRC_MANTAN", "SRC_SPELL",
    "WIN", "SUCCESS", "STOPPED", "CANCELLED", "HANDED",
    "EventWriter", "shared", "reset_shared", "emit",
    "NORMAL", "DIAGNOSTIC", "MODES",
    "product_line", "stamped", "summary_of", "counted",
]
