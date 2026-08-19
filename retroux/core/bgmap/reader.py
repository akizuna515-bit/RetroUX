"""MapMaster を読む側の入口（2026-08-02 / Phase 6）。

★★ **GUI からはここだけを使ってください。** ★★

⚠ Qt にも GUI にも依存しません。Core 層です。

## なぜ要るのか

★`MapMaster` の中身（`TerrainCell` の並び、`DynamicOverlay` の3層）は
これからも変わります。⚠ GUI が直接触ると、変えるたびに GUI が壊れます。

★ここを挟んでおけば、**GUI 側は触らずに済みます**。

## 使い方

```python
master = load_map_master(prg, 0x40)                 # ★ROM から
terrain = get_base_terrain(master)                  # ★変わらない
objects = get_dynamic_objects(master)               # ★在り処（状態は unknown）
live = apply_runtime_state(master, ram)             # ⚠ RAM を当てた**写し**
view = compose_map_layers(live, visible=seen_cells) # ★見たマスだけ
```

⚠⚠ `apply_runtime_state` は**新しい `MapMaster` を返します**。
  元の `MapMaster` も、その `BaseTerrain` も書き換えません。

## ⚠ 「見ていないマスを描かない」

★`compose_map_layers()` に `visible` を渡すと、**そのマスだけ**返します。
渡さなければ全部返します。⚠ どちらにするかは呼ぶ側が決めてください
（指示書 §2.2: ROM 解析だけで未探索地形を自動開示しない）。
"""

from __future__ import annotations

import dataclasses

from . import map_master as _mm
from .dungeon_map import OPENED_TERRAIN
from .overlay import STATE_OPENED, UNKNOWN

#: ★1 論理セルが画面何マスぶんか（種別で違う）
SPAN_HALVED = 2
SPAN_PLAIN = 1


# --- 読み込み -------------------------------------------------------------

def load_map_master(prg: bytes, map_id: int, ram=None, rom_path=None):
    """ROM（と、あれば RAM）から1マップぶんを読む。

    ⚠ 世界地図（種別0）は `ValueError` になります。★別経路だからです。
    """
    return _mm.build(prg, map_id, ram=ram, rom_path=rom_path)


def span_of(master) -> int:
    """★1 論理セルが画面何マスぶんか。"""
    return SPAN_HALVED if master.halved else SPAN_PLAIN


# --- 座標 -----------------------------------------------------------------

def logical_to_physical(master, cx: int, cy: int) -> list:
    """論理セル → 画面マス。★種別2以上は 2×2 の 4 マス。"""
    span = span_of(master)
    return [(cx * span + dx, cy * span + dy)
            for dy in range(span) for dx in range(span)]


def physical_to_logical(master, x: int, y: int) -> tuple:
    """画面マス → 論理セル。

    ⚠ 負の座標でも**切り捨て**で答えます（`//` を使うので `-1 -> -1`）。
      範囲の外かどうかは呼ぶ側で見てください（`cell_at` が None を返します）。
    """
    span = span_of(master)
    return (x // span, y // span)


# --- 層ごとに取り出す -----------------------------------------------------

def get_base_terrain(master) -> list:
    """★地形IDの格子 `[y][x]`（論理セル）。**変わりません**。"""
    return master.terrain


def get_terrain_cell(master, cx: int, cy: int):
    """1 論理セルの詳細。⚠ 範囲外は None。"""
    return master.cell_at(cx, cy)


def get_dynamic_objects(master) -> list:
    """★宝箱・扉の一覧（定義 + 状態）。

    ⚠ RAM を当てていなければ、状態はすべて `unknown` です。
    """
    return master.dynamic.elements


def get_unknown_dynamic(master) -> list:
    """⚠ RAM の表にあるが ROM 側に見当たらない座標。**捨てません**。"""
    return master.dynamic.unknown_dynamic()


def get_art(master) -> dict:
    """★索引 → `{"tile_ids", "attribute", ...}`。"""
    return {entry["index"]: entry for entry in master.art_layer()}


def get_knowledge(master) -> set:
    """⚠ 見つけた論理セル。★呼ぶ側が入れた分だけです。"""
    return set(master.dynamic.knowledge.discovered)


def mark_discovered(master, cx: int, cy: int) -> None:
    """★「そのセルを見た」と記録します。⚠ 地形は変わりません。"""
    master.dynamic.knowledge.discover((cx, cy))


# --- 状態を当てる ---------------------------------------------------------

def apply_runtime_state(master, ram):
    """⚠ RAM を当てた**新しい** `MapMaster` を返します。

    ★★ 元の `MapMaster` も `BaseTerrain` も書き換えません。
    """
    return dataclasses.replace(
        master, dynamic=master.dynamic.apply_runtime_state(ram))


def get_player_position(ram) -> tuple:
    """⚠ 主人公の**画面マス**座標 `(x, y)`。読めなければ `(None, None)`。

    ★RAM `$0016` / `$0017`（`memory_map.yaml` と同じ番地）。
    """
    try:
        return (ram[0x0016], ram[0x0017])
    except (IndexError, TypeError):
        return (None, None)


# --- 合成 -----------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class ComposedTile:
    """★合成した 1 画面マス。"""

    x: int
    y: int
    logical: tuple
    terrain_id: int
    """★動的差分を反映した**後**の地形ID。"""
    base_terrain_id: int
    """★ROM のままの地形ID（**変わりません**）。"""
    index: int
    tile_ids: tuple
    attribute: int
    object_type: str | None = None
    object_state: str | None = None
    discovered: bool = False


def compose_map_layers(master, visible=None) -> list:
    """★層を重ねた画面マスの一覧。

    `visible` に論理セルの集合を渡すと、**そのセルだけ**返します。
    ⚠ 渡さなければ全部返します（★どちらにするかは呼ぶ側の判断）。
    """
    span = span_of(master)
    known = set(master.dynamic.knowledge.discovered)
    by_cell = {e.cell: e for e in master.dynamic.elements}
    out = []
    for cell in master.cells:
        key = (cell.logical_x, cell.logical_y)
        if visible is not None and key not in visible:
            continue
        element = by_cell.get(key)
        # ⚠ 状態が unknown のときは**差し替えません**
        opened = element is not None and element.state == STATE_OPENED
        terrain = OPENED_TERRAIN if opened else cell.terrain_id
        for i, (px, py) in enumerate(cell.physical):
            out.append(ComposedTile(
                x=px, y=py, logical=key,
                terrain_id=terrain, base_terrain_id=cell.terrain_id,
                index=cell.indices[i], tile_ids=cell.tiles[i],
                attribute=cell.attributes[i],
                object_type=(element.kind if element else None),
                object_state=(element.state if element else None),
                discovered=key in known))
    assert span in (SPAN_PLAIN, SPAN_HALVED)
    return out


def compose_summary(master, visible=None) -> str:
    """★合成の結果を一言で。⚠ 分からないものは数えて出します。"""
    tiles = compose_map_layers(master, visible)
    unknown = sum(1 for t in tiles if t.object_state == UNKNOWN)
    return (f"map ${master.map_id:02X}  {len(tiles)} マス"
            f" / ★見つけた {sum(1 for t in tiles if t.discovered)}"
            f" / ⚠ 状態不明の物 {unknown}")
