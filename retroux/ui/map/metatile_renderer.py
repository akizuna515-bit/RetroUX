"""メタタイル画像で地図を描く（2026-08-02 / マップ指示書 Phase 7・§15）。

★★ **現行の単色表示は消さない**（指示書 §15.5）★★
  新方式が安定するまで、切り替えて見比べられるようにする。

## レイヤー（指示書 §15.2）

    Terrain  背景CHRから作ったメタタイル画像   ← ここが担当
    Marker   現在地・メモ                      ← ★別レイヤー（焼き込まない）

⚠ 主人公の絵を地図へ焼き込まない（指示書 §15.3）。
  現在地は既存の `_draw_here_marker` が上に重ねる。

⚠ 未探索は**空欄か暗い背景**にする（指示書 §15.4）。
  ★黒いメタタイル画像を未探索の代わりに使わない。
  「黒い地形」と「まだ見ていない」は別のこと。
"""

from __future__ import annotations

import pathlib

from PySide6.QtGui import QImage, QPainter, QPixmap

from ...core.bgmap.catalog import SCALES, AssetStore

#: 描き方の名前（設定・GUI で選ぶ / 指示書 §16）
LEGACY = "legacy_pixel"
CHARACTER = "character_metatile"


class MetatileRenderer:
    """メタタイルの PNG を並べて地図を描く。

    ★画像は**辞書から読むだけ**。ここでは作らない（指示書 §10.3）。
    ⚠ 無いものは描かない。**勝手に黒で埋めない**。
    """

    def __init__(self, store: AssetStore | None = None,
                 assets_root=None) -> None:
        if store is None:
            root = pathlib.Path(assets_root) if assets_root else None
            store = AssetStore(root or pathlib.Path("work/map-assets"))
        self.store = store
        #: ★読み込んだ画像を覚えておく（毎回ディスクを読まない）
        self._cache: dict[tuple[str, str], QPixmap | None] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def pixmap_for(self, key: str, scale: str) -> QPixmap | None:
        """メタタイルの画像。⚠ 無ければ None（作らない）。"""
        cached = self._cache.get((key, scale))
        if cached is not None:
            return cached
        if (key, scale) in self._cache:
            return None                  # ★「無い」ことも覚える
        path = self.store.image_path(key, scale)
        if path is None:
            self._cache[(key, scale)] = None
            return None
        image = QImage(str(path))
        if image.isNull():
            self._cache[(key, scale)] = None
            return None
        pixmap = QPixmap.fromImage(image)
        self._cache[(key, scale)] = pixmap
        return pixmap

    def can_draw(self, cells) -> bool:
        """★描けるだけの画像がそろっているか。

        ⚠ 半分も引けないなら、現行表示のままにしたほうがよい
          （まだらに欠けた地図は、単色より読みにくい）。
        """
        if not cells:
            return False
        # ★同じ cells に対しては答えを覚える（RX-0095）。paintEvent のたびに
        #   呼ばれ、世界地図では 52,153 マスぶん辞書を引いていた（0.77 秒/回）。
        #   ⚠ 「無い」が TTL で「有る」に変わりうるので、短い時間だけ覚える。
        import time
        sig = (id(cells), len(cells))
        hit = getattr(self, "_can_draw_cache", None)
        now = time.monotonic()
        if hit is not None and hit[0] == sig and now - hit[2] < 5.0:
            return hit[1]
        found = sum(1 for c in cells
                    if self.store.image_path(c[2], "1x") is not None)
        ok = found * 2 >= len(cells)
        self._can_draw_cache = (sig, ok, now)
        return ok

    def draw(self, painter: QPainter, cells, origin, scale: str,
             cell_pixels: int) -> tuple[int, int]:
        """メタタイルを並べる。

        `cells` は `[(x, y, metatile_key, 回数, 確度)]`。
        戻り値は `(描いた数, 画像が無くて描けなかった数)`。

        ⚠ 描けなかったマスは**そのまま**にする。★未探索と同じ見た目にして、
          「黒い地形」と取り違えさせない（指示書 §15.4）。
        """
        drawn = missing = 0
        left, top = origin
        for x, y, key, _count, _confidence in cells:
            pixmap = self.pixmap_for(key, scale)
            if pixmap is None:
                missing += 1
                continue
            painter.drawPixmap(left + x * cell_pixels,
                               top + y * cell_pixels, pixmap)
            drawn += 1
        return drawn, missing

    def keys(self, cells) -> set:
        """絵を置けるマスの座標。★残りは別の描き方に任せる。"""
        return {(x, y) for x, y, key, *_ in cells
                if self.store.image_path(key, "1x") is not None}


def scale_for_zoom(zoom_px: int) -> str:
    """1マスの画素数から倍率の名前を選ぶ。

    ⚠ 任意の小数倍率は作らない（指示書 §10.4）。★定義済みから選ぶ。

    ⚠⚠ **これだけでは足りません**（2026-08-02 に依頼者の画面で露見）。
      地図の格子が 15px のとき、ここは「1x（16px）」を返します。
      15px の格子に 16px の画像を並べると **1マスごとに 1px ずつずれ**、
      15×17 のマップでは右へ 15px・下へ 17px はみ出しました。
      ★格子のほうを `fit_zoom()` で丸めてから使ってください。
    """
    best, diff = "1x", None
    for name, factor in SCALES.items():
        d = abs(16 * factor - zoom_px)
        if diff is None or d < diff:
            best, diff = name, d
    return best


#: ★メタタイルで描けるときの、1マスの画素数（定義済み倍率そのもの）
CELL_PIXELS = tuple(sorted(int(16 * f) for f in SCALES.values()))


def fit_zoom(zoom_px: int) -> int | None:
    """その大きさに**収まる**、定義済みの1マス画素数。⚠ 無ければ None。

    ★★ **地図の格子とメタタイルの大きさを一致させるため** ★★
      （2026-08-02 / 依頼者の画面で「はみ出す」として見つかった）

    ⚠ 一番小さい 8px にも足りないときは `None` を返します。
      ★そのときは現行表示へ譲ります（潰れた絵を出すより良い）。
    """
    fits = [p for p in CELL_PIXELS if p <= zoom_px]
    return max(fits) if fits else None


def cell_pixels_for(scale: str) -> int:
    """その倍率での1マスの画素数。"""
    return int(16 * SCALES.get(scale, 1))
