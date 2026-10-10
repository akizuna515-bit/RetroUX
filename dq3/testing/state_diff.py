"""ゲーム状態の**前後差分**を取る共通基盤（RX3-0048 A-5 / OBSERVER + ASSERT）。

## ⚠⚠ 特定イベント専用の解析を増やす前に、これを置く（指示書 A-5）

```python
before = capture_state()
...
after = capture_state()
diff = compare_state(before, after)
```

★戦闘の前後・宝箱の前後・買い物の前後、⚠ どれも**同じ道具**で見ます。

## ★どこから読むか

⚠⚠ Python は FCEUX の RAM を直接読めません。
★製品（`dev.lua`）が **CONFIRMED の番地だけ**から書いている `work/runtime/state.json` を読みます
（`dq3rom/profiles/dq3_fc_jp_rev0a.json` の `runtime.party` は `confidence: confirmed`）。

```text
gold / frame / loc_kind / map_id / map_x / map_y / in_battle
party[i]  level / hp / max_hp / mp / max_mp / exp / to_next
          strength / agility / stamina / wisdom / luck / attack / defence
```

⚠⚠ **inventory / equipment / spell flags は入れていません。**
★番地が CONFIRMED になっていないためです（追加方針 §4-4「未確定は Observer 限定」）。
⚠ 推測で埋めません。入れるときは profile が `confirmed` になってからです。

## ★差分の形

```json
{"changed": {"gold": {"before": 306, "after": 378, "delta": 72}},
 "added": {}, "removed": {}, "same": 61}
```

★数なら `delta` を付けます（⚠ 「+72」がそのまま読める）。
"""

from __future__ import annotations

import datetime
import json
import pathlib

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ★製品が書いている状態（⚠ dev.lua の StateWriter）
STATE_JSON = paths.lazy_runtime("state.json")

#: ★snapshot に入れる項目（⚠ すべて CONFIRMED の番地から来るもの）
TOP_FIELDS = ("gold", "frame", "loc_kind", "map_id", "map_x", "map_y", "in_battle")
PARTY_FIELDS = ("level", "hp", "max_hp", "mp", "max_mp", "exp", "to_next",
                "strength", "agility", "stamina", "wisdom", "luck",
                "attack", "defence")

#: ⚠ 差分を見ない項目（★毎回変わるので比べても意味が無い）
IGNORE_IN_DIFF = ("frame", "captured_at")


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def flatten(state: dict) -> dict:
    """★入れ子を `party.0.hp` の形に平らにする（⚠ 比べやすくする）。"""
    out = {}
    for key in TOP_FIELDS:
        if key in state:
            out[key] = state[key]
    for i, member in enumerate(state.get("party") or []):
        if not isinstance(member, dict):
            continue
        for key in PARTY_FIELDS:
            if key in member:
                out["party.%d.%s" % (i, key)] = member[key]
    return out


def capture_state(path=None, *, label: str | None = None) -> dict:
    """★★ いまの状態を写す。⚠ 読めなければ `{"available": False, ...}`（落ちない）。"""
    path = pathlib.Path(path) if path is not None else STATE_JSON
    out = {"available": False, "captured_at": _now(), "source": str(path),
           "label": label}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        out["why"] = "⚠ 読めません: %s" % err
        return out
    if not isinstance(raw, dict):
        out["why"] = "⚠ 形が違います"
        return out
    out.update(flatten(raw))
    out["available"] = True
    try:
        out["source_mtime"] = datetime.datetime.fromtimestamp(
            path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        pass
    return out


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def compare_state(before: dict, after: dict) -> dict:
    """★★ 2 つの snapshot の差分。⚠ どちらかが読めていなければそう書く。"""
    out = {"changed": {}, "added": {}, "removed": {}, "same": 0,
           "before_at": before.get("captured_at"),
           "after_at": after.get("captured_at")}
    if not before.get("available") or not after.get("available"):
        out["why"] = "⚠ 片方が読めていません（before=%s / after=%s）" % (
            before.get("available"), after.get("available"))
        return out
    skip = set(IGNORE_IN_DIFF) | {"available", "source", "source_mtime", "label", "why"}
    keys = (set(before) | set(after)) - skip
    for key in sorted(keys):
        if key not in before:
            out["added"][key] = after[key]
        elif key not in after:
            out["removed"][key] = before[key]
        elif before[key] != after[key]:
            row = {"before": before[key], "after": after[key]}
            if _is_number(before[key]) and _is_number(after[key]):
                row["delta"] = after[key] - before[key]
            out["changed"][key] = row
        else:
            out["same"] += 1
    return out


def summarize(diff: dict) -> list[str]:
    """★人が読む 1 行ずつ（⚠ 指示書 §14 の「EXP +96」の形）。"""
    lines = []
    for key, row in sorted(diff.get("changed", {}).items()):
        if "delta" in row:
            lines.append("%s %+d" % (key, row["delta"]) if isinstance(row["delta"], int)
                         else "%s %+.2f" % (key, row["delta"]))
        else:
            lines.append("%s %r → %r" % (key, row["before"], row["after"]))
    for key, v in diff.get("added", {}).items():
        lines.append("%s + %r" % (key, v))
    for key, v in diff.get("removed", {}).items():
        lines.append("%s - %r" % (key, v))
    return lines


def write_all(root, before: dict, after: dict) -> dict:
    """★`state_before.json` / `state_after.json` / `state_diff.json` を書く。"""
    root = pathlib.Path(root)
    diff = compare_state(before, after)
    for name, body in (("state_before.json", before), ("state_after.json", after),
                       ("state_diff.json", diff)):
        (root / name).write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    return diff
