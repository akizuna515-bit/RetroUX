"""背景CHRからマップを組み立てる（2026-08-02 / マップ指示書）。

★★ **画面キャプチャを正本にしない。** ★★
  ネームテーブル・属性テーブル・CHR・背景パレットから組み直すので、
  OAM スプライト（主人公・NPC）が**構造的に混ざらない**。

    reconstruct.py  PPU の中身 -> 画面の色番号。CHR 半分の見極め
    characters.py   8×8 キャラクタ / 16×16 メタタイル / 倍率別画像
"""

from .characters import (
    SCALES, Character, Metatile, character_at, character_key, character_of,
    chr_hash, metatile_at, metatile_key, metatile_of, palette_signature,
    scale_nearest, write_png,
)
from .rom_assets import MapTiles, RomTileSource
from .reconstruct import (
    COLS, PATTERN_HALF, ROWS, TILE, Capture, attribute_for, choose_pattern_half,
    load_screen, nametable_index, palette_colors, screen_indices, tile_pixels,
)

__all__ = [
    "COLS", "PATTERN_HALF", "ROWS", "SCALES", "TILE", "Capture", "Character",
    "MapTiles", "Metatile", "RomTileSource", "attribute_for", "character_at",
    "character_key", "character_of", "chr_hash", "choose_pattern_half",
    "load_screen", "metatile_at", "metatile_key", "metatile_of",
    "nametable_index", "palette_colors", "scale_nearest", "screen_indices",
    "tile_pixels", "write_png",
]
