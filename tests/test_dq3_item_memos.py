"""イベントで渡される品も「入手」として残す（RX3-0312 / 2026-09-20）。

⚠⚠ 依頼者「ひかりのたまの取得イベントが拾えない ※竜の女王から与えられるので、拾えないと思う」。

## ★調べて分かったこと（⚠ 見立ては半分当たり）

```text
★持ち物としては拾えていた  progress.json の items_ever に **114（ひかりのたま）が在る**
⚠ 取得イベントにならない   勇者メモへ書く口は 宝箱 と しらべる の 2 本だけで、
                           どちらも `chest_bits` の印が立ったことがきっかけ
                           → ⚠ 会話で渡される品は、どちらの印も立たない
```

## ⚠ ついでに見つかった実バグ

★`view_model` は前から `source="search"` を渡していたのに、`SOURCES` に無く
**黙って `unknown` に落ちて**いました。
★実データ: `memos.jsonl` の `source == "unknown"` の **4 件が全部「しらべる：…」**。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.knowledge import memos as M                       # noqa: E402
from dq3.knowledge import progress as PG                   # noqa: E402

LIGHT_ORB = 114        #: ★ひかりのたま（⚠ ROM の辞書から引いた番号）


def _party(*item_lists):
    return [{"items": list(x)} for x in item_lists]


# --- ⚠ 黙って unknown に落ちていた分類 ---------------------------------------

def test_しらべるの分類が残る():
    """⚠⚠ `source="search"` が `SOURCES` に無く、★unknown に落ちていた。"""
    assert M.SEARCH in M.SOURCES
    assert M.ITEM in M.SOURCES


def test_知らない分類は今までどおりunknown(tmp_path):
    store = M.MemoStore(tmp_path / "memos.jsonl")
    got = store.add("x", source="そんな分類は無い")
    assert got.source == M.UNKNOWN


@pytest.mark.parametrize("source", [M.SEARCH, M.ITEM])
def test_新しい分類はそのまま残る(tmp_path, source):
    store = M.MemoStore(tmp_path / "memos.jsonl")
    assert store.add("x", source=source).source == source


# --- ★増えた品を覚える -------------------------------------------------------

def test_初めて数えた分はいま手に入れたにしない(tmp_path):
    """⚠⚠ これが無いと、★最初の 1 回で 70 件以上が勇者メモに流れる。"""
    book = PG.Progress(path=tmp_path / "progress.json")
    assert book.note_party(_party([1, 2, 3])) == 3
    assert book.items_ever == {1, 2, 3}
    assert book.take_new_items() == [], "⚠⚠ 前から持っていた分を「いま手に入れた」にした"
    assert book.items_seen is True


def test_2回目からは増えた分だけ返す(tmp_path):
    book = PG.Progress(path=tmp_path / "progress.json")
    book.note_party(_party([1, 2]))
    book.take_new_items()
    assert book.note_party(_party([1, 2, LIGHT_ORB])) == 1
    assert book.take_new_items() == [LIGHT_ORB]
    assert book.take_new_items() == [], "⚠ 受け取ったら空になる"


def test_持ち物が空の更新は数えない(tmp_path):
    """⚠ `state.json` が届く前の空は「見た」に数えない（★次の本物が全部流れる）。"""
    book = PG.Progress(path=tmp_path / "progress.json")
    assert book.note_party([]) == 0
    assert book.items_seen is False
    book.note_party(_party([1]))
    assert book.items_seen is True and book.take_new_items() == []


def test_装備中のbit7を落とす(tmp_path):
    book = PG.Progress(path=tmp_path / "progress.json")
    book.note_party(_party([1]))
    book.note_party(_party([1, LIGHT_ORB | 0x80]))
    assert book.take_new_items() == [LIGHT_ORB]


def test_書いて読み直しても2度流れない(tmp_path):
    """⚠⚠ 起動し直すたびに全部流れると、★勇者メモが埋まる。"""
    path = tmp_path / "progress.json"
    book = PG.Progress(path=path)
    book.note_party(_party([1, 2, LIGHT_ORB]))
    book.save()
    again = PG.Progress.load(path)
    assert again.items_seen is True
    assert again.note_party(_party([1, 2, LIGHT_ORB])) == 0
    assert again.take_new_items() == []


def test_持ち物が空のまま保存しても見たことは残る(tmp_path):
    """⚠⚠ 壊す実験で見つけた穴（★`items_seen` を書き出さないと、ここだけ抜ける）。

    ★枠はあるが全部空（`0xFF`）の場面で保存 → ⚠ `items_ever` が空なので
    「中身があれば見たこと」の当て推量が効きません。★だから旗そのものを書きます。
    """
    path = tmp_path / "progress.json"
    book = PG.Progress(path=path)
    book.note_party(_party([0xFF, 0xFF]))
    assert book.items_ever == set() and book.items_seen is True
    book.save(force=True)

    again = PG.Progress.load(path)
    assert again.items_seen is True, "⚠⚠ 次の起動で「初めて見た」に戻った"
    assert again.note_party(_party([LIGHT_ORB])) == 1
    assert again.take_new_items() == [LIGHT_ORB], "⚠⚠ 最初の 1 個が勇者メモに出ない"


def test_古い記録も見たことがあるとみなす(tmp_path):
    """★`items_seen` が無い記録（★この直しの前のもの）を読んでも流さない。"""
    import json

    path = tmp_path / "progress.json"
    path.write_text(json.dumps({"items_ever": [1, 2, 3]}), encoding="utf-8")
    got = PG.Progress.load(path)
    assert got.items_seen is True, "⚠⚠ 既にある 3 件が「いま手に入れた」になる"


def test_まっさらな記録は見ていないことにする(tmp_path):
    import json

    path = tmp_path / "progress.json"
    path.write_text(json.dumps({"items_ever": []}), encoding="utf-8")
    assert PG.Progress.load(path).items_seen is False


def test_2人の書き手が見たことを消し合わない(tmp_path):
    """⚠ 書く人は 2 人（勇者会議と画面）。★片方が見ていれば見たこと。"""
    path = tmp_path / "progress.json"
    first = PG.Progress(path=path)
    first.note_party(_party([1]))
    first.save()
    second = PG.Progress(path=path)          # ⚠ 読まずに作った（items_seen は False）
    second.note_defeated([5])
    second.save()
    assert PG.Progress.load(path).items_seen is True


# --- ★勇者メモの 1 行 --------------------------------------------------------

def test_メモの文は場所と品名(tmp_path):
    assert PG.memo_text("ひかりのたま", "龍の女王の城") == "龍の女王の城　入手：ひかりのたま"


def test_場所が分からなければ品名だけ():
    assert PG.memo_text("ひかりのたま") == "入手：ひかりのたま"


def test_品名が分からなければ疑問符():
    """⚠ 推測で名前を作らない。"""
    assert PG.memo_text(None, "どこか") == "どこか　入手：？"


# --- ★画面につなぐ -----------------------------------------------------------

class _Book:
    @staticmethod
    def get_location(map_id):
        return type("L", (), {"location_id": "L%d" % int(map_id)})()

    @staticmethod
    def get_location_name(map_id, detailed=False):
        return "龍の女王の城"


class _VM:
    """★`Dq3ViewModel` の判断だけを借りる（⚠ 本物の記録には書かない）。"""

    from dq3.ui.view_model import Dq3ViewModel as _Real

    ITEM_SETTLE_TICKS = _Real.ITEM_SETTLE_TICKS
    note_item_memos = _Real.note_item_memos
    _add_item_memo = _Real._add_item_memo

    def __init__(self) -> None:
        self.location_book = _Book()
        self.added: list = []

    def position(self):
        return (1, 35, 5, 5)

    def add_memo(self, text, **kw):
        got = dict(kw, text=text)
        self.added.append(got)
        return got


@pytest.fixture()
def vm(monkeypatch):
    from dq3.knowledge import rom_names

    monkeypatch.setattr(rom_names, "item",
                        lambda i: "ひかりのたま" if int(i) == LIGHT_ORB else "なにか")
    return _VM()


def _settle(vm, n=None):
    for _ in range(n if n is not None else vm.ITEM_SETTLE_TICKS):
        got = vm.note_item_memos()
        if got:
            return got
    return []


def test_待ってから勇者メモにする(vm):
    """★★ これが直したかったこと（⚠ 竜の女王のひかりのたま）。"""
    assert vm.note_item_memos([LIGHT_ORB]) == [], "⚠ その場では書かない"
    got = _settle(vm)
    assert len(got) == 1
    assert got[0]["text"] == "龍の女王の城　入手：ひかりのたま"
    assert got[0]["source"] == "item"
    assert got[0]["item_id"] == "114"
    assert got[0]["event_id"] == "item:114", "⚠ 同じ品を 2 度書かないための鍵"
    assert got[0]["location_id"] == "L35" and got[0]["map_id"] == 35


def test_宝箱が名乗り出たら書かない(vm):
    """⚠⚠ 宝箱の品まで「入手：…」で二重に出さない。"""
    vm.note_item_memos([LIGHT_ORB])
    vm.note_item_memos([], claimed=["114"])           # ★宝箱のメモが出た（★文字列でも効く）
    assert _settle(vm, vm.ITEM_SETTLE_TICKS + 2) == []
    assert vm.added == []


def test_名乗り出たのが別の品なら書く(vm):
    vm.note_item_memos([LIGHT_ORB])
    vm.note_item_memos([], claimed=["7"])
    assert len(_settle(vm)) == 1


def test_待っている間に同じ品が来ても1件(vm):
    vm.note_item_memos([LIGHT_ORB])
    vm.note_item_memos([LIGHT_ORB])
    got = _settle(vm, vm.ITEM_SETTLE_TICKS + 2)
    assert len(got) == 1, got


def test_何も無ければ何もしない(vm):
    assert vm.note_item_memos() == [] and vm.added == []


def test_世界地図で拾っても場所は付けない(vm, monkeypatch):
    """⚠ 世界地図は「地点」ではない（★場所の名前を作らない）。"""
    monkeypatch.setattr(type(vm), "position", lambda self: (0, 7, 1, 1), raising=False)
    vm.note_item_memos([LIGHT_ORB])
    got = _settle(vm)
    assert got[0]["text"] == "入手：ひかりのたま"
    assert got[0]["map_id"] is None and got[0]["location_id"] is None


def test_名前が引けなくても落ちない(vm, monkeypatch):
    from dq3.knowledge import rom_names

    monkeypatch.setattr(rom_names, "item", lambda i: (_ for _ in ()).throw(RuntimeError("x")))
    vm.note_item_memos([LIGHT_ORB])
    got = _settle(vm)
    assert got[0]["text"].endswith("入手：？")
