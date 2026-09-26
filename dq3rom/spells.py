"""呪文の表を ROM から読む（RX3-0125 / 2026-09-08）。

## ★出どころ（⚠ 北米版の逆アセンブルを**教師**にして、日本版で裏を取った）

```text
北米版 bank4 `_b4_dD_spells_list`   1 呪文 1 バイト（EEmmmmmm）
  bit0-5  消費 MP
  bit7    相手を選ぶ（★選択の窓が出る）     bit6  敵側
    0x00  自分 / 味方全体（選ばない）        例: スクルト / ベホマラー / ルーラ
    0x40  敵全体（選ばない）                 例: イオ / ギガデイン / メガンテ
    0x80  味方 1 人                          例: ホイミ / ザオラル / バイキルト
    0xC0  敵 1 群                            例: メラ / ギラ / ラリホー / ルカニ
北米版 `_bs_attackspell_single_tbl` …   対象の表（★どの ID が単体・群・全体か）
北米版 `_bs_player_spell_randrange_tbl` ダメージ（base, delta）× 18
北米版 `_bs_healing_randrange_tbl`      回復（base, delta）× 6
```

★日本版では**バイト列の署名**で探し、⚠ 番地は直書きしていません（`find_tables`）。
★ID は北米版と完全一致（0 メラ … 61 トラマナ）。名前は `dq3rom.names` が ROM から引きます。

## ⚠ 分類（`kind`）は ID の集合で決めている

★対象の表（ROM）で分かるのは「攻撃の単体・群」「回復の単体・全体」だけです。
⚠ バフ / デバフ / 蘇生 / 状態回復 は**北米版の処理名**（SPEEDUP / SAP / VIVIFY…）から
ID を写しました。★根拠は `docs/design/dq3-findings.md` の RX3-0125。
"""
from __future__ import annotations

import dataclasses

#: ★呪文の数（⚠ 表は 62 バイト）
COUNT = 62

#: ★1 バイトの読み方
MP_MASK = 0x3F
TARGET_MASK = 0xC0

#: ★対象（⚠ 上位 2 bit）
SELF_PARTY = "self_party"      #: 0x00 選ばない（自分 / 味方全体 / 移動）
ENEMIES_ALL = "enemies_all"    #: 0x40 敵全体
ALLY_SINGLE = "ally_single"    #: 0x80 味方 1 人
ENEMY_GROUP = "enemy_group"    #: 0xC0 敵 1 群
TARGET_OF = {0x00: SELF_PARTY, 0x40: ENEMIES_ALL, 0x80: ALLY_SINGLE, 0xC0: ENEMY_GROUP}

#: ★種別
ATTACK = "attack"
HEAL = "heal"
REVIVE = "revive"
BUFF = "buff"
DEBUFF = "debuff"
CURE = "cure"
INSTANT = "instant"          #: ★即死・追い払う・眠らせる等（⚠ 効くかは耐性次第）
FIELD = "field"
OTHER = "other"

#: ★北米版の処理名から写した ID（⚠ 対象の表に無いものだけ）
_BUFF = {25: "speed", 45: "defense_single", 46: "defense_party", 47: "defense_party",
         48: "bounce", 49: "breath", 50: "attack_up"}
_DEBUFF = {24: "slow", 43: "sap_single", 44: "sap_group", 37: "surround", 36: "stopspell"}
_INSTANT = {18: "beat", 19: "beat", 20: "sacrifice", 21: "expel", 22: "limbo", 23: "robmagic",
            34: "sleep", 39: "chaos"}

#: ★★ 即死の**効果の範囲**（RX3-0326 / 2026-09-20）。
#:
#:   ⚠⚠ `target`（`$C0` = `enemy_group`）は**カーソルが何を選ぶか**で、効果の範囲ではありません。
#:     ★ザキもザラキも `enemy_group` です（FC の DQ は「群を選んでから 1 体に当たる」形）。
#:     → ⚠ `target` を範囲の正本にすると、**ザキまで群全体**になります。
#:
#:   ★ROM から確かめたこと（confirmed）:
#:     - 耐性の番号 4 = `beat`（`enemy_detail.RESISTANCES`）
#:     - bank4 `$99C9`〜`$9A0A` が**即死の単体ルーチン**（`LDA #$04 / JSR $A3EF` を 2 回。
#:       ★中に**ループが無い** → 1 体だけ）
#:
#:   ⚠ まだ確かめられていないこと（inferred）:
#:     - ⚠ 呪文番号 → ルーチンの**関数表を特定できていません**（★3 つの候補表はどれも別物でした）。
#:       そのため「19 = ザラキ が群」は**原作の挙動から入れた値**です。
#:     → ★確かめるには: 敵 3 体にザラキを撃つ実機セーブで、**2 体以上同時に倒れるか**を見る。
INSTANT_SCOPE = {18: "single", 19: "group"}
_REVIVE = {32: "vivify", 33: "revive"}
_CURE = {35: "awake", 52: "antidote", 53: "numboff", 54: "curseoff"}
_FIELD = {38, 55, 56, 57, 58, 59, 60, 61}

#: ★効くかどうかを決める敵の耐性（`dq3rom.enemy_detail.RESISTANCES` の名前）
#:   ★23 マホトラ = 耐性 10（RX3-0260 / JP bank 4 $A735 `LDA #$0A` / `enemy_detail.RESISTANCES` の注記）
#:   ⚠⚠ 2026-09-14（RX3-0266）訂正: 以前ここに「ルカニ / ボミオス の耐性は未同定」と書いていたが誤り。
#:     ★ボミオス（24）= 耐性 12 / ★ルカニ・ルカナン（43・44）= 耐性 8 `sap`（JP `$A81B LDA #$08`）
#:   ★★ RX3-0267（2026-09-14）: 43・44 と攻撃呪文 0〜17 を入れた（★戦闘 AI の見込みが耐性の確率を使う）
RESIST_FIELD = {34: "sleep", 36: "stopspell", 37: "surround", 18: "beat", 19: "beat",
                21: "expel_fairywater", 22: "limbo_slow", 24: "limbo_slow", 39: "chaos",
                20: "sacrifice", 23: "robmagic", 43: "sap", 44: "sap"}

#: ★★ 攻撃呪文の耐性（RX3-0267 / JP bank 4 `$A4BF`: **呪文の番号**で 0〜3 を選ぶ）。
#:
#:   ```text
#:   0〜8   メラ・ギラ・イオ系  → 耐性 0（⚠ 名前は `damage_reduction` のまま / 戦闘 AI が読む）
#:   9〜12  ヒャド系            → 耐性 1 `ice_spells`
#:   13〜15 バギ系              → 耐性 2 `wind_spells`
#:   16〜17 ライデイン・ギガデイン → 耐性 3 `lightning_spells`
#:   ```
#:
#:   ★効くか効かないかの**二択**（`$A4DB JSR $A3EF / BCS`）。⚠ ダメージを減らす倍率ではない（RX3-0266 の実機で確認）。
ATTACK_RESIST = {sid: ("damage_reduction" if sid <= 8 else "ice_spells" if sid <= 12
                       else "wind_spells" if sid <= 15 else "lightning_spells") for sid in range(18)}
RESIST_FIELD.update(ATTACK_RESIST)


@dataclasses.dataclass(frozen=True)
class Spell:
    """★1 つの呪文（⚠ 名前は持たない。★`rom_names.spell(id)` が ROM から引く）。"""

    spell_id: int
    mp: int
    target: str
    kind: str
    #: ★ダメージ / 回復の目安（⚠ 攻撃・回復以外は None）
    base: int | None = None
    delta: int | None = None
    #: ★バフ・デバフ・即死の中身（北米版の処理名）
    effect: str | None = None
    #: ★効くかどうかを決める敵の耐性
    resist: str | None = None
    #: ★攻撃・回復の広さ（single / group / all / None）
    scope: str | None = None

    @property
    def avg(self) -> float | None:
        """★平均（⚠ base + delta の半分。★乱数の形は近似）。"""
        if self.base is None:
            return None
        if self.base == 0xFF:
            return None                      # ★ベホマ = 全快
        return self.base + (self.delta or 0) / 2.0

    def to_lua(self) -> dict:
        return {"id": self.spell_id, "mp": self.mp, "target": self.target, "kind": self.kind,
                "base": self.base, "delta": self.delta, "effect": self.effect,
                "resist": self.resist, "scope": self.scope}


#: ★署名（⚠ 北米版の表の先頭 12 バイト。★日本版でも同じ並びだった）
_SIG_TABLE = bytes([0xC2, 0xC6, 0xCC, 0xC4, 0xC6, 0xCC, 0x45, 0x49, 0x52, 0xC3, 0xC6, 0xCC])
_SIG_DAMAGE = bytes([0x08, 0x06, 0x46, 0x14, 0xA0, 0x28, 0x10, 0x08])
_SIG_HEAL = bytes([0x1E, 0x0A, 0x4B, 0x14, 0xFF, 0x00, 0x1E, 0x0A])


@dataclasses.dataclass(frozen=True)
class Tables:
    table: int
    targets: int
    damage: int
    heal: int


def find_tables(prg: bytes) -> Tables | None:
    """★署名で表を探す（⚠ 見つからなければ None。★推測で番地を決めない）。"""
    t = prg.find(_SIG_TABLE)
    d = prg.find(_SIG_DAMAGE)
    h = prg.find(_SIG_HEAL)
    if t < 0 or d < 0 or h < 0:
        return None
    # ★対象の表は呪文表の直後（★北米版と同じ並び。⚠ 17 バイト）
    return Tables(table=t, targets=t + COUNT, damage=d, heal=h)


def read_targets(prg: bytes, tables: Tables) -> dict:
    """★攻撃の単体 / 群、回復の単体 / 全体（⚠ ROM の表そのもの）。"""
    at = tables.targets
    return {
        "attack_single": tuple(prg[at:at + 4]),
        "attack_group": tuple(prg[at + 4:at + 12]),
        "heal_single": tuple(prg[at + 12:at + 15]),
        "heal_all": tuple(prg[at + 15:at + 17]),
    }


def attack_scope(target: str, spell_id: int, single: set) -> str:
    """★★ 攻撃呪文の**範囲**（RX3-0429 / P-2 / 2026-09-24）。

    ## ⚠⚠ 8 バイトの表（`attack_group`）から決めてはいけません

      ★昔は「単体の表に居る＝single / 群の表に居る＝group / **どちらにも居ない＝all**」
      で決めていました。⚠ その結果、ROM の中で**辻褄が合わない**ものが 3 件出ます。

      ```text
      id  5 ベギラゴン  target=enemy_group   ⚠ なのに scope=all
      id  8 イオナズン  target=enemies_all   ⚠ なのに scope=group
      id 16 ライデイン  target=enemy_group   ⚠ なのに scope=all
      ```

      ★`target` 欄は「**プレイヤーに何を選ばせるか**」です。
      ⚠ 群を選ばせる呪文が「敵全体」であることはありえません（★ROM の中だけで矛盾）。

    ## ★決め方（⚠ 18 件すべてが原作と一致することを実測）

      ```text
      target = enemies_all                → all     （★選ばせない＝敵全体）
      target = enemy_group かつ 単体の表   → single
      target = enemy_group                → group   （★群を選ばせる）
      ```

      ⚠ 8 バイトの表が**何なのかは未解明**です（★イオナズンが入っている説明が付かない）。
        ここでは**使いません**。`read_targets` は生の表として残します。

    @param target   `TARGET_OF[raw & TARGET_MASK]`
    @param single   `read_targets(...)["attack_single"]` の集合
    """
    if target == ENEMIES_ALL:
        return "all"
    if spell_id in single:
        return "single"
    return "group"


def read_all(prg: bytes) -> list[Spell]:
    """★62 件。⚠ 表が見つからなければ空（★呼ぶ側が「読めない」と扱う）。"""
    tables = find_tables(prg)
    if tables is None:
        return []
    targets = read_targets(prg, tables)
    single = set(targets["attack_single"])
    group = set(targets["attack_group"])
    heal_single = set(targets["heal_single"])
    heal_all = set(targets["heal_all"])
    out = []
    for sid in range(COUNT):
        raw = prg[tables.table + sid]
        mp = raw & MP_MASK
        target = TARGET_OF[raw & TARGET_MASK]
        kind, effect, scope, base, delta = OTHER, None, None, None, None
        if sid in single or sid in group or (sid <= 17):
            kind = ATTACK
            # ⚠⚠ 範囲は **`target` 欄** から決めます（★8 バイトの表は使わない / RX3-0429）
            scope = attack_scope(target, sid, single)
            if sid < 18:
                base, delta = prg[tables.damage + sid * 2], prg[tables.damage + sid * 2 + 1]
        elif sid in heal_single or sid in heal_all:
            kind = HEAL
            scope = "single" if sid in heal_single else "all"
            base, delta = prg[tables.heal + (sid - 26) * 2], prg[tables.heal + (sid - 26) * 2 + 1]
        elif sid in _REVIVE:
            kind, effect = REVIVE, _REVIVE[sid]
        elif sid in _BUFF:
            kind, effect = BUFF, _BUFF[sid]
        elif sid in _DEBUFF:
            kind, effect = DEBUFF, _DEBUFF[sid]
        elif sid in _INSTANT:
            kind, effect = INSTANT, _INSTANT[sid]
            # ★即死は範囲を別の表から入れる（⚠ `target` は範囲ではない / 上の註）
            scope = INSTANT_SCOPE.get(sid)
        elif sid in _CURE:
            kind, effect = CURE, _CURE[sid]
        elif sid in _FIELD:
            kind = FIELD
        out.append(Spell(spell_id=sid, mp=mp, target=target, kind=kind, base=base, delta=delta,
                         effect=effect, resist=RESIST_FIELD.get(sid), scope=scope))
    return out


__all__ = ["Spell", "Tables", "find_tables", "read_targets", "read_all", "COUNT",
           "SELF_PARTY", "ENEMIES_ALL", "ALLY_SINGLE", "ENEMY_GROUP",
           "ATTACK", "HEAL", "REVIVE", "BUFF", "DEBUFF", "CURE", "INSTANT", "FIELD", "OTHER"]
