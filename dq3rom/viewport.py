"""画面の升目と地図の升目を行き来する（RX3-0016 / 2026-08-26）。

★★ 何が分かったか ★★

**主人公は、いつも画面の同じ升に描かれる。**

    主人公の升 = (8, 7)      ★16x16 の升で数えて、左から 8 番目・上から 7 番目

したがって、地図の升は**スクロールを見なくても**決まる。

    地図 = 主人公の地図座標 + (画面の升 - (8, 7))

⚠ スクロールから求めようとして**失敗した**。★面はスクロールに合わせて
書き換わる（＝地図の原点と面の原点は一致しない）ので、
`scroll / 16` は地図座標にならない。

## ★どうやって確かめたか

地図バッファ（実機の `dq3_helper.lua` が書き出した map 9 の 26x26）と、
実機のセーブステート 2 つ（`fc9` / `fc7`）の画面を突き合わせた。

⚠ 「同じ地図タイルは同じ見た目になるはず」を手がかりに、
ずれ 26x26 通りを総当たりして矛盾の数を数えた。

| | 矛盾が最も少ないずれ | ★式が出す値 |
| --- | --- | --- |
| `fc9` 位置(2,10) | (20, 3) 矛盾 39（次点 48） | (2-8, 10-7) = (20, 3) |
| `fc7` 位置(19,13) | (11, 6) 矛盾 15（次点 82） | (19-8, 13-7) = (11, 6) |

★2 つとも一致した。⚠ そして残った矛盾は**窓の枠の隠し漏れ**で、
地形のタイルは **13 種すべてが 1 通りの見た目**に収まった。

## ⚠ まだ確かめていないこと

- **世界地図**（広い map）でも中央固定か。★町・ダンジョンでしか見ていない
- 端に寄ったとき。⚠ `fc7` は右端に寄っており、地図の外が映っていた
  （★＝端でも中央固定。少なくとも 26x26 では）
"""

from __future__ import annotations

import dataclasses

#: 1 つの地図の升は 2x2 のタイル（16x16 ピクセル）。
TILES_PER_CELL = 2

#: ★主人公が描かれる升（16x16 単位）。⚠ 実測で決めた（上の表）。
HERO_CELL_X = 8
HERO_CELL_Y = 7

#: 画面に入る升の数（32x30 タイル ÷ 2）。⚠ 縦は 15 だが最下段は半端。
CELLS_ACROSS = 16
CELLS_DOWN = 15


@dataclasses.dataclass(frozen=True)
class Viewport:
    """いま画面が地図のどこを映しているか。

    ⚠ `party_x` / `party_y` は RAM `$30` / `$31`。
    """

    party_x: int
    party_y: int
    width: int
    height: int

    @property
    def left(self) -> int:
        """★画面の左端が地図の何列目か（⚠ 負になりうる = 地図の外）。"""
        return self.party_x - HERO_CELL_X

    @property
    def top(self) -> int:
        return self.party_y - HERO_CELL_Y

    def map_at(self, tile_x: int, tile_y: int) -> tuple[int, int]:
        """画面のタイル座標（32x30）→ 地図の升目。

        ⚠ 地図の外を指すこともある。★範囲は `contains` で確かめる。
        """
        return (self.left + tile_x // TILES_PER_CELL,
                self.top + tile_y // TILES_PER_CELL)

    def screen_at(self, map_x: int, map_y: int) -> tuple[int, int]:
        """地図の升目 → 画面のタイル座標（★升の左上）。"""
        return ((map_x - self.left) * TILES_PER_CELL,
                (map_y - self.top) * TILES_PER_CELL)

    def contains(self, map_x: int, map_y: int) -> bool:
        """その升が**地図の中**にあるか。⚠ 画面に映っているかとは別。"""
        return 0 <= map_x < self.width and 0 <= map_y < self.height

    def on_screen(self, map_x: int, map_y: int) -> bool:
        """その升が**いま画面に映っているか**。"""
        sx, sy = self.screen_at(map_x, map_y)
        return 0 <= sx < CELLS_ACROSS * TILES_PER_CELL and \
            0 <= sy < CELLS_DOWN * TILES_PER_CELL

    def visible_cells(self):
        """画面に映っていて、かつ地図の中にある升を全部返す。

        ★探索済み領域を記録するときの単位（No-Spoiler の土台）。
        """
        for cy in range(CELLS_DOWN):
            for cx in range(CELLS_ACROSS):
                mx, my = self.left + cx, self.top + cy
                if self.contains(mx, my):
                    yield (mx, my, cx * TILES_PER_CELL, cy * TILES_PER_CELL)


def of_state(chunks, width: int, height: int) -> Viewport:
    """savestate のチャンクから作る。⚠ 地図の大きさは ROM 側から渡す。"""
    ram = chunks["RAM"]
    return Viewport(party_x=ram[0x30], party_y=ram[0x31],
                    width=width, height=height)
