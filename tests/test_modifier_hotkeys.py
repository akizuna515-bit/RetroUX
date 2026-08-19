"""修飾キー付きホットキー（2026-08-01 / 課題 #48・#56）。

★★ **本物の Lua を走らせる。** ★★

## 依頼者の報告

  #48（2026-08-01）
      「メモ（Ctrl+M）は、マップにフォーカスを明示的に示せば動くが、
        ゲーム画面からやると満タンがうごいてしまう」

  #56（2026-08-01）
      「いまの場所を追うが外れる？ → Fと連動してる。
        FはFCEUXのAボタンと一緒なので」

## ⚠⚠ 何が起きていたか

`input.get()` は `"Ctrl+M"` という名前を**返しません**（キー名は `M` と
`control` が別々に来る / `lua-engine.cpp:2500`）。

そのため:

  ・**修飾つきの割り当ては一度も発火しなかった**
  ・代わりに**修飾なしの同じ文字**（`M` = まんたん）が発火した
  ・`F`（= FCEUX の A ボタン）は、戦闘で攻撃するたびに発火した
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
           / "modifier_key_test.lua")


@pytest.fixture(scope="module")
def result():
    if not (RUNNER.exists() and HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def test_the_harness_passes(result):
    assert "不合格 0" in result, result


def test_ctrl_m_does_not_fire_mantan(result):
    """★★ **#48 そのもの** ★★

    ⚠ `mantan` は `M`（修飾なし）に割り当ててある。
      `Ctrl+M`（メモ）を押したときに動いてはいけない。
    """
    assert "OK   M の割り当ては Ctrl+M で発火しない" in result, result


def test_plain_m_still_fires_mantan(result):
    """⚠ 直しすぎて `M` まで効かなくなっていないこと。"""
    assert "OK   M の割り当ては M だけで発火する" in result, result


def test_an_extra_modifier_does_not_fire(result):
    """⚠ `Ctrl+M` に Shift が足されたら別の操作。発火させない。"""
    assert "OK   Ctrl+M に Shift が足されたら発火しない" in result, result


def test_a_modified_key_survives_the_game_button(result):
    """★★ **#56 そのもの** ★★

    `F` は FCEUX の A ボタン。`Ctrl+F` なら攻撃で発火しない。
    """
    assert "OK   Ctrl+F は F だけでは発火しない" in result, result


def test_it_reports_enough_checks(result):
    m = re.search(r"合計 (\d+) 項目", result)
    assert m and int(m.group(1)) >= 20, result


# --- 割り当てそのもの --------------------------------------------------

def _bindings() -> dict:
    path = PROJECT_ROOT / "retroux" / "config" / "default_keybindings.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_map_follow_key_is_not_a_bare_f():
    """★★ **F はゲームの A ボタン**（依頼者の実機確認）★★

    ⚠ 修飾なしの `F` に戻したら、また戦闘のたびに追従が反転する。
    """
    keys = (_bindings()["bindings"]["toggle_map_follow"] or {}).get("keyboard")
    assert keys, "割り当てが空"
    assert "F" not in keys, f"F は FCEUX の A ボタン: {keys}"


def test_the_hazard_is_written_down():
    """★なぜ F を避けるのかを設定ファイルに書く（また戻さないため）。

    ⚠ 理由が書いていないと、次に見た人が「短いほうが押しやすい」と
      戻してしまう。
    """
    text = (PROJECT_ROOT / "retroux" / "config"
            / "default_keybindings.yaml").read_text(encoding="utf-8")
    assert "Aボタン" in text or "A ボタン" in text
    assert "ゲームの操作キー" in text
