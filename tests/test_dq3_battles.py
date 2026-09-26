"""戦闘ごとの記録と回帰の指標（RX3-0050 §13 / §14 / §18）。"""

from __future__ import annotations

import json

from dq3.testing import battles

AUTO = """=== AUTO_V0 start 2026-09-01 ===
AUTO_V0_DONE 前の遊び turns=9
=== AUTO_V0 start 2026-09-02 10:00:00 ===
AUTO_V0 ON + turbo
AUTO_V0 turn=1 slot=p1 action=attack
AUTO_V0 turn=2 slot=p2 action=attack
AUTO_V0_DONE 戦闘が終わった（地形 960 マス / $62=2） turns=2
AUTO_V0 ON + turbo
AUTO_V0_STOP reason=見知らぬ画面
"""


def _state(gold, exp, hp, level=5):
    return {"available": True, "captured_at": "x", "gold": gold,
            "party.0.exp": exp, "party.0.hp": hp, "party.0.level": level}


def test_この_runの結末だけを読む():
    got = battles.auto_outcomes(AUTO)
    assert [o["turns"] for o in got] == [2, None], "⚠ 前の遊びの分を混ぜている"
    assert got[1]["stopped"] == "見知らぬ画面"


def test_turnsは累積なので差にする():
    """⚠⚠ 製品の `turns=` は戦闘をまたいで増え続ける（★実機: 14 / 28 / 42 / 49 / 63）。"""
    text = chr(10).join(["=== AUTO_V0 start", "AUTO_V0_DONE a turns=14",
                          "AUTO_V0_DONE b turns=28", "AUTO_V0_DONE c turns=42", ""])
    got = battles.auto_outcomes(text)
    assert [o["turns"] for o in got] == [14, 14, 14]
    assert [o["turns_total"] for o in got] == [14, 28, 42]


def test_startとendを組にする():
    ev = [{"event": "battle_start", "battle_id": 1, "frame": 100, "x": 5, "y": 6, "hp": [34, 40]},
          {"event": "battle_end", "battle_id": 1, "frame": 700, "frames": 600,
           "result": "won", "hp": [30, 40]},
          {"event": "battle_start", "battle_id": 2, "frame": 900, "x": 5, "y": 7, "hp": [30, 40]}]
    got = battles.pair_events(ev)
    assert len(got) == 2
    assert got[0]["result"] == "won" and got[0]["frames"] == 600
    assert "result" not in got[1], "⚠ 終わっていない戦闘に結果を作った"


def test_前後の差分がつく():
    ev = [{"event": "battle_start", "battle_id": 1, "frame": 1},
          {"event": "battle_end", "battle_id": 1, "frame": 2, "result": "won"}]
    snaps = [{"battle_id": 1, "before": _state(306, 399, 34), "after": _state(378, 495, 20)}]
    got = battles.merge(ev, snaps, AUTO)
    assert got[0]["diff"]["gold"]["delta"] == 72
    assert got[0]["diff"]["party.0.exp"]["delta"] == 96
    assert "gold +72" in got[0]["diff_lines"]
    assert got[0]["turns"] == 2


def test_指標():
    ev = []
    snaps = []
    for i in range(1, 4):
        ev += [{"event": "battle_start", "battle_id": i, "frame": i * 10},
               {"event": "battle_end", "battle_id": i, "frame": i * 10 + 5,
                "result": "won" if i < 3 else "lost"}]
        snaps.append({"battle_id": i, "before": _state(100, 10, 30),
                      "after": _state(110, 20, 25, level=6 if i == 2 else 5)})
    rows = battles.merge(ev, snaps, "=== AUTO_V0 start\nAUTO_V0_DONE a turns=4\n"
                                    "AUTO_V0_DONE b turns=8\nAUTO_V0_DONE c turns=6\n")
    s = battles.summarize(rows, stop_reason="player_death")
    assert (s["battles"], s["wins"], s["losses"], s["deaths"]) == (3, 2, 1, 1)
    assert s["average_turns"] == round((4 + 4 + 6) / 3, 1) and s["max_turns"] == 6
    assert s["gold_gained"] == 30 and s["exp_gained"] == 30
    assert s["level_ups"] == [{"battle_id": 2, "member": 0, "from": 5, "to": 6}]
    assert s["items_observed"] is None, "⚠⚠ 番地が確定していないものを数えている"
    assert s["hangs"] == 0 and s["unexpected_stops"] == 0


def test_hangは指標に出る():
    s = battles.summarize([], stop_reason="hang_suspected")
    assert s["hangs"] == 1 and s["battles"] == 0 and s["average_turns"] is None


def test_folderから作る(tmp_path):
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"event": "battle_start", "battle_id": 1, "frame": 1}) + "\n"
        + json.dumps({"event": "battle_end", "battle_id": 1, "frame": 9, "result": "won"}) + "\n",
        encoding="utf-8")
    (tmp_path / "battles.jsonl").write_text(
        json.dumps({"battle_id": 1, "before": _state(1, 1, 1), "after": _state(2, 2, 2)}) + "\n",
        encoding="utf-8")
    log = tmp_path / "auto.log"
    log.write_text(AUTO, encoding="utf-8")
    got = battles.build(tmp_path, auto_log=log, stop_reason="max_battles")
    assert got["summary"]["battles"] == 1 and got["summary"]["gold_gained"] == 1
    assert (tmp_path / "battles.json").exists()


def test_無いものは空():
    assert battles.load_jsonl("無い.jsonl") == []
    assert battles.auto_outcomes("") == []
