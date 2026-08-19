"""見た所の記録（DB への出し入れ）。

★2026-08-01 に `test_map_trail.py`（788 実質行）から切り出しました（指示書 §11.3）。
  ⚠ **内容は1件も減らしていません。**機械で切り、件数で確かめています。
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest
import yaml

# ★既定の倍率は**定数から読む**（数字を写さない / 2026-08-01）
from retroux.ui.map.canvas import TrailView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.bridge.state_reader import GameState, _parse  # noqa: E402
from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.ui.main_window import MainWindow  # noqa: E402
from retroux.ui.map_window import MapWindow, load_map_meta  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402

MAP_PATH = (pathlib.Path(__file__).resolve().parents[1]
            / "retroux" / "plugins" / "dq2" / "memory_map.yaml")


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        yield QApplication([])
    except Exception as exc:                          # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")


@pytest.fixture(scope="module")
def mm() -> dict:
    return yaml.safe_load(MAP_PATH.read_text(encoding="utf-8"))


META = {
    0x07: {"map_id": 7, "type": "town", "width": 23, "height": 23,
           "border_tile": 1, "palette": 13, "data_pointer": "0x8E83"},
    0x59: {"map_id": 0x59, "type": "dungeon_b", "width": 11, "height": 11,
           "border_tile": 0x24, "palette": 0x5B, "data_pointer": "0xA48B"},
}


@pytest.fixture
def vm(tmp_path, mm):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    view_model = ViewModel(
        Recorder(db, "HASH", events, tmp_path / "command.json"), db, "HASH",
        monsters={int(k): str(v) for k, v in mm["monsters"].items()},
        monster_stats={int(k): v for k, v in mm["monster_stats"].items()},
        map_meta=META,
        view_radius=0,          # ★既定のテストは1マスだけ（範囲は別に試す）
    )
    yield view_model, tmp_path
    db.close()


def field(map_id=0x07, x=5, y=6, ptr=0x8E83, **kw) -> GameState:
    return GameState(in_battle=False, fresh=True, map_id=map_id,
                     map_x=x, map_y=y, map_data_pointer=ptr, **kw)

# --- 1. 記録するもの・しないもの ---------------------------------------


def test_records_where_you_walked(vm):
    view_model, _ = vm
    assert view_model.note_position(field(x=1, y=2)) == 1
    assert view_model.visited_tiles(0x07, 0x8E83) == [(1, 2, 1, None)]

# --- 1b. 「画面に映った範囲」を記録する（依頼者の追加指示）--------------


def test_records_the_visible_square_around_you(vm):
    """★★ 立ったマスではなく、**中心から ±radius マス**を記録する。"""
    view_model, _ = vm
    view_model.view_radius = 2
    added = view_model.note_position(field(x=10, y=10))
    assert added == 25, f"5x5 のはずが {added}"
    seen = {(x, y) for x, y, _n, _c in view_model.visited_tiles(0x07, 0x8E83)}
    assert (8, 8) in seen and (12, 12) in seen
    assert (7, 10) not in seen, "範囲より広く 記録 している"


def test_does_not_record_negative_coordinates(vm):
    """⚠★ 負の座標は記録しない（枠からはみ出した足跡を作らない）。

    ★★ **2026-08-02 に契約を変えました** ★★
      もとは「ROM の大きさ（map 07 なら 23×23）の外も切る」でしたが、
      ⚠ **ROM の値のほうが小さい**と実測で分かりました:
          map $3D  ROM 15×17  ->  実際 29/33
      ★切っていたせいで、記録も現在地の印も失われていました
        （依頼者「save3では表示されない（印）」）。

    ⚠ さらに悪いことに、`VisitedTile` を見て「収まっている」と
      確かめていました。**切った後を見ていた**ので当たり前です
      （★測り方が循環していた）。

    ★いまは座標が 1 バイトであることだけを守ります。
    """
    view_model, _ = vm
    view_model.view_radius = 2
    view_model.note_position(field(x=0, y=0))
    seen = {(x, y) for x, y, _n, _c in view_model.visited_tiles(0x07, 0x8E83)}
    assert all(x >= 0 and y >= 0 for x, y in seen)
    assert len(seen) == 9, f"0..2 の 3x3 のはずが {len(seen)}"


def test_records_beyond_the_rom_size(vm):
    """★★ ROM が言う大きさより外でも記録する（2026-08-02）。

    ⚠ ROM の読み方が未解明なので、**見えた事実のほうを信じます**。
    """
    view_model, _ = vm
    view_model.view_radius = 1
    view_model.note_position(field(x=22, y=22))     # map 07 は ROM 23×23
    seen = {(x, y) for x, y, _n, _c in view_model.visited_tiles(0x07, 0x8E83)}
    assert (23, 23) in seen, "★ROM の外を切り捨ててしまっている"


def test_does_not_record_beyond_one_byte(vm):
    """⚠ 座標は 1 バイト。★そこだけは守る（壊れた値を貯めない）。"""
    view_model, _ = vm
    view_model.view_radius = 2
    view_model.note_position(field(x=255, y=255))
    seen = {(x, y) for x, y, _n, _c in view_model.visited_tiles(0x07, 0x8E83)}
    assert all(x <= 255 and y <= 255 for x, y in seen)


def test_unknown_map_size_does_not_clip(vm):
    """★大きさを知らないマップでは切らない（推測で狭めない）。"""
    view_model, _ = vm
    view_model.view_radius = 1
    added = view_model.note_position(field(map_id=0x77, ptr=0x8888, x=50, y=50))
    assert added == 9


def test_does_not_record_during_battle(vm):
    """★★ 戦闘中の座標は足跡ではない。記録しない。"""
    view_model, _ = vm
    state = field(x=3, y=4)
    state.in_battle = True
    assert view_model.note_position(state) == 0
    assert view_model.visited_tiles(0x07, 0x8E83) == []


def test_zero_is_a_real_coordinate(vm):
    """⚠★ (0,0) は正しい座標。**None と混ぜない**（playbook の原則）。"""
    view_model, _ = vm
    assert view_model.note_position(field(x=0, y=0)) == 1
    assert view_model.visited_tiles(0x07, 0x8E83) == [(0, 0, 1, None)]


@pytest.mark.parametrize("kw", [
    {"map_id": None}, {"x": None}, {"y": None}, {"ptr": None},
])
def test_missing_values_are_not_recorded(vm, kw):
    """★読めていない値で足跡を作らない（推測で埋めない）。"""
    view_model, _ = vm
    assert view_model.note_position(field(**kw)) == 0
    assert view_model.visited_maps() == []


def test_read_only_does_not_write(vm):
    """⚠ 閲覧専用のときは書かない（取り込みプロセスと二重書きしない）。"""
    view_model, _ = vm
    view_model.read_only = True
    assert view_model.note_position(field()) == 0
    assert view_model.visited_maps() == []


def test_same_tile_does_not_pile_up(vm):
    """★同じマスに十数フレーム居る。行が増え続けないこと。"""
    view_model, _ = vm
    for _ in range(20):
        view_model.note_position(field(x=4, y=4))
    tiles = view_model.visited_tiles(0x07, 0x8E83)
    assert len(tiles) == 1
    assert tiles[0][2] == 20, "通った回数を数えていない"


def test_only_the_first_visit_is_new(vm):
    view_model, _ = vm
    assert view_model.note_position(field(x=9, y=9)) == 1
    assert view_model.note_position(field(x=9, y=9)) == 0


def test_the_pointer_is_part_of_the_key(vm):
    """★★ データ位置（`$23-$24`）も鍵に含めること。

    記録を map_id だけで束ねると、別の場所の記録が混ざる。
    ⚠ ここは **DB の性質**を確かめる（ViewModel は下の
      `test_mismatched_pointer_is_not_recorded` で食い違いを弾く）。
    """
    view_model, _ = vm
    db = view_model.db
    db.mark_visited("HASH", 0x07, 0x8E83, 1, 1)
    db.mark_visited("HASH", 0x07, 0x9999, 2, 2)
    assert view_model.visited_tiles(0x07, 0x8E83) == [(1, 1, 1, None)]
    assert view_model.visited_tiles(0x07, 0x9999) == [(2, 2, 1, None)]
    assert len(view_model.visited_maps()) == 2


def test_mismatched_pointer_is_not_recorded(vm):
    """★★ 実データで見つかった不具合（2026-07-30）★★

    記録の中に **`map_id`=01（ワールドマップ）なのに町のポインタ**という組が
    3つあり、それぞれ **ちょうど 225 マス（15×15 = 記録1回ぶん）**だった。
    → マップの切り替わりの瞬間に `$31` と `$23-$24` が食い違ったまま
      1回だけ記録されていた。地図の一覧に幽霊のような項目が並ぶ。

    ROM のヘッダ表と突き合わせて弾く。
    """
    view_model, _ = vm
    assert view_model.note_position(field(map_id=0x07, ptr=0x8E83)) == 1
    assert view_model.note_position(field(map_id=0x07, ptr=0x9999)) == 0
    assert view_model.visited_tiles(0x07, 0x9999) == []


def test_unknown_map_is_still_recorded(vm):
    """⚠ 表に無いマップは判断できないので**通す**。

    分からないことを理由に、正しい記録まで捨てない。
    """
    view_model, _ = vm
    assert view_model.note_position(field(map_id=0x77, ptr=0x8888)) == 1


def test_recording_failure_does_not_break_anything(vm, monkeypatch):
    """⚠ 記録に失敗しても本体は止めない（地図が欠けるだけ）。"""
    view_model, _ = vm

    def boom(*_a, **_k):
        raise RuntimeError("DB が壊れた")

    monkeypatch.setattr(view_model.db, "mark_visited", boom)
    assert view_model.note_position(field()) == 0
    assert view_model.visited_maps() == []

# --- 2. state.json の読み取り ------------------------------------------


def test_state_reader_keeps_zero():
    """⚠★ `raw.get(...) or None` と書くと **0 が None になる**。"""
    got = _parse({"map_id": 0, "map_x": 0, "map_y": 0, "map_data_pointer": 0})
    assert (got.map_id, got.map_x, got.map_y) == (0, 0, 0)
    assert got.map_data_pointer == 0


def test_state_reader_missing_position_is_none():
    got = _parse({})
    assert got.map_id is None and got.map_x is None


def test_state_reader_ignores_junk():
    got = _parse({"map_x": "ここ", "map_y": True})
    assert got.map_x is None and got.map_y is None

# --- 3. maps.json ------------------------------------------------------


def test_map_meta_is_optional(tmp_path):
    """★無くても動く（推測の大きさを出さない）。"""
    assert load_map_meta(None) == {}
    assert load_map_meta(tmp_path / "nope.json") == {}


def test_map_meta_survives_broken_json(tmp_path):
    p = tmp_path / "maps.json"
    p.write_text("{壊れている", encoding="utf-8")
    assert load_map_meta(p) == {}


def test_map_meta_is_read(tmp_path):
    p = tmp_path / "maps.json"
    p.write_text(json.dumps({"maps": [
        {"map_id": 7, "width": 23, "height": 23},
        {"map_id": "だめ"},
    ]}), encoding="utf-8")
    got = load_map_meta(p)
    assert got[7]["width"] == 23
    assert len(got) == 1, "読めない行で落ちている"

# --- 6. 画面の色を地図に写す（2026-07-29 / 依頼者の指摘）----------------
#
# > マップが、周りが記憶出来ていないように思える（画面とMAPの色が違う）


def _packed(radius: int, color: str = "4A9") -> str:
    side = radius * 2 + 1
    return color * (side * side)


def test_records_the_colour_that_was_on_screen(vm):
    """★見たマスの色を覚えること（地図をゲーム画面と同じ色で描くため）。"""
    view_model, _ = vm
    state = field(x=10, y=10)
    state.map_view_radius = 1
    state.map_colors = _packed(1)
    assert view_model.note_position(state) == 9
    tiles = view_model.visited_tiles(0x07, 0x8E83)
    assert all(c == "4A9" for _x, _y, _n, c in tiles)


def test_unknown_cells_keep_no_colour(vm):
    """★"___" は「画面の外で分からない」。**それらしい色に丸めない**。"""
    view_model, _ = vm
    state = field(x=10, y=10)
    state.map_view_radius = 1
    state.map_colors = "___" + "4A9" * 8
    view_model.note_position(state)
    got = {(x, y): c for x, y, _n, c in view_model.visited_tiles(0x07, 0x8E83)}
    assert got[(9, 9)] is None, "分からないマスに色を付けた"
    assert got[(10, 10)] == "4A9"


def test_mismatched_colour_length_is_ignored(vm):
    """⚠★ 長さが合わない色列は**丸ごと捨てる**。

    ずらして塗ると、陸と海が入れ替わった嘘の地図になる。
    """
    view_model, _ = vm
    state = field(x=10, y=10)
    state.map_view_radius = 1
    state.map_colors = "4A9" * 5          # 9マスぶん無い
    view_model.note_position(state)
    assert all(c is None for _x, _y, _n, c in
               view_model.visited_tiles(0x07, 0x8E83))


def test_known_colour_is_not_erased_later(vm):
    """★あとで色が読めなかった回に、覚えた色を消さないこと。"""
    view_model, _ = vm
    state = field(x=10, y=10)
    state.map_view_radius = 0
    state.map_colors = "4A9"
    view_model.note_position(state)

    blank = field(x=10, y=10)
    blank.map_view_radius = 0
    blank.map_colors = None
    view_model.note_position(blank)
    assert view_model.visited_tiles(0x07, 0x8E83) == [(10, 10, 2, "4A9")]


def test_radius_comes_from_the_emulator_side(vm):
    """★色を拾った範囲と記録する範囲を合わせる（ずれると色が食い違う）。"""
    view_model, _ = vm
    view_model.view_radius = 7             # 設定は 7 でも…
    state = field(x=10, y=10)
    state.map_view_radius = 1              # …Lua が 1 で拾ったなら 1 に合わせる
    state.map_colors = _packed(1)
    assert view_model.note_position(state) == 9


def test_tile_colour_conversion():
    """RGB444 の16進 → 色。読めない値は None（推測で色を作らない）。"""
    from retroux.ui.map_window import _tile_color

    assert _tile_color("F00").name() == "#ff0000"
    assert _tile_color("08F").name() == "#0088ff"
    assert _tile_color("___") is None
    assert _tile_color("") is None
    assert _tile_color(None) is None
    assert _tile_color("12") is None

# --- 7. 既存の DB に列を足す（2026-07-29 / 実害が出た）------------------


def test_existing_database_gets_the_colour_column(tmp_path):
    """★★ `CREATE TABLE IF NOT EXISTS` は**既にある表に列を足さない**。

    ⚠ これを忘れて実害が出た: `VisitedTile.color` をスキーマに書き足しただけで
      済ませたため、**すでに DB を持っている環境（＝遊んでいる人）だけ**が
      地図の記録に失敗した。新規の DB では通るのでテストも通ってしまう。

    → **色の列が無い古い DB を作って**、開き直したら足されることを見る。
    """
    import sqlite3

    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE VisitedTile ("
        " rom_hash TEXT NOT NULL, map_id INTEGER NOT NULL,"
        " map_ptr INTEGER NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL,"
        " visits INTEGER NOT NULL DEFAULT 1,"
        " first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,"
        " PRIMARY KEY (rom_hash, map_id, map_ptr, x, y));")
    con.execute("INSERT INTO VisitedTile VALUES ('H',1,32768,5,6,3,'a','b')")
    con.commit()
    con.close()

    db = Database(path)
    try:
        cols = {r["name"] for r in
                db._conn.execute("PRAGMA table_info(VisitedTile)")}
        assert "color" in cols, "古い DB に色の列が足されていない"
        # ★もともとの記録が消えていないこと
        assert db.visited_tiles("H", 1, 32768) == [(5, 6, 3, None)]
        # ★そのうえで書き込めること（ここが実害の出た経路）
        assert db.mark_visited("H", 1, 32768, 9, 9, "4A9") is True
        assert (9, 9, 1, "4A9") in db.visited_tiles("H", 1, 32768)
    finally:
        db.close()
