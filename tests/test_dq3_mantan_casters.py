"""まんたん: 唱えてよい人をチェックで選ぶ ＋ 勇者の MP は最後の手段（RX3-0214 / 2026-09-12）。

★依頼者「まんたんでは、対象のキャラを対象にするか否かを決めるチェックボックスが欲しい
（今のパーティの並び順で職業名1文字で良い） ※勇者のMPではまんたんは最後の手段」。
★「対象」= まんたんで呪文を唱える人（MP を使う人）と読んだ（WI の推奨の読み方）。
"""
from __future__ import annotations

import pytest

from dq3.phase0 import mantan_settings as MS

YAML = """dq3_phase0:
  mantan:
    healer: p3
    hp_below: 90
"""


def test_既定は全員():
    assert MS.MantanSettings().casters == MS.HEALERS
    assert "casters" in MS.FIELDS and MS.LABELS["casters"] == "唱えてよい人"


@pytest.mark.parametrize("value, expected", [
    (["p3", "p1"], ("p1", "p3")),                   # ★並びの順にそろえる
    (("P2", "p2"), ("p2",)),                        # ★大文字 / 重ねても 1 回
])
def test_唱えてよい人の値を確かめる(value, expected):
    assert MS.check("casters", value) == (expected, None)


@pytest.mark.parametrize("value", [[], ["p9"], "p1", 3, None])
def test_おかしな値は理由つきで断る(value):
    got, why = MS.check("casters", value)
    assert got is None and why


def test_重ね書きはLuaの並び(tmp_path):
    from dq3.ui.ui_settings import UiSettings

    settings = UiSettings(tmp_path / "ui.json")
    assert MS.set_value(settings, "casters", ["p2", "p3"]) is None
    text = MS.overlay_lua(settings)
    assert 'casters = {"p2", "p3"}' in text, text
    assert MS.effective(settings, tmp_path / "none.yaml").value.casters == ("p2", "p3")


class _VM:
    def party_names(self): return ["アレル", "ミリア", "ガイ", "ルナ"]

    def ai_members(self):
        # ★勇者（0）/ 僧侶（2）/ 戦士（4）/ 魔法使い（1・女 = 9）
        return [{"slot": "p1", "class_gender": 0}, {"slot": "p2", "class_gender": 2},
                {"slot": "p3", "class_gender": 4}, {"slot": "p4", "class_gender": 9}]


@pytest.fixture()
def window(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from dq3.ui.mantan_window import MantanWindow
    from dq3.ui.ui_settings import UiSettings

    QApplication.instance() or QApplication([])
    cfg = tmp_path / "dq3_phase0.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    settings = UiSettings(tmp_path / "ui.json")
    monkeypatch.setattr(MS, "overlay_path", lambda out_dir=None: tmp_path / "dq3_mantan.lua")
    win = MantanWindow(settings, _VM(), None, None, config_path=cfg)
    return win, settings, cfg, tmp_path


def test_唱えてよい人は職業名1文字で並ぶ(window):
    win, _settings, _cfg, _tmp = window
    assert [win.casters[s].text() for s in MS.HEALERS] == ["勇", "僧", "戦", "魔"]
    assert all(win.casters[s].isChecked() for s in MS.HEALERS), "⚠ 既定は全員"
    assert "勇者" in win.casters["p1"].toolTip() and "アレル" in win.casters["p1"].toolTip()
    assert "勇者" not in win.casters["p2"].toolTip()


def test_外すと保存して重ね書きへ(window):
    win, settings, cfg, tmp = window
    win.casters["p3"].setChecked(False)
    assert MS.effective(settings, cfg).value.casters == ("p1", "p2", "p4")
    assert 'casters = {"p1", "p2", "p4"}' in (tmp / "dq3_mantan.lua").read_text(encoding="utf-8")


def test_全員は外せない(window):
    win, settings, cfg, _tmp = window
    for slot in ("p1", "p2", "p3"):
        win.casters[slot].setChecked(False)
    win.casters["p4"].setChecked(False)
    assert MS.effective(settings, cfg).value.casters == ("p4",), "⚠ 全員外れた（★誰も唱えない）"
    assert win.casters["p4"].isChecked(), "⚠ 断ったのにチェックが外れて見える"
    assert "1 人は" in win.problems.text()


def test_右画面の1行は唱える人(tmp_path):
    """★RX3-0221: 回復役の欄を消したので、右画面の 1 行も唱えてよい人を出す（★全員なら「全員」）。"""
    from dq3.ui.ui_settings import UiSettings

    cfg = tmp_path / "dq3_phase0.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    settings = UiSettings(tmp_path / "ui.json")
    names = {"p1": "アレル", "p2": "ミリア", "p3": "ガイ", "p4": "ルナ"}
    assert MS.summary(MS.effective(settings, cfg), names).startswith("全員・HP 90% 未満")
    MS.set_value(settings, "casters", ["p2", "p4"])
    assert MS.summary(MS.effective(settings, cfg), names).startswith("ミリア・ルナ・HP 90% 未満")
