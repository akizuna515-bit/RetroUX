"""地図の**描き方**だけ（2026-08-01 に `map_window.py` から分離 / §8.2）。

★★ **ここは DB も SQLite も知らない。** ★★
  渡されたマスの並びを絵にするだけ。指示書 §8.2 の通り。

  ⚠ 知ってしまうと、描き方を変えるたびに DB の話が付いてくる。
    逆に「この色でいいか」を試すのに、記録を用意しないと動かせなくなる。

---

## 描き方（2026-07-30 / 指示書 `input/MAP表示改善.md`）

**1マス=1画素の `QImage` を作り、整数倍で拡大する**（ミニマップ方式）。
以前は1マスずつ `fillRect` していたため「色付きセルの表」に見えていた。

| | 値 | 理由 |
| --- | --- | --- |
| 通常マップの倍率 | 4（枠に収まる範囲で） | 町・ダンジョンは小さい（最大 29×25） |
| ワールドマップの倍率 | 1 | **256×256** あるので等倍から |
| 補間 | **切る** | ぼかすとドットが溶ける |

★ワールドマップの大きさは **実測で 256×256**（`config.yaml` の
  `map.overworld_width` / `overworld_height`）。
  ⚠ 指示書は 128 を例示していたが、記録済みの座標は x が 128..255 に
  4,950 マスあり、**128 では収まらない**。1バイト座標なので上限は 256。
"""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

# 見た所の色。何度も見た所ほど濃い（★何度も通った＝主要な通路）
TRAIL_LIGHT = QColor(60, 92, 130)
TRAIL_HEAVY = QColor(120, 190, 255)
HERE = QColor(255, 210, 90)
FRAME = QColor(90, 90, 90)
BACKDROP = QColor(24, 24, 28)
# ★「まだ見ていないマス」。**透明**にする。
#   黒で塗ると「黒い地形を見た」と読めてしまう（0 と 不明 を混ぜない）。
UNSEEN = QColor(0, 0, 0, 0)

#: ★★ 枠の中の「まだ見ていない所」の下地（2026-08-01 / 依頼者の報告）★★
#:
#: ⚠⚠ 依頼者「ロンダルキアの洞窟だと、うまくマップが表示されてない」
#:
#:   実データで再現しました。ID $3E（5F）の 67 マスのうち
#:   **53 マスが `000`（真っ黒）**でした。洞窟の床が黒いためです。
#:   ⚠ 背景（`BACKDROP` = ほぼ黒）と見分けが付かず、
#:     **歩いたのに何も出ていないように見えて**いました。
#:
#: ★上の `UNSEEN` の注釈は「見ていない所を黒くするな」と警告していますが、
#:   **見た所が黒い**場合が抜けていました。裏返しの見落としです。
#:
#: ★★ 色は**嘘をつきません**。床は黒のまま塗り、代わりに
#:   「まだ見ていない所」を**はっきり違う色**にして区別します。
UNKNOWN_FLOOR = QColor(46, 46, 54)

#: ★★ 「見たけれど、まだ絵が無い」マス（2026-08-02 / 依頼者の報告）★★
#:
#: ⚠⚠ 依頼者「前のゴミが悪さしてる？」→ **そのとおりでした。**
#:   昔の記録は1マスの**中心1画素**を色にしていたため、洞窟の床
#:   （黒地に赤い点）で点に当たったマスが**真っ赤**になっていました。
#:   周りが本物の絵になると、その赤が「溶岩」のように見えます。
#:
#: ★見た事実は残しますが、**地形の色は主張しません**。
#:   ⚠ 「まだ見ていない」（`UNKNOWN_FLOOR`）とも違う色にして、
#:     3つ（未探索 / 見たが絵なし / 絵あり）が見分けられるようにします。
#: ★そこを歩き直せば、本物の絵に置き換わります。
SEEN_NO_ART = QColor(74, 78, 92)


def tile_color(packed):
    """1マスの色。読めなければ None。

    ★★ 2つの形を読みます ★★

    | 形 | 出どころ | いつから |
    | --- | --- | --- |
    | `"RGB"`（4ビット×3） | ⚠ Lua が**画面から**拾った色 | 2026-07-29 |
    | `"RRGGBB"`（8ビット×3） | ★**ROM の絵**の平均色 | 2026-08-11 |

    ★★ 依頼者の指摘（2026-07-29）: 「画面とMAPの色が違う」
      **ゲーム画面に出ていた色そのもの**で塗る。陸と海が区別できるようになる。

    ⚠⚠ 画面から拾う道には**黒塗り**の弱点がありました（暗転・フェードの
      一瞬を拾ったマスが黒く残る）。★世界地図は ROM の色（6文字）へ
      移しました（`core/bgmap/world_art.py`）。丸めないので 6 文字です。

    ⚠ 読めない値を**それらしい色に丸めない**。分からないなら None を返し、
      呼び出し側が「見たことは分かるが色は不明」として描く。
    """
    if not packed:
        return None
    try:
        if len(packed) == 3:
            r, g, b = (int(c, 16) * 17 for c in packed)
        elif len(packed) == 6:
            r, g, b = (int(packed[i:i + 2], 16) for i in (0, 2, 4))
        else:
            return None
    except ValueError:
        return None
    return QColor(r, g, b)


#: ★旧名。`map_window.py` を経由して呼ぶものが居るので残す
_tile_color = tile_color


class TrailView(QWidget):
    """見た範囲を**ピクセルマップ**として描く枠（2026-07-30 に作り直し）。

    ★★ 依頼者の指示書（`input/MAP表示改善.md`）★★

      > 現状は「訪問済みタイルを可変サイズの色付き四角で描く」実装になっている。
      > これを、**画面の縮小イメージに近い見え方**になるよう、
      > **タイルをピクセル的に表示するミニマップ方式**へ修正する。

    ## 何が変わったか

    | | 前 | 後 |
    | --- | --- | --- |
    | 描き方 | 1マスずつ `fillRect` | **1マス=1画素の `QImage` を作って拡大** |
    | 倍率 | 枠に合わせて可変（`min(w//cols, h//rows)`） | **整数倍だけ**（1.3倍のような半端な拡大をしない） |
    | 補間 | （なし） | **明示的に切る**（`FastTransformation`） |

    ★整数倍にこだわる理由: 半端な倍率だと1マスが 2px と 3px に割れて、
      **同じ地形が違う大きさに見える**。ドット絵の地図では致命的。

    ★★ **余白を埋めるより、ドット感を保つ** ★★（指示書 2章）
      枠に対して 1.7 倍がぴったりでも、**1倍**で描く。
    """

    #: 通常マップの既定の倍率
    #: ★2026-08-01 に 4 -> 8（依頼者の実機確認「縮尺が小さすぎる」）
    ZOOM_NORMAL = 8
    #: ワールドマップの既定の倍率（256×256 と大きいので控えめ）
    #: ★2026-08-01 に 1 -> 2。★2026-08-11 に 2 -> 4（依頼者「倍ぐらい大きく」）。
    #:   ⚠ 大きいぶん枠に収まらないが、★世界地図は**スクロール枠**に入れて
    #:     自分中心に見せる（`window.py`）。収まらなければスクロールバーが出る。
    ZOOM_OVERWORLD = 4
    #: 上限。★これ以上大きくしても情報は増えない
    ZOOM_MAX = 16
    #: 0 を指定されたときの意味 =「枠に収まる最大の整数倍」
    ZOOM_FIT = 0

    #: ★★ 拡大後の絵の**最低の大きさ**（px / 2026-08-01 / 課題 #63）★★
    #:
    #: ⚠⚠ ROM には **1×1 / 3×3 / 5×5** のマップがあります（宿屋・店・祠など、
    #:   建物の中の小部屋）。既定の倍率だと 8〜40px の点にしかならず、
    #:   560px の枠の真ん中で**現在地の印にほぼ覆われて**いました。
    #:   依頼者の報告「ダンジョンなどマップが切り替えの場合、うまく描けていない」。
    #:
    #: ★指示書の「余白を埋めるより、ドット感を保つ」は
    #:   **半端な倍率を使うな**という意味です（1.7倍がぴったりでも1倍で描く）。
    #:   整数倍のまま大きくするのは、その方針に沿っています。
    #:
    #: ⚠ 枠に収まる範囲でしか上げません（はみ出させない）。
    MIN_DRAWN_PIXELS = 240

    #: ★★ 倍率固定の**唯一の例外**（2026-08-09 / 依頼者の指示「小部屋はBでOK」）
    #:
    #: これ以下のマップだけ `MIN_DRAWN_PIXELS` まで拡大します。
    #: ⚠ 5 を超えると「固定だから広さを見比べられる」が崩れます。
    #:   ★1×1 の部屋には見比べる相手が居ないので、ここだけ外します。
    TINY_MAP_CELLS = 5
    #: 現在地の輪の半径（px）。★倍率につられない（2026-08-01 / 課題 #55）
    #: ⚠ つられると、等倍のワールドマップでまた見えなくなる
    MARKER_RADIUS = 7

    #: ★★ ゲーム画面に映っている範囲の半径（マス / 2026-08-09）★★
    #:
    #: 依頼者「現在位置は、画面表示領域を枠表示で（多少のずれは許容）」
    #:
    #: ⚠ **ぴったりではありません。** ゲーム画面は 16×15 マスで、スクロール量に
    #:   よって半マスずれます。★ここは「だいたいこの辺が見えている」を
    #:   示すもので、当てにして歩く枠ではありません。
    #: ★既定は `config.yaml` の `map.view_radius` と同じ 7（＝15×15）。
    VIEW_RADIUS = 7

    def __init__(self) -> None:
        super().__init__()
        self.tiles: list = []
        self.width_tiles: int | None = None
        self.height_tiles: int | None = None
        self.here: tuple[int, int] | None = None
        self.map_type: str | None = None
        # ★枠の外にあった記録の数。**0 でなければ画面に出す。**
        #   記録がずれている合図なので、黙って捨てない
        #   （Qt は範囲外の setPixelColor を勝手に無視するので、
        #    数えないと「無かったこと」になってしまう）。
        self.outside_count = 0
        # ★タイルの絵（2026-08-01 / 課題 #65）。無ければ色で描く
        self.art: dict = {}
        self.art_map_id: int | None = None
        #: `{(x, y): タイルID}`。★これがあると**推測せずに**絵を引ける
        self.tile_ids: dict = {}
        # ★倍率は設定から差し替えられる（`config.yaml` の `map.zoom` /
        #   `map.overworld_zoom`）。0 なら「枠に収まる最大の整数倍」。
        self.zoom_normal = self.ZOOM_NORMAL
        self.zoom_overworld = self.ZOOM_OVERWORLD
        #: ★ゲーム画面に映っている範囲の半径（マス / `config.yaml` の
        #: `map.view_radius`）。⚠ 現在地を**枠**で出すのに使う（2026-08-09）。
        self.view_radius = self.VIEW_RADIUS
        # ★★ 2026-08-09: 320 -> 192（4区画の左列が 362px しかないため）★★
        #   ⚠ 320 だと、窓の余白や一覧と合わせて 460px を切れませんでした。
        #   ★192 = 24マス × ×8。ローレシア城がちょうど収まる大きさです。
        #     これより小さくすると、街ひとつ入りません。
        self.setMinimumSize(192, 192)

    @property
    def is_overworld(self) -> bool:
        return self.map_type == "overworld"

    def set_art(self, art: dict, map_id: int | None,
                tile_ids: dict | None = None) -> None:
        """タイルの絵を渡す（2026-08-01 / 課題 #65）。

        ★★ 依頼者「俺的にはタイル拡大表示だと思っていたのだが」★★
          1マス1色をやめ、**実際の絵を拡大**して描く。

        ⚠ 絵が無いマス（まだ見ていない・読めなかった）は、
          これまでどおり色で塗る。**無いものを推測で描かない。**
        """
        self.art = art or {}
        self.art_map_id = map_id
        self.tile_ids = tile_ids or {}

    def set_data(self, tiles, width, height, here, map_type=None) -> None:
        self.tiles = list(tiles or [])
        self.width_tiles = width
        self.height_tiles = height
        self.here = here
        self.map_type = map_type
        self.update()

    # --- 部品（★テストしやすいように分けてある / 指示書 5章）-------------

    def bounds(self) -> tuple[int, int]:
        """描く枠の大きさ（マス）。

        ★★ **見た所と現在地は必ず入る**（2026-08-02 / 依頼者の報告）★★

          ⚠⚠ 依頼者「save3では表示されない（印）」。原因はここでした。
            ROM から取った大きさ（`map $3D` なら 15×17）より、
            実際の座標のほうが**大きい**のです（実測 29/33）。
            枠に入らない現在地は描かれず、印が消えていました。

          ★実測（遷移の記録は枠で切っていないので信用できる）:
              map $3D  ROM 15×17  ->  実際 29/33
              map $3E  ROM 17×19  ->  実際 32/37
              map $3F  ROM 19×23  ->  実際 33/42
            ⚠ おおむね**2倍**ですが、`$39` の高さだけ合いません。
              **ROM の正しい読み方は未解明**です（`docs/rom-analysis-notes.md`）。
              ★分からないので「×2」と決めつけません。
              代わりに**見えている事実に合わせて枠を広げます**。

          ⚠ 広げたことは黙りません。`beyond_rom` で画面に出します。
        """
        w = self.width_tiles or 0
        h = self.height_tiles or 0
        for x, y, _n, _c in self.tiles:
            w, h = max(w, x + 1), max(h, y + 1)
        if self.here is not None:
            w, h = max(w, self.here[0] + 1), max(h, self.here[1] + 1)
        return max(w, 1), max(h, 1)

    def rom_bounds(self) -> tuple[int, int] | None:
        """ROM が言っている大きさ。⚠ 分からなければ None。"""
        if self.width_tiles and self.height_tiles:
            return self.width_tiles, self.height_tiles
        return None

    def beyond_rom(self) -> tuple[int, int] | None:
        """ROM の値をはみ出しているぶん。★はみ出していなければ None。

        ⚠ **黙って広げない。** 画面に出して、
          「ROM の読み方がまだ分かっていない」と分かるようにする。
        """
        rom = self.rom_bounds()
        if rom is None:
            return None
        w, h = self.bounds()
        if w <= rom[0] and h <= rom[1]:
            return None
        return (max(w - rom[0], 0), max(h - rom[1], 0))

    def pick_zoom(self, cols: int, rows: int,
                  avail_w: int | None = None, avail_h: int | None = None) -> int:
        """整数倍率を決める。**枠に収まる最大の整数倍**まで。

        ★半端な倍率は使わない（指示書 2章）。収まらないときは 1 まで下げる。

        ★`avail_*` を渡せるようにしてあるのは**テストのため**。
          この widget には最低の大きさ（320×320）があるので、
          `resize()` では「収まらない場合」を作れない。
        """
        want = self.zoom_overworld if self.is_overworld else self.zoom_normal
        if cols <= 0 or rows <= 0:
            return 1
        w = self.width() if avail_w is None else avail_w
        h = self.height() if avail_h is None else avail_h
        fit = min(w // cols, h // rows)
        if want == self.ZOOM_FIT:
            return max(1, min(fit, self.ZOOM_MAX))

        # ★★ **指定された倍率は動かさない**（2026-08-09 / 依頼者の指示）★★
        #   ⚠ 依頼者「ダンジョン、街MAPは8倍固定で良い。固定のほうが分かりやすい」
        #     マップごとに倍率が変わると、部屋の広さを見比べられません。
        #   ★枠に収まらないときだけ下げます（はみ出させない）。
        zoom = max(1, min(want, fit, self.ZOOM_MAX))
        if self._is_tiny(cols, rows):
            # ★★ 小部屋だけは例外（2026-08-01 課題 #63 / 2026-08-09 に再確認）★★
            #   ⚠ ROM には 1×1 / 3×3 / 5×5 のマップ（宿屋・店・祠）があります。
            #     ×8 のままだと 8〜40px の点で、現在地の印にほぼ覆われます。
            #   ★見比べる相手が居ない大きさなので、固定から外しても
            #     「部屋の広さを見比べる」という狙いは損なわれません。
            need = max(-(-self.MIN_DRAWN_PIXELS // max(cols, rows)), 1)
            zoom = max(zoom, min(need, fit))
        return zoom

    def _is_tiny(self, cols: int, rows: int) -> bool:
        """★救済する小部屋か（2026-08-09）。⚠ ここだけ倍率固定の例外。"""
        return 0 < max(cols, rows) <= self.TINY_MAP_CELLS

    def build_image(self, cols: int, rows: int):
        """1マス=1画素の画像を作る。

        ★背景は透明にする。「見ていないマス」と「黒い地形」を混ぜないため
          （黒で塗ると、見ていない所を『黒い地形を見た』と誤読させる）。
        """
        from PySide6.QtGui import QImage

        image = QImage(max(cols, 1), max(rows, 1), QImage.Format.Format_ARGB32)
        image.fill(UNSEEN)

        heaviest = max((n for _x, _y, n, _c in self.tiles), default=1)
        outside = 0
        for x, y, visits, packed in self.tiles:
            if not (0 <= x < cols and 0 <= y < rows):
                # ⚠ 枠の外は描かない（大きさが違うと分かるように）。
                #   ★ただし**数える**。Qt は範囲外の書き込みを黙って無視するので、
                #     数えないと記録のずれに気づけない。
                outside += 1
                continue
            color = tile_color(packed)
            if color is None:
                # ★色が分からないマスは「見た」ことだけ出す（回数で濃さを変える）
                ratio = min(1.0, visits / max(heaviest, 1))
                color = QColor(
                    int(TRAIL_LIGHT.red()
                        + (TRAIL_HEAVY.red() - TRAIL_LIGHT.red()) * ratio),
                    int(TRAIL_LIGHT.green()
                        + (TRAIL_HEAVY.green() - TRAIL_LIGHT.green()) * ratio),
                    int(TRAIL_LIGHT.blue()
                        + (TRAIL_HEAVY.blue() - TRAIL_LIGHT.blue()) * ratio))
            image.setPixelColor(x, y, color)

        # ★現在地は**最後に**置く（見た色に上書きされないように）
        if self.here is not None:
            hx, hy = self.here
            if 0 <= hx < cols and 0 <= hy < rows:
                image.setPixelColor(hx, hy, HERE)
        self.outside_count = outside
        return image

    def target_rect(self, cols: int, rows: int, zoom: int) -> QRect:
        """拡大後の絵を置く位置（枠の中央）。"""
        w, h = cols * zoom, rows * zoom
        return QRect((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def here_center(self, rect: QRect, zoom: int):
        """いま立っているマスの**画面上の中心**。分からなければ None。

        ★★ 拡大後の座標を返す（2026-08-01 / 課題 #55）★★
          ⚠ 画像（1マス=1画素）へ印を描き込むと、倍率で潰れます。
            ワールドマップは等倍〜2倍なので、**1〜2px の点**にしかなりません。
            依頼者の指摘「自分がいまどこにいるかがわかりずらい」。
        """
        if self.here is None:
            return None
        hx, hy = self.here
        cols, rows = self.bounds()
        if not (0 <= hx < cols and 0 <= hy < rows):
            return None
        return (rect.left() + hx * zoom + zoom // 2,
                rect.top() + hy * zoom + zoom // 2)

    # --- 背景キャラクタ方式（2026-08-02 / マップ指示書 Phase 7）----------
    #
    # ★★ **現行表示を消さない**（指示書 §15.5）★★
    #   `renderer` を切り替えて見比べられるようにする。
    #     "character_metatile" … 新方式（メタタイル画像を並べる）
    #     "legacy_pixel"       … 現行（単色セル / タイルの絵）
    #   ⚠ 既定は新方式だが、**画像が足りなければ勝手に現行へ落ちる**。

    def set_renderer(self, name: str) -> None:
        """描き方を選ぶ。★知らない名前なら現行のままにする。"""
        from .metatile_renderer import CHARACTER, LEGACY

        self._renderer = name if name in (CHARACTER, LEGACY) else LEGACY
        self.update()

    def renderer_name(self) -> str:
        from .metatile_renderer import CHARACTER

        return getattr(self, "_renderer", CHARACTER)

    def set_metatiles(self, cells) -> None:
        """そのマップの `[(x, y, 鍵, 回数, 確度)]` を受け取る。

        ⚠ 空のときは新方式で描かない（**勝手に黒で埋めない**）。
        """
        self._metatiles = list(cells or [])
        self.update()

    def _metatile_renderer(self):
        renderer = getattr(self, "_mt_renderer", None)
        if renderer is None:
            from .metatile_renderer import MetatileRenderer

            renderer = MetatileRenderer()
            self._mt_renderer = renderer
        return renderer

    def metatile_ready(self) -> bool:
        """★メタタイルで描く**材料**がそろっているか（⚠ 枠の大きさは見ない）。

        ★2026-08-14 に `_metatile_zoom()` から切り出した（RX-0049）。
          ⚠ 「材料が無い」と「枠が小さい」は**別のこと**。
            ★前者は諦めるしかないが、後者は**スクロールで見せられる**。
        """
        from .metatile_renderer import CHARACTER

        if self.renderer_name() != CHARACTER:
            self._give_up_metatiles(f"描き方が {self.renderer_name()}")
            return False
        cells = getattr(self, "_metatiles", None)
        if not cells:
            self._give_up_metatiles("メタタイルが1件も渡っていない")
            return False
        if not self._metatile_renderer().can_draw(cells):
            self._give_up_metatiles(self._art_shortage(cells))
            return False
        return True

    def metatile_min_zoom(self) -> int | None:
        """★**枠に収まらなくても**絵で描ける最小の1マス画素数（RX-0049）。

        ⚠ 枠は見ない。★呼ぶ側がスクロール枠にする前提。

        依頼者の判断（2026-08-15 / RX-0049 の案 b）:

        > 49でスクロール枠。

        ★灯台 1F は 44×44 で、地図の枠が縦 352px を切ると収まらない。
          ⚠ これまでは**青い跡へ落ちて**いた。★これからはスクロールで見せる。
        """
        from .metatile_renderer import CELL_PIXELS

        if not self.metatile_ready():
            return None
        return min(CELL_PIXELS)

    def _metatile_zoom(self, cols: int, rows: int) -> int | None:
        """メタタイルで描くときの1マス画素数。⚠ 描けないなら None。

        ★★ **格子と画像の大きさを一致させる**（2026-08-02）★★
          ⚠ ここを合わせないと、1マスごとに端数が積もって枠からはみ出す。
            依頼者の画面（15×17 マス / 格子 15px / 画像 16px）で
            **右へ 15px・下へ 17px** はみ出しているのを実測した。

        ⚠⚠ 丸める元は `pick_zoom()` の結果**ではなく、枠に収まる上限**。
          ★一度これを間違え、15px から 8px へ**半分に縮めて**しまった。
            収まる上限は 17px なので、正しくは 16px（今より大きい）。

        ⚠ 一番小さい 8px にも足りないときは None（現行表示へ譲る）。
        """
        # ⚠⚠ **判断しているのはここ**（2026-08-14 / RX-0048）★★
        #   ★`paintEvent` は `metatile_zoom is not None and _draw_metatiles(...)`
        #     と**短絡**する。⚠ つまりここで None を返した時点で
        #     `_draw_metatiles()` は**呼ばれない**。
        #     理由を向こうに置いても、実機では1行も出ない。
        return self.metatile_zoom_for(cols, rows, self.width(), self.height())

    def metatile_zoom_for(self, cols: int, rows: int,
                          width: int, height: int) -> int | None:
        """★**与えられた大きさ**で、メタタイルの1マス画素数を決める。

        ⚠⚠ **`self.width()` で決めてはいけない場面がある**（2026-08-18）。

          `MapWindow._apply_map_view()` は「枠に収める」ときに
          widget を枠いっぱいへ伸ばす。★その widget の大きさを見て
          「入るか」を決めると、**決めるたびに前提が変わる**。

          実測（依頼者の画面 / `_draw` を10回）:

              1: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
              2: 枠内側 323x393 / widget 323x393 / 収める   / 倍率 None
              3: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
              ...

          ⚠ 依頼者の画面では**青と地形が点滅**して見えた。

        → ★呼ぶ側は**枠の内側**（`maximumViewportSize()`）を渡すこと。
        """
        from .metatile_renderer import fit_zoom

        if not self.metatile_ready():
            return None
        if cols <= 0 or rows <= 0:
            self._give_up_metatiles(f"マップの大きさが {cols}x{rows}")
            return None
        limit = min(width // cols, height // rows)
        # ★★ 設定した倍率で頭を打つ（2026-08-09 / 依頼者の指示）★★
        #   ⚠ ここは「枠に収まる最大」だけを見ていたので、マップの大きさ次第で
        #     ×16 になったり ×32 になったりしていました。★固定します。
        want = self.zoom_overworld if self.is_overworld else self.zoom_normal
        if want != self.ZOOM_FIT and not self._is_tiny(cols, rows):
            # ★小部屋だけは頭打ちにしない（`pick_zoom` と同じ例外）
            limit = min(limit, want)
        got = fit_zoom(limit)
        # ⚠⚠ **None のときは理由を残す**（2026-08-14 / RX-0048）★★
        #   ★大きいマップ（塔は 44×44）では 1マス 8px にも足りず、
        #     ここで None になって**現行表示（青い跡）へ落ちる**。
        #   ⚠ 手がかりが無いと「地図が壊れた」としか見えない。
        if got is None:
            self._give_up_metatiles(
                f"1マスが 8px に満たない（枠 {self.width()}x{self.height()} /"
                f" マップ {cols}x{rows} / 収まる上限 {limit}px）")
        else:
            self._giveup_now = None      # ★描けたので理由は無い
        return got

    def metatile_giveup(self) -> str | None:
        """★直近の `_metatile_zoom()` で ROM の絵をやめた理由。描けたなら None。

        ⚠⚠ **画面に出すためにある**（2026-08-14 / RX-0048）。
          ログにだけ書いても、遊んでいる人には届かない。
        """
        return getattr(self, "_giveup_now", None)

    def _art_shortage(self, cells) -> str:
        """絵がどれだけ足りないかを数える（★理由の文言）。"""
        store = self._metatile_renderer().store
        found = sum(1 for c in cells if store.image_path(c[2], "1x") is not None)
        return f"絵が半分に満たない（{found}/{len(cells)}）"

    def _give_up_metatiles(self, why: str) -> None:
        """★メタタイルで描かなかった理由を残す（2026-08-14 / RX-0048）。

        ⚠⚠ **青い跡だけになる道は4つあり、見た目では区別できない**。

            1. `renderer_name() != CHARACTER`
            2. メタタイルが1件も渡っていない
            3. 絵が半分に満たない
            4. 1マスが 8px に満たない

        ★2026-08-14 に「塔の地図がちゃんと出ない」と報告を受けたとき、
          ⚠ ログにも画面にも**手がかりが1つも無かった**。
          部品を1つずつ手で動かして調べても、実行時にどれを通ったかは
          **分からないままだった**。

        ⚠ 描画は毎回走るので、**変わったときだけ**出す（★毎回だと埋まる）。
        """
        self._giveup_now = why           # ★画面へ出すぶん（毎回上書き）
        if getattr(self, "_last_giveup", None) == why:
            return                       # ⚠ ログは変わったときだけ
        self._last_giveup = why
        from ...core.logging_setup import get_logger

        get_logger("map").debug("地図: 現行表示へ譲りました（%s）", why)

    def _draw_metatiles(self, painter, rect, zoom: int) -> bool:
        """メタタイル画像で描く。描けたら True。

        ⚠ 描けないときは **False を返して現行へ譲る**。
          まだらに欠けた地図は、単色より読みにくい。
        """
        from .metatile_renderer import CHARACTER, scale_for_zoom

        # ⚠ ここの3つは `_metatile_zoom()` と**同じ判定**（2026-08-14 / RX-0048）。
        #   ★実機は向こうで先に落ちるので、ここへは来ない。
        #     ⚠ ただし他から直接呼ばれても黙らないよう、理由は残す。
        def _give_up(why: str) -> bool:
            self._give_up_metatiles(why)
            return False

        if self.renderer_name() != CHARACTER:
            return _give_up(f"描き方が {self.renderer_name()}")
        cells = getattr(self, "_metatiles", None)
        if not cells:
            return _give_up("メタタイルが1件も渡っていない")
        renderer = self._metatile_renderer()
        if not renderer.can_draw(cells):
            return _give_up(self._art_shortage(cells))

        # ★★ 格子と画像の大きさは**必ず同じ**にする（2026-08-02）★★
        #   ⚠ 呼ぶ側（`paintEvent`）が `metatile_zoom()` で丸めた `zoom` を
        #     渡してくる約束。念のためここでも確かめる。
        scale = scale_for_zoom(zoom)
        # ⚠ ぼかさない（指示書 §10.2）
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # ★★ 絵の無いマスは**これまでどおり色で塗る**（2026-08-02）★★
        #   ⚠ 何も描かないと「見たのに未探索と同じ見た目」になる。
        #     依頼者の画面では 255 マス中 85 マスが穴になっていた。
        #   ★見たことは分かっているのだから、そう見せる。
        #     ⚠ 見ていないマスは相変わらず塗らない（指示書 §15.4）。
        self._fill_cells_without_art(painter, rect, zoom,
                                     renderer.keys(cells))
        drawn, missing = renderer.draw(
            painter, cells, (rect.left(), rect.top()), scale, zoom)
        # ⚠⚠ **描けなかったことを黙って捨てない**（2026-08-14 / RX-0048）★★
        #
        #   ★2026-08-14 に「塔の地図がちゃんと出ない」と報告を受けたが、
        #     ⚠ ログにも画面にも**手がかりが1つも残っていなかった**。
        #     部品を1つずつ手で動かして調べるしかなく、それでも
        #     実行時に何が起きたかは分からなかった。
        #
        #   ★1度だけ残す（⚠ 描画は毎回走るので、毎回出すと埋まる）。
        state = (self.__class__.__name__, scale, zoom, drawn, missing)
        if getattr(self, "_last_draw_state", None) != state:
            self._last_draw_state = state
            from ...core.logging_setup import get_logger

            get_logger("map").debug(
                "地図を描いた: 倍率 %s / 1マス %dpx / ★描けた %d / ⚠ 描けない %d",
                scale, zoom, drawn, missing)
        return drawn > 0

    def _fill_cells_without_art(self, painter, rect, zoom: int,
                                have_art: set) -> int:
        """絵の無い「見たマス」を色で塗る。塗った数を返す。

        ⚠ 色も分からないマスは**塗らない**（推測で埋めない）。
        """
        cols, rows = self.bounds()
        painted = 0
        for x, y, _visits, packed in self.tiles:
            if (x, y) in have_art or not (0 <= x < cols and 0 <= y < rows):
                continue
            # ⚠ 色が読めないマスは塗らない。★「見た」ことより
            #   「何色だったか分からない」ほうを優先して黙る（推測で埋めない）
            if tile_color(packed) is None:
                continue
            # ★★ **昔の色をそのまま出さない**（2026-08-02 / 依頼者の報告）★★
            #
            #   依頼者「前のゴミが悪さしてる？」→ そのとおりでした。
            #   ⚠ 昔の記録は**1マスの中心1画素**を色にしていました。
            #     洞窟の床は黒地に赤い点なので、点に当たったマスが
            #     **真っ赤**になっていました（実データで 3 マス）。
            #   ⚠ 周りが本物の絵になったせいで、その赤が
            #     「溶岩のような地形」に見えてしまいます。
            #
            #   ★見た事実は残しつつ、**地形の色は主張しない**一色にします。
            painter.fillRect(rect.left() + x * zoom, rect.top() + y * zoom,
                             zoom, zoom, SEEN_NO_ART)
            painted += 1
        return painted

    #: ★1マスがこれ未満なら絵をやめて色で描く（2026-08-01 / 課題 #65）
    #: ⚠ 8×8 の絵を 8px 未満に押し込むと、ただの潰れた点になる。
    ART_MIN_ZOOM = 8

    #: ★★ 絵が「まっさら」ばかりなら**使わない**（2026-08-01）★★
    #:
    #: ⚠⚠ タイルIDの読み取り位置がずれると、画面の黒帯（空白タイル）を
    #:   拾って**地図が一様に真っ黒**になる。実際そうなった:
    #:     ロンダルキア 6F の 391 マス中 **362 が `5F`（空白）**。
    #:   ★スクロールを考えずにネームテーブルの固定位置を読んでいたため。
    #:
    #: ⚠ 直るまで、**色で描いていた頃より悪くしない**ための歯止め。
    ART_MIN_VARIETY = 0.25

    def _can_draw_art(self, zoom: int) -> bool:
        """絵で描けるか。★材料が怪しければ静かに色へ戻る。"""
        if not self.art or self.art_map_id is None:
            return False
        if zoom < self.ART_MIN_ZOOM or not self.tile_ids:
            return False
        # ★★ 中身のある絵が、どれだけのマスに当たっているかを見る ★★
        good = 0
        for (x, y, _n, _c) in self.tiles:
            pixels = self.art.get(
                (self.art_map_id, str(self.tile_ids.get((x, y), "")).upper()))
            if pixels and len(set(pixels)) > 1:
                good += 1
        if not self.tiles:
            return False
        return good / len(self.tiles) >= self.ART_MIN_VARIETY

    def _draw_art(self, painter: QPainter, rect: QRect, zoom: int) -> None:
        """タイルの絵を敷き詰める（2026-08-01 / 課題 #65）。

        ★1マスを 8×8 の小片に割り、そのまま拡大して塗る。
        ⚠ **絵が無いマスは色で塗る**（見たことは分かっているので）。
          絵も色も無ければ何も塗らない＝下地のまま（まだ見ていない）。
        """
        from ..map import tile_art as art_mod

        side = art_mod.TILE_SIDE
        cell = max(zoom // side, 1)          # ★小片1つの大きさ（整数倍）
        cols, rows = self.bounds()
        outside = 0
        for x, y, visits, packed in self.tiles:
            if not (0 <= x < cols and 0 <= y < rows):
                outside += 1
                continue
            left = rect.left() + x * zoom
            top = rect.top() + y * zoom
            pixels = self._art_for(x, y, packed)
            if pixels is None:
                # ★絵が無い -> これまでどおり1色で塗る
                color = tile_color(packed) or self._trail_color(visits)
                painter.fillRect(left, top, zoom, zoom, color)
                continue
            for i, hexes in enumerate(pixels):
                px, py = i % side, i // side
                painter.fillRect(left + px * cell, top + py * cell,
                                 cell, cell,
                                 QColor(int(hexes[0:2], 16),
                                        int(hexes[2:4], 16),
                                        int(hexes[4:6], 16)))
        self.outside_count = outside

    def _art_for(self, x: int, y: int, packed) -> list[str] | None:
        """そのマスの絵。★無ければ None（色で描く）。

        ★★ **タイルIDで引く。推測しない。**（2026-08-01 / 課題 #65）★★

        ⚠⚠ 最初は「記録した色に平均が近い絵」を選ぶ形にした。
          洞窟の床が格子模様になり、**別のタイルの絵を当てて**いた。
          ★色は 1マス1色に潰れているので、絵の区別には足りない。
            `VisitedTile.tile`（ネームテーブルのタイルID）で引く。

        ⚠ 古い記録にはタイルIDが無い。そのときは None を返し、
          これまでどおり色で描く（**推測で絵を当てない**）。
        """
        if not self.art or self.art_map_id is None:
            return None
        tile = self.tile_ids.get((x, y))
        if not tile:
            return None
        return self.art.get((self.art_map_id, str(tile).upper()))

    def _art_average(self, pixels: list[str]):
        """絵の平均色。★何度も使うので覚えておく。"""
        self._avg_cache = getattr(self, "_avg_cache", {})
        key = id(pixels)
        got = self._avg_cache.get(key)
        if got is not None:
            return got
        r = g = b = 0
        try:
            for px in pixels:
                r += int(px[0:2], 16)
                g += int(px[2:4], 16)
                b += int(px[4:6], 16)
        except ValueError:
            return None
        n = len(pixels) or 1
        got = (r // n, g // n, b // n)
        self._avg_cache[key] = got
        return got

    def _trail_color(self, visits: int) -> QColor:
        """色が分からないマスの「見た」印（回数で濃さを変える）。"""
        heaviest = max((n for _x, _y, n, _c in self.tiles), default=1)
        ratio = min(1.0, visits / max(heaviest, 1))
        return QColor(
            int(TRAIL_LIGHT.red() + (TRAIL_HEAVY.red() - TRAIL_LIGHT.red()) * ratio),
            int(TRAIL_LIGHT.green() + (TRAIL_HEAVY.green() - TRAIL_LIGHT.green()) * ratio),
            int(TRAIL_LIGHT.blue() + (TRAIL_HEAVY.blue() - TRAIL_LIGHT.blue()) * ratio))

    def _draw_viewport(self, painter: QPainter, rect: QRect,
                       zoom: int) -> None:
        """★いまゲーム画面に映っている範囲を**枠**で出す（2026-08-09）。

        依頼者「現在位置は、画面表示領域を枠表示で（多少のずれは許容）」

        ⚠ **ぴったりではありません**（`VIEW_RADIUS` の注釈）。だから枠線だけに
          して、中は塗りません。★塗ると「ここは確かめた」に見えてしまいます。
        ⚠ マップの端では枠が地図からはみ出します。★それが実際の見え方なので、
          切り詰めません（画面には地図の外も映っています）。
        """
        if self.here is None:
            return
        hx, hy = self.here
        r = self.view_radius
        if r <= 0:
            return
        side = (r * 2 + 1) * zoom
        box = QRect(rect.left() + (hx - r) * zoom,
                    rect.top() + (hy - r) * zoom, side, side)
        # ★暗い線を下に敷いてから明るい線を重ねる（明るい地形でも見えるように）
        for color, width in ((QColor(0, 0, 0, 150), 3), (HERE, 1)):
            painter.setPen(QPen(color, width))
            painter.drawRect(box)

    def _draw_here_marker(self, painter: QPainter, rect: QRect,
                          zoom: int) -> None:
        """いま立っているマスを目立たせる（2026-08-01 / 課題 #55）。

        ★★ **十字線＋輪** ★★
          ⚠ 塗りつぶすと、その下の地形が見えなくなる。
            マウスポインタと同じで「指す」だけにする。

        ★輪の大きさは倍率に**つられない**。等倍のワールドマップでも
          同じ見た目で見つけられるようにする。
        """
        center = self.here_center(rect, zoom)
        if center is None:
            return
        cx, cy = center
        self._draw_viewport(painter, rect, zoom)
        # ★★ 2026-08-09: 世界地図は**枠だけ**（依頼者の指示）★★
        #   > ワールドマップでの現在位置アイコンは、単純な枠アイコンに変えたい
        #   ⚠ 256×256 を ×1〜2 で描くので、輪と十字線が地形を覆っていました。
        #   ★街やダンジョン（×8）では枠が広すぎて「どのマスか」が分からない
        #     ので、そちらは輪と十字線を残します。
        if self.is_overworld:
            return

        # ★外側に暗い線を1本引いてから明るい線を重ねる。
        #   ⚠ 明るい地形（砂漠・雪原）の上だと、黄色1色では見えなくなる。
        for color, width in ((QColor(0, 0, 0, 180), 4), (HERE, 2)):
            painter.setPen(QPen(color, width))
            painter.drawEllipse(cx - self.MARKER_RADIUS, cy - self.MARKER_RADIUS,
                                self.MARKER_RADIUS * 2, self.MARKER_RADIUS * 2)
            # 十字線（★輪の中は描かない。中に居るマスを隠さないため）
            gap, arm = self.MARKER_RADIUS + 2, self.MARKER_RADIUS + 7
            painter.drawLine(cx - arm, cy, cx - gap, cy)
            painter.drawLine(cx + gap, cy, cx + arm, cy)
            painter.drawLine(cx, cy - arm, cx, cy - gap)
            painter.drawLine(cx, cy + gap, cx, cy + arm)

    # --- 描く ---------------------------------------------------------

    def paintEvent(self, event) -> None:      # noqa: N802 (Qt の名前)
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKDROP)
        cols, rows = self.bounds()
        if cols <= 0 or rows <= 0:
            painter.end()
            return

        zoom = self.pick_zoom(cols, rows)
        # ★★ メタタイルで描くなら、格子を**画像の大きさへ丸める**（2026-08-02）
        #   ⚠⚠ 依頼者の画面で見つかった: 格子 15px に 16px の画像を並べ、
        #     1マスごとに 1px ずつずれて **右へ 15px・下へ 17px はみ出した**。
        #   ★丸めた結果は少し小さくなるが、**ぴったり合う**ほうが読みやすい。
        metatile_zoom = self._metatile_zoom(cols, rows)
        if metatile_zoom is not None:
            zoom = metatile_zoom
        rect = self.target_rect(cols, rows, zoom)

        # ★★ 枠の中の「まだ見ていない所」に下地を敷く（2026-08-01）★★
        #   ⚠ これが無いと、**黒い床を見たマス**が背景と見分けられない
        #     （ロンダルキアの洞窟で 67 マス中 53 マスが真っ黒だった）。
        #   ★地形の主張はしていない。「ここはマップの中だが、まだ見ていない」
        #     という一色を置くだけ。
        painter.fillRect(rect, UNKNOWN_FLOOR)

        # ★★ 背景キャラクタで描く（2026-08-02 / マップ指示書 Phase 7）★★
        #
        #   ⚠ **現行表示は消さない**（指示書 §15.5「新方式が安定するまで
        #     現行表示を削除しない」）。切り替えて見比べられるようにする。
        #   ★引けるメタタイルが半分に満たなければ、勝手に現行へ落ちる
        #     （まだらに欠けた地図は単色より読みにくい）。
        #   ⚠⚠ **`metatile_zoom` が None なら使わない**（2026-08-09 / 依頼者の報告）
        #     `_metatile_zoom()` の None は「メタタイルでは描けない」の意ですが、
        #     ここがそれを見ずに呼んでいました。★世界地図は 256×256 で倍率が
        #     ×1 になるため、**8px の画像を 1px 間隔で並べて**いました。
        #     1マスが隣を8マスぶん覆うので、山や町の位置がずれて見えます。
        #     ⚠ `_draw_metatiles()` は描けてしまうので True を返し、
        #       現行表示へ落ちる道も塞がっていました。
        if metatile_zoom is not None and self._draw_metatiles(
                painter, rect, zoom):
            painter.setPen(QPen(FRAME, 1))
            painter.drawRect(rect.adjusted(-1, -1, 0, 0))
            self._draw_here_marker(painter, rect, zoom)
            painter.end()
            return

        # ★★ 絵があるなら**絵で描く**（2026-08-01 / 課題 #65）★★
        #   依頼者「俺的にはタイル拡大表示だと思っていたのだが」
        #   ⚠ 1マスが 8px 未満だと絵が潰れるので、そのときは色で描く。
        if self._can_draw_art(zoom):
            self._draw_art(painter, rect, zoom)
            painter.setPen(QPen(FRAME, 1))
            painter.drawRect(rect.adjusted(-1, -1, 0, 0))
            self._draw_here_marker(painter, rect, zoom)
            painter.end()
            return

        # ★★ ぼかさない ★★ 既定では滑らかに拡大されてドットが溶ける。
        #   明示的に切る（指示書「アンチエイリアスや滑らか補間を使わない」）。
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.drawImage(rect, self.build_image(cols, rows))

        # マップの本当の大きさの枠（★中は塗らない。地形を知らないので）
        painter.setPen(QPen(FRAME, 1))
        painter.drawRect(rect.adjusted(-1, -1, 0, 0))

        # ★★ 現在地は**最後に**描く（2026-08-01 / 課題 #55）★★
        #   ⚠ 枠より先に描くと、端に居るとき枠線に隠れる。
        self._draw_here_marker(painter, rect, zoom)
        painter.end()
