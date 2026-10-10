"""下段の窓の配色 ― ★モンスターの帯も白地（RX3-0112 / 2026-09-07）。

依頼者 2026-09-07: 「RX111 OK だが、モンスター表示領域も白地にしたい」

## ⚠⚠ 絵だけは暗いままです（★これは仕様）

★モンスターの絵は **RGB（透過なし）で背景が黒にベタ塗り**されています（実測）。
⚠ 白い札に直接載せると黒い四角が浮くので、★**絵の枠だけ**暗くしています。

```text
⚠ だめ  黒を透明にする  → ★輪郭の黒まで抜けて、絵に穴があく
★採用  絵の枠だけ暗くする → ⚠ 「ゲームの画面」として見える
```

⚠ 絵そのものは**1 ピクセルも触っていません**。
"""
from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.ui import theme as T                        # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# ----------------------------------------------------------------------
# ★配色そのもの
# ----------------------------------------------------------------------
def test_地は明るく字は濃い():
    """⚠ 色名ではなく**明るさ**で見る（★配色を変えても壊れない）。"""
    for c in T.PAPER_COLOURS:
        assert T.luma(c) > 0.9, c
    for c in T.INK_COLOURS:
        assert T.luma(c) < T.MAX_LUMA, c


def test_絵の枠だけは暗い():
    """⚠⚠ これは**わざと**です（★絵の PNG の背景が黒でベタ塗りのため）。

    ⚠ 「白地なのに暗い色がある」と見えるので、★理由を検査に書いておきます。
    """
    assert T.luma(T.ART_BACK) < 0.2, T.ART_BACK
    assert T.luma(T.ART_BORDER) < 0.3, T.ART_BORDER
    # ★白地の決まり（`MAX_LUMA`）の**外**であることを明示する
    assert T.ART_BACK not in T.INK_COLOURS + T.PAPER_COLOURS


def test_字の色は互いに見分けがつく():
    assert len(set(T.INK_COLOURS)) == len(T.INK_COLOURS)


# ----------------------------------------------------------------------
# ★モンスターの帯
# ----------------------------------------------------------------------
def test_帯の地色は白(app):
    """⚠ 基底（`retroux`）が `#14161a` を掛けているのを上書きできていること。"""
    from dq3.ui.monster_panel import Dq3MonsterStrip

    strip = Dq3MonsterStrip()
    assert T.PAPER in strip.styleSheet(), strip.styleSheet()


def test_札の地色は白で字は濃い(app):
    from dq3.ui.monster_panel import Dq3MonsterCard, Dq3MonsterStrip

    strip = Dq3MonsterStrip()
    strip.set_cards([Dq3MonsterCard(monster_id=1, name="スライム", art=None,
                                    stats=(("HP", "8"),), resist="", special="", legend="")])
    card = strip.card_widgets()[0]                   # ★RX3-0276: 札は段の列の中（⚠ `_row` の子は列）
    assert T.CARD in card.styleSheet(), card.styleSheet()
    from PySide6.QtWidgets import QLabel

    inks = {lbl.styleSheet() for lbl in card.findChildren(QLabel)}
    assert any(T.INK in s for s in inks), inks


def test_帯に黒地の色が残っていない():
    """⚠⚠ 書き換え漏れの歯止め（★黒地のときの色をそのまま探す）。"""
    src = pathlib.Path(
        pathlib.Path(__file__).resolve().parents[1] / "dq3" / "ui" / "monster_panel.py"
    ).read_text(encoding="utf-8")
    old = ("#1c1f26", "#333842", "#6a7080", "#b9c0cc", "#c9a86a", "#d8dce4", "#14161a")
    code = [ln for ln in src.splitlines()
            if not ln.lstrip().startswith("#")
            for bad in old if bad in ln]
    assert not code, "⚠ 黒地のときの色が残っている: %s" % code


def test_色を2か所に書いていない():
    """⚠ ログの窓と帯は別ファイルだが、★同じ窓に並ぶ（配色は `theme` が正本）。"""
    from dq3.ui import battle_window as BW

    assert BW.PAPER is T.PAPER
    assert BW.BORDER is T.BORDER
    assert BW.INK is T.INK
    assert BW.PLAIN_COLOR is T.MUTED


# ----------------------------------------------------------------------
# ⚠ 絵の前提（★崩れたら配色の判断も変わる）
# ----------------------------------------------------------------------
ART_DIR = pathlib.Path(__file__).resolve().parents[1] / "work" / "cache" / "dq3-monster-art"


@pytest.mark.skipif(not ART_DIR.exists(), reason="★絵がまだ作られていません")
def test_絵は透過を持たない():
    """★この前提が「絵の枠だけ暗くする」判断の根拠です。

    ⚠ 透過つきになったら、★白地に直接載せられます（＝ この検査が赤くなる）。
    """
    import struct

    got = sorted(ART_DIR.glob("*.png"))[:5]
    if not got:
        pytest.skip("★絵がまだ作られていません")
    for f in got:
        raw = f.read_bytes()
        _w, _h, _depth, ctype = struct.unpack(">IIBB", raw[16:26])
        assert ctype == 2, "⚠ %s の colour type が %d（★2 = RGB のはず）" % (f.name, ctype)
        assert b"tRNS" not in raw, "⚠ %s に透過が付いた（★白地へ直接載せられます）" % f.name
