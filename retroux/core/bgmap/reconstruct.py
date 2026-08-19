"""PPU の中身から背景を組み直す（2026-08-02 / マップ指示書 Phase 4・§7）。

★★ **画面キャプチャを正本にしない。** ★★

  ネームテーブル・属性テーブル・CHR・背景パレットから作り直します。
  ⚠ こうすると OAM スプライト（主人公・NPC・カーソル）が
    **構造的に混ざりません**（指示書 §7.2・§2.4）。
  ★FCEUX の画面は「合っているか」の照合にだけ使います。

## NES の背景の組み立て（実装の根拠）

    ネームテーブル : 32×30 の格子。各マスが**タイルID**（0-255）
    CHR           : タイルID × 16 バイト。前半8が下位ビット、後半8が上位
                    → 1画素あたり **0..3** の番号
    属性テーブル   : 1バイトが **4×4 タイル（32×32 画素）**を受け持つ。
                    その中を 2×2 タイルずつ4つに分け、各2ビットで
                    **どのパレット組（0-3）を使うか**を決める
    背景パレット   : $3F00-$3F0F。4色 × 4組。
                    ⚠ **各組の色0は共通の背景色**（$3F00）を使う

⚠⚠ **背景がどちらの CHR 半分を使うかは Lua から読めない**
  （PPUCTRL のビット4）。★両方で組んで、画面と合う方を採ります。
"""

from __future__ import annotations

import dataclasses
import pathlib

#: 1タイルの大きさ（画素）
TILE = 8
#: 画面のタイル数
COLS, ROWS = 32, 30
#: CHR の半分（背景はどちらか一方を使う）
PATTERN_HALF = 0x1000


def _unhex(text: str) -> bytes:
    return bytes.fromhex(text.strip())


@dataclasses.dataclass(frozen=True)
class Capture:
    """1回ぶんの採取（`bg_capture_probe.lua` が書いたもの）。"""

    slot: int
    map_id: int
    map_x: int
    map_y: int
    scroll_x: int
    scroll_y: int
    state: str
    nametable_left: bytes
    nametable_right: bytes
    attr_left: bytes
    attr_right: bytes
    palette: bytes
    chr_data: bytes

    @classmethod
    def load(cls, path) -> "Capture":
        raw: dict[str, str] = {}
        for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                raw[key] = value
        return cls(
            slot=int(raw["slot"]), map_id=int(raw["map_id"]),
            map_x=int(raw["map_x"]), map_y=int(raw["map_y"]),
            scroll_x=int(raw["scroll_x"]), scroll_y=int(raw["scroll_y"]),
            state=raw["state"],
            nametable_left=_unhex(raw["nametable_left"]),
            nametable_right=_unhex(raw["nametable_right"]),
            attr_left=_unhex(raw["attr_left"]),
            attr_right=_unhex(raw["attr_right"]),
            palette=_unhex(raw["palette"]),
            chr_data=_unhex(raw["chr"]),
        )


def tile_pixels(chr_data: bytes, tile_id: int, half: int = 0) -> list[list[int]]:
    """タイル1枚を 8×8 の **0..3 の番号**にする。

    ⚠ 色ではありません。パレットを当てる前の段階です。
    ★0 は「そのパレット組の色0」＝共通の背景色になります。
    """
    base = half + tile_id * 16
    out = []
    for y in range(TILE):
        lo = chr_data[base + y] if base + y < len(chr_data) else 0
        hi = chr_data[base + y + 8] if base + y + 8 < len(chr_data) else 0
        row = []
        for x in range(TILE):
            bit = 7 - x
            row.append(((lo >> bit) & 1) | (((hi >> bit) & 1) << 1))
        out.append(row)
    return out


def attribute_for(attr: bytes, col: int, row: int) -> int:
    """そのタイルが使う**パレット組**（0-3）を返す。

    ⚠ 1バイトが 4×4 タイルを受け持ち、その中を 2×2 タイルずつ4つに分ける。
      ビットの並びは 下位から 左上・右上・左下・右下。
    """
    index = (row // 4) * 8 + (col // 4)
    if index >= len(attr):
        return 0
    byte = attr[index]
    quadrant = ((row % 4) // 2) * 2 + ((col % 4) // 2)
    return (byte >> (quadrant * 2)) & 0x3


def palette_colors(palette: bytes, group: int) -> tuple[int, int, int, int]:
    """パレット組の4色を **NES の色番号**で返す。

    ⚠ **各組の色0は共通の背景色**（`$3F00`）。組ごとの $3Fx0 ではない。
      ここを間違えると、透明部分だけ色が変わって見える。
    """
    base = group * 4
    universal = palette[0] if palette else 0x0F
    return (
        universal,
        palette[base + 1] if base + 1 < len(palette) else 0x0F,
        palette[base + 2] if base + 2 < len(palette) else 0x0F,
        palette[base + 3] if base + 3 < len(palette) else 0x0F,
    )


def nametable_index(col: int, row: int, scroll_x: int, scroll_y: int):
    """画面の (col,row) が、どちらのネームテーブルのどこから来るか。

    ★2026-08-01 の実測: ネームテーブル2枚は**左右に並ぶ 64 列**
      （`$2000 == $2800` / `$2400 == $2C00` ＝ 垂直ミラーリング）。
    ⚠ たては1枚の中で 30 行を巡回する。
    """
    c64 = (col + scroll_x // TILE) % (COLS * 2)
    nr = (row + scroll_y // TILE) % ROWS
    return ("left" if c64 < COLS else "right"), (c64 % COLS), nr


def screen_indices(cap: Capture, half: int = 0) -> list[list[int]]:
    """画面 256×240 を **NES の色番号**の格子にする。

    ⚠ ここではまだ RGB にしません（パレットファイルが要るため）。
    """
    out = [[0] * (COLS * TILE) for _ in range(ROWS * TILE)]
    for row in range(ROWS):
        for col in range(COLS):
            side, nc, nr = nametable_index(col, row, cap.scroll_x, cap.scroll_y)
            if side == "left":
                tile_id = cap.nametable_left[nr * COLS + nc]
                group = attribute_for(cap.attr_left, nc, nr)
            else:
                tile_id = cap.nametable_right[nr * COLS + nc]
                group = attribute_for(cap.attr_right, nc, nr)
            colors = palette_colors(cap.palette, group)
            pixels = tile_pixels(cap.chr_data, tile_id, half)
            for y in range(TILE):
                dst = out[row * TILE + y]
                src = pixels[y]
                for x in range(TILE):
                    dst[col * TILE + x] = colors[src[x]]
    return out


def choose_pattern_half(cap: Capture, screen_rgb, nes_palette,
                        step: int = 2) -> tuple[int, float, float]:
    """背景が使う CHR の半分を**画面と照らして**決める。

    ⚠⚠ PPUCTRL のビット4は Lua から読めない。★推測せず、両方試す。

    戻り値は `(選んだ半分, その一致率, もう片方の一致率)`。
    """
    scores = {}
    for half in (0, PATTERN_HALF):
        indices = screen_indices(cap, half)
        scores[half] = _match_rate(indices, screen_rgb, nes_palette, step)
    best = max(scores, key=lambda h: scores[h])
    other = PATTERN_HALF if best == 0 else 0
    return best, scores[best], scores[other]


def _match_rate(indices, screen_rgb, nes_palette, step: int) -> float:
    """再構成した色と、画面の色がどれだけ一致するか。

    ⚠ スプライトが乗っている画素は**必ず食い違う**。それでよい。
      ★スプライトが混ざっていないことの裏返しでもある。
    """
    if not screen_rgb:
        return 0.0
    height = len(screen_rgb)
    width = len(screen_rgb[0]) if height else 0
    hit = total = 0
    for y in range(height):
        for x in range(width):
            index = indices[y * step][x * step]
            want = nes_palette.rgb(index & 0x3F)
            got = screen_rgb[y][x]
            total += 1
            # ⚠ 完全一致は求めない。FCEUX の画面は引き伸ばされていることがある
            if all(abs(a - b) <= 24 for a, b in zip(want, got)):
                hit += 1
    return hit / total if total else 0.0


def load_screen(path) -> list[list[tuple[int, int, int]]]:
    """`bg_capture_probe.lua` が書いた画面の色を読む。"""
    lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    head: dict[str, int] = {}
    body_from = 0
    for i, line in enumerate(lines):
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            head[key] = int(value)
        else:
            body_from = i
            break
    else:
        body_from = len(lines)
    rows = []
    for line in lines[body_from:]:
        line = line.strip()
        if not line:
            continue
        rows.append([(int(line[i:i + 2], 16), int(line[i + 2:i + 4], 16),
                      int(line[i + 4:i + 6], 16))
                     for i in range(0, len(line), 6)])
    return rows
