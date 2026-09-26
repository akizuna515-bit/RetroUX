"""Guide Master（人が精査した攻略 Topic の正本）を読む・検める（RX3-0074 / 2026-09-04）。

★★ ここは**人が編集した CSV** を、壊さず・黙らず読むところ ★★

```text
input/dq3_guide_topic_master.csv        ★正式（⚠ 人が置く。コードは書かない）
input/dq3_guide_topic_master_draft.csv  ★正式が無いときの代わり（★同じ形）
        ↓ ここ（読む・検める・正規化する）
GuideMaster（topics / children / stats）   ＝ runtime の正規化モデル
        ↓
Topic State（work/ / ⚠ このプレイの進み具合）  ★別ファイル（`guide.py`）
```

## ⚠⚠ 守ること

```text
⚠ input/ は読むだけ           ★コードから 1 バイトも書かない
⚠ 列を勝手に消さない          ★知らない列は**そのまま素通し**（`extra`）
⚠⚠ 壊れたら黙って動かさない   ★重複 id / 無い親 / 無い前提 / 変な priority は**止める**
★人が Excel で行を足しても    ⚠ コードを直さずに読める（列名で読む）
```

## ★列（⚠ 2026-09-04 の正本 25 列。★足りない列は空で読む）

```text
必須   topic_id / title / priority / category
構造   parent_topic_id / prerequisite_topic_ids / next_topic_ids（★区切りは | か ;）
並び   phase / sequence / topic_type / requiredness
文     objective / completion_hint / ui_head_hint / notes
関連   related_location_names / related_item_names / related_boss_names
       （⚠ 名前で書く。★ROM の id へは実行時に解く / `guide_mapping.py`）
id     location_id / item_ids / monster_ids / spell_ids（⚠ 人が入れたら使う。空でよい）
管理   rom_link_status / review_status / source_url
```
"""
from __future__ import annotations

import csv
import dataclasses
import io
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ★正式な置き場（⚠ 人が置く）。★無ければ `_draft` を読む
OFFICIAL_PATH = ROOT / "input" / "dq3_guide_topic_master.csv"
DRAFT_PATH = ROOT / "input" / "dq3_guide_topic_master_draft.csv"
CANDIDATE_PATHS = (OFFICIAL_PATH, DRAFT_PATH)

#: ★無いと読めない列（⚠ これ以外は空で読む）
REQUIRED_COLUMNS = ("topic_id", "title", "priority", "category")

#: ★分類（⚠ Head の優先順に使う / 指示書 §13）
CATEGORIES = ("main", "sub", "exploration", "utility")

#: ★priority の範囲（⚠ 人の打ち間違いを止める）
PRIORITY_MIN, PRIORITY_MAX = 0, 100


class GuideMasterError(ValueError):
    """⚠⚠ 正本が壊れている（★黙って動かさない / 指示書 §28）。"""

    def __init__(self, problems: list[str], path=None) -> None:
        self.problems = list(problems)
        self.path = path
        super().__init__("Guide Master に問題が %d 件:\n  " % len(problems)
                         + "\n  ".join(problems))


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


def split_ids(text) -> tuple[str, ...]:
    """★`|` か `;` 区切り（⚠ 正本は `|`、PoC は `;`。★両方読む）。"""
    raw = (text or "").replace("；", ";").replace("|", ";")
    return tuple(p.strip() for p in raw.split(";") if p.strip())


def _int(text, default=None):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return default


def _ints(text) -> tuple[int, ...]:
    got = []
    for part in split_ids(text):
        value = _int(part)
        if value is not None:
            got.append(value)
    return tuple(got)


KNOWN_COLUMNS = frozenset((
    "topic_id", "title", "category", "priority", "objective", "completion_hint",
    "parent_topic_id", "prerequisite_topic_ids", "next_topic_ids", "ui_head_hint",
    "notes", "phase", "sequence", "topic_type", "requiredness",
    "related_location_names", "related_item_names", "related_boss_names",
    "location_id", "item_ids", "monster_ids", "spell_ids", "review_status",
    "source_url", "rom_link_status",
))


def topic_from_row(row: dict) -> Topic:
    """★1 行 → Topic。⚠ 知らない列は `extra` へ（★消さない）。"""
    get = lambda key: (row.get(key) or "").strip()      # noqa: E731
    extra = tuple(sorted((k, (v or "").strip()) for k, v in row.items()
                         if k and k not in KNOWN_COLUMNS))
    return Topic(
        topic_id=get("topic_id"),
        title=get("title"),
        category=get("category"),
        priority=_int(row.get("priority"), 0),
        objective=get("objective"),
        completion_hint=get("completion_hint"),
        parent_topic_id=get("parent_topic_id"),
        prerequisite_topic_ids=split_ids(row.get("prerequisite_topic_ids")),
        next_topic_ids=split_ids(row.get("next_topic_ids")),
        ui_head_hint=get("ui_head_hint"),
        notes=get("notes"),
        phase=_int(row.get("phase")),
        sequence=_int(row.get("sequence")),
        topic_type=get("topic_type"),
        requiredness=get("requiredness"),
        related_location_names=split_ids(row.get("related_location_names")),
        related_item_names=split_ids(row.get("related_item_names")),
        related_boss_names=split_ids(row.get("related_boss_names")),
        location_id=get("location_id"),
        item_ids=_ints(row.get("item_ids")),
        monster_ids=_ints(row.get("monster_ids")),
        spell_ids=_ints(row.get("spell_ids")),
        review_status=get("review_status"),
        source_url=get("source_url"),
        extra=extra)


# --- ★検める --------------------------------------------------------------------

def validate(columns, rows: list[dict]) -> list[str]:
    """★人の編集で壊れやすい所を見る（⚠ 指示書 §28）。★問題を全部並べて返す。"""
    problems: list[str] = []
    have = set(columns or [])
    missing = [c for c in REQUIRED_COLUMNS if c not in have]
    if missing:
        problems.append("列が足りない: %s" % ", ".join(missing))
        return problems                       # ⚠ 列が無いと下は見られない

    ids: dict[str, int] = {}
    for line, row in enumerate(rows, start=2):        # ★1 行目は見出し
        topic_id = (row.get("topic_id") or "").strip()
        if not topic_id:
            problems.append("%d 行目: topic_id が空" % line)
            continue
        if topic_id in ids:
            problems.append("topic_id が重複: %s（%d 行目と %d 行目）"
                            % (topic_id, ids[topic_id], line))
        ids.setdefault(topic_id, line)

    for line, row in enumerate(rows, start=2):
        topic_id = (row.get("topic_id") or "").strip()
        if not topic_id:
            continue
        where = "%s（%d 行目）" % (topic_id, line)
        priority = _int(row.get("priority"))
        if priority is None or not PRIORITY_MIN <= priority <= PRIORITY_MAX:
            problems.append("%s: priority が %d〜%d の整数でない: %r"
                            % (where, PRIORITY_MIN, PRIORITY_MAX, row.get("priority")))
        category = (row.get("category") or "").strip()
        if category not in CATEGORIES:
            problems.append("%s: category が未知: %r（★%s）"
                            % (where, category, " / ".join(CATEGORIES)))
        if (row.get("sequence") or "").strip() and _int(row.get("sequence")) is None:
            problems.append("%s: sequence が整数でない: %r" % (where, row.get("sequence")))
        parent = (row.get("parent_topic_id") or "").strip()
        if parent:
            if parent == topic_id:
                problems.append("%s: 親が自分自身" % where)
            elif parent not in ids:
                problems.append("%s: 親が無い: %s" % (where, parent))
        for label, key in (("前提", "prerequisite_topic_ids"), ("次", "next_topic_ids")):
            for ref in split_ids(row.get(key)):
                if ref not in ids:
                    problems.append("%s: %sの Topic が無い: %s" % (where, label, ref))
    return problems


# --- ★読む ----------------------------------------------------------------------

def resolve_path(path=None) -> pathlib.Path | None:
    """★読む CSV を決める（⚠ 正式 → draft の順。★無ければ None）。"""
    if path is not None:
        target = pathlib.Path(path)
        return target if target.exists() else None
    for candidate in CANDIDATE_PATHS:
        if candidate.exists():
            return candidate
    return None


def read_rows(path) -> tuple[list[str], list[dict]]:
    """★CSV を素のまま読む（⚠ BOM 付き UTF-8 / CRLF を想定。★どちらでも読める）。"""
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader]
        return list(reader.fieldnames or []), rows


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


def load(path=None, strict: bool = True) -> GuideMaster:
    """★読んで検める。

    ⚠⚠ `strict=True`（既定）では問題があれば **`GuideMasterError`** で止めます
      （★黙って壊れた状態で動かさない / 指示書 §28）。
    ★`strict=False` は「問題を並べて見たい」とき用（⚠ `problems` に残す）。
    """
    target = resolve_path(path)
    if target is None:
        problems = ["Guide Master がありません: %s"
                    % " / ".join(str(p) for p in CANDIDATE_PATHS)]
        if strict:
            raise GuideMasterError(problems, path)
        return GuideMaster({}, None, (), problems)
    columns, rows = read_rows(target)
    problems = validate(columns, rows)
    if problems and strict:
        raise GuideMasterError(problems, target)
    topics: dict[str, Topic] = {}
    for row in rows:
        topic = topic_from_row(row)
        if topic.topic_id and topic.topic_id not in topics:
            topics[topic.topic_id] = topic
    return GuideMaster(topics, target, tuple(columns), problems)


def main(argv=None) -> int:
    """★読めるか・壊れていないかを見る（⚠ 書かない）。"""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Guide Master を読んで検める")
    parser.add_argument("--path", default=None)
    args = parser.parse_args(argv)
    master = load(args.path, strict=False)
    if master.problems:
        print("⚠⚠ Guide Master に問題 %d 件（%s）" % (len(master.problems), master.path),
              file=sys.stderr)
        for p in master.problems:
            print("  " + p, file=sys.stderr)
        return 1
    print("★Guide Master %s" % master.path)
    print(json.dumps(master.stats(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
