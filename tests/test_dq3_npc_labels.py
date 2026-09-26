"""見た目の札 — バラモスは「バ」（RX3-0301 / 2026-09-20）。

⚠⚠ 依頼者「勇者メモ バラモスは バ で良い」。

## ★どうやって番号を決めたか（⚠ 推測ではありません）

```text
根拠1  ROM の NPC 表       map 88 (8,3) 見た目 84 talk_id 401
                           ★見た目 84 は **250 枚の map の昼夜ぜんぶで、この 1 体だけ**
根拠2  実機のセーブ         fixture battle_baramos（= tools/fceux/fcs/DQ3_J-bak.fc9）
                           map 88 / 戦闘中 / 敵は バラモス 1 匹 / パーティは (8,4)
                           → ★真上 (8,3) が、根拠1 の見た目 84 の升
```

⚠ 見つからなかった探し方も書いておきます（★次の人が同じ道を掘らない）:

```text
⚠ セーブ 141 本の**実機の見た目の枠**（WRAM $6ABE）を総当たり → ★1 件も出ない
   理由: 戦闘中は枠が 0xff に戻る（fc9 の枠は 04 06 04 04 ff 4c ff …）
★ROM の表から引いたら 1 発だった
```

## ⚠ ほかの穴は埋めません

★依頼者の指示は バラモスの 1 件だけです（⚠「ゾーマは？で良い」）。
⚠ `124` は **null のまま**（★見た目と実物の対応が取れていない）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3.testing import npc_sprites as NS

ROOT = pathlib.Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT / "data" / "dq3" / "npc-appearance-labels.json"
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"

BARAMOS_APP = 84        #: ★バラモスの見た目（⚠ 下の 2 件がこの数の根拠）
BARAMOS_MAP = 88        #: ★バラモス城の小部屋（`work/dq3-knowledge/location-book.json` L88）
BARAMOS_AT = (8, 3)     #: ★ROM の表での立ち位置
BARAMOS_ENEMY = 132     #: ★戦闘の敵番号（⚠ 見た目の番号とは別物）

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="⚠ ROM が無い")


@pytest.fixture(scope="module")
def labels() -> dict:
    return json.loads(LABELS_PATH.read_text(encoding="utf-8"))


# --- ★依頼者が決めたこと -------------------------------------------------

def test_バラモスの札はバ(labels):
    assert labels[str(BARAMOS_APP)] == "バ"


def test_勇者メモに出る字もバになる(labels):
    """⚠ 表を直しても、★読む側が別の道で字を作っていたら意味がない（両端をつなぐ）。"""
    from dq3.knowledge.town_service import TownService

    assert NS.label_for(BARAMOS_APP) == "バ"
    assert TownService().appearance_label(BARAMOS_APP) == "バ"


def test_勇者メモの1行はバで始まる():
    """★`商「…」` と同じ形（指示書 §15-2）。⚠ 本文は作り物（★原作の字を焼かない）。"""
    from dq3.knowledge.town_service import TownService

    line = TownService.memo_text("バ", "＊「ここは とおさんぞ")
    assert line == "バ「ここは とおさんぞ」", line


# --- ★番号の根拠1: ROM の表 ----------------------------------------------

@needs_rom
def test_見た目84はROMの全mapでこの1体だけ():
    """⚠⚠ 「そこに居る」だけでは足りない。★ほかに 1 体も居ないことまで数える。"""
    from dq3.testing import npc_rom as R

    lists = R.parse_lists(R._prg(None))
    hits = []
    for map_id, recs in enumerate(lists):
        for night in (False, True):
            for r in R.expand(recs, night=night):
                if r["appearance_id"] == BARAMOS_APP:
                    hits.append((map_id, night, r["x"], r["y"], r["talk_id"]))
    assert [(m, x, y) for m, _n, x, y, _t in hits] == [
        (BARAMOS_MAP,) + BARAMOS_AT, (BARAMOS_MAP,) + BARAMOS_AT], hits
    assert {t for *_r, t in hits} == {401}, hits


@needs_rom
def test_同じ小部屋の残り2体は別の見た目():
    """⚠ 部屋ごと「バ」にしていないこと（★両脇の炎は 76 のまま）。"""
    from dq3.testing import npc_rom as R

    rows = R.npcs_for_map(BARAMOS_MAP, night=False)
    assert sorted((r["x"], r["y"], r["appearance_id"]) for r in rows) == [
        (5, 4, 76), (8, 3, BARAMOS_APP), (11, 4, 76)]


# --- ★番号の根拠2: 実機のセーブ -------------------------------------------

@needs_rom
def test_バラモスの見た目は実機のセーブと一致する():
    """★戦闘中のセーブで、パーティの真上が ROM の表の「見た目 84」の升。

    ⚠ このセーブの**実機の見た目の枠**は `0xff` です（★戦闘中は消える）。
    → ★だから「枠を総当たり」では見つかりません。⚠ 位置で突き合わせます。
    """
    from dq3.testing import fixtures as FX
    from dq3.testing import npc_rom as R

    try:
        fx = FX.get("battle_baramos")
    except Exception as exc:                                   # noqa: BLE001
        pytest.skip("⚠ fixture battle_baramos が使えません: %s" % exc)

    exp = fx.expected
    assert exp["map_id"] == BARAMOS_MAP
    assert exp["in_battle"] is True
    assert [g["id"] for g in exp["enemy_groups"]] == [BARAMOS_ENEMY]
    px, py = exp["local_pos"]
    # ★真上の升（⚠ 会話の届く範囲ではなく、★隣接 1 升ちょうど）
    assert (px, py - 1) == BARAMOS_AT, (exp["local_pos"], BARAMOS_AT)

    rows = {(r["x"], r["y"]): r["appearance_id"]
            for r in R.npcs_for_map(BARAMOS_MAP, night=False)}
    assert rows[BARAMOS_AT] == BARAMOS_APP


# --- ⚠ 巻き込んでいないこと ------------------------------------------------

def test_穴は推測で埋めない(labels):
    """⚠ 依頼者の指示は バラモスの 1 件だけ（★「ゾーマは？で良い」）。"""
    assert labels["124"] is None, "⚠⚠ 根拠なく埋めた"
    assert sum(1 for v in labels.values() if v is None) == 1


def test_表の件数を増やしていない(labels):
    """⚠ 番号を勝手に足していない（★飛んでいる番号はそのまま）。"""
    assert len(labels) == 51
    for missing in ("132", "196", "200", "204"):
        assert missing not in labels, missing


def test_魔の札は92に残る(labels):
    """★もとは 84 と 92 が両方「魔」でした。⚠ 消したのではなく、★84 だけ変えた。"""
    assert labels["92"] == "魔"
    assert [k for k, v in labels.items() if v == "バ"] == [str(BARAMOS_APP)]


def test_未定義は疑問符で出る():
    """⚠ 穴のままの見た目は「？」（★依頼者「ゾーマは？で良い」）。"""
    assert NS.label_for(124) == NS.UNDEFINED == "？"
    assert NS.label_for(0xFF) == NS.UNDEFINED
