"""画面を文字に起こす（RX3-0016 / 2026-08-25）。

★★ これが効くと何が変わるか ★★

- **Auto 戦闘 v0** … 「たたかう が画面に出ているか」で戦闘コマンド待ちを判定できる。
  ⚠ RAM の解析を 1 つも足さずに済む（指示書 §2.4「ROM 解析を追加しない」）
- **会話メモ** … 圧縮されたメッセージを解かずに、表示された文章をそのまま読める。
  ⚠ しかも「原作テキストを成果物に焼かない」方針と衝突しない

⚠ DQ3 の濁点は**対象文字の 1 行上**に置かれる。★1 行だけ見ても読めない。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from dq3rom import screen
from retroux.core.text import Charset

from dq3_states import BATTLE_COMMAND, pick

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
#: ★依頼者が遊んで作った戦闘中のセーブステート
#: ★★ **戦闘中のセーブを「中身」で選ぶ**（RX3-0028 / 2026-08-31）。
#:
#:   ⚠⚠ 以前は `fc2` / `fc6` と番号で名指ししていました。
#:     ★依頼者がセーブ 5〜9 を撮り直した瞬間に落ちます（⚠ 実際に落ちた）。
STATES = pick(BATTLE_COMMAND)


@pytest.fixture(scope="module")
def charset() -> Charset:
    return Charset(json.loads(PROFILE.read_text(encoding="utf-8"))["text"])


# --- セーブステート不要 -------------------------------------------------

def test_濁点は1行上から合成する(charset):
    """★DQ3 固有。⚠ `retroux/core/text.py` は変えずに、こちら側で合成する。"""
    nt = bytearray(1024)
    # y=1 に「にける」、y=0 の同じ列に濁点
    for x, code in enumerate((0x120, 0x113, 0x133), start=5):   # に け る
        nt[32 + x] = code - screen.PATTERN_BASE
    nt[0 + 6] = screen.DAKUTEN - screen.PATTERN_BASE            # け の上
    lines = screen.read_screen(nt, charset)
    assert "にげる" in lines[1].text


def test_ソの濁点はゾ(charset):
    """⚠ RX3-0216: 「ソ」が濁点の表に無く、アニマルゾンビ を「アニマルソンビ」と覚えていた。"""
    nt = bytearray(1024)
    nt[32 + 5] = 0x14B - screen.PATTERN_BASE                      # ソ
    nt[0 + 5] = screen.DAKUTEN - screen.PATTERN_BASE              # ソ の上に濁点
    assert "ゾ" in screen.read_screen(nt, charset)[1].text


def test_英字のタイルはCHRの字の形どおり(charset):
    """⚠ RX3-0227（2026-09-13 依頼者「りりょくのつえの勇者メモがMPと表示すべきがLMと表示される」）。

    ★CHR の字の形（依頼者のセーブ 2 本で同じ）: 0x163 = L / 0x164 = M / 0x165 = P / 0x166 = V / 0x167 = X。
    ⚠ 表が 1 つずれていて（0x164 = L / 0x165 = M …）、「MP」が「LM」と読まれていた。
    """
    nt = bytearray(1024)
    for x, code in enumerate((0x163, 0x164, 0x165, 0x166, 0x167), start=5):
        nt[32 + x] = code - screen.PATTERN_BASE
    assert "LMPVX" in screen.read_screen(nt, charset)[1].text
    nt = bytearray(1024)
    for x, code in enumerate((0x164, 0x165), start=5):         # ★「MP」（りりょくのつえ の話）
        nt[32 + x] = code - screen.PATTERN_BASE
    assert "MP" in screen.read_screen(nt, charset)[1].text


def test_読めないタイルは黙って捨てない(charset):
    nt = bytearray(1024)
    nt[0] = 0xFF                       # ⚠ 表に無い
    lines = screen.read_screen(nt, charset)
    assert lines[0].unknown == (screen.PATTERN_BASE + 0xFF,)


def test_カーソルが無ければNoneを返す(charset):
    """⚠ 推測で 0 行目を返さない（★「不明なら入力しない」の土台）。"""
    assert screen.cursor_row(bytearray(1024)) is None


# --- セーブステート時 ---------------------------------------------------

_HAVE = [p for p in STATES if p.exists()]
needs_state = pytest.mark.skipif(
    not _HAVE, reason="戦闘中のセーブステートが無い（tools/fceux/fcs/）")


@needs_state
@pytest.mark.parametrize("path", _HAVE, ids=[p.name for p in _HAVE])
def test_戦闘コマンドの窓が読める(charset, path):
    """★★ 要。実機の画面から、コマンドがそのまま読めること。

    ## ⚠⚠ 2026-08-31 訂正: 「4 項目」ではありませんでした

      ★ここは `たたかう / にげる / ぼうぎょ / どうぐ` の 4 つを求めていました。
      ⚠ 実際は**使えるコマンドだけ**が並びます（★3〜4 項目）。

      ```text
      fc2  たたかう にげる ぼうぎょ どうぐ
      fc6  たたかう じゅもん にげる どうぐ   ⚠ 呪文を覚えて ぼうぎょ が消えた
      ```

      ⚠ 依頼者が遊んで撮り直した瞬間に落ちました（★`RX3-0020` の知見が
        検査に反映されていなかった）。
    """
    from retroux.core.bgmap import savestate as ss

    state = ss.load(path)
    assert state.byte(0x62) != 0, "⚠ このセーブステートは戦闘中ではない"
    nt = state.chunks["NTAR"]
    lines = screen.read_screen(nt, charset)
    text = " ".join(ln.stripped for ln in lines)
    # ★どの並びでも必ず出るもの
    for item in ("たたかう", "にげる"):
        assert item in text, f"⚠ 『{item}』が読めていない"
    # ⚠ 残りは**その時に使えるもの**。★3〜4 項目に収まること
    known = ("たたかう", "にげる", "ぼうぎょ", "どうぐ", "じゅもん")
    found = [w for w in known if w in text]
    assert 3 <= len(found) <= 4, (
        "⚠⚠ コマンドが %d 項目に見えます（★3〜4 のはず）: %r" % (len(found), found))


@needs_state
@pytest.mark.parametrize("path", _HAVE, ids=[p.name for p in _HAVE])
def test_カーソルはたたかうの行にある(charset, path):
    """★これが Auto v0 の土台。⚠ カーソル行が取れないなら入力しない。

    ## ⚠⚠ 2026-08-31: **1 枚に写っていないことがある**

      ★下位メニューの ▶ は点滅します。⚠ 消えているフレームで撮った
      セーブでは `cursor_row` が `None` になります（★実際に落ちた）。

      → ⚠ 「必ず在る」ではなく「**在るなら たたかう の行**」を見ます。
        ★1 枚も写っていなければ、この検査は空回りなので、そちらを断ります
        （`test_カーソルが写ったセーブが1つはある`）。
    """
    from retroux.core.bgmap import savestate as ss

    nt = ss.load(path).chunks["NTAR"]
    lines = screen.read_screen(nt, charset)
    rows = [ln.row for ln in screen.find(lines, "たたかう")]
    assert rows, "⚠ 『たたかう』が見つからない"
    got = screen.cursor_row(nt)
    assert got in (None, rows[0]), (
        "⚠⚠ カーソルが たたかう の行にない: %s（たたかう は %d 行目）"
        % (got, rows[0]))


@needs_state
def test_カーソルが写ったセーブが1つはある(charset):
    """⚠⚠ 全部 `None` だと、上の検査は**何も見ていません**。"""
    from retroux.core.bgmap import savestate as ss

    seen = [p.name for p in _HAVE
            if screen.cursor_row(ss.load(p).chunks["NTAR"]) is not None]
    assert seen, (
        "⚠⚠ ▶ が写っているセーブが 1 つもありません（★点滅の消えた側ばかり）。"
        " 上の検査は空回りしています: %r" % [p.name for p in _HAVE])
