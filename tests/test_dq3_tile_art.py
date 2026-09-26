"""地図の升を、ゲーム内のタイルの絵にする（RX3-0032 / 2026-08-31）。

★経路は `tests/test_dq3_map_tiles.py` が**実機のネームテーブルと突き合わせて**
確かめています（⚠ 634/634 一致）。ここは「絵になるか」を見ます。
"""

from __future__ import annotations

import io
import pathlib

import pytest

from dq3.knowledge import tile_art
from dq3_states import FIELD, pick

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOC_KIND, LOCAL = 0x2F, 1


def _local():
    """★ローカル地図のセーブ（⚠ 材料はローカル専用）。"""
    from retroux.core.bgmap import savestate as ss

    for path in pick(FIELD):
        ch = ss.load(path).chunks
        if ch["RAM"][LOC_KIND] == LOCAL and "WRAM" in ch:
            return path
    pytest.fail("⚠⚠ ローカル地図のセーブが 1 本もありません")


def test_索引の決め方はここだけ():
    """⚠⚠ **bit5 の升は索引 32**（★実測 / `dq3-map-tiles-report.md`）。"""
    assert tile_art.index_of(0x0B) == 11
    assert tile_art.index_of(0x1F) == 31
    assert tile_art.index_of(0x2B) == tile_art.DARK_INDEX
    assert tile_art.index_of(0x3F) == tile_art.DARK_INDEX


def test_黒く塗るのは勇者と層が違う升():
    """⚠⚠ RX3-0191（2026-09-12 依頼者「エルフの森の近辺洞窟で、画面とMAPの表示が異なる（MAPは黒表示）」）。

    ★ゲームは「升の層（& 0xE0）が勇者の升の層と違えば黒」。⚠ bit5 だけで決めると、洞窟で白黒が逆になる。
    """
    cave_hero = 0x33                                     # ★依頼者の save1: 勇者は層 0x20
    assert tile_art.index_of(0x33, cave_hero) == 0x13, "⚠⚠ 勇者と同じ層の通路を黒くしている"
    assert tile_art.index_of(0x2B, cave_hero) == 0x0B
    assert tile_art.index_of(0x13, cave_hero) == tile_art.DARK_INDEX, "⚠⚠ 別の層（岩）を地形で描いている"
    town_hero = 0x08                                     # ★町: 勇者は層 0 → 今までの bit5 と同じ
    assert tile_art.index_of(0x2B, town_hero) == tile_art.DARK_INDEX
    assert tile_art.index_of(0x0B, town_hero) == 0x0B


def test_セーブから升の絵ができる():
    art = tile_art.from_savestate(_local())
    assert art.known() > 20, "⚠ 索引が %d しか作れていない" % art.known()
    got = art.block(0x0B)
    assert got is not None
    assert len(got) == tile_art.CELL * tile_art.CELL * 3


def test_bit5の升は同じ絵になる():
    """★地形が違っても、bit5 が立っていれば同じ絵（⚠ 索引 32）。"""
    art = tile_art.from_savestate(_local())
    a, b = art.block(0x2B), art.block(0x28)
    assert a is not None and a == b, "⚠⚠ bit5 の升が別の絵になっている"


def test_空の索引は作らない():
    """⚠ 中身が全部 0 の索引で「黒い四角」を作らない（★分かるように出さない）。"""
    art = tile_art.from_savestate(_local())
    from retroux.core.bgmap import savestate as ss

    w = ss.load(_local()).chunks["WRAM"]
    for idx in range(64):
        o = tile_art.TILESET_OFF + idx * 4
        if not any(w[o:o + 4]):
            assert idx not in art.cells, "⚠ 空の索引 %d を作っている" % idx


def test_材料が足りなければ黙らない():
    """⚠⚠ **空を返さない**（★`RX3-0016` で 1 度やられた形）。"""
    with pytest.raises(tile_art.TileArtError):
        tile_art.build(b"\x00" * 8192, b"", b"\x00" * 32)
    with pytest.raises(tile_art.TileArtError):
        tile_art.build(b"\x00" * 8192, b"\x00" * 8192, b"")
    with pytest.raises(tile_art.TileArtError):
        tile_art.build(b"", b"\x00" * 8192, b"\x00" * 32)
    # ⚠ 材料はあるが tileset が空 → ★1 つも作れないので断る
    with pytest.raises(tile_art.TileArtError):
        tile_art.build(b"\x00" * 8192, b"\x11" * 8192, b"\x0F" * 32)


def test_画面側が出せなければ色ブロックへ落ちる():
    """⚠ 絵が出せないときに**落ちない**こと（★色ブロックのまま）。

    ⚠⚠ **字面しか見ていません。** ★実際に色ブロックへ落ちることは
      `tests/test_dq3_map_art_dark.py` と `tests/test_dq3_map_tile_draw.py`
      が**動かして**見ています（⚠ 字面だけだと 9 日間気づけません）。
    """
    src = io.open(ROOT / "dq3" / "ui" / "map_window.py",
                  encoding="utf-8", newline="").read()
    assert "def _tile_art(" in src
    assert "art = _tile_art(self.vm)" in src
    # ⚠ 2026-09-02（`RX3-0046`）: 「絵を持っている」ではなく
    #   ★**いまの地図の升も揃っている**ときだけタイルで描く
    assert "if self._drew_tiles:" in src, (
        "⚠⚠ 出せないときの道がありません（★色ブロックへ落ちること）")


def test_升ごとに色が変わる():
    """⚠⚠ **今日ここを踏んだ**（2026-08-31 / RX3-0032）。

    `from_savestate` の既定が `group=0` のままで、★両端は正しいのに
    **橋渡しが落として**いました（⚠ 全部が組 0 の色で描かれていた）。

    ⚠⚠ 最初この検査を「色の顔ぶれが 2 種以上あるか」で書いたら、
      ★**壊しても通りました**（升ごとに使う色番号が違うので、
      同じパレットでも顔ぶれは変わる）。
      → ★**組を決め打ちしたものと比べて、違うこと**で見ます。
    """
    from retroux.core.bgmap import savestate as ss

    path = _local()
    w = ss.load(path).chunks["WRAM"]
    art = tile_art.from_savestate(path)

    # ★材料の確認（⚠ 組が 1 つしか無い地図では、この検査は空回りする）
    groups = {w[tile_art.PALETTE_OFF + idx] for idx in art.cells}
    assert len(groups) > 1, (
        "⚠⚠ この地図は 1 つの組しか使っていない（★検査が空回り）")

    # ⚠⚠ **組 0 に決め打ちしたものと、違うこと**（★ここが本番）
    forced = tile_art.from_savestate(path, group=0)
    assert art.cells.keys() == forced.cells.keys()
    diff = sum(1 for k in art.cells if art.cells[k] != forced.cells[k])
    assert diff > 0, (
        "⚠⚠ `$7300` を使っていない（★組 0 に決め打ちしたのと同じ絵）")

    # ★組が 0 でない索引は、必ず違う絵になるはず
    for idx in art.cells:
        if w[tile_art.PALETTE_OFF + idx] % 4 != 0:
            assert art.cells[idx] != forced.cells[idx], (
                "⚠ 索引 %d は組 %d なのに、組 0 と同じ絵"
                % (idx, w[tile_art.PALETTE_OFF + idx]))


def test_組を指定すれば全部その色になる():
    """★見比べ用の逃げ道（⚠ 既定ではない）。"""
    import collections

    art = tile_art.from_savestate(_local(), group=1)
    seen = set()
    for block in art.cells.values():
        seen |= {tuple(block[i:i + 3]) for i in range(0, len(block), 3)}
    # ⚠ 4 色（★色 0 は共通）しか出ないはず
    assert len(seen) <= 4, "⚠ 組を決め打ちしたのに %d 色出ている" % len(seen)
