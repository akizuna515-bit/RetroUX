"""ダンジョンを ROM だけで描く（2026-08-02 / 実コードの写し）。

★★★ **観測辞書ではありません。すべて実コードから取りました。**

## ⚠⚠ 一番の落とし穴（記録）

論理セルの値は **`(生バイト & $E0) >> 3`（4刻み）**。
★下位2ビットが空いていて、そこに**象限**が入ります。

⚠ 私は `>> 5`（0-7）にして、**非単調セルが 0%** になりました。
★`>> 3` に直したところ **82.9〜92.2%** へ跳ねました。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.dungeon_map import (CELL_SHIFT, CHEST_TERRAIN,
                                            DungeonMap, map_kind)
from retroux.core.bgmap.rom_tiles import load_prg
from retroux.core.bgmap.terrain_reader import quadrant

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
CAPTURES = PROJECT_ROOT / "work" / "map-capture"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
_caps = sorted(CAPTURES.glob("*/capture.txt")) if CAPTURES.exists() else []
needs_capture = pytest.mark.skipif(not _caps, reason="採取データが無い")


def test_値は4刻みで下位2ビットが空く():
    """⚠⚠ **ここを `>>5` にすると非単調セルが 0% になります**。

    ★`$DFEC` の `LSR` ×3。象限が入る余地を残すためです。
    """
    assert CELL_SHIFT == 3


def test_象限の作り方はコードどおり():
    """★`$DDB0`-`$DDB4`: `PLA/LSR` `PLA/ROL` `AND #$03`。

    ⚠ つまり `((y & 1) << 1) | (x & 1)`。
    """
    assert quadrant(0, 0) == 0
    assert quadrant(1, 0) == 1
    assert quadrant(0, 1) == 2
    assert quadrant(1, 1) == 3


@needs_rom
def test_象限だけ違う4点は同じ論理セルを見る():
    """★★ 依頼者の指定した検証（2026-08-02）。

    `(2n,2m)` `(2n+1,2m)` `(2n,2m+1)` `(2n+1,2m+1)` は
    **同じ論理セル**を見て、**索引だけが 0-3 ずれる**。
    """
    m = DungeonMap(load_prg(ROM), 0x40)
    n, k = 5, 6
    base = None
    for dy in (0, 1):
        for dx in (0, 1):
            x, y = 2 * n + dx, 2 * k + dy
            assert (x >> 1, y >> 1) == (n, k)
            idx = m.index_at(x, y)
            if base is None:
                base = idx & ~0x03
            assert idx & ~0x03 == base, "★上位は同じはず"
            assert idx & 0x03 == quadrant(x, y)


@needs_rom
def test_範囲外は境界タイル():
    """⚠ `$DDC9: LDA $20` — 0 ではなく**境界タイルID**。"""
    m = DungeonMap(load_prg(ROM), 0x40)
    assert m.cell(-1, 0) == m.border
    assert m.cell(m.width, 0) == m.border
    assert m.cell(0, m.height) == m.border


@needs_rom
def test_画面の大きさは論理セルの2倍():
    m = DungeonMap(load_prg(ROM), 0x40)
    assert m.screen_size == (m.width * 2, m.height * 2)


@needs_rom
@pytest.mark.parametrize("map_id,kind", [
    (0x01, 0), (0x0B, 1), (0x3D, 2), (0x40, 2), (0x63, 3)])
def test_種別はmap_idで決まる(map_id, kind):
    assert map_kind(map_id) == kind


# --- ★★ 実測との照合（★採取地点ごとに数える）------------------------

def _cells_of(cap):
    """採取データの画面マスを `(x, y, タイル4枚, 属性)` で出す。

    ⚠ 主人公は画面の `(8, 7)` にいる前提です。
    ★マップの端やスクロール途中では**この前提が崩れます**
      （`_aligned` で外します）。
    """
    px, py = cap.int_of("x"), cap.int_of("y")
    for (cx, cy), (q, a) in cap.cells.items():
        if cy >= 10:
            continue
        tiles = tuple(int(q[i:i + 2], 16) for i in (0, 2, 4, 6))
        if min(tiles) < 0x90:
            continue
        x, y = px + cx - 8, py + cy - 7
        if x < 0 or y < 0:
            continue
        yield x, y, tiles, int(a)


def _aligned(cap) -> bool:
    """★スクロールがマス境界に乗っているか。

    ⚠ 歩いている途中（`scroll % 16 != 0`）に採ると、画面が1マスずれます。
    ★実測: `1785668320-003` は `scroll_x=225` で 2/50 しか合いませんが、
      ずれを 1 直すと **50/50** になります。デコーダのせいではありません。
    """
    sx, sy = cap.int_of("scroll_x"), cap.int_of("scroll_y")
    return sx is not None and sy is not None and sx % 16 == 0 and sy % 16 == 0


def _rate_of(dmap, cap):
    """1地点ぶんの一致率。⚠ 単調セルは数えません。"""
    ok = total = 0
    for x, y, tiles, _attr in _cells_of(cap):
        if len(set(tiles)) == 1:
            continue                     # ⚠ 一色は何をしても当たる
        total += 1
        ok += dmap.metatile_at(x, y)[0] == tiles
    return ok, total


@needs_rom
@needs_capture
@pytest.mark.parametrize("map_id", [0x3D, 0x40])
def test_ほとんどの採取地点が完全に一致する(map_id):
    """★★★ **これが到達点**（2026-08-02）。

    ⚠⚠ **マス単位で数えません。**
      同じマスを複数の地点が見ていると、ずれた地点の票が
      正しい票を打ち消して、実力より低い数字が出ます
      （★これで `$3E` を 54.5% と読み違えました）。

    実測（★マス境界に乗った地点だけ / 材料 20 マス以上）:
      map `$3D` `$40` は**ほぼ全地点が 100%**。
    """
    from retroux.tools.dq2_map_capture import Capture

    dmap = DungeonMap(load_prg(ROM), map_id)
    rates = []
    for path in _caps:
        cap = Capture.load(path)
        if cap.int_of("map_id") != map_id or not _aligned(cap):
            continue
        ok, total = _rate_of(dmap, cap)
        if total >= 20:                  # ⚠ 材料が薄い地点は数えない
            rates.append((cap.capture_id, ok / total))
    if len(rates) < 2:
        pytest.skip(f"★数えられる地点が {len(rates)} しかない")
    perfect = [r for r in rates if r[1] >= 0.999]
    assert len(perfect) >= len(rates) / 2, (
        f"★完全一致 {len(perfect)}/{len(rates)} 地点: "
        + ", ".join(f"{i}={r:.0%}" for i, r in rates))


@needs_rom
@needs_capture
def test_map3Eは採取が足りないことを記録する():
    """⚠⚠ **これは「まだ低い」ことを固定するテストです。**

    map `$3E` は採取が **7地点・y は 2/4/5 の3種だけ**（マップ上端 10%）。
    ★総当たりでは地点ごとに最適なずれが `(0,-7)` `(2,-7)` などと
      ばらつきます。⚠ つまり「主人公は画面 `(8,7)`」が崩れています。

    ★★ ROM から描いた `$3E` は迷路として成立しています
      （`work/map3E-dynamic.png`）。**デコーダの問題ではありません。**

    ⚠ 数字を緩めて通すのではなく、**低いことをそのまま記録**します。
      採取をやり直したらここが上がるはずで、そのとき気づけます。
    """
    from retroux.tools.dq2_map_capture import Capture

    dmap = DungeonMap(load_prg(ROM), 0x3E)
    rates = []
    for path in _caps:
        cap = Capture.load(path)
        if cap.int_of("map_id") != 0x3E or not _aligned(cap):
            continue
        ok, total = _rate_of(dmap, cap)
        if total >= 20:
            rates.append(ok / total)
    if len(rates) < 2:
        pytest.skip(f"★数えられる地点が {len(rates)} しかない")
    perfect = [r for r in rates if r >= 0.999]
    # ⚠ いまは 4 地点中 1 地点だけが完全一致。★上がったら知らせる
    assert len(perfect) < len(rates), (
        "★全地点が一致するようになりました。"
        "⚠ このテストを `test_ほとんどの採取地点が完全に一致する` へ移してください")


@needs_rom
@needs_capture
def test_属性も合う():
    """★パレット組（5バイト目 & 3）。"""
    from retroux.tools.dq2_map_capture import Capture

    dmap = DungeonMap(load_prg(ROM), 0x40)
    ok = total = 0
    for path in _caps:
        cap = Capture.load(path)
        if cap.int_of("map_id") != 0x40 or not _aligned(cap):
            continue
        for x, y, _tiles, attr in _cells_of(cap):
            total += 1
            ok += dmap.metatile_at(x, y)[1] == attr
    if total < 50:
        pytest.skip("★材料が足りない")
    assert ok / total >= 0.90, f"★{ok}/{total}"


# --- ★ 動的差分（宝箱・扉）を基礎地形から分ける ----------------------

@needs_rom
def test_宝箱は基礎地形から分けて持つ():
    """★★ 依頼者の指摘（2026-08-02）:

      「左上の謎の宝箱と、赤い枠が左上の湖に存在するのがちょっとおかしい」

    ★map `$40` の宝箱は **3個**。依頼者の見ている攻略サイトの
      01 / 02 / 03 と数も位置も合います。
    """
    from retroux.core.bgmap.overlay import KIND_CHEST, build_dynamic

    dmap = DungeonMap(load_prg(ROM), 0x40)
    overlay = build_dynamic(dmap)
    cells = sorted({e.cell for e in overlay.elements if e.kind == KIND_CHEST})
    assert cells == [(1, 7), (7, 13), (11, 14)]


@needs_rom
def test_RAMが無いときは状態を決めつけない():
    """⚠⚠ **分からないものを `closed` にしません**（推測で埋めない）。"""
    from retroux.core.bgmap.overlay import UNKNOWN, build_dynamic

    overlay = build_dynamic(DungeonMap(load_prg(ROM), 0x40))
    assert overlay.has_ram is False
    assert overlay.elements
    assert all(e.state == UNKNOWN for e in overlay.elements)
    assert len(overlay.unresolved()) == len(overlay.elements)


@needs_rom
def test_開封済みの宝箱は床になる():
    """★`$E006: LDA #$00 / STA $0C` の写し。"""
    from retroux.core.bgmap.overlay import (CHEST_LIST, OPENED_TERRAIN,
                                            build_dynamic, composed_terrain)

    dmap = DungeonMap(load_prg(ROM), 0x40)
    ram = bytearray(0x800)
    # ★セル (7, 13) を「開けた」ことにする
    ram[CHEST_LIST], ram[CHEST_LIST + 1] = 7, 13
    overlay = build_dynamic(dmap, ram)
    assert composed_terrain(dmap, 14, 26, overlay) == OPENED_TERRAIN
    # ⚠ 開けていない宝箱はそのまま
    assert composed_terrain(dmap, 2, 14, overlay) == CHEST_TERRAIN


@needs_rom
def test_壁向き補正はダンジョンでは使わない():
    """★★★ `$DDD6: LDA $1F / BEQ` — **種別0（世界地図）だけ**が
    `$DE29`（壁向き補正）へ行きます。街とダンジョンは `$DF7D` へ飛びます。

    ⚠ 2026-08-02、私はダンジョンにも当てていました。
      外したところ map `$40` の一致が上がりました。
    """
    import retroux.core.bgmap.dungeon_map as mod

    assert not hasattr(mod, "wall_shape"), "⚠ 壁補正を持ち込まないこと"


@needs_rom
def test_索引はマスクしない():
    """⚠⚠ `$DD64` は `& $1F` を**しません**。

    ★境界の外は `$20`（map `$40` では `$24`）が入るので、
      索引は `$24`-`$27` になります。種別1/2 の表は **40 件**なので
      これは範囲内です。丸めると別の絵になります。
    """
    from retroux.core.bgmap.dungeon_map import TABLE_ENTRIES

    dmap = DungeonMap(load_prg(ROM), 0x40)
    assert dmap.border == 0x24
    assert dmap.index_at(-2, 0) == 0x24
    assert dmap.index_at(-1, 1) == 0x27
    # ★40 件表なので $27 は範囲内。⚠ ここが 32 だと丸めたくなる
    assert TABLE_ENTRIES[2] == 40
    assert dmap.index_at(-1, 1) < TABLE_ENTRIES[2]


@needs_rom
def test_変換表の件数はROM表の間隔から出す():
    """★`$DC6F` のポインタの差が 5 の倍数であることで裏を取る。

    ⚠ 種別3 は次の値（`$7C20`）が逆行するので**測れません**。
      分からないものを 40 と決めつけません。
    """
    from retroux.core.bgmap.dungeon_map import TABLE_ENTRIES, TERRAIN_TABLES

    for kind, count in TABLE_ENTRIES.items():
        span = TERRAIN_TABLES[kind + 1] - TERRAIN_TABLES[kind]
        assert span % 5 == 0, f"⚠ 種別{kind} の間隔が 5 の倍数でない"
        assert span // 5 == count
    assert 3 not in TABLE_ENTRIES, "⚠ 種別3 の件数は測れていません"
