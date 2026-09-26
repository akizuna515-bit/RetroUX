"""AUTO_V0 の「終わりの行」を数える、たった 1 か所（RX3-0153 / 2026-09-10）。

## ⚠⚠ なぜ 1 か所に置くか

★同じ読み取りを `auto_watch` / `adventure_log` / `testing.battles` の
3 か所に書いていました。⚠ 片方だけ直すと**静かに食い違います**
（★教訓「同じ判定を 2 か所に書いて片方だけ直っていた」）。

## ★2 つの書式

```text
AUTO_V0_DONE … rounds=9 actions=36    ★新（2026-09-10 以降）
AUTO_V0_DONE … turns=36               ⚠ 旧（★248 戦ぶんの記録が残っている）
```

⚠⚠ 旧の `turns=` は **2 重に誤り**でした:

1. ★数えているのは **1 人 1 回の行動**です（4 人なら 1 ターンで 4 増える）。
2. ⚠ `finish()` で 0 に戻していないので、**戦闘をまたいで累積**します
   （★実測 2026-09-10: 8 / 16 / 24 / 32）。

→ ★旧の行は `cumulative=True` を立てて返します。**差を取るのは読む側**です
  （⚠ 累積かどうかを行の見た目から決められるのは、ここだけなので）。
"""

from __future__ import annotations

import re

#: ★終わりの行（⚠ 新旧どちらも受ける）
#:
#: ★RX3-0198（2026-09-12）: `actions=` の後ろに戦闘のまとめが続く形も受ける（⚠ 行末で固定のまま）:
#:
#: ```text
#: AUTO_V0_DONE 勝利 rounds=2 actions=8 strategy=leveling attack=5 magic=2 heal=1 support=0 defend=0 other=0 mp_used=12
#: ```
#:
#: ⚠ 付いていない行（2026-09-12 までの記録）は、今までと**同じ辞書**を返す（★`summary` を足さない）。
DONE = re.compile(
    r"^AUTO_V0_DONE\s+(?P<why>.*?)\s+"
    r"(?:rounds=(?P<rounds>\d+)\s+actions=(?P<actions>\d+)(?P<extra>(?:\s+[a-z_]+=\S+)*)"
    r"|turns=(?P<legacy>\d+))\s*$")

#: ★まとめの行動の種類（★Lua の `COUNT.KINDS` と同じ並び）
SUMMARY_KINDS = ("attack", "magic", "heal", "support", "defend", "other")


def _summary(extra: str) -> dict:
    """★`strategy=leveling attack=5 … mp_used=12` → 辞書（★数字は int / ⚠ 知らない鍵も捨てない）。"""
    out: dict = {}
    for token in (extra or "").split():
        key, _sep, value = token.partition("=")
        out[key] = int(value) if value.isdigit() else value
    return out


def event_fields(summary) -> dict:
    """★まとめ → `battle.end` の data（★`strategy` / `breakdown` / `mp_used`）。

    ⚠ 無い値は入れません（★旧い記録で「MP消費 0」と書いたら作り話 / 依頼者 §23）。
    """
    if not summary:
        return {}
    out: dict = {}
    if summary.get("strategy"):
        out["strategy"] = str(summary["strategy"])
    kinds = {k: int(summary[k]) for k in SUMMARY_KINDS if isinstance(summary.get(k), int)}
    if kinds:
        out["breakdown"] = kinds
    if isinstance(summary.get("mp_used"), int):
        out["mp_used"] = int(summary["mp_used"])
    return out

#: ★止めた行
STOP = re.compile(r"^AUTO_V0_STOP reason=(?P<why>.+?)\s*$")

#: ★`AUTO_V0 turn=N act=M slot=…` の行。
#:
#: ⚠⚠ 2026-09-24（RX3-0429 / P-17）で**意味が変わりました**:
#:   ```text
#:   ★いま   turn = 本当のターン数 / act = 行動の通し番号
#:   ⚠ 以前  turn = **行動の通し番号**（★ターンではなかった）
#:   ```
#:   ⚠ 古い記録も読めるように、★`act=` は**あっても無くてもよい**ことにします。
TURN = re.compile(r"^AUTO_V0 turn=(?P<n>\d+)(?:\s+act=(?P<act>\d+))?"
                  r"(?:\s+slot=(?P<slot>\S+))?")


def parse_done(line: str):
    """★終わりの行を読む。⚠ 合わなければ `None`。

    ```python
    {"why": "戦闘が終わった", "rounds": 9, "actions": 36, "cumulative": False}
    {"why": "戦闘が終わった", "rounds": None, "actions": 36, "cumulative": True}
    {"why": "勝利", "rounds": 2, "actions": 8, "cumulative": False,
     "summary": {"strategy": "leveling", "attack": 5, "magic": 2, …, "mp_used": 12}}   ★RX3-0198
    ```
    """
    m = DONE.match((line or "").strip())
    if m is None:
        return None
    if m.group("legacy") is not None:
        return {"why": m.group("why"), "rounds": None,
                "actions": int(m.group("legacy")), "cumulative": True}
    got = {"why": m.group("why"), "rounds": int(m.group("rounds")),
           "actions": int(m.group("actions")), "cumulative": False}
    if (m.group("extra") or "").strip():
        got["summary"] = _summary(m.group("extra"))
    return got


#: ★1 回の遊びの区切り（⚠ 旧い `turns=` の累積は、ここで 0 に戻る）
START = "=== AUTO_V0 start"


def scan(text: str) -> list:
    """★記録の全文から、戦闘ごとの結末を**順に**取る。

    ⚠⚠ 旧い `turns=` は累積なので、★前の行との**差**をその戦闘ぶんにします
    （⚠ 減っていたら数え直しなので、そのまま使う）。

    ```python
    {"kind": "done", "why": "…", "rounds": 9, "actions": 36,
     "cumulative": False, "actions_total": None}
    {"kind": "stopped", "why": "screen_frozen", "rounds": None, "actions": None}
    ```
    """
    out, prev = [], 0
    for line in (text or "").splitlines():
        if START in line:
            prev = 0
        got = parse_done(line)
        if got is not None:
            if got["cumulative"]:
                total = got["actions"]
                got["actions_total"] = total
                got["actions"] = total - prev if total >= prev else total
                prev = total
            else:
                got["actions_total"] = None
                prev = 0                       # ★新しい書式は戦闘ごとに 0 から
            got["kind"] = "done"
            out.append(got)
            continue
        m = STOP.match(line.strip())
        if m:
            out.append({"kind": "stopped", "why": m.group("why"),
                        "rounds": None, "actions": None,
                        "cumulative": False, "actions_total": None})
    return out


def slot_index(slot) -> int:
    """★`p3` → 3。⚠ 読めなければ 0（★落とさない）。"""
    got = re.search(r"\d+", str(slot or ""))
    return int(got.group(0)) if got else 0


def describe(rounds, actions) -> str:
    """★人が読む形（⚠ 依頼者の指定 2026-09-10:「9ターン（36行動）」）。

    ⚠ 旧い記録は `rounds` が分からないので、★**行動だけ**書きます。
    """
    actions = int(actions or 0)
    if rounds:
        return "%dターン（%d行動）" % (int(rounds), actions)
    return "%d行動" % actions


class Live(object):
    """★走っている最中に数える（⚠ `AUTO_V0 turn=` の行だけで畳む）。

    ★区切りの決め方は `auto_v0.lua` の `count_action` と同じです
    （⚠ slot の番号が**増えなくなったら**次のターン）。
    """

    def __init__(self):
        self.actions = 0
        self.rounds = 0
        self._last = None

    def feed(self, slot=None):
        self.actions += 1
        idx = slot_index(slot)
        if self._last is None or idx <= self._last:
            self.rounds += 1
        self._last = idx
        return self.actions

    def reset(self):
        self.actions, self.rounds, self._last = 0, 0, None

    def text(self) -> str:
        return describe(self.rounds, self.actions)
