"""撮った画面から「窓の番号と画面が一致したか」を答える（RX3-0124 ① / 2026-09-19）。

⚠⚠ **実機の走行は高い**ので、★判定は合成した画面でここに固定します。
★実機で撮れたら、同じ関数に通すだけで答えが出ます。

```text
窓 $1D   「はい」「いいえ」   ★選択肢
窓 $16   「かいにきた」       ★店
窓 $17   「どくのちりょう」   ★教会
```
"""
from __future__ import annotations

import io
import json

import pytest

from dq3.testing import choice_shots as CS
from dq3rom import screen as SC

COLS, ROWS = SC.COLUMNS, SC.ROWS


@pytest.fixture(scope="module")
def cs():
    return CS.charset()


#: ★濁った字 → 素の字（⚠ `dq3rom/screen.py` の表を逆に引く）
_PLAIN = {v: k for k, v in SC._VOICED.items()}
_PLAIN.update({v: k for k, v in SC._SEMI_VOICED.items()})


def _tiles(cs, rows) -> str:
    """★語を置いた画面（⚠ 文字表を逆に引く / 原作の文は持たない）。

    ⚠⚠ **濁点は 1 行上の別タイル**です（RX3-0108 / memory）。
    ★`ど` のような字は、素の `と` を置いて**上の升に印**を置きます。
    """
    back = {}
    for code, ch in cs.table.items():
        back.setdefault(ch, code - SC.PATTERN_BASE)
    got = bytearray(COLS * ROWS)
    for y, x, word in rows:
        for i, ch in enumerate(word):
            mark = None
            if ch not in back and ch in _PLAIN:
                mark = (SC.HANDAKUTEN if ch in SC._SEMI_VOICED.values()
                        else SC.DAKUTEN)
                ch = _PLAIN[ch]
            assert ch in back, "⚠ 文字表に無い字: %r" % ch
            got[y * COLS + x + i] = back[ch]
            if mark is not None:
                assert y > 0, "⚠ 1 行目には濁点を置けない"
                got[(y - 1) * COLS + x + i] = mark - SC.PATTERN_BASE
    return bytes(got).hex()


def _row(cs, wid, rows, frame=100):
    return {"f": frame, "id": wid, "delay": 20, "screen": _tiles(cs, rows)}


def _write(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + chr(10))


# --- ★読む -------------------------------------------------------------

def test_1行1枚で読める(tmp_path, cs):
    p = tmp_path / "shots.jsonl"
    _write(p, [_row(cs, 0x1D, [(10, 5, "はい"), (12, 5, "いいえ")])])
    got = CS.load(p)
    assert len(got) == 1 and got[0]["id"] == 0x1D


def test_壊れた行があっても残りは読む(tmp_path, cs):
    """⚠ 1 行が読めないだけで全部を失わない。"""
    p = tmp_path / "shots.jsonl"
    body = json.dumps(_row(cs, 0x1D, [(10, 5, "はい"), (12, 5, "いいえ")]),
                      ensure_ascii=False)
    io.open(p, "w", encoding="utf-8", newline="").write(
        "これは JSON ではない" + chr(10) + body + chr(10))
    got = CS.load(p)
    assert len(got) == 1 and got[0]["broken"] == 1


def test_記録が無ければ空(tmp_path):
    assert CS.load(tmp_path / "ない.jsonl") == []


def test_画面が取れなかった行は空(cs):
    """⚠ probe は `?no-host` のような印を書くことがある（★数字に化けさせない）。"""
    assert CS.screen_of({"screen": "?no-host"}) == b""
    assert CS.text_of({"screen": "?nil"}, cs) == ""


# --- ★判定 -------------------------------------------------------------

def test_選択肢の窓は2語そろって一致(cs):
    row = _row(cs, 0x1D, [(10, 5, "はい"), (12, 5, "いいえ")])
    wid, hit, full = CS.matched(row, cs)
    assert wid == 0x1D and set(hit) == {"はい", "いいえ"} and full


def test_片方だけなら一致にしない(cs):
    """⚠⚠ 「はい」だけなら、★別の窓かもしれない（RX3-0273 の教訓）。"""
    row = _row(cs, 0x1D, [(10, 5, "はい")])
    _wid, hit, full = CS.matched(row, cs)
    assert hit == ("はい",) and not full


def test_番号と画面が食い違えば一致にしない(cs):
    """⚠ 窓 $16（店）と言いながら「はい／いいえ」が写っている。"""
    row = _row(cs, 0x16, [(10, 5, "はい"), (12, 5, "いいえ")])
    _wid, hit, full = CS.matched(row, cs)
    assert hit == () and not full


def test_知らない窓は判定しない(cs):
    row = _row(cs, 0x04, [(10, 5, "はい")])
    wid, hit, full = CS.matched(row, cs)
    assert wid == 0x04 and hit == () and not full


def test_店と教会の窓も見る(cs):
    for wid, word in ((0x16, "かいにきた"), (0x17, "どくのちりょう")):
        _w, _h, full = CS.matched(_row(cs, wid, [(10, 4, word)]), cs)
        assert full, wid


# --- ★まとめ -----------------------------------------------------------

def test_3つそろえば合格(cs):
    rows = [_row(cs, 0x1D, [(10, 5, "はい"), (12, 5, "いいえ")]),
            _row(cs, 0x16, [(10, 4, "かいにきた")]),
            _row(cs, 0x17, [(10, 4, "どくのちりょう")])]
    got = CS.verdict(rows, cs)
    assert got["ok"] and got["confirmed"] == [0x16, 0x17, 0x1D]
    assert got["missing"] == []


def test_足りない窓を黙らせない(cs):
    """⚠⚠ 「0 枚」を素通りさせない（★この計画で何度も踏んだ形）。"""
    got = CS.verdict([_row(cs, 0x1D, [(10, 5, "はい"), (12, 5, "いいえ")])], cs)
    assert not got["ok"] and got["missing"] == [0x16, 0x17]


def test_1枚も無くても答えを出す(cs):
    got = CS.verdict([], cs)
    assert got["shots"] == 0 and not got["ok"]
    assert got["missing"] == [0x16, 0x17, 0x1D]


def test_人が読む1枚に原作の文を出さない(cs):
    """⚠ 語の有無だけ（★台詞を写さない / `docs/00-project-policy.md`）。"""
    rows = [_row(cs, 0x1D, [(10, 5, "はい"), (12, 5, "いいえ"),
                            (2, 2, "おまえにこの")])]
    text = CS.report(rows, cs)
    assert "はい" in text and "いいえ" in text
    assert "おまえにこの" not in text, "⚠⚠ 画面の文をそのまま出している"
