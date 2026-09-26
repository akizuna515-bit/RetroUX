"""お店画面を性能順に並べ替える（RX3-0285 / 2026-09-18）。

依頼者「性能順でソートする WI をつくりたい」（★`RX3-0274`「お店すべて」の実機確認 OK の直後）。

```text
★見出しを押して並べ替え（品 / 性能 / 値段）。⚠ 最初の 1 回は性能・値段なら高い順
⚠⚠ 画面の文字では並べない    「性能」は `攻撃 12` `守備 30` `—` という文字（★文字順だと 9 > 12）
⚠⚠ 番号だけを並べ替える      品と街・店を別々に並べ替えると**対応がずれる**
```
"""
from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.ui import shop_window as SW                         # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Info:
    """★`ItemInfo` の並べ替えに要る所だけ（⚠ ROM を読まない）。"""

    def __init__(self, label, pri_stat, buy_price, category="armor"):
        self.label = label
        self.pri_stat = pri_stat
        self.buy_price = buy_price
        self.category = category

    @property
    def stat_label(self) -> str:
        if self.pri_stat is None:
            return ""
        head = "攻撃" if self.category == "weapon" else "守備"
        return "%s %d" % (head, self.pri_stat)


def _sample():
    return [
        _Info("かわのふく", 4, 10),
        _Info("てつのよろい", 12, 350),
        _Info("やくそう", None, 8, "item"),
        _Info("けいこぎ", 9, 60),
        _Info("どうのつるぎ", 12, 100, "weapon"),      # ★性能が同じ・分類が違う
    ]


def _labels(infos, keep):
    return [infos[k].label for k in keep]


# --- ★並べ替えの中身（⚠ Qt を使わない） -------------------------------------

def test_性能は数として並ぶ():
    """⚠⚠ 画面の文字（`守備 9` / `守備 12`）で並べると 9 が上に来る。"""
    infos = _sample()
    keep = list(range(len(infos)))
    got = _labels(infos, SW.sort_keep(infos, keep, 1, desc=True))
    assert got[:2] == ["どうのつるぎ", "てつのよろい"], got   # ★12 が先（⚠ 9 ではない）
    assert got.index("けいこぎ") < got.index("かわのふく")     # ★9 → 4


def test_性能の無い品はいつも最後():
    infos = _sample()
    keep = list(range(len(infos)))
    for desc in (True, False):
        got = _labels(infos, SW.sort_keep(infos, keep, 1, desc=desc))
        assert got[-1] == "やくそう", (desc, got)


def test_同じ性能は分類_元の順で安定():
    """⚠ 武器と防具で `12` が同じでも、★分類でまとまる（= 散らばらない）。"""
    infos = _sample()
    keep = list(range(len(infos)))
    got = _labels(infos, SW.sort_keep(infos, keep, 1, desc=True))
    # ★CATEGORY_ORDER は weapon → armor（⚠ 同値なら武器が先）
    assert got.index("どうのつるぎ") < got.index("てつのよろい")


def test_値段でも並べ替えられる():
    """⚠ 画面は `⚠ 1200 G` の飾りつき（★中身の数で並べる）。"""
    infos = _sample()
    keep = list(range(len(infos)))
    assert _labels(infos, SW.sort_keep(infos, keep, 2, desc=True))[0] == "てつのよろい"
    assert _labels(infos, SW.sort_keep(infos, keep, 2, desc=False))[0] == "やくそう"  # ★8 G


def test_売っていない品は値段でも最後():
    infos = _sample() + [_Info("おうじゃのけん", 40, 0, "weapon")]
    keep = list(range(len(infos)))
    for desc in (True, False):
        got = _labels(infos, SW.sort_keep(infos, keep, 2, desc=desc))
        assert got[-1] == "おうじゃのけん", (desc, got)


def test_品は辞書順():
    infos = _sample()
    keep = list(range(len(infos)))
    got = _labels(infos, SW.sort_keep(infos, keep, 0, desc=False))
    assert got == sorted(got)


def test_並べ替えない列は触らない():
    """⚠ 「街・店」で並べ替えても意味が無い（★同じ品が散らばるだけ）。"""
    infos = _sample()
    keep = [4, 0, 2]
    assert SW.sort_keep(infos, keep, 3, desc=True) == keep
    assert 3 not in SW.SORTABLE_COLUMNS


def test_絞ったあとの番号だけを並べ替える():
    """★`keep`（= 検索で残った番号）の中だけで並ぶ（⚠ 外の品を引き込まない）。"""
    infos = _sample()
    keep = [0, 1]                                            # ★かわのふく / てつのよろい
    got = SW.sort_keep(infos, keep, 1, desc=True)
    assert got == [1, 0] and set(got) == set(keep)


# --- ★画面（⚠ 見出しを押す所までつなぐ） -------------------------------------

def _app():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:                                      # pragma: no cover
        pytest.skip("Qt が無い環境")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path):
    """★「お店すべて」の窓（⚠ 行った街は検査が用意する / RX-0141）。"""
    from dq3.knowledge import item_info as II

    II.reset()
    if not II.available():
        pytest.skip("DQ3 の ROM が読めない")
    _app()
    from dq3.knowledge.location_book import LocationBook
    from dq3.ui.shop_window import ALL_SHOPS_KEY, Dq3ShopWindow

    book = LocationBook(path=tmp_path / "location-book.json")
    for map_id in II.shops_by_map():
        book.enter(map_id)

    class _VM:
        gold = 999
        location_book = book

        def equip_members(self):
            return []

    win = Dq3ShopWindow(_VM())
    index = win.shop_select.findData(ALL_SHOPS_KEY)           # ★「お店すべて」= 街・店の欄が出る
    assert index >= 0
    win.shop_select.setCurrentIndex(index)
    yield win
    win.close()


def _rows(win):
    """★いま並んでいる `(品, 性能の文字, 値段の文字, 街・店)`。"""
    out = []
    for i in range(win.list.topLevelItemCount()):
        item = win.list.topLevelItem(i)
        out.append(tuple(item.text(c) for c in range(4)))
    return out


def test_見出しを押すと性能の高い順になる(window):
    from PySide6.QtCore import Qt

    window.kind_select.setCurrentIndex(window.kind_select.findText("よろい"))
    before = _rows(window)
    assert len(before) >= 3, before

    window.sort_by(1)                                        # ★1 回目 = 高い順
    assert window.sort_state() == (1, True)
    stats = [int(r[1].split()[-1]) for r in _rows(window) if r[1] != "—"]
    assert stats == sorted(stats, reverse=True), stats
    assert window.list.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

    window.sort_by(1)                                        # ★2 回目 = 低い順
    assert window.sort_state() == (1, False)
    stats = [int(r[1].split()[-1]) for r in _rows(window) if r[1] != "—"]
    assert stats == sorted(stats), stats


def test_並べ替えても品と街_店の対応がずれない(window):
    """⚠⚠ ここが本題（★品・街/店を別々に並べ替えると静かにずれる）。"""
    window.kind_select.setCurrentIndex(window.kind_select.findText("よろい"))
    pairs_before = {(r[0], r[3]) for r in _rows(window)}
    window.sort_by(1)
    rows = _rows(window)
    assert {(r[0], r[3]) for r in rows} == pairs_before, "⚠⚠ 品と街・店の組が変わった"
    # ★選んだ行の中身と街・店も一致する
    for i in (0, len(rows) - 1):
        window.list.setCurrentItem(window.list.topLevelItem(i))
        assert window.current().label == rows[i][0]
        assert (window.current_where() or "") == rows[i][3]


def test_検索と併せても崩れない(window):
    window.sort_by(1)
    window.search_edit.setText("かわ")
    rows = _rows(window)
    assert rows, "⚠ 「かわ」で 1 件も出ない（★材料を確かめること）"
    assert all("かわ" in r[0] for r in rows), rows
    stats = [int(r[1].split()[-1]) for r in rows if r[1] != "—"]
    assert stats == sorted(stats, reverse=True), stats


def test_開いたときは店の順のまま(window):
    """⚠ 並べ替えを覚えない（★WI の Scope / 開くたびに店の順から）。"""
    assert window.sort_state() is None


def test_Qtの文字ソートは使わない():
    """⚠⚠ `setSortingEnabled(True)` に戻すと、★画面の文字で並んで 9 > 12 になる。"""
    src = (ROOT / "dq3" / "ui" / "shop_window.py").read_text(encoding="utf-8")
    # ⚠ 註釈（「使わない」と書いてある行）は数えない（★中身の行だけ見る）
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    hit = [ln.strip() for ln in code if "setSortingEnabled" in ln]
    assert not hit, "⚠⚠ Qt の文字ソートを使っている: %r" % hit
    assert "sectionClicked" in src, "⚠ 見出しを押せるようにつないでいない"
