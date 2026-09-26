"""手で話した会話でも、相手を残す（RX3-0133 / 2026-09-09）。

```text
⚠ これまで  勇者メモが `？「おわかいの。…` （★相手が分からない）
★これから  向き（$0644）＋ NPC のいまの位置 → `老「おわかいの。…`
           ⚠ 決まらなければ、これまでどおり `？`（★推測で名乗らせない）
```

★店員は**カウンター越し**なので、1 升先だけでなく 2 升先も見ます（RX3-0053 の実測）。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3.knowledge.town_service import TownService

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Service(TownService):
    """★NPC の一覧だけ差し替える（⚠ ROM も state.json も要らない）。"""

    def __init__(self, npcs, status="DEFAULT") -> None:      # noqa: D107
        self._npcs = npcs
        self._status = status

    def current_npcs(self, map_id, time_byte, npc_tbl_hex):  # noqa: D102
        return {"map_id": map_id, "time": "day", "status": self._status,
                "npcs": self._npcs, "runtime_count": len(self._npcs)}


def _npc(npc_id, x, y, appearance=3, role=None):
    return {"npc_id": npc_id, "x": x, "y": y, "appearance_id": appearance, "role": role,
            "talk_id": 1, "facing": 0, "walking": False, "position_source": "ram"}


# --- ★向きから相手を決める ----------------------------------------------

def test_向いた先に居る人を返す():
    npcs = [_npc(1, 5, 4), _npc(2, 9, 9)]
    s = _Service(npcs)
    # ★上（0）を向いていれば (5,4) の人
    assert s.npc_in_front(9, 0, None, (5, 5), 0)["npc_id"] == 1
    # ⚠ 下（2）を向いていれば誰も居ない
    assert s.npc_in_front(9, 0, None, (5, 5), 2) is None


def test_四方向それぞれで拾える():
    s = _Service([_npc(1, 5, 4), _npc(2, 6, 5), _npc(3, 5, 6), _npc(4, 4, 5)])
    got = {facing: s.npc_in_front(9, 0, None, (5, 5), facing)["npc_id"]
           for facing in (0, 1, 2, 3)}
    assert got == {0: 1, 1: 2, 2: 3, 3: 4}, "⚠ 向きの並びが `nav_v0` と違う"


def test_店員はカウンター越しでも拾う():
    """⚠⚠ 1 升先しか見ないと、★店の人は永久に「？」のままになる。"""
    s = _Service([_npc(7, 5, 3, role="item_shop")])
    assert s.npc_in_front(9, 0, None, (5, 5), 0)["npc_id"] == 7
    # ⚠ 3 升先は見ない（★遠くの人を話し相手にしない）
    s2 = _Service([_npc(7, 5, 2)])
    assert s2.npc_in_front(9, 0, None, (5, 5), 0) is None


def test_手前の人を返す():
    """⚠ 間に別の人が居たら、★話しているのは手前の人。"""
    s = _Service([_npc(1, 5, 4), _npc(2, 5, 3)])
    assert s.npc_in_front(9, 0, None, (5, 5), 0)["npc_id"] == 1


def test_分からないときはNoneにする():
    s = _Service([_npc(1, 5, 4)])
    assert s.npc_in_front(9, 0, None, (5, 5), None) is None      # ⚠ 向きが届いていない
    assert s.npc_in_front(9, 0, None, None, 0) is None           # ⚠ 居場所が届いていない
    assert _Service([_npc(1, 5, 4)], status="UNKNOWN").npc_in_front(9, 0, None, (5, 5), 0) is None


# --- ★勇者メモへ入るところ ----------------------------------------------

class _VM:
    """★`Dq3ViewModel._talker_now` だけを動かす（⚠ 実機も state.json も要らない）。"""

    def __init__(self, tmp_path, npcs, facing, pos):
        from dq3.ui.view_model import Dq3ViewModel

        self.vm = Dq3ViewModel(state_path=tmp_path / "state.json",
                               knowledge_path=tmp_path / "k.json",
                               memo_path=tmp_path / "memos.jsonl",
                               seen_path=tmp_path / "seen.json")
        self.vm.position = lambda: pos
        self.vm.facing = lambda: facing
        self.vm.time_byte = lambda: 0
        self.vm.npc_table_hex = lambda: None
        self.vm._town_service = _Service(npcs)


def test_目の前の人の見た目の字がメモの話者になる(tmp_path, monkeypatch):
    from dq3.knowledge import town_service as TS

    monkeypatch.setattr(_Service, "appearance_label", lambda self, aid: "老", raising=False)
    got = _VM(tmp_path, [_npc(1, 5, 4, appearance=12)], 0, (1, 9, 5, 5))
    speaker, npc_id, map_id = got.vm._talker_now()
    assert speaker == "老" and npc_id == 1 and map_id == 9
    assert TS.TownService.FACING_STEPS[0] == (0, -1)


def test_世界地図では相手を決めない(tmp_path):
    got = _VM(tmp_path, [_npc(1, 154, 193)], 0, (0, 9, 154, 194))
    assert got.vm._talker_now() == (None, None, None), "⚠ 世界地図に話す相手は居ない"


def test_相手が決まらなければ話者は空のまま(tmp_path):
    got = _VM(tmp_path, [], 0, (1, 9, 5, 5))
    assert got.vm._talker_now() == (None, None, None)


def test_会話メモは相手が分かれば話者つきで残る(tmp_path, monkeypatch):
    monkeypatch.setattr(_Service, "appearance_label", lambda self, aid: "商", raising=False)
    got = _VM(tmp_path, [_npc(3, 5, 3, role="item_shop")], 0, (1, 9, 5, 5))
    vm = got.vm
    vm.conversation_open_now = lambda: True
    memo = vm.add_memo("＊「ここは どうぐやです。」", source="conversation",
                       speaker=vm._talker_now()[0])
    assert memo is not None
    assert memo.speaker_label == "商"
    assert memo.line.startswith("商　ここは どうぐやです。"), memo.line   # ★RX3-0253: 「」は出さない


def test_話者が空なら今までどおりハテナ(tmp_path):
    got = _VM(tmp_path, [], 0, (1, 9, 5, 5))
    memo = got.vm.add_memo("＊「おわかいの。」", source="conversation")
    assert memo.speaker_label == "？"
    assert memo.line.startswith("？　")


# --- ★配線（⚠ 向きが届いていること）------------------------------------

def test_向きがstateまで来ている():
    """⚠⚠ 写しが 3 か所（profile → 生成物 → dev.lua）。★どれか 1 つ欠けると常に `？`。"""
    import json

    profile = json.loads((ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
                         .read_text(encoding="utf-8"))
    assert profile["runtime"]["location"]["facing"] == "0x0644"
    from dq3.phase0.generate_lua import LOCATION_KEYS

    assert "facing" in LOCATION_KEYS
    dev = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert "out.facing = memory.readbyte(LOC.facing)" in dev, "⚠ state.json へ向きを載せていない"
    vm = (ROOT / "dq3" / "ui" / "view_model.py").read_text(encoding="utf-8")
    assert "def facing(self)" in vm and "_talker_now" in vm


@pytest.mark.parametrize("facing", [0, 1, 2, 3])
def test_向きの並びはnav_v0と同じ(facing):
    """⚠ `nav_v0.lua` は `up=0, right=1, down=2, left=3`。★ずれると別の人を掴む。"""
    nav = (ROOT / "dq3" / "phase0" / "nav_v0.lua").read_text(encoding="utf-8")
    assert "KEY_INDEX = {up = 0, right = 1, down = 2, left = 3}" in nav
    steps = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}
    assert TownService.FACING_STEPS[facing] == steps[facing]
