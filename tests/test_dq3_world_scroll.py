"""ワールドマップを探索済み範囲まで自由にスクロールする（RX3-0255 / 2026-09-13）。

依頼者の小WI（★正本の写し `docs/requests/260913_dq3-world-map-scroll.md`）:

```text
通常            現在地へ追随
手でスクロール   追随を止める（⚠ 主人公が歩いても毎歩戻さない）
「現在地」       現在地へ戻り、追随を再開
描く範囲         ★これまで見た升だけ（⚠ 未探索は出さない）
```

⚠⚠ 直す前の世界地図は、追随中は**勇者のまわり 48 升だけの絵**でした（`FOLLOW_VIEW`）。
  → スクロールしてもその 48 升の中しか動けず、昔見た升は描かれませんでした。
⚠⚠ 手でスクロールしていても、勇者が見えている所の外にいれば**次の 1 歩で引き戻して**いました
  （★ダンジョンも同じ / `_hero_off_screen`）。
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


def _value() -> int:
    """★世界地図の仮色がある升の値（⚠ 色が無い値だと「塗った」を見分けられない）。"""
    from dq3.ui import map_palette

    return sorted(map_palette.palette(0, None, None))[0]


class _Terrain:
    def __init__(self, width, height, value):
        self.width, self.height = width, height
        self._value = value
        self.tileset = None

    def at(self, x, y):
        return self._value if (0 <= x < self.width and 0 <= y < self.height) else None


class _Source:
    def __init__(self, terrain):
        self._terrain = terrain
        self.available = True
        self.last_error = None

    def get(self, kind, map_id=None):
        return self._terrain


def _vm(at, patches):
    """★見た升は `patches`（x0, y0, x1, y1 / 両端を含む）だけ。⚠ ほかは見ていない。"""
    from dq3.knowledge.seen_map import SeenMap, map_key

    seen = SeenMap(pathlib.Path("使わない"))
    key = map_key(at[0], at[1])
    for x0, y0, x1, y1 in patches:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                seen.mark(key, x, y)

    class VM:
        tile_art = None
        tile_art_runtime = None
        memos = ()

        def __init__(self):
            self._at = at
            self.key = key

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


#: ★離れた 2 か所（⚠ 48 升の窓には同時に入らない）
FAR = ((60, 60, 70, 70), (200, 180, 210, 190))


def _scroll(*, at=(0, 0, 205, 185), patches=FAR, size=256, box=(300, 300)):
    from PySide6.QtWidgets import QApplication

    from dq3.ui.map_window import MapCanvas, MapScroll

    vm = _vm(at, patches)
    canvas = MapCanvas(vm)
    canvas._terrain = _Source(_Terrain(size, size, _value()))
    scroll = MapScroll(canvas)
    scroll.resize(*box)
    scroll.show()
    QApplication.processEvents()
    scroll.fit()
    return scroll, canvas, vm


def _walk(scroll, vm, at, *, mark=True):
    """★1 歩（★見た升も足す = 実機では歩くと周りを見る）。"""
    from PySide6.QtWidgets import QApplication

    vm._at = at
    if mark:
        vm.seen.mark(vm.key, at[2], at[3])
    scroll.fit()
    QApplication.processEvents()


def _gap(scroll, canvas):
    x, y = canvas.hero_at()
    view = scroll.viewport()
    return (abs(x - (scroll.horizontalScrollBar().value() + view.width() // 2)),
            abs(y - (scroll.verticalScrollBar().value() + view.height() // 2)))


def _painted(canvas, x, y) -> bool:
    """★その升に色が置かれているか（⚠ 色ブロックの絵 = 1 升 1 px）。"""
    from dq3.ui.map_window import UNSEEN

    image = canvas._image
    ox, oy = canvas.origin
    px, py = x - ox, y - oy
    if not (0 <= px < image.width() and 0 <= py < image.height()):
        return False
    return image.pixel(px, py) != UNSEEN.rgb()


def _by_hand(scroll, to_min=True):
    """★人がスクロールバーを動かした（★`actionTriggered` が鳴る）。"""
    from PySide6.QtWidgets import QAbstractSlider

    act = (QAbstractSlider.SliderAction.SliderToMinimum if to_min
           else QAbstractSlider.SliderAction.SliderToMaximum)
    scroll.horizontalScrollBar().triggerAction(act)
    scroll.verticalScrollBar().triggerAction(act)


# --- ★描く範囲（指示書 §4）----------------------------------------------------

def test_昔見た所も絵に入る_見ていない所は塗らない():
    _s, canvas, _vm = _scroll()
    assert _painted(canvas, 65, 65), "⚠⚠ 昔見た升が絵に入っていない（★勇者のまわりだけの絵のまま）"
    assert _painted(canvas, 205, 185), "⚠ いま居る所が描けていない"
    # ⚠⚠ No-Spoiler: 2 か所の間は見ていない → 絵の中でも塗らない
    assert not _painted(canvas, 130, 120), "⚠⚠ 見ていない升を塗った（★未探索を開示した）"
    assert canvas.width() >= (210 - 60 + 1) * 8, "⚠ 見た範囲を囲っていない: %d px" % canvas.width()


def test_世界地図は1升8pxのまま():
    from dq3.ui import map_scale

    _s, canvas, _vm = _scroll()
    ox, _oy = canvas.origin
    cells = canvas._image.width()
    assert canvas.width() == cells * map_scale.cell_px(0) == cells * 8, "⚠ 1 升が 8px でない（★拡大縮小は足さない）"
    assert ox % 16 == 0, "⚠ 範囲を 16 升の区切りで取っていない（★1 歩ごとに作り直すことになる）"


def test_スクロールバーで昔の所まで動かせる():
    scroll, canvas, _vm = _scroll()
    bar = scroll.horizontalScrollBar()
    assert bar.maximum() > 0 and scroll.verticalScrollBar().maximum() > 0, "⚠ スクロールバーが出ない"
    _by_hand(scroll)
    ox, oy = canvas.origin
    view = scroll.viewport()
    left, top = bar.value() // 8 + ox, scroll.verticalScrollBar().value() // 8 + oy
    assert left <= 65 <= left + view.width() // 8 and top <= 65 <= top + view.height() // 8, (
        "⚠⚠ 昔見た所（65, 65）まで動かせない（見えているのは %d, %d から）" % (left, top))


# --- ★追随と手の操作（指示書 §2・§3）-------------------------------------------

def test_通常は現在地へ追随する():
    scroll, canvas, vm = _scroll()
    for step in range(1, 5):
        _walk(scroll, vm, (0, 0, 205 + step, 185))
        gx, gy = _gap(scroll, canvas)
        assert gx <= 8 and gy <= 8, "⚠ %d 歩目で現在地が真ん中にない（ずれ %d, %d px）" % (step, gx, gy)


def test_手でスクロールしたら歩いても引き戻さない():
    """⚠⚠ 直す前は、勇者が見えている所の外なら**次の 1 歩で引き戻して**いた。"""
    scroll, canvas, vm = _scroll()
    _by_hand(scroll)
    assert scroll.following is False
    held = (scroll.horizontalScrollBar().value(), scroll.verticalScrollBar().value())
    for step in range(1, 6):
        _walk(scroll, vm, (0, 0, 205 + step, 185))
        now = (scroll.horizontalScrollBar().value(), scroll.verticalScrollBar().value())
        assert now == held, "⚠⚠ %d 歩目で現在地へ引き戻された（%r → %r）" % (step, held, now)
    assert scroll.following is False, "⚠ 歩いただけで追随に戻った"


def test_現在地で戻り_以後は追随する():
    scroll, canvas, vm = _scroll()
    _by_hand(scroll)
    _walk(scroll, vm, (0, 0, 206, 185))
    assert scroll.follow_again() and scroll.following
    gx, gy = _gap(scroll, canvas)
    assert gx <= 8 and gy <= 8, "⚠ 「現在地」で真ん中に戻らない"
    for step in range(1, 4):
        _walk(scroll, vm, (0, 0, 206 + step, 185 + step))
        gx, gy = _gap(scroll, canvas)
        assert gx <= 8 and gy <= 8, "⚠⚠ 「現在地」の後、%d 歩目で追随していない" % step


def test_MAP窓の現在地ボタンも同じ動き():
    """★ワールド専用の操作は作らない（指示書 §3）→ ★いつもの「現在地」ボタンで戻る。"""
    from dq3.ui.map_window import Dq3MapWindow

    vm = _vm((0, 0, 205, 185), FAR)
    win = Dq3MapWindow(vm)
    win.canvas._terrain = _Source(_Terrain(256, 256, _value()))
    win.resize(420, 420)
    win.show()
    from PySide6.QtWidgets import QApplication, QPushButton

    QApplication.processEvents()
    win.scroll.fit()
    _by_hand(win.scroll)
    assert win.scroll.following is False
    button = next(b for b in win.findChildren(QPushButton) if b.text() == "現在地")
    button.click()
    assert win.scroll.following, "⚠⚠ 「現在地」ボタンで追随に戻らない"
    win.close()


def test_見た範囲が広がっても見ている所をずらさない():
    """★手で昔の所を見ている間に、勇者が新しい所を見て絵が左上へ広がっても、★見ている升はそのまま。"""
    scroll, canvas, vm = _scroll()
    _by_hand(scroll, to_min=False)                       # ★右下（いま居る方）を見ている
    ox, oy = canvas.origin
    before = (ox + scroll.horizontalScrollBar().value() // 8, oy + scroll.verticalScrollBar().value() // 8)
    # ★ずっと左上で新しい升を見た（⚠ 見た範囲の左上が広がる）
    vm.seen.mark(vm.key, 10, 12)
    scroll.fit()
    assert canvas.origin != (ox, oy), "⚠ 検査の前提: 範囲が広がっていない"
    nx, ny = canvas.origin
    after = (nx + scroll.horizontalScrollBar().value() // 8, ny + scroll.verticalScrollBar().value() // 8)
    assert after == before, "⚠⚠ 絵が広がったら、見ている所がずれた（%r → %r）" % (before, after)
    assert _painted(canvas, 10, 12) and _painted(canvas, 65, 65)


def test_新しく見た升は描き足す_絵を作り直さない():
    """⚠ 世界地図は 256x256。★1 歩ごとに全体を作り直すと重い → 範囲が同じなら描き足す。"""
    scroll, canvas, vm = _scroll()
    image = canvas._image
    _walk(scroll, vm, (0, 0, 211, 185))                   # ★範囲の中で新しい升
    assert canvas._image is image, "⚠ 範囲が同じなのに絵を作り直した"
    assert _painted(canvas, 211, 185), "⚠⚠ 新しく見た升が描かれていない"


def test_見た升が減ったら作り直す():
    """⚠ 記録を消した（新しい冒険）→ ★描き足しで古い升を残さない。"""
    scroll, canvas, vm = _scroll()
    vm.seen.maps[vm.key].cells.discard((65, 65))
    scroll.fit()
    assert not _painted(canvas, 65, 65), "⚠⚠ 記録から消えた升が残っている"


def test_開き直したら現在地へ戻る():
    scroll, canvas, vm = _scroll()
    _by_hand(scroll)
    scroll.hide()
    scroll.show()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    assert scroll.following, "⚠ 開き直したのに手で動かした所のまま"
    gx, gy = _gap(scroll, canvas)
    assert gx <= 8 and gy <= 8


# --- ★ダンジョンとの操作統一（指示書 §5）----------------------------------------

def _dungeon():
    return _scroll(at=(5, 45, 100, 100), patches=((0, 0, 199, 199),), size=200)


def test_ダンジョンでも手で動かしたら歩いても引き戻さない():
    scroll, canvas, vm = _dungeon()
    _by_hand(scroll)
    held = (scroll.horizontalScrollBar().value(), scroll.verticalScrollBar().value())
    for step in range(1, 13):                           # ⚠ 見えている所の外まで歩く
        _walk(scroll, vm, (5, 45, 100 + step, 100), mark=False)
    gx, _gy = _gap(scroll, canvas)
    assert gx > scroll.viewport().width() // 2, "⚠ 検査の前提: 勇者が見えている所の外に出ていない"
    # ⚠ ダンジョンの絵は勇者のまわりの窓なので、窓が動いたぶんは見ている升を保つ（★スクロールの値は動いてよい）
    assert scroll.following is False, "⚠⚠ 歩いただけで追随に戻った（★引き戻した）"


def test_同じ地図の中で遠くへ飛んだら追随に戻る_階段():
    """★RX3-0107: 洞窟は階が変わっても同じ地図（⚠ 座標だけ飛ぶ）→ ★見失わないよう追随に戻す。"""
    from dq3.ui.map_window import JUMP_CELLS

    scroll, canvas, vm = _dungeon()
    _by_hand(scroll)
    _walk(scroll, vm, (5, 45, 100 + JUMP_CELLS, 100 + JUMP_CELLS), mark=False)
    assert scroll.following, "⚠⚠ 階段で遠くへ飛んだのに追随に戻らない（★見失う）"
    gx, gy = _gap(scroll, canvas)
    assert gx <= 8 and gy <= 8


# --- ★範囲の決め方 --------------------------------------------------------------

def test_範囲は見た所に半窓の余白_16升の区切り_地図の中():
    from dq3.ui.map_window import FOLLOW_VIEW, WORLD_CHUNK, world_extent

    left, top, w, h = world_extent((60, 60, 210, 190), 256, 256, FOLLOW_VIEW)
    assert left <= 60 - FOLLOW_VIEW // 2 and top <= 60 - FOLLOW_VIEW // 2
    assert left + w >= 211 + FOLLOW_VIEW // 2 and top + h >= 191 + FOLLOW_VIEW // 2
    assert left % WORLD_CHUNK == 0 and top % WORLD_CHUNK == 0
    # ★地図の端では地図の中に収める
    left, top, w, h = world_extent((0, 0, 3, 3), 256, 256, FOLLOW_VIEW)
    assert (left, top) == (0, 0) and w >= FOLLOW_VIEW and h >= FOLLOW_VIEW
    left, top, w, h = world_extent((250, 250, 255, 255), 256, 256, FOLLOW_VIEW)
    assert left + w == 256 and top + h == 256 and w >= FOLLOW_VIEW
    # ★地図が窓より小さければ地図ぜんぶ
    assert world_extent((5, 5, 6, 6), 20, 30, FOLLOW_VIEW) == (0, 0, 20, 30)
