"""戦略ドロップダウン（2026-08-10 / UI整理 Phase 3）。

設計: docs/design/strategy-unification-design.md

★★ 確かめたいこと ★★
  1. メイン画面のドロップダウンは4戦略（目的+作戦を1つに畳んだ）
  2. `set_strategy` が既存の目的×作戦を束ねる
  3. ユーザー指定1（custom_1）は選べるが「準備中」で実行しない
  4. 手動を選ぶと AUTO が OFF、AUTO 戦略を選ぶと ON になる（戦闘外のみ）
  5. ⚠ 初期化・差し替えで誤発火しない
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
from retroux.ui.main_window import MainWindow  # noqa: E402
from retroux.ui.view_model import ViewModel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    repo = TacticsRepository(tmp_path / "profiles")
    vm = ViewModel(Recorder(db, "HASH", events, tmp_path / "command.json"),
                   db, "HASH", tactics=repo)
    vm._tactics_lua_path = tmp_path / "tactics.lua"
    vm._mission_path = tmp_path / "mission.yaml"
    win = MainWindow(vm, interval_ms=100000, heartbeat=None)
    win.show()
    app.processEvents()
    yield win
    win.close()


# --- ドロップダウンの中身 ----------------------------------------------

def test_三戦略が1つのドロップダウンに並ぶ(window):
    """★★ 2026-08-11: 手動を外し**3戦略だけ**（依頼者）。★手動は AUTO OFF。"""
    p = window._strategy_picker
    values = [p.itemData(i) for i in range(p.count())]
    assert values == ["leveling", "dungeon", "custom_1"]
    assert "manual" not in values, "★手動はドロップダウンに出さない"
    # ⚠ 旧ドロップダウン（目的・作戦）は無い
    assert not hasattr(window, "_mission_picker")
    assert not hasattr(window, "_tactics_picker")


# --- 束ねる（set_strategy）---------------------------------------------

def test_レベル上げは目的grindingを束ねる(window):
    window.vm.set_strategy("leveling", source="test")
    assert window.vm.mission().mission.value == "grinding"


def test_ダンジョンは目的dungeonを束ねる(window):
    window.vm.set_strategy("dungeon", source="test")
    assert window.vm.mission().mission.value == "dungeon"


def test_AUTO入切の意図を返す(window):
    """★★ 2026-08-11: 3戦略はどれも AUTO を入れる（手動は AUTO ボタン OFF）。"""
    assert window.vm.set_strategy("leveling").auto_enabled is True
    assert window.vm.set_strategy("dungeon").auto_enabled is True
    assert window.vm.set_strategy("custom_1").auto_enabled is True


# --- custom_1（ユーザー指定1 / Phase 4）--------------------------------

def test_ユーザー指定1を選ぶと固定戦略が有効になる(window):
    """★★ 2026-08-11（Phase 4）: 準備中を外し、固定戦略を有効化する。★★

    ⚠ 目的・作戦は変えない。★「custom_1 が有効」を覚え、Lua へ渡す
      （固定行動の中身は config.lua の user_strategies）。
    """
    window.vm.set_strategy("dungeon", source="test")   # ★まず AUTO 戦略に
    window._on_strategy_picked("custom_1")

    assert window.vm._active_strategy == "custom_1"
    assert "亀の子戦術" in window._align_status.text()
    # ★AIループは回す（固定行動が横取りする）。手動ではない
    assert window.vm.current_strategy(auto_on=True) == "custom_1"
    # ★Lua へ渡す目印
    assert window.vm._active_strategy_lua() == {"id": "custom_1",
                                                "type": "fixed"}


def test_他の戦略を選ぶと固定戦略が解除される(window):
    """★AUTO / 手動へ移ると custom_1 は解除。"""
    window._on_strategy_picked("custom_1")
    assert window.vm._active_strategy == "custom_1"
    window._on_strategy_picked("dungeon")
    assert window.vm._active_strategy is None
    assert window.vm._active_strategy_lua() is None


# --- 戦略 → AUTO 連動（戦闘外のみ）------------------------------------
#
# ⚠ 2026-08-11: 「手動」戦略は廃止。手動で遊ぶときは AUTO ボタンを OFF に
#   する（戦略ドロップダウンには手動が無い）。

def test_AUTO戦略を選ぶとAUTOが入る(window):
    window._auto_button.setChecked(False)
    window._on_strategy_picked("leveling")
    QApplication.instance().processEvents()
    assert window._auto_button.isChecked() is True


# --- 現在値の反映 ------------------------------------------------------

def test_現在の戦略が導ける(window):
    """★★ 2026-08-11: 戦略は AUTO の入切に依らず、目的/固定から決まる。

    ⚠ 手動戦略は廃止。AUTO が OFF でも、選んでいる戦略（レベル上げ/
      ダンジョン探索/亀の子）を返す（AUTO はあくまで「AI を動かすか」）。
    """
    window.vm.set_strategy("leveling", source="test")
    assert window.vm.current_strategy(auto_on=True) == "leveling"
    assert window.vm.current_strategy(auto_on=False) == "leveling"
    window.vm.set_strategy("dungeon", source="test")
    assert window.vm.current_strategy(auto_on=True) == "dungeon"
