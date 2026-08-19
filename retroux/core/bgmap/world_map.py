"""世界地図の最小デコーダ（2026-08-02 / Phase 7 の試作）。

★★ 2026-08-11: 地図の描画に**繋がりました**（`world_art.py` 経由）★★

  ここは**地形ID を出すところまで**です。絵と色は `world_art.py`。
  ⚠ 街・ダンジョンの共通処理へは**混ぜません**（依頼者の指示）。
  ★`dungeon_map.py` からは呼びません（テストで固定）。

## ★ 世界地図だけが通る道（`$DDD6: LDA $1F / BEQ $DDDD`）

```
DED4: LDA #$00 / STA $0F / ASL $0E / ROL $0F   ; ★y * 2（16 ビット）
DEDC: ADC $DD9B / ADC $DD9C                    ; ★★行ポインタ表の先頭を足す
DEEB: LDA ($0E),Y → $10 / INY → $11            ; ★★その行の先頭アドレス
DEF6: LDA $0C / CMP #$80 / BCC $DF26           ; ★x < $80 なら正順
DEFC: EOR #$FF / STA $0C                       ; ★★x >= $80 は左右反転
```

★`$DD9B`/`$DD9C` の実データは `C0 9C` すなわち **`$9CC0`**。

## ★★ 行ポインタ表は bank3

⚠ `$9CC0` は `$8000`-`$BFFF`（差し替えバンク）なので、どのバンクかは
アドレスだけでは決まりません。★**中身で決めました**:

| bank | `$9CC0` から 6 件 | |
| --- | --- | --- |
| 3 | `$9EC2 $9ECA $9ED2 $9EDC $9EE9 $9EFB` | ★単調増加 |
| 他 | ばらばら | ⚠ |

★しかも **256 行 × 2 バイト = 512** なので `$9CC0 + $200 = $9EC0`。
最初の行データが `$9EC2` で、**ぴったり続いています**。

## ★ ランレングス（`$DF26`-`$DF4E` / `$DF00`-`$DF23`）

```
DF26: DEY / STY $0D           ; ★位置 = 0
DF29: LDA ($10),Y / INC $0D   ; ★1 バイト読んで位置 +1
DF2D: AND #$E0 / BEQ $DF3A    ; ★上位3bit が 0 なら 1 マスぶん
DF31: AND #$1F / ADC $0D      ; ★★非 0 なら「下位5bit」ぶん余計に進む
DF3A: LDA $0C / CMP $0D / BCC $DF44   ; ★x に届いたか
DF40: INY / JMP $DF29
DF44: LDA ($10),Y / AND #$E0 / BNE $DF76
DF4A: AND #$1F / STA $0C      ; ★上位3bit が 0 → 地形は**下位5bit**
DF76: LSR ×5 / BCC $DF4E      ; ★★非 0 → 地形は **b >> 5**（0-7）
```

⚠⚠ **同じバイトでも、繰り返しかどうかで読む場所が変わります。**

- 上位3bit が 0: そのマス 1 つぶん。地形 = `b & $1F`（0-31）
- 上位3bit が非0: `1 + (b & $1F)` マスぶん。地形 = `b >> 5`（0-7）

★`$DF7B: BCC $DF4E` は必ず成立します（`AND #$E0` 済みなので bit4 は 0）。

## ⚠ 特別扱い（`$DF50`-`$DF71`）

```
DF50: LDA $05F8 / BEQ         ; ⚠ 何かの旗
DF55: LDA $12 / CMP #$B2 / CMP #$B9   ; ★x が $B2-$B8
DF5F: LDA $13 / CMP #$A3 / CMP #$AC   ; ★y が $A3-$AB
DF69: LDA $0C / CMP #$13 / BCC
DF6F: LDA #$04 / STA $0C      ; ★地形 $13 以上を $04 に変える
```

⚠ `$05F8` が何かは **unknown** です。★ここでは**再現しません**
（`special_region()` で「当てはまるか」だけ答えます）。

## ⚠ 壁向き補正について

★`$DE29`-`$DE9B`（`wall_shape.py`）は**この経路でだけ**使われます。
⚠ ここではまだ当てていません（★まず素の地形を出して確かめる段階）。
"""

from __future__ import annotations

#: ★世界地図の `map_id`
WORLD_MAP_ID = 0x01
#: ★幅も高さも 256（ヘッダは `$FF` すなわち 255 + 1）
WORLD_SIZE = 256

#: ★行ポインタ表（`$DD9B`/`$DD9C` の実データ）
ROW_POINTER_TABLE = 0x9CC0
#: ★★どのバンクにあるか。中身が単調増加であることから決めた
ROW_POINTER_BANK = 3
#: 差し替えバンクの載る位置
SWAPPABLE_ORIGIN = 0x8000
BANK_SIZE = 0x4000

#: ★左右反転が始まる x（`$DEF8: CMP #$80`）
MIRROR_FROM = 0x80

#: ⚠ 特別扱いの範囲（`$DF55`-`$DF67`）。★再現はしません
SPECIAL_X = range(0xB2, 0xB9)
SPECIAL_Y = range(0xA3, 0xAC)
SPECIAL_MIN_TERRAIN = 0x13
SPECIAL_REPLACEMENT = 0x04


class WorldMapError(Exception):
    """⚠ 読めないときに投げます（★黙って 0 を返しません）。"""


def _bank_offset(address: int, bank: int = ROW_POINTER_BANK) -> int:
    return bank * BANK_SIZE + address - SWAPPABLE_ORIGIN


def row_pointer(prg: bytes, y: int) -> int:
    """★その行のデータが始まるアドレス。⚠ 範囲外は例外。"""
    if not 0 <= y < WORLD_SIZE:
        raise WorldMapError(f"⚠ y={y} は 0-{WORLD_SIZE - 1} の外です")
    off = _bank_offset(ROW_POINTER_TABLE) + y * 2
    return prg[off] | (prg[off + 1] << 8)


def row_length(prg: bytes, y: int) -> int:
    """★その行のバイト数（★次の行の先頭との差）。

    ⚠ 最後の行は次が無いので、`row_pointer` の並びからは測れません。
      その場合は `None` を返します（★`measured_row_length` を使ってください）。
    """
    if y + 1 >= WORLD_SIZE:
        return None
    return row_pointer(prg, y + 1) - row_pointer(prg, y)


def measured_row_length(prg: bytes, y: int, limit: int = 64):
    """★展開して「幅ぶん埋まる」ところまで数えたバイト数。

    ⚠⚠ **推測ではありません。** 幅が `WORLD_SIZE`（256）と
      ヘッダで分かっているので、そこに達したところが行の終わりです。

    ★2026-08-03、最後の行 `y=255` は `$B81A` から `9F` が 8 個で、
      `($9F & $1F) + 1 = 32` マス × 8 = **ちょうど 256** でした。
      その次（`$B822`）からは別のデータ（`09 00 0B 00 …`）が始まります。

    ⚠ 幅に届かないまま `limit` を超えたら `None`（★埋めません）。
    """
    base = _bank_offset(row_pointer(prg, y))
    position = 0
    for i in range(limit):
        if base + i >= len(prg):
            return None
        value = prg[base + i]
        position += 1
        if value & 0xE0:
            position += value & 0x1F
        if position >= WORLD_SIZE:
            return i + 1
    return None                          # ⚠ 届かなかった（★推測しない）


def effective_row_length(prg: bytes, y: int):
    """★使う長さ。次の行があればその差、無ければ数えた値。"""
    length = row_length(prg, y)
    return measured_row_length(prg, y) if length is None else length


def _walk(prg: bytes, start: int, count: int, target: int, backwards: bool):
    """★ランレングスを進んで、`target` に届いたバイトを返す。

    `backwards` は `$DF00` 経路（`x >= $80` を反転したあと）。
    ⚠ 届かなければ `None`（★最後のバイトで埋めません）。
    """
    base = _bank_offset(start)
    position = 0
    order = range(count - 1, -1, -1) if backwards else range(count)
    for i in order:
        value = prg[base + i]
        position += 1
        if value & 0xE0:
            position += value & 0x1F
        if target < position:
            return value
    return None


def terrain_at(prg: bytes, x: int, y: int):
    """★世界地図のそのマスの地形ID。⚠ 読めなければ None。

    ★`$DEF6` のとおり、`x >= $80` は `EOR #$FF` で折り返します。
    """
    if not (0 <= x < WORLD_SIZE and 0 <= y < WORLD_SIZE):
        return None
    length = effective_row_length(prg, y)
    if length is None or length <= 0:
        return None                      # ⚠ 測れない行（★埋めない）
    mirrored = x >= MIRROR_FROM
    target = (x ^ 0xFF) if mirrored else x
    value = _walk(prg, row_pointer(prg, y), length, target, mirrored)
    if value is None:
        return None                      # ⚠ 行が足りない（★埋めない）
    # ★★上位3bit が 0 なら下位5bit、非0 なら b >> 5（`$DF44`-`$DF7B`）
    return (value >> 5) if (value & 0xE0) else (value & 0x1F)


def special_region(x: int, y: int, terrain_id: int) -> bool:
    """⚠ `$DF50`-`$DF71` の特別扱いに当てはまるか。

    ★**当てはまるかを答えるだけ**で、置き換えはしません
      （`$05F8` が何か分かっていないため）。
    """
    return (x in SPECIAL_X and y in SPECIAL_Y
            and terrain_id is not None and terrain_id >= SPECIAL_MIN_TERRAIN)


def decode_grid(prg: bytes, size: int = WORLD_SIZE) -> list:
    """★全体を `[y][x]` の格子にします。⚠ 読めないマスは None。"""
    return [[terrain_at(prg, x, y) for x in range(size)]
            for y in range(size)]


def coverage(grid) -> dict:
    """★どれだけ読めたか。⚠ 「描けた」だけで正しいとしないための材料。"""
    total = sum(len(row) for row in grid)
    unread = sum(1 for row in grid for v in row if v is None)
    tally: dict = {}
    for row in grid:
        for value in row:
            if value is not None:
                tally[value] = tally.get(value, 0) + 1
    return {"total": total, "unread": unread, "read": total - unread,
            "terrain_ids": dict(sorted(tally.items()))}
