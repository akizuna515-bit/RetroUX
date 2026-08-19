"""撮った画面から敵1体を切り出す（2026-07-27〜28）。

★★ 座標も分割の規則も**実測で決めた**（推測していない）★★
  `research/probes/archived/analyze_art.py` / `research/probes/archived/analyze_art2.py` で実写を測った結果:
    画面 256x224 / 背景は純黒 / パーティ枠 y 8..70 / メッセージ枠 y 137..
    -> **敵の帯は y 71..136**

★守りたい契約:
  1. 帯の外（パーティ枠・メッセージ枠）を巻き込まない
  2. 複数体が並んでいても**1体だけ**切り出す（体の間の黒い列で分ける）
  3. ⚠ 複数種のときは **かたまりの数と体数が合うときだけ** 対応づける
     — 合わないまま保存すると**違う敵の絵を図鑑に載せる**
  4. 画面の大きさが違ったら**何もしない**（実測した座標が当てにならない）
  5. ファイル名から敵の並びを読む（`$0162` は画面の並び順どおり）
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from retroux.core.art.trim import (  # noqa: E402
    BACKGROUND, BAND_BOTTOM, BAND_TOP, EXPECT_H, EXPECT_W, MIN_GAP,
    column_blobs, find_sprite, parse_ids,
)

WHITE = (255, 255, 255)


def blank(w: int = EXPECT_W, h: int = EXPECT_H):
    return [[BACKGROUND for _ in range(w)] for _ in range(h)]


def draw(px, x0, x1, y0, y1, color=WHITE):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            px[y][x] = color


# --- 5. ファイル名から並びを読む --------------------------------------


@pytest.mark.parametrize("stem,expected", [
    ("0C", [0x0C]),
    ("12-06-06", [0x12, 0x06, 0x06]),
    ("0f", [0x0F]),
    ("", []),
    ("zz", []),
    ("0C-", []),
    ("0C-123", []),
])
def test_parse_ids(stem, expected):
    assert parse_ids(stem) == expected


# --- 1. 帯の外を巻き込まない ------------------------------------------


def test_ignores_party_window_above_the_band():
    """★パーティ枠（y 8..70）を敵と間違えないこと。

    実測では**3枚すべてで同じ画素**だった＝必ず写っている。
    帯を固定していなければ、毎回これを切り出してしまう。
    """
    px = blank()
    draw(px, 33, 174, 8, 70)              # パーティ枠
    draw(px, 110, 140, 100, 127)          # 敵
    got = find_sprite(px, EXPECT_W, EXPECT_H)
    assert got.ok
    assert got.top >= BAND_TOP, f"パーティ枠を巻き込んだ（top={got.top}）"


def test_ignores_message_window_below_the_band():
    """★メッセージ枠（y 137..）を巻き込まないこと。"""
    px = blank()
    draw(px, 110, 140, 100, 127)          # 敵
    draw(px, 16, 231, 137, 214)           # メッセージ枠
    got = find_sprite(px, EXPECT_W, EXPECT_H)
    assert got.ok
    assert got.top + got.height - 1 <= BAND_BOTTOM, "メッセージ枠を巻き込んだ"


def test_nothing_in_the_band():
    """★何も居なければ切り出さない（真っ黒な絵を図鑑に載せない）。"""
    px = blank()
    draw(px, 33, 174, 8, 70)              # パーティ枠だけ
    got = find_sprite(px, EXPECT_W, EXPECT_H)
    assert not got.ok
    assert "見つからない" in got.reason


# --- 2. 複数体でも1体だけ ---------------------------------------------


def test_single_sprite():
    px = blank()
    draw(px, 110, 140, 100, 127)
    got = find_sprite(px, EXPECT_W, EXPECT_H)
    assert got.ok
    # 余白ぶん広い
    assert got.left <= 110 and got.left + got.width - 1 >= 140


def test_takes_only_the_leftmost_of_many():
    """★★ 実際に起きた不具合。よろいムカデ4体で幅216pxの集合写真になった。"""
    px = blank()
    for i in range(4):
        x = 16 + i * 56
        draw(px, x, x + 30, 100, 127)
    got = find_sprite(px, EXPECT_W, EXPECT_H)
    assert got.ok
    assert got.width < 60, f"集合写真になっている（幅 {got.width}）"
    assert "4体ぶん検出" in got.reason


def test_small_gap_inside_one_sprite_is_not_split():
    """⚠ 敵の絵の中の黒い列（脚の間など）で割らないこと。

    `MIN_GAP` 未満の隙間は同じ体として繋げる。
    """
    px = blank()
    draw(px, 100, 118, 100, 127)
    draw(px, 118 + MIN_GAP - 1, 140, 100, 127)   # 隙間は MIN_GAP 未満
    blobs = column_blobs(px, EXPECT_W, BAND_TOP, BAND_BOTTOM)
    assert len(blobs) == 1, f"1体を割ってしまった: {blobs}"


def test_wide_gap_splits():
    px = blank()
    draw(px, 100, 118, 100, 127)
    draw(px, 118 + MIN_GAP + 4, 150, 100, 127)   # 隙間は MIN_GAP 以上
    blobs = column_blobs(px, EXPECT_W, BAND_TOP, BAND_BOTTOM)
    assert len(blobs) == 2, f"割れていない: {blobs}"


def test_height_comes_from_the_chosen_blob_only():
    """★選んだ体の高さだけを見ること（隣の背の高い敵に引っ張られない）。"""
    px = blank()
    draw(px, 40, 70, 118, 127)            # 低い敵（左）
    draw(px, 140, 170, 80, 127)           # 高い敵（右）
    got = find_sprite(px, EXPECT_W, EXPECT_H)
    assert got.ok
    assert got.height < 30, f"隣の高さを巻き込んだ（{got.height}）"


# --- 4. 画面の大きさが違ったら何もしない ------------------------------


def test_refuses_unexpected_screen_size():
    """★実測した座標が当てにならないので手を出さない。"""
    px = blank(256, 240)
    draw(px, 110, 140, 100, 127)
    got = find_sprite(px, 256, 240)
    assert not got.ok
    assert "大きさ" in got.reason


# --- 3. 複数種の対応づけ（split_file 経由 / 実ファイルで）---------------


@pytest.fixture
def art(tmp_path):
    """テスト用の raw と出力先を作る。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    return raw, tmp_path / "out"


def _save(path, sprites):
    """sprites = [(x0, x1)] の位置に四角を描いた画面を PNG で保存する。"""
    from PySide6.QtGui import QImage, qRgb

    img = QImage(EXPECT_W, EXPECT_H, QImage.Format.Format_RGB32)
    img.fill(qRgb(0, 0, 0))
    for x0, x1 in sprites:
        for y in range(100, 128):
            for x in range(x0, x1 + 1):
                img.setPixel(x, y, qRgb(255, 255, 255))
    assert img.save(str(path))


def test_multi_species_mapped_by_position(art):
    """★★ これが「1戦闘で複数種を埋める」中身 ★★

    `$0162` は画面の並び順どおりなので、左から i 番目のかたまりが ids[i]。
    """
    from retroux.core.art.trim import trim_new

    raw, out = art
    _save(raw / "12-06-0C.png", [(40, 70), (110, 140), (180, 210)])
    results = trim_new(raw, out)
    assert results and results[0][1].ok, results
    assert sorted(p.name for p in out.glob("*.png")) == ["06.png", "0C.png", "12.png"]


def test_mismatch_does_not_save_anything(art):
    """⚠⚠ かたまりの数と体数が合わなければ**何もしない**。

    ずれたまま保存すると**違う敵の絵を図鑑に載せる**。
    「分からないときは動かない」。
    """
    from retroux.core.art.trim import trim_new

    raw, out = art
    # 名前は3体ぶんだが、画面には4体いる
    _save(raw / "12-06-0C.png", [(20, 45), (70, 95), (120, 145), (170, 195)])
    results = trim_new(raw, out)
    assert results and not results[0][1].ok
    assert "合わない" in results[0][1].reason
    assert list(out.glob("*.png")) == [], "合わないのに保存した"


def test_same_species_uses_leftmost_even_if_counts_differ(art):
    """★1種だけなら数が合わなくても取り違えようがないので左端を使う。"""
    from retroux.core.art.trim import trim_new

    raw, out = art
    _save(raw / "0F.png", [(20, 45), (70, 95), (120, 145)])
    results = trim_new(raw, out)
    assert results and results[0][1].ok
    assert [p.name for p in out.glob("*.png")] == ["0F.png"]


def test_skips_when_everything_is_already_there(art):
    from retroux.core.art.trim import trim_new

    raw, out = art
    _save(raw / "0C.png", [(110, 140)])
    assert trim_new(raw, out)              # 1回目は切り出す
    assert trim_new(raw, out) == [], "2回目も切り出そうとした"


def test_unreadable_name_is_reported(art):
    from retroux.core.art.trim import trim_new

    raw, out = art
    _save(raw / "battle01.png", [(110, 140)])
    results = trim_new(raw, out)
    assert results and not results[0][1].ok
    assert "敵ID" in results[0][1].reason
