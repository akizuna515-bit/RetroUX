"""4戦略の受入（2026-08-11 / UI整理 Phase 6・自動でできる範囲）。

設計: docs/design/strategy-unification-design.md（§6 Phase 6）
実機の手順: docs/design/strategy-acceptance-phase6.md

★★ ここで固めること（実機を起動せずに確かめられる契約）★★
  戦略を選んだとき、下の4つが**まとめて正しく**束ねられること。
    ・目的（Mission）        … AUTO 戦略だけが持つ
    ・作戦（tactics profile） … どの作戦へ束ねるか
    ・AUTO の入切            … 手動だけ OFF
    ・Lua への目印           … 固定戦略だけ {id,type=fixed}
  加えて、⚔「戦略の中身」窓が戦略ごとに正しい見せ方になること。

⚠ 実機でしか見られない部分（メニュー移動・実際の入力・戦闘の完走）は
  上の手順書のチェックリストで人が確認する。ここでは配線を固定する。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.db.database import Database  # noqa: E402
from retroux.core.recorder import Recorder  # noqa: E402
from retroux.core.tactics import TacticsRepository  # noqa: E402
from retroux.ui.strategy_detail_window import StrategyDetailWindow  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def vm(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    repo = TacticsRepository(tmp_path / "profiles")
    made = ViewModel(Recorder(db, "HASH", events, tmp_path / "command.json"),
                     db, "HASH", tactics=repo)
    made._tactics_lua_path = tmp_path / "tactics.lua"
    made._mission_path = tmp_path / "mission.yaml"
    return made


# --- AUTO 戦略（レベル上げ / ダンジョン攻略）--------------------------

def test_レベル上げは目的と作戦を束ねAUTOが入る(vm):
    sw = vm.set_strategy("leveling", source="acceptance")
    assert sw.ok and sw.auto_enabled is True
    assert vm.mission().mission.value == "grinding"
    assert vm.active_tactics().id == "balanced"          # バッチリ戦う
    # ★AUTO 戦略は固定でも手動でもない
    assert vm._active_strategy is None
    assert vm._active_strategy_lua() is None
    assert vm.current_strategy(auto_on=True) == "leveling"


def test_ダンジョン攻略は省資源の作戦を束ねる(vm):
    sw = vm.set_strategy("dungeon", source="acceptance")
    assert sw.ok and sw.auto_enabled is True
    assert vm.mission().mission.value == "dungeon"
    assert vm.active_tactics().id == "life_first"         # いのちをだいじに
    assert vm._active_strategy_lua() is None
    assert vm.current_strategy(auto_on=True) == "dungeon"


# --- ユーザー指定1（固定行動）----------------------------------------

def test_ユーザー指定1は固定の目印をLuaへ渡す(vm):
    vm.set_strategy("dungeon", source="acceptance")       # まず AUTO に
    sw = vm.set_strategy("custom_1", source="acceptance")
    assert sw.ok
    # ★固定でも AI ループは回す（固定行動が横取りするため）
    assert sw.auto_enabled is True
    assert vm._active_strategy == "custom_1"
    assert vm._active_strategy_lua() == {"id": "custom_1", "type": "fixed"}
    assert vm.current_strategy(auto_on=True) == "custom_1"
    # ⚠ 目的・作戦は変えない（薄い被せもの）
    assert vm.mission().mission.value == "dungeon"


def test_ユーザー指定1から別戦略へ移ると固定が解ける(vm):
    vm.set_strategy("custom_1", source="acceptance")
    assert vm._active_strategy == "custom_1"
    vm.set_strategy("leveling", source="acceptance")
    assert vm._active_strategy is None
    assert vm._active_strategy_lua() is None


# --- 手動は廃止（2026-08-11）-----------------------------------------
#
# ⚠ 「手動」戦略はドロップダウンから外した。手動で遊ぶときは AUTO ボタンを
#   OFF にする（AUTO は「AI を動かすか」の別軸）。


def test_手動戦略はドロップダウンに出ない(vm):
    values = [v for v, _t, _n in vm.strategy_choices()]
    assert values == ["leveling", "dungeon", "custom_1"]
    assert "manual" not in values


# --- ⚔ 窓の見せ方（戦略ごと）------------------------------------------

def _detail(app, vm):
    win = StrategyDetailWindow(vm)
    win.show()
    app.processEvents()
    return win


def test_窓_AUTOは作戦の要約とエクスポート可(app, vm):
    vm.set_strategy("dungeon", source="acceptance")
    win = _detail(app, vm)
    try:
        win.show_for("dungeon")
        body = win._body.toPlainText()
        assert "ダンジョン探索" in win._banner.text()
        assert "目的" in body and "ダンジョン探索" in body
        assert win._export_button.isEnabled()
    finally:
        win.close()


def test_窓_ユーザー指定1は固定行動で表示のみ(app, vm):
    win = _detail(app, vm)
    try:
        win.show_for("custom_1")
        body = win._body.toPlainText()
        assert "亀の子戦術" in win._banner.text()
        assert "ちからのたて" in body and "たたかう" in body
        assert not win._export_button.isEnabled()         # 表示のみ
    finally:
        win.close()
