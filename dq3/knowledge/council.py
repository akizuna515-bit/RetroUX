"""勇者会議 AI v1 — 「次に何をするのが自然か」を**規則で**決める（RX3-0074 / 2026-09-04）。

★★ LLM は使いません。作文もしません ★★

```text
勇者メモ（人が書く / data/dq3/hero-memo.yaml）  ★Topic と Rule はここから組む
  + Fact（実際に聞いた会話から / concepts）
  + Topic State（このプレイの進み具合 / work/）
        ↓ ここ
次に追う Topic（Head）／その理由／最近動いた Topic
```

⚠⚠ 2026-09-28（RX3-0455）: 旧経路（`input/` の Guide Master ＋
`data/dq3/topic-rules.csv` ＋ `guide_mapping` の弱い Rule）は**退役しました**。
★2026-10-03（RX3-0432）: 旧経路の分岐と `use_hero_memo` / `master_path` / `rules_path` を**消しました**。
⚠ 以前は既定が旧経路（`use_hero_memo=False`）で、★引数を書き忘れると黙って旧 2 表を読んでいました。
→ ★勇者メモだけが正本です（⚠ 切り替えの口はもうありません）。

## ★Head の決め方（指示書 §12〜§13）

```text
1 category      main → sub → exploration / utility
2 requiredness  required / practical_required → optional
3 priority      大きいほう
4 更新          最近動いたほう
5 sequence      小さいほう（★同点の最後の決め手）
⚠ active だけ   ★resolved / discovered / unknown は Head にしない
```

⚠ main が全部 unknown で sub だけ active なら、★sub が Head になります（§13）。

## ⚠⚠ 守ること

```text
⚠ 文章を作らない        ★ui_head_hint → objective → title の順に**そのまま**出す（§15）
⚠ 根拠は id と種類だけ   ★原文は詳細を開いたときだけ（§17）
⚠ 毎フレーム評価しない   ★会議の画面を開いたとき／「更新」で評価する（§25）
⚠ 状態は Qt を知らない   ★この module は画面なしで検査できる
```
"""
from __future__ import annotations

import dataclasses
import datetime

from dq3.knowledge import guide as G
from dq3.knowledge import guide_master as GM
from dq3.knowledge import rom_names

#: ★category の優先（⚠ 小さいほど先 / §13）
CATEGORY_RANK = {"main": 0, "sub": 1, "exploration": 2, "utility": 2}
#: ★requiredness の優先
REQUIREDNESS_RANK = {"required": 0, "practical_required": 0, "optional": 1}

#: ★predicate → 人が読める根拠（⚠ 原文は出さない / §17）
REASON_OF = {
    "obtain_hint": "その品を手に入れたかと尋ねられた",
    "obtain": "その品を手に入れた",
    "defeat": "その敵を倒した",
    "visit": "その場所へ行った",
    "": "関係のある名前や場所に触れた",
}

#: ★分類の見出し（⚠ 画面用。★Master の語をそのまま出さない）
#: ★★ ⚠⚠ 画面へ出す言葉は**ここだけ**（RX3-0123 / 2026-09-08）★★
#:
#:   ⚠ 内部の値（`main` / `active` / `update_count`）は**変えません**。
#:   ★変えるのは言い換えの表と、⚠ それを使う 2 か所（`pick_head` / `detail_lines`）。
#:
#:   ```text
#:   internal          UI
#:   main              メイン       ⚠ 「本筋」は物語の用語に読めた
#:   active            対応中       ⚠ 「追える」は状態の直訳だった
#:   update_count=2    更新 2 回    ⚠⚠ 「この話は 2 回動いた」をやめる
#:   ```
CATEGORY_LABEL = {"main": "メイン", "sub": "寄り道", "exploration": "探索", "utility": "支度"}
STATUS_LABEL = {"unknown": "未知", "discovered": "手がかりあり", "active": "対応中", "resolved": "完了"}


def update_text(count, when: str = "") -> str:
    """★「更新 N 回」（⚠ `when` があれば「/ 最後 …」を足す）。

    ## ⚠⚠ 「進展 N 回」にしない（2026-09-08 依頼者）

      ★「進展」だと **攻略が N 段階進んだ**と読めます。
      ⚠ 実体は Fact / Topic の**更新回数**なので、★意味を盛りません。
    """
    got = "更新 %d 回" % int(count or 0)
    return "%s / 最後 %s" % (got, when) if when else got


def _sort_key_head(pair) -> tuple:
    topic, _state = pair
    return (CATEGORY_RANK.get(topic.category, 3),
            REQUIREDNESS_RANK.get(topic.requiredness, 2),
            -topic.priority)


def rank_active(book: G.TopicBook) -> list:
    """★active な Topic を Head の優先順に並べる（⚠ 安定ソートを弱い鍵から）。"""
    rows = [(t, book.state(tid)) for tid, t in book.master.items()
            if book.state(tid).status == "active"]
    rows.sort(key=lambda p: (p[0].sequence is None, p[0].sequence or 0))       # 5
    rows.sort(key=lambda p: p[1].last_updated_at or "", reverse=True)          # 4
    rows.sort(key=_sort_key_head)                                              # 1-3
    return rows


def _entity_name(rule: G.Rule, catalog=None) -> str | None:
    """★Rule の相手の名前（⚠ 場所は catalog、品・敵は ROM。無ければ None）。"""
    if rule.entity_kind == "location":
        return catalog.place(rule.location_id).name if (catalog is not None and rule.location_id) else None
    if rule.entity_kind in ("item", "monster", "spell") and rule.entity_id is not None:
        return rom_names.name(rule.entity_kind, rule.entity_id)
    if rule.entity_kind == "event":
        from dq3.knowledge.story import label_of     # ★物語の旗（RX3-0211）

        return label_of(rule.entity_name)
    return None


def reasons_for(state: G.TopicState, rules_by_id: dict, catalog=None) -> list[str]:
    """★「なぜ上がったか」（⚠ id と種類だけ。原文は詳細で）。"""
    got: list[str] = []
    seen_pred: set[str] = set()
    for rule_id in state.matched_rule_ids:
        rule = rules_by_id.get(rule_id)
        if rule is None:
            continue
        key = rule.predicate
        if key in seen_pred:
            continue
        seen_pred.add(key)
        name = _entity_name(rule, catalog)
        text = REASON_OF.get(key, "関係のある話を聞いた")
        got.append("%s（%s）" % (text, name) if name else text)
    if state.update_count:
        # ⚠ 言い換えは `update_text` の 1 か所（RX3-0123）
        got.append(update_text(state.update_count, _short(state.last_updated_at)))
    return got


def _short(stamp: str | None) -> str:
    if not stamp:
        return "—"
    try:
        return datetime.datetime.fromisoformat(stamp).strftime("%m/%d %H:%M")
    except ValueError:
        return stamp


def badge_of(state: G.TopicState) -> str:
    """★NEW / 更新（⚠ 動いていない Topic は空 / §22）。"""
    if state.update_count == 1:
        return "NEW"
    if state.update_count > 1:
        return "更新"
    return ""


def location_marks(topic: GM.Topic, catalog=None) -> list[str]:
    """★関連する場所の表示（⚠ 解けた場所だけ id と「行った」を添える / RX3-0076）。"""
    got = []
    for written in topic.related_location_names:
        loc = catalog.resolve(written) if catalog is not None else None
        if loc is None:
            got.append(written)
            continue
        place = catalog.place(loc)
        got.append("%s（%s%s）" % (written, loc, " / 行った" if place.visited else ""))
    return got


def nav_target_of(topic: GM.Topic, catalog=None) -> str | None:
    """★[ここへ向かう] の行き先（⚠ **明示された場所だけ** / §26-27）。

    ## ⚠⚠ 2026-09-27（RX3-0432 / 依頼者の判断「案 A」）に変えました

    ★もとは `location_id` が空なら **関連する場所（`related_location_names`）の
    名前が解けた最初のもの**を行き先にしていました。
    ⚠ そこは勇者メモの `about`（＝ ただのコメント）が入る欄で、
      ★「メモに地名が書いてある」から「そこへ行け」を導いていました。

    > 依頼者（2026-09-27）「関連を勇者が把握しきるのはイベント終了後。単にコメントと思っていた」

    → ★行き先は **`location_id` に明示されたときだけ**にします。
      ⚠ 関連する場所は「関連する場所」欄に**表示するだけ**（`location_marks`）。
    """
    return topic.location_id or None


#: ★名前の分からない場所の見せ方（RX3-0248 / 依頼者の案「不明（L23)とか？」）
UNKNOWN_PLACE = "不明"


def place_label(location_id: str | None, catalog=None) -> str:
    """★場所の見せ方: 名前が分かれば「ジパング（L23）」、分からなければ「不明（L23）」（RX3-0248）。

    ⚠⚠ 2026-09-13 依頼者「行き先候補のL23が意味不明。 表示を工夫できないか？ 不明（L23)とか？」
    ★名前は場所の表（`catalog.place`: 勇者が知った名前 / 承認済みの名前）から引く（⚠ 知らない場所の名前は出さない）。
    """
    if not location_id:
        return ""
    name = None
    if catalog is not None:
        try:
            name = catalog.place(location_id).name
        except Exception:                                # noqa: BLE001
            name = None
    return "%s（%s）" % (name or UNKNOWN_PLACE, location_id)


def pick_head(book: G.TopicBook, catalog=None) -> dict | None:
    """★いちばん上に出す候補を 1 件（⚠ active だけ / §12）。"""
    rows = rank_active(book)
    if not rows:
        return None
    topic, state = rows[0]
    rules_by_id = {r.rule_id: r for r in book.rules}
    return {
        "topic_id": topic.topic_id, "title": topic.title,
        "ui_head_hint": topic.ui_head_hint, "message": topic.head_message,
        "category": topic.category, "priority": topic.priority,
        "status": state.status, "reason_fact_ids": list(state.matched_fact_ids),
        "reasons": reasons_for(state, rules_by_id, catalog),
        "clue_count": len(state.matched_fact_ids),
        "last_updated_at": state.last_updated_at,
        # ★[ここへ向かう] の受け口（⚠ 証拠で解けた location_id だけ / §26-27）
        "nav_target": nav_target_of(topic, catalog),
        "related_locations": location_marks(topic, catalog),
    }


# --- ★画面へ渡す形 ---------------------------------------------------------------

#: ★まだ何も起きていない Topic（⚠⚠ **勇者はこの話を知りません**）
UNKNOWN = "unknown"


def known_topic(book) -> "callable":
    """★「勇者が知っている話か」を返す関数（RX3-0117）。

    ⚠⚠ **World Knowledge ≠ 表示してよいもの。**

    ```text
    ROM / Guide Master で存在を知っている   ★正本（⚠ 消さない）
      → ★Player Knowledge の濾し器          ⚠⚠ ここ
        → 勇者会議のチャート
    ```

    ★`unknown` の Topic は、⚠ **題名も件数も**出しません。
    """
    def known(topic_id) -> bool:
        try:
            return book.state(topic_id).status != UNKNOWN
        except Exception:                                # noqa: BLE001
            return False                                 # ⚠ 分からないものは出さない

    return known


def card_of(topic: GM.Topic, state: G.TopicState, master: GM.GuideMaster, catalog=None,
            known=None) -> dict:
    """★Topic 1 件の札（⚠ Fact を並べない / §20）。

    `known` … ★「その Topic を勇者が知っているか」を返す関数（RX3-0117）。
    ⚠ 渡すと、**知っている子だけ**を `children` に入れます
    （⚠⚠ 渡さないと、★後続 Topic の題名がそのまま次の攻略先になります）。
    """
    children = [c.topic_id for c in master.children(topic.topic_id)]
    if known is not None:
        children = [c for c in children if known(c)]
    nav = nav_target_of(topic, catalog)
    return {
        "nav_target": nav,
        "nav_target_label": place_label(nav, catalog),       # ★RX3-0248: 「ジパング（L23）」/「不明（L23）」
        "topic_id": topic.topic_id, "title": topic.title,
        "category": topic.category, "category_label": CATEGORY_LABEL.get(topic.category, topic.category),
        "status": state.status, "status_label": STATUS_LABEL.get(state.status, state.status),
        "priority": topic.priority, "sequence": topic.sequence, "phase": topic.phase,
        "last_updated_at": state.last_updated_at, "last_updated_label": _short(state.last_updated_at),
        "update_count": state.update_count, "badge": badge_of(state),
        "objective": topic.objective, "completion_hint": topic.completion_hint,
        "message": topic.head_message,
        "parent_topic_id": topic.parent_topic_id,
        "children": children,
        "related_locations": location_marks(topic, catalog),
        "matched_fact_ids": list(state.matched_fact_ids),
        "matched_rule_ids": list(state.matched_rule_ids),
    }


@dataclasses.dataclass
class CouncilView:
    """★勇者会議の画面が描くもの（⚠ Qt を知らない）。"""

    ok: bool = True
    error: str = ""
    master_path: str = ""
    topic_count: int = 0
    fact_count: int = 0
    head: dict | None = None
    #: ★active / discovered（priority DESC → 更新 DESC）
    recent: list = dataclasses.field(default_factory=list)
    #: ★resolved（⚠ 消さない。畳んで出す / §24）
    resolved: list = dataclasses.field(default_factory=list)
    #: ⚠⚠ **常に空**（RX3-0117 / 2026-09-08 に依頼者の判断で取り下げ）。
    #:
    #: ★もとは「まだ何も無い Topic」を一覧の下に出していました
    #: （⚠ 2026-09-04「存在は攻略のネタバレではない」）。
    #: ⚠⚠ 札が `objective` / `completion_hint` / `children` を持つため、
    #: ★**知らないはずの攻略先が読めていました**。
    #:
    #: ⚠ 欄そのものは残します（★画面の作りを変えないため。⚠ 中身は入れない）。
    unknown: list = dataclasses.field(default_factory=list)
    moved: dict = dataclasses.field(default_factory=dict)
    #: ★詳細で「関連 Fact」を出すための材料（fact_id → {subject, predicate, name, observation, text}）
    facts: dict = dataclasses.field(default_factory=dict)
    resolution_summary: dict = dataclasses.field(default_factory=dict)
    #: ★起きたことの数（items / defeated / visited / RX3-0076）
    progress: dict = dataclasses.field(default_factory=dict)
    #: ★★ 勇者が知っていて、まだ行っていない場所（`reachable.Reachable` / RX3-0113）
    #:
    #:   ⚠⚠ **ROM の 20 件を素で入れません。** ★`reachable.collect` の濾し器を通ったものだけ。
    #:   ⚠ 0 件なら空（★画面は節ごと出しません）。
    reachable: list = dataclasses.field(default_factory=list)
    #: ⚠ ゲームの `$0750` とこちらの記録の食い違い（★`reachable.compare_visited`）
    visited_diff: dict = dataclasses.field(default_factory=dict)
    #: ★勇者メモの scenario（`scenario_view.ScenarioView` / RX3-0434）
    #:   ⚠ 見えているカードがある scenario だけ
    scenarios: list = dataclasses.field(default_factory=list)


class Council:
    """★評価の入口（⚠ 開いたとき／更新ボタンで 1 回 / §25）。"""

    def __init__(self, state_path=None, *, rom_path=None,
                 knowledge_path=None, progress_path=None, game_state_path=None,
                 vm=None, catalog=None, hero_memo_path=None) -> None:
        # ⚠ 2026-10-03（RX3-0432）: `rules_path` / `master_path` / `use_hero_memo` を消した。
        #   ★位置で渡していた呼び出しが黙って別の引数に入らないよう、★2 つめから名前で受ける。
        self.state_path = state_path
        #: ★人が書く原本（RX3-0432 / 既定は `data/dq3/hero-memo.yaml`）
        self.hero_memo_path = hero_memo_path
        self.rom_path = rom_path
        #: ★場所の名前・行った場所（player-knowledge.json）
        self.knowledge_path = knowledge_path
        #: ★起きたこと（progress.json）と、いまの state.json（⚠ vm があれば vm から）
        self.progress_path = progress_path
        self.game_state_path = game_state_path
        self.vm = vm
        self.catalog = catalog

    def _progress(self, PG, catalog):
        """★手に入れた / 倒した / 行った を取り込む（⚠ vm があれば生きた値、無ければファイル）。"""
        progress = PG.Progress.load(self.progress_path)
        if self.vm is not None:
            PG.gather(self.vm, progress)
        else:
            PG.gather(None, progress, state=PG.load_state(self.game_state_path),
                      enemy_book=self._enemy_book(), visited=catalog.visited)
        return progress

    def _enemy_book(self):
        try:
            from dq3.knowledge.enemies_seen import EnemyBook

            return EnemyBook.load()
        except Exception:                                  # noqa: BLE001
            return None

    def _facts(self):
        """★聞いた会話 → Fact（⚠ RX3-0070 のまま）。"""
        from dq3.knowledge import concepts as C

        matcher = C.Matcher(self.rom_path)
        facts, texts = [], {}
        # ★勇者メモの会話の番号を行番号から order へ移した（RX3-0235）→ ★Topic の記録を付け替える表（旧 → 新）
        legacy = C.legacy_memo_ids()
        self.legacy_fact_ids = {}
        for observation in C.observations():
            got = C.analyse(observation, matcher)
            for fact in got["facts"]:
                facts.append(fact)
                texts[fact["fact_id"]] = observation.text
                old = legacy.get(fact.get("source_observation_id"))
                if old is not None:
                    self.legacy_fact_ids[C.fact_id_of(fact.get("subject"), fact.get("predicate"),
                                                      fact.get("object"), old)] = fact["fact_id"]
        return facts, texts

    def evaluate(self, save: bool = True) -> CouncilView:
        view = CouncilView()
        # ★人が書いた「気になること」から作る（RX3-0432）。⚠ 攻略チャート（Guide Master）は読みません。
        from dq3.knowledge import hero_memo as HM

        try:
            built = HM.build(self.hero_memo_path, rom_path=self.rom_path)
        except HM.HeroMemoError as exc:
            view.ok = False
            view.error = str(exc)
            return view
        topics, rules = built.topics, built.rules
        # ★下流（`card_of` / `reachable`）は `GuideMaster` を要るので同じ形で渡す
        master = built.as_master()
        view.master_path = str(built.path or "")
        view.topic_count = len(topics)
        # ⚠ 解けなかった条件は**黙って捨てない**（★`resolution_summary` に残す）
        #   ★`resolution_summary` は辞書なので、⚠ 型を合わせる
        view.resolution_summary = {
            "unresolved": len(built.unresolved),
            "details": ["%s `%s: %s`（%s）" % row for row in built.unresolved[:10]],
        }

        # ★場所（RX3-0076）: 実プレイで覚えた名前 ＋ 人が承認した表 ＋ ルーラ表
        from dq3.knowledge import locations as LOC
        from dq3.knowledge import progress as PG

        # ⚠⚠ RX3-0183（2026-09-12）: 読み込んだ表を `self.catalog` に残して**使い回して**いた。
        #   ★窓は Council を 1 つ持ち続けるので、⚠ 開いたまま遊んだ間の地名・行った場所が入らなかった
        #   （★progress.json にカザーブが入っていなかった）。→ ★評価のたびに読み直す（⚠ 渡された表だけは使う）
        catalog = self.catalog if self.catalog is not None else LOC.LocationCatalog.load(
            knowledge_path=self.knowledge_path, rom_path=self.rom_path)
        self.last_catalog = catalog
        # ★勇者メモは「出る条件が成立したカードだけ」を見せる（⚠ 片づいただけでは出さない / RX3-0436）
        book = G.TopicBook.load(master=topics, rules=rules, path=self.state_path,
                                require_appear=True)

        facts, texts = self._facts()
        # ★起きたこと（手に入れた / 倒した / 行った）も Fact にする（RX3-0076）
        progress = self._progress(PG, catalog)
        progress_facts = progress.facts()
        # ★品は「一度でも手に入れた」で数える（⚠ items_ever だけだと拾ってすぐ手放した品が抜ける / RX3-0490）
        view.progress = {"items": len(progress.acquired_ever()), "defeated": len(progress.defeated),
                         "visited": len(progress.visited)}
        facts = facts + progress_facts
        # ★先に Fact の番号を付け替える（⚠ 当て直しで Topic の更新回数を進めない / RX3-0235）
        book.rename_facts(getattr(self, "legacy_fact_ids", None) or {})
        # ★★ 勇者メモでは Fact を**論理的に 1 つ**にする（RX3-0436）★★
        #   ⚠ 同じ名前を 4 人から聞くと、観測ごとに 4 つの Fact になり、
        #     詳細に「まほうのカギ heard」が 4 行並んでいた。
        #   ★観測（誰から / いつ）は `source_observation_ids` に残す。
        from dq3.knowledge import concepts as C

        facts, renames = C.logical_facts(facts)
        texts = {fact["fact_id"]: [texts[f] for f in fact["observation_fact_ids"] if texts.get(f)]
                 for fact in facts}
        # ★保存済みの状態も論理 Fact の番号へ（⚠ 付け替えないと当て直しで「更新」になる）
        book.rename_facts(renames)
        view.fact_count = len(facts)
        view.moved = book.apply_all(facts)
        if save:
            book.save()
            progress.save()
            # ★会話の記録から拾った地名を残す（⚠ 聞き込み履歴を初期化しても消えないように / RX3-0077）
            LOC.persist_learned(catalog.learned, self.knowledge_path)

        for fact in facts:
            kind, _, ident = (fact.get("subject") or "").partition(":")
            name = rom_names.name(kind, int(ident)) if kind in ("item", "monster", "spell") and ident.isdigit() else None
            if kind == "location":
                name = catalog.place(ident).name
            elif kind == "word":
                name = ident
            got_text = texts.get(fact["fact_id"], "")
            if isinstance(got_text, list):
                # ★論理 Fact: 同じ文は 1 回だけ（⚠ 全部の観測は `observations` に残る）
                got_text = "\n".join(dict.fromkeys(got_text))
            view.facts[fact["fact_id"]] = {
                "subject": fact.get("subject"), "predicate": fact.get("predicate"),
                "name": name, "observation": fact.get("source_observation_id"),
                "observations": list(fact.get("source_observation_ids") or []),
                "count": int(fact.get("count") or 1),
                "text": got_text,
            }

        # ★★ ⚠⚠ ここが Player Knowledge の濾し器（RX3-0117 / 2026-09-08）★★
        #
        #   ⚠ 2026-09-04 に「★存在は攻略のネタバレではない」として
        #     `unknown` の Topic を一覧の下へ出していました。
        #   → ⚠⚠ 依頼者の判断で**取り下げます**。`objective` も
        #     `completion_hint` も持つ札なので、★次の攻略先がそのまま読めました。
        #
        #   ★Guide Master / World Model は**そのまま**です（⚠ 正本は消さない）。
        known = known_topic(book)
        view.head = pick_head(book, catalog)
        view.recent = [card_of(t, s, master, catalog, known) for t, s in book.ordered(("active", "discovered"))]
        view.resolved = [card_of(t, s, master, catalog, known) for t, s in book.ordered(("resolved",))]
        #: ⚠⚠ **空**（★件数も出さない。⚠ 「N 件ある」だけでも先が読めます）
        view.unknown = []
        view.scenarios = self._scenarios(built, book, view, facts)

        # ★★ 行ってみる？（RX3-0113 / 2026-09-10）★★
        #
        #   ⚠⚠ **ここも同じ濾し器の考えです。** ROM は 20 件の地名を素で持っており、
        #     ★そのまま出すと終盤の地名まで渡します。→ `reachable` が濾します。
        #   ⚠ 材料が無くても画面は続けます（★落とさない）。
        view.reachable, view.visited_diff = self._reachable(book, master)
        return view

    @staticmethod
    def _scenarios(built, book, view: CouncilView, facts: list) -> list:
        """★見えているカードを scenario で束ねる（RX3-0434 / ⚠ 状態は保存しない）。

        ★各カードに `scenario_id` を添えます（⚠ 単独のカードは空文字）。
        """
        from dq3.knowledge import scenario_view as SV

        cards = {card["topic_id"]: card for card in view.recent + view.resolved}
        for topic_id, card in cards.items():
            card["scenario_id"] = built.scenario_of.get(topic_id, "")
            # ★片づいたカードだけに「分かったこと」の文を添える（RX3-0437）。
            #   ⚠ 対応中のカードには渡さない（★まだ知らないことを先に見せない）
            card["done_text"] = (built.done_of.get(topic_id, "")
                                 if card.get("status") == "resolved" else "")
        positions = {fact.get("fact_id"): i for i, fact in enumerate(facts)}
        return SV.build(built.scenarios, built.scenario_of, book, cards, positions)

    def _reachable(self, book, master) -> tuple:
        """★勇者が知っていて、まだ行っていない場所と、⚠ ゲームの記録との食い違い。"""
        from dq3.knowledge import reachable as RE

        try:
            location_book = self._location_book()
            if location_book is None:
                return [], {}
            rows = RE.collect(location_book, book, master, rom_path=self.rom_path)
            diff = RE.compare_visited(self._rura_bits(), location_book, rom_path=self.rom_path)
            return rows, diff
        except Exception:                                  # noqa: BLE001 - ★画面は落とさない
            return [], {}

    def _location_book(self):
        """★場所の名前の**唯一の入口**（RX3-0080）。⚠ 画面が持っていればそれを使う。"""
        got = getattr(self.vm, "location_book", None)
        if got is not None:
            return got
        import pathlib

        from dq3.knowledge.location_book import LocationBook
        from dq3 import paths

        base = (pathlib.Path(self.knowledge_path).parent if self.knowledge_path
                else paths.work("dq3-knowledge"))
        from dq3.knowledge.locations import NAMES_PATH

        return LocationBook.load(path=base / "location-book.json", names_path=NAMES_PATH)

    def _rura_bits(self):
        """★`state.json` の `rura`（⚠ Lua が載せていなければ None）。"""
        got = getattr(self.vm, "rura_bits", None)
        if callable(got):
            try:
                return got()
            except Exception:                              # noqa: BLE001
                return None
        return got


def main(argv=None) -> int:
    """★1 本通っているかを見る（⚠ 画面なし）。"""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="勇者会議 AI v1（画面なし）")
    parser.add_argument("--state", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    # ★勇者メモを正本にする（RX3-0454 / ⚠ 旧 Guide Master の経路は使わない）
    view = Council(state_path=args.state).evaluate(save=not args.dry_run)
    if not view.ok:
        print("⚠⚠ " + view.error, file=sys.stderr)
        return 1
    print("★勇者メモ %s / カード %d 件 / Fact %d 件" % (view.master_path, view.topic_count, view.fact_count))
    print("★解決: %s" % json.dumps(view.resolution_summary, ensure_ascii=False))
    for topic_id, fact_ids in view.moved.items():
        print("  ★動いた %s ← %s" % (topic_id, fact_ids))
    print("★Head: %s" % (json.dumps(view.head, ensure_ascii=False) if view.head else "（無し）"))
    for card in view.recent:
        print("  %-4s %-5s %-10s p%3d %s" % (card["badge"], card["topic_id"], card["status"], card["priority"], card["title"]))
    print("★resolved %d / unknown %d" % (len(view.resolved), len(view.unknown)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
