"""画面の升目 ↔ 地図の升目（RX3-0016 / 2026-08-26）。

★★ 何を確かめるか ★★

**主人公はいつも画面の同じ升 (8, 7) に描かれる**、という 1 点だけ。
これが正しければ、地図座標は

    地図 = 主人公の地図座標 + (画面の升 - (8, 7))

で決まる。⚠ スクロールは要らない。

## ⚠ スクロールから求めようとして失敗した

面はスクロールに合わせて書き換わるので、`scroll / 16` は地図座標にならない。
★総当たりで確かめたところ、2 つのセーブステートで**式が出す値がそのまま最良**だった。

## ★確かめ方

「同じ地図タイルは同じ見た目になるはず」を手がかりにする。
⚠ ただし**窓が乗っている升は除く**（窓は地形ではない）。
★実測では、窓を除けば地形タイルは**すべて 1 通りの見た目**に収まる。
"""

from __future__ import annotations

import collections
import pathlib

import pytest

from dq3rom import ppu, viewport

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()
ROM_CANDIDATES = list((ROOT / "work").rglob("DQ3_J.nes"))

from dq3_states import FIELD, pick


#: ★いまどこに居るか（⚠ 1 = ローカル。★profile の `location.kind`）
LOC_KIND, LOCAL = 0x2F, 1
#: ★ローカルの地図番号（⚠ `kind` が 1 のときだけ意味がある）
MAP_NO = 0x8B


def _same_map(map_id):
    """★その地図を写している、戦闘でないセーブ（⚠ 番号は当てにしない）。

    ⚠⚠ **`map_no` だけで選ばないこと。**
      ★世界地図に出ても `$8B` は**前のローカルの値が残ったまま**です
      （profile の `_kind_note`。⚠ セーブ 10 個中 8 個がそうだった）。
      → ⚠ 混ぜると別の地図どうしを突き合わせ、★矛盾が 108 件出ました。
    """
    from retroux.core.bgmap import savestate as ss

    got = []
    for path in pick(FIELD):
        ram = ss.load(path).chunks["RAM"]
        if ram[LOC_KIND] == LOCAL and ram[MAP_NO] == map_id:
            got.append(path)
    return got

#: ★★ 同じ地図を、違う場所・違うスクロールで写したセーブ**全部**。
#:
#:   ⚠⚠ 2026-08-31: ここは `fc9` / `fc7` と番号で名指ししていた。
#:     ★依頼者が撮り直したら 2 枚が近い場所になり、
#:     ⚠ 見た升が 192 に減って落ちた（★200 要る / RX3-0028）。
#:   → ★同じ地図のものを**全部**使う。枚数が増えるぶん材料も増える。
MAP_ID = 9
STATES = [p.name for p in _same_map(MAP_ID)]

#: ⚠ 地形のタイルはすべて 0x80 以上（実測）。★窓の中身・枠は 0x80 未満。
TERRAIN_FLOOR = 0x80


def _rom():
    if not ROM_CANDIDATES:
        pytest.skip("DQ3 の ROM が無い")
    return ROM_CANDIDATES[0]


@pytest.fixture(scope="module")
def world():
    """ROM から地図を起こす。★`work/` の一時ファイルには頼らない。"""
    from dq3rom import area_maps as am, profile as dq3

    ident = dq3.load_and_identify(_rom())
    found = [m for m in am.decode_all(ident) if m.ok and m.entry.map_id == MAP_ID]
    if not found:
        pytest.skip("map %d が読めない" % MAP_ID)
    d = found[0].decoded
    # ⚠ 実機の地図バッファは tiles + 32 * phase2（★実測で一致を確認した）
    grid = [[d.tiles[y][x] + 32 * d.phase2[y][x] for x in range(d.width)]
            for y in range(d.height)]
    return grid, d.width, d.height


def _states():
    from retroux.core.bgmap import savestate as ss

    out = []
    for name in STATES:
        path = FCS / name
        if not path.exists():
            continue
        chunks = ss.load(path).chunks
        if chunks["RAM"][0x8B] != MAP_ID:
            continue
        out.append((name, chunks))
    if not out:
        pytest.skip("map %d のセーブステートが無い" % MAP_ID)
    return out


def _blocks(chunks):
    """16x16 の升ごとの 2x2 タイル。⚠ 窓が混じる升は返さない。"""
    scroll = ppu.scroll_of(chunks)
    screen = ppu.compose(chunks["NTAR"], scroll, ppu.mirroring_of(chunks))
    for cy in range(viewport.CELLS_DOWN):
        for cx in range(viewport.CELLS_ACROSS):
            cells = [screen[(cy * 2 + dy) * 32 + cx * 2 + dx]
                     for dy in range(2) for dx in range(2)]
            if any(v < TERRAIN_FLOOR for v in cells):
                continue                       # ⚠ 窓・文字が乗っている
            yield cx, cy, tuple(cells)


def _consistency(world, shift_x: int = 0, shift_y: int = 0,
                 with_below: bool = True) -> tuple[int, int]:
    """(矛盾の数, 見た数)。★ずれをわざと足せる。

    ⚠ 見た目は**そのタイルだけ**では決まらない。壁は「下の升が壁でないとき」に
    下半分の描き方が変わる（★`dq3rom/wall_join.py` で確かめた自動つなぎ）。
    そこで既定では **(タイル, 下の升のタイル)** を鍵にする。
    """
    grid, w, h = world
    table: dict = {}
    bad = seen = 0
    for _name, chunks in _states():
        v = viewport.of_state(chunks, w, h)
        for cx, cy, pat in _blocks(chunks):
            mx = v.left + cx + shift_x
            my = v.top + cy + shift_y
            if not v.contains(mx, my):
                continue
            below = grid[my + 1][mx] if my + 1 < h else -1
            key = (grid[my][mx], below) if with_below else grid[my][mx]
            seen += 1
            if key in table:
                if table[key] != pat:
                    bad += 1
            else:
                table[key] = pat
    return bad, seen


def test_主人公はいつも同じ升にいる():
    """★(8, 7) の升 = 画面のタイル (16, 14)。"""
    for _name, chunks in _states():
        ram = chunks["RAM"]
        v = viewport.of_state(chunks, 26, 26)
        assert v.screen_at(ram[0x30], ram[0x31]) == (16, 14)


@pytest.mark.xfail(reason="⚠ 基準にしていたセーブが失われた（RX-0135）。★観点は docs/audit/tests-waiting-savestates.md", strict=False)
def test_地図のタイルと見た目が1対1(world):
    """★窓を除けば、同じ地図タイルは必ず同じ見た目になる。

    ⚠ 鍵は (タイル, 下の升) — 壁の自動つなぎのぶん。
    """
    bad, seen = _consistency(world)
    assert seen > 200, "⚠ 見た升が %d しかない（★材料不足）" % seen
    assert bad == 0, "⚠ 矛盾 %d 件 / 見た升 %d" % (bad, seen)


def test_下の升を見ないと矛盾する(world):
    """★★ 壁の自動つなぎを、**画面の側から**もう一度確かめる。

    ⚠ タイルだけを鍵にすると矛盾が出る。★それは誤差ではなく仕組み。
    実測では 1 種類（`0x0B` = 壁）だけが 2 通りの見た目を持ち、
    下半分が `B9 B9` か `F0 F0` に分かれる。
    """
    bad, seen = _consistency(world, with_below=False)
    assert bad > 0, "⚠ 下の升を見なくても矛盾しない（★前提が変わった？）"
    assert bad < seen // 10, "⚠ 矛盾が多すぎる（%d / %d）★式のほうを疑う" % (bad, seen)


@pytest.mark.parametrize(("dx", "dy"), [(1, 0), (-1, 0), (0, 1), (0, -1)])
@pytest.mark.xfail(reason="⚠ 基準にしていたセーブが失われた（RX-0135）。★観点は docs/audit/tests-waiting-savestates.md", strict=False)
def test_1マスずらすと矛盾が出る(world, dx, dy):
    """★★ 上の検査が「たまたま通った」のでないことを示す。

    ⚠ どんなずれでも通ってしまうなら、その検査は何も守っていない。
    """
    bad, seen = _consistency(world, dx, dy)
    assert bad > 0, "⚠ (%+d,%+d) ずらしても矛盾が出ない（★検査が効いていない）" % (dx, dy)


def test_地図の外を指すことがある():
    """⚠ 画面には地図の外も映る。★`contains` で弾く。"""
    v = viewport.Viewport(party_x=2, party_y=10, width=26, height=26)
    assert v.map_at(0, 0) == (-6, 3)
    assert not v.contains(-6, 3)
    assert v.contains(2, 10)


def test_画面と地図を往復できる():
    v = viewport.Viewport(party_x=19, party_y=13, width=26, height=26)
    for mx, my in ((19, 13), (11, 6), (25, 20)):
        sx, sy = v.screen_at(mx, my)
        assert v.map_at(sx, sy) == (mx, my)
        assert v.map_at(sx + 1, sy + 1) == (mx, my)   # ★升の中はどこでも同じ
