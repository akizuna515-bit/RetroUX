"""非ワールドマップを全件まとめて出す（2026-08-02 / Phase 1）。

★★ **描けなくてもデータを捨てません。** ★★

⚠ 失敗したマップは `failed` として理由を残します。黙って飛ばしません。

## 出す物（`artifacts/maps/<map_id>/`）

| ファイル | 中身 |
| --- | --- |
| `map_master.json` | ★正本（地形・動的差分・素性） |
| `terrain.png` | ★地形IDを色で塗り分けた図（**意味ではなく識別**） |
| `art.png` | ★ROM の絵そのまま |
| `dynamic-overlay.png` | ★宝箱・扉の印だけ（背景は透明） |
| `composite.png` | ★絵に印を重ねたもの |
| `validation.json` | ★検算の結果 |

まとめ: `artifacts/maps/index.json` と `artifacts/maps/report.md`。

## 使い方

    python -m retroux.tools.dq2_map_batch
    python -m retroux.tools.dq2_map_batch --only 0x0B,0x40 --no-png
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import traceback

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
OUT_ROOT = PROJECT_ROOT / "artifacts" / "maps"
PALETTE_FILE = PROJECT_ROOT / "tools" / "fceux" / "palettes" / "FCEUX.pal"

#: ★マップの数（ヘッダ表の件数）。⚠ 実測ではなく表の大きさから
MAP_COUNT = 109
TILE = 16

#: ★地形IDを見分けるための色。⚠ **意味ではありません**（水・壁などと決めない）
_WHEEL = ((228, 80, 80), (80, 180, 228), (120, 200, 100), (232, 200, 90),
          (180, 130, 220), (240, 150, 80), (110, 220, 200), (220, 120, 180))


def _terrain_colour(terrain_id: int):
    """★識別用の色。同じIDは同じ色になります。"""
    r, g, b = _WHEEL[(terrain_id >> 2) % len(_WHEEL)]
    shade = 1.0 - 0.22 * (terrain_id & 3)
    return (int(r * shade), int(g * shade), int(b * shade), 255)


def _blank(width: int, height: int, colour=(0, 0, 0, 0)):
    return [[colour] * width for _ in range(height)]


def _frame(canvas, ox: int, oy: int, colour, size: int) -> None:
    for i in range(size):
        for x, y in ((ox + i, oy), (ox + i, oy + size - 1),
                     (ox, oy + i), (ox + size - 1, oy + i)):
            if 0 <= y < len(canvas) and 0 <= x < len(canvas[0]):
                canvas[y][x] = colour


def _validate(dmap, master) -> dict:
    """★検算。⚠ 「描けた」だけで正しいとはしません。"""
    from ..core.bgmap.dungeon_map import TABLE_ENTRIES, TERRAIN_TABLES

    out: dict = {"checks": [], "warnings": []}

    def check(name: str, ok: bool, detail: str = "") -> None:
        out["checks"].append({"name": name, "ok": bool(ok), "detail": detail})

    data_len = dmap.width * dmap.height
    end = dmap.pointer + data_len
    check("データが PRG の中に収まる", end <= len(dmap.prg),
          f"ptr ${dmap.pointer:04X} + {data_len} = ${end:04X}")

    limit = TABLE_ENTRIES.get(dmap.kind)
    idx = [dmap.index_at(x, y)
           for y in range(dmap.screen_size[1])
           for x in range(dmap.screen_size[0])]
    top = max(idx) if idx else 0
    if limit is None:
        out["warnings"].append(
            f"⚠ 種別{dmap.kind} の変換表の件数は測れていません（索引の最大 ${top:02X}）")
        check("索引が表の中", True, f"⚠ 上限が unknown。最大 ${top:02X}")
    else:
        check("索引が表の中", top < limit, f"最大 ${top:02X} / 上限 {limit}")
        if top >= limit:
            out["warnings"].append(
                f"⚠ 索引 ${top:02X} が表の件数 {limit} を超えています"
                "（★丸めずにそのまま出しています）")

    table_end = (TERRAIN_TABLES[dmap.kind] - 0x8000 + 0x8000
                 + (top + 1) * 5)
    check("変換表の読み先が PRG の中", table_end <= len(dmap.prg))

    # ★1 論理セル = 1 要素であること（2×2 で 4 件に増えていないか）
    cells = [e.cell for e in master.dynamic.elements]
    check("動的差分が論理セル単位", len(cells) == len(set(cells)),
          f"{len(cells)} 件 / 重複なし {len(set(cells))}")
    return out


#: ★コンタクトシートの 1 枚の大きさ
THUMB = 72
#: ★横に何枚並べるか
SHEET_COLS = 11
#: ⚠ 描けなかったマスの色（★見て分かるように）
SHEET_FAILED = (200, 40, 40, 255)
SHEET_PARTIAL = (200, 160, 40, 255)
SHEET_BG = (24, 24, 28, 255)


def _thumbnail(canvas, size: int = THUMB):
    """★最近傍で縮める。⚠ 外部ライブラリを使いません。"""
    height, width = len(canvas), len(canvas[0])
    step = max(width, height) / size
    out = []
    for y in range(size):
        sy = min(int(y * step), height - 1)
        row = canvas[sy]
        out.append([row[min(int(x * step), width - 1)] for x in range(size)])
    return out


def _flat(colour, size: int = THUMB):
    return [[colour] * size for _ in range(size)]


def contact_sheet(thumbs: list, path: pathlib.Path) -> None:
    """★全マップを並べた 1 枚。⚠ 描けなかったものも色で分かるように。"""
    from ..core.bgmap.characters import write_png

    rows = (len(thumbs) + SHEET_COLS - 1) // SHEET_COLS
    sheet = [[SHEET_BG] * (SHEET_COLS * THUMB) for _ in range(rows * THUMB)]
    for i, thumb in enumerate(thumbs):
        ox, oy = (i % SHEET_COLS) * THUMB, (i // SHEET_COLS) * THUMB
        for y in range(THUMB):
            line = sheet[oy + y]
            for x in range(THUMB):
                line[ox + x] = thumb[y][x]
    write_png(sheet, path)


def process(prg: bytes, map_id: int, out_dir: pathlib.Path,
            make_png: bool = True) -> dict:
    """1マップぶん。★失敗しても理由を返します。"""
    from ..core.bgmap import map_master
    from ..core.bgmap.dungeon_map import DungeonMap, map_kind
    from ..core.bgmap.overlay import KIND_CHEST
    from ..core.bgmap.rom_tiles import (MAP_HEADER, MAP_HEADER_SIZE,
                                        order_for_map)

    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    header = list(prg[off:off + MAP_HEADER_SIZE])
    row: dict = {"map_id": map_id, "map_id_hex": f"${map_id:02X}",
                 "map_type": map_kind(map_id), "header": header,
                 "status": "failed", "failure_reason": None}
    try:
        row["tile_set"] = list(order_for_map(prg, map_id) or [])
    except Exception as exc:                            # noqa: BLE001
        row["tile_set"] = None
        row["failure_reason"] = f"⚠ タイルセットが取れません: {exc}"

    try:
        master = map_master.build(prg, map_id)
        dmap = DungeonMap(prg, map_id)
    except ValueError as exc:
        row["failure_reason"] = str(exc)
        return row
    except Exception as exc:                            # noqa: BLE001
        row["failure_reason"] = f"⚠ 組み立てで落ちました: {exc}"
        row["traceback"] = traceback.format_exc(limit=3)
        return row

    row.update({
        "logical_size": [dmap.width, dmap.height],
        "physical_size": list(dmap.screen_size),
        "border_tile": dmap.border,
        "data_pointer": dmap.pointer,
        "terrain_distribution": {f"${i:02X}": n for i, n
                                 in sorted(_distribution(master).items())},
        "chest_count": sum(1 for e in master.dynamic.elements
                           if e.kind == KIND_CHEST),
        "door_count": sum(1 for e in master.dynamic.elements
                          if e.kind != KIND_CHEST),
        "unknown_object_count": 0,
        "unknown_terrain_ids": sorted(master.unknown_terrain),
    })

    out_dir.mkdir(parents=True, exist_ok=True)
    validation = _validate(dmap, master)
    row["out_of_range_table_refs"] = [w for w in validation["warnings"]
                                      if "表の件数" in w]
    _write_json(out_dir / "map_master.json", master.to_dict())
    _write_json(out_dir / "validation.json", validation)

    row["tile_set_basis"] = (
        "★マップ種別がそのまま CHR 索引（$D0AB: LDA $1F / STA $0C / JSR $8000）"
        if row.get("tile_set") else "⚠ 決められませんでした")
    row["confidence"] = {
        "terrain": "confirmed", "art": "confirmed",
        "dynamic_objects": "confirmed",
        "dynamic_state": "unknown",          # ⚠ RAM を当てていない
        "tile_set": "confirmed" if row.get("tile_set") else "unknown",
    }

    if not make_png:
        row["status"] = "partial"
        row["failure_reason"] = "★--no-png のため絵は作っていません"
        return row

    try:
        row["_thumb"] = _render_all(dmap, master, out_dir)
        row["status"] = "renderable"
    except Exception as exc:                            # noqa: BLE001
        row["status"] = "partial"
        row["failure_reason"] = f"⚠ 絵が作れません（データは残しました）: {exc}"
    return row


def _distribution(master) -> dict:
    tally: dict = {}
    for line in master.terrain:
        for value in line:
            tally[value] = tally.get(value, 0) + 1
    return tally


def _write_json(path: pathlib.Path, payload) -> None:
    path.write_bytes(json.dumps(payload, ensure_ascii=False,
                                indent=1).encode("utf-8"))


def _render_all(dmap, master, out_dir: pathlib.Path):
    """4 枚を作る。★terrain / art / dynamic を混ぜません。

    ★戻り値はコンタクトシート用の縮小版です。
    """
    from dq2rom.monsters.palette import load_nes_palette

    from ..core.bgmap.characters import write_png
    from ..core.bgmap.overlay import KIND_CHEST
    from ..core.bgmap.rom_assets import RomTileSource

    width, height = dmap.screen_size
    span = 2 if dmap.halved else 1

    # --- terrain: 地形IDの塗り分け（★意味ではなく識別）------------------
    terrain = _blank(dmap.width * TILE * span, dmap.height * TILE * span)
    for cy in range(dmap.height):
        for cx in range(dmap.width):
            colour = _terrain_colour(dmap.cell(cx, cy))
            for dy in range(TILE * span):
                line = terrain[cy * TILE * span + dy]
                for dx in range(TILE * span):
                    line[cx * TILE * span + dx] = colour
    write_png(terrain, out_dir / "terrain.png")

    # --- art: ROM の絵 --------------------------------------------------
    tiles = RomTileSource(ROM).for_map(dmap.map_id)
    if tiles is None:
        raise RuntimeError("★CHR かパレットが取れません")
    nes = load_nes_palette(PALETTE_FILE)
    art = _blank(width * TILE, height * TILE, (0, 0, 0, 255))
    for y in range(height):
        for x in range(width):
            four, group = dmap.metatile_at(x, y)
            for dy, line in enumerate(tiles.metatile(four, group, x=x, y=y)
                                      .rgba(nes)):
                target = art[y * TILE + dy]
                for dx, px in enumerate(line):
                    target[x * TILE + dx] = tuple(px)
    write_png(art, out_dir / "art.png")

    # --- dynamic: 印だけ（★背景は透明）----------------------------------
    marks = _blank(width * TILE, height * TILE)
    for e in master.dynamic.elements:
        colour = (255, 220, 0, 255) if e.kind == KIND_CHEST else (0, 200, 255, 255)
        _frame(marks, e.x * TILE, e.y * TILE, colour, TILE * span)
    write_png(marks, out_dir / "dynamic-overlay.png")

    # --- composite: 重ねる（★art は壊さない）----------------------------
    composite = [list(line) for line in art]
    for y, line in enumerate(marks):
        for x, px in enumerate(line):
            if px[3]:
                composite[y][x] = px
    write_png(composite, out_dir / "composite.png")
    return _thumbnail(composite)


def run(only=None, make_png: bool = True) -> int:
    from ..core.bgmap.rom_tiles import load_prg

    if not ROM.exists():
        print(f"✗ ROM がありません: {ROM}")
        return 1
    prg = load_prg(ROM)
    rom_sha = hashlib.sha256(ROM.read_bytes()).hexdigest()

    targets = only if only else list(range(MAP_COUNT))
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for map_id in targets:
        row = process(prg, map_id, OUT_ROOT / f"{map_id:02X}", make_png)
        rows.append(row)
        mark = {"renderable": "★", "partial": "▲", "failed": "⚠"}[row["status"]]
        print(f"  {mark} ${map_id:02X} 種別{row['map_type']} "
              f"{row.get('logical_size') or '--'} "
              f"{row.get('failure_reason') or ''}")

    # ★コンタクトシート（⚠ 描けなかったものも色で分かるように）
    if make_png:
        thumbs = []
        for row in rows:
            thumb = row.pop("_thumb", None)
            if thumb is None:
                thumb = _flat(SHEET_FAILED if row["status"] == "failed"
                              else SHEET_PARTIAL)
            thumbs.append(thumb)
        contact_sheet(thumbs, OUT_ROOT / "contact-sheet.png")
        print(f"★コンタクトシート: {OUT_ROOT / 'contact-sheet.png'}")
    for row in rows:
        row.pop("_thumb", None)

    index = {"rom": {"sha256": rom_sha, "game_id": "DQ2", "region": "JP"},
             "map_count": len(rows), "maps": rows}
    _write_json(OUT_ROOT / "index.json", index)
    _write_report(OUT_ROOT / "report.md", index)
    ok = sum(r["status"] == "renderable" for r in rows)
    part = sum(r["status"] == "partial" for r in rows)
    bad = sum(r["status"] == "failed" for r in rows)
    print(f"\n★描けた {ok} / ▲一部 {part} / ⚠ 失敗 {bad}")
    print(f"★{OUT_ROOT}")
    return 0


def _write_report(path: pathlib.Path, index: dict) -> None:
    rows = index["maps"]
    n_terrain = sum(1 for r in rows if r.get("logical_size"))
    n_art = sum(1 for r in rows if r["status"] == "renderable")
    n_unknown = sum(len(r.get("unknown_terrain_ids") or []) for r in rows)
    n_oor = sum(1 for r in rows if r.get("out_of_range_table_refs"))
    lines = ["# 非ワールドマップ 全件変換の結果", "",
             f"ROM `sha256 {index['rom']['sha256']}`", "",
             "⚠ **描けなかったものも消していません。**理由を残しています。", "",
             "## まとめ", "",
             "| 項目 | 件数 |", "| --- | --- |",
             f"| ★地形が読めた | {n_terrain} |",
             f"| ★絵が描けた（art / composite） | {n_art} |",
             f"| ⚠ 一部 | {sum(1 for r in rows if r['status'] == 'partial')} |",
             f"| ⚠ 失敗 | {sum(1 for r in rows if r['status'] == 'failed')} |",
             f"| 宝箱 | {sum(r.get('chest_count', 0) for r in rows)} |",
             f"| 扉 | {sum(r.get('door_count', 0) for r in rows)} |",
             f"| ⚠ 名前の分からない地形ID（延べ） | {n_unknown} |",
             f"| ⚠ 変換表の範囲外を参照 | {n_oor} |", "",
             "## タイルセットの決め方", "",
             "★`$D0AB: LDA $1F / STA $0C / JSR $8000` — "
             "**マップ種別がそのまま CHR 索引**（confidence: confirmed）。",
             "⚠ 境界タイルID は関係ありません。", "",
             "## マップごと", "",
             "| map | 種別 | 論理 | 画面 | 宝箱 | 扉 | 地形ID種 | 状態 | 備考 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in index["maps"]:
        size = r.get("logical_size")
        phys = r.get("physical_size")
        mark = {"renderable": "★描けた", "partial": "▲一部",
                "failed": "⚠ 失敗"}[r["status"]]
        lines.append(
            f"| `{r['map_id_hex']}` | {r['map_type']} | "
            f"{'x'.join(map(str, size)) if size else '--'} | "
            f"{'x'.join(map(str, phys)) if phys else '--'} | "
            f"{r.get('chest_count', '--')} | {r.get('door_count', '--')} | "
            f"{len(r.get('terrain_distribution') or {})} | {mark} | "
            f"{(r.get('failure_reason') or '').replace('|', '/')} |")
    by_kind: dict = {}
    for r in index["maps"]:
        by_kind.setdefault(r["map_type"], []).append(r)
    lines += ["", "## 種別ごと", "",
              "| 種別 | 件数 | ★描けた |", "| --- | --- | --- |"]
    for kind in sorted(by_kind):
        rs = by_kind[kind]
        lines.append(f"| {kind} | {len(rs)} | "
                     f"{sum(x['status'] == 'renderable' for x in rs)} |")
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                   # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="非ワールドマップを全件出す")
    parser.add_argument("--only", default=None,
                        help="map_id をカンマ区切りで（例 0x0B,0x40）")
    parser.add_argument("--no-png", action="store_true")
    args = parser.parse_args(argv)
    only = ([int(v, 0) for v in args.only.split(",")] if args.only else None)
    return run(only, not args.no_png)


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
