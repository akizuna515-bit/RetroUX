"""戦闘AI設定画面の「戦闘開始時 自動 / 手動」（RX3-0237 仕様 §5 / 2026-09-13）。

```text
自動（既定）  戦闘開始で AUTO ON ＋ TURBO ON（★倒したことのある敵だけ・ボス候補でない・窓の色が危険でない）
手動          戦闘開始は AUTO OFF ＋ TURBO OFF → 人が A（AUTO）で AUTO＋TURBO へ
```

★保存は今までと同じ `automation.battle_auto_known`（true = 自動 / false = 手動）→ `dq3_battle_auto.lua` → auto_v0。
⚠ メイン画面には置かない（仕様 §5・§10）。★判断そのものは Lua の足場（`dq3_auto_ai_test.lua` の 10）。
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                     # noqa: E402

pytest.importorskip("PySide6")

from test_dq3_battle_ai_window import _hub        # noqa: E402  ★同じ足場（ROM が無くても開ける）


def test_既定は自動で_手動にすると保存してLuaへ渡す(tmp_path, monkeypatch):
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    from dq3.phase0 import battle_auto_overlay as BA
    from dq3.ui.battle_ai_window import START_AUTO, START_MANUAL, BattleAiWindow

    hub, _cmd = _hub(tmp_path, monkeypatch)
    w = BattleAiWindow(hub)
    assert w.start_buttons[START_AUTO].isChecked(), "★既定は 自動（通常プレイ向け / 仕様 §5）"
    assert [b.text() for b in w.start_buttons.values()] == ["自動", "手動"]
    assert "AUTO と TURBO" in w.start_buttons[START_AUTO].toolTip()
    assert "A（AUTO）" in w.start_buttons[START_MANUAL].toolTip()

    w.start_buttons[START_MANUAL].click()
    body = json.loads((tmp_path / "ui.json").read_text(encoding="utf-8"))
    assert body["automation"]["battle_auto_known"] is False
    lua = tmp_path / "work" / "generated" / BA.OVERLAY_NAME
    assert "auto_known = false" in lua.read_text(encoding="utf-8"), "⚠⚠ 手動にしたのに Lua へ渡っていない"
    assert BattleAiWindow(hub).start_buttons[START_MANUAL].isChecked(), "⚠ 開き直したら戻っていた"

    w.start_buttons[START_AUTO].click()
    assert "auto_known = true" in lua.read_text(encoding="utf-8"), "⚠⚠ 自動に戻したのに Lua へ渡っていない"


def test_前の管理画面の設定を引き継ぐ(tmp_path, monkeypatch):
    """★2026-09-13 まで管理画面で「倒したことのある敵とは自動で戦う」を切っていた人は「手動」で開く。"""
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    (tmp_path / "ui.json").write_text(json.dumps({"automation": {"battle_auto_known": False}}), encoding="utf-8")
    from dq3.ui.battle_ai_window import START_MANUAL, BattleAiWindow

    hub, _cmd = _hub(tmp_path, monkeypatch)
    assert BattleAiWindow(hub).start_buttons[START_MANUAL].isChecked()


def test_メイン画面には置かない():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    # ★部品で見る（⚠ 註の「戦闘開始時」という字では決めない / 字で見ると註に反応した）
    for widget in ("START_AUTO", "START_MANUAL", "start_buttons", "set_battle_start"):
        assert widget not in src, "⚠⚠ 戦闘開始時の切り替えをメイン画面に置いた（仕様 §10）: %s" % widget
