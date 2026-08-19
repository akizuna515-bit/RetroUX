"""生の地図が「歩いた先そのまま」になるまでの通し（2026-08-02 / 課題 #65）。

★★ **ここで見たいのは「配線したつもり」で届いていないこと** ★★

    bridge.lua ──(1マス9文字)──▶ ViewModel ──▶ DB の metatile_key
                                     │
                                     └─ 絵は ROM から（採取が要らない）

⚠ 一番困るのは、途中で黙って落ちて「何も起きない」こと。
  ★DB に本当に書かれたかまで見ます。
"""

from __future__ import annotations

import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
PALETTE = PROJECT_ROOT / "tools" / "fceux" / "palettes" / "FCEUX.pal"
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")


# --- Lua 側の約束 -------------------------------------------------------

def test_Luaが4枚とパレット組を出す():
    """★`map_seen_cells` が居ること、そして状態に載っていること。

    ⚠⚠ **行の字面を固定しない**（2026-08-07 に落ちた）。

      ここは前 `add("map_cells", self:map_seen_cells(radius))` という
      **1行そのもの**を見ていました。★軽量化（採取を移動時だけにする）で
      採取が `_map_sample` 越しになった途端、⚠ **直っているのに赤く**
      なりました。`docs/design/handoff-20260807.md` §5 の5番と同じ形です。

      → ★見るのは「欄が state.json に載るか」だけにします。
        ⚠ どこから値を取るかは実装の都合です。
    """
    text = BRIDGE.read_bytes().decode("utf-8")
    assert "function Bridge:map_seen_cells(" in text
    assert 'add("map_cells", ' in text
    # ⚠ 分からないときは nil を入れる（欄ごと消さない）
    assert 'add("map_cells", nil)' in text


def test_動いている最中は出さない():
    """⚠⚠ 動いている最中は 2×2 が属性の区画をまたぎ、**色を間違える**。

    ★止まっているときのスクロールは 16 の倍数（実測）。それを門にする。
    """
    text = BRIDGE.read_bytes().decode("utf-8")
    body = text.split("function Bridge:map_seen_cells(")[1]
    body = body.split("\nend")[0]
    assert "px % 16 ~= 0 or py % 16 ~= 0" in body
    assert "return nil" in body


def test_属性の読み方がPythonと同じ式():
    """⚠ Lua と Python で式がずれると、**色だけ**が静かに狂う。

    Python 側（`attribute_for`）:
        index    = (row // 4) * 8 + (col // 4)
        quadrant = ((row % 4) // 2) * 2 + ((col % 4) // 2)
        値       = (byte >> (quadrant * 2)) & 3
    """
    text = BRIDGE.read_bytes().decode("utf-8")
    body = text.split("function Bridge:map_seen_cells(")[1].split("\nend")[0]
    assert "0x3C0 + math.floor(nr / 4) * 8 + math.floor(nc / 4)" in body
    assert "(math.floor(nr % 4 / 2) * 2" in body
    assert "+ math.floor(nc % 4 / 2)) * 2" in body


def test_古い出し方を消していない():
    """⚠ 指示書 §15.5「新方式が安定するまで現行表示を削除しない」。"""
    text = BRIDGE.read_bytes().decode("utf-8")
    assert "function Bridge:map_seen_tiles(" in text
    # ⚠ 字面ではなく**欄があること**を見る（★上の注意と同じ理由）
    assert 'add("map_tiles", ' in text


def test_受け取る側にも欄がある():
    from retroux.core.bridge.state_reader import GameState

    assert "map_cells" in GameState.__dataclass_fields__
    assert "map_tiles" in GameState.__dataclass_fields__


def test_状態を読むと欄が埋まる(tmp_path):
    """★JSON から本当に取り出せるか（欄を足しただけで読めない、を防ぐ）。"""
    import json

    from retroux.core.bridge.state_reader import StateReader

    path = tmp_path / "state.json"
    path.write_text(json.dumps({"map_cells": "A1A5A0A43"}), encoding="utf-8")
    got = StateReader(path).read()
    assert got.map_cells == "A1A5A0A43"


# --- ★★ 通し: 歩いた先が DB に入るか ★★ ------------------------------

@needs_rom
def test_見たマスの絵がDBまで届く(tmp_path):
    """★★ **これが本題**。⚠ 「つないだつもり」で届かないのが一番困る。"""
    from dq2rom.monsters.palette import load_nes_palette

    from retroux.core.bgmap.catalog import AssetStore
    from retroux.core.bgmap.live import UNKNOWN_CELL, LiveMetatiles
    from retroux.core.bgmap.rom_assets import RomTileSource
    from retroux.core.bridge.state_reader import GameState
    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder
    from retroux.ui.view_model import ViewModel

    db = Database(tmp_path / "map.sqlite3")
    db.register_rom("deadbeef", "DQ2_J", "JP")
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    rec = Recorder(db, "deadbeef", events, tmp_path / "command.json")
    store = AssetStore(tmp_path / "assets")
    store.prepare()
    live = LiveMetatiles(RomTileSource(ROM), store,
                         load_nes_palette(PALETTE))

    radius = 1
    cells = {(0, 0): "A1A5A0A43", (1, 0): "A3A7A2A63"}
    packed = "".join(
        cells.get((dx, dy), UNKNOWN_CELL)
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1))

    vm = ViewModel(recorder=rec, db=db, rom_hash="deadbeef",
                   map_meta={},
                   view_radius=radius, live_metatiles=live)
    state = GameState(map_id=0x3F, map_x=10, map_y=10,
                      map_data_pointer=0xA0B3, map_view_radius=radius,
                      map_cells=packed)
    added = vm.note_position(state)
    assert added > 0, "★マスが1つも記録されなかった"

    # ★★ DB に metatile_key が入っているか
    rows = db._conn.execute(
        "SELECT x, y, metatile_key FROM VisitedTile"
        " WHERE metatile_key IS NOT NULL").fetchall()
    got = {(r["x"], r["y"]): r["metatile_key"] for r in rows}
    assert got, "⚠ 絵が1マスも結びついていない（配線が届いていない）"
    # ★見たマスの位置に入っている（主人公は (10,10)）
    assert (10, 10) in got and (11, 10) in got
    # ⚠ 見ていないマスには入らない（指示書 §2.2）
    assert (10, 9) not in got
    # ★絵の PNG も出来ている
    assert store.image_path(got[(10, 10)], "1x") is not None
    db.close()


@needs_rom
def test_絵の係が無くても地図は動く(tmp_path):
    """⚠ 新しい仕組みが無い環境でも、これまでどおり記録できること。"""
    from retroux.core.bridge.state_reader import GameState
    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder
    from retroux.ui.view_model import ViewModel

    db = Database(tmp_path / "map.sqlite3")
    db.register_rom("deadbeef", "DQ2_J", "JP")
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    rec = Recorder(db, "deadbeef", events, tmp_path / "command.json")
    vm = ViewModel(recorder=rec, db=db, rom_hash="deadbeef",
                   map_meta={}, view_radius=1)
    state = GameState(map_id=0x3F, map_x=10, map_y=10,
                      map_data_pointer=0xA0B3, map_view_radius=1,
                      map_cells="A1A5A0A43")
    assert vm.note_position(state) > 0
    db.close()


@needs_rom
def test_表の外のマップでは絵を付けない(tmp_path):
    """⚠⚠ **推測で描かない。** ★マスを見た記録は残るが、絵は付かない。

    ⚠ 2026-08-02 まではここに城 `$07` を使っていました。
      ★Phase 1（2026-08-03）で全109マップが描けるようになったので、
        **ヘッダ表の外**の `map_id` で確かめます。
    """
    from dq2rom.monsters.palette import load_nes_palette

    from retroux.core.bgmap.catalog import AssetStore
    from retroux.core.bgmap.live import LiveMetatiles
    from retroux.core.bgmap.rom_assets import RomTileSource
    from retroux.core.bridge.state_reader import GameState
    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder
    from retroux.ui.view_model import ViewModel

    db = Database(tmp_path / "map.sqlite3")
    db.register_rom("deadbeef", "DQ2_J", "JP")
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    rec = Recorder(db, "deadbeef", events, tmp_path / "command.json")
    store = AssetStore(tmp_path / "assets")
    store.prepare()
    live = LiveMetatiles(RomTileSource(ROM), store, load_nes_palette(PALETTE))
    vm = ViewModel(recorder=rec, db=db, rom_hash="deadbeef",
                   map_meta={},
                   view_radius=0, live_metatiles=live)
    state = GameState(map_id=0x99, map_x=5, map_y=5,
                      map_data_pointer=0x8E83, map_view_radius=0,
                      map_cells="A1A5A0A43")
    vm.note_position(state)
    rows = db._conn.execute(
        "SELECT metatile_key FROM VisitedTile"
        " WHERE metatile_key IS NOT NULL").fetchall()
    assert not rows, "★確かめていないマップに絵を付けてしまった"
    # ★理由は数に残る（黙って捨てない）
    assert live.tally.no_tileset == 1
    db.close()



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ 上の `test_属性の読み方がPythonと同じ式` は、式が**文字として**
#   書いてあるかを見ています。★書き方を変えただけで赤くなり
#   （直っているのに赤い）、⚠ 括弧の位置をひとつ動かして**意味が変わっても
#   緑**です。
#
# ★ここでは Python 側（`attribute_for`）に**答えを作らせ**、
#   同じ入力で Lua を走らせて**全パターン突き合わせ**ます。
#   ⚠ ずれると「色だけ」が静かに狂い、地図に記録されると直せません。
# =====================================================================

import os          # noqa: E402
import subprocess  # noqa: E402
import sys         # noqa: E402

import pytest      # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_ATTR_HARNESS = (_ROOT / "research" / "probes" / "active"
                 / "attribute_formula_test.lua")
_ATTR_RUNNER = _ROOT / "research" / "probes" / "reusable" / "lua_run.py"


def _expected_cases():
    """★Python 側の答えを作る（⚠ 1バイトが受け持つ 4×4 を**全部**）。

    ## ⚠⚠ **全部を同じ値にしないこと**（2026-08-12 の反省）

      ★最初は `bytes([byte]) * 64` で作っていました。⚠ どのバイトも
        同じなので、**どの index を読んでも同じ答え**になり、
        「列と行を入れ替える」という壊し方でも**緑のまま**でした。
      ★index が意味を持つよう、**バイトごとに違う値**を入れます。
    """
    from retroux.core.bgmap.reconstruct import attribute_for

    cases = []
    # ★並びを確かめる用（★4つの組の詰め方を変えた 8 通り）
    #   ⚠ ただし index を確かめるため、**位置ごとに回転**させる。
    patterns = [0xE4, 0x1B, 0x00, 0xFF, 0x4E, 0xB1, 0x39, 0x93]
    for seed in patterns:
        attr = bytes(((seed + i * 37) & 0xFF) for i in range(64))
        for row in range(16):
            for col in range(32):
                cases.append((list(attr), col, row,
                              attribute_for(attr, col, row)))
    # ★ビットの並びだけを見る用（★全部同じ値。上と役割が違う）
    for seed in (0xE4, 0x1B):
        attr = bytes([seed]) * 64
        for row in range(4):
            for col in range(4):
                cases.append((list(attr), col, row,
                              attribute_for(attr, col, row)))
    return cases


@pytest.fixture(scope="module")
def attr_lua(tmp_path_factory):
    if not (_ATTR_RUNNER.exists() and _ATTR_HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    cases = _expected_cases()
    assert cases, "★答えが1件も作れていない"

    # ★Lua が読める形で書き出す（⚠ 表は 1 始まり）
    lines = ["return {"]
    for attr, col, row, value in cases:
        lines.append("  { attr = { " + ", ".join(str(v) for v in attr)
                     + f" }}, col = {col}, row = {row}, value = {value} }},")
    lines.append("}")
    path = tmp_path_factory.mktemp("attr") / "expected.lua"
    path.write_text("\n".join(lines), encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(_ATTR_RUNNER), str(_ATTR_HARNESS)],
        cwd=str(_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8",
             "RETROUX_ATTR_EXPECTED": str(path)})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _attr_ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_属性の式がPythonと全パターン一致する(attr_lua):
    """⚠⚠ **ここがずれると色だけが静かに狂います。**

    ★8通りのバイト × 8行 × 8列 = 512 件を突き合わせます。
    """
    assert "すべて合格" in attr_lua, attr_lua
    assert _attr_ok(attr_lua, "★Python と全一致"), attr_lua


def test_照合を1件もせずに合格しない(attr_lua):
    """⚠ 期待値が空でも「合格」になる作りにしないこと。"""
    assert _attr_ok(attr_lua, "★1件も照合しないまま合格にしない"), attr_lua


def test_ビットの並びを固定する(attr_lua):
    """★下位から 左上・右上・左下・右下（⚠ 並びが逆だと色が入れ替わる）。"""
    for label in ("★左上（列0 行0）は下位2ビット", "★右上（列2 行0）",
                  "★左下（列0 行2）", "★右下（列2 行2）"):
        assert _attr_ok(attr_lua, label), attr_lua


def test_2かける2の中は同じ組(attr_lua):
    """★1マス（2×2 タイル）が1つの組に収まる、という前提そのもの。"""
    assert _attr_ok(attr_lua, "⚠ 左上の中の (1,1) も同じ組"), attr_lua


def test_表の外を読んでも落ちない(attr_lua):
    assert _attr_ok(attr_lua, "⚠ 表が空でも 0"), attr_lua
    assert _attr_ok(attr_lua, "⚠ 行が表の外でも 0"), attr_lua
