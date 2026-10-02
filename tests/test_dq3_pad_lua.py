"""人のパッド入力（Lua）を実機なしで動かす（RX3-0486 / 2026-10-02）。

★`tests/lua/dq3_pad_test.lua` を FCEUX 同梱の `lua5.1.dll` で動かします
（`research/probes/reusable/lua_run.py`）。
⚠ 中で見ること: 読み込める（★Lua 5.1 の上限）/ 半端な行 / 0.5 秒で離す / ターボ中も途切れない /
  `B.tick` は自動を優先し、⚠ true だけを 1 回だけ渡す。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "tests" / "lua" / "dq3_pad_test.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"

pytestmark = pytest.mark.skipif(not (RUNNER.exists() and DLL.exists()),
                                reason="Lua を動かす材料が無い（tools/fceux/lua5.1.dll）")


def test_パッドの読み手とB_tickの調停():
    proc = subprocess.run([sys.executable, str(RUNNER), str(HARNESS)], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "PAD_TEST passed=" in out and "failed=0" in out, out
