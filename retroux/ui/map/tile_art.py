"""タイルの絵を読む（2026-08-01 / 課題 #65）。

依頼者:
    > ダンジョンの土と壁が複雑ないろなので分かりづらい。
    > キャラクタパターンを作って、切り替わらないようにすると良いかと思う。
    > 元のパターンから倍率毎の大きさのパターンを

    > 俺的にはタイル拡大表示だと思っていたのだが。

★★ **1マス = 1色 をやめ、実際の絵を拡大して描く。** ★★

## どこから来るか

`bridge.lua` の `_dump_tile_art` が、初めて見たタイルの 8×8 を
**画面の画素から**読んで `work/generated/tile_art.txt` へ追記します。

    マップID:タイルID<TAB>RRGGBB を 64 個つないだもの

⚠ CHR（パターンテーブル）ではなく**画面**から読んでいます。
  CHR は 0..3 の番号しか無く、色にするにはパレットと属性テーブルを
  組み合わせる必要があり、間違えると別の色になります。
  ★画面の画素なら**実際に出ている色**そのものです。

⚠ 主人公はスプライトなので、その周りのマスは読んでいません
  （読むと**服の色**が地形として入ります）。
"""

from __future__ import annotations

import pathlib

#: 1タイルの一辺（画素）。★`bridge.lua` の間引きと揃える
TILE_SIDE = 8


def load(path) -> dict[tuple[int, str], list[str]]:
    """`{(マップID, タイルID): ["RRGGBB", ...64個]}` を読む。

    ★無くても動く（絵が無ければ、これまでどおり色で描く）。
    ⚠ 壊れた行は**黙って飛ばす**が、読めた行は使う。
      1行おかしいだけで全部を捨てない。
    """
    if path is None:
        return {}
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    out: dict[tuple[int, str], list[str]] = {}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        if "\t" not in line:
            continue
        key, art = line.split("\t", 1)
        if ":" not in key:
            continue
        map_hex, tile_hex = key.split(":", 1)
        try:
            map_id = int(map_hex, 16)
        except ValueError:
            continue
        need = TILE_SIDE * TILE_SIDE * 6
        if len(art) != need:
            continue
        out[(map_id, tile_hex.upper())] = [art[i:i + 6]
                                           for i in range(0, need, 6)]
    return out


def average(pixels: list[str]) -> str | None:
    """その絵の**平均の色**（倍率が小さくて模様を描けないとき用）。

    ⚠ 中心の1画素ではなく**平均**。中心だけだと、洞窟の床
      （黒地に赤い点）が「ほぼ黒」になる（実測 88%）。
    """
    if not pixels:
        return None
    r = g = b = 0
    for px in pixels:
        try:
            r += int(px[0:2], 16)
            g += int(px[2:4], 16)
            b += int(px[4:6], 16)
        except ValueError:
            return None
    n = len(pixels)
    return f"{r // n:02X}{g // n:02X}{b // n:02X}"
