"""Location Master — 人が編集する「場所」の正本（RX3-0080 / 2026-09-05）。

★★ ゲームの `map_id` と、プレイヤーが思う「場所」を**分ける** ★★

```text
map_id       ROM / runtime の単位（★技術）。★アリアハン城は 1F / 2F / B1 で別の map
location_id  プレイヤーが思う単位（★1 つの場所に複数の map が属してよい）
             ⚠ 既存の `L<map_id>` と**同じ名前空間**にする（★visit Fact / Guide Rule がこれを使う）
```

```text
input/dq3_location_master.csv     ★人が編集する正本（⚠ コードは書かない）
      ↓ ここ（読む・検める）
LocationMaster
      ↓
work/dq3-knowledge/location-book.json   ⚠ 実行時に分かったこと（★候補。Git の外）
```

## ⚠⚠ 守ること

```text
⚠ input/ は読むだけ            ★自動で見つけたものは work/ 側に置く（指示書 §18）
⚠⚠ 壊れたら黙って動かさない     ★map_id 重複 / 不正 source / 列不足で止める
⚠ 推測で種別を決めない          ★`location_type` は人が入れる（下の実測を見よ）
★人が行を足しても直さない        ⚠ 列名で読む
```

## ★★ 実測: **tileset では種別を判定できません**（2026-09-05）

```text
tileset 5   レーベ（村）と アリアハン城（城）の**両方**
→ ⚠ 「tileset から town / castle / cave を決める」は成り立たない
→ ★`location_type` が空なら `unknown` のまま。仮名では「場所」と呼ぶ（指示書 §11）
```
"""
from __future__ import annotations

import csv
import dataclasses
import io
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ★正式な置き場（⚠ 人が置く）。★無ければ `_draft` を読む（Guide Master と同じ作法）
OFFICIAL_PATH = ROOT / "input" / "dq3_location_master.csv"
DRAFT_PATH = ROOT / "input" / "dq3_location_master_draft.csv"
CANDIDATE_PATHS = (OFFICIAL_PATH, DRAFT_PATH)

#: ★無いと読めない列
REQUIRED_COLUMNS = ("map_id", "location_id")

#: ★名前の出どころ（指示書 §5）
SOURCES = ("rom", "dialogue", "manual", "provisional", "")

#: ★場所の種別（指示書 §5）。⚠ 空 = `unknown`（★推測しない）
TYPES = ("town", "castle", "village", "cave", "tower", "shrine",
         "dungeon", "field", "building", "unknown", "")

#: ★確からしさ（⚠ 既存の言い方に合わせる）
CONFIDENCES = ("CONFIRMED", "OBSERVED", "HYPOTHESIS", "INFERRED", "UNKNOWN", "")

#: ★種別 → 仮名で呼ぶ言葉（⚠ 分からなければ「場所」/ 指示書 §11）
TYPE_WORD = {
    "town": "街", "castle": "城", "village": "村", "cave": "洞窟",
    "tower": "塔", "shrine": "祠", "dungeon": "迷宮", "building": "建物",
    "field": "場所", "unknown": "場所", "": "場所",
}

#: ★「拠点」とみなす種別（指示書 §8）
BASE_TYPES = ("town", "castle", "village")


class LocationMasterError(ValueError):
    """⚠⚠ 正本が壊れている（★黙って動かさない）。"""

    def __init__(self, problems: list[str], path=None) -> None:
        self.problems = list(problems)
        self.path = path
        super().__init__("Location Master に問題が %d 件:\n  " % len(problems)
                         + "\n  ".join(problems))


@dataclasses.dataclass(frozen=True)
class Row:
    """★1 行 = 1 つの map（⚠ 同じ location_id を複数の行が持ってよい）。"""

    map_id: int
    location_id: str
    display_name: str = ""
    suffix: str = ""
    name_source: str = ""
    confidence: str = ""
    parent_location_id: str = ""
    location_type: str = ""
    notes: str = ""

    @property
    def named(self) -> bool:
        """★人／ROM／会話で名前が決まっているか（⚠ 仮名は含めない）。"""
        return bool(self.display_name) and self.name_source in ("rom", "dialogue", "manual")


def _int(text, default=None):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return default


def resolve_path(path=None) -> pathlib.Path | None:
    if path is not None:
        target = pathlib.Path(path)
        return target if target.exists() else None
    for candidate in CANDIDATE_PATHS:
        if candidate.exists():
            return candidate
    return None


def read_rows(path) -> tuple[list[str], list[dict]]:
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def validate(columns, rows: list[dict]) -> list[str]:
    """★人の編集で壊れやすい所を見る（⚠ 問題は全部並べて返す）。"""
    problems: list[str] = []
    have = set(columns or [])
    missing = [c for c in REQUIRED_COLUMNS if c not in have]
    if missing:
        problems.append("列が足りない: %s" % ", ".join(missing))
        return problems

    seen: dict[int, int] = {}
    ids: set[str] = set()
    for line, row in enumerate(rows, start=2):
        where = "%d 行目" % line
        map_id = _int(row.get("map_id"))
        if map_id is None:
            problems.append("%s: map_id が整数でない: %r" % (where, row.get("map_id")))
            continue
        if map_id in seen:
            problems.append("map_id が重複: %d（%d 行目と %s）" % (map_id, seen[map_id], where))
        seen.setdefault(map_id, line)
        loc = (row.get("location_id") or "").strip()
        if not loc:
            problems.append("%s: location_id が空" % where)
            continue
        if any(ch.isspace() for ch in loc):
            problems.append("%s: location_id に空白がある: %r" % (where, loc))
        ids.add(loc)
        source = (row.get("name_source") or "").strip()
        if source not in SOURCES:
            problems.append("%s: name_source が未知: %r（★%s）"
                            % (where, source, " / ".join(x for x in SOURCES if x)))
        kind = (row.get("location_type") or "").strip()
        if kind not in TYPES:
            problems.append("%s: location_type が未知: %r" % (where, kind))
        conf = (row.get("confidence") or "").strip()
        if conf not in CONFIDENCES:
            problems.append("%s: confidence が未知: %r" % (where, conf))
        if source and source != "provisional" and not (row.get("display_name") or "").strip():
            problems.append("%s: name_source=%s なのに display_name が空" % (where, source))

    for line, row in enumerate(rows, start=2):
        parent = (row.get("parent_location_id") or "").strip()
        loc = (row.get("location_id") or "").strip()
        if parent and parent not in ids:
            problems.append("%d 行目: 親の location_id が無い: %s" % (line, parent))
        if parent and parent == loc:
            problems.append("%d 行目: 親が自分自身" % line)
    return problems


@dataclasses.dataclass
class LocationMaster:
    """★正規化した runtime モデル（⚠ 読み取り専用のつもりで使う）。"""

    by_map: dict[int, Row] = dataclasses.field(default_factory=dict)
    path: pathlib.Path | None = None
    columns: tuple[str, ...] = ()
    problems: list[str] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def maps_of(self, location_id: str) -> list[int]:
        """★その場所に属する map（⚠ 若い順）。"""
        return sorted(m for m, r in self.by_map.items() if r.location_id == location_id)

    def location_ids(self) -> list[str]:
        return sorted({r.location_id for r in self.by_map.values()})

    def stats(self) -> dict:
        rows = list(self.by_map.values())
        groups = {}
        for r in rows:
            groups.setdefault(r.location_id, []).append(r.map_id)
        multi = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
        kinds: dict[str, int] = {}
        for r in rows:
            kinds[r.location_type or "unknown"] = kinds.get(r.location_type or "unknown", 0) + 1
        return {"rows": len(rows), "locations": len(groups),
                "multi_map": multi, "named": sum(1 for r in rows if r.named),
                "by_type": dict(sorted(kinds.items())),
                "columns": list(self.columns)}


def load(path=None, strict: bool = True) -> LocationMaster:
    """★読んで検める。⚠ `strict` なら壊れているとき `LocationMasterError`。"""
    target = resolve_path(path)
    if target is None:
        problems = ["Location Master がありません: %s"
                    % " / ".join(str(p) for p in CANDIDATE_PATHS)]
        if strict:
            raise LocationMasterError(problems, path)
        return LocationMaster({}, None, (), problems)
    columns, rows = read_rows(target)
    problems = validate(columns, rows)
    if problems and strict:
        raise LocationMasterError(problems, target)
    by_map: dict[int, Row] = {}
    for row in rows:
        map_id = _int(row.get("map_id"))
        loc = (row.get("location_id") or "").strip()
        if map_id is None or not loc or map_id in by_map:
            continue
        get = lambda k: (row.get(k) or "").strip()          # noqa: E731
        by_map[map_id] = Row(
            map_id=map_id, location_id=loc, display_name=get("display_name"),
            suffix=get("suffix"), name_source=get("name_source"),
            confidence=get("confidence"), parent_location_id=get("parent_location_id"),
            location_type=get("location_type"), notes=get("notes"))
    return LocationMaster(by_map, target, tuple(columns), problems)


def main(argv=None) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Location Master を読んで検める")
    parser.add_argument("--path", default=None)
    args = parser.parse_args(argv)
    master = load(args.path, strict=False)
    if master.problems:
        print("⚠⚠ Location Master に問題 %d 件（%s）" % (len(master.problems), master.path),
              file=sys.stderr)
        for p in master.problems:
            print("  " + p, file=sys.stderr)
        return 1
    print("★Location Master %s" % master.path)
    print(json.dumps(master.stats(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
