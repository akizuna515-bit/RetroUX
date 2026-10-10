"""画面はスクロールを反映して組み立てる（RX3-0016 / 2026-08-26）。

★★ なぜこの検査が要るのか ★★

ネームテーブルを **1 枚そのまま**画面だと思って読んでいた。⚠ そのせいで
**会話の窓が 1 つも取れていなかった**（`docs/research/260825_dq3-text-capture.md` §6-2 で
「未検証」としていたもの）。

窓は 30 行で折り返す。⚠ 折り返した窓は「下辺が無い」ように見えるので、
★エラーにならず**黙って消える**。いちばん見つけにくい壊れ方だった。
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from dq3rom import ppu, window
from retroux.core.text import Charset
from retroux.core.bgmap import savestate as ss

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()

from dq3_states import (CONVERSATION, WRAPPED, all_states, one,
                        one_of)


def _chunks(name: str):
    path = FCS / name
    if not path.exists():
        pytest.skip("セーブステートが無い: %s" % name)
    return ss.load(path).chunks


@pytest.fixture(scope="module")
def charset() -> Charset:
    return Charset(json.loads(PROFILE.read_text(encoding="utf-8"))["text"])


def test_スクロールの組み立て方が実機の実測と合う():
    """★`dq3_scroll_probe.lua` が実機で採った値と突き合わせる。

        実機 2026-08-25: DQ3_J.fc7 → scroll=(64,80) $2000=0x91 → 面 1

    ⚠⚠ **そのセーブは失われました**（2026-08-31 / `RX3-0028`）。
      ★依頼者が会話中のセーブを撮るときに `fc7` が上書きされ、
      ⚠ いま**面 1 を映しているセーブが 1 本もありません**。

    ★残せるのは「実測値をどう組み立てるか」の式です。
      ⚠ これは単位検査であって、実機の証拠ではありません（★区別すること）。
      面 1 のセーブを撮り直してもらえれば、突き合わせを戻せます。
    """
    got = ppu.Scroll(x=8 * 8 + 0, y=10 * 8 + 0, nametable=1)
    assert (got.x, got.y, got.nametable) == (64, 80, 1)
    assert got.tile_x == 8 and got.tile_y == 10


def test_いまあるセーブでもスクロールが読める():
    """★式が動くことは、いまあるセーブでも見る（⚠ 落ちないこと）。"""
    for path in all_states():
        s = ppu.scroll_of(_chunks(path.name))
        assert 0 <= s.x < 512 and 0 <= s.y < 480, (path.name, s)
        assert s.nametable in (0, 1, 2, 3), (path.name, s)


def test_ミラーリングは縦():
    """★面が横に並ぶ（MMC1 制御レジスタ = 0x0E → 下位 2 ビット = 2）。"""
    for path in all_states():
        assert ppu.mirroring_of(_chunks(path.name)) == ppu.VERTICAL, path.name


def test_組み立てた画面は32x30():
    screen = ppu.screen_of(_chunks(one(CONVERSATION).name))
    assert len(screen) == 32 * 30


def test_折り返した会話窓が取れる(charset):
    """⚠ これが取れなかったのが、テキスト取得基盤の最後の穴だった。

    ★**折り返していて、かつ会話**のセーブを使う（⚠ 番号で名指ししない）。
      下の行が y=0,1 へ回り込んでいるので、1 面だけ読むと消える。

    ## ⚠⚠ 2026-08-31: `WRAPPED` だけで選んで落ちました

      ★折り返しているのが「パーティの状態の窓」でも `WRAPPED` は立ちます。
      ⚠ 依頼者がセーブを撮り直したら、そちらが選ばれて `＊「` が無くなりました。
    """
    chunks = _chunks(one_of(WRAPPED, CONVERSATION).name)
    screen = ppu.screen_of(chunks)
    wins = window.find_windows(screen)
    texts = [window.text_of(w, screen, charset)[0] for w in wins]
    joined = "\n".join(texts)
    # ⚠⚠ **台詞そのものを当てにしない**（★セーブを撮り直すと変わる）。
    #   ★DQ3 の会話は `＊「` で始まる（⚠ 飾りであって、原作の文ではない）。
    assert "＊「" in joined, joined
    body = joined[joined.index("＊「") + 2:]
    assert len(body.replace(" ", "")) >= 8, "⚠ 中身が取れていない: %r" % joined


def test_折り返しを無視すると会話窓は消える(charset):
    """★上の検査が「たまたま通った」のでないことを示す。

    ⚠ ネームテーブルを 1 枚そのまま読むと、会話窓は**見つからない**。
    """
    chunks = _chunks(one_of(WRAPPED, CONVERSATION).name)
    raw = chunks["NTAR"]
    found = []
    for base in (0, 0x400):
        for w in window.find_windows(raw, base=base):
            found.append(window.text_of(w, raw, charset, base=base)[0])
    assert not any("ようこそ" in t for t in found), found


def test_濁点だけの行は残らない(charset):
    """⚠ 濁点は 1 行上のマスにある。★下の行へ合成済みなので、行としては残さない。

    ## ⚠⚠ 2026-09-07（RX3-0108）: この検査は **1 度すり抜けました**

      ★もとは `line.strip("゛゜ ")` だけを見ていました。⚠ 半濁点の番号が
      違っていたせいで印が `<6B>` になり、★`strip` で消えないので
      **「印だけの行」に見えなくなった**のです。
      → ⚠ 印の行は `<XX>` も含めて空になること、を見ます。
    """
    chunks = _chunks(one(CONVERSATION).name)
    screen = ppu.screen_of(chunks)
    for w in window.find_windows(screen):
        text, _ = window.text_of(w, screen, charset)
        for line in text.split("\n"):
            assert line.strip("゛゜ ") or not line.strip(), repr(line)
            # ⚠ 読めないタイルが印の代わりに残っていないこと
            assert not re.fullmatch(r"(?:<[0-9A-F]{2}>|[゛゜ ])+", line), repr(line)
