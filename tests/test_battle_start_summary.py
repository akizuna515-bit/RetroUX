"""戦闘開始を1行にまとめたこと（RX-0040 / 指示書 §18C・§24）。

## ⚠⚠ なぜ要るか

実機（2026-08-14 / 16分・4戦闘）で、戦闘のたびに **INFO が3行**出ていた:

    [INFO] lua [敵] しびれくらげ×2
    [INFO] lua [戦術] 省資源（適合度 4.5 / 次点との差 0.5）★この戦術で判断します
    [INFO] lua [役割] lorasia:attack(2.0) / samaltria:attack(1.1) / moonbrooke:item(1.3)

★1戦闘3行 × 4戦闘 = **12行**（その日の INFO 39 行の 31%）。

判定は3件とも **MERGE** だったが、⚠ **実装していなかった**
（`apply_lua_log_levels.py` の対応表に MERGE が無かった）。
⚠⚠ さらに `test_log_verdicts_applied.py` の `WANT` にも無く、
★**歯止めがこの漏れを検出できていなかった**。

## ★ ここで見ること

  1. まとめた1行が出る（★INFO）
  2. 元の3行は DEBUG（⚠ normal では出ない）
  3. ⚠ **1戦闘に1回だけ**（★見立ては毎ポーリング走る）
  4. ⚠ 材料が欠けても落ちない
"""

from __future__ import annotations

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"


@pytest.fixture(scope="module")
def src():
    return BRIDGE.read_text(encoding="utf-8")


# --- 1. まとめた行がある ---------------------------------------------------

def test_まとめた1行がある(src):
    assert "function Bridge:_log_battle_start_summary" in src
    block = src.split("function Bridge:_log_battle_start_summary")[1][:1200]
    assert '"戦闘開始: "' in block, block[:400]


def test_まとめた行はINFO(src):
    """★段階を渡していない＝既定の INFO。"""
    block = src.split("function Bridge:_log_battle_start_summary")[1][:1200]
    line = [l for l in block.splitlines() if 'self:log("戦闘開始: "' in l]
    assert line, block[:400]
    for bad in ('"DEBUG"', '"WARNING"', '"ERROR"'):
        assert bad not in line[0], f"まとめた行が {bad}: {line[0]}"


def test_材料がそろってから呼ぶ(src):
    """⚠ 役割は戦術の直後に決まる。★その後ろで呼ぶこと。"""
    call = src.index("self:_log_battle_start_summary()")
    roles = src.index("self:_log_contributions(a, choice.directive)")
    assert roles < call, "役割が決まる前にまとめている"


# --- 2. 元の3行は DEBUG ----------------------------------------------------

def test_元の3行はDEBUG(src):
    """⚠ normal では出ない。★調べたいときは diagnostic。"""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_log_inventory import build

    judged, _ = build()
    for mark in ("[敵]", "[戦術]", "[役割]"):
        rows = [r for r in judged
                if r["file"].endswith("bridge.lua") and r["kind"] == "lua-log"
                and mark in r["snippet"]]
        assert rows, f"{mark} が棚卸しに無い"
        for r in rows:
            assert r["level"] == "DEBUG", (
                f"{mark} が {r['level']} のまま: {r['file']}:{r['line']}")


# --- 3. ⚠⚠ 1戦闘に1回だけ（★ここが要）----------------------------------

def test_1戦闘に1回だけ(src):
    """⚠ 見立ては**毎ポーリング**走る。★印が無いと同じ行が並ぶ。"""
    block = src.split("function Bridge:_log_battle_start_summary")[1][:1200]
    assert "start_logged_seq" in block, block[:400]
    assert "battle_seq" in block, "戦闘の通し番号で区切っていない"


def test_実Luaで一度しか出ない():
    """★★ 字面ではなく**動かして**確かめる（V2）。"""
    import os
    import subprocess
    import tempfile

    runner = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
    if not runner.exists():
        pytest.skip("Lua のハーネスが無い")

    script = """
local root = os.getenv("RETROUX_ROOT")
root = (root or "."):gsub("\\\\", "/"):gsub("/$", "")
local Bridge = assert(loadfile(root .. "/retroux/emulator/fceux/bridge.lua"))()

-- ★`Bridge.new` を通さない（⚠ 実機の状態が要らない）
local said = {}
local fake = {
  start_view = { enemies = "しびれくらげ×2", plan = "省資源",
                 roles = "lorasia:attack(2.0) / samaltria:attack(1.1)" },
  state = { battle_seq = 1 },
  log = function(_self, msg) said[#said + 1] = msg end,
}
-- ★毎ポーリングを模す
for _ = 1, 5 do Bridge._log_battle_start_summary(fake) end
print("COUNT1=" .. #said)
print("LINE=" .. tostring(said[1]))

-- ★次の戦闘では、また出る
fake.state.battle_seq = 2
for _ = 1, 5 do Bridge._log_battle_start_summary(fake) end
print("COUNT2=" .. #said)
"""
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    done = subprocess.run([sys.executable, str(runner), path],
                          cwd=str(PROJECT_ROOT), capture_output=True,
                          timeout=60,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, out + err

    got = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    assert got.get("COUNT1") == "1", f"5回呼んで {got.get('COUNT1')} 行出た\n{out}"
    assert got.get("COUNT2") == "2", f"次の戦闘で出ていない\n{out}"
    line = got.get("LINE", "")
    assert line.startswith("戦闘開始: "), line
    assert "しびれくらげ×2" in line, line
    assert "戦術=省資源" in line, line
    # ★役割は点数を落として短くする
    assert "役割=" in line, line
    assert "(2.0)" not in line, f"点数が残っている（★詳細は DEBUG 側）: {line}"


# --- 4. ⚠ 材料が欠けても落ちない ------------------------------------------

def test_材料が欠けても落ちない():
    import os
    import subprocess
    import tempfile

    runner = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
    if not runner.exists():
        pytest.skip("Lua のハーネスが無い")

    script = """
local root = os.getenv("RETROUX_ROOT")
root = (root or "."):gsub("\\\\", "/"):gsub("/$", "")
local Bridge = assert(loadfile(root .. "/retroux/emulator/fceux/bridge.lua"))()

local said = {}
local function run(view, seq)
  local fake = { start_view = view, state = { battle_seq = seq },
                 log = function(_s, m) said[#said + 1] = m end }
  local ok, err = pcall(function()
    Bridge._log_battle_start_summary(fake)
  end)
  return ok, err
end

-- ★材料がまったく無い
print("NIL_OK=" .. tostring((run(nil, 1))))
-- ★敵だけ読めていない
local ok = run({ plan = "省資源" }, 2)
print("PARTIAL_OK=" .. tostring(ok))
print("PARTIAL_LINE=" .. tostring(said[#said]))
"""
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    done = subprocess.run([sys.executable, str(runner), path],
                          cwd=str(PROJECT_ROOT), capture_output=True,
                          timeout=60,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, out + err
    got = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    assert got.get("NIL_OK") == "true", out
    assert got.get("PARTIAL_OK") == "true", out
    # ⚠ 読めていないことを**隠さない**
    assert "読めていません" in got.get("PARTIAL_LINE", ""), got.get("PARTIAL_LINE")
