"""冒険ログ — ★既存の記録を 1 本のテキストにまとめる（RX3-0150 / 2026-09-10 → ★RX3-0518 / 2026-10-05）。

## ★目的（依頼者 2026-10-05 / F1）

★「プレイヤーが実際に体験した事実を、後から人間や外部 AI が読み返せる記録」。

```text
RetroUX   ★体験した事実を記録し、出す（⚠ 攻略の知識は足さない）
外部 AI   ★人が貼ったものを読み、人向けに整理する（⚠ ここから API では繋がない）
```

## ⚠⚠ 新しいログ基盤を作りません

★読むのは**既にあるもの**だけです（`docs/audit/260910_dq3-log-inventory.md` の棚卸し）。

```text
state.json         ★いまの場所・パーティ（名前・職業・Lv・HP・MP）・所持金
location-book.json ★訪れた場所（`visit_order` / `first_seen_at` / ★`name_source` で仮名かどうか）
progress.json      ★物語の旗（`story`）・手に入れた品・倒した敵
topic-state.json   ★勇者メモの話の状態（★名前は `data/dq3/hero-memo.yaml` の memo）
memos.jsonl        ★聞いた話・手に入れた品（⚠ 時刻は 2026-09-10 以降の行だけ）
auto_v0.log        ★自動戦闘の数とターン
product.log        ★RetroUX が代わりにやったこと（⚠ 起動・操作の失敗は外して出す）
```

## ⚠⚠ 欠けているものは「無い」と書きます

★これが**いちばん大事な決まり**です。⚠ 書かないと、読んだ生成 AI が
**埋めて作文します**（= 嘘の冒険ログ）。★逆に、⚠ **有るものを「無い」と書かない**
（RX3-0518: レベルアップと入手の時刻は残っているのに「無い」と書いていた）。

## ★名前の決まり（RX3-0518）

```text
仮名の場所   ★「○○（仮名）」（⚠ RetroUX が自動で付けた名前。正式名のように見せない）
内部 ID      ★名前が引けなければ「T017（名称未設定）」（⚠ 推測で名前を作らない）
並び         ★どの節も 古い → 新しい（★見出しに書く）
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
import re

from .. import battle_count as BC
from .. import paths
from ..events import writer as EW

#: ★自動戦闘の記録（⚠ 手動の戦闘は残らない）。★読み方は `battle_count` に 1 本
BATTLE_DONE = BC.DONE
BATTLE_STOP = BC.STOP

#: ⚠⚠ **読んだ AI へ最初に伝えること**（★埋めさせないため）
PREAMBLE = """これは、ファミコン版ドラゴンクエストIII を実際に遊んだ記録です。
補助ツール「RetroUX DQ3」が、ゲームから読み取って残したものだけが入っています。
セーブ／ロードでやり直した出来事も含めた、これまでに体験したことの累積です。

⚠ お願い:
- ここに**書かれていないこと**を、推測で補わないでください。
- 「記録に無い」と明記した項目は、本当に記録がありません（起きなかった、
  という意味ではありません）。
- 地名・人物・アイテムの名前は、ここにあるものだけを使ってください。
- 「（仮名）」の付いた地名は、RetroUX が自動で付けた仮の呼び名です（正式な名前ではありません）。
- 「（名称未設定）」は、名前の分からない記録です。名前を推測しないでください。
- どの節も、古い出来事 → 新しい出来事 の順に並んでいます（いちばん下が最近）。
"""

#: ★何が残っていないか（⚠ コードが実際に出せるものと突き合わせて書く / RX3-0518）
MISSING = """この記録に**無いもの・足りないもの**（⚠ 補わないでください）:
- 手で戦った戦闘の結果（★自動戦闘だけが残ります）
- レベルアップは、自動戦闘のあとに上がったときだけ「レベルが上がりました」と残ります
  （★誰が何レベルになったかは残りません。いまのレベルは「1 いまの状況」にあります）
- 呪文を覚えたこと（★記録していません）
- 手に入れた品の時刻は、宝箱・しらべる・持ち物に初めて増えたときのものだけです
  （★それより前の古い記録や、持ち物で見えただけの品は「手に入れた」事実だけ）
- 物語の進み具合・勇者メモの話が「いつ」片づいたか（★片づいたかどうかだけ）
- 2026-09-10 より前の勇者メモの時刻（★順番だけが残ります）
- セーブ／ロードでやり直したかどうか（★区別せずに積み上げています）
- 聞いた話・出来事は、最近のぶんだけを載せています（★件数は各節の見出し）
"""

#: ★仮名の印（⚠ 正式な名前のように見せない / 依頼者 §2-1・§4）
PROVISIONAL_MARK = "（仮名）"
#: ★名前の引けない内部 ID の印（⚠ 推測で名前を作らない / 依頼者 §3）
UNNAMED_MARK = "（名称未設定）"
#: ★まだ名前の無い場所
NO_NAME = "（名前はまだ知りません）"

#: ★勇者メモの状態の言い方（★勇者会議の `council.STATUS_LABEL` と同じ語）
TOPIC_STATUS = (("active", "対応中"), ("discovered", "手がかりあり"), ("resolved", "片づいた"))

#: ★手に入れた品の勇者メモ（★`progress.ACQUIRE_SOURCES` と同じ）
ACQUIRE_SOURCES = ("chest", "search", "item", "unknown")

#: ★世界地図の種別 → 呼び名（★地図の窓 `map_window` と同じ語）
WORLD_NAMES = {0: "世界地図", 2: "アレフガルド"}


def _read(name, default=None):
    """★記録を 1 つ読む（⚠ 無ければ既定値。★落とさない）。"""
    try:
        got = json.loads(paths.work("dq3-knowledge", name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        got = None
    # ⚠ 形の違う記録（`[]` など）で冒険ログ全体を失わない
    return got if isinstance(got, dict) else (default if default is not None else {})


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
            if not isinstance(row.get("at"), str):
                row["at"] = None               # ⚠ 形の違う時刻は「時刻なし」に（★並べるときに落ちない）
            got.append(row)
    got.sort(key=lambda r: _order(r.get("order")))
    return got


def _order(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _when(text) -> str:
    """★ISO の時刻 → 「2026-09-07 23:00」（⚠ 無ければ空）。"""
    return text[:16].replace("T", " ") if isinstance(text, str) else ""


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
        text = paths.work("runtime", "dq3-probe", "auto_v0.log").read_text(
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
# ★場所の名前（⚠ 仮名を正式名のように見せない / RX3-0518）
# ----------------------------------------------------------------------

def _book():
    """★場所の帳面（⚠ 画面と同じ読み方。★表の名前・Master を載せる / 保存はしない）。"""
    from .location_book import LocationBook
    from .locations import NAMES_PATH

    try:
        return LocationBook.load(path=paths.work("dq3-knowledge", "location-book.json"),
                                 names_path=NAMES_PATH)
    except Exception:                                    # noqa: BLE001 ★名前が無いだけ
        return None


def _location(book, location_id):
    """★記録の 1 か所を、画面と同じ名前の決め方で（⚠ 無ければ None）。"""
    if book is None or not location_id:
        return None
    row = book.locations.get(location_id)
    if row is None:
        return None
    for map_id in row.map_ids or ():
        got = book.get_location(map_id)
        if got.location_id == location_id:
            return got
    return row


def place_label(loc) -> str:
    """★場所 1 つの呼び名（★仮名なら「（仮名）」を付ける）。"""
    from .location_book import KNOWN_SOURCES

    name = loc.name(detailed=True) if loc is not None else None
    if not name:
        return NO_NAME
    return name if loc.name_source in KNOWN_SOURCES else name + PROVISIONAL_MARK


def _label_of(book, location_id, fallback=None) -> str:
    loc = _location(book, location_id)
    if loc is None:
        return fallback or NO_NAME
    return place_label(loc)


def _is_small_room(loc) -> bool:
    """★建物の中の小部屋の仮名（⚠ 束ねて数だけ出す / 依頼者 §7 の整理候補）。"""
    from .location_book import INNER_WORD, KNOWN_SOURCES

    name = loc.name() or ""
    return loc.name_source not in KNOWN_SOURCES and INNER_WORD in name


# ----------------------------------------------------------------------
# ★節ごとに組み立てる（⚠ どの節も「無ければ、無いと書く」）
# ----------------------------------------------------------------------

def _here_lines(state: dict, book) -> list:
    """★現在地（★`loc_kind` / `map_id` / `map_x`・`map_y`。⚠ 世界地図では map_id が来ない）。"""
    from .seen_map import is_local

    try:
        kind = int(state["loc_kind"]) if state.get("loc_kind") is not None else None
        map_id = int(state["map_id"]) if state.get("map_id") is not None else None
    except (TypeError, ValueError):
        kind = map_id = None                             # ⚠ 形の違う値は「届いていない」と同じ
    if kind is None:
        last = book.visit_order[-1] if (book is not None and book.visit_order) else None
        out = ["  現在地: ⚠ 届いていません（★FCEUX につないでいないとき）"]
        if last:
            out.append("  最後に入った場所（記録から）: %s" % _label_of(book, last))
        return out
    if is_local(kind) and map_id is not None and book is not None:
        return ["  現在地: %s" % place_label(book.get_location(map_id))]
    if is_local(kind):
        return ["  現在地: %s" % NO_NAME]
    out = ["  現在地: %s" % WORLD_NAMES.get(kind, "世界地図")]
    xy = (state.get("map_x"), state.get("map_y"))
    near = (book.nearest_known_base(xy, kind)
            if (book is not None and None not in xy) else None)
    if near is not None:
        out.append("  いちばん近い、名前の分かっている町: %s" % place_label(near))
    return out


def _member_line(i: int, m: dict) -> str:
    """★「あかり / 勇者 / Lv46 / HP 407/407 / MP 0/0」（⚠ 読めない欄は書かない）。"""
    from . import item_info as II
    from . import name_text as NT

    name = NT.party_name(m.get("name_tiles")) or "%d 人目" % (i + 1)
    parts = [name]
    job = II.class_name(m.get("class_gender"))
    if job:
        parts.append(job)
    if m.get("level") is not None:
        parts.append("Lv%s" % m.get("level"))
    for label, now, top in (("HP", "hp", ("max_hp", "hp_max")), ("MP", "mp", ("max_mp", "mp_max"))):
        most = next((m.get(k) for k in top if m.get(k) is not None), None)
        if m.get(now) is not None and most is not None:
            parts.append("%s %s/%s" % (label, m.get(now), most))
    return "    " + " / ".join(parts)


def _party_lines(state: dict) -> list:
    rows = [m for m in (state.get("party") or []) if isinstance(m, dict)]
    if not rows:
        return ["  ⚠ パーティの記録が届いていません（★FCEUX につないでいないとき）"]
    out = ["  パーティ:"] + [_member_line(i, m) for i, m in enumerate(rows)]
    gold = state.get("gold")
    if gold is not None:
        out.append("  所持金 %s G" % gold)
    return out


def _story_lines(progress: dict) -> list:
    """★物語の旗（★`progress.json` の `story` を `story-flags.csv` の言葉で）。"""
    from . import story as ST

    raw = progress.get("story")
    got = [f for f in (raw if isinstance(raw, list) else []) if isinstance(f, str)]
    try:
        flags = ST.load_flags()
    except Exception:                                    # noqa: BLE001 ★言葉が無いだけ
        flags = []
    order = {f.flag_id: n for n, f in enumerate(flags)}
    got.sort(key=lambda f: (order.get(f, len(order)), f))
    out = ["  ・%s" % (ST.label_of(f, flags) or f + UNNAMED_MARK) for f in got]
    if not out:
        out = ["  ⚠ まだ記録がありません"]
    if flags:                                            # ⚠ 表が読めないときに「0 個」と言わない
        out.append("  ★RetroUX が読めるゲームの旗は %d 個だけです"
                   "（ここに無い出来事は「起きていない」という意味ではありません）" % len(flags))
    return out


def _topic_names():
    """★勇者メモの話の名前（★`hero-memo.yaml` の memo / 片づいたら done）と話の束の題。

    戻り値: `({lead_id: (書いた順, Lead)}, {scenario id: 題})`
    """
    from . import hero_memo as HM

    try:
        scenarios, leads = HM.load_document(strict=False, problems=[])
    except Exception:                                    # noqa: BLE001 ★名前が無いだけ
        return {}, {}
    return {lead.lead_id: (n, lead) for n, lead in enumerate(leads)}, scenarios


def _topic_text(lead, status: str, scenarios: dict) -> str:
    text = (lead.done if (status == "resolved" and lead.done) else lead.memo) or ""
    text = " ".join(text.split())
    title = scenarios.get(lead.scenario) if lead.scenario else None
    return "［%s］%s" % (title, text) if title else text


def _topic_lines(state: dict) -> list:
    """★勇者メモの話（⚠ 知らない話は出さない / RX3-0117。★名前の無い ID は名称未設定でまとめる）。

    ⚠⚠ **時刻は出しません**（RX3-0518）。★`topic-state.json` の時刻は RetroUX が**判定した**時刻で、
      ⚠ 本物の記録では 64 件のほとんどが 2026-09-27〜28（★勇者メモへ切り替えた日）でした。
      → 出すと「その日に全部片づけた」と読めます。★並びだけ使います（同じ時刻なら勇者メモの並び）。
    """
    rows = (state or {}).get("topics") or {}
    leads, scenarios = _topic_names()
    out, unnamed = [], []
    for status, label in TOPIC_STATUS:
        key = "last_updated_at" if status == "resolved" else "first_seen_at"
        got = [(r.get(key) or "", leads.get(tid, (len(leads), None))[0], tid)
               for tid, r in rows.items() if isinstance(r, dict) and r.get("status") == status]
        lines = []
        for _at, _n, tid in sorted(got):
            lead = leads.get(tid, (0, None))[1]
            if lead is None:
                unnamed.append(tid)
                continue
            lines.append("    %s" % _topic_text(lead, status, scenarios))
        if lines:
            out += ["  %s（%d 件）:" % (label, len(lines))] + lines
    if unnamed:
        out.append("  ⚠ 名前の分からない古い記録 %d 件: %s"
                   % (len(unnamed), "、".join(t + UNNAMED_MARK for t in sorted(unnamed))))
    return out or ["  ⚠ まだ記録がありません"]


def _first_visit_order(book) -> list:
    """★はじめて入った順（★`first_seen_at`）。⚠ 時刻の無い古い記録は先頭に、`visit_order` の並びで。

    ⚠⚠ `visit_order` は**はじめて入った順ではありません**（RX3-0518 の実測）。
      ★入り直すと後ろへ回る（= 直近に居た順 / `get_last_known_base` の材料）。
    """
    known = list(book.visit_order)
    known += sorted(lid for lid, loc in book.locations.items()
                    if loc.visited and lid not in known)
    rank = {lid: n for n, lid in enumerate(known)}

    def first(lid):
        loc = book.locations.get(lid)
        return (loc.first_seen_at if loc is not None else None) or ""

    return sorted(known, key=lambda lid: (bool(first(lid)), first(lid), rank[lid]))


def _place_lines(book) -> list:
    """★訪れた場所（★はじめて入った順 / ⚠ 仮名の小部屋は数だけ）。"""
    if book is None:
        return ["  ⚠ まだ記録がありません"]
    out, rooms, provisional = [], 0, 0
    for lid in _first_visit_order(book):
        loc = _location(book, lid)
        if loc is None:
            continue
        if _is_small_room(loc):
            rooms += 1
            continue
        label = place_label(loc)
        provisional += label.endswith(PROVISIONAL_MARK)
        when = _when(loc.first_seen_at)
        out.append("  %s%s" % (label, ("　%s" % when) if when else ""))
    if not out and not rooms:
        return ["  ⚠ まだ記録がありません"]
    head = ["  %d か所（うち仮名 %d）" % (len(out), provisional)]
    if rooms:
        out.append("  ほかに、建物の中の小部屋 %d か所（★すべて仮名。一覧は省きました）" % rooms)
    return head + out


def _line_of(row: dict) -> str:
    """★1 行の見え方は `Memo.line` の 1 か所（⚠ 話者と `＊` の扱いを 2 度書かない）。"""
    from ..ui.models import Memo

    fields = {"order", "text", "location_id", "map_id", "npc_id", "item_id",
              "event_id", "at", "source", "speaker", "raw_digest"}
    try:
        return Memo(**{k: v for k, v in row.items() if k in fields}).line
    except (TypeError, ValueError):
        return (row.get("text") or "").strip()


def _memo_line(row: dict, book) -> str:
    """★勇者メモ 1 行（★頭の地名を、いまの呼び名＋仮名の印に置き換える / RX3-0518）。

    ⚠ 入手・発見の行は「<地名>　入手：…」「<地名>を見つけた」の形で、地名は**書いた時の名前**です。
    """
    text = _line_of(row)
    label = _label_of(book, row.get("location_id"), "")
    if not label or label == NO_NAME:
        return text
    source = row.get("source")
    head, sep, rest = text.partition("　")
    # ⚠ 頭が地名のときだけ（★「入手：…」「宝箱：…」の前。品名の中の空白で切らない）
    if source in ACQUIRE_SOURCES and sep and "：" not in head and "：" in rest:
        return "%s　%s" % (label, rest)
    if source == "discovery" and text.endswith("を見つけた"):
        return "%sを見つけた" % label
    if source in ("conversation", "npc_talk"):
        return "［%s］%s" % (label, text)
    return text


def _clip(text: str, n: int) -> str:
    return text[:n] + ("…" if len(text) > n else "")


def _talk_lines(memos: list, book, limit: int) -> list:
    out = []
    for row in memos:
        if row.get("source") not in ("conversation", "npc_talk"):
            continue
        when = _when(row.get("at"))
        out.append("  %s%s" % (_clip(_memo_line(row, book), 90),
                               ("　%s" % when) if when else ""))
    if not out:
        return ["  ⚠ まだ記録がありません"]
    return out[-limit:] if limit else out


#: ★同じ品の「宝箱：…」と「入手：…」を 1 つとみなす間（秒）
#:   ★本物の 2 行は 26 秒差（13:50:14 / 13:50:40）。⚠ 広げすぎると本当の 2 回目を消すので短めに
SAME_PICKUP_SECONDS = 120


def _seconds(text):
    import datetime

    try:
        return datetime.datetime.fromisoformat(str(text)).timestamp()
    except (TypeError, ValueError):
        return None


def _echo_rows(memos: list) -> set:
    """★宝箱・しらべる の入手と同じ品の「入手：…」（= 持ち物が増えたことで書いた 2 行目）。

    ⚠⚠ 本物の記録で 2 行並んでいた（RX3-0518 / 例: 「しらべる：オリハルコン を入手」と「入手：オリハルコン」が同じ分）。
      ★RX3-0312 は宝箱・しらべるが名乗り出るのを待つ作りですが、すり抜けた行が残っています。
      → ★冒険ログでは 1 つにまとめます（⚠ 勇者メモの記録そのものは変えない）。
    """
    found = {}
    for row in memos:
        if row.get("source") in ACQUIRE_SOURCES and row.get("source") != "item":
            found.setdefault(str(row.get("item_id")), []).append(_seconds(row.get("at")))
    out = set()
    for row in memos:
        if row.get("source") != "item" or row.get("item_id") is None:
            continue
        at = _seconds(row.get("at"))
        near = found.get(str(row.get("item_id"))) or ()
        if at is not None and any(t is not None and abs(t - at) <= SAME_PICKUP_SECONDS for t in near):
            out.add(id(row))
    return out


def _acquired_lines(memos: list, book, progress: dict, limit: int) -> list:
    """★手に入れたもの（★時刻のある入手の勇者メモ / ⚠ 全体の数は品の種類で）。"""
    echo = _echo_rows(memos)
    rows = [r for r in memos
            if r.get("source") in ACQUIRE_SOURCES and r.get("at") and id(r) not in echo]
    rows.sort(key=lambda r: r.get("at"))
    out = ["  手に入れた品 %d 種類（★一度でも手に入れた品）" % len(_items_ever(progress))]
    if rows:
        out.append("  時刻の分かる入手（★最近の %d 件）:" % min(limit, len(rows)))
        out += ["    %s  %s" % (_when(r.get("at")), _memo_line(r, book)) for r in rows[-limit:]]
    else:
        out.append("  ⚠ 時刻の分かる入手の記録はまだありません")
    return out


def _items_ever(progress: dict) -> set:
    """★一度でも手に入れた品（RX3-0490）。

    ⚠⚠ `items_ever` は**持ち物を覗いたときに見えた品**だけです。★拾ってすぐ使った・渡した品が抜けます
      （★2026-09-28 の実測で 7 種 / RX3-0443）。
    → ★`progress.Progress.acquired_ever()` と同じ材料（items_ever ∪ acquired ∪ 勇者メモの入手行）で数えます。
    """
    from . import progress as PG

    got = set()
    for key in ("items_ever", "acquired"):
        for raw in progress.get(key) or ():
            try:
                got.add(int(raw))
            except (TypeError, ValueError):
                continue
    return got | PG.acquired_items(paths.work("dq3-knowledge", "memos.jsonl"))


def _battle_lines(enemies: dict) -> list:
    """★自動戦闘の数（⚠ 単位と範囲を**言葉にする**）。

    ⚠⚠ 記録には **2 つの単位**が混ざります（★RX3-0153 / 2026-09-10）:

    ```text
    行動  ★1 人 1 回。⚠ 4 人なら 1 ターンで 4 増える
    ターン ★全員が 1 回動く区切り（= 人が「ターン」と呼ぶもの）
    ```

    ⚠ `turns=` しか無い**古い行**はターンが分からないので、★行動だけ書きます。
    """
    out = ["  出会った敵 %d 種類 / 倒した敵 %d 種類"
           % (len(enemies.get("met") or []), len(enemies.get("defeated") or []))]
    got = battles()
    if not got["battles"] and not got["stopped"]:
        return out + ["  ⚠ 自動戦闘の記録がありません"]
    out.append("  自動戦闘 %d 戦 / のべ %s"
               % (got["battles"], BC.describe(got["rounds"], got["actions"])))
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
    ups = sum(1 for row in actions(0) if LEVEL_UP in row)
    if ups:
        out.append("  自動戦闘のあとにレベルが上がった記録 %d 回（★誰が何レベルになったかは残っていません）" % ups)
    out.append("  ⚠ 「行動」は 1 人 1 回です（★4 人なら 1 ターン = 4 行動）")
    out.append("  ⚠ 手で戦ったぶんは、この数に入っていません")
    out.append("  ⚠ この数は**記録の全期間**です（★今回の起動ぶんではありません）")
    return out


# ----------------------------------------------------------------------
# ★RetroUX が代わりにやったこと（⚠ 起動・操作の失敗は外して出す / RX3-0518 §7）
# ----------------------------------------------------------------------

#: ★レベルアップの印（★`events/formatter.py` の自動戦闘の行）
LEVEL_UP = "レベルが上がりました"

#: ★冒険の結果が書いてある行（★これがあれば失敗の語があっても残す）
#:   ⚠ 例「まんたん：窓を閉じられません / 3人回復 / HP +247」は回復した事実がある
PLAY_WORDS = ("勝利", "到着", "人回復", "呪文の結果", "手で戦う画面に戻しました", LEVEL_UP)

#: ★RetroUX の操作の失敗・中断（⚠ ゲームの出来事ではない / ★診断用の記録には残る）
#:   ⚠ AI が「道がふさがっていた」をゲームの出来事と読む（2026-10-05 の実データで確認）
TOOL_WORDS = ("見つかりません", "動きません", "閉じられません", "かみ合わなく",
              "うまくいきませんでした", "経路を見失いました", "相手が動きました",
              "到達できません", "ふさがっています", "選べません", "回復できませんでした",
              "回復は要りませんでした", "ユーザー操作", "停止")

#: ★起動の 1 行（★`dq3/startup.py` の `log_startup`: 「<ISO 時刻> RetroUX DQ3 …」）
_STARTUP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} RetroUX ")


def action_kind(row: str) -> str:
    """★1 行の種類: `startup` / `tool`（操作の失敗・中断）/ `play`。

    ⚠ どちらの語にも当たらない行は `play`（★新しい種類の行を黙って消さない）。
    """
    if _STARTUP.match(row):
        return "startup"
    if any(w in row for w in PLAY_WORDS):
        return "play"
    if any(w in row for w in TOOL_WORDS):
        return "tool"
    return "play"


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
    rows = actions(0)
    kept = [r for r in rows if action_kind(r) == "play"]
    if not kept:
        out = ["  ⚠ まだ記録がありません"]
    else:
        out = ["  " + row for row in kept[-limit:]]        # ★古い順（いちばん下が最近）
    startup = sum(1 for r in rows if action_kind(r) == "startup")
    tool = sum(1 for r in rows if action_kind(r) == "tool")
    if startup or tool:
        out.append("  ★記録全体で省いた行: RetroUX の起動 %d 行 / RetroUX の操作の失敗・中断 %d 行"
                   "（★ゲームの出来事ではないため）" % (startup, tool))
    return out


def _timeline_lines(memos: list, book, limit: int) -> list:
    """★時刻を持つものだけを並べる（⚠ 持たないものは入れない）。"""
    rows, entered = [], set()
    if book is not None:
        for lid, row in book.locations.items():
            if not isinstance(row.first_seen_at, str) or not row.first_seen_at:
                continue
            entered.add(lid)
            loc = _location(book, lid)
            # ⚠ 仮名の小部屋・名前の無い場所は並べない（★「4 訪れた場所」と同じ扱い / 本物の出来事を押し出す）
            if loc is None or _is_small_room(loc) or not loc.name():
                continue
            rows.append((row.first_seen_at, "はじめて %s へ入った" % place_label(loc)))
    echo = _echo_rows(memos)
    for memo in memos:
        when = memo.get("at")
        if not when or id(memo) in echo:
            continue
        # ★「○○を見つけた」は「はじめて ○○ へ入った」と同じ出来事（⚠ 2 行にしない）
        if memo.get("source") == "discovery" and memo.get("location_id") in entered:
            continue
        rows.append((when, _clip(_memo_line(memo, book), 60)))
    if not rows:
        return ["  ⚠ 時刻つきの記録がまだありません（★2026-09-10 より前は順番だけ）"]
    rows.sort(key=lambda r: r[0])
    return ["  %s  %s" % (_when(w), t) for w, t in rows[-limit:]]


# ----------------------------------------------------------------------
# ★入口
# ----------------------------------------------------------------------

def _load_state(state):
    if state is not None:
        return state
    try:
        got = json.loads(paths.runtime("state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def build(*, talks: int = 20, timeline: int = 40, actions_n: int = 30,
          acquired_n: int = 30, state=None) -> str:
    """★clipboard へ入れる 1 本のテキスト（⚠ 既存の記録だけから）。"""
    memos = _memos()
    book = _book()
    progress = _read("progress.json")
    enemies = _read("enemy-names.json")
    topics = _read("topic-state.json")
    state = _load_state(state)

    out = ["# 冒険の記録（RetroUX DQ3）", "", PREAMBLE, "## 1 いまの状況", ""]
    out += _here_lines(state, book) + _party_lines(state)
    out += ["", "## 2 物語の進み具合（★ゲームの中の旗）", ""] + _story_lines(progress)
    out += ["", "## 3 勇者メモの話（★RetroUX が気づいた順。⚠ いつ片づいたかの時刻は残っていません）", ""]
    out += _topic_lines(topics)
    out += ["", "## 4 訪れた場所（★はじめて入った順。時刻の無い古い記録が先頭）", ""] + _place_lines(book)
    out += ["", "## 5 聞いた話（★古い順。最近の %d 件）" % talks, ""]
    out += _talk_lines(memos, book, talks)
    out += ["", "## 6 手に入れたもの（★古い順）", ""]
    out += _acquired_lines(memos, book, progress, acquired_n)
    out += ["", "## 7 戦い", ""] + _battle_lines(enemies)
    out += ["", "## 8 RetroUX が代わりにやったこと（★古い順。最近の %d 件）" % actions_n, ""]
    out += _action_lines(actions_n)
    out += ["", "## 9 時刻の分かる出来事（★古い順。最近の %d 件）" % timeline, ""]
    out += _timeline_lines(memos, book, timeline)
    out += ["", "---", "", MISSING]
    return "\n".join(out)


__all__ = ["build", "battles", "actions", "action_kind", "place_label",
           "PREAMBLE", "MISSING", "PROVISIONAL_MARK", "UNNAMED_MARK"]
