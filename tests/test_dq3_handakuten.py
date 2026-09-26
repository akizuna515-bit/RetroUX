"""半濁点のマスが本文へ `<6B>` として漏れる（RX3-0108 / 2026-09-07）。

## ⚠⚠ 実機で出ていた形

依頼者の聞き込みで、`work/dq3-knowledge/npc-conversations.json` に
**そのまま**残っていた 1 件:

```text
＊「あなたが あの ゆうかんだったオルテガの むすこさんか？<6B>゛  ゛おちちうえは りっはでしたぞ！
                                                        ~~~~        ~~~~~~ ⚠ りっぱ にならない
```

★原因は 1 つでした。⚠ `dq3rom/screen.py` の `HANDAKUTEN` が **`0x169`** のままで、
実際の半濁点は **`0x16B`** です（★profile が 2026-09-03 に訂正済みだった）。

```text
① 合成が起きない   は の上の印が半濁点と認識されない → りっは のまま
② 印が本文へ漏れる 0x16B は文字表に無い → `<6B>` として残り、
                   ⚠ 「印だけの行を落とす」判定まですり抜ける
```

## ★この検査が守るもの

⚠ 「`<6B>` が出ない」だけでは弱い（★印を全部捨てても通る）。
★だから **`ぱ` になること**と**印が消えること**を、⚠ 同じ 1 枚で見ます。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3rom import screen as sc
from dq3rom import window as win

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"

COLUMNS = sc.COLUMNS


@pytest.fixture(scope="module")
def charset():
    from dq3.knowledge import conversation as cv

    got = cv._charset()
    assert got is not None, "⚠ 文字表が読めない（★この検査は空回り）"
    return got


@pytest.fixture(scope="module")
def rev(charset):
    """★文字 → タイル番号（⚠ 同じ絵が複数あるので最初の 1 つ）。"""
    out: dict[str, int] = {}
    for code, ch in charset.table.items():
        out.setdefault(ch, code - sc.PATTERN_BASE)
    return out


def _screen_with_window(lines, marks, rev):
    """★窓を 1 つ置いた 32x30 の画面を作る。

    `lines`  … 窓の中の行（★印を除いた素の字）
    `marks`  … `{(行, 列): タイル番号}`。⚠ **その行そのもの**へ印を置く
                （★DQ3 は印を 1 行上に描くので、直したい字の 1 行上を指す）
    """
    blank = rev.get(" ", 0)
    scr = [0] * (COLUMNS * sc.ROWS)
    inner = max(len(ln) for ln in lines)
    x0, y0 = 2, 18
    bw, bh = inner + 2, len(lines) + 2

    def put(x, y, v):
        scr[y * COLUMNS + x] = v

    put(x0, y0, win.TOP_LEFT)
    put(x0 + bw - 1, y0, win.TOP_RIGHT)
    put(x0, y0 + bh - 1, win.BOTTOM_LEFT)
    put(x0 + bw - 1, y0 + bh - 1, win.BOTTOM_RIGHT)
    for i in range(1, bw - 1):
        put(x0 + i, y0, win.EDGE_TOP)
        put(x0 + i, y0 + bh - 1, win.EDGE_BOTTOM)
    for j in range(1, bh - 1):
        put(x0, y0 + j, win.EDGE_LEFT)
        put(x0 + bw - 1, y0 + j, win.EDGE_RIGHT)
    for j, line in enumerate(lines):
        for i in range(inner):
            ch = line[i] if i < len(line) else " "
            put(x0 + 1 + i, y0 + 1 + j, rev.get(ch, blank))
    for (j, i), tile in marks.items():
        put(x0 + 1 + i, y0 + 1 + j, tile)
    return bytes(scr)


#: ★実機で出ていた並び。⚠ 印の行（1 行目）は **下の行**（2 行目）に効く
#:   `おちちうえは りっはでしたぞ！`
#:      0123456789...
#:   ★9 = は（→ ぱ）/ 10 = て（→ で）/ 13 = そ（→ ぞ）
REAL_LINES = ["                            ", "おちちうえは りっはてしたそ！"]
REAL_MARKS_INDEX = {9: "handaku", 10: "daku", 13: "daku"}


def _real_screen(rev):
    marks = {}
    for col, kind in REAL_MARKS_INDEX.items():
        tile = (sc.HANDAKUTEN if kind == "handaku" else sc.DAKUTEN) - sc.PATTERN_BASE
        marks[(0, col)] = tile
    return _screen_with_window(REAL_LINES, marks, rev)


def _only_window_text(raw, charset):
    boxes = win.find_windows(raw)
    assert len(boxes) == 1, "⚠ 窓が %d 個（★組み立てを間違えている）" % len(boxes)
    return win.text_of(boxes[0], raw, charset)


def test_半濁点が合成されて本文に印が残らない(charset, rev):
    """★これが依頼者の会話そのもの（⚠ りっぱ / で / ぞ が揃うこと）。"""
    text, unknown = _only_window_text(_real_screen(rev), charset)
    assert "りっぱ" in text, "⚠ 半濁点が合成されていない: %r" % text
    assert "でしたぞ" in text, "⚠ 濁点が合成されていない: %r" % text
    assert "<6B>" not in text, "⚠⚠ 印が本文に漏れた: %r" % text
    assert "゛" not in text and "゜" not in text, repr(text)
    assert not unknown, "⚠ 読めないタイルが残った: %s" % [hex(u) for u in unknown]


def test_印だけの行は行として残らない(charset, rev):
    """⚠ 「印だけの行を落とす」判定を、★半濁点でも効かせる。

    ⚠⚠ もとの実装は `line.strip("゛゜ ")` で見ていたので、
    ★`<6B>` が入った瞬間に**行が残りました**（＝ この検査の本体）。
    """
    text, _ = _only_window_text(_real_screen(rev), charset)
    assert text.split("\n")[0].strip(), "⚠ 先頭に空行が残った: %r" % text
    assert len(text.split("\n")) == 1, "⚠ 印の行が残っている: %r" % text


def test_番号を戻すと本文に6Bが出る(charset, rev, monkeypatch):
    """⚠⚠ **壊して赤くなること**を確かめる（★「0 件」は通っていないだけのことがある）。

    ★`HANDAKUTEN` を昔の `0x169` に戻すと、⚠ 症状が 2 つとも再現します。
    """
    # ⚠⚠ **画面は先に作る**（★`_real_screen` は `sc.HANDAKUTEN` を見てタイルを置くので、
    #   先に壊すと「置いたタイルも一緒にずれて」壊した気になれません）。
    raw = _real_screen(rev)
    monkeypatch.setattr(sc, "HANDAKUTEN", 0x169)
    monkeypatch.setattr(sc, "MARK_TILES", (sc.DAKUTEN, 0x169))
    text, unknown = _only_window_text(raw, charset)
    assert "<6B>" in text, "⚠ 壊しても再現しない（★この検査は空回り）: %r" % text
    assert "りっは" in text, repr(text)
    assert 0x16B in unknown


def test_文字表の番号と定数がずれていない():
    """⚠⚠ 2026-09-03 の訂正が **ソースへ届いていなかった**（★それがこの WI）。"""
    spec = json.loads(PROFILE.read_text(encoding="utf-8"))
    enc = spec["tables"]["names"]["encoding"]
    assert int(enc["dakuten_tile"], 16) == sc.DAKUTEN
    assert int(enc["handakuten_tile"], 16) == sc.HANDAKUTEN


def test_印は文字表に載せない(charset):
    """★印を「文字」として持たせない（⚠ 持たせると本文へ出る道が復活する）。

    ⚠ `0x16A` は歴史的に `゛` として載っています。★載っていても
    `is_mark_tile` が先に拾うので本文には出ませんが、
    ⚠ **半濁点のほうは載せないでください**（★載せると `゜` が本文に出ます）。
    """
    assert charset.table.get(sc.HANDAKUTEN) is None
    assert sc.is_mark_tile(sc.DAKUTEN) and sc.is_mark_tile(sc.HANDAKUTEN)
    assert not sc.is_mark_tile(0x169)          # ⚠ 未確定の番号を印にしない


def test_画面まるごと読む側でも印は文字にならない(charset, rev):
    """★`read_screen`（戦闘の判定などが使う）でも同じ守り。"""
    raw = _real_screen(rev)
    lines = sc.read_screen(raw, charset)
    body = [ln for ln in lines if "りっ" in ln.text]
    assert len(body) == 1, repr([ln.text for ln in lines])
    assert "りっぱでしたぞ" in body[0].text, repr(body[0].text)
    # ⚠ 印の行は空白だけになる（★窓の枠は別物なので、内側だけを見る）
    mark_row = lines[body[0].row - 1]
    inside = mark_row.text.replace("␣", " ")[3:3 + len(REAL_LINES[0])]
    assert not inside.strip(), repr(mark_row.text)
    assert "゛" not in mark_row.text and "゜" not in mark_row.text
