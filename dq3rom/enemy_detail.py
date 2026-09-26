"""敵データ表の未解読領域を解く ― 行動・耐性・ドロップ（RX3-0039 / 2026-09-01）。

`dq3rom/enemies.py` が 23 bytes のうち基本性能を読みます。⚠ こちらは残りです。

```text
+10..17   行動 8 枠     ★下位 6 bit = 行動 ID / bit7 = 4 つの 2bit 制御場
+18..21   ★上位 6 bit = 耐性 2bit x 3 / 下位 2 bit = 既知（GOLD/ATK/DEF/HP 上位）
+22       ★bit7-6・5-4 = 耐性 / bit3 = 旗 / bit2-0 = ドロップ率
```

## ⚠⚠ 根拠は逆アセンブルのコードフロー（★推測ではない）

⚠ 資料の文面は写しません（★LICENSE 無し。構造と意味だけ使う /
`docs/research/dq3-disassembly-study.md`）。

| 何を | どこで確かめたか |
| --- | --- |
| 行動 ID は 6 bit | `_b4_s27` の末尾が `AND #$3F`（★`bank04.inc:9366` 付近） |
| 行動 ID は 64 種 | `_bs_emove_fptr_stage1_tbl` が**ちょうど 64 エントリ** |
| bit7 は 2bit 場 | `sub_6B974` が「2 バイトの bit7 を組にして 0..3 を作る」 |
| 耐性の並び | `sub_6B994`: `Y = 0x12 + i/3`、マスク表 `$C0,$30,$0C` |
| 耐性の効き | しきい値表 `0, $4D, $B3, $FF`（★乱数と比較） |
| ドロップ | `_b4_s17`: `+9 AND ITEM_TYPE_MASK` / `+22 AND #7` |

## ★確度の区別（⚠ 崩さない）

```text
confirmed        ★コードフローで裏が取れた
high-confidence  ★複数の材料が一致する（⚠ 1 本では決まらない）
inferred         ⚠ そう見えるだけ
unresolved       ⚠⚠ 何も分かっていない（★埋めない）
```

⚠ `raw` は必ず残します。★解釈が訂正されても ROM を読み直さなくてよいように。
"""

from __future__ import annotations

import dataclasses
import re

#: ★行動 8 枠の位置
ACTION_FIRST, ACTION_COUNT = 10, 8

#: ★行動 ID のマスク（⚠ `_b4_s27` の `AND #$3F`）。bit6 は**未使用**
MOVE_ID_MASK = 0x3F

#: ★bit7 だけが旗として使われる（⚠ bit6 が立った実データは 1 件も無い）
MOVE_FLAG_BIT = 0x80

#: ★★ 行動 ID → 名前。⚠ `_bs_emove_fptr_stage1_tbl` の**関数名から**起こした。
#:
#:   ⚠ 同じ関数を指す範囲（ブレス・回復・仲間呼び）は、★実際の中身が
#:     別の表で分かれるため、**番号を付けて区別**しています。
#:     その範囲の「どれがどれか」は `high-confidence` 止まりです。
MOVE_NAMES: tuple[str, ...] = (
    "assessing",                 # 0x00
    "protects_itself",           # 0x01
    "regular_attack",            # 0x02
    "attack_maybe_crit",         # 0x03
    "attack_maybe_sleep",        # 0x04
    "attack_maybe_poison",       # 0x05
    "attack_maybe_numb",         # 0x06
    "try_flee",                  # 0x07
    "reinforce_own_type",        # 0x08
    "curious_dance",             # 0x09
    "breath_0A",                 # 0x0A ★ここから 6 つは同じ関数
    "breath_0B",                 # 0x0B
    "breath_0C",                 # 0x0C
    "breath_0D",                 # 0x0D
    "breath_0E",                 # 0x0E
    "breath_0F",                 # 0x0F
    "sweet_breath",              # 0x10
    "toxic_breath",              # 0x11
    "scorching_breath",          # 0x12
    "spell_single_13",           # 0x13 ★注釈: BLAZE
    "spell_single_14",           # 0x14 ★注釈: BLAZEMORE
    "spell_single_15",           # 0x15 ★注釈: BLAZEMOST
    "spell_single_16",           # 0x16 ★注釈: ICEBOLT
    "spell_party_17",            # 0x17 ★注釈: FIREBAL
    "spell_party_18",            # 0x18 ★注釈: FIREBANE
    "spell_party_19",            # 0x19 ★注釈: EXPLODET
    "spell_party_1A",            # 0x1A ★注釈: SNOWBLAST
    "spell_party_1B",            # 0x1B ★注釈: SNOWSTORM
    "spell_party_1C",            # 0x1C ★注釈: INFERNOS
    "spell_party_1D",            # 0x1D ★注釈: INFERMORE
    "spell_party_1E",            # 0x1E ★注釈: INFERMOST
    "chant_beat_1F",             # 0x1F
    "chant_beat_20",             # 0x20
    "chant_sacrifice",           # 0x21
    "chant_sleep",               # 0x22
    "chant_stopspell",           # 0x23
    "chant_sap",                 # 0x24
    "chant_defence",             # 0x25
    "chant_surround",            # 0x26
    "chant_robmagic",            # 0x27
    "chant_chaos",               # 0x28
    "chant_slow",                # 0x29
    "chant_limbo",               # 0x2A
    "zoma_freeze_beam",          # 0x2B
    "chant_bounce",              # 0x2C
    "chant_increase",            # 0x2D
    "chant_increase2",           # 0x2E
    "chant_vivify",              # 0x2F
    "chant_revive",              # 0x30
    "heal_single_31",            # 0x31 ★ここから 10 個は 2 つの関数を共有
    "heal_single_32",            # 0x32
    "heal_single_33",            # 0x33
    "heal_multi_34",             # 0x34
    "heal_multi_35",             # 0x35
    "heal_single_36",            # 0x36
    "heal_single_37",            # 0x37
    "heal_single_38",            # 0x38
    "heal_multi_39",             # 0x39
    "heal_multi_3A",             # 0x3A
    "reinforce_specific_3B",     # 0x3B ★ここから 5 つは特定の敵を呼ぶ
    "reinforce_specific_3C",     # 0x3C
    "reinforce_specific_3D",     # 0x3D
    "reinforce_specific_3E",     # 0x3E
    "reinforce_specific_3F",     # 0x3F
)
assert len(MOVE_NAMES) == 64

#: ★行動の大分類（⚠ 関数の族から。★UI と戦術 AI の当てにする）
MOVE_CATEGORY: dict[str, tuple[int, ...]] = {
    "wait": (0x00,),
    "defend": (0x01,),
    "attack": (0x02, 0x03, 0x04, 0x05, 0x06),
    "flee": (0x07,),
    "reinforce": (0x08, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F),
    "dance": (0x09,),
    "breath": tuple(range(0x0A, 0x13)),
    "spell_damage": tuple(range(0x13, 0x1F)),
    "spell_instadeath": (0x1F, 0x20, 0x21),
    "spell_status": (0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A),
    "special": (0x2B,),
    "spell_buff": (0x2C, 0x2D, 0x2E),
    "spell_revive": (0x2F, 0x30),
    "heal": tuple(range(0x31, 0x3B)),
}

#: ★★ bit7 の 4 つの組（⚠ `sub_6B974` が 2 バイトずつ読む）。
#:
#:   `(名前, 先頭 offset, 逆アセンブルの入口, 確度)`
#:
#:   ⚠⚠ **8 枠は単純な 8 択ではありません。** 下位 6 bit が行動 ID で、
#:     上位 bit は**別の 4 つの 2bit 値**を作っています。
CONTROL_FIELDS: tuple[tuple[str, int, str, str], ...] = (
    ("unknown_pair_10_11", 10, "_b4_s29", "unresolved"),
    ("select_mode", 12, "sub_6B960", "high-confidence"),
    ("actions_per_turn", 14, "_b4_s2A", "high-confidence"),
    ("unknown_pair_16_17", 16, "_b4_s18", "unresolved"),
)

#: ★★ 耐性 ― `sub_6B994` の `Y = 0x12 + i/3` と マスク表 `$C0,$30,$0C`。
#:
#:   `(番号, offset, 右シフト量, 名前, 確度)`
#:
#:   ★★ 2026-09-14（RX3-0266）: JP ROM で `JSR $A3EF`（耐性の判定）を呼ぶ 16 か所を**全部**読み直して確定しました。
#:     ⚠ 以前の名前は北米版のファイルの中で**近くにあった処理名**から取っていて、5 つ外れていました:
#:
#:     ```text
#:     0  damage_reduction → ★メラ・ギラ・イオ系（呪文 0〜8）⚠ 名前は戦闘 AI が読むので据え置き（中身は下）
#:     1  unknown_1        → ★ヒャド系（呪文 9〜12）
#:     2  numboff          → ★バギ系（呪文 13〜15）⚠ キアリク（しびれを治す）は耐性を見ない
#:     3  unknown_3        → ★ライデイン・ギガデイン（呪文 16・17）
#:     8  pc_damage_8      → ★ルカニ・ルカナン（呪文 43・44 / JP `$A819 LDA #$08`）
#:     ```
#:
#:     ★攻撃呪文は JP bank 4 `$A4BF`〜`$A4DB` が**呪文の番号から** 0〜3 を選び `JSR $A3EF` → ⚠ 効く / 効かない の**二択**
#:       （★ダメージを減らすのではない。⚠ 倍率表 `$98F3` を使うのはブレスの 1 か所 `$98C7` だけ）。
#:     ★番号 10 = マホトラ（RX3-0260 / JP `$A735 LDA #$0A`）。
#:     ★呼び出し元の番地・呪文と道具の対応は `docs/design/dq3-resistance-analysis.md`。
RESISTANCES: tuple[tuple[int, int, int, str, str], ...] = (
    (0,  0x12, 6, "damage_reduction",  "confirmed"),
    (1,  0x12, 4, "ice_spells",        "confirmed"),
    (2,  0x12, 2, "wind_spells",       "confirmed"),
    (3,  0x13, 6, "lightning_spells",  "confirmed"),
    (4,  0x13, 4, "beat",              "confirmed"),
    (5,  0x13, 2, "sacrifice",         "confirmed"),
    (6,  0x14, 6, "sleep",             "confirmed"),
    (7,  0x14, 4, "stopspell",         "confirmed"),
    (8,  0x14, 2, "sap",               "confirmed"),
    (9,  0x15, 6, "surround",          "confirmed"),
    (10, 0x15, 4, "robmagic",          "confirmed"),
    (11, 0x15, 2, "chaos",             "confirmed"),
    (12, 0x16, 6, "limbo_slow",        "confirmed"),
    (13, 0x16, 4, "expel_fairywater",  "confirmed"),
)

#: ★★ 耐性レベル → 乱数のしきい値（⚠ `byte_6B9CE`）。
#:
#:   ★判定は `_rand_ex` と比べるだけです（`sub_6A337`）。
#:   ⚠ `$FF` は**特別扱い**で、比較せずに「効かない」へ抜けます。
RESIST_THRESHOLD: tuple[int, ...] = (0x00, 0x4D, 0xB3, 0xFF)

#: ★★ 「効く確率」（%）。⚠ **目安ではなく、コードから出した値**です。
#:
#:   ## ★向きの確かめ方（⚠ 取り違えると真逆になる）
#:
#:     `sub_6A337` は carry を返し、⚠ 呼び出し側は
#:     `BCC → "is not asleep"` と分岐します（★`_bs_spell_sleep`）。
#:     → **carry=1 が「効く」**。
#:
#:     判定は `rand() >= しきい値` なので、
#:     ★効く確率 = `(256 - しきい値) / 256`。
#:
#:   ```text
#:   レベル 0  しきい値 0x00  → ★必ず効く（⚠ 比較せず carry=1 へ抜ける）
#:   レベル 1  しきい値 0x4D  → 179/256 = 70%
#:   レベル 2  しきい値 0xB3  →  77/256 = 30%
#:   レベル 3  しきい値 0xFF  → ★効かない（⚠ 比較せず carry=0 へ抜ける）
#:   ```
RESIST_PERCENT: tuple[int, ...] = (100, 70, 30, 0)

#: ★言葉での言い方（⚠ 数字だけだと意味が読み取れない / DQ2 の図鑑と同じ考え）
RESIST_LABEL: tuple[str, ...] = ("必ず効く", "70%", "30%", "効かない")


def resist_percent(level: int) -> int:
    """★その段階で効く確率（%）。⚠ しきい値から計算する（表を二重に持たない）。"""
    threshold = RESIST_THRESHOLD[int(level) & 3]
    return round((256 - threshold) / 256 * 100)

#: ★ダメージ側の耐性は倍率表（⚠ `byte_69837`。★上の乱数とは別の使い方）
#:
#:   ⚠⚠ 2026-09-14（RX3-0266）: この倍率を使うのは**ブレスの 1 か所だけ**です（JP bank 4 `$98C7`〜`$98E6` / 表 `$98F3` /
#:     耐性 0 を `$BA32` で直接引く）。★攻撃呪文（メラ〜ギガデイン）は `RESIST_THRESHOLD` の確率で
#:     「効く / 効かない」の**二択**（`$A4DB JSR $A3EF / BCS $A4E6`）。
#:   ⚠ `resistances_of()` は 14 個すべてに `damage_scale` を付けていますが、意味があるのは耐性 0 のブレスだけです。
DAMAGE_SCALE: tuple[int, ...] = (0xFF, 0xCC, 0x99, 0x80)

#: ★ドロップ ― `_b4_s17`
DROP_ITEM_OFFSET, DROP_ODDS_OFFSET = 9, 0x16
#: ⚠ `+9` の bit7 は「装備品か」の旗（★`_b4_s17` は落として使う）
DROP_ITEM_MASK, DROP_EQUIP_BIT = 0x7F, 0x80

#: ★★ 「品なし」を表す ID（⚠ `item_ids.inc`: `ITEM_SWORD_HORNED = $7F`）。
#:
#:   `_b4_s17` の註釈:
#:
#:     > if it was this, it was really meant to mean no item
#:
#:   ⚠ 実データ 139 体には 1 体もありませんが、★規則として持ちます
#:     （⚠ 持たないと「品 127」という**存在しない品**を出してしまう）。
NO_ITEM_ID = 0x7F
#: ★ドロップ率は**下位 3 bit だけ**
DROP_ODDS_MASK = 0x07
#: ⚠ `+22` の bit3 は別の旗（★`sub_6BA04` が単独で読む）
DROP_BYTE_FLAG_BIT = 0x08

#: ★★ ドロップ率の変換表（⚠ **式ではありません**）。
#:
#:   ⚠⚠ 最初、`A = 1 << (7 - odds - 1)` を確率だと思って `1/1` を出しました。
#:     ★`A` は**乱数と比べるしきい値**であって、確率そのものではありません。
#:     → ⚠ 逆アセンブルの註釈にある**表をそのまま写します**（推測しない）。
#:
#:   ★判定は `rand() >= A` なら落とさない、です（`_b4_s17`）。
DROP_RATE: dict[int, str] = {
    0: "always",     # ★しきい値を作らずに抜ける
    1: "1/8",        # ⚠ rand >= 32 で外れ
    2: "1/16",
    3: "1/32",
    4: "1/64",
    5: "1/128",
    6: "1/256",
    7: "1/2048",     # ★終盤のボスだけ（⚠ (1/256) x (1/8) の二段判定）
}


def move_name(move_id: int) -> str:
    """★行動 ID の名前。⚠ 範囲外は隠さずそのまま出す。"""
    if 0 <= move_id < len(MOVE_NAMES):
        return MOVE_NAMES[move_id]
    return "unknown_%02X" % move_id           # pragma: no cover


def move_category(move_id: int) -> str:
    """★行動の大分類（⚠ 分からなければ `unknown`）。"""
    for name, ids in MOVE_CATEGORY.items():
        if move_id in ids:
            return name
    return "unknown"                          # pragma: no cover


# --- ★攻撃呪文の行動 → 唱える呪文（RX3-0224 / 2026-09-12）------------------------------
#
#   ★北米版 bank04 `_bs_emove_stage1_spell_single` / `_bs_emove_stage1_spell_party`（:2344〜2383）:
#
#   ```text
#   single  行動 ID - $13 → X → `_bs_attackspell_single_tbl`,X    （0x13..0x16 の 4 つ）
#   party   行動 ID - $17 → X → `_bs_attackspell_multiple_tbl`,X  （0x17..0x1E の 8 つ）
#   → 引いた値を byte_49（唱える呪文）と「呪文を唱えた」の文の引数へ
#   ```
#
#   ★2 つの表は**続けて並ぶ**（4 + 8 = 12 バイト）→ ★「行動 ID - $13」で引く 1 本の表として読める。
#   ★値は呪文の ID（`dq3/knowledge/spell_info` / `rom_names.spell` と同じ番号 / 0 = いちばん安い火の呪文）。
#   ★JP ROM file 0x013535（bank 4 / CPU $B535）。★確かめ方は 2 つ:
#     1. ★ROM 自身のコードが指している: bank 4 に `SEC / SBC #$13 / TAX / LDA $B535,X` と
#        `SEC / SBC #$17 / TAX / LDA $B539,X` が 1 か所ずつ（★`attack_spell_table` が読むたびに見る）
#     2. ★北米版の並び（呪文の定数を番号にしたもの）で ROM 全体を探して 1 件だけ（検査）
#   ★すぐ後ろに回復の表（`_bs_heal_single_tbl` / `_bs_heal_multiple_tbl`）が北米版と同じ並びで続く。
#   ⚠ 名前はここに持たない（★ROM から実行時に引く / No-Spoiler）。
ATTACK_SPELL_TABLE = {"file": 0x013535, "count": 12, "first_move": 0x13, "party_move": 0x17,
                      "symbols": ("_bs_attackspell_single_tbl", "_bs_attackspell_multiple_tbl")}
#: ★PRG の 1 bank（⚠ 表のある bank が CPU $8000〜$BFFF に来る）
PRG_BANK_SIZE, PRG_BANK_CPU = 0x4000, 0x8000
#: ★呪文の ID の数（⚠ 北米版 `spell_ids.inc` の末尾 $3D まで。★$41 以上は道具専用の偽の呪文）
SPELL_ID_COUNT = 0x3E


def _prg_of(src) -> bytes | None:
    """★PRG（bytes）/ ROM（`.prg`）/ 識別結果（`.rom.prg`）のどれでも受ける。"""
    if isinstance(src, (bytes, bytearray, memoryview)):
        return bytes(src)
    rom = getattr(src, "rom", src)
    prg = getattr(rom, "prg", None)
    return bytes(prg) if prg is not None else None


def _code_reads(prg: bytes, first_move: int, cpu_addr: int) -> bool:
    """★`SEC / SBC #first_move / TAX / LDA cpu_addr,X` が表と同じ bank に 1 か所だけあるか。"""
    bank = ATTACK_SPELL_TABLE["file"] // PRG_BANK_SIZE
    code = prg[bank * PRG_BANK_SIZE:(bank + 1) * PRG_BANK_SIZE]
    want = bytes([0x38, 0xE9, first_move, 0xAA, 0xBD, cpu_addr & 0xFF, cpu_addr >> 8])
    return code.count(want) == 1


def attack_spell_table(prg_or_rom) -> bytes | None:
    """★攻撃呪文の表 12 バイト（行動 0x13 から順）。⚠ 読めない / 裏が取れなければ None。

    ⚠ 黙って別の場所を読まない: 長さ / ROM のコードが指す番地 / 値が呪文 ID の範囲で重複しない、
      の 3 つが揃わなければ None（★呼ぶ側は「こうげき呪文(17)」のまま出す）。
    """
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    spec = ATTACK_SPELL_TABLE
    start, count = spec["file"], spec["count"]
    table = prg[start:start + count]
    if len(table) != count:
        return None
    cpu = PRG_BANK_CPU + start % PRG_BANK_SIZE
    party_cpu = cpu + (spec["party_move"] - spec["first_move"])
    if not (_code_reads(prg, spec["first_move"], cpu)
            and _code_reads(prg, spec["party_move"], party_cpu)):
        return None
    if len(set(table)) != count or max(table) >= SPELL_ID_COUNT:
        return None
    return table


def attack_spells(prg_or_rom) -> dict[int, int]:
    """★攻撃呪文の行動 ID → 呪文 ID のすべて。⚠ 読めなければ空。"""
    table = attack_spell_table(prg_or_rom)
    if table is None:
        return {}
    first = ATTACK_SPELL_TABLE["first_move"]
    return {first + i: spell_id for i, spell_id in enumerate(table)}


def spell_of_move(prg_or_rom, move_id: int) -> int | None:
    """★その行動で唱える呪文の ID（⚠ 攻撃呪文でない / 表が読めなければ None）。"""
    index = int(move_id) - ATTACK_SPELL_TABLE["first_move"]
    if not 0 <= index < ATTACK_SPELL_TABLE["count"]:
        return None
    table = attack_spell_table(prg_or_rom)
    return None if table is None else table[index]


#: ★★ 敵の攻撃呪文・ブレスのダメージの幅（RX3-0278 / 2026-09-16 / JP ROM のコードを読んだ）。
#:
#:   ```text
#:   表     bank 4 $B56A（PRG 0x1356A）= (基数, 幅) × 18
#:   読む   $BF58: LDX $51 / LDA $0558,X / CMP #$10 / BCS / ADC #$15 / SEC / SBC #$13 / ASL / TAY
#:                 LDA $B56B,Y / JSR $AD48 / CLC / ADC $B56A,Y
#:   $AD48  乱数 × A の上位バイト → 0..幅-1     ★ダメージ = 基数 + 0..幅-1
#:   索引   行動 0x13..0x1E → 0..11 ／ ★ブレス 0x0A..0x0F → 12..17（+$15 してから -$13）
#:   種類   $8E7B: LDX $51 / LDA $0558,X / CMP #$0D / BCC → 文 $36、以上は文 $37（★炎 / 冷気 / RX3-0039）
#:   ```
#:
#:   ⚠ この幅は**防ぐ前**の値です。⚠ `$BF7A` で行動 < $10 かつ `$073C` の bit2 なら 2/3
#:     （★フバーハらしい / 未確認）。⚠ 防具・耐性の倍率も別。
DAMAGE_RANGE_TABLE = {"file": 0x01356A, "count": 18}
#: ★読む命令（`$BF5A` から / ⚠ この並びが bank 4 に 1 か所だけあることを確かめてから表を信じる）
_DAMAGE_READER = bytes([0xBD, 0x58, 0x05, 0xC9, 0x10, 0xB0, 0x02, 0x69, 0x15, 0x38, 0xE9, 0x13,
                        0x0A, 0xA8, 0xB9, 0x6B, 0xB5, 0x20, 0x48, 0xAD, 0x18, 0x79, 0x6A, 0xB5])
#: ★炎と冷気の分かれ目（`CMP #$0D / BCC +4 / LDA #$37`）
_BREATH_KIND = bytes([0xBD, 0x58, 0x05, 0xC9, 0x0D, 0x90, 0x04, 0xA9, 0x37])
BREATH_FIRST, BREATH_LAST, BREATH_COLD_FROM = 0x0A, 0x0F, 0x0D


def _battle_bank(prg: bytes) -> bytes:
    """★戦闘のコードが入っている面（⚠ 命令を数えるときは**ここだけ**を見る）。

    ⚠⚠ 2026-09-22（RX3-0368）: ★`_bank_has_once` は面を絞っていたのに、
      ⚠ 正規表現で探すほうは **PRG 全体**を見ていました。
      → ★同じ「1 か所だけ」を言うのに**範囲が違う**と、
        ⚠ 片方だけがすり抜けます。ここに揃えます。
    """
    bank = DAMAGE_RANGE_TABLE["file"] // PRG_BANK_SIZE
    return prg[bank * PRG_BANK_SIZE:(bank + 1) * PRG_BANK_SIZE]


def _bank_has_once(prg: bytes, want: bytes) -> bool:
    return _battle_bank(prg).count(want) == 1


def breath_damage(prg_or_rom, move_id: int) -> tuple[str, int, int] | None:
    """★ブレス 0x0A〜0x0F の `(種類, 最小, 最大)`。種類は `"fire"` / `"cold"`。

    ⚠ ブレスでない / 表の長さ・読む命令・分かれ目の命令のどれかが合わなければ None
    （★呼ぶ側は「ブレス(0B)」のまま出す / ⚠ 黙って別の場所を読まない）。
    """
    move_id = int(move_id)
    if not BREATH_FIRST <= move_id <= BREATH_LAST:
        return None
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    spec = DAMAGE_RANGE_TABLE
    table = prg[spec["file"]:spec["file"] + spec["count"] * 2]
    if len(table) != spec["count"] * 2:
        return None
    if not (_bank_has_once(prg, _DAMAGE_READER) and _bank_has_once(prg, _BREATH_KIND)):
        return None
    index = move_id + 0x15 - 0x13
    base, width = table[index * 2], table[index * 2 + 1]
    if width == 0:
        return None
    kind = "fire" if move_id < BREATH_COLD_FROM else "cold"
    return kind, base, base + width - 1


#: ★★ 敵が唱える攻撃呪文の行動 ID（RX3-0361 / 2026-09-22）
#:
#:   ⚠⚠ **味方の呪文の表とは別物です。**
#:   ★`DAMAGE_RANGE_TABLE` の前半 12 件（index 0..11）が、そのまま行動 0x13..0x1E です
#:     （⚠ 後半 6 件がブレス 0x0A..0x0F）。読む命令は `_DAMAGE_READER` の 1 本だけで、
#:     ★呪文もブレスも**同じ場所から**引かれます。
#:
#:   ```text
#:   例  move 0x19（敵のイオナズン）  ★敵表 60..79   ⚠ 味方の呪文表 120..160
#:   ```
SPELL_DAMAGE_FIRST, SPELL_DAMAGE_LAST = 0x13, 0x1E


def spell_damage(prg_or_rom, move_id: int) -> tuple[int, int] | None:
    """★敵の攻撃呪文 0x13〜0x1E の `(最小, 最大)`。

    ⚠ 呪文でない / 表の長さ・読む命令が合わなければ None
    （★呼ぶ側は 0 = 「分からない」のままにする / ⚠ 味方の表で代用しない）。
    """
    move_id = int(move_id)
    if not SPELL_DAMAGE_FIRST <= move_id <= SPELL_DAMAGE_LAST:
        return None
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    spec = DAMAGE_RANGE_TABLE
    table = prg[spec["file"]:spec["file"] + spec["count"] * 2]
    if len(table) != spec["count"] * 2:
        return None
    if not _bank_has_once(prg, _DAMAGE_READER):
        return None
    index = move_id - SPELL_DAMAGE_FIRST
    base, width = table[index * 2], table[index * 2 + 1]
    if width == 0:
        return None
    return base, base + width - 1


def breath_tier(move_id: int) -> int | None:
    """★同じ種類の中の強さ 0 / 1 / 2（弱 / 中 / 強）。⚠ ブレス 0x0A〜0x0F でなければ None。

    ★表の幅は種類ごとに番号順で大きくなる（炎 6〜9 < 30〜39 < 80〜99 / 冷気 9〜20 < 40〜59 < 100〜139）。
    """
    move_id = int(move_id)
    if not BREATH_FIRST <= move_id <= BREATH_LAST:
        return None
    return (move_id - BREATH_FIRST) % (BREATH_COLD_FROM - BREATH_FIRST)


#: ★★ 共有 ID の残り 3 族の中身（RX3-0278 / 2026-09-16 / JP bank 4 のコードを読んだ）。
#:
#:   ```text
#:   回復  $94D7  LDA #$36 / STA $04 / LDA $0558,X / CMP #$36 / BCS / LDA #$31 / STA $04 / SEC / SBC $04 / TAX / LDA $B541,X
#:               → 0x31..0x33 と 0x36..0x38 が $B541 の 3 つ（★呪文 ID）
#:         $9516  LDA #$34 / … / CMP #$39 / BCC / LDA #$39 / … / LDA $B544,X
#:               → 0x34..0x35 と 0x39..0x3A が $B544 の 2 つ
#:         ★回復量も $BF94 で 行動 - $31 → $B59A → 同じ行を引く（⚠ 31〜33 と 36〜38 は呪文も量も同じ）
#:         ⚠ 違うのは使う条件だけ（$BDA1 の表: $8615 / $8623）。★意味は未確認
#:   即死  $BE49 の表: 0x1F → $8FE4 `LDA #$12 / JSR $90AE`、0x20 → $907F … `LDA #$13 / JMP $9574`（$9574 = JSR $90AE）
#:         ★$90AE は A の呪文を唱える（0x2F/0x30 も `LDA #$21 / LDA #$20` で同じ入口）
#:   仲間  $8E0F  LDA $0558,X / SEC / SBC #$3B / TAX / LDA $8E4B,X  → ★敵 ID（5 つ）
#:   ```
SHARED_MOVE_CODE = {
    "heal_single": (0x013541, 3, bytes([0xA9, 0x36, 0x85, 0x04, 0xA6, 0x51, 0xBD, 0x58, 0x05, 0xC9, 0x36, 0xB0, 0x06,
                                        0x48, 0xA9, 0x31, 0x85, 0x04, 0x68, 0x38, 0xE5, 0x04, 0xAA, 0xBD, 0x41, 0xB5])),
    "heal_multi": (0x013544, 2, bytes([0xA9, 0x34, 0x85, 0x04, 0xA6, 0x51, 0xBD, 0x58, 0x05, 0xC9, 0x39, 0x90, 0x06,
                                       0x48, 0xA9, 0x39, 0x85, 0x04, 0x68, 0x38, 0xE5, 0x04, 0xAA, 0xBD, 0x44, 0xB5])),
    "reinforce": (0x010E4B, 5, bytes([0xA6, 0x51, 0xBD, 0x58, 0x05, 0x38, 0xE9, 0x3B, 0xAA, 0xBD, 0x4B, 0x8E])),
}
#: ★即死の 2 つ（★関数の頭の命令ごと確かめる / `(行動, 命令, 呪文 ID)`）
BEAT_CODE = ((0x1F, bytes([0xA9, 0x12, 0x20, 0xAE, 0x90]), 0x12),
             (0x20, bytes([0xA9, 0x20, 0x85, 0x47, 0xA9, 0x13, 0x4C, 0x74, 0x95]), 0x13))
ENEMY_ID_COUNT = 140


def _heal_index(move_id: int) -> tuple[str, int] | None:
    if 0x31 <= move_id <= 0x33 or 0x36 <= move_id <= 0x38:
        return "heal_single", move_id - (0x31 if move_id < 0x36 else 0x36)
    if 0x34 <= move_id <= 0x35 or 0x39 <= move_id <= 0x3A:
        return "heal_multi", move_id - (0x34 if move_id < 0x39 else 0x39)
    return None


def _shared_table(prg: bytes, name: str) -> bytes | None:
    start, count, code = SHARED_MOVE_CODE[name]
    table = prg[start:start + count]
    if len(table) != count or not _bank_has_once(prg, code):
        return None
    return table


def shared_move_target(prg_or_rom, move_id: int) -> tuple[str, int] | None:
    """★共有 ID の中身: `("spell", 呪文 ID)` か `("monster", 敵 ID)`。

    ★回復 0x31〜0x3A・即死 0x1F / 0x20 は呪文、仲間を呼ぶ 0x3B〜0x3F は呼ぶ敵。
    ⚠ 読む命令が 1 か所に無い / 値が範囲外なら None（★呼ぶ側は番号のまま出す）。
    """
    move_id = int(move_id)
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    heal = _heal_index(move_id)
    if heal is not None:
        table = _shared_table(prg, heal[0])
        got = None if table is None else table[heal[1]]
        return None if got is None or got >= SPELL_ID_COUNT else ("spell", got)
    for beat_move, code, spell_id in BEAT_CODE:
        if move_id == beat_move:
            return ("spell", spell_id) if _bank_has_once(prg, code) else None
    if 0x3B <= move_id <= 0x3F:
        table = _shared_table(prg, "reinforce")
        got = None if table is None else table[move_id - 0x3B]
        return None if got is None or got >= ENEMY_ID_COUNT else ("monster", got)
    return None


#: ★★ 敵の回復量を引く命令（RX3-0363 / 2026-09-22 / JP bank4 `$BF94`）。
#:
#:   ```text
#:   A6 51        LDX $51
#:   BD 58 05     LDA $0558,X      ★いまの行動
#:   38 E9 31     SEC / SBC #$31
#:   AA           TAX
#:   BD ?? ??     LDA 索引表,X     ★行動 → 行（⚠ 31〜35 と 36〜3A は同じ行）
#:   0A A8        ASL / TAY        ★1 行 2 バイト
#:   B9 ?? ??     LDA 量の表,Y     ★基数
#:   C9 FF        CMP #$FF         ⚠ $FF なら**全回復**
#:   ```
#:
#:   ⚠⚠ **味方の呪文表ではありません**（★`RX3-0361` と同じ型の間違いを繰り返さない）。
#:   ★番地は**命令から逆算**します（⚠ 書き写さない）。
_HEAL_READER = re.compile(
    rb"\xA6\x51\xBD\x58\x05\x38\xE9\x31\xAA\xBD(..)\x0A\xA8\xB9(..)\xC9\xFF", re.S)

#: ★回復の行動 ID（⚠ `_heal_index` と同じ範囲）
HEAL_FIRST, HEAL_LAST = 0x31, 0x3A
#: ★全体を回復する行動（⚠ `$B541` / `$B544` の分かれ方と同じ）
HEAL_MULTI_MOVES = (0x34, 0x35, 0x39, 0x3A)
#: ★「全回復」を表す基数
HEAL_FULL = 0xFF


def heal_amount(prg_or_rom, move_id: int) -> tuple[int, int] | str | None:
    """★敵が 1 回で戻す HP。`(最小, 最大)` か `"full"`（★全回復）。

    ⚠ 回復の行動でない / 読む命令が 1 か所に無ければ None
    （★呼ぶ側は 0 = 「分からない」のままにする / ⚠ 味方の表で代用しない）。
    """
    move_id = int(move_id)
    if not HEAL_FIRST <= move_id <= HEAL_LAST:
        return None
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    hits = _HEAL_READER.findall(_battle_bank(prg))
    if len(hits) != 1:
        return None                       # ⚠ 1 か所でなければ信じない
    index_addr = hits[0][0][0] | (hits[0][0][1] << 8)
    table_addr = hits[0][1][0] | (hits[0][1][1] << 8)
    bank = 4
    idx_off = bank * 0x4000 + (index_addr - 0x8000) + (move_id - HEAL_FIRST)
    if not 0 <= idx_off < len(prg):
        return None
    row = prg[idx_off]
    row_off = bank * 0x4000 + (table_addr - 0x8000) + row * 2
    if not 0 <= row_off + 1 < len(prg):
        return None
    base, width = prg[row_off], prg[row_off + 1]
    if base == HEAL_FULL:
        return "full"
    if width == 0:
        return None
    return base, base + width - 1


def heals_whole_group(move_id: int) -> bool:
    """★その回復が**群のみんな**に届くか（⚠ ベホマラー / ベホマズン）。"""
    return int(move_id) in HEAL_MULTI_MOVES


#: ★★ 仲間を呼ぶ行動（RX3-0363）。
#:
#:   ```text
#:   move 8      ★**自分と同じ敵**を呼ぶ
#:               （JP bank4 $8D27: `LDX $59 / LDA $07B5,X` = 自分の ID をそのまま新しい枠へ）
#:   0x3B..0x3F  ★決まった敵を呼ぶ（`shared_move_target` が敵 ID を返す）
#:   ```
#:
#:   ⚠⚠ **呼べないことがあります**（★`$8D27` の `JSR $8E1C / BCS` → 失敗は `$8E19`。
#:     ⚠ 枠の空きらしいが**未確認**）。→ ★見積りは**上限**になります。
REINFORCE_SELF_MOVE = 8
#: ★`$8D27` が自分の ID を読む命令（⚠ これが無ければ「自分と同じ」と言えない）
_REINFORCE_SELF_CODE = bytes([0xA6, 0x59, 0xBD, 0xB5, 0x07, 0x20, 0x1C, 0x8E])


def reinforce_calls_self(prg_or_rom) -> bool:
    """★move 8 が「自分と同じ敵」を呼ぶこと（⚠ 命令が 1 か所に無ければ False）。"""
    prg = _prg_of(prg_or_rom)
    return prg is not None and _bank_has_once(prg, _REINFORCE_SELF_CODE)


#: ★★ 呼べるかの判定（RX3-0363 / 2026-09-22 / JP bank4 `$8E1C`）。
#:
#:   ```text
#:   85 45         STA $45          ★呼ぶ敵の ID
#:   A2 00 …       ⚠ $0530 を 16 まで見て**空き**を探す。無ければ CLC（失敗）
#:   A2 03         LDX #$03         ★群は 4 つ
#:   BD B5 07      LDA $07B5,X      ★その群の敵 ID
#:   C5 45         CMP $45
#:   F0 05         BEQ 成功
#:   CA 10 F6      DEX / BPL        ⚠ 3 → 0
#:   18 60         CLC / RTS        ⚠⚠ **その敵が場に居なければ失敗**
#:   ```
#:
#:   ⚠⚠ **呼べるのは「もう場に居る種類」だけです。**
#:   ★だから マドハンド の「だいまじんを呼ぶ」枠は、⚠ だいまじんが居ない戦闘では
#:     **何も起きません**（★手番を 1 つ捨てる）。
#:   ★move 8（自分と同じ）は自分の群が必ず居るので、⚠ 空きさえあれば通ります。
_REINFORCE_NEEDS_PRESENT_CODE = bytes(
    [0xA2, 0x03, 0xBD, 0xB5, 0x07, 0xC5, 0x45, 0xF0, 0x05, 0xCA, 0x10, 0xF6, 0x18, 0x60])


def reinforce_needs_same_kind_present(prg_or_rom) -> bool:
    """⚠⚠ 呼ぶ敵が**すでに場に居る**ことが要る（★命令が 1 か所に無ければ False）。"""
    prg = _prg_of(prg_or_rom)
    return prg is not None and _bank_has_once(prg, _REINFORCE_NEEDS_PRESENT_CODE)


#: ★★ 戦闘に入る敵の枠の数（RX3-0368 / JP bank4 `$8E1E`）。
#:
#:   ```text
#:   A2 00        LDX #$00
#:   BD 30 05     LDA $0530,X      ★枠が埋まっているか
#:   E8           INX
#:   3D 30 05     AND $0530,X      ★生きているか
#:   10 07        BPL 空きあり     ⚠ どちらかが落ちていれば使える
#:   E8 / E0 10   INX / CPX #$10   ★16 バイト ＝ **8 体ぶん**（1 体 2 バイト）
#:   ```
#:
#:   ⚠ 枠の数は**命令から逆算**します（★`#$10` を書き写さない）。
_SLOT_SCAN_CODE = re.compile(
    rb"\xA2\x00\xBD\x30\x05\xE8\x3D\x30\x05\x10\x07\xE8\xE0(.)\xD0\xF2", re.S)
#: ★1 体あたりのバイト数（⚠ `$0530` と `$0531` の組）
SLOT_BYTES = 2


def reinforce_slot_limit(prg_or_rom) -> int | None:
    """★戦闘に入る敵の数の上限（⚠ 命令が 1 か所に無ければ None）。"""
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    hits = _SLOT_SCAN_CODE.findall(_battle_bank(prg))
    if len(hits) != 1:
        return None
    return hits[0][0] // SLOT_BYTES


#: ★★ 蘇生（RX3-0368 / 2026-09-22 / JP bank4 `$9443` 付近 / ★5 か所とも 1 件ずつ一致）。
#:
#:   ```text
#:   BD 31 05 / 30 ?? / BD 30 05 / 10 ??   ⚠ **死んでいる敵**にだけ効く
#:   A5 49 / C9 21 / F0 05 / 20 ?? ?? / 10 ??
#:       → ★$21（ザオリク）は乱数を**通らない** ＝ 必ず成功
#:       → ⚠ $20（ザオラル）は乱数の bit7 で失敗 ＝ **半々**
#:   A5 49 / C9 21 / F0 04 / 46 5A / 66 59
#:       → ★$21 はそのまま ＝ **全快**
#:       → ⚠ $20 は 1 回右シフト ＝ **最大 HP の半分**
#:   ```
#:
#:   ⚠⚠ 戻る HP は `_bs_read_enemy_prop_HP`（★表の**最大 HP**）から作ります。
#:   ⚠ 相手は `byte_54C` で選ばれた敵なので、★**群をまたぎます**。
REVIVE_FULL_MOVE, REVIVE_HALF_MOVE = 0x30, 0x2F
#: ★半分にする命令（⚠ これが無ければ「全快」と言えない）
_REVIVE_HALF_CODE = bytes([0xA5, 0x49, 0xC9, 0x21, 0xF0, 0x04, 0x46, 0x5A, 0x66, 0x59])
#: ★ザオラルだけ乱数を引く命令
_REVIVE_RANDOM_CODE = re.compile(rb"\xA5\x49\xC9\x21\xF0\x05\x20..\x10.", re.S)
#: ★死んでいる相手にだけ効く命令
_REVIVE_NEEDS_DEAD_CODE = re.compile(rb"\xBD\x31\x05\x30.\xBD\x30\x05\x10.", re.S)


#: ★★ ダメージを出さない「息」（RX3-0371 / 2026-09-22 / JP ROM のコードを読んだ）。
#:
#:   ⚠⚠ **0x10〜0x12 はダメージ 0 が正しい**です（★状態異常だけ）。
#:     ⚠ 名前（`scorching_breath`）から「灼熱 ＝ 大ダメージ」と思いがちですが、
#:     ★実際は**麻痺**にするだけでした。→ ⚠ ダメージの穴ではなく**分類の誤り**です。
#:
#:   ```text
#:   0x10 眠り    $9D53  B9 E1 07 / 29 08 → 09 08 / 99 E1 07   ★運試し #$60
#:   0x11 毒      $8EE1  BD 3D 07 / 29 20 → 09 20 / 9D 3D 07   ★運試し #$60
#:   0x12 麻痺    $8F2C  BD 3D 07 / 29 40 → 09 40 / 9D 3D 07   ★運試し #$20
#:   ```
#:
#:   ★`$073D` bit5 = 毒 / bit6 = 麻痺 は profile で既に confirmed
#:     （⚠ まひの根拠に `$8F37 ORA #$40` が挙がっている = ここ）。
#:
#:   ⚠ 「どの息がダメージを出さないか」は**表から出します**（`DAMAGE_RANGE_TABLE` に
#:     行が無い息）。★下の命令は「では何をするのか」の裏取りです（⚠ 推測で status と言わない）。
STATUS_BREATH_CODE: dict[int, tuple[str, bytes]] = {
    # ⚠ `B9 E1 07 29 08`（眠っているか見る）だけでは **2 か所**あります（★ラリホーと共通）。
    #   → ★運試しまで含めて 1 か所に絞ります。
    0x10: ("sleep", bytes([0xB9, 0xE1, 0x07, 0x29, 0x08, 0xD0, 0x1D, 0xA9, 0x60])),
    0x11: ("poison", bytes([0xBD, 0x3D, 0x07, 0x29, 0x20, 0xD0, 0x12, 0xA9, 0x60])),
    0x12: ("paralyze", bytes([0xBD, 0x3D, 0x07, 0x29, 0x40, 0xD0, 0x12, 0xA9, 0x20])),
}


def breath_status(prg_or_rom, move_id: int) -> str | None:
    """★その息が**ダメージでなく状態異常**なら、その種類。

    ⚠ ダメージの行がある息（0x0A〜0x0F）は None。
    ⚠ 裏取りの命令が 1 か所に無ければ None（★推測で status と言わない）。
    """
    move_id = int(move_id)
    got = STATUS_BREATH_CODE.get(move_id)
    if got is None:
        return None
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    # ⚠ ダメージの行があるなら、それは**ダメージの息**（★分類を上書きしない）
    if breath_damage(prg, move_id) is not None:
        return None
    return got[0] if _bank_has_once(prg, got[1]) else None


#: ★★ 運試しの閾値（RX3-0373 / ⚠ `_bs_player_luck_test` の引数）。
#:
#:   ★`STATUS_BREATH_CODE` の命令の中に `A9 xx`（`LDA #閾値`）が入っています。
STATUS_BREATH_PROB = {0x10: 0x60, 0x11: 0x60, 0x12: 0x20}

#: ★★ 味方へ状態異常を与える**呪文**（RX3-0375 / 2026-09-22 / JP ROM のコードを読んだ）。
#:
#:   ```text
#:   move  呪文        本体      旗             閾値   効き方
#:   0x22  ラリホー    $9D53    $07E1 bit3     $60    ★眠り（⚠ あまい息と**同じ本体**）
#:   0x23  マホトーン  $9E37    $073C bit5     $60    ⚠ 呪文を封じる
#:   0x26  マヌーサ    $9EB6    $073C bit4     $A0    ⚠ 物理が外れる（★命中 0.375）
#:   0x28  メダパニ    $924F    $073D bit4     $40    ★混乱
#:   ```
#:
#:   ⚠ どれも `_bs_player_luck_test`（`$A8F7`）を通ります。
#:     → ★確率は `status_chance()` の同じ式です。
#:
#:   `{move: (種類, 閾値, 裏取りの命令)}`
STATUS_SPELL_CODE: dict[int, tuple[str, int, bytes]] = {
    0x22: ("sleep", 0x60,
           bytes([0xB9, 0xE1, 0x07, 0x29, 0x08, 0xD0, 0x1D, 0xA9, 0x60])),
    0x23: ("stopspell", 0x60,
           bytes([0xBD, 0x3C, 0x07, 0x29, 0x20, 0xD0, 0x12, 0xA9, 0x60])),
    0x26: ("illusion", 0xA0,
           bytes([0xBD, 0x3C, 0x07, 0x29, 0x10, 0xD0, 0x12, 0xA9, 0xA0])),
    0x28: ("confuse", 0x40,
           bytes([0xBD, 0x3C, 0x07, 0x29, 0x40, 0xD0, 0x1C, 0xA9, 0x40])),
}

#: ★★ 混乱が覚める確率（RX3-0375 / JP bank4 `$97DF`）。
#:
#:   ```text
#:   20 63 AD   JSR 乱数
#:   C9 20      CMP #$20        ← ★閾値
#:   B0 0B      BCS 覚めない
#:   BD 3D 07 / 29 EF / 9D 3D 07 ← ★$073D bit4 を落とす
#:   00 74 F7   ⚠ 文が出て**その手番は終わる**
#:   ```
#:
#:   → ★P(覚める) = 32 / 256 = 0.125 → ⚠ **期待 8 ターン**（★戦闘の長さで頭打ち）。
_CONFUSE_WAKE = re.compile(
    rb"\x20\x63\xAD\xC9(.)\xB0.\xBD\x3D\x07\x29\xEF\x9D\x3D\x07", re.S)


def confuse_wake_rate(prg_or_rom) -> float | None:
    """★混乱が 1 ターンで覚める確率（⚠ 命令が 1 か所に無ければ None）。"""
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    hits = _CONFUSE_WAKE.findall(_battle_bank(prg))
    if len(hits) != 1:
        return None
    return hits[0][0] / 256.0


def status_of_move(prg_or_rom, move_id: int) -> tuple[str, int] | None:
    """★★ その行動が味方に与える状態異常 `(種類, 閾値)`（RX3-0375）。

    ★息（0x10-0x12）も呪文（0x22 / 0x23 / 0x26 / 0x28）もここで引けます。
    ⚠ 裏取りの命令が 1 か所に無ければ None（★推測で言わない）。
    """
    move_id = int(move_id)
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    kind = breath_status(prg, move_id)
    if kind is not None:
        prob = STATUS_BREATH_PROB.get(move_id)
        return (kind, prob) if prob is not None else None
    got = STATUS_SPELL_CODE.get(move_id)
    if got is None:
        return None
    return (got[0], got[1]) if _bank_has_once(prg, got[2]) else None

#: ★★ 状態異常が入る確率の式（RX3-0373 / 2026-09-22 / JP bank4 `$A917`）。
#:
#:   ```text
#:   u16[4] = ($180 - EffLUCK) / 2
#:   u16[4] = u16[4] * 閾値
#:   u16[4] = u16[4] / $80
#:   JSR _rand_ex / CMP u16[4]     ← ★乱数 < この値 なら**入る**（BCS は「運が良くて避けた」）
#:   ```
#:
#:   → ★`P = (384 - 運のよさ) × 閾値 / 65536`
#:
#:   ⚠ `EffLUCK` は**装備込みの運**です。★`state.json` の `luck`（素の値）で近似します。
#:     ⚠ 装備は運を**上げる**方向なので、★こちらは確率を**高めに**見ます（= 敵を弱く見積もらない）。
LUCK_BASE = 0x180
#: ★式が変わっていないことを確かめる命令（⚠ `$180` を作る所 ＋ 割る所）
_LUCK_CODE = bytes([0xA9, 0x80, 0x85, 0x04, 0xA9, 0x01, 0x85, 0x05])


def status_chance(prob_arg: int, luck: int) -> float:
    """★その状態異常が入る確率（⚠ 0〜1 / 運のよさは 0〜255）。"""
    got = (LUCK_BASE - max(0, min(int(luck), 255))) * int(prob_arg) / 65536.0
    return max(0.0, min(1.0, got))


def luck_formula_ok(prg_or_rom) -> bool:
    """⚠ 式を作る命令が ROM にあること（★無ければ確率を出さない）。"""
    prg = _prg_of(prg_or_rom)
    return prg is not None and _battle_bank(prg).count(_LUCK_CODE) >= 1


#: ★★ 眠りが続くターン（RX3-0373 / JP bank4 `$9645` → 表 `$B4EF`）。
#:
#:   ```text
#:   8A 0A AA        TXA / ASL / TAX        ★味方 index × 2
#:   BD 3C 07        LDA $073C,X            ★味方の状態（下位バイト）
#:   29 03           AND #$03               ★カウンタ（bit0-1）
#:   A8              TAY
#:   B9 EF B4        LDA $B4EF,Y            ⚠ **敵は $B4F3**（★4 バイト前の別の表）
#:   20 63 AD        JSR 乱数 / CMP / BEQ / BCC → 目覚め
#:   ```
#:
#:   ⚠⚠ **味方と敵で表が違います**（★味方 `FF 80 55 20` / 敵 `FF C0 80 40`）。
#:     → ★味方のほうが**長く眠ります**（⚠ 2.737 ターン / 敵は 2.207）。
_SLEEP_READER = re.compile(rb"\x8A\x0A\xAA\xBD\x3C\x07\x29\x03\xA8\xB9(..)", re.S)
#: ★カウンタの数（⚠ 2bit）
SLEEP_STEPS = 4


def party_sleep_table(prg_or_rom) -> tuple[int, ...] | None:
    """★味方の眠りの閾値表（⚠ 命令から**逆算**します / 番地は書き写さない）。"""
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    hits = _SLEEP_READER.findall(_battle_bank(prg))
    if len(hits) != 1:
        return None
    addr = hits[0][0] | (hits[0][1] << 8)
    off = 4 * PRG_BANK_SIZE + (addr - 0x8000)
    got = prg[off:off + SLEEP_STEPS]
    return tuple(got) if len(got) == SLEEP_STEPS else None


def sleep_turns(table) -> float | None:
    """★眠っているターン数の期待値（⚠ カウンタは 3 から始まり、毎ターン 1 減る）。

    ⚠ 目覚めたターンも**行動しません**（★文だけで手番が終わる）。
    """
    if not table or len(table) < SLEEP_STEPS:
        return None
    left, total, counter, turn = 1.0, 0.0, SLEEP_STEPS - 1, 1
    while counter >= 0:
        wake = (table[counter] + 1) / 256.0
        total += turn * left * wake
        left *= (1.0 - wake)
        counter -= 1
        turn += 1
    return total + turn * left if left > 0 else total


def revive_effect(prg_or_rom, move_id: int) -> tuple[float, float] | None:
    """★蘇生の `(戻る割合, 成功率)`。割合は**最大 HP に対する**もの。

    ```text
    move 0x30 ザオリク  (1.0, 1.0)   ★全快 / 必ず成功
    move 0x2F ザオラル  (0.5, 0.5)   ⚠ 半分 / 半々
    ```

    ⚠ 蘇生でない / 命令が 1 か所に無ければ None（★推測で埋めない）。
    """
    move_id = int(move_id)
    if move_id not in (REVIVE_FULL_MOVE, REVIVE_HALF_MOVE):
        return None
    prg = _prg_of(prg_or_rom)
    if prg is None:
        return None
    if not _bank_has_once(prg, _REVIVE_HALF_CODE):
        return None
    if len(_REVIVE_RANDOM_CODE.findall(_battle_bank(prg))) != 1:
        return None
    if len(_REVIVE_NEEDS_DEAD_CODE.findall(_battle_bank(prg))) != 1:
        return None
    if move_id == REVIVE_FULL_MOVE:
        return 1.0, 1.0
    return 0.5, 0.5


def actions_of(raw: bytes) -> list[dict]:
    """★8 枠を解く。⚠ `raw` も一緒に返す（**捨てない**）。"""
    out = []
    for slot in range(ACTION_COUNT):
        byte = raw[ACTION_FIRST + slot]
        move_id = byte & MOVE_ID_MASK
        out.append({
            "slot": slot,
            "raw": byte,
            "move_id": move_id,
            "name": move_name(move_id),
            "category": move_category(move_id),
            "flag": bool(byte & MOVE_FLAG_BIT),
        })
    return out


def control_fields_of(raw: bytes) -> dict:
    """★bit7 が作る 4 つの 2bit 値（⚠ `sub_6B974` と同じ組み方）。

    ```text
    値 = (raw[off] の bit7 → bit0) | (raw[off+1] の bit7 → bit1)
    ```
    """
    out = {}
    for name, off, entry, confidence in CONTROL_FIELDS:
        lo = 1 if raw[off] & MOVE_FLAG_BIT else 0
        hi = 2 if raw[off + 1] & MOVE_FLAG_BIT else 0
        out[name] = {"value": lo | hi, "source": entry,
                     "confidence": confidence}
    return out


def resistances_of(raw: bytes) -> dict:
    """★14 個の耐性（⚠ 生の 0..3 と、しきい値の両方を返す）。"""
    out = {}
    for index, off, shift, name, confidence in RESISTANCES:
        level = (raw[off] >> shift) & 0x03
        out[name] = {
            "index": index,
            "level": level,
            "threshold": RESIST_THRESHOLD[level],
            "percent": resist_percent(level),
            "damage_scale": DAMAGE_SCALE[level],
            "note": RESIST_LABEL[level],
            "confidence": confidence,
        }
    return out


def drop_of(raw: bytes) -> dict:
    """★ドロップ（⚠ `_b4_s17` の読み方をそのまま写す）。

    ## ⚠ 率は `DROP_RATE` の**表**で引きます（★式ではない）

    ```text
    odds == 0  → ★しきい値を作らずに抜ける = **必ず落とす**
    odds 1..6  → ⚠ しきい値 A = 32,16,8,4,2,1 と `rand()` を比べる
    odds == 7  → ★二段判定（⚠ 終盤のボスだけ）
    ```
    """
    item_raw = raw[DROP_ITEM_OFFSET]
    odds_byte = raw[DROP_ODDS_OFFSET]
    odds = odds_byte & DROP_ODDS_MASK
    item_id = item_raw & DROP_ITEM_MASK
    return {
        "item_raw": item_raw,
        # ⚠ `0x7F` は「品なし」（★`ITEM_SWORD_HORNED` を流用している）
        "item_id": None if item_id == NO_ITEM_ID else item_id,
        "has_item": item_id != NO_ITEM_ID,
        "equip_bit": bool(item_raw & DROP_EQUIP_BIT),
        "odds_raw": odds,
        "rate": DROP_RATE[odds],
        "byte_flag_bit3": bool(odds_byte & DROP_BYTE_FLAG_BIT),
    }


@dataclasses.dataclass(frozen=True)
class EnemyDetail:
    """★1 体ぶんの解析結果。⚠ `raw` を必ず持つ。"""

    enemy_id: int
    raw: bytes
    actions: tuple
    control: dict
    resistances: dict
    drop: dict

    @classmethod
    def from_raw(cls, enemy_id: int, raw: bytes) -> "EnemyDetail":
        return cls(enemy_id=enemy_id, raw=bytes(raw),
                   actions=tuple(actions_of(raw)),
                   control=control_fields_of(raw),
                   resistances=resistances_of(raw),
                   drop=drop_of(raw))

    def to_json(self) -> dict:
        """⚠ raw と decoded の**両方**を出す（★解釈が変わっても残る）。"""
        return {
            "monster_id": self.enemy_id,
            "actions_raw": list(self.raw[ACTION_FIRST:ACTION_FIRST + 8]),
            "resistance_raw": list(self.raw[0x12:0x17]),
            "drop_raw": [self.raw[DROP_ITEM_OFFSET], self.raw[DROP_ODDS_OFFSET]],
            "actions": list(self.actions),
            "control": self.control,
            "resistances": self.resistances,
            "drop": self.drop,
        }


def read_all(enemies) -> list[EnemyDetail]:
    """`dq3rom.enemies.read_all()` の結果から、全件を解く。"""
    return [EnemyDetail.from_raw(e.enemy_id, e.raw) for e in enemies]
