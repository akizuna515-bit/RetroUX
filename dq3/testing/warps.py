"""世界地図で warp する升（町・城・洞窟の入口）を起こす（RX3-0050 / OBSERVER）。

## ★2 つの根拠を**分けて**持つ（追加方針 §4-1）

```text
landmark_cells   HYPOTHESIS  ★世界地図で**珍しいタイル**（id 8〜21, 27, 31 / 各 1〜14 升）の升
                              ⚠ 2026-09-02 実測: アリアハンの入口 (159,192) は tile 10、(160,192) は 11。
                              ★地形（0〜6）は数千升、目印は数升。⚠ 1 町の一致なので仮説
arrival_world    CONFIRMED   ★ローカルから世界地図へ出たときに**降りる升**（19 件 / ROM の表）
                              ⚠ 入口そのものではない（★アリアハンの (159,192) は入っていない）
```

★どちらも「踏むと地図が変わる**かもしれない**升」として、フィールドの run では避けます。
⚠ 製品の判断には使いません（★Observer / RUNNER 限定）。

## ⚠ 限界

★仮説に無い入口は、踏んでから覚えます（`dq3_field_run.lua` の escape）。
★実際に warp した升は `boundary`/`warp_cells` として証跡に残るので、⚠ 仮説の裏取りに使えます。
"""

from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"

#: ⚠ HYPOTHESIS: 世界地図でこれ以下の升しか無いタイルは「目印」（★地形は数千升ある）
LANDMARK_MAX_CELLS = 20
#: ⚠ 0〜6 は地形（海・草原・森・丘・山・…）。★7 と 23 は数十升あり橋などの疑い → 目印にしない
TERRAIN_MAX_ID = 7
NOT_LANDMARK = {23}


def landmark_cells(terrain) -> dict:
    """★珍しいタイルの升（HYPOTHESIS）。`terrain.at(x, y)` を持つものを受け取る。"""
    count = collections.Counter()
    for y in range(terrain.height):
        for x in range(terrain.width):
            count[terrain.at(x, y)] += 1
    rare = {t for t, n in count.items()
            if t is not None and t > TERRAIN_MAX_ID and n <= LANDMARK_MAX_CELLS
            and t not in NOT_LANDMARK}
    cells = [[x, y] for y in range(terrain.height) for x in range(terrain.width)
             if terrain.at(x, y) in rare]
    return {"tiles": sorted(rare), "cells": cells,
            "confidence": "HYPOTHESIS",
            "why": "★世界地図で %d 升以下しか無いタイル（⚠ アリアハン (159,192)=tile 10 の 1 例で裏取り）"
                   % LANDMARK_MAX_CELLS}


def arrival_world_cells(rom=None) -> dict:
    """★ROM の arrival_world（CONFIRMED）。⚠ ROM が無ければ空で理由を書く。"""
    rom = pathlib.Path(rom) if rom is not None else ROM
    if not rom.exists():
        return {"cells": [], "why": "⚠ ROM がありません: %s" % rom}
    try:
        from dq3rom import entrances as en
        from dq3rom import profile as dq3

        ident = dq3.load_and_identify(rom)
        tables = en.read_arrival_tables(ident)
    except Exception as err:                                  # noqa: BLE001
        return {"cells": [], "why": "⚠ ROM を読めません: %s" % err}
    cells = set()
    for name, rows in tables.items():
        if "world" not in name:
            continue
        for row in rows:
            if len(row) >= 3:
                cells.add((int(row[1]), int(row[2])))
            elif len(row) == 2:
                cells.add((int(row[0]), int(row[1])))
    return {"cells": sorted([list(c) for c in cells]), "confidence": "CONFIRMED",
            "why": "★ローカルから世界地図へ出たときに降りる升（⚠ 入口そのものではない）"}


def world_warp_cells() -> dict:
    """★★ フィールドの run で避ける升（★2 つの根拠の和）。⚠ どちらも無ければ空。"""
    out = {"cells": [], "landmark": None, "arrival": None}
    try:
        from dq3.knowledge.terrain import TerrainSource

        world = TerrainSource().get(0)
        if world is not None:
            out["landmark"] = landmark_cells(world)
    except Exception as err:                                  # noqa: BLE001
        out["landmark"] = {"cells": [], "why": "⚠ 世界地図を読めません: %s" % err}
    out["arrival"] = arrival_world_cells()
    cells = {tuple(c) for c in (out["landmark"] or {}).get("cells", [])}
    cells |= {tuple(c) for c in (out["arrival"] or {}).get("cells", [])}
    out["cells"] = sorted([list(c) for c in cells])
    return out


def write(root) -> dict:
    """★run の folder に `world_warps.json` を書く。"""
    got = world_warp_cells()
    pathlib.Path(root, "world_warps.json").write_text(
        json.dumps(got, ensure_ascii=False) + "\n", encoding="utf-8")
    return got
