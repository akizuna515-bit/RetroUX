"""場所は**数の順**に並べる（RX3-0438 / 2026-09-27 依頼者）。

⚠ 文字列の順だと L1 → L10 → L100 → L11 … になり、地図を見ながら
`location-names.csv` を直すときに探せない。
"""
from __future__ import annotations

import collections
import importlib.util
import pathlib

import pytest

from dq3.knowledge.locations import sort_key

#: ★文字列の順と数の順が**食い違う**並び（⚠ 1 例だけだと偶然一致する）
MIXED = ["L100", "L2", "L10", "world", "L1", "L21", "L3"]
WANT = ["L1", "L2", "L3", "L10", "L21", "L100", "world"]


def test_Lの数は数の順でそれ以外は後ろ():
    assert sorted(MIXED, key=sort_key) == WANT
    assert sorted(MIXED) != WANT, "⚠ 見本が文字列の順と一致している（検査にならない）"


def test_勇者メモの控えの場所の一覧は数の順():
    script = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "dq3_memo_export.py"
    if not script.is_file():
        pytest.skip("★公開版には scripts/dq3_memo_export.py がありません")
    spec = importlib.util.spec_from_file_location("dq3_memo_export_t", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # ⚠ メモの数は「多い順」と「数の順」が食い違うように付ける
    counts = collections.Counter({loc: n for n, loc in enumerate(reversed(WANT), start=1)})
    assert [loc for loc, _n in mod.in_location_order(counts)] == WANT


def test_管理画面の場所の一覧は数の順(tmp_path):
    from dq3.knowledge.location_book import Location, LocationBook

    book = LocationBook(path=tmp_path / "location-book.json")
    for loc in MIXED:
        book.locations[loc] = Location(location_id=loc)
    assert [row.location_id for row in book.all_locations()] == WANT
