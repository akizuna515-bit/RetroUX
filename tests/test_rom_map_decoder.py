"""マップ展開ルーチン `$E03C` の移植（2026-08-02 / Stop 1'）。

★2026-08-02 に完成しました（`bgmap/dungeon_map.py` / `world_map.py`）。
⚠ この文書は **Stop 1' の時点の記録**です。いまの正本は
  `docs/map-decoder-architecture.md` を見てください。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.rom_map import (
    KIND_DUNGEON_MAX, KIND_HALVED, KIND_TOWN_MAX, MASK_NARROW, MASK_WIDE,
    map_kind, read_header,
)
from retroux.core.bgmap.rom_tiles import load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")


# --- ★ マップ種別（`$E20A` の写し）------------------------------------

@pytest.mark.parametrize("map_id,kind", [
    (0x01, 0),          # ★世界地図
    (0x00, 1), (0x07, 1), (0x0B, 1), (0x2A, 1),   # 街・城
    (0x2B, 2), (0x3D, 2), (0x3F, 2), (0x43, 2),   # ダンジョン
    (0x44, 3), (0x59, 3), (0xFF, 3),
])
def test_マップ種別はmap_idだけで決まる(map_id, kind):
    """★ROM のコード `$E20A`:

        LDA $31 / CMP #$01 -> 0
                  CMP #$2B / BCC -> 1
                  CMP #$44 / BCC -> 2
                  else          -> 3
        STA $1F / STA $0C   ← ★タイルセット番号も同じ値
    """
    assert map_kind(map_id) == kind


def test_境目はROMのコードどおり():
    assert (KIND_TOWN_MAX, KIND_DUNGEON_MAX) == (0x2B, 0x44)
    assert KIND_HALVED == 2
    assert (MASK_WIDE, MASK_NARROW) == (0x3F, 0x0F)


@needs_rom
@pytest.mark.parametrize("map_id,halved", [
    (0x01, False), (0x0B, False), (0x07, False),   # ★等倍
    (0x3D, True), (0x3F, True), (0x40, True),      # ★2倍
])
def test_ダンジョンだけ座標が2倍(map_id, halved):
    """★`$E042: LSR $12 / LSR $13` は種別 2 以上のときだけ。

    ⚠ これが「ヘッダ寸法が実測の約半分」の正体。
      城 `$07`（種別1）が実測 20/21 でヘッダ 23×23 に収まっていたことと合う。
    """
    assert read_header(load_prg(ROM), map_id).halved is halved


# --- ⚠ ここから下は「当時どう探したか」の記録 -----------------------
#
#   ★地形データの位置は**確定しています**（ヘッダ byte3-4 のポインタ /
#     2026-08-02）。下の探索は、そこへ辿り着くまでの手当たりです。
#   ⚠ 消さずに残すのは、同じ探し方を繰り返さないためです。

def _row_totals(prg, off, mask, count=8):
    """各行の「連の長さの合計」。★bit7 が立つバイトがその行の最後（仮）。"""
    out, pos = [], 0
    for _ in range(count):
        total, n = 0, 0
        while off + pos < len(prg):
            b = prg[off + pos]
            pos += 1
            n += 1
            total += (b & mask) + 1
            if b & 0x80 or n > 60:
                break
        out.append(total)
    return out


@needs_rom
def test_byte5と6は5バイト周期で地形ではない():
    """⚠⚠ **2026-08-02、ここで2回続けて誤りました。記録として残します。**

    1回目: byte3/byte4 を地形データだと思った
    2回目: 「行の合計が幅+1 になる」ので byte5/byte6 だと思った
           → ★実は**各行が1バイト**で、たまたま合っていただけ
           → 展開すると街の地形がほぼ全部 0 になった（明確な誤り）

    ★中身を見れば一目でした:

        map $3F byte5/6 -> 22 10 05 54 90 | 22 10 05 54 90 | 22 10 05 54 90
                           ★**5バイト周期の繰り返し**
        map $3F byte3/4 -> E6 E6 E1 E2 E2 07 E0 E0 E7 07 45 …
                           ★こちらのほうがランレングスらしい

    ⚠ 「数字が合った」だけで決めない。**中身の形も見る。**
    """
    from retroux.core.bgmap.rom_tiles import MAP_HEADER, MAP_HEADER_SIZE

    prg = load_prg(ROM)
    o = MAP_HEADER + 0x3F * MAP_HEADER_SIZE
    ptr = prg[o + 5] | (prg[o + 6] << 8)
    off = 0x08000 + (ptr - 0x8000)
    data = prg[off:off + 30]
    # ★5バイトごとに同じ並びが続く
    assert data[0:5] == data[5:10] == data[10:15], data[:15].hex(" ")


@needs_rom
def test_行の合計だけで決めない():
    """⚠ 「幅+1 に一致」は**必要条件でしかない**。

    ★各行が1バイトでも合ってしまう（それが 2 回目の誤りの正体）。
    """
    from retroux.core.bgmap.rom_tiles import MAP_HEADER, MAP_HEADER_SIZE

    prg = load_prg(ROM)
    o = MAP_HEADER + 0x0B * MAP_HEADER_SIZE
    w = prg[o + 1]
    ptr = prg[o + 5] | (prg[o + 6] << 8)
    totals = _row_totals(prg, 0x08000 + (ptr - 0x8000), 0x3F)
    # ★合計は幅+1 とぴったり合う。⚠ でも地形データではなかった
    assert all(t == w + 1 for t in totals)


@needs_rom
def test_展開はまだ正しくない():
    """⚠⚠ **未達を隠さない**（2026-08-02）。

    いまの `terrain_at()` で街（map $0B）を展開すると、
    画面が多様なのに**地形がほぼ全部 0** になります。

    ★直ったらこのテストは落ちるので、そのとき前へ進めること。
    """
    from retroux.core.bgmap.rom_map import read_header, terrain_at

    prg = load_prg(ROM)
    h = read_header(prg, 0x0B)
    kinds = {terrain_at(prg, h, x, y)
             for y in range(10) for x in range(16)}
    assert len(kinds) <= 2, (
        f"★地形が {len(kinds)} 種類出るようになった（{sorted(kinds)}）。"
        "展開が直ったなら、この歯止めを外して前へ進めること")
