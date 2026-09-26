"""「行ってみる？」の台帳（RX3-0310 / 2026-09-20）。

依頼者の指示（2026-09-20）:

```text
会話・発見 → 勇者メモ → 行ってみる？ → 探索・確認 → 完了
```

★ここは **Qt を使わない判断だけ**（⚠ 画面は `test_dq3_go_window.py`）。
"""
from __future__ import annotations

import json

import pytest

from dq3.knowledge import go_list as GL


@pytest.fixture()
def book(tmp_path):
    return GL.GoList(tmp_path / "go-list.json")


# --- ★足す ---------------------------------------------------------------

def test_足すとACTIVEで残る(book):
    got = book.add("その先に小さな村があるらしい。", source_memo_id=703,
                   source_location_id="L1")
    assert got.status == GL.ACTIVE and got.active
    assert got.display_text == "その先に小さな村があるらしい。"
    assert got.source_memo_id == 703 and got.source_location_id == "L1"
    assert got.created_at and got.completed_at is None
    assert got.target_location_id is None, "⚠ 行き先は分からなくてよい（依頼者 §7）"


def test_行き先が分からなくても足せる(book):
    """★依頼者「東の方に町があるらしい」→ `target_location_id = null`。"""
    got = book.add("東の方に町があるらしい")
    assert got is not None and got.target_location_id is None


def test_空文は足さない(book):
    assert book.add("") is None and book.add("   ") is None
    assert book.items == {}


def test_改行とかぎかっこを落とす(book):
    got = book.add("＊「東へ行くと\n  洞窟がある。")
    assert got.display_text == "東へ行くと 洞窟がある。"


def test_長すぎる文は切る(book):
    got = book.add("あ" * 500)
    assert len(got.display_text) == GL.MAX_TEXT


def test_同じ文を二度足さない(book):
    first = book.add("岬の洞窟へ行ってみる")
    again = book.add("岬の洞窟へ行ってみる")
    assert again is first and len(book.items) == 1


def test_終えた文はもう一度足せる(book):
    """⚠ 前に行った所へ、★また行きたくなることがある。"""
    first = book.add("岬の洞窟へ行ってみる")
    book.complete(first.id)
    again = book.add("岬の洞窟へ行ってみる")
    assert again is not first and len(book.items) == 2


def test_idは重ならない(book):
    ids = {book.add("文 %d" % i).id for i in range(5)}
    assert len(ids) == 5


# --- ★終える -------------------------------------------------------------

def test_行ったらDONEになり一覧から消える(book):
    got = book.add("岬の洞窟へ行ってみる")
    assert book.complete(got.id) is True
    assert got.status == GL.DONE and got.completed_at
    assert book.active_items() == []
    assert book.done_items() == [got], "⚠⚠ 消してはいけない（★依頼者 §11）"


def test_二度終えない(book):
    got = book.add("岬の洞窟へ行ってみる")
    book.complete(got.id)
    stamp = got.completed_at
    assert book.complete(got.id) is False
    assert got.completed_at == stamp


def test_知らないidは終えない(book):
    assert book.complete("go9999") is False


def test_間違えて終えたら戻せる(book):
    got = book.add("岬の洞窟へ行ってみる")
    book.complete(got.id)
    assert book.reopen(got.id) is True
    assert got.active and got.completed_at is None
    assert book.reopen(got.id) is False


# --- ★着いたら終える（依頼者 §10）------------------------------------------

def test_行き先の決まっている分は着いたら終わる(book):
    got = book.add("岬の洞窟へ行ってみる", target_location_id="L45")
    done = book.complete_arrival("L45")
    assert done == [got] and got.status == GL.DONE


def test_関係ない場所に着いても終わらない(book):
    """⚠⚠ 依頼者の確認項目「無関係な Location 到達では完了しない」。"""
    got = book.add("岬の洞窟へ行ってみる", target_location_id="L45")
    assert book.complete_arrival("L9") == []
    assert got.active


def test_行き先の無い分は着いても終わらない(book):
    """★依頼者 §7「無理に Location へ紐付けない。手動完了で閉じられればよい」。"""
    got = book.add("東の方に町があるらしい")
    assert book.complete_arrival("L9") == []
    assert book.complete_arrival(None) == []
    assert got.active


def test_同じ行き先が複数あればまとめて終わる(book):
    a = book.add("岬の洞窟へ行ってみる", target_location_id="L45")
    b = book.add("岬の洞窟の奥を見る", target_location_id="L45")
    c = book.add("よその話", target_location_id="L9")
    assert sorted(x.id for x in book.complete_arrival("L45")) == sorted([a.id, b.id])
    assert c.active


def test_終えた分は着いても触らない(book):
    got = book.add("岬の洞窟へ行ってみる", target_location_id="L45")
    book.complete(got.id)
    stamp = got.completed_at
    assert book.complete_arrival("L45") == []
    assert got.completed_at == stamp


def test_行き先は後から結び付けられる(book):
    """★依頼者 §6（⚠ 初版は自動で推し量らない）。"""
    got = book.add("岬の洞窟へ行ってみる")
    assert book.set_target(got.id, "L45") is True
    assert book.set_target(got.id, "L45") is False, "⚠ 変わっていないのに dirty にしない"
    assert book.complete_arrival("L45") == [got]


# --- ★読み書き -------------------------------------------------------------

def test_書いて読み直しても残る(tmp_path):
    path = tmp_path / "go-list.json"
    book = GL.GoList(path)
    a = book.add("岬の洞窟へ行ってみる", source_memo_id=12, source_location_id="L1",
                 target_location_id="L45")
    b = book.add("東の方に町があるらしい")
    book.complete(b.id)
    assert book.save() is True

    again = GL.GoList.load(path)
    assert [x.id for x in again.active_items()] == [a.id]
    got = again.items[a.id]
    assert (got.display_text, got.source_memo_id, got.source_location_id,
            got.target_location_id) == ("岬の洞窟へ行ってみる", 12, "L1", "L45")
    assert again.items[b.id].status == GL.DONE and again.items[b.id].completed_at


def test_変わっていなければ書かない(book):
    book.add("岬の洞窟へ行ってみる")
    assert book.save() is True
    assert book.save() is False
    assert book.save(force=True) is True


def test_ファイルが無ければ空で始まる(tmp_path):
    got = GL.GoList.load(tmp_path / "まだない.json")
    assert got.items == {} and got.active_items() == []


def test_壊れた1件を捨てて残りは読む(tmp_path):
    path = tmp_path / "go-list.json"
    path.write_text(json.dumps({"items": {
        "go0001": {"id": "go0001", "display_text": "生きている", "status": "ACTIVE"},
        "go0002": "⚠ 壊れている",
    }}, ensure_ascii=False), encoding="utf-8")
    got = GL.GoList.load(path)
    assert [x.id for x in got.active_items()] == ["go0001"]
    assert got.failed == 1 and got.last_error


def test_知らない状態はACTIVEに寄せる(tmp_path):
    path = tmp_path / "go-list.json"
    path.write_text(json.dumps({"items": {"go0001": {
        "id": "go0001", "display_text": "x", "status": "なにこれ"}}},
        ensure_ascii=False), encoding="utf-8")
    assert GL.GoList.load(path).items["go0001"].status == GL.ACTIVE


def test_書き先はimportのときに固めない(monkeypatch, tmp_path):
    """⚠⚠ 既定の書き先を定義時に固めると、★隔離先に切り替えても本物に書く（RX3-0215）。

    ⚠ `monkeypatch` で戻します（★検査そのものが隔離先の印を立てているので、消すと本物に戻る）。
    """
    before = GL.default_path()
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    assert GL.default_path() != before, "⚠⚠ 書き先が固まっている"
    assert GL.default_path() == tmp_path / "work" / "dq3-knowledge" / "go-list.json"
