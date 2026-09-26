"""見た地図の「訪れた地点」の印（RX3-0132 / 2026-09-09）。

```text
⚠ これまで  画面の隅から 20 + i*40 で横並び（★座標を持っていなかった頃の仮置き）
★これから  location-book の世界座標に置く。⚠ 世界地図のときだけ
```

依頼者 2026-09-09「緑のポチの必要性はなんだっけ？ なければ消して良い」
→ ★意味のある場所に出るようにしました（⚠ 要らなければ出さない選択も残せます）。
"""
from __future__ import annotations

import os
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                          # noqa: E402

pytest.importorskip("PySide6")

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
#: ★升の絵（metatile）は ROM から出す（RX3-0232）。窓を実際に描く検査だけが要る
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


class _Loc:
    def __init__(self, x, y, name_rule="", parent_location_id="", name_source=""):
        self.world_x, self.world_y = x, y
        self.name_rule, self.parent_location_id = name_rule, parent_location_id
        self.name_source = name_source


class _Book:
    def __init__(self, rows):
        self.locations = rows


class _VM:
    def __init__(self, rows, visited):
        self.location_book = _Book(rows)
        self._visited = visited

    def known_locations(self):
        return sorted(self._visited)


def _view(vm):
    from dq3.ui.map_window import MapCanvas

    view = MapCanvas.__new__(MapCanvas)               # ⚠ Qt を組まない（★純粋な計算だけ見る）
    view.vm = vm
    return view


def test_世界座標のある地点だけを出す():
    vm = _VM({"L0": _Loc(172, 218), "L9": _Loc(154, 194), "L110": _Loc(None, None)},
             ["L0", "L9", "L110"])
    got = _view(vm)._marks()
    assert sorted(got) == [(154, 194, "L9"), (172, 218, "L0")]


def test_訪れていない地点は出さない():
    vm = _VM({"L0": _Loc(172, 218), "L9": _Loc(154, 194)}, ["L0"])
    assert _view(vm)._marks() == [(172, 218, "L0")]


def test_場所の中の部屋と塔の階は印にしない():
    """⚠⚠ RX3-0275（依頼者「ここのmapに◯があるが、何もない」）。

    ★アッサラームの小部屋1（L121）が町の 2 升東に、イシスの城（L85）が町と別に ◯ を出していた。
    ★世界地図に入口があるのは、それを中に持つ場所だけ。
    """
    p = "provisional"
    vm = _VM({"L12": _Loc(86, 110, name_source="rom"),
              "L121": _Loc(88, 110, name_rule="parent", name_source=p),
              "L61": _Loc(128, 112, name_rule="direction", name_source=p),
              "L219": _Loc(128, 112, name_rule="floor", parent_location_id="L61", name_source=p),
              "L86": _Loc(37, 138, name_rule="parent", name_source=p),
              "L200": _Loc(30, 30, parent_location_id="L12", name_source=p)},
             ["L12", "L121", "L61", "L219", "L86", "L200"])
    assert sorted(_view(vm)._marks()) == [(86, 110, "L12"), (128, 112, "L61")]


def test_正式な名前になった場所は仮名の頃の付け方が残っていても出す():
    """⚠ ルザミ・ノルドの洞窟: 仮名の頃の name_rule（parent）が残ったまま、正式な名前になっている。"""
    vm = _VM({"L19": _Loc(209, 242, name_rule="parent", name_source="rom"),
              "L47": _Loc(92, 104, name_rule="parent", name_source="dialogue")}, ["L19", "L47"])
    assert sorted(_view(vm)._marks()) == [(92, 104, "L47"), (209, 242, "L19")], "⚠⚠ 町・洞窟の ◯ まで消した"


def test_同じ升の印は1つで名前の確かな場所を出す():
    """⚠ レーベ (159,192) と同じ升に仮名の場所がある → ★レーベの ◯ を出す（⚠ 番号の若い仮名ではない）。"""
    vm = _VM({"L10": _Loc(159, 192, name_rule="direction", name_source="provisional"),
              "L9": _Loc(159, 192, name_source="dialogue")}, ["L10", "L9"])
    assert _view(vm)._marks() == [(159, 192, "L9")], "⚠ 同じ升に ◯ を 2 つ重ねた / 仮名の場所を出した"


def test_台帳が無くても落ちない():
    class _Bare:
        location_book = None

        def known_locations(self):
            return ["L0"]

    assert _view(_Bare())._marks() == []


def test_升の座標を返す(monkeypatch):
    """⚠⚠ **画面の座標を返さないこと。** ★地形と同じ変換で置くのは `paintEvent` の仕事。"""
    src = (ROOT / "dq3" / "ui" / "map_window.py").read_text(encoding="utf-8")
    assert "20 + (i % 8) * 40" not in src, "⚠⚠ 仮置きの並べ方が残っている"
    assert 'place["kind"] in (0, 2)' in src, "⚠ 世界地図のときだけにしていない"
    assert "self._place" in src, "⚠ 地形と同じ変換を使っていない"


@needs_rom
def test_窓を組んで印が地形の上に出る(tmp_path):
    """★本当に窓を組んで、⚠ 印が地形の枠の中に入ること。"""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from dq3.ui.map_window import MapCanvas

    class _VM2(_VM):
        follow = True

        def position(self):
            return (0, 9, 172, 218)                    # ★世界地図

        @property
        def seen(self):
            class _Seen:
                def cells(self, _key):
                    return {(x, y) for x in range(168, 178) for y in range(214, 222)}

                def count(self, _key):
                    return len(self.cells(_key))
            return _Seen()

        def tile_art(self):
            return None                                # ⚠ 色ブロックで描く（★絵は要らない）

    vm = _VM2({"L0": _Loc(172, 218)}, ["L0"])
    view = MapCanvas(vm)
    view.resize(320, 320)
    view.grab()                                        # ★paintEvent を通す
    assert view._place is not None, "⚠ 地形を描けていない"
    assert view._place["kind"] == 0
    assert view._hits, "⚠⚠ 印が 1 つも出ていない（★押せない）"


class _WorldVM(_VM):
    """★世界地図 (172,218) の周りを見た記録（★色ブロックで描く）。"""

    follow = True

    def position(self):
        return (0, 9, 172, 218)

    @property
    def seen(self):
        class _Seen:
            def cells(self, _key):
                return {(x, y) for x in range(168, 178) for y in range(214, 222)}

            def count(self, _key):
                return len(self.cells(_key))
        return _Seen()

    def tile_art(self):
        return None


def _pixel(visited, at=None):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from dq3.ui.map_window import MapCanvas

    view = MapCanvas(_WorldVM({"L0": _Loc(172, 218)}, visited))
    view.resize(320, 320)
    img = view.grab().toImage()
    if at is None:
        at = view._hits[0][0].center()                 # ★当たり判定の枠の真ん中 = 印の真ん中
    c = img.pixelColor(at)
    return (c.red(), c.green(), c.blue()), at


@needs_rom
def test_印の中は透けて升の絵が見える():
    """⚠⚠ RX3-0190（2026-09-12 依頼者「緑丸で邪魔されてわからない。透明の緑丸にすると良いかも。」）。

    ★塗りつぶした緑の丸が、その升の絵（村）を隠していた → ★輪にして中を透かす。
    """
    marked, at = _pixel(["L0"])
    under, _ = _pixel([], at)                            # ★同じ升の、印の無い色
    green = (0x8B, 0xD4, 0x50)

    def dist(a, b):
        return sum(abs(x - y) for x, y in zip(a, b))

    assert marked != green, "⚠⚠ 印の中が緑で塗りつぶされている（★升の絵が見えない）"
    assert dist(marked, under) < dist(marked, green), (
        "⚠ 印の中が地形の色より緑に近い: 印 %s / 地形 %s" % (marked, under))
