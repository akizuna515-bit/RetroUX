"""restock_v0（補充の Lua）を実機なしで動かす（RX3-0066 / RX3-0119）。

★足場は `research/probes/active/dq3_restock_v0_test.lua`。
⚠⚠ **買い物は取り返しがつきません。** ★ここで固定するのは、
「窓が無ければ 1 つも押さない」「買えていなければ止まる」です。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_restock_v0_test.lua"
TARGET = ROOT / "dq3" / "phase0" / "restock_v0.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists() and TARGET.exists()),
    reason="Lua を動かせない環境")


@pytest.fixture(scope="module")
def result() -> str:
    done = subprocess.run([sys.executable, str(RUNNER), str(HARNESS)], cwd=str(ROOT),
                          capture_output=True, timeout=180, text=True,
                          encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, "⚠⚠ 落ちました" + chr(10) + both
    return both


def test_最後まで走って合格する(result):
    assert "すべて合格" in result, result


def test_OKが減っていない(result):
    n = sum(1 for line in result.splitlines() if re.match(r"^OK\b", line))
    assert n >= 10, "⚠ OK が %d 件しかありません%s%s" % (n, chr(10), result)


def test_安全側の約束を動かして確かめている(result):
    for line in ("OK 店の窓が無ければ 1 つも押さない",
                 "OK 計画が空なら押さない",
                 "OK 窓を確かめてから押す（売買選択 → 品揃え → 持ち主）",
                 "OK 買えたと言い張らない（所持金と袋の両方を見る）",
                 "OK 買えたら数え、もう買わないなら「いいえ」へ寄せる",
                 "OK 戦闘中は押さない",
                 # ★RX3-0202「DQ2のような対応が必要（平均的に所持）」
                 "OK 1 個ごとに持ち主を変える（carriers の順）",
                 "OK 満杯の持ち主は RAM を見て選び直す",
                 "OK 「もてない」と聞かれたら いいえ（B）で答えて carrier_full で止まる",
                 "OK 誰にも空きが無ければ持ち主の窓で押さない"):
        assert any(ln.startswith(line) for ln in result.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + result)
