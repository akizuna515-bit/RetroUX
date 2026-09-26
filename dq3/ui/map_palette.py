"""地図の色（RX3-0023 / 2026-08-29）。

★★ ここは**仮色**です ★★

⚠⚠ 実ゲームの色ではありません（指示書 §9「見た目をそれっぽくしない」）。
  ★地形を**見分けられる**ことだけが目的です。

## ★どうやって決めたか

⚠ 機械的に割り当てた色（`dq3rom/world_map.logical_palette`）は、
海が真っ青・草原が砂色…と**実際と食い違って読みにくい**ものでした。

★そこで、依頼者のセーブステートの画面から
**升 1 つ（16x16 ピクセル）の平均色**を採りました。

```text
世界地図（世界に居るセーブ 7 個 / ⚠ 窓の中は除いた）
   0  #042C33   165 升   ★海
   2  #398A20   423 升   ★草原
   3  #22590D   178 升
   4  #24450E   187 升
   5  #090B02    51 升   ⚠ ほぼ黒（★暗い所で採ったため当てにならない）
   6  #060705    56 升   ⚠ 同上
```

⚠ 平均はどれも**暗い**（★ファミコンの絵は黒い縁取りが多い）ので、
小さく描くと潰れます。→ ★明るさを持ち上げてから使います。

## ⚠⚠ 分かっていないこと

```text
⚠ 地形の**意味**（海・草原・森…）は資料に無い。★色の実測だけが根拠
⚠ ローカル地図は tileset ごとに同じ番号が別の地形になる
   → ★地図 9 だけ実測。他は**共通の仮色**を当てる
⚠ 実測できていない番号は、番号から機械的に色を作る（★見分けるため）
```
"""

from __future__ import annotations

#: ★明るさの持ち上げ（⚠ 実測の平均は暗くて、小さく描くと潰れる）
LIFT = 1.45
FLOOR = 44


def _lift(hexcolour: str) -> tuple[int, int, int]:
    """★暗い実測色を、見える明るさへ持ち上げる。"""
    r = int(hexcolour[1:3], 16)
    g = int(hexcolour[3:5], 16)
    b = int(hexcolour[5:7], 16)
    out = []
    for v in (r, g, b):
        v = int(v * LIFT)
        out.append(max(0, min(255, v)))
    if max(out) < FLOOR:
        # ⚠ まっ黒に近いものは、★見えるところまで持ち上げる
        out = [max(v, FLOOR) for v in out]
    return tuple(out)


#: ★世界地図（⚠ 実測。`work/dq3-probe` のセーブ 7 個ぶん）
WORLD_MEASURED = {
    0: "#042C33",     # ★海
    2: "#398A20",     # ★草原
    3: "#22590D",
    4: "#24450E",
    5: "#090B02",     # ⚠ 暗い所で採った（当てにならない）
    6: "#060705",     # ⚠ 同上
    8: "#111143",
    9: "#5D4876",
    10: "#314F34",
    11: "#2F4A2A",
}

#: ★tileset 05（⚠ 実測は地図 9 だけだが、★同じ tileset は 9 件ある:
#:   1 / 2 / 9 / 12 / 17 / 22 / 32 / 70 / 85）
#:
#: ⚠⚠ **同じ番号でも tileset が違えば別の地形**。だから tileset で分ける。
TILESET_MEASURED = {0x05: {
    8: "#6A2C50",
    10: "#5E4E57",
    11: "#5F5F5F",    # ★壁
    14: "#79572A",
    20: "#5978A7",
    24: "#8E713F",    # ★道
    25: "#407E02",
    26: "#348B02",
    28: "#2D78E5",    # ★水
    29: "#7FCE0A",    # ★草
}}

#: ⚠ 昔の名前（★消さずに残す。外から見ている検査がある）
LOCAL9_MEASURED = TILESET_MEASURED[0x05]

#: ★居場所の種別（⚠ `dq3/knowledge/seen_map.py` と同じ値）
KIND_WORLD = 0
KIND_LOCAL = 1
KIND_ALEFGARD = 2


def _generic(tile: int) -> tuple[int, int, int]:
    """実測していない番号の色。

    ⚠ 「それっぽく」しない。★**隣どうしが見分けられる**ことだけを狙う。
    """
    # ★色相を番号でぐるぐる回す（⚠ 32 種を等間隔に）
    hue = (tile * 11) % 32
    table = [
        (150, 90, 80), (150, 120, 80), (140, 145, 80), (110, 150, 85),
        (85, 150, 100), (80, 145, 135), (80, 125, 155), (95, 100, 155),
    ]
    base = table[hue % len(table)]
    # ⚠ 同じ色相でも番号で明るさを変える（★8 種を超えても見分く）
    shade = 0.75 + 0.25 * ((tile // 8) % 2)
    return tuple(int(v * shade) for v in base)


def palette(kind: int, map_id=None, tileset=None) -> dict:
    """その地図の「地形の番号 → RGB」。

    ⚠ 実測があるものは実測を使い、★無いものは機械的な色を当てます。

    ⚠⚠ ローカルは **tileset** で分けます（★同じ番号でも tileset が違えば
      別の地形）。`tileset` が分からないときは、⚠ 地図 9 だけ特別扱いします
      （★互換のため。分かるなら必ず渡してください）。
    """
    measured = {}
    if kind in (KIND_WORLD, KIND_ALEFGARD):
        measured = WORLD_MEASURED
    elif kind == KIND_LOCAL:
        if tileset is not None:
            measured = TILESET_MEASURED.get(int(tileset), {})
        elif map_id == 9:
            measured = TILESET_MEASURED[0x05]
    out = {}
    for tile in range(32):
        got = measured.get(tile)
        out[tile] = _lift(got) if got else _generic(tile)
    return out
