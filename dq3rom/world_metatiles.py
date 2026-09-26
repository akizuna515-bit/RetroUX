"""世界地図の升の絵を ROM から起こす（RX3-0232 / 2026-09-16）。

## ⚠⚠ 確度をはっきりさせます

★これは **ROM のコードをそのまま写したものではありません**。
⚠ 升の絵を作る本体（固定バンク 15 `$F860` / 差分表 `$B412`）は**読み切っていません**。

★代わりに、`dq3rom/collision.py` が使っているのと**同じ 3 バイト組**から、
実機で採った表（`data/dq3/world-metatiles.json` の 22 件）を**全部再現できる**
規則を見つけました。⚠ 自由なパラメータは `FIRST_CHR` の 1 つだけです。

```text
★確かめたこと  22 件すべて一致（⚠ 不一致 0）。★1 つ合わせて 21 件が独立に当たった
⚠ 確かめていない  CHR を積む routine そのもの（★順序はデータから見つけた規則）
```

## 3 バイト組（★collision と同じ表 / `tile_definitions`）

    byte0 = 見た目     ★形 = byte0 >> 4 / パレット組 = (byte0 >> 2) & 3
    byte1 = 絵の番号   ⚠ CHR の位置ではない。★「同じ番号なら同じ絵」の鍵
    byte2 = collision  ★`dq3rom/collision.py` が使う

## ★形（byte0 >> 4）

```text
0  ★1 枚を 4 つ並べる     （例: 草原）          … CHR 1 枚
1  ★連番 4 枚             （例: 海・林・町）    … CHR 4 枚
4  ★鏡（左右対称）        （例: 升 30）         … CHR 2 枚
```

## ★CHR の位置の決まり方（⚠ ここがデータから見つけた規則）

★升 id を 0 から順に見て、**byte1 が初めて出たときだけ**、形のぶんだけ
CHR を先頭から順に取っていきます（⚠ 同じ byte1 は同じ絵を使い回す）。

```text
id 0  byte1=$1B 形1 → 141,142,143,144
id 1  byte1=$30 形0 → 145
id 2  byte1=$2F 形0 → 146
id 3  byte1=$1F 形1 → 147,148,149,150
 …
id 7  byte1=$31 形0 → 163        ★実機の表では**空いていた所**
id 8  byte1=$32 形1 → 164,…      ⚠ 実機の表と一致（★7 が 1 枚使った辻褄が合う）
```

⚠⚠ **この「空きがちょうど埋まる」ことが、規則の裏取りです。**
★id 16（形0）も同じで、その次の id 17 が 197 から始まります。

## ⚠ 気をつけること

- ⚠ `FIRST_CHR` は**実機の表から採った値**です（★ROM からは出していません）。
- ⚠ 升 31 の CHR（223..226）は、実機の表で**いちばん後ろより先**にあります。
  ★同じ規則の続きですが、⚠ 実機の表で裏が取れているわけではありません。
- ⚠ アレフガルドの地図も同じ絵かは**見ていません**（★表は升 id だけで引く）。
"""

from __future__ import annotations

import dataclasses

from . import collision
from .profile import Identified

#: ★世界地図の tileset
TILESET = 0

#: ⚠ 唯一の自由なパラメータ。★実機の表の升 0 が 141..144 だったことから
FIRST_CHR = 141

#: ★形 → CHR を何枚使うか
SHAPE_SLOTS = {0: 1, 1: 4, 4: 2}

#: ★升は 32 個
COUNT = collision.TABLE_SIZE


class MetatileError(ValueError):
    """⚠ 知らない形が出た。★黙って埋めない。"""


@dataclasses.dataclass(frozen=True)
class Metatile:
    """升 1 つの絵。"""

    tile_id: int
    tiles: tuple[int, int, int, int]      # ★左上・右上・左下・右下
    pal: int
    shape: int
    art_id: int                            # ★byte1（⚠ CHR の位置ではない）
    collision: int                         # ★byte2

    def to_json(self) -> dict:
        return {"tiles": list(self.tiles), "pal": self.pal}


def shape_of(byte0: int) -> int:
    """★形（⚠ 知らない形は断る）。"""
    shape = byte0 >> 4
    if shape not in SHAPE_SLOTS:
        raise MetatileError("⚠ 知らない形です: byte0=0x%02X（形 %d）" % (byte0, shape))
    return shape


def pal_of(byte0: int) -> int:
    """★パレット組（0..3）。"""
    return (byte0 >> 2) & 3


def tiles_of(shape: int, first: int) -> tuple[int, int, int, int]:
    """★形 → 4 枚の並び。"""
    if shape == 0:
        return (first, first, first, first)
    if shape == 1:
        return (first, first + 1, first + 2, first + 3)
    if shape == 4:
        return (first, first + 1, first + 1, first)
    raise MetatileError("⚠ 知らない形です: %d" % shape)


def read_records(ident: Identified, tileset: int = TILESET) -> list[tuple[int, int, int]]:
    """★3 バイト組を 32 個読む（⚠ collision と同じ表）。"""
    prg = ident.rom.prg
    base = ident.table_prg("tile_definitions")
    limit = collision.group_count(ident)
    out: list[tuple[int, int, int]] = []
    for g in collision.group_indices(tileset):
        if not 0 <= g < limit:
            raise MetatileError(
                "tileset %d のグループ %d が表の外です（0〜%d）" % (tileset, g, limit - 1))
        o = base + g * collision.GROUP_BYTES
        for i in range(8):
            r = prg[o + i * collision.TILE_RECORD: o + (i + 1) * collision.TILE_RECORD]
            out.append((r[0], r[1], r[2]))
    return out


def build(ident: Identified, tileset: int = TILESET,
          first: int = FIRST_CHR) -> dict[int, Metatile]:
    """升 32 個ぶんの絵を起こす。

    ⚠ `first` は実機の表から採った値です（★ROM からは出していません）。
    """
    seen: dict[int, int] = {}
    nxt = first
    out: dict[int, Metatile] = {}
    for i, (b0, b1, b2) in enumerate(read_records(ident, tileset)):
        shape = shape_of(b0)
        if b1 not in seen:
            seen[b1] = nxt
            nxt += SHAPE_SLOTS[shape]
        out[i] = Metatile(tile_id=i, tiles=tiles_of(shape, seen[b1]), pal=pal_of(b0),
                          shape=shape, art_id=b1, collision=b2)
    return out


def disagreements(ident: Identified, known: dict) -> list[str]:
    """★実機から採った表と突き合わせる。空なら全部一致。

    ⚠ `known` は `data/dq3/world-metatiles.json` の `metatiles`（★鍵は文字列）。
    """
    got = build(ident)
    bad: list[str] = []
    for key, row in sorted(known.items(), key=lambda kv: int(kv[0])):
        mine = got.get(int(key))
        if mine is None:
            bad.append("升 %s が ROM 側に無い" % key)
            continue
        if list(mine.tiles) != list(row.get("tiles") or []):
            bad.append("升 %s の CHR: ROM %s ≠ 実機 %s" % (key, list(mine.tiles), row.get("tiles")))
        if mine.pal != row.get("pal"):
            bad.append("升 %s のパレット組: ROM %d ≠ 実機 %s" % (key, mine.pal, row.get("pal")))
    return bad


__all__ = ["TILESET", "FIRST_CHR", "SHAPE_SLOTS", "COUNT", "MetatileError", "Metatile",
           "shape_of", "pal_of", "tiles_of", "read_records", "build", "disagreements"]
