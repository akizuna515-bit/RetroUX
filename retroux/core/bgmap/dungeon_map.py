"""ダンジョンの地形を ROM だけで描く（2026-08-02）。

★★★ **実コードから組み立てました。観測辞書ではありません。** ★★★

## ★★ 経路の分かれ目（`$DDD6`）

```
DDD6: LDA $1F / BEQ $DDDD    ; ★種別0（世界地図）だけ $DDDD へ
DDDA: JMP $DF7D              ; ★★街・ダンジョンは**全部こっち**
```

★★★ **`$DE29`（壁向き補正）と `$DED4`（行ポインタ＋ランレングス）は
世界地図専用です。ダンジョンでは呼ばれません。**

⚠⚠ 2026-08-02、私は `wall_shape()` をダンジョンにも当てていました。
★外したところ map `$40` が **92.2% → 96.7%** に上がりました。
  当たっていたのは「中心が `$04` 以外は素通し」という性質のためで、
  `$04` になるセルだけが**余計に書き換わって**いました。

## 処理順（すべて実コードの写し）

```
1. 線形に読む     ptr + y*(幅) + x             $DFA8-$DFD9  ★幅は $21+1
2. 値を取り出す   (生バイト & $E0) >> 3         $DFE8  ★ダンジョン（種別2以上）
                  生バイト & $1F                $DFE1  ★街（種別1）
3. 宝箱・扉       $051A / $052A と照合          $DFF1-$E038  → overlay.py
4. 象限を OR      | ((y&1)<<1 | (x&1))          $DDB0-$DDB8
5. 5バイト表      $DC6F[種別] + 索引*5          $DD64
6. 4枚＋属性      そのまま 2×2 に置く            $DCE5-$DD3F
```

⚠ **象限差分（`+8 / -2 / +6`）という段はありません。**
★索引に象限が入るので、表の別の行を引くだけです。

## ★ 実測（2026-08-02 / capture 41地点。★壁補正を外したあと）

```
map $40  単調 640/660 97.0%   ★非単調 1066/1102 96.7%
map $3D  単調 673/681 98.8%   ★非単調  310/ 374 82.9%
map $3E  単調 141/174 81.0%   ⚠ 非単調   91/ 167 54.5%
```

⚠ `$3E` は観測が **7地点・y は 2/4/5 の3種だけ**（マップ上端 10%）と
偏っています。★map 固有処理と断じるには材料が足りません。
"""

from __future__ import annotations

from .rom_tiles import MAP_HEADER, MAP_HEADER_SIZE
from .terrain_reader import HALVED_KIND, quadrant

#: bank2 が PRG のどこにあるか
BANK2 = 0x08000
#: 種別ごとの5バイト表の先頭（★`$DC6F` の実データ / bank2）
TERRAIN_TABLES = {0: 0x83B3, 1: 0x8453, 2: 0x851B, 3: 0x85E3}
#: ★表の件数（ROM 表の間隔から / 1 件 5 バイト）。
#: ⚠ 種別で違います。種別3 は次の値が逆行するため測れません。
TABLE_ENTRIES = {0: 32, 1: 40, 2: 40}
#: ★宝箱の地形ID（`$DFF1: CMP #$14`）。開封済みは `$051A` の8組
CHEST_TERRAIN = 0x14
#: ★扉の地形ID（`$E015`/`$E019`/`$E01D`）。開放済みは `$052A` の8組
DOOR_TERRAINS = (0x18, 0x19, 0x1A)
#: ★開封・開放されたマスが差し替わる値（`$E006: LDA #$00`）
OPENED_TERRAIN = 0x00
#: 1件のバイト数（タイル4枚 ＋ 属性）
TABLE_ENTRY = 5
#: ★論理セルの値を取り出すシフト（`$DFEC` の `LSR` ×3）
CELL_SHIFT = 3


def map_kind(map_id: int) -> int:
    """`$E20C` の写し。"""
    if map_id == 0x01:
        return 0
    if map_id < 0x2B:
        return 1
    if map_id < 0x44:
        return 2
    return 3


class DungeonMap:
    """1マップぶん。★ROM だけで絵が出せます。"""

    def __init__(self, prg: bytes, map_id: int) -> None:
        off = MAP_HEADER + map_id * MAP_HEADER_SIZE
        self.prg = prg
        self.map_id = map_id
        self.kind = map_kind(map_id)
        self.border = prg[off]
        self.width = prg[off + 1] + 1
        self.height = prg[off + 2] + 1
        self.pointer = prg[off + 3] | (prg[off + 4] << 8)

    @property
    def halved(self) -> bool:
        """★座標を 1/2 して象限を使うか（`$DD9F: CMP #$02`）。

        ⚠ 種別1（街）は 1 論理セル = 1 画面マスです。
        """
        return self.kind >= HALVED_KIND

    @property
    def screen_size(self) -> tuple[int, int]:
        """★画面のマスでの大きさ。種別2以上は論理セルの2倍。"""
        if self.halved:
            return (self.width * 2, self.height * 2)
        return (self.width, self.height)

    def raw(self, cx: int, cy: int):
        """★生バイト。⚠ 範囲外は None（0 と混ぜない）。"""
        if not (0 <= cx < self.width and 0 <= cy < self.height):
            return None
        addr = BANK2 + (self.pointer + cy * self.width + cx - 0x8000)
        if not 0 <= addr < len(self.prg):
            return None
        return self.prg[addr]

    def cell(self, cx: int, cy: int) -> int:
        """論理セルの値。⚠ 範囲外は境界タイル（`$DDC9` の写し）。

        ★種別で取り出し方が違います（`$DFDB: LDA $1F / CMP #$02`）:

        - 種別2以上: `(b & $E0) >> 3`（`$DFEA`）★4 刻み
        - 種別1:     `b & $1F`（`$DFE3`）
        """
        value = self.raw(cx, cy)
        if value is None:
            return self.border
        if self.halved:
            return (value & 0xE0) >> CELL_SHIFT
        return value & 0x1F

    def terrain_at(self, x: int, y: int) -> int:
        """★そのマスの**地形ID**（象限を混ぜる前）。

        ⚠ 壁向き補正は当てません（`$DDD6` により世界地図専用）。
        """
        if self.halved:
            return self.cell(x >> 1, y >> 1)
        return self.cell(x, y)

    def index_at(self, x: int, y: int) -> int:
        """`$DD64` に渡る索引（地形ID | 象限）。

        ⚠⚠ **`& $1F` をしません。**
        `$DD64` は `LDA $0C / ASL / ASL / ADC $0C` で 5 倍するだけで、
        マスクしません。★境界の外は `$20` すなわち `$24`（`$DDC9`）が
        入るので、索引は **$24-$27** になります。

        ★種別1/2 の表は **40 件**（`$8453`-`$851B` の差 200 = 40×5）
        なので、$24-$27 は**範囲内**です。丸めてはいけません。

        ⚠ 種別1（街）は象限を使いません（`$DD9F: BCC $DDBB`）。
        """
        if not self.halved:
            return self.terrain_at(x, y)
        return self.terrain_at(x, y) | quadrant(x, y)

    def metatile_at(self, x: int, y: int) -> tuple[tuple, int]:
        """その画面マスの `(タイル4枚, パレット組)`。"""
        base = (BANK2 + (TERRAIN_TABLES[self.kind] - 0x8000)
                + self.index_at(x, y) * TABLE_ENTRY)
        return tuple(self.prg[base:base + 4]), self.prg[base + 4] & 3
