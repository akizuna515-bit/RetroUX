"""世界地図のどの升が、どの map へ入るか（RX3-0067 / 2026-09-16）。

## ★★ 表は bank6 `$B24C`。⚠⚠ **行番号がそのまま map 番号**です

```text
bank6 $B24C + map * 5  →  (world_x, world_y, ?, ?, ?)    ★map 0..64
```

⚠ つまりこの表は「升 → map」ではなく「**map → その世界地図の入口の升**」です。
★引っくり返せば「升 → map」になります（`by_cell`）。

## ⚠ 確度は `OBSERVED` です（★コードは読めていません）

⚠⚠ **この表を読む ROM のコードは見つけていません。** `LDA $B24C,X` の形は
ROM のどこにもなく、★ポインタ経由で引かれているはずです。
→ ⚠ だから `confirmed` とは書きません。

★代わりに、**独立した 2 本**で確かめています。

```text
① ROM の構造   世界地図へ出る出口を持つ map（0..64）は 28 件。
               ★そのうち 27 件で、表の升が**入口のニブル（$1）の升**だった
               （⚠ 合わないのは map 4 の 1 件だけ）
② 依頼者の記録  ROM 名・手入力の場所 22 件と突き合わせ
               ★ぴったり 9 件 / ★1〜2 升ずれ 11 件 / ⚠ 遠い 2 件
               ⚠ 1〜2 升のずれは **入る 1 歩手前の升**を記録しているため（`RX3-0275`）
               ⚠ 遠い 2 件はルーラで着いた升（★同じく `RX3-0275` の註）
```

★行番号 = map 番号の決め手（⚠ ROM 名・手入力だけを使った）:

```text
行  0 → アリアハン map 0     行 20 → カザーブ map 20
行  9 → レーベ   map 9      行 21 → テドン   map 21
行 12 → アッサラーム map 12  行 22 → ムオル   map 22
行 63 → シャンパーニのとう map 63
```

## ⚠ 分かっていないこと

- ⚠ 後ろの 3 バイトが何かは**決めていません**（★着く向き・位置らしいが裏が無い）。
- ⚠ 表は **map 0..64 まで**です。★世界地図へ出る出口を持つ map には
  147 / 148 / 151 / 156 / 162 / 166 / 216 のように**表の外**のものがあり、
  そこは別の入り方（★親の map を経由）と思われます。⚠ 確かめていません。
- ⚠ map 4 だけ、表の升が入口のニブルではありません（★理由は不明）。
- ⚠ アレフガルドの升も同じ表に混ざります（★13 件）。
  ⚠⚠ **どちらの世界かは、この表だけでは決まりません。**
"""

from __future__ import annotations

import dataclasses

from . import collision
from .profile import Identified

#: 表のある場所
BANK = 6
TABLE_CPU = 0xB24C
#: ★1 件 5 バイト
ENTRY = 5
#: ★件数（⚠ map 0..64）
COUNT = 65

#: ★入口として数える collision の下位ニブル（⚠ `entrances.ENTRANCE_NIBBLES` と同じ）
ENTRANCE_NIBBLES = (0x01, 0x0A, 0x0F)

#: ★世界地図の tileset
WORLD_TILESET = 0

#: ⚠ 表の升が入口のニブルでない map（★理由は不明 / 黙って直さない）
KNOWN_ODD = (4,)


class WorldEntranceError(ValueError):
    """⚠ 表が想定と違う。★握りつぶさない。"""


@dataclasses.dataclass(frozen=True)
class WorldEntrance:
    """★map 1 つの、世界地図での入口。"""

    map_id: int
    x: int
    y: int
    rest: tuple[int, int, int]      #: ⚠ 後ろの 3 バイト（★意味は未確定）

    @property
    def empty(self) -> bool:
        """★(0,0) は「世界地図の入口を持たない」印（⚠ 2 件ある）。"""
        return (self.x, self.y) == (0, 0)

    def to_json(self) -> dict:
        return {"map_id": self.map_id, "world_x": self.x, "world_y": self.y,
                "confidence": "OBSERVED"}


def read(ident: Identified) -> dict[int, WorldEntrance]:
    """★表をそのまま起こす（⚠ map 0..64）。"""
    win = ident.window(BANK)
    base = TABLE_CPU - 0x8000
    out: dict[int, WorldEntrance] = {}
    for m in range(COUNT):
        o = base + m * ENTRY
        if o + ENTRY > len(win):
            raise WorldEntranceError("⚠ 表が窓からはみ出しました: map %d" % m)
        x, y, a, b, c = win[o:o + ENTRY]
        out[m] = WorldEntrance(map_id=m, x=x, y=y, rest=(a, b, c))
    return out


def by_cell(ident: Identified) -> dict[tuple[int, int], list[int]]:
    """★升 → その升から入る map（⚠ 同じ升に 2 つ載ることがある）。"""
    out: dict[tuple[int, int], list[int]] = {}
    for e in read(ident).values():
        if e.empty:
            continue
        out.setdefault((e.x, e.y), []).append(e.map_id)
    return out


def entrance_cells(ident: Identified, name: str) -> set[tuple[int, int]]:
    """★その世界地図で、入口のニブルを持つ升。"""
    from . import world_map

    table = collision.base_table(ident, WORLD_TILESET)
    want = {i for i, v in enumerate(table) if (v & 0x0F) in ENTRANCE_NIBBLES}
    w = world_map.decode(ident, name)
    return {(x, y) for y, row in enumerate(w.tiles)
            for x, t in enumerate(row) if t in want}


def disagreements(ident: Identified) -> list[str]:
    """★「世界へ出る出口を持つ map は、表でも入口の升を指す」を確かめる。

    ⚠ 空にはなりません（★`KNOWN_ODD` の map 4 が残ります）。
    ⚠⚠ **黙って除かない**ので、呼ぶ側が `KNOWN_ODD` と突き合わせてください。
    """
    from . import entrances as en

    cells = entrance_cells(ident, "world_main") | entrance_cells(ident, "world_alefgard")
    blocks = en.read_blocks(ident)
    table = read(ident)
    bad: list[str] = []
    for m, blk in enumerate(blocks):
        if m >= COUNT:
            continue
        if not any(0xC0 <= (e.kind or 0) for e in blk):
            continue                      # ★世界地図へ出ない map は対象外
        e = table[m]
        if (e.x, e.y) not in cells:
            bad.append("map %d の升 (%d,%d) が入口の升でない" % (m, e.x, e.y))
    return bad


#: ★世界地図の名前（⚠ `world_map.decode` に渡す名前）
WORLDS = ("world_main", "world_alefgard")


def world_links(ident: Identified) -> dict:
    """★`dq3.knowledge.map_graph` に渡す材料（⚠ あちらは ROM を読みません）。

    ★どちらの世界かは「**その世界で入口のニブルを持つ升か**」で決めます。
    ⚠ 両方・どちらでもない行は、★黙って片方に寄せず `unplaced` に出します
    （★いまは `KNOWN_ODD` の map 4 だけ）。

    ```text
    entrances       [{map_id, world, x, y}]   ★世界地図 → map の辺になる行
    unplaced        [map_id]                  ⚠ どちらの世界か決まらない行
    entrance_cells  {world: {(x, y)}}         ★着いた升の世界を決める材料
    sizes           {world: (幅, 高さ)}
    ```
    """
    from . import world_map

    cells = {n: entrance_cells(ident, n) for n in WORLDS}
    sizes = {}
    for n in WORLDS:
        w = world_map.decode(ident, n)
        sizes[n] = (len(w.tiles[0]) if w.tiles else 0, len(w.tiles))
    rows: list[dict] = []
    unplaced: list[int] = []
    for e in read(ident).values():
        if e.empty:
            continue
        hits = [n for n in WORLDS if (e.x, e.y) in cells[n]]
        if len(hits) != 1:
            unplaced.append(e.map_id)
            continue
        rows.append({"map_id": e.map_id, "world": hits[0], "x": e.x, "y": e.y})
    return {"entrances": rows, "unplaced": unplaced,
            "entrance_cells": cells, "sizes": sizes}


def summary(ident: Identified) -> dict:
    table = read(ident)
    cells = entrance_cells(ident, "world_main")
    return {
        "maps": len(table),
        "empty": sum(1 for e in table.values() if e.empty),
        "on_main": sum(1 for e in table.values() if (e.x, e.y) in cells),
        "disagreements": len(disagreements(ident)),
    }


__all__ = ["BANK", "TABLE_CPU", "ENTRY", "COUNT", "KNOWN_ODD", "WORLD_TILESET",
           "WorldEntranceError", "WorldEntrance", "read", "by_cell",
           "entrance_cells", "disagreements", "summary", "WORLDS", "world_links"]
