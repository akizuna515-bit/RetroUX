"""「しらべる」で取った隠し道具を勇者メモへ（RX3-0281 / 2026-09-18）。

⚠⚠ 依頼者（2026-09-18）「いのちのきのみを見つける前（save1）でまちから隠しアイテム手に入れたが、勇者メモに追加されない」。
★宝箱は残る（RX3-0261）のに、しらべるの升は**別の表**なので拾えていなかった。

```text
印    WRAM $608E〜 の同じ並びの **26 バイト目**（★通し番号 200〜207）
升    dq3rom/search_spots.py（★map / x / y / 品番）
文    「テドンの小部屋1　しらべる：いのちのきのみ を入手」
```
"""
from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.knowledge import hidden_items as HI                # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


def _bits(*serials: int, size: int = 26) -> str:
    """★通し番号を立てた `chest_bits`（★MSB から / `chest_flags` と同じ並び）。"""
    raw = bytearray(26)
    for n in serials:
        raw[n >> 3] |= 1 << (7 - (n & 7))
    return bytes(raw[:size]).hex()          # ⚠ 古い Lua（25 バイト）も作れるように


def test_印の読み方():
    assert HI.taken_serials(_bits()) == []
    assert HI.taken_serials(_bits(205, 207)) == [205, 207]
    assert HI.taken_serials(_bits(5, 192)) == [], "⚠ 宝箱（0〜192）は隠し道具に混ぜない"
    # ⚠⚠ 25 バイトしか来ない古い Lua は「読めない」（★「取っていない」と混ぜない）
    assert HI.taken_serials(_bits(205, size=25)) is None
    assert HI.taken_serials(None) is None and HI.taken_serials("zz") is None


def test_初めて見たときに立っている分は流さない(tmp_path):
    book = HI.HiddenItemBook(tmp_path / "hidden.json")
    assert book.update(_bits(206, 207)) == 3               # ★2 件 ＋「見た」ことの印
    assert book.take_new() == [], "⚠⚠ 前から取ってあった分をメモに流した"
    assert all(r.get("taken_before_seen") for r in book.records.values())


def test_新しく立ったものだけ1件ずつ流す(tmp_path):
    book = HI.HiddenItemBook(tmp_path / "hidden.json")
    book.update(_bits(206, 207))
    book.take_new()
    assert book.update(_bits(205, 206, 207)) == 1
    got = book.take_new()
    assert [r["serial"] for r in got] == [205]
    assert "taken_before_seen" not in got[0]
    assert book.take_new() == [], "⚠ 受け取ったら空（★1 つの升は 1 回だけ）"


def test_セーブを読み直しても重複しない(tmp_path):
    p = tmp_path / "hidden.json"
    book = HI.HiddenItemBook(p)
    book.update(_bits(206))
    book.update(_bits(205, 206))
    assert [r["serial"] for r in book.take_new()] == [205]
    book.save(force=True)
    # ⚠ 古いセーブを読んで印が 0 に戻る → ★記録は消さない
    assert book.update(_bits()) == 0
    again = HI.HiddenItemBook.load(p)                        # ★起動し直し
    assert again.initialized and set(again.records) == {"205", "206"}
    assert again.update(_bits(205, 206)) == 0 and again.take_new() == [], "⚠⚠ 取り直しで 2 度目のメモが出た"


def test_壊れた記録は数える(tmp_path):
    got = HI.HiddenItemBook.from_dict({"initialized": True, "hidden_items": {"205": {"serial": 205}, "x": 1}})
    assert set(got.records) == {"205"} and got.failed == 1 and got.last_error


def test_文の形は宝箱と同じ():
    assert HI.memo_text("いのちのきのみ", "テドンの小部屋1") == "テドンの小部屋1　しらべる：いのちのきのみ を入手"
    assert HI.memo_text("いのちのきのみ") == "しらべる：いのちのきのみ を入手"
    assert HI.memo_text(None, "どこか") == "どこか　しらべる：？ を入手", "⚠ 名前を推測しない"


def test_画面がメモへ流す所につないである():
    """⚠ 作っても**呼ばれていなければ**出ない（★宝箱の隣で呼ぶ / RX3-0281）。

    ⚠⚠ 「文字列がある」だけの弱い検査だが、★動かす検査（下）と組で見る（挙動は `note_hidden_memos` が持つ）。
    """
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "note_hidden_memos()" in src, "⚠⚠ 画面から呼んでいない（★作っただけになる）"
    body = src[src.index("note_chest_memos()"):]
    assert body.index("note_hidden_memos()") < 600, "⚠ 宝箱の隣で呼んでいない（★片方だけ忘れる形）"


@needs_rom
def test_ROMの升と印が対応している():
    """★通し番号 200〜207 の 8 升（⚠ 依頼者の実機で 205 = テドンの小部屋1 が立った / RX3-0012）。"""
    got = HI.spots()
    assert sorted(got) == list(range(200, 208)), sorted(got)
    assert (got[205].map_id, got[205].x, got[205].y) == (133, 4, 5)


@needs_rom
def test_画面は新しく取った分をメモに足す(tmp_path):
    """★`view_model` → 勇者メモ（⚠ 置き場は検査の一時フォルダ / 本物の `work/` に書かない）。"""
    from dq3.ui.view_model import Dq3ViewModel

    # ⚠⚠ `memo_path` を渡さないと**本物の勇者メモ**へ書く（★2026-09-18 に 1 行書いてしまい、消した）
    vm = Dq3ViewModel(state_path=tmp_path / "state.json", seen_path=tmp_path / "seen.json",
                      knowledge_path=tmp_path / "knowledge.json", memo_path=tmp_path / "memos.jsonl")
    vm._raw = lambda: {"chest_bits": _bits(206, 207)}
    assert vm.note_hidden_memos() == [], "⚠ 初めて見た分は流さない"
    vm._raw = lambda: {"chest_bits": _bits(205, 206, 207)}
    made = vm.note_hidden_memos()
    assert len(made) == 1, made
    assert "しらべる：いのちのきのみ を入手" in made[0].text, made[0].text
    assert made[0].event_id == "hidden:205" and made[0].map_id == 133
    assert vm.note_hidden_memos() == [], "⚠⚠ 同じ升で 2 度出た"
