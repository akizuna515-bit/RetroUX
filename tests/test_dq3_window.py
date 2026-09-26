"""枠つき窓を見つけて中身だけ取る（RX3-0016 / 2026-08-25）。

★★ なぜ窓ごとに分けるのか ★★

依頼者の指示書（`docs/research/dq3-text-capture-brief.md`）§2 の考え方。
DQ3 は意味のある文字を**ほとんど枠の中**に出すので、枠を見つけて中だけ取れば
地形や飾りを拾わずに済む。

⚠ そしてもう 1 つ、実際に踏んだ理由がある。
**呪文の一覧が開くと窓が 2 つになり、カーソルも 2 つ出る**。
★画面を 1 枚の板として見ていたので「どちらの窓のカーソルか」が分からなかった。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from dq3rom import window
from retroux.core.text import Charset

from dq3_states import BATTLE_COMMAND, pick

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
#: ★★ **戦闘中のセーブを「中身」で選ぶ**（RX3-0028 / 2026-08-31）。
#:
#:   ⚠⚠ 以前は `fc2` / `fc6` と番号で名指ししていました。
#:     ★依頼者がセーブ 5〜9 を撮り直した瞬間に落ちます（⚠ 実際に落ちた）。
STATES = pick(BATTLE_COMMAND)


@pytest.fixture(scope="module")
def charset() -> Charset:
    return Charset(json.loads(PROFILE.read_text(encoding="utf-8"))["text"])


def _blank():
    return bytearray(1024)


def _draw(nt, x, y, w, h):
    """枠だけの窓を描く。"""
    nt[y * 32 + x] = window.TOP_LEFT
    nt[y * 32 + x + w - 1] = window.TOP_RIGHT
    for k in range(1, w - 1):
        nt[y * 32 + x + k] = window.EDGE_TOP
    for yy in range(y + 1, y + h - 1):
        nt[yy * 32 + x] = window.EDGE_LEFT
        nt[yy * 32 + x + w - 1] = window.EDGE_RIGHT
    nt[(y + h - 1) * 32 + x] = window.BOTTOM_LEFT
    nt[(y + h - 1) * 32 + x + w - 1] = window.BOTTOM_RIGHT
    for k in range(1, w - 1):
        nt[(y + h - 1) * 32 + x + k] = window.EDGE_BOTTOM


# --- セーブステート不要 -------------------------------------------------

def test_窓を見つけて大きさが分かる():
    nt = _blank()
    _draw(nt, 4, 6, 10, 5)
    got = window.find_windows(nt)
    assert len(got) == 1
    w = got[0]
    assert (w.x, w.y, w.width, w.height) == (4, 6, 10, 5)
    assert w.key == "04_06_10_05"


def test_窓が複数あっても別々に取れる():
    """⚠ これが要。★呪文の一覧は独立した窓として出る。"""
    nt = _blank()
    _draw(nt, 2, 2, 8, 4)
    _draw(nt, 14, 2, 10, 6)
    got = window.find_windows(nt)
    assert len(got) == 2
    assert {w.key for w in got} == {"02_02_08_04", "14_02_10_06"}


def test_枠は中身に含めない():
    nt = _blank()
    _draw(nt, 0, 0, 5, 4)
    nt[1 * 32 + 1] = 0x11          # 中身
    w = window.find_windows(nt)[0]
    assert w.tiles == ((0x11, 0, 0), (0, 0, 0))


def test_窓が無ければ空を返す():
    """⚠ 例外にしない（★窓が無い画面もある）。"""
    assert window.find_windows(_blank()) == []


def test_読めないタイルはrawが分かる形で残す(charset):
    """★指示書 §6。⚠ データを捨てない。"""
    nt = _blank()
    _draw(nt, 0, 0, 5, 4)
    nt[1 * 32 + 1] = 0xEE          # ⚠ 表に無い
    w = window.find_windows(nt)[0]
    text, unknown = window.text_of(w, nt, charset)
    assert "<EE>" in text
    assert unknown == [0x1EE]


def test_指紋は中身が変われば変わる():
    """★同じ窓で文章が更新されたことを見分ける（指示書 §8）。"""
    nt = _blank()
    _draw(nt, 0, 0, 6, 4)
    nt[1 * 32 + 1] = 0x11
    a = window.find_windows(nt)[0].digest
    nt[1 * 32 + 1] = 0x12
    b = window.find_windows(nt)[0].digest
    assert a != b


# --- セーブステート時 ---------------------------------------------------

_HAVE = [p for p in STATES if p.exists()]


@pytest.mark.skipif(not _HAVE, reason="セーブステートが無い")
@pytest.mark.parametrize("path", _HAVE, ids=[p.name for p in _HAVE])
def test_実機の戦闘画面で窓が3つ取れる(charset, path):
    """★★ 要。パーティ状態 / コマンド / 敵 の 3 つ。"""
    from retroux.core.bgmap import savestate as ss

    nt = ss.load(path).chunks["NTAR"]
    got = window.find_windows(nt)
    assert len(got) == 3, [w.key for w in got]

    texts = [window.text_of(w, nt, charset)[0] for w in got]
    joined = " ".join(texts)
    assert "たたかう" in joined
    assert "スライム" in joined
    # ⚠ 枠のタイルが中身に混ざっていないこと
    for w in got:
        for row in w.tiles:
            assert window.TOP_LEFT not in row
            assert window.BOTTOM_RIGHT not in row
