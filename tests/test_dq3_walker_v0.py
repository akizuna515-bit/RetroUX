"""MAP 制約つき Random Walker v0（RX3-0031 / 2026-08-31）。

★★ ここが要 ★★

偽の地図を置き、⚠ **本物の `walker_v0.lua` をそのまま動かす**。
実機を起動せずに、次を見ます。

- ★押しても動かない向きを覚えるか（⚠ 通行可否を**前提にしない**）
- ⚠ 閉じ込められたら止まるか
- ⚠ 止まる合図（戦闘など）で、その場でやめるか
- ★未訪問を好み、直前へは戻りにくいか（⚠ ただし禁止ではない）

## ⚠⚠ なぜ「予測」を使わないのか

  ★DQ3 の「どの地形が歩けるか」は世界地図もローカルも**未検証**（`RX3-0010`）。
  ⚠ 予測を前提にすると、外れたときに「walker のバグ」と「仮説の誤り」を
  切り分けられません。→ ★**押してみて、座標が変わったかで決める**。
"""

from __future__ import annotations

import io
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_walker_v0_test.lua"
TARGET = ROOT / "dq3" / "phase0" / "walker_v0.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists() and TARGET.exists()),
    reason="Lua を動かせない環境")


@pytest.fixture(scope="module")
def result() -> str:
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(ROOT), capture_output=True, timeout=180,
        text=True, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, f"⚠⚠ 落ちました\n{both}"
    return both


def test_最後まで走って合格する(result):
    assert "すべて合格" in result, result


def test_OKが減っていない(result):
    n = sum(1 for line in result.splitlines() if re.match(r"^OK\b", line))
    assert n >= 17, f"⚠ OK が {n} 件しかありません\n{result}"


def test_壁を覚えることを動かして確かめている(result):
    for line in ("OK 押しても動かない向きを覚える",
                 "OK 同じ壁には二度ぶつからない",
                 "OK ok の行は本当に動いている（★歩けない升へは行かない）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_止まる道が全部あることを動かして確かめている(result):
    for line in ("OK 四方が塞がったら止まる（boxed_in）",
                 "OK 上限まで歩いたら止まる（max_steps）",
                 "OK 止まる合図（戦闘など）で、その場でやめる",
                 "OK 場所が読めなければ止まる（state_unavailable）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result


def test_重みが効いていることを動かして確かめている(result):
    for line in ("OK 未訪問の升を好んで選ぶ",
                 "OK 直前の升へは戻りにくい",
                 "OK 戻る道しか無ければ、ちゃんと戻る（⚠ 禁止にしていない）"):
        assert line in result, "⚠ " + line + " が出ていません" + chr(10) + result
    assert "★実測: up=" in result, "⚠ 実測値が出ていません"


def test_通行可否を前提にしていない():
    """⚠⚠ **予測に頼らないこと**が walker v0 の芯です。

    ★`RX3-0010`（通行可否）が未検証のうちは、⚠ 予測を前提にすると
    「walker のバグ」と「仮説の誤り」を切り分けられません。
    """
    src = io.open(TARGET, encoding="utf-8", newline="").read()
    body = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("--"))
    for gone in ("walkmap", "collision", "BLOCKED_BIT", "0x80"):
        assert gone not in body, (
            "⚠⚠ 通行可否の予測に頼っています（%s）" % gone)
    assert "self.blocked[" in body, (
        "⚠⚠ 押して動かなかったことを覚えていません")


def test_止まる理由の語を増やしていない():
    """⚠ `auto_v0` / `mantan_v0` と語彙を分けないこと。"""
    src = io.open(TARGET, encoding="utf-8", newline="").read()
    got = set(re.findall(r'self\.stop\("([a-z_]+)"\)', src))
    known = {"max_steps", "boxed_in", "state_unavailable"}
    assert got == known, "⚠ 止まる理由が変わりました: %s" % (got,)
