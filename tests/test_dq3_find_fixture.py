"""持ち物で savestate を探す道具（RX3-0401 / 2026-09-23）。

```text
A  居ない枠を読まない（★hp_max 0 は「ひのきのぼう を持っている」に見える）
B  装備の bit と空き（0xFF）を正しく外す
C  使える職業かどうかを roles.lua と**同じ式**で決める
D  「持っているだけ」の人を usable に数えない
E  読めないこと（敵の強さ・ターン数）を点に入れない
F  ⚠⚠ 0 件を**通過にしない**（★条件と探した数を出す）
G  同じ場面の世代をまとめる
```

⚠ 本物の savestate は使いません（★撮り直されると赤くなる / RX3-0028）。
★作り物の RAM を、**製品と同じ profile の番地**へ置いて確かめます。
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dq3_find_fixture as FF                               # noqa: E402

#: ★作り物の道具（⚠ ROM が無い環境でも回る。★id は ROM から引いた実際の値と同じ形）
TABLE = {
    80: {"id": 80, "name": "けんじゃのいし", "kind": "heal", "spell": "ベホマラー",
         "use_mask": None, "consumed": False},
    58: {"id": 58, "name": "ちからのたて", "kind": "heal", "spell": "ベホイミ",
         "use_mask": 0b00010001, "consumed": False},       # ★勇者(0) と 戦士(4) だけ
    12: {"id": 12, "name": "いなづまのけん", "kind": "attack", "spell": "ベギラマ",
         "use_mask": 0b00010001, "consumed": False},
}


def _profile() -> dict:
    path = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
    return json.loads(path.read_text(encoding="utf-8"))["runtime"]["party"]


def make_ram(members) -> bytes:
    """★`members` = `[(class_id, level, hp, hp_max, mp, [持ち物 …]), …]` → 2048 バイト。"""
    p = _profile()
    ram = bytearray(2048)

    def at(key) -> int:
        return int(str(p[key]), 16)

    for i, row in enumerate(members):
        class_id, level, hp, hp_max, mp, items = row
        ram[at("class_gender") + i] = class_id
        ram[at("level") + i] = level
        for key, value in (("hp_current", hp), ("hp_max", hp_max),
                           ("mp_current", mp), ("mp_max", mp)):
            ram[at(key) + i * 2] = value & 0xFF
            ram[at(key) + i * 2 + 1] = value >> 8
        base = at("items") + i * int(p["item_slots"])
        for s in range(int(p["item_slots"])):
            ram[base + s] = 0xFF                           # ★まず全部 空き
        for s, (item_id, equipped) in enumerate(items):
            ram[base + s] = item_id | (0x80 if equipped else 0)
    return bytes(ram)


def candidate(members, scene=None) -> dict:
    """★`inspect` が返す形を、ROM 無しで組み立てる。"""
    party = FF.party_of(make_ram(members))
    for m in party:
        m["holds"] = []
        for it in m["items"]:
            row = TABLE.get(it["id"])
            if row is None:
                continue
            m["holds"].append({**row, "equipped": it["equipped"],
                               "usable": FF.usable_by(row["use_mask"], m["class_id"])})
    return {"path": "作り物", "pool": "test", "mtime": 0.0, "party": party,
            "scene": scene if scene is not None else {"safe_to_walk": True, "party_alive": True,
                                                      "world_map": True}}


# --- ★Case A / B -----------------------------------------------------------

def test_A_居ない枠は読まない():
    ram = make_ram([(0, 40, 300, 350, 100, [(80, False)]),
                    (4, 38, 300, 0, 0, [(58, False)])])    # ⚠ hp_max 0 = 居ない
    got = FF.party_of(ram)
    assert [m["slot"] for m in got] == [1]
    assert got[0]["class"] == "勇者" and got[0]["level"] == 40


def test_B_装備と空きを見分ける():
    ram = make_ram([(4, 38, 300, 350, 60, [(12, True), (58, False)])])
    items = FF.party_of(ram)[0]["items"]
    assert items == [{"id": 12, "equipped": True}, {"id": 58, "equipped": False}]
    assert len(items) == 2                                 # ⚠ 0xFF の枠は入らない


# --- ★Case C / D -----------------------------------------------------------

def test_C_使える職業の式はroles_luaと同じ():
    # ★`roles.lua`: mask == nil or floor(mask / 2^(cls % 8)) % 2 == 1
    assert FF.usable_by(None, 1) is True                   # ★表を引かない品は誰でも
    assert FF.usable_by(0b00010001, 0) is True             # ★勇者
    assert FF.usable_by(0b00010001, 4) is True             # ★戦士
    assert FF.usable_by(0b00010001, 1) is False            # ⚠ 魔法使いは使えない
    assert FF.usable_by(0b00010001, None) is None          # ⚠ 「分からない」（★False にしない）


def test_D_持っているだけの人はusableに数えない():
    cand = candidate([(1, 40, 200, 220, 180, [(58, False)]),    # ⚠ 魔法使いが たて を持つ
                      (4, 38, 300, 350, 60, [(80, False)])])    # ★戦士が 石 を持つ
    assert FF.holders(cand, 58) == [1]
    assert FF.holders(cand, 58, usable_only=True) == []    # ⚠⚠ ここが「持っているだけ」
    assert FF.holders(cand, 80, usable_only=True) == [2]   # ★石は誰でも使える


# --- ★Case E ---------------------------------------------------------------

def test_E_読めないものを点に入れない():
    # ⚠ 依頼者 §6 の D/E/F（敵が何ターンで消えるか 等）は savestate から読めない。
    #   ★点の内訳に混ぜない（★推測を順位にしない）。
    labels = [name for name, _points in FF.SCORE_RULES]
    assert not [x for x in labels if "ターン" in x or "敵" in x]
    assert [x for x in labels if x.startswith("A ")]       # ★読めるものは入っている


def test_E_石を持つほうが上に来る():
    kinds = {80: "heal", 58: "heal"}
    want = {80: "けんじゃのいし", 58: "ちからのたて"}
    with_stone = candidate([(3, 40, 200, 260, 180, [(80, False)])])
    without = candidate([(3, 40, 200, 260, 180, [])])
    assert FF.score(with_stone, want, kinds)[0] > FF.score(without, want, kinds)[0]


# --- ★Case F ---------------------------------------------------------------

def test_F_0件を通過にしない(capsys, monkeypatch):
    monkeypatch.setattr(FF, "POOLS", (("なし", "work/no-such-dir", "*"),))
    monkeypatch.setattr(FF, "battle_items", lambda rom_path=None: TABLE)
    monkeypatch.setattr(FF, "item_ids_for", lambda words, rom_path=None: {80: "けんじゃのいし"})
    assert FF.main(["--item", "けんじゃのいし"]) == 0
    out = capsys.readouterr().out
    assert "0 件" in out and "★探した: 0 本" in out        # ⚠ 探した数も出す
    assert "★候補 0 件" in out


# --- ★Case G ---------------------------------------------------------------

def test_G_同じ場面はまとまる():
    scene = {"safe_to_walk": True, "party_alive": True, "world_map": True,
             "map_id": 8, "world_pos": [77, 59]}
    one = candidate([(3, 40, 200, 260, 180, [(80, False)])], scene)
    two = candidate([(3, 40, 200, 260, 180, [(80, False)])], scene)
    other = candidate([(3, 41, 200, 260, 180, [(80, False)])], scene)
    assert FF.signature(one) == FF.signature(two)
    assert FF.signature(one) != FF.signature(other)        # ⚠ Lv が違えば別の場面


# --- ★Case H（2026-09-23 に踏んだ穴）----------------------------------------

def test_H_種類が分からない場所を落とさない(monkeypatch):
    """⚠⚠ 「分からない」を「遭遇が無い」と同じにしない。

    ★実際に踏んだ形: `location_master` は 23 行で**全部 unknown**。
    ⚠ `--encounter-only` が町も洞窟も区別できないまま**全部落とし**、
    ★「世界地図しか候補が無い」ように見えました。
    """
    monkeypatch.setattr(FF, "location_types", lambda: {})
    assert FF.encounters_here({"world_map": False, "map_id": 200}) is None
    assert FF.encounters_here({"world_map": True}) is True


def test_H_町と分かっている場所だけ落とす(monkeypatch):
    monkeypatch.setattr(FF, "location_types", lambda: {5: "town", 200: "cave"})
    assert FF.encounters_here({"world_map": False, "map_id": 5}) is False
    assert FF.encounters_here({"world_map": False, "map_id": 200}) is True


def test_H_効かない絞り込みだと言う(capsys, monkeypatch):
    monkeypatch.setattr(FF, "POOLS", (("なし", "work/no-such-dir", "*"),))
    monkeypatch.setattr(FF, "battle_items", lambda rom_path=None: TABLE)
    monkeypatch.setattr(FF, "item_ids_for", lambda words, rom_path=None: {80: "けんじゃのいし"})
    monkeypatch.setattr(FF, "types_known", lambda: 0)
    FF.main(["--item", "けんじゃのいし", "--encounter-only"])
    assert "何も外していません" in capsys.readouterr().out


# --- ★Case I（2026-09-23 に実機で踏んだ / RX3-0406）--------------------------

def test_I_袋の空きを数える():
    """⚠⚠ 空き 0 の fixture は、無人の run ではドロップのたびに止まります。

    ★2026-09-23: 全員 空き 0 の savestate を benchmark に選び、
    ⚠ 「なにか すてますか?」の一覧に A を 41 回押して走行が止まりました。
    """
    cand = candidate([(0, 45, 400, 400, 140, [(80, False)] * 8),   # ★8 枠すべて埋まっている
                      (4, 42, 380, 380, 74, [(58, False)])])
    assert [m["free"] for m in cand["party"]] == [0, 7]
    assert FF.free_total(cand) == 7


def test_I_空きが無いものを外せる():
    labels = [name for name, _points in FF.SCORE_RULES]
    assert "袋に空きがある" in labels                      # ★点の内訳に入っている
    full = candidate([(0, 45, 400, 400, 140, [(80, False)] * 8)])
    assert FF.free_total(full) == 0


# --- ★Case J: 敵の名前で探す（RX3-0387 の材料）------------------------------

def test_J_戦闘中でなければ敵で拾わない():
    # ⚠ 戦闘の外の `enemy_*` は**前の戦闘の値**（★RX3-0226 と同じ注意）
    assert FF.enemies_here({"in_battle": False, "enemy_kind": ["ヒドラ"]}, ("ヒドラ",)) is False
    assert FF.enemies_here({"in_battle": True, "enemy_kind": ["ヒドラ"]}, ("ヒドラ",)) is True


def test_J_指定した敵が全部いること():
    scene = {"in_battle": True, "enemy_kind": ["ヒドラ", "おおめだま"]}
    assert FF.enemies_here(scene, ("ヒドラ", "おおめだま")) is True
    assert FF.enemies_here(scene, ("ヒドラ", "ソードイド")) is False
