"""区画（部屋）データ（2026-08-03 / Phase 4）。

★★★ **展開規則が実コードから確定しました。** ★★★

⚠ これは**地形ではありません**。「そのマスが見えるか」の判定に使います。
★`BaseTerrain` には影響しません。

## なぜ要るのか

DQ2 のダンジョンは「入った部屋だけ見える」ようになっています。

```
DCA1: LDA $1D / CMP $0D / BEQ $DCC9   ; ★同じ区画なら見える
DCC5: LDA #$24 / STA $0C              ; ⚠ 違えば境界タイルで隠す
```

`$1D` がプレイヤーのいる区画、`$0D` がそのマスの区画です。

## ★ 展開（`$E046`-`$E0A1` の写し）

```
E046: LDA $1F / CMP #$02
E04A: LDA #$3F / BCC       ; ★種別 < 2 はマスク $3F
E04E: LDA #$0F             ; ★種別 >= 2 はマスク $0F
E050: STA $0F
E052: LDA $25 / ORA $26 / BNE   ; ⚠ ポインタが 0 なら区画なし
E070: LDY #$FF / LDX #$00
E074: CPX $13 / BEQ $E081  ; ★行 y まで進む
E079: LDA ($25),Y / BMI $E074   ; ★★bit7 が立つバイトが「行の終わり」
E081: LDA #$FF / STA $0E   ; ★位置 = -1
E085: INY
E086: LDA ($25),Y / TAX    ; ★1 バイト読む
E089: AND $0F              ; ★★マスクで「長さ」を取る
E08B: SEC / ADC $0E / STA $0E   ; ★位置 += 長さ + 1
E090: CMP $12 / BCS $E099  ; ★x に届いたか
E094: TXA / BPL $E085      ; ⚠ bit7 が立っていなければ次のバイトへ
E097: LDX #$00             ; ⚠ 行を越えたら区画 0
E099: TXA / AND #$7F       ; ★bit7 を落とす
E09C: LSR / LSR $0F / BNE $E09C  ; ★★★マスクの幅だけ右シフト
E0A1: STA $0D              ; ★区画番号
```

★つまり 1 バイトは:

```
bit7      : ★その行の最後のかたまり
中間ビット: ★区画番号
下位ビット: ★長さ（マスクの幅ぶん）
```

| 種別 | マスク | 長さ | 区画番号 |
| --- | --- | --- | --- |
| 1（街） | `$3F` | 下位 6 ビット | bit6 だけ（0-1） |
| 2, 3 | `$0F` | 下位 4 ビット | bit4-6（0-7） |

⚠⚠ **区画 0 は「通路」**です（`$DCAD: LDA $1D / BNE $DCC5`）。
★プレイヤーが区画 0 にいるときは `$20`、区画の中にいるときは `$24` で隠します。
"""

from __future__ import annotations

import dataclasses

from .rom_tiles import MAP_HEADER, MAP_HEADER_SIZE

#: bank2 が PRG のどこにあるか
BANK2 = 0x08000

#: ★マスク（`$E04A` / `$E04E`）
MASK_TOWN = 0x3F
MASK_DUNGEON = 0x0F
#: ★マスクが変わる種別（`$E048: CMP #$02`）
DUNGEON_KIND = 2

#: ★行の終わりを示すビット（`$E07C: BMI`）
ROW_END_BIT = 0x80
#: ⚠ 通路（区画に属さない）
CORRIDOR = 0


def mask_for_kind(kind: int) -> int:
    """★種別ごとのマスク。"""
    return MASK_DUNGEON if kind >= DUNGEON_KIND else MASK_TOWN


def _shift_of(mask: int) -> int:
    """★マスクの幅（`$E09C: LSR / LSR $0F / BNE` の回数）。"""
    shift = 0
    while mask:
        mask >>= 1
        shift += 1
    return shift


@dataclasses.dataclass
class RegionMap:
    """1マップぶんの区画。⚠ 持っていないマップもあります。"""

    map_id: int
    kind: int
    pointer: int
    width: int
    height: int
    prg: bytes

    @property
    def has_data(self) -> bool:
        """⚠ ポインタが 0 なら区画なし（`$E052: ORA $26`）。"""
        return bool(self.pointer)

    @property
    def mask(self) -> int:
        return mask_for_kind(self.kind)

    def region_at(self, x: int, y: int):
        """★そのマスの区画番号。⚠ 区画データが無ければ None。

        ★引数は `$12`/`$13`、すなわち**論理セル座標**です。
        """
        if not self.has_data:
            return None
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        base = BANK2 + self.pointer - 0x8000
        mask, shift = self.mask, _shift_of(self.mask)

        # ★行 y まで進む（`$E074`-`$E07E`）
        index, row = 0, 0
        while row < y:
            if base + index >= len(self.prg):
                return None                  # ⚠ 読み切れない（★埋めない）
            if self.prg[base + index] & ROW_END_BIT:
                row += 1
            index += 1

        # ★その行を x まで進む（`$E081`-`$E095`）
        position = -1
        while True:
            if base + index >= len(self.prg):
                return None
            value = self.prg[base + index]
            position += (value & mask) + 1
            if position >= x:
                return (value & 0x7F) >> shift
            if value & ROW_END_BIT:
                return CORRIDOR              # ⚠ 行を越えた（`$E097: LDX #$00`）
            index += 1

    def grid(self) -> list:
        """★`[y][x]` の格子。⚠ 読めないマスは None。"""
        return [[self.region_at(x, y) for x in range(self.width)]
                for y in range(self.height)]

    def regions(self) -> dict:
        """★区画番号 → そのセルの一覧。

        ⚠⚠ **同じ番号が離れた場所で使い回されます。**
          番号はダンジョンで 3 ビット（0-7）しかないためです。
          ★「1 つの部屋」が欲しいときは `rooms()` を使ってください。
        """
        out: dict = {}
        for y in range(self.height):
            for x in range(self.width):
                value = self.region_at(x, y)
                if value is None:
                    continue
                out.setdefault(value, []).append((x, y))
        return out

    def rooms(self) -> list:
        """★つながったかたまりごとに分ける（**1 つの部屋 = 1 件**）。

        ⚠⚠ 2026-08-03、map `$40` の区画 7 が `(0,0)(1,0)(0,1)` と
          `(0,10)(1,10)` の**2 か所**に分かれていました。
          ★番号が足りないので、離れた部屋で使い回されています。

        ⚠ 通路（区画0）は分かれていて当たり前なので、**まとめません**
          （★呼ぶ側が必要なら分けてください）。

        戻り値は `[(区画番号, [(x, y), ...]), ...]`。
        """
        out = []
        for region_id, cells in sorted(self.regions().items()):
            if region_id == CORRIDOR:
                out.append((region_id, list(cells)))
                continue
            remaining = set(cells)
            while remaining:
                stack, group = [remaining.pop()], []
                while stack:
                    x, y = stack.pop()
                    group.append((x, y))
                    for near in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if near in remaining:
                            remaining.discard(near)
                            stack.append(near)
                out.append((region_id, sorted(group)))
        return out


def load(prg: bytes, map_id: int) -> RegionMap:
    """ヘッダから区画データを読む。⚠ 無くても `RegionMap` は返します。"""
    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    kind = (0 if map_id == 0x01 else
            1 if map_id < 0x2B else 2 if map_id < 0x44 else 3)
    return RegionMap(map_id=map_id, kind=kind,
                     pointer=prg[off + 5] | (prg[off + 6] << 8),
                     width=prg[off + 1] + 1, height=prg[off + 2] + 1,
                     prg=prg)


def to_dict(region_map: RegionMap, current=None, visited=None) -> list:
    """★依頼者の指定した形で出す。

    `current` はプレイヤーのいる区画番号（⚠ 分からなければ None）。
    `visited` は行ったことのある区画番号の集合。
    """
    out = []
    for region_id, cells in sorted(region_map.regions().items()):
        out.append({
            "region_id": region_id,
            "cells": [list(c) for c in cells],
            "visibility": {
                # ⚠ 分からないものは None（★False と混ぜない）
                "current": (None if current is None else region_id == current),
                "visited": (None if visited is None else region_id in visited),
                "revealed": False,
            },
            "source": {"rom": [f"header byte5/6 -> ${region_map.pointer:04X}"],
                       "ram": ["$1D"] if current is not None else []},
            "confidence": "confirmed",
        })
    return out
