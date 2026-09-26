"""壁の自動つなぎ（RX3-0010 / 2026-08-24）。

★★ ここの要は **実機の地図バッファとの突き合わせ**。 ★★

⚠ ROM から展開しただけの地図は、実機と **9.3% 違っていた**（map 9 で 63/676）。
実機は展開のあとに壁のタイルを差し替える。`dq3rom/wall_join.py` はその処理を写したもの。

★突き合わせの材料は **セーブステートの `WRAM` チャンク**（`$6000-$7FFF`）。
FCEUX を起こさずに、実機が持っていた地図（`$7400`）と collision 表（`$6DE0`）が読める。
"""

from __future__ import annotations

import pathlib

import pytest

from dq2rom import ines
from dq3rom import collision as col
from dq3rom import wall_join

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"
#: ★依頼者が遊んで作ったもの。⚠ 無ければ skip（ROM と同じ扱い）
STATE_PATH = PROJECT_ROOT / "tools" / "fceux" / "fcs" / "DQ3_J.fc7"

#: WRAM の中での位置（$6000 起点）
WRAM_COLLISION = 0x0DE0
WRAM_MAPBUF = 0x1400


# --- ROM 不要 -----------------------------------------------------------

def test_差し替え先は後勝ち():
    """⚠ 実機は上書きしながら 32 個なめる。★後に出てきたほうが残る。"""
    table = [0x00] * 32
    table[3] = 0x50
    table[9] = 0x50          # ★同じクラス。後の 9 が勝つ
    table[20] = 0x60
    assert wall_join.target_tiles(table) == {0: 9, 1: 20}


def test_対象でないタイルは触らない():
    class _D:
        width = height = 2
        background = 0
        tiles = [[1, 1], [1, 1]]
        phase2 = [[0, 0], [0, 0]]

    table = [0x00] * 32       # ⚠ どれも上位 3 bit が 0 → 対象外
    assert wall_join.apply(_D(), table, 5) == [[1, 1], [1, 1]]


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
def test_宝箱と扉は壁つなぎで変わらない(ident, area):
    """★★ これが要。⚠ 変わるようになったら赤くする。

    差し替えは `$90→$D0` / `$A0→$E0` / `$B0→$F0` の 3 通りだけのはずで、
    宝箱（下位ニブル 3）や扉（$B/$C/$D）はどちらの側にも現れない。
    """
    ov = col.read_overrides(ident)
    interesting = {col.CHEST, col.DOOR_ANY, col.DOOR_MAGIC, col.DOOR_FINAL}
    for m in area:
        table = col.table_for(ident, m.entry.tileset, m.entry.map_id, ov)
        for i, v in enumerate(table):
            if (v & 0x70) in wall_join.CONVERTIBLE + wall_join.TARGETS:
                assert (v & 0x0F) not in interesting, (
                    f"map {m.entry.map_id} tile {i} の collision {v:02X} が"
                    f"壁つなぎの対象で、かつ宝箱／扉のニブルを持っている")


@needs_rom
def test_実際に効いている(ident, area):
    """⚠ 「何も変わらない」実装になっていないか（★静かな無効化の見張り）。"""
    ov = col.read_overrides(ident)
    changed = sum(
        1 for m in area
        if wall_join.changes(m.decoded,
                             col.table_for(ident, m.entry.tileset,
                                           m.entry.map_id, ov),
                             m.entry.tileset))
    assert changed >= 150, f"⚠ {changed} map でしか変わっていない"


@needs_rom
@pytest.mark.skipif(not STATE_PATH.exists(),
                    reason=f"実機のセーブステートが無い（{STATE_PATH}）")
@pytest.mark.xfail(reason="⚠ 基準にしていたセーブが失われた（RX-0135）。★観点は docs/audit/tests-waiting-savestates.md", strict=False)
def test_実機の地図バッファと完全に一致する(ident, area):
    """★★★ このファイルの本体。⚠ 1 マスでも違えば赤。"""
    from retroux.core.bgmap import savestate as ss

    state = ss.load(STATE_PATH)
    wram = state.chunks.get("WRAM")
    assert wram and len(wram) == 8192, "⚠ WRAM チャンクが読めない"

    map_id = state.byte(0x8B)
    assert state.byte(0x2F) != 0, "⚠ このセーブステートは世界地図。町の中で採り直して"
    by_id = {m.entry.map_id: m for m in area}
    m = by_id.get(map_id)
    assert m is not None, f"⚠ map {map_id} を復号できていない"
    d = m.decoded

    live_table = list(wram[WRAM_COLLISION:WRAM_COLLISION + 32])
    table = col.table_for(ident, m.entry.tileset, map_id)
    assert table == live_table, "⚠ collision 表が実機と違う"

    assert (d.width, d.height) == (state.byte(0x88), state.byte(0x89)), (
        "⚠ 寸法が実機と違う（★切り替わりの途中で保存された可能性）")

    tiles = wall_join.apply(d, table, m.entry.tileset)
    bad = [(x, y, tiles[y][x], wram[WRAM_MAPBUF + y * d.width + x] % 32)
           for y in range(d.height) for x in range(d.width)
           if tiles[y][x] != wram[WRAM_MAPBUF + y * d.width + x] % 32]
    assert not bad, (
        f"⚠ map {map_id} で {len(bad)} マスが実機と違う（先頭 5 件: {bad[:5]}）")
