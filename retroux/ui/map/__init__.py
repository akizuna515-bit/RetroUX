"""地図の画面（2026-08-01 に `map_window.py` を3つへ分けた / 指示書 §8）。

| ファイル | 持ち場 | 知らないもの |
| --- | --- | --- |
| `canvas.py` | 絵にする（画像・倍率・座標） | **DB / SQLite** |
| `presenter.py` | 出す中身を組み立てる | **widget / Qt の見た目** |
| `window.py` | 並べる・シグナル・キー・操作 | — |

★`from ..ui.map_window import MapWindow` は**そのまま使えます**。
  旧 `map_window.py` が再エクスポートしています（指示書 §8）。
"""

from .canvas import TrailView
from .presenter import MapPresenter, load_map_meta
from .window import MapWindow

__all__ = ["MapWindow", "MapPresenter", "TrailView", "load_map_meta"]
