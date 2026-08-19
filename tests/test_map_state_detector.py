"""ゲーム状態の見分け（2026-08-02 / マップ指示書 §18.1）。

★★ **ここが落ちると、移動中やメニュー中の背景を地形にしてしまう。** ★★

## 実測の根拠（2026-08-02 / 日本版）

    $0035 メニュー開閉フラグ  静止 00 / メニュー FF
    $0059 メニューID          静止 00 / コマンドメニュー 06
    ★静止中のスクロールは必ず 16 の倍数。移動中だけ半端になる
"""

from __future__ import annotations

import pytest

from retroux.core.bgmap.state import (
    BATTLE, FIELD_IDLE, FIELD_MENU, FIELD_MESSAGE, FIELD_MOVING,
    FIELD_SETTLING, MAP_TRANSITION, Snapshot, detect, may_capture, why_not,
)


def idle(**kw) -> Snapshot:
    """★何も起きていない状態を土台にする。"""
    base = dict(stable=5, scroll_x=32, scroll_y=112)
    base.update(kw)
    return Snapshot(**base)


# --- 判定の順（指示書 §6.1）--------------------------------------------

def test_戦闘中はBATTLE():
    assert detect(idle(in_battle=True)) == BATTLE


def test_戦闘はメニューより先に見る():
    """⚠ 戦闘中にメニューが開いていても BATTLE。"""
    assert detect(idle(in_battle=True, menu_open=True)) == BATTLE


def test_マップ切替はMAP_TRANSITION():
    assert detect(idle(map_changed=True)) == MAP_TRANSITION


def test_メニュー中はFIELD_MENU():
    assert detect(idle(menu_open=True)) == FIELD_MENU
    # ★フラグが立っていなくてもメニューIDが 0 でなければメニュー
    assert detect(idle(menu_id=0x06)) == FIELD_MENU


def test_メッセージ中はFIELD_MESSAGE():
    assert detect(idle(message_active=True)) == FIELD_MESSAGE


def test_メッセージが不明なら判定に使わない():
    """⚠ 番地が未特定。**推測で埋めない**（None のまま扱う）。"""
    assert detect(idle(message_active=None)) == FIELD_IDLE


# --- 移動中（★スクロールの端数で見る）---------------------------------

@pytest.mark.parametrize("sx,sy", [(11, 0), (0, 12), (33, 48), (1, 1)])
def test_スクロールが半端なら移動中(sx, sy):
    """★★ **2026-08-02 の実測**: 静止中は必ず 16 の倍数。"""
    assert detect(idle(scroll_x=sx, scroll_y=sy)) == FIELD_MOVING


@pytest.mark.parametrize("sx,sy", [(0, 0), (16, 32), (144, 96), (32, 112)])
def test_スクロールが16の倍数なら静止(sx, sy):
    assert detect(idle(scroll_x=sx, scroll_y=sy)) == FIELD_IDLE


def test_メニューは移動より先に見る():
    """⚠ メニュー中でもスクロールは揃っている。順番が逆だと取り違える。"""
    assert detect(idle(menu_open=True, scroll_x=11)) == FIELD_MENU


# --- 落ち着き待ち（指示書 §6.3）-----------------------------------------

@pytest.mark.parametrize("stable", [0, 1, 2])
def test_背景が落ち着くまではFIELD_SETTLING(stable):
    """⚠ 固定フレーム待ちだけにしない。**連続一致**で見る。"""
    assert detect(idle(stable=stable)) == FIELD_SETTLING


def test_3回続けて同じなら静止():
    assert detect(idle(stable=3)) == FIELD_IDLE


# --- 採ってよいか（指示書 §6.2）-----------------------------------------

def test_静止していれば採ってよい():
    assert may_capture(idle()) is True


@pytest.mark.parametrize("kw", [
    {"in_battle": True},
    {"menu_open": True},
    {"menu_id": 0x06},
    {"map_changed": True},
    {"scroll_x": 11},
    {"stable": 0},
    {"message_active": True},
])
def test_それ以外では採らない(kw):
    assert may_capture(idle(**kw)) is False


def test_真っ暗なら採らない():
    """⚠⚠ **ここが落ちると、暗転中の1枚で床や壁が塗りつぶされる。**

    ★実機では暗転を作れないことがある（FCEUX が先に描画を終える）ので、
      **判定を直接試せる**ようにしてある。
    """
    assert may_capture(idle(dark=True)) is False
    # ★静止していても暗ければ採らない
    assert detect(idle(dark=True)) == FIELD_IDLE     # 状態としては静止
    assert may_capture(idle(dark=True)) is False     # ⚠ でも採らない


# --- 理由を残す（指示書 §11.2）------------------------------------------

def test_採ってよいときは理由が無い():
    assert why_not(idle()) is None


def test_黒は理由をblack_or_transitionにする():
    """★指示書 §2.3 の例と同じ言葉にそろえる。"""
    assert why_not(idle(dark=True)) == "black_or_transition"


@pytest.mark.parametrize("kw,want", [
    ({"menu_open": True}, "field_menu"),
    ({"scroll_x": 11}, "field_moving"),
    ({"stable": 0}, "field_settling"),
    ({"map_changed": True}, "map_transition"),
    ({"in_battle": True}, "battle"),
])
def test_採らなかった理由が残る(kw, want):
    assert why_not(idle(**kw)) == want


# --- Lua 側と食い違わないこと -------------------------------------------

def test_Lua側と同じ番地を使っている():
    """⚠⚠ 判定が **Python と Lua の2か所**にある。片方だけ直すと食い違う。

    ★番地は `rom_profiles.yaml` が正本。両方がそれと一致していること。
    """
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parents[1]
    profile = yaml.safe_load(
        (root / "retroux" / "plugins" / "dq2" / "rom_profiles.yaml")
        .read_text(encoding="utf-8"))
    ram = profile["rom_profiles"]["dq2_jp"]["ram"]

    lua = (root / "research" / "probes" / "active"
           / "map_validation_probe.lua").read_text(encoding="utf-8")
    # ★Lua が正本と同じ番地を書いていること
    assert f"0x{ram['menu_id']:04X}" in lua, "menu_id"
    assert f"0x{ram['menu_open_flag']:04X}" in lua, "menu_open_flag"
    assert f"0x{ram['scroll_x']:04X}" in lua, "scroll_x"
    assert f"0x{ram['scroll_y']:04X}" in lua, "scroll_y"


def test_スクロールの刻みが正本と一致する():
    """★16 の倍数という規則も `rom_profiles.yaml` に書いてある。"""
    import pathlib

    import yaml

    from retroux.core.bgmap.state import SCROLL_ALIGNMENT

    root = pathlib.Path(__file__).resolve().parents[1]
    profile = yaml.safe_load(
        (root / "retroux" / "plugins" / "dq2" / "rom_profiles.yaml")
        .read_text(encoding="utf-8"))
    assert profile["state_rules"]["scroll_alignment"] == SCROLL_ALIGNMENT


def test_北米版の番地を実行時に使わない():
    """⚠⚠ 指示書 §3「北米版のアドレスを日本版へ直接適用しない」。"""
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parents[1]
    profile = yaml.safe_load(
        (root / "retroux" / "plugins" / "dq2" / "rom_profiles.yaml")
        .read_text(encoding="utf-8"))
    us = profile["rom_profiles"]["dw2_us_reference"]
    assert us["use_at_runtime"] is False


def test_測っていない項目はnullのまま():
    """★推測で埋めない（指示書 §3.3）。"""
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parents[1]
    profile = yaml.safe_load(
        (root / "retroux" / "plugins" / "dq2" / "rom_profiles.yaml")
        .read_text(encoding="utf-8"))
    ram = profile["rom_profiles"]["dq2_jp"]["ram"]
    # ⚠ これらはまだ測っていない。★埋まっていたら根拠を確かめること
    for name in ("message_state", "transition_state", "fade_state",
                 "map_render_type"):
        assert ram[name] is None, (
            f"{name} が埋まっている。★実測の根拠があるなら"
            "このテストも一緒に直すこと")
