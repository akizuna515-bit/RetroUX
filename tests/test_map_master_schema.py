"""MapMaster の受け渡し形（2026-08-02 / Phase 2）。

★★ **層を混ぜないこと**と、**unknown を丸めないこと**を固定します。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from retroux.core.bgmap import map_master, schema
from retroux.core.bgmap.rom_tiles import load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
SCHEMA = PROJECT_ROOT / "docs" / "schema" / "map-master-1.1.0.schema.json"
SAMPLE = PROJECT_ROOT / "docs" / "schema" / "sample-map-master.json"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")

#: ★街 / ダンジョン（種別2）/ ダンジョン（種別3）
KINDS = [(0x0B, 1), (0x40, 2), (0x50, 3)]


def _schema() -> dict:
    return schema.load(SCHEMA)


def test_スキーマに私が見られないキーワードが無い():
    """⚠⚠ **知らない書き方を「通った」ことにしません。**

    ★小さな検証器なので、対応していないキーワードを使ってしまうと
      検査したつもりで何も見ていないことになります。
    """
    unknown = schema.unsupported_keywords(_schema())
    assert not unknown, f"⚠ 見られないキーワード: {sorted(unknown)}"


@needs_rom
@pytest.mark.parametrize("map_id,kind", KINDS)
def test_出力がスキーマに合う(map_id, kind):
    master = map_master.build(load_prg(ROM), map_id, rom_path=ROM)
    assert master.kind == kind
    problems = schema.validate(master.to_dict(), _schema())
    assert not problems, "\n".join(problems[:10])


@needs_rom
def test_サンプルが最新の形と合う():
    """★同梱サンプルが古びたら気づけるようにします。"""
    if not SAMPLE.exists():
        pytest.skip("★サンプルがまだありません")
    sample = json.loads(SAMPLE.read_bytes().decode("utf-8"))
    assert sample["schema_version"] == map_master.SCHEMA_VERSION
    assert not schema.validate(sample, _schema())


@needs_rom
def test_版が上がったらサンプルも作り直す():
    """⚠ 形を変えたら `SCHEMA_VERSION` を上げること。"""
    assert _schema()["title"].endswith(map_master.SCHEMA_VERSION)


# --- ★ 層を混ぜない -------------------------------------------------------

@needs_rom
def test_地形と動的差分と絵は別の層に入る():
    d = map_master.build(load_prg(ROM), 0x40, rom_path=ROM).to_dict()
    assert set(d["layers"]) == {"terrain", "dynamic", "art", "knowledge"}
    # ★宝箱は dynamic にいるが、terrain からは消えていない（**基礎は不変**）
    chests = [e for e in d["layers"]["dynamic"] if e["object_type"] == "chest"]
    assert chests
    for e in chests:
        cell = next(c for c in d["layers"]["terrain"]
                    if c["logical_x"] == e["logical_x"]
                    and c["logical_y"] == e["logical_y"])
        assert cell["terrain_id"] == map_master.CHEST_TERRAIN, (
            "⚠ 基礎地形から宝箱を消してはいけません")


@needs_rom
def test_絵の層は索引ごとに1件():
    """★マスごとに持つと同じ絵が何百も並びます。"""
    d = map_master.build(load_prg(ROM), 0x40, rom_path=ROM).to_dict()
    art = d["layers"]["art"]
    assert len({e["index"] for e in art}) == len(art)


@needs_rom
def test_遊んだ記録はROMからは作らない():
    """⚠ `knowledge` は ROM から作れません。★空で渡します。"""
    d = map_master.build(load_prg(ROM), 0x40, rom_path=ROM).to_dict()
    assert d["layers"]["knowledge"] == []


# --- ★ unknown を丸めない -------------------------------------------------

@needs_rom
def test_RAMが無ければ状態はunknown():
    d = map_master.build(load_prg(ROM), 0x40, rom_path=ROM).to_dict()
    assert d["confidence"]["dynamic_state"] == "unknown"
    assert all(e["current_state"] == "unknown" for e in d["layers"]["dynamic"])


@needs_rom
def test_全マップでタイルセットが決まる():
    """★★ 2026-08-03 / Phase 1 で**全件決まりました**。

    ⚠ 以前は「街の多くは分からない」前提で、`null` が出ることを
      確かめる試験でした。★`$D0AB: LDA $1F / STA $0C / JSR $8000` を
      読んで、**種別がそのまま索引**と分かりました。
    """
    prg = load_prg(ROM)
    for map_id in range(0x00, 0x2B):
        if map_id == 0x01:
            continue                        # ★世界地図は別経路
        d = map_master.build(prg, map_id).to_dict()
        assert d["map"]["tile_set"] == [1], f"⚠ map ${map_id:02X}"
        assert d["confidence"]["tile_set"] == "confirmed"
        assert not any(u["kind"] == "tile_set" for u in d["unknowns"])


@needs_rom
def test_分からないものはunknownのまま残る():
    """⚠ 「全部分かった」ことにしません。★まだ残っています。"""
    d = map_master.build(load_prg(ROM), 0x50).to_dict()
    kinds = {u["kind"] for u in d["unknowns"]}
    assert "terrain_meaning" in kinds, "★地形IDの意味は unknown のまま"
    assert "conversion_table_size" in kinds, "★種別3 の表の件数は unknown"


@needs_rom
def test_範囲外のセルはraw_byteがnull():
    """⚠ 読めなかったバイトを 0 と書きません。"""
    master = map_master.build(load_prg(ROM), 0x40)
    assert all(c.raw_byte is not None for c in master.cells), (
        "★このマップは全セル読めるはず")
    assert master.cell_at(-1, 0) is None
    assert master.cell_at(master.width, 0) is None


@needs_rom
def test_変換表の件数が測れない種別はunknownと書く():
    """⚠ 種別3 は次の値が逆行するので測れません。"""
    d = map_master.build(load_prg(ROM), 0x50, rom_path=ROM).to_dict()
    assert d["map"]["map_type"] == 3
    assert d["confidence"]["conversion_table_size"] == "unknown"
    assert any(u["kind"] == "conversion_table_size" for u in d["unknowns"])


# --- ★ 座標の往復（property test 風）--------------------------------------

@needs_rom
@pytest.mark.parametrize("map_id,kind", KINDS)
def test_論理と画面の行き来が戻ってくる(map_id, kind):
    """★`logical -> physical -> logical` が元に戻ること。"""
    master = map_master.build(load_prg(ROM), map_id)
    span = 2 if master.halved else 1
    for cell in master.cells:
        assert len(cell.physical) == span * span
        for px, py in cell.physical:
            assert (px // span, py // span) == (cell.logical_x, cell.logical_y)


@needs_rom
def test_2x2の4マスは同じ地形で象限だけ違う():
    """★種別2以上。索引の上位は同じ、下位2ビットだけが 0-3。"""
    master = map_master.build(load_prg(ROM), 0x40)
    for cell in master.cells:
        assert len(set(i & ~0x03 for i in cell.indices)) == 1
        assert sorted(i & 0x03 for i in cell.indices) == [0, 1, 2, 3]


@needs_rom
def test_街は1論理セルが1マス():
    master = map_master.build(load_prg(ROM), 0x0B)
    assert not master.halved
    for cell in master.cells:
        assert len(cell.physical) == 1
        assert cell.physical[0] == (cell.logical_x, cell.logical_y)
