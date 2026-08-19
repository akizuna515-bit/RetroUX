"""ROM が言う大きさより広い所を歩く（2026-08-02 / 依頼者の報告）。

⚠⚠ 依頼者「save3では表示されない（印）」

★★ 原因（実測） ★★

  ROM から取った大きさより、**実際の座標のほうが大きい**:

      map $3D  ROM 15×17  ->  実際 29/33
      map $3E  ROM 17×19  ->  実際 32/37
      map $3F  ROM 19×23  ->  実際 33/42

  枠に入らない現在地は描かれず、印が消えていました。
  ⚠ 記録のほうも `note_position` が枠で切っていたので、
    **DB を見ると「全部収まっている」ように見えていました**
    （★切った後を見ていた＝測り方が循環していた）。

★★ ここで固定する契約 ★★

  1. ★見た所と現在地は**必ず枠に入る**
  2. ⚠⚠ 広げたことを**黙らない**（画面に出す）
  3. ⚠ ROM の値は消さない（正しい読み方が分かったら戻せるように）
  4. ★記録も ROM の大きさで切らない
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from retroux.ui.map.canvas import TrailView          # noqa: E402
from retroux.ui.map.presenter import MapPresenter    # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _view(rom_size=(15, 17), tiles=(), here=None):
    v = TrailView()
    v.resize(400, 400)
    v.tiles = [(x, y, 1, "000") for x, y in tiles]
    v.width_tiles, v.height_tiles = rom_size
    v.here = here
    return v


# --- ★★ 印が消えないこと ★★ ------------------------------------------

def test_現在地が枠に入る():
    """★★ **これが依頼者の訴えへの答え**。

    ⚠ map $3D は ROM が 15×17 と言うが、実際は (20,22) に立てる。
    """
    v = _view(here=(20, 22))
    assert v.bounds() == (21, 23)


def test_印の位置が出る():
    """⚠ 枠の外だと `here_center` が None を返し、印が描かれない。"""
    v = _view(here=(20, 22))
    rect = v.target_rect(*v.bounds(), 16)
    assert v.here_center(rect, 16) is not None


def test_見た所も枠に入る():
    """★記録が枠からこぼれない（345 マスが消えていた）。"""
    v = _view(tiles=[(3, 3), (28, 32)])
    assert v.bounds() == (29, 33)


def test_収まっているときはROMの値のまま():
    """⚠ いつも広げるのではない。★ROM の値を尊重する。"""
    v = _view(tiles=[(3, 3)], here=(5, 5))
    assert v.bounds() == (15, 17)
    assert v.beyond_rom() is None


# --- ⚠ 黙って広げない ---------------------------------------------------

def test_はみ出しぶんを数える():
    v = _view(here=(20, 22))
    assert v.beyond_rom() == (6, 6)


def test_ROMの値は消さない():
    """★正しい読み方が分かったら戻せるように、元の値は持っておく。"""
    v = _view(here=(20, 22))
    assert v.rom_bounds() == (15, 17)


def test_ROMの大きさを知らないマップでは何も言わない():
    """⚠ 「はみ出している」と言うには、元の値が要る。"""
    v = _view(rom_size=(None, None), tiles=[(3, 3)])
    assert v.rom_bounds() is None
    assert v.beyond_rom() is None
    assert v.bounds() == (4, 4)


def test_見出しにはみ出しを書く():
    """⚠⚠ **黙って広げない。** ★ROM の読み方が未解明だと分かるように。"""
    class _Detail:
        label, kind = "ロンダルキアへの洞窟 4F", "dungeon_a"
        width, height = 15, 17
        data_pointer, tiles = "0x9E2B", []
        # ★地形の出どころ（2026-08-09）。ここは観測の地図の話
        source, note, outside_rom = "observed", "", 0

    text = MapPresenter.title_text(None, _Detail(), 16, 0, (6, 6))
    assert "ROM の値より広い" in text
    assert "+6×+6" in text
    assert "未解明" in text


def test_はみ出していなければ何も書かない():
    class _Detail:
        label, kind = "街", "town"
        width, height = 19, 25
        data_pointer, tiles = "0x1234", []
        source, note, outside_rom = "observed", "", 0

    text = MapPresenter.title_text(None, _Detail(), 16, 0, None)
    assert "ROM の値より広い" not in text


# --- ★記録も切らない ---------------------------------------------------

def test_記録はROMの大きさで切らない():
    """⚠⚠ ここで切っていたので、DB が「収まっている」ように見えていた。

    ★座標は 1 バイトなので、そこだけは守る。
    """
    import inspect

    from retroux.ui.view_model import ViewModel

    src = inspect.getsource(ViewModel.note_position)
    assert "x > 255 or y > 255" in src
    # ⚠ 昔の切り方が残っていないこと
    assert "if width and x >= width" not in src
    assert "if height and y >= height" not in src
