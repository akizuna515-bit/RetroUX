"""MAP と勇者メモ（別ウィンドウ / RX3-0019 / 2026-08-29）。

依頼者 2026-08-29:「別ウィンドウで OK。」★DQ2 と同じ形にします。

```text
┌─ 見た地図 — RetroUX DQ3 ───┐
│                            │
│            MAP             │   ★現在地 + 訪れた地点
│                            │
├────────────────────────────┤
│ 勇者メモ                   │
│ ・直近メモ1                │
│ ・直近メモ2                │
│ ・直近メモ3   [すべて]     │
└────────────────────────────┘
```

## ⚠⚠ 「完全地図は出さない」（DQ2 の決定を踏襲）

DQ2 での依頼者の判断:

    抽出はする。**出すのは自分が見た所だけ**（完全地図は出さない）。

★ダンジョンの全体図を最初から見せると、**探索そのものが消えます**。

依頼者 2026-08-29 の選択も**「見た所だけ塗る」**でした。

## ★どうやって「見た所だけ」にするか

```text
地形     ROM から起こす（dq3/knowledge/terrain.py）
見た升   画面に映った升の記録（dq3/knowledge/seen_map.py）
描く     ⚠ **記録にある升だけ**を塗る。★それ以外は黒のまま
```

⚠⚠ **地形を先に全部描いてから覆い隠す、ではありません。**
★升ごとに「見たか」を見て、見ていなければ**そもそも色を置きません**。
⚠ 覆い隠す作りにすると、覆いが外れた瞬間に全部見えてしまいます。

## ⚠ 色は「仮色」です（指示書 §9）

★実ゲームの色ではありません。⚠ 地形を**見分けられる**ことだけが目的です。

## ⚠ 重くしない（DQ2 で踏んだ実測）

    地図の描き直しが 1 回 137.8 ms（★1 歩ごと = 267 ms 間隔）
    → 267 ms の枠で 138 ms。⚠ 録画が乗ると FCEUX が 1 フレーム落ちる

★ここでは**現在地の印だけ**を動かし、下地は作り直しません。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QScrollArea, QVBoxLayout,
                               QWidget)

from .location_popup import show_location_popup
from .memo_panel import MemoPanel

#: ★1 マスの大きさ（⚠ 拡大縮小は今回やらない）
CELL_PX = 6

#: ★地点の印の大きさ
MARK_PX = 9
#: ★地点の印の塗り（⚠ 0〜255。★薄く透かして升の絵を見せる / RX3-0190）と輪の太さ
MARK_FILL_ALPHA = 48
MARK_RING_PX = 2

#: ★まだ見ていない升の色（⚠ 背景と同じにしない。「地図の外」と区別する）
UNSEEN = QColor("#14161b")

#: ★★ 探索済みで、いまは別の層の升にかぶせる影（RX3-0205 / ダンジョン探索MAP v1）。
#:   ⚠ 0〜255。★地形は見せて、いまの部屋と見分ける（⚠ 黒くすると前の部屋が消えて見える）
EXPLORED_DIM = QColor(0, 0, 0, 120)

#: ★宝箱の印（RX3-0207）: 未開封 = 金の枠（中を薄く）/ 開封済み = 灰の枠
CHEST_CLOSED = QColor("#f0c040")
CHEST_FILL = QColor(0xf0, 0xc0, 0x40, 90)
CHEST_OPENED = QColor("#8a93a5")

#: ★地図の外（⚠ ここは地図そのものが無い）
OUTSIDE = QColor("#1e222a")

#: ★いま居る升の印
HERO = QColor("#ffd966")

#: ★★ 追随する窓の大きさ（升）。
#:
#: 依頼者 2026-08-30:「DQ2 みたく、まずは自分の位置に追随するようにしたい」
#:
#: ⚠⚠ 見た所**ぜんぶ**を囲うと、離れた 2 か所を歩いたときに
#:   ★地図が 2 つに割れて浮いて見える（実機で実際にそうなった）。
#:   → ★いま居るところを中心にした、決まった大きさの窓だけを出す。
FOLLOW_VIEW = 48

#: ★「地図を見る」画面で、見た所のまわりに取る余白（升）
MARGIN = 6

#: ⚠ 「地図を見る」画面で、これより小さくは切り詰めない
BROWSE_MIN = 64

#: ⚠ 昔の名前（★外から見ている検査がある）
MIN_VIEW = FOLLOW_VIEW

#: ★★ 世界地図・アレフガルドは、追随中も**見た所ぜんぶ**を絵にする（RX3-0255 / 2026-09-13 依頼者の小WI）。
#:
#:   ★スクロールバーで昔の所を見返せるように（⚠ 以前は勇者のまわり 48 升だけの絵で、その外へ行けなかった）。
#:   ⚠ 上の「2 つに割れて浮いて見える」（2026-08-30）は、見た所ぜんぶを**窓へ縮めて**出していたとき。
#:     ★いまは 1 升 8px 固定でスクロールする（RX3-0045）ので、画面に映るのは勇者のまわりだけです。
WORLD_KINDS = (0, 2)
#: ★範囲は 16 升の区切りで取る（⚠ 見た升が 1 つ増えるたびに絵を作り直さない）
WORLD_CHUNK = 16
#: ★手で動かしている間でも、一度にこれだけ飛んだら追随に戻す（升 / ★階段・ワープ / RX3-0107）。
#:   ⚠ 歩き（Turbo でも）で 1 回の描き直しの間にこれほど進むことはない
JUMP_CELLS = FOLLOW_VIEW // 2


def world_extent(bbox, width, height, span):
    """★世界地図の絵の範囲（RX3-0255）。`bbox` = 見た升と現在地を囲む (x0, y0, x1, y1)（両端を含む）。

    ```text
    ★見た所 + 半窓の余白（★端の升でも現在地を真ん中へ寄せられる）
    ★16 升の区切りへ外向きに丸める（⚠ 1 歩ごとに広がらない）
    ⚠ 地図の中に収める / ★窓より狭くしない / ★地図が窓より小さければ地図ぜんぶ
    ```

    ⚠ 見ていない升は範囲に入っても**塗りません**（★範囲は絵の大きさだけ / No-Spoiler）。
    戻り値: (left, top, width, height)（升）
    """
    x0, y0, x1, y1 = bbox
    half = span // 2
    left, right = _at_least(max(0, _chunk_down(x0 - half)), min(width, _chunk_up(x1 + 1 + half)), span, width)
    top, bottom = _at_least(max(0, _chunk_down(y0 - half)), min(height, _chunk_up(y1 + 1 + half)), span, height)
    return left, top, right - left, bottom - top


def _chunk_down(v: int) -> int:
    return (v // WORLD_CHUNK) * WORLD_CHUNK


def _chunk_up(v: int) -> int:
    return -((-v) // WORLD_CHUNK) * WORLD_CHUNK


def _at_least(lo: int, hi: int, need: int, limit: int):
    """⚠ 窓より狭くしない（★地図が窓より小さければ地図ぜんぶ）。`hi` は含まない端。"""
    if limit <= need:
        return 0, limit
    if hi - lo >= need:
        return lo, hi
    hi = min(limit, lo + need)
    return max(0, hi - need), hi


def _grow_box(box, cells, hero):
    """★見た升（と現在地）を囲む箱を広げる（⚠ `box` が None なら作る）。"""
    xs = [x for x, _y in cells]
    ys = [y for _x, y in cells]
    xs.append(hero[0])
    ys.append(hero[1])
    if box is not None:
        xs += (box[0], box[2])
        ys += (box[1], box[3])
    return (min(xs), min(ys), max(xs), max(ys))


def _in_extent(cell, extent) -> bool:
    """★升が範囲の中か（`extent` = (left, top, width, height)）。"""
    left, top, width, height = extent
    return left <= cell[0] < left + width and top <= cell[1] < top + height


def _jumped(was, here) -> bool:
    """★一度に遠くへ飛んだか（★階段・ワープ / RX3-0255）。"""
    return max(abs(here[0] - was[0]), abs(here[1] - was[1])) >= JUMP_CELLS


def _tile_cells(view_model, kind, map_id):
    """★★ **実機が持っている升**（⚠ ROM から起こした升ではない）。

    ## ⚠⚠ ここを間違えると 17% の升が別のタイルになります

      ★2026-09-01 実測（依頼者のセーブ 4 本 / 2,704 升）:

      ```text
      ROM から起こした値   11
      実機の $7400         11 / 27 / 43 / 59   ⚠ bit4・bit5 が乗る
      ```

      ⚠ 違いは **bit4 と bit5 だけ**（★2,704 升すべてでそう）。
      ⚠⚠ ですが `index_of()` は bit4 を**そのまま索引に使う**ので、
        ROM の値で引くと **113/676 の升が別のタイル**になります。

      ★タイルの絵は `$7400` の値で引くものとして実機と突き合わせてあります
      （`RX3-0032` / 634 升一致）。→ ⚠ **引く値も実機のものを使います**。

    ⚠ bit4・bit5 が何かは**未確認**（★別途 `RX3-0044`）。ここでは解きません。

    ⚠ いまの地図と違えば `None`（★前の地図の升で描かない）。
    """
    got = getattr(view_model, "tile_art_runtime", None)
    if got is None:
        return None
    if got.kind != kind:
        return None                       # ⚠⚠ 別の地図の升は使わない
    # ★世界地図（kind 0）は map_id を持たない（RX3-0061）。★ローカルだけ番号も比べる
    from dq3.knowledge.seen_map import is_local

    if is_local(kind) and got.map_id != map_id:
        return None
    return got


def _tile_art(view_model):
    """★ゲーム内のタイルの絵（⚠ 出せなければ `None`）。

    ⚠⚠ **材料は実行時の RAM にしかありません**
      （tileset は `$7200`、CHR は CHR-RAM、パレットは `$3F00`）。
      ★いまはセーブステートから作ります（`RX3-0032`）。

    ⚠ 出せなければ**色ブロックのまま**にします（★黙って落ちない）。
    """
    got = getattr(view_model, "tile_art", None)
    return got() if callable(got) else got


def _palette(kind, map_id=None, tileset=None) -> dict:
    """地形 → 色（★仮色）。⚠ 実ゲームの色ではありません（指示書 §9）。

    ★色の決め方は `dq3/ui/map_palette.py`（⚠ 実測をもとにした仮色）。
    ⚠ ここで色を作らない（★2 か所で作ると、同じ地形が違う色に見える）。
    """
    from . import map_palette

    return {tile: QColor(*rgb)
            for tile, rgb in map_palette.palette(kind, map_id,
                                                 tileset).items()}


def art_reason(view_model, kind, map_id) -> str:
    """★タイルの絵が出せない**理由**（⚠ 出せているときは空 / RX3-0097 C）。

    ⚠⚠ 依頼者「別の地図を選ぶと色ブロックのまま」→ ★**壊れているのではなく材料が無い**。
    ★材料（tileset `$7200` / CHR-RAM / パレット `$3F00`）は**実行時の RAM にしかない**ので、
    ⚠ いま居る地図しか本物の絵は出せません（`RX3-0032`）。
    → ★黙って色ブロックにせず、理由を書きます。
    """
    if _tile_art(view_model) is None:
        return "⚠ タイルの絵がまだありません（★実機につないで地図に入ると出ます）"
    if _tile_cells(view_model, kind, map_id) is None:
        return "⚠ この地図の絵はありません（★絵は**いま居る地図**の分だけ / 色は仮の色）"
    return ""


def place_label(vm, kind, map_id) -> str:
    """★下に出す場所の呼び名（⚠ 地名は `vm.place_name` だけから / RX3-0094）。"""
    if kind == 0:
        return "世界地図"
    if kind == 2:
        return "アレフガルド"
    from dq3.knowledge.seen_map import is_local

    if not is_local(kind):
        return "⚠ 種別 %s" % kind
    got = None
    try:
        got = vm.place_name(map_id)
    except Exception:                                      # noqa: BLE001
        got = None
    return got or ("地図 %s" % map_id)


class MapCanvas(QFrame):
    """地図の絵（★見た升の地形 + 現在地 + 訪れた地点）。

    ⚠⚠ **見ていない升には、そもそも色を置きません**（★覆い隠すのではなく）。
    """

    def __init__(self, view_model, *, on_click=None, follow=True,
                 parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self._on_click = on_click
        #: ★★ いま居るところに追随するか。
        #:
        #: ⚠⚠ 用途が違うので**兼ねない**（依頼者 2026-08-30）:
        #:   `True`  いつもの窓 → ★いま何が近くにあるか（48 升）
        #:   `False` 地図を見る画面 → ★どこへ行ったか（地図の全体）
        self.follow = bool(follow)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        #: ★いま画面に出ている地点の当たり判定（⚠ 描いたときに作り直す）
        self._hits: list[tuple[QRect, str]] = []
        #: ★地形の絵（⚠ 1 升 1 ピクセル。描くときに拡大する）
        self._image = None
        #: ⚠ どの地図の、何升ぶんで作った絵か（★変わったときだけ作り直す）
        self._image_for = None
        self._terrain = None
        #: ⚠ どのタイルの絵で描いたか（★変わったら覚えた升を捨てる）
        self._last_art = None
        #: ★索引 → 升 1 つの絵（⚠ `forget_tiles()` で捨てる）
        self._tile_cache: dict = {}
        #: ⚠ 人が変えられる倍率（★いまは 1.0 固定 / `map_scale`）
        self.zoom = 1.0
        #: ★人が選んだ 1 升の大きさ（★地図の分類ごと: local / dungeon / RX3-0206）
        self.levels: dict = {}
        #: ⚠ いまどこに居るか（★1 升の px は**種別**で決まる）
        self._at_now = None
        #: ⚠⚠ **実際にタイルで描いたか**（★絵を持っているか、ではない）
        self._drew_tiles = False

    # --- ★地形の絵 ------------------------------------------------------

    @property
    def terrain(self):
        """⚠ 遅らせて作る（★起動を重くしない / ROM が無くても落ちない）。"""
        if self._terrain is None:
            from dq3.knowledge.terrain import TerrainSource

            self._terrain = TerrainSource()
        return self._terrain

    def _build_image(self, key, kind, map_id, seen, hero_x, hero_y, explored=frozenset(), extent=None):
        """★見た升だけを塗った絵を作る。⚠ 見ていない升は塗らない。

        ⚠⚠ **毎回作らない。** 世界地図は 256x256 = 65,536 升あるので、
        ★1 秒に 2 回作り直すと画面が固まる（DQ2 で 137.8 ms の実績）。
        """
        got = self.terrain.get(kind, map_id)
        if got is None:
            return None
        # ★★ **いま居るところに追随する**（依頼者 2026-08-30）。
        #
        #   ⚠⚠ 見た所ぜんぶを囲うと、離れた 2 か所を歩いたときに
        #     ★地図が 2 つに割れて浮いて見える（実機でそうなった）。
        #   → ★主人公を真ん中に置いた、決まった大きさの窓を出す。
        #
        #   ⚠ 地図が窓より小さければ、★地図ぜんぶを出す（縮めない）。
        span = self._follow_span(kind)
        if extent is not None:
            # ★★ 世界地図の追随（RX3-0255）: 見た所ぜんぶ（★範囲は `world_extent` / 1 升 8px のままスクロール）
            left, top, width, height = extent
        elif not self.follow:
            # ★追随しない画面（「地図を見る」）では、**見た所のまわり**を出す。
            #
            #   ⚠ 地図ぜんぶを出すと、世界地図（256x256）では
            #     ★歩いた所が**点にしか見えない**（2026-08-30 に描いて確かめた）。
            #   ⚠ かといって切り詰めすぎると、離れた 2 か所が入らない。
            #   → ★見た所を全部囲い、まわりに余白を足す。
            if seen:
                xs = [x for x, _y in seen]
                ys = [y for _x, y in seen]
                left, right = min(xs) - MARGIN, max(xs) + MARGIN
                top, bottom = min(ys) - MARGIN, max(ys) + MARGIN
                # ⚠ 小さすぎると拡大しすぎる（★真ん中を保って広げる）
                if right - left + 1 < BROWSE_MIN:
                    mid = (left + right) // 2
                    left, right = mid - BROWSE_MIN // 2, mid + BROWSE_MIN // 2
                if bottom - top + 1 < BROWSE_MIN:
                    mid = (top + bottom) // 2
                    top, bottom = mid - BROWSE_MIN // 2, mid + BROWSE_MIN // 2
                left = max(0, left)
                top = max(0, top)
                right = min(got.width - 1, right)
                bottom = min(got.height - 1, bottom)
                width = right - left + 1
                height = bottom - top + 1
            else:
                left = top = 0
                width, height = got.width, got.height
            self.origin = (left, top)
        elif got.width <= span and got.height <= span:
            left = top = 0
            width, height = got.width, got.height
        else:
            left = int(hero_x) - span // 2
            top = int(hero_y) - span // 2
            # ⚠ 端では地図からはみ出さないように寄せる（★窓の大きさは保つ）
            left = max(0, min(left, max(0, got.width - span)))
            top = max(0, min(top, max(0, got.height - span)))
            width = min(span, got.width)
            height = min(span, got.height)
        self.origin = (left, top)
        art = _tile_art(self.vm)
        # ⚠ 倍率の決め方が変わるので、★どちらで描いたかを覚えておく
        if art is not self._last_art:
            self.forget_tiles()           # ⚠ 別の地図の絵を使い回さない
            self._last_art = art
        # ⚠⚠ 升の値は**実機のもの**を使う（★ROM の値では索引がずれる）
        live = _tile_cells(self.vm, kind, map_id)
        # ⚠⚠ **実際にタイルで描いたか**を覚える（★`_tiled()` が見る）。
        #   ⚠ 「絵を持っている」と「タイルで描いた」は別です。
        #   ★取り違えると、地形は正しいのに **16 分の 1 の大きさ**で出ます。
        self._drew_tiles = art is not None and live is not None
        if self._drew_tiles:
            self._fallback_palette = _palette(kind, map_id, getattr(got, "tileset", None))
            # ★町・洞窟は「勇者の升の層」と違う升を黒く描く（RX3-0191）。⚠ 世界地図は層を持たない
            hero_raw = live.at(int(hero_x), int(hero_y)) if kind not in (0, 2) else None
            return self._tile_image(live, art, seen, left, top, width, height, hero_raw=hero_raw,
                                    explored=explored)
        # ⚠⚠ **いまの地図の材料が無ければタイルで描きません**（RX3-0046）。
        #
        #   ★材料は「地図が変わったとき」に書かれます。⚠ 暗転中・戦闘中は
        #   見送るので、★材料が**前の地図のまま**という時間が生まれます。
        #   ⚠ そこで前の地図の tileset で描くと、**別の絵**が出ます。
        #   → ★色ブロックに戻します（⚠ 地形は正しく見分けられる）。
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(OUTSIDE)
        colours = _palette(kind, map_id, getattr(got, "tileset", None))
        image.fill(UNSEEN)
        # ⚠⚠ **記録にある升だけ**を塗る（★覆い隠すのではない）
        self._paint_blocks(image, got, colours, seen, left, top, width, height)
        return image

    @staticmethod
    def _paint_blocks(image, got, colours, cells, left, top, width, height) -> None:
        """★色ブロックで升を塗る（⚠ 記録にある升だけ / ★世界地図の描き足しにも使う / RX3-0255）。"""
        for x, y in cells:
            px, py = x - left, y - top
            if not (0 <= px < width and 0 <= py < height):
                continue
            tile = got.at(x, y)
            if tile is None:
                continue
            colour = colours.get(tile)
            if colour is not None:
                image.setPixel(px, py, colour.rgb())

    def _tile_pixmap(self, art, raw: int, hero_raw: int | None = None):
        """★1 升ぶんの絵（⚠ **同じ升を何度も作らない** / 指示書 §12 第一段階）。

        ## ⚠⚠ ここが遅さの元でした

          ★もとは `setPixel` を升ごとに **256 回**呼んでいました。
          ⚠ 48x48 升なら **589,824 回**です。
          → ★`QImage` をバイト列から**一度に**作り、⚠ 索引で覚えます。
        """
        from dq3.knowledge.tile_art import CELL, index_of

        # ★覚えるのは「決まった索引」（⚠ 同じ升の値でも、勇者の層しだいで黒になる / RX3-0191）
        key = index_of(raw, hero_raw)
        cache = getattr(self, "_tile_cache", None)
        if cache is None:
            cache = self._tile_cache = {}
        got = cache.get(key)
        if got is not None:
            return got
        block = art.block(raw, hero_raw)
        if block is None:
            return None
        # ⚠ `QImage` は元のバイト列を**参照**するので、★保持しておく
        image = QImage(block, CELL, CELL, CELL * 3,
                       QImage.Format.Format_RGB888)
        cache[key] = (image, block)
        return cache[key]

    def forget_tiles(self) -> None:
        """⚠ 地図が変わったら、★覚えた升の絵を捨てる（別の地図では別の絵）。"""
        self._tile_cache = {}

    def _fallback_colour(self, raw: int):
        """★タイルの絵が無い升の色（★色ブロックと同じ表）。"""
        colours = getattr(self, "_fallback_palette", None)
        if colours is None:
            return None
        return colours.get(raw)

    def _tile_image(self, got, art, seen, left, top, width, height, hero_raw=None,
                    explored=frozenset()):
        """★★ ゲーム内のタイルで描く（RX3-0032 / RX3-0043）。

        ⚠ 升 1 つが 16x16 になるので、絵は色ブロックの **16 倍**です。
        ⚠⚠ **見ていない升は塗りません**（★色ブロックと同じ約束）。

        ★描き方（指示書 §12）:

        ```text
        第一段階  升の絵を索引でキャッシュ（⚠ 同じ絵を作り直さない）
        第二段階  地図が変わらなければ、★この絵ごとキャッシュ（`_image_now`）
        ```
        """
        from dq3.knowledge.tile_art import CELL

        image = QImage(width * CELL, height * CELL,
                       QImage.Format.Format_RGB32)
        image.fill(UNSEEN)
        self._paint_tiles(image, got, art, seen, left, top, width, height,
                          hero_raw=hero_raw, explored=explored)
        return image

    def _paint_tiles(self, image, got, art, cells, left, top, width, height, hero_raw=None,
                     explored=frozenset()) -> None:
        """★升をタイルで描く（⚠ 記録にある升だけ / ★世界地図の描き足しにも使う / RX3-0255）。"""
        from dq3.knowledge.tile_art import CELL, DARK_INDEX, index_of

        painter = QPainter(image)
        try:
            for x, y in cells:
                px, py = x - left, y - top
                if not (0 <= px < width and 0 <= py < height):
                    continue
                raw = got.at(x, y)
                if raw is None:
                    continue
                # ★★ 探索済みで、いまは別の層の升（RX3-0205）: ⚠ 黒くせず、地形を描いて影をかぶせる
                #   ★見ていない升（seen に無い）はここへ来ない（⚠ 探索済み ⊆ 見た升 / No-Spoiler）
                dim = (hero_raw is not None and (x, y) in explored
                       and index_of(raw, hero_raw) == DARK_INDEX)
                tile = self._tile_pixmap(art, raw, raw if dim else hero_raw)
                if tile is None:
                    # ★絵の無い升は色ブロックで埋める（★世界地図の未知のタイル id / RX3-0061）
                    colour = self._fallback_colour(raw)
                    if colour is not None:
                        painter.fillRect(px * CELL, py * CELL, CELL, CELL, colour)
                    continue
                painter.drawImage(px * CELL, py * CELL, tile[0])
                if dim:
                    painter.fillRect(px * CELL, py * CELL, CELL, CELL, EXPLORED_DIM)
        finally:
            painter.end()

    def _image_now(self):
        """★いまの地図の絵。⚠ 出せなければ `None`。"""
        from dq3.knowledge.seen_map import map_key

        at = self.vm.position()
        if at is None:
            return None, None
        kind, map_id, _x, _y = at
        key = map_key(kind, map_id)
        seen = self.vm.seen.cells(key)
        # ★探索済み（RX3-0205）。⚠ 持たない画面（検査の偽物）では空
        store = getattr(self.vm, "explored", None)
        explored = store.cells(key) if store is not None else frozenset()
        # ⚠ 追随するので、**居る場所が変わっても**作り直す
        # ★町・洞窟は勇者の居る升で黒く塗る升が変わる（RX3-0191）→ ★「地図を見る」でも居る升を含める
        #   ⚠ 世界地図（256x256）は層が無いので、今までどおり（★作り直しを増やさない）
        # ⚠ 1 升の px は**種別**で決まる（★`_scale_for` が見る）
        self._at_now = at
        if self.follow and kind in WORLD_KINDS:
            # ★★ 世界地図は追随中も見た所ぜんぶ（RX3-0255）。⚠ 居る場所では作り直さない（★増えた升を描き足す）
            return self._world_image_now(key, kind, map_id, seen, _x, _y), at
        # ⚠⚠ 材料（絵・実機の升）も鍵に入れる（RX3-0428）。⚠ 無いと、セーブを読んだ直後の
        #   色ブロックが、立ち止まっている間ずっと使い回される（★材料が後から届いても描き直さない）。
        #   ★どちらも材料のファイルが書き換わったときだけ別の物になる（`vm.tile_art`）→ 描き直しは増えない
        stuff = (_tile_art(self.vm), _tile_cells(self.vm, kind, map_id))
        stamp = ((key, len(seen), len(explored), _x, _y, stuff) if (self.follow or kind not in (0, 2))
                 else (key, len(seen), len(explored), stuff))
        if stamp != self._image_for:
            self._image = self._build_image(key, kind, map_id, seen,
                                            _x, _y, explored=explored)
            self._image_for = stamp
        return self._image, at

    def _world_image_now(self, key, kind, map_id, seen, hero_x, hero_y):
        """★★ 世界地図の絵（RX3-0255）: 追随中も**見た所ぜんぶ**（★スクロールで昔の所を見返せる）。

        ⚠⚠ 毎歩作り直しません（★世界地図は 256x256 升 / タイルなら 1 升 16x16）:

        ```text
        見た升・材料・地図が同じ          ★そのまま（⚠ 歩いただけでは作り直さない）
        見た升が増えただけ・範囲も同じ    ★増えた升だけ描き足す
        範囲が広がった・升が減った・地図や材料が変わった   ⚠ 作り直す
        ```
        """
        art, live = _tile_art(self.vm), _tile_cells(self.vm, kind, map_id)
        stamp = ("world", key, len(seen), art, live)
        hero = (int(hero_x), int(hero_y))
        was = getattr(self, "_world", None)
        inside = was is not None and _in_extent(hero, was["extent"])
        if stamp == self._image_for and self._image is not None and inside:
            return self._image
        same = (was is not None and self._image is not None and self._image_for is not None
                and self._image_for[:2] == ("world", key) and self._image_for[3:] == (art, live))
        got = self.terrain.get(kind, map_id)
        if got is None:
            self._image, self._image_for, self._world = None, stamp, None
            return None
        if same:
            fresh = seen - was["painted"]
            if len(was["painted"]) + len(fresh) == len(seen):      # ⚠ 減った升が無い（★記録を消していない）
                box = _grow_box(was["box"], fresh, hero)
                if world_extent(box, got.width, got.height, FOLLOW_VIEW) == was["extent"]:
                    self._paint_more(fresh, was["extent"], kind, map_id, got)
                    was["painted"] |= fresh
                    was["box"] = box
                    self._image_for = stamp
                    return self._image
        # ⚠ 作り直す（★範囲は見た所ぜんぶ + 半窓 / 16 升の区切り）
        box = _grow_box(None, seen, hero)
        extent = world_extent(box, got.width, got.height, FOLLOW_VIEW)
        self._image = self._build_image(key, kind, map_id, seen, hero_x, hero_y, extent=extent)
        self._image_for = stamp
        self._world = ({"painted": set(seen), "box": box, "extent": extent}
                       if self._image is not None else None)
        return self._image

    def _paint_more(self, cells, extent, kind, map_id, got) -> None:
        """★増えた升だけ、いまの絵へ描き足す（⚠ 作り直したときと同じ描き方 / RX3-0255）。"""
        left, top, width, height = extent
        if self._drew_tiles:
            self._paint_tiles(self._image, _tile_cells(self.vm, kind, map_id), _tile_art(self.vm),
                              cells, left, top, width, height)
        else:
            colours = _palette(kind, map_id, getattr(got, "tileset", None))
            self._paint_blocks(self._image, got, colours, cells, left, top, width, height)

    def unit_now(self) -> float:
        """★いまの 1 升の画面上の px（★`MapScroll` が、見ている所を保つのに使う / RX3-0255）。"""
        return self._px_per_cell(self._scale_for(None))

    # --- ★地点をどこへ置くか --------------------------------------------

    def _marks(self, world_kind=None) -> list[tuple[int, int, str]]:
        """★訪れた地点を**世界地図の升**で返す（指示書 §11 / RX3-0132）。

        ## ⚠⚠ どちらの世界の地点か（RX3-0315 / 2026-09-20）

          ⚠ 依頼者「アレフガルドでの緑の丸が誤って表示される。
            おそらく下の世界の正解地図は別座標。」★そのとおりでした。

          ```text
          上の世界      world_main      256 x 256
          アレフガルド  world_alefgard  158 x 138   ⚠ 升の意味も広さも違う
          ```

          ★`world_kind` を渡すと、**その世界の地点だけ**返します。
          ⚠ 世界が分からない記録（`world_kind is None` / ★この直しより前のもの）は
            **上の世界のときだけ**出します（⚠ 下の世界には推測で置かない）。

        ⚠⚠ ここは長らく `20 + i * 40` と**画面の隅から並べる**だけでした。
          ★座標を持っていなかった頃の仮置きです（`RX3-0016` 待ち）。
          ⚠ いまは `location-book` が世界座標（`world_x` / `world_y`）を持っているので、
            **本当の場所**に置きます。⚠ 持っていない地点は**出しません**（★推測で置かない）。

        ⚠ 戻すのは升の座標です。★画面のどこに描くかは `paintEvent` が
          地形と**同じ変換**で決めます（⚠ 2 か所で計算すると必ずずれます）。
        """
        book = getattr(self.vm, "location_book", None)
        if book is None:
            return []
        from dq3.knowledge import location_book as LB

        cands = []
        for order, loc_id in enumerate(self.vm.known_locations()):
            got = getattr(book, "locations", {}).get(loc_id)
            if got is None or got.world_x is None or got.world_y is None:
                continue                       # ⚠ 世界座標を知らない地点は置かない
            if world_kind is not None:
                where = getattr(got, "world_kind", None)
                if where is None:
                    if int(world_kind) != LB.WORLD_KIND:
                        continue               # ⚠ 分からない記録は下の世界に置かない
                elif int(where) != int(world_kind):
                    continue                   # ⚠⚠ よその世界の地点は出さない
            source = getattr(got, "name_source", "")
            # ⚠⚠ 場所の中の部屋・塔の階（★仮名のもの）は ◯ にしない（RX3-0275 / 依頼者「ここのmapに◯があるが、何もない」）。
            #   ★世界地図に入口があるのは、それを中に持つ場所だけ（⚠ 部屋の升は入口の升ではない）。
            #   ⚠ 正式な名前になった場所は、仮名の頃の付け方（name_rule）が残っていても出す（★ルザミ・ノルドの洞窟）
            inner = getattr(got, "name_rule", "") in (LB.PARENT_RULE, LB.FLOOR_RULE) \
                or getattr(got, "parent_location_id", "")
            if source == LB.PROVISIONAL and inner:
                continue
            known = source in LB.KNOWN_SOURCES
            cands.append((0 if known else 1, order, (int(got.world_x), int(got.world_y)), loc_id))
        out = []
        seen: set = set()
        for _known, _order, at, loc_id in sorted(cands):
            if at in seen:
                continue                       # ★同じ升の ◯ は 1 つ（★名前の確かな場所を先に）
            seen.add(at)
            out.append((at[0], at[1], loc_id))
        return out

    def _tiled(self) -> bool:
        """★いまタイルで描いているか（⚠ 色ブロックなら False）。

        ⚠⚠ **絵を持っているか**ではなく、★**実際に描いたか**です（RX3-0046）。
          ⚠ いまの地図の材料が無ければ、絵を持っていても色ブロックで描きます。
        """
        return bool(getattr(self, "_drew_tiles", False))

    def _scale_for(self, image, box=None):
        """★作った絵を画面へ出すときの倍率。

        ## ⚠⚠ **枠の大きさを見ません**（RX3-0045）

          ★DQ2 は 2026-08-18 に、widget を枠へ伸ばしてから「入るか」を
          測って、⚠ **測るたびに前提が変わり点滅**しました。

        ```text
        1 升の px   ★地図の種別だけで決まる（`map_scale`）
        収まらない  ⚠ 縮めずスクロール（`MapScroll`）
        ```

        @param box ⚠ 受け取るが**使いません**（★古い呼び方との互換）。
        """
        from . import map_scale

        _at = getattr(self, "_at_now", None)
        kind = _at[0] if _at else map_scale.KIND_LOCAL
        return map_scale.image_scale(kind, tiled=self._tiled(), zoom=self._zoom_now())

    def _zoom_now(self) -> float:
        """★いま使う倍率（★選んだ 1 升の大きさ x 人の倍率 / RX3-0206）。"""
        from . import map_scale

        at = getattr(self, "_at_now", None)
        kind = at[0] if at else map_scale.KIND_LOCAL
        levels = getattr(self, "levels", None) or {}
        level = levels.get(map_scale.map_class(kind)) or map_scale.default_level(kind)
        return map_scale.level_zoom(kind, level) * float(self.zoom or 1.0)

    def level_now(self) -> str:
        """★いまの地図の 1 升の大きさ（小 / 標準 / 大 / RX3-0206）。"""
        from . import map_scale

        at = getattr(self, "_at_now", None) or self.vm.position()
        kind = at[0] if at else map_scale.KIND_LOCAL
        levels = getattr(self, "levels", None) or {}
        return levels.get(map_scale.map_class(kind)) or map_scale.default_level(kind)

    def set_level(self, level: str) -> bool:
        """★1 升の大きさを選ぶ（★いまの地図の分類ぶん / ⚠ 世界地図は変えない / RX3-0206）。"""
        from . import map_scale

        at = getattr(self, "_at_now", None) or self.vm.position()
        kind = at[0] if at else map_scale.KIND_LOCAL
        if map_scale.map_class(kind) == "world" or level not in map_scale.SIZE_LABELS:
            return False
        if getattr(self, "levels", None) is None:
            self.levels = {}
        self.levels[map_scale.map_class(kind)] = level
        self._image_for = None             # ★追随する窓の広さも変わるので作り直す
        return True

    def _follow_span(self, kind) -> int:
        """★追随する窓の升数（RX3-0206）。★1 升が小さいときは広く（⚠ 画面の上の大きさはおよそ同じ）。"""
        from . import map_scale

        if kind in (map_scale.KIND_WORLD, map_scale.KIND_ALEFGARD):
            return FOLLOW_VIEW
        px = map_scale.cell_px(kind, zoom=self._zoom_now())
        return max(FOLLOW_VIEW, FOLLOW_VIEW * map_scale.SOURCE_CELL // max(1, px))

    def _px_per_cell(self, scale: float) -> float:
        """★画面の上で 1 升が何ピクセルになるか。

        ```text
        色ブロック   絵の 1 升 =  1 px  →  倍率そのもの
        タイル       絵の 1 升 = 16 px  →  ⚠ 倍率 x 16
        ```

        ⚠⚠ ここを間違えると、**地形は正しいのに印だけ 16 倍ずれます**。
        """
        from . import map_scale

        if not self._tiled():
            return scale
        return scale * map_scale.SOURCE_CELL

    def content_size(self):
        """★★ 中身が画面上で何ピクセルになるか（⚠ `None` なら出せない）。

        ⚠⚠ **窓の大きさを見ません。** ★`MapScroll` がこれを
          `setFixedSize()` に渡し、収まらなければスクロールバーが出ます。
        """
        from . import map_scale

        image, at = self._image_now()
        if image is None or at is None:
            return None
        src = map_scale.SOURCE_CELL if self._tiled() else 1
        cells_w = max(1, image.width() // src)
        cells_h = max(1, image.height() // src)
        return map_scale.draw_size(at[0], cells_w, cells_h, zoom=self._zoom_now())

    def hero_at(self):
        """★現在地が中身の中で何ピクセル目か（⚠ 分からなければ `None`）。

        ★`MapScroll` が「地図に入ったとき現在地へ寄せる」のに使います。
        """
        image, at = self._image_now()
        if image is None or at is None:
            return None
        _kind, _map_id, x, y = at
        unit = self._px_per_cell(self._scale_for(image))
        ox, oy = getattr(self, "origin", (0, 0))
        return (int((x - ox) * unit + unit / 2),
                int((y - oy) * unit + unit / 2))

    def _draw_terrain(self, painter):
        """★地形を描く。⚠ 何も描けなければ `None`。

        ⚠⚠ **見ていない升には色が入っていません**（`_build_image`）。
          ★ここで覆い隠しているのではありません。
        """
        image, at = self._image_now()
        if image is None:
            return None
        box = self.rect().adjusted(2, 2, -2, -2)
        if box.width() <= 0 or box.height() <= 0:
            return None
        scale = self._scale_for(image)
        if scale <= 0:
            return None
        w = int(image.width() * scale)
        h = int(image.height() * scale)
        # ★枠より小さければ真ん中に。⚠ 大きければ**左上から**（★端が切れない）
        x0 = box.x() + max(0, (box.width() - w) // 2)
        y0 = box.y() + max(0, (box.height() - h) // 2)
        painter.drawImage(QRect(x0, y0, w, h), image)

        if not self.follow:
            # ⚠ そこに**居るわけではない**ので、★現在地の印は出さない
            return QRect(x0, y0, w, h)

        # ★いま居る升（⚠ 地形の上に描く）
        #
        #   ⚠⚠ **1 升が何ピクセルか**で置く（★倍率そのものではない）。
        #     タイルで描くと絵の 1 升は 16 ピクセルなので、
        #     ⚠ 倍率だけで掛けると印が **16 分の 1 の場所**へ寄ります
        #     （★2026-09-01 のキャプチャで左上に固まって出た）。
        _kind, _map_id, hero_x, hero_y = at
        unit = self._px_per_cell(scale)
        cell = max(2, int(unit))
        painter.setPen(QPen(HERO, 1))
        painter.setBrush(HERO)
        ox, oy = getattr(self, "origin", (0, 0))
        painter.drawRect(QRect(x0 + int((hero_x - ox) * unit),
                               y0 + int((hero_y - oy) * unit), cell, cell))
        # ★地点の印も**同じ変換**で置く（⚠ 2 か所で計算しない / RX3-0132）
        self._place = {"x0": x0, "y0": y0, "unit": unit, "origin": (ox, oy),
                       "kind": _kind, "w": w, "h": h}
        return QRect(x0, y0, w, h)

    def _draw_chests(self, painter, place) -> int:
        """★見つけた宝箱の印（RX3-0207）。戻り値: 描いた数。

        ⚠ 記録にある宝箱だけ（= 探索済みの升で見つけたもの / ★ROM から先回りで出さない）。
        ★未開封 = 金の枠（中を薄く）/ 開封済み = 灰の枠。⚠ 升の絵を隠さないよう、枠を主にする。
        """
        at = getattr(self, "_at_now", None)
        getter = getattr(self.vm, "chest_marks", None)
        if at is None or getter is None or at[1] is None:
            return 0
        try:
            marks = getter(at[1])
        except Exception:                                  # noqa: BLE001 ★印が出ないだけ
            return 0
        unit = place["unit"]
        ox, oy = place["origin"]
        size = max(4, int(unit * 0.7))
        drawn = 0
        for cx, cy, state in marks:
            px = place["x0"] + int((cx - ox) * unit + (unit - size) / 2)
            py = place["y0"] + int((cy - oy) * unit + (unit - size) / 2)
            if not (place["x0"] <= px <= place["x0"] + place["w"]
                    and place["y0"] <= py <= place["y0"] + place["h"]):
                continue
            opened = state == "OPENED"
            painter.setBrush(Qt.BrushStyle.NoBrush if opened else CHEST_FILL)
            painter.setPen(QPen(CHEST_OPENED if opened else CHEST_CLOSED, 2))
            painter.drawRect(QRect(px, py, size, size))
            drawn += 1
        return drawn

    def paintEvent(self, event) -> None:                 # noqa: N802 (Qt の名前)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e222a"))
        self._hits = []

        self._place = None
        drawn = self._draw_terrain(painter)

        # ★★ 地点の印は**世界地図のときだけ**（RX3-0132 / 2026-09-09）。
        #   ⚠⚠ 以前は画面の隅から機械的に並べていました（★座標が無かった頃の仮置き）。
        #     依頼者「緑のポチの必要性はなんだっけ？」— ★意味の無い場所に出ていました。
        #   ⚠ 街やダンジョンの中では世界座標を当てられないので、★出しません。
        marks = []
        place = getattr(self, "_place", None)
        if place is not None and place["kind"] in (0, 2):
            unit = place["unit"]
            ox, oy = place["origin"]
            for cx, cy, loc in self._marks(place["kind"]):
                px = place["x0"] + int((cx - ox) * unit + unit / 2)
                py = place["y0"] + int((cy - oy) * unit + unit / 2)
                # ⚠ 描いた地形の外へはみ出す印は出さない（★スクロールで切れている所）
                if place["x0"] <= px <= place["x0"] + place["w"] \
                        and place["y0"] <= py <= place["y0"] + place["h"]:
                    marks.append((px, py, loc))
        # ★★ 宝箱（RX3-0207）: ⚠ 町・洞窟・塔の中だけ / 見つけたものだけ
        if place is not None and place["kind"] not in (0, 2):
            self._draw_chests(painter, place)
        if drawn is None:
            painter.setPen(QPen(QColor("#8a93a5")))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "まだ地図がありません" + chr(10) + chr(10)
                + "⚠ 歩いた所から少しずつ開けます" + chr(10)
                + "（★見た所だけを出します。完全地図は出しません）")
        for x, y, loc in marks:
            rect = QRect(x - MARK_PX // 2, y - MARK_PX // 2, MARK_PX, MARK_PX)
            # ⚠⚠ 2026-09-12 依頼者「緑丸で邪魔されてわからない。透明の緑丸にすると良いかも。」（RX3-0190）
            #   ★塗りつぶすと、その升の絵（村・城）が**隠れます**。→ ★輪にして、中は薄く透かす
            painter.setBrush(QColor(0x8b, 0xd4, 0x50, MARK_FILL_ALPHA))
            painter.setPen(QPen(QColor("#8bd450"), MARK_RING_PX))
            painter.drawEllipse(rect)
            # ★当たり判定は少し広くする（⚠ 印ぴったりだと押しにくい）
            self._hits.append((rect.adjusted(-4, -4, 4, 4), loc))

        # ★現在地（⚠ 届いていなければ出さない）
        pos = self.vm.position()
        if pos is not None:
            from dq3.knowledge.seen_map import map_key

            kind, map_id, x, y = pos
            name = place_label(self.vm, kind, map_id)
            why = art_reason(self.vm, kind, map_id)
            if why:
                name = "%s　%s" % (name, why)
            text = self._status_text(name, kind, map_id, x, y)
            # ⚠⚠ 2026-09-07 依頼者「文字がマップ色につぶれて見えない」（RX3-0105）。
            #   ★地図の色は場所ごとに変わるので、⚠ 文字色だけでは**必ずどこかで潰れます**。
            #   → ★文字の下に**帯を敷き**ます（⚠ 透けさせない）。
            metrics = painter.fontMetrics()
            box = metrics.boundingRect(text)
            band = QRect(0, self.height() - box.height() - 8,
                         self.width(), box.height() + 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(24, 26, 32, 216))
            painter.drawRect(band)
            painter.setPen(QPen(QColor("#e6e9ef")))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(8, self.height() - 8, text)
        painter.end()

    def _status_text(self, name, kind, map_id, x, y) -> str:
        """下に出す 1 行（★場所・座標・見た升の数）。

        ⚠⚠ 地図の広さ（ROM の総升数）と割合は**出しません**（RX3-0206 / 指示書 §14）。
          ★「まだ部屋が残っている」こと自体がネタバレになる（⚠ 探索率は内部の検査用だけ）。
        """
        from dq3.knowledge.seen_map import map_key

        count = self.vm.seen.count(map_key(kind, map_id))
        return "%s (%d, %d) / 見た %d 升" % (name, x, y, count)

    def mousePressEvent(self, event) -> None:            # noqa: N802 (Qt の名前)
        where = event.position().toPoint()
        for rect, loc in self._hits:
            if rect.contains(where):
                if self._on_click is not None:
                    self._on_click(loc, self.mapToGlobal(where))
                return
        super().mousePressEvent(event)


class MapScroll(QScrollArea):
    """★地図をスクロールして見せる枠（RX3-0045 / 2026-09-01）。

    ## ⚠⚠ 「縮める」のをやめました

      依頼者 2026-09-01:

      > 世界地図一番小さいブロックで丁度いい感じだったので、そうしたい。
      > スクロールバー対応を DQ2 でやった。

    ```text
    1 升の px    ★地図の種別で固定（`map_scale`）
    収まらない   ⚠ 縮めずスクロールバー
    ```

    ## ⚠⚠ 点滅させない（★DQ2 が 2026-08-18 に踏んだ穴）

      ★中身の大きさは **枠を一切見ずに**決まります
      （`MapCanvas.content_size()`）。⚠ だから測るたびに変わりません。

    ## ★寄せ方（RX3-0206 / ダンジョン探索MAP v1 §5）

      ★追随中は毎歩、現在地を真ん中へ（⚠ 地図の端では寄せる = スクロールの範囲で止まる）。
      ⚠ 人がスクロールしたら追随を止め、「現在地」か地図・階が変わったら戻す。
      ★RX3-0255: 止めている間は歩いても寄せない / 開き直したら戻す / 世界地図も見た所ぜんぶをスクロールで見る。
    """

    def __init__(self, canvas, parent=None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        # ⚠⚠ **伸ばさない**（★中身の大きさは中身が決める）
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidget(canvas)
        #: ⚠ どの地図で寄せたか（★同じ地図では寄せ直さない）
        self._centred_for = None
        #: ⚠⚠ **まだ寄せられていない**（★枠の大きさが決まる前は効かない）
        self._want_centre = False
        #: ⚠ どの枠の大きさで寄せたか（★変わったら寄せ直す）
        self._centred_view = None
        #: ★★ 現在地に追随しているか（RX3-0206）。⚠ 人がスクロールしたら止め、「現在地」か地図が変わったら戻す
        self.following = True
        for bar in (self.horizontalScrollBar(), self.verticalScrollBar()):
            bar.actionTriggered.connect(self._by_hand)
        self.fit()

    def fit(self) -> bool:
        """★中身の大きさを当てはめる。⚠ 変わっていなければ何もしない。

        戻り値: ★大きさを変えたか。
        """
        before = self._view_anchor()
        want = self.canvas.content_size()
        if want is None:
            return False
        w, h = want
        if (self.canvas.width(), self.canvas.height()) == (w, h):
            self._keep_view(before)
            self._centre_if_new()
            return False
        self.canvas.setFixedSize(w, h)
        self._keep_view(before)
        self._centre_if_new()
        return True

    def _centre_if_new(self) -> None:
        """⚠ 地図が変わったときと、★現在地が枠の外へ出たときに寄せる。

        ## ⚠⚠ 「地図が変わったとき」だけでは足りませんでした（RX3-0107）

          ★依頼者「階段移動したときに MAP が追随しないので見失ってしまう」。
          ⚠ 洞窟は**階が変わっても同じ地図**です（★実測 / 2026-09-07）:

          ```text
          DQ3_J.fc2（階段前）  kind=5 map_no=45 58x40 local=(2,8)
          DQ3_J.fc3（階段後）  kind=5 map_no=45 58x40 local=(5,34)
          ⚠⚠ 番号も寸法も**変わらない**。★座標だけが飛ぶ
          ```

          → ★`(kind, map_id)` だけを見ていたので、**一度も寄せ直しません**でした。

        ⚠ 手の操作は奪いません（RX3-0255 / 2026-09-13 依頼者の小WI）。
          ★人がスクロールしている間は、歩いても寄せません
          （⚠ 以前は枠の外へ出たら寄せていた = 昔の所を見ていても次の 1 歩で引き戻していた）。
          ★ただし一度に `JUMP_CELLS` 升以上飛んだら（★階段・ワープ）追随に戻します（⚠ 見失わない / RX3-0107）。
        """
        at = getattr(self.canvas, "_at_now", None)
        if at is None:
            return
        key = (at[0], at[1])
        if key != self._centred_for:
            self._centred_for = key
            self.following = True          # ★地図・階が変わったら追随に戻す（RX3-0206）
            self._want_centre = True
        here = (at[2], at[3])
        was = getattr(self, "_hero_cell", None)
        if here != was:
            self._hero_cell = here
            # ★一度に遠くへ飛んだ（★階段・ワープ）→ 追随に戻す（RX3-0107 / ⚠ 見失わない）
            if was is not None and _jumped(was, here):
                self.following = True
            # ★★ 追随中は毎歩真ん中へ（RX3-0206 / 指示書 §5-1）。⚠ 人が動かしている間は寄せない（RX3-0255）
            if getattr(self, "following", True):
                self._want_centre = True
        if self._want_centre:
            self.centre_on_hero()

    def _view_anchor(self):
        """★いまの絵の左上がどの升か（★地図・1 升の px と組で / ⚠ 分からなければ None）。"""
        at = getattr(self.canvas, "_at_now", None)
        origin = getattr(self.canvas, "origin", None)
        if at is None or origin is None or not hasattr(self.canvas, "unit_now"):
            return None
        return (at[0], at[1]), origin, self.canvas.unit_now()

    def _keep_view(self, before) -> None:
        """★手で動かしている間に絵の左上が動いたら、見ている升を保つ（RX3-0255）。

        ★世界地図: 見た範囲が左・上へ広がった / 町・洞窟: 勇者のまわりの窓が動いた。
        ⚠ 追随中は寄せ直すので何もしない。⚠ 地図か 1 升の px が変わったら保たない。
        """
        if before is None or getattr(self, "following", True):
            return
        after = self._view_anchor()
        if after is None or after[0] != before[0] or after[2] != before[2] or after[1] == before[1]:
            return
        unit = after[2]
        dx = int(round((before[1][0] - after[1][0]) * unit))
        dy = int(round((before[1][1] - after[1][1]) * unit))
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + dy)

    def centre_on_hero(self) -> bool:
        """★現在地が真ん中に来るようスクロールする。

        ## ⚠⚠ 枠の大きさが決まる前は効きません

          ★作った直後の `viewport()` はまだ小さく、⚠ `setValue()` は
            **その時点の上限で頭打ち**になります。
          ⚠ 一度そこで「寄せた」ことにすると、あとで枠が広がっても
            **二度と寄りません**（★2026-09-01 の検査で捕まえた）。

          → ★効かせられたときだけ「寄せた」ことにします。

        戻り値: ★実際に寄せられたか。
        """
        at = self.canvas.hero_at()
        if at is None:
            return False
        view = self.viewport()
        if view.width() <= 1 or view.height() <= 1:
            return False                  # ⚠ まだ大きさが決まっていない
        x, y = at
        self.horizontalScrollBar().setValue(x - view.width() // 2)
        self.verticalScrollBar().setValue(y - view.height() // 2)
        self._want_centre = False
        self._centred_view = (view.width(), view.height())
        return True

    def _by_hand(self, _action=None) -> None:
        """★人がスクロールした → 追随を止める（RX3-0206）。⚠ こちらの `setValue` では呼ばれない。"""
        self.following = False

    def follow_again(self) -> bool:
        """★「現在地」: 追随に戻して、現在地を真ん中へ（RX3-0206）。"""
        self.following = True
        self._want_centre = True
        return self.centre_on_hero()

    def resizeEvent(self, event) -> None:            # noqa: N802 (Qt の名前)
        """⚠ 枠の大きさが変わったら寄せ直す。

        ## ⚠⚠ 作った直後に寄せても効きません

          ★`__init__` の時点の `viewport()` はまだ小さく、
          ⚠ `setValue()` は**その時点の上限で頭打ち**になります。
          ⚠⚠ そこで「寄せた」ことにすると、あとで枠が広がっても
            **二度と寄りません**（★2026-09-01 の検査で捕まえた）。

        ⚠ 手で動かしている間は、枠の大きさが変わっても寄せません（RX3-0255 / ★見ている所を奪わない）。
        """
        super().resizeEvent(event)
        view = self.viewport()
        if self._want_centre or (getattr(self, "following", True)
                                 and self._centred_view != (view.width(), view.height())):
            self.centre_on_hero()

    def showEvent(self, event) -> None:              # noqa: N802 (Qt の名前)
        """★開き直したら現在地へ戻り、追随する（RX3-0255 / 指示書 §1「地図を開いた際の現在地へのセンタリング」）。

        ⚠ 最小化から戻したとき（spontaneous）は、手で動かした所を残す。
        """
        super().showEvent(event)
        if not event.spontaneous():
            self.following = True
            self._want_centre = True
        if self._want_centre:
            self.centre_on_hero()


class Dq3MapWindow(QWidget):
    """MAP と勇者メモ（★別ウィンドウ）。"""

    def __init__(self, view_model, *, memo_limit: int = 3, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        # ★窓の名前は「中身」で（RX3-0306 / 依頼者「左：地図、勇者メモ」）
        self.setWindowTitle("地図、勇者メモ")
        self.setWindowFlag(Qt.WindowType.Window, True)
        # ★起動直後から画面にぴったり収める（依頼者 2026-08-29）
        # ⚠⚠ **Qt の論理座標**で置く（★物理を渡すと 150% の画面で 1.5 倍になる）
        from . import layout as layout_mod
        self.setGeometry(
            *layout_mod.default_sizes(layout_mod.qt_area()).map.as_tuple())
        # ⚠ フォーカスを奪わない（★奪うとゲームを操作できなくなる / DQ2 の知見）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ⚠ 見出しは付けない（★題名の帯に同じ字が出ている / 依頼者 2026-08-29）
        self.canvas = MapCanvas(view_model, on_click=self._clicked)
        # ⚠⚠ **縮めずスクロール**（RX3-0045 / 依頼者 2026-09-01）
        self.scroll = MapScroll(self.canvas)
        root.addWidget(self.scroll, 1)

        # ★MAP の下に勇者メモ（指示書 §7）
        self.memos = MemoPanel(view_model, limit=memo_limit)
        root.addWidget(self.memos)

        # ★いまの場所の名前を、人が付け直せる（RX3-0080 §16 案 B / ⚠ 大きな編集画面は作らない）
        from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.place_label = QLabel("")
        self.place_label.setStyleSheet("color:#8a93a5; font-size:11px;")
        row.addWidget(self.place_label, 1)
        self.rename_button = QPushButton("命名")
        self.rename_button.setToolTip("★いまの場所の名前を、手で付けます（⚠ 候補は出しません / RX3-0309）\n"
                                      "⚠ 仮名（自動で付けた名前）を、正式な名前へ変えられます（★あとで付け直せる）\n"
                                      "★同じ場所として扱われている map はまとめて変わります")
        self.rename_button.clicked.connect(self.rename_here)
        row.addWidget(self.rename_button)
        # ★★ 1 升の大きさと「現在地」（RX3-0206 / ダンジョン探索MAP v1 §5・§6）
        from . import map_scale

        self.size_box = QComboBox()
        self.size_box.addItems(list(map_scale.SIZE_LABELS))
        self.size_box.setToolTip("★地図の 1 升の大きさ（★洞窟・塔は「小」から / 町は「標準」から）\n"
                                 "⚠ 世界地図は変わりません")
        self.size_box.activated.connect(self._size_picked)
        row.addWidget(self.size_box)
        self.here_button = QPushButton("現在地")
        self.here_button.setToolTip("★いまの場所を真ん中に出して、また追随します\n"
                                    "⚠ 手でスクロールすると追随を止めます")
        self.here_button.clicked.connect(self.scroll.follow_again)
        row.addWidget(self.here_button)
        # ★★ ⚠⚠ 勇者会議のボタンは**この行に置きません**（RX3-0308 / 依頼者 2026-09-20）★★
        #
        #   > 勇者会議のボタンは、勇者メモの欄にしたい。MAP が少し横に伸びてしまった
        #
        #   ★この窓の既定の幅は **360 px**。⚠ この行に 4 つ目のボタンを足すと最小幅が
        #     **378 px** になり、Qt が窓を押し広げていました（★実測 2026-09-20）。
        #   → ★勇者会議は `MemoPanel` のボタンの行へ（`self.memos.council_button`）。
        root.addLayout(row)

        self._popup = None

    @property
    def council_button(self):
        """★勇者会議のボタン（⚠ 実体は勇者メモの欄 / RX3-0308）。"""
        return self.memos.council_button

    def open_council(self) -> None:
        """★勇者会議を開く（⚠ 実体は `MemoPanel.open_council` / RX3-0308）。"""
        self.memos.open_council()

    @property
    def _council(self):
        """★開いている勇者会議の窓（⚠ 持ち主は勇者メモの欄 / RX3-0308）。"""
        return self.memos._council

    def _clicked(self, location_id: str, at: QPoint) -> None:
        """★地点をクリックしたら、ポップアップを出す（指示書 §4.1 / §5）。"""
        view = self.vm.location_view(location_id)
        if self._popup is not None:
            self._popup.close()
        # ⚠ 詳細画面はまだ無い（指示書 §6: 未実装でよい）
        self._popup = show_location_popup(view, at, on_detail=None, parent=self)

    # --- ★場所の名前（RX3-0080）------------------------------------------

    def here_location(self):
        """★いま居る場所（⚠ 世界地図なら None）。

        ⚠⚠ 2026-09-07（RX3-0106）: `at[0] != 1` にしていたので、★洞窟（kind = 5）で
        **[名前] が灰色のまま**でした（⚠ ダンジョン名を人が入れられない）。
        → ★`is_local()` に合わせます（`RX3-0103` と同じ直し）。
        """
        from dq3.knowledge.seen_map import is_local

        at = self.vm.position()
        if at is None or at[1] is None or not is_local(at[0]):
            return None
        return self.vm.location_book.get_location(at[1])

    def rename_here(self) -> bool:
        """★いまの場所の名前を付け直す（⚠ `location_id` は変えない / 指示書 §12）。"""
        loc = self.here_location()
        if loc is None:
            self.place_label.setText("⚠ 町や城の中でだけ付け直せます")
            return False
        # ★★ 「命名」: 人が手で名前を入れる（⚠ 候補は出しません / RX3-0309）
        got = self._ask_name(loc)
        if not got:
            return False
        book = self.vm.location_book
        changed = book.rename(loc.location_id, got)
        book.save(force=True)
        self.refresh_place()
        return changed

    def _ask_name(self, loc):
        """★「命名」の窓。戻り値: 決めた名前（⚠ やめたら None）。

        ⚠⚠ 2026-09-20（RX3-0309）: 名前の**候補を出す機能を外しました**。
        ★いまの名前（仮名も）を初めの値にして、⚠ 人が手で入れるだけです。
        """
        from .name_dialog import NameDialog

        return NameDialog.ask(loc.location_id, loc.display_name or "", parent=self)

    def refresh_place(self) -> None:
        """★いまの場所の名前を 1 行で出す。"""
        loc = self.here_location()
        if loc is None:
            self.place_label.setText("世界地図")
            self.rename_button.setEnabled(False)
            if getattr(self, "size_box", None) is not None:
                self.size_box.setEnabled(False)       # ⚠ 世界地図は 8 px のまま（RX3-0206）
            return
        mark = "（仮）" if loc.name_source == "provisional" else ""
        # ★見つけた宝箱の一覧（RX3-0207）: ⚠ 中身は開けたものだけ
        self.place_label.setToolTip(self._chest_summary(loc))
        self.place_label.setText("%s%s" % (loc.name(detailed=True) or loc.location_id, mark))
        self.rename_button.setEnabled(True)
        if getattr(self, "size_box", None) is not None:
            self.size_box.setEnabled(True)
            self.size_box.setCurrentText(self.canvas.level_now())

    def _chest_summary(self, loc) -> str:
        """★この場所で見つけた宝箱（RX3-0207）。⚠ 中身は開けたものだけ / ⚠ 見つけていない数は言わない。"""
        rows = []
        book = getattr(self.vm, "chests", None)
        for map_id in (getattr(loc, "map_ids", None) or []):
            try:
                rows.extend(book.rows(map_id) if book is not None else [])
            except Exception:                              # noqa: BLE001
                pass
        if not rows:
            return ""
        opened = [r for r in rows if r.get("state") == "OPENED"]
        names = "・".join(str(r.get("item_name") or "？") for r in opened)
        return "宝箱: 見つけた %d / 開けた %d%s" % (len(rows), len(opened),
                                              ("（%s）" % names) if names else "")

    def _size_picked(self, index: int) -> None:
        """★1 升の大きさを選んだ（RX3-0206）。"""
        from . import map_scale

        if 0 <= index < len(map_scale.SIZE_LABELS):
            self.canvas.set_level(map_scale.SIZE_LABELS[index])
            self.scroll.fit()
            self.scroll.follow_again()
            self.canvas.update()

    def refresh(self) -> None:
        """★定期的に呼ぶ（⚠ 下地は作り直さない。印だけ動く）。"""
        self.memos.refresh()
        self.refresh_place()
        # ⚠ 地図が変われば大きさも変わる（★中で「変わったときだけ」動く）
        self.scroll.fit()
        self.canvas.update()
