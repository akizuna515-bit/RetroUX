"""場所の名前と id（Location Naming v1 / RX3-0076 / 2026-09-05）。

★★ DQ3 の ROM に地名の平文は無い（RX3-0013）。だから名前は**証拠のある所からだけ**取る ★★

```text
① 実プレイで覚えた名前   会話の挨拶「Xの むら／まち／しろに ようこそ」を聞いた map
                          → player-knowledge.json の location_names["L9"] = "レーベ"
② 人が承認した表         data/dq3/location-names.csv（review_status = APPROVED だけ）
                          ★ダンジョンはこれしか無い（⚠ 挨拶が無いので）
③ ROM                    ルーラ表（20 map / 一覧順）と area_directory（★id と種別の材料）
        ↓
LocationCatalog   location_id（L<map_id>）↔ 名前 / 行った / ルーラの索引
        ↓
Guide Master の related_location_names → location_id（fold 後の完全一致だけ）
```

## ⚠⚠ 守ること

```text
⚠ 勝手に名寄せしない     ★①か②の証拠がある名前だけ id に結ぶ
⚠ ROM から地名を引かない ★No-Spoiler（訪れて聞いた名前だけ）
⚠ DRAFT は結ばない        ★表に人が書いても APPROVED になるまで nav_target にしない
★挨拶の濁点の揺れ         「レーべ」（ひらがなの べ）も fold で同じ鍵になる（実測 / 2026-09-03）
```
"""
from __future__ import annotations

import csv
import dataclasses
import io
import json
import pathlib
import re

from dq3.knowledge.concepts import PLACE_TYPES, fold

from .. import ownership as _own
from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ★★ 地名の表（⚠ 人が 3 列を書く）★★
#
#   ★**user 側にあればそれを読みます**（案 A / `RX3-0472`）。
#     ⚠ `location_book.table_names()` と `item_info._names_path()` は
#       **ここを見ている**ので、★読み口はこの 1 行だけです。
#   ⚠⚠ `concepts.LOCATION_NAMES` が同じ表を**別に持っていました**。
#     ★そちらもこの resolver を通すようにしました（2026-10-01 / 「同じ判定を 2 か所」）。
NAMES_PATH = _own.lazy_resolve("data/dq3/location-names.csv")
KNOWLEDGE_PATH = paths.lazy_work("dq3-knowledge", "player-knowledge.json")

#: ★挨拶の形（⚠ 会話の記録は「＊「」を含む。★場所の型は concepts.PLACE_TYPES と同じ語）
#:
#: ⚠⚠ **ここの見本だけは架空にしません**（RX3-0433 / 2026-10-01）。
#:   ★挨拶の見本は「正規表現そのものを地名入りで書き出したもの」で、
#:   ⚠ 架空の文に替えると**どの形を拾うのかが分からなくなります**。
#:   ★地名は ROM のルーラ表にある語、残りは照合する助詞と語尾だけです
#:   （⚠ 物語・台詞としての内容は入っていません）。
#:
#: ⚠⚠ 2026-09-07（RX3-0100）: 城の挨拶を拾えていませんでした。
#:
#:   ```text
#:   ＊「アりアハンの おしろにようこそ。   ← ★実際の記録（2 人から / 2026-09-05）
#:   ⚠ ①「の」の**直後の空白**  ⚠ ② 丁寧の「**お**しろ」
#:   → ★どちらか片方を外しても拾えず、**両方**が効いていました（実測）
#:   ```
#: ★場所の型は `concepts.PLACE_TYPES` から作ります（⚠ 2 か所に書かない）。
#: ⚠ `PLACE_TYPES` に無いが、挨拶には出る語（★港町）。種別は付けません。
#:   ⚠⚠ 前の正規表現には在ったので、★落とさないように足しています。
EXTRA_GREETING_WORDS = ("みなと",)
_TYPE_WORDS = "|".join(tuple(PLACE_TYPES) + EXTRA_GREETING_WORDS)
GREETING = re.compile(
    r"([^＊「」\s]{1,8}?)の\s*お?("
    + _TYPE_WORDS
    + r")に\s*ようこそ")

#: ★挨拶の別の形（RX3-0188 / 2026-09-12 依頼者「ここはエルフの隠れ村よというが、場所が更新されない」）
#:
#:   ```text
#:   ＊「ようこそ ロマりアのおしろに！        ← ★語順が逆（ロマリア / 記録の文）
#:   ＊「ここは エルフのかくれむらよ。        ← ★「ここは X の（かくれ）TYPE よ」（記録の文）
#:   ```
#:   ⚠ 種別の語が無い「ここは カザーブ。」は拾いません（★「ここは だいじな…」を地名にしない）。
GREETING_WELCOME_FIRST = re.compile(
    r"ようこそ\s*([^＊「」\s、。！？]{1,8}?)の\s*お?(" + _TYPE_WORDS + r")に")
GREETING_HERE_IS = re.compile(
    r"ここは\s*([^＊「」\s、。！？]{1,8}?)の\s*(かくれ)?お?(" + _TYPE_WORDS + r")\s*(?:よ|だ|じゃ|です|。|！)")

APPROVED = "APPROVED"


def location_id_of(map_id) -> str:
    return "L%d" % int(map_id)


def sort_key(location_id) -> tuple:
    """★`L<数>` を**数の順**に並べる鍵（2026-09-27 依頼者 / RX3-0438）。

    ⚠ 文字列の順だと L1 → L10 → L100 → L11 … になり、地図を見ながら表を直すときに探せない。
    ★`L<数>` は数の順（L1 → L2 → … → L10 → … → L100）、⚠ それ以外（`world` など）は後ろに文字列の順。
    """
    text = str(location_id or "")
    if text[:1] == "L" and text[1:].isdigit():
        return (0, int(text[1:]), "")
    return (1, 0, text)


@dataclasses.dataclass(frozen=True)
class Place:
    location_id: str
    name: str | None = None
    source: str = ""            #: ★learned / approved / ""（名前なし）
    visited: bool = False
    rura_index: int | None = None
    kind: str = ""

    @property
    def map_id(self) -> int | None:
        try:
            return int(self.location_id[1:])
        except ValueError:
            return None


def greeting_place(text: str):
    """★挨拶の文から `(地名, 種別)` を取る（⚠ 無ければ None。★作文しない）。

    ⚠ 種別は `concepts.PLACE_TYPES` の語（★`しろ` → `castle`）。
    """
    # ⚠ 記録された本文は `RX3-0093` より前の綴りのことがある（★「アりアハン」）
    #   → ★画面の名前と**同じ関数**を通す（⚠ ずらすと突き合わせが割れる）
    from dq3.knowledge.name_text import to_display

    text = text or ""
    m = GREETING.search(text) or GREETING_WELCOME_FIRST.search(text)
    if m:
        return to_display(m.group(1)), PLACE_TYPES.get(m.group(2), "")
    m = GREETING_HERE_IS.search(text)
    if not m:
        return None
    kind = PLACE_TYPES.get(m.group(3), "")
    if m.group(2):
        # ★「エルフの かくれむら」は、それ全体が場所の名前（⚠ 「エルフ」だけでは村の名前にならない）
        return to_display("%sの%s%s" % (m.group(1), m.group(2), m.group(3))), kind
    return to_display(m.group(1)), kind


def greeting_name(text: str) -> str | None:
    """★挨拶の文から地名を取る（⚠ 無ければ None。★作文しない）。"""
    got = greeting_place(text)
    return got[0] if got else None


def read_names_table(path=None) -> dict[str, dict]:
    """★人が承認する表（⚠ 無ければ空）。location_id → {name, kind, review_status, evidence}。"""
    target = pathlib.Path(path) if path else NAMES_PATH
    got: dict[str, dict] = {}
    try:
        with io.open(target, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                loc = (row.get("location_id") or "").strip()
                if loc:
                    got[loc] = {k: (v or "").strip() for k, v in row.items() if k}
    except OSError:
        return {}
    return got


def read_learned(path=None) -> tuple[dict[str, str], set[str]]:
    """★実プレイで覚えた名前と、行った場所。"""
    target = pathlib.Path(path) if path else KNOWLEDGE_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, set()
    names = {str(k): str(v) for k, v in (raw.get("location_names") or {}).items() if v}
    visited = {str(v) for v in raw.get("visited_locations") or []}
    return names, visited


BOOK_PATH = paths.lazy_work("dq3-knowledge", "location-book.json")

#: ★場所の台帳（`location_book`）の名前のうち、勇者会議の名前の表へ渡してよいもの（⚠ 仮名は入れない）
BOOK_SOURCES = ("rom", "dialogue", "manual")


def read_book_names(path=None) -> tuple[dict[str, str], set[str]]:
    """★場所の台帳（location-book.json）の**確かな名前**と、その行った場所（RX3-0183）。

    ⚠⚠ 2026-09-12 依頼者「そもそもロマリア到着したのに更新されていない？」:
      勇者会議の名前の表はこの台帳を**読んでいなかった**。ロマリアの挨拶は語順が逆で拾えず、
      カザーブの「ここは カザーブ。」は挨拶でない → ★台帳は ROM の地名で両方を知っていたのに、会議は知らなかった。
    ⚠ 仮名（provisional）は入れない（★「アリアハン北西の場所」を話の決まりに当てない）。
    ★台帳の ROM の地名は**入った場所だけ**（RX3-0092）なので、ネタバレにはならない。
    """
    target = pathlib.Path(path) if path else BOOK_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, set()
    rows = raw.get("locations", raw) if isinstance(raw, dict) else {}
    names: dict[str, str] = {}
    visited: set[str] = set()
    for loc_id, row in (rows.items() if isinstance(rows, dict) else ()):
        if not isinstance(row, dict) or row.get("name_source") not in BOOK_SOURCES:
            continue
        name = row.get("display_name")
        if not name:
            continue
        names[str(loc_id)] = str(name)
        if row.get("visited"):
            visited.add(str(loc_id))
    return names, visited


CONVERSATIONS_PATH = paths.lazy_work("dq3-knowledge", "npc-conversations.json")


def read_conversation_names(path=None) -> dict[str, str]:
    """★聞いた会話の記録（map/npc → 文）から挨拶を拾う（⚠ 過去の記録にも効く）。

    ★2026-09-05: `location_names` を書く仕組みが無かった頃の記録にも
      「レーべのむらに ようこそ」（map 9）が残っていた。⚠ 同じ証拠なので使う。
    """
    target = pathlib.Path(path) if path else CONVERSATIONS_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    got: dict[str, str] = {}
    for key, rows in (raw or {}).items():
        if "/" not in key:
            continue
        map_id = key.split("/")[0]
        if not map_id.isdigit():
            continue
        for row in rows or []:
            learn_from_text(got, (row or {}).get("text") or "", int(map_id))
    return got


def place_from_records(map_id, path=None):
    """★記録済みの会話から、その map の `(地名, 種別)` を取る（RX3-0101）。

    ⚠⚠ `learn_from_text` は「既に覚えていれば触らない」ので、★一度
    `player-knowledge.json` に入ると**場所の台帳へは二度と渡りません**。
    → ★台帳を直すときは、こちらで記録から取り直します（⚠ 聞き直さなくてよい）。
    """
    if map_id is None:
        return None
    target = pathlib.Path(path) if path else CONVERSATIONS_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    head = "%d/" % int(map_id)
    for key, rows in (raw or {}).items():
        if not str(key).startswith(head):
            continue
        for row in rows or []:
            got = greeting_place((row or {}).get("text") or "")
            if got:
                return got
    return None


def persist_learned(names: dict, path=None) -> int:
    """★覚えた名前を player-knowledge.json に書き足す（⚠ 既にある名前は触らない）。

    ⚠⚠ 2026-09-05: 会話の記録（npc-conversations.json）から拾った名前は**記憶の中だけ**で、
      聞き込み履歴を初期化した途端に「レーべ」が消えた（★ハーネスで踏んだ / RX3-0077）。
      → ★拾った名前はここで残す。戻り値: 足した数。
    """
    if not names:
        return 0
    target = pathlib.Path(path) if path else KNOWLEDGE_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    have = dict(raw.get("location_names") or {})
    added = 0
    for loc, name in names.items():
        if name and not have.get(loc):
            have[loc] = name
            added += 1
    if not added:
        return 0
    raw["location_names"] = have
    raw.setdefault("visited_locations", [])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        return 0
    return added


def rura_points(rom_path=None) -> list[int]:
    """★ルーラ表（⚠ ROM が無ければ空）。"""
    try:
        from dq3rom import profile as P
        from dq3rom import rura

        # ⚠ 解決は `dq3/paths.py::rom()` の 1 本（RX3-0467）
        target = pathlib.Path(rom_path) if rom_path else paths.rom_or_legacy()
        return rura.read_points(P.load_and_identify(target))
    except Exception:                                      # noqa: BLE001
        return []


class LocationCatalog:
    """★場所の一覧（⚠ 名前は証拠のある所からだけ）。"""

    def __init__(self, learned=None, visited=None, table=None, points=None) -> None:
        self.learned: dict[str, str] = dict(learned or {})
        self.visited: set[str] = set(visited or ())
        self.table: dict[str, dict] = dict(table or {})
        self.points: list[int] = list(points or [])
        #: ★fold(名前) → location_id（⚠ 承認済み・覚えたものだけ）
        self._by_name: dict[str, str] = {}
        for loc, row in self.table.items():
            if row.get("review_status", "").upper() == APPROVED and row.get("name"):
                self._by_name[fold(row["name"])] = loc
        for loc, name in self.learned.items():           # ★実プレイの名前が最優先
            self._by_name[fold(name)] = loc

    @classmethod
    def load(cls, knowledge_path=None, names_path=None, rom_path=None, with_rom=True,
             conversations_path=None, book_path=None) -> "LocationCatalog":
        learned, visited = read_learned(knowledge_path)
        # ★過去の会話の記録からも拾う（⚠ player-knowledge に書いたものが先）
        merged = read_conversation_names(conversations_path)
        merged.update(learned)
        # ★場所の台帳の確かな名前も（RX3-0183）。⚠ 既に知っている名前は変えない（★足すだけ）
        #   ⚠ `knowledge_path` を渡されたら、台帳も**同じ置き場**から読む（★検査が本物の台帳を読まない）
        if book_path is None and knowledge_path is not None:
            book_path = pathlib.Path(knowledge_path).parent / BOOK_PATH.name
        book_names, book_visited = read_book_names(book_path)
        for loc_id, name in book_names.items():
            merged.setdefault(loc_id, name)
        return cls(merged, visited | book_visited, read_names_table(names_path),
                   rura_points(rom_path) if with_rom else [])

    def place(self, location_id: str) -> Place:
        row = self.table.get(location_id, {})
        name, source = None, ""
        if location_id in self.learned:
            name, source = self.learned[location_id], "learned"
        elif row.get("review_status", "").upper() == APPROVED and row.get("name"):
            name, source = row["name"], "approved"
        map_id = int(location_id[1:]) if location_id[1:].isdigit() else None
        rura = self.points.index(map_id) if map_id in self.points else None
        return Place(location_id, name, source, location_id in self.visited, rura, row.get("kind", ""))

    def resolve(self, name: str) -> str | None:
        """★Guide Master の地名 → location_id（⚠ fold 後の完全一致だけ）。"""
        return self._by_name.get(fold(name))

    def resolve_all(self, names) -> list[tuple[str, str | None]]:
        return [(n, self.resolve(n)) for n in names]

    def known(self) -> list[Place]:
        ids = set(self.learned) | self.visited | {
            loc for loc, row in self.table.items() if row.get("name")}
        return [self.place(loc) for loc in sorted(ids, key=lambda s: (len(s), s))]


def learn_from_text(names: dict, text: str, map_id) -> str | None:
    """★挨拶を聞いたら、その map の名前として覚える（⚠ 既に覚えていれば触らない）。

    戻り値: ★新しく覚えた名前。⚠ 無ければ None。
    """
    if map_id is None:
        return None
    got = greeting_name(text)
    if not got:
        return None
    loc = location_id_of(map_id)
    if names.get(loc):
        return None
    names[loc] = got
    return got


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="場所の名前と id（証拠のあるものだけ）")
    parser.add_argument("--no-rom", action="store_true")
    args = parser.parse_args(argv)
    cat = LocationCatalog.load(with_rom=not args.no_rom)
    print("★覚えた名前 %d / 行った %d / 表 %d 行（APPROVED %d）/ ルーラ表 %d"
          % (len(cat.learned), len(cat.visited), len(cat.table),
             sum(1 for r in cat.table.values() if r.get("review_status", "").upper() == APPROVED),
             len(cat.points)))
    for p in cat.known():
        print("  %-5s %-10s %-8s %s%s" % (p.location_id, p.name or "（名前なし）", p.source,
                                         "行った" if p.visited else "", " ルーラ%d" % p.rura_index if p.rura_index is not None else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
