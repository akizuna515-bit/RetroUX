"""前後差分の共通基盤（RX3-0048 A-5）。

⚠ 入力は製品（dev.lua）が書く `work/state.json` の形（★2026-09-02 の実物を縮めたもの）。
"""

from __future__ import annotations

import copy
import json

from dq3.testing import state_diff as sd

STATE = {
    "frame": 735249, "game": "dq3", "gold": 306, "in_battle": False,
    "loc_kind": 1, "map_id": 9, "map_x": 8, "map_y": 18, "turbo_enabled": False,
    "party": [
        {"index": 0, "level": 5, "hp": 34, "max_hp": 34, "mp": 9, "max_mp": 9,
         "exp": 399, "to_next": 100, "strength": 18, "agility": 12, "stamina": 15,
         "wisdom": 10, "luck": 6, "attack": 30, "defence": 14, "name": "p1"},
        {"index": 1, "level": 6, "hp": 40, "max_hp": 40, "mp": 0, "max_mp": 0,
         "exp": 399, "to_next": 27, "strength": 21, "agility": 6, "stamina": 19,
         "wisdom": 5, "luck": 8, "attack": 28, "defence": 17, "name": "p2"},
    ],
}


def _write(tmp_path, body, name="state.json"):
    p = tmp_path / name
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_平らにする():
    got = sd.flatten(STATE)
    assert got["gold"] == 306 and got["map_id"] == 9
    assert got["party.0.hp"] == 34 and got["party.1.level"] == 6
    assert "party.0.name" not in got, "⚠ 決めた項目以外を入れている"
    assert "turbo_enabled" not in got


def test_写す(tmp_path):
    got = sd.capture_state(_write(tmp_path, STATE), label="before")
    assert got["available"] is True and got["label"] == "before"
    assert got["gold"] == 306 and "captured_at" in got


def test_読めなければそう言う(tmp_path):
    got = sd.capture_state(tmp_path / "無い.json")
    assert got["available"] is False and "why" in got
    (tmp_path / "壊れ.json").write_text("{", encoding="utf-8")
    assert sd.capture_state(tmp_path / "壊れ.json")["available"] is False


def test_戦闘の前後の差分(tmp_path):
    """★指示書 §14 の例: EXP +96 / Gold +72。"""
    before = sd.capture_state(_write(tmp_path, STATE, "b.json"))
    after_body = copy.deepcopy(STATE)
    after_body["gold"] += 72
    for m in after_body["party"]:
        m["exp"] += 96
    after_body["party"][0]["hp"] = 20
    after = sd.capture_state(_write(tmp_path, after_body, "a.json"))
    diff = sd.compare_state(before, after)
    assert diff["changed"]["gold"] == {"before": 306, "after": 378, "delta": 72}
    assert diff["changed"]["party.0.exp"]["delta"] == 96
    assert diff["changed"]["party.0.hp"]["delta"] == -14
    assert "party.1.hp" not in diff["changed"]
    assert diff["same"] > 20


def test_frameは差分に数えない(tmp_path):
    """⚠ 毎回変わるものを差分に出すと、★本当の変化が埋もれる。"""
    before = sd.capture_state(_write(tmp_path, STATE, "b.json"))
    after_body = copy.deepcopy(STATE)
    after_body["frame"] += 1000
    after = sd.capture_state(_write(tmp_path, after_body, "a.json"))
    diff = sd.compare_state(before, after)
    assert diff["changed"] == {} and diff["added"] == {} and diff["removed"] == {}


def test_レベルアップは値の変化として出る(tmp_path):
    before = sd.capture_state(_write(tmp_path, STATE, "b.json"))
    after_body = copy.deepcopy(STATE)
    after_body["party"][0]["level"] = 6
    after_body["party"][0]["max_hp"] = 40
    after = sd.capture_state(_write(tmp_path, after_body, "a.json"))
    lines = sd.summarize(sd.compare_state(before, after))
    assert "party.0.level +1" in lines and "party.0.max_hp +6" in lines


def test_片方が読めなければ差分を作らない(tmp_path):
    before = sd.capture_state(_write(tmp_path, STATE, "b.json"))
    after = sd.capture_state(tmp_path / "無い.json")
    diff = sd.compare_state(before, after)
    assert "why" in diff and diff["changed"] == {}


def test_地図が変われば出る(tmp_path):
    before = sd.capture_state(_write(tmp_path, STATE, "b.json"))
    after_body = copy.deepcopy(STATE)
    after_body.update({"loc_kind": 0, "map_id": None, "map_x": 172, "map_y": 219})
    after = sd.capture_state(_write(tmp_path, after_body, "a.json"))
    diff = sd.compare_state(before, after)
    assert diff["changed"]["loc_kind"]["delta"] == -1
    assert diff["changed"]["map_id"] == {"before": 9, "after": None}, (
        "⚠ 数でない変化に delta を付けている")


def test_3つのファイルを書く(tmp_path):
    before = sd.capture_state(_write(tmp_path, STATE, "b.json"))
    after = sd.capture_state(_write(tmp_path, STATE, "a.json"))
    sd.write_all(tmp_path, before, after)
    for name in ("state_before.json", "state_after.json", "state_diff.json"):
        assert (tmp_path / name).exists(), "⚠ %s が無い" % name
    diff = json.loads((tmp_path / "state_diff.json").read_text(encoding="utf-8"))
    assert diff["changed"] == {}
