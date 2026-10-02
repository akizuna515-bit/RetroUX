"""勇者メモの scenario を、カードの状態から導く（RX3-0434 / 2026-09-27）。

## ★scenario は「束ねる文脈」で、進行を制御しない

```text
カードの状態（TopicBook）   ★出る・片づくは**カードの Fact だけ**で決まる
        ↓ ここ（⚠ 毎回導く。保存しない）
ScenarioView               ★その時点の勇者が「何の話として」気にしているか
```

## ★状態は 3 つだけ

```text
hidden   所属する見えているカードが 0 枚        → ⚠ 何も出さない（題名も）
open     対応中のカードが 1 枚以上              → 見出し ＋ 気になっていること
quiet    見えているカードはあるが対応中が 0 枚   → 「いまは気になることはない」
```

⚠⚠ **`resolved` は作りません**（2026-09-27 依頼者の確定）。
★「見えているカードが全部片づいた」は、勇者が**いま知っている範囲で**片づいた、でしかありません。
⚠ 「完了」と言えば後から出るカードで**誤り**になり、「まだ続きがある」と言えば**漏れ**になります。
→ ★`quiet` は戻れる状態です。新しいカードが 1 枚出れば `open` に戻ります。

## ⚠ 漏らさないこと

★ScenarioView には**見えているカードだけ**を入れます（⚠ 画面側が漏らしようのない形で渡す）。
⚠ 件数・分母・未発見のカードの題名は、ここから先へ**そもそも渡りません**。

## ★並び（⚠ id 順・YAML の順・scenario 定義の順は**使わない**）

```text
気になっていること   出た順（first_seen_at）
分かったこと         片づいた順の新しいほうから（resolved_at）
scenario どうし      所属カードのいちばん最近動いた時刻の新しいほうから
```

⚠ 時刻は秒までなので、★初回の評価では多くが同じ時刻になります。
→ ★同じ時刻なら、当たった Fact の並び（記録の順）で決めます。
"""
from __future__ import annotations

import dataclasses

HIDDEN = "hidden"
OPEN = "open"
QUIET = "quiet"

#: ★対応中として数える状態（⚠ 勇者メモは前提を持たないので discovered は実際には出ない）
ACTIVE = ("active", "discovered")
RESOLVED = "resolved"

#: ★quiet のときに出す言葉（⚠⚠ 「完了」「まだ続きがある」は出さない）
QUIET_TEXT = "いまは気になることはない"


@dataclasses.dataclass(frozen=True)
class ScenarioView:
    """★画面に出す scenario 1 つ（⚠ 見えているカードだけ）。"""

    scenario_id: str
    title: str
    state: str
    #: ★気になっていること（card の dict / 出た順）
    open_cards: tuple = ()
    #: ★分かったこと（card の dict / 片づいた順の新しいほうから）
    done_cards: tuple = ()


def state_of(statuses) -> str:
    """★所属カードの状態の並び → hidden / open / quiet。"""
    seen = [s for s in statuses if s in ACTIVE or s == RESOLVED]
    if not seen:
        return HIDDEN
    if any(s in ACTIVE for s in seen):
        return OPEN
    return QUIET


def _positions(state, fact_pos: dict) -> list[int]:
    return [fact_pos[f] for f in state.matched_fact_ids if f in fact_pos]


def _first_key(state, fact_pos: dict) -> tuple:
    return (state.first_seen_at or "", min(_positions(state, fact_pos), default=len(fact_pos)))


def _last_key(state, fact_pos: dict) -> tuple:
    return (state.last_updated_at or "", max(_positions(state, fact_pos), default=-1))


def _resolved_key(state, fact_pos: dict) -> tuple:
    # ⚠ `resolved_at` の無い古い記録は、最後に動いた時刻で代える
    return (state.resolved_at or state.last_updated_at or "",
            max(_positions(state, fact_pos), default=-1))


def build(titles: dict, scenario_of: dict, book, cards: dict,
          fact_pos: dict | None = None) -> list[ScenarioView]:
    """★scenario ごとに束ねる（⚠ hidden は返さない）。

    titles       scenario id → title
    scenario_of  topic_id → scenario id
    book         `TopicBook`（★`state(topic_id)` だけ使う）
    cards        topic_id → card の dict（⚠ 見えているカードだけ入っている想定）
    fact_pos     fact_id → 記録の中の位置（★同じ時刻のときの決め手）
    """
    fact_pos = fact_pos or {}
    members: dict[str, list[str]] = {}
    for topic_id, sid in scenario_of.items():
        if sid in titles:
            members.setdefault(sid, []).append(topic_id)

    got = []
    for sid, topic_ids in members.items():
        states = {tid: book.state(tid) for tid in topic_ids}
        state = state_of(s.status for s in states.values())
        if state == HIDDEN:
            continue
        # ⚠⚠ ここで**見えているカードだけ**に絞る（★以降に未発見のカードは渡らない）
        open_ids = [t for t in topic_ids if states[t].status in ACTIVE and t in cards]
        done_ids = [t for t in topic_ids if states[t].status == RESOLVED and t in cards]
        if not open_ids and not done_ids:
            continue
        open_ids.sort(key=lambda t: _first_key(states[t], fact_pos))
        done_ids.sort(key=lambda t: _resolved_key(states[t], fact_pos), reverse=True)
        moved = max(_last_key(states[t], fact_pos) for t in open_ids + done_ids)
        got.append((moved, ScenarioView(
            scenario_id=sid, title=titles[sid], state=state,
            open_cards=tuple(cards[t] for t in open_ids),
            done_cards=tuple(cards[t] for t in done_ids))))
    got.sort(key=lambda pair: pair[0], reverse=True)
    return [view for _moved, view in got]
