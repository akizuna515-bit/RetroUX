"""聞き込みでアッサラームの押しの強い商人に話しかけない（RX3-0217 / 2026-09-12）。

⚠⚠ 依頼者「save5 アッサラームの押しの強い商人。無限ループになり、はいを選んだ後、商品を選ばずにBか、
ずっと値切るとようやく解放される。聞き込みで無限ループにはまってしまう」。
★聞き込みは話しかけたあと B しか押さない。★B は選択肢の「いいえ」で、この商人は
「まあ そういわずに」と同じことを聞き直す → ⚠ B を 16 回押して聞き込みごと止まり、窓が開いたまま残った
（`nav_v0.log`「B を 16 回押した」/ `town_speed.log` reason=window_will_not_close）。
→ ★王様（RX3-0194）と同じく聞き込みの候補にしない。⚠ 手で話すのは止めない。

★見本の文は依頼者の記録（2026-09-12 18:52 / map 12 / npc 11）を短く写したもの。
"""
from __future__ import annotations

import json

import pytest

from dq3.knowledge import npc_heard as H
from dq3.knowledge import town_service as TS
from dq3.testing import passability as P

MERCHANT_TEXT = "＊「おお！ わたしの ともだち！＊「うっているものを みますか？＊「まあ そういわずに"


@pytest.fixture(autouse=True)
def _本物の会話の記録を読まない(monkeypatch, tmp_path):
    """⚠ 依頼者の記録には、この商人の「そういわずに」が**もう入っている**。
    ★読むと記録からの見分けで外れてしまい、表（974 / 973）を消しても緑のまま（★壊す実験で分かった）。"""
    monkeypatch.setattr(TS, "CONVERSATIONS_PATH", tmp_path / "no-conversations.json")


def _service(tmp_path):
    table = [0x00] * 32
    table[2] = 0x80 | 0x10
    # ★3 行の広間（⚠ 1 行の廊下だと手前の人がふさぎ、外さなくても奥の商人に届かない = 検査が素通りする）
    tiles = [[2 if c == "#" else 8 for c in row] for row in [".......", ".......", "......."]]
    svc = TS.TownService(heard=H.HeardLedger(tmp_path), rom_maps={12: P.RomMap(12, tiles, table, 0)})
    npcs = [
        {"npc_id": 11, "slot": 15, "x": 6, "y": 0, "movement": "fixed", "talk_id": 974,
         "appearance_id": 28, "role": None, "role_status": None},                    # ★押しの強い商人
        {"npc_id": 10, "slot": 14, "x": 4, "y": 0, "movement": "fixed", "talk_id": 973,
         "appearance_id": 28, "role": None, "role_status": None},                    # ★もう 1 人
        {"npc_id": 1, "slot": 5, "x": 2, "y": 0, "movement": "fixed", "talk_id": 293,
         "appearance_id": 20, "role": None, "role_status": None},                    # ★ふつうの町の人
    ]
    svc.current_npcs = lambda *a, **k: {"map_id": 12, "time": "day", "status": "DEFAULT",
                                        "npcs": npcs, "runtime_count": 3}
    return svc


def test_押しの強い商人は聞き込みの候補にしない(tmp_path):
    got = _service(tmp_path).unheard_reachable_npcs(12, 0, None, (0, 2))
    ids = [c["npc"]["npc_id"] for c in got]
    assert 11 not in ids and 10 not in ids, "⚠⚠ 押しの強い商人に聞き込みで話しかける（★B で聞き直しが続く）"
    assert ids == [1], "⚠ ほかの人まで外している: %s" % ids


def test_押しの強い商人は数にも入れない(tmp_path):
    assert _service(tmp_path).counts(12, 0, None)["talkable"] == 1, "⚠ 商人を「話しかけられる人」に数えている"


def test_話しかけない相手には理由がある():
    assert TS.HEARING_SKIP_TALK_IDS[974] and TS.HEARING_SKIP_TALK_IDS[973]
    assert not TS.hearing_target({"talk_id": 974}, learned=frozenset())
    assert not TS.hearing_target({"talk_id": 973}, learned=frozenset())


def test_記録から聞き直す商人を見分ける(tmp_path):
    """★ほかの町の押しの強い商人も、一度「そういわずに」が記録に残れば次から話しかけない。"""
    path = tmp_path / "npc-conversations.json"
    path.write_text(json.dumps({
        "12/11": [{"npc_id": 11, "talk_id": 998, "text": MERCHANT_TEXT}],
        "12/3": [{"npc_id": 3, "talk_id": 577, "text": "＊「ここは アッサラームの まちです。"}],
    }, ensure_ascii=False), encoding="utf-8")
    got = TS.learned_save_talks(path)
    assert 998 in got, "⚠⚠ 聞き直し続ける商人を記録から見分けていない"
    assert 577 not in got, "⚠ ふつうの町の人まで外した"
    assert not TS.hearing_target({"talk_id": 998}, learned=got)
    assert TS.hearing_target({"talk_id": 577}, learned=got)


def test_王様の見分け方は変わらない(tmp_path):
    """⚠ 言葉の組を増やしても、王様は「ぼうけんのしょ」と「たびだつ」の両方で見分ける（★片方だけでは外さない）。"""
    path = tmp_path / "npc-conversations.json"
    path.write_text(json.dumps({
        "71/5": [{"npc_id": 5, "talk_id": 578, "text": "＊「おうさまに はなせば ぼうけんのしょに かいてくれるぞ。"}],
    }, ensure_ascii=False), encoding="utf-8")
    assert 578 not in TS.learned_save_talks(path)
