"""戦略の中身を見せる窓（2026-08-11 / UI整理 Phase 5）。

設計: docs/design/strategy-unification-design.md（§6 Phase 5）

★★ 確かめたいこと ★★
  1. custom_1 の固定行動を、DQ2 プラグインから人が読める形で取れる
     （ちからのたて。★アイテムIDが名前に解決される）
  2. AUTO 戦略（ダンジョン攻略）では、いまの作戦の要約を read-only 表示
  3. ユーザー指定1 では固定行動を表示し、★エクスポートは無効（表示のみ）
  4. 手動では「設定する項目はありません」と出る
  5. ⚠ Core に DQ2 固有データを持たない（プラグイン側にある / §13）
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


@pytest.fixture
def window(app, vm):
    win = StrategyDetailWindow(vm)
    win.show()
    app.processEvents()
    yield win, vm
    win.close()


# --- プラグインの読み取り（固定行動）----------------------------------

def test_プラグインからcustom_1の固定行動が読める():
    """★ちからのたて。★アイテムID 0x1D が「ちからのたて」に解決される。"""
    from retroux.plugins.dq2 import user_strategy

    assert user_strategy.strategy_name("custom_1") == "亀の子戦術"
    from retroux.core.tactics import models

    rows = user_strategy.fixed_action_lines("custom_1")
    assert len(rows) == 3
    as_dict = dict(rows)
    lorasia = models.CHARACTER_LABELS["lorasia"]
    samaltria = models.CHARACTER_LABELS["samaltria"]
    moonbrooke = models.CHARACTER_LABELS["moonbrooke"]
    assert as_dict[lorasia] == "たたかう"
    assert "ちからのたて" in as_dict[samaltria]
    assert "どうぐ" in as_dict[samaltria]
    assert "ちからのたて" in as_dict[moonbrooke]
    # ★生のIDが漏れていない（名前に解決されている）
    assert "0x1D" not in as_dict[samaltria]


def test_Coreに固定行動のアイテムIDが無い():
    """⚠ §13: Core には ROM のアイテムID（0x1D）を**データ**として入れない。"""
    import pathlib

    core = (pathlib.Path(__file__).resolve().parents[1]
            / "retroux" / "core" / "strategy")
    for f in core.glob("*.py"):
        assert "0x1D" not in f.read_text(encoding="utf-8"), f.name


# --- AUTO 戦略（読むだけの要約）---------------------------------------

def test_AUTO戦略はいまの作戦の要約を出す(window):
    win, vm = window
    # ★実際の流れ: 戦略を適用してから中身を見る（作戦も束ねられる）
    vm.set_strategy("dungeon", source="test")
    win.show_for("dungeon")
    body = win._body.toPlainText()
    assert "目的" in body
    # ★ダンジョン攻略に束ねた作戦（いのちをだいじに）が要約に出る
    assert "ダンジョン探索" in body
    # ★AUTO はエクスポートできる（配布用）
    assert win._export_button.isEnabled()
    assert "レベル上げ" not in win._banner.text()
    assert "ダンジョン探索" in win._banner.text()


# --- ユーザー指定1（固定行動 / 表示のみ）------------------------------

def test_ユーザー指定1は固定行動を出しエクスポートは無効(window):
    win, vm = window
    win.show_for("custom_1")
    body = win._body.toPlainText()
    assert "ちからのたて" in body
    assert "ローレシア" in body and "ムーンブルク" in body
    assert "たたかう" in body
    # ★表示のみ（作戦の書き出しはしない）
    assert not win._export_button.isEnabled()
    assert "亀の子戦術" in win._banner.text()


# --- 手動 -------------------------------------------------------------

def test_手動は設定する項目が無いと出す(window):
    win, vm = window
    win.show_for("manual")
    body = win._body.toPlainText()
    assert "設定する項目はありません" in body
    assert not win._export_button.isEnabled()
    assert "手動" in win._banner.text()


# --- コピー -----------------------------------------------------------

def test_テキストをコピーできる(window):
    win, vm = window
    win.show_for("custom_1")
    win.copy_text()
    # ★環境によってクリップボードが無い。★どちらでも詰まらせない
    assert ("コピーしました" in win._status.text()
            or "クリップボード" in win._status.text())
