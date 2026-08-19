"""世界地図を ROM の絵で描く（2026-08-11 / `world_art.py`）。

★★ ここで固定するのは3つです ★★

1. **地形ID → メタタイル**の表が `$83B3` の 32 件であること（★ROM の中身）
2. 索引が表の中に収まること（⚠ 丸めない・埋めない）
3. **見たマスしか返さない**こと（指示書 §2.2 / ★開示を増やさない）

⚠ 「実測と合うか」は `research/probes/active/world_metatile_check.py`。
  遊んだ記録（`work/`）が要るので、テストからは外してあります。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap import world_art as WA
from retroux.core.bgmap.rom_tiles import load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
PALETTE = PROJECT_ROOT / "tools" / "fceux" / "palettes" / "FCEUX.pal"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
needs_palette = pytest.mark.skipif(not PALETTE.exists(), reason="パレットが無い")


@pytest.fixture(scope="module")
def prg():
    if not ROM.exists():
        pytest.skip("ROM が無い")
    return load_prg(ROM)


@pytest.fixture(scope="module")
def art(prg):
    return WA.WorldArt(prg)


# --- ★ 変換表（`$DD64` の種別0）------------------------------------------

@needs_rom
def test_変換表の場所がコードと合っている(prg):
    """★`$DC6F` の**種別0**が `$83B3` を指している。

    ⚠ 番地を書き写したのではありません。ROM の中身を読んで確かめます。
    """
    assert WA.TERRAIN_TABLE == 0x83B3
    off = 0x1DC6F + WA.WORLD_KIND * 2
    assert prg[off] | (prg[off + 1] << 8) == WA.TERRAIN_TABLE


@needs_rom
def test_表は32件で次の表にぶつかる(prg):
    """★件数は**次の表との差**で決まります（160 = 32 × 5）。

    ⚠ 32 件目の先は種別1（街）の表です。★はみ出せば別の地形の絵が出ます。
    """
    from retroux.core.bgmap.dungeon_map import TERRAIN_TABLES

    assert WA.TERRAIN_COUNT == 32
    assert (TERRAIN_TABLES[1] - TERRAIN_TABLES[0]
            == WA.TERRAIN_COUNT * 5)


@needs_rom
def test_表の中身が実測と合う(prg):
    """★★ **これが「変換表である」裏づけ**（2026-08-11 の答え合わせ）。

    実測（遊んで見た 21,215 マス）で、地形IDごとに一番多かった
    メタタイル4枚が、下の値と**1バイトも違わず**一致しました。
    ⚠ 手で決めた値ではありません。

    ★`$14`（20）以降は**壁向き補正でしか出てこない**海岸線の角です。
      ここが合うことが、`wall_shape` を通す経路の裏づけになります。
    """
    want = {
        1: ((0x90, 0x90, 0x90, 0x90), 3),     # ★草原
        2: ((0x91, 0x91, 0x91, 0x91), 1),     # ★砂漠
        3: ((0xA2, 0xA2, 0x9F, 0x9F), 3),     # ★林
        4: ((0xA1, 0xA0, 0xA0, 0xA1), 0),     # ★★海（境界タイルIDも $04）
        7: ((0x9C, 0x9E, 0x9B, 0x9D), 1),
        20: ((0xA4, 0xA6, 0xA3, 0xA5), 0),    # ★海岸線（角）
        27: ((0xA5, 0xAB, 0xAE, 0xAF), 0),
    }
    for index, (tiles, group) in want.items():
        assert WA.table_entry(prg, index) == (tiles, group), f"索引 {index}"


@needs_rom
def test_表の外は丸めずに例外(prg):
    """⚠⚠ **黙って 0 番を返さない。**

    ★丸めると、間違った絵が「正しい絵の顔」で出てきます。
    """
    with pytest.raises(WA.WorldArtError):
        WA.table_entry(prg, WA.TERRAIN_COUNT)
    with pytest.raises(WA.WorldArtError):
        WA.table_entry(prg, -1)


@needs_rom
def test_ヘッダが256x256と言っている(prg):
    """★設定で補っていた値（実測 256×256）は ROM にも書いてあります。

    ⚠ ヘッダ byte1/byte2 は **幅-1 / 高さ-1**（`$DFAE: INC $0C`）。
    """
    assert WA.header_size(prg) == (WA.WORLD_SIZE, WA.WORLD_SIZE)


# --- ★ 索引（地形＋壁向き補正）--------------------------------------------

@needs_rom
def test_全部のマスが表の中に収まる(art):
    """★★ 256×256 のどこにも「表の外」が出ない。

    ⚠ ここが破れたら、**丸めずに**表の件数を疑うこと。
    """
    used = art.used_indices()
    assert used, "★1マスも読めていない"
    assert max(used) < WA.TERRAIN_COUNT
    assert sum(used.values()) == WA.WORLD_SIZE * WA.WORLD_SIZE, (
        "⚠ 読めないマスがある（★0 で埋めないこと）")


@needs_rom
def test_海だけが壁向き補正を受ける(art):
    """★`$DE2C: CMP #$04` — 中心が `$04`（海）でなければ素通し。

    ⚠ 補正後にだけ現れる索引（`$14`-`$1B`）は、素の地形には出ません。
    """
    from retroux.core.bgmap.wall_shape import CENTRE_VALUE

    changed = [(x, y) for y in range(art.size) for x in range(art.size)
               if art.index[y][x] != art.terrain[y][x]]
    assert changed, "★海岸線が1つも出ていない"
    assert all(art.terrain[y][x] == CENTRE_VALUE for x, y in changed)


@needs_rom
def test_近傍は端で巻き戻る(art):
    """⚠ `$DE3A: ADC $12` は **8 ビット**の足し算。

    ★x=255 の右隣は x=0 です。★ここを「枠の外」にすると、
      端のマスだけ海岸線が余計に出ます。
    """
    assert art._terrain_wrapped(art.size, 10) == art.terrain[10][0]
    assert art._terrain_wrapped(-1, 10) == art.terrain[10][art.size - 1]


# --- ★★ 見たマスしか返さない（指示書 §2.2）-------------------------------

@needs_rom
def test_渡したマスしか返さない(art):
    """★★★ **開示を増やさない。** ROM から全部読めても、返しません。"""
    seen = {(10, 10), (11, 10), (200, 130)}
    cells = art.cells(seen)
    assert {(c.x, c.y) for c in cells} == seen


@needs_rom
def test_何も渡さなければ何も返さない(art):
    """⚠ 「渡さなければ全部」を既定にしない（★開示の穴を作らない）。"""
    assert art.cells(None) == []
    assert art.cells(set()) == []


@needs_rom
def test_枠の外は返さない(art):
    assert art.cells({(-1, 0), (0, -1), (256, 0), (0, 256)}) == []


# --- ★ 1マス1色（ミニマップ）---------------------------------------------

def test_平均色は真っ黒にならない():
    """⚠⚠ **最頻色にすると森・山が真っ黒になりました**（2026-08-11）。

    輪郭線の黒が一番多いためです。★それでは「黒塗り」を作り直すことに
      なるので、平均にしています。
    """
    rows = [[(0, 0, 0, 255)] * 3 + [(0, 255, 0, 255)] * 1 for _ in range(4)]
    assert WA.average_rgb(rows) == (0, 63, 0)


def test_色は6文字で渡す():
    """★4ビットへ丸めない（`tile_color` が6文字も読みます）。"""
    assert WA.hex_color((8, 123, 238)) == "087BEE"


@needs_rom
@needs_palette
def test_ROMの色に真っ黒な地形が無い(prg):
    """★★ 黒塗りの根治を数で確かめる。

    ⚠ 1マスでも真っ黒があると、「見たのに黒い」が復活します。
    """
    from dq2rom.monsters.palette import load_nes_palette

    from retroux.core.bgmap.rom_assets import RomTileSource

    source = RomTileSource(ROM)
    maptiles = source.for_map(WA.WORLD_MAP_ID)
    assert maptiles is not None, "★世界地図の CHR とパレットが取れない"
    colors = WA.terrain_colors(prg, maptiles, load_nes_palette(PALETTE))
    assert len(colors) == WA.TERRAIN_COUNT
    assert all(sum(c) > 24 for c in colors.values()), (
        f"⚠ 真っ黒に近い地形がある: "
        f"{[i for i, c in colors.items() if sum(c) <= 24]}")
    # ★海（索引4）は青い。⚠ 「それらしい色」ではなく ROM のパレットから
    r, g, b = colors[4]
    assert b > r and b > g, f"★海が青くない: {colors[4]}"


# --- ⚠ 経路を混ぜない -----------------------------------------------------

def test_ダンジョンの読み方を借りていない():
    """★★ 借りてよいのは**表の在り処**だけ（`$DD64` は種別共通）。

    ⚠ 読み方（`DungeonMap` の線形読み）は世界地図には使えません。
    """
    import ast

    tree = ast.parse(pathlib.Path(WA.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
    assert "DungeonMap" not in imported
    assert imported >= {"TERRAIN_TABLES", "TABLE_ENTRY"}


def test_MapMasterは世界地図を受けつけないまま():
    """★種別0 は別経路のままにします（⚠ 混ぜない）。"""
    from retroux.core.bgmap import map_master

    assert 0 not in map_master.SUPPORTED_KINDS


# --- ★ 地図プレゼンタ（★画面は建てない）----------------------------------

class _StubLive:
    """PNG を書かない偽者。⚠ 絵の材料（CHR・パレット）は**本物**を使う。

    ★`key_for` だけ差し替えます（ディスクへ書かないため）。
    """

    def __init__(self) -> None:
        from dq2rom.monsters.palette import load_nes_palette

        from retroux.core.bgmap.rom_assets import RomTileSource

        self.source = RomTileSource(ROM)
        self.nes_palette = load_nes_palette(PALETTE)
        self.asked: list = []

    def key_for(self, map_id, tiles, group):
        self.asked.append((map_id, tuple(tiles), group))
        return "-".join(f"{t:02X}" for t in tiles) + f"-{group}"


class _StubVM:
    """⚠ `world_layer` / `detail` が触るところだけ。★余計な口は持たせない。"""

    map_meta: dict = {}

    def __init__(self, live, tiles) -> None:
        self.live_metatiles = live
        self._tiles = tiles

    def visited_tiles(self, _map_id, _ptr):
        return list(self._tiles)

    def map_size(self, _map_id):
        return (WA.WORLD_SIZE, WA.WORLD_SIZE)

    def map_type(self, _map_id):
        return "overworld"

    def map_label(self, _map_id, _ptr):
        return "世界地図"

    def location_of_map(self, _map_id):
        return None


@needs_rom
@needs_palette
def test_世界地図は見たマスだけをROMの色で返す():
    """★★ 依頼者の決定「見た範囲だけ／色は ROM から」★★"""
    from retroux.ui.map.presenter import MapPresenter

    live = _StubLive()
    observed = [(10, 10, 3, "000"), (11, 10, 1, None), (200, 130, 9, "abc")]
    p = MapPresenter(_StubVM(live, observed))
    out = p.world_layer(live.source.prg, live, WA.WORLD_MAP_ID, 0x8000,
                        observed)

    assert [(x, y) for x, y, _v, _c in out["tiles"]] == [
        (10, 10), (11, 10), (200, 130)]
    assert out["width"] == out["height"] == WA.WORLD_SIZE
    assert out["colored"] is True
    # ⚠ 観測の色（"000" = 黒塗り）は**使わない**。★ROM の色に置き換わる
    for _x, _y, _visits, color in out["tiles"]:
        assert len(color) == 6 and color != "000000"
    # ★歩いた回数は残す（色が読めないときの濃さに使う）
    assert [v for _x, _y, v, _c in out["tiles"]] == [3, 1, 9]


@needs_rom
@needs_palette
def test_枠の外の記録は黙って捨てず数える():
    from retroux.ui.map.presenter import MapPresenter

    live = _StubLive()
    observed = [(10, 10, 1, None), (300, 10, 1, None)]
    p = MapPresenter(_StubVM(live, observed))
    out = p.world_layer(live.source.prg, live, WA.WORLD_MAP_ID, 0x8000,
                        observed)
    assert out["outside"] == 1
    assert len(out["tiles"]) == 1


@needs_rom
@needs_palette
def test_ポインタが食い違えば組まない():
    """⚠ 切替の一瞬に別のマップのポインタで記録されたぶん（2026-07-30）。"""
    from retroux.ui.map.presenter import MapPresenter

    live = _StubLive()
    p = MapPresenter(_StubVM(live, []))
    out = p.world_layer(live.source.prg, live, WA.WORLD_MAP_ID, 0x9999,
                        [(10, 10, 1, None)])
    assert "tiles" not in out
    assert "$8000" in out["note"]


@needs_rom
@needs_palette
def test_材料は一度だけ作る():
    """⚠⚠ `WorldArt` は 0.3 秒かかる。★歩くたびに作り直さないこと。

    （`_draw()` は 0.2 秒ごとに呼ばれます）
    """
    from retroux.ui.map.presenter import MapPresenter

    live = _StubLive()
    p = MapPresenter(_StubVM(live, []))
    args = (live.source.prg, live, WA.WORLD_MAP_ID, 0x8000,
            [(10, 10, 1, None)])
    p.world_layer(*args)
    first = p._world_cache
    p.world_layer(*args)
    assert p._world_cache is first
    # ★絵の鍵を引くのも 32 件だけ（マスの数ぶん引かない）
    assert len(live.asked) == WA.TERRAIN_COUNT


@needs_rom
@needs_palette
def test_世界地図はrom_layerから世界地図の道へ回る():
    """★`rom_layer` は種別で振り分けます（⚠ MapMaster へは行かない）。"""
    from retroux.ui.map.presenter import MapPresenter

    live = _StubLive()
    observed = [(10, 10, 1, None)]
    p = MapPresenter(_StubVM(live, observed))
    out = p.rom_layer(WA.WORLD_MAP_ID, 0x8000, observed)
    assert out.get("colored") is True


# --- ★ 描く側（★1マス1画素の絵に ROM の色が乗るか）------------------------

def test_地図の絵にROMの色がそのまま乗る():
    """★`tile_color` は 6 文字（`"RRGGBB"`）も読む（2026-08-11）。

    ⚠ 4 ビットへ丸めると、隣り合う地形が同じ色に潰れます。
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from retroux.ui.map.canvas import TrailView, tile_color

    # ★昔の形（画面から拾った 3 文字）も読めたままにする
    assert tile_color("F00").name() == "#ff0000"
    assert tile_color("087BEE").name() == "#087bee"
    assert tile_color("08") is None          # ⚠ 中途半端な長さは None
    assert tile_color("ZZZZZZ") is None      # ⚠ 16 進でないものも None

    QApplication.instance() or QApplication([])
    view = TrailView()
    view.set_data([(1, 1, 1, "087BEE"), (2, 1, 1, None)], 4, 4, None,
                  "overworld")
    image = view.build_image(4, 4)
    assert image.pixelColor(1, 1).name() == "#087bee"
    # ⚠ 色が分からないマスは**推測しない**（歩いた印の色になる）
    assert image.pixelColor(2, 1).name() != "#087bee"


@needs_rom
@needs_palette
def test_地図の中身はROM由来になる():
    """★★ `window.py` が呼ぶのはここ（`detail`）です。

    ⚠ 絵（メタタイル）は倍率 ×4 では並べられないので、
      **色だけ**が ROM 由来という道を通ります（`colored`）。
      ★ここが `metatiles` の有無で切り替わっていると、世界地図は
        観測の色（黒塗りの元）に戻ってしまいます。
    """
    from retroux.ui.map.presenter import MapPresenter

    live = _StubLive()
    observed = [(10, 10, 4, "000"), (11, 10, 2, None)]
    detail = MapPresenter(_StubVM(live, observed)).detail(
        WA.WORLD_MAP_ID, 0x8000)

    assert detail.source == "rom"
    assert detail.width == detail.height == WA.WORLD_SIZE
    assert [(x, y) for x, y, _v, _c in detail.tiles] == [(10, 10), (11, 10)]
    assert all(len(c) == 6 for _x, _y, _v, c in detail.tiles)
