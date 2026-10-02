"""`location-names.csv` の name を場所の既定の名前にする（RX3-0439 / 2026-09-27 依頼者）。

```text
人が画面で付けた名前（manual）   ★いちばん強い
location-names.csv の name       ★既定（⚠ review_status は見ない）
ROM の地名 / 会話で覚えた名前 / 仮名
```

⚠ 表は**渡されたときだけ**読む（★検査が本物の表の名前を拾わない）。
"""
from __future__ import annotations

from dq3.knowledge import location_book as LB
from dq3.knowledge import location_master as LM


def _table(tmp_path, rows: str):
    path = tmp_path / "location-names.csv"
    path.write_bytes(("location_id,map_id,name,kind,review_status,evidence,notes\n" + rows)
                     .encode("utf-8"))
    return path


def _book(tmp_path, names_path=None, rom=None, heard=None):
    return LB.LocationBook(LM.LocationMaster({}), tmp_path / "book.json",
                           rom or (lambda map_id: None), heard or (lambda map_id: None),
                           names_path=names_path)


def test_表の名前が仮名の代わりに出る(tmp_path):
    names = _table(tmp_path, "L41,41,ためしのほこら,,DRAFT,,\n")
    book = _book(tmp_path, names)
    book.enter(41)
    assert book.get_location_name(41) == "ためしのほこら"
    assert book.locations["L41"].name_source == LB.TABLE
    assert book.locations["L41"].known, "⚠ 表の名前は正式な名前として扱う"


def test_表を渡さなければ今までどおり仮名(tmp_path):
    _table(tmp_path, "L41,41,ためしのほこら,,DRAFT,,\n")
    book = _book(tmp_path)
    book.enter(41)
    assert book.get_location_name(41) != "ためしのほこら"


def test_表の名前はROMと会話より強い(tmp_path):
    names = _table(tmp_path, "L9,9,ひょうのなまえ,,DRAFT,,\n")
    book = _book(tmp_path, names, rom=lambda m: "ろむのなまえ", heard=lambda m: ("かいわのなまえ", ""))
    book.enter(9)
    assert book.get_location_name(9) == "ひょうのなまえ"
    assert not book.promote("L9", "かいわのなまえ", source="dialogue")


def test_画面で付けた名前は表より強い(tmp_path):
    names = _table(tmp_path, "L9,9,ひょうのなまえ,,DRAFT,,\n")
    book = _book(tmp_path, names)
    book.enter(9)
    book.rename("L9", "わたしの名前")
    assert book.get_location_name(9) == "わたしの名前"
    assert book.locations["L9"].name_source == "manual"


def test_命名の窓の既定の文字は表の名前(tmp_path):
    """★命名の窓は `display_name` を既定にする（`map_window._ask_name`）→ 表の名前になる。"""
    names = _table(tmp_path, "L41,41,ためしのほこら,,DRAFT,,\n")
    book = _book(tmp_path, names)
    book.enter(41)
    assert book.get_location(41).display_name == "ためしのほこら"


def test_表を書き換えたら読み直す(tmp_path):
    import os

    names = _table(tmp_path, "L41,41,まえのなまえ,,DRAFT,,\n")
    book = _book(tmp_path, names)
    book.enter(41)
    assert book.get_location_name(41) == "まえのなまえ"
    names.write_bytes("location_id,map_id,name,kind,review_status,evidence,notes\n"
                      "L41,41,あとのなまえ,,DRAFT,,\n".encode("utf-8"))
    stat = names.stat()
    os.utime(names, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))   # ⚠ 同じ時刻にしない
    assert book.get_location_name(41) == "あとのなまえ"


def test_表から名前が消えたら表の名前も消す(tmp_path):
    import os

    names = _table(tmp_path, "L41,41,けすなまえ,,DRAFT,,\n")
    book = _book(tmp_path, names)
    book.enter(41)
    names.write_bytes("location_id,map_id,name,kind,review_status,evidence,notes\n"
                      "L41,41,,,DRAFT,,\n".encode("utf-8"))
    stat = names.stat()
    os.utime(names, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    assert book.get_location_name(41) != "けすなまえ"
    assert book.locations["L41"].name_source != LB.TABLE
