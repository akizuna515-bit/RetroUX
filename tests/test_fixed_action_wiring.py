"""固定行動（ユーザー指定1）の Lua 配線（2026-08-11 / UI整理 Phase 4）。

★ここは「配線が消えていない」ことを**ソースで**守ります。

⚠⚠ **2026-08-12 の訂正。** ここには元々こう書いてありました:

    ⚠ FCEUX の Lua は実機でしか動かせない（Lua ランタイムを同梱していない）。

★これは**誤りです。** `tools/fceux/lua5.1.dll` があり、
  `research/probes/reusable/lua_run.py` で**実機なしに実 Lua を動かせます**
  （`tests/test_menu_cleanup.py` など多数が既にそうしています）。

⚠ この誤った断り書きのせいで、下の「防御にフォールバックできる」は
  **ソースに文字列があるか**しか見ていませんでした。その結果、
  ★防御の入力は**実機で1度も成功していないのに緑のまま**でした
  （依頼者の実機ログ「防御の入力が 17 回で進まない」）。

★**挙動は `tests/test_defend_input.py` が実際に呼んで確かめます。**
  ここは配線が消えていないことだけを見ます（役割の違いに注意）。

守りたい配線:
  1. 戦闘中枢が固定行動を見て、優先順(heal/attack/item)を横取りする
  2. 指定の道具は条件なしで使う（`_forced_item` / `forced`）
  3. 有効判定は `tactics.lua` の `strategy` 目印 × config の user_strategies
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (PROJECT_ROOT
          / "retroux" / "emulator" / "fceux" / "bridge.lua")


def _src() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def test_固定行動の判定関数がある():
    src = _src()
    assert "function Bridge:_fixed_action_for_current()" in src
    # ★tactics.lua の strategy 目印を見て、config の user_strategies を引く
    assert "self.tactics.strategy" in src or "self.tactics and self.tactics.strategy" in src
    assert "user_strategies" in src


def test_戦闘中枢が固定行動を横取りする():
    src = _src()
    # ★中枢で判定関数を呼んでいる
    assert "self:_fixed_action_for_current()" in src
    # ★固定戦略のときは優先順ループを回さない
    assert "skip_priority" in src


def test_指定の道具は条件なしで使う():
    src = _src()
    # ★`_forced_item` を立てて道具使用を呼ぶ
    assert "self._forced_item" in src
    assert "_find_battle_item(m.index, m, forced)" in src \
        or "_find_battle_item(m.index, m, self._forced_item)" in src
    # ★_find_battle_item に forced 経路がある（条件を見ない）
    assert "function Bridge:_find_battle_item(who, member, forced)" in src


def test_固定時は通常の歯止めを飛ばす():
    """⚠ 有効か／回数上限／reusable の歯止めは固定戦略では見ない。"""
    src = _src()
    assert "local forced = self._forced_item" in src
    # ★reusable の歯止めを forced のとき飛ばす
    assert "forced == nil" in src


def test_道具が無ければ防御にフォールバックできる():
    """★★ 2026-08-11: 亀の子戦術「無ければ防御」（依頼者）★★

    ⚠ 指定の道具（ちからのたて）が持ち物に無いとき、fallback: defend なら
      「ぼうぎょ」する。防御の入力は役割「手動:防御」と1か所（`_claim_defend`）。

    ⚠⚠ **ここは「呼んでいる」ことしか見ていません。**
      ★実際に押せるか（＝遊んで役に立つか）は
        `tests/test_defend_input.py` が実 Lua で確かめます。
    """
    src = _src()
    # ★判定関数が fallback を運ぶ
    assert "fallback = spec.fallback" in src
    # ★防御の入力は共通関数
    assert "function Bridge:_claim_defend(m)" in src
    # ★中枢: 道具が使えなかったとき fallback == defend なら防御を呼ぶ
    assert 'fixed.fallback == "defend"' in src
    assert "self:_claim_defend(dm)" in src



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ 上の検査は全部「`bridge.lua` にこの文字列があるか」だけです。
#   ★引き当ての鍵をひとつ間違えても、Lua は落ちずに「見つからない＝既定」へ
#     落ちるので、**素通りしたまま緑**になります。
#   実際 2026-08-11 の「無ければ防御」は、字面は合っているのに
#   **実機で1度も成功していません**でした。
# =====================================================================


@pytest.fixture(scope="module")
def lua_result():
    harness = (PROJECT_ROOT / "research" / "probes" / "active"
               / "fixed_action_test.lua")
    runner = (PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py")
    if not (runner.exists() and harness.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(runner), str(harness)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_本物のbridgeで固定行動が引ける(lua_result):
    assert "すべて合格" in lua_result, lua_result


def test_検査の数が足りている(lua_result):
    """⚠ 途中で落ちて「0件でも合格」にしない。"""
    count = sum(1 for line in lua_result.splitlines()
                if line.startswith("OK "))
    assert count >= 11, f"OK が {count} 件しかありません\n{lua_result}"


def test_鍵は表示名であること(lua_result):
    """⚠⚠ **ここを間違えると亀の子が丸ごと効きません。**

    ★内部ID（`samaltria`）で書いた設定は引けないこと＝表示名で引いている証拠。
      ⚠ 内部IDでも引けてしまうなら、実装が別物になっています。
    """
    assert _ok(lua_result, "内部IDで書いた設定は引かない"), lua_result


def test_番が読めないときは横取りしない(lua_result):
    """★人の番を AI が奪う形の不具合を防ぎます。"""
    assert _ok(lua_result, "★番が読めなければ nil"), lua_result


def test_無ければ防御を本当に運んでいる(lua_result):
    """★2026-08-11 の依頼「道具が無ければ防御」。字面ではなく値で見ます。"""
    assert _ok(lua_result, "★代替行動（無ければ防御）を運ぶ"), lua_result
