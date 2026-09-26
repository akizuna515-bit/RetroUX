"""実機の画面を PNG に起こす（2026-08-25）。

★★ この道具が生まれた経緯 ★★

Auto 戦闘 v0 が「9,000 フレーム 1 マスも動かない」で詰まった。
⚠ ログをいくら眺めても分からなかったのに、★画面を 1 枚描いたら**1 分で**分かった
（フィールドでコマンド窓が開きっぱなしだった）。

★依頼者が居なくても実機の画面を確かめられる。**行き詰まったらまずこれ**。
"""

from __future__ import annotations

import pathlib

import pytest

from dq3rom import render

from dq3_states import BATTLE, SCROLLED, pick

ROOT = pathlib.Path(__file__).resolve().parents[1]
#: ⚠⚠ 番号で名指ししない（RX3-0028 / 2026-08-31）。★中身で選ぶ。
STATES = pick(BATTLE)[:1] + pick(SCROLLED)[:1]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# --- セーブステート不要 -------------------------------------------------

def test_材料が足りなければ描かない():
    """⚠ 中途半端な絵を返さない（★真っ黒な PNG は「動いた」に見えてしまう）。"""
    with pytest.raises(render.RenderError):
        render.render(bytes(1024), bytes(16), bytes(32))       # CHR が足りない
    with pytest.raises(render.RenderError):
        render.render(bytes(1024), bytes(0x2000), bytes(4))    # パレットが足りない
    with pytest.raises(render.RenderError):
        render.render(bytes(10), bytes(0x2000), bytes(32))     # 画面が足りない


def test_probeの書き出しを読める():
    text = "\n".join([
        "=== なにか ===",
        "@snapshot f=100",
        "@NT", "AABB",
        "@CHR", "CCDD",
        "@PAL", "EEFF",
        "@snapshot f=200",
        "@NT", "0011",
    ])
    snaps = render.parse_probe_dump(text)
    assert len(snaps) == 2
    assert snaps[0]["NT"] == "AABB" and snaps[0]["CHR"] == "CCDD"
    assert snaps[1]["NT"] == "0011"


def test_全部同じ色でも描ける():
    """★極端な入力でも落ちないこと。"""
    px, w, h = render.render(bytes(1024), bytes(0x2000), bytes(32))
    assert (w, h) == (256, 240)
    assert len(px) == w * h * 3


# --- セーブステート時 ---------------------------------------------------

_HAVE = [p for p in STATES if p.exists()]
needs_state = pytest.mark.skipif(not _HAVE, reason="セーブステートが無い")


@needs_state
@pytest.mark.parametrize("path", _HAVE, ids=[p.name for p in _HAVE])
def test_実機の画面を描ける(tmp_path, path):
    """★★ 要。セーブステートだけで、実機の画面がそのまま出ること。"""
    from retroux.core.bgmap import savestate as ss

    px, w, h = render.from_savestate(ss.load(path))
    assert (w, h) == (256, 240)

    # ⚠ 「描けた」を「真っ黒でない」で確かめる（★成功の目印を形だけにしない）
    colours = {tuple(px[i:i + 3]) for i in range(0, len(px), 3)}
    assert len(colours) >= 4, f"⚠ 色が {len(colours)} 種しかない（描けていない疑い）"

    out = render.write_png(tmp_path / "x.png", px, w, h)
    assert out.read_bytes()[:8] == PNG_MAGIC
    assert out.stat().st_size > 500


@needs_state
def test_戦闘画面と町の画面は違う絵になる(tmp_path):
    """⚠ 同じ絵を返していないか（★「動いた」の見せかけを防ぐ）。"""
    from retroux.core.bgmap import savestate as ss

    if len(_HAVE) < 2:
        pytest.skip("セーブステートが 2 つ要る")
    a, _, _ = render.from_savestate(ss.load(_HAVE[0]))
    b, _, _ = render.from_savestate(ss.load(_HAVE[1]))
    assert bytes(a) != bytes(b)


# --- ★スクロールとスプライト（2026-08-26 追加）-------------------------

def _state(name: str):
    from retroux.core.bgmap import savestate as ss

    path = ROOT / "tools" / "fceux" / "fcs" / name
    if not path.exists():
        pytest.skip(f"セーブステートが無い: {name}")
    return ss.load(path)


def test_スクロールを反映すると面1枚とは違う絵になる():
    """★★ それまでは面 1 枚をそのまま描いていた。

    ⚠ スクロールしている場面では**実機と違う絵**が出ていたのに、
    「PNG が出た」だけで正しく見えていた。

    ⚠⚠ 2026-09-02: ここも `fc9` を名指ししていた。★fc9 を撮り直した（RX3-0052 の後始末）
      瞬間に落ちた。→ スクロールしているセーブを**種類**で選ぶ（RX3-0028 と同じ直し）。
    """
    state = _state(pick(SCROLLED)[0].name)
    fixed, _, _ = render.from_savestate(state, sprites=False)
    one_page, _, _ = render.from_savestate(state, raw=True)
    assert bytes(fixed) != bytes(one_page), "⚠ 直っていない（★同じ絵が出ている）"


@pytest.mark.xfail(reason="⚠ 基準にしていたセーブが失われた（RX-0135）。★観点は docs/audit/tests-waiting-savestates.md", strict=False)
def test_スクロールが0なら面1枚と同じ絵になる():
    """★上の検査が「何を変えても違う」と言っているだけでないことを示す。

    ⚠ 戦闘中はスクロール (0,0)。★このときは一致するはず。

    ⚠⚠ 2026-08-31: ここは `fc6` と名指ししていた。
      ★依頼者がそのセーブを撮り直した瞬間に落ちた（RX3-0028）。
    """
    from dq3rom import ppu

    state = _state(pick(BATTLE)[0].name)
    scroll = ppu.scroll_of(state.chunks)
    assert (scroll.x, scroll.y, scroll.nametable) == (0, 0, 0), scroll
    fixed, _, _ = render.from_savestate(state, sprites=False)
    one_page, _, _ = render.from_savestate(state, raw=True)
    assert bytes(fixed) == bytes(one_page)


def test_人物が描かれる():
    """⚠ 背景だけだと「誰がどこにいるか」が写らない。

    ⚠ 2026-09-02: `fc9` の名指しをやめた（★戦闘画面で撮り直したら人物が 1 枚も無かった）。
    """
    state = _state(pick(SCROLLED)[0].name)
    without, w, h = render.from_savestate(state, sprites=False)
    with_, _, _ = render.from_savestate(state, sprites=True)
    assert bytes(without) != bytes(with_), "⚠ スプライトが 1 枚も描かれていない"


def test_主人公の升に人物が描かれる():
    """★主人公はいつも画面の升 (8,7)。⚠ そこが変わっていなければ描けていない。"""
    from dq3rom import viewport

    state = _state("DQ3_J.fc9")
    without, w, _ = render.from_savestate(state, sprites=False)
    with_, _, _ = render.from_savestate(state, sprites=True)
    tx, ty = viewport.HERO_CELL_X * 16, viewport.HERO_CELL_Y * 16
    changed = 0
    for y in range(ty, ty + 16):
        for x in range(tx, tx + 16):
            p = (y * w + x) * 3
            if without[p:p + 3] != with_[p:p + 3]:
                changed += 1
    assert changed > 20, f"⚠ 主人公の升で変わった点が {changed} しかない"
