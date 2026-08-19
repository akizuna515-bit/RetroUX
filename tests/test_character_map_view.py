"""キャラクタ方式の地図表示（2026-08-02 / マップ指示書 §18.6）。

★★ 守りたい契約 ★★

  1. 新レンダラーで描ける
  2. ⚠ **現行表示へ切り替えられる**（指示書 §15.5「削除しない」）
  3. 0.5 / 1 / 2 / 4 倍を選べる。⚠ 任意の小数倍率は作らない
  4. 自動倍率は**定義済みの中から**選ぶ
  5. ⚠ 現在地マーカーは地形画像と**別レイヤー**（焼き込まない）
  6. ⚠⚠ **未探索を「黒い地形」として描かない**（指示書 §15.4）
  7. 画像が足りなければ**勝手に現行へ落ちる**
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtGui import QImage, QPainter          # noqa: E402
from PySide6.QtWidgets import QApplication          # noqa: E402

from retroux.core.bgmap.catalog import (            # noqa: E402
    AssetStore, auto_scale,
)
from retroux.ui.map.metatile_renderer import (      # noqa: E402
    CHARACTER, LEGACY, MetatileRenderer, cell_pixels_for, scale_for_zoom,
)


@pytest.fixture(scope="module")
def qapp():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        yield QApplication([])
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")


def _make_store(tmp_path, keys=("k1", "k2")) -> AssetStore:
    """★本物の PNG を書いて辞書を作る（偽物で済ませない）。"""
    from retroux.core.bgmap import Character, Metatile

    store = AssetStore(tmp_path)
    store.prepare()

    class _Pal:
        def rgb(self, index):
            return (index, 0, 0)

    for i, key in enumerate(keys):
        ch = Character(
            key=f"c{i}:00:AA", tile_id=0, chr_hash=f"h{i}",
            palette_signature="AA",
            pattern=tuple(tuple([1] * 8) for _ in range(8)),
            colors=(0x0F, 0x30, 0x16, 0x06))
        mt = Metatile(key=key, top_left=ch, top_right=ch,
                      bottom_left=ch, bottom_right=ch, map_id=1, x=0, y=0)
        store.put_metatile(mt, _Pal())
    return store


# --- 1. 描ける ----------------------------------------------------------

def test_メタタイルを並べて描ける(qapp, tmp_path):
    store = _make_store(tmp_path)
    renderer = MetatileRenderer(store)
    cells = [(0, 0, "k1", 3, "confirmed"), (1, 0, "k2", 3, "confirmed")]
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    drawn, missing = renderer.draw(painter, cells, (0, 0), "1x", 16)
    painter.end()
    assert drawn == 2
    assert missing == 0


def test_画像が無いマスは飛ばす(qapp, tmp_path):
    """⚠ **勝手に黒で埋めない**（指示書 §15.4）。"""
    store = _make_store(tmp_path, keys=("k1",))
    renderer = MetatileRenderer(store)
    cells = [(0, 0, "k1", 3, "confirmed"), (1, 0, "ない", 1, "provisional")]
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    drawn, missing = renderer.draw(painter, cells, (0, 0), "1x", 16)
    painter.end()
    assert drawn == 1
    assert missing == 1


def test_無い画像はNoneを返す(qapp, tmp_path):
    store = _make_store(tmp_path)
    renderer = MetatileRenderer(store)
    assert renderer.pixmap_for("ない鍵", "1x") is None
    assert renderer.pixmap_for("k1", "1x") is not None


def test_2回目はキャッシュから返す(qapp, tmp_path):
    """★毎回ディスクを読まない。"""
    store = _make_store(tmp_path)
    renderer = MetatileRenderer(store)
    first = renderer.pixmap_for("k1", "1x")
    second = renderer.pixmap_for("k1", "1x")
    assert first is second


def test_無いことも覚える(qapp, tmp_path):
    """⚠ 無い鍵を何度も探しに行かない。"""
    store = _make_store(tmp_path)
    renderer = MetatileRenderer(store)
    assert renderer.pixmap_for("ない", "1x") is None
    assert ("ない", "1x") in renderer._cache


# --- 2. 足りなければ現行へ譲る ------------------------------------------

def test_半分も引けなければ描かない(qapp, tmp_path):
    """⚠ まだらに欠けた地図は、単色より読みにくい。"""
    store = _make_store(tmp_path, keys=("k1",))
    renderer = MetatileRenderer(store)
    ok = [(0, 0, "k1", 3, "confirmed")]
    bad = [(i, 0, f"ない{i}", 1, "provisional") for i in range(5)]
    assert renderer.can_draw(ok) is True
    assert renderer.can_draw(ok + bad) is False
    assert renderer.can_draw([]) is False


# --- 3. 倍率（指示書 §10.4）--------------------------------------------

@pytest.mark.parametrize("zoom_px,want", [
    (8, "half"), (16, "1x"), (32, "2x"), (64, "4x"),
])
def test_1マスの画素数から倍率を選ぶ(zoom_px, want):
    assert scale_for_zoom(zoom_px) == want


def test_中途半端な倍率でも定義済みから選ぶ():
    """⚠ 任意の小数倍率は作らない。"""
    assert scale_for_zoom(20) in ("1x", "2x")
    assert scale_for_zoom(1000) == "4x"


@pytest.mark.parametrize("scale,px", [
    ("half", 8), ("1x", 16), ("2x", 32), ("4x", 64),
])
def test_倍率ごとの1マスの画素数(scale, px):
    assert cell_pixels_for(scale) == px


def test_自動倍率は収まる最大():
    assert auto_scale(10, 10, 700, 700) == "4x"
    assert auto_scale(100, 100, 100, 100) == "half"


# --- 4. 切り替え（指示書 §15.5）-----------------------------------------

@pytest.fixture()
def canvas(qapp):
    from retroux.ui.map.canvas import TrailView

    view = TrailView()
    yield view
    view.deleteLater()


def test_現行表示へ切り替えられる(canvas):
    """⚠⚠ **新方式が安定するまで現行を消さない**（指示書 §15.5）。"""
    canvas.set_renderer(LEGACY)
    assert canvas.renderer_name() == LEGACY
    canvas.set_renderer(CHARACTER)
    assert canvas.renderer_name() == CHARACTER


def test_知らない名前なら現行にする(canvas):
    canvas.set_renderer("でたらめ")
    assert canvas.renderer_name() == LEGACY


def test_メタタイルが無ければ新方式で描かない(canvas):
    """⚠ 空のまま新方式にすると、真っ黒な地図になってしまう。"""
    canvas.set_renderer(CHARACTER)
    canvas.set_metatiles([])
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    assert canvas._draw_metatiles(painter, image.rect(), 16) is False
    painter.end()


def test_現行のときは新方式で描かない(canvas, tmp_path):
    canvas.set_renderer(LEGACY)
    canvas.set_metatiles([(0, 0, "k1", 3, "confirmed")])
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    assert canvas._draw_metatiles(painter, image.rect(), 16) is False
    painter.end()


# --- 5. 現在地は別レイヤー（指示書 §15.3）-------------------------------

def test_現在地マーカーは地形と別に描く(canvas):
    """⚠ 主人公の絵を地図へ**焼き込まない**。

    ★`_draw_here_marker` が地形の**あと**に呼ばれること。
    """
    import inspect

    src = inspect.getsource(canvas.paintEvent)
    # ★新方式でも現在地マーカーを呼んでいる
    assert src.count("_draw_here_marker") >= 2
    # ⚠ 地形を描く前に呼んでいない（順番が逆だと隠れる）
    assert src.index("_draw_metatiles") < src.index("_draw_here_marker")


def test_追従は今までどおり(canvas):
    """★既存の follow を壊していない（指示書 §19）。"""
    assert hasattr(canvas, "here_center")
    assert hasattr(canvas, "set_data")


# --- 6. 配線（★実際に通す）---------------------------------------------

def test_presenterがメタタイルを運ぶ():
    """⚠ 「作った」だけでは画面に届かない。★実際に通す。"""
    from retroux.ui.map.presenter import MapPresenter

    class _VM:
        map_meta = {}

        def map_size(self, _map_id):
            return (10, 10)

        def location_of_map(self, _map_id):
            return None

        def visited_tiles(self, _a, _b):
            return []

        def map_type(self, _a):
            return "dungeon"

        def map_label(self, _a, _b=0):
            return "テスト"

        def visited_tile_ids(self, _a, _b):
            return {}

        def visited_metatiles(self, _a, _b):
            return [(1, 2, "keyA", 3, "confirmed")]

    detail = MapPresenter(_VM()).detail(0x3F, 0x8000)
    assert detail.metatiles == [(1, 2, "keyA", 3, "confirmed")]


def test_古いViewModelでも落ちない():
    """⚠ `visited_metatiles` を持たない ViewModel でも動くこと。"""
    from retroux.ui.map.presenter import MapPresenter

    class _Old:
        map_meta = {}

        def map_size(self, _a):
            return (10, 10)

        def location_of_map(self, _a):
            return None

        def visited_tiles(self, _a, _b):
            return []

        def map_type(self, _a):
            return "dungeon"

        def map_label(self, _a, _b=0):
            return "古い"

    detail = MapPresenter(_Old()).detail(0x3F, 0x8000)
    assert detail.metatiles == []


def test_ViewModelがDBの失敗を飲み込む(tmp_path):
    """⚠ 古い DB には列が無い。★空を返して止まらない。"""
    from retroux.ui.view_model import ViewModel

    class _BadDB:
        def visited_metatiles(self, *_a):
            raise RuntimeError("そんな列は無い")

    vm = ViewModel.__new__(ViewModel)
    vm.db = _BadDB()
    vm.rom_hash = "HASH"
    assert vm.visited_metatiles(1, 2) == []


# --- 7. 設定 -------------------------------------------------------------

def test_設定にLuaの予約語を使わない():
    """⚠⚠ 2026-08-02 に実際に踏んだ（テスト14件が赤くなった）。

    指示書 §16 の例は `local:` だが、そのまま書くと生成される Lua が
    `local = "..."` になり、**`local` は Lua の予約語**なので
    `unexpected symbol near 'local'` で config.lua ぜんぶが読めなくなる。
    """
    import pathlib

    from retroux.core.config.generate_lua import LUA_KEYWORDS, to_lua

    root = pathlib.Path(__file__).resolve().parents[1]
    import yaml
    cfg = yaml.safe_load(
        (root / "retroux" / "plugins" / "dq2" / "config.yaml")
        .read_text(encoding="utf-8"))

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert k not in LUA_KEYWORDS, (
                    f"★Lua の予約語をキーに使っている: {path}.{k}")
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(cfg)
    # ★万一書かれても、生成側が `["local"]` の形にして守ること
    #   （裸の `local = ` にならない）
    assert "local = " not in to_lua({"local": 1})


def test_予約語は添字の形にする():
    """★生成側の守り。設定を書く人を守る。"""
    from retroux.core.config.generate_lua import to_lua

    got = to_lua({"local": "x", "end": 1, "ok": 2})
    assert '["local"]' in got
    assert '["end"]' in got
    assert "ok = 2" in got          # ★予約語でないものはそのまま


def test_描き方の設定がある():
    """指示書 §16。★ワールドマップは現行のまま（§2.1）。"""
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load(
        (root / "retroux" / "plugins" / "dq2" / "config.yaml")
        .read_text(encoding="utf-8"))
    rendering = cfg["map"]["rendering"]
    assert rendering["world"] == LEGACY
    assert rendering["non_world"] == CHARACTER
    capture = rendering["capture"]
    assert capture["allowed_state"] == "field_idle"
    assert capture["ignore_black"] is True
