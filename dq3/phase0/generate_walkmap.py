"""世界地図の「通行できる／できない」を Lua へ渡す（RX3-0015 の足場 / 2026-08-25）。

★★ ねらい ★★

依頼者の案「ランダムウォークではなく、草原を選んで歩く」。
⚠ でたらめに歩くと海や山にぶつかって進まない。
★世界地図は ROM から復号済みで、collision も出せるので、**歩ける方向が事前に分かる**。

## ⚠ ここで使う仮説

    collision の bit7 が立っている  →  通行できない

⚠ これは ROM のコードから**そう見える**だけで、裏が取れていない（`RX3-0010`）。
★だからこの道具は「予測」を出し、probe 側が**実際に歩けたかを突き合わせる**。
つまり歩かせること自体が、仮説の検証になる。

## 妥当性（作った時点で確かめたこと）

- 通行できると予測されるマスは **31%**（★残りは海と山。DQ3 の世界の見た目と合う）
- ⚠ セーブステート 4 つで、**プレイヤーが立っているマスは全部「通行可」**と予測された
"""

from __future__ import annotations

import pathlib

from dq3 import paths as P3
from dq3rom import collision as col
from dq3rom import profile as dq3
from dq3rom import world_map as wm

ROOT = pathlib.Path(__file__).resolve().parents[2]
#: ★生成物の置き場（⚠ **write_root 側** / RX3-0466 / 2026-09-29）。
#   ⚠⚠ 以前は `ROOT / "work" / "generated" / ...` で program 側に書いていた。
OUT = P3.lazy_generated("dq3_walkmap.lua")
NEWLINE = chr(10)

#: 通行できないとみなすビット。⚠ `RX3-0010` で裏を取るまでは仮説
BLOCKED_BIT = 0x80


def build(rom: pathlib.Path) -> dict:
    ident = dq3.load_and_identify(rom)
    world = wm.decode(ident, "world_main")
    table = col.table_for(ident, 0, 0xFFFF)
    blocked = {i for i, v in enumerate(table) if v & BLOCKED_BIT}
    rows = [(r.tiles if hasattr(r, "tiles") else r) for r in world.rows]
    height = len(rows)
    width = len(rows[0])
    # ★1 マス 1 文字。'.' 歩ける / '#' 歩けない
    cells = "".join("#" if t in blocked else "."
                    for row in rows for t in row)
    return {"width": width, "height": height, "cells": cells,
            "blocked_tiles": sorted(blocked)}


def write_lua(data: dict, out: pathlib.Path | P3.LazyPath = OUT) -> pathlib.Path:
    # ⚠ 既定の `OUT` は `LazyPath`（★使う瞬間に書き先を引き直す / RX3-0466）
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "-- 自動生成ファイル。直接編集しないこと。" + NEWLINE
        + "-- 生成: python -m dq3.phase0.generate_walkmap" + NEWLINE
        + "--" + NEWLINE
        + "-- ★世界地図の「歩ける（.）／歩けない（#）」。⚠ collision の bit7 による**予測**。" + NEWLINE
        + f"local W, H = {data['width']}, {data['height']}" + NEWLINE
        + f'local CELLS = "{data["cells"]}"' + NEWLINE
        + "return {" + NEWLINE
        + "  width = W, height = H," + NEWLINE
        + "  -- ⚠ 範囲外は「歩けない」を返す（★推測で通さない）" + NEWLINE
        + "  passable = function(x, y)" + NEWLINE
        + "    if x < 0 or y < 0 or x >= W or y >= H then return false end" + NEWLINE
        + '    return CELLS:sub(y * W + x + 1, y * W + x + 1) == "."' + NEWLINE
        + "  end," + NEWLINE
        + "}" + NEWLINE,
        encoding="utf-8")
    return out


def main() -> int:
    # ⚠ 解決は `dq3/paths.py::rom()` の 1 本（RX3-0467）
    data = build(P3.rom_or_legacy())
    path = write_lua(data)
    ok = data["cells"].count(".")
    total = data["width"] * data["height"]
    print(f"→ {path}")
    print(f"  ★歩けると予測: {ok}/{total} = {ok / total:.1%}")
    print(f"  ⚠ 歩けないタイル: {data['blocked_tiles']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
