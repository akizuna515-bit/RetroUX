"""カウンター越しに動く NPC と話す（RX3-0182 / 2026-09-12）。

⚠⚠ 依頼者「save7 カザーブの村のさかばで聞き込みできない ※カウンター越しでNPCが移動するパターン」。
★酒場の人（map 20 / 動く）はカウンター (27,4)(27,5) の奥 (28,4)(28,5) の 2 升だけを動く。
⚠ Lua（`nav_v0.lua`）は動く相手と「隣（1 升）」でしか話さず、⚠ Lua の地図はカウンターを壁と同じ `B` で書いていた
→ 待ちの上限で `skip_unreachable_now`。
→ ★Python は Lua の地図にカウンターを `K` で書く（★通れないのは同じ）。Lua は間がカウンターなら 2 升先でも話す。

★Lua 側は `research/probes/active/dq3_nav_v0_test.lua`（`tests/test_dq3_nav_v0.py`）が本物の `nav_v0.lua` を動かして見る。
"""
from __future__ import annotations

from dq3.knowledge import town_service as TS
from dq3.testing import passability as P

PASS_TILE, WALL_TILE, COUNTER_TILE = 8, 2, 14


def _rom(rows: list[str]) -> P.RomMap:
    """★文字の地図 → RomMap（`.` 床 / `#` 壁 / `=` カウンター）。⚠ ROM を使わない。"""
    table = [0x00] * 32
    table[WALL_TILE] = 0x80 | 0x10                  # ★壁（壁の形の bit あり）
    table[COUNTER_TILE] = 0x80                      # ★カウンター（通れないが壁の形が無い / `navigation.is_counter`）
    kinds = {"#": WALL_TILE, "=": COUNTER_TILE}
    tiles = [[kinds.get(c, PASS_TILE) for c in row] for row in rows]
    return P.RomMap(20, tiles, table, 0)


#: ★カザーブの酒場の形（★カウンター 2 升の奥に 2 升の囲い）
TAVERN = ["#####",
          "..=.#",
          "..=.#",
          "#####"]


def test_Luaの地図にカウンターをKで書く():
    got = TS.TownService.grid_text(_rom(TAVERN)).splitlines()
    assert got[0] == "5 4"
    assert got[2] == "PPKPB" and got[3] == "PPKPB", "⚠⚠ カウンターが壁と同じ字のまま（Lua が 2 升先で話せない）"


def test_壁と床はいままでと同じ字():
    """⚠ `RomMap.to_text` は変えない（★probe・検査が `B` を前提にしている）。"""
    rom = _rom(TAVERN)
    plain = rom.to_text().splitlines()
    assert plain[2] == "PPBPB", "★RomMap.to_text はカウンターも B のまま"
    got = TS.TownService.grid_text(rom).splitlines()
    for a, b in zip(plain, got):
        assert len(a) == len(b)
        assert all(x == y or (x == "B" and y == "K") for x, y in zip(a, b))


def test_write_gridはKの入った地図を書く(tmp_path, monkeypatch):
    monkeypatch.setattr(TS, "GRID_DIR", tmp_path)
    svc = TS.TownService(rom_maps={20: _rom(TAVERN)})
    path = svc.write_grid(20)
    assert path is not None and "K" in path.read_text(encoding="utf-8")
