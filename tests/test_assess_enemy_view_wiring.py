"""戦況の見立てに敵ステータスが届く配線（2026-08-11 / 依頼者の実機指摘）。

★★ 直した不具合 ★★
  bridge.lua に `_enemy_view` が**2つ**あり（見立て用と道具・攻撃用）、
  Lua では後の定義が勝つため、見立て用（ROM の `stats` を載せる方）が
  **呼ばれていなかった**。道具・攻撃用は `stats` を付けないので、
  `Assessment.threat_of` が毎回「能力が分からない敵」に倒れ、戦況が
  ずっと「unknown_enemy / 能力が分からない」になっていた。

★見立て用を `_assess_enemy_view` に改名し、`_assess_battle` がそれを呼ぶ。
"""

from __future__ import annotations

import pathlib

BRIDGE = (pathlib.Path(__file__).resolve().parents[1]
          / "retroux" / "emulator" / "fceux" / "bridge.lua")


def _bridge() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def test_enemy_viewが二重定義でない():
    """⚠⚠ 同名関数が2つあると、後勝ちで**意図しない方**が呼ばれる。"""
    src = _bridge()
    assert src.count("function Bridge:_enemy_view()") == 1, (
        "⚠ `_enemy_view` が二重定義（後勝ちで見立て用が消える）")


def test_見立て用のenemy_viewがある():
    src = _bridge()
    assert "function Bridge:_assess_enemy_view()" in src


def test_assess_battleは見立て用を呼ぶ():
    """★見立て（estimate）へ渡す敵は `_assess_enemy_view` から取る。"""
    src = _bridge()
    assert "self:_assess_enemy_view()" in src


def test_見立て用はROMのstatsを敵に載せる():
    """★threat_of は `enemy.stats.attack` を読む。★stats を載せていること。"""
    src = _bridge()
    # `_assess_enemy_view` の本体で monster_stats を引き、`stats = info` を渡す
    start = src.index("function Bridge:_assess_enemy_view()")
    end = src.index("function Bridge:", start + 10)
    body = src[start:end]
    assert "monster_stats" in body, "★ROM の能力表を引いていない"
    assert "stats = info" in body, "★敵に stats を載せていない（threat が nil になる）"



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ ここは **2回**こけている場所です。どちらも「落ちない」壊れ方でした:
#
#   2026-08-06  `monster_stats` を `addresses` の下から引いていた
#               → ★全部 nil。⚠ 落ちないので気づかない
#   2026-08-11  同じ名前の関数が2つあり**後勝ちで上書き**
#               → ★戦況が毎回「能力が分からない」（依頼者の実機指摘）
#
# ★字面では「その語が出てくるか」しか見られません。**値**を見ます。
# =====================================================================

import os          # noqa: E402
import subprocess  # noqa: E402
import sys         # noqa: E402

import pytest      # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_AV_HARNESS = (_ROOT / "research" / "probes" / "active"
               / "assess_enemy_view_test.lua")
_AV_RUNNER = _ROOT / "research" / "probes" / "reusable" / "lua_run.py"


@pytest.fixture(scope="module")
def view_lua():
    if not (_AV_RUNNER.exists() and _AV_HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(_AV_RUNNER), str(_AV_HARNESS)],
        cwd=str(_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _v_ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_本物のbridgeで見立て用の敵が全部通る(view_lua):
    assert "すべて合格" in view_lua, view_lua


def test_見立ての検査の数が足りている(view_lua):
    count = sum(1 for line in view_lua.splitlines()
                if line.startswith("OK "))
    assert count >= 18, f"OK が {count} 件しかありません\n{view_lua}"


def test_敵に能力が載る(view_lua):
    """⚠⚠ **2026-08-11 の不具合そのもの**（★載らないと戦況が出せません）。"""
    assert _v_ok(view_lua, "★1体目に能力が載る"), view_lua
    assert _v_ok(view_lua, "攻撃力が入っている"), view_lua


def test_能力表をトップレベルから引く(view_lua):
    """⚠⚠ **2026-08-06 の不具合そのもの。**

    ★`monster_stats` は `memory_map` の**トップレベル**です。
    ⚠ `addresses` の下だけを見ると全部 nil になり、**落ちません**。
    """
    assert _v_ok(view_lua, "★addresses の下にしか無いときも引く"), view_lua


def test_分からないものを0にしない(view_lua):
    """★表に無い敵の能力は nil（⚠ 0 を作ると「弱い敵」に見えます）。"""
    assert _v_ok(view_lua, "⚠ 表に無い敵の能力は nil"), view_lua
    assert _v_ok(view_lua, "★名前は残す（見立てから消さない）"), view_lua


def test_印はtrueのときだけ立てる(view_lua):
    """⚠ `~= false` で立てると、壊れた値でも「回復する敵」になります。"""
    assert _v_ok(view_lua, '⚠ 文字列の "true" では印を立てない'), view_lua
    assert _v_ok(view_lua, "⚠ 付かない印は nil（false にしない）"), view_lua


def test_敵が読めなくても落ちない(view_lua):
    """★見立ては**記録と表示**のためのもの。⚠ 本体を止めません。"""
    assert _v_ok(view_lua, "⚠ 落ちずに表を返す"), view_lua
