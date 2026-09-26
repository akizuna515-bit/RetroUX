"""MAP 窓が、ゲーム内のタイルで描く（RX3-0043 / 2026-09-01）。

## ⚠⚠ ここが守るもの（指示書 §17）

```text
★実際の RetroUX MAP Window で出ること   ⚠ PoC の PNG ではない
⚠ 小さい地図を画面いっぱいに拡大しない
⚠ 1 歩ごとに全タイルを作り直さない
```

## ⚠ 「絵にした後で比べる」をしない

★2026-08-31 の教訓。⚠ ここは**同じ形のデータどうし**（升の索引）で
突き合わせます。★ピクセルを目視で比べません。
"""

from __future__ import annotations

import os
import pathlib
import time

import pytest

pytest.importorskip("PySide6")

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CELL = 16                       #: ★`tile_art.CELL`（⚠ 検査側でも固定する）


@pytest.fixture(scope="module", autouse=True)
def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Terrain:
    """★ROM から起こした地図の代わり（⚠ 値は実機と**わざと違える**）。"""

    def __init__(self, width, height, value=5):
        self.width, self.height = width, height
        self._value = value
        self.tileset = None

    def at(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return self._value


class _Source:
    def __init__(self, terrain):
        self._terrain = terrain
        self.available = True
        self.last_error = None

    def get(self, kind, map_id=None):
        return self._terrain


class _Art:
    """★索引 → 16x16 の絵（⚠ 索引ごとに違う色にして見分ける）。"""

    def __init__(self, indices):
        self.cells = {i: bytes([i, 0, 0]) * (CELL * CELL) for i in indices}
        self.asked = []

    def block(self, raw, hero_raw=None):
        from dq3.knowledge.tile_art import index_of

        self.asked.append(raw)
        return self.cells.get(index_of(raw, hero_raw))


class _Runtime:
    """★実機が持っている升（⚠ ROM とは違う値）。"""

    def __init__(self, kind, map_id, width, height, value):
        self.kind, self.map_id = kind, map_id
        self.width, self.height = width, height
        self.cells = bytes([value]) * (width * height)

    def at(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return self.cells[y * self.width + x]


def _canvas(seen_cells, *, at=(1, 9, 10, 10), size=20, art=None,
            runtime=None, rom_value=5, follow=True):
    from dq3.knowledge.seen_map import SeenMap, map_key
    from dq3.ui.map_window import MapCanvas

    seen = SeenMap(pathlib.Path("使わない"))
    key = map_key(at[0], at[1])
    for x, y in seen_cells:
        seen.mark(key, x, y)

    class VM:
        tile_art = art
        tile_art_runtime = runtime

        def position(self):
            return at

        def known_locations(self):
            return []

    VM.seen = seen
    canvas = MapCanvas(VM(), follow=follow)
    canvas._terrain = _Source(_Terrain(size, size, rom_value))
    return canvas


# --- ★タイルで描けているか ------------------------------------------------

def test_絵があればタイルで描く():
    """⚠⚠ 升 1 つが 16x16 になる（★色ブロックなら 1x1）。"""
    art = _Art([3])
    canvas = _canvas([(10, 10)], art=art,
                     runtime=_Runtime(1, 9, 20, 20, 3))
    image, _at = canvas._image_now()
    assert image is not None
    assert image.width() % CELL == 0 and image.width() >= CELL * 20, (
        "⚠ タイルで描いていない（幅 %d）" % image.width())


def test_絵が無ければ色ブロックのまま():
    """⚠⚠ **落ちません**（★材料が無いのが普通 / 指示書 §1）。"""
    canvas = _canvas([(10, 10)], art=None, runtime=None)
    image, _at = canvas._image_now()
    assert image is not None
    assert image.width() == 20, "⚠ 絵が無いのにタイルの大きさになっている"


def test_引く値は実機の升():
    """⚠⚠ **ここが 113/676 の食い違いの本体**（★2026-09-01 実測）。

    ROM から起こした値は 5、実機の値は 27。★引くのは 27 でなければならない。
    """
    art = _Art([5, 27])
    canvas = _canvas([(10, 10)], art=art, rom_value=5,
                     runtime=_Runtime(1, 9, 20, 20, 27))
    canvas._image_now()
    assert 27 in art.asked, "⚠⚠ ROM の値で引いている（★別のタイルが出る）"
    assert 5 not in art.asked, "⚠ ROM の値も引いてしまっている"


def test_別の地図の升は使わない():
    """⚠⚠ 実機がまだ前の地図を持っていたら、★**タイルで描きません**。

    ## ⚠ 2026-09-02 に変えました（`RX3-0046`）

      ★もとは「ROM の値で描く」でした。⚠ ですが ROM の値で引くと
      **113/676 の升が別のタイル**になります（`_tile_cells` の説明）。
      ⚠⚠ しかも tileset は**前の地図のもの**なので、★絵そのものが別です。

      → ★色ブロックへ戻します（⚠ 地形は正しく見分けられる）。
    """
    art = _Art([5, 27])
    canvas = _canvas([(10, 10)], at=(1, 9, 10, 10), art=art, rom_value=5,
                     runtime=_Runtime(1, 21, 20, 20, 27))   # ⚠ 別の地図
    image, _at = canvas._image_now()
    assert art.asked == [], "⚠⚠ 別の地図の tileset で描いた"
    assert canvas._tiled() is False
    assert image.width() == 20, (       # ★地図 20x20 が 1 升 1px で 20px
        "⚠ 色ブロックに戻っていない（幅 %d）" % image.width())


def test_見ていない升はタイルでも塗らない():
    """⚠⚠ No-Spoiler は描き方を変えても変わらない。"""
    from dq3.ui.map_window import UNSEEN

    art = _Art([3])
    canvas = _canvas([(10, 10)], art=art,
                     runtime=_Runtime(1, 9, 20, 20, 3))
    image, _at = canvas._image_now()
    ox, oy = canvas.origin
    見た = image.pixel((10 - ox) * CELL + 8, (10 - oy) * CELL + 8)
    見ていない = image.pixel((15 - ox) * CELL + 8, (15 - oy) * CELL + 8)
    assert 見た != UNSEEN.rgb(), "⚠ 見た升が塗られていない"
    assert 見ていない == UNSEEN.rgb(), "⚠⚠ 見ていない升にタイルが出ている"


# --- ⚠ 同じ升の絵を作り直さない（指示書 §12 第一段階）--------------------

def test_同じ索引の絵は1回しか作らない():
    art = _Art([3])
    見た = [(x, y) for y in range(5, 15) for x in range(5, 15)]
    canvas = _canvas(見た, art=art, runtime=_Runtime(1, 9, 20, 20, 3))
    canvas._image_now()
    assert len(canvas._tile_cache) == 1, "⚠ 索引ごとに 1 つのはず"
    # ★`block()` は 100 升ぶん呼ばれない（⚠ 覚えている）
    assert len(art.asked) <= 2, (
        "⚠⚠ 升ごとに絵を作り直している（%d 回）" % len(art.asked))


def test_絵が入れ替わったら覚えたものを捨てる():
    art = _Art([3])
    canvas = _canvas([(10, 10)], art=art, runtime=_Runtime(1, 9, 20, 20, 3))
    canvas._image_now()
    assert canvas._tile_cache
    canvas.vm.__class__.tile_art = _Art([4])
    canvas._image_for = None              # ⚠ 作り直させる
    canvas._image_now()
    assert 3 not in canvas._tile_cache, "⚠⚠ 前の地図の絵を使い回した"


# --- ⚠ 倍率（RX3-0045: ★枠を見ない）------------------------------------

def test_タイルは等倍で出す():
    """★1 升 16px の絵を 1 升 16px で出す（⚠ にじませない）。"""
    from PySide6.QtGui import QImage

    canvas = _canvas([(1, 1)], art=_Art([3]),
                     runtime=_Runtime(1, 9, 5, 5, 3), size=5)
    canvas._image_now()
    image = QImage(5 * CELL, 5 * CELL, QImage.Format.Format_RGB32)
    assert canvas._scale_for(image) == 1.0


def test_枠を広げても倍率が変わらない():
    """⚠⚠ **これが「点滅しない」の本体**（★DQ2 が 2026-08-18 に踏んだ穴）。"""
    from PySide6.QtGui import QImage

    canvas = _canvas([(1, 1)], art=_Art([3]),
                     runtime=_Runtime(1, 9, 5, 5, 3), size=5)
    canvas._image_now()
    image = QImage(5 * CELL, 5 * CELL, QImage.Format.Format_RGB32)
    見えた = set()
    for 幅 in (100, 320, 760, 4000):
        canvas.resize(幅, 幅)
        見えた.add(canvas._scale_for(image))
    assert len(見えた) == 1, "⚠⚠ 枠の大きさで倍率が変わっている: %r" % 見えた


def test_色ブロックは升の数だけ広げる():
    """⚠ 1 升 1px なので、★1 升の px そのもの。"""
    from PySide6.QtGui import QImage

    canvas = _canvas([(1, 1)], art=None, runtime=None, size=20)
    canvas._image_now()
    image = QImage(20, 20, QImage.Format.Format_RGB32)
    assert canvas._scale_for(image) == 16.0


def test_中身の大きさは枠を見ない():
    """★`MapScroll` がこれを `setFixedSize()` に渡します。"""
    canvas = _canvas([(1, 1)], art=_Art([3]),
                     runtime=_Runtime(1, 9, 5, 5, 3), size=5)
    for 幅 in (100, 4000):
        canvas.resize(幅, 幅)
        assert canvas.content_size() == (5 * CELL, 5 * CELL)


def test_世界地図は一番小さいブロック():
    """★依頼者 2026-09-01（⚠ 色ブロックのまま / タイルは使わない）。"""
    canvas = _canvas([(1, 1)], at=(0, 0, 1, 1), art=None, runtime=None,
                     size=32, follow=False)
    got = canvas.content_size()
    assert got is not None
    # ⚠ 「地図を見る」画面は見た所のまわりを切り出すので、★升の数は決め打てない
    w, h = got
    assert w % 8 == 0 and h % 8 == 0, "⚠ 1 升が 8px になっていない: %r" % (got,)
    from PySide6.QtGui import QImage

    image = QImage(32, 32, QImage.Format.Format_RGB32)
    assert canvas._scale_for(image) == 8.0


# --- ⚠ 遅くないか（指示書 §12）-------------------------------------------

def test_描き直しが遅すぎない():
    """⚠⚠ DQ2 で 137.8 ms 掛かって**1 フレーム落ちた**実測がある。

    ★ここは 48x48 升（`FOLLOW_VIEW`）を作り直す時間を測ります。
    ⚠ 目安は 100 ms。★超えたら第二段階のキャッシュが要ります。
    """
    from dq3.ui.map_window import FOLLOW_VIEW

    n = FOLLOW_VIEW
    art = _Art(list(range(64)))
    見た = [(x, y) for y in range(n) for x in range(n)]
    canvas = _canvas(見た, at=(1, 9, n // 2, n // 2), art=art, size=n * 2,
                     runtime=_Runtime(1, 9, n * 2, n * 2, 7))
    始め = time.perf_counter()
    image, _at = canvas._image_now()
    掛かった = (time.perf_counter() - 始め) * 1000
    assert image is not None
    assert 掛かった < 100, "⚠⚠ %d 升の描き直しに %.1f ms 掛かった" % (
        n * n, 掛かった)


def test_同じ場所では作り直さない():
    """⚠ 追随する窓は居場所が変われば作り直す（★仕様）。

    ⚠⚠ ですが**同じ場所なら作り直しません**（★ここを固定する）。
    """
    art = _Art([3])
    canvas = _canvas([(10, 10)], art=art, runtime=_Runtime(1, 9, 20, 20, 3))
    canvas._image_now()
    回数 = len(art.asked)
    for _ in range(10):
        canvas._image_now()
    assert len(art.asked) == 回数, "⚠⚠ 同じ場所なのに作り直している"


# --- ⚠⚠ 現在地の印（★2026-09-01 のキャプチャで左上に固まった）--------------

def test_現在地の印は升の大きさで置く():
    """⚠⚠ **地形は正しいのに印だけ 16 分の 1 の場所へ寄っていました**。

    ★倍率（絵のピクセル比）と、⚠ 1 升のピクセル数は別ものです。

    ```text
    色ブロック   絵の 1 升 =  1 px  →  1 升 = 倍率 x 1
    タイル       絵の 1 升 = 16 px  →  1 升 = 倍率 x 16
    ```
    """
    canvas = _canvas([(10, 10)], art=_Art([3]),
                     runtime=_Runtime(1, 9, 20, 20, 3))
    # ⚠ 「絵を持っている」ではなく★**実際に描いた**かで決まる（RX3-0046）
    canvas._image_now()
    assert canvas._tiled() is True
    assert canvas._px_per_cell(1.0) == CELL, "⚠⚠ 印が 16 分の 1 に寄る"
    assert canvas._px_per_cell(0.5) == CELL / 2

    canvas._drew_tiles = False          # ⚠ 色ブロックで描いたことにする
    assert canvas._px_per_cell(1.0) == 1.0, "⚠ 色ブロックの置き方が変わった"
    assert canvas._px_per_cell(20.0) == 20.0


def test_現在地の印が地形の中に入る():
    """⚠ 端に寄っていないこと（★左上に固まる壊れ方を捕まえる）。"""
    from PySide6.QtGui import QPainter, QPixmap

    n = 20
    見た = [(x, y) for y in range(n) for x in range(n)]
    canvas = _canvas(見た, at=(1, 9, 10, 10), art=_Art([3]), size=n,
                     runtime=_Runtime(1, 9, n, n, 3), follow=True)
    canvas.resize(600, 600)
    出す先 = QPixmap(600, 600)
    painter = QPainter(出す先)
    try:
        枠 = canvas._draw_terrain(painter)
    finally:
        painter.end()
    assert 枠 is not None
    倍率 = 枠.width() / (n * CELL)
    印 = 枠.x() + int(10 * canvas._px_per_cell(倍率))
    真ん中 = 枠.x() + 枠.width() // 2
    assert abs(印 - 真ん中) <= 枠.width() * 0.1, (
        "⚠⚠ 真ん中に居るのに印が %d（★地形は %d〜%d）"
        % (印, 枠.x(), 枠.x() + 枠.width()))
