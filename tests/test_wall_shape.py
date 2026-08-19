"""壁向き補正（2026-08-02 / `$DE29`-`$DE9B` の写し）。

★★ **実コードから取りました。観測辞書ではありません。**

⚠ 観測から作った規則表は別のマップへ渡りませんでした
（`$40` の規則を `$3D` に当てて非単調 0/4）。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.wall_shape import (
    CORNER_SHAPE, DIAGONAL_DX, DIAGONAL_DY, NEIGHBOUR_BIT, NEIGHBOUR_DX,
    NEIGHBOUR_DY, SHAPE_TABLE, WALL_VALUES, wall_shape,
)
from retroux.core.bgmap.rom_tiles import load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")


def _at(prg, cpu, n):
    return list(prg[0x1C000 + (cpu - 0xC000):0x1C000 + (cpu - 0xC000) + n])


def _signed(values):
    return [v - 256 if v & 0x80 else v for v in values]


@needs_rom
def test_表がROMと一致する():
    """★★ **写し間違いをここで止める**（今日は手写しで何度も外した）。"""
    prg = load_prg(ROM)
    assert _signed(_at(prg, 0xDEC8, 4)) == list(NEIGHBOUR_DX)
    assert _signed(_at(prg, 0xDECC, 4)) == list(NEIGHBOUR_DY)
    assert _at(prg, 0xDED0, 4) == list(NEIGHBOUR_BIT)
    assert _at(prg, 0xDEA0, 16) == list(SHAPE_TABLE)
    assert _signed(_at(prg, 0xDEB0, 8)) == list(DIAGONAL_DX)
    assert _signed(_at(prg, 0xDEB8, 8)) == list(DIAGONAL_DY)
    assert _at(prg, 0xDEC0, 8) == list(CORNER_SHAPE)


def test_壁とみなす値はコードどおり():
    """★`CMP #$04` / `#$09` / `#$0D` の3つ。"""
    assert WALL_VALUES == {0x04, 0x09, 0x0D}


def test_中心が壁でなければ補正しない():
    """⚠ `DE2C: CMP #$04 / BNE` — 壁以外はそのまま返す。"""
    assert wall_shape(lambda x, y: 0x07, 5, 5) == 0x07
    assert wall_shape(lambda x, y: 0x00, 5, 5) == 0x00


def test_まわりが全部壁なら補正しない():
    """★ビットが 0 → `$DEA0[0]` は `$FF` → 補正なし。"""
    assert wall_shape(lambda x, y: 0x04, 5, 5) == 0x04


def test_斜めが壁でなければ形を捨てて04に戻る():
    """★★ `DE90: BNE $DE99` → `LDA #$04`（2026-08-11 に訂正）★★

    ⚠⚠ 2026-08-02 の写しは、ここで**形（0-7）をそのまま返して**いました。
      その値で変換表を引くと 1→草原・2→砂漠…と**別の地形の絵**になります。

    ⚠ 前のテストは「上だけ床」で試していたので、`$DEA0[1]` がたまたま
      `4` で、**間違ったままでも緑**でした（2026-08-11 に気づいた）。
      ★形が 4 以外になる向きでも確かめます。
    """
    for bits, opened in ((0x01, (5, 4)), (0x02, (6, 5)),
                         (0x04, (5, 6)), (0x08, (4, 5))):
        shape = SHAPE_TABLE[bits]
        diag = (5 + DIAGONAL_DX[shape], 5 + DIAGONAL_DY[shape])

        def value_at(x, y, opened=opened, diag=diag):
            if (x, y) in (opened, diag):
                return 0x00          # ★開いている向きと、対応する斜めが床
            return 0x04
        assert wall_shape(value_at, 5, 5) == 0x04, f"形 ${shape:02X}"


def test_つながる値は3種類とも同じ扱い():
    """★`$04` / `$09` / `$0D` はどれも「つながっている」。"""
    for wall in (0x04, 0x09, 0x0D):
        def value_at(x, y, w=wall):
            return w if (x, y) != (5, 5) else 0x04
        assert wall_shape(value_at, 5, 5) == 0x04, f"${wall:02X}"


def test_斜めを見て角になる():
    """★★ 2段目（`DE7A`-`DE97`）。

    形が `$15` 未満のとき、対応する斜めが壁なら角の形へ差し替える。
    """
    # ★上だけ開く -> 形 4。斜めは DIAGONAL[4] = (+1,+1)
    def value_at(x, y):
        if (x, y) == (5, 4):
            return 0x00              # ★上は床
        return 0x04                  # ★他は全部壁（斜めも壁）
    got = wall_shape(value_at, 5, 5)
    assert got == CORNER_SHAPE[SHAPE_TABLE[0x01]]


def test_出てくる値は04か14から1Bだけ():
    """★★ `$DEA0` の中身は `$FF` か 0-7 なので、`CMP #$15 / BCS` は
    **この表では通りません**。★結果は `$04` か角の形しかありません。

    ⚠ ここが破れたら、変換表（32 件）の外を引いていないか疑うこと。
    """
    import itertools

    allowed = {0x04} | set(CORNER_SHAPE)
    for around in itertools.product((0x00, 0x04, 0x09, 0x0D), repeat=8):
        near = dict(zip(
            [(5 + dx, 5 + dy) for dx, dy in
             ((0, -1), (1, 0), (0, 1), (-1, 0),
              (-1, 1), (-1, -1), (1, 1), (1, -1))], around))

        def value_at(x, y, near=near):
            return 0x04 if (x, y) == (5, 5) else near.get((x, y), 0x00)
        assert wall_shape(value_at, 5, 5) in allowed


# --- ⚠ まだ絵が合わないことを隠さない --------------------------------

def test_絵の対応はまだ合っていない():
    """⚠⚠ **未達を隠さない**（2026-08-02）。

    補正の値そのものは取れています（単調セルが 98% 合う）が、
    その値で変換表を引くと**非単調セルが 0%** です。

    ```
    map $3D  単調 667/681 97.9%   ⚠ 非単調   0/374  0.0%
    map $40  単調 648/660 98.2%   ⚠ 非単調   0/1102 0.0%
    ```

    ★考えられること:
      1. `$DE9B: STA $0C` の後にさらに変換がある
      2. `$DED4` の戻り値が私の `>>5` と違う
      3. 象限のずれを掛ける順番が違う

    ★合うようになったらこのテストを消して前へ進めること。
    """
    import retroux.core.bgmap as bgmap

    assert not hasattr(bgmap, "metatile_for_position"), (
        "★絵まで通ったのなら、この歯止めを外して前へ進めること")
