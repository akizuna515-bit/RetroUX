"""入口表（entrance → map_id）（RX3-0013 ② / 2026-08-31）。

★ROM 不要: 区切りの読み方・種別の帯・数が合わないときの残し方
★ROM 時  : 243 block ちょうど・件数の辻褄・**行って戻れること**

⚠⚠ 一番効く検査は「戻り」です。表の先頭が 1 block ずれただけで
`load_map` の 404 件が総崩れになります（★件数の一致だけでは気づけません）。
"""

from __future__ import annotations

import pathlib

import pytest

from dq3rom import area_maps as am
from dq3rom import collision
from dq3rom import entrances as en
from dq3rom import profile as dq3

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"

#: ⚠ 件数が合わない 12 map（★2026-08-31 時点。理由は未解明）
KNOWN_MISMATCH = {0, 60, 70, 80, 85, 97, 105, 113, 117, 151, 198, 216}


# --- ROM 不要 ---------------------------------------------------------------

def test_parse_splits_on_terminator():
    data = bytes([0x0A, 0x00, 0x0B, 0x85, 0xFF, 0xFF, 0x0C, 0x02, 0xFF])
    blocks = en.parse(data, 3)
    assert [len(b) for b in blocks] == [2, 0, 1]
    assert blocks[0][1] == en.Entrance(index=1, dest_map=0x0B, kind=0x85)


def test_parse_refuses_when_short():
    """⚠ 足りないまま返すと、以後の map が全部ずれる。"""
    with pytest.raises(en.EntranceError):
        en.parse(bytes([0x0A, 0x00, 0xFF]), 2)


@pytest.mark.parametrize("kind,band", [
    (0x00, "load_map"), (0x7F, "load_map"), (0x80, "band_80"), (0xBF, "band_80"),
    (0xC0, "band_c0"), (0xEF, "band_c0"), (0xF0, "band_f0"), (0xFD, "band_f0"),
    (0xFE, "band_fe"), (0xFF, "band_fe"),
])
def test_band_boundaries(kind, band):
    assert en.band_of(kind) == band


class _Decoded:
    def __init__(self, tiles):
        self.tiles = tiles


def test_sites_keeps_extra_cells():
    """⚠ 升のほうが多くても黙って捨てない（★行き先 None で残す）。"""
    table = [0] * 32
    table[3] = 0x01
    decoded = _Decoded([[0, 3], [3, 0]])
    got = en.sites(decoded, table, [en.Entrance(0, 9, 0)])
    assert [(s.x, s.y) for s in got] == [(1, 0), (0, 1)]
    assert got[0].entrance is not None and got[1].entrance is None


# --- ROM 時 -----------------------------------------------------------------

def _rom_ready() -> bool:
    try:
        dq3.load_and_identify(ROM_PATH)
    except Exception:
        return False
    return True


needs_rom = pytest.mark.skipif(
    not _rom_ready(), reason=f"DQ3 Rev 0A の ROM が読めない（{ROM_PATH}）")


@pytest.fixture(scope="module")
def rom():
    ident = dq3.load_and_identify(ROM_PATH)
    n = len(am.read_directory(ident))
    return ident, n, en.read_blocks(ident, n)


@needs_rom
def test_table_ends_exactly_at_243_blocks(rom):
    """★area_directory と同じ 243。⚠ 余りも不足も出ない。"""
    ident, n, blocks = rom
    assert (n, len(blocks)) == (243, 243)
    start = ident.table_prg("entrance_table")
    end = ident.table_prg("entrance_table", "end_file_exclusive")
    used = sum(len(b) * 2 + 1 for b in blocks)
    assert used == end - start


@needs_rom
def test_every_load_map_has_a_way_back(rom):
    """★★ 行き先の map には、必ず元の map へ戻る行がある（404/404）。 ★★"""
    _, n, blocks = rom
    missing = [(src, e.dest_map)
               for src, blk in enumerate(blocks) for e in blk
               if e.band == "load_map"
               and not (e.dest_map < n
                        and any(x.dest_map == src for x in blocks[e.dest_map]))]
    assert missing == []


@needs_rom
def test_load_map_count_is_pinned(rom):
    _, _, blocks = rom
    n = sum(1 for b in blocks for e in b if e.band == "load_map")
    assert n == 404


@needs_rom
def test_cell_count_agrees_with_table(rom):
    """★入口の升の数と、表の対の数が合う（⚠ 既知の 12 件を除く）。"""
    ident, _, blocks = rom
    ov = collision.read_overrides(ident)
    bad = set()
    checked = 0
    for m in am.decode_all(ident):
        if not m.ok:
            continue
        checked += 1
        table = collision.table_for(ident, m.entry.tileset, m.entry.map_id, ov)
        cells = len(en.scan_order(m.decoded, table))
        if cells != len(blocks[m.entry.map_id]):
            bad.add(m.entry.map_id)
    assert checked == 204
    assert bad == KNOWN_MISMATCH


@needs_rom
def test_map9_entrances(rom):
    """★セーブステートのある町（map 9）。⚠ 走査順もろとも固定する。"""
    ident, _, blocks = rom
    m = next(x for x in am.decode_all(ident) if x.entry.map_id == 9)
    table = collision.table_for(ident, m.entry.tileset, 9,
                                collision.read_overrides(ident))
    got = [(s.x, s.y, s.entrance.dest_map, s.entrance.kind)
           for s in en.sites(m.decoded, table, blocks[9])]
    assert got == [(24, 2, 110, 0), (6, 3, 110, 0), (5, 21, 109, 0)]


@needs_rom
def test_profile_block_count_matches_directory(rom):
    """⚠ profile の `blocks` を誰も読まないと、書き間違えても気づけない。"""
    ident, n, _ = rom
    assert int(ident.table("entrance_table")["blocks"]) == n
    with pytest.raises(en.EntranceError):
        en.read_blocks(ident, n - 1)


# --- 着地点 -----------------------------------------------------------------

_TABLES = {
    "arrival_local": [(15, 29, 0), (13, 39, 1)],
    "arrival_world": [(0, 163, 200)],
    "arrival_world_short": [(93, 104)],
}


def test_arrival_below_80_is_an_entrance_index():
    a = en.arrival_of(en.Entrance(0, 110, 0x03), _TABLES)
    assert (a.where, a.to_map, a.to_index) == ("entrance", 110, 3)


def test_arrival_80_reads_the_local_table():
    a = en.arrival_of(en.Entrance(0, 70, 0x81), _TABLES)
    assert (a.where, a.x, a.y, a.facing) == ("local", 13, 39, 1)


def test_arrival_c0_and_f0_read_the_world_tables():
    a = en.arrival_of(en.Entrance(0, 0, 0xC0), _TABLES)
    assert (a.where, a.world, a.x, a.y) == ("world", 0, 163, 200)
    b = en.arrival_of(en.Entrance(0, 0, 0xF0), _TABLES)
    assert (b.where, b.world, b.x, b.y) == ("world", None, 93, 104)


def test_arrival_fe_stays_unknown():
    """⚠ 表を引かない帯。★分からないものを分かったことにしない。"""
    assert en.arrival_of(en.Entrance(0, 0, 0xFE), _TABLES).where == "unknown"


def test_arrival_refuses_to_read_past_the_table():
    with pytest.raises(en.EntranceError):
        en.arrival_of(en.Entrance(0, 0, 0x8F), _TABLES)


@needs_rom
def test_arrival_tables_are_pinned(rom):
    ident, _, _ = rom
    t = en.read_arrival_tables(ident)
    assert [len(v) for v in
            (t["arrival_local"], t["arrival_world"], t["arrival_world_short"])
            ] == [7, 19, 9]
    assert t["arrival_local"][0] == (0x0F, 0x1D, 0)
    assert t["arrival_world"][0] == (0, 0xA3, 0xC8)
    assert t["arrival_world_short"][0] == (0x5D, 0x68)


@needs_rom
def test_every_used_arrival_index_is_inside_its_table(rom):
    """⚠ 表の大きさを取り違えると、ここで気づく。

    ★`arrival_world` は索引 18 まで使う（⚠ 表は 19 件でぴったり）。
    ★★ 使われていない 1 件（索引 10）は **中身が 0,0,0** だった。
      ⚠ 表の切り方が合っている、いちばん静かな証拠。
    """
    ident, _, blocks = rom
    t = en.read_arrival_tables(ident)
    used = {"arrival_local": set(), "arrival_world": set(),
            "arrival_world_short": set()}
    for blk in blocks:
        for e in blk:
            en.arrival_of(e, t)          # ⚠ はみ出せばここで落ちる
            for name, base in (("arrival_local", 0x80),
                               ("arrival_world", 0xC0),
                               ("arrival_world_short", 0xF0)):
                if en.band_of(base) == e.band:
                    used[name].add(e.kind - base)
    assert max(used["arrival_world"]) == 18
    assert used["arrival_world"] == set(range(19)) - {10}
    assert t["arrival_world"][10] == (0, 0, 0)
    assert used["arrival_local"] == set(range(7)) - {1}
    assert used["arrival_world_short"] == set(range(8))


@needs_rom
def test_arrival_index_leads_back_to_where_we_came_from(rom):
    """★★ 行った先の「その番目」の入口が、元の map へ戻る（396/404）。 ★★

    ⚠ 残り 8 件のうち 6 件は「件数が合わない 12 map」に触れているもの。
    ★2 件（map 43/44 → 148）は**本当に非対称**（★148 は 2 か所から入れる）。
    """
    _, _, blocks = rom
    off = []
    total = 0
    for src, blk in enumerate(blocks):
        for i, e in enumerate(blk):
            if e.band != "load_map":
                continue
            total += 1
            dest = blocks[e.dest_map]
            if e.kind >= len(dest) or dest[e.kind].band != "load_map" \
                    or dest[e.kind].dest_map != src:
                off.append((src, i, e.dest_map, e.kind))
    assert total == 404
    assert len(off) == 8, off
    asymmetric = [r for r in off if not ({r[0], r[2]} & KNOWN_MISMATCH)]
    assert asymmetric == [(43, 1, 148, 1), (44, 0, 148, 0)]
