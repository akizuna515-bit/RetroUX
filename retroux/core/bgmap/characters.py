"""背景キャラクタ（8×8）とメタタイル（16×16）を作る
（2026-08-02 / マップ指示書 Phase 4・5 / §8・§10）。

## ★ 正本は 8×8（指示書 §8.1）

  NES の背景キャラクタの単位そのもの。ここを崩さない。

## ★ 表示は 16×16 のメタタイル（指示書 §8.2）

      左上  右上
      左下  右下

  DQ2 の1マスは 16×16 画素 ＝ 2×2 キャラクタ。

## ⚠⚠ 鍵はタイルIDだけにしない（指示書 §7.3）

    <CHR内容のハッシュ>:<タイルID>:<パレットの署名>

  ⚠ DQ2 は **CHR-RAM**。同じタイルIDでも中身が入れ替わる。
    IDだけを鍵にすると、別の絵を同じものとして扱ってしまう。
  ⚠ 同じ絵でもパレットが違えば見た目が違う。署名に色も入れる。

## ★ 倍率（指示書 §10）

  1倍（16×16）を正本にし、2倍・4倍は**最近傍の整数拡大**で作る。
  ⚠ アンチエイリアスをかけない（ぼやけると地形が読めない）。
  0.5倍は最近傍縮小。
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib

from . import reconstruct as R

#: 出せる倍率（指示書 §10.1）。★任意の小数倍率は作らない
SCALES = {"half": 0.5, "1x": 1, "2x": 2, "4x": 4}


def chr_hash(chr_data: bytes, tile_id: int, half: int = 0) -> str:
    """そのタイルの **CHR 16 バイト**のハッシュ。

    ★中身そのものを鍵にする。⚠ タイルIDは鍵にしない（CHR-RAM のため）。
    """
    base = half + tile_id * 16
    return hashlib.sha1(chr_data[base:base + 16]).hexdigest()[:12]


def palette_signature(palette: bytes, group: int) -> str:
    """使っている4色を短い文字列にする。"""
    return "".join(f"{c:02X}" for c in R.palette_colors(palette, group))


def character_key(chr_data: bytes, tile_id: int, palette: bytes, group: int,
                  half: int = 0) -> str:
    """指示書 §7.3 の鍵: `<CHRハッシュ>:<タイルID>:<パレット署名>`。"""
    return (f"{chr_hash(chr_data, tile_id, half)}"
            f":{tile_id:02X}"
            f":{palette_signature(palette, group)}")


@dataclasses.dataclass(frozen=True)
class Character:
    """8×8 の背景キャラクタ1枚。"""

    key: str
    tile_id: int
    chr_hash: str
    palette_signature: str
    #: 0..3 の番号（パレットを当てる前）
    pattern: tuple[tuple[int, ...], ...]
    #: NES の色番号 4つ
    colors: tuple[int, int, int, int]

    def rgba(self, nes_palette, opaque: bool = True):
        """RGBA の 8×8 にする。

        ⚠ 地形画像は基本的に**不透明**（指示書 §9.3）。
          `opaque=False` にすると色0を透明にする。
        """
        out = []
        for row in self.pattern:
            line = []
            for n in row:
                r, g, b = nes_palette.rgb(self.colors[n] & 0x3F)
                alpha = 255 if (opaque or n != 0) else 0
                line.append((r, g, b, alpha))
            out.append(line)
        return out

    @property
    def is_blank(self) -> bool:
        """★全部が色0＝地の色。指示書 §11.1 の「黒観測」の候補。"""
        return all(n == 0 for row in self.pattern for n in row)


def character_of(chr_data: bytes, palette: bytes, tile_id: int, group: int,
                 half: int = 0) -> Character:
    """CHR とパレットから 8×8 を1枚作る。

    ★★ **画面が要りません。** ★★
      ⚠ 以前は `Capture`（採ったセーブステート）からしか作れず、
        「採った場所の周りしか描けない」という縛りになっていました。
      ★ROM から組んだ CHR とパレットを渡せば、同じものが作れます。
        鍵の作り方は変えていないので、**採ったものと同じ鍵**になります
        （＝辞書もDBもそのまま使えます）。
    """
    return Character(
        key=character_key(chr_data, tile_id, palette, group, half),
        tile_id=tile_id,
        chr_hash=chr_hash(chr_data, tile_id, half),
        palette_signature=palette_signature(palette, group),
        pattern=tuple(tuple(r) for r in R.tile_pixels(chr_data, tile_id, half)),
        colors=R.palette_colors(palette, group),
    )


def character_at(cap: R.Capture, col: int, row: int, half: int) -> Character:
    """画面の (col,row) にある 8×8 キャラクタを作る。"""
    side, nc, nr = R.nametable_index(col, row, cap.scroll_x, cap.scroll_y)
    if side == "left":
        tile_id = cap.nametable_left[nr * R.COLS + nc]
        group = R.attribute_for(cap.attr_left, nc, nr)
    else:
        tile_id = cap.nametable_right[nr * R.COLS + nc]
        group = R.attribute_for(cap.attr_right, nc, nr)
    return character_of(cap.chr_data, cap.palette, tile_id, group, half)


@dataclasses.dataclass(frozen=True)
class Metatile:
    """16×16 のメタタイル（2×2 キャラクタ / 指示書 §8.2）。"""

    key: str
    top_left: Character
    top_right: Character
    bottom_left: Character
    bottom_right: Character
    map_id: int
    x: int
    y: int

    @property
    def characters(self):
        return (self.top_left, self.top_right,
                self.bottom_left, self.bottom_right)

    @property
    def is_blank(self) -> bool:
        """★4枚とも地の色なら「黒観測」（指示書 §11.1）。

        ⚠ **地形として保存しない**。既存の地形も上書きしない。
        """
        return all(c.is_blank for c in self.characters)

    def rgba(self, nes_palette, opaque: bool = True):
        """16×16 の RGBA にする。"""
        tl = self.top_left.rgba(nes_palette, opaque)
        tr = self.top_right.rgba(nes_palette, opaque)
        bl = self.bottom_left.rgba(nes_palette, opaque)
        br = self.bottom_right.rgba(nes_palette, opaque)
        rows = []
        for y in range(R.TILE):
            rows.append(tl[y] + tr[y])
        for y in range(R.TILE):
            rows.append(bl[y] + br[y])
        return rows


def metatile_key(characters) -> str:
    """4枚の鍵から 16×16 の鍵を作る。★並びは 左上・右上・左下・右下。"""
    return hashlib.sha1(
        "|".join(c.key for c in characters).encode()).hexdigest()[:16]


def metatile_of(chr_data: bytes, palette: bytes, tiles, group: int,
                map_id: int = -1, x: int = -1, y: int = -1,
                half: int = 0) -> Metatile:
    """CHR とパレットから 16×16 を1マス作る。

    `tiles` は **左上・右上・左下・右下**のタイルID 4つ。

    ⚠⚠ **4枚とも要ります。左上だけでは足りません。**
      ★2026-08-02 に実測したところ、残り3枚の決まり方は
        マップごとに違いました（ダンジョンは差 `(4,-1,3)`、
        街は `(2,-1,1)`、しかも例外あり）。
        ★規則を1つに決めてしまうと、街の飾りで間違えます。
    """
    tl, tr, bl, br = (
        character_of(chr_data, palette, t, group, half) for t in tiles)
    return Metatile(key=metatile_key((tl, tr, bl, br)),
                    top_left=tl, top_right=tr,
                    bottom_left=bl, bottom_right=br,
                    map_id=map_id, x=x, y=y)


def metatile_at(cap: R.Capture, cell_col: int, cell_row: int,
                half: int) -> Metatile:
    """1マス（16×16）ぶんのメタタイルを作る。

    `cell_col` / `cell_row` は **16 画素単位**（画面 16×15 マス）。
    """
    col, row = cell_col * 2, cell_row * 2
    tl = character_at(cap, col, row, half)
    tr = character_at(cap, col + 1, row, half)
    bl = character_at(cap, col, row + 1, half)
    br = character_at(cap, col + 1, row + 1, half)
    return Metatile(key=metatile_key((tl, tr, bl, br)),
                    top_left=tl, top_right=tr,
                    bottom_left=bl, bottom_right=br,
                    map_id=cap.map_id, x=cell_col, y=cell_row)


def scale_nearest(rows, factor):
    """最近傍で拡大・縮小する（指示書 §10.2）。

    ⚠⚠ **平滑化しない**。ぼやけると床と壁が見分けられなくなる。
    """
    if factor == 1:
        return [list(r) for r in rows]
    if factor >= 1:
        step = int(factor)
        out = []
        for row in rows:
            line = []
            for px in row:
                line.extend([px] * step)
            for _ in range(step):
                out.append(list(line))
        return out
    # ★縮小（0.5倍）。⚠ 平均しない。最近傍で間引く
    take = int(round(1 / factor))
    return [[row[x] for x in range(0, len(row), take)]
            for y, row in enumerate(rows) if y % take == 0]


def write_png(rows, path) -> pathlib.Path:
    """RGBA の格子を PNG にする。★既存の書き出しを使い回す。"""
    from dq2rom.monsters import png

    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png.encode([[tuple(p) for p in row] for row in rows]))
    return path
