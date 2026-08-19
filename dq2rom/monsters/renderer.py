"""展開したタイルを並べて絵にする。

★重ね順: **画素で置くタイル（bit6=0）が下、格子のタイル（bit6=1）が上**。
  格子のほうが絵の本体で、実機の撮影と完全一致している側。

★パレット番号 0 は**透明**にする（指示書 6.1「背景透明」）。
  戦闘画面では 0 番が背景色（黒）として見えているが、
  図鑑に載せるときは透明のほうが使いやすい。
"""

from __future__ import annotations

import dataclasses

from ..provenance import Confidence
from .decoder import Block
from .palette import MonsterPalettes, NesPalette

Pixel = tuple[int, int, int, int]
TRANSPARENT: Pixel = (0, 0, 0, 0)


@dataclasses.dataclass(frozen=True)
class Rendered:
    rows: list[list[Pixel]]
    width: int
    height: int
    origin_x: int               # 元の座標系でのはみ出し量
    origin_y: int
    grid_tiles: int
    other_tiles: int
    skipped: int                # パレットが無くて描けなかったタイル
    confidence: Confidence
    notes: tuple[str, ...]


def tile_indices(tile: bytes) -> list[list[int]]:
    """NES の 2bpp プレーナ 16バイト → 8x8 のパレット番号（0..3）。"""
    out = []
    for y in range(8):
        low, high = tile[y], tile[y + 8]
        out.append([(((high >> (7 - x)) & 1) << 1) | ((low >> (7 - x)) & 1)
                    for x in range(8)])
    return out


def render(blocks: list[Block], palettes: MonsterPalettes,
           nes: NesPalette) -> Rendered:
    """1体ぶんを RGBA にする。"""
    placements = [(b, p) for b in blocks for p in b.placements]
    if not placements:
        raise ValueError("置くタイルが1枚もありません")

    xs = [p.x for _b, p in placements]
    ys = [p.y for _b, p in placements]
    x0, y0 = min(xs), min(ys)
    width = max(xs) + 8 - x0
    height = max(ys) + 8 - y0

    rows: list[list[Pixel]] = [[TRANSPARENT] * width for _ in range(height)]

    grid = other = skipped = 0
    # ★下のレイヤーから描く
    for on_grid in (False, True):
        for block, place in placements:
            if place.on_grid != on_grid:
                continue
            colors = palettes.for_layer(on_grid)
            if colors is None:
                # ★パレットが宣言されていない。**推測で色を作らない**
                skipped += 1
                continue
            px = tile_indices(block.variants[place.variant])
            for dy in range(8):
                for dx in range(8):
                    index = px[dy][dx]
                    if index == 0:
                        continue            # 透明
                    r, g, b = nes.rgb(colors[index - 1])
                    rows[place.y - y0 + dy][place.x - x0 + dx] = (r, g, b, 255)
            if on_grid:
                grid += 1
            else:
                other += 1

    notes = []
    confidence = Confidence.CONFIRMED
    if other:
        confidence = Confidence.PROBABLE
        notes.append(
            "画素で置くタイル（bit6=0）の位置は撮影3枚から割り出した式で、"
            "格子のタイルほど確かではない")
    if palettes.ambiguous:
        confidence = Confidence.PROBABLE
        notes.append(
            f"パレットが複数ある（低{len(palettes.low)} 高{len(palettes.high)}）。"
            "どのタイルがどれを使うかは未解明なので先頭を使った")
    if skipped:
        confidence = Confidence.TENTATIVE
        notes.append(f"パレットが無いレイヤーのタイルを {skipped} 枚描けなかった")

    return Rendered(rows=rows, width=width, height=height,
                    origin_x=x0, origin_y=y0,
                    grid_tiles=grid, other_tiles=other, skipped=skipped,
                    confidence=confidence, notes=tuple(notes))
