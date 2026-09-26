"""dq3_helper.lua を**実機なしで**動かして見る（RX3-0009 / RX3-0010 / 2026-08-24）。

★★ なぜこれが要るか ★★

`research/probes/active/dq3_helper.lua` は「FCEUX の中でしか動かせない」と
思われがちだが、⚠ それは誤り。使っている API は数えるほどなので、
**偽物を置けば同梱の `lua5.1.dll` で動く**。

⚠ 2026-08-24 に helper を大きく直した（表示位置・ターボ・写す時機・通行の記録）。
★構文検査だけでは足りず、実際にこの検査が **2 つの不具合**を見つけた。

1. 扉を距離 6 以内でしか出しておらず、**探すときに何も出なかった**
2. **map が変わっただけで「歩いた」ことにしていた**（階段で飛んだ先を
   「歩いて通れた」と記録してしまう）

⚠ どちらも実機では「なんとなく動いている」ように見えるので、
★人が遊んで気づくのは難しい種類の壊れ方だった。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = PROJECT_ROOT / "research" / "probes" / "active" / "dq3_helper_test.lua"
HELPER = PROJECT_ROOT / "research" / "probes" / "active" / "dq3_helper.lua"
DLL = PROJECT_ROOT / "tools" / "fceux" / "lua5.1.dll"

#: ⚠ `lua_run.py` が `RETROUX_WRITE_ROOT` に立てる隔離先と同じ場所

def _sandbox() -> pathlib.Path:
    """★走行ごとの隔離先（`conftest.py` が決める）。"""
    got = os.environ.get("RETROUX_TEST_SANDBOX")
    return pathlib.Path(got) if got else (
        PROJECT_ROOT / "work" / "_test_sandbox")

# ⚠ 隔離先は**走行ごとに変わる**（RX-0114 / 2026-08-30）。
#   ★`conftest.py` が `RETROUX_TEST_SANDBOX` を立てる。
#   ⚠ 直書きすると、並列で走ったとき隣の走行の書いたものを読む。
SANDBOX = _sandbox() / "work"

TAB = "\t"

pytestmark = pytest.mark.skipif(
    not (DLL.exists() and RUNNER.exists() and HARNESS.exists() and HELPER.exists()),
    reason=f"Lua を動かす材料が無い（{DLL} / {HARNESS}）")


def _prepare() -> None:
    """★helper が読み書きする場所を用意する。

    ⚠ Lua はフォルダを作れない。`io.open(..., "a")` はフォルダが無いと
    **nil を返すだけ**で、⚠ そのまま「記録できなかった」が静かに通る。
    """
    (SANDBOX / "dq3-probe").mkdir(parents=True, exist_ok=True)
    (SANDBOX / "dq3-world-model").mkdir(parents=True, exist_ok=True)
    for name in ("collision_seen.txt", "walkable.txt"):
        (SANDBOX / "dq3-probe" / name).write_text("", encoding="utf-8")
    (SANDBOX / "dq3-world-model" / "doors.tsv").write_text(
        TAB.join(["9", "21", "5", "any_key", "1"]) + "\n"
        + TAB.join(["9", "4", "19", "any_key", "1"]) + "\n", encoding="utf-8")
    (SANDBOX / "dq3-world-model" / "chests.tsv").write_text(
        TAB.join(["9", "20", "13", "item", "42"]) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def result() -> str:
    _prepare()
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=180,
        text=True, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    if "lua5.1" in (done.stderr or "") and done.returncode != 0:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, f"⚠⚠ 落ちました\n{both}"
    return both


def test_最後まで走って合格する(result):
    assert "すべて合格" in result, f"⚠ 最後まで行っていません\n{result}"


def test_OKが全部出ている(result):
    """⚠ 途中で静かに減っていないか。★件数は `>=` で見る。"""
    count = sum(1 for line in result.splitlines() if re.match(r"^OK\b", line))
    assert count >= 15, f"⚠ OK が {count} 件しかありません\n{result}"


def test_歩いた記録が実際に書かれている(result):
    """★★ 「合格」だけでなく、**ファイルに残ったか**を外から見る。

    ⚠ 検査の中だけで完結させると、書き出しが壊れても気づけない。
    """
    text = (SANDBOX / "dq3-probe" / "walkable.txt").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines, "⚠ 1 行も書かれていない"
    # map,x,y,生バイト,タイル,collision
    for line in lines:
        assert re.match(r"^\d+,\d+,\d+,[0-9A-F]{2},\d+,[0-9A-F]{2}$", line), line
    assert any(line.startswith("9,20,13,0F,15,03") for line in lines), lines


def test_地図バッファも書かれている(result):
    """★実機の地図そのもの。⚠ これがあれば訪れた map を 1 マスずつ検算できる。"""
    path = SANDBOX / "dq3-probe" / "mapbuf_9.txt"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines[0].startswith("# map=9 26x26"), lines[0]
    assert len(lines) == 1 + 26, f"⚠ 行数が {len(lines)}"
    for row in lines[1:]:
        cells = row.split()
        assert len(cells) == 26, row
        assert all(re.match(r"^[0-9A-F]{2}$", c) for c in cells), row


def test_collision表も書かれている(result):
    text = (SANDBOX / "dq3-probe" / "collision_seen.txt").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines, "⚠ 1 行も書かれていない"
    for line in lines:
        head, _, table = line.partition(",")
        assert head.isdigit(), line
        assert len(table.rsplit(",", 1)[-1].split()) == 32, line
