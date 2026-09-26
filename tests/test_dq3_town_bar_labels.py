"""街の行のボタンは 1 文字（RX3-0290 / 2026-09-18）。

⚠⚠ 依頼者「聞き込みも『聞』再聞き込みは『再』、補充は『補』にしてサイズを稼ぎたい」。

```text
★画面に出す字   宿 道 武 神 ／ 聞 再 ／ 補 ／ 止（実行中）
⚠ 名前          「聞き込み」「再聞き込み」「補充」のまま
                 ★記録（行動履歴・`[HEARING]`）とメッセージは名前で書く
★説明           1 文字では分からないので、**ツールチップに正式な名前**を入れる
```
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from dq3.ui import town_bar as TB                              # noqa: E402
from test_dq3_town_ui import _Commands, _Service, _VM          # noqa: E402


def _bar(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    return TB.TownBar(_VM(), _Service(tmp_path), _Commands())


# --- ★字 -------------------------------------------------------------------

def test_出す字はすべて1文字():
    for name, label in TB.BUTTON_LABEL.items():
        assert len(label) == 1, (name, label)
    assert len(TB.STOP_LABEL) == 1 and len(TB.RESTOCK_LABEL) == 1
    for _role, text, _name in TB.MOVE_BUTTONS:
        assert len(text) == 1, text


def test_画面のボタンも1文字(tmp_path):
    bar = _bar(tmp_path)
    buttons = list(bar.move_buttons.values()) + [bar.hear_button, bar.restock_button]
    assert [b.text() for b in buttons] == ["宿", "道", "武", "神", "入", "聞", "補"]
    for b in buttons:
        assert b.width() <= 32 or b.maximumWidth() <= 32, b.text()
    bar.close()


def test_1文字の意味はツールチップに出す(tmp_path):
    """⚠ 1 文字だけでは何のボタンか分からない（★RX3-0257 と同じ作法）。"""
    bar = _bar(tmp_path)
    assert "聞き込み" in bar.hear_button.toolTip()
    assert "補充" in bar.restock_button.toolTip()
    for role, _text, name in TB.MOVE_BUTTONS:
        assert name in bar.move_buttons[role].toolTip(), name
    bar.close()


def test_実行中は止(tmp_path):
    bar = _bar(tmp_path)
    bar._on_hear()
    assert bar.hear_button.text() == TB.STOP_LABEL
    assert "止" in bar.hear_button.toolTip()
    bar._on_hear()
    assert bar.hear_button.text() == "聞"
    bar.close()


# --- ⚠ 名前のほうは変えない ---------------------------------------------------

def test_名前は聞き込みのまま():
    """⚠⚠ 記録と台帳の文言まで 1 文字にしない（★後から読めなくなる）。"""
    assert TB.HEAR == "聞き込み" and TB.REHEAR == "再聞き込み"
    assert set(TB.BUTTON_LABEL) == {TB.HEAR, TB.REHEAR}


def test_記録とメッセージは名前で書く(tmp_path):
    """★行動履歴・画面の文は「聞き込み中」（⚠ 「聞中」にしない）。"""
    from dq3 import action_log as AL

    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    ctl = TB.TownNavController(vm, svc, cmd, clock=lambda: 0.0,
                               action_log=AL.ActionLog(clock=lambda: 0.0))
    assert ctl.hearing_kind() in (TB.HEAR, TB.REHEAR)
    assert ctl.start_hearing()
    ctl.done_count = 0
    ctl._note_progress() if hasattr(ctl, "_note_progress") else None
    assert TB.HEAR in ctl.message or TB.REHEAR in ctl.message, ctl.message


def test_1文字を台帳や記録へ混ぜない():
    """⚠ `BUTTON_LABEL` の字が、記録の文言に紛れ込んでいないこと。"""
    src = (ROOT / "dq3" / "ui" / "town_bar.py").read_text(encoding="utf-8")
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    for bad in ('"[HEARING] %s" % BUTTON_LABEL', 'begin(BUTTON_LABEL'):
        assert not any(bad in ln for ln in code), bad
