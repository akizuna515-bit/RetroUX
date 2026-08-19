"""`decision_id` がセッションをまたいでも一意であること（§7・§27）。

## ⚠⚠ 何が壊れていたか（実測 / 2026-08-13）

    battle_decision_snapshot イベント数 : 3,497
      ユニークな decision_id            :   833     ⚠ 1 ID あたり 4.2 回

ID は `b{battle_seq}_t{turn}_{name}` で、`battle_seq` は
**セッションごとに 1 から振り直される**。★別セッションの別の判断が同じ ID になる。

さらに `bnil_t1_samaltria` が **201 件**（`battle_seq` が nil のまま
「nil という名前の戦闘」が作られていた）。

## ⚠⚠ 「対になる」検査では見つからない

    battle_action 3,296 件すべてに対の snapshot があった（100%）

★これは **衝突した相手と結ばれても成立する**。
⚠ 対応の検査だけを見ていると、この壊れ方を**そのまま通す**。

→ ★だから「一意であること」を**別に**見る。
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"


def _run_lua(body: str) -> str:
    if not RUNNER.exists():
        pytest.skip("Lua のハーネスが無い")
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(body)
        path = fh.name
    done = subprocess.run([sys.executable, str(RUNNER), path],
                          cwd=str(PROJECT_ROOT), capture_output=True,
                          timeout=120,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, out + err
    return out


#: ★2つの Bridge を作り、**同じ戦闘・同じターン・同じ人**の ID を比べる。
#:   ⚠ 以前はこれが同じ文字列になっていた。
SCRIPT = """
local root = os.getenv("RETROUX_ROOT")
root = (root or "."):gsub("\\\\", "/"):gsub("/$", "")

-- ★FCEUX の API を最小限だけ用意する（probe と同じ形）
local ram
memory = { readbyte = function(a) return ram:byte(a + 1) or 0 end,
           writebyte = function() end }
emu = { speedmode = function() end, frameadvance = function() end,
        framecount = function() return 0 end, message = function() end,
        registerbefore = function() end, registerafter = function() end,
        registerexit = function() end, pause = function() end,
        emulating = function() return true end }
joypad = { set = function() end, get = function() return {} end,
           getdown = function() return {} end }
gui = { text = function() end, register = function() end }
savestate = { object = function() return {} end, save = function() end,
              load = function() end, create = function() return {} end }
rom = { readbyte = function() return 0 end }

local FakeRam = assert(loadfile(
  root .. "/research/probes/reusable/fake_ram.lua"))()
local mm = assert(loadfile(root .. "/work/generated/memory_map.lua"))()
ram = FakeRam.build(mm, { party = {
  { hp = 100, max_hp = 173, mp = 0,  max_mp = 0,   status = 0x84 },
} })

local Bridge = assert(loadfile(root .. "/retroux/emulator/fceux/bridge.lua"))()

-- ★セッション識別子そのものが起動ごとに変わること
local a = Bridge.new({ root = root })
local b = Bridge.new({ root = root })
print("SESSION_A=" .. tostring(a.session_id))
print("SESSION_B=" .. tostring(b.session_id))

-- ★同じ戦闘・同じターン・同じ人でも、セッションが違えば ID が違うこと
a.state.battle_seq = 1; a.turn_no = 1; a.snapshot_done = {}
b.state.battle_seq = 1; b.turn_no = 1; b.snapshot_done = {}
local member = { index = 0, name = "lorasia" }
-- ⚠ emit と game の中身は要らない。★ID の組み立てだけを見る
local function id_of(br)
  br.emit = function() end
  local ok, got = pcall(function() return br:_emit_decision_snapshot(member) end)
  return ok and tostring(got) or ("ERR:" .. tostring(got))
end
print("ID_A=" .. id_of(a))
print("ID_B=" .. id_of(b))
"""


@pytest.fixture(scope="module")
def lua_out():
    return _run_lua(SCRIPT)


def _values(out: str) -> dict:
    got = {}
    for line in out.splitlines():
        if "=" in line and line.split("=", 1)[0] in ("SESSION_A", "SESSION_B",
                                                     "ID_A", "ID_B"):
            key, _, value = line.partition("=")
            got[key] = value
    return got


def test_セッション識別子が起動ごとに変わる(lua_out):
    ids = _values(lua_out)
    assert ids.get("SESSION_A") and ids["SESSION_A"] != "nil", lua_out
    assert ids["SESSION_A"] != ids["SESSION_B"], (
        f"同じプロセスで作った2つが同じ識別子になっている: {ids}")


def test_同じ戦闘ターン人でもセッションが違えばIDが違う(lua_out):
    """★★ **これが本体**（⚠ 実測で 3,497 件が 833 個に潰れていた）。"""
    ids = _values(lua_out)
    a, b = ids.get("ID_A", ""), ids.get("ID_B", "")
    assert a and not a.startswith("ERR:"), lua_out
    assert b and not b.startswith("ERR:"), lua_out
    assert a != b, (
        f"別セッションの同じ戦闘・ターン・人で ID が同じ: {a}\n{lua_out}")
    # ★形も見る（⚠ たまたま違うだけ、を避ける）
    assert a.endswith("_b1_t1_lorasia"), a
    assert b.endswith("_b1_t1_lorasia"), b


def test_IDにセッション識別子が入っている():
    """★これが無いとセッションをまたいで衝突する。"""
    src = BRIDGE.read_text(encoding="utf-8")
    block = src.split("function Bridge:_emit_decision_snapshot")[1][:3000]
    assert "self.session_id" in block, (
        "decision_id にセッション識別子が入っていない")
    assert 'string.format("%s_b%s_t%s_%s"' in block, block[:600]


def test_通し番号が無いときはIDを作らない():
    """⚠ 以前は `bnil_...` という**偽の ID**を作っていた（実測 201 件）。

    ★「nil という名前の戦闘」を作ると、そこへ全部が集まる。
    """
    src = BRIDGE.read_text(encoding="utf-8")
    block = src.split("function Bridge:_emit_decision_snapshot")[1][:3000]
    assert "if battle_seq == nil then" in block, block[:800]
    assert "return nil" in block


def test_通し番号が無いことを黙って捨てない():
    """⚠ 記録しないなら、**記録しなかったこと**を知らせる。"""
    src = BRIDGE.read_text(encoding="utf-8")
    block = src.split("function Bridge:_emit_decision_snapshot")[1][:3000]
    assert "seq_missing_told" in block, "1回だけ知らせる仕掛けが無い"
    assert '"WARNING"' in block, "段階が WARNING になっていない"


def test_session_startに識別子が入っている():
    """★後から「どのセッションの判断か」を辿れるように。"""
    src = BRIDGE.read_text(encoding="utf-8")
    block = src.split('self:emit("session_start"')[1][:400]
    assert "session_id = self.session_id" in block, block


# --- ★ 溜まったイベントに対する検査（実データがあれば）--------------------

def test_溜まったeventsのIDが一意である():
    """⚠ **古いデータには古い形の ID が混ざる**（★2026-08-13 より前）。

    ★ここでは「新しい形（セッション識別子つき）の ID だけ」を見る。
      ⚠ 古い形まで一意を求めると、**直したのに永久に赤い**検査になる。
    """
    import collections
    import json

    events = PROJECT_ROOT / "work" / "events.jsonl"
    if not events.exists():
        pytest.skip("実測データが無い")
    ids = collections.Counter()
    for line in events.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or "battle_decision_snapshot" not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        got = e.get("decision_id")
        # ★新しい形は `{session}_b{n}_t{n}_{name}`（⚠ 古い形は `b` で始まる）
        if isinstance(got, str) and not got.startswith("b"):
            ids[got] += 1
    if not ids:
        pytest.skip("新しい形の decision_id がまだ無い（★実機で貯め直すと入る）")
    dup = {k: v for k, v in ids.items() if v > 1}
    assert not dup, f"同じ ID が複数回出ている: {list(dup.items())[:5]}"
