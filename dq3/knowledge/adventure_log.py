"""冒険ログ v0 — ★既存の記録を 1 本のテキストにまとめる（RX3-0150 / 2026-09-10）。

## ⚠⚠ 新しいログ基盤を作りません

★読むのは**既にあるもの**だけです（`docs/design/dq3-log-inventory.md` の棚卸し）。

```text
memos.jsonl        ★聞いた話・見つけたもの（⚠ 時刻は 2026-09-10 以降の行だけ）
location-book.json ★訪れた場所（`visit_order` / `first_seen_at`）
progress.json      ★手に入れた品・倒した敵・行った場所
topic-state.json   ★追っている話（`first_seen_at` / `last_updated_at`）
npc-heard.json     ★誰と何回話したか（★ISO8601 の時刻つき）
auto_v0.log        ★自動戦闘の数とターン
state.json         ★いまのパーティ
```

## ⚠⚠ 欠けているものは「無い」と書きます

★これが**いちばん大事な決まり**です。⚠ 書かないと、読んだ生成 AI が
**埋めて作文します**（= 嘘の冒険ログ）。

```text
⚠ 手動の戦闘は残っていません
⚠ アイテムを「いつ」取ったかは残っていません
⚠ レベルアップ・呪文習得は記録していません
```

## ★使い方

```python
from dq3.knowledge import adventure_log as AL

text = AL.build()          # ★clipboard へ入れる 1 本のテキスト
```

⚠ 生成 AI の API へは繋ぎません（★人が貼るだけ / 依頼者の指示）。
"""
from __future__ import annotations

import json

from .. import battle_count as BC
from .. import paths
from ..events import writer as EW

#: ★自動戦闘の記録（⚠ 手動の戦闘は残らない）。★読み方は `battle_count` に 1 本
BATTLE_DONE = BC.DONE
BATTLE_STOP = BC.STOP

#: ⚠⚠ **読んだ AI へ最初に伝えること**（★埋めさせないため）
PREAMBLE = """これは、ファミコン版ドラゴンクエストIII を実際に遊んだ記録です。
補助ツール「RetroUX DQ3」が、ゲームから読み取って残したものだけが入っています。

⚠ お願い:
- ここに**書かれていないこと**を、推測で補わないでください。
- 「記録に無い」と明記した項目は、本当に記録がありません（起きなかった、
  という意味ではありません）。
- 地名・人物・アイテムの名前は、ここにあるものだけを使ってください。
"""

#: ★何が残っていないか（⚠ 棚卸しの結果をそのまま書く）
MISSING = """この記録に**無いもの**（⚠ 補わないでください）:
- 手動で戦った戦闘（★自動戦闘だけが残ります）
- アイテムを「いつ」手に入れたか（★手に入れた事実だけが残ります）
- レベルアップ・呪文の習得（★記録していません）
- 2026-09-10 より前に書いた勇者メモの時刻（★順番だけが残ります）
"""


def _read(name, default=None):
    """★記録を 1 つ読む（⚠ 無ければ既定値。★落とさない）。"""
    try:
        return json.loads(paths.work("dq3-knowledge", name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default if default is not None else {}


def _memos() -> list:
    got = []
    try:
        text = paths.work("dq3-knowledge", "memos.jsonl").read_text(encoding="utf-8")
    except OSError:
        return got
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue                       # ⚠ 壊れた 1 行で全部を失わない
        if isinstance(row, dict):
            got.append(row)
    got.sort(key=lambda r: r.get("order") or 0)
    return got


def battles() -> dict:
    """★自動戦闘の数（⚠ `auto_v0.log` から。★手動は入らない）。

    ```json
    {"battles": 2, "rounds": 9, "actions": 60, "old": 1, "stopped": 1, "reasons": {}}
    ```

    ⚠ `old` は**ターン数が分からない古い行**の数です（★`turns=` しか無い）。
      → `rounds` はその戦闘ぶんを**含みません**。⚠ 平均を出すときに割る数を間違えない。
    """
    out = {"battles": 0, "rounds": 0, "actions": 0, "old": 0,
           "stopped": 0, "reasons": {}}
    try:
        text = paths.work("dq3-probe", "auto_v0.log").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return out
    for got in BC.scan(text):
        if got["kind"] == "stopped":
            out["stopped"] += 1
            why = got["why"]
            out["reasons"][why] = out["reasons"].get(why, 0) + 1
            continue
        out["battles"] += 1
        out["actions"] += got["actions"]
        if got["rounds"] is None:
            out["old"] += 1
        else:
            out["rounds"] += got["rounds"]
    return out


# ----------------------------------------------------------------------
# ★節ごとに組み立てる（⚠ どの節も「無ければ、無いと書く」）
# ----------------------------------------------------------------------

def _party_lines(state: dict) -> list:
    rows = state.get("party") or []
    if not rows:
        return ["⚠ パーティの記録が届いていません（★FCEUX につないでいないとき）"]
    out = []
    for i, m in enumerate(rows):
        out.append("  %d 人目  Lv%s  HP %s/%s  MP %s/%s"
                   % (i + 1, m.get("level"), m.get("hp"), m.get("max_hp"),
                      m.get("mp"), m.get("max_mp")))
    gold = state.get("gold")
    if gold is not None:
        out.append("  所持金 %s G" % gold)
    return out


def _place_lines(book: dict) -> list:
    locs = book.get("locations") or {}
    order = book.get("visit_order") or []
    out = []
    for loc in order:
        row = locs.get(loc) or {}
        name = row.get("display_name") or "（名前はまだ知りません）"
        when = row.get("first_seen_at")
        out.append("  %s%s" % (name, ("　%s" % when[:16].replace("T", " ")) if when else ""))
    left = [l for l in locs if l not in order]
    for loc in sorted(left):
        row = locs.get(loc) or {}
        if row.get("visited"):
            out.append("  %s" % (row.get("display_name") or loc))
    return out or ["  ⚠ まだ記録がありません"]


def _line_of(row: dict) -> str:
    """★1 行の見え方は `Memo.line` の 1 か所（⚠ 話者と `＊` の扱いを 2 度書かない）。"""
    from ..ui.models import Memo

    fields = {"order", "text", "location_id", "map_id", "npc_id", "item_id",
              "event_id", "at", "source", "speaker", "raw_digest"}
    try:
        return Memo(**{k: v for k, v in row.items() if k in fields}).line
    except (TypeError, ValueError):
        return (row.get("text") or "").strip()


def _talk_lines(memos: list, limit: int) -> list:
    out = []
    for row in memos:
        if row.get("source") not in ("conversation", "npc_talk"):
            continue
        text = _line_of(row)
        when = row.get("at")
        out.append("  %s%s%s"
                   % (text[:74], "…" if len(text) > 74 else "",
                      ("　%s" % when[:16].replace("T", " ")) if when else ""))
    if not out:
        return ["  ⚠ まだ記録がありません"]
    return out[-limit:] if limit else out


def _found_lines(memos: list) -> list:
    out = ["  %s" % (row.get("text") or "").strip()
           for row in memos if row.get("source") == "discovery"]
    return out or ["  ⚠ まだ記録がありません"]


def _topic_lines(state: dict) -> list:
    rows = (state or {}).get("topics") or {}
    out = []
    for tid, row in sorted(rows.items()):
        if (row or {}).get("status") == "unknown":
            continue                       # ⚠⚠ 勇者が知らない話は出さない（RX3-0117）
        out.append("  %s  %s  最後 %s"
                   % (tid, row.get("status"),
                      (row.get("last_updated_at") or "")[:16].replace("T", " ")))
    return out or ["  ⚠ まだ記録がありません"]


def _battle_lines() -> list:
    """★自動戦闘の数（⚠ 単位と範囲を**言葉にする**）。

    ⚠⚠ 記録には **2 つの単位**が混ざります（★RX3-0153 / 2026-09-10）:

    ```text
    行動  ★1 人 1 回。⚠ 4 人なら 1 ターンで 4 増える
    ターン ★全員が 1 回動く区切り（= 人が「ターン」と呼ぶもの）
    ```

    ⚠ `turns=` しか無い**古い行**はターンが分からないので、★行動だけ書きます。
    """
    got = battles()
    if not got["battles"] and not got["stopped"]:
        return ["  ⚠ 自動戦闘の記録がありません"]
    out = ["  自動戦闘 %d 戦 / のべ %s"
           % (got["battles"], BC.describe(got["rounds"], got["actions"]))]
    known = got["battles"] - got["old"]
    if known:
        out.append("  1 戦あたり 平均 %.0f ターン（%.0f 行動）"
                   % (got["rounds"] / known, got["actions"] / got["battles"]))
    elif got["battles"]:
        out.append("  1 戦あたり 平均 %.0f 行動" % (got["actions"] / got["battles"]))
    if got["old"]:
        out.append("  ⚠ うち %d 戦は古い記録で、ターン数が残っていません（★行動だけ）"
                   % got["old"])
    if got["stopped"]:
        out.append("  ⚠ 途中で止めた戦闘 %d 件" % got["stopped"])
    out.append("  ⚠ 「行動」は 1 人 1 回です（★4 人なら 1 ターン = 4 行動）")
    out.append("  ⚠ 手で戦ったぶんは、この数に入っていません")
    out.append("  ⚠ この数は**記録の全期間**です（★今回の起動ぶんではありません）")
    return out


def actions(limit: int = 30) -> list:
    """★RetroUX が代わりにやったこと（⚠ Product Log から / RX3-0154）。

    ⚠⚠ **ここは Event Log そのものではありません。** ★冒険ログは Event と
    Knowledge を組み合わせて作ります（依頼者 §17）。この節は Event 側の材料です。

    ```text
    2026-09-10 16:12 自動戦闘：勝利 2ターン（8行動）
    ```

    ★時刻つきなので、⚠ **時系列に並べられる数少ない記録**です。
    """
    try:
        text = paths.work(*EW.LOG_DIR, EW.PRODUCT_NAME).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return rows[-int(limit):] if limit else rows


def _action_lines(limit: int) -> list:
    got = actions(limit)
    if not got:
        return ["  ⚠ まだ記録がありません"]
    # ★新しい順（⚠ 他の節と並べ方を揃える）
    return ["  " + row for row in reversed(got)]


def _growth_lines(progress: dict, enemies: dict) -> list:
    out = ["  手に入れた品 %d 種類（⚠ いつ取ったかは残っていません）"
           % len(progress.get("items_ever") or [])]
    out.append("  出会った敵 %d 種類 / 倒した敵 %d 種類"
               % (len(enemies.get("met") or []), len(enemies.get("defeated") or [])))
    out.append("  ⚠ レベルアップと呪文の習得は記録していません")
    return out


def _timeline_lines(memos: list, book: dict, limit: int) -> list:
    """★時刻を持つものだけを並べる（⚠ 持たないものは入れない）。"""
    rows = []
    for loc, row in ((book.get("locations") or {})).items():
        when = (row or {}).get("first_seen_at")
        if when:
            rows.append((when, "はじめて %s へ入った"
                         % ((row or {}).get("display_name") or loc)))
    for memo in memos:
        when = memo.get("at")
        if when:
            rows.append((when, _line_of(memo)[:48]))
    if not rows:
        return ["  ⚠ 時刻つきの記録がまだありません（★2026-09-10 より前は順番だけ）"]
    rows.sort()
    return ["  %s  %s" % (w[:16].replace("T", " "), t) for w, t in rows[-limit:]]


# ----------------------------------------------------------------------
# ★入口
# ----------------------------------------------------------------------

def build(*, talks: int = 20, timeline: int = 40, actions_n: int = 30,
          state=None) -> str:
    """★clipboard へ入れる 1 本のテキスト（⚠ 既存の記録だけから）。"""
    memos = _memos()
    book = _read("location-book.json")
    progress = _read("progress.json")
    enemies = _read("enemy-names.json")
    topics = _read("topic-state.json")
    if state is None:
        try:
            state = json.loads(paths.work("state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}

    out = ["# 冒険の記録（RetroUX DQ3）", "", PREAMBLE, "## 1 いまのパーティ", ""]
    out += _party_lines(state)
    out += ["", "## 2 追っている話", ""] + _topic_lines(topics)
    out += ["", "## 3 訪れた場所（★行った順）", ""] + _place_lines(book)
    out += ["", "## 4 聞いた話（★新しい順に %d 件まで）" % talks, ""] + _talk_lines(memos, talks)
    out += ["", "## 5 見つけたもの", ""] + _found_lines(memos)
    out += ["", "## 6 戦い", ""] + _battle_lines()
    out += ["", "## 7 手に入れたもの・成長", ""] + _growth_lines(progress, enemies)
    out += ["", "## 8 RetroUX が代わりにやったこと（★新しい順に %d 件まで）" % actions_n, ""]
    out += _action_lines(actions_n)
    out += ["", "## 9 時刻の分かる出来事（★新しい順に %d 件まで）" % timeline, ""]
    out += _timeline_lines(memos, book, timeline)
    out += ["", "---", "", MISSING]
    return "\n".join(out)


__all__ = ["build", "battles", "actions", "PREAMBLE", "MISSING"]
