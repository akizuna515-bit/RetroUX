"""勇者会議のカード（Topic）の型（RX3-0074 / 2026-09-04 → ★2026-10-03 型だけに / RX3-0432）。

⚠⚠ **旧 Guide Master（`input/` の攻略 Topic の CSV）を読む部分は消しました。**

  ★勇者会議の正本は `data/dq3/hero-memo.yaml` です（`hero_memo.py`）。
  ★ここに残るのは、勇者メモが組み立てて下流（`card_of` / `reachable`）へ渡す**型**だけです。

  ```text
  Topic        ★カード 1 枚（勇者メモの 1 件から作る / `hero_memo.Compiled.topics`）
  GuideMaster  ★カードの束（`hero_memo.Compiled.as_master()`）
  ```

  ⚠ 名前は歴史的なものです（★中身はもう攻略チャートではありません）。
  ⚠ 経緯: RX3-0455（2026-09-28 / 旧経路の退役）→ RX3-0432（2026-10-03 / 読む口と旧 2 表を削除）。
"""
from __future__ import annotations

import dataclasses
import pathlib


@dataclasses.dataclass(frozen=True)
class Topic:
    """★人が編集した Topic（⚠ 実行時に書き換えない）。"""

    topic_id: str
    title: str = ""
    category: str = ""
    priority: int = 0
    objective: str = ""
    completion_hint: str = ""
    parent_topic_id: str = ""
    prerequisite_topic_ids: tuple[str, ...] = ()
    next_topic_ids: tuple[str, ...] = ()
    ui_head_hint: str = ""
    notes: str = ""
    # --- ★2026-09-04 の正本で増えた列 ------------------------------------
    phase: int | None = None
    sequence: int | None = None
    topic_type: str = ""
    requiredness: str = ""
    related_location_names: tuple[str, ...] = ()
    related_item_names: tuple[str, ...] = ()
    related_boss_names: tuple[str, ...] = ()
    location_id: str = ""
    item_ids: tuple[int, ...] = ()
    monster_ids: tuple[int, ...] = ()
    spell_ids: tuple[int, ...] = ()
    review_status: str = ""
    source_url: str = ""
    #: ★知らない列（⚠ 消さずに素通し / 指示書 §3）
    extra: tuple[tuple[str, str], ...] = ()

    @property
    def head_message(self) -> str:
        """★画面のいちばん上に出す文（⚠ 作文しない / 指示書 §15）。"""
        return self.ui_head_hint or self.objective or self.title


@dataclasses.dataclass
class GuideMaster:
    """★正規化した runtime モデル（⚠ 読み取り専用のつもりで使う）。"""

    topics: dict[str, Topic]
    path: pathlib.Path | None = None
    columns: tuple[str, ...] = ()
    problems: list[str] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def children(self, topic_id: str) -> list[Topic]:
        """★子 Topic（⚠ sequence 順 / 指示書 §14）。"""
        got = [t for t in self.topics.values() if t.parent_topic_id == topic_id]
        got.sort(key=lambda t: (t.sequence is None, t.sequence or 0, t.topic_id))
        return got

    def parent(self, topic_id: str) -> Topic | None:
        topic = self.topics.get(topic_id)
        if topic is None or not topic.parent_topic_id:
            return None
        return self.topics.get(topic.parent_topic_id)

    def stats(self) -> dict:
        """★報告用（指示書 §31）。"""
        by_category: dict[str, int] = {}
        for t in self.topics.values():
            by_category[t.category] = by_category.get(t.category, 0) + 1
        priorities = [t.priority for t in self.topics.values()]
        return {
            "count": len(self.topics),
            "by_category": dict(sorted(by_category.items())),
            "with_parent": sum(1 for t in self.topics.values() if t.parent_topic_id),
            "priority_min": min(priorities) if priorities else None,
            "priority_max": max(priorities) if priorities else None,
            "phases": sorted({t.phase for t in self.topics.values() if t.phase is not None}),
            "columns": list(self.columns),
        }
