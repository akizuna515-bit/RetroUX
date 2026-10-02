"""聞き込みで王様に話しかけない（RX3-0194 / 2026-09-12）。

⚠⚠ 依頼者「save3 王様に聞き込みをしてセーブして終了してしまう」。
★王様（talk_id 430 / event_script 70）は冒険の書に記録したあと、**続けて旅立つかを尋ねる**。
★聞き込みは窓を B で閉じるので、⚠ B（取り消し）が「いいえ」になり**ゲームが終わる**。
→ ★聞き込みの候補にしない。⚠ 「未完」「もう全員」の数にも入れない（★手で話すのは止めない）。

★見本の文は**架空**です（⚠ 原作の会話は公開物に入れません / RX3-0433）。
★ただし見分けに使う語（`ぼうけんのしょ` / `たびだつ` = `town_service.SAVE_TALK_WORDS`）は
⚠ 本物と同じものを含めてあります（★ここを外すと検査が空回りします）。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3.knowledge import npc_heard as H
from dq3.knowledge import town_service as TS
from dq3.testing import passability as P
from dq3.testing import talk_script as T


@pytest.fixture(autouse=True)
def _本物の会話の記録を読まない(monkeypatch, tmp_path):
    """⚠ 依頼者の記録には王様の「ぼうけんのしょ」「たびだつ」が**もう入っている**。
    ★読むと記録からの見分けで外れてしまい、表（430 / 426）を消しても緑のまま（★RX3-0217 の壊す実験で分かった）。"""
    monkeypatch.setattr(TS, "CONVERSATIONS_PATH", tmp_path / "no-conversations.json")

#: ★架空の文（⚠ `SAVE_TALK_WORDS` の 2 語だけは本物と同じ / 上の註）
KING_TEXT = ("＊「おお よくきた！わがくにの たからとなるものよ！＊「そなたらの てがらを"
             "この ぼうけんのしょに かきとめよう。＊「このあとは どうする？ すぐに たびだつのか？")


def _service(tmp_path):
    table = [0x00] * 32
    table[2] = 0x80 | 0x10
    # ★3 行の広間（⚠ 2026-09-12 までは 1 行の廊下で、手前の大臣がふさいで王様に届かず、
    #   ★王様を外さなくても候補に入らなかった = この検査は素通りしていた / RX3-0217 の壊す実験で分かった）
    tiles = [[2 if c == "#" else 8 for c in row] for row in [".......", ".......", "......."]]
    svc = TS.TownService(heard=H.HeardLedger(tmp_path), rom_maps={71: P.RomMap(71, tiles, table, 0)})
    npcs = [
        {"npc_id": 0, "slot": 4, "x": 6, "y": 0, "movement": "fixed", "talk_id": 430,
         "appearance_id": 8, "role": None, "role_status": None},                     # ★王様
        {"npc_id": 1, "slot": 5, "x": 3, "y": 0, "movement": "fixed", "talk_id": 293,
         "appearance_id": 20, "role": None, "role_status": None},                    # ★大臣など
    ]
    svc.current_npcs = lambda *a, **k: {"map_id": 71, "time": "day", "status": "DEFAULT",
                                        "npcs": npcs, "runtime_count": 2}
    return svc


def test_王様は聞き込みの候補にしない(tmp_path):
    got = _service(tmp_path).unheard_reachable_npcs(71, 0, None, (0, 2))
    ids = [c["npc"]["npc_id"] for c in got]
    assert 0 not in ids, "⚠⚠ 王様に聞き込みで話しかける（★B で『いいえ』になりゲームが終わる）"
    assert ids == [1], "⚠ ほかの人まで外している: %s" % ids


def test_王様は数にも入れない(tmp_path):
    got = _service(tmp_path).counts(71, 0, None)
    assert got["talkable"] == 1, "⚠ 王様を「話しかけられる人」に数えている（★未完 1 人と出る）"


def test_話しかけない相手には理由がある():
    assert TS.HEARING_SKIP_TALK_IDS[430] and TS.HEARING_SKIP_TALK_IDS[426]
    assert "ぼうけんのしょ" in KING_TEXT and "たびだつ" in KING_TEXT
    assert TS.hearing_target({"talk_id": 293}) and not TS.hearing_target({"talk_id": 430})
    assert not TS.hearing_target({"talk_id": 0}) and not TS.hearing_target({})


# ★2026-09-12 依頼者「save8 ロマリアの玉座で同様の動きになってしまった（セーブして終了）」
#   ★記録（15:47 / map 74 / npc 1 / talk_id 426 = 台本 66）。⚠ 王様ごとに talk_id も台本も違う
#: ★架空の文（⚠ `SAVE_TALK_WORDS` の 2 語だけは本物と同じ / 冒頭の註）
ROMARIA_TEXT = ("＊「よくきた！そなたらの はたらきは みみにしておる。＊「ここでの てがらを"
                "この ぼうけんのしょに のこしておこう。＊「それでは すぐに たびだつのか？")


def test_ロマリアの王様も話しかけない():
    assert not TS.hearing_target({"talk_id": 426}, learned=frozenset()), "⚠⚠ ロマリアの王様に聞き込みで話しかける"


def test_記録から王様を見分ける(tmp_path):
    """★はじめて見る王様でも、一度記録に残れば次から話しかけない（⚠ 番号の決まりが無いため）。"""
    import json

    path = tmp_path / "npc-conversations.json"
    path.write_text(json.dumps({
        "99/1": [{"npc_id": 1, "talk_id": 999, "text": ROMARIA_TEXT}],
        "71/5": [{"npc_id": 5, "talk_id": 578, "text": "＊「おうさまに はなせば ぼうけんのしょに かいてくれるぞ。"}],
    }, ensure_ascii=False), encoding="utf-8")
    got = TS.learned_save_talks(path)
    assert 999 in got, "⚠⚠ 記録して旅立つかを聞く相手を見分けていない"
    assert 578 not in got, "⚠ 冒険の書の話をしただけの人まで外した（★「たびだつ」も要る）"
    assert not TS.hearing_target({"talk_id": 999}, learned=got)
    assert TS.hearing_target({"talk_id": 578}, learned=got)
    assert TS.learned_save_talks(tmp_path / "none.json") == frozenset(), "⚠ 記録が無いのに誰かを外した"


# ---------------------------------------------------------------------------
# ⚠⚠ 2026-09-12 再発（依頼者「イシス（save6）でやはり再発する『またすぐにたびたつつもりですか？』系」/ RX3-0194 再開）
#   ★手の表（430 / 426）と会話の記録では、イシスの女王（433）を防げなかった。→ ★王様は ROM から起こす。
# ---------------------------------------------------------------------------
ROM = pathlib.Path(__file__).resolve().parents[1] / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM（work/rom/DQ3_J.nes）が無い")
SAVE_KINGS = frozenset({426, 430, 431, 432, 433, 434, 435, 436})


@needs_rom
def test_記録して旅立つかを聞く相手をROMから起こす():
    got = T.save_king_talk_ids(ROM)
    assert got == SAVE_KINGS, "⚠⚠ $BB61 に入る台本が変わった: %s" % sorted(got)
    assert 973 not in got and 974 not in got, "⚠ 押しの強い商人は王様ではない（★手の表のまま）"


@needs_rom
def test_Q2の言い回しは2つだけ():
    """★$BF29 + 10 × 王の番号 + 3（メッセージ 3 = Q2）。

    ⚠ 03 = 王様の言い回し / 14 = イシスの女王の言い回し（★$BE4C / $BEC1）。
    ⚠⚠ 本文は写しません（★原作の会話は公開物に入れません / RX3-0433）。
    ★どちらも「記録したあと、すぐ旅立つかを尋ねる」文です。"""
    rom = ROM.read_bytes()
    at = lambda cpu: 0x10 + 13 * 0x4000 + (cpu - 0x8000)          # noqa: E731
    assert [rom[at(0xBF29 + 10 * k + 3)] for k in range(7)] == [0x03, 0x03, 0x03, 0x14, 0x03, 0x03, 0x03]


@needs_rom
def test_イシスの女王ほか記録する相手は聞き込みの候補にしない():
    for tid in (433, 432, 434, 436, 431, 435):
        assert not TS.hearing_target({"talk_id": tid}, learned=frozenset()), (
            "⚠⚠ talk_id %d（$BB61 = 記録して旅立つかを聞く）に聞き込みで話しかける" % tid)
    assert TS.hearing_target({"talk_id": 293}, learned=frozenset()), "⚠ ふつうの人まで外した"


def test_ROMが読めなくても手の表で王様を外す(monkeypatch):
    monkeypatch.setattr(TS, "rom_save_kings", lambda: frozenset())
    assert not TS.hearing_target({"talk_id": 430}, learned=frozenset())
    assert not TS.hearing_target({"talk_id": 426}, learned=frozenset())


def test_版の違うROMからは起こさない(tmp_path):
    fake = tmp_path / "other.nes"
    fake.write_bytes(bytes(0x10 + 16 * 0x4000))
    assert T.save_king_talk_ids(fake) == frozenset(), "⚠ 表の位置が合わない ROM から相手を作った"
    assert T.save_king_talk_ids(tmp_path / "none.nes") == frozenset()


def test_はいといいえのタイルをLuaへ渡せる():
    got = TS.depart_answer_params()
    assert len(got.get("yes", "")) == 4 and len(got.get("no", "")) == 6, got
    assert got["no"][:2] == got["no"][2:4] == got["yes"][2:], "★はい の「い」と いいえ の「い」は同じ字"
