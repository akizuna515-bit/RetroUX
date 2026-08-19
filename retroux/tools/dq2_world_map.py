"""世界地図を展開して確かめる（2026-08-02 / 調べるための道具）。

★これは**確認用の道具**です。画面（地図）に出しているのは `world_art.py`。

★出すのは**地形IDの塗り分け**だけです。⚠ 絵と色つきで見たいときは
`research/probes/active/world_metatile_check.py` を使ってください。

## 使い方

    python -m retroux.tools.dq2_world_map
    python -m retroux.tools.dq2_world_map --ascii
"""

from __future__ import annotations

import argparse
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
OUT = PROJECT_ROOT / "work" / "world-map.png"

#: ★地形IDを見分けるための色。⚠ **意味ではありません**
#:   （★「$04 が海」と決めつけない。数が多いだけで名前は付けない）
_WHEEL = ((40, 70, 200), (60, 150, 60), (200, 190, 90), (150, 110, 60),
          (120, 120, 130), (210, 120, 60), (90, 200, 200), (200, 90, 170))
#: ⚠ 読めなかったマス（★0 と混ぜない）
UNREAD_COLOUR = (255, 0, 255, 255)

ASCII_CHARS = " .:-=+*#%@ABCDEFGHIJKLMNOPQRSTU"


def _colour(terrain_id):
    if terrain_id is None:
        return UNREAD_COLOUR             # ⚠ 読めなかった印
    r, g, b = _WHEEL[terrain_id % len(_WHEEL)]
    shade = 1.0 - 0.13 * (terrain_id // len(_WHEEL))
    return (max(0, int(r * shade)), max(0, int(g * shade)),
            max(0, int(b * shade)), 255)


def run(as_ascii: bool = False, scale: int = 2) -> int:
    from ..core.bgmap import world_map as W
    from ..core.bgmap.characters import write_png
    from ..core.bgmap.rom_tiles import load_prg

    if not ROM.exists():
        print(f"✗ ROM がありません: {ROM}")
        return 1
    prg = load_prg(ROM)
    grid = W.decode_grid(prg)
    cov = W.coverage(grid)

    print(f"★世界地図（map ${W.WORLD_MAP_ID:02X}） "
          f"{W.WORLD_SIZE}x{W.WORLD_SIZE}")
    print(f"  ★読めた {cov['read']}/{cov['total']} "
          f"({cov['read'] / cov['total']:.1%})")
    if cov["unread"]:
        print(f"  ⚠ 読めない {cov['unread']} マス"
              "（★最後の行は次の行ポインタが無いので長さを測れません）")
    print(f"  地形ID {len(cov['terrain_ids'])} 種: " + "  ".join(
        f"${i:02X}×{n}" for i, n in
        sorted(cov["terrain_ids"].items(), key=lambda kv: -kv[1])[:8]))

    special = sum(1 for y in range(W.WORLD_SIZE) for x in range(W.WORLD_SIZE)
                  if W.special_region(x, y, grid[y][x]))
    print(f"  ⚠ 特別扱いの範囲に当たるマス {special}"
          "（★$05F8 が不明なので置き換えていません）")

    if as_ascii:
        for y in range(0, W.WORLD_SIZE, 4):
            print("  " + "".join(
                "?" if grid[y][x] is None
                else ASCII_CHARS[grid[y][x] % len(ASCII_CHARS)]
                for x in range(0, W.WORLD_SIZE, 2)))
        return 0

    canvas = [[_colour(grid[y // scale][x // scale])
               for x in range(W.WORLD_SIZE * scale)]
              for y in range(W.WORLD_SIZE * scale)]
    write_png(canvas, OUT)
    print(f"★書きました: {OUT}")
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                   # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="世界地図を展開する（試作）")
    parser.add_argument("--ascii", action="store_true")
    parser.add_argument("--scale", type=int, default=2)
    args = parser.parse_args(argv)
    return run(args.ascii, args.scale)


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
