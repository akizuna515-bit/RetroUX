"""Fact → Guide Topic → Topic State（RX3-0072 / 2026-09-03）。

★★ 攻略情報を**自動生成しません** ★★

  ⚠ 大きな攻略 Topic は、**人が編集した Master** を正とします。
    ★Fact 側から新しい Topic を勝手に作りません。

```text
勇者メモ（人が書く / data/dq3/hero-memo.yaml）               ＝ 設計情報
      ↓ hero_memo.build() が Topic と Rule に組み替える
Fact（RX3-0070 が実際の冒険から起こす）
      ↓
Topic State（work/ / ⚠ このプレイの進み具合）                ＝ 進行状況
```

⚠⚠ 2026-09-28（RX3-0455）: **旧経路は退役しました**。

```text
⚠ 旧 data/dq3/topic-rules.csv                 ★人が書いていた Rule 表
⚠ 旧 input/dq3_guide_topic_master*.csv        ★第三者の攻略情報から起こした Topic 表
```

★2026-10-03（RX3-0432）: 読む口（`load_master` / `load_rules` / `MASTER_PATH` / `RULES_PATH`）も消しました。
⚠ `TopicBook` は正本を**渡されたものだけ**使います（★省くと空 / 黙って旧 2 表を読まない）。
→ ⚠ 新しい Topic をここに足さないでください。**勇者メモに書きます**。

## ⚠ 守ること

```text
★照合は (kind, id) ＋ predicate     ⚠ 名前の文字列では照合しない
⚠ Master は**書き換えない**         ★進み具合は別ファイル
⚠⚠ 観測していない Fact で進めない   ★Fact が無ければ unknown のまま
⚠ 同じ Fact を二度当てない          ★`fact_id` で覚える
★1 つの Fact が複数 Topic に効いてよい（N:M）
```

## ★状態

```text
unknown     まだ Fact との接点が無い
discovered  関連する Fact を 1 件以上得た
active      ⚠ いま追う価値がある（★前提の Topic が片づいている）
resolved    ⚠ 完了の重みの Fact が当たった（★Stretch）
```
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib

from dq3.knowledge.guide_master import Topic  # noqa: F401 - ★再輸出

from .. import paths

#: ⚠ このプレイの進み具合（★Git の外 / playdata の作法に合わせる）
STATE_PATH = paths.lazy_work("dq3-knowledge", "topic-state.json")

#: ★この重み以上の Fact が当たったら「片づいた」とみなす（⚠ Stretch / §22）
RESOLVE_WEIGHT = 100

STATUSES = ("unknown", "discovered", "active", "resolved")


def _now() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


# --- ★静的な正本 -----------------------------------------------------------------

# ★`Topic` は `guide_master.py` にあります（⚠ 2026-09-04 に列が 25 に増えたため移した）。


@dataclasses.dataclass(frozen=True)
class Rule:
    """★Fact と Topic を結ぶ条件（⚠ 名前ではなく id で書く）。

    ★`source`: `explicit` = 人が書いた条件（★勇者メモ）/
      `master` = 旧 Guide Master の関連名から作っていた弱い Rule
      （⚠ 作る側は 2026-10-03 に消した / RX3-0432。★値の意味だけ残す）。
    """

    rule_id: str
    topic_id: str
    entity_kind: str = ""
    entity_id: int | None = None
    predicate: str = ""
    place_type: str = ""
    location_id: str = ""
    match_mode: str = "ANY"
    weight: int = 0
    notes: str = ""
    source: str = "explicit"
    #: ★2026-09-05（RX3-0076）: id の代わりに**名前**で書ける（⚠ 実行時に ROM / 場所表で解く）
    entity_name: str = ""
    #: ★`match_mode = ALL` のとき、同じ group の Rule が**全部**当たって初めて片づく
    group: str = ""

    @property
    def completes(self) -> bool:
        """★これが当たれば片づく（⚠ 明示 Rule の 100 だけ / 指示書 §11）。"""
        return self.source == "explicit" and self.weight >= RESOLVE_WEIGHT

    @property
    def needs_resolve(self) -> bool:
        """⚠ 名前で書かれていて、まだ id に解けていない。"""
        return self.subject() is None and bool(self.entity_name)

    def resolved(self, entity_id, location_id: str = "") -> "Rule":
        """★解けた id を入れた Rule（⚠ 元は変えない）。"""
        if self.entity_kind == "location":
            return dataclasses.replace(self, location_id=location_id)
        return dataclasses.replace(self, entity_id=int(entity_id))

    def subject(self) -> str | None:
        """★この規則が待っている subject（⚠ Fact と同じ書き方）。"""
        if self.entity_kind == "event":
            # ★物語の旗は名前で書く（RX3-0211 / `data/dq3/story-flags.csv` の flag_id）
            return "event:%s" % self.entity_name if self.entity_name else None
        if self.entity_kind == "location":
            # ★場所は `location:L<map_id>`（⚠ 名前ではなく id / RX3-0076）
            return "location:%s" % self.location_id if self.location_id else None
        if self.entity_kind == "word":
            # ★一般の語（`concept-words.csv` / RX3-0436）は書いた語そのもの
            return "word:%s" % self.entity_name if self.entity_name else None
        if self.entity_kind and self.entity_id is not None:
            return "%s:%d" % (self.entity_kind, self.entity_id)
        if self.place_type:
            return "place_type:%s" % self.place_type
        return None

    def matches(self, fact: dict) -> bool:
        """★`(kind, id) + predicate` で当てる。⚠ 名前は見ない。"""
        if self.predicate and fact.get("predicate") != self.predicate:
            return False
        want = self.subject()
        if want is None:
            return False                      # ⚠ 条件が空の規則は当てない
        return fact.get("subject") == want


# --- ★このプレイの進み具合 ---------------------------------------------------------

@dataclasses.dataclass
class TopicState:
    """⚠ Master とは**別**に持つ（★指示書 §10）。"""

    topic_id: str
    status: str = "unknown"
    matched_fact_ids: list[str] = dataclasses.field(default_factory=list)
    matched_rule_ids: list[str] = dataclasses.field(default_factory=list)
    best_weight: int = 0
    first_seen_at: str | None = None
    last_updated_at: str | None = None
    update_count: int = 0
    #: ★片づいた時刻（RX3-0434 / 勇者メモの scenario で「分かったこと」を新しい順に並べる）
    #:  ⚠ 片づいた後に同じ話をまた聞くと `last_updated_at` は進むので、★別に持つ
    resolved_at: str | None = None

    def to_json(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "TopicState":
        return cls(
            topic_id=data["topic_id"],
            status=data.get("status", "unknown"),
            matched_fact_ids=list(data.get("matched_fact_ids") or []),
            matched_rule_ids=list(data.get("matched_rule_ids") or []),
            best_weight=int(data.get("best_weight") or 0),
            first_seen_at=data.get("first_seen_at"),
            last_updated_at=data.get("last_updated_at"),
            update_count=int(data.get("update_count") or 0),
            resolved_at=data.get("resolved_at"))


class TopicBook:
    """★Fact を Topic へ当て、進み具合を覚える。"""

    def __init__(self, master=None, rules=None, path=None, require_appear: bool = False) -> None:
        #: ★出る条件が 1 度も成立していない Topic は、片づいても見せない（RX3-0436 / 勇者メモ）。
        #:   ⚠ 片づく条件だけ先に成立すると「分かったこと」に出て、**出ていないカードが漏れる**。
        self.require_appear = require_appear
        # ⚠ 2026-10-03（RX3-0432）: 省いたら空（★以前は旧 2 表を黙って読んでいた）
        self.master = master if master is not None else {}
        self.rules = rules if rules is not None else []
        self.path = pathlib.Path(path) if path is not None else STATE_PATH
        self.states: dict[str, TopicState] = {}
        self._dirty = False
        #: ⚠ 正本に無い topic_id を指す規則（★人の書き間違いを黙って捨てない）
        self.orphan_rules = [r.rule_id for r in self.rules if r.topic_id not in self.master]

    # --- ★当てる -------------------------------------------------------------

    def apply(self, fact: dict) -> list[str]:
        """★1 つの Fact を当てる。⚠ 動いた Topic の id を返す。

        ⚠⚠ **同じ Fact を二度当てません**（★`fact_id` で覚える / 指示書 §12）。
        ★1 つの Fact が複数 Topic に効いてよい（N:M / §13）。
        """
        fact_id = fact.get("fact_id")
        if not fact_id:
            return []
        moved = []
        for rule in self.rules:
            if rule.topic_id not in self.master:
                continue                      # ⚠ 正本に無い Topic は進めない
            if not rule.matches(fact):
                continue
            state = self.states.get(rule.topic_id)
            if state is None:
                # ⚠ `first_seen_at` は**見えた瞬間**に刻む（`_set_status` / RX3-0436）。
                #   ★AND の組の 1 本目が当たっただけでは、まだ勇者はこの話を知らない
                state = TopicState(topic_id=rule.topic_id)
                self.states[rule.topic_id] = state
            if fact_id in state.matched_fact_ids and rule.rule_id in state.matched_rule_ids:
                continue                      # ⚠ 同じ Rule で二度目は数えない
            # ★★ 2026-09-12（RX3-0211）: 以前は同じ Fact を Topic ごとに 1 回だけ当てていた。
            #   ⚠ 後から足した完了の Rule が、既に当たった Fact（★めざめのこなの入手 等）で当たらなかった。
            #   → ★Rule が違えば当てる（⚠ Fact の一覧には 1 回だけ残す）
            if fact_id not in state.matched_fact_ids:
                state.matched_fact_ids.append(fact_id)
            if rule.rule_id not in state.matched_rule_ids:
                state.matched_rule_ids.append(rule.rule_id)
            state.best_weight = max(state.best_weight, rule.weight)
            self._set_status(state, self._status_of(rule.topic_id, state))
            self._dirty = True
            if state.status == "unknown":
                # ⚠⚠ まだ見えない（AND の組が途中）→ 数えない・動いたと言わない（RX3-0436）。
                #   ★数えると、見えた瞬間に NEW ではなく「更新」になる / ⚠ moved から題名が漏れる
                continue
            state.update_count += 1
            state.last_updated_at = _now()
            moved.append(rule.topic_id)
        if moved:
            self._refresh_statuses()
        return moved

    def rename_facts(self, mapping: dict) -> int:
        """★Fact の番号を付け替える（⚠ 数えない / 更新回数・時刻は変えない）。戻り値: 付け替えた数。

        ★RX3-0235: 勇者メモの会話の Fact の番号を、行番号から通し番号（order）へ移したときに 1 度だけ使う
        （⚠ 付け替えないと、同じ話が新しい Fact として当たり直し、Topic の更新回数が進む）。
        """
        n = 0
        for state in self.states.values():
            ids = state.matched_fact_ids
            fresh: list[str] = []
            for fid in ids:
                new = mapping.get(fid, fid)
                if new != fid:
                    n += 1
                # ★2026-09-27（RX3-0436）: 観測ごとの Fact を論理 Fact へ畳むと、
                #   ★複数の番号が同じ番号になる → ⚠ 1 つに畳む（並びは最初に出た位置）
                if new not in fresh:
                    fresh.append(new)
            state.matched_fact_ids = fresh
        if n:
            self._dirty = True
        return n

    def _refresh_statuses(self) -> None:
        """★前提が片づいたら、待っていた Topic を discovered → active に上げる（RX3-0076）。

        ⚠⚠ 2026-09-05: 状態は「その Topic に Fact が当たったとき」しか決め直して
          いなかった。★A が resolved になっても、先に discovered になっていた B は
          **次の Fact が来るまで discovered のまま**だった（検査で踏んだ）。
          → ★何かが動いたら全部決め直す（⚠ 30 件なので安い。update_count は触らない）。
        """
        for topic_id, state in self.states.items():
            if topic_id not in self.master:
                continue
            fresh = self._status_of(topic_id, state)
            if fresh != state.status:
                self._set_status(state, fresh)
                self._dirty = True

    @staticmethod
    def _set_status(state: TopicState, status: str) -> None:
        """★状態を変える（⚠ 片づいた瞬間だけ `resolved_at` を刻む / 戻ったら消す）。

        ★見えた瞬間（`unknown` 以外になった最初）に `first_seen_at` を刻む（RX3-0436）。
        """
        if status != "unknown" and state.first_seen_at is None:
            state.first_seen_at = _now()
        if status == "resolved" and state.status != "resolved":
            state.resolved_at = _now()
        elif status != "resolved":
            state.resolved_at = None
        state.status = status

    def apply_all(self, facts) -> dict[str, list[str]]:
        got: dict[str, list[str]] = {}
        for fact in facts:
            for topic_id in self.apply(fact):
                got.setdefault(topic_id, []).append(fact.get("fact_id"))
        return got

    def completed(self, topic_id: str, state: TopicState) -> bool:
        """★片づいたか（⚠ 明示 Rule だけ / RX3-0076 で ALL 条件を足した）。

        ```text
        ANY   weight 100 の明示 Rule が 1 本でも当たった
        ALL   同じ group の Rule が**全部**当たった（★6 色のオーブ など）
        ```
        ⚠ 弱い Rule（source = master）は何本当たっても片づけない。
        """
        matched = set(state.matched_rule_ids)
        # ★ALL の group: 条件（★`#` の前 = 元の rule_id）ごとに「同名 2 id のどれか」が当たればよい
        groups: dict[str, dict[str, bool]] = {}
        for rule in self.rules:
            if rule.topic_id != topic_id or not rule.completes:
                continue
            if rule.match_mode == "ALL":
                base = rule.rule_id.split("#", 1)[0]
                conds = groups.setdefault(rule.group or base, {})
                conds[base] = conds.get(base, False) or (rule.rule_id in matched)
            elif rule.rule_id in matched:
                return True
        for conds in groups.values():
            if conds and all(conds.values()):
                return True
        return False

    def appeared(self, topic_id: str, state: TopicState) -> bool:
        """★見えてよいか（RX3-0436 / 勇者メモの `all_of`）。

        ```text
        出る側に ALL の組が無い Topic   ★今までどおり（何か 1 本当たれば見える）
        ALL の組がある Topic            ★ANY の出る Rule が当たった / ALL の組が全部当たった
                                        ⚠ 片づく Rule の途中（retires_all の 1 本目）では見せない
        ```
        ⚠ 片づいたかどうかは先に `completed` が見る（★片づいた話は「分かったこと」に出る）。
        """
        rules = [r for r in self.rules if r.topic_id == topic_id and not r.completes]
        if not self.require_appear and not any(r.match_mode == "ALL" for r in rules):
            return True
        matched = set(state.matched_rule_ids)
        groups: dict[str, dict[str, bool]] = {}
        for rule in rules:
            if rule.match_mode != "ALL":
                if rule.rule_id in matched:
                    return True
                continue
            base = rule.rule_id.split("#", 1)[0]
            conds = groups.setdefault(rule.group or base, {})
            conds[base] = conds.get(base, False) or (rule.rule_id in matched)
        return any(conds and all(conds.values()) for conds in groups.values())

    def _status_of(self, topic_id: str, state: TopicState) -> str:
        """★状態を決める（指示書 §10）。"""
        appeared = self.appeared(topic_id, state)
        if self.completed(topic_id, state) and (appeared or not self.require_appear):
            return "resolved"                 # ★完了条件が成立した
        if not appeared:
            return "unknown"                  # ⚠ 出る条件が未成立（★まだ勇者は知らない）
        topic = self.master[topic_id]
        for need in topic.prerequisite_topic_ids:
            done = self.states.get(need)
            if done is None or done.status != "resolved":
                # ⚠ 前提が片づいていない → ★追う段ではない
                return "discovered"
        return "active"

    # --- ★出す ---------------------------------------------------------------

    def state(self, topic_id: str) -> TopicState:
        """⚠ 触れていない Topic は `unknown`（★勝手に進めない）。"""
        return self.states.get(topic_id) or TopicState(topic_id=topic_id)

    def ordered(self, statuses=("active", "discovered")) -> list[tuple[Topic, TopicState]]:
        """★勇者会議の一覧の並び（⚠ priority DESC → last_updated_at DESC / 指示書 §21）。

        ★安定ソートを**弱い鍵から順に**かけます（⚠ 最後にかけた鍵が最優先）。
        """
        got = []
        for topic_id, topic in self.master.items():
            state = self.state(topic_id)
            if state.status in statuses:
                got.append((topic, state))
        got.sort(key=lambda pair: pair[1].last_updated_at or "", reverse=True)
        got.sort(key=lambda pair: -pair[0].priority)
        return got

    def head_candidate(self) -> dict | None:
        """★いちばん上に出す候補を 1 件。

        ⚠⚠ 判定は `council.pick_head` の **1 か所**にあります（★ここは入口だけ）。
          同じ判定を 2 か所に書いて片方だけ直る事故を避けるためです。
        """
        from dq3.knowledge import council

        return council.pick_head(self)

    # --- ★しまう・戻す ---------------------------------------------------------

    def save(self, force: bool = False) -> bool:
        if not force and not self._dirty:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(
                {"game": "dq3",
                 "topics": {k: v.to_json() for k, v in sorted(self.states.items())}},
                ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            return False
        self._dirty = False
        return True

    @classmethod
    def load(cls, master=None, rules=None, path=None, require_appear: bool = False) -> "TopicBook":
        got = cls(master, rules, path, require_appear=require_appear)
        try:
            data = json.loads(got.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return got
        for topic_id, row in (data.get("topics") or {}).items():
            try:
                got.states[topic_id] = TopicState.from_json(row)
            except (KeyError, TypeError, ValueError):
                continue                      # ⚠ 壊れた行は捨てて、残りは読む
        if require_appear:
            # ★保存された状態は古い規則で決めたもの → ⚠ 今の規則で決め直す（RX3-0436）
            got._refresh_statuses()
        return got


# --- ★CLI ------------------------------------------------------------------------

def main(argv=None) -> int:
    import argparse
    import sys

    from dq3.knowledge import concepts as C

    parser = argparse.ArgumentParser(description="Fact → 勇者メモのカード → Topic State")
    parser.add_argument("--state", default=None, help="進み具合の置き場（⚠ work/ 配下）")
    parser.add_argument("--dry-run", action="store_true", help="★書かずに見るだけ")
    args = parser.parse_args(argv)

    # ★2026-09-28（RX3-0455）: 旧 Guide Master / topic-rules.csv をやめ、**勇者メモ**を読む。
    #   ⚠ 旧 2 表は第三者の攻略サイト由来で、★公開物にも入りません。
    from dq3.knowledge import hero_memo as HM

    try:
        built = HM.build(HM.DEFAULT_PATH)
    except HM.HeroMemoError as exc:
        print("⚠⚠ %s" % exc, file=sys.stderr)
        return 1
    if not built.topics:
        print("⚠ 勇者メモの原本がありません: %s" % HM.DEFAULT_PATH, file=sys.stderr)
        return 1
    master, rules = built.as_master(), built.rules
    book = TopicBook.load(master=master.topics, rules=rules, path=args.state,
                          require_appear=True)
    if book.orphan_rules:
        print("⚠ 正本に無い Topic を指す規則: %s" % book.orphan_rules, file=sys.stderr)

    matcher = C.Matcher()
    facts = []
    for observation in C.observations():
        facts.extend(C.analyse(observation, matcher)["facts"])
    print("★Fact %d 件 / Topic %d 件 / 規則 %d 件" % (len(facts), len(book.master), len(book.rules)))
    moved = book.apply_all(facts)
    for topic_id, fact_ids in moved.items():
        state = book.state(topic_id)
        print("  ★%s %s ← %s（更新 %d 回 / %s）"
              % (topic_id, state.status, fact_ids, state.update_count, state.last_updated_at))
    for topic, state in book.ordered():
        print("  %-5s %-10s priority %3d  %s" % (topic.topic_id, state.status, topic.priority, topic.title))
    head = book.head_candidate()
    print("★いちばん上の候補:", json.dumps(head, ensure_ascii=False) if head else "（無し）")
    if not args.dry_run:
        book.save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
