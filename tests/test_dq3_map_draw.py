"""地図を描く（RX3-0023 / 2026-08-29）。

⚠⚠ ここが崩れると、★**行っていない所の地形が見えます**。
  依頼者の判断（指示書 §10 / DQ2 から踏襲）は「出すのは自分が見た所だけ」。
  ⚠ 崩れても**エラーは出ません**。だから機械で止めます。
"""

from __future__ import annotations

import os
import pathlib

import pytest

pytest.importorskip("PySide6")

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module", autouse=True)
def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _FakeTerrain:
    """★決まった形の地図（⚠ ROM を読まない）。"""

    def __init__(self, width=20, height=20, value=5):
        self.width = width
        self.height = height
        self._value = value

    def at(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return self._value


class _FakeSource:
    def __init__(self, terrain=None):
        self._terrain = terrain
        self.available = terrain is not None
        self.last_error = None
        self.calls = 0

    def get(self, kind, map_id=None):
        self.calls += 1
        return self._terrain


def _canvas(seen_cells, *, terrain=None, at=(1, 9, 10, 10)):
    """★見た升を与えて、絵を作る。"""
    from dq3.knowledge.seen_map import SeenMap, map_key
    from dq3.ui.map_window import MapCanvas

    seen = SeenMap(pathlib.Path("使わない"))
    key = map_key(at[0], at[1])
    for x, y in seen_cells:
        seen.mark(key, x, y)

    class VM:
        def __init__(self):
            #: ★動かせるようにする（⚠ 歩いたときの追随を見るため）
            self._at = at

        def position(self):
            return self._at

        def known_locations(self):
            return []

    VM.seen = seen
    canvas = MapCanvas(VM())
    canvas._terrain = _FakeSource(terrain if terrain is not None
                                  else _FakeTerrain())
    return canvas


# --- ⚠⚠ No-Spoiler --------------------------------------------------------

def test_見ていない升は塗らない():
    """⚠⚠ **これが今回いちばん大事な検査**。

    ★見た升だけに色を置く。⚠ 「先に全部描いてから覆い隠す」ではない
    （★覆いが外れた瞬間に全部見えてしまうため）。
    """
    from dq3.ui.map_window import UNSEEN

    canvas = _canvas([(10, 10), (11, 10)])
    image, _at = canvas._image_now()
    assert image is not None

    ox, oy = canvas.origin
    seen_rgb = image.pixel(10 - ox, 10 - oy)
    unseen_rgb = image.pixel(15 - ox, 15 - oy)
    assert seen_rgb != UNSEEN.rgb(), "⚠ 見た升が塗られていない"
    assert unseen_rgb == UNSEEN.rgb(), (
        "⚠⚠ **見ていない升に地形の色が入っている**")


def test_地図の外は地形にしない():
    """⚠ 記録に地図の外が混ざっても、★地形を出さない。"""
    from dq3.ui.map_window import UNSEEN

    canvas = _canvas([(10, 10), (100, 100)],
                     terrain=_FakeTerrain(width=20, height=20))
    image, _at = canvas._image_now()
    ox, oy = canvas.origin
    # ★(100,100) は地図の外なので、⚠ 色が入らない
    px, py = 100 - ox, 100 - oy
    if 0 <= px < image.width() and 0 <= py < image.height():
        assert image.pixel(px, py) == UNSEEN.rgb()


def test_全部見た所だけで絵ができている():
    """★塗られている升の数 = 見た升のうち地図の中にあるものの数。

    ⚠ ここが増えていたら、★どこかで「見ていない所」を塗っている。
    """
    from dq3.ui.map_window import UNSEEN

    cells = [(x, y) for y in range(5, 9) for x in range(5, 9)]
    canvas = _canvas(cells)
    image, _at = canvas._image_now()

    painted = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixel(x, y) != UNSEEN.rgb():
                painted += 1
    assert painted == len(cells), (
        "⚠⚠ 塗った升が %d（★見たのは %d 升）" % (painted, len(cells)))


# --- ⚠ 重くしない -----------------------------------------------------------

def test_見た升が増えないうちは絵を作り直さない():
    """⚠⚠ 世界地図は 256x256 = 65,536 升。

    ★1 秒に 2 回作り直すと画面が固まる（DQ2 で 137.8 ms の実績）。
    """
    canvas = _canvas([(10, 10)])
    canvas._image_now()
    before = canvas._terrain.calls

    canvas._image_now()
    canvas._image_now()

    assert canvas._terrain.calls == before, "⚠⚠ 毎回作り直している"


def test_見た升が増えたら作り直す():
    from dq3.knowledge.seen_map import map_key

    canvas = _canvas([(10, 10)])
    canvas._image_now()
    before = canvas._terrain.calls

    canvas.vm.seen.mark(map_key(1, 9), 11, 10)
    canvas._image_now()

    assert canvas._terrain.calls > before, "⚠ 増えたのに古い絵のまま"


# --- ⚠ ROM が無くても落ちない ----------------------------------------------

def test_ROMが無くても落ちない():
    """★`work/rom/DQ3_J.nes` は Git の外（⚠ 利用者が置くもの）。"""
    canvas = _canvas([(10, 10)], terrain=None)
    canvas._terrain = _FakeSource(None)

    image, _at = canvas._image_now()
    assert image is None
    # ⚠ 描いても落ちない
    canvas.resize(200, 160)
    canvas.grab()


def test_居場所が届いていなければ描かない():
    from dq3.knowledge.seen_map import SeenMap
    from dq3.ui.map_window import MapCanvas

    class VM:
        seen = SeenMap(pathlib.Path("使わない"))

        def position(self):
            return None

        def known_locations(self):
            return []

    canvas = MapCanvas(VM())
    canvas._terrain = _FakeSource(_FakeTerrain())
    image, at = canvas._image_now()
    assert image is None and at is None


# --- ★切り出し -------------------------------------------------------------

def test_見た所のまわりだけ切り出す():
    """⚠ 世界地図をまるごと出すと、★序盤は画面のほとんどが黒。"""
    from dq3.ui.map_window import MIN_VIEW

    canvas = _canvas([(100, 100)], terrain=_FakeTerrain(256, 256))
    image, _at = canvas._image_now()

    assert image.width() <= MIN_VIEW + 4, (
        "⚠ 切り出せていない（%d 升）" % image.width())
    assert image.width() >= MIN_VIEW - 4, (
        "⚠⚠ 切り詰めすぎ（★歩くたびに絵が飛ぶ）")


def test_切り出しても地図からはみ出さない():
    """⚠ 端に居ると、★切り出しが地図の外へ出る。"""
    canvas = _canvas([(0, 0)], terrain=_FakeTerrain(20, 20))
    image, _at = canvas._image_now()

    assert canvas.origin == (0, 0)
    assert image.width() <= 20 and image.height() <= 20


# --- ★色 -------------------------------------------------------------------

def test_色は1か所で決める():
    """⚠ 2 か所で作ると、★同じ地形が違う色に見える。"""
    src = (ROOT / "dq3" / "ui" / "map_window.py").read_text(encoding="utf-8")
    assert "from . import map_palette" in src
    assert "logical_palette" not in src, (
        "⚠ 昔の仮色に戻っている（★読みにくかったので実測に替えた）")


def test_実測した色を使う():
    """★世界地図と地図 9 は、依頼者の画面から採った色を使う。"""
    from dq3.ui.map_palette import (KIND_LOCAL, KIND_WORLD, LOCAL9_MEASURED,
                                    WORLD_MEASURED, palette)

    assert 0 in WORLD_MEASURED and 2 in WORLD_MEASURED
    assert 29 in LOCAL9_MEASURED
    world = palette(KIND_WORLD)
    # ⚠ 海（0）と草原（2）が同じ色に見えない
    assert world[0] != world[2]
    local = palette(KIND_LOCAL, 9)
    assert local[24] != local[29], "⚠ 道と草が同じ色"


def test_実測していない番号にも色がある():
    """⚠ 色が無いと、★その升だけ「見ていない」ように見える。"""
    from dq3.ui.map_palette import palette

    got = palette(0)
    for tile in range(32):
        assert tile in got, "⚠ 地形 %d の色が無い" % tile
        assert max(got[tile]) >= 30, "⚠⚠ 地形 %d が暗すぎて見えない" % tile


def test_ローカルの色はtilesetで決まる():
    """⚠⚠ **同じ番号でも tileset が違えば別の地形**。

    ★実測したのは地図 9 だけだが、tileset 05 は 9 件ある
    （1 / 2 / 9 / 12 / 17 / 22 / 32 / 70 / 85）。
    ⚠ 地図番号で分けると、★その 8 件が機械的な色のままになる。
    """
    from dq3.ui.map_palette import KIND_LOCAL, palette

    nine = palette(KIND_LOCAL, 9, 0x05)
    same = palette(KIND_LOCAL, 1, 0x05)
    other = palette(KIND_LOCAL, 3, 0x02)

    assert nine == same, "⚠⚠ 同じ tileset なのに色が違う"
    assert nine != other, "⚠ tileset が違うのに同じ色"


def test_tilesetが分からなければ機械的な色():
    """⚠ 分からないのに、★実測の色を当てない（別の地形かもしれない）。"""
    from dq3.ui.map_palette import KIND_LOCAL, palette

    known = palette(KIND_LOCAL, 1, 0x05)
    unknown = palette(KIND_LOCAL, 1, None)
    assert known != unknown, "⚠⚠ 分からないのに実測の色を当てている"


def test_地形はtilesetを持っている():
    """⚠ 持っていないと、★色を選べない。"""
    from dq3.knowledge.terrain import TerrainSource

    src = TerrainSource()
    if not src.available:
        pytest.skip("⚠ ROM が無い環境")
    got = src.get(1, 9)
    assert got is not None and got.tileset == 0x05
    world = src.get(0)
    assert world is not None and world.tileset is None, (
        "⚠ 世界地図に tileset は無い")


def test_描くときにtilesetを渡している():
    """⚠ 渡し忘れると、★9 件ぜんぶが機械的な色になる。"""
    src = (ROOT / "dq3" / "ui" / "map_window.py").read_text(encoding="utf-8")
    assert 'getattr(got, "tileset", None)' in src, (
        "⚠⚠ tileset を渡していない")


# --- ★どこまで開けたか -----------------------------------------------------

def test_見た数は出すが割合も地図の広さも出さない():
    """⚠⚠ 2026-09-12 依頼者の指示書「DQ3 ダンジョン探索MAP v1」§14（RX3-0206）。

    ★ROM の地図を分母にすると「まだ部屋が残っている」こと自体がネタバレになる。
    ⚠ 以前（2026-09-10 まで）は「25.0% / 400 升」と出していた。
    """
    canvas = _canvas([(x, y) for y in range(10) for x in range(10)],
                     terrain=_FakeTerrain(20, 20))
    text = canvas._status_text("地図 9", 1, 9, 10, 10)

    assert "100 升" in text
    assert "%" not in text, "⚠⚠ 割合を出している（★探索率はネタバレ）: %r" % text
    assert "400" not in text, "⚠⚠ ROM の地図の広さを出している: %r" % text


def test_広さが分からなければ割合を出さない():
    """⚠⚠ 分からないのに「何%」と出すと、★嘘の進み具合になる。"""
    canvas = _canvas([(10, 10)], terrain=None)
    canvas._terrain = _FakeSource(None)
    text = canvas._status_text("世界地図", 0, None, 10, 10)

    assert "%" not in text, "⚠⚠ 広さを知らないのに割合を出した: %r" % text


# --- ★★ いま居るところに追随する（依頼者 2026-08-30）------------------------

def test_主人公が真ん中に来る():
    """依頼者 2026-08-30:「DQ2 みたく、まずは自分の位置に追随するようにしたい」。

    ★RX3-0255（2026-09-13）: 世界地図は追随中も見た所ぜんぶを絵にする（★`test_dq3_world_scroll.py`）。
      → ★勇者のまわりの窓は町・洞窟のしくみ（⚠ ここは町の地図で見る）。
    """
    from dq3.ui.map_window import FOLLOW_VIEW

    canvas = _canvas([(100, 100)], terrain=_FakeTerrain(256, 256),
                     at=(1, 9, 100, 100))
    image, _at = canvas._image_now()
    ox, oy = canvas.origin

    assert image.width() == FOLLOW_VIEW and image.height() == FOLLOW_VIEW
    assert 100 - ox == FOLLOW_VIEW // 2, "⚠ 横が真ん中でない"
    assert 100 - oy == FOLLOW_VIEW // 2, "⚠ 縦が真ん中でない"


def test_歩くと窓がついてくる():
    # ★町の地図で見る（★RX3-0255: 世界地図は窓ではなく見た所ぜんぶ）
    canvas = _canvas([(100, 100)], terrain=_FakeTerrain(256, 256),
                     at=(1, 9, 100, 100))
    canvas._image_now()
    before = canvas.origin

    canvas.vm._at = (1, 9, 120, 100)
    canvas._image_now()

    assert canvas.origin[0] == before[0] + 20, "⚠⚠ ついてきていない"


def test_離れた2か所を歩いても割れない():
    """⚠⚠ **依頼者が実機で見た形**（2026-08-30）。

    ★見た所ぜんぶを**窓へ縮めて**出すと、離れた 2 か所が**浮いて 2 つに割れて**見える。

    ★RX3-0255（2026-09-13 依頼者の小WI）: 世界地図は見た所ぜんぶを絵にする（★スクロールで昔の所を見返す）。
      ⚠ ただし縮めない（1 升 8px）→ ★画面に映るのは勇者のまわりだけ（⚠ 遠くの記録は画面の外）。
    """
    from PySide6.QtWidgets import QApplication

    from dq3.ui.map_window import MapScroll

    far = [(10, 10), (11, 10), (200, 200), (201, 200)]
    canvas = _canvas(far, terrain=_FakeTerrain(256, 256),
                     at=(0, None, 200, 200))
    scroll = MapScroll(canvas)
    scroll.resize(400, 400)
    scroll.show()
    QApplication.processEvents()
    scroll.fit()

    assert canvas.unit_now() == 8, "⚠⚠ 縮めている（★割れて見える元）: 1 升 %s px" % canvas.unit_now()
    view = scroll.viewport()
    left = canvas.origin[0] + scroll.horizontalScrollBar().value() // 8
    top = canvas.origin[1] + scroll.verticalScrollBar().value() // 8
    right, bottom = left + view.width() // 8, top + view.height() // 8
    assert left <= 200 <= right and top <= 200 <= bottom, "⚠ 勇者が画面に映っていない"
    assert not (left <= 10 <= right and top <= 10 <= bottom), "⚠⚠ 遠くの記録まで画面に入っている（★縮めた）"
    scroll.close()


def test_端では窓が地図からはみ出さない():
    """⚠ 端に寄っても、★窓の大きさは保つ（地図の中へ寄せる）。"""
    from dq3.ui.map_window import FOLLOW_VIEW

    canvas = _canvas([(0, 0)], terrain=_FakeTerrain(256, 256),
                     at=(0, None, 0, 0))
    image, _at = canvas._image_now()

    assert canvas.origin == (0, 0)
    assert image.width() == FOLLOW_VIEW


def test_小さい地図はぜんぶ出す():
    """⚠ 26x26 の街を 48 升の窓で切ると、★かえって見づらい。"""
    canvas = _canvas([(10, 10)], terrain=_FakeTerrain(26, 26),
                     at=(1, 9, 10, 10))
    image, _at = canvas._image_now()

    assert canvas.origin == (0, 0)
    assert image.width() == 26 and image.height() == 26
