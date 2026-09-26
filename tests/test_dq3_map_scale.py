"""地図を出す大きさ（RX3-0043 → RX3-0045 / 2026-09-01）。

## ⚠⚠ ここが守る約束

依頼者 2026-09-01:

> 世界地図一番小さいブロックで丁度いい感じだったので、そうしたい。
> スクロールバー対応を DQ2 でやった。

```text
1 升の px    ★地図の種別で固定
収まらない   ⚠ 縮めずスクロール（★`MapScroll` が受け持つ）
```

## ⚠⚠ 「枠の大きさを見ない」が芯です

★DQ2 は 2026-08-18 に、widget を枠へ伸ばしてから測って**点滅**しました。
⚠ ここに枠を渡す口が無いこと自体が、★振動しないことの根拠です。
"""

from __future__ import annotations

import inspect

from dq3.ui import map_scale

WORLD, LOCAL, ALEFGARD = 0, 1, 2


def test_世界地図は一番小さいブロック():
    """★依頼者の指定（⚠ DQ2 の `CELL_PIXELS` の最小と同じ考え方）。"""
    assert map_scale.cell_px(WORLD) == map_scale.WORLD_CELL
    assert map_scale.cell_px(ALEFGARD) == map_scale.WORLD_CELL
    assert map_scale.WORLD_CELL == min(
        p for p in map_scale.CELL_PIXELS if p >= 8), (
        "⚠ 一番小さいブロックが %d px になっている" % map_scale.WORLD_CELL)


def test_ローカルはタイルの等倍():
    """⚠⚠ 縮めると**画素を捨てます**（★タイルは 16x16）。"""
    assert map_scale.cell_px(LOCAL) == map_scale.SOURCE_CELL


def test_世界地図はローカルより小さい():
    assert map_scale.cell_px(WORLD) < map_scale.cell_px(LOCAL)


def test_知らない種別はローカル扱い():
    """⚠ 真っ黒にするより、★出したほうがまし。"""
    assert map_scale.cell_px(99) == map_scale.cell_px(LOCAL)


# --- ⚠⚠ 枠を見ない -------------------------------------------------------

def test_枠を受け取る口が無い():
    """⚠⚠ **これが「点滅しない」の根拠**（★構造で保証する）。

    ★DQ2 の記録（2026-08-18）:

    ```text
    1: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
    2: 枠内側 323x393 / widget 323x393 / 収める   / 倍率 None
    ```

    ⚠ 枠を渡せてしまうと、いつか誰かが渡します。★渡す口を作りません。
    """
    引数 = list(inspect.signature(map_scale.cell_px).parameters)
    assert 引数 == ["kind", "zoom"], "⚠⚠ 枠の口が増えている: %r" % 引数


def test_同じ種別なら何度呼んでも同じ():
    """⚠ 振動しないこと（★状態を持たない）。"""
    for kind in (WORLD, LOCAL, ALEFGARD):
        got = {map_scale.cell_px(kind) for _ in range(50)}
        assert len(got) == 1, "⚠⚠ %d の倍率が揺れている: %r" % (kind, got)


def test_縮める仕掛けは残っていない():
    """⚠⚠ `shrink_to_fit` は**スクロールに置き換えました**。

    ★残しておくと「縮める道」が生き続けます（⚠ 使われない値は飾り）。
    """
    assert not hasattr(map_scale, "shrink_to_fit"), (
        "⚠ 縮める道が残っている（★スクロールに置き換えたはず）")
    assert not hasattr(map_scale, "fits")


# --- ★描く大きさ ---------------------------------------------------------

def test_描く大きさは升の倍数():
    w, h = map_scale.draw_size(LOCAL, 26, 20)
    assert (w, h) == (26 * 16, 20 * 16)
    w, h = map_scale.draw_size(WORLD, 256, 256)
    assert (w, h) == (256 * 8, 256 * 8)


def test_小さい地図ほど画面で小さい():
    """★「小さい場所は小さく、大きい場所は大きく」（指示書 §9）。"""
    小 = map_scale.draw_size(LOCAL, 5, 5)[0]
    中 = map_scale.draw_size(LOCAL, 16, 16)[0]
    大 = map_scale.draw_size(LOCAL, 26, 26)[0]
    assert 小 < 中 < 大, "⚠ 小さい地図が大きく出ている（%d/%d/%d）" % (小, 中, 大)


def test_世界地図は枠に収まらない():
    """⚠⚠ **収まらないのが正しい**（★だからスクロールが要る）。"""
    w, h = map_scale.draw_size(WORLD, 256, 256)
    assert w == h == 2048
    assert w > 1200, "⚠ 収まってしまうと、スクロールの検査が通らない"


# --- ★絵をどれだけ拡大するか ---------------------------------------------

def test_タイルは等倍で出す():
    """★絵の 1 升が 16px なので、⚠ 1 升 16px なら 1.0 倍。"""
    assert map_scale.image_scale(LOCAL, tiled=True) == 1.0


def test_色ブロックは升の数だけ広げる():
    """⚠ 絵の 1 升が 1px なので、★1 升の px そのもの。"""
    assert map_scale.image_scale(LOCAL, tiled=False) == 16.0
    assert map_scale.image_scale(WORLD, tiled=False) == 8.0


def test_世界地図をタイルで出すなら半分():
    """⚠ いまは起きないが、★式としては半分（16px の絵を 8px で）。"""
    assert map_scale.image_scale(WORLD, tiled=True) == 0.5


# --- ⚠ 将来のズーム ------------------------------------------------------

def test_倍率を動かせる():
    assert map_scale.cell_px(LOCAL, zoom=2.0) == 32
    assert map_scale.cell_px(WORLD, zoom=2.0) == 16


def test_升を潰さない():
    assert map_scale.cell_px(LOCAL, zoom=0.01) == map_scale.MIN_CELL


def test_引き伸ばしすぎない():
    assert map_scale.cell_px(LOCAL, zoom=99) == map_scale.MAX_CELL


def test_変な入力で落ちない():
    assert map_scale.cell_px(None) >= map_scale.MIN_CELL
    assert map_scale.draw_size(LOCAL, 0, 0) == (0, 0)
    assert map_scale.draw_size(LOCAL, -5, -5) == (0, 0)
    assert map_scale.cell_px(LOCAL, zoom=0) == map_scale.SOURCE_CELL
