"""heard の台帳（RX3-0056）。★ROM の Master と実際に話した事実を分ける。"""
from __future__ import annotations

import json

from dq3.knowledge import npc_heard as H

MASTER = {"map_id": 9, "npcs": [
    {"npc_id": 1, "talk_id": 0x00B, "initial_x": 8, "initial_y": 16, "appearance_id": 28, "movement": "fixed"},
    {"npc_id": 6, "talk_id": 0x247, "initial_x": 3, "initial_y": 10, "appearance_id": 44, "movement": "random"},
]}


def test_話した相手だけがUIへ返る(tmp_path):
    led = H.HeardLedger(tmp_path)
    assert led.get_heard_npcs(9, MASTER) == []
    # ★文の中身はこの検査で使いません（⚠ 役目は MASTER の talk_id から決まる）→ 架空 / RX3-0433
    led.record(9, 1, 0x00B, at=100, text="＊「ようこそ。ここは やどやですよ。")
    got = led.get_heard_npcs(9, MASTER, labels={28: "商"})
    assert [g["npc_id"] for g in got] == [1]
    assert got[0]["role"] == "inn" and got[0]["appearance_label"] == "商"
    assert got[0]["text"].startswith("＊「ようこそ")
    assert led.counts(9, MASTER) == {"npc_total": 2, "npc_heard": 1}


def test_同じNPCの複数の会話を持てる(tmp_path):
    led = H.HeardLedger(tmp_path)
    led.record(9, 6, 0x247, at=1, text="こんにちは")
    led.record(9, 6, 0x247, at=2, text="こんにちは")
    led.record(9, 6, 0x247, at=3, text="こんばんは", time="night")
    texts = led.texts(9, 6)
    assert [t["count"] for t in texts] == [2, 1] and texts[0]["last_heard_at"] == 2
    e = led.heard["9"]["6"]
    assert e["count"] == 3 and e["time"] == ["day", "night"] and e["talk_ids"] == [0x247]


def test_未会話リストはRAMの位置を優先(tmp_path):
    led = H.HeardLedger(tmp_path)
    led.record(9, 1, 0x00B, at=1)
    slots = [{"x": 8, "y": 16}, {"x": 0, "y": 9}]
    got = led.get_unheard_npcs(9, MASTER, slots, reachable=lambda x, y: (x, y) != (0, 9))
    assert got == [{"npc_id": 6, "x": 0, "y": 9, "position_source": "ram", "movement": "random",
                    "appearance_id": 44, "talk_id": 0x247, "reachable": False}]
    got = led.get_unheard_npcs(9, MASTER)
    assert got[0]["position_source"] == "rom" and got[0]["x"] == 3


def test_保存して読み直せる(tmp_path):
    led = H.HeardLedger(tmp_path)
    led.record(9, 1, 0x00B, at=5, text="やど")
    led.save()
    again = H.HeardLedger(tmp_path)
    assert again.is_heard(9, 1) and again.texts(9, 1)[0]["text_hash"] == H.text_hash("やど")
    body = json.loads((tmp_path / "npc-heard.json").read_text(encoding="utf-8"))
    assert body == {"9": {"1": {"talk_ids": [11], "time": ["day"], "first": 5, "last": 5, "count": 1}}}
