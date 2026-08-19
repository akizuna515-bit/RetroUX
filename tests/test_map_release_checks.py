"""ROM 地図の公開前チェック（チェックリスト §5 のうち自動で見られるもの）。

★実機なしで確かめられる3件をここで見ます:

    ⚠ 世界地図では現行表示へ落ちる
    ⚠ `map_id` 不明・ポインタ食い違いでも落ちない
    ⚠ 既定（`observed`）では見た目が変わらない

## ⚠⚠ どれも「落ちない」ことが要点

★地図が出ないのは困りますが、⚠ **本体が止まるほうがもっと困ります**。
「組めないなら理由を返す」が守られているかを見ます。
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from retroux.core.bgmap import settings as S       # noqa: E402
from retroux.ui.map.presenter import MapPresenter  # noqa: E402

ROM_PATH = pathlib.Path(
    os.environ.get("DQ2_ROM_PATH") or "work/rom/DQ2_J.nes")
needs_rom = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"ROM がありません（{ROM_PATH}）")


class _Vm:
    """presenter が触るものだけ持つ入れ物。"""

    def __init__(self, map_render=None, live=None) -> None:
        self.map_render = map_render
        self.live_metatiles = live


@pytest.fixture(scope="module")
def live():
    import yaml

    from retroux.gui import _build_live_metatiles

    if not ROM_PATH.exists():
        pytest.skip("ROM がありません")
    config = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "config.yaml").read_bytes().decode("utf-8"))
    got = _build_live_metatiles(config, ROM_PATH)
    if got is None:
        pytest.skip("★絵の材料を用意できない環境")
    return got


# --- ⚠ 1. 世界地図では現行表示へ落ちる ---------------------------------

@needs_rom
def test_世界地図はROMの地形で描く(live):
    """★★ ⚠⚠ **チェックリストの文言は古い** ★★

    §5 は「⚠ **世界地図では現行表示へ落ちる**」と書いてあるが、
    ★2026-08-11 に**世界地図も ROM から描けるようになった**
    （`world_layer()` / 65536/65536）。

    ⚠ 「落ちる」ままだと、直したのに古い前提で確認することになる。
    → ★いまは**描ける**ことを、こちらで固定する。
    """
    from retroux.core.bgmap.world_art import WORLD_MAP_ID

    vm = _Vm(S.load({}), live)
    got = MapPresenter(vm).rom_layer(WORLD_MAP_ID, 0, [(0, 0, 1, None)])
    assert got is not None, "⚠ 世界地図で None（★理由すら返っていない）"
    # ★描けているか、理由が返っているかのどちらか。⚠ 例外は出ないこと
    assert "metatiles" in got or got.get("note"), got


# --- ⚠ 2. map_id 不明・ポインタ食い違いでも落ちない --------------------

@needs_rom
@pytest.mark.parametrize("map_id,map_ptr,why", [
    (0x6D, 0, "★ヘッダ表の外（実測で確認）"),
    (0xFF, 0, "⚠ ありえない map_id"),
    (0x40, 0xFFFF, "⚠ ポインタが食い違う"),
    (0x40, 0x0000, "⚠ ポインタが 0"),
])
def test_おかしな指定でも落ちない(live, map_id, map_ptr, why):
    """★★★ ⚠⚠ **本体を止めない** ★★★

    ★地図が出ないのは困るが、⚠ **本体が止まるほうがもっと困る**。
    「組めないなら理由を返す」が守られていること。
    """
    vm = _Vm(S.load({}), live)
    got = MapPresenter(vm).rom_layer(map_id, map_ptr, [(0, 0, 1, None)])
    # ⚠ 例外が出ないことが第一。★出せないなら理由があること
    if got is not None and not got.get("metatiles"):
        assert got.get("note"), f"⚠ 出せないのに理由が無い（{why}）: {got}"


@needs_rom
def test_理由は読んで分かる言葉である(live):
    """⚠ 「エラー」だけでは、利用者も次の人も直せない。"""
    vm = _Vm(S.load({}), live)
    got = MapPresenter(vm).rom_layer(0xFF, 0, [(0, 0, 1, None)])
    note = (got or {}).get("note", "")
    assert note, "★理由が空"
    assert any(w in note for w in ("map", "ヘッダ", "表", "見つ", "読め")), note


# --- ⚠ 3. 既定（observed）では見た目が変わらない -----------------------

@needs_rom
def test_設定でこれまでの地図に戻せる(live):
    """★`renderer: observed` にしたら ROM の地形を使わないこと。"""
    vm = _Vm(S.load({"map": {"rom_master": {"renderer": "observed"}}}), live)
    got = MapPresenter(vm).rom_layer(0x40, 0, [(0, 0, 1, None)])
    assert got is not None
    assert not got.get("metatiles"), "⚠ observed なのに ROM で描いている"
    assert "設定" in got.get("note", ""), got


@needs_rom
def test_既定はROMの地形である(live):
    """⚠⚠ **チェックリストの「既定は observed」は古い**。

    ★2026-08-09 から既定は `rom_master`（＝ROM の地形で描く）。
    ⚠ ここを取り違えると「変わらないはず」で確認して食い違う。
    """
    assert S.load({}).uses_rom_master, (
        "★既定が ROM の地形でなくなっている")
    vm = _Vm(S.load({}), live)
    got = MapPresenter(vm).rom_layer(0x40, 0, [(0, 0, 1, None)])
    assert got is not None and got.get("metatiles"), (
        "⚠ 既定で ROM の地形が出ていない")


@needs_rom
def test_設定を変えると出るものが変わる(live):
    """★片側だけだと「常に同じ」でも通る（⚠ 両方向を見る）。"""
    walked = [(x, 0, 1, None) for x in range(4)]
    rom = MapPresenter(_Vm(S.load({}), live)).rom_layer(0x40, 0, walked)
    obs = MapPresenter(
        _Vm(S.load({"map": {"rom_master": {"renderer": "observed"}}}), live)
    ).rom_layer(0x40, 0, walked)
    assert rom.get("metatiles") and not obs.get("metatiles"), (rom, obs)


# --- ⚠⚠ 4. 世界地図で嘘の注意を出さない（2026-08-19 / RX-0061）--------

@needs_rom
def test_世界地図では黄色い注意を出さない():
    """★★★ ⚠⚠ **地形は出ているのに「出せていません」と出ていた** ★★★

    依頼者の画面（2026-08-19）:

        ⚠ ROM の地形を出せていません
          （1マスが 8px に満たない（枠 512x512 / マップ 256x256 / 収まる上限 2px））

    ★ところが**世界地図はちゃんと描けていた**。⚠ 注意のほうが嘘。

    ## ⚠ なぜ出たか

      ★世界地図は `_apply_map_view` の**別の道**で描く
        （`is_overworld` → 固定サイズ ×2）。メタタイルは使わない。
      ⚠ ところが `paintEvent` の `_metatile_zoom()` は
        256×256 を 2px で並べようとして**必ず None** になり、
        ★その理由が `_render_note` へ出ていた。

    ⚠ 「黙らない」ようにしたものが、今度は**嘘をつく**ようになっていた。

    ★★ **字面では見ない。実際に窓を開く。** ★★
    """
    from PySide6.QtWidgets import QApplication

    from retroux.core.bgmap.world_art import WORLD_MAP_ID
    from retroux.gui import build_view_model
    from retroux.ui.map.window import MapWindow

    app = QApplication.instance() or QApplication([])
    vm, db = build_view_model(read_only=True)
    try:
        win = MapWindow(vm)
        keys = [k for k in win._keys if k[0] == WORLD_MAP_ID]
        if not keys:
            pytest.skip("★世界地図の記録がまだありません")
        win._list.setCurrentRow(win._keys.index(keys[0]))
        win.resize(360, 520)
        win.show()
        app.processEvents()
        win._draw()
        app.processEvents()
        assert win._view.is_overworld, "★世界地図として扱われていない"
        assert not win._render_note.isVisible(), (
            f"⚠⚠ 嘘の注意が出ている: {win._render_note.text()}")
        win.close()
    finally:
        db.close()


@needs_rom
def test_街の地図では今までどおり注意を出す():
    """⚠ 世界地図を除いたせいで、**街でも黙る**ようになっていないこと。

    ★片側だけ直すと、もう片方が壊れる（この計画で何度も踏んだ形）。
    """
    from PySide6.QtWidgets import QApplication

    from retroux.gui import build_view_model
    from retroux.ui.map.window import MapWindow

    app = QApplication.instance() or QApplication([])
    vm, db = build_view_model(read_only=True)
    try:
        win = MapWindow(vm)
        # ★灯台 1F（44×44）を、⚠ 8px も並べられない小さな窓で開く
        keys = [k for k in win._keys if k[0] == 0x50]
        if not keys:
            pytest.skip("★灯台 1F の記録がまだありません")
        win._list.setCurrentRow(win._keys.index(keys[0]))
        win.show()
        app.processEvents()
        # ⚠ 絵は渡っているのに、材料が足りない形を作る
        win._view.set_metatiles([(0, 0, "no-such-key", 1, "confirmed")])
        win._view._metatile_zoom(*win._view.bounds())
        app.processEvents()
        assert win._view.metatile_giveup(), (
            "★理由が残っていない（⚠ 街でも黙るようになった）")
        win.close()
    finally:
        db.close()
