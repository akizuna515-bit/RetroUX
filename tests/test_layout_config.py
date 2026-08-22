"""レイアウト設定の計算・保存・復元（2026-08-01 の指示書 §3〜§7・§18）。

★★ **固定座標を使わない** ★★
  設計の基準は 1920×1080 だが、実際には必ずずれる:
    ・タスクバーを除いた作業領域（上や左に置いている人もいる）
    ・DPI スケーリング
    ・複数モニター
    ・**FCEUX の実寸**（1280×960 を渡しても 784×731 に丸められる）

  だから `anchor` の名前だけを設定に書き、計算は `layout.py` に集約する。

## ⚠⚠ 保存した配置で守りたいのは「速さ」ではなく **見える場所に開くこと**

  見えない場所に開いた窓は、利用者から見れば**起動していない**のと同じ。
  ★軽微なはみ出しは戻して収め、戻せないときだけ標準へ落とす。
"""

from __future__ import annotations

import pytest

from retroux.core import layout

#: FHD からタスクバー 40px を引いた作業領域
AREA = (0, 0, 1920, 1040)
#: FCEUX の実寸（実測）
EMU = (784, 731)


# --- 1. 標準配置の計算（指示書 §3）------------------------------------

def test_the_game_sits_at_the_top(): 
    """★★ ゲーム画面を主役にする（指示書 §3.3）★★

    ★縦は常に上端。横は `anchor` で決める（下の2つのテストを参照）。
    """
    made = layout.compute_standard(AREA, EMU)
    emu = made["emulator"]
    assert 0 <= emu.y <= 12, f"上端から離れすぎ: {emu.y}"
    # ★大きさは指定しない（FCEUX が内部倍率で丸めるため）
    assert emu.width is None and emu.height is None


def _cfg(anchor: str) -> dict:
    made = layout.load_default()
    made["windows"]["emulator"]["anchor"] = anchor
    return made


#: ⚠ 4区画に入らない画面（★従来配置へ落ちる）。`anchor` はこちらの話。
NARROW = (0, 0, 1000, 1040)


def test_the_top_left_anchor_packs_everything_into_the_corner():
    """★★ **横に広い画面向け**（2026-08-01 / 依頼者の環境 3840×1552）★★

    ⚠ 3840px で中央に置くと窓が右へ寄り、視線の移動が大きい。

    ★★ 2026-08-09: `anchor` は**従来配置だけ**の話になりました。★★
      4区画（左・中・右・下）ではゲーム画面が左右のパネルに挟まれるので、
      横位置は寄せ方ではなく**両脇の幅**で決まります。
      ⚠ だからここは4区画に入らない画面で確かめます。
    """
    made = layout.compute_standard(NARROW, EMU, _cfg("top_left"))
    assert "log" not in made, "★このテストは従来配置を見るためのもの"
    assert made["emulator"].x <= 16, f"左へ寄っていない: {made['emulator'].x}"
    # ★下段も**同じ向き**に寄る（片方だけ中央にしない）
    assert abs(made["map"].x - made["emulator"].x) <= 16,         f"下段が別の向きに寄っている（{made['map'].x} / {made['emulator'].x}）"


def test_the_top_center_anchor_still_works():
    """★1920px 前後では中央が自然。**切り替えられること**を残す。"""
    made = layout.compute_standard(AREA, EMU, _cfg("top_center"))
    assert made["emulator"].x == (1920 - EMU[0]) // 2, "横中央に来ていない"


def test_the_map_sits_to_the_left_of_the_game():
    """★★ **地図はゲーム画面の左**（2026-08-09 / 依頼者の指示「案1」）★★

        ┌────────┬──────────┬────────┐
        │  地図  │  FCEUX   │ RetroUX│
        ├────────┴──────────┴────────┤
        │  ログ / モンスター          │
        └────────────────────────────┘

    ⚠ 2026-08-07 までは「地図は FCEUX の真下」でした。★従来配置は
      4区画に入らない画面のために残してあります（下のテスト）。
    """
    made = layout.compute_standard(AREA, EMU)
    assert "log" in made, "★4区画になっていない"
    assert made["map"].x + made["map"].width <= made["emulator"].x, (
        "地図が FCEUX に重なっている")
    assert made["map"].y == made["emulator"].y, "上端がそろっていない"


def test_the_log_row_spans_the_bottom():
    """★★ 下段はログと出会ったモンスター（2026-08-09）★★

    ⚠ 上段と重ならないこと。★幅は端から端まで。
    """
    made = layout.compute_standard(AREA, EMU)
    log = made["log"]
    assert log.y >= made["emulator"].y + EMU[1], "下段が上段に重なっている"
    assert log.width > made["map"].width + made["main"].width, (
        "下段が端まで伸びていない")


def test_a_narrow_screen_keeps_the_old_arrangement():
    """★従来配置（地図は FCEUX の真下）は**消していません**。

    ⚠ 4区画に入らない画面ではこちらのほうが素直です。
    """
    made = layout.compute_standard(NARROW, EMU)
    assert "log" not in made
    assert made["map"].y >= made["emulator"].y + EMU[1], "地図が重なっている"
    assert made["map"].x == made["emulator"].x, "左端がそろっていない"


def test_the_main_window_sits_beside_the_game():
    """★★★ **RetroUX は FCEUX の横**（2026-08-07 / 依頼者の指示）。

        > RetroUXのウィンドウは、エミュレータ画面の横に置いてほしい

    ⚠ 以前は下段に置いていたため、★横に広い画面では右が大きく余り、
      RetroUX が縦に潰れて戦闘ログが数行しか見えませんでした。
    """
    made = layout.compute_standard(AREA, EMU)
    emu_right = made["emulator"].x + EMU[0]
    assert made["main"].x >= emu_right, "RetroUX が FCEUX に重なっている"
    # ★上端は FCEUX とそろえる（⚠ 下段ではない）
    assert made["main"].y == made["emulator"].y, "上端がそろっていない"


def test_the_main_window_is_tall_enough_to_read():
    """⚠⚠ **横に置く意味は「縦に伸ばせること」**です。

    ★戦闘ログが数行しか見えないなら、横に置いた意味がありません。
    """
    made = layout.compute_standard(AREA, EMU)
    assert made["main"].height > EMU[1] // 2, (
        f"RetroUX が低すぎます: {made['main'].height}")


def test_a_narrow_screen_falls_back_to_the_lower_row():
    """⚠⚠ **横に入りきらない画面で、画面外へ押し出さない。**

    ★狭い画面では従来どおり「FCEUX の下に横並び」へ戻します。
    """
    narrow = (0, 0, 900, 1040)
    made = layout.compute_standard(narrow, EMU)
    assert made["main"].x + made["main"].width <= narrow[0] + narrow[2], (
        "⚠ RetroUX が右へはみ出しました")


def test_nothing_goes_outside_the_work_area():
    """⚠ 画面外へ出さない（受入条件4）。"""
    for area in (AREA, (0, 0, 1366, 728), (100, 50, 2560, 1350)):
        made = layout.compute_standard(area, EMU)
        ax, ay, aw, ah = area
        for key, p in made.items():
            assert p.x >= ax, f"{key} が左へはみ出した（{area}）"
            assert p.y >= ay, f"{key} が上へはみ出した（{area}）"
            if p.width:
                assert p.x + p.width <= ax + aw, f"{key} が右へ（{area}）"
            if p.height:
                assert p.y + p.height <= ay + ah, f"{key} が下へ（{area}）"


def test_a_tall_game_window_shrinks_the_lower_row_instead_of_pushing_it_out():
    """⚠ FCEUX が大きいと下段の余りが減る。**押し出さずに詰める**。"""
    made = layout.compute_standard(AREA, (784, 900))
    assert made["map"].height > 0, "高さが無くなった"
    assert made["map"].y + made["map"].height <= AREA[1] + AREA[3]


def test_a_narrow_screen_shrinks_the_widths():
    """⚠ 幅が足りないときも重ねない（受入条件4）。"""
    made = layout.compute_standard((0, 0, 1000, 800), (600, 400))
    assert made["map"].x + made["map"].width <= made["main"].x
    assert made["main"].x + made["main"].width <= 1000


def test_the_work_area_offset_is_respected():
    """★タスクバーが上や左にある場合（作業領域の原点が 0 でない）。"""
    made = layout.compute_standard((60, 40, 1860, 1000), EMU)
    assert made["emulator"].x >= 60
    assert made["emulator"].y >= 40


def test_the_map_is_not_a_thin_sidebar():
    """⚠ 地図は細長い帯にしない（指示書 §3.4）。

    ★★ 2026-08-09: 4区画では地図は**縦長**になります（左の一列）。★★
      ⚠ §3.4 が避けたかったのは「細くて中身が読めない帯」なので、
        向きではなく**幅そのもの**を見ます。
      ★×8 固定だと 24×24 の城が 192px、ロンダルキア級（33×42）で 264px。
        ここを割ると地図が切れます。
    """
    made = layout.compute_standard(AREA, EMU)
    assert made["map"].width >= 280, (
        f"地図が細すぎます: {made['map'].width}px")
    # ⚠ 従来配置（横長）でも読める幅であること
    narrow = layout.compute_standard(NARROW, EMU)
    assert narrow["map"].width >= narrow["map"].height


# --- 2. 同梱の既定（指示書 §4.1）--------------------------------------

def test_the_shipped_default_layout_is_readable():
    """★★ 同梱の既定が読めなければ何も始まらない。 ★★"""
    cfg = layout.load_default()
    assert cfg.get("schema_version") == layout.SCHEMA_VERSION
    for key in ("emulator", "map", "main", "lua_script"):
        assert key in cfg["windows"], key


def test_the_lua_window_is_declared_as_minimized():
    """★Lua Script は利用者向け画面ではない（指示書 §9）。"""
    spec = layout.load_default()["windows"]["lua_script"]
    assert spec.get("visible") is False
    assert spec.get("behavior") == "minimize"


# --- 3. 保存と復元 -------------------------------------------------------
#
# ★2026-08-21（RX-0056）: `layout.save` / `load_saved` / `clear` は撤去した。
#   ⚠ その層（`config/layout.yaml`）は一度も動いていなかった。配置の記憶は
#   `retroux/ui/window_state.py` が担い、検査は tests/test_window_recovery.py にある。

def test_layoutには保存と復元が無い():
    """⚠ 二重管理に戻さない（記憶は window_state だけ）。"""
    for name in ("save", "load_saved", "clear", "USER_PATH"):
        assert not hasattr(layout, name), name
