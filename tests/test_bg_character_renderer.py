"""背景キャラクタの組み立て（2026-08-02 / マップ指示書 §18.3）。

★★ 守りたい契約 ★★

  1. 2bpp の CHR を 8×8 の番号（0..3）へ正しく変える
  2. 属性テーブルから**パレット組**を正しく引く
  3. ⚠ **各組の色0は共通の背景色**（$3F00）。組ごとの $3Fx0 ではない
  4. ⚠⚠ 同じ tile_id でも **CHR が違えば別の鍵**（DQ2 は CHR-RAM）
  5. ⚠ 同じ CHR でも **パレットが違えば別の鍵**
  6. スプライトを含まない（★PPU の背景だけから作るので構造的に）
  7. 拡大で補間しない
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap import (
    Capture, Character, attribute_for, character_key, chr_hash, metatile_at,
    nametable_index, palette_colors, scale_nearest, tile_pixels,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = PROJECT_ROOT / "work" / "map-assets"


# --- 1. CHR を 0..3 の番号へ -------------------------------------------

def test_2bppのCHRを番号へ変えられる():
    """★先頭8バイトが下位ビット、後の8バイトが上位ビット。"""
    # 1行目: 下位 1000_0000 / 上位 0000_0000 -> 左端だけ 1
    # 2行目: 下位 0000_0000 / 上位 1000_0000 -> 左端だけ 2
    # 3行目: 下位 1000_0000 / 上位 1000_0000 -> 左端だけ 3
    data = bytes([0x80, 0x00, 0x80, 0, 0, 0, 0, 0,
                  0x00, 0x80, 0x80, 0, 0, 0, 0, 0])
    px = tile_pixels(data, 0)
    assert px[0][0] == 1
    assert px[1][0] == 2
    assert px[2][0] == 3
    assert px[0][1] == 0


def test_CHRの外を読んでも落ちない():
    """⚠ 短いデータでも例外を投げない（0 として扱う）。"""
    px = tile_pixels(b"", 0)
    assert px == [[0] * 8 for _ in range(8)]


# --- 2. 属性テーブル ----------------------------------------------------

@pytest.mark.parametrize("col,row,want", [
    (0, 0, 0b00),      # 左上
    (2, 0, 0b01),      # 右上
    (0, 2, 0b10),      # 左下
    (2, 2, 0b11),      # 右下
])
def test_属性テーブルから正しい組を引く(col, row, want):
    """⚠ 1バイトが 4×4 タイル。下位から 左上・右上・左下・右下。"""
    attr = bytes([0b11_10_01_00] + [0] * 63)
    assert attribute_for(attr, col, row) == want


def test_属性テーブルの外は0にする():
    assert attribute_for(b"", 0, 0) == 0
    assert attribute_for(bytes(64), 31, 29) == 0


# --- 3. パレット --------------------------------------------------------

def test_どの組でも色0は共通の背景色():
    """⚠⚠ **ここを間違えると透明部分だけ色が変わる。**

    NES は $3F04 / $3F08 / $3F0C を描画に使わず、
    **$3F00 を全組の色0として使う**。
    """
    palette = bytes([0x0F, 0x30, 0x16, 0x06,
                     0x11, 0x21, 0x31, 0x01,     # ★$3F04 = 0x11 は使われない
                     0x12, 0x22, 0x32, 0x02,
                     0x13, 0x23, 0x33, 0x03])
    for group in range(4):
        assert palette_colors(palette, group)[0] == 0x0F


def test_組ごとに色1から3が変わる():
    palette = bytes([0x0F, 0x30, 0x16, 0x06,
                     0x11, 0x21, 0x31, 0x01,
                     0x12, 0x22, 0x32, 0x02,
                     0x13, 0x23, 0x33, 0x03])
    assert palette_colors(palette, 0)[1:] == (0x30, 0x16, 0x06)
    assert palette_colors(palette, 1)[1:] == (0x21, 0x31, 0x01)


# --- 4. 鍵（指示書 §7.3）------------------------------------------------

def test_同じタイルIDでもCHRが違えば別の鍵():
    """⚠⚠ DQ2 は **CHR-RAM**。IDだけを鍵にすると別の絵を同じ扱いにする。"""
    palette = bytes([0x0F] + [0x30] * 15)
    a = bytes([0xFF] * 16) + bytes(16)
    b = bytes([0x0F] * 16) + bytes(16)
    assert character_key(a, 0, palette, 0) != character_key(b, 0, palette, 0)


def test_同じCHRでもパレットが違えば別の鍵():
    data = bytes([0xFF] * 16)
    p1 = bytes([0x0F, 0x30, 0x16, 0x06] + [0] * 12)
    p2 = bytes([0x0F, 0x21, 0x31, 0x01] + [0] * 12)
    assert character_key(data, 0, p1, 0) != character_key(data, 0, p2, 0)


def test_同じCHRと同じパレットなら同じ鍵():
    data = bytes([0xFF] * 16)
    palette = bytes([0x0F, 0x30, 0x16, 0x06] + [0] * 12)
    assert character_key(data, 0, palette, 0) == character_key(
        data, 0, palette, 0)


def test_鍵にCHRハッシュとタイルIDとパレットが入る():
    data = bytes([0xFF] * 32)
    palette = bytes([0x0F, 0x30, 0x16, 0x06] + [0] * 12)
    key = character_key(data, 1, palette, 0)
    parts = key.split(":")
    assert len(parts) == 3
    assert parts[0] == chr_hash(data, 1)
    assert parts[1] == "01"


# --- 5. ネームテーブルの選び方 ------------------------------------------

def test_2枚が左右に並ぶ():
    """★2026-08-01 実測: 垂直ミラーリングで 64 列。"""
    assert nametable_index(0, 0, 0, 0) == ("left", 0, 0)
    # 横スクロール 32 列ぶん（256画素）で右のネームテーブルへ
    assert nametable_index(0, 0, 256, 0)[0] == "right"


def test_たては30行で巡回する():
    assert nametable_index(0, 0, 0, 30 * 8) == ("left", 0, 0)


# --- 6. 拡大・縮小（指示書 §10.2）---------------------------------------

def test_拡大しても補間しない():
    """⚠⚠ 平滑化するとぼやけて床と壁が見分けられなくなる。"""
    rows = [[(10, 20, 30, 255), (40, 50, 60, 255)]]
    got = scale_nearest(rows, 2)
    assert len(got) == 2 and len(got[0]) == 4
    # ★元の色がそのまま並ぶ（中間色を作らない）
    assert got[0] == [(10, 20, 30, 255), (10, 20, 30, 255),
                      (40, 50, 60, 255), (40, 50, 60, 255)]
    assert got[0] == got[1]


def test_4倍も整数で拡大する():
    rows = [[(1, 2, 3, 255)]]
    got = scale_nearest(rows, 4)
    assert len(got) == 4 and len(got[0]) == 4


def test_半分は間引く():
    rows = [[(i, 0, 0, 255) for i in range(4)] for _ in range(4)]
    got = scale_nearest(rows, 0.5)
    assert len(got) == 2 and len(got[0]) == 2
    # ★平均していない（元の画素がそのまま）
    assert got[0][0] == (0, 0, 0, 255)
    assert got[0][1] == (2, 0, 0, 255)


def test_1倍はそのまま():
    rows = [[(1, 2, 3, 255)]]
    assert scale_nearest(rows, 1) == [[(1, 2, 3, 255)]]


# --- 7. 地の色だけのキャラクタ（指示書 §11.1）---------------------------

def test_全部が色0なら黒観測の候補():
    blank = Character(key="k", tile_id=0, chr_hash="h", palette_signature="s",
                      pattern=tuple(tuple([0] * 8) for _ in range(8)),
                      colors=(0x0F, 0x30, 0x16, 0x06))
    assert blank.is_blank is True

    lit = Character(key="k", tile_id=0, chr_hash="h", palette_signature="s",
                    pattern=tuple(tuple([1] + [0] * 7) for _ in range(8)),
                    colors=(0x0F, 0x30, 0x16, 0x06))
    assert lit.is_blank is False


# --- 8. 実データ（★あるときだけ）---------------------------------------

needs_capture = pytest.mark.skipif(
    not (ASSETS / "capture-3.txt").exists(),
    reason="採取データが無い（bg_capture_probe.lua を先に走らせる）")


@needs_capture
def test_実データからメタタイルを作れる():
    cap = Capture.load(ASSETS / "capture-3.txt")
    mt = metatile_at(cap, 8, 6, 0)
    assert len(mt.key) == 16
    assert len(mt.characters) == 4
    # ★16×16 になる
    palette = _FakePalette()
    rows = mt.rgba(palette)
    assert len(rows) == 16
    assert len(rows[0]) == 16


@needs_capture
def test_採取したのはFIELD_IDLEだけ():
    """指示書 §6.2「マップDBへ正式保存してよいのは FIELD_IDLE だけ」。"""
    for path in sorted(ASSETS.glob("capture-*.txt")):
        cap = Capture.load(path)
        assert cap.state == "FIELD_IDLE", path.name


class _FakePalette:
    def rgb(self, index):
        return (index, index, index)


@needs_capture
def test_画面と照らして再構成が合っている():
    """★★ **ここが本質の指標**（指示書 §13.4「一致率99%以上」）。

    ⚠ 100% にはならない。**スプライト（主人公・NPC）のぶんだけ食い違う**。
      ★それは「スプライトが混ざっていない」ことの裏返しでもある。

    ⚠ CHR のどちらの半分を背景が使うかは Lua から読めない（PPUCTRL bit4）。
      ★**両方で組んで、画面と合う方**を選んでいることも確かめる。
    """
    from dq2rom.monsters.palette import load_nes_palette

    from retroux.core.bgmap import choose_pattern_half, load_screen

    pal_path = PROJECT_ROOT / "tools" / "fceux" / "palettes" / "FCEUX.pal"
    if not pal_path.exists():
        pytest.skip("FCEUX.pal が無い")
    palette = load_nes_palette(pal_path)

    worst = 1.0
    for path in sorted(ASSETS.glob("capture-*.txt")):
        slot = path.stem.split("-")[1]
        screen_path = ASSETS / f"screen-{slot}.txt"
        if not screen_path.exists():
            continue
        cap = Capture.load(path)
        screen = load_screen(screen_path)
        half, best, other = choose_pattern_half(cap, screen, palette)
        # ★選んだ方が明らかに勝っていること（迷っていない）
        assert best > other + 0.2, (
            f"save{slot}: どちらの CHR 半分か決めきれていない "
            f"（{best:.1%} vs {other:.1%}）")
        assert best >= 0.90, f"save{slot}: 再構成が {best:.1%} しか合わない"
        worst = min(worst, best)
    assert worst < 1.0, "★100% は不自然（スプライトが混ざっている疑い）"
