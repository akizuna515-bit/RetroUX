"""地図の描き方（倍率・色・印）。

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

# --- 8. ピクセルマップ表示（2026-07-30 / `input/MAP表示改善.md`）---------
#
# > 現状は「訪問済みタイルを可変サイズの色付き四角で描く」実装になっている。
# > これを、画面の縮小イメージに近い見え方になるよう、
# > タイルをピクセル的に表示するミニマップ方式へ修正する。


OVERWORLD = {
    "map_id": 1, "type": "overworld", "width": None, "height": None,
    "border_tile": 4, "palette": 0, "data_pointer": "0x8000",
}


@pytest.fixture
def vm_over(tmp_path, mm):
    """ワールドマップ入りの ViewModel（大きさは設定から補う）。"""
    db = Database(tmp_path / "o.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    view_model = ViewModel(
        Recorder(db, "HASH", events, tmp_path / "command.json"), db, "HASH",
        monsters={int(k): str(v) for k, v in mm["monsters"].items()},
        map_meta={**META, 1: OVERWORLD},
        view_radius=0,
        overworld_size=(256, 256),
    )
    yield view_model, tmp_path
    db.close()


def test_overworld_size_comes_from_the_setting(vm_over):
    """★★ ROM のヘッダ表は map 01 の幅・高さが `$FF,$FF` で**読めない**。

    そこだけ設定から補う（実測 256×256）。
    """
    view_model, _ = vm_over
    assert view_model.map_size(1) == (256, 256)
    assert view_model.map_type(1) == "overworld"


def test_normal_map_keeps_the_rom_size(vm_over):
    """★通常マップは今までどおり ROM の値を使う（設定で上書きしない）。"""
    view_model, _ = vm_over
    assert view_model.map_size(0x07) == (23, 23)


def test_unknown_map_size_stays_unknown(vm_over):
    """⚠ 分からないマップに**設定値を当てはめない**（None と 0 を混ぜない）。"""
    view_model, _ = vm_over
    assert view_model.map_size(0x77) == (None, None)


def test_overworld_records_across_the_whole_canvas(vm_over):
    """★ワールドマップの端まで記録できること（256 の外は切る）。"""
    view_model, _ = vm_over
    view_model.view_radius = 2
    view_model.note_position(field(map_id=1, ptr=0x8000, x=254, y=254))
    seen = {(x, y) for x, y, _n, _c in view_model.visited_tiles(1, 0x8000)}
    assert (255, 255) in seen
    assert all(x < 256 and y < 256 for x, y in seen), "256 の外を記録した"


def test_coordinates_never_exceed_the_canvas(vm_over):
    """★★ 実データにあった不具合（2026-07-30）★★

    `map_x + dx` を切らずに記録していたため、**x/y が 255 を超えた記録が
    345 マス**あった。座標は1バイト（`$16`/`$17`）なのでありえない値。
    """
    view_model, _ = vm_over
    view_model.view_radius = 7
    view_model.note_position(field(map_id=1, ptr=0x8000, x=255, y=255))
    tiles = view_model.visited_tiles(1, 0x8000)
    assert tiles, "何も記録されていない"
    assert max(x for x, _y, _n, _c in tiles) <= 255
    assert max(y for _x, y, _n, _c in tiles) <= 255

# --- 8b. 描画モデル -----------------------------------------------------


@pytest.fixture
def view(app):
    from retroux.ui.map_window import TrailView

    widget = TrailView()
    widget.resize(400, 400)
    yield widget


def test_view_keeps_what_it_was_given(view):
    """★指示書 4章: tiles / here / 大きさ / 種別 を保持できること。"""
    view.set_data([(1, 2, 1, "4A9")], 23, 23, (5, 6), "town")
    assert view.tiles == [(1, 2, 1, "4A9")]
    assert (view.width_tiles, view.height_tiles) == (23, 23)
    assert view.here == (5, 6)
    assert view.map_type == "town" and not view.is_overworld


def test_overworld_flag(view):
    view.set_data([], 256, 256, None, "overworld")
    assert view.is_overworld


def test_image_is_one_pixel_per_tile(view):
    """★★ 1マス=1画素の画像を作ること（拡大四角ではない）。"""
    view.set_data([(3, 4, 1, "F00")], 23, 23, None, "town")
    image = view.build_image(23, 23)
    assert (image.width(), image.height()) == (23, 23)
    assert image.pixelColor(3, 4).name() == "#ff0000"


def test_unseen_tiles_are_transparent(view):
    """⚠★ 見ていないマスは**透明**。黒で塗ると「黒い地形を見た」と読める。"""
    view.set_data([(3, 4, 1, "F00")], 10, 10, None, "town")
    image = view.build_image(10, 10)
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(3, 4).alpha() == 255


def test_here_is_drawn_last(view):
    """★現在地は見た色に上書きされないこと。"""
    from retroux.ui.map_window import HERE

    view.set_data([(3, 4, 1, "F00")], 10, 10, (3, 4), "town")
    image = view.build_image(10, 10)
    assert image.pixelColor(3, 4).name() == HERE.name()


def test_tiles_outside_the_canvas_are_not_drawn(view):
    """⚠ 枠の外は描かない（大きさが違うと分かるように）。

    ★★ そして**数える**。Qt は範囲外の `setPixelColor` を黙って無視するので、
      数えないと「記録がずれている」ことに気づけない
      （実際に 346 マスの枠外記録があった / 2026-07-30）。
    """
    view.set_data([(50, 50, 1, "F00"), (3, 3, 1, "0F0")], 10, 10, None, "town")
    image = view.build_image(10, 10)
    assert image.pixelColor(3, 3).alpha() == 255
    assert view.outside_count == 1, "枠の外を数えていない"


def test_outside_count_is_zero_when_everything_fits(view):
    view.set_data([(3, 3, 1, "0F0")], 10, 10, None, "town")
    view.build_image(10, 10)
    assert view.outside_count == 0


# ⚠ **既定値の数字を書かない**（2026-08-01）。
#   4 と 1 を直に書いていたため、依頼者の要望で 8 と 2 に上げた途端に
#   赤くなった。★見たいのは「整数倍か」「枠に収まるか」であって、
#   既定値が何かではない（指示書 §14.2）。
@pytest.mark.parametrize("cols,rows,kind,expected", [
    # 小さい町 -> 400px に余裕で収まるので**既定どおり**
    (23, 23, "town", TrailView.ZOOM_NORMAL),
    # ★ワールドマップ 256 マスは 400px に収まらない -> 1 まで下がる
    (256, 256, "overworld", 1),
    (29, 25, "dungeon_a", TrailView.ZOOM_NORMAL),
])
def test_zoom_is_an_integer(view, cols, rows, kind, expected):
    """★★ 整数倍だけ（1.3倍のような半端な拡大をしない）。

    ⚠ 2026-08-01: 小さいマップに**下限**（`MIN_DRAWN_PIXELS`）を入れたので、
      既定より**上がる**ことがある。見たいのは「整数倍か」「枠に収まるか」。
    """
    view.resize(400, 400)
    view.set_data([], cols, rows, None, kind)
    zoom = view.pick_zoom(cols, rows)
    assert zoom >= expected, f"既定を下回った（×{zoom}）"
    assert cols * zoom <= 400 and rows * zoom <= 400, f"枠を越えた（×{zoom}）"
    assert isinstance(zoom, int)


def test_zoom_shrinks_to_fit_but_stays_integer(view):
    """★収まらないときは整数倍のまま下げる（枠に合わせて割らない）。

    ★この widget には最低の大きさ（320×320）があるので、
      `resize()` では「収まらない場合」を作れない。使える大きさを直に渡す。
    """
    view.set_data([], 256, 256, None, "overworld")
    # 100px しか無くても 1 を下回らない（0倍にしない）
    assert view.pick_zoom(256, 256, 100, 100) == 1

    view.set_data([], 23, 23, None, "town")
    assert view.pick_zoom(23, 23, 60, 60) == 2       # 60//23 = 2
    # ★広くても**枠いっぱいには広げない**（指示書 2章
    #   「余白を埋めるより、ドット感を保つ」）。⚠ 数字は書かない。
    #   ⚠ ただし下限（MIN_DRAWN_PIXELS）までは上がる。
    wide = view.pick_zoom(23, 23, 4000, 4000)
    assert wide >= TrailView.ZOOM_NORMAL
    assert 23 * wide <= TrailView.MIN_DRAWN_PIXELS + 23, \
        f"枠いっぱいまで広げている（×{wide}）"


def test_target_rect_is_centred(view):
    view.resize(480, 400)
    view.set_data([], 10, 10, None, "town")
    rect = view.target_rect(10, 10, 4)
    assert (rect.width(), rect.height()) == (40, 40)
    # ★widget の実寸から中央を出す（最低の大きさで丸められることがある）
    assert rect.x() == (view.width() - 40) // 2
    assert rect.y() == (view.height() - 40) // 2


def test_paint_does_not_crash_on_empty(view, app):
    """⚠ 記録が空でも描けること（表示のための処理で本体を止めない）。"""
    view.set_data([], None, None, None, None)
    view.show()
    app.processEvents()
    view.repaint()
    app.processEvents()
    view.close()


@pytest.mark.parametrize("ptr", [0, 0x7FFF, 0xC000, 0xFFFF])
def test_pointer_outside_the_bank_window_is_not_recorded(vm, ptr):
    """★★ 実データにあった不具合（2026-07-30）★★

    `map_ptr = 0` の記録が 64 マスあった。マップのデータ位置は必ず
    切り替えバンクの窓 `$8000-$BFFF` にあるので、0 は
    「まだマップを読み込んでいない」（タイトル画面など）。
    """
    view_model, _ = vm
    assert view_model.note_position(field(map_id=0x77, ptr=ptr)) == 0
    assert view_model.visited_maps() == []


def test_zoom_can_be_configured(view):
    """★倍率は設定から差し替えられること（`config.yaml` の `map.zoom`）。"""
    view.zoom_normal, view.zoom_overworld = 8, 2
    # ★下限（MIN_DRAWN_PIXELS）が効かない大きさで見る。
    #   ⚠ 小さいマップだと下限のほうが強く、設定を見たことにならない。
    view.set_data([], 40, 40, None, "town")
    assert view.pick_zoom(40, 40, 400, 400) == 8
    view.set_data([], 256, 256, None, "overworld")
    assert view.pick_zoom(256, 256, 1000, 1000) == 2


def test_zoom_zero_means_fit_to_the_frame(view):
    """★0 は「枠に収まる**最大の整数倍**」。半端な倍率にはしない。"""
    from retroux.ui.map_window import TrailView

    view.zoom_normal = TrailView.ZOOM_FIT
    view.set_data([], 23, 23, None, "town")
    got = view.pick_zoom(23, 23, 230, 230)
    assert got == 10, "枠に収まる最大の整数倍になっていない"
    assert isinstance(got, int)
    # ★上限は超えない（これ以上大きくしても情報は増えない）
    assert view.pick_zoom(23, 23, 4000, 4000) == TrailView.ZOOM_MAX


def test_zoom_never_becomes_zero(view):
    """⚠ 収まらなくても 0 倍にしない（何も見えなくなる）。"""
    from retroux.ui.map_window import TrailView

    view.zoom_normal = TrailView.ZOOM_FIT
    view.set_data([], 300, 300, None, "town")
    assert view.pick_zoom(300, 300, 100, 100) == 1

# --- 現在地の印（2026-08-01 / 課題 #55）--------------------------------
#
# 依頼者の報告:
#   「ワールドマップで、自分がいまどこにいるかがわかりずらい。
#     キャラ位置はもう少しマウスポインタっぽく強調が必要」

def test_the_here_marker_is_placed_after_zooming(view):
    """★★ 印は**拡大後の座標**に置く ★★

    ⚠ 画像（1マス=1画素）へ描き込むと倍率で潰れる。ワールドマップは
      等倍〜2倍なので、**1〜2px の点**にしかならない（それが元の不具合）。
    """
    view.set_data([], 100, 100, (10, 20), "overworld")
    rect = view.target_rect(100, 100, 2)
    got = view.here_center(rect, 2)
    assert got is not None
    # ★マスの左上ではなく**中心**を指す（10*2 + 1, 20*2 + 1）
    assert got == (rect.left() + 21, rect.top() + 41)


def test_the_marker_size_does_not_follow_the_zoom(view):
    """★★ 輪の大きさは倍率につられない ★★

    ⚠ つられると、等倍のワールドマップでまた見えなくなる。
      （倍率1で半径1px の輪は、点と区別が付かない）
    """
    assert TrailView.MARKER_RADIUS >= 5


def test_there_is_no_marker_when_the_place_is_unknown(view):
    """⚠ 分からないのに**それらしい場所へ置かない**（0 と 不明 を混ぜない）。"""
    view.set_data([], 50, 50, None, "town")
    assert view.here_center(view.target_rect(50, 50, 4), 4) is None


def test_a_marker_shows_even_beyond_the_rom_size(view):
    """★★ **ROM の枠の外に居ても印を出す**（2026-08-02 に契約を変えた）。

    ⚠⚠ もとは「枠の外には描かない」でした。依頼者の報告
      「save3では表示されない（印）」で、その前提が誤りだと分かりました。

    ★実測（遷移の記録は枠で切っていないので信用できる）:
        map $3D  ROM 15×17  ->  実際 29/33
        map $3E  ROM 17×19  ->  実際 32/37
      **ROM の値のほうが小さい**のです。正しい読み方は未解明。

    ★分からないので「ROM が正しい」とも決めず、
      **見えている事実（立っている座標）に合わせて枠を広げます**。
      ⚠ 広げたことは `beyond_rom()` で画面に出します（黙らない）。
    """
    view.set_data([], 20, 20, (99, 99), "town")
    assert view.bounds() == (100, 100)
    assert view.here_center(view.target_rect(*view.bounds(), 4), 4) is not None
    # ⚠ 広げたことを黙らない
    assert view.beyond_rom() == (80, 80)


def test_no_marker_when_the_place_is_unknown(view):
    """⚠ 立っている場所が分からないときは、やはり描かない。

    ★「広げる」のは**分かっている座標**のためであって、
      分からないものを埋めるためではない。
    """
    view.set_data([], 20, 20, None, "town")
    assert view.here_center(view.target_rect(20, 20, 4), 4) is None


def test_painting_with_a_marker_does_not_crash(view, app):
    """⚠ 印を描く処理で本体を止めない（表示のための処理）。"""
    view.set_data([(1, 1, 1, "0F0")], 20, 20, (1, 1), "town")
    view.show()
    app.processEvents()
    view.repaint()
    app.processEvents()
    view.close()

# --- 小さいマップ（2026-08-01 / 課題 #63）------------------------------
#
# 依頼者の報告:
#   「ダンジョンなどマップが切り替えの場合、うまく描けていない
#     ※もしくは別マップになっている？」
#
# ⚠⚠ 調べた結果、記録は**正しかった**。ROM の表に 1×1 / 3×3 / 5×5 の
#   マップが実在する（宿屋・店・祠などの小部屋）。
#   実データ: ID 0x24〜0x28 は 1×1、0x23 は 3×3、0x29 は 5×5。
#
# ★問題は**描き方**。既定の倍率では 8〜40px の点にしかならず、
#   560px の枠の真ん中で**現在地の印にほぼ覆われて**いた。

@pytest.mark.parametrize("cols,rows", [(1, 1), (3, 3), (5, 5)])
def test_a_tiny_map_is_drawn_big_enough_to_see(view, cols, rows):
    """★★ 1マスの部屋が 8px の点にならないこと ★★"""
    view.set_data([], cols, rows, None, "town")
    zoom = view.pick_zoom(cols, rows, 560, 560)
    drawn = cols * zoom
    assert drawn >= TrailView.MIN_DRAWN_PIXELS, \
        f"{cols}x{rows} が {drawn}px にしかならない"


def test_a_tiny_map_never_overflows_the_frame(view):
    """⚠ 大きくするのは**枠に収まる範囲**だけ（はみ出させない）。"""
    for avail in (100, 200, 320, 560):
        zoom = view.pick_zoom(3, 3, avail, avail)
        assert 3 * zoom <= avail, f"枠 {avail}px を越えた（×{zoom}）"


def test_the_zoom_is_still_an_integer_when_enlarged(view):
    """★★ 半端な倍率は使わない（指示書 2章）★★

    ⚠ 「小さいから大きくする」ときも整数倍を崩さない。
    """
    for cols in (1, 3, 5, 7):
        zoom = view.pick_zoom(cols, cols, 560, 560)
        assert isinstance(zoom, int) and zoom >= 1


def test_a_big_map_is_not_blown_up(view):
    """⚠ もともと十分大きいマップの倍率は**変えない**。

    ★ワールドマップ（256×256）は等倍〜2倍のまま。
      ここが上がると 560px の枠から溢れる。
    """
    view.set_data([], 256, 256, None, "overworld")
    zoom = view.pick_zoom(256, 256, 560, 560)
    assert zoom <= TrailView.ZOOM_OVERWORLD


def test_a_town_gets_a_bit_bigger_but_stays_sane(view):
    """★23×23 の町は既定の×8 では 184px。下限まで少しだけ上がる。"""
    zoom = view.pick_zoom(23, 23, 560, 560)
    assert zoom >= TrailView.ZOOM_NORMAL
    assert 23 * zoom <= 560


def test_the_here_marker_does_not_swallow_a_tiny_map(view):
    """★★ **これが依頼者の見ていた状態** ★★

    ⚠ 3×3 が 24px のとき、直径 14px の印がほぼ全部を覆っていた。
      拡大後は1マスが印より十分大きいこと。
    """
    zoom = view.pick_zoom(3, 3, 560, 560)
    assert zoom > TrailView.MARKER_RADIUS * 2, \
        f"1マス {zoom}px では印（直径 {TrailView.MARKER_RADIUS * 2}px）に覆われる"

# --- 黒い床が見えないと困る（2026-08-01 / 依頼者の報告）----------------
#
# 依頼者「ロンダルキアの洞窟だと、うまくマップが表示されてない」
#
# ⚠⚠ 実データで再現しました。ID $3E（5F）の 67 マスのうち
#   **53 マスが `000`（真っ黒）**。洞窟の床が黒いためです。
#   背景（BACKDROP = ほぼ黒）と見分けが付かず、
#   **歩いたのに何も出ていないように見えて**いました。
#
# ★`UNSEEN` の注釈は「見ていない所を黒くするな」と警告していましたが、
#   **見た所が黒い**場合が抜けていました。裏返しの見落としです。


def _pixel(view, app, x, y):
    """描いた結果の1画素を読む。★実際に塗ってから見る。"""
    from PySide6.QtGui import QPixmap

    view.show()
    app.processEvents()
    pix = QPixmap(view.size())
    view.render(pix)
    return pix.toImage().pixelColor(x, y)


def test_a_black_floor_is_distinguishable_from_unseen(view, app):
    """★★ **見たマスと見ていないマスが見分けられること** ★★

    ⚠ 色は嘘をつきません。床は黒のまま塗り、代わりに
      「まだ見ていない所」をはっきり違う色にして区別します。
    """
    from retroux.ui.map.canvas import BACKDROP, UNKNOWN_FLOOR

    assert UNKNOWN_FLOOR != BACKDROP, "枠の中と外が同じ色"
    # ★真っ黒の床と、はっきり違うこと（合計で 60 以上離す）
    diff = (UNKNOWN_FLOOR.red() + UNKNOWN_FLOOR.green() + UNKNOWN_FLOOR.blue())
    assert diff >= 60, f"黒い床と見分けが付かない: {UNKNOWN_FLOOR.name()}"


def test_a_seen_black_tile_really_stays_black(view, app):
    """★見た黒い床は**黒のまま**（下地で塗りつぶさない）。

    ⚠ 下地で上書きすると「黒い床を見た」という事実が消えます。
    """
    from retroux.ui.map.canvas import UNKNOWN_FLOOR

    view.resize(400, 400)
    # ★左上の1マスだけ「見た黒い床」、残りは見ていない
    view.set_data([(0, 0, 1, "000")], 4, 4, None, "dungeon_a")
    zoom = view.pick_zoom(4, 4)
    rect = view.target_rect(4, 4, zoom)
    seen = _pixel(view, app, rect.left() + zoom // 2, rect.top() + zoom // 2)
    assert seen.red() < 20 and seen.green() < 20 and seen.blue() < 20,         f"見た黒い床が塗り替えられている: {seen.name()}"
    # ★隣（見ていない）は下地の色
    unseen = _pixel(view, app, rect.left() + zoom + zoom // 2,
                    rect.top() + zoom // 2)
    assert unseen.name() == UNKNOWN_FLOOR.name(),         f"見ていない所が下地になっていない: {unseen.name()}"


def test_the_underlay_stays_inside_the_frame(view, app):
    """⚠ 下地は**枠の中だけ**（マップの外まで塗らない）。

    ★塗ってしまうと、マップの大きさが分からなくなります。
    """
    from retroux.ui.map.canvas import BACKDROP

    view.resize(400, 400)
    view.set_data([], 4, 4, None, "town")
    zoom = view.pick_zoom(4, 4)
    rect = view.target_rect(4, 4, zoom)
    outside = _pixel(view, app, max(rect.left() - 6, 0), rect.top() + 4)
    assert outside.name() == BACKDROP.name(),         f"枠の外まで塗っている: {outside.name()}"
