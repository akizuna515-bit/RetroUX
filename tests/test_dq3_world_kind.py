"""地点の印は、その世界の地図にだけ出す（RX3-0315 / 2026-09-20）。

⚠⚠ 依頼者「アレフガルドでの緑の丸が誤って表示される。おそらく下の世界の正解地図は別座標。」

## ★何が起きていたか

```text
上の世界      world_main      256 x 256
アレフガルド  world_alefgard  158 x 138   ⚠ 升の意味も広さも違う
```

★`Location` は `world_x` / `world_y` を持っていましたが、
⚠⚠ **どちらの世界の座標か**を持っていませんでした。
→ ⚠ 上の世界の地点が、そのままアレフガルドの地図に重なって出ていました。

⚠ さらに `note_world` は **`kind == 0` のときしか呼ばれていません**でした。
★アレフガルドの地点は「最後に居た**上の世界**の升」を覚えてしまいます。

## ⚠ 昔の記録の扱い

★`world_kind` が `None` の記録（この直しより前のもの）は、
**上の世界のときだけ**出します（⚠ 下の世界には推測で置かない）。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.knowledge import location_book as LB                # noqa: E402
from dq3.knowledge import location_master as LM              # noqa: E402

UPPER, ALEF = LB.WORLD_KIND, LB.ALEFGARD_KIND


def _book(tmp_path):
    return LB.LocationBook(LM.LocationMaster({}), tmp_path / "book.json",
                           lambda m: None, lambda m: None)


# --- ★台帳がどちらの世界かを覚える -------------------------------------------

def test_世界地図の種別は2つ():
    assert LB.WORLD_KINDS == (0, 2)


def test_上の世界で覚えた地点は上の世界(tmp_path):
    book = _book(tmp_path)
    book.note_world(100, 50, kind=UPPER)
    book.enter(9)
    got = book.locations["L9"]
    assert (got.world_x, got.world_y) == (100, 50)
    assert got.world_kind == UPPER


def test_アレフガルドで覚えた地点はアレフガルド(tmp_path):
    """★★ これが直したかったこと。"""
    book = _book(tmp_path)
    book.note_world(100, 50, kind=UPPER)
    book.enter(9)
    book.note_world(30, 40, kind=ALEF)
    book.enter(7)
    got = book.locations["L7"]
    assert (got.world_x, got.world_y) == (30, 40)
    assert got.world_kind == ALEF, "⚠⚠ 下の世界の地点が上の世界の升を持った"


def test_世界を移っても前の地点は書き換えない(tmp_path):
    """⚠⚠ 上の世界の (100,50) と 下の世界の (100,50) は**別の場所**。"""
    book = _book(tmp_path)
    book.note_world(100, 50, kind=UPPER)
    book.enter(9)                                   # ★上の世界の L9
    book.note_world(101, 50, kind=ALEF)             # ⚠ 下の世界で隣の升に出た
    got = book.locations["L9"]
    assert (got.world_x, got.world_y) == (100, 50), "⚠⚠ よその世界の升で直した"
    assert got.world_kind == UPPER


def test_同じ世界なら今までどおり直す(tmp_path):
    """★出口の升で直す仕組み（RX3-0275）は、同じ世界では今までどおり。"""
    book = _book(tmp_path)
    book.note_world(100, 50, kind=UPPER)
    book.enter(9)
    book.note_world(101, 50, exit_xy=(101, 50), kind=UPPER)
    got = book.locations["L9"]
    assert (got.world_x, got.world_y) == (101, 50)


def test_書いて読み直しても世界が残る(tmp_path):
    book = _book(tmp_path)
    book.note_world(30, 40, kind=ALEF)
    book.enter(7)
    book.save(force=True)
    again = LB.LocationBook.load(path=tmp_path / "book.json",
                                 rom_place_name=lambda m: None,
                                 heard_place_name=lambda m: None)
    assert again.locations["L7"].world_kind == ALEF
    assert again.last_world_kind == ALEF


def test_古い記録は分からないまま(tmp_path):
    """⚠ この欄より前の記録は `None`（★推測で埋めない）。"""
    import json

    path = tmp_path / "book.json"
    path.write_text(json.dumps({"locations": {"L9": {
        "location_id": "L9", "world_x": 100, "world_y": 50, "visited": True}}}),
        encoding="utf-8")
    got = LB.LocationBook.load(path=path, rom_place_name=lambda m: None,
                               heard_place_name=lambda m: None)
    assert got.locations["L9"].world_kind is None
    assert got.last_world_kind == UPPER, "⚠ 既定は上の世界"


# --- ★仮名の方角も同じ世界だけで ---------------------------------------------

def test_仮名の基準は同じ世界の拠点だけ(tmp_path):
    """⚠⚠ 別の世界の町を基準に方角を言わない（★升の意味が違う）。"""
    book = _book(tmp_path)
    book.note_world(100, 50, kind=UPPER)
    book.enter(9)
    book.rename("L9", "アリアハン")                  # ★上の世界の拠点
    upper = book.nearest_known_base((101, 51), kind=UPPER)
    assert upper is not None and upper.location_id == "L9"
    assert book.nearest_known_base((101, 51), kind=ALEF) is None, (
        "⚠⚠ 下の世界から上の世界の町を基準にした")


# --- ★画面（緑の丸）---------------------------------------------------------

class _Canvas:
    """★`MapCanvas._marks` だけを借りる（⚠ 本物の窓は作らない）。"""

    from dq3.ui.map_window import MapCanvas as _Real

    _marks = _Real._marks

    def __init__(self, vm):
        self.vm = vm


class _VM:
    def __init__(self, book, known):
        self.location_book = book
        self._known = list(known)

    def known_locations(self):
        return list(self._known)


def _canvas(tmp_path):
    book = _book(tmp_path)
    book.note_world(100, 50, kind=UPPER)
    book.enter(9)
    book.rename("L9", "アリアハン")
    book.note_world(30, 40, kind=ALEF)
    book.enter(7)
    book.rename("L7", "ラダトーム")
    return _Canvas(_VM(book, ["L9", "L7"])), book


def test_上の世界には上の世界の地点だけ(tmp_path):
    got, _book_ = _canvas(tmp_path)
    assert got._marks(UPPER) == [(100, 50, "L9")]


def test_アレフガルドには下の世界の地点だけ(tmp_path):
    """★★ 依頼者「アレフガルドでの緑の丸が誤って表示される」。"""
    got, _book_ = _canvas(tmp_path)
    assert got._marks(ALEF) == [(30, 40, "L7")]


def test_世界を渡さなければ今までどおり全部(tmp_path):
    """⚠ 古い呼び方（引数なし）を壊さない。"""
    got, _book_ = _canvas(tmp_path)
    assert sorted(got._marks()) == [(30, 40, "L7"), (100, 50, "L9")]


def test_世界の分からない地点は上の世界だけに出す(tmp_path):
    """⚠⚠ 下の世界に推測で置かない（★この直しより前の記録）。"""
    got, book = _canvas(tmp_path)
    book.locations["L9"].world_kind = None
    assert got._marks(UPPER) == [(100, 50, "L9")]
    assert got._marks(ALEF) == [(30, 40, "L7")], "⚠⚠ 分からない地点を下の世界に置いた"


def test_座標を知らない地点は今までどおり出さない(tmp_path):
    got, book = _canvas(tmp_path)
    book.locations["L9"].world_x = None
    assert got._marks(UPPER) == []


# --- ⚠ 壊す実験で見つかった、通っていなかった道 -------------------------------


def test_よその世界の出口の升では直さない(tmp_path):
    """⚠⚠ `exit_xy` つき（= 信じてよい升）でも、★別の世界なら直さない。

    ⚠ 壊す実験で分かった穴: 上の検査は `exit_xy` を渡していないので、
    ★そもそも「直す」枝に入っていませんでした。
    """
    book = _book(tmp_path)
    book.note_world(100, 50, kind=UPPER)
    book.enter(9)
    # ⚠ 下の世界で、たまたま 1 升ずれた所に出た（★上の世界の記録を書き換えてはいけない）
    book.note_world(101, 50, exit_xy=(101, 50), kind=ALEF)
    got = book.locations["L9"]
    assert (got.world_x, got.world_y) == (100, 50), "⚠⚠ よその世界の升で直した"
    assert got.world_kind == UPPER


def test_出口の升で直したら世界も覚える(tmp_path):
    """⚠ 壊す実験で分かった穴: `_fix_world` の側で世界を覚えていなかった。"""
    book = _book(tmp_path)
    book.note_world(100, 50, kind=ALEF)
    book.enter(7)
    book.locations["L7"].world_kind = None          # ⚠ 昔の記録のふり
    book.note_world(101, 50, exit_xy=(101, 50), kind=ALEF)
    got = book.locations["L7"]
    assert (got.world_x, got.world_y) == (101, 50)
    assert got.world_kind == ALEF, "⚠⚠ 直したのに世界を覚えていない"


def test_座標の無い地点を埋めたときも世界を覚える(tmp_path):
    book = _book(tmp_path)
    book.enter(7)                                   # ⚠ まだ升を知らない
    assert book.locations["L7"].world_x is None
    book.note_world(30, 40, kind=ALEF)
    got = book.locations["L7"]
    assert (got.world_x, got.world_y) == (30, 40)
    assert got.world_kind == ALEF


# --- ★画面から台帳まで（⚠ ここを通していなかった）----------------------------


class _Watcher:
    def note(self, state):
        return 0


class _NoteVM:
    """★`Dq3ViewModel.note_here` だけを借りる（⚠ 本物の記録には書かない）。"""

    from dq3.ui.view_model import Dq3ViewModel as _Real

    note_here = _Real.note_here

    @staticmethod
    def _complete_go_on_arrival(location_id):
        return []                                    # ⚠ 「行ってみる？」は別の検査で見る

    @staticmethod
    def mark_memo_done(*_a, **_k):
        return None

    def add_memo(self, text, **kw):
        return None

    def __init__(self, book, at):
        self.location_book = book
        self._at = at
        self._visited: set = set()
        self.saved = 0

    def position(self):
        return self._at

    def save_knowledge(self):
        self.saved += 1


def test_アレフガルドでも升を覚える(tmp_path):
    """★★ 壊す実験で分かった穴: ⚠ `note_here` の関所を 1 度も通していなかった。

    ⚠⚠ ここが `kind == 0` だけだと、★下の世界では升を 1 度も覚えません。
    """
    book = _book(tmp_path)
    vm = _NoteVM(book, (ALEF, None, 30, 40))
    assert vm.note_here() is None                   # ★世界地図は「地点」ではない
    assert book.last_world == (30, 40)
    assert book.last_world_kind == ALEF, "⚠⚠ 下の世界の升を覚えていない"


def test_上の世界でも今までどおり升を覚える(tmp_path):
    book = _book(tmp_path)
    vm = _NoteVM(book, (UPPER, None, 100, 50))
    assert vm.note_here() is None
    assert book.last_world == (100, 50) and book.last_world_kind == UPPER


def test_町の中では升を覚えない(tmp_path):
    """⚠ 町（kind 1）は世界地図ではない（★升を上書きしない）。"""
    book = _book(tmp_path)
    book.note_world(100, 50, kind=UPPER)
    vm = _NoteVM(book, (1, 9, 5, 5))
    vm.note_here()
    assert book.last_world == (100, 50) and book.last_world_kind == UPPER


# --- ★★ 仮名の基準は同じ世界だけ（RX3-0321 / 2026-09-20）--------------------
#
#   ⚠⚠ 依頼者「save2 ルビスの従者のほこらだが、仮名がアッサラームの南東の場所（仮）
#     となっている。地下世界を意識できていない？」→ ★そのとおりでした。


def _town(book, map_id, name, xy, kind):
    book.note_world(xy[0], xy[1], kind=kind)
    book.enter(map_id)
    book.rename("L%d" % map_id, name)
    return book.locations["L%d" % map_id]


def test_下の世界では上の世界の町を基準にしない(tmp_path):
    """★★ これが直したかったこと。"""
    book = _book(tmp_path)
    _town(book, 12, "アッサラーム", (86, 110), UPPER)
    book.note_world(99, 122, kind=ALEF)          # ⚠ 下の世界（★升は上の世界と近い数）
    got = book.enter(41)
    name = got["location"].display_name
    assert "アッサラーム" not in name, "⚠⚠ よその世界の町を名乗った: %s" % name
    assert name.startswith(LB.UNSURE_HEAD), name


def test_下の世界に拠点があればそれを基準にする(tmp_path):
    book = _book(tmp_path)
    _town(book, 12, "アッサラーム", (86, 110), UPPER)
    _town(book, 7, "ラダトーム", (100, 120), ALEF)
    book.note_world(99, 122, kind=ALEF)
    got = book.enter(41)
    name = got["location"].display_name
    assert name.startswith("ラダトーム"), name


def test_上の世界は今までどおり(tmp_path):
    """⚠ 世界の分からない記録（★この直しより前）も、上の世界では基準にできる。"""
    book = _book(tmp_path)
    _town(book, 12, "アッサラーム", (86, 110), UPPER)
    book.locations["L12"].world_kind = None      # ⚠ 昔の記録のふり
    book.note_world(88, 120, kind=UPPER)
    got = book.enter(41)
    assert got["location"].display_name.startswith("アッサラーム")


def test_世界の分からない拠点は下の世界では使わない(tmp_path):
    """⚠⚠ 下の世界に推測で持ち込まない（★緑の丸と同じ向きの決まり）。"""
    book = _book(tmp_path)
    _town(book, 12, "アッサラーム", (86, 110), UPPER)
    book.locations["L12"].world_kind = None
    assert book.nearest_known_base((88, 120), kind=UPPER) is not None
    assert book.nearest_known_base((88, 120), kind=ALEF) is None


def test_よその世界の町を名乗る仮名は付け直す(tmp_path):
    """★もう付いてしまった仮名も、⚠ **入り直したときに**直る。"""
    book = _book(tmp_path)
    _town(book, 12, "アッサラーム", (86, 110), UPPER)
    book.note_world(99, 122, kind=ALEF)
    book.enter(41)
    loc = book.locations["L41"]
    # ⚠ この直しの前に付いた形にしておく
    loc.display_name, loc.name_rule = "アッサラーム南東の場所", LB.DIRECTION_RULE
    loc.name_source = LB.PROVISIONAL
    assert book._needs_rename(loc) is True, "⚠⚠ 付け直しの対象にならない"
    book.enter(41)
    assert "アッサラーム" not in book.locations["L41"].display_name


def test_上の世界の仮名は付け直さない(tmp_path):
    """⚠ 巻き込まない（★入るたびに名前が変わるのは依頼者の困りごと）。"""
    book = _book(tmp_path)
    _town(book, 12, "アッサラーム", (86, 110), UPPER)
    book.note_world(88, 120, kind=UPPER)
    book.enter(41)
    before = book.locations["L41"].display_name
    assert before.startswith("アッサラーム")
    assert book._needs_rename(book.locations["L41"]) is False
    book.enter(41)
    assert book.locations["L41"].display_name == before


def test_基準が1つも無い上の世界の仮名は触らない(tmp_path):
    """⚠⚠ 壊す実験で分かった穴: ★`near is None` の枝を、上の世界で 1 度も通していなかった。

    ★拠点が 1 つも無いのは、⚠ **記録を消した後**などに起きます。
    ⚠ そこで付け直すと、★入るたびに名前が変わります（= 依頼者の困りごと / RX3-0122）。
    """
    book = _book(tmp_path)
    book.note_world(88, 120, kind=UPPER)
    book.enter(41)
    loc = book.locations["L41"]
    loc.display_name, loc.name_rule = "どこかの北西の場所", LB.DIRECTION_RULE
    loc.name_source = LB.PROVISIONAL
    assert book.nearest_known_base((88, 120), kind=UPPER) is None, "⚠ 前提: 拠点が無い"
    assert book._needs_rename(loc) is False, "⚠⚠ 上の世界の仮名まで付け直した"


def test_基準が1つも無い下の世界の仮名は付け直す(tmp_path):
    """★下の世界では、⚠ 拠点が無ければ方角で名乗れない（= 付け直す）。"""
    book = _book(tmp_path)
    book.note_world(99, 122, kind=ALEF)
    book.enter(41)
    loc = book.locations["L41"]
    loc.display_name, loc.name_rule = "アッサラーム南東の場所", LB.DIRECTION_RULE
    loc.name_source = LB.PROVISIONAL
    assert book.nearest_known_base((99, 122), kind=ALEF) is None
    assert book._needs_rename(loc) is True
