"""大目的（2026-08-05 / 戦闘AI再設計 Phase 3）。

指示書 §18 Phase 3 の完了条件:

  1. **目的ラジオボタンで挙動傾向が変化する**
  2. 既存の戦術リストボックスと競合しない
  3. ボス目的では AUTO を標準 OFF にできる

## ★★ 大目的は「価値基準」であって命令ではない（指示書 §5）

    誤: レベル上げ -> 常に速攻 -> 常にMP温存しない
    正: レベル上げ -> **時間の価値が高く、MP の価値が低い**

⚠ 戦術プロフィールを**上書きしません**。人が決めた「最低残存MP」に
倍率をかけるだけです。

## ⚠⚠ この実装で踏んだこと（記録）

1. **テストが利用者の `config/mission.yaml` を書き換えた。**
   ★既定が「ダンジョン攻略」のはずが、テストの書いた「レベル上げ」で
   起動するようになりました。→ `_mission_path` で差し替え可能にしました。

2. **操作直後の一言が AUTO の文言に塗りつぶされた。**
   目的を変えたことが画面から消えました。
   → いま何で戦っているかは**常時見える場所**（`戦術:` の行）に出します。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.mission import (
    MISSION_LABELS, Mission, MissionSettings, Risk, load, save,
)
from retroux.core.mission.repository import from_dict
from retroux.core.mission.settings import MISSION_PRESETS, label

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


# --- ★★ 完了条件3: ボス目的は AUTO を標準 OFF ---------------------------

def test_ボス目的はAUTOが既定OFF():
    """★★★ **Phase 3 完了条件そのもの**。"""
    assert MissionSettings(mission=Mission.BOSS_MANUAL).auto_enabled is False


def test_ほかの目的はAUTOが入る():
    for mission in (Mission.GRINDING, Mission.DUNGEON):
        assert MissionSettings(mission=mission).auto_enabled is True


# --- ★★ 完了条件1: 目的で挙動が変わる ------------------------------------

def test_目的でMP予約の重みが変わる():
    """★これが「挙動傾向が変化する」の中身です。"""
    scales = {m: MissionSettings(mission=m).mp_reserve_scale for m in Mission}
    assert scales[Mission.DUNGEON] == 1.0, "★既定は挙動を変えない"
    assert scales[Mission.GRINDING] < 1.0, "★レベル上げは予約をゆるめる"
    assert scales[Mission.BOSS_MANUAL] == 0.0, "★ボスは全力投入"


def test_レベル上げでも予約を0にしない():
    """⚠⚠ 0 にすると**ダンジョンから出られなくなります**。

    ★ルーラ・リレミトぶんまで使い切らせない。
    """
    assert MissionSettings(mission=Mission.GRINDING).mp_reserve_scale > 0


def test_目的ごとの重みが全部そろっている():
    """⚠ 抜けがあると、Phase 4 で読んだときに黙って nil になります。"""
    keys = set(MISSION_PRESETS[Mission.DUNGEON])
    for mission, preset in MISSION_PRESETS.items():
        assert set(preset) == keys, f"⚠ {mission.value} の項目が違います"


# --- ★★ 既定は「これまでどおり」 ----------------------------------------

def test_既定はダンジョン攻略():
    """★★★ **触っていない人の挙動を変えない**。

    ⚠ `GRINDING` を既定にすると、勝手にMP温存がゆるみます。
    """
    got = MissionSettings()
    assert got.mission is Mission.DUNGEON
    assert got.mp_reserve_scale == 1.0, "★既定は倍率1.0（＝何もしない）"
    assert got.auto_enabled is True


def test_設定が無くても落ちない(tmp_path):
    got, problems = load(tmp_path / "ない.yaml")
    assert got.mission is Mission.DUNGEON
    assert problems == [], "★無いのは異常ではありません"


# --- ⚠ 知らない値を黙って通さない ----------------------------------------

def test_知らない目的は既定のまま():
    """⚠⚠ 打ち間違いが別の目的になると、

    ★「ボスにしたのに AUTO が入る」のような事故になります。
    """
    got, problems = from_dict({"mission": "そんな目的"})
    assert got.mission is Mission.DUNGEON
    assert problems and "知らない目的" in problems[0]
    # ★使える値を教えること
    assert "grinding" in problems[0]


def test_知らない許容度も既定のまま():
    got, problems = from_dict({"risk": "でたらめ"})
    assert got.risk is Risk.NORMAL
    assert problems


def test_中身が辞書でなくても落ちない():
    got, problems = from_dict("これは文字列")
    assert got.mission is Mission.DUNGEON
    assert problems


# --- ★ 保存と読み直し ----------------------------------------------------

def test_保存して読み直せる(tmp_path):
    path = tmp_path / "mission.yaml"
    ok, why = save(MissionSettings(mission=Mission.GRINDING, risk=Risk.BOLD),
                   path)
    assert ok, why
    got, problems = load(path)
    assert got.mission is Mission.GRINDING
    assert got.risk is Risk.BOLD
    assert problems == []


def test_書けなくても理由を返す(tmp_path):
    """⚠ 例外を投げない。★呼ぶ側が起動できなくなるのを避ける。"""
    blocker = tmp_path / "ふさぐ"
    blocker.write_text("これはファイル", encoding="utf-8")
    ok, why = save(MissionSettings(), blocker / "mission.yaml")
    assert ok is False and why


# --- ★ Lua への受け渡し --------------------------------------------------

def test_Luaへ渡す形に重みが入る():
    got = MissionSettings(mission=Mission.GRINDING).to_lua_dict()
    assert got["mission"] == "grinding"
    assert got["mp_reserve_scale"] == 0.5
    assert got["auto_enabled"] is True
    assert "risk" in got


def test_tacticsluaへ相乗りする(tmp_path):
    """★別ファイルにせず `tactics.lua` に載せます。

    ⚠ 別にすると、版の管理と読み直しの仕組みが**もう1組**要ります。
    """
    from retroux.core.tactics import lua_bridge
    from retroux.core.tactics.profile_repository import build_presets

    text = lua_bridge.render(build_presets()[0],
                             mission=MissionSettings(
                                 mission=Mission.BOSS_MANUAL))
    assert "mission" in text
    assert "boss_manual" in text
    assert "mp_reserve_scale" in text


def test_missionを渡さなければ載らない():
    """⚠ 既存の呼び出しを壊さないこと（後方互換）。"""
    from retroux.core.tactics import lua_bridge
    from retroux.core.tactics.profile_repository import build_presets

    text = lua_bridge.render(build_presets()[0])
    assert "boss_manual" not in text


# --- ⚠ 表示 --------------------------------------------------------------

def test_表示名が日本語():
    """★英語の値をそのまま出さない。"""
    for mission in Mission:
        assert MISSION_LABELS[mission]
        assert mission.value not in MISSION_LABELS[mission]
    assert "ダンジョン攻略" in label(MissionSettings())


def test_利用者の設定はGit管理外():
    """⚠ 人それぞれなので共有しない（`config/mantan.yaml` と同じ）。"""
    text = (PROJECT_ROOT / ".gitignore").read_bytes().decode("utf-8")
    assert "config/mission.yaml" in text


def test_本番の設定を勝手に作らない():
    """⚠⚠ **実際に踏んだ**（上の説明1）。

    ★テストが `config/mission.yaml` を書くと、利用者の既定が変わります。
    """
    from retroux.ui.view_model import ViewModel

    # ★差し替え口があること
    assert hasattr(ViewModel, "_mission_path")
    assert ViewModel._mission_path is None
