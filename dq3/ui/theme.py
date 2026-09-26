"""下段の窓の配色（RX3-0111 / RX3-0112 / 2026-09-07）。

依頼者 2026-09-07:

    現在の黒背景ログ画面は白背景へ変更する。… 派手にしすぎない。
    （★モンスター表示領域も白地にしたい / RX3-0112）

## ⚠⚠ 色を 2 か所に書かない

★ログの窓（`battle_window.py`）とモンスターの帯（`monster_panel.py`）は
**別のファイル**ですが、⚠ 同じ窓の中に並びます。★配色はここ 1 か所に置きます。

## ⚠⚠ モンスターの絵だけは暗いままです

★絵の PNG は **RGB（透過なし）で背景が黒にベタ塗り**されています（実測）。
⚠ 白い札に直接載せると、**黒い四角が浮きます**。

```text
⚠ だめ  黒を透明にする  → ★輪郭の黒まで抜けて、絵に穴があく
★採用  絵の枠だけ暗くする → ⚠ 「ゲームの画面」として見える
```

★絵そのものは**1 ピクセルも触りません**（⚠ ROM から起こしたものを加工しない）。
"""
from __future__ import annotations

#: ★地色（⚠ 真っ白は目が疲れるので、ごく薄いグレー）
PAPER = "#fbfbf9"
#: ★札の地色（⚠ 帯より少しだけ明るくして、札の境目を出す）
CARD = "#ffffff"
#: ★枠線
BORDER = "#d8d8d2"
#: ★本文の字
INK = "#2b2d33"
#: ★添えの字（⚠ 本文より弱く、でも読める濃さ）
MUTED = "#5a606b"
#: ★数字・性能の字
STAT = "#3a3f47"
#: ★耐性・特技（⚠ 黒地の `#c9a86a` は白地では読めない）
ACCENT = "#8a5a00"

#: ⚠⚠ **絵の枠だけは暗いまま**（★上の註）。
ART_BACK = "#1c1f26"
ART_BORDER = "#333842"

#: ★白地で読める濃さの上限（⚠ 検査が使う）。
#:   ⚠ `ART_BACK` / `ART_BORDER` は**この決まりの外**です（★暗いのが目的）。
MAX_LUMA = 0.62


def luma(hex_colour: str) -> float:
    """★その色の明るさ（0..1）。⚠ 色名ではなく**明るさ**で見るために。"""
    text = hex_colour.lstrip("#")
    r, g, b = (int(text[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def mix(a: str, b: str, t: float) -> str:
    """★2 色のあいだの色（`t=0` で `a`、`t=1` で `b`）。

    ⚠⚠ **新しいテーマ色を増やさないための道具**です（依頼者 2026-09-20
    「新しいテーマ色を勝手に増やさないでください」）。
    ★ボタンの「ふれたとき」「入っているとき」「押せないとき」の色は、
    ここにある色から**その場で作ります**（⚠ 名前を付けて増やさない）。
    """
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else float(t))
    xa, xb = a.lstrip("#"), b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        va, vb = int(xa[i:i + 2], 16), int(xb[i:i + 2], 16)
        out.append(int(round(va + (vb - va) * t)))
    return "#%02x%02x%02x" % tuple(out)


#: ★白地に載せる字の色ぜんぶ（⚠ 検査がまとめて見る）
INK_COLOURS = (INK, MUTED, STAT, ACCENT)
#: ★地の色ぜんぶ
PAPER_COLOURS = (PAPER, CARD)


__all__ = ["PAPER", "CARD", "BORDER", "INK", "MUTED", "STAT", "ACCENT",
           "ART_BACK", "ART_BORDER", "MAX_LUMA", "luma", "mix",
           "INK_COLOURS", "PAPER_COLOURS"]
