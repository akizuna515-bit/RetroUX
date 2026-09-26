"""ダンジョン探索MAP v1 Phase B: 現在地を中央に・洞窟と塔は一段小さく（RX3-0206 / 2026-09-12）。

依頼者の指示書「DQ3 ダンジョン探索MAP v1」§5・§6・§14:

```text
通常            主人公を中央に（★毎歩）
MAP の端        境界へ寄せる（⚠ 余白を出さない）
階・地図が変わる 新しい現在地へ追随
手でスクロール   追随を止める →「現在地」で戻す
縮尺            洞窟・塔は一段小さく（16 → 8 px）/ 小・標準・大 / ⚠ 町は今のまま
探索率          ⚠ 通常の画面には出さない
```
"""
from __future__ import annotations

import os
import pathlib

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module", autouse=True)
def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Terrain:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.tileset = None

    def at(self, x, y):
        return 5 if (0 <= x < self.width and 0 <= y < self.height) else None


class _Source:
    def __init__(self, terrain):
        self._terrain = terrain
        self.available = True
        self.last_error = None

    def get(self, kind, map_id=None):
        return self._terrain


def _vm(at, size):
    from dq3.knowledge.seen_map import SeenMap, map_key

    seen = SeenMap(pathlib.Path("使わない"))
    key = map_key(at[0], at[1])
    for y in range(size):
        for x in range(size):
            seen.mark(key, x, y)

    class VM:
        tile_art = None
        tile_art_runtime = None
        memos = ()

        def __init__(self):
            self._at = at

        def place_name(self, map_id):
            return None

        def position(self):
            return self._at

        def known_locations(self):
            return []

        def recent_memos(self, n=3):
            return []

        def map_memos(self, key, n=3):
            return []

        def location_view(self, loc):
            return None

    VM.seen = seen
    return VM()


def _scroll(*, at, size=200, box=(300, 300)):
    from PySide6.QtWidgets import QApplication

    from dq3.ui.map_window import MapCanvas, MapScroll

    vm = _vm(at, size)
    canvas = MapCanvas(vm)
    canvas._terrain = _Source(_Terrain(size, size))
    scroll = MapScroll(canvas)
    scroll.resize(*box)
    scroll.show()
    QApplication.processEvents()
    scroll.fit()
    return scroll, canvas, vm


def _walk(scroll, vm, at):
    from PySide6.QtWidgets import QApplication

    vm._at = at
    scroll.fit()
    QApplication.processEvents()


def _gap(scroll, canvas):
    """★現在地と、見えている所の真ん中のずれ（px）。"""
    x, y = canvas.hero_at()
    view = scroll.viewport()
    return (abs(x - (scroll.horizontalScrollBar().value() + view.width() // 2)),
            abs(y - (scroll.verticalScrollBar().value() + view.height() // 2)))


# --- ★縮尺 ------------------------------------------------------------------

def test_洞窟と塔は一段小さく_町と世界地図は今のまま():
    from dq3.ui import map_scale as S

    assert S.cell_px(5) == 8, "⚠⚠ 洞窟・塔が一段小さくなっていない"
    assert S.cell_px(1) == 16, "⚠ 町まで小さくした"
    assert S.cell_px(0) == 8 and S.cell_px(99) == 16
    assert S.default_level(5) == "小" and S.default_level(1) == "標準"
    assert S.cell_px(5, zoom=S.level_zoom(5, "大")) == 32
    assert S.cell_px(1, zoom=S.level_zoom(1, "小")) == 8
    assert S.level_zoom(0, "大") == 1.0, "⚠ 世界地図まで変えた"


def test_洞窟では広い範囲を出す_町は今までどおり():
    _s, canvas, _vm = _scroll(at=(5, 45, 100, 100))
    assert canvas.width() == 96 * 8, "⚠ 1 升が小さいのに範囲が 48 升のまま（★階の形をつかめない）: %d" % canvas.width()
    _s, canvas, _vm = _scroll(at=(1, 9, 100, 100))
    assert canvas.width() == 48 * 16, "⚠ 町の見え方まで変えた"


def test_大きさを選べる(_app):
    from dq3.ui.map_window import Dq3MapWindow

    vm = _vm((5, 45, 100, 100), 200)
    win = Dq3MapWindow(vm)
    win.canvas._terrain = _Source(_Terrain(200, 200))
    assert [win.size_box.itemText(i) for i in range(win.size_box.count())] == ["小", "標準", "大"]
    win.canvas.content_size()
    assert win.canvas.level_now() == "小", "⚠ 洞窟の最初が「小」でない"
    win._size_picked(2)
    assert win.canvas.level_now() == "大"
    assert win.canvas.content_size()[0] == 48 * 32, "⚠ 選んだ大きさで描いていない"


# --- ★追随 ------------------------------------------------------------------

def test_歩くたびに現在地が真ん中に来る():
    scroll, canvas, vm = _scroll(at=(5, 45, 100, 100))
    for step in range(1, 6):
        _walk(scroll, vm, (5, 45, 100 + step, 100 + step))
        gx, gy = _gap(scroll, canvas)
        assert gx <= 8 and gy <= 8, "⚠⚠ %d 歩目で現在地が真ん中にない（ずれ %d, %d px）" % (step, gx, gy)


def test_追随の窓が止まる端の近くでもスクロールで真ん中へ():
    """★地図の端に近いと、追随する窓（96 升）はそれ以上動かない → ★スクロールで現在地を真ん中へ。

    ⚠ 端から遠い所では窓が勇者と一緒に動くので、スクロールしなくても真ん中に来てしまう（★ここで見分ける）。
    """
    scroll, canvas, vm = _scroll(at=(5, 45, 160, 100))
    for x in range(161, 181, 3):
        _walk(scroll, vm, (5, 45, x, 100))
        gx, _gy = _gap(scroll, canvas)
        assert gx <= 8, "⚠⚠ 端の近くで現在地が真ん中から外れた（x=%d / ずれ %d px）" % (x, gx)


def test_地図の端では余白を出さない():
    scroll, canvas, vm = _scroll(at=(5, 45, 0, 0))
    assert scroll.horizontalScrollBar().value() == 0 and scroll.verticalScrollBar().value() == 0
    assert getattr(canvas, "origin", (0, 0)) == (0, 0), "⚠ 地図の外（余白）から描いている"
    x, y = canvas.hero_at()
    assert x < 300 and y < 300, "⚠ 端に居るのに現在地が見えていない"


def test_手でスクロールしたら追随を止め_現在地で戻る():
    from PySide6.QtWidgets import QAbstractSlider

    scroll, canvas, vm = _scroll(at=(5, 45, 100, 100))
    bar = scroll.horizontalScrollBar()
    bar.triggerAction(QAbstractSlider.SliderAction.SliderSingleStepAdd)   # ★人がスクロールした
    assert scroll.following is False, "⚠⚠ 人がスクロールしても追随したまま（★手の操作を奪う）"
    # ★見えている左端の升（★RX3-0255: 勇者のまわりの窓が動いても、見ている升は保つ = スクロールの値は窓のぶん動く）
    unit = canvas.unit_now()
    held = canvas.origin[0] + bar.value() / unit
    _walk(scroll, vm, (5, 45, 101, 100))                                 # ★枠の中を 1 歩
    assert canvas.origin[0] + bar.value() / unit == held, "⚠⚠ 手で動かしたのに戻された（★見ている升がずれた）"
    assert scroll.following is False
    assert scroll.follow_again() and scroll.following
    gx, gy = _gap(scroll, canvas)
    assert gx <= 8 and gy <= 8, "⚠ 「現在地」で真ん中に戻らない"


def test_地図や階が変わったら追随に戻る():
    from PySide6.QtWidgets import QAbstractSlider

    scroll, canvas, vm = _scroll(at=(5, 45, 100, 100))
    scroll.horizontalScrollBar().triggerAction(QAbstractSlider.SliderAction.SliderSingleStepAdd)
    assert scroll.following is False
    canvas._image_for = None
    _walk(scroll, vm, (5, 46, 60, 60))                                  # ★階段で別の map へ
    assert scroll.following, "⚠⚠ 別の階へ移ったのに追随しない（★見失う）"
    gx, gy = _gap(scroll, canvas)
    assert gx <= 8 and gy <= 8
