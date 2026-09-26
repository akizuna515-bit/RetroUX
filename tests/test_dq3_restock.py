"""補充（リストック）の計画（RX3-0066 / 2026-09-08）。

★DQ2 の `retroux/plugins/dq2/restock.lua` から**考え方**を移した層です。
⚠ 実機の店操作（窓の番号・品揃えの読み方）は `RX3-0119` へ分離しました。

## ⚠⚠ 移植でいちばん危ないところ

```text
           DQ2            DQ3
装備中     bit6（0x40）   ⚠⚠ bit7（0x80）
空き枠     nil / 0        ⚠⚠ 0xFF（★0 は「ひのきのぼう」）
```

★`& 0x3F` をそのまま持ってくると、⚠ `0x40` 以上の道具が**全部ずれます**。
"""
from __future__ import annotations

import pytest

import pathlib

from dq3.knowledge import restock as RS

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
#: ★`build_plan`/`to_params` は品名・値段を ROM（`item_info`）から引く（RX3-0083）
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")

E = RS.EMPTY_SLOT


def _who(name, *items):
    """★1 人（⚠ 8 枠。★足りないぶんは空きで埋める）。"""
    bag = list(items) + [E] * (RS.ITEM_SLOTS - len(items))
    return {"name": name, "inventory": bag[:RS.ITEM_SLOTS]}


#: ★どうぐや（⚠ 実物の並びではなく、★この検査のための最小の店）
SHOP = (RS.HERB, RS.ANTIDOTE, RS.WING)


# ======================================================================
# ★袋を読む（⚠⚠ DQ2 との差）
# ======================================================================
def test_装備中も1個と数える():
    """⚠⚠ DQ3 の装備中の印は **bit7**（★DQ2 の bit6 ではない）。"""
    party = [_who("アリス", 2, 2 | RS.EQUIPPED_BIT)]
    assert RS.count_have(party, 2) == 2


def test_0x3Fで切ると別の道具になる():
    """★★ ⚠⚠ DQ2 のマスクを持ってきたときに何が起きるか ★★

    ```text
    やくそう 101 = 0x65      ⚠ `& 0x3F` → 0x25 = 37（★別の道具）
    ```
    """
    assert RS.HERB & 0x3F != RS.HERB, "⚠ この検査の前提が崩れている"
    party = [_who("アリス", RS.HERB)]
    assert RS.count_have(party, RS.HERB) == 1
    assert RS.count_have(party, RS.HERB & 0x3F) == 0, "⚠⚠ 0x3F で切った ID が当たった"


def test_空き枠は0xFFだけ():
    """⚠⚠ `0` は空きではありません（★「ひのきのぼう」）。"""
    assert RS.free_slots([_who("アリス", 0, 0)]) == 6
    assert RS.count_have([_who("アリス", 0, 0)], 0) == 2, "⚠ 0 を空きと数えた"


def test_送られてこない枠を空きと見なさない():
    """⚠ Lua が袋を送っていないとき、★「8 枠空いている」と思い込まない。"""
    assert RS.free_slots([{"name": "アリス"}]) == 0
    assert RS.free_slots([]) == 0


def test_持たせる相手は空きが最も多い人():
    party = [_who("アリス", 1, 2, 3), _who("ボブ", 1), _who("カイ", 1, 2)]
    pos, name, free = RS.carrier(party)
    assert (pos, name, free) == (1, "ボブ", 7)


def test_空きが無ければ持たせる相手は居ない():
    full = [_who("アリス", *range(RS.ITEM_SLOTS))]
    assert RS.carrier(full) == (None, None, 0)


# ======================================================================
# ★計画（⚠ 0 個 → 目標 / 途中 → 目標 / 足りている）
# ======================================================================
@needs_rom
def test_0個なら目標の数だけ買う():
    plan = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 5)], gold=1000)
    assert [(l.item_id, l.have, l.need, l.buy) for l in plan.lines] == [(RS.HERB, 0, 5, 5)]
    assert plan.total_cost == 5 * plan.lines[0].price
    assert plan.stop is None


@needs_rom
def test_3個あれば差分の2個だけ買う():
    party = [_who("アリス", RS.HERB, RS.HERB), _who("ボブ", RS.HERB)]
    plan = RS.build_plan(party, SHOP, [(RS.HERB, 5)], gold=1000)
    assert [(l.have, l.buy) for l in plan.lines] == [(3, 2)]


def test_足りていれば1個も買わない():
    party = [_who("アリス", *([RS.HERB] * 5))]
    plan = RS.build_plan(party, SHOP, [(RS.HERB, 5)], gold=1000)
    assert plan.is_empty() and plan.stop == RS.ENOUGH
    assert "足りている" in plan.summary()


@needs_rom
def test_複数の品をまとめて計画する():
    plan = RS.build_plan([_who("アリス"), _who("ボブ")], SHOP,
                         [(RS.HERB, 3), (RS.ANTIDOTE, 2)], gold=1000)
    assert [l.item_id for l in plan.lines] == [RS.HERB, RS.ANTIDOTE]
    assert plan.total_buy == 5


# ======================================================================
# ⚠ 安全停止（★ボタンを 1 つも押さずに終わる）
# ======================================================================
def test_店が扱っていなければ止まる():
    plan = RS.build_plan([_who("アリス")], (RS.ANTIDOTE,), [(RS.HERB, 5)], gold=1000)
    assert plan.is_empty() and plan.stop == RS.NOT_SOLD
    assert "扱っていません" in plan.summary() or "置いていません" in plan.summary()


def test_品揃えが読めなくても落ちない():
    plan = RS.build_plan([_who("アリス")], None, [(RS.HERB, 5)], gold=1000)
    assert plan.is_empty() and plan.stop == RS.NOT_SOLD


@needs_rom
def test_所持金が足りなければ買える数まで削る():
    plan = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 5)], gold=20)
    price = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 1)], gold=999).lines[0].price
    assert plan.lines[0].buy == 20 // price
    assert plan.notes and "足りません" in plan.notes[0]


def test_1個も買えなければ止まる():
    plan = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 5)], gold=0)
    assert plan.is_empty() and plan.stop == RS.NO_GOLD
    assert "お金が足りません" in plan.summary()


def test_残しておくお金は使わない():
    """★宿代を残す（⚠ 所持金ぜんぶを使い切らない）。"""
    plan = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 5)], gold=100, keep_gold=100)
    assert plan.is_empty() and plan.stop == RS.NO_GOLD


@needs_rom
def test_袋がいっぱいなら止まる():
    full = [_who("アリス", *range(RS.ITEM_SLOTS))]
    plan = RS.build_plan(full, SHOP, [(RS.HERB, 5)], gold=9999)
    assert plan.is_empty() and plan.stop == RS.NO_SLOT
    assert "袋がいっぱい" in plan.summary()


@needs_rom
def test_空き枠より多くは買わない():
    party = [_who("アリス", *range(RS.ITEM_SLOTS - 2))]      # ★空き 2
    plan = RS.build_plan(party, SHOP, [(RS.HERB, 5)], gold=9999)
    assert plan.total_buy == 2, [(l.name, l.buy) for l in plan.lines]


@needs_rom
def test_1回の上限を超えて買わない():
    party = [_who(str(i)) for i in range(4)]                 # ★空き 32
    plan = RS.build_plan(party, SHOP, [(RS.HERB, 99)], gold=10 ** 6)
    assert plan.total_buy == RS.MAX_PURCHASES


def test_補充リストが空なら止まる():
    plan = RS.build_plan([_who("アリス")], SHOP, [], gold=1000)
    assert plan.is_empty() and plan.stop == RS.NO_WANTS
    assert "決まっていません" in plan.summary()


def test_目標0は無視する():
    plan = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 0)], gold=1000)
    assert plan.is_empty() and plan.stop == RS.NO_WANTS


def test_戦闘中は何もしない():
    plan = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 5)], gold=1000, in_battle=True)
    assert plan.is_empty() and plan.stop == RS.IN_BATTLE
    assert "戦闘中" in plan.summary()


def test_想定外の値でも落ちない():
    """⚠ Lua から欠けた値が来ても、★例外にしない。"""
    party = [{"name": "アリス", "inventory": [None, "x", E, E, E, E, E, E]}, None]
    plan = RS.build_plan(party, SHOP, [(RS.HERB, 1)], gold=None or 0)
    assert plan.is_empty(), plan.lines
    assert RS.count_have(party, RS.HERB) == 0


# ======================================================================
# ★1 行サマリー（RX3-0110 / ⚠ 生の値を人へ出さない）
# ======================================================================
@needs_rom
def test_買う計画は1行で出る():
    plan = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 2)], gold=1000)
    line = plan.summary()
    assert "やくそう 2個" in line and "G）" in line


def test_サマリーに内部の値を混ぜない():
    """⚠⚠ `key=value` / `0x1F` / `{...}` を人向けの本文へ入れない。"""
    from dq3 import action_log as AL

    for plan in (RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 2)], gold=1000),
                 RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 2)], gold=0),
                 RS.build_plan([_who("アリス")], SHOP, [], gold=0)):
        got = plan.as_summary()
        assert AL.is_user_safe(got.message), got.message
        assert got.action == "restock"
        # ★内部の値は Technical Log 側（⚠ 人へは渡さない）
        assert "stop" in got.detail


@needs_rom
def test_買えなければ中断ではなく停止():
    """⚠ 「買えない」は失敗ではありません（★ゲームの状態）。"""
    from dq3 import action_log as AL

    stopped = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 5)], gold=0)
    assert stopped.status() == AL.CANCELLED
    assert stopped.as_summary().status_label == "停止"

    partial = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 5)], gold=20)
    assert partial.status() == AL.PARTIAL

    done = RS.build_plan([_who("アリス")], SHOP, [(RS.HERB, 2)], gold=1000)
    assert done.status() == AL.SUCCESS


# ======================================================================
# ⚠ ROM に聞いて確かめる（★名前を書き写した ID が合っているか）
# ======================================================================
def test_道具のIDがROMと合っている():
    """⚠⚠ ID を手で書き写しています。★合っているかは ROM に聞きます。"""
    from dq3.knowledge import item_info as II

    if not II.available():
        pytest.skip("⚠ ROM が読めない環境")
    for item_id, name in ((RS.HERB, "やくそう"), (RS.ANTIDOTE, "どくけしそう"),
                          (RS.HOLY_WATER, "せいすい"), (RS.WING, "キメラのつばさ")):
        got = II.info(item_id)
        assert got is not None and got.name == name, (item_id, got and got.name)
        assert got.category == "item", "⚠ v0 は消耗品だけ"


def test_既定の目標は消耗品だけ():
    from dq3.knowledge import item_info as II

    if not II.available():
        pytest.skip("⚠ ROM が読めない環境")
    for item_id, want in RS.DEFAULT_WANTS:
        assert want > 0
        assert II.info(item_id).category == "item", "⚠⚠ 装備品が既定に入っている"


def test_本物の店の品揃えで計画できる():
    """★ROM の実際の品揃えで 1 本通す（⚠ 作り物の店だけで満足しない）。"""
    from dq3.knowledge import item_info as II

    if not II.available():
        pytest.skip("⚠ ROM が読めない環境")
    lists = [row for row in II.shop_lists() if RS.HERB in row]
    assert lists, "⚠ やくそうを置く店が 1 つも無い"
    plan = RS.build_plan([_who("アリス")], lists[0], [(RS.HERB, 3)], gold=1000)
    assert plan.total_buy == 3 and plan.lines[0].name == "やくそう"


# ======================================================================
# ★実機への頼みごと（RX3-0119 / 2026-09-08）
# ======================================================================
#
# ⚠ Lua は文字コード表を持ちません。★語の**タイル列**を渡し、
#   ⚠ Lua は画面から探してその行へ寄せます（★行番号を計算しない）。

def _party(*bags):
    return [{"name": "p%d" % (i + 1), "inventory": list(b) + [E] * (RS.ITEM_SLOTS - len(b))}
            for i, b in enumerate(bags)]


@needs_rom
def test_頼みごとにタイル列を載せる():
    party = _party([1, 2, 3, 4, 5, 6, 7, 8], [1])
    plan = RS.build_plan(party, SHOP, [(RS.HERB, 2)], gold=1000)
    got = RS.to_params(plan, party)
    assert got["items"].startswith("2E12190D:2:"), got["items"]
    assert got["carrier"] == "1", "⚠ 空きが最も多い人でない"


def test_タイル列はROMの窓の定義と一致する():
    """★★ ⚠⚠ **ROM で裏を取る**（★推測で並べない）。

    ★`$0E:$9BDC` の窓の定義に入っているバイト列と、
    ⚠ Python が組んだタイル列が**同じ**であること。
    """
    rom = ROOT / "input" / "Dragon Quest 3 (J).nes"
    if not rom.exists():
        pytest.skip("⚠ ROM が読めない環境")
    prg = rom.read_bytes()[16:]

    def entry(index):
        off = 0x39BDC + index * 2
        cpu = prg[off] | (prg[off + 1] << 8)
        return prg[14 * 0x4000 + (cpu - 0x8000):14 * 0x4000 + (cpu - 0x8000) + 16]

    party = _party([1], [1])
    plan = RS.build_plan(party, SHOP, [(RS.HERB, 1)], gold=1000)
    got = RS.to_params(plan, party)
    # ★かいにきた（窓 0x16）/ はい・いいえ（窓 0x1D）
    assert entry(0x16)[6:11].hex().upper() == got["trade"], entry(0x16).hex()
    yes_no = entry(0x1D)
    assert yes_no[6:8].hex().upper() == got["yes"], yes_no.hex()
    assert yes_no[9:12].hex().upper() == got["no"], yes_no.hex()


def test_品名のタイル列はROMの名前から作る():
    from dq3.knowledge import item_info as II

    if not II.available():
        pytest.skip("⚠ ROM が読めない環境")
    party = _party([1], [1])
    plan = RS.build_plan(party, SHOP, [(RS.ANTIDOTE, 1)], gold=1000)
    got = RS.to_params(plan, party)
    from dq3.phase0.generate_lua import tile_bytes

    want = "".join("%02X" % b for b in tile_bytes(II.info(RS.ANTIDOTE).name,
                                                  RS._charset()))
    assert got["items"].startswith(want + ":"), got["items"]


@needs_rom
def test_持ち主を渡さなければ空きが多い人():
    party = _party([1, 2, 3], [1], [])
    plan = RS.build_plan(party, SHOP, [(RS.HERB, 1)], gold=1000)
    assert RS.to_params(plan, party)["carrier"] == "2"
    assert RS.to_params(plan, party, carrier_pos=0)["carrier"] == "0"


# ======================================================================
# ★1 個ごとに持ち主を選び直す（RX3-0202 / 2026-09-12）
# ======================================================================
#
# > 「save8 補充で誰かの持ち物がいっぱいな時の対応がない。
# >   DQ2のような対応が必要（平均的に所持）」
#
# ⚠ 以前は 1 人に全部を持たせ、★その人が満杯になると実機が「もてない」と聞き返した。

def _save8():
    """★save8 の空き: あかり 2 / ハンソロ 3 / エルシト 4 / ロミオ 0。"""
    return [_who("あかり", *range(6)), _who("ハンソロ", *range(5)),
            _who("エルシト", *range(4)), _who("ロミオ", *range(8))]


def test_save8は1個ごとに空きが最も多い人へ():
    party = _save8()
    assert [RS.free_slots([m]) for m in party] == [2, 3, 4, 0], "⚠ この検査の前提が崩れている"
    got = RS.carriers(party, 6)
    assert [party[i]["name"] for i in got] == [
        "エルシト", "ハンソロ", "エルシト", "あかり", "ハンソロ", "エルシト"], got


def test_満杯の人には持たせない():
    party = _save8()
    got = RS.carriers(party, 9)                      # ★空きの合計ぶん
    assert 3 not in got, "⚠⚠ 満杯のロミオに持たせた: %s" % got
    assert len(got) == 9
    # ⚠ 先頭が満杯でも、★先頭を選ばない
    party = [_who("アリス", *range(RS.ITEM_SLOTS)), _who("ボブ", 1)]
    assert RS.carriers(party, 3) == [1, 1, 1]


def test_同じ空きなら並びの早い人から順に回る():
    party = [_who("アリス", 1), _who("ボブ", 1), _who("カイ", 1)]
    assert RS.carriers(party, 4) == [0, 1, 2, 0]


def test_同じ空きなら生きている人():
    """★DQ2 と同じ（⚠ 死んでいる人に回復の道具を預けない）。★分かるときだけ使う。"""
    dead, live = _who("アリス", 1), _who("ボブ", 1)
    dead["alive"], live["alive"] = False, True
    assert RS.carriers([dead, live], 1) == [1]
    dead, live = _who("アリス", 1), _who("ボブ", 1)
    dead["hp"], live["hp"] = 0, 12
    assert RS.carriers([dead, live], 2) == [1, 0], "⚠ 空きの多さより生死を優先した"
    # ⚠ 生死が分からなければ並び順（★推測で決めない）
    assert RS.carriers([_who("アリス", 1), _who("ボブ", 1)], 1) == [0]


@needs_rom
def test_全員満杯なら持ち主の列は空():
    full = [_who("アリス", *range(RS.ITEM_SLOTS)), _who("ボブ", *range(RS.ITEM_SLOTS))]
    assert RS.carriers(full, 3) == []
    assert RS.carriers(full, 0) == [] and RS.carriers(None, 3) == []
    plan = RS.build_plan(full, SHOP, [(RS.HERB, 3)], gold=9999)
    assert plan.is_empty() and plan.stop == RS.NO_SLOT


@needs_rom
def test_持ち主の列は買う数と同じ長さ():
    """⚠⚠ 列が短いと、★足りないぶんを誰に持たせるか Lua が迷う。"""
    party = _save8()
    for want in (1, 6, 9, 12):
        plan = RS.build_plan(party, SHOP, [(RS.HERB, want)], gold=10 ** 6)
        got = RS.to_params(plan, party)
        order = got["carriers"].split(",")
        assert len(order) == plan.total_buy == min(want, 9), (want, got["carriers"])
        assert got["carrier"] == order[0], "⚠ carrier は列の先頭（★古い Lua 向け）"
        assert "3" not in order, "⚠⚠ 満杯のロミオが列に居る"


@needs_rom
def test_頼みごとに持ち主の列と満杯の語を載せる():
    party = _save8()
    plan = RS.build_plan(party, SHOP, [(RS.HERB, 6)], gold=1000)
    got = RS.to_params(plan, party)
    assert got["carriers"] == "2,1,2,0,1,2", got["carriers"]
    assert got["full"], "⚠ 「もてない」のタイル列が無い（★聞き返されても答えられない）"
    # ⚠ 名指ししたときは列を送らない（★Lua は carrier を使い、満杯なら選び直す）
    named = RS.to_params(plan, party, carrier_pos=1)
    assert named["carrier"] == "1" and named["carriers"] == ""


def test_頼みごとは製品の一覧にある():
    """⚠ 頼みごとの名前を増やしたら、★画面側の一覧にも入れる。"""
    from dq3.ui.commands import ACTIONS

    assert "restock" in ACTIONS and "restock_stop" in ACTIONS
