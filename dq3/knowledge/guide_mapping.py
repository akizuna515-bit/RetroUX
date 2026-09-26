"""Guide Master の「関連する名前」を、実行時に ROM の (kind, id) へ解く（RX3-0074 / 2026-09-04）。

★★ Git に置く正本へ、ROM 依存の id を手で書かせない ★★

```text
Guide Master（人が書いた名前 / related_item_names = とうぞくのかぎ）
        +
Runtime Name Dictionary（ユーザーの ROM から起こした名前 / rom_names）
        ↓ fold（かなを畳む / RX3-0070 と同じ）で**完全一致**
entity name → (kind, id)                 ★item:88
        ↓
弱い Rule（weight 40 / predicate なし）   ⚠ 「関係がある」だけ。★完了には使わない
```

## ⚠⚠ 守ること（指示書 §7〜§9）

```text
★完全一致（fold 後）だけ      ⚠ 部分一致・類似度は**使わない**（新しい判定を増やさない）
⚠ 解けない名前は解けないまま  ★`unresolved` に残す（黙って捨てない）
⚠ 同じ名前が 2 つの id を持つ  ★両方へ解く（⚠ 曖昧ではない。原作が同名で 2 体持つ）
⚠ 弱い Rule は 40             ★discovered / active までしか動かせない（100 が resolved）
★人が明示した Rule が先        ⚠ 同じ (topic, subject) に明示 Rule があれば作らない
```
"""
from __future__ import annotations

import dataclasses

from dq3.knowledge import rom_names
from dq3.knowledge.concepts import fold
from dq3.knowledge.guide_master import GuideMaster, Topic

#: ★Guide Master から生成する弱い Rule の重み（⚠ resolved の 100 には届かせない / §9）
WEAK_WEIGHT = 40

#: ★Guide Master の列 → ROM の kind
NAME_COLUMNS = (("related_item_names", "item"), ("related_boss_names", "monster"))
ID_COLUMNS = (("item_ids", "item"), ("monster_ids", "monster"), ("spell_ids", "spell"))


@dataclasses.dataclass(frozen=True)
class Resolved:
    kind: str
    entity_id: int
    written: str          #: ★Guide Master に人が書いた名前
    rom_name: str         #: ★ROM の綴り（⚠ 表示用。鍵にしない）

    @property
    def subject(self) -> str:
        return "%s:%d" % (self.kind, self.entity_id)


@dataclasses.dataclass
class Resolution:
    """★1 Topic ぶんの解決結果（⚠ 解けなかったものも残す / 報告用）。"""

    topic_id: str
    resolved: list[Resolved] = dataclasses.field(default_factory=list)
    unresolved: list[tuple[str, str]] = dataclasses.field(default_factory=list)   # (kind, written)
    multi: list[tuple[str, str, tuple[int, ...]]] = dataclasses.field(default_factory=list)


def name_index(rom_path=None) -> dict[tuple[str, str], list[tuple[int, str]]]:
    """★(kind, fold(名前)) → [(id, ROM の綴り)]。⚠ ROM が無ければ空。"""
    data = rom_names._load(rom_path)
    got: dict[tuple[str, str], list[tuple[int, str]]] = {}
    if data is None:
        return got
    for kind, table in (data.get("names") or {}).items():
        for key, name in table.items():
            got.setdefault((kind, fold(name)), []).append((int(key), name))
    return got


def resolve_topic(topic: Topic, index) -> Resolution:
    """★1 Topic の名前と id 列を (kind, id) へ。⚠ 完全一致だけ。"""
    got = Resolution(topic.topic_id)
    seen: set[str] = set()

    def keep(kind, entity_id, written, rom_name):
        row = Resolved(kind, entity_id, written, rom_name)
        if row.subject in seen:
            return
        seen.add(row.subject)
        got.resolved.append(row)

    for column, kind in NAME_COLUMNS:
        for written in getattr(topic, column):
            hits = index.get((kind, fold(written)), [])
            if not hits:
                got.unresolved.append((kind, written))
                continue
            if len(hits) > 1:
                # ⚠ 同じ綴りが 2 つ以上（★原作が同名で複数持つ / カンダタ・ゾーマ）。
                #   ★曖昧一致ではない（fold 後に**完全に同じ**）ので、全部へ解く。
                got.multi.append((kind, written, tuple(i for i, _ in hits)))
            for entity_id, rom_name in hits:
                keep(kind, entity_id, written, rom_name)
    for column, kind in ID_COLUMNS:
        for entity_id in getattr(topic, column):
            # ★人が id を直に書いたら、それも使う（⚠ 名前は ROM から引く）
            keep(kind, entity_id, "#%d" % entity_id,
                 rom_names.name(kind, entity_id) or "")
    return got


def resolve_all(master: GuideMaster, index=None, rom_path=None) -> dict[str, Resolution]:
    if index is None:
        index = name_index(rom_path)
    return {tid: resolve_topic(topic, index) for tid, topic in master.topics.items()}


def resolve_rules(rules, index=None, catalog=None, rom_path=None) -> tuple[list, list]:
    """★名前で書かれた Rule を id に解く（RX3-0076 / 2026-09-05）。

    ```text
    item / monster / spell   ROM の名前辞書（fold 後の完全一致）。⚠ 同名 2 id は Rule を 2 本に増やす
    location                 LocationCatalog（★実プレイで覚えた名前 / 人が APPROVED した表）
    ```
    戻り値: (解けた Rule の一覧, 解けなかった Rule の一覧)。⚠ 解けない Rule は当たらないだけ（★落とさない）。
    """
    if index is None:
        index = name_index(rom_path)
    got, unresolved = [], []
    for rule in rules:
        if not rule.needs_resolve:
            got.append(rule)
            continue
        if rule.entity_kind == "location":
            loc = catalog.resolve(rule.entity_name) if catalog is not None else None
            if loc is None:
                unresolved.append(rule)
            else:
                got.append(rule.resolved(None, location_id=loc))
            continue
        hits = index.get((rule.entity_kind, fold(rule.entity_name)), [])
        if not hits:
            unresolved.append(rule)
            continue
        for i, (entity_id, _rom_name) in enumerate(hits):
            row = rule.resolved(entity_id)
            if i:
                # ★同名 2 id（カンダタ / ゾーマ）: ⚠ どちらを倒しても同じ条件が成立するよう、
                #   同じ group 名の**別 Rule**にはしない → ANY なら片方で足りる。
                #   ALL の group では「同名のどれか」で 1 本ぶんとみなすため rule_id を揃えない
                row = dataclasses.replace(row, rule_id="%s#%d" % (rule.rule_id, entity_id))
            got.append(row)
    return got, unresolved


def derived_rules(master: GuideMaster, explicit_rules, resolutions=None, rom_path=None,
                  catalog=None) -> list:
    """★弱い Rule を作る（⚠ 明示 Rule と同じ (topic, subject) は作らない / §9）。

    ★2026-09-05: 関連する**場所**も弱い Rule にする（⚠ 名前が解けた場所だけ）。
    """
    from dq3.knowledge.guide import Rule

    if resolutions is None:
        resolutions = resolve_all(master, rom_path=rom_path)
    explicit = {(r.topic_id, r.subject()) for r in explicit_rules}
    got = []
    for topic_id, resolution in resolutions.items():
        for row in resolution.resolved:
            if (topic_id, row.subject) in explicit:
                continue                      # ★人が明示した Rule が先
            got.append(Rule(
                rule_id="GM-%s-%s-%d" % (topic_id, row.kind, row.entity_id),
                topic_id=topic_id, entity_kind=row.kind, entity_id=row.entity_id,
                predicate="",                 # ⚠ どの predicate でも「関係あり」
                weight=WEAK_WEIGHT, source="master",
                notes="Guide Master の関連（%s）" % row.written))
    if catalog is not None:
        for topic_id, topic in master.topics.items():
            for written in topic.related_location_names:
                loc = catalog.resolve(written)
                if loc is None or (topic_id, "location:%s" % loc) in explicit:
                    continue
                got.append(Rule(
                    rule_id="GM-%s-location-%s" % (topic_id, loc),
                    topic_id=topic_id, entity_kind="location", location_id=loc,
                    predicate="", weight=WEAK_WEIGHT, source="master",
                    notes="Guide Master の関連する場所（%s）" % written))
    return got


def all_rules(master: GuideMaster, explicit_rules, rom_path=None, catalog=None) -> tuple[list, dict]:
    """★明示 Rule（★名前は解いて）＋ 弱い Rule（⚠ 明示が先に並ぶ）と、解決の記録。

    ⚠ 解けなかった明示 Rule は `resolutions["_unresolved_rules"]` に残す（★黙って捨てない）。
    """
    index = name_index(rom_path)
    resolutions = resolve_all(master, index)
    explicit, unresolved = resolve_rules(explicit_rules, index, catalog)
    weak = derived_rules(master, explicit, resolutions, catalog=catalog)
    resolutions["_unresolved_rules"] = unresolved
    return list(explicit) + weak, resolutions


def summary(resolutions: dict) -> dict:
    """★報告用の数（指示書 §37-3）。"""
    rows = {tid: r for tid, r in resolutions.items() if isinstance(r, Resolution)}
    return {
        "resolved": sum(len(r.resolved) for r in rows.values()),
        "unresolved": [(tid, kind, written) for tid, r in rows.items()
                       for kind, written in r.unresolved],
        "multi": [(tid, kind, written, ids) for tid, r in rows.items()
                  for kind, written, ids in r.multi],
        "topics_with_entities": sum(1 for r in rows.values() if r.resolved),
        # ★名前で書いた明示 Rule のうち、まだ解けていないもの（⚠ 地名は挨拶を聞くまで解けない）
        "unresolved_rules": [(r.rule_id, r.topic_id, r.entity_kind, r.entity_name)
                             for r in resolutions.get("_unresolved_rules", [])],
    }
