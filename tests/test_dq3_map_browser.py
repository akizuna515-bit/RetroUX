"""行った地図を選んで見る（RX3-0024 / 2026-08-30）。

依頼者 2026-08-30:

    ボタンを押すと各 MAP 画面が出て、MAP 選択（言ったところ）と
    メモが出るようにする感じで

⚠⚠ ここが崩れると、★**行っていない地図が一覧に出ます**（No-Spoiler）。
"""

from __future__ import annotations

import os
import pathlib

import pytest

pytest.importorskip("PySide6")

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
#: ★地図の絵（metatile）は ROM から出す（RX3-0232）
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module", autouse=True)
def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _vm(*marks):
    """★見た升を与えた、画面が使う中身。"""
    from dq3.knowledge.seen_map import SeenMap
    from dq3.ui.models import MemoBook

    seen = SeenMap(pathlib.Path("使わない"))
    for key, cells in marks:
        for x, y in cells:
            seen.mark(key, x, y)

    class VM:
        memos = MemoBook()

        def place_name(self, map_id):
            return None                       # ⚠ 名前は知らない（★番号で出る側を見る）

        def position(self):
            return (0, None, 10, 10)

        def known_locations(self):
            return []

        def recent_memos(self, n=3):
            return []

    VM.seen = seen
    return VM()


def _browser(*marks):
    from dq3.ui.map_browser import Dq3MapBrowser

    return Dq3MapBrowser(_vm(*marks))


# --- ⚠⚠ No-Spoiler --------------------------------------------------------

def test_行った地図だけを一覧に出す():
    """⚠⚠ **これが今回いちばん大事な検査**。

    ★ROM には 243 件のエリアマップがあるが、⚠ そこから一覧を作らない
    （★行っていない所が分かってしまう）。
    """
    got = _browser(("w", [(10, 10)]), ("L9", [(3, 3)]))

    keys = [got.list.item(i).data(0x0100)  # Qt.ItemDataRole.UserRole
            for i in range(got.list.count())]
    assert sorted(keys) == ["L9", "w"], "⚠⚠ 行っていない地図が出ている"


def test_記録が空の地図は出さない():
    """⚠ 鍵だけあって升が 0 の地図は、★行っていないのと同じ。"""
    from dq3.knowledge.seen_map import SeenMap

    vm = _vm(("w", [(10, 10)]))
    vm.seen.maps.setdefault("L3", SeenMap(pathlib.Path("x")).maps.get("L3"))
    from dq3.knowledge.seen_map import _Map

    vm.seen.maps["L3"] = _Map()          # ⚠ 升が 0
    from dq3.ui.map_browser import Dq3MapBrowser

    got = Dq3MapBrowser(vm)
    keys = [got.list.item(i).data(0x0100) for i in range(got.list.count())]
    assert keys == ["w"], "⚠⚠ 升が 0 の地図を出している"


def test_一覧が空なら案内を出す():
    """⚠ 黙って空にしない（★何が起きているか分かるように）。"""
    got = _browser()

    assert got.list.count() == 0
    assert got.empty.isVisibleTo(got), "⚠ 案内が出ていない"
    assert not got.canvas.isVisibleTo(got)


# --- ★一覧の見え方 ---------------------------------------------------------

def test_名前を知らない地図は番号で出す():
    """⚠⚠ 知らないものを「知っている風」に出さない。"""
    from dq3.ui.map_browser import label_of

    assert label_of("w", 10).startswith("世界地図")
    assert label_of("a", 10).startswith("アレフガルド")
    assert "9" in label_of("L9", 10)
    # ★何升見たかも出す（⚠ 進み具合が分かるように）
    assert "10" in label_of("w", 10)


def test_鍵から居場所へ戻せる():
    from dq3.ui.map_browser import key_to_position

    assert key_to_position("w") == (0, None)
    assert key_to_position("a") == (2, None)
    assert key_to_position("L9") == (1, 9)
    assert key_to_position("L?") is None
    assert key_to_position("なにこれ") is None


# --- ★選ぶ -----------------------------------------------------------------

def test_選ぶとその地図になる():
    got = _browser(("w", [(100, 100)]), ("L9", [(3, 3)]))

    got.list.setCurrentRow(0)
    first = got.model.position()
    got.list.setCurrentRow(1)
    second = got.model.position()

    assert first is not None and second is not None
    assert first[0] != second[0] or first[1] != second[1], (
        "⚠ 選んでも地図が変わっていない")


def test_選んだ地図の真ん中を見る():
    """⚠ 追随ではないので、★見た所の真ん中を見る。"""
    got = _browser(("w", [(100, 100), (110, 120)]))
    got.list.setCurrentRow(0)

    _kind, _map_id, x, y = got.model.position()
    assert 100 <= x <= 110 and 100 <= y <= 120


def test_記録が無い地図は選べない():
    from dq3.ui.map_browser import _BrowseModel

    model = _BrowseModel(_vm(("w", [(1, 1)])))
    assert model.select("L9") is False
    assert model.position() is None


# --- ⚠⚠ いつもの窓と分ける -------------------------------------------------

def test_この画面は追随しない():
    """⚠⚠ 用途が違うので**兼ねない**（依頼者 2026-08-30）。

    ★いつもの窓 → いま何が近くにあるか（追随）
    ★この画面   → どこへ行ったか（見た所ぜんぶ）
    """
    got = _browser(("w", [(100, 100)]))
    assert got.canvas.follow is False


def test_いつもの窓は追随のまま():
    """⚠ こちらを直したせいで、★あちらが変わっていないこと。"""
    from dq3.ui.map_window import MapCanvas

    class VM:
        seen = None

        def position(self):
            return None

        def known_locations(self):
            return []

    assert MapCanvas(VM()).follow is True


@needs_rom
def test_離れた2か所が両方入る():
    """⚠ 追随する窓では入りきらないが、★こちらでは両方見たい。"""
    got = _browser(("w", [(10, 10), (200, 200)]))
    got.list.setCurrentRow(0)
    image, _at = got.canvas._image_now()

    ox, oy = got.canvas.origin
    assert ox <= 10 and oy <= 10
    assert ox + image.width() > 200, "⚠⚠ 遠いほうが入っていない"


def test_現在地の印を出さない():
    """⚠ そこに**居るわけではない**（★選んで見ているだけ）。"""
    src = (ROOT / "dq3" / "ui" / "map_window.py").read_text(encoding="utf-8")
    i = src.index("if not self.follow:", src.index("def _draw_terrain"))
    j = src.index("# ★いま居る升", i)
    assert "return QRect" in src[i:j], "⚠⚠ 追随しない画面でも印を出している"


# --- ★ボタンとつながっていること -------------------------------------------

def test_ボタンから開ける():
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert '("map", "地図", ' in src, "⚠ ボタンが無い"
    assert "def open_map_browser" in src
    assert "Dq3MapBrowser" in src


def test_二つ開かない():
    """⚠ 押すたびに増えると、★窓だらけになる。"""
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    i = src.index("def open_map_browser")
    j = src.index("def ", i + 10)
    body = src[i:j]
    assert "_map_browser" in body and "if got is None:" in body
    assert "raise_()" in body


def test_閉じるとき一緒に閉じる():
    """⚠ 残ると、★次の起動で二重に出る。"""
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    i = src.index("def closeEvent")
    j = src.index("super().closeEvent", i)
    assert "_map_browser" in src[i:j], "⚠⚠ 閉じ忘れている"


# --- ★地名の入口は 1 本（RX3-0094 B）--------------------------------------------

class _FakeSeen:
    maps: dict = {}

    def count(self, key):
        return 0


class _FakeVm:
    """★`place_name` だけ持つ最小の view model。"""

    def __init__(self, names):
        self._names = names
        self.seen = _FakeSeen()

    def place_name(self, map_id):
        return self._names.get(int(map_id))


def test_地図の一覧は場所の名前を使う():
    """⚠⚠ 2026-09-07 依頼者「地図を見るだと地図0と表示されている」。

    ★`RX3-0080 §20` は「場所の名前を取る**唯一の入口**」を決めているのに、
    ⚠ 地図の一覧は `"地図 %s" % map_id` を**直書き**していました。
    """
    from dq3.ui.map_browser import label_of

    assert label_of("L0", 100, name="アリアハン").startswith("アリアハン")
    # ⚠ 知らない場所は今までどおり番号
    assert label_of("L70", 10).startswith("地図 70")
    assert label_of("w", 10).startswith("世界地図")
    assert label_of("a", 10).startswith("アレフガルド")


def test_地図の下の行も場所の名前を使う():
    from dq3.ui.map_window import place_label

    vm = _FakeVm({0: "アリアハン"})
    assert place_label(vm, 1, 0) == "アリアハン"
    assert place_label(vm, 1, 70) == "地図 70"
    assert place_label(vm, 0, None) == "世界地図"
    assert place_label(vm, 2, None) == "アレフガルド"


def test_メモ詳細も同じ入口を通る():
    from dq3.ui.memo_detail import place_name

    vm = _FakeVm({0: "アリアハン"})
    assert place_name(vm, 0) == "アリアハン"
    assert place_name(vm, 70) == "map 70"


def test_地図を見る画面にもタイルの絵が渡る():
    """⚠⚠ 2026-09-07 依頼者「地図で、地図の CHR が表示されていない」。

    ★`MapCanvas` は `view_model.tile_art` / `tile_art_runtime` を見ます
      （`map_window._tile_art` / `_tile_art_runtime` は `getattr(..., None)`）。
    ⚠ `_BrowseModel` はそれを**中継していなかった**ので、
      ★絵が無い扱いになり、⚠ 色ブロックで塗られていました。
    """
    from dq3.ui.map_browser import _BrowseModel
    from dq3.ui.map_window import _tile_art, _tile_cells

    class _Runtime:
        kind = 1
        map_id = 0
        cells = {(0, 0): 7}

    class VM:
        seen = None
        tile_art = "★絵"
        tile_art_runtime = _Runtime()

        def position(self):
            return None

    model = _BrowseModel(VM())
    assert model.tile_art == "★絵", "⚠ タイルの絵が中継されていない"
    assert model.tile_art_runtime is VM.tile_art_runtime
    # ★`MapCanvas` が実際に使う口から見ても同じ
    assert _tile_art(model) == "★絵"
    assert _tile_cells(model, 1, 0) is VM.tile_art_runtime
    # ⚠ 別の地図の升は使わない（★中継しても、ここの判断は変わらない）
    assert _tile_cells(model, 1, 70) is None


def test_絵が出せないときは理由を出す():
    """⚠⚠ 依頼者「別の地図を選ぶと色ブロックのまま」→ ★壊れていない、材料が無い。"""
    from dq3.ui.map_window import art_reason

    class _Runtime:
        kind, map_id = 1, 0

    class VM:
        tile_art = "★絵"
        tile_art_runtime = _Runtime()

    vm = VM()
    assert art_reason(vm, 1, 0) == "", "⚠ 出せているのに理由を書いている"
    assert "いま居る地図" in art_reason(vm, 1, 70)

    class NoArt:
        tile_art = None
        tile_art_runtime = None

    assert "実機につないで" in art_reason(NoArt(), 1, 0)
