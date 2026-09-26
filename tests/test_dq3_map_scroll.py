"""地図をスクロールして見せる（RX3-0045 / 2026-09-01）。

依頼者 2026-09-01:

> 世界地図一番小さいブロックで丁度いい感じだったので、そうしたい。
> スクロールバー対応を DQ2 でやった。

## ⚠⚠ ここが守るもの

```text
★収まらない地図は**縮まない**（⚠ スクロールバーが出る）
★世界地図は 1 升 8px
⚠ 地図が変わったときだけ現在地へ寄せる（★手の操作を奪わない）
⚠⚠ 何度描き直しても大きさが振動しない（★DQ2 が 2026-08-18 に踏んだ）
```
"""

from __future__ import annotations

import os
import pathlib

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CELL = 16


@pytest.fixture(scope="module", autouse=True)
def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Terrain:
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


def _scroll(*, at=(1, 9, 10, 10), size=20, box=(400, 400), follow=True):
    """★スクロール枠に入れた地図（⚠ 色ブロック。タイルは別の検査で見る）。"""
    from dq3.knowledge.seen_map import SeenMap, map_key
    from dq3.ui.map_window import MapCanvas, MapScroll

    seen = SeenMap(pathlib.Path("使わない"))
    key = map_key(at[0], at[1])
    for y in range(size):
        for x in range(size):
            seen.mark(key, x, y)

    class VM:
        tile_art = None
        tile_art_runtime = None

        def __init__(self):
            self._at = at

        def place_name(self, map_id):
            return None                       # ⚠ 名前は知らない（★番号で出る側を見る）

        def position(self):
            return self._at

        def known_locations(self):
            return []

        # ⚠ 窓を丸ごと作るのに要るぶんだけ（★画面の中身は見ない）
        def recent_memos(self, n=3):
            return []

        memos = ()                    # ⚠ `len()` される（★メソッドではない）

        def map_memos(self, key, n=3):
            return []

        def location_view(self, loc):
            return None

    VM.seen = seen
    vm = VM()
    canvas = MapCanvas(vm, follow=follow)
    canvas._terrain = _Source(_Terrain(size, size))
    scroll = MapScroll(canvas)
    scroll.resize(*box)
    scroll.show()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    return scroll, canvas, vm


# --- ⚠⚠ 縮めない --------------------------------------------------------

def test_収まらない地図は縮まない():
    """⚠⚠ **これが RX3-0045 の芯**（★もとは 768px を 610px へ縮めていた）。"""
    scroll, canvas, _vm = _scroll(at=(1, 9, 10, 10), size=40, box=(400, 400))
    # ★追随する窓は 40 升ぶん（⚠ FOLLOW_VIEW 48 より小さいので全部出る）
    assert canvas.width() == 40 * CELL, (
        "⚠⚠ 縮んでいる（%d px / ★%d px のはず）" % (canvas.width(), 40 * CELL))
    assert canvas.width() > scroll.viewport().width()


def test_収まらなければスクロールバーが出る():
    scroll, _canvas, _vm = _scroll(size=40, box=(300, 300))
    assert scroll.horizontalScrollBar().maximum() > 0, "⚠ 横に動かせない"
    assert scroll.verticalScrollBar().maximum() > 0, "⚠ 縦に動かせない"


def test_収まるならスクロールバーは出ない():
    scroll, _canvas, _vm = _scroll(size=5, box=(600, 600))
    assert scroll.horizontalScrollBar().maximum() == 0
    assert scroll.verticalScrollBar().maximum() == 0


def test_小さい地図を広げない():
    """⚠ 枠が広くても、★5x5 は 5x5 のまま（指示書 §9）。"""
    _scroll_, canvas, _vm = _scroll(size=5, box=(2000, 2000))
    assert canvas.width() == 5 * CELL


# --- ★世界地図 -----------------------------------------------------------

def test_世界地図は1升8px():
    """★依頼者「一番小さいブロックで丁度いい」。"""
    _s, canvas, _vm = _scroll(at=(0, 0, 100, 100), size=128, box=(400, 400))
    got = canvas.content_size()
    assert got is not None
    assert got[0] % 8 == 0
    from dq3.ui import map_scale

    assert map_scale.cell_px(0) == 8
    # ★RX3-0255: 世界地図は追随中も見た所ぜんぶ（⚠ 以前は 48 升の窓 = 384 px）→ ★見た 128 升 x 8 = 1024 px
    assert canvas.width() == 128 * 8, (
        "⚠ 世界地図の 1 升が 8px でないか、見た所ぜんぶを絵にしていない（%d px）" % canvas.width())


# --- ⚠⚠ 振動しない ------------------------------------------------------

def test_何度描き直しても大きさが変わらない():
    """⚠⚠ **DQ2 が 2026-08-18 に踏んだ穴**（★点滅の正体）。

    ```text
    1: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
    2: 枠内側 323x393 / widget 323x393 / 収める   / 倍率 None
    ```
    """
    scroll, canvas, _vm = _scroll(size=40, box=(360, 380))
    見えた = set()
    for _ in range(20):
        scroll.fit()
        見えた.add((canvas.width(), canvas.height()))
    assert len(見えた) == 1, "⚠⚠ 大きさが振動している: %r" % 見えた


def test_2回目のfitは何もしない():
    scroll, _canvas, _vm = _scroll(size=20)
    assert scroll.fit() is False, "⚠ 変わっていないのに当て直している"


# --- ⚠ 寄せるのは地図が変わったときだけ ----------------------------------

def test_地図に入ったら現在地が見える():
    scroll, canvas, _vm = _scroll(at=(1, 9, 40, 40), size=48, box=(300, 300))
    at = canvas.hero_at()
    assert at is not None
    x, y = at
    左 = scroll.horizontalScrollBar().value()
    上 = scroll.verticalScrollBar().value()
    view = scroll.viewport()
    assert 左 <= x <= 左 + view.width(), (
        "⚠⚠ 現在地が見えていない（x=%d / 見えているのは %d〜%d）"
        % (x, 左, 左 + view.width()))
    assert 上 <= y <= 上 + view.height()


def test_同じ地図では寄せ直さない():
    """⚠⚠ **毎回寄せると手でスクロールできません**。"""
    scroll, _canvas, _vm = _scroll(at=(1, 9, 40, 40), size=48, box=(300, 300))
    scroll.horizontalScrollBar().setValue(0)
    scroll.verticalScrollBar().setValue(0)
    for _ in range(5):
        scroll.fit()
    assert scroll.horizontalScrollBar().value() == 0, (
        "⚠⚠ 手で動かしたのに戻された")


def test_地図が変われば寄せ直す():
    scroll, canvas, vm = _scroll(at=(1, 9, 40, 40), size=48, box=(300, 300))
    scroll.horizontalScrollBar().setValue(0)
    scroll.verticalScrollBar().setValue(0)
    vm._at = (1, 21, 40, 40)          # ⚠ 別の地図へ移った
    canvas._image_for = None
    scroll.fit()
    assert scroll.horizontalScrollBar().value() != 0, (
        "⚠ 地図が変わったのに寄せ直していない")


# --- ⚠ 製品に入っているか ------------------------------------------------

def test_MAP窓がスクロール枠を使っている():
    """⚠⚠ 「書いてある」だけでなく、★実際に入っていること。"""
    from dq3.ui.map_window import MapScroll

    _s, canvas, vm = _scroll()
    from dq3.ui.map_window import Dq3MapWindow

    win = Dq3MapWindow(vm)
    assert isinstance(win.scroll, MapScroll)
    assert win.scroll.widget() is win.canvas


def test_地図を見る画面もスクロール枠を使っている():
    from dq3.ui.map_window import MapScroll

    _s, _canvas, vm = _scroll()
    from dq3.ui.map_browser import Dq3MapBrowser

    browser = Dq3MapBrowser(vm)
    assert isinstance(browser.scroll, MapScroll)
    assert browser.scroll.widget() is browser.canvas


def test_同じ地図でも現在地が枠の外へ飛んだら寄せ直す():
    """⚠⚠ 2026-09-07 依頼者「階段移動したときに MAP が追随しないので見失う」。

    ★実測（DQ3_J.fc2 / fc3）: 洞窟は**階が変わっても同じ地図**でした。

    ```text
    階段前  kind=5 map_no=45 58x40 local=(2,8)
    階段後  kind=5 map_no=45 58x40 local=(5,34)
    ⚠⚠ 番号も寸法も変わらない。★座標だけが飛ぶ
    ```

    → ⚠ `(kind, map_id)` だけを見ていたので、**一度も寄せ直さない**。
    """
    from dq3.ui.map_window import MapScroll

    class _Canvas:
        _at_now = (5, 45, 2, 8)

        def __init__(self):
            self.hero = (10, 10)

        def hero_at(self):
            return self.hero

        def width(self):
            return 2000

        def height(self):
            return 2000

    scroll = MapScroll.__new__(MapScroll)                 # ⚠ Qt を作らずに中身だけ見る
    scroll.canvas = _Canvas()
    scroll._centred_for = (5, 45)
    scroll._want_centre = False
    scroll._hero_cell = (2, 8)
    moved = []
    scroll.centre_on_hero = lambda: (moved.append(scroll.canvas._at_now), True)[1]
    scroll._hero_off_screen = lambda: True

    # ★同じ升に居るあいだは動かさない（⚠ 手の操作を奪わない）
    scroll._centre_if_new()
    assert moved == [], "⚠ 立ち止まっているのに寄せている"

    # ★階段で飛んだ（⚠ 地図は同じ 45 のまま）
    scroll.canvas._at_now = (5, 45, 5, 34)
    scroll._centre_if_new()
    assert moved, "⚠⚠ 同じ地図の中で飛んだのに寄せ直していない"


def test_手で動かしている間は枠の中なら寄せ直さない():
    """⚠ 人がスクロールしている間に 1 マス歩くたびに動かすと、★見ている所が勝手にずれます。

    ★2026-09-12（RX3-0206）: 追随中は毎歩真ん中へ寄せる（指示書 §5-1）。⚠ 人がスクロールしたら止める。
    → ★ここは「止めている間」の約束（★追随中の約束は test_dq3_map_follow.py）。
    """
    from dq3.ui.map_window import MapScroll

    class _Canvas:
        _at_now = (1, 9, 4, 4)

        def hero_at(self):
            return (10, 10)

    scroll = MapScroll.__new__(MapScroll)
    scroll.canvas = _Canvas()
    scroll._centred_for = (1, 9)
    scroll._want_centre = False
    scroll._hero_cell = (4, 4)
    scroll.following = False                              # ★人がスクロールして追随を止めた
    moved = []
    scroll.centre_on_hero = lambda: (moved.append(1), True)[1]
    scroll._hero_off_screen = lambda: False

    scroll.canvas._at_now = (1, 9, 5, 4)                  # ★1 マス歩いた
    scroll._centre_if_new()
    assert moved == [], "⚠ 枠の中に居るのに寄せている"
