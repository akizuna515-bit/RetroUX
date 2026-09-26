"""AUTO_V0 の数え方を 1 か所にまとめた（RX3-0153 / 2026-09-10）。

## ⚠⚠ ここが直した中身

★`AUTO_V0_DONE … turns=N` は **2 重に誤って**いました（実測 2026-09-10）:

```text
AUTO_V0_DONE 戦闘が終わった（…） turns=8
AUTO_V0_DONE 戦闘が終わった（…） turns=16   ⚠ 前の戦闘ぶんが乗ったまま
AUTO_V0_DONE 戦闘が終わった（…） turns=24
AUTO_V0_DONE 戦闘が終わった（…） turns=32
```

1. ★数えていたのは **1 人 1 回の行動**（4 人なら 1 ターンで 4）
2. ⚠ `finish()` で 0 に戻していないので、**戦闘をまたいで累積**する

→ ★新しい書式は `rounds=R actions=A`。⚠ 旧い記録 248 戦ぶんも読めること。
"""
from __future__ import annotations

import pytest

from dq3 import battle_count as BC


# --- ★読み取り ---------------------------------------------------------

def test_新しい書式はターンと行動を分けて持つ():
    got = BC.parse_done("AUTO_V0_DONE 戦闘が終わった（…） rounds=9 actions=36")
    assert got == {"why": "戦闘が終わった（…）", "rounds": 9, "actions": 36,
                   "cumulative": False}


def test_古い書式も読める():
    """⚠⚠ 248 戦ぶんの記録が `turns=` のまま残っている（★捨てない）。"""
    got = BC.parse_done("AUTO_V0_DONE 戦闘が終わった（…） turns=36")
    assert got["actions"] == 36
    assert got["rounds"] is None, "⚠⚠ 分からないターン数を作っている"
    assert got["cumulative"] is True


#: ★RX3-0198（2026-09-12）: `auto_v0.lua` の `COUNT.fields` が後ろに付ける形
SUMMARY_LINE = ("AUTO_V0_DONE 勝利（結果は自動で送る） rounds=2 actions=8 strategy=leveling "
                "attack=5 magic=2 heal=1 support=0 defend=0 other=0 mp_used=12")


def test_まとめの付いた行も読める():
    """⚠⚠ DONE は行末で固定の正規表現。★後ろに `key=value` が付いても落とさない。"""
    got = BC.parse_done(SUMMARY_LINE)
    assert got is not None, "⚠⚠ まとめを付けたら終わりの行として読めなくなった"
    assert (got["why"], got["rounds"], got["actions"]) == ("勝利（結果は自動で送る）", 2, 8)
    assert got["summary"] == {"strategy": "leveling", "attack": 5, "magic": 2, "heal": 1,
                              "support": 0, "defend": 0, "other": 0, "mp_used": 12}


def test_まとめの無い行は今までと同じ辞書():
    """★2026-09-12 までの記録（⚠ `summary` を足さない = 読む側を変えなくてよい）。"""
    got = BC.parse_done("AUTO_V0_DONE 戦闘が終わった（…） rounds=9 actions=36")
    assert "summary" not in got


def test_まとめはEventのdataになる():
    got = BC.event_fields(BC.parse_done(SUMMARY_LINE)["summary"])
    assert got == {"strategy": "leveling", "mp_used": 12,
                   "breakdown": {"attack": 5, "magic": 2, "heal": 1, "support": 0,
                                 "defend": 0, "other": 0}}
    assert BC.event_fields(None) == {}
    # ⚠ MP が分からない（1 度も押していない）なら、MP消費 を作らない
    assert "mp_used" not in BC.event_fields({"attack": 0, "magic": 0})


def test_まとめ付きの行でも戦闘ごとに数える():
    text = chr(10).join(["=== AUTO_V0 start", SUMMARY_LINE, SUMMARY_LINE])
    assert [g["actions"] for g in BC.scan(text)] == [8, 8]


@pytest.mark.parametrize("line", [
    "AUTO_V0_DONE 戦闘が終わった",                 # ⚠ 数が無い
    "AUTO_V0 turn=3 slot=p1 action=attack",
    "AUTO_V0_STOP reason=screen_frozen",
    "",
])
def test_関係ない行はNoneを返す(line):
    assert BC.parse_done(line) is None


# --- ⚠⚠ 累積をほどく ---------------------------------------------------

def test_古い記録は差を取る():
    """★実測 2026-09-10 の 8 / 16 / 24 / 32 を、⚠ 8・8・8・8 に戻す。"""
    text = chr(10).join([
        "=== AUTO_V0 start",
        "AUTO_V0_DONE a turns=8",
        "AUTO_V0_DONE b turns=16",
        "AUTO_V0_DONE c turns=24",
        "AUTO_V0_DONE d turns=32",
    ])
    got = BC.scan(text)
    assert [g["actions"] for g in got] == [8, 8, 8, 8]
    assert [g["actions_total"] for g in got] == [8, 16, 24, 32]


def test_新しい記録は差を取らない():
    """⚠⚠ ここが**壊れやすい所**。★新しい書式は戦闘ごとに 0 から数え直す。

    ⚠ 古いほうの「差を取る」を当ててしまうと、8・8・8 が **8・0・0** になります。
    """
    text = chr(10).join([
        "=== AUTO_V0 start",
        "AUTO_V0_DONE a rounds=2 actions=8",
        "AUTO_V0_DONE b rounds=2 actions=8",
        "AUTO_V0_DONE c rounds=2 actions=8",
    ])
    got = BC.scan(text)
    assert [g["actions"] for g in got] == [8, 8, 8]
    assert [g["rounds"] for g in got] == [2, 2, 2]


def test_遊びをまたぐと数え直す():
    """★`=== AUTO_V0 start` で 0 に戻す（⚠ 前の遊びの分を引かない）。"""
    text = chr(10).join(["AUTO_V0_DONE a turns=20",
                         "=== AUTO_V0 start",
                         "AUTO_V0_DONE b turns=6"])
    assert [g["actions"] for g in BC.scan(text)] == [20, 6]


def test_止まった行も順番に残る():
    text = chr(10).join(["AUTO_V0_DONE a rounds=1 actions=4",
                         "AUTO_V0_STOP reason=screen_frozen"])
    got = BC.scan(text)
    assert [g["kind"] for g in got] == ["done", "stopped"]
    assert got[1]["why"] == "screen_frozen"


# --- ★走りながら数える -------------------------------------------------

def test_slotが増えなくなったら次のターン():
    """★区切りの決め方は `auto_v0.lua` の `count_action` と同じ。"""
    live = BC.Live()
    for slot in ("p1", "p2", "p3", "p4", "p1", "p2"):
        live.feed(slot)
    assert (live.rounds, live.actions) == (2, 6)


def test_人が減っても数えられる():
    """⚠ 死んだ人は行動しないので、★slot が飛ぶ（p1 p3 / p1 p3 …）。"""
    live = BC.Live()
    for slot in ("p1", "p3", "p1", "p3"):
        live.feed(slot)
    assert (live.rounds, live.actions) == (2, 4)


def test_slotが読めなくても落とさない():
    live = BC.Live()
    live.feed(None)
    live.feed("???")
    assert live.actions == 2


def test_数え直せる():
    live = BC.Live()
    live.feed("p1")
    live.reset()
    assert (live.rounds, live.actions) == (0, 0)


# --- ★出す形 -----------------------------------------------------------

def test_依頼者の指定どおりに書く():
    """★2026-09-10 の指定:「9ターン（36行動）」（⚠ 「手」ではない）。"""
    assert BC.describe(9, 36) == "9ターン（36行動）"


def test_ターンが分からなければ名乗らない():
    """⚠⚠ 旧い記録で「9ターン」と書いたら、それは**作り話**。"""
    got = BC.describe(None, 36)
    assert got == "36行動"
    assert "ターン" not in got
