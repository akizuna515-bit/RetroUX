"""RX3-0226 戦闘の見込み: 守備を上げる敵（じごくのハサミ）とマヌーサ（2026-09-13）。

依頼者: 「地獄のハサミなど、守備力をめちゃ上げる敵にになってダメージが通らないが、
オート戦闘が消化戦になって負ける。戦闘期待値の計算変更が必要。あとはマヌーサ食ったときも気になる」

```text
いまの守備力  RAM $0520（WORD×8 / profile battle_enemies.defense）→ auto_v0 read_enemies の g.def
              ★ROM: bank 9 $88EE が上げ下げを書き、$9820 が たたかう のダメージ計算で読む（999 で頭打ち）
マヌーサ      $073C+2i の下位バイト bit4（profile status_flags.illusion）→ 物理 × 0.375
              ★ROM: bank 8 $96EC で 乱数 < $A0 なら空振り / $9EC2 で敵が立てる / $8276 で戦闘の頭に消す
```

⚠ 判断（Lua）は `research/probes/active/dq3_ai_test.lua` の M1〜M4 が見る（★ここで走らせる）。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"
RUNNER = ROOT / "research" / "probes" / "reusable" / "lua_run.py"
JUDGE = ROOT / "research" / "probes" / "active" / "dq3_ai_test.lua"
DLL = ROOT / "tools" / "fceux" / "lua5.1.dll"


def _profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def _prg() -> bytes:
    if not ROM.exists():
        pytest.skip("ROM が無い")
    rom = ROM.read_bytes()
    return rom[16:16 + rom[4] * 16384]


def _le(addr: int) -> bytes:
    return bytes([addr & 0xFF, addr >> 8])


# --- ★マヌーサ -----------------------------------------------------------

def test_マヌーサの旗を確かめた旗としてLuaへ渡す():
    row = _profile()["runtime"]["party"]["status_flags"]["illusion"]
    assert (row["byte"], row["bit"], row["confidence"]) == (0, 4, "confirmed"), row
    from dq3.phase0 import generate_lua as GL

    assert GL._party(_profile())["status_flags"]["illusion"] == {"byte": 0, "bit": 4}


def test_マヌーサの当たる率はROMの乱数の比較から():
    """★たたかう: `LDA status,X / AND #mask / BEQ / JSR 乱数 / CMP #n / BCS` → 乱数 < n で空振り。"""
    from dq3.battle_ai import generate as G

    prg = _prg()
    party = _profile()["runtime"]["party"]
    row = party["status_flags"]["illusion"]
    addr = int(party["status"], 16) + int(row["byte"])
    mask = 1 << int(row["bit"])
    miss = re.compile(rb"\xBD" + re.escape(_le(addr)) + rb"\x29" + re.escape(bytes([mask]))
                      + rb"\xF0.\x20..\xC9(.)\xB0", re.S)
    hits = list(miss.finditer(prg))
    assert len(hits) == 1, "⚠ 空振りの判定が 1 か所に決まらない: %d" % len(hits)
    rate = (256 - hits[0].group(1)[0]) / 256
    assert G.TUNING["illusion_hit_rate"] == rate == 0.375
    lua = (ROOT / "dq3" / "phase0" / "ai" / "situation.lua").read_text(encoding="utf-8")
    assert "Situation.ILLUSION_HIT = %s" % rate in lua, "⚠ Lua の既定が ROM の値と違う"
    # ★敵の マヌーサ が同じ bit を立て、戦闘の頭に下位バイトを bit7 以外消す（= 1 戦闘だけ）
    assert b"\x09" + bytes([mask]) + b"\x9D" + _le(addr) in prg, "⚠ 立てる所が無い"
    assert b"\xBD" + _le(addr) + b"\x29\x80\x9D" + _le(addr) in prg, "⚠ 戦闘の頭に消す所が無い"


def test_実測の比の目安がある():
    from dq3.battle_ai import generate as G

    assert 0 < G.TUNING["observed_ratio"] < 1
    assert G.TUNING["observed_min_expect"] > 0


# --- ★敵のいまの守備力 ----------------------------------------------------

def test_敵のいまの守備力はROMが書き換えて読む番地():
    from dq3.phase0 import generate_lua as GL

    prg = _prg()
    ene = GL._battle_enemies(_profile())
    lo, hi = ene["defense"], ene["defense"] + 1
    assert ene.get("defense_size") == 2
    # ★上げ下げ（スクルト / ルカニ）の書き込み: LDA $08 / STA lo,X / LDA $09 / STA hi,X / RTS
    assert b"\xA5\x08\x9D" + _le(lo) + b"\xA5\x09\x9D" + _le(hi) + b"\x60" in prg
    # ★たたかう のダメージ計算の読み出し: ASL / TAX / LDA lo,X / STA $59 / LDA hi,X / STA $5A / RTS
    assert b"\x0A\xAA\xBD" + _le(lo) + b"\x85\x59\xBD" + _le(hi) + b"\x85\x5A\x60" in prg
    # ★999（$03E7）で頭打ち
    assert re.search(rb"\xC9\x03\x90.\xD0.\xA5\x08\xC9\xE7", prg, re.S)
    lua = (ROOT / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    assert "ENE.defense" in lua and "g.def[k + 1]" in lua, "⚠ auto_v0 が守備力を読んでいない"
    sit = (ROOT / "dq3" / "phase0" / "ai" / "situation.lua").read_text(encoding="utf-8")
    assert "Situation.DEF_CAP = 999" in sit


#: ⚠ 守備力が**もう動かされている**セーブ（★除くなら、必ず理由を実測で書く）
#:
#: ```text
#: battle_baramos  バラモス戦の最中（RX3-0301 / 2026-09-20）
#:   ★ROM の表 100 に対し RAM は **0**
#:   ⚠ 「読めていない」ではない: ★すばやさは $0518 = 0x55 = 85 で ROM とぴたり一致
#:   → ★戦闘中に下げられた値（ルカニ / ルカナン）。⚠ この検査の前提「まだ動かされていない」を満たさない
#: ```
DEFENSE_ALREADY_CHANGED = {"battle_baramos.fcs"}


def test_敵のいまの守備力はスクルト前のセーブで表の値():
    """★戦闘に入った敵の守備力は ROM の表の値から始まる（⚠ 1 本では決めない / 生きている枠をすべて）。"""
    from dq3rom import enemies as EN
    from dq3rom import profile as P
    from retroux.core.bgmap import savestate as ss

    if not ROM.exists():
        pytest.skip("ROM が無い")
    base = {e.enemy_id: e.defense for e in EN.read_all(P.load_and_identify(ROM))}
    ene = _profile()["runtime"]["battle_enemies"]
    ids, counts = int(ene["ids"], 16), int(ene["counts"], 16)
    status, dfn = int(ene["status"], 16), int(ene["defense"], 16)
    paths = sorted((ROOT / "work" / "tests" / "fixtures" / "dq3").rglob("*.fcs"))
    paths += sorted((ROOT / "work" / "tests" / "savestates").glob("DQ3_J*"))
    seen = 0
    for path in paths:
        try:
            ram = ss.load(path).chunks["RAM"]
        except Exception:                                  # noqa: BLE001
            continue
        slot = 0
        for g in range(4):
            eid, n = ram[ids + g], ram[counts + g]
            if eid == 0xFF:
                continue
            for _ in range(n):
                if slot < 8 and ram[status + slot * 2 + 1] & 0x80 and eid in base:
                    got = ram[dfn + slot * 2] + ram[dfn + slot * 2 + 1] * 256
                    if path.name in DEFENSE_ALREADY_CHANGED:
                        # ⚠ 黙って飛ばさない。★下げられた後でも「読めている」ことは見る
                        assert 0 <= got <= base[eid], (
                            "⚠⚠ %s 枠 %d: 守備力 %d（★表 %d を超えた = 読み方が違う）"
                            % (path.name, slot, got, base[eid]))
                    else:
                        assert got == base[eid], "⚠ %s 枠 %d: 守備力 %d / 表 %d" % (
                            path.name, slot, got, base[eid])
                        seen += 1
                slot += 1
    if seen < 10:
        pytest.skip("生きている敵の枠が足りない（%d）" % seen)


# --- ★判断（Lua）---------------------------------------------------------

@pytest.fixture(scope="module")
def judge(tmp_path_factory) -> str:
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S

    if not (DLL.exists() and RUNNER.exists() and ROM.exists()):
        pytest.skip("Lua か ROM が無い")
    out = tmp_path_factory.mktemp("dq3-ai-estimate")
    data = G.regenerate(S.BattleAiSettings(), [], out_dir=out)
    assert data.get("ok"), data.get("error")
    env = dict(os.environ)
    env["DQ3_AI_GENERATED"] = str(out / ("%s.lua" % G.MODULE)).replace(chr(92), "/")
    done = subprocess.run([sys.executable, str(RUNNER), str(JUDGE)], cwd=str(ROOT), capture_output=True,
                          timeout=300, text=True, env=env, encoding="utf-8", errors="replace")
    both = (done.stdout or "") + (done.stderr or "")
    assert done.returncode == 0, "⚠⚠ 落ちました" + chr(10) + both
    return both


def test_守備を上げた敵とマヌーサで消化戦と見誤らない(judge):
    assert "すべて合格" in judge, judge
    for line in ("OK M1 守備を上げた敵", "OK M2 物理で片づかない", "OK M3 マヌーサ", "OK M4 実測"):
        assert any(ln.startswith(line) for ln in judge.splitlines()), (
            "⚠ " + line + " が出ていません" + chr(10) + judge)
    n = sum(1 for ln in judge.splitlines() if re.match(r"^OK\b", ln))
    assert n >= 38, judge                                   # ★RX3-0226 で 34 → 38
