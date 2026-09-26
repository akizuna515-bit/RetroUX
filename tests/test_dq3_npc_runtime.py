"""実機で写した NPC の表 × OAM の解析（RX3-0053）。★ROM なしで、作った sample で検査する。"""
from __future__ import annotations

import json

from dq3.testing import npc_runtime as NR


def _tbl(npcs):
    """★仲間 4 slot + NPC + 終端 の hex。"""
    b = bytearray([8, 18, 0, 0x82] * 4)
    for x, y, app, st in npcs:
        b += bytes([x, y, app, st])
    b += bytes([0xFF] * 4)
    b += bytes([0xFF] * (0x78 - len(b)))
    return b.hex()


def _char(x, y):
    """★16x16 の人物（4 枚）。"""
    return [[y, 1, 0, x], [y, 2, 0, x + 8], [y + 8, 3, 0, x], [y + 8, 4, 0, x + 8]]


def test_表はslot4からで終端で止まる():
    got = NR.slots_of({"tbl": _tbl([(8, 16, 5, 0x92)])})
    assert [s["slot"] for s in got] == [0, 1, 2, 3, 4]
    assert got[4] == {"slot": 4, "x": 8, "y": 16, "appearance_slot": 5, "state": 0x92, "party": False}


def test_画面内のNPCはOAMに居る():
    rows = [{"frame": 1, "px": 8, "py": 18, "phase": "walk", "tbl": _tbl([(8, 16, 5, 0x92)]),
             "s": _char(128, 107) + _char(128, 107 - 32)}]
    tr = NR.track(rows)
    assert tr[0]["expected_visible"] and tr[0]["oam_present"]


def test_画面外のNPCは表に残りOAMには居ない():
    rows = [{"frame": 1, "px": 8, "py": 18, "phase": "walk", "tbl": _tbl([(8, 16, 5, 0x92)]),
             "s": _char(128, 107) + _char(128, 107 - 32)},
            {"frame": 2, "px": 21, "py": 14, "phase": "walk", "tbl": _tbl([(8, 16, 5, 0x92)]),
             "s": _char(128, 107)}]
    tr = NR.track(rows)
    assert tr[1]["expected_visible"] is False and tr[1]["oam_present"] is False
    c = NR.correlation(tr, [{"fixed": True}])
    s = c["slots"][0]
    assert s["samples"] == 2 and s["samples_offscreen"] == 1 and s["moved"] is False
    assert c["H4_fixed_never_moved"] == 1 and c["H5_drawn_when_visible"] == 1
    assert c["rom_vs_state_bit7_agree"] == 1


def test_動くNPCは座標が変わる():
    rows = [{"frame": f, "px": 8, "py": 18, "phase": "walk", "tbl": _tbl([(3 + f, 10, 9, 0x03)]), "s": []}
            for f in range(3)]
    c = NR.correlation(NR.track(rows), [{"fixed": False}])
    assert c["H3_moving_changed_position"] == 1 and c["H4_fixed_total"] == 0


def test_書き込みPCを読み込み時とゲームループに分ける():
    pcs = NR.classify_pcs({"write_hook": True, "read_hook": False, "n_writes": 30,
                           "writes": {"F3F8": {"n": 11, "first": 1, "last": 2, "offs": {"0": 11},
                                               "phases": {"load": 11}},
                                      "ADDC": {"n": 19, "first": 100, "last": 900, "offs": {"0": 10, "1": 9},
                                               "phases": {"walk": 19}}}})
    kinds = {w["pc"]: (w["kind"], w["bytes"]) for w in pcs["writes"]}
    assert kinds == {"$F3F8": ("load", "x"), "$ADDC": ("play", "x+y")}


def test_analyzeは4つの成果物を書く(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    rows = [{"frame": 1, "kind": 1, "map_id": 9, "px": 8, "py": 18, "phase": "load", "time": 0,
             "tbl": _tbl([(8, 16, 5, 0x92)]), "s": _char(128, 107 - 32)}]
    (run / "npc_track.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (run / "npc_pc.json").write_text(json.dumps({"write_hook": True, "writes": {}, "reads": {}}), encoding="utf-8")
    monkeypatch.setattr(NR.R, "npcs_for_map", lambda map_id, night, rom=None: [
        {"x": 8, "y": 16, "appearance_id": 0x1C, "facing": "down", "fixed": True}])
    out = tmp_path / "out"
    got = NR.analyze(run, 9, out)
    assert got["compare"]["ok"] == 1
    assert {p.name for p in out.iterdir()} == {"map_009_initial.json", "map_009_tracking.jsonl",
                                               "ram_oam_correlation.json", "npc_write_pc.json"}
    assert "H5" in NR.summarize(got)
