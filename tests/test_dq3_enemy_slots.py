"""敵の群とスロットの対応・敵の状態（RX3-0268 / 2026-09-14）。

```text
群        状態の 1 バイト目（$0530+2i）の bit3-2・使用中は bit7   ← JP bank 4 $BB75（戦闘の初めに 1 体ずつ）
眠り      2 バイト目 bit5   ← $9DC3  ⎫
封じ      1 バイト目 bit5   ← $9E85  ⎬ ★RX3-0266 の実機（隔離した FCEUX）で予想と食い違い 0
幻        1 バイト目 bit4   ← $9F04  ⎭
混乱・マホカンタ              ⚠ コードだけ → 戦闘 AI へは渡さない
```

⚠ 以前の `read_enemies` は「群のスロットが先頭から数だけ並ぶ」とみなしていた（援軍の後にずれうる）。
★Lua の動きは `research/probes/active/dq3_auto_ai_test.lua` / `dq3_ai_test.lua`（RX3-0268 の場面）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"


def _profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def _prg() -> bytes:
    if not ROM.exists():
        pytest.skip("ROM が無い")
    from dq3.testing.npc_rom import _prg as prg

    return prg(None)


def test_群と状態の旗は生成物へ渡る_確かめた旗だけ():
    """★橋渡しで黙って落ちないこと（⚠ 両端が正しくても間で捨てられた前例がある）。"""
    from dq3.phase0 import generate_lua as GL

    ene = GL._battle_enemies(_profile())
    assert ene.get("used_bit") == 0x80 and ene.get("group_shift") == 2
    assert ene.get("status_flags") == {"asleep": {"byte": 1, "bit": 5},
                                       "sealed": {"byte": 0, "bit": 5},
                                       "illusion": {"byte": 0, "bit": 4}}, ene.get("status_flags")
    # ⚠ コードだけの旗は profile にはあるが渡さない
    raw = _profile()["runtime"]["battle_enemies"]["status_flags"]
    assert raw["confused"]["confidence"] != "confirmed" and raw["reflect"]["confidence"] != "confirmed"


def test_群と状態の旗はROMの命令で書かれている():
    """★名前ではなく ROM の命令で確かめる（⚠ profile の値だけを根拠にしない）。"""
    prg = _prg()
    # ★戦闘の初め: TXA / ASL / ASL / ORA #$80 / STA $0530,Y（= 群 × 4 | 使用中）
    assert bytes.fromhex("8A0A0A0980993005") in prg
    # ★ラリホー: LDA $0531,X / ORA #$20 / STA $0531,X（→ 眠りの勘定 $0530 |= 3）
    assert bytes.fromhex("BD31050920" + "9D3105" + "BD3005" + "0903" + "9D3005") in prg
    # ★マホトーン / マヌーサ: 文を出してから（JSR $A412）LDA $0530,X / ORA #$20 or #$10 / STA $0530,X / RTS
    assert bytes.fromhex("2012A4BD300509209D300560") in prg
    assert bytes.fromhex("2012A4BD300509109D300560") in prg


def test_群の旗はセーブの群ごとの一覧と合う():
    """★戦闘中の固定セーブで、群の bit から作った一覧が ROM 自身の一覧（$07C1 + 8×群）と同じ。"""
    from retroux.core.bgmap import savestate as ss

    ene = _profile()["runtime"]["battle_enemies"]
    ids, counts, status = int(ene["ids"], 16), int(ene["counts"], 16), int(ene["status"], 16)
    checked = 0
    for path in sorted((ROOT / "work" / "test-fixtures" / "dq3").rglob("*.fcs")):
        try:
            ram = ss.load(path).chunks["RAM"]
        except Exception:                                  # noqa: BLE001
            continue
        by_bits: dict[int, list[int]] = {}
        for slot in range(8):
            b0 = ram[status + 2 * slot]
            if b0 & 0x80:
                by_bits.setdefault((b0 >> 2) & 3, []).append(slot)
        if not by_bits:
            continue                                       # ★戦闘中でない
        for g in range(4):
            if ram[ids + g] == 0xFF or ram[counts + g] == 0:
                continue
            listed = [x & 7 for x in ram[0x07C1 + 8 * g:0x07C1 + 8 * g + 8] if x & 0x80 and x < 0x88]
            assert by_bits.get(g, []) == listed, "%s 群 %d: bit %s / 一覧 %s" % (path.name, g, by_bits.get(g), listed)
            checked += 1
    if checked == 0:
        pytest.skip("戦闘中の固定セーブが無い")


def test_製品が群の旗と状態を読む():
    lua = (ROOT / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    body = lua.split("local function read_enemies()")[1].split("\nlocal function ")[0]
    assert "AIX.enemy_slots()" in body and "AIX.enemy_status(slot)" in body
    sit = (ROOT / "dq3" / "phase0" / "ai" / "situation.lua").read_text(encoding="utf-8")
    assert "statuses = statuses" in sit
    act = (ROOT / "dq3" / "phase0" / "ai" / "actions.lua").read_text(encoding="utf-8")
    assert 'status = "asleep"' in act and 'status = "illusion"' in act
    assert "not all_affected(g, eff.status)" in act
