"""場所の名前を取る**唯一の入口**（RX3-0080 / 2026-09-05）。

★★ 地名の判定を、機能ごとに書かない（指示書 §20）★★

```text
Location Master（人が編集 / input/）      ★確定した名前・種別・どの map が同じ場所か
      +
実行時に分かったこと（work/ / Git の外）   ★会話で覚えた名前 / 仮名 / 行った記録 / 世界の座標
      ↓ ここ
get_location(map_id) / get_location_name(map_id, detailed=)
```

## ★名前の決め方（⚠ 上から順に）

```text
1 Master の display_name（name_source = rom / dialogue / manual）  ★人と ROM が決めたもの
2 実行時に会話で覚えた名前（★「Xの むらに ようこそ」）
3 実行時に付けた仮名（★1 度付けたら変えない）
4 まだ無ければ、その場で仮名を作って**残す**
```

## ⚠⚠ 仮名の作り方（指示書 §9〜§11）

```text
<直近の既知拠点><方角>の<種別>     例: アリアハン北西の洞窟
方角   世界地図の座標差から 8 方向（⚠ 距離は出さない）
種別   ⚠⚠ **推測しない**。★Master に無ければ「場所」
       （実測: tileset では村と城を見分けられない / location_master.py 参照）
拠点   ★名前が確定していて、実際に訪れた場所のうち直近のもの
```

## ⚠ 発見は **location_id** で数える（指示書 §14）

```text
★1F → 2F → B1 と歩いても、location_id が同じなら「新しい場所」ではない
⚠ map_id で数えると、階を移るたびに「見つけた」と言ってしまう
```

## ⚠ No-Spoiler（指示書 §19）

```text
⚠⚠ まだ知らない正式名を先回りで出さない
★出すのは「人が Master に書いた名前」「会話で聞いた名前」「自分で付けた仮名」だけ
⚠ ROM から地名を引いてくることはしない（★DQ3 の ROM に地名の平文は無い / RX3-0013）
```
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib

from dq3.knowledge import location_master as LM

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ⚠ このプレイで分かったこと（★Git の外 / playdata の作法）
BOOK_PATH = paths.lazy_work("dq3-knowledge", "location-book.json")

#: ★8 方向（⚠ 距離は出さない / 指示書 §10）
DIRECTIONS = ("北", "北東", "東", "南東", "南", "南西", "西", "北西")

#: ★世界地図の種別（⚠ `seen_map` と同じ値 / RX3-0315）
#:
#:   ⚠⚠ 2 つの世界は**別の地図**です（★升の意味も広さも違う）。
#:     上の世界      `world_main`     256 x 256
#:     アレフガルド  `world_alefgard` 158 x 138
WORLD_KIND = 0
ALEFGARD_KIND = 2
WORLD_KINDS = (WORLD_KIND, ALEFGARD_KIND)

#: ★仮名の出どころ
PROVISIONAL = "provisional"

#: ★親の中にある小さい場所（⚠ 種別が分からないとき / RX3-0122）
INNER_WORD = "小部屋"

#: ★近くの拠点しか言えないとき（RX3-0122）
NEARBY_WORD = "近辺"

#: ⚠ 何も言えないとき（★「知らない場所」より、⚠ **確かめていない**と分かる言い方）
UNSURE_HEAD = "未確認の"

#: ★名前が確かだと言える出どころ（⚠ 仮名は入れない）
#: ★`data/dq3/location-names.csv` の `name`（人が表に書いた名前 / RX3-0439）
TABLE = "table"
KNOWN_SOURCES = ("rom", "dialogue", "manual", TABLE)

#: ★仮名の付け方（⚠ `Location.name_rule` に残す / RX3-0122）
PARENT_RULE = "parent"
DIRECTION_RULE = "direction"
NEARBY_RULE = "nearby"
UNSURE_RULE = "unsure"
FLOOR_RULE = "floor"

#: ★★ 塔・洞窟の別の階（RX3-0196 / 2026-09-12 依頼者「save5 ここはナジミの塔２Fなんだが、うまく特定できないか？
#:   ※ナジミの塔から階段で上がってきた」→ 案 A）。★親が塔・洞窟なら「ナジミの塔 #2」。
#:   ⚠ #n は**通し番号**で、何階かは言わない（★上り下りは今の材料では分からない）
FLOOR_MARK = " #"
#: ★「塔・洞窟らしい」種別（location_master の TYPES から）
DUNGEON_TYPES = ("cave", "tower", "shrine", "dungeon")
#: ★種別が空のとき、名前の終わりで見る（⚠ 人が付けた名前・挨拶の名前 / ★DQ3 の ROM から種別は取れない）
DUNGEON_WORDS = ("塔", "とう", "洞窟", "どうくつ", "祠", "ほこら", "迷宮", "ダンジョン")
#: ★名前の終わりの階の印（「２F」「2」「#3」「B1」）として外す字
FLOOR_TAIL_CHARS = "0123456789０１２３４５６７８９FＦ階BＢ#＃ "

#: ★★ 出口の升で直してよい近さ（RX3-0275 / 依頼者「◯があるが、何もない」）
#:   ★入ったときの升（⚠ 0.5 秒おきの読みで町の 1〜2 歩手前）を、出た直後の升（★その場所の升）で直す。
#:   ⚠ これより遠い = ルーラ・キメラのつばさで出た（★別の町の升で上書きしない）。
EXIT_NEAR = 3


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def default_location_id(map_id) -> str:
    """★既定は 1 map = 1 場所（⚠ 既存の `L<map_id>` と同じ名前空間）。

    ⚠⚠ ここを変えると、既に貯まっている `visit` Fact と Guide Rule が当たらなくなります
      （★`location:L9` は「レーベへ行った」として使われている / RX3-0076）。
    """
    return "L%d" % int(map_id)


def _rom_place_name(map_id) -> str | None:
    """★ルーラの行き先なら、その名前（RX3-0092）。⚠ ROM が無ければ None。

    ⚠⚠ **入った場所にしか呼びません**（★一覧を先に見せるとネタバレになる）。
    ⚠ 20 件だけです。★城・洞窟・小さな村は入っていません。
    """
    try:
        from dq3.knowledge import rom_names as RN

        return RN.place_for_map(map_id)
    except Exception:                              # noqa: BLE001 - ★名前が無いだけ
        return None


def _heard_place_name(map_id):
    """★記録済みの挨拶から `(地名, 種別)`（⚠ 無ければ None / RX3-0101）。"""
    try:
        from dq3.knowledge.locations import place_from_records

        return place_from_records(map_id)
    except Exception:                                  # noqa: BLE001 ★名前が出ないだけ
        return None


def direction_between(base, here) -> str | None:
    """★拠点から見た方角（⚠ 世界地図の座標。★同じ升なら None）。

    ⚠ 世界地図は y が下へ増えます（★北は y が小さいほう）。
    """
    if not base or not here:
        return None
    bx, by = base
    hx, hy = here
    dx, dy = hx - bx, hy - by
    if dx == 0 and dy == 0:
        return None
    # ★8 方向。⚠ 45 度ずつに切る（★片方が他方の 2.5 倍以上なら斜めにしない）
    ns = "" if abs(dy) * 2.5 < abs(dx) else ("北" if dy < 0 else "南")
    ew = "" if abs(dx) * 2.5 < abs(dy) else ("東" if dx > 0 else "西")
    return (ns + ew) or None


def _pair(xy):
    """★(x, y) にする（⚠ 形が違えば None）。"""
    try:
        x, y = xy
        return (int(x), int(y))
    except (TypeError, ValueError):
        return None


def _same_world(where, kind) -> bool:
    """★同じ世界の升か（RX3-0321 / 2026-09-20）。

    ⚠⚠ 依頼者「save2 ルビスの従者のほこらだが、仮名がアッサラームの南東の場所（仮）となっている。
      地下世界を意識できていない？」→ ★そのとおりでした。

    ```text
    kind が None      ★どこでもよい（⚠ 世界を問わない呼び方）
    上の世界（0）     ★世界の分からない記録も混ぜる（⚠ ほぼ全部が上の世界だった）
    アレフガルド（2） ⚠⚠ **分からない記録は混ぜない**（★上の世界の町を基準にしない）
    ```

    ★`_marks`（緑の丸 / RX3-0315）と**同じ向き**の決まりです。
    """
    if kind is None:
        return True
    if where is None:
        return int(kind) == WORLD_KIND        # ⚠ 下の世界では、分からない記録を使わない
    return int(where) == int(kind)


def _near(a, b, limit: int | None = None) -> bool:
    """★2 升が近いか（★縦横斜めの升の数 / RX3-0275）。"""
    limit = EXIT_NEAR if limit is None else limit
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= limit


@dataclasses.dataclass
class Location:
    """★1 つの場所（⚠ 複数の map が属してよい）。"""

    location_id: str
    display_name: str | None = None
    suffix: str = ""
    name_source: str = ""
    confidence: str = ""
    #: ★仮名の付け方（RX3-0122）。⚠ 空は「RX3-0122 より前に付いたもの」
    #:
    #:   ```text
    #:   parent     レーベの小部屋1     ★世界座標は要らない
    #:   floor      ナジミの塔 #2       ★世界座標は要らない（塔・洞窟の別の階 / RX3-0196）
    #:   direction  レーベ北西の場所    ⚠ 世界座標が要る
    #:   nearby     レーベ近辺1         ★同上（⚠ 向きだけ出ない）
    #:   unsure     未確認の場所1       ★何も要らない
    #:   ```
    name_rule: str = ""
    location_type: str = ""
    parent_location_id: str = ""
    map_ids: list = dataclasses.field(default_factory=list)
    visited: bool = False
    first_seen_at: str | None = None
    #: ★はじめて入ったときの**世界地図の**座標（⚠ 方角の材料）
    world_x: int | None = None
    world_y: int | None = None
    #: ★★ **どちらの世界の座標か**（RX3-0315 / 2026-09-20）
    #:
    #:   ```text
    #:   0     上の世界（world_main / 256 x 256）
    #:   2     アレフガルド（world_alefgard / 158 x 138）
    #:   None  ⚠ 分からない（★この欄より前に覚えた記録）
    #:   ```
    #:
    #:   ⚠⚠ 依頼者「アレフガルドでの緑の丸が誤って表示される。
    #:     おそらく下の世界の正解地図は別座標。」
    #:   ★そのとおりでした。⚠ 座標だけ持っていて**どちらの世界か**を持っていなかったので、
    #:     上の世界の地点が、そのままアレフガルドの地図に重なって出ていました。
    world_kind: int | None = None
    #: ★勇者メモに「見つけた」を書いたか（⚠ 二度書かない）
    memo_done: bool = False

    @property
    def known(self) -> bool:
        """★正式な名前が分かっているか（⚠ 仮名は「分かっている」ではない）。"""
        return bool(self.display_name) and self.name_source in KNOWN_SOURCES

    @property
    def is_base(self) -> bool:
        """★仮名の基準にしてよい拠点か（指示書 §8）。

        ⚠ 種別が分からないものも拠点に含めます。★DQ3 の ROM から種別は取れず
          （実測 / `location_master.py`）、⚠ 除くと基準が 1 つも無くなるためです。
        """
        return self.known and self.visited and (
            not self.location_type or self.location_type in LM.BASE_TYPES)

    def name(self, detailed: bool = False) -> str | None:
        """★表示名（⚠ `detailed` なら suffix つき / 指示書 §6）。"""
        if not self.display_name:
            return None
        if detailed and self.suffix:
            return "%s %s" % (self.display_name, self.suffix)
        return self.display_name

    def to_json(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Location":
        got = cls(location_id=data["location_id"])
        for key, value in data.items():
            if hasattr(got, key):
                setattr(got, key, value)
        got.map_ids = list(got.map_ids or [])
        return got


#: ★`location-names.csv` の読み込み（⚠ 書き換えたら読み直す / 更新時刻で見る）
_TABLE_CACHE: dict = {}


def table_names(path=None) -> dict[str, str]:
    """★location_id → 表の `name`（⚠ 空の行は入れない / 無ければ空）。"""
    from dq3.knowledge import locations as LOCS

    target = pathlib.Path(path) if path else LOCS.NAMES_PATH
    try:
        stamp = target.stat().st_mtime_ns
    except OSError:
        return {}
    cached = _TABLE_CACHE.get(str(target))
    if cached and cached[0] == stamp:
        return cached[1]
    got = {loc: str(row.get("name") or "").strip()
           for loc, row in LOCS.read_names_table(target).items()}
    got = {loc: name for loc, name in got.items() if name}
    _TABLE_CACHE[str(target)] = (stamp, got)
    return got


class LocationBook:
    """★Master ＋ 実行時。⚠ 地名を出すのはここだけ。"""

    def __init__(self, master: LM.LocationMaster | None = None, path=None,
                 rom_place_name=None, heard_place_name=None, names_path=None) -> None:
        self.master = master if master is not None else LM.LocationMaster({})
        #: ★`location-names.csv`（RX3-0439）。⚠ **渡されたときだけ**読む
        #:   （★検査が本物の表の名前を拾わないように / 画面は `NAMES_PATH` を渡す）
        self.names_path = names_path
        self.path = pathlib.Path(path) if path is not None else BOOK_PATH
        #: ★map 番号 → ROM の地名（⚠ 検査で差し替える。★既定はユーザーの ROM / RX3-0092）
        self.rom_place_name = rom_place_name if rom_place_name is not None else _rom_place_name
        #: ★記録済みの挨拶から地名を取る（⚠ 検査で差し替える / RX3-0101）
        self.heard_place_name = (heard_place_name if heard_place_name is not None
                                 else _heard_place_name)
        self.locations: dict[str, Location] = {}
        #: ★最後に居た世界地図の升（⚠ 方角の材料）
        self.last_world: tuple[int, int] | None = None
        #: ★最後に居た世界地図の種別（RX3-0315 / ⚠ 0 = 上の世界 / 2 = アレフガルド）
        self.last_world_kind: int = WORLD_KIND
        #: ★訪れた順（⚠ 直近の拠点を出すため）
        self.visit_order: list[str] = []
        self._dirty = False

    # --- ★読み書き ---------------------------------------------------------

    @classmethod
    def load(cls, master_path=None, path=None, strict: bool = False,
             rom_place_name=None, heard_place_name=None, names_path=None) -> "LocationBook":
        master = LM.load(master_path, strict=strict) if LM.resolve_path(master_path) else LM.LocationMaster({})
        got = cls(master, path, rom_place_name, heard_place_name, names_path=names_path)
        try:
            data = json.loads(got.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # ★はじめてなら、既にある記録を取り込む（指示書 §22）
            got.migrate(got.path.parent / "player-knowledge.json")
            return got
        for loc_id, row in (data.get("locations") or {}).items():
            try:
                got.locations[loc_id] = Location.from_json(row)
            except (KeyError, TypeError):
                continue                                 # ⚠ 壊れた行は捨てて、残りは読む
        try:
            got.last_world_kind = int(data.get("last_world_kind", WORLD_KIND))
        except (TypeError, ValueError):
            got.last_world_kind = WORLD_KIND
        world = data.get("last_world")
        if isinstance(world, list) and len(world) == 2:
            got.last_world = (int(world[0]), int(world[1]))
        got.visit_order = [x for x in (data.get("visit_order") or []) if isinstance(x, str)]
        return got

    def migrate(self, knowledge_path=None) -> int:
        """★既にある記録を取り込む（指示書 §22 / ⚠ 二重管理をしない）。

        ```text
        player-knowledge.json の visited_locations   → 行った場所
        player-knowledge.json の location_names      → 会話で覚えた名前（★レーベ = L9）
        ```
        ⚠ ここでは**仮名を付けません**（★実際に入ったときに付ける）。
        戻り値: ★足した場所の数。
        """
        from dq3.knowledge import locations as LOC

        names, visited = LOC.read_learned(knowledge_path)
        added = 0
        for loc_id in sorted(visited | set(names)):
            loc = self.locations.get(loc_id)
            if loc is None:
                loc = Location(location_id=loc_id)
                self.locations[loc_id] = loc
                added += 1
                self._dirty = True
            if loc_id[1:].isdigit():
                map_id = int(loc_id[1:])
                if map_id not in (loc.map_ids or []):
                    loc.map_ids = sorted((loc.map_ids or []) + [map_id])
                    self._dirty = True
            if loc_id in visited and not loc.visited:
                loc.visited = True
                self._dirty = True
                if loc_id not in self.visit_order:
                    self.visit_order.append(loc_id)
            if names.get(loc_id) and not loc.display_name:
                loc.display_name = names[loc_id]
                loc.name_source = "dialogue"
                loc.confidence = "OBSERVED"
                self._dirty = True
        return added

    def save(self, force: bool = False) -> bool:
        if not force and not self._dirty:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "game": "dq3",
                "last_world": list(self.last_world) if self.last_world else None,
                "last_world_kind": int(self.last_world_kind),
                "visit_order": self.visit_order,
                "locations": {k: v.to_json() for k, v in sorted(self.locations.items())},
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            return False
        self._dirty = False
        return True

    # --- ★引く -------------------------------------------------------------

    def location_id_of(self, map_id) -> str:
        """★その map が属する場所（⚠ Master が言えばそれ、無ければ 1 map = 1 場所）。"""
        row = self.master.by_map.get(int(map_id))
        return row.location_id if row else default_location_id(map_id)

    def get_location(self, map_id) -> Location:
        """★その map の場所（⚠ 無ければその場で作る。★まだ保存はしない）。"""
        map_id = int(map_id)
        loc_id = self.location_id_of(map_id)
        got = self.locations.get(loc_id)
        if got is None:
            got = Location(location_id=loc_id)
        return self._merge_master(got, map_id)

    def _merge_master(self, loc: Location, map_id: int | None = None) -> Location:
        """★Master が言うことを上書きで載せる（⚠ 人の編集がいちばん強い）。"""
        rows = [r for r in self.master.by_map.values() if r.location_id == loc.location_id]
        maps = sorted({r.map_id for r in rows} | set(loc.map_ids or []))
        if map_id is not None and map_id not in maps:
            maps.append(map_id)
        loc.map_ids = sorted(maps)
        row = next((r for r in rows if r.map_id == map_id), None) or (rows[0] if rows else None)
        if row is not None:
            if row.named:
                loc.display_name = row.display_name
                loc.name_source = row.name_source
                loc.confidence = row.confidence or loc.confidence
            if row.location_type:
                loc.location_type = row.location_type
            if row.parent_location_id:
                loc.parent_location_id = row.parent_location_id
        if not (row is not None and row.named) and loc.name_source != "manual":
            self._apply_table_name(loc, self.names_path)
        # ★suffix は map ごと（⚠ Master にあればそれ、無ければ 2 つ目以降に連番）
        loc.suffix = self.suffix_for(loc, map_id)
        return loc

    @staticmethod
    def _apply_table_name(loc: Location, names_path) -> None:
        """★`location-names.csv` の `name` を既定の名前にする（RX3-0439 / 2026-09-27 依頼者）。

        ```text
        人が画面で付けた名前（manual）   ★いちばん強い（⚠ ここでは触らない）
        location-names.csv の name       ★ここ（⚠ review_status は見ない。表示の既定なので）
        ROM の地名 / 会話で覚えた名前 / 仮名
        ```

        ★命名の窓の既定の文字も `display_name` なので、これで表の名前になる。
        ⚠ 表から名前が消えたら、表から来た名前も消す（★次に入ったときに付け直す）。
        """
        name = table_names(names_path).get(loc.location_id, "") if names_path else ""
        if name:
            if loc.display_name != name or loc.name_source != TABLE:
                loc.display_name, loc.name_source, loc.confidence = name, TABLE, "CONFIRMED"
        elif loc.name_source == TABLE:
            loc.display_name, loc.name_source, loc.confidence = "", PROVISIONAL, ""

    def suffix_for(self, loc: Location, map_id: int | None) -> str:
        """★同じ場所の中で map を見分ける印（指示書 §7）。

        ⚠ 階の名前は**推測しません**。★Master に書いてあればそれ、無ければ `#2` `#3`。
        """
        if map_id is None:
            return ""
        row = self.master.by_map.get(int(map_id))
        if row is not None and row.suffix:
            return row.suffix
        maps = list(loc.map_ids or [])
        if len(maps) <= 1 or map_id not in maps:
            return ""
        index = maps.index(int(map_id))
        return "" if index == 0 else "#%d" % (index + 1)

    def get_location_name(self, map_id, detailed: bool = False) -> str | None:
        """★表示名（⚠ 無ければ None。★仮名を勝手に作らない / 作るのは `enter` のとき）。"""
        return self.get_location(map_id).name(detailed=detailed)

    def is_location_known(self, location_id: str) -> bool:
        loc = self.locations.get(location_id)
        if loc is None:
            return False
        return self._merge_master(loc).known

    def get_last_known_base(self, kind=None) -> Location | None:
        """★直近に居た「名前の分かっている拠点」（指示書 §8）。

        ⚠⚠ `kind` を渡すと、★**その世界の拠点だけ**（RX3-0321 / 2026-09-20）。
          ⚠ ここを絞らないと、`nearest_known_base` で外したはずの
            **よその世界の町が、フォールバックで戻ってきます**（★実際に踏んだ）。
        """
        for loc_id in reversed(self.visit_order):
            loc = self.locations.get(loc_id)
            if loc is None or not self._merge_master(loc).is_base:
                continue
            if kind is not None and not _same_world(loc.world_kind, kind):
                continue
            return loc
        return None

    def nearest_known_base(self, world_xy, kind=None) -> Location | None:
        """★その升にいちばん近い「名前の分かっている拠点」（RX3-0180）。⚠ 座標が無ければ None。

        ⚠⚠ 2026-09-12 依頼者「save5 祠の場所だが、アリアハンではなく、ロマリアの北東に思える」:
          仮名の拠点を**直近に居た拠点**で選んでいたので、ルーラや旅の扉で別の大陸へ渡ると
          ⚠ 遠い拠点の名前を名乗った（★ロマリアのそばの祠が「アリアハン北西の場所」）。
        → ★世界座標のある拠点のうち、升の距離がいちばん近いもの。⚠ 同じ距離なら直近に居たほう。

        ⚠ **ROM に名前がある拠点（ルーラの町）を先に**見ます。★人が名前を付けた場所
          （「アリアハンの玉座」「ナジミの塔への洞窟」）も拠点扱いで、町と同じ升の座標を持つため、
          ⚠ 混ぜると「アリアハンの玉座北東の場所」のような名前になります（2026-09-12 に空打ちで確かめた）。
          → ROM の町が 1 つも無いときだけ、ほかの拠点から選びます。
        """
        if not world_xy:
            return None
        hx, hy = int(world_xy[0]), int(world_xy[1])
        recent = {loc_id: i for i, loc_id in enumerate(self.visit_order)}
        bases = [loc for loc in self.locations.values()
                 if loc.world_x is not None and loc.world_y is not None and loc.display_name
                 and _same_world(loc.world_kind, kind)
                 and self._merge_master(loc).is_base]
        towns = [loc for loc in bases if loc.name_source == "rom"]
        best = None
        for loc in towns or bases:
            key = ((loc.world_x - hx) ** 2 + (loc.world_y - hy) ** 2,
                   -recent.get(loc.location_id, -1))
            if best is None or key < best[0]:
                best = (key, loc)
        return best[1] if best is not None else None

    # --- ★仮名 -------------------------------------------------------------

    def make_provisional_name(self, world_xy=None, location_type: str = "",
                              base: Location | None = None,
                              parent: Location | None = None) -> str:
        """★仮名を作る（⚠ 保存はしない。★`enter` が保存する）。

        ## ★決め方（⚠ 上から順に。★確かなものを先に / RX3-0122）

        ```text
        0 塔・洞窟の中  ナジミの塔 #2          ★塔・洞窟から階段で（RX3-0196 / #n は通し番号）
        1 親が分かる    レーベの小部屋1        ★同じ場所の中から入った
        2 方角が出る    アリアハン北西の洞窟   ★世界座標があり向きが決まる
        3 近隣が分かる  レーベ近辺1            ⚠ 方角は出ないが近くに既知の拠点
        4 何も無い      未確認の場所1          ⚠⚠ 推測しない
        ```

        ⚠⚠ **攻略知識から正式名を推測しません。** ★仮名は `provisional` のままです。

        ## ⚠⚠ 座標が無いときに拠点の名前を使ってはいけない（2026-09-06 / RX3-0091）

        ★`direction_between` は「同じ升」でも「座標が無い」でも `None` を返します。
        ⚠ 見分けずに拠点の名前を使うと、**まったく無関係な場所の名前**を名乗ります
          （★依頼者の実機で、アリアハン（map 0）が「レーべの場所 2」になった）。
        → ★座標が片方でも無いなら、拠点の**方角**は名乗りません。

        ## ⚠ 「レーベの場所」をやめた理由（2026-09-08 / RX3-0122）

        ★方角が出ないのに「レーベの場所」と書くと、⚠ **レーベそのもの**に見えます。
        → ★`レーベ近辺1`。⚠ 「近く」だとしか言っていないことが分かります。
        """
        return self.provisional_for(world_xy, location_type, base, parent)[0]

    def provisional_for(self, world_xy=None, location_type: str = "",
                        base: Location | None = None,
                        parent: Location | None = None) -> tuple:
        """★仮名と、⚠ **どの決まりで付けたか**（`(名前, name_rule)` / RX3-0122）。

        ⚠ 付け方を残すのは、★あとで「付け直してよいか」を決めるためです
        （`_needs_rename`。⚠ 座標を使っていない仮名を消すと、入るたびに名前が変わる）。
        """
        word = LM.TYPE_WORD.get(location_type or "", "場所")
        # --- ★0 塔・洞窟の別の階（RX3-0196）。⚠ 階の仮名の中からも続けて数える
        root = self.dungeon_root(parent)
        if root:
            return self._floor_name(root), FLOOR_RULE
        # --- ★1 親（⚠ 名前の確かな場所の中から入ったときだけ）
        if parent is not None and parent.display_name and parent.name_source in KNOWN_SOURCES:
            # ⚠ 種別が分からないなら「小部屋」（★「場所」より中に居ることが伝わる）
            inner = word if location_type else INNER_WORD
            return self._numbered("%sの%s" % (parent.display_name, inner)), PARENT_RULE
        if base is None:
            # ★いちばん近い拠点（RX3-0180）。⚠ 座標が無ければ直近の拠点（★下の条件で方角には使わない）
            # ⚠⚠ 別の世界の拠点を基準にしない（RX3-0315 / ★升の意味が違う）
            base = (self.nearest_known_base(world_xy, kind=self.last_world_kind)
                    or self.get_last_known_base(kind=self.last_world_kind))
        # ⚠ 「拠点の名前を使ってよい」= 拠点に名前があり、★両方の座標がある
        locatable = (base is not None and base.display_name
                     and base.world_x is not None and bool(world_xy))
        if locatable:
            where = direction_between((base.world_x, base.world_y), world_xy)
            # --- ★2 方角
            if where:
                return self._unique("%s%sの%s" % (base.display_name, where, word)), DIRECTION_RULE
            # --- ★3 近隣（⚠ 同じ升なので向きが言えない）
            return self._numbered("%s%s" % (base.display_name, NEARBY_WORD)), NEARBY_RULE
        # --- ★4 何も言えない
        return self._numbered("%s%s" % (UNSURE_HEAD, word)), UNSURE_RULE

    def _needs_rename(self, loc: Location) -> bool:
        """⚠ 既に付いている仮名が、★いまの決まりでは作れない形か（RX3-0091）。

        ⚠⚠ `RX3-0091` より前に付いた仮名は、座標が無いのに拠点の名前を名乗って
        いることがあります（★記録に残ってしまうので、入り直したときに直します）。

        ## ⚠⚠ 付け直してよいのは「座標が要る付け方」だけ（2026-09-08 / RX3-0122）

        ★`レーベの小部屋1` や `レーベ近辺1` は**世界座標を使っていません**。
        ⚠ ここで一緒に消すと、★入るたびに名前が変わります（= 依頼者の困りごと）。
        """
        if loc.name_source != PROVISIONAL or not loc.display_name:
            return False
        if loc.world_x is not None:
            # ★RX3-0180: 方角の仮名が**いちばん近い拠点**を名乗っていなければ付け直す
            #   （★「アリアハン北西の場所」→「ロマリア北西の場所」）。⚠ 近い拠点が同じなら触らない
            if loc.name_rule == DIRECTION_RULE:
                near = self.nearest_known_base((loc.world_x, loc.world_y),
                                               kind=loc.world_kind)
                # ★★ よその世界の町を名乗っている仮名は付け直す（RX3-0321 / 2026-09-20）
                #   ⚠⚠ 依頼者「ルビスの従者のほこらだが、仮名がアッサラームの南東の場所（仮）」。
                #   ★下の世界なのに、上の世界の町を基準にしていました。
                #   → ⚠ 同じ世界に拠点が 1 つも無ければ、★方角では名乗れない（付け直す）。
                if near is None:
                    return loc.world_kind is not None and loc.world_kind != WORLD_KIND
                return not loc.display_name.startswith(near.display_name)
            return False
        if loc.name_rule in (PARENT_RULE, NEARBY_RULE, UNSURE_RULE, FLOOR_RULE):
            return False                    # ★座標を使っていないので、そのままでよい
        # ⚠ 古い記録（`name_rule` が空）。★安全な形だけ残す
        return not (loc.display_name.startswith(UNSURE_HEAD)
                    or loc.display_name.startswith("知らない"))

    def is_town_like(self, map_id) -> bool:
        """★その map が「町のたぐい」と**分かっている**か（RX3-0355 / 2026-09-21）。

        ⚠⚠ 依頼者「特にダンジョンはこの機能は一旦凍結させたい」（★自動移動の `[入]`）。

        ```text
        ★true   種別が town / castle / village
                 ★ROM の地名（ルーラの行き先）= 町だと分かっている
        ⚠ false 塔・洞窟・祠・迷宮 / ★**分からない**とき（安全側）
        ```

        ⚠ 「分からない = false」です。★推測で町だと決めません
        （⚠ DQ3 の ROM から種別は取れません / `RX3-0080`）。
        """
        try:
            loc = self.get_location(int(map_id))
        except Exception:                                # noqa: BLE001 ★読めないときは黙って false
            return False
        if loc is None:
            return False
        if loc.location_type in LM.BASE_TYPES:
            return True
        if loc.location_type:
            return False                                 # ★塔・洞窟…と分かっている
        # ⚠ 種別が空 → ★ROM の地名（ルーラの行き先）なら町
        if loc.name_source == "rom":
            return True
        name = (loc.display_name or "").rstrip(FLOOR_TAIL_CHARS) or (loc.display_name or "")
        if name.endswith(DUNGEON_WORDS):
            return False
        return False                                     # ⚠ 分からない → ★出さない（安全側）

    @staticmethod
    def dungeon_root(parent) -> str | None:
        """★親が塔・洞窟なら、その場所の名前（⚠ 階の印は外す / RX3-0196）。町・城・村なら None。

        ```text
        ★階の仮名（ナジミの塔 #2）        → ナジミの塔（★仮名の階からも続けて数える）
        ★名前の確かな塔・洞窟             → 種別が塔・洞窟・祠・迷宮 / 種別が空なら名前の終わり（塔・洞窟…）
        ⚠ 町・城・村（種別）/ ROM の地名   → None（★今までどおり「〜の小部屋」）
        ```
        ⚠ 人が付けた「ナジミの塔２F」は、終わりの階の印（２F / 2 / #3 / B1）を外して「ナジミの塔」。
        """
        if parent is None or not parent.display_name:
            return None
        if parent.name_source == PROVISIONAL:
            if parent.name_rule == FLOOR_RULE:
                return parent.display_name.split(FLOOR_MARK)[0]
            return None                          # ⚠ 仮名の中に仮名を作らない（RX3-0122）
        if parent.name_source not in KNOWN_SOURCES or parent.name_source == "rom":
            return None                          # ★ROM の地名は町（ルーラの行き先）だけ
        if parent.location_type in LM.BASE_TYPES:
            return None
        base = parent.display_name.rstrip(FLOOR_TAIL_CHARS) or parent.display_name
        if parent.location_type in DUNGEON_TYPES:
            return base
        if not parent.location_type and base.endswith(DUNGEON_WORDS):
            return base
        return None

    def _floor_name(self, root: str) -> str:
        """★`ナジミの塔 #2` から番号を振る（⚠ #1 は塔そのもの / ★同じ名前を 2 か所に付けない）。"""
        taken = {loc.display_name for loc in self.locations.values() if loc.display_name}
        for n in range(2, 1000):
            candidate = "%s%s%d" % (root, FLOOR_MARK, n)
            if candidate not in taken:
                return candidate
        return "%s%s?" % (root, FLOOR_MARK)

    def _numbered(self, prefix: str) -> str:
        """★`レーベ近辺1` のように **1 から**番号を振る（RX3-0122）。

        ⚠ `_unique` は 1 つ目に番号を付けません（★`レーベ北西の場所` は 1 つで足りる）。
        ⚠⚠ こちらは「同じ言い方が何個も出る」前提なので、★最初から番号を付けます
        （★`レーベ近辺` と `レーベ近辺 2` が混ざると、どちらが先か分かりません）。

        ★同じ場所には**同じ仮名**が付き続けます（⚠ 名前は保存されているので、
        入り直しても作り直しません）。
        """
        taken = {loc.display_name for loc in self.locations.values() if loc.display_name}
        for n in range(1, 1000):
            candidate = "%s%d" % (prefix, n)
            if candidate not in taken:
                return candidate
        return prefix

    def _unique(self, name: str) -> str:
        """⚠⚠ **同じ仮名を 2 か所に付けない**（★2026-09-06 に実際に起きた）。

        ★方角も種別も分からないと、別の場所が**まったく同じ名前**になります
          （⚠ 「レーべの場所」が 2 つできた）。→ ★2 つ目からは番号を足します。
        """
        taken = {loc.display_name for loc in self.locations.values() if loc.display_name}
        if name not in taken:
            return name
        for n in range(2, 100):
            candidate = "%s %d" % (name, n)
            if candidate not in taken:
                return candidate
        return name

    # --- ★入る -------------------------------------------------------------

    def note_world(self, x, y, exit_xy=None, kind=None) -> None:
        """★世界地図に居るあいだ、升を覚えておく（⚠ 入った瞬間の方角に使う）。

        ★`exit_xy` は Lua（`world_edges.lua`）が毎フレーム見た「出た直後の升」（RX3-0275）。
          ⚠ 0.5 秒おきの `x, y` は、出たあと歩いた升のことがある → ★届いていればこちらを使い、
          入ったときの升（町の 1〜2 歩手前）を直す（⚠ 近いときだけ / `_fix_world`）。

        ★★ 出た**直後**の升を、その場所の世界座標として覚えます ★★

        ⚠⚠ これが無いと方角が出ません（2026-09-05 に実測で踏んだ）。
          ★町から出ると、勇者は**その町の升**に立ちます。だから「出た直後の升」＝
          その場所の世界地図での位置です。⚠ 後から歩いた升を使うとずれます。
        """
        if x is None or y is None:
            return
        got = (int(x), int(y))
        # ★★ **どちらの世界の升か**（RX3-0315 / 2026-09-20）
        #   ⚠⚠ ここは長らく上の世界（kind 0）でしか呼ばれておらず、
        #     ★アレフガルドの地点は「最後に居た**上の世界**の升」を持っていました。
        #     → ⚠ 緑の丸が、下の世界の地図に**まったく違う升**で出ていました。
        world = WORLD_KIND if kind is None else int(kind)
        exit_at = _pair(exit_xy)
        inside = getattr(self, "_inside", None)
        if inside:
            self._inside = None
            loc = self.locations.get(inside)
            if loc is not None:
                self._fix_world(loc, exit_at or got, trusted=exit_at is not None,
                                kind=world)
        if got != self.last_world or world != self.last_world_kind:
            self.last_world, self.last_world_kind = got, world
            self._dirty = True

    def _fix_world(self, loc: Location, at: tuple, trusted: bool, kind=None) -> None:
        """★出た直後の升で、その場所（と中に持つ場所）の世界座標を埋める / 直す（RX3-0275）。

        ```text
        座標が空                      ★埋める（今までどおり）
        trusted（Lua の出口の升）で近い ★直す（⚠ 入ったときの升は 0.5 秒おきの読みで町の 1〜2 歩手前）
        遠い（EXIT_NEAR 升より先）     ⚠ 直さない（★ルーラ・キメラのつばさで別の町へ出た）
        ```
        """
        targets = [loc]
        anchor = self.anchor_of(loc)
        if anchor is not None and anchor is not loc:
            targets.append(anchor)
        world = WORLD_KIND if kind is None else int(kind)
        for target in targets:
            # ⚠⚠ **別の世界の升とは比べない**（RX3-0315）。
            #   ★上の世界の (100, 50) と アレフガルドの (100, 50) は**まったく別の場所**です。
            same_world = target.world_kind is None or target.world_kind == world
            if target.world_x is None or target.world_y is None:
                target.world_x, target.world_y = at
            elif not same_world:
                continue                       # ⚠ よその世界の座標は直さない
            elif trusted and (target.world_x, target.world_y) != at \
                    and _near((target.world_x, target.world_y), at):
                target.world_x, target.world_y = at
            else:
                continue
            target.world_kind = world
            self._dirty = True

    def anchor_of(self, loc: Location | None) -> Location | None:
        """★その場所を中に持つ、名前の確かな場所（⚠ 自分が確かなら自分 / 分からなければ None / RX3-0275）。

        ★親の id を辿る。⚠ RX3-0275 より前の小部屋は親の id を持たない → 仮名「Xの小部屋N」の X で引く。
        ⚠ 仮名しか無い場所（未確認の場所1 など）は None（★仮名の中の仮名を作らない / RX3-0122）。
        """
        seen: set = set()
        cur = loc
        while cur is not None and cur.location_id not in seen:
            if cur.display_name and cur.name_source in KNOWN_SOURCES:
                return cur
            seen.add(cur.location_id)
            nxt = self.locations.get(cur.parent_location_id) if cur.parent_location_id else None
            if nxt is None and cur.name_rule == PARENT_RULE:
                nxt = self._holder_by_name(cur.display_name)
            cur = nxt
        return None

    def _holder_by_name(self, name) -> Location | None:
        """★仮名「Xの小部屋N」（★`provisional_for` の 1 の形）の X の場所（⚠ 名前の確かなものだけ）。"""
        if not name:
            return None
        for word in (INNER_WORD, *LM.TYPE_WORD.values()):
            head, sep, tail = name.rpartition("の" + word)
            if sep and head and tail.isdigit():
                for other in self.locations.values():
                    if other.display_name == head and other.name_source in KNOWN_SOURCES:
                        return other
        return None

    @staticmethod
    def _inner_but_named_by_direction(loc: Location, parent, anchor, fresh: bool) -> bool:
        """★仮名の小部屋・階から入り直した場所が、世界地図の方角の仮名を持っている（RX3-0275）。

        ★RX3-0275 より前は、仮名の小部屋から入ると親にできず、方角で名付けていた（★イシスの城の奥が「イシス西の場所」）。
        ⚠ 町そのもの（小部屋でない）から入った場所は触らない（★町の外の原っぱの map など）。
        """
        return (not fresh and anchor is not None and parent is not None
                and loc.name_source == PROVISIONAL
                and loc.name_rule in (DIRECTION_RULE, NEARBY_RULE)
                and parent.name_rule in (PARENT_RULE, FLOOR_RULE))

    def enter(self, map_id, world_xy=None) -> dict:
        """★その map に入った。⚠ **場所が初めてのときだけ** `first` を True で返す。

        戻り値: `{"location": Location, "first": bool, "name": str, "provisional": bool}`
        """
        map_id = int(map_id)
        loc_id = self.location_id_of(map_id)
        # ★★ ⚠ どこから入ったか（RX3-0122）★★
        #
        #   ★`_inside` は「いま中に居る場所」で、⚠ 世界地図へ出ると消えます
        #   （`note_world`）。★消えていない = **世界地図を経ずに**別の map へ移った
        #   ＝ 同じ場所の中（小部屋・地下）と見なせます。
        #
        #   ⚠ 親にできるのは**名前の確かな場所**だけです（`make_provisional_name`）。
        #     ★仮名の中の仮名（「未確認の場所1の小部屋1」）を作らないため。
        came_from = getattr(self, "_inside", None)
        parent = self.locations.get(came_from) if came_from and came_from != loc_id else None
        # ★★ 小部屋の小部屋（RX3-0275 / 依頼者「◯があるが、何もない」/ イシス西の場所）:
        #   ⚠ 仮名の小部屋から入ると親にできず、世界地図の方角で名付けていた（★城の奥の部屋が「イシス西の場所」）。
        #   → ★それを中に持つ、名前の確かな場所を親にする（★仮名の中の仮名は作らない決まりのまま）。
        anchor = self.anchor_of(parent) if parent is not None else None
        fresh = loc_id not in self.locations
        loc = self.locations.get(loc_id) or Location(location_id=loc_id)
        self.locations[loc_id] = loc
        loc = self._merge_master(loc, map_id)
        if fresh:
            loc.first_seen_at = _now()
            # ★入口の升（Lua が毎フレーム見た / RX3-0275）→ 中に持つ場所の升 → ⚠ 最後に読んだ世界地図の升
            held = ((anchor.world_x, anchor.world_y)
                    if anchor is not None and anchor.world_x is not None else None)
            here = _pair(world_xy) or held or self.last_world
            if here:
                loc.world_x, loc.world_y = int(here[0]), int(here[1])
                # ★どちらの世界の升か（RX3-0315）。★中に持つ場所から受け継いだなら、その世界
                loc.world_kind = (anchor.world_kind
                                  if (held is not None and _pair(world_xy) is None
                                      and anchor is not None and anchor.world_kind is not None)
                                  else self.last_world_kind)
        if not loc.visited:
            loc.visited = True
        if loc_id in self.visit_order:
            self.visit_order.remove(loc_id)
        self.visit_order.append(loc_id)
        #: ★次に世界地図へ出たとき、その升をこの場所の座標として覚える
        self._inside = loc_id
        provisional = False
        if self._needs_rename(loc):
            # ⚠ 誤った仮名（★座標が無いのに拠点を名乗っている）は付け直す
            loc.display_name = None
        if self._inner_but_named_by_direction(loc, parent, anchor, fresh):
            # ★★ 前の決まりで世界地図の方角の名前になった奥の部屋（RX3-0275）→ 付け直す / 升も中に持つ場所へ
            loc.display_name = None
            if anchor.world_x is not None:
                loc.world_x, loc.world_y = anchor.world_x, anchor.world_y
        # ⚠⚠ 2026-09-07（RX3-0094）: **入るたびに引き直します**。
        #   ★`RX3-0093` で復号器を直しても、⚠ すでに保存された名前は古いままでした
        #     （`name_source: rom` を付け直しの対象にしていなかったため）。
        #   ★ROM は正本で、引くのは安い。⚠ 人が付けた名前（manual）だけは触りません。
        if loc.name_source not in ("manual", TABLE):
            # ★入った場所だけ ROM の地名を引く（⚠ ネタバレを出さない / RX3-0092）
            from_rom = self.rom_place_name(map_id)
            if from_rom:
                loc.display_name = from_rom
                loc.name_source, loc.confidence = "rom", "OBSERVED"
        # ⚠⚠ 2026-09-07（RX3-0101）: 記録済みの挨拶が台帳へ渡っていませんでした。
        #   ★`learn_from_text` は「既に覚えていれば触らない」ので、⚠ 一度
        #   `player-knowledge.json` に入ると**二度と promote されません**。
        #   → ★入るたびに記録からも取り直します（⚠ 聞き直さなくてよい）。
        if loc.name_source not in ("rom", "manual", "dialogue", TABLE):
            heard = self.heard_place_name(map_id)
            if heard and heard[0]:
                self.promote(loc.location_id, heard[0], source="dialogue",
                             location_type=heard[1])
        if not loc.display_name:
            loc.display_name, loc.name_rule = self.provisional_for(
                (loc.world_x, loc.world_y) if loc.world_x is not None else None,
                loc.location_type, parent=anchor or parent)
            if loc.name_rule == FLOOR_RULE and parent is not None:
                loc.parent_location_id = parent.location_id      # ★どの塔の階か（RX3-0196）
            elif loc.name_rule == PARENT_RULE and anchor is not None:
                loc.parent_location_id = anchor.location_id      # ★どの場所の中か（RX3-0275 / ◯ を出さない）
            loc.name_source = PROVISIONAL
            loc.confidence = "HYPOTHESIS"
            provisional = True
        self._dirty = True
        return {"location": loc, "first": fresh, "name": loc.name(detailed=True),
                "provisional": provisional or loc.name_source == PROVISIONAL}

    def mark_location_visited(self, location_id: str, map_id=None) -> Location:
        loc = self.locations.get(location_id) or Location(location_id=location_id)
        self.locations[location_id] = loc
        if map_id is not None and int(map_id) not in (loc.map_ids or []):
            loc.map_ids = sorted((loc.map_ids or []) + [int(map_id)])
        loc.visited = True
        if location_id in self.visit_order:
            self.visit_order.remove(location_id)
        self.visit_order.append(location_id)
        self._dirty = True
        return loc

    def mark_memo_done(self, location_id: str) -> None:
        loc = self.locations.get(location_id)
        if loc is not None and not loc.memo_done:
            loc.memo_done = True
            self._dirty = True

    # --- ★名前を昇格させる ---------------------------------------------------

    def promote(self, location_id: str, name: str, source: str = "dialogue",
                confidence: str = "OBSERVED", location_type: str = "") -> bool:
        """★仮名 → 正式名（⚠ `location_id` は変えない / 指示書 §12）。

        ⚠⚠ ここで id を変えると、★過去のメモ・訪問記録・Fact との繋がりが切れます。
        """
        if not name or source not in ("rom", "dialogue", "manual"):
            return False
        loc = self.locations.get(location_id)
        if loc is None:
            return False
        if loc.name_source in ("rom", "manual", TABLE) and source == "dialogue":
            return False                                 # ⚠ 人と ROM のほうが強い
        if location_type and not loc.location_type:
            loc.location_type = location_type
        # ⚠⚠ 2026-09-07（RX3-0100）: 城の挨拶は「アリアハンの おしろ」なので、
        #   ★取れる名前は **map 0 と同じ「アリアハン」**です。
        #   ⚠ そのままだと `_unique` が「アリアハン 2」を作ります（★`RX3-0091` の形）。
        #   → ★挨拶は**種別も**教えてくれるので、⚠ ぶつかるときだけ種別で分けます。
        taken = {o.display_name for k, o in self.locations.items()
                 if k != location_id and o.display_name}
        if name in taken and (location_type or loc.location_type):
            word = LM.TYPE_WORD.get(location_type or loc.location_type, "")
            if word:
                name = "%sの%s" % (name, word)
        if loc.display_name == name and loc.name_source == source:
            return False
        loc.display_name = name
        loc.name_source = source
        loc.confidence = confidence
        self._dirty = True
        return True

    def rename(self, location_id: str, name: str, *, suffix=None, location_type=None) -> bool:
        """★人が画面から付け直す（⚠ `manual` になる / 指示書 §17）。"""
        loc = self.locations.get(location_id) or Location(location_id=location_id)
        self.locations[location_id] = loc
        changed = False
        if name and name != loc.display_name:
            loc.display_name, loc.name_source, loc.confidence = name, "manual", "CONFIRMED"
            changed = True
        if suffix is not None and suffix != loc.suffix:
            loc.suffix, changed = suffix, True
        if location_type is not None and location_type != loc.location_type:
            loc.location_type, changed = location_type, True
        self._dirty |= changed
        return changed

    # --- ★出す -------------------------------------------------------------

    def all_locations(self) -> list[Location]:
        from dq3.knowledge.locations import sort_key

        # ★数の順（RX3-0438 / 管理画面の場所の一覧 / ⚠ 文字列の順だと L10 が L1 の直後に来る）
        return [self._merge_master(v) for _k, v in sorted(self.locations.items(),
                                                           key=lambda kv: sort_key(kv[0]))]

    def stats(self) -> dict:
        rows = self.all_locations()
        return {"locations": len(rows),
                "visited": sum(1 for r in rows if r.visited),
                "named": sum(1 for r in rows if r.known),
                "provisional": sum(1 for r in rows if r.name_source == PROVISIONAL),
                "base": (self.get_last_known_base().display_name
                         if self.get_last_known_base() else None),
                "master_rows": len(self.master.by_map)}


def memo_text(name: str, provisional: bool) -> str:
    """★勇者メモの 1 行（⚠ 既存の文体に合わせる / 指示書 §13）。

    ★既存は「はじめてこの場所へ来た」。⚠ 名前が分かったので、名前で書きます。
    """
    if provisional:
        return "%sを見つけた" % name
    return "%sへ はじめて来た" % name


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="場所の名前（★唯一の入口）")
    parser.add_argument("--map", type=int, default=None, help="★その map の場所を見る")
    args = parser.parse_args(argv)
    from dq3.knowledge.locations import NAMES_PATH

    book = LocationBook.load(names_path=NAMES_PATH)
    if args.map is not None:
        loc = book.get_location(args.map)
        print("map %d → %s / %s（%s / %s）"
              % (args.map, loc.location_id, loc.name(detailed=True), loc.name_source or "—",
                 "行った" if loc.visited else "まだ"))
        return 0
    print("★%s" % json.dumps(book.stats(), ensure_ascii=False))
    for loc in book.all_locations():
        print("  %-6s %-18s %-12s maps=%s%s"
              % (loc.location_id, loc.name(detailed=True) or "（名前なし）",
                 loc.name_source or "—", loc.map_ids, " 行った" if loc.visited else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
