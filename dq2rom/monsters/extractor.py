"""全モンスターぶんの PNG / JSON / 一覧シートを出す（指示書 §6）。

★出力は `output/rom-analysis/<rom_sha1>/monsters/` の下（Git 管理外）。
  **RetroUX 本体のデータは書き換えない**（指示書 §19-9）。
  図鑑へ入れるのは別の明示的な手順にする。

★1枚でも失敗したら止めるのではなく、**残りを続けて最後にまとめて報告**する
  （指示書 18「失敗したマップがあっても他の処理を継続できる」と同じ考え）。
"""

from __future__ import annotations

import collections
import dataclasses
import json
import pathlib

from ..ines import Rom
from ..locator import (
    MonsterGraphicsEntry, locate_monster_graphics_table,
    read_monster_graphics_table,
)
from ..provenance import Confidence
from . import png
from .decoder import DecodeError, decode_monster
from .palette import NesPalette, PaletteError, read_monster_palettes
from .renderer import Rendered, render

SCHEMA_VERSION = "1.0"


@dataclasses.dataclass
class Result:
    monster_id: int
    ok: bool
    reason: str = ""
    rendered: Rendered | None = None
    png_path: pathlib.Path | None = None
    json_path: pathlib.Path | None = None
    meta: dict | None = None


def _entry_json(rom: Rom, entry: MonsterGraphicsEntry, blocks, palettes,
                rendered: Rendered) -> dict:
    """指示書 6.2 の形。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "game_id": "dq2_fc_jp",
        "rom_sha1": rom.sha1,
        "monster_id": entry.monster_id,
        "name": None,                      # 名前は後工程（指示書 6.3）
        "graphic": {
            "width_px": rendered.width,
            "height_px": rendered.height,
            "tile_width": (rendered.width + 7) // 8,
            "tile_height": (rendered.height + 7) // 8,
            "layout": "grid_tiles_over_pixel_tiles",
            "grid_tiles": rendered.grid_tiles,
            "pixel_tiles": rendered.other_tiles,
            "blocks": len(blocks),
            "transparent_color_index": 0,
            "palettes": palettes.to_json(),
            "source": {
                "prg_bank": 1,
                "cpu_address": f"0x{entry.graphics_addr:04X}",
                "rom_offset_start": f"0x{blocks[0].prg_start:05X}",
                "rom_offset_end": f"0x{blocks[-1].prg_end:05X}",
                "bytes_consumed": blocks[-1].prg_end - blocks[0].prg_start,
                "pointer_table_index": entry.monster_id,
                "count": entry.count,
            },
        },
        "confidence": rendered.confidence.value,
        "notes": list(rendered.notes),
        "evidence": [
            {"type": "byte_signature",
             "note": "索引表は5バイト間隔の count 列で特定。候補は1か所のみ"},
            {"type": "boundary_check",
             "note": "展開が消費したバイト数が、索引表の言う次の絵の位置と"
                     "全38枚でぴったり一致する"},
            {"type": "runtime_capture",
             "note": "実機で撮った10枚と、スプライトに隠れていないマスが全部一致"},
        ],
    }


def extract(rom: Rom, out_dir: pathlib.Path, nes: NesPalette,
            scale: int = 1, only: int | None = None) -> list[Result]:
    table = locate_monster_graphics_table(rom)
    entries = read_monster_graphics_table(rom, table.prg_offset)
    targets = [e for e in entries
               if e.in_range and e.monster_id != 0
               and (only is None or e.monster_id == only)]

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Result] = []
    for entry in targets:
        try:
            blocks = decode_monster(rom.prg, entry.graphics_addr, entry.count)
            palettes = read_monster_palettes(rom.prg, entry.palette_addr)
            rendered = render(blocks, palettes, nes)
        except (DecodeError, PaletteError, ValueError) as exc:
            results.append(Result(entry.monster_id, False, str(exc)))
            continue

        stem = f"monster_{entry.monster_id:03d}"
        png_path = png.write(out_dir / f"{stem}.png", rendered.rows, scale)
        meta = _entry_json(rom, entry, blocks, palettes, rendered)
        json_path = out_dir / f"{stem}.json"
        json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        results.append(Result(entry.monster_id, True, rendered=rendered,
                              png_path=png_path, json_path=json_path, meta=meta))

    if results:
        summary = {
            "schema_version": SCHEMA_VERSION,
            "rom_sha1": rom.sha1,
            "palette_source": nes.source,
            "count": sum(1 for r in results if r.ok),
            "failed": [{"monster_id": r.monster_id, "reason": r.reason}
                       for r in results if not r.ok],
            "monsters": [r.meta for r in results if r.ok],
        }
        (out_dir / "monsters.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    return results


# --- 一覧シート（指示書 6.3）------------------------------------------

CELL_PAD = 4
LABEL_H = 7


def _digit_rows(text: str) -> list[list[bool]]:
    """5x7 の極小フォントで数字と16進を描く（外部フォントを使わないため）。"""
    font = {
        "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
        "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
        "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
        "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
        "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
        "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
        "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
        "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
        "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
        "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
        "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
        "B": ("11110", "10001", "11110", "10001", "10001", "10001", "11110"),
        "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
        "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
        "E": ("11111", "10000", "11110", "10000", "10000", "10000", "11111"),
        "F": ("11111", "10000", "11110", "10000", "10000", "10000", "10000"),
        " ": ("00000",) * 7,
    }
    rows = [[] for _ in range(LABEL_H)]
    for ch in text.upper():
        glyph = font.get(ch, font[" "])
        for y in range(LABEL_H):
            rows[y].extend(c == "1" for c in glyph[y])
            rows[y].append(False)
    return rows


def contact_sheet(results: list[Result], path: pathlib.Path,
                  columns: int = 8) -> pathlib.Path:
    """全部を並べた1枚の絵。★ID順に正しく並ぶことを優先（指示書 6.3）。"""
    done = [r for r in results if r.ok and r.rendered]
    if not done:
        raise ValueError("並べる絵がありません")
    cw = max(r.rendered.width for r in done) + CELL_PAD * 2
    ch = max(r.rendered.height for r in done) + CELL_PAD * 2 + LABEL_H + 2
    rows_n = (len(done) + columns - 1) // columns
    width, height = cw * columns, ch * rows_n

    bg = (24, 24, 24, 255)
    canvas = [[bg] * width for _ in range(height)]
    for i, r in enumerate(done):
        cx = (i % columns) * cw
        cy = (i // columns) * ch
        # ラベル（ID を16進で）
        label = _digit_rows(f"{r.monster_id:02X}")
        for y, line in enumerate(label):
            for x, on in enumerate(line):
                if on and cx + 2 + x < width and cy + 1 + y < height:
                    canvas[cy + 1 + y][cx + 2 + x] = (200, 200, 200, 255)
        # 絵（セルの中央下寄せ）
        ox = cx + (cw - r.rendered.width) // 2
        oy = cy + LABEL_H + 2 + CELL_PAD
        for y, line in enumerate(r.rendered.rows):
            for x, px in enumerate(line):
                if px[3] == 0:
                    continue
                yy, xx = oy + y, ox + x
                if 0 <= yy < height and 0 <= xx < width:
                    canvas[yy][xx] = px
    return png.write(path, canvas)


def group_by_picture(rom: Rom) -> dict[int, list[int]]:
    """同じ絵を使う敵をまとめる（色違い）。"""
    table = locate_monster_graphics_table(rom)
    entries = read_monster_graphics_table(rom, table.prg_offset)
    out: dict[int, list[int]] = collections.defaultdict(list)
    for e in entries:
        if e.in_range and e.monster_id != 0:
            out[e.graphics_addr].append(e.monster_id)
    return dict(out)


__all__ = ["Result", "extract", "contact_sheet", "group_by_picture",
           "Confidence", "SCHEMA_VERSION"]
