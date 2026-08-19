"""地図の画面 — **中身は `ui/map/` へ移りました**（2026-08-01 / 指示書 §8）。

★このファイルは**呼び出し口を変えないために残しています**（指示書 §8）。

    retroux/ui/map/
      window.py     並べる・シグナル・キー・操作
      canvas.py     絵にする（DB を知らない）
      presenter.py  出す中身を組み立てる（widget を知らない）

⚠ **新しく書くときは `ui/map/` の中を直に import してください。**
  ここを厚くすると、また1つのファイルに戻ります。

## なぜ残すのか

`gui.py` `tools/map_prune.py` と、テスト2本が
`from ..ui.map_window import MapWindow` / `load_map_meta` で呼んでいます。
★分割で**呼び出し側を書き換えない**ほうが、
  「振る舞いを変えていない」ことがはっきりします。
"""

from __future__ import annotations

from .map.canvas import (BACKDROP, FRAME, HERE, TRAIL_HEAVY, TRAIL_LIGHT,
                         UNSEEN, TrailView, _tile_color, tile_color)
from .map.presenter import MapPresenter, load_map_meta
from .map.window import MapWindow

__all__ = [
    "MapWindow", "TrailView", "MapPresenter", "load_map_meta",
    "tile_color", "_tile_color",
    "TRAIL_LIGHT", "TRAIL_HEAVY", "HERE", "FRAME", "BACKDROP", "UNSEEN",
]
