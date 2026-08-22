"""溜めた events から AI 判断の傾向を出す CLI（RX-0030 / 2026-08-21）。

設計は `docs/design/event-observation-policy.md` §6。⚠ **新しいログ行は足さない**
（既存の `work/events*.jsonl` から引くだけ）。

    PYTHONUTF8=1 python -m retroux.tools.battle_analyze sessions
    PYTHONUTF8=1 python -m retroux.tools.battle_analyze strategy-distribution
    PYTHONUTF8=1 python -m retroux.tools.battle_analyze role-distribution
    PYTHONUTF8=1 python -m retroux.tools.battle_analyze veto
    PYTHONUTF8=1 python -m retroux.tools.battle_analyze outcomes
    PYTHONUTF8=1 python -m retroux.tools.battle_analyze manual-fallback
    PYTHONUTF8=1 python -m retroux.tools.battle_analyze estimate-vs-actual
    PYTHONUTF8=1 python -m retroux.tools.battle_analyze decision-ids
  共通: `--events <path>`（複数可。既定 work/events*.jsonl）/ `--include-probes` / `--json`

## ⚠ 検査由来の記録を除く（RX-0031）

2026-08-13 まで `research/probes/` が本物の `events.jsonl` へ書いていた。
★その区間は **同じ秒に `session_start` が複数ある**（最大 13 本）ことで見分けられる
（人が起動すると 1 秒に 1 本しか立たない）。既定では**その秒に始まったセッションを
まるごと除く**。`--include-probes` で含められる。⚠ DB やファイルからは**消さない**
（分析側で除外する判断 / RX-0031）。

## ⚠ decision_id の新旧（RX-0033）

2026-08-13 以前の `decision_id` は `b{seq}_t{turn}_{name}` でセッションをまたぐと衝突する。
新しい形は `{session_id}_b…`。★ここでは **(セッション, decision_id) の組**で数え、
古い形の一意性を前提にしない。`decision-ids` で新旧の内訳を出す。

## ⚠ 出せないものは「出せない」と言う

`estimate-vs-actual`（推定撃破ターン vs 実ターン）は、推定値が events に**入っていない**
（state.json にしか無い）ので、いまは出せない。黙って 0 件にせず理由を出す。
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_GLOB = str(PROJECT_ROOT / "work" / "events*.jsonl")


# --- 読み込み ----------------------------------------------------------------

def read_events(paths) -> list[dict]:
    """複数ファイルを**時刻順**に連結する。壊れた行は数えて飛ばす。"""
    out: list[dict] = []
    bad = 0
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                if isinstance(e, dict):
                    out.append(e)
    if bad:
        print(f"⚠ 読めない行 {bad} 件を飛ばしました", file=sys.stderr)
    return out


def split_sessions(events: list[dict]) -> list[dict]:
    """`session_start` で区切る。戻り値: [{start, session_id, events:[...]}, ...]

    ★先頭に `session_start` が無い行（ローテーション直後など）は「不明セッション」へ。
    """
    sessions: list[dict] = []
    cur = {"start": None, "session_id": None, "events": []}
    for e in events:
        if e.get("type") == "session_start":
            if cur["events"] or cur["start"] is not None:
                sessions.append(cur)
            cur = {"start": e.get("time"), "session_id": e.get("session_id"), "events": []}
        cur["events"].append(e)
    if cur["events"]:
        sessions.append(cur)
    return sessions


def mark_probes(sessions: list[dict]) -> None:
    """同じ秒に始まったセッションが 2 本以上あれば全部 `probe=True`（RX-0031）。"""
    by_sec = collections.Counter(s["start"] for s in sessions if s["start"] is not None)
    for s in sessions:
        s["probe"] = s["start"] is not None and by_sec[s["start"]] > 1


def select(sessions: list[dict], include_probes: bool) -> list[dict]:
    return [s for s in sessions if include_probes or not s.get("probe")]


# --- 集計（★純ロジック。テストしやすいように dict を返す）-----------------------

def _battles(session: dict) -> list[list[dict]]:
    """`battle_start`〜`battle_end` の塊に切る。終わりが無い戦闘も 1 塊として残す。"""
    out: list[list[dict]] = []
    cur: list[dict] | None = None
    for e in session["events"]:
        t = e.get("type")
        if t == "battle_start":
            if cur:
                out.append(cur)
            cur = [e]
            continue
        if cur is not None:
            cur.append(e)
            if t == "battle_end":
                out.append(cur)
                cur = None
    if cur:
        out.append(cur)
    return out


def strategy_distribution(sessions) -> dict:
    """戦闘ごとに**最初の snapshot** の strategy（profile / risk / engine）を数える。"""
    c: collections.Counter = collections.Counter()
    battles = 0
    for s in sessions:
        for b in _battles(s):
            battles += 1
            snap = next((e for e in b if e.get("type") == "battle_decision_snapshot"), None)
            if snap is None:
                c[("(snapshotなし)", "", "")] += 1
                continue
            st = snap.get("strategy") or {}
            c[(str(st.get("profile", "?")), str(st.get("risk", "?")), str(st.get("engine", "?")))] += 1
    return {"battles": battles,
            "rows": [{"profile": k[0], "risk": k[1], "engine": k[2], "battles": v}
                     for k, v in c.most_common()]}


def role_distribution(sessions) -> dict:
    """snapshot の `role.action` を人ごとに数える。⚠ `role` が無い snapshot（古い形）は別枠。"""
    c: dict = collections.defaultdict(collections.Counter)
    missing = 0
    for s in sessions:
        for e in s["events"]:
            if e.get("type") != "battle_decision_snapshot":
                continue
            role = e.get("role")
            if not role:
                missing += 1
                continue
            c[str(e.get("actor"))][str(role.get("action", "?"))] += 1
    return {"without_role": missing,
            "rows": [{"actor": a, "action": act, "count": n}
                     for a in sorted(c) for act, n in c[a].most_common()]}


def veto(sessions) -> dict:
    c: collections.Counter = collections.Counter()
    for s in sessions:
        for e in s["events"]:
            if e.get("type") == "battle_veto":
                c[(str(e.get("actor")), str(e.get("kind")), str(e.get("reason")))] += 1
    return {"rows": [{"actor": k[0], "kind": k[1], "reason": k[2], "count": v}
                     for k, v in c.most_common()]}


def outcomes(sessions) -> dict:
    c: collections.Counter = collections.Counter()
    turns: dict = collections.defaultdict(list)
    for s in sessions:
        for b in _battles(s):
            end = next((e for e in b if e.get("type") == "battle_end"), None)
            key = str(end.get("outcome")) if end else "(終わりが記録されていない)"
            c[key] += 1
            nturn = max((int(e.get("turn") or 0) for e in b if e.get("type") == "battle_turn"), default=0)
            turns[key].append(nturn)
    rows = []
    for k, v in c.most_common():
        ts = turns[k]
        rows.append({"outcome": k, "battles": v,
                     "avg_turns": round(sum(ts) / len(ts), 2) if ts else None})
    return {"rows": rows}


def manual_fallback(sessions) -> dict:
    c: collections.Counter = collections.Counter()
    for s in sessions:
        for e in s["events"]:
            if e.get("type") == "manual_latched":
                c[str(e.get("reason"))] += 1
    return {"rows": [{"reason": k, "count": v} for k, v in c.most_common()]}


def decision_ids(sessions) -> dict:
    """新旧の内訳と、(セッション, id) で見た重複（★一意を前提にしない）。"""
    old = new = 0
    dup: collections.Counter = collections.Counter()
    for i, s in enumerate(sessions):
        seen: collections.Counter = collections.Counter()
        for e in s["events"]:
            d = e.get("decision_id")
            if not d or e.get("type") != "battle_decision_snapshot":
                continue
            if d.startswith("b"):
                old += 1
            else:
                new += 1
            seen[d] += 1
        dup[i] = sum(1 for v in seen.values() if v > 1)
    return {"old_form": old, "new_form": new,
            "sessions_with_duplicates": sum(1 for v in dup.values() if v)}


def estimate_vs_actual(sessions) -> dict:
    """⚠ 材料が events に無い。黙って 0 件にしない。"""
    has = any(("turns_to_win" in e or "battle_turns_to_win" in e)
              for s in sessions for e in s["events"]
              if e.get("type") == "battle_decision_snapshot")
    return {"available": has,
            "note": ("" if has else
                     "推定撃破ターン（battle_turns_to_win）が events に入っていない"
                     "（state.json にしか無い）。★snapshot へ入れるまで出せない")}


COMMANDS = {
    "strategy-distribution": strategy_distribution,
    "role-distribution": role_distribution,
    "veto": veto,
    "outcomes": outcomes,
    "manual-fallback": manual_fallback,
    "decision-ids": decision_ids,
    "estimate-vs-actual": estimate_vs_actual,
}


def sessions_summary(all_sessions: list[dict]) -> dict:
    probes = [s for s in all_sessions if s.get("probe")]
    return {"sessions": len(all_sessions), "probe_sessions": len(probes),
            "probe_battles": sum(len(_battles(s)) for s in probes),
            "kept_sessions": len(all_sessions) - len(probes),
            "kept_battles": sum(len(_battles(s)) for s in all_sessions if not s.get("probe"))}


# --- 表示 ------------------------------------------------------------------------

def _print_rows(rows: list[dict]) -> None:
    if not rows:
        print("  （該当なし）")
        return
    cols = list(rows[0].keys())
    widths = {c: max(len(str(c)), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  " + "  ".join(str(c).ljust(widths[c]) for c in cols))
    for r in rows:
        print("  " + "  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="events から AI 判断の傾向を出す")
    ap.add_argument("command", choices=["sessions", *COMMANDS])
    ap.add_argument("--events", nargs="*", help="events ファイル（既定 work/events*.jsonl）")
    ap.add_argument("--include-probes", action="store_true",
                    help="検査由来（同一秒に複数起動）のセッションも含める")
    ap.add_argument("--json", action="store_true", help="JSON で出す")
    args = ap.parse_args(argv)

    paths = args.events or sorted(glob.glob(DEFAULT_GLOB))
    if not paths:
        print("events ファイルがありません", file=sys.stderr)
        return 1
    all_sessions = split_sessions(read_events(paths))
    mark_probes(all_sessions)
    summary = sessions_summary(all_sessions)

    if args.command == "sessions":
        result = summary
    else:
        result = COMMANDS[args.command](select(all_sessions, args.include_probes))

    if args.json:
        print(json.dumps({"command": args.command, "summary": summary, "result": result},
                         ensure_ascii=False, indent=1))
        return 0
    print(f"== {args.command}  ★{len(paths)} ファイル / セッション {summary['sessions']}"
          f"（検査由来 {summary['probe_sessions']} を"
          f"{'含む' if args.include_probes else '除外'}）")
    if "rows" in result:
        _print_rows(result["rows"])
    for k, v in result.items():
        if k != "rows":
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
