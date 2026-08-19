"""ROM から作った地図を1つにまとめて渡す（2026-08-02 / Phase 2）。

★★ **GUI と、将来の別ゲームへ渡す形をここで決めます。** ★★

★2026-08-09 に GUI（`ui/map/presenter.py`）へ繋がりました。
  ⚠ 世界地図（種別0）はここではなく `world_art.py` の担当です。

## 層

| 層 | 中身 | 変わるか |
| --- | --- | --- |
| `terrain` | 地形IDの格子（★1 論理セル 1 件） | ★ROM 由来。変わらない |
| `dynamic` | 宝箱・扉の位置と状態 | ⚠ プレイで変わる |
| `art` | 索引 → タイル4枚とパレット組 | ★ROM 由来。変わらない |
| `knowledge` | プレイヤーが見つけたか | ⚠ 遊んだ分だけ増える |

★`art` は**索引ごとに1件**です。マスごとに持つと同じ絵が何百も並ぶので、
`terrain` の各セルから索引で引きます。

## ⚠ 「見ていないマスを描かない」との関係

★ここが出すのは **地図の中身**です。⚠ 指示書 §2.2 のとおり、
**どこまで見せるかは呼ぶ側が決めます**。ここは「全部」を持っていますが、
GUI は歩いたマスだけを描いてください。

## ⚠ 分かっていないもの

★地形IDに名前を付けるのは、コードで確定した **宝箱 `$14`** と
**扉 `$18`-`$1A`** だけです。他は `unknown` のまま数だけ数えます
（★推測で「これは水」と決めない）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib

from .dungeon_map import (BANK2, CHEST_TERRAIN, DOOR_TERRAINS, TABLE_ENTRIES,
                          TABLE_ENTRY, TERRAIN_TABLES, DungeonMap, map_kind)
from .overlay import DynamicOverlay, build_dynamic
from .rom_tiles import MAP_HEADER, MAP_HEADER_SIZE, order_for_map

#: ★この形の版。⚠ 中身を変えたら上げること
SCHEMA_VERSION = "1.1.0"
GAME_ID = "DQ2"
REGION = "JP"

#: ★名前が確定している地形ID（**コードから**）
NAMED_TERRAIN = {CHEST_TERRAIN: "chest",
                 **{t: "door" for t in DOOR_TERRAINS}}

#: ⚠ 種別0（世界地図）は別経路です
SUPPORTED_KINDS = (1, 2, 3)

#: ★どの道を通って読んだか（`decoder_path`）
PATH_TOWN = "kind1/linear/low5bits"
PATH_DUNGEON = "kind2-3/linear/high3bits/halved/quadrant"

CONFIRMED = "confirmed"
PROBABLE = "probable"
UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True)
class TerrainCell:
    """地形の 1 論理セル。★ROM のどこから来たかまで持ちます。"""

    logical_x: int
    logical_y: int
    terrain_id: int
    raw_byte: int | None
    """⚠ 範囲外なら None（★0 と混ぜない）。"""
    source_address: int | None
    """★PRG のオフセット。⚠ 範囲外なら None。"""
    physical: tuple
    """★このセルが覆う画面マス `[(x, y), ...]`。"""
    indices: tuple
    """★画面マスごとの変換表の索引（種別2以上は象限ぶん4つ）。"""
    tiles: tuple
    """★索引ごとのタイル4枚。"""
    attributes: tuple
    """★索引ごとのパレット組。"""
    decoder_path: str
    confidence: str

    def to_dict(self) -> dict:
        return {
            "logical_x": self.logical_x, "logical_y": self.logical_y,
            "terrain_id": self.terrain_id, "raw_byte": self.raw_byte,
            "source_address": self.source_address,
            "physical_coverage": [list(p) for p in self.physical],
            "indices": list(self.indices),
            "visual_tile_ids": [list(t) for t in self.tiles],
            "attributes": list(self.attributes),
            "decoder_path": self.decoder_path,
            "confidence": self.confidence,
        }


@dataclasses.dataclass
class MapMaster:
    """1マップぶんの「正本」。★GUI へはこれを渡します。"""

    map_id: int
    kind: int
    width: int
    height: int
    screen_width: int
    screen_height: int
    border: int
    header: list
    tile_set: list | None
    pointer: int
    cells: list
    """`TerrainCell` の並び（★行優先）。"""
    dynamic: DynamicOverlay
    unknown_terrain: dict
    rom_sha256: str | None = None

    # --- 使う側の入口 ---------------------------------------------------

    @property
    def terrain(self) -> list:
        """★地形IDだけの格子 `[y][x]`（★昔からの形）。"""
        return [[c.terrain_id for c in self.cells[y * self.width:
                                                  (y + 1) * self.width]]
                for y in range(self.height)]

    def cell_at(self, cx: int, cy: int):
        """論理セル。⚠ 範囲外は None。"""
        if not (0 <= cx < self.width and 0 <= cy < self.height):
            return None
        return self.cells[cy * self.width + cx]

    @property
    def halved(self) -> bool:
        """★1 論理セルが画面 2×2 マスか。"""
        return self.kind >= 2

    def summary(self) -> str:
        unknown = ", ".join(f"${i:02X}×{n}"
                            for i, n in sorted(self.unknown_terrain.items()))
        return (f"map ${self.map_id:02X} 種別{self.kind}"
                f"  {self.width}x{self.height} セル"
                f" / 画面 {self.screen_width}x{self.screen_height} マス\n"
                f"  {self.dynamic.summary()}\n"
                f"  ⚠ 名前が分かっていない地形ID: {unknown or 'なし'}")

    # --- 受け渡し -------------------------------------------------------

    def art_layer(self) -> list:
        """索引 → 絵。★同じ索引は1件だけ（マスごとに持たない）。"""
        seen: dict = {}
        for cell in self.cells:
            for idx, tiles, attr in zip(cell.indices, cell.tiles,
                                        cell.attributes):
                if idx in seen:
                    continue
                base = (BANK2 + TERRAIN_TABLES[self.kind] - 0x8000
                        + idx * TABLE_ENTRY)
                seen[idx] = {"index": idx, "tile_ids": list(tiles),
                             "attribute": attr, "source_address": base,
                             "confidence": CONFIRMED}
        return [seen[k] for k in sorted(seen)]

    def to_dict(self) -> dict:
        """★受け渡し用。⚠ 分からないものは `unknown` のまま残します。"""
        limit = TABLE_ENTRIES.get(self.kind)
        used = max((i for c in self.cells for i in c.indices), default=0)
        return {
            "schema_version": SCHEMA_VERSION,
            "rom": {"sha256": self.rom_sha256, "game_id": GAME_ID,
                    "region": REGION},
            "map": {
                "map_id": self.map_id,
                "map_id_hex": f"${self.map_id:02X}",
                "map_type": self.kind,
                "tile_set": self.tile_set,
                "logical_size": {"width": self.width, "height": self.height},
                "physical_size": {"width": self.screen_width,
                                  "height": self.screen_height},
                "header": list(self.header),
                "border_tile": self.border,
                "data_pointer": self.pointer,
            },
            "layers": {
                "terrain": [c.to_dict() for c in self.cells],
                # ⚠ 表にだけある座標も**捨てません**（`unknown_dynamic`）
                "dynamic": ([self._element(e) for e in self.dynamic.elements]
                            + self.dynamic.unknown_dynamic()),
                "art": self.art_layer(),
                # ⚠ 遊んだ記録は ROM からは作れません。★入れた分だけ出ます
                "knowledge": [{"logical_x": c[0], "logical_y": c[1]}
                              for c in
                              sorted(self.dynamic.knowledge.discovered)],
            },
            "source": {
                "header_address": MAP_HEADER + self.map_id * MAP_HEADER_SIZE,
                "terrain_data_address": BANK2 + self.pointer - 0x8000,
                "conversion_table_address": (BANK2 + TERRAIN_TABLES[self.kind]
                                             - 0x8000),
                "decoder_path": (PATH_DUNGEON if self.halved else PATH_TOWN),
            },
            "confidence": {
                "terrain": CONFIRMED,
                "art": CONFIRMED,
                # ★宝箱・扉の**在り処**は確定。⚠ **状態**は RAM 次第
                "dynamic_objects": CONFIRMED,
                "dynamic_state": (CONFIRMED if self.dynamic.has_ram
                                  else UNKNOWN),
                "tile_set": CONFIRMED if self.tile_set else UNKNOWN,
                "conversion_table_size": (CONFIRMED if limit is not None
                                          else UNKNOWN),
            },
            "unknowns": self._unknowns(limit, used),
        }

    @staticmethod
    def _element(e) -> dict:
        """★定義（ROM）と状態（RAM）を、出どころを添えて出します。"""
        return {
            "object_type": e.kind,
            "logical_x": e.cell[0], "logical_y": e.cell[1],
            "physical_x": e.x, "physical_y": e.y,
            "terrain_id": e.terrain_id,
            "current_state": e.state,
            "state_source": e.source,
            "rom_evidence": e.definition.rom_evidence,
            "ram_evidence": e.definition.ram_evidence,
            "confidence": e.confidence,
        }

    def _unknowns(self, limit, used) -> list:
        out = [{"kind": "terrain_meaning",
                "detail": f"地形ID ${i:02X} の意味（{n} マス）",
                "confidence": UNKNOWN}
               for i, n in sorted(self.unknown_terrain.items())]
        if self.tile_set is None:
            out.append({"kind": "tile_set",
                        "detail": f"map ${self.map_id:02X} のタイルセット決定規則",
                        "confidence": UNKNOWN})
        if limit is None:
            out.append({"kind": "conversion_table_size",
                        "detail": f"種別{self.kind} の変換表の件数"
                                  f"（使った最大の索引 ${used:02X}）",
                        "confidence": UNKNOWN})
        elif used >= limit:
            out.append({"kind": "table_out_of_range",
                        "detail": f"索引 ${used:02X} が件数 {limit} を超える"
                                  "（★丸めずそのまま出しています）",
                        "confidence": UNKNOWN})
        out.append({"kind": "header_bytes", "detail": "ヘッダ byte5/byte6",
                    "confidence": UNKNOWN})
        return out


def build(prg: bytes, map_id: int, ram=None, rom_path=None) -> MapMaster:
    """ROM（と、あれば RAM）から1マップぶんを組み立てる。

    ⚠ 世界地図（種別0）は**別の手順**です。ここは種別1以上だけ受け付けます。
    """
    kind = map_kind(map_id)
    if kind not in SUPPORTED_KINDS:
        raise ValueError(
            f"⚠ map ${map_id:02X} は種別{kind}です。"
            "★いまの手順は街・ダンジョン（種別1以上）だけに使えます。"
            "世界地図は行ポインタ＋ランレングスで別経路です")

    dmap = DungeonMap(prg, map_id)
    path = PATH_DUNGEON if dmap.halved else PATH_TOWN
    span = 2 if dmap.halved else 1
    table = BANK2 + TERRAIN_TABLES[kind] - 0x8000

    cells, unknown = [], {}
    for cy in range(dmap.height):
        for cx in range(dmap.width):
            raw = dmap.raw(cx, cy)
            terrain = dmap.cell(cx, cy)
            if terrain not in NAMED_TERRAIN:
                unknown[terrain] = unknown.get(terrain, 0) + 1
            physical, indices, tiles, attrs = [], [], [], []
            for dy in range(span):
                for dx in range(span):
                    x, y = cx * span + dx, cy * span + dy
                    idx = dmap.index_at(x, y)
                    base = table + idx * TABLE_ENTRY
                    physical.append((x, y))
                    indices.append(idx)
                    tiles.append(tuple(prg[base:base + 4]))
                    attrs.append(prg[base + 4] & 3)
            cells.append(TerrainCell(
                logical_x=cx, logical_y=cy, terrain_id=terrain, raw_byte=raw,
                source_address=(None if raw is None
                                else BANK2 + dmap.pointer - 0x8000
                                + cy * dmap.width + cx),
                physical=tuple(physical), indices=tuple(indices),
                tiles=tuple(tiles), attributes=tuple(attrs),
                decoder_path=path, confidence=CONFIRMED))

    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    sha = None
    if rom_path is not None:
        sha = hashlib.sha256(pathlib.Path(rom_path).read_bytes()).hexdigest()
    screen_w, screen_h = dmap.screen_size
    return MapMaster(
        map_id=map_id, kind=kind, width=dmap.width, height=dmap.height,
        screen_width=screen_w, screen_height=screen_h, border=dmap.border,
        header=list(prg[off:off + MAP_HEADER_SIZE]),
        tile_set=(list(order_for_map(prg, map_id) or []) or None),
        pointer=dmap.pointer, cells=cells,
        dynamic=build_dynamic(dmap, ram), unknown_terrain=unknown,
        rom_sha256=sha)
