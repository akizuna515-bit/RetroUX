"""勇者メモのカードが「いつ初めて見えたか」を、実際の記録を時系列に再生して調べる（RX3-0436）。

## ★何をするか

```text
実際の記録（会話・入手・行った場所）   ★勇者メモの記録番号 #order を時計にする
        ↓ 論理 Fact（同じ知識は 1 つ / `concepts.logical_facts`）
        ↓ 古い順に 1 つずつ当てる（⚠ 画面と同じ `TopicBook`）
カードごとに
  first_visible   初めて見えた時点（#order）と、そのとき成立した条件・原因の Fact
  resolved        片づいた時点
  NEVER_TRIGGERED 記録を最後まで流しても 1 度も見えない
  review          ⚠ 「定義上は正しいが、物語として早すぎる／遅すぎる」かもしれない印
```

⚠ 正しい / 間違いは**決めません**。★人が判断する材料を出すだけです。

## ⚠ 時計

```text
heard   その会話の勇者メモの番号（⚠ 聞き込みの台帳の会話は、同じ本文のメモを探す）
obtain  その品を入手したメモ（宝箱 / 入手 / しらべる）の番号
visit   その場所で書かれた最初のメモの番号
defeat / set（旗）  ⚠ 記録に時刻が無い → 「時刻不明」（★最後にまとめて当てる）
```
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

from dq3.knowledge import concepts as C
from dq3.knowledge import guide as G
from dq3.knowledge import progress as PG

#: ★predicate → 勇者メモの言い方（⚠ `hero_memo.VOCABULARY` の逆）
VERB_OF = {"heard": "聞いた", "obtain": "持った", "acquired": "入手した",
           "defeat": "倒した", "visit": "行った", "set": "フラグ"}

#: ★入手のメモ（⚠ `item_id` を持つ行 / ★出どころは `progress.ACQUIRE_SOURCES` 1 本）

#: ★review の印（⚠ 人が見る材料。★ERROR ではない）
REVIEW_VISIT = "到着と同時に出る"
REVIEW_SAME = "出ると同時に片づく"
REVIEW_RESOLVED_FIRST = "片づく条件だけ成立（出る条件は未成立 / 画面には出ない）"
REVIEW_NO_TIME = "出た時刻が分からない"
REVIEW_BEFORE_SOURCE = "⚠⚠ 条件の初出より前に見えた"
REVIEW_APPEAR_NO_TIME = "出る条件は成立しているが時刻が分からない"
REVIEW_FAR_AHEAD = "同じ scenario のほかのカードより大きく早い"
NEVER_TRIGGERED = "NEVER_TRIGGERED"

#: ★「大きく早い」の目安（⚠ 記録の番号の差 / 人が見る材料なので粗くてよい）
FAR_AHEAD_GAP = 300


@dataclasses.dataclass(frozen=True)
class Clock:
    """★記録の中の時点（⚠ `order` が無ければ時刻不明）。"""

    order: int | None = None
    at: str | None = None

    @property
    def label(self) -> str:
        return "#%d" % self.order if self.order is not None else "時刻不明"

    def key(self) -> tuple:
        return (self.order is None, self.order or 0)


@dataclasses.dataclass
class Trigger:
    """★条件 1 本と、それを満たした Fact。"""

    condition: str
    subject: str
    clock: Clock
    #: ★all_of の組の名前（⚠ 1 本の条件は空）
    group: str = ""


@dataclasses.dataclass
class CardTimeline:
    topic_id: str
    first_visible: Clock | None = None
    triggers: list = dataclasses.field(default_factory=list)
    resolved: Clock | None = None
    resolve_triggers: list = dataclasses.field(default_factory=list)
    review: list = dataclasses.field(default_factory=list)

    @property
    def never_triggered(self) -> bool:
        return self.first_visible is None and self.resolved is None


# --- ★時計 -------------------------------------------------------------------

def memo_rows(path=None) -> list[dict]:
    """★勇者メモの記録（`order` の順）。⚠ 無ければ空。"""
    try:
        lines = pathlib.Path(path or C.MEMOS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    got = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("order"), int):
            got.append(row)
    got.sort(key=lambda r: r["order"])
    return got


def fact_clocks(facts: list[dict], observations: list, rows: list[dict]) -> dict[str, Clock]:
    """★論理 Fact → いちばん早い時点。"""
    talk = [(C._plain(r.get("text") or ""), r) for r in rows if r.get("source") in C.MEMO_SOURCES]
    obs_text = {o.observation_id: C._plain(o.text) for o in observations}
    obs_map = {o.observation_id: o.map_id for o in observations}
    first_at_loc: dict[str, dict] = {}
    first_item: dict[int, dict] = {}
    for row in rows:
        first_at_loc.setdefault(str(row.get("location_id")), row)
        # ⚠⚠ `item_id` は**文字列**（★int と決め打っていたので、ここは常に空だった / 2026-09-28）
        raw_item = str(row.get("item_id") or "").strip()
        if row.get("source") in PG.ACQUIRE_SOURCES and raw_item.isdigit():
            first_item.setdefault(int(raw_item), row)

    def talk_row(observation_id: str) -> dict | None:
        if observation_id.startswith("memo-o"):
            order = int(observation_id[len("memo-o"):])
            return next((r for _p, r in talk if r["order"] == order), None)
        plain = obs_text.get(observation_id) or ""
        if not plain:
            return None
        # ★聞き込みの台帳の会話は、同じ本文のメモのうち最初のもの。
        #   ⚠ 部分一致だけだと、短い決まり文句（店の口上など）が**別の町のメモ**に当たる（実測 1 件）。
        #   → ★同じ map で本文が同じ → 同じ本文 → 同じ map で片方が他方を含む、の順に探す
        same_map = [(p, r) for p, r in talk if r.get("map_id") == obs_map.get(observation_id)]
        for pool, loose in ((same_map, False), (talk, False), (same_map, True)):
            got = next((r for p, r in pool
                        if p and (p == plain or (loose and (p in plain or plain in p)))), None)
            if got is not None:
                return got
        return None

    got: dict[str, Clock] = {}
    for fact in facts:
        kind, _, ident = str(fact.get("subject") or "").partition(":")
        hits: list[dict] = []
        if fact.get("predicate") == "heard":
            hits = [r for r in (talk_row(o) for o in fact.get("source_observation_ids")
                                or [fact.get("source_observation_id")]) if r]
        elif fact.get("predicate") in ("obtain", "acquired") and kind == "item" and ident.isdigit():
            hits = [first_item[int(ident)]] if int(ident) in first_item else []
        elif fact.get("predicate") == "visit" and kind == "location":
            hits = [first_at_loc[ident]] if ident in first_at_loc else []
        first = min(hits, key=lambda r: r["order"]) if hits else None
        got[fact["fact_id"]] = Clock(first["order"], first.get("at")) if first else Clock()
    return got


# --- ★再生 -------------------------------------------------------------------

def _condition_text(rule: G.Rule) -> str:
    return "%s: %s" % (VERB_OF.get(rule.predicate, rule.predicate), rule.entity_name or rule.subject())


def replay(topics: dict, rules: list, facts: list[dict], clocks: dict[str, Clock]) -> dict[str, CardTimeline]:
    """★古い順に 1 つずつ当て、見えた・片づいた瞬間を記録する（⚠ 状態はメモリの中だけ）。"""
    # ⚠ 画面（`Council`）と同じ見せ方で再生する（★`require_appear`）
    book = G.TopicBook(master=topics, rules=rules, path=pathlib.Path("__replay_never_saved__"),
                       require_appear=True)
    got = {tid: CardTimeline(topic_id=tid) for tid in topics}
    hit: dict[str, tuple[str, Clock]] = {}                  # rule_id → (subject, 時点)
    order = sorted(range(len(facts)),
                   key=lambda i: clocks.get(facts[i]["fact_id"], Clock()).key() + (i,))
    for i in order:
        fact = facts[i]
        clock = clocks.get(fact["fact_id"], Clock())
        for rule in rules:
            if rule.matches(fact):
                hit.setdefault(rule.rule_id, (fact.get("subject"), clock))
        before = {tid: book.state(tid).status for tid in topics}
        book.apply(fact)
        for tid in topics:
            now = book.state(tid).status
            if now == before[tid]:
                continue
            card = got[tid]
            if before[tid] == "unknown" and now != "unknown" and card.first_visible is None:
                card.first_visible = clock
                card.triggers = _appear_triggers(rules, tid, hit)
            if now == "resolved" and card.resolved is None:
                card.resolved = clock
                card.resolve_triggers = _triggers(rules, tid, hit, completes=True)
    for tid, card in got.items():
        if card.first_visible is None and _triggers(rules, tid, hit, completes=True):
            # ⚠ 片づく条件だけが成立し、出る条件は成立していない（★画面には出ない）
            card.review.append(REVIEW_RESOLVED_FIRST)
        _review(card)
    return got


def _triggers(rules, topic_id, hit, completes: bool) -> list[Trigger]:
    return [Trigger(_condition_text(r), hit[r.rule_id][0], hit[r.rule_id][1])
            for r in rules
            if r.topic_id == topic_id and r.completes == completes and r.rule_id in hit]


def _appear_triggers(rules, topic_id, hit) -> list[Trigger]:
    """★見えた理由になった条件だけ（⚠ 1 本の条件なら当たった全部 / all_of なら**そろった組**）。"""
    mine = [r for r in rules if r.topic_id == topic_id and not r.completes]
    single = [r for r in mine if r.match_mode != "ALL" and r.rule_id in hit]
    groups: dict[str, list] = {}
    for rule in mine:
        if rule.match_mode == "ALL":
            groups.setdefault(rule.group, []).append(rule)
    done = [r for members in groups.values() if all(m.rule_id in hit for m in members)
            for r in members]
    return [Trigger(_condition_text(r), hit[r.rule_id][0], hit[r.rule_id][1],
                    r.group if r.match_mode == "ALL" else "") for r in single + done]


def _review(card: CardTimeline) -> None:
    if card.never_triggered and REVIEW_APPEAR_NO_TIME not in card.review:
        card.review.append(NEVER_TRIGGERED)
        return
    if card.first_visible is None:
        return
    if card.first_visible.order is None:
        card.review.append(REVIEW_NO_TIME)
    if any(t.condition.startswith(VERB_OF["visit"]) and t.clock == card.first_visible
           for t in card.triggers):
        card.review.append(REVIEW_VISIT)
    if card.resolved is not None and card.resolved == card.first_visible:
        card.review.append(REVIEW_SAME)
    # ⚠ 見えた時点より前に、理由が**そろっていた**はず（★1 本なら 1 本、all_of なら組の全部）。
    #   ★そろっていないのに見えていたら、再生か判定が壊れている
    if card.triggers and card.first_visible.order is not None and not _explained(card):
        card.review.append(REVIEW_BEFORE_SOURCE)


def _explained(card: CardTimeline) -> bool:
    at = card.first_visible.key()
    if any(not t.group and t.clock.key() <= at for t in card.triggers):
        return True
    groups: dict[str, list] = {}
    for t in card.triggers:
        if t.group:
            groups.setdefault(t.group, []).append(t)
    return any(all(t.clock.key() <= at for t in members) for members in groups.values())


def mark_far_ahead(timeline: dict[str, CardTimeline], scenario_of: dict[str, str]) -> None:
    """★同じ scenario のほかのカードより `FAR_AHEAD_GAP` 以上早く見えたカードに印を付ける。"""
    by_scenario: dict[str, list[CardTimeline]] = {}
    for tid, card in timeline.items():
        if scenario_of.get(tid) and card.first_visible and card.first_visible.order is not None:
            by_scenario.setdefault(scenario_of[tid], []).append(card)
    for cards in by_scenario.values():
        for card in cards:
            others = [c.first_visible.order for c in cards if c is not card]
            if others and min(others) - card.first_visible.order >= FAR_AHEAD_GAP:
                card.review.append(REVIEW_FAR_AHEAD)


def nearby_talk(rows: list[dict], clock: Clock | None) -> tuple[dict | None, dict | None]:
    """★その時点の直前・直後の会話（⚠ 同じ番号の会話は「直前」側に入れる）。"""
    if clock is None or clock.order is None:
        return None, None
    talk = [r for r in rows if r.get("source") in C.MEMO_SOURCES]
    before = [r for r in talk if r["order"] <= clock.order]
    after = [r for r in talk if r["order"] > clock.order]
    return (before[-1] if before else None), (after[0] if after else None)
