"""画面の組み立ては Lua と Python で同じ答えになる（RX3-0016 / 2026-08-26）。

★★ なぜこの検査が要るか ★★

画面の組み立ては **2 か所**にある。

    dq3/phase0/screen.lua   ← ★実機で走るのはこちら
    dq3rom/ppu.py                             ← 解析で使うのはこちら

⚠ 同じ計算を 2 か所に書くと、**片方だけ直る**。
そして実機で走るのは Lua のほうなので、⚠ Python だけ直しても意味がない。

★ここでは **同梱の `lua5.1.dll` で本物の Lua を動かし**、
実機のセーブステートを材料に **1 バイトずつ**突き合わせる。

⚠ Python の再実装どうしを比べても「同じ勘違いを 2 回書いた」かもしれない。
★答えの元は実機のセーブステート。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

from dq3rom import ppu

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = ROOT / "research" / "probes" / "active" / "dq3_screen_test.lua"
MODULE = ROOT / "dq3" / "phase0" / "screen.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"
# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()


def _sandbox() -> pathlib.Path:
    """★走行ごとの隔離先（`conftest.py` が決める）。"""
    got = os.environ.get("RETROUX_TEST_SANDBOX")
    return pathlib.Path(got) if got else (
        ROOT / "work" / "_test_sandbox")

# ⚠ 隔離先は**走行ごとに変わる**（RX-0114 / 2026-08-30）。
#   ★`conftest.py` が `RETROUX_TEST_SANDBOX` を立てる。
#   ⚠ 直書きすると、並列で走ったとき隣の走行の書いたものを読む。
SANDBOX = _sandbox() / "work"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists() and MODULE.exists()),
    reason="Lua を動かす材料が無い")

#: ★材料に使うセーブステート。⚠ 中身の場面が違うものを混ぜる。
CASES = ["DQ3_J.fc9", "DQ3_J.fc7", "DQ3_J.fc6"]


def _write_cases() -> list[str]:
    """Python 側の答えを書き出す。★Lua はこれと突き合わせる。"""
    from retroux.core.bgmap import savestate as ss

    (SANDBOX / "dq3-probe").mkdir(parents=True, exist_ok=True)
    used: list[str] = []
    blocks: list[str] = []
    for name in CASES:
        path = FCS / name
        if not path.exists():
            continue
        chunks = ss.load(path).chunks
        scroll = ppu.scroll_of(chunks)
        ntar = bytes(chunks["NTAR"])
        want = bytes(ppu.compose(ntar, scroll, ppu.mirroring_of(chunks)))
        blocks.append(
            f"{name} {scroll.x} {scroll.y} {scroll.nametable}\n"
            f"{ntar.hex()}\n{want.hex()}\n")
        used.append(name)
    (SANDBOX / "dq3-probe" / "screen_case.txt").write_text(
        "".join(blocks), encoding="utf-8")
    return used


@pytest.fixture(scope="module")
def run() -> tuple[str, list[str]]:
    used = _write_cases()
    if not used:
        pytest.skip("セーブステートが 1 つも無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(ROOT), capture_output=True, timeout=180,
        text=True, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, f"⚠⚠ 落ちました\n{both}"
    return both, used


def test_最後まで走って合格する(run):
    out, _ = run
    assert "すべて合格" in out, f"⚠ 失敗があります\n{out}"


def test_OKが全部出ている(run):
    """⚠ 途中で静かに減っていないか。"""
    out, used = run
    count = sum(1 for line in out.splitlines() if re.match(r"^OK\b", line))
    # 純粋な計算 5 件 + セーブステートの件数
    assert count >= 5 + len(used), f"⚠ OK が {count} 件しかありません\n{out}"


def test_セーブステートごとの一致が名指しで出ている(run):
    """★「合格」だけでなく、**どのセーブステートで合ったか**を見る。

    ⚠ 材料が 0 件でも「すべて合格」は出てしまう（★0 件は合格ではない）。
    """
    out, used = run
    for name in used:
        assert f"{name} が Python と 1 バイトずつ一致" in out, (name, out)


def test_答えの用意に失敗したら気づける(run):
    """⚠ 材料の file が無いとき、Lua は**黙って飛ばさず** NG を出す。"""
    out, _ = run
    assert "答えの file が無い" not in out, out
