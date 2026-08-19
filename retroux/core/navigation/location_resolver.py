"""いま居る場所の**名前**を決める（2026-07-30 / マッパー仕様 4章・フェーズ1）。

★★ **物理マップと論理ロケーションは別物** ★★

    物理マップ  … ROM の `map_id`（+ `map_ptr`）。1フロア = 1つ
    ロケーション … 人が呼ぶ名前。「ローレシア」は 1F/2F/B1 の3マップ

だから表示は **ロケーション名 + 階層** で作る:

    map_id $04  ->  ローレシア B1

## 何が確かで、何が確かでないか

| もの | 出どころ | 確かさ |
| --- | --- | --- |
| map_id ごとの区別 | ROM | 確か |
| 階層ラベル（B1 / 2F …） | 北米版逆アセンブルのコメント | 確か |
| 日本語名 | ⚠ ROM に5件だけ。残りは人の知識 | `name_source` を見る |
| ワールドマップの地域名 | ⚠ 座標の範囲。**遊んで溜める** | 既定では空 |

★**名前が間違っていても経路の判断は壊れない。**
  自動移動が使うのは `map_id` と階層（どちらも ROM 由来）だから。

## 分からないときの態度（仕様 2.4 と同じ）

⚠ 表に無い map_id を**近い名前に丸めない**。
  「未登録のマップ」とはっきり出す。間違った名前は、
  あとで人が「ここは○○のはず」と判断する材料を壊す。
"""

from __future__ import annotations

import dataclasses
import pathlib

from .models import Confidence

#: 検索語に付けるゲーム名。★英語名も出す（英語の攻略サイトが引ける）
GAME_TITLE_JA = "ドラゴンクエストII"
GAME_TITLE_EN = "Dragon Warrior II"


def unique_terms(terms) -> list[str]:
    """重複を消しつつ**順番は保つ**（前のほうが当たりやすい語）。

    ★別の関数にしてある理由: いまの語の組み合わせでは重複が起きないので、
      `search_terms` 越しには**この処理が効いているか確かめられない**。
      語を足したときに順番が崩れないよう、ここを直接試す。
    """
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique.append(term)
    return unique


@dataclasses.dataclass(frozen=True)
class Binding:
    """物理マップ1つぶんの割り当て（`map_bindings.yaml` の1行）。"""

    map_id: int
    location_id: str
    confidence: Confidence
    floor_label: str | None = None
    floor_index: int | None = None
    #: 同じ階に複数マップがあるときの枝番（例: ロンダルキアへの洞窟 2F-1）
    floor_variant: int | None = None
    evidence_en: str | None = None


@dataclasses.dataclass(frozen=True)
class Location:
    """論理ロケーション1つぶん（`locations.yaml` の1件）。"""

    location_id: str
    name: str
    name_en: str
    #: `"rom"` / `"knowledge"` / `None`。★None は日本語名が無い（英名を出す）
    name_source: str | None
    type: str
    known_floors: tuple[int, ...] = ()

    @property
    def name_is_from_rom(self) -> bool:
        return self.name_source == "rom"


@dataclasses.dataclass(frozen=True)
class Region:
    """ワールドマップの地域（`world_regions.yaml` の1件）。

    ⚠ 座標の範囲は ROM から取れない。**既定では1件も無い。**
    """

    region_id: str
    name: str
    location_id: str | None
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    confidence: Confidence = Confidence.PROVISIONAL

    def contains(self, x: int, y: int) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    @property
    def area(self) -> int:
        return (self.x_max - self.x_min + 1) * (self.y_max - self.y_min + 1)


@dataclasses.dataclass(frozen=True)
class ResolvedLocation:
    """「いまここ」の答え。**表示と検索に必要なものを全部入れて返す。**"""

    map_id: int
    map_ptr: int | None
    location: Location | None
    binding: Binding | None
    region: Region | None
    confidence: Confidence
    #: 画面に出す文字列（例: `ローレシア B1`）
    display: str
    #: 名前の出どころを1語で（`rom` / `knowledge` / `unknown` / `unregistered`）
    source: str

    @property
    def registered(self) -> bool:
        """辞書に載っているマップか。★載っていなければ名前を作っていない。"""
        return self.binding is not None

    @property
    def floor_label(self) -> str | None:
        if self.binding is None:
            return None
        return self.binding.floor_label

    @property
    def needs_check(self) -> bool:
        """⚠ 人に確認してほしいか（ROM 由来でない名前・未登録・地域が未設定）。"""
        if self.binding is None:
            return True
        if self.location is None or self.location.name_source != "rom":
            return True
        return False

    def search_terms(self, *, game_ja: str = GAME_TITLE_JA,
                     game_en: str = GAME_TITLE_EN) -> list[str]:
        """攻略を検索するときの語（仕様 4.7）。

        ★重複を消しつつ**順番は保つ**（前のほうが当たりやすい語）。
        """
        if self.location is None:
            return []
        floor = self.floor_label
        base = self.location.name
        terms: list[str] = []
        if floor:
            terms.append(f"{game_ja} {base} {floor} 攻略")
            terms.append(f"{base} {floor}")
        terms.append(f"{game_ja} {base} 攻略")
        terms.append(f"{base} 地図")
        if self.location.name_en and self.location.name_en != base:
            en_floor = f" {floor}" if floor else ""
            terms.append(f"{game_en} {self.location.name_en}{en_floor} map")
        return unique_terms(terms)


class LocationDictionary:
    """3つの YAML を読んで持っておくだけの入れ物。

    ⚠ ファイルが無い・壊れている場合は**空で立ち上がる**。
      地名が出ないだけで、ゲームと移動記録は動く（仕様 11章と同じ態度）。
    """

    def __init__(self, locations: dict[str, Location] | None = None,
                 bindings: dict[int, Binding] | None = None,
                 regions: list[Region] | None = None,
                 problems: list[str] | None = None) -> None:
        self.locations = locations or {}
        self.bindings = bindings or {}
        self.regions = list(regions or [])
        #: 読み込みで気づいた不整合。★捨てずに持って、画面かログに出す
        self.problems = list(problems or [])

    # --- 読み込み -----------------------------------------------------

    @classmethod
    def load(cls, data_dir, logger=None) -> "LocationDictionary":
        directory = pathlib.Path(data_dir)
        problems: list[str] = []
        locations = cls._load_locations(directory, problems)
        bindings = cls._load_bindings(directory, problems, locations)
        regions = cls._load_regions(directory, problems)
        if logger is not None:
            for problem in problems:
                logger.warning("ロケーション辞書: %s", problem)
        return cls(locations, bindings, regions, problems)

    @staticmethod
    def _read_yaml(path: pathlib.Path, problems: list[str]):
        if not path.exists():
            problems.append(f"{path.name} が無い（地名は出ません）")
            return None
        try:
            import yaml
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:                          # noqa: BLE001
            problems.append(f"{path.name} が読めない: {exc}")
            return None

    @classmethod
    def _load_locations(cls, directory: pathlib.Path,
                        problems: list[str]) -> dict[str, Location]:
        raw = cls._read_yaml(directory / "locations.yaml", problems)
        found: dict[str, Location] = {}
        for loc_id, entry in ((raw or {}).get("locations") or {}).items():
            if not isinstance(entry, dict):
                problems.append(f"locations.{loc_id} の書き方が変（飛ばしました）")
                continue
            name_en = str(entry.get("name_en") or loc_id)
            floors = entry.get("floors") or {}
            known = floors.get("known") or []
            found[str(loc_id)] = Location(
                location_id=str(loc_id),
                # ★日本語名が無ければ英名を出す（空文字にしない）
                name=str(entry.get("name") or name_en),
                name_en=name_en,
                name_source=entry.get("name_source") or None,
                type=str(entry.get("type") or "unknown"),
                known_floors=tuple(int(i) for i in known
                                   if isinstance(i, int)),
            )
        return found

    @classmethod
    def _load_bindings(cls, directory: pathlib.Path, problems: list[str],
                       locations: dict[str, Location]) -> dict[int, Binding]:
        raw = cls._read_yaml(directory / "map_bindings.yaml", problems)
        found: dict[int, Binding] = {}
        for entry in ((raw or {}).get("bindings") or []):
            if not isinstance(entry, dict) or entry.get("map_id") is None:
                problems.append(f"bindings に map_id が無い行がある: {entry!r}")
                continue
            map_id = int(entry["map_id"])
            loc_id = str(entry.get("location_id") or "")
            if loc_id not in locations:
                # ⚠ 参照先が無い。**適当に作らない**で飛ばす
                problems.append(
                    f"map ${map_id:02X} の location_id '{loc_id}' が"
                    " locations.yaml に無い")
                continue
            if map_id in found:
                problems.append(f"map ${map_id:02X} が2回出てくる（後を無視）")
                continue
            found[map_id] = Binding(
                map_id=map_id,
                location_id=loc_id,
                confidence=_confidence(entry.get("confidence"),
                                       Confidence.PROBABLE),
                floor_label=(str(entry["floor_label"])
                             if entry.get("floor_label") else None),
                floor_index=(int(entry["floor_index"])
                             if entry.get("floor_index") is not None else None),
                floor_variant=(int(entry["floor_variant"])
                               if entry.get("floor_variant") is not None
                               else None),
                evidence_en=(str(entry["evidence_en"])
                             if entry.get("evidence_en") else None),
            )
        return found

    @classmethod
    def _load_regions(cls, directory: pathlib.Path,
                      problems: list[str]) -> list[Region]:
        raw = cls._read_yaml(directory / "world_regions.yaml", problems)
        found: list[Region] = []
        for entry in ((raw or {}).get("regions") or []):
            bounds = (entry or {}).get("bounds") or {}
            keys = ("x_min", "x_max", "y_min", "y_max")
            if not all(bounds.get(k) is not None for k in keys):
                problems.append(
                    f"regions の bounds が足りない（飛ばしました）: {entry!r}")
                continue
            values = {k: int(bounds[k]) for k in keys}
            if values["x_min"] > values["x_max"] or values["y_min"] > values["y_max"]:
                # ⚠ 逆さの範囲は黙って直さない。書いた人の意図が分からない
                problems.append(f"regions の bounds が逆さ: {entry!r}")
                continue
            found.append(Region(
                region_id=str(entry.get("region_id") or "?"),
                name=str(entry.get("name") or entry.get("region_id") or "?"),
                location_id=(str(entry["location_id"])
                             if entry.get("location_id") else None),
                confidence=_confidence(entry.get("confidence"),
                                       Confidence.PROVISIONAL),
                **values))
        return found

    # --- 引き --------------------------------------------------------

    def region_at(self, x: int, y: int) -> Region | None:
        """その座標を含む地域。★重なっていたら**狭いほう**を採る。

        狭いほうが具体的（「ローレシア城前」より「ローレシア周辺」が広い）。
        """
        hits = [r for r in self.regions if r.contains(x, y)]
        if not hits:
            return None
        return min(hits, key=lambda r: r.area)

    @property
    def is_empty(self) -> bool:
        return not self.bindings


class LocationResolver:
    """`Place` から表示用の名前を作る。**推測しない。**"""

    def __init__(self, dictionary: LocationDictionary,
                 game_title_ja: str = GAME_TITLE_JA,
                 game_title_en: str = GAME_TITLE_EN) -> None:
        self.dictionary = dictionary
        self.game_title_ja = game_title_ja
        self.game_title_en = game_title_en

    @classmethod
    def load(cls, data_dir, logger=None, **kwargs) -> "LocationResolver":
        return cls(LocationDictionary.load(data_dir, logger=logger), **kwargs)

    def resolve_map(self, map_id) -> ResolvedLocation | None:
        """`map_id` だけで引く（座標を持っていない一覧表示用）。

        ⚠ 地域名は付かない。座標が無いので**どの地域かは言えない**。
        """
        if map_id is None:
            return None
        return self.resolve(_MapOnly(int(map_id)))

    def resolve(self, place) -> ResolvedLocation | None:
        """いま居る場所の名前。**場所が読めていなければ None。**

        ⚠ `place` が None のときに「不明」という `ResolvedLocation` を
          返さない。呼ぶ側が「まだ分からない」と「未登録のマップ」を
          区別できなくなるため。
        """
        if place is None or getattr(place, "map_id", None) is None:
            return None
        map_id = int(place.map_id)
        map_ptr = getattr(place, "map_ptr", None)
        binding = self.dictionary.bindings.get(map_id)
        if binding is None:
            # ★未登録。**近い名前に丸めない**
            return ResolvedLocation(
                map_id=map_id, map_ptr=map_ptr, location=None, binding=None,
                region=None, confidence=Confidence.PROVISIONAL,
                display=f"未登録のマップ（ID ${map_id:02X}）",
                source="unregistered")
        location = self.dictionary.locations.get(binding.location_id)
        if location is None:
            # 読み込み時に弾いているので普通は来ない。来たら黙らない
            return ResolvedLocation(
                map_id=map_id, map_ptr=map_ptr, location=None, binding=binding,
                region=None, confidence=Confidence.PROVISIONAL,
                display=f"名前が引けないマップ（ID ${map_id:02X}）",
                source="unknown")

        region = None
        if location.type == "overworld":
            x, y = getattr(place, "x", None), getattr(place, "y", None)
            if x is not None and y is not None:
                region = self.dictionary.region_at(int(x), int(y))

        return ResolvedLocation(
            map_id=map_id, map_ptr=map_ptr, location=location, binding=binding,
            region=region,
            confidence=self._confidence(binding, location, region),
            display=self._display(location, binding, region),
            source=location.name_source or "unknown")

    # --- 組み立て ----------------------------------------------------

    @staticmethod
    def _display(location: Location, binding: Binding,
                 region: Region | None) -> str:
        parts = [location.name]
        if binding.floor_label:
            floor = binding.floor_label
            if binding.floor_variant is not None:
                # ★同じ階に複数マップ。「2F」だけだと別マップと区別できない
                floor = f"{floor}（その{binding.floor_variant}）"
            parts.append(floor)
        text = " ".join(parts)
        if region is not None:
            # 例: 世界地図（ローレシア周辺）
            text = f"{text}（{region.name}）"
        return text

    @staticmethod
    def _confidence(binding: Binding, location: Location,
                    region: Region | None) -> Confidence:
        """どのくらい確かか。★**一番弱いものに合わせる**（仕様 2.4）。"""
        levels = [binding.confidence]
        if region is not None:
            levels.append(region.confidence)
        if location.name_source is None:
            # 日本語名が無く英名を出している。名前としては弱い
            levels.append(Confidence.PROVISIONAL)
        # ★順番の表は `Confidence.rank` 1箇所だけ（models.py）
        return min(levels, key=lambda c: c.rank)

    def search_terms(self, place) -> list[str]:
        resolved = self.resolve(place)
        if resolved is None:
            return []
        return resolved.search_terms(game_ja=self.game_title_ja,
                                     game_en=self.game_title_en)


@dataclasses.dataclass(frozen=True)
class _MapOnly:
    """`map_id` しか分からないときの `Place` 代わり（座標は None）。"""

    map_id: int
    map_ptr: int | None = None
    x: int | None = None
    y: int | None = None


def _confidence(value, default: Confidence) -> Confidence:
    """文字列から確度。**読めなければ既定へ**（勝手に上げない）。"""
    return Confidence.parse(value, default)
