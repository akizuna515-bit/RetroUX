"""地図にメタタイルを並べるときの**格子**（2026-08-02 / 課題 #65）。

⚠⚠ **依頼者の画面で見つかった不具合**（2026-08-02）:

    「タイルは正しくなった。ただMAPはへの描画がイマイチ」

  実測すると、地図の格子は **15px** なのに画像は **16px** でした。
  1マスごとに 1px ずつ積もり、15×17 のマップで
  **右へ 15px・下へ 17px はみ出して**いました。

★★ ここで固定する契約 ★★

  1. ⚠⚠ 格子と画像の大きさは**必ず同じ**
  2. ⚠ 丸める元は `pick_zoom()` の結果ではなく、**枠に収まる上限**
     （★一度ここを間違え、15px を 8px へ半分に縮めてしまった）
  3. ★絵の無い「見たマス」は色で塗る（穴にして未探索と混ぜない）
  4. ⚠ 8px にも足りないときは現行表示へ譲る
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from retroux.ui.map.canvas import TrailView                    # noqa: E402
from retroux.ui.map.metatile_renderer import (                 # noqa: E402
    CELL_PIXELS, CHARACTER, LEGACY, cell_pixels_for, fit_zoom, scale_for_zoom,
)


@pytest.fixture(scope="module", autouse=True)
def _app():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


# --- 倍率の丸め --------------------------------------------------------

def test_使える1マスの大きさは4つだけ():
    """⚠ 任意の小数倍率は作らない（指示書 §10.4）。"""
    assert CELL_PIXELS == (8, 16, 32, 64)


@pytest.mark.parametrize("avail,want", [
    (7, None),      # ⚠ 一番小さい 8px にも足りない -> 現行へ譲る
    (8, 8),
    (15, 8),
    (16, 16),
    (17, 16),       # ★依頼者の場面。15px ではなく 16px が正しい
    (31, 16),
    (64, 64),
    (200, 64),      # ⚠ 上限を超えて作らない
])
def test_収まる最大の定義済みを選ぶ(avail, want):
    assert fit_zoom(avail) == want


def test_丸めた大きさは画像とぴったり同じ():
    """★★ **ここが本題**。格子＝画像 でなければ端数が積もる。"""
    for px in CELL_PIXELS:
        assert cell_pixels_for(scale_for_zoom(px)) == px


# --- ★★ はみ出さないこと ★★ ------------------------------------------

def _view(cols, rows, *, size=300, with_art=True):
    view = TrailView()
    view.resize(size, size)
    view.tiles = [(x, y, 1, "000")
                  for y in range(rows) for x in range(cols)]
    view.width_tiles, view.height_tiles = cols, rows
    if with_art:
        view.set_metatiles([(x, y, "dummy", 1, "confirmed")
                            for y in range(rows) for x in range(cols)])
    return view


class _AlwaysHave:
    """★画像が全部そろっている体の描画係（ディスクを見ない）。"""

    def can_draw(self, cells):
        return True

    def keys(self, cells):
        return {(x, y) for x, y, *_ in cells}


def test_依頼者の場面で枠からはみ出さない():
    """⚠⚠ 15×17 マス。**これが実際にはみ出していた形**。

    ★2026-08-09 に倍率を **8px 固定**にしました（依頼者の指示
      「ダンジョン、街MAPは8倍固定で良い。固定のほうが分かりやすい」）。
      ⚠ はみ出さないという**不変条件はそのまま**です。
    """
    view = _view(15, 17)
    view._mt_renderer = _AlwaysHave()
    cols, rows = view.bounds()
    zoom = view._metatile_zoom(cols, rows)
    assert zoom == 8, f"★8px 固定のはずが {zoom}px"
    # ★絵の大きさが枠に収まる
    assert cols * zoom <= view.width()
    assert rows * zoom <= view.height()


def test_枠に収まらないときは枠から丸める():
    """⚠⚠ **一度ここを間違えた**（2026-08-02）。

    設定した倍率が枠に入らないとき、**枠に収まる上限から丸める**。
    ⚠ 途中の値から丸めると、収まるはずの 16px を 8px へ**半分に**縮めてしまう。

    ★2026-08-09 に既定が 8px 固定になったので、この道は
      「設定のほうが枠より大きい」ときにだけ通ります。そこを固定します。
    """
    view = _view(15, 17)                    # ★枠 320px -> 上限 320//17 = 18px
    view.zoom_normal = 64                   # ⚠ 設定は枠に入らない大きさ
    view._mt_renderer = _AlwaysHave()
    cols, rows = view.bounds()
    zoom = view._metatile_zoom(cols, rows)
    assert zoom == 16, f"★上限 18px から丸めて 16px のはずが {zoom}px"
    assert cols * zoom <= view.width()
    assert rows * zoom <= view.height()


def test_狭すぎるときは現行表示へ譲る():
    """⚠ 8px にも足りないなら、潰れた絵より現行表示のほうがよい。"""
    view = _view(60, 60, size=320)
    view._mt_renderer = _AlwaysHave()
    # 320 // 60 = 5px -> 8px に足りない
    assert view._metatile_zoom(*view.bounds()) is None


def test_現行表示を選んでいるときは丸めない():
    """★見比べられるようにしてある（指示書 §15.5）。"""
    view = _view(15, 17)
    view._mt_renderer = _AlwaysHave()
    view.set_renderer(LEGACY)
    assert view._metatile_zoom(*view.bounds()) is None
    view.set_renderer(CHARACTER)
    assert view._metatile_zoom(*view.bounds()) == 8      # ★8px 固定


def test_絵が無ければ丸めない():
    """⚠ メタタイルが無いのに格子だけ変えない。"""
    view = _view(15, 17, with_art=False)
    assert view._metatile_zoom(*view.bounds()) is None


# --- ★絵の無いマスを穴にしない -----------------------------------------

def test_絵の無い見たマスは色で塗る():
    """⚠⚠ 依頼者の画面では **255 マス中 85 マスが穴**になっていた。

    ★見たことは分かっているのだから、そう見せる。
      ⚠ 見ていないマスは相変わらず塗らない（指示書 §15.4）。
    """
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtCore import QRect

    view = _view(4, 4, with_art=False)
    # ★左上の1マスだけ絵がある。残り 15 マスは色で塗るはず
    view.tiles = [(x, y, 1, "F00") for y in range(4) for x in range(4)]
    pixmap = QPixmap(64, 64)
    painter = QPainter(pixmap)
    painted = view._fill_cells_without_art(
        painter, QRect(0, 0, 64, 64), 16, {(0, 0)})
    painter.end()
    assert painted == 15


def test_色が分からないマスは塗らない():
    """⚠ 推測で埋めない。★「見たが色は不明」を色で言い切らない。"""
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtCore import QRect

    view = _view(2, 2, with_art=False)
    view.tiles = [(0, 0, 1, None), (1, 0, 1, "___"),
                  (0, 1, 1, "0F0"), (1, 1, 1, "zzz")]
    pixmap = QPixmap(32, 32)
    painter = QPainter(pixmap)
    painted = view._fill_cells_without_art(
        painter, QRect(0, 0, 32, 32), 16, set())
    painter.end()
    assert painted == 1, "★読める色は1マスだけ"


def test_遠くのマスも枠に入るので塗る():
    """★★ **2026-08-02 に契約を変えた**（依頼者「印が出ない」）。

    ⚠ もとは「枠の外は塗らない」でした。ですが枠の元にしていた
      ROM の大きさが**実際より小さい**と分かったので、
      `bounds()` が記録に合わせて広がるようになりました。
      ★結果、記録はすべて枠の中に入ります。
    """
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtCore import QRect

    view = _view(2, 2, with_art=False)
    view.tiles = [(0, 0, 1, "F00"), (9, 9, 1, "F00")]
    assert view.bounds() == (10, 10), "★記録に合わせて広がっている"
    pixmap = QPixmap(160, 160)
    painter = QPainter(pixmap)
    painted = view._fill_cells_without_art(
        painter, QRect(0, 0, 160, 160), 16, set())
    painter.end()
    assert painted == 2


def test_壊れた座標は塗らない():
    """⚠ 枠が広がるとはいえ、**負の座標**までは受け入れない。"""
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtCore import QRect

    view = _view(2, 2, with_art=False)
    view.tiles = [(0, 0, 1, "F00"), (-3, -3, 1, "F00")]
    pixmap = QPixmap(32, 32)
    painter = QPainter(pixmap)
    painted = view._fill_cells_without_art(
        painter, QRect(0, 0, 32, 32), 16, set())
    painter.end()
    assert painted == 1
