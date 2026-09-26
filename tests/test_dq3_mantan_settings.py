"""まんたんの設定画面（RX3-0160 / 2026-09-11）。★RX3-0158 §14 の推奨案。

★固定すること（報告 §15 のテスト観点）:

```text
1 画面で何も変えていなければ、設定ファイルの値そのまま（★入れた日に動きを変えない）
2 画面で変えた項目だけが上書きされ、既定に戻すと消える
3 壊れた値は既定へ落とし、理由を出す（⚠ 黙って捨てない）
4 ⚠ 設定ファイル（YAML）は書き換えない
5 まんたんは始めるたびに読み直す（★Lua の足場で動かして見る）
```
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.phase0 import mantan_settings as MS          # noqa: E402
from dq3.ui.ui_settings import UiSettings              # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

YAML = """dq3_phase0:
  mantan:
    # ★註（⚠ 消えてはいけない）
    healer: p3
    spell: ホイミ
    hp_below: 90
    min_mp: 4
    turbo: true
    heal_order: spell_first
    casters: [p1, p2, p3, p4]
    max_casts: 12
"""


@pytest.fixture()
def bench(tmp_path):
    cfg = tmp_path / "dq3_phase0.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    settings = UiSettings(tmp_path / "ui.json")
    return cfg, settings, tmp_path


# ======================================================================
# ★値
# ======================================================================

def test_画面で何も変えていなければ設定ファイルの値(bench):
    cfg, settings, _ = bench
    eff = MS.effective(settings, cfg)
    assert eff.value == MS.MantanSettings(healer="p3", hp_below=90, min_mp=4, turbo=True)
    assert set(eff.source.values()) == {"file"}
    assert eff.problems == []


def test_既定はいまの設定ファイルと同じ():
    """⚠ 入れた日に動きを変えない（★本物の YAML と型の既定が同じ）。"""
    eff = MS.effective(None)
    assert eff.value == MS.DEFAULTS, "⚠⚠ 本物の設定ファイルと既定がずれている"


def test_画面で変えた項目だけが上書きされる(bench):
    cfg, settings, _ = bench
    assert MS.set_value(settings, "hp_below", 70) is None
    eff = MS.effective(settings, cfg)
    assert eff.value.hp_below == 70 and eff.source["hp_below"] == "screen"
    assert eff.value.healer == "p3" and eff.source["healer"] == "file", "⚠ 他の項目まで変わった"


def test_既定に戻すと設定ファイルの値へ(bench):
    cfg, settings, _ = bench
    MS.set_value(settings, "hp_below", 70)
    MS.set_value(settings, "healer", "p2")
    MS.reset(settings, "hp_below")
    eff = MS.effective(settings, cfg)
    assert eff.value.hp_below == 90 and eff.value.healer == "p2"
    MS.reset(settings)
    assert set(MS.effective(settings, cfg).source.values()) == {"file"}


@pytest.mark.parametrize("field, value", [
    ("healer", "p9"), ("healer", "僧侶"),                 # ⚠ 並びの番号だけ
    ("hp_below", 200), ("hp_below", 10), ("hp_below", "高め"), ("hp_below", True),
    ("min_mp", -1), ("min_mp", 99),
    ("turbo", "yes"),
])
def test_駄目な値は書かない(bench, field, value):
    cfg, settings, _ = bench
    why = MS.set_value(settings, field, value)
    assert why, "⚠⚠ 駄目な値を受け付けた"
    assert MS.effective(settings, cfg).source[field] == "file"


def test_壊れた設定ファイルは既定へ落として理由を出す(bench):
    """⚠⚠ DQ2 と同じ: 設定が 1 つ壊れていても遊べること。"""
    cfg, settings, _ = bench
    cfg.write_text(YAML.replace("healer: p3", "healer: p9"), encoding="utf-8")
    eff = MS.effective(settings, cfg)
    assert eff.value.healer == "p3" and eff.source["healer"] == "default"
    assert any("p1〜p4" in p for p in eff.problems), "⚠ 理由を出していない"


def test_設定ファイルは書き換えない(bench):
    """⚠⚠ 註が消える / Git が汚れる（RX3-0158 §3）。★画面の値は UiSettings へ。"""
    cfg, settings, tmp = bench
    before = cfg.read_bytes()
    MS.set_value(settings, "hp_below", 70)
    MS.write_overlay(settings, tmp)
    MS.reset(settings)
    assert cfg.read_bytes() == before
    src = (ROOT / "dq3" / "phase0" / "mantan_settings.py").read_text(encoding="utf-8")
    assert "safe_dump" not in src and "yaml.dump" not in src, "⚠⚠ YAML を書いている"


# ======================================================================
# ★まんたんへ渡す重ね書き
# ======================================================================

def test_重ね書きは画面で変えた項目だけ(bench):
    cfg, settings, tmp = bench
    MS.set_value(settings, "hp_below", 70)
    MS.set_value(settings, "turbo", False)
    text = MS.write_overlay(settings, tmp).read_text(encoding="utf-8")
    assert "return {hp_below = 70, turbo = false}" in text
    assert "healer" not in text, "⚠ 変えていない項目まで重ねている"


def test_何も変えていなければ空の表(bench):
    _cfg, settings, tmp = bench
    assert "return {}" in MS.write_overlay(settings, tmp).read_text(encoding="utf-8")


# ======================================================================
# ★画面（offscreen）
# ======================================================================

class _VM:
    def party_names(self): return ["あかり", "ハンソロ", "エルシド", "ロミオ"]
    def ai_members(self): return []


class _Commands:
    def __init__(self): self.sent = []
    def send(self, action, **params): self.sent.append(action); return 1


@pytest.fixture()
def window(bench, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from dq3.ui.mantan_window import MantanWindow

    QApplication.instance() or QApplication([])
    cfg, settings, tmp = bench
    monkeypatch.setattr(MS, "overlay_path", lambda out_dir=None: tmp / "dq3_mantan.lua")
    cmd = _Commands()
    win = MantanWindow(settings, _VM(), cmd, None, config_path=cfg)
    return win, settings, cmd, tmp, cfg


def test_窓は今の値で開く(window):
    win, _settings, _cmd, _tmp, _cfg = window
    # ★RX3-0221: 回復役の欄は消した（唱えてよい人のチェックと重なる）
    assert not hasattr(win, "healer"), "⚠ 回復役の欄が残っている"
    assert all(win.casters[s].isChecked() for s in MS.HEALERS), "⚠ 唱えてよい人の既定は全員"
    assert "エルシド" in win.casters["p3"].toolTip(), "⚠ 名前が出ていない"
    assert win.hp.value() == 90 and win.mp.value() == 4 and win.turbo.isChecked()
    assert "設定ファイルの値で動いています" in win.file_note.text()


def test_動かすとすぐ保存して重ね書きを書く(window):
    """★戦闘 AI 設定の窓と同じ（⚠ 保存ボタンを押し忘れる事故を作らない）。"""
    win, settings, _cmd, tmp, cfg = window
    win.hp.setValue(70)
    win.casters["p3"].setChecked(False)
    eff = MS.effective(settings, cfg)
    assert eff.value.hp_below == 70 and eff.value.casters == ("p1", "p2", "p4")
    text = (tmp / "dq3_mantan.lua").read_text(encoding="utf-8")
    assert "hp_below = 70" in text and 'casters = {"p1", "p2", "p4"}' in text
    assert "画面で変えている" in win.file_note.text()


def test_HPは5刻み(window):
    win, settings, _cmd, _tmp, cfg = window
    win.hp.setValue(73)
    assert MS.effective(settings, cfg).value.hp_below == 75


def test_既定に戻すボタン(window):
    win, settings, _cmd, _tmp, cfg = window
    win.hp.setValue(70)
    win.reset_all()
    assert MS.effective(settings, cfg).value.hp_below == 90
    assert win.hp.value() == 90


def test_実行は満と同じ頼み(window):
    win, _settings, cmd, _tmp, _cfg = window
    win.run_now()
    assert cmd.sent == ["mantan"], "⚠ 新しい押し方を作っている"


def test_戦闘中の回復は別の窓だと書いてある(window):
    """⚠ 「回復役」が 2 か所にある（RX3-0158 §13）。★言葉で分ける。"""
    from dq3.ui.mantan_window import BATTLE_NOTE

    win = window[0]
    assert "AI設定" in BATTLE_NOTE


def test_右画面の1行(bench):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from dq3.ui.mantan_window import MantanRow

    QApplication.instance() or QApplication([])
    cfg, settings, _ = bench
    row = MantanRow(settings, _VM(), config_path=cfg)
    # ★RX3-0221: 回復役の欄を消したので、右画面の 1 行は唱えてよい人（★全員なら「全員」）
    assert row.summary.text() == "全員・HP 90% 未満"
    MS.set_value(settings, "hp_below", 70)
    row.refresh()
    assert row.summary.text() == "全員・HP 70% 未満"
    MS.set_value(settings, "casters", ["p2", "p4"])
    row.refresh()
    assert row.summary.text() == "ハンソロ・ロミオ・HP 70% 未満"


def test_本物の右画面に行がある():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from dq3.ui.main_window import Dq3MainWindow
    from dq3.ui.view_model import Dq3ViewModel

    QApplication.instance() or QApplication([])
    win = Dq3MainWindow(Dq3ViewModel())
    assert win.mantan_row.button.text() == "設定"
    win.open_mantan()
    assert win._mantan.windowTitle() == "まんたん設定"


# ======================================================================
# ★まんたん（Lua）が始めるたびに読み直す
# ======================================================================

RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_mantan_reload_test.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"


@pytest.fixture(scope="module")
def reload_run() -> str:
    if not (DLL.exists() and RUNNER.exists() and HARNESS.exists()):
        pytest.skip("Lua を動かせない環境")
    from dq3.phase0.generate_lua import build, write_lua

    write_lua(build())
    done = subprocess.run([sys.executable, str(RUNNER), str(HARNESS)], cwd=str(ROOT),
                          capture_output=True, timeout=180, text=True,
                          encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, "⚠⚠ 落ちました" + chr(10) + both
    return both


def test_まんたんが始めるたびに読み直す(reload_run):
    assert "再起動なしで" in reload_run, reload_run
    assert "すべて合格" in reload_run


def test_読み直しのOKが減っていない(reload_run):
    n = sum(1 for line in reload_run.splitlines() if re.match(r"^OK\b", line))
    assert n >= 5, reload_run


# ======================================================================
# ★回復のしかた（RX3-0174 / 2026-09-11 依頼者「道具を優先 / 呪文を優先 / 道具を使わない を設定で」）
# ======================================================================

def test_回復のしかたを選べてLuaへ渡る(bench):
    cfg, settings, tmp = bench
    assert MS.effective(settings, cfg).value.heal_order == "spell_first"
    assert MS.set_value(settings, "heal_order", "item_first") is None
    assert MS.effective(settings, cfg).value.heal_order == "item_first"
    lua = MS.write_overlay(settings, tmp).read_text(encoding="utf-8")
    assert 'heal_order = "item_first"' in lua, lua
    assert MS.set_value(settings, "heal_order", "おまかせ") is not None, "⚠ 知らない語を通した"
    assert MS.HEAL_ORDER_UI == {"spell_first": "呪文を優先", "item_first": "道具を優先",
                                "spell_only": "道具を使わない"}


def test_回復のしかたは既定と違うときだけ右画面に出る(bench):
    cfg, settings, _ = bench
    eff = MS.effective(settings, cfg)
    assert "優先" not in MS.summary(eff), "⚠ 既定なのに 1 行が長くなった"
    MS.set_value(settings, "heal_order", "spell_only")
    assert MS.summary(MS.effective(settings, cfg)).endswith("・道具を使わない")


def test_Luaの語と画面の語が同じ():
    """⚠ 画面の 3 つの語と Lua（mantan_items.lua）の語がずれると、黙って既定で動く。"""
    lua = (ROOT / "dq3" / "phase0" / "mantan_items.lua").read_text(encoding="utf-8")
    for key in MS.HEAL_ORDERS:
        assert '"%s"' % key in lua, key
