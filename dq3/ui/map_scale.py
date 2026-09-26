"""地図の 1 升を何ピクセルで出すか（RX3-0043 → RX3-0045 / 2026-09-01）。

## ⚠⚠ 「窓に合わせて縮める」をやめました（RX3-0045）

★はじめは、はみ出すぶんを縮めていました。
⚠ 48x48 の地図が 768px → 610px に縮み、**タイルがにじみます**。

→ ★DQ2 と同じにします（依頼者「スクロールバー対応を DQ2 でやった」）。

```text
1 升の px は**固定**    ⚠ 枠の大きさで変えない
収まらなければスクロール  ★縮めない
```

## ★1 升を何 px にするか

```text
世界地図・アレフガルド   8px   ★依頼者「一番小さいブロックで丁度いい」
ローカル                16px   ★タイルの等倍（⚠ 画素を捨てない）
```

⚠ DQ2 の `CELL_PIXELS` は `(8, 16, 32, 64)` で、★一番小さいのが 8px です
（`retroux/ui/map/metatile_renderer.py`）。★同じ考え方で並べてあります。

## ⚠⚠ 枠の大きさを**見ません**

★DQ2 は 2026-08-18 にここで穴に落ちています:

```text
1: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
2: 枠内側 323x393 / widget 323x393 / 収める   / 倍率 None
3: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
```

⚠ widget を枠へ伸ばしてから「入るか」を測ると、★測るたびに前提が変わり、
  依頼者の画面で**青と地形が点滅**しました。

→ ★ここは **地図の種別だけ**で決めます。⚠⚠ 構造として振動しません。

## ★ここが唯一の置き場（指示書 §10）

⚠ 倍率を描画コードに散らさないこと。★将来 `-` / `100%` / `+` を足すときは、
`zoom` を動かすだけで済むようにしてあります。

## ⚠ 数字は仮です

指示書 §8:

> 数値は固定仕様ではない。実画面をキャプチャして DQ2 と比較し、
> 人間が見て自然なサイズに調整すること。
"""

from __future__ import annotations

#: ★タイルの絵そのものの大きさ（⚠ `tile_art.CELL` と同じ）
SOURCE_CELL = 16

#: ★選べる 1 升の大きさ（⚠ DQ2 は `(8, 16, 32, 64)`）
#:
#:   ⚠ 半端な倍率は使いません（★DQ2 の「余白を埋めるより、ドット感を保つ」）。
CELL_PIXELS: tuple[int, ...] = (4, 8, 16, 32)

#: ★居場所の種別（⚠ `dq3.knowledge.terrain` と同じ値）
KIND_WORLD, KIND_LOCAL, KIND_ALEFGARD = 0, 1, 2

#: ★★ 世界地図の 1 升（⚠ 依頼者 2026-09-01「一番小さいブロックで丁度いい」）
#:
#:   ```text
#:   世界地図    256 x 256 升 x 8px = 2,048 px   ⚠ スクロールで見る
#:   アレフガルド 158 x 138 升 x 8px = 1,264 px
#:   ```
WORLD_CELL = 8

#: ★★ ローカルの 1 升（⚠ タイルの絵と 1:1。★縮めると画素を捨てる）
#:
#:   ⚠ 2026-09-01 に一度 8px にしてみて、★5x5 の場所が 40x40 px になり
#:     何が描いてあるか分かりませんでした（`RX3-0043`）。
LOCAL_CELL = SOURCE_CELL

#: ★★ 洞窟・塔（種別 5）の 1 升（RX3-0206 / 2026-09-12 依頼者「DQ3 ダンジョン探索MAP v1」§6）。
#:   ★細部ではなく、その階の形をつかむため、町より一段小さく（16 → 8 px）。⚠ 町・城・知らない種別は今のまま
KIND_DUNGEON = 5
DUNGEON_KINDS = (KIND_DUNGEON,)
DUNGEON_CELL = 8

#: ★★ 人が選べる 1 升の大きさ（RX3-0206 / ★ローカルの地図だけ。⚠ 世界地図は 8 px のまま）
SIZE_LEVELS: tuple[tuple[str, int], ...] = (("小", 8), ("標準", 16), ("大", 32))
SIZE_LABELS: tuple[str, ...] = tuple(name for name, _px in SIZE_LEVELS)

#: ⚠ 人が変えられる倍率（★いまは 1.0 固定。将来ここを動かす）
DEFAULT_ZOOM = 1.0

#: ⚠ 升をこれより小さくしない（★潰れて何も見えなくなる）
MIN_CELL = CELL_PIXELS[0]
#: ⚠ 大きくもしない（★引き伸ばしても情報は増えない）
MAX_CELL = CELL_PIXELS[-1]


def base_cell(kind) -> int:
    """★その種別の 1 升（⚠ 倍率をかける前）。

    ⚠ 知らない種別はローカル扱い（★真っ黒にするより出したほうがまし）。
    """
    if kind in (KIND_WORLD, KIND_ALEFGARD):
        return WORLD_CELL
    return DUNGEON_CELL if kind in DUNGEON_KINDS else LOCAL_CELL


def map_class(kind) -> str:
    """★地図の分類（world / dungeon / local）。★1 升の大きさは分類ごとに選ぶ（RX3-0206）。"""
    if kind in (KIND_WORLD, KIND_ALEFGARD):
        return "world"
    return "dungeon" if kind in DUNGEON_KINDS else "local"


def default_level(kind) -> str:
    """★最初の 1 升の大きさ（★洞窟・塔は「小」/ 町は「標準」/ RX3-0206）。"""
    return "小" if map_class(kind) == "dungeon" else "標準"


def level_zoom(kind, level) -> float:
    """★選んだ大きさ → `cell_px` に渡す倍率（⚠ 世界地図・知らない名前は 1.0）。"""
    if map_class(kind) == "world":
        return 1.0
    px = dict(SIZE_LEVELS).get(level)
    if px is None:
        return 1.0
    return px / base_cell(kind)


def cell_px(kind, *, zoom: float = DEFAULT_ZOOM) -> int:
    """★1 升を何 px で出すか。

    ⚠⚠ **枠の大きさを見ません**（★見ると振動します / 上の DQ2 の記録）。

    @param zoom ⚠ 人が変えた倍率（★将来のズーム用）
    """
    got = base_cell(kind) * float(zoom or 1.0)
    return max(MIN_CELL, min(MAX_CELL, int(round(got))))


def draw_size(kind, width: int, height: int, *,
              zoom: float = DEFAULT_ZOOM) -> tuple[int, int]:
    """★描いた絵を、画面上で何 px にするか（`(幅, 高さ)`）。

    ⚠ 窓に入らなければ**スクロール**します（★縮めません）。
    """
    px = cell_px(kind, zoom=zoom)
    return (max(0, int(width)) * px, max(0, int(height)) * px)


def image_scale(kind, *, tiled: bool, zoom: float = DEFAULT_ZOOM) -> float:
    """★作った絵を画面へ出すときの倍率。

    ```text
    タイル       絵の 1 升 = 16 px  →  ★1 升の px ÷ 16
    色ブロック   絵の 1 升 =  1 px  →  ★1 升の px そのもの
    ```

    ⚠⚠ ここを取り違えると、地形は正しいのに**印だけ 16 倍ずれます**
      （★2026-09-01 に実際にそうなった）。
    """
    unit = cell_px(kind, zoom=zoom)
    return unit / SOURCE_CELL if tiled else float(unit)
