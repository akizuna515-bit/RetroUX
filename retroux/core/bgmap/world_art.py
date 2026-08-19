"""世界地図を **ROM の絵**で描く（2026-08-11）。

★★★ **「見た範囲だけ／色は ROM から」**（依頼者の決定）★★★

  ⚠ これまで世界地図の色は、**画面のピクセルを1マス1点ずつ**拾っていました。
    暗転・フェード・窓が重なった一瞬を拾うと、そのマスは黒いまま残ります
    （2026-08-11 の「黒塗り」）。★色を ROM から作れば、原理的に起きません。

  ⚠⚠ **開示は増えません。** どのマスを描くかは、これまでどおり
    「見たマス」の記録だけで決めます（指示書 §2.2）。
    ここが持っているのは **絵（見た目）だけ**です。

## ★★ 地形ID → メタタイル（2026-08-11 に確定）★★

★材料は**すでに全部そろっていました**。繋いだだけです。

| もの | どこ | 根拠 |
| --- | --- | --- |
| 地形ID（0-31） | `world_map.decode_grid` | 行ポインタ＋RLE。★256×256 を 100% |
| 壁向き補正 | `wall_shape.wall_shape` | `$DE29`-`$DE9B`。★**世界地図専用** |
| 地形ID → タイル4枚＋属性 | `$83B3` から 5 バイト × 32 件 | `$DD64` / `$DC6F` の種別0 |
| CHR とパレット | `rom_tiles.chr_for_map(prg, …, $01)` | 索引0 = `world_map` |

```
DD64: LDA $1F / ASL / TAY           ; ★種別*2 → $DC6F,Y = $83B3（種別0）
DD68: LDA $0C / ASL / ASL / ADC $0C ; ★索引 * 5
```

★1 件 = `[タイルID ×4][属性]`。並びは **左上・右上・左下・右下**、
パレット組は属性の下位2ビット。

## ★★ 答え合わせ（2026-08-11 / 実測 21,215 マス）★★

⚠ 「描けた」だけで正しいとしないため、**遊んで見た絵**と突き合わせました
（`research/probes/active/world_metatile_check.py`）。

- 地形IDごとに**実測で一番多かった4枚**を数えると、
  **n≥20 の 22 種すべてで ROM の表と1バイトも違わず一致**しました。
  ★壁向き補正でしか出てこない索引 `$14`-`$1B`（海岸線の角）も含みます。
- パレット組も 4 組すべて一致（実測 6,700 件）。
- ⚠ マス単位の完全一致は 63.3%（確度 `confirmed` に限れば 85.4%）。
  ★足りないぶんは**記録側の揺れ**です（`map_seen_cells` は 15 フレーム
  分の使い回しがあり、歩いている最中の1枚が最初に入ると
  `record_metatile` は**上書きしません**）。⚠ ROM 側の話ではありません。

## ⚠ 端は「巻き戻る」

`$DE3A: LDA $DEC8,Y / CLC / ADC $12` は **8 ビットの足し算**です。
★近傍を見るとき x=255 の右隣は x=0 になります（ここでも同じにします）。

## ⚠ ここでやらないこと

- **宝箱・扉の差し替え**（`$DFF1`-`$E03A`）。★あれは `$DF7D` の道
  （街・ダンジョン）だけで、世界地図は通りません。
  ⚠ 世界地図の `$14` は「海岸線の角」であって宝箱ではありません。
- `$DF50`-`$DF71` の特別扱い（`$05F8` が何か不明）。★`world_map` の
  `special_region()` で「当てはまるか」だけ分かります。
"""

from __future__ import annotations

import dataclasses

from . import wall_shape as _wall
from . import world_map as _world
from .dungeon_map import BANK2, TABLE_ENTRIES, TABLE_ENTRY, TERRAIN_TABLES
from .rom_tiles import MAP_HEADER, MAP_HEADER_SIZE

#: ★世界地図の `map_id`（種別0）
WORLD_MAP_ID = _world.WORLD_MAP_ID
#: ★マップ種別（`$E20C`）
WORLD_KIND = 0
#: ★5バイト変換表の先頭（`$DC6F` の種別0 / bank2）
TERRAIN_TABLE = TERRAIN_TABLES[WORLD_KIND]
#: ★件数（次の表 `$8453` との差 160 = 32×5）
TERRAIN_COUNT = TABLE_ENTRIES[WORLD_KIND]
#: 幅も高さも 256（★ヘッダ byte1/2 が `$FF` = 255 + 1）
WORLD_SIZE = _world.WORLD_SIZE


class WorldArtError(Exception):
    """⚠ 読めないときに投げます（★黙って 0 を返しません）。"""


@dataclasses.dataclass(frozen=True)
class WorldCell:
    """世界地図の1マス（★16×16 画素ぶん）。"""

    x: int
    y: int
    #: ★素の地形ID（RLE から。壁向き補正の**前**）
    terrain_id: int
    #: ★変換表の索引（壁向き補正の**後**）
    index: int
    #: タイルID 4枚（左上・右上・左下・右下）
    tile_ids: tuple
    #: パレット組（0-3）
    attribute: int


def table_entry(prg: bytes, index: int) -> tuple[tuple, int]:
    """変換表の1件 `(タイル4枚, パレット組)`。⚠ 表の外は例外。

    ⚠⚠ **丸めません。** 索引が 32 件を超えたら、それは
      「まだ分かっていないことがある」の合図です。★黙って 0 番を返すと、
      間違った絵が正しい絵の顔で出てきます。
    """
    if not 0 <= index < TERRAIN_COUNT:
        raise WorldArtError(
            f"⚠ 索引 ${index:02X} は世界地図の表（{TERRAIN_COUNT} 件）の外です")
    base = BANK2 + TERRAIN_TABLE - 0x8000 + index * TABLE_ENTRY
    if base + TABLE_ENTRY > len(prg):
        raise WorldArtError(f"⚠ PRG が短すぎます（${base:05X}）")
    return tuple(prg[base:base + 4]), prg[base + 4] & 3


def header_size(prg: bytes) -> tuple[int, int]:
    """ヘッダが言う世界地図の大きさ。★`$FF`+1 で 256×256。

    ⚠ 設定で補っていた値（実測 256×256）と同じであることを確かめる用。
    """
    off = MAP_HEADER + WORLD_MAP_ID * MAP_HEADER_SIZE
    if off + MAP_HEADER_SIZE > len(prg):
        raise WorldArtError("⚠ ヘッダ表の外です")
    return prg[off + 1] + 1, prg[off + 2] + 1


class WorldArt:
    """世界地図ぜんぶ（★地形と、そのマスの絵）。

    ⚠ 作るのに 0.3 秒ほどかかります（256×256 の展開と壁向き補正）。
      ★**使い回してください**。描くたびに作り直さないこと。
    """

    def __init__(self, prg: bytes, size: int = WORLD_SIZE) -> None:
        self.prg = prg
        self.size = size
        #: ★素の地形ID `[y][x]`。⚠ 読めないマスは None
        self.terrain = _world.decode_grid(prg, size)
        #: ★壁向き補正まで済ませた索引 `[y][x]`
        self.index = [[self._wall_shaped(x, y) for x in range(size)]
                      for y in range(size)]
        #: 索引 → `(タイル4枚, パレット組)`。★32 件しかないので先に引く
        #:   （⚠ 2万マスぶん毎回 PRG を切り出すと、描くたびに 0.1 秒かかる）
        self.entries = {i: table_entry(prg, i) for i in range(TERRAIN_COUNT)}

    # --- 地形 -----------------------------------------------------------

    def _terrain_wrapped(self, x: int, y: int):
        """⚠ 端は巻き戻る（`ADC $12` は 8 ビット）。"""
        return self.terrain[y % self.size][x % self.size]

    def _wall_shaped(self, x: int, y: int):
        value = self.terrain[y][x]
        if value is None:
            return None                    # ⚠ 読めないマスは埋めない
        return _wall.wall_shape(self._terrain_wrapped, x, y)

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size

    def terrain_at(self, x: int, y: int):
        """素の地形ID。⚠ 枠の外・読めないマスは None。"""
        return self.terrain[y][x] if self.inside(x, y) else None

    def index_at(self, x: int, y: int):
        """変換表の索引（壁向き補正の後）。⚠ 枠の外は None。"""
        return self.index[y][x] if self.inside(x, y) else None

    # --- 絵 -------------------------------------------------------------

    def cell_at(self, x: int, y: int):
        """そのマスの `WorldCell`。⚠ 枠の外・読めないマスは None。"""
        index = self.index_at(x, y)
        if index is None:
            return None
        tiles, group = self.entries[index]
        return WorldCell(x=x, y=y, terrain_id=self.terrain[y][x],
                         index=index, tile_ids=tiles, attribute=group)

    def cells(self, visited):
        """**見たマスだけ**の `WorldCell` の並び（指示書 §2.2）。

        ⚠ `visited` は `(x, y)` の集まり。★渡さないと何も返しません
          （「全部返す」を既定にしないこと。開示を増やす道を作らない）。
        """
        out = []
        for x, y in sorted(visited or ()):
            cell = self.cell_at(x, y)
            if cell is not None:
                out.append(cell)
        return out

    def used_indices(self) -> dict:
        """索引ごとのマス数。★どの絵が要るかを先に知るため。"""
        tally: dict = {}
        for row in self.index:
            for value in row:
                if value is not None:
                    tally[value] = tally.get(value, 0) + 1
        return dict(sorted(tally.items()))


# --- ★ 1マス1色（ミニマップ用）------------------------------------------

def average_rgb(rows) -> tuple[int, int, int]:
    """16×16 の平均色。

    ★★ **なぜ平均なのか** ★★
      1マスが 4 画素しかない縮尺では、絵は置けません。★依頼者の指示書
      「**画面の縮小イメージに近い見え方**」に一番近いのは、
      16×16 を1画素へ縮めたときの色＝平均です。

    ⚠⚠ **最頻色ではありません。** 一度そちらで試したところ、森・山・林の
      7 種が**真っ黒**になりました（輪郭線の黒が一番多いため）。
      ★それでは「黒塗り」を作り直すことになります。

    ⚠ `characters.scale_nearest` が 0.5 倍で平均を禁じているのとは
      **別の話**です。あちらは 8×8 の絵として読ませるためのもので、
      ここは 1 画素の代表色です。
    """
    n = 0
    total = [0, 0, 0]
    for row in rows:
        for pixel in row:
            for i in range(3):
                total[i] += pixel[i]
            n += 1
    if not n:
        raise WorldArtError("⚠ 画素がありません")
    return tuple(v // n for v in total)


def terrain_colors(prg: bytes, map_tiles, nes_palette) -> dict:
    """索引 → `(r, g, b)`。★32 件ぶん一度に作ります。

    `map_tiles` は `rom_assets.RomTileSource.for_map($01)` の戻り
    （CHR とパレット）。⚠ 表の外は作りません（32 件だけ）。
    """
    out = {}
    for index in range(TERRAIN_COUNT):
        tiles, group = table_entry(prg, index)
        out[index] = average_rgb(
            map_tiles.metatile(tiles, group).rgba(nes_palette))
    return out


def hex_color(rgb) -> str:
    """`(r, g, b)` を `"RRGGBB"` にする。★地図の色はこの形で渡します。

    ⚠ 昔からの色は 1 成分 4 ビットの3文字（`"RGB"`）でした。
      ★ROM の色は 8 ビットそのままなので、**丸めずに6文字**で渡します
      （`ui/map/canvas.py` の `tile_color` が両方を読みます）。
    """
    r, g, b = rgb
    return f"{r:02X}{g:02X}{b:02X}"
