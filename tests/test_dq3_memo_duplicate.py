"""同じ台詞が勇者メモに 2 件入る（RX3-0294 / 2026-09-18）。

⚠⚠ 違うのは**頭の札**と、聞き込みの側だけに付く**末尾の 」** だけでした。

```text
20:25:06  npc_talk      囚「おら ひとをころしちまったでな。…かわいそうになあ‥。」
20:27:17  conversation  ＊「おら ひとをころしちまったでな。…かわいそうになあ‥。
```

★`add_if_new` は本文の**完全一致**で見分けていたので、⚠ ここをすり抜けます。
（★話者を埋める道 `fill_speaker` のほうは、前から `talk_body` で見ていた。）

★実測（依頼者の記録 / 会話メモ 889 行）: 65 組 130 行が二重 ＝ **65 行が余分**。
"""
from __future__ import annotations

import io
import json

import pytest

from dq3.knowledge import memos as M

HEARD = "囚「おら ひとをころしちまったでな。かわいそうになあ‥。」"   # ★聞き込み（札 ＋ 末尾の 」）
TALKED = "＊「おら ひとをころしちまったでな。かわいそうになあ‥。"      # ★手で話した


@pytest.fixture()
def store(tmp_path):
    return M.MemoStore(tmp_path / "memos.jsonl")


# --- ★鍵 ---------------------------------------------------------------

def test_札と末尾の鉤括弧を外して比べる():
    a = M.talk_key(HEARD, location_id="L23", npc_id=7)
    b = M.talk_key(TALKED, location_id="L23", npc_id=7)
    assert a == b and a is not None


def test_相手が分からなければ畳まない():
    """⚠ 推測で消さない（★実測 51 行が `npc_id` 無し）。"""
    assert M.talk_key(HEARD, location_id="L23", npc_id=None) is None


def test_会話でなければ触らない():
    """⚠ 地図・宝箱のメモを巻き込まない。"""
    assert M.talk_key("サマンオサの小部屋3　宝箱：魔物だった",
                      location_id="L23", npc_id=7) is None


def test_場所が違えば別物():
    assert (M.talk_key(HEARD, location_id="L23", npc_id=7)
            != M.talk_key(HEARD, location_id="L24", npc_id=7))


def test_相手が違えば別物():
    """⚠⚠ ここが「場所 + 本文」だけにしてはいけない理由（★宿屋の『ぐうぐう‥‥。』）。"""
    assert (M.talk_key(HEARD, location_id="L23", npc_id=7)
            != M.talk_key(HEARD, location_id="L23", npc_id=8))


def test_番号が文字でも同じ鍵になる():
    assert (M.talk_key(HEARD, location_id="L23", npc_id="7")
            == M.talk_key(HEARD, location_id="L23", npc_id=7))


# --- ★足すとき --------------------------------------------------------

def test_聞き込みのあとに手で話しても増えない(store):
    """★依頼者の記録で起きていた向き（⚠ 話者が埋まっているので fill_speaker は働かない）。"""
    got = store.add_if_new(HEARD, location_id="L23", npc_id=7,
                           source=M.NPC_TALK, speaker="囚")
    assert got is not None
    assert store.add_if_new(TALKED, location_id="L23", npc_id=7,
                            source=M.CONVERSATION) is None
    assert len(list(store)) == 1
    # ★残るのは先に記録したほう（⚠ 話者の札が付いている）
    assert list(store)[0].text == HEARD


def test_手で話したあとに聞き込んでも増えない(store):
    """★こちらは前から 1 件だった（`fill_speaker` が話者を埋める）。⚠ 壊していないこと。"""
    store.add_if_new(TALKED, location_id="L23", npc_id=7, source=M.CONVERSATION)
    assert store.add_if_new(HEARD, location_id="L23", npc_id=7,
                            source=M.NPC_TALK, speaker="囚") is None
    rows = list(store)
    assert len(rows) == 1
    assert rows[0].speaker == "囚", "⚠ 話者が埋まっていない（★RX3-0236 を壊した）"


def test_別の人の同じ台詞は残る(store):
    """⚠⚠ 宿屋で 6 人が「ぐうぐう‥‥。」と言う（★依頼者の記録 L11 / 実測）。

    ```text
    村「ぐうぐう‥‥。」 npc=3    娘「ぐうぐう‥‥。」 npc=7
    商「ぐうぐう‥‥。」 npc=8    老「ぐうぐう‥‥。」 npc=2
    ```

    ★札は人ごとに違うが、`talk_body` は**同じ**になる。⚠ 相手で分けていないと 1 件に潰れる。
    """
    for npc, who in ((3, "村"), (7, "娘"), (8, "商"), (2, "老")):
        store.add_if_new(who + "「ぐうぐう‥‥。」", location_id="L11",
                         npc_id=npc, source=M.NPC_TALK, speaker=who)
    assert len(list(store)) == 4


def test_相手が分からない行は畳まない(store):
    """⚠ 同じ相手だと確かめられないものを消さない。"""
    store.add_if_new(HEARD, location_id="L23", npc_id=None, source=M.NPC_TALK,
                     speaker="囚")
    store.add_if_new(TALKED, location_id="L23", npc_id=None,
                     source=M.CONVERSATION)
    assert len(list(store)) == 2


def test_中身が違えば増える(store):
    store.add_if_new(HEARD, location_id="L23", npc_id=7, source=M.NPC_TALK,
                     speaker="囚")
    got = store.add_if_new("＊「べつの はなしだ。", location_id="L23", npc_id=7,
                           source=M.CONVERSATION)
    assert got is not None and len(list(store)) == 2


# --- ★読むとき（★既にある記録）----------------------------------------

def _write(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + chr(10))


def test_既にある二重は読むときに畳む(tmp_path):
    """★依頼者の記録には既に 65 行ぶん入っている（⚠ ファイルは書き換えない）。"""
    path = tmp_path / "memos.jsonl"
    _write(path, [
        {"order": 1, "text": HEARD, "location_id": "L23", "npc_id": 7,
         "source": "npc_talk", "speaker": "囚"},
        {"order": 2, "text": TALKED, "location_id": "L23", "npc_id": 7,
         "source": "conversation"},
        {"order": 3, "text": "＊「べつの はなしだ。", "location_id": "L23",
         "npc_id": 7, "source": "conversation"},
    ])
    store = M.MemoStore(path)
    assert len(list(store)) == 2
    assert store.folded == 1, "⚠ 何行畳んだかを残していない（★黙って減らさない）"
    # ⚠⚠ ファイルは**減っていない**（★依頼者の記録を書き換えない）
    assert len([ln for ln in io.open(path, encoding="utf-8") if ln.strip()]) == 3


def test_畳んでも通し番号は先へ進む(tmp_path):
    """⚠ 畳んだ行の `order` を使い回すと、⚠ 記録が上書きされる。"""
    path = tmp_path / "memos.jsonl"
    _write(path, [
        {"order": 1, "text": HEARD, "location_id": "L23", "npc_id": 7,
         "source": "npc_talk", "speaker": "囚"},
        {"order": 2, "text": TALKED, "location_id": "L23", "npc_id": 7,
         "source": "conversation"},
    ])
    store = M.MemoStore(path)
    got = store.add("＊「あたらしい はなし。", location_id="L23", npc_id=8,
                    source=M.CONVERSATION)
    assert got.order == 3


def test_畳む対象が無ければ0(tmp_path):
    """⚠ 数えるところが常に動いていないか（★空回りしていない）。"""
    path = tmp_path / "memos.jsonl"
    _write(path, [{"order": 1, "text": HEARD, "location_id": "L23",
                   "npc_id": 7, "source": "npc_talk", "speaker": "囚"}])
    store = M.MemoStore(path)
    assert store.folded == 0 and len(list(store)) == 1
