"""ユーザー指定戦略（custom_1）のデータと Lua 渡し（2026-08-11 / Phase 4）。

★★ 確かめること ★★
  1. DQ2 プラグインに custom_1 の固定行動データがある（ちからのたて）
  2. lua_bridge が「有効な戦略」の目印を tactics.lua に載せる
  3. ⚠ Core に DQ2 固有データを持たない（プラグイン側にある / §13）
"""

from __future__ import annotations

import pathlib

import yaml


def _plugin_config():
    p = (pathlib.Path(__file__).resolve().parents[1]
         / "retroux" / "plugins" / "dq2" / "config.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_プラグインにcustom_1の固定行動がある():
    cfg = _plugin_config()
    us = cfg.get("user_strategies", {})
    assert "custom_1" in us, "★custom_1 の定義が無い"
    actors = us["custom_1"]["actors"]
    # ★ローレシア＝たたかう / サマル・ムーン＝ちからのたて（0x1D）
    assert actors["lorasia"]["action"] == "attack"
    assert actors["samaltria"]["action"] == "item"
    assert actors["samaltria"]["item"] == 0x1D
    assert actors["moonbrooke"]["item"] == 0x1D


def test_lua_bridgeが戦略の目印を載せる():
    from retroux.core.tactics import lua_bridge
    from retroux.core.tactics.profile_repository import build_presets

    prof = build_presets()[0]     # ★何かひとつプロファイル
    body = lua_bridge.render(prof, rev=1,
                             strategy={"id": "custom_1", "type": "fixed"})
    assert '"id"' in body or "id" in body
    assert "custom_1" in body
    assert "fixed" in body


def test_戦略を渡さなければ載らない():
    from retroux.core.tactics import lua_bridge
    from retroux.core.tactics.profile_repository import build_presets

    prof = build_presets()[0]
    body = lua_bridge.render(prof, rev=1)     # strategy 無し
    assert "custom_1" not in body


def test_Coreにdq2固有の固定行動データがない():
    """⚠ §13: Core に ROM のアイテムID等を**データ**として入れない。

    ★説明のためコメントに「ちからのたて」と書くのは可（概念の説明）。
      ⚠ 実データの目印は ROM のアイテムID（0x1D）。これが Core にあると
        DQ2 に縛られる。
    """
    core = (pathlib.Path(__file__).resolve().parents[1]
            / "retroux" / "core" / "strategy")
    for f in core.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "0x1D" not in text, f"★{f.name} に ROM のアイテムID（データ）"
