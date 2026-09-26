"""ルーラの行き先（RX3-0013 ③ / 2026-08-31）。

★ROM 不要: bit の読み方（⚠ 人ごと・3 バイト・下位から）
★ROM 時  : 表の中身と、入口表との辻褄
★実機    : ⚠⚠ **セーブステートで「行った町だけ立っている」ことを見る**

⚠ 一番効くのは最後の 1 本です。表の並びが 1 つずれると、
`fc2`（アリアハンだけ）が別の町を指し始めます。
"""

from __future__ import annotations

import pathlib

import pytest

from dq3rom import area_maps as am
from dq3rom import entrances as en
from dq3rom import profile as dq3
from dq3rom import rura

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"
# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()

ALIAHAN = 0x00
REEVE = 0x09


def _rom_ready() -> bool:
    try:
        dq3.load_and_identify(ROM_PATH)
    except Exception:
        return False
    return True


needs_rom = pytest.mark.skipif(
    not _rom_ready(), reason=f"DQ3 Rev 0A の ROM が読めない（{ROM_PATH}）")


@pytest.fixture(scope="module")
def ident():
    return dq3.load_and_identify(ROM_PATH)


# --- ROM 不要 ---------------------------------------------------------------

class _Prof:
    def __init__(self, **over):
        self.data = {"runtime": {"rura": dict(
            {"returnable": "0x0750", "stride": 3, "players": 4, "bits": 20},
            **over)}}


def _ram(offset: int, raw: bytes) -> bytes:
    b = bytearray(0x800)
    b[offset:offset + len(raw)] = raw
    return bytes(b)


def test_bits_are_read_low_byte_first():
    ram = _ram(0x750, bytes([0b0000_0101, 0x00, 0x08]))
    assert rura.known_indices(ram, _Prof(), 0) == [0, 2, 19]


def test_each_player_has_its_own_three_bytes():
    """⚠ 死んでいる間に訪れた町は、その人だけ落ちる（★だから人ごと）。"""
    ram = _ram(0x750, bytes([0x01, 0, 0, 0x02, 0, 0, 0x04, 0, 0, 0x08, 0, 0]))
    got = [rura.known_indices(ram, _Prof(), p) for p in range(4)]
    assert got == [[0], [1], [2], [3]]


def test_bits_above_the_table_are_ignored():
    """⚠ 3 バイト = 24 bit あるが、行き先は 20 件しかない。"""
    ram = _ram(0x750, bytes([0x00, 0x00, 0xF0]))
    assert rura.known_indices(ram, _Prof(), 0) == []


def test_refuses_an_unknown_player():
    with pytest.raises(rura.RuraError):
        rura.known_indices(_ram(0x750, b"\0\0\0"), _Prof(), 4)


def test_party_known_is_the_union():
    ram = _ram(0x750, bytes([0x01, 0, 0, 0x02, 0, 0, 0, 0, 0, 0, 0, 0]))
    assert rura.party_known(ram, _Prof(), list(range(20))) == [0, 1]


# --- ROM 時 -----------------------------------------------------------------

@needs_rom
def test_points_are_pinned(ident):
    assert rura.read_points(ident) == [
        0x00, 0x09, 0x01, 0x14, 0x0B, 0x0C, 0x50, 0x0A, 0x0E, 0x33,
        0x0F, 0x17, 0x02, 0x06, 0x19, 0x07, 0x12, 0x10, 0x1A, 0x11]


@needs_rom
def test_points_are_real_maps(ident):
    dirs = {e.map_id: e for e in am.read_directory(ident)}
    assert all(dirs[v].used for v in rura.read_points(ident))


@needs_rom
def test_points_with_interiors_appear_in_the_entrance_table(ident):
    """★内部 map を持つ町は、必ず入口表の行き先にも出る。

    ⚠ 出ない 2 件（スー / ハウクネス）は block が空＝内部 map が無い。
    """
    blocks = en.read_blocks(ident)
    dests = {e.dest_map for b in blocks for e in b if e.band == "load_map"}
    absent = [v for v in rura.read_points(ident) if v not in dests]
    assert absent == [0x19, 0x12]
    assert all(blocks[v] == [] for v in absent)


# --- 実機のセーブステート ---------------------------------------------------

@needs_rom
def test_savestates_show_only_the_towns_visited(ident):
    """★★ `fc2` はアリアハンだけ / それ以外はアリアハン＋レーベ。 ★★

    ⚠⚠ 表の並びが 1 つずれると、ここが別の町を指して赤くなる。
    """
    from retroux.core.bgmap import savestate as ss

    states = sorted(FCS.glob("DQ3_J.fc[0-9]"))
    if not states:
        pytest.skip("DQ3 のセーブステートが無い")
    points = rura.read_points(ident)
    got = {p.name: rura.party_known(ss.load(p).ram, ident.profile, points)
           for p in states}
    assert got["DQ3_J.fc2"] == [ALIAHAN]
    others = {k: v for k, v in got.items() if k != "DQ3_J.fc2"}
    assert others, "⚠ fc2 しか無ければ、この検査は何も見ていない"
    assert all(v == [ALIAHAN, REEVE] for v in others.values()), got


@needs_rom
def test_profile_bit_count_matches_the_table(ident):
    """⚠ `bits` を誰も読まないと、書き間違えても気づけない。"""
    c = ident.profile.data["runtime"]["rura"]
    assert int(c["bits"]) == len(rura.read_points(ident))


def test_maps_refuse_an_index_outside_the_table():
    ram = _ram(0x750, bytes([0x00, 0x00, 0x08]))          # bit19
    with pytest.raises(rura.RuraError):
        rura.known_maps(ram, _Prof(), list(range(10)), 0)
