"""戦闘ごとの記録と、回帰試験の指標（RX3-0050 / PoC-C §13 §14 §18）。

## ★入力

```text
events.jsonl      ★Lua（dq3_field_run.lua）が書く battle_start / battle_end
battles.jsonl     ★Python（RUNNER）が書く。戦闘ごとの before / after（state.json の写し）
auto_v0.log       ★製品の自動戦闘の記録（⚠ 既存。★最大限そのまま使う / 指示書 §13）
```

## ★出力（指示書 §18）

```json
{"battles": 5, "wins": 5, "losses": 0, "deaths": 0,
 "average_turns": 12.4, "max_turns": 42,
 "exp_gained": 480, "gold_gained": 360,
 "items_observed": null, "hangs": 0, "unexpected_stops": 0}
```

⚠ `items_observed` は **null**（★所持品の番地が confirmed でないので写していない / 推測で埋めない）。

## ⚠ 「turn」は製品の数え方

★`auto_v0` の `turn=` は**1 人の行動ごと**に増えます（4 人なら 1 巡で 4）。
⚠ ここでは**外に出す名前を変えません**（`turns` = 行動の数）。
★2026-09-10（RX3-0153）から `rounds` が別に載ります（= 人が言う「ターン」）。

> ★読み取りの正本は `dq3/battle_count.py` です（⚠ ここへ写しません）。
"""

from __future__ import annotations

import json
import pathlib

from . import state_diff

from .. import battle_count as BC
from .. import paths

#: ★製品の自動戦闘の記録（⚠ dev.lua が追記する）
AUTO_LOG = paths.lazy_work("runtime", "dq3-probe", "auto_v0.log")

_START = BC.START


def load_jsonl(path) -> list[dict]:
    out = []
    path = pathlib.Path(path)
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def auto_outcomes(text: str) -> list[dict]:
    """★製品の記録から、**この run の**戦闘ごとの結末を順に取る。

    ★最後の `=== AUTO_V0 start` 以降だけを見る（⚠ 前の遊びの分を混ぜない）。

    ```json
    {"turns": 42, "rounds": null, "done": "戦闘が終わった（…）", "stopped": null}
    ```

    ⚠⚠ 旧い `turns=` は**戦闘をまたいで累積**します（★2026-09-02 実機: 14 / 28 / 42）。
      → ★差を取るのは `battle_count.scan()` の仕事です（⚠ ここでは数え直さない）。
    """
    if _START in text:
        text = text[text.rfind(_START):]
    out = []
    for got in BC.scan(text):
        if got["kind"] == "stopped":
            out.append({"turns": None, "rounds": None, "done": None,
                        "stopped": got["why"]})
            continue
        row = {"turns": got["actions"], "rounds": got["rounds"],
               "done": got["why"].strip(), "stopped": None}
        if got["actions_total"] is not None:
            row["turns_total"] = got["actions_total"]
        out.append(row)
    return out


def pair_events(events: list[dict]) -> list[dict]:
    """★battle_start と battle_end を battle_id で組にする。⚠ 片方しか無いものも残す。"""
    by_id: dict[int, dict] = {}
    for e in events:
        bid = e.get("battle_id")
        if bid is None:
            continue
        row = by_id.setdefault(bid, {"battle_id": bid})
        if e.get("event") == "battle_start":
            row["start_frame"] = e.get("frame")
            row["x"], row["y"] = e.get("x"), e.get("y")
            row["hp_before"] = e.get("hp")
            row["auto_pressed"] = e.get("auto")
        elif e.get("event") == "battle_end":
            row["end_frame"] = e.get("frame")
            row["frames"] = e.get("frames")
            row["result"] = e.get("result")
            row["hp_after"] = e.get("hp")
    return [by_id[k] for k in sorted(by_id)]


def merge(events: list[dict], snapshots: list[dict], auto_text: str = "") -> list[dict]:
    """★★ 1 戦 = 1 行にまとめる（events + before/after + 製品の turns）。"""
    rows = pair_events(events)
    snaps = {s.get("battle_id"): s for s in snapshots}
    outcomes = auto_outcomes(auto_text)
    for i, row in enumerate(rows):
        s = snaps.get(row["battle_id"], {})
        before, after = s.get("before"), s.get("after")
        row["before"] = before
        row["after"] = after
        if before and after:
            diff = state_diff.compare_state(before, after)
            row["diff"] = diff.get("changed", {})
            row["diff_lines"] = state_diff.summarize(diff)
        else:
            row["diff"] = None
        if i < len(outcomes):
            row["turns"] = outcomes[i]["turns"]
            row["rounds"] = outcomes[i]["rounds"]
            row["auto_done"] = outcomes[i]["done"]
            row["auto_stopped"] = outcomes[i]["stopped"]
        else:
            row["turns"] = None
            row["rounds"] = None
    return rows


def _sum_delta(rows, key) -> int | None:
    got, seen = 0, False
    for r in rows:
        d = (r.get("diff") or {}).get(key)
        if d and isinstance(d.get("delta"), (int, float)):
            got += d["delta"]
            seen = True
    return got if seen else None


def summarize(rows: list[dict], *, stop_reason=None) -> dict:
    """★回帰試験の指標（指示書 §18）。⚠ 分からないものは null。"""
    #: ⚠ `turns` は**行動**の数（★1 人 1 回）。`rounds` が人の言う「ターン」（RX3-0153）
    turns = [r["turns"] for r in rows if isinstance(r.get("turns"), int)]
    rounds = [r["rounds"] for r in rows if isinstance(r.get("rounds"), int)]
    results = [r.get("result") for r in rows]
    exp = sum(v for v in (_sum_delta(rows, "party.%d.exp" % i) for i in range(4)) if v) or None
    levels = []
    for r in rows:
        for i in range(4):
            d = (r.get("diff") or {}).get("party.%d.level" % i)
            if d and d.get("delta"):
                levels.append({"battle_id": r["battle_id"], "member": i,
                               "from": d["before"], "to": d["after"]})
    return {
        "battles": len(rows),
        "wins": results.count("won"),
        "losses": results.count("lost"),
        "deaths": results.count("lost"),
        "unfinished": sum(1 for r in rows if "result" not in r),
        "average_actions": round(sum(turns) / len(turns), 1) if turns else None,
        "max_actions": max(turns) if turns else None,
        "average_rounds": round(sum(rounds) / len(rounds), 1) if rounds else None,
        "max_rounds": max(rounds) if rounds else None,
        #: ⚠ 旧い名前（★中身は「行動」）。読む側を一度に直せないので残す
        "average_turns": round(sum(turns) / len(turns), 1) if turns else None,
        "max_turns": max(turns) if turns else None,
        "exp_gained": exp,
        "gold_gained": _sum_delta(rows, "gold"),
        "level_ups": levels,
        "items_observed": None,
        "items_observed_why": "⚠ 所持品の番地が confirmed でないので写していない",
        "hangs": 1 if stop_reason in ("hang_suspected", "fceux_exited", "timeout") else 0,
        "unexpected_stops": 1 if stop_reason in ("battle_too_long", "unexpected_map",
                                                 "state_unavailable", "boxed_in") else 0,
    }


def build(root, *, auto_log=None, stop_reason=None) -> dict:
    """★run の folder から `battles.json` を作って返す。"""
    root = pathlib.Path(root)
    auto_path = pathlib.Path(auto_log) if auto_log else AUTO_LOG
    text = auto_path.read_text(encoding="utf-8", errors="replace") if auto_path.exists() else ""
    rows = merge(load_jsonl(root / "events.jsonl"), load_jsonl(root / "battles.jsonl"), text)
    out = {"battles": rows, "summary": summarize(rows, stop_reason=stop_reason)}
    (root / "battles.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    return out
