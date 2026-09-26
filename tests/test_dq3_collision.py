"""collision[32] の再現（RX3-0009 / 2026-08-24）。

★ここで見張るのは 3 つ。

1. **実機の実測 32 バイトと一致する**（錨。これが外れたら全部やり直し）
2. **上書き表が効いている**（⚠ 効いていないと宝箱が数百件の誤検出になる）
3. **宝箱の個数表と一致する**（教師データ。⚠ 未解決は「上限」で書く）

⚠ 3 の未解決件数は `<=` で書く。★等号で固定すると、直したときに赤くなって
「直っていない主張」を守ってしまう（RX-0102 の教訓）。
"""

from __future__ import annotations

import pathlib

import pytest

from dq2rom import ines
from dq3rom import collision as col

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"

#: ★実機（FCEUX）の WRAM $6DE0-$6DFF から採った 32 バイト。
#:   (tileset, map_id, 32 バイト)。⚠ すべて日本版 ROM を実機で動かして採った実測値
ANCHORS = (
    # 世界地図（2026-08-24）
    (0, None, (
        0x84, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0x05,
        0x00, 0x00, 0x01, 0x02, 0x01, 0x02, 0x01, 0x01,
        0x80, 0x01, 0x00, 0x01, 0x01, 0x01, 0x80, 0x80,
        0x80, 0x80, 0x80, 0x00, 0x80, 0x80, 0x00, 0x00)),
    # 町 map 0（2026-08-24）
    (1, 0, (
        0x80, 0x80, 0x80, 0x00, 0x00, 0x80, 0x80, 0x80,
        0x00, 0x0A, 0x01, 0x90, 0x8B, 0x8C, 0x80, 0x03,
        0x00, 0x00, 0x80, 0x80, 0x01, 0x02, 0x00, 0x80,
        0x00, 0x80, 0x00, 0xD0, 0x84, 0x00, 0x00, 0x03)),
    # ★map 71（19x24）。依頼者が遊びながら採った（2026-08-24 22:01）
    (2, 71, (
        0x80, 0x80, 0xC0, 0x00, 0x80, 0x80, 0xC0, 0x00,
        0x00, 0x0A, 0x01, 0x90, 0x8B, 0x8C, 0x80, 0x03,
        0x80, 0x80, 0x80, 0x80, 0x8D, 0x06, 0x07, 0x00,
        0x00, 0x80, 0x00, 0xD0, 0x84, 0x00, 0x00, 0x03)),
    # ★map 70（30x30）。同上。⚠ 記録では map 番号が 0 になっていたが、
    #   寸法（30x30）と表の両方が map 70 と一致した（切り替わり途中の取りこぼし）
    (5, 70, (
        0x80, 0x00, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80,
        0x00, 0x0A, 0x01, 0x90, 0x8B, 0x8C, 0x80, 0x03,
        0x00, 0x00, 0x80, 0x80, 0x80, 0x00, 0x00, 0x8D,
        0x00, 0x80, 0x00, 0xD0, 0x84, 0x00, 0x00, 0x03)),
    # ★map 9（26x26）。写す時機を直したあとに採り直した（2026-08-24 22:41）。
    #   ⚠ 直す前は**世界地図の表**が記録されていた。同じ tileset 5 の map 70 と
    #   同じ値になることまで確かめられた。
    (5, 9, (
        0x80, 0x00, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80,
        0x00, 0x0A, 0x01, 0x90, 0x8B, 0x8C, 0x80, 0x03,
        0x00, 0x00, 0x80, 0x80, 0x80, 0x00, 0x00, 0x8D,
        0x00, 0x80, 0x00, 0xD0, 0x84, 0x00, 0x00, 0x03)),
)

#: ⚠ まだ宝箱の個数が合わない map（`dq3rom/chests.py` の表）。★増えたら赤
KNOWN_MISMATCH = {23, 47, 98, 117, 235}


# --- ROM 不要 -----------------------------------------------------------

def test_グループの選び方は3通り():
    """$F64E の分岐そのまま。⚠ 1〜8 だけ**連続しない**。"""
    assert col.group_indices(0) == [18, 19, 20, 21]        # 世界地図
    assert col.group_indices(1) == [2, 0, 3, 1]            # ★ここが連続しない
    assert col.group_indices(8) == [16, 0, 17, 1]
    assert col.group_indices(9) == [22, 23, 24, 25]        # 9 以上は連続
    assert col.group_indices(27) == [94, 95, 96, 97]


def test_下位ニブルで拾う():
    table = [0x00] * 32
    table[5] = 0x83                       # ★上位ビットが立っていても宝箱
    table[9] = 0x8B
    assert col.tiles_with(table, col.CHEST) == {5}
    assert col.tiles_with(table, col.DOOR_ANY) == {9}


# --- ROM 時 -------------------------------------------------------------

def _rom_ready() -> bool:
    try:
        rom = ines.load(ROM_PATH)
    except Exception:                                  # noqa: BLE001
        return False
    return rom.mapper == 1 and rom.prg_banks == 16


needs_rom = pytest.mark.skipif(
    not _rom_ready(), reason=f"DQ3 Rev 0A の ROM が読めない（{ROM_PATH}）")


@pytest.fixture(scope="module")
def ident():
    from dq3rom import profile as dq3

    return dq3.load_and_identify(ROM_PATH)


@pytest.fixture(scope="module")
def area(ident):
    from dq3rom import area_maps as am

    return [m for m in am.decode_all(ident) if m.ok]


@needs_rom
@pytest.mark.parametrize(('tileset', 'map_id', 'expected'), ANCHORS,
                         ids=[f'ts{t}' for t, _m, _e in ANCHORS])
def test_実機の32バイトと一致する(ident, tileset, map_id, expected):
    """★★ 錨。⚠ ここが外れたら他の緑は意味を持たない。

    ★5 件（tileset 0 / 1 / 2 / 5 / 5）で実機と一致している。
    ⚠ map_id が None のものは、どの map の上書きも当てない素の表。
    """
    mid = 0xFFFF if map_id is None else map_id
    assert tuple(col.table_for(ident, tileset, mid)) == expected


@needs_rom
def test_グループ表を使い切る(ident):
    """★tileset の最大 27 が、表の最後のグループとちょうど合う。"""
    n = col.group_count(ident)
    assert n == 98
    assert max(col.group_indices(27)) == n - 1
    with pytest.raises(col.CollisionError):
        col.table_for(ident, 28, 0)        # ⚠ 表の外は黙って返さない


@needs_rom
def test_上書き表が実際に効いている(ident, area):
    """⚠ 効いていないと宝箱が数百件の誤検出になる（実際に踏んだ）。"""
    ov = col.read_overrides(ident)
    assert len(ov) == 17
    by_id = {m.entry.map_id: m for m in area}
    for mid in (74, 79, 90, 107):
        m = by_id[mid]
        before = col.base_table(ident, m.entry.tileset)
        after = col.table_for(ident, m.entry.tileset, mid, ov)
        # ★上書き前は誤検出（map ごとに 40〜562 件。⚠ 数は map の広さ次第）
        assert len(col.find(m.decoded, before, col.CHEST)) > 20
        assert col.find(m.decoded, after, col.CHEST) == []         # 上書き後は 0


@needs_rom
def test_宝箱の個数表と一致する(ident, area):
    """★★ 教師データ。⚠ 未解決は「上限」で書く（直ったら赤くならないように）。"""
    from dq3rom import chests

    want = {mid: n for mid, n in chests.read_tables(ident)[0]}
    ov = col.read_overrides(ident)
    bad = set()
    for m in area:
        mid = m.entry.map_id
        n = len(col.find(m.decoded, col.table_for(ident, m.entry.tileset, mid, ov),
                         col.CHEST))
        if n != want.get(mid, 0):
            bad.add(mid)
    assert bad <= KNOWN_MISMATCH, f"新しく合わなくなった map: {sorted(bad - KNOWN_MISMATCH)}"
    assert len(area) - len(bad) >= 199


@needs_rom
def test_扉が3種そろう(ident, area):
    from dq3rom import doors

    ds = doors.build(ident, area)
    s = doors.summary(ds)
    assert set(s["kinds"]) == {"any_key", "magic_key", "final_key"}
    assert all(v > 0 for v in s["kinds"].values())
    # ★強い鍵ほど開けられる扉が多い（bank12 $982B の階層）
    for d in ds:
        req = d.to_json()["requirements"][0]
        assert req["item_ids"], d.object_id
        assert len(req["item_ids"]) == 4 - d.rank
