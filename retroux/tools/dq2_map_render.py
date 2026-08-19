"""ROM だけでマップ全体の絵を作る（2026-08-02 / 依頼者の指示 Phase B）。

★★ **層を分けて描けます。** ★★

| 層 | 出すもの |
| --- | --- |
| `base` | ROM の地形だけ（★宝箱・扉も地形のまま） |
| `dynamic` | 宝箱・扉に印を付ける（★状態が分かれば反映） |

## 使い方

    python -m retroux.tools.dq2_map_render --map 0x40
    python -m retroux.tools.dq2_map_render --map 0x3D --layer dynamic

⚠ ROM が要ります（`work/rom/DQ2_J.nes`）。**同梱しません**。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
OUT_DIR = PROJECT_ROOT / "work"

#: メタタイル1枚の大きさ
TILE = 16


def render(map_id: int, layer: str = "base", out=None):
    """1マップぶんの PNG を作る。★戻り値は書いた場所。"""
    # ⚠ PIL も PySide6 も要りません。★プロジェクト既存の書き出しを使います。
    from dq2rom.monsters.palette import load_nes_palette

    from ..core.bgmap.characters import write_png
    from ..core.bgmap.dungeon_map import DungeonMap
    from ..core.bgmap.overlay import KIND_CHEST, build_dynamic
    from ..core.bgmap.rom_assets import RomTileSource
    from ..core.bgmap.rom_tiles import load_prg

    palette_file = PROJECT_ROOT / "tools" / "fceux" / "palettes" / "FCEUX.pal"
    if not palette_file.exists():
        raise SystemExit(f"⚠ NES パレットがありません: {palette_file}")
    nes_palette = load_nes_palette(palette_file)

    prg = load_prg(ROM)
    dmap = DungeonMap(prg, map_id)
    tiles = RomTileSource(ROM).for_map(map_id)
    if tiles is None:
        raise SystemExit(f"⚠ map ${map_id:02X} の絵の材料が取れません")

    width, height = dmap.screen_size
    canvas = [[(0, 0, 0, 255)] * (width * TILE) for _ in range(height * TILE)]
    for y in range(height):
        for x in range(width):
            four, group = dmap.metatile_at(x, y)
            rows = tiles.metatile(four, group, x=x, y=y).rgba(nes_palette)
            for dy, row in enumerate(rows):
                line = canvas[y * TILE + dy]
                for dx, px in enumerate(row):
                    line[x * TILE + dx] = tuple(px)

    overlay = build_dynamic(dmap)
    if layer == "dynamic":
        for e in overlay.elements:
            colour = (255, 220, 0, 255) if e.kind == KIND_CHEST \
                else (0, 200, 255, 255)
            # ★要素は論理セル単位。2×2 マスぶんを1つの枠で囲む
            _frame(canvas, e.x * TILE, e.y * TILE, colour, span=2)

    out = pathlib.Path(out) if out else OUT_DIR / f"map{map_id:02X}-{layer}.png"
    write_png(canvas, out)
    return out, dmap, overlay


def _frame(canvas, ox: int, oy: int, colour, span: int = 1) -> None:
    """★マスを枠で囲む（動的差分の印）。`span` はマス数。"""
    size = TILE * span
    for i in range(size):
        for x, y in ((ox + i, oy), (ox + i, oy + size - 1),
                     (ox, oy + i), (ox + size - 1, oy + i)):
            if 0 <= y < len(canvas) and 0 <= x < len(canvas[0]):
                canvas[y][x] = colour


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="ROM だけでマップを描く")
    parser.add_argument("--map", required=True,
                        help="map_id（16進なら 0x40）")
    parser.add_argument("--layer", default="base", choices=("base", "dynamic"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    map_id = int(args.map, 0)
    out, dmap, overlay = render(map_id, args.layer, args.out)
    print(f"★map ${map_id:02X}  {dmap.width}x{dmap.height} セル"
          f" / 画面 {dmap.screen_size[0]}x{dmap.screen_size[1]} マス")
    print(f"  {overlay.summary()}")
    print(f"★書きました: {out}")
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
