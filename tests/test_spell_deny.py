"""「唱えてはいけない呪文」と「マホトーン中は唱えない」を Lua で**実際に呼ぶ**。

★なぜ Python のテストから Lua を呼ぶか（playbook）:
  `DQ2:spell_denied` / `DQ2:spell_blocked` は memory_map の構造に依存する。
  キー名を1つ間違えても構文は正しいので `research/probes/reusable/luacheck.py` は通り、
  **実機で初めて分かる**。FCEUX 同梱の `lua5.1.dll` で本物を呼ぶ。

★守っている契約（中身は research/probes/active/deny_test.lua）:
  1. メガンテ(0x0C) / パルプンテ(0x0F) / ルーラ(0x14) が理由つきで拒否される
  2. 回復呪文は拒否されない（機能を殺していない）
  3. 未知の呪文IDも拒否される
  4. マホトーン中は `Bridge:_plan_battle_heal` が計画を返さず、
     **その理由がマホトーンである**（別の理由で落ちていたら何も確かめていない）

⚠ 材料（lua5.1.dll / work/ramdump / work/generated）が無い環境では skip する。
  ここで落とすと本題と関係ないテストが赤くなる。
  ★ただし **skip と成功を混ぜない**: Lua 側は材料が無いとき終了コード 2 を返し、
    ここでそれを skip として扱う（playbook #43「採れなかったを合格に見せない」）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DLL = PROJECT_ROOT / "tools" / "fceux" / "lua5.1.dll"
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
SCRIPT = PROJECT_ROOT / "research" / "probes" / "active" / "deny_test.lua"
GENERATED = PROJECT_ROOT / "work" / "generated" / "memory_map.lua"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and SCRIPT.exists() and GENERATED.exists()),
    reason=("Lua を動かす材料が無い（tools/fceux/lua5.1.dll・research/probes/active/deny_test.lua・"
            "work/generated）。python -m retroux.core.config.generate_lua で"
            "生成できる"),
)


@pytest.fixture(scope="module")
def result() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUNNER), str(SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT,
        env={**__import__("os").environ, "RETROUX_ROOT": str(PROJECT_ROOT)},
    )


def test_lua_checks_pass(result):
    """★本題: NG が 0 件であること。"""
    out = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 2:
        pytest.skip("RAM ダンプが無いためマホトーンの検査を実施できていない:\n" + out)
    assert result.returncode == 0, "deny_test.lua が NG を報告しました:\n" + out
    assert "NG 0 件" in out, out


def test_reports_some_checks(result):
    """★検査が1件も走らずに「成功」になっていないこと。

    条件が揃わないと `check()` が呼ばれず、それでも終了コードは 0 になる。
    「採れなかった」を合格に見せないため、件数の下限を置く。
    """
    out = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 2:
        pytest.skip("材料不足")
    import re
    m = re.search(r"OK (\d+) 件", out)
    assert m is not None, "件数が報告されていない:\n" + out
    assert int(m.group(1)) >= 20, f"検査が {m.group(1)} 件しか走っていない:\n{out}"


def test_silence_reason_is_reported(result):
    """マホトーンで落ちたことが**理由の文字列**で分かること。

    「唱えない」だけでは、回復不要で落ちたのか封じられて落ちたのか区別できない。
    """
    out = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 2:
        pytest.skip("材料不足")
    assert "マホトーンで呪文を封じられている" in out, out


def test_dangerous_spells_appear_in_output(result):
    """3つの危険な呪文がすべて検査対象に入っていること。"""
    out = (result.stdout or "") + (result.stderr or "")
    for label in ("0x0C", "0x0F", "0x14"):
        assert label in out, f"{label} が検査されていない:\n{out}"
