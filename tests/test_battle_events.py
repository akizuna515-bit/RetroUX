"""行動単位ログの取り込み（MVP2 Phase 3 / 指示書 7.4・7.5）。

★守りたい契約:
  1. 戦闘中に届いた出来事が、**その戦闘の battle_id** に結びつく
  2. 戦闘をまたいで**混ざらない**
  3. 戦闘が終わらなかったら書かれない（書く先が無いので当然）
  4. 「AIが決めたこと」と「HPがこう変わった」を区別できる
"""

from __future__ import annotations

import pytest

from retroux.core.db.database import Database
from retroux.core.recorder import Recorder

START = ('{"type":"battle_start","frame":1,"time":1784980800,'
         '"enemy_ids":[1],"enemy_count":1}')
END = ('{"type":"battle_end","frame":100,"time":1784980810,'
       '"duration_frames":99,"outcome":"win","duration_ms":1000}')
TURN = '{"type":"battle_turn","frame":10,"turn":1}'
ACTION = ('{"type":"battle_action","frame":12,"turn":1,"seq":1,'
          '"actor":"samaltria","action":"ホイミ","target":"lorasia",'
          '"selected_by":"ai","reason":"HPが半分未満"}')
OBS = ('{"type":"battle_observation","frame":20,"turn":1,"seq":2,'
       '"kind":"party_hp","index":0,"name":"lorasia",'
       '"before":30,"after":59,"delta":29}')


@pytest.fixture
def rec(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    yield recorder, events, db
    db.close()


def _write(events, lines):
    events.write_text("".join(x + "\n" for x in lines), encoding="utf-8")


def test_events_are_linked_to_the_battle(rec):
    recorder, events, db = rec
    _write(events, [START, TURN, ACTION, OBS, END])
    recorder.poll()

    battle = db.recent_battles("HASH", 1)[0]
    rows = db.battle_events(battle["id"])

    kinds = [r["kind"] for r in rows]
    assert kinds == ["turn", "action", "party_hp"]
    assert rows[1]["actor"] == "samaltria"
    assert rows[1]["action_name"] == "ホイミ"
    assert rows[1]["selected_by"] == "ai"
    assert rows[2]["delta"] == 29


def test_not_mixed_between_battles(rec):
    """★前の戦闘の残りを持ち越さない。"""
    recorder, events, db = rec
    _write(events, [START, ACTION, END, START, OBS, END])
    recorder.poll()

    battles = db.recent_battles("HASH", 2)
    newest, oldest = battles[0], battles[1]
    assert [r["kind"] for r in db.battle_events(oldest["id"])] == ["action"]
    assert [r["kind"] for r in db.battle_events(newest["id"])] == ["party_hp"]


def test_unfinished_battle_writes_nothing(rec):
    """戦闘が終わっていなければ書かれない（battle_id がまだ無い）。"""
    recorder, events, db = rec
    _write(events, [START, ACTION, OBS])
    recorder.poll()

    assert db.recent_battles("HASH", 5) == []
    # 溜まってはいる（次に終わったときに書かれる）
    assert len(recorder._pending_events) == 2


def test_ai_and_observation_are_distinguishable(rec):
    """「AIが決めたこと」と「HPがこう変わった」を混ぜない。"""
    recorder, events, db = rec
    _write(events, [START, ACTION, OBS, END])
    recorder.poll()

    rows = db.battle_events(db.recent_battles("HASH", 1)[0]["id"])
    by_kind = {r["kind"]: r for r in rows}
    assert by_kind["action"]["selected_by"] == "ai"
    # 観測には「誰が決めたか」が無い（分からないので入れない）
    assert by_kind["party_hp"]["selected_by"] is None
