"""実機の画面を PNG に起こす（2026-08-25）。

## ★★ なぜ道具にするのか

2026-08-25、Auto 戦闘 v0 が「9,000 フレーム 1 マスも動かない」で詰まった。
⚠ ログをいくら眺めても分からなかったものが、★**画面を 1 枚描いたら 1 分で分かった**
（コマンド窓が開きっぱなしだった）。

★依頼者が居なくても実機の画面を確かめられる。**行き詰まったらまずこれ**。

## 材料

| どこから | 何が要るか |
| --- | --- |
| セーブステート | `NTAR`（2048）/ `CHRR`（8192）/ `PRAM`（32） |
| probe の書き出し | 同じ 3 つを 16 進で並べたもの |

⚠ DQ3 は CHR-RAM なので、**字形も背景も CHR-RAM の中にある**。
★だから ROM だけでは描けない。実行中の状態が要る。

## ⚠ 分かっていないこと

- 背景がどちらのパターンテーブルを使うかは、★`PPUCTRL` を見れば分かるはずだが
  未確認。いまは **1 側（`$1000`）**を既定にしている（文字が `0x100` 起点なので）
- ファミコンの色は**近似値**。⚠ 実機・エミュレータごとに少し違う
"""

from __future__ import annotations

import pathlib
import struct
import zlib

#: 画面の升目
COLUMNS, ROWS = 32, 30
#: 1 面ぶんのバイト数（升目 960 ＋ 属性 64）
NAMETABLE_SIZE = 1024
#: 属性表の位置
ATTRIBUTE_AT = 960
#: 背景のパターンテーブル。★DQ3 は 1 側（文字が 0x100 起点）
PATTERN_TABLE = 0x1000

#: ファミコンの色（★近似値。⚠ 実機と完全には一致しない）
NES_PALETTE = (
    (0x66, 0x66, 0x66), (0x00, 0x2A, 0x88), (0x14, 0x12, 0xA7), (0x3B, 0x00, 0xA4),
    (0x5C, 0x00, 0x7E), (0x6E, 0x00, 0x40), (0x6C, 0x06, 0x00), (0x56, 0x1D, 0x00),
    (0x33, 0x35, 0x00), (0x0B, 0x48, 0x00), (0x00, 0x52, 0x00), (0x00, 0x4F, 0x08),
    (0x00, 0x40, 0x4D), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00),
    (0xAD, 0xAD, 0xAD), (0x15, 0x5F, 0xD9), (0x42, 0x40, 0xFF), (0x75, 0x27, 0xFE),
    (0xA0, 0x1A, 0xCC), (0xB7, 0x1E, 0x7B), (0xB5, 0x31, 0x20), (0x99, 0x4E, 0x00),
    (0x6B, 0x6D, 0x00), (0x38, 0x87, 0x00), (0x0C, 0x93, 0x00), (0x00, 0x8F, 0x32),
    (0x00, 0x7C, 0x8D), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00),
    (0xFF, 0xFE, 0xFF), (0x64, 0xB0, 0xFF), (0x92, 0x90, 0xFF), (0xC6, 0x76, 0xFF),
    (0xF3, 0x6A, 0xFF), (0xFE, 0x6E, 0xCC), (0xFE, 0x81, 0x70), (0xEA, 0x9E, 0x22),
    (0xBC, 0xBE, 0x00), (0x88, 0xD8, 0x00), (0x5C, 0xE4, 0x30), (0x45, 0xE0, 0x82),
    (0x48, 0xCD, 0xDE), (0x4F, 0x4F, 0x4F), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00),
    (0xFF, 0xFE, 0xFF), (0xC0, 0xDF, 0xFF), (0xD3, 0xD2, 0xFF), (0xE8, 0xC8, 0xFF),
    (0xFB, 0xC2, 0xFF), (0xFE, 0xC4, 0xEA), (0xFE, 0xCC, 0xC5), (0xF7, 0xD8, 0xA5),
    (0xE4, 0xE5, 0x94), (0xCF, 0xEF, 0x96), (0xBD, 0xF4, 0xAB), (0xB3, 0xF3, 0xCC),
    (0xB5, 0xEB, 0xF2), (0xB8, 0xB8, 0xB8), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00),
)


class RenderError(ValueError):
    """⚠ 描けなかった。★中途半端な絵を返さない。"""


def _tile_rows(chr_data: bytes, index: int) -> list[list[int]]:
    """8x8 の 2bpp を 0..3 で返す。"""
    o = PATTERN_TABLE + index * 16
    if o + 16 > len(chr_data):
        raise RenderError(f"CHR が足りません（タイル {index}）")
    out = []
    for y in range(8):
        lo, hi = chr_data[o + y], chr_data[o + y + 8]
        out.append([((lo >> (7 - x)) & 1) | (((hi >> (7 - x)) & 1) << 1)
                    for x in range(8)])
    return out


def render(nametable: bytes, chr_data: bytes, palette: bytes,
           second_screen: bool = False) -> tuple[bytearray, int, int]:
    """(RGB の並び, 幅, 高さ) を返す。"""
    if len(chr_data) < 0x2000:
        raise RenderError(f"CHR が {len(chr_data)} バイトしかありません（8192 のはず）")
    if len(palette) < 32:
        raise RenderError(f"パレットが {len(palette)} バイトしかありません（32 のはず）")
    base = NAMETABLE_SIZE if second_screen else 0
    if len(nametable) < base + NAMETABLE_SIZE:
        raise RenderError("ネームテーブルが足りません")

    w, h = COLUMNS * 8, ROWS * 8
    px = bytearray(w * h * 3)
    for ty in range(ROWS):
        for tx in range(COLUMNS):
            tile = nametable[base + ty * COLUMNS + tx]
            # 属性は 16x16 ごとに 2 bit
            attr = nametable[base + ATTRIBUTE_AT + (ty // 4) * 8 + (tx // 4)]
            shift = ((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2
            sub = (attr >> shift) & 3
            rows = _tile_rows(chr_data, tile)
            for y in range(8):
                for x in range(8):
                    v = rows[y][x]
                    # ⚠ 0 は「透明」ではなく**背景色**（$3F00）
                    idx = palette[0] if v == 0 else palette[sub * 4 + v]
                    r, g, b = NES_PALETTE[idx & 0x3F]
                    p = ((ty * 8 + y) * w + tx * 8 + x) * 3
                    px[p], px[p + 1], px[p + 2] = r, g, b
    return px, w, h


def render_screen(tiles, subs, chr_data: bytes,
                  palette: bytes) -> tuple[bytearray, int, int]:
    """**組み立て済みの画面**（32x30）を描く。

    ★`dq3rom/ppu.py` がスクロールを反映して作ったものを受ける。
    ⚠ 属性も面ごとに取り直したものを受ける（`compose_attributes`）。
    """
    if len(chr_data) < 0x2000:
        raise RenderError(f"CHR が {len(chr_data)} バイトしかありません（8192 のはず）")
    if len(palette) < 32:
        raise RenderError(f"パレットが {len(palette)} バイトしかありません（32 のはず）")
    if len(tiles) < COLUMNS * ROWS or len(subs) < COLUMNS * ROWS:
        raise RenderError("画面が足りません（32x30 のはず）")

    w, h = COLUMNS * 8, ROWS * 8
    px = bytearray(w * h * 3)
    for ty in range(ROWS):
        for tx in range(COLUMNS):
            i = ty * COLUMNS + tx
            rows = _tile_rows(chr_data, tiles[i])
            sub = subs[i]
            for y in range(8):
                for x in range(8):
                    v = rows[y][x]
                    # ⚠ 0 は「透明」ではなく**背景色**（$3F00）
                    idx = palette[0] if v == 0 else palette[sub * 4 + v]
                    r, g, b = NES_PALETTE[idx & 0x3F]
                    p = ((ty * 8 + y) * w + tx * 8 + x) * 3
                    px[p], px[p + 1], px[p + 2] = r, g, b
    return px, w, h


def draw_sprites(px: bytearray, w: int, h: int, oam: bytes, chr_data: bytes,
                 palette: bytes, ppuctrl: int) -> int:
    """スプライト（人物・カーソルなど）を上から描く。描いた枚数を返す。

    ⚠⚠ **手を抜いているところ**（★あとで直すなら、ここ）

    - 前後関係（属性の bit5「背景の後ろ」）を見ていない。**全部前に描く**
    - 1 走査線 8 枚の制限を見ていない（★実機なら消えるものも描く）

    ⚠ どちらも「実機より多く見える」方向なので、**見落としは生まない**。
    ★位置を知るのが目的なので、いまはこれで足りる。
    """
    tall = bool(ppuctrl & 0x20)          # ★8x16 か
    table = 0x1000 if (ppuctrl & 0x08) else 0x0000
    drawn = 0
    # ⚠ 番号が小さいほど手前。★上書きされないよう、後ろから描く
    for i in range(63, -1, -1):
        y, tile, attr, x = oam[i * 4:i * 4 + 4]
        if y >= 0xEF:                    # ⚠ 画面の外へ追いやったもの
            continue
        top = y + 1                      # ★OAM の y は「1 少ない」
        sub = 4 + (attr & 3)             # ★スプライトのパレットは 16 番から
        flip_x, flip_y = bool(attr & 0x40), bool(attr & 0x80)
        if tall:
            base = 0x1000 if (tile & 1) else 0x0000
            parts = [(base, (tile & 0xFE)), (base, (tile & 0xFE) + 1)]
        else:
            parts = [(table, tile)]
        for part, (tbl, idx) in enumerate(parts):
            o = tbl + idx * 16
            if o + 16 > len(chr_data):
                continue
            for ry in range(8):
                lo, hi = chr_data[o + ry], chr_data[o + ry + 8]
                sy = top + part * 8 + (7 - ry if flip_y else ry)
                if not (0 <= sy < h):
                    continue
                for rx in range(8):
                    v = ((lo >> (7 - rx)) & 1) | (((hi >> (7 - rx)) & 1) << 1)
                    if v == 0:           # ★0 は透明（背景と違って本当に透明）
                        continue
                    sx = x + (7 - rx if flip_x else rx)
                    if not (0 <= sx < w):
                        continue
                    idxc = palette[sub * 4 + v]
                    r, g, b = NES_PALETTE[idxc & 0x3F]
                    q = (sy * w + sx) * 3
                    px[q], px[q + 1], px[q + 2] = r, g, b
        drawn += 1
    return drawn


def write_png(path: pathlib.Path, px: bytearray, w: int, h: int) -> pathlib.Path:
    """外部ライブラリ無しで PNG を書く（★同梱物を増やさない）。"""
    raw = b"".join(b"\x00" + bytes(px[y * w * 3:(y + 1) * w * 3]) for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9))
                     + chunk(b"IEND", b""))
    return path


def from_savestate(state, second_screen: bool = False, raw: bool = False,
                   sprites: bool = True):
    """セーブステートから描く。★遊びを止めずに、いつでも画面を出せる。

    ⚠ 既定では**スクロールを反映**する（2026-08-26）。
    ★それまでは面 1 枚をそのまま描いていたので、
    スクロールしている場面では**実機と違う絵**になっていた。

    `raw=True` で昔どおり面 1 枚を描く（★面の中身を確かめたいとき）。
    """
    for key, size in (("NTAR", 2048), ("CHRR", 8192), ("PRAM", 32)):
        if key not in state.chunks:
            raise RenderError(f"セーブステートに {key} がありません")
        if len(state.chunks[key]) < size:
            raise RenderError(f"{key} が {len(state.chunks[key])} バイトしかありません")
    if raw:
        # ⚠ 面 1 枚をそのまま描く。★中身を確かめたいときだけ
        return render(state.chunks["NTAR"], state.chunks["CHRR"],
                      state.chunks["PRAM"], second_screen)
    from . import ppu

    ntar = state.chunks["NTAR"]
    scroll = ppu.scroll_of(state.chunks)
    mirroring = ppu.mirroring_of(state.chunks)
    px, w, h = render_screen(ppu.compose(ntar, scroll, mirroring),
                             ppu.compose_attributes(ntar, scroll, mirroring),
                             state.chunks["CHRR"], state.chunks["PRAM"])
    # ★人物やカーソルはスプライト。⚠ 背景だけだと「誰がどこにいるか」が写らない
    oam = state.chunks.get("SPRA")
    ppur = state.chunks.get("PPUR")
    if sprites and oam is not None and len(oam) >= 256:
        ctrl = ppur[0] if ppur else 0
        draw_sprites(px, w, h, oam, state.chunks["CHRR"],
                     state.chunks["PRAM"], ctrl)
    return px, w, h


def parse_probe_dump(text: str) -> list[dict]:
    """probe が書いた 16 進の並びを読む（`@NT` / `@CHR` / `@PAL`）。"""
    snaps: list[dict] = []
    cur: dict | None = None
    key: str | None = None
    for line in text.splitlines():
        if line.startswith("@snapshot"):
            cur = {"tag": line[1:].strip(), "NT": "", "CHR": "", "PAL": ""}
            snaps.append(cur)
            key = None
        elif line.startswith("@") and cur is not None:
            key = line[1:].strip()
        elif cur is not None and key and line and all(
                c in "0123456789ABCDEF" for c in line):
            cur[key] += line
    return snaps
