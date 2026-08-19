"""MapMaster と、これまでの地図を繋ぐ層（2026-08-03 / Phase 3）。

★★ **既存の地図を置き換えません。** ★★

⚠ GUI からはここを通してください。`MapMaster` が無いマップでは
**これまでどおりの表示へ落ちます**（`fallback_to_observed_map`）。

⚠ Qt にも GUI にも依存しません。Core 層です。

## 重ねる順（★依頼者の指定）

```
1. terrain               ★ROM。変わらない
2. art                   ★ROM。変わらない
3. dynamic definition    ★ROM。そこに宝箱・扉がある
4. runtime dynamic state ⚠ RAM。いま開いているか
5. knowledge             ⚠ 見つけたか
6. exploration mask      ⚠ 歩いたマスだけ見せる
7. player / markers      ⚠ 現在地
```

★★★ **1-3 は不変です。** 4 以降は**重ねるだけ**で、
`BaseTerrain` を書き換えません。

## `map_id` がぶつかるとき

⚠ `map_id` だけでは足りません。2026-07-30 に「`map_id`=01 なのに町の
ポインタ」という記録が見つかっています（マップ切替の一瞬）。

★`resolve_map_master()` は `map_ptr` も見て、食い違えば **`None`** を返します
（→ 呼ぶ側は fallback へ）。
"""

from __future__ import annotations

import dataclasses

from . import map_master as _mm
from . import reader as _reader
from .dungeon_map import map_kind
from .overlay import (KIND_CHEST, STATE_CLOSED, STATE_OPENED, UNKNOWN,
                      RuntimeState)
from .rom_tiles import MAP_HEADER, MAP_HEADER_SIZE

#: ★どうして MapMaster を使えなかったか（★黙って何もしない、を避ける）
REASON_WORLD_MAP = "world_map"
REASON_POINTER_MISMATCH = "pointer_mismatch"
REASON_OUT_OF_RANGE = "out_of_range"
REASON_BUILD_FAILED = "build_failed"

#: ★重ねる順（依頼者の指定）
LAYER_ORDER = ("terrain", "art", "dynamic_definition", "runtime_state",
               "knowledge", "exploration_mask", "markers")


@dataclasses.dataclass(frozen=True)
class Resolution:
    """★`MapMaster` を用意できたか。⚠ できなければ理由を持ちます。"""

    master: object | None
    reason: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.master is not None

    def __bool__(self) -> bool:
        return self.ok


def resolve_map_master(prg: bytes, map_id: int, map_ptr: int | None = None,
                       rom_hash: str | None = None,
                       ram=None) -> Resolution:
    """`map_id`（と `map_ptr`）から `MapMaster` を出す。

    ⚠ 出せないときは **`None` と理由**を返します。★呼ぶ側が fallback します。
    """
    if not 0 <= map_id < 0x6D:
        return Resolution(None, REASON_OUT_OF_RANGE,
                          f"⚠ map ${map_id:02X} はヘッダ表の外です")
    if map_kind(map_id) == 0:
        return Resolution(None, REASON_WORLD_MAP,
                          "⚠ 世界地図は別経路です（★現行表示のまま）")
    # ⚠ map_id だけでは足りない。ポインタが食い違えば使わない
    if map_ptr:
        off = MAP_HEADER + map_id * MAP_HEADER_SIZE
        want = prg[off + 3] | (prg[off + 4] << 8)
        if want != map_ptr:
            return Resolution(
                None, REASON_POINTER_MISMATCH,
                f"⚠ map ${map_id:02X} のポインタは ${want:04X} のはずが "
                f"${map_ptr:04X} でした（★切替の一瞬かもしれません）")
    try:
        master = _mm.build(prg, map_id, ram=ram)
    except Exception as exc:                            # noqa: BLE001
        return Resolution(None, REASON_BUILD_FAILED, f"⚠ {exc}")
    return Resolution(master)


def load_map_layers(master) -> dict:
    """★層ごとに取り出す。⚠ 混ぜません。"""
    return {
        "terrain": _reader.get_base_terrain(master),
        "art": _reader.get_art(master),
        "dynamic_definition": [e.definition for e in
                               _reader.get_dynamic_objects(master)],
        "runtime_state": master.dynamic.runtime,
        "knowledge": _reader.get_knowledge(master),
    }


def compose_static_layers(master) -> list:
    """★1-3 だけ（**変わらない部分**）を重ねます。

    ⚠ 状態は反映しません。`apply_runtime_dynamic_state` を先に呼んでください。
    """
    return _reader.compose_map_layers(master)


def apply_runtime_dynamic_state(master, ram):
    """⚠ RAM を当てた**新しい** `MapMaster` を返します。

    ★★ 元も `BaseTerrain` も書き換えません。
    """
    return _reader.apply_runtime_state(master, ram)


def apply_exploration_mask(tiles, visited=None):
    """★歩いたマスだけ残します（指示書 §2.2）。

    `visited` は**論理セル**の集合。⚠ `None` なら全部返します
    （★全体表示はデバッグ用。既定にしないでください）。
    """
    if visited is None:
        return list(tiles)
    return [t for t in tiles if t.logical in visited]


def logical_to_physical(master, cx: int, cy: int) -> list:
    return _reader.logical_to_physical(master, cx, cy)


def physical_to_logical(master, x: int, y: int) -> tuple:
    return _reader.physical_to_logical(master, x, y)


def resolve_player_position(master, ram) -> dict:
    """⚠ 主人公の位置。読めなければ全部 `None`。

    ★ゲーム座標（`$16`/`$17`）は**画面のマス**です。
    """
    x, y = _reader.get_player_position(ram)
    if x is None or master is None:
        return {"physical": (x, y), "logical": (None, None),
                "inside": None}
    logical = physical_to_logical(master, x, y)
    inside = (0 <= x < master.screen_width and 0 <= y < master.screen_height)
    return {"physical": (x, y), "logical": logical, "inside": inside}


#: ★プレイヤーのいる区画（`$DCA1: LDA $1D`）
PLAYER_REGION = 0x1D


def resolve_current_region(prg, master, ram, visited_regions=None) -> dict:
    """★区画（部屋）。⚠ データが無いマップでは空です。

    ★`$DCA1: LDA $1D / CMP $0D / BEQ` — 同じ区画なら見える。
      展開規則は `region_map.py`（★2026-08-03 に確定）。

    ⚠⚠ **これは「見せてよい」という意味ではありません。**
      `revealed` は常に False にしてあります。どこまで見せるかは
      観測マスク（`apply_exploration_mask`）で決めてください（§2.2）。
    """
    from . import region_map as _region

    if master is None:
        return {"regions": [], "current": None, "confidence": UNKNOWN,
                "note": "⚠ MapMaster がありません"}
    region_map = _region.load(prg, master.map_id)
    if not region_map.has_data:
        return {"regions": [], "current": None, "confidence": "confirmed",
                "note": "⚠ このマップに区画データはありません"}
    current = None
    if ram is not None:
        try:
            current = ram[PLAYER_REGION]
        except (IndexError, TypeError):
            current = None
    return {"regions": _region.to_dict(region_map, current, visited_regions),
            "current": current,
            "rooms": [{"region_id": rid, "cells": [list(c) for c in cells]}
                      for rid, cells in region_map.rooms()],
            "confidence": "confirmed",
            "note": ("⚠ 同じ番号が離れた部屋で使い回されます。"
                     "★1 つの部屋が欲しいときは rooms を見てください")}


def fallback_to_observed_map(resolution: Resolution) -> dict:
    """★`MapMaster` を使えないときに、呼ぶ側へ渡す案内。

    ⚠ 黙って何もしないのを避けます。**理由を言葉で**返します。
    """
    return {"use_observed": True,
            "reason": resolution.reason,
            "detail": resolution.detail}


# --- ★ まとめて使う入口 ---------------------------------------------------

@dataclasses.dataclass
class MapView:
    """★GUI へ渡す 1 枚ぶん。⚠ Qt には触れません。"""

    map_id: int
    map_type: int
    logical_size: tuple
    physical_size: tuple
    tiles: list
    """`ComposedTile` の並び。"""
    player: dict
    region: dict
    objects: list
    """★宝箱・扉（状態つき）。"""
    used_master: bool
    fallback: dict | None = None

    def chests(self, state=None) -> list:
        out = [o for o in self.objects if o.kind == KIND_CHEST]
        return out if state is None else [o for o in out if o.state == state]

    def summary(self) -> str:
        if not self.used_master:
            return f"⚠ 現行表示へ落ちました: {(self.fallback or {}).get('detail')}"
        opened = sum(1 for o in self.objects if o.state == STATE_OPENED)
        closed = sum(1 for o in self.objects if o.state == STATE_CLOSED)
        unknown = sum(1 for o in self.objects if o.state == UNKNOWN)
        return (f"map ${self.map_id:02X} 種別{self.map_type}"
                f"  {len(self.tiles)} マス"
                f" / 宝箱・扉 ★開 {opened} 閉 {closed} ⚠ 不明 {unknown}")


def build_view(prg: bytes, map_id: int, map_ptr: int | None = None,
               ram=None, visited=None, knowledge=None) -> MapView:
    """★1 回で全部やります（★層の順序はここで守ります）。

    ⚠ `visited`（歩いた論理セル）を渡さないと**全部見えます**。
      指示書 §2.2 のとおり、ふだんは渡してください。
    """
    resolution = resolve_map_master(prg, map_id, map_ptr)
    if not resolution:
        return MapView(map_id=map_id, map_type=map_kind(map_id),
                       logical_size=(None, None), physical_size=(None, None),
                       tiles=[], player=resolve_player_position(None, ram),
                       region=resolve_current_region(prg, None, ram),
                       objects=[], used_master=False,
                       fallback=fallback_to_observed_map(resolution))
    master = resolution.master
    # 4. ⚠ RAM を当てる（★新しい写しを作る。元は変えない）
    if ram is not None:
        master = apply_runtime_dynamic_state(master, ram)
    # 5. ⚠ 見つけたセル
    for cell in (knowledge or ()):
        _reader.mark_discovered(master, cell[0], cell[1])
    # 1-3 を重ね、6. マスクをかける
    tiles = apply_exploration_mask(compose_static_layers(master), visited)
    return MapView(
        map_id=map_id, map_type=master.kind,
        logical_size=(master.width, master.height),
        physical_size=(master.screen_width, master.screen_height),
        tiles=tiles,
        player=resolve_player_position(master, ram),
        region=resolve_current_region(prg, master, ram),
        objects=_reader.get_dynamic_objects(master),
        used_master=True)
