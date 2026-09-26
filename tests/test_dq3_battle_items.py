"""戦闘で使う道具の表（RX3-0213 → RX3-0346 / 2026-09-21）。

⚠⚠ 依頼者「力のたてや、けんじゃのいし（未取得）を … つかう」。

## ★何が起きていたか

```python
# dq3/battle_ai/generate.py（★直す前）
if spell is None or spell.get("kind") != "attack" or meta is None:
    continue                    # ⚠ attack 以外は表に入れない
```

★`attack` 以外を**全部捨てて**いました。⚠ 回復の道具は AI から存在しませんでした。

## ★ROM の事実（`IM.battle_effects` を全件引いた）

```text
id 58  ちからのたて    ベホイミ    heal  ally_single  ⚠ consumed 無し（★減らない）
id 80  けんじゃのいし  ベホマラー  heal  self_party   ⚠ consumed 無し（★減らない）
```

⚠ ここは**形**だけを見ます（★実際に使うかは `dq3_ai_test.lua` の SI 系）。
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "input" / "Dragon Quest 3 (J).nes"
needs_rom = pytest.mark.skipif(not ROM.exists(), reason="⚠ ROM が読めない環境")

SHIELD, STONE = 58, 80                    #: ★ちからのたて / けんじゃのいし


@pytest.fixture(scope="module")
def items() -> dict:
    """★生成物の道具の表（⚠ 本番の `work/generated` には書かない）。"""
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S

    data = G.build(S.BattleAiSettings(), [], rom_path=ROM)
    assert data.get("ok"), data.get("error")
    return data["items"]


@needs_rom
def test_回復の道具が表に入る(items):
    """⚠⚠ これが依頼者の症状（★一度も使わなかった）。"""
    got = {r["id"]: r for r in items["heal_items"]}
    assert SHIELD in got, "⚠⚠ ちからのたて が表に無い（★AI から存在しない）"
    assert STONE in got, "⚠⚠ けんじゃのいし が表に無い"
    assert got[SHIELD]["target"] == "ally_single", got[SHIELD]
    assert got[STONE]["target"] == "self_party", got[STONE]


@needs_rom
def test_攻撃の道具は今までどおり(items):
    """⚠ 広げたせいで攻撃の道具が減っていないこと（★RX3-0213 を壊さない）。"""
    kinds = {r["id"] for r in items["attack"]}
    # ★まどうしのつえ(7) / いなづまのけん(26) / いかづちのつえ(27) / おうじゃのけん(28)
    for item_id in (7, 26, 27, 28):
        assert item_id in kinds, "⚠ 攻撃の道具 %d が落ちた" % item_id


@needs_rom
def test_攻撃と回復は混ざらない(items):
    """⚠ 同じ品が両方に出ない（★どちらの手として押すかが決まらない）。"""
    a = {r["id"] for r in items["attack"]}
    h = {r["id"] for r in items["heal_items"]}
    assert not (a & h), "⚠⚠ 両方に出ている品がある: %s" % sorted(a & h)


@needs_rom
def test_減る品は入れない(items):
    """⚠⚠ 在庫を黙って減らさない（★やくそう・せかいじゅのは は `consumed`）。

    ★`やくそう`(101) は別の道（`items.herb`）で扱います。
    """
    from dq3rom import item_meta as IM
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    consumed = {r.item_id for r in IM.build(prg) if "consumed" in r.flags}
    assert consumed, "⚠ 前提が崩れた（★減る品が 1 つも無い）"
    for key in ("attack", "heal_items"):
        got = {r["id"] for r in items[key]}
        assert not (got & consumed), (
            "⚠⚠ %s に減る品が入った: %s" % (key, sorted(got & consumed)))
        for r in items[key]:
            assert r["consumed"] is False, r


@needs_rom
def test_減る品の歯止めは本当に効く():
    """⚠⚠ **いまの ROM では、この歯止めは一度も発火しません。**

    ★`attack` / `heal` の道具に、⚠ `consumed` の品が**たまたま 1 つも無い**ためです
    （★どくがのこな は `instant`、せかいじゅのは は `revive`）。
    → ⚠ 上の `test_減る品は入れない` は「**通っていないだけ**」でも緑になります
      （★`project_retroux_zero_findings_means_untested` と同じ形）。

    ★そこで、⚠ **消える品が attack になった場合**を作って、歯止めが鳴ることを見ます。
    ★`instant` / `cure` を足すときに、⚠ この歯止めが要るからです。
    """
    from dq3.battle_ai import generate as G
    from dq3.battle_ai.generate import _battle_items
    from dq3rom import item_meta as IM
    from dq3rom import profile as P
    from dq3.knowledge import spell_info as SI
    from retroux.core.text import Charset
    import json

    prg = P.load_and_identify(ROM).rom.prg
    profile = json.loads((ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
                         .read_text(encoding="utf-8"))
    charset = Charset(profile["text"]).table
    spells = {int(k): dict(v) for k, v in SI.lua_table(ROM)["spells"].items()}

    effects = IM.battle_effects(prg)
    flags = {r.item_id: r.flags for r in IM.build(prg)}
    doomed = [i for i in effects if "consumed" in flags.get(i, ())]
    assert doomed, "⚠ 前提が崩れた（★戦闘で使えて消える品が無い）"

    # ⚠ その品の効果を「攻撃呪文」だと**偽って**渡す（★ROM は書き換えない）
    faked = dict(spells)
    for item_id in doomed:
        sid = int(effects[item_id])
        row = dict(faked.get(sid) or {})
        row["kind"] = "attack"
        row.setdefault("target", "enemy_group")
        faked[sid] = row
    got = _battle_items(prg, faked, ROM, charset)
    ids = {r["id"] for r in got["attack"]} | {r["id"] for r in got["heal"]}
    assert not (ids & set(doomed)), (
        "⚠⚠ 消える品が表に入った（★歯止めが効いていない）: %s" % sorted(ids & set(doomed)))
    assert G.BATTLE_ITEM_KINDS == ("attack", "heal"), "⚠ 入れる効き方が変わった"


@needs_rom
def test_対象外の効き方は入れない(items):
    """⚠ `instant` / `debuff` / `buff` / `cure` はまだ入れない（★RX3-0346 の Scope）。

    ★ゆうわくのけん（メダパニ）/ くさなぎのけん（ルカナン）/ たいようのいし（シャナク）。
    """
    got = {r["id"] for r in items["attack"]} | {r["id"] for r in items["heal_items"]}
    for item_id, why in ((22, "ゆうわくのけん/メダパニ"), (29, "くさなぎのけん/ルカナン"),
                         (117, "たいようのいし/シャナク"), (16, "あまぐものつえ/マホトーン")):
        assert item_id not in got, "⚠ 対象外の効き方が入った: %s" % why


@pytest.fixture(scope="module")
def enemies() -> dict:
    """★敵の表（⚠ 本番の `work/generated` には書かない）。"""
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S

    data = G.build(S.BattleAiSettings(), [], rom_path=ROM)
    assert data.get("ok"), data.get("error")
    return data["enemies"]


@needs_rom
def test_敵の行動枠が8つ出る(enemies):
    """★Enemy Action Model v1 の入力（RX3-0359）。⚠ 139 体すべて 8 枠。"""
    assert len(enemies) == 139, len(enemies)
    for eid, row in enemies.items():
        acts = row.get("acts")
        assert acts is not None, "⚠ %d に acts が無い" % eid
        assert len(acts["slots"]) == 8, "⚠ %d の枠が %d" % (eid, len(acts["slots"]))
        assert acts["select_mode"] in (0, 1, 2, 3), acts["select_mode"]
        assert acts["gating_mode"] in (0, 1, 2, 3), acts["gating_mode"]


@needs_rom
def test_呪文の枠にMPコストが入る(enemies):
    """⚠⚠ MP コストが 1 件も入らないと、★成立条件が**永久に鳴りません**。

    ★表の場所は `_b4_s28` の命令から逆算しています（⚠ 番地を写していない）。
    """
    spells = [s for row in enemies.values() for s in row["acts"]["slots"]
              if 0x13 <= s["move_id"] <= 0x3A]
    assert spells, "⚠ 前提が崩れた（★呪文の枠が 1 つも無い）"
    priced = [s for s in spells if s["mp"] > 0]
    assert len(priced) >= len(spells) * 0.8, (
        "⚠⚠ MP コストが入っていない枠が多すぎる: %d / %d" % (len(priced), len(spells)))
    # ★呪文でない枠には MP を付けない
    for row in enemies.values():
        for s in row["acts"]["slots"]:
            if not (0x13 <= s["move_id"] <= 0x3A):
                assert s["mp"] == 0, "⚠ 呪文でない枠に MP が付いた: %s" % s


@needs_rom
def test_MPコスト表はROMから逆算する():
    """⚠⚠ 番地を書き写していないこと（★版が変われば命令ごと動く）。"""
    from dq3.battle_ai import generate as G
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    got = G._enemy_mp_costs(prg)
    assert len(got) == 40, "⚠ 40 件でない: %d" % len(got)
    # ★RX3-0358 で読み出した値（⚠ ここが変わったら ROM か逆算が変わっている）
    assert got[0] == 2, got[:4]            # ★move $13
    assert got[0x35 - 0x13] == 62, got     # ★move $35（ベホマラー級）
    src = (ROOT / "dq3" / "battle_ai" / "generate.py").read_text(encoding="utf-8")
    body = src.split(chr(34) * 3, 2)[2]
    assert "0xBE21" not in body and "$BE21" not in body, (
        "⚠⚠ 表の番地を書き写している（★命令から逆算すること）")


@needs_rom
def test_成立条件の印が付く(enemies):
    """★回復（move $31-$3A）と蘇生（$2F,$30）に印が要る（RX3-0358）。"""
    heal = [s for row in enemies.values() for s in row["acts"]["slots"]
            if 0x31 <= s["move_id"] <= 0x3A]
    assert heal, "⚠ 回復の枠が 1 つも無い"
    assert all(s["needs_heal_target"] for s in heal), "⚠ 回復に印が無い枠がある"
    rev = [s for row in enemies.values() for s in row["acts"]["slots"]
           if s["move_id"] in (0x2F, 0x30)]
    assert all(s["needs_dead_target"] for s in rev), "⚠ 蘇生に印が無い枠がある"
    # ⚠ 物理には印を付けない
    phys = [s for row in enemies.values() for s in row["acts"]["slots"]
            if s["category"] == "attack"]
    assert not any(s["needs_heal_target"] or s["needs_dead_target"] for s in phys)


@needs_rom
def test_敵の呪文は敵の表から引く(enemies):
    """⚠⚠ 味方の呪文表を敵に流用しないこと（RX3-0361 / 2026-09-22）。

    ★ROM には敵専用のダメージ表が 1 本あり（`DAMAGE_RANGE_TABLE` / bank4 $B56A）、
      ⚠ **呪文 0x13-0x1E とブレス 0x0A-0x0F が同じ 18 件**に入っています。
      ★読む命令も 1 本だけ（`_DAMAGE_READER`）。

    ```text
    例  move 0x19（イオナズン）  ★敵 60..79 → 69   ⚠ 味方表 120..160 → 140
    ```

    ⚠ 実測: 88 枠すべてが 1.22 倍 〜 2.01 倍に過大でした。
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    # ★表の端（⚠ ここが変われば ROM か索引が変わっている）
    assert ED.spell_damage(prg, 0x13) == (7, 11), ED.spell_damage(prg, 0x13)
    assert ED.spell_damage(prg, 0x19) == (60, 79), ED.spell_damage(prg, 0x19)
    assert ED.spell_damage(prg, 0x1E) == (30, 61), ED.spell_damage(prg, 0x1E)
    # ⚠ 呪文でない ID は None（★ブレスは `breath_damage` の担当）
    assert ED.spell_damage(prg, 0x12) is None
    assert ED.spell_damage(prg, 0x1F) is None
    assert ED.spell_damage(prg, 0x0B) is None

    # ⚠⚠ 生成物が**敵の表の値**になっている（★味方の表ではない）
    slots = [s for row in enemies.values() for s in row["acts"]["slots"]
             if s["category"] == "spell_damage"]
    assert slots, "⚠ 攻撃呪文の枠が 1 つも無い"
    for s in slots:
        got = ED.spell_damage(prg, s["move_id"])
        assert got is not None, "⚠ 0x13-0x1E の外に攻撃呪文がある: %#x" % s["move_id"]
        assert s["dmg"] == int((got[0] + got[1]) / 2), (
            "⚠⚠ move %#x のダメージが敵の表と違う（★味方表を引いている？）: %d vs %s"
            % (s["move_id"], s["dmg"], got))
    # ★実機で見た敵（⚠ アークマージのイオナズンは 140 ではない）
    arch = [s["dmg"] for s in enemies[119]["acts"]["slots"] if s["move_id"] == 0x19]
    assert arch and set(arch) == {69}, "⚠⚠ アークマージのイオナズンが 69 でない: %s" % arch


@needs_rom
def test_呪文の表を読む命令が合わなければ諦める():
    """⚠⚠ 黙って別の場所を読まないこと（★`breath_damage` と同じ約束）。

    ⚠ 表の番地だけを信じると、★版が違う ROM で**隣の何か**を威力として読みます。
      → ⚠⚠ 0（= 分からない）ではなく、**もっともらしい嘘**が出ます。
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = bytes(P.load_and_identify(ROM).rom.prg)
    assert ED.spell_damage(prg, 0x19) == (60, 79)
    at = prg.find(ED._DAMAGE_READER)
    assert at > 0, "⚠ 読む命令が見つからない"
    broken = prg[:at + 4] + bytes([prg[at + 4] ^ 0xFF]) + prg[at + 5:]
    assert ED.spell_damage(broken, 0x19) is None, "⚠⚠ 命令が違うのに表を信じた"
    # ⚠ 表が短くても諦める
    assert ED.spell_damage(prg[:ED.DAMAGE_RANGE_TABLE["file"] + 3], 0x19) is None


@needs_rom
def test_敵の呪文の威力は味方の呪文表と別物():
    """★「同じ値が入っているだけ」を除く（⚠ 偶然一致していないこと）。"""
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    data = G.build(S.BattleAiSettings())
    spells = data["spells"]
    diff = 0
    for move in range(ED.SPELL_DAMAGE_FIRST, ED.SPELL_DAMAGE_LAST + 1):
        enemy = ED.spell_damage(prg, move)
        sid = ED.spell_of_move(prg, move)
        row = spells.get(int(sid)) if sid is not None else None
        if enemy is None or row is None:
            continue
        party = int((row.get("base") or 0) + (row.get("delta") or 0) / 2)
        if party != int((enemy[0] + enemy[1]) / 2):
            diff += 1
    assert diff >= 10, (
        "⚠⚠ 敵の表と味方の表がほとんど同じ値 ―― 片方を引いても差が出ない。"
        "★この検査は壊れ方を捕まえられない: 違うのは %d 件" % diff)


@needs_rom
def test_敵の回復量はROMの表から(enemies):
    """★敵が 1 回で戻す HP（RX3-0363 / JP bank4 $BF94 → 索引 → (基数, 幅)）。

    ⚠⚠ **味方の呪文表ではありません**（★`RX3-0361` と同じ型の間違いを繰り返さない）。
    ★番地は命令から逆算します。
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    # ★ROM の値（⚠ ここが変われば ROM か逆算が変わっている）
    assert ED.heal_amount(prg, 0x31) == (30, 39)     # ★ホイミ
    assert ED.heal_amount(prg, 0x32) == (75, 94)     # ★ベホイミ
    assert ED.heal_amount(prg, 0x33) == "full"       # ★ベホマ
    assert ED.heal_amount(prg, 0x34) == (62, 77)     # ★ベホマラー
    assert ED.heal_amount(prg, 0x35) == "full"       # ★ベホマズン
    # ★0x36-0x3A は 0x31-0x35 と同じ行（⚠ 違うのは使う条件だけ）
    for lo, hi in ((0x31, 0x36), (0x32, 0x37), (0x33, 0x38), (0x34, 0x39), (0x35, 0x3A)):
        assert ED.heal_amount(prg, lo) == ED.heal_amount(prg, hi), (lo, hi)
    # ⚠ 回復でない ID は None
    assert ED.heal_amount(prg, 0x30) is None and ED.heal_amount(prg, 0x3B) is None
    # ★群に届くのは 4 つだけ
    multi = [m for m in range(0x31, 0x3B) if ED.heals_whole_group(m)]
    assert multi == [0x34, 0x35, 0x39, 0x3A], multi

    # ⚠⚠ 生成物に入っている（★入れ忘れると Lua が 0 と見る）
    heal = [s for row in enemies.values() for s in row["acts"]["slots"]
            if s["category"] == "heal"]
    assert heal, "⚠ 回復の枠が 1 つも無い"
    for s in heal:
        got = ED.heal_amount(prg, s["move_id"])
        if got == "full":
            assert s.get("heal_full") is True, s
        else:
            assert s.get("heal_hp") == int((got[0] + got[1]) / 2), s


@needs_rom
def test_回復量の表を読む命令が合わなければ諦める():
    """⚠⚠ 黙って別の場所を読まないこと（★`breath_damage` と同じ約束）。"""
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = bytes(P.load_and_identify(ROM).rom.prg)
    assert ED.heal_amount(prg, 0x32) == (75, 94)
    at = prg.find(bytes([0xA6, 0x51, 0xBD, 0x58, 0x05, 0x38, 0xE9, 0x31, 0xAA, 0xBD]))
    assert at > 0, "⚠ 読む命令が見つからない"
    broken = prg[:at + 3] + bytes([prg[at + 3] ^ 0xFF]) + prg[at + 4:]
    assert ED.heal_amount(broken, 0x32) is None, "⚠⚠ 命令が違うのに表を信じた"
    # ⚠⚠ 2 か所あっても諦める（★どちらが本物か言えない）
    hit = ED._HEAL_READER.search(ED._battle_bank(prg))
    assert hit is not None
    code = ED._battle_bank(prg)[hit.start():hit.end()]
    at2 = 0x10010   # ★bank 4 の中（⚠ 外に置くと数えません）
    twice = prg[:at2] + code + prg[at2 + len(code):]
    assert ED.heal_amount(twice, 0x32) is None, (
        "⚠⚠ 読む命令が 2 か所あるのに先頭を信じた")


@needs_rom
def test_仲間呼びは場に居る種類だけ(enemies):
    """⚠⚠ ROM が「もう場に居る種類」しか呼ばせません（★JP bank4 $8E1C）。

    ```text
    A2 03 / BD B5 07 / C5 45 / F0 05 / CA / 10 F6 / 18 60
       ★群は 4 つ。⚠ 見つからなければ CLC（失敗）＝ 手番を 1 つ捨てる
    ```

    ★これを見ないと マドハンド の見立てが **27 倍**変わります
    （⚠ 実測: だいまじんが居れば 283.8 / 居なければ 10.4）。
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    assert ED.reinforce_calls_self(prg), "⚠ move 8 が自分と同じ敵を呼ぶ根拠が無い"
    assert ED.reinforce_needs_same_kind_present(prg), "⚠ 場に居る判定の命令が無い"

    calls = [s for row in enemies.values() for s in row["acts"]["slots"]
             if "calls" in s]
    assert calls, "⚠ 仲間を呼ぶ枠が 1 つも無い"
    for s in calls:
        if s["move_id"] == ED.REINFORCE_SELF_MOVE:
            assert s["calls"] == "self", s
            assert "calls_present_only" not in s, (
                "⚠⚠ 自分と同じ敵を呼ぶ枠に「場に居ること」を要求している: %s" % s)
        else:
            assert isinstance(s["calls"], int), s
            assert s.get("calls_present_only") is True, (
                "⚠⚠ 決まった敵を呼ぶ枠に条件が付いていない: %s" % s)
    # ★マドハンド（105）は自分と だいまじん（117）を呼ぶ
    mud = enemies[105]["acts"]["slots"]
    assert {s.get("calls") for s in mud if "calls" in s} == {"self", 117}


@needs_rom
def test_蘇生で戻るHPはROMから(enemies):
    """★ザオリクは全快・必ず成功／⚠ ザオラルは半分・半々（RX3-0368）。

    ```text
    BD 31 05 / 30 ?? / BD 30 05 / 10 ??   ⚠ **死んでいる敵**にだけ効く
    A5 49 / C9 21 / F0 05 / 20 ?? ?? / 10 ??   ★$21 は乱数を通らない ＝ 必ず成功
    A5 49 / C9 21 / F0 04 / 46 5A / 66 59      ★$21 はそのまま ＝ 全快
    ```

    ⚠ 戻る HP は `_bs_read_enemy_prop_HP`（★表の**最大 HP**）から作られます。
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    assert ED.revive_effect(prg, 0x30) == (1.0, 1.0), ED.revive_effect(prg, 0x30)
    assert ED.revive_effect(prg, 0x2F) == (0.5, 0.5), ED.revive_effect(prg, 0x2F)
    # ⚠ 蘇生でない ID は None
    assert ED.revive_effect(prg, 0x31) is None
    assert ED.revive_effect(prg, 0x2E) is None

    # ⚠⚠ 生成物に入っている（★入れ忘れると Lua が 0 と見る）
    rev = [s for row in enemies.values() for s in row["acts"]["slots"]
           if s.get("revives")]
    assert rev, "⚠ 蘇生の枠が 1 つも無い"
    for s in rev:
        want = ED.revive_effect(prg, s["move_id"])
        assert (s.get("revive_ratio"), s.get("revive_success")) == want, s
    # ★アークマージ（119）は 8 枠中 4 枠がザオリク
    arch = [s for s in enemies[119]["acts"]["slots"] if s.get("revives")]
    assert len(arch) == 4 and all(s["revive_ratio"] == 1.0 for s in arch)


@needs_rom
def test_蘇生の命令が合わなければ諦める():
    """⚠⚠ 黙って別の意味に読まないこと（★命令を 1 バイト壊したら None）。"""
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = bytes(P.load_and_identify(ROM).rom.prg)
    assert ED.revive_effect(prg, 0x2F) == (0.5, 0.5)
    at = prg.find(ED._REVIVE_HALF_CODE)
    assert at > 0, "⚠ 半分にする命令が見つからない"
    broken = prg[:at + 6] + bytes([prg[at + 6] ^ 0xFF]) + prg[at + 7:]
    assert ED.revive_effect(broken, 0x2F) is None, "⚠⚠ 命令が違うのに割合を信じた"
    # ⚠⚠ 2 か所あっても諦める（★どちらが本物か言えない）
    at2 = 0x10010   # ★bank 4 の中（⚠ 外に置くと数えません）
    twice = prg[:at2] + ED._REVIVE_HALF_CODE + prg[at2 + len(ED._REVIVE_HALF_CODE):]
    assert ED.revive_effect(twice, 0x2F) is None, (
        "⚠⚠ 命令が 2 か所あるのに先頭を信じた")


@needs_rom
def test_敵の枠は8体で命令から逆算する():
    """⚠⚠ `#$10` を書き写さないこと（★版が変われば命令ごと動く / RX3-0368）。

    ```text
    A2 00 / BD 30 05 / E8 / 3D 30 05 / 10 07 / E8 / E0 10 / D0 F2
       → ★16 バイト ＝ **8 体ぶん**（⚠ 1 体 2 バイト）
    ```
    """
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    assert ED.reinforce_slot_limit(prg) == 8
    # ⚠ 生成物に入っている（★入れ忘れると Lua が頭打ちしない）
    assert G.build(S.BattleAiSettings())["enemy_slots"] == 8
    # ⚠⚠ 番地でも数でもなく、★命令から逆算していること
    src = (ROOT / "dq3rom" / "enemy_detail.py").read_text(encoding="utf-8")
    at = src.find("def reinforce_slot_limit")
    body = src[at:at + 600]
    assert "return 8" not in body and "= 8" not in body, (
        "⚠⚠ 枠の数を書き写している（★命令から逆算すること）")


@needs_rom
def test_蘇生は印だけで値を付けない(enemies):
    """⚠⚠ 戻る HP が未解析です（★`RX3-0364`）。⚠ 0 と数えたことにしない。"""
    rev = [s for row in enemies.values() for s in row["acts"]["slots"]
           if s["move_id"] in (0x2F, 0x30)]
    assert rev, "⚠ 蘇生の枠が 1 つも無い"
    for s in rev:
        assert s.get("revives") is True, s
        assert "heal_hp" not in s and "heal_full" not in s, (
            "⚠⚠ 未解析の蘇生に回復量を付けている: %s" % s)


@needs_rom
def test_ダメージを出さない息は状態異常に分類する(enemies):
    """⚠⚠ 0x10 / 0x11 / 0x12 は ROM で**ダメージを 1 も出しません**（RX3-0371）。

    ★依頼者は「灼熱（0x12）がダメージ 0 なのは過小評価」と見ていましたが、
    ⚠ ROM を読むと **麻痺にするだけ**でした。→ ★ダメージの穴ではなく**分類の誤り**。

    ```text
    0x10 眠り    $9D53  B9 E1 07 / 29 08 → 09 08 / 99 E1 07   ★運試し #$60
    0x11 毒      $8EE1  BD 3D 07 / 29 20 → 09 20 / 9D 3D 07   ★運試し #$60
    0x12 麻痺    $8F2C  BD 3D 07 / 29 40 → 09 40 / 9D 3D 07   ★運試し #$20
    ```
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    assert ED.breath_status(prg, 0x10) == "sleep"
    assert ED.breath_status(prg, 0x11) == "poison"
    assert ED.breath_status(prg, 0x12) == "paralyze"
    # ⚠ ダメージの息（0x0A-0x0F）は None（★分類を上書きしない）
    for move in range(0x0A, 0x10):
        assert ED.breath_status(prg, move) is None, move

    # ⚠⚠ 生成物に **dmg 0 の magic_damage が 1 枠も無い**
    holes = [s for row in enemies.values() for s in row["acts"]["slots"]
             if s["klass"] == "magic_damage" and not s.get("dmg")]
    assert holes == [], "⚠⚠ ダメージの分からない枠が残っている: %s" % holes[:3]
    # ★3 つは status になっている
    for move in (0x10, 0x11, 0x12):
        got = [s["klass"] for row in enemies.values() for s in row["acts"]["slots"]
               if s["move_id"] == move]
        assert got and set(got) == {"status"}, (move, set(got))


@needs_rom
def test_息の分類を直してもlegacyの旗は変えない(enemies):
    """⚠⚠ 依頼者 §14「製品判断は変えず、shadow 分類のみ」。

    ★`acts.status` は legacy が読む旗（`enemy_status_threat` 1.2 が掛かる）。
    ⚠ ここが変わると**既存 AI の動きが変わります**。
    """
    for row in enemies.values():
        acts = row["acts"]
        # ★旗は `kinds`（分類を直す**前**）から作られている
        assert acts["status"] == (acts["kinds"].get("status", 0) > 0)
    # ⚠ 息だけで状態異常になる敵は、★旗が立っていない（= legacy は今までどおり）
    only_breath = [row for row in enemies.values()
                   if any(s["move_id"] in (0x10, 0x11, 0x12) for s in row["acts"]["slots"])
                   and row["acts"]["kinds"].get("status", 0) == 0]
    assert only_breath, "⚠ 前提が崩れた（★息だけの敵が居るはず）"
    for row in only_breath:
        assert row["acts"]["status"] is False, (
            "⚠⚠ legacy の旗が変わった（★動きが変わる）")


@needs_rom
def test_行動の分類表を生成物に渡す():
    """★実測ログで「何をしたか」を読むのに要ります（RX3-0371）。"""
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S

    got = G.build(S.BattleAiSettings())["move_names"]
    assert len(got) == 64
    assert got[2] == "attack" and got[0x30] == "spell_revive"
    assert got[0x12] == "breath", "⚠ ここは ROM の分類のまま（★AI の klass とは別）"


@needs_rom
def test_味方の眠りは敵とは別の表():
    """⚠⚠ 味方 `$B4EF` / 敵 `$B4F3`（★4 バイト前の**別の表**）。

    ```text
    味方 FF 80 55 20 → ★2.737 ターン
    敵   FF C0 80 40 → ★2.207 ターン（⚠ findings の既存の記述と一致）
    ```

    ⚠ 番地は**命令から逆算**します（★書き写さない）。
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    table = ED.party_sleep_table(prg)
    assert table == (0xFF, 0x80, 0x55, 0x20), table
    got = ED.sleep_turns(table)
    assert round(got, 3) == 2.737, got
    # ★敵の表で計算すると 2.207（⚠ findings の既存の記述と一致 = 式の裏取り）
    assert round(ED.sleep_turns((0xFF, 0xC0, 0x80, 0x40)), 3) == 2.207
    # ⚠⚠ 味方のほうが**長く眠る**（★取り違えたら気づきたい）
    assert got > ED.sleep_turns((0xFF, 0xC0, 0x80, 0x40))
    # ⚠ 生成物に入っている
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S

    assert G.build(S.BattleAiSettings())["party_sleep_turns"] == 2.737
    # ⚠⚠ 番地を書き写していない
    src = (ROOT / "dq3rom" / "enemy_detail.py").read_text(encoding="utf-8")
    at = src.find("def party_sleep_table")
    body = src[at:at + 500]
    assert "0xB4EF" not in body and "$B4EF" not in body, (
        "⚠⚠ 表の番地を書き写している（★命令から逆算すること）")


@needs_rom
def test_状態異常が入る確率は運で変わる():
    """★`P = (384 − 運のよさ) × 閾値 / 65536`（JP bank4 `$A917`）。

    ⚠⚠ **運を見ない式に戻さないこと**（★運 0 と運 255 で 3 倍違う）。
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    assert ED.luck_formula_ok(prg), "⚠ 式を作る命令が ROM に無い"
    # ★眠り / 毒（閾値 $60）
    assert round(ED.status_chance(0x60, 0), 3) == 0.562
    assert round(ED.status_chance(0x60, 255), 3) == 0.189
    # ★麻痺（閾値 $20）
    assert round(ED.status_chance(0x20, 0), 3) == 0.188
    # ⚠⚠ 運が上がるほど**下がる**（★運を見ていないと同じ値になる）
    rows = [ED.status_chance(0x60, l) for l in (0, 50, 100, 200, 255)]
    assert rows == sorted(rows, reverse=True), rows
    assert rows[0] > rows[-1] * 2.5, "⚠⚠ 運の効きが弱すぎる（★式が違う？）"
    # ⚠ 生成物の枠に閾値が入っている
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S

    slots = [s for row in G.build(S.BattleAiSettings())["enemies"].values()
             for s in row["acts"]["slots"] if s.get("status_kind")]
    assert slots, "⚠ 状態異常の枠が 1 つも無い"
    for s in slots:
        want = ED.status_of_move(prg, s["move_id"])
        assert want is not None, s
        assert (s["status_kind"], s["status_prob"]) == want, s
        # ★手番を奇うのは 3 つだけ（⚠ 毒・マヌーサ・マホトーンは奇わない）
        assert s.get("steals_turn") == (
            s["status_kind"] in ("sleep", "paralyze", "confuse")), s
        # ⚠ 弱めるものは**別の欄**（★手番にもダメージにも足さない）
        assert s.get("weakens") == (
            s["status_kind"] if s["status_kind"] in ("illusion", "stopspell") else None), s


@needs_rom
def test_呪文の状態異常も読める():
    """★味方へのラリホー / マホトーン / マヌーサ / メダパニ（RX3-0375）。

    ```text
    move  呪文        本体      旗             閾値
    0x22  ラリホー    $9D53    $07E1 bit3     $60   ★あまい息と**同じ本体**
    0x23  マホトーン  $9E37    $073C bit5     $60
    0x26  マヌーサ    $9EB6    $073C bit4     $A0
    0x28  メダパニ    $924F    $073D bit4     $40
    ```
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    assert ED.status_of_move(prg, 0x22) == ("sleep", 0x60)
    assert ED.status_of_move(prg, 0x23) == ("stopspell", 0x60)
    assert ED.status_of_move(prg, 0x26) == ("illusion", 0xA0)
    assert ED.status_of_move(prg, 0x28) == ("confuse", 0x40)
    # ★息も同じ口から引ける
    assert ED.status_of_move(prg, 0x10) == ("sleep", 0x60)
    assert ED.status_of_move(prg, 0x12) == ("paralyze", 0x20)
    # ⚠ まだ読めていない呪文は None（★推測で言わない）
    assert ED.status_of_move(prg, 0x29) is None      # ボミオス
    assert ED.status_of_move(prg, 0x2A) is None      # ラリホーマ系
    assert ED.status_of_move(prg, 0x02) is None      # ★ただの攻撃


@needs_rom
def test_呪文の状態異常も命令が合わなければ諦める():
    """⚠⚠ 黙って別の意味に読まないこと（★版が違う ROM で嘘が出る）。

    ★`breath_damage` / `heal_amount` / `revive_effect` と**同じ約束**です。
    """
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = bytes(P.load_and_identify(ROM).rom.prg)
    assert ED.status_of_move(prg, 0x26) == ("illusion", 0xA0)
    code = ED.STATUS_SPELL_CODE[0x26][2]
    at = prg.find(code)
    assert at > 0, "⚠ 裏取りの命令が見つからない"
    broken = prg[:at + 4] + bytes([prg[at + 4] ^ 0xFF]) + prg[at + 5:]
    assert ED.status_of_move(broken, 0x26) is None, "⚠⚠ 命令が違うのに信じた"
    # ⚠⚠ 2 か所あっても諦める（★どちらが本物か言えない）
    at2 = 0x10010   # ★bank 4 の中
    twice = prg[:at2] + code + prg[at2 + len(code):]
    assert ED.status_of_move(twice, 0x26) is None, (
        "⚠⚠ 命令が 2 か所あるのに先頭を信じた")


@needs_rom
def test_混乱が覚める確率():
    """★毎ターン 12.5% で覚める（JP bank4 `$97DF` / ⚠ 期待 8 ターン）。

    ⚠⚠ 目覚めたターンも**行動しません**（★文が出て手番が終わる）。
    """
    from dq3.battle_ai import generate as G
    from dq3.battle_ai import settings as S
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    prg = P.load_and_identify(ROM).rom.prg
    assert ED.confuse_wake_rate(prg) == pytest.approx(0.125)
    assert G.build(S.BattleAiSettings())["party_confuse_turns"] == 8.0
    # ⚠⚠ 眠り（2.737）より**ずっと長い**（★取り違えたら気づきたい）
    assert 8.0 > G.build(S.BattleAiSettings())["party_sleep_turns"] * 2


@needs_rom
def test_名前のタイルが作れない品は入れない(items):
    """⚠ 一覧で探せない ＝ 押せない（★RX3-0213 の約束）。"""
    for key in ("attack", "heal_items"):
        for r in items[key]:
            assert r["tiles"], "⚠ タイルの無い品が入った: %s" % r
            assert r["name"], "⚠ 名前の無い品が入った: %s" % r
