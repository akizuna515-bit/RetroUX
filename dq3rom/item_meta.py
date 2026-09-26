"""アイテムの性能を ROM から起こす（RX3-0082 / 2026-09-05）。

★★ 「攻略情報を集める」のではなく、**ゲーム自身がどう解釈しているか**を追った ★★

```text
装備変更 → 能力再計算   `_b0_s16_player_EffATK_calc` / `_b0_s18_player_EffDEF_calc`
                        → `_far_read_pri_stat_tbl`（bank 9 に切り替えて `Y` = item_id で引く）
                        → ★`_gear_pri_stat_tbl`（攻守が**同じ 1 本の表**）
装備できるか            `_b0_s5E_check_if_item_can_be_equipped`
                        → ★`_b0_d40_class_equip_permission_mask_list`（職業の bit マスク）
使えるか                `_b0_s5E_check_if_item_can_be_used`
                        → ★`_b0_d41_item_use_list`（⚠ 装飾品は $27 引いて後ろへ積む）
店の値段                `_bD_s12` → ★`(d44 & 0x7F) * 10 ** (d42 & 3)`
売値                    `_bD_s13` → ★`買値 - (買値 + 3) / 4`（= 3/4）
分類                    ⚠⚠ 表ではなく **ID の範囲**（`item_ids.inc` の註釈そのもの）
戦闘で使ったときの効果  `_bs_pcAction_03_item` → `loc_6AEA2`
                        → ★`_bs_item_effect_tbl`（d42 bit7 の品を若い順に数えた番号で引く / RX3-0213）
```

## ⚠⚠ d42 / d44 の中身（★RX3-0213 / 2026-09-12 に訂正）

```text
d42 `use_effect`  ★印の bit（$80 戦闘で使える / $40 戦闘が参照 / $20 未確定 / $10 / $08 / $04）
                  ＋ 下位 2 bit = 値段の桁
d44 `effect_arg`  ★bit7 = フィールドで使う処理がある印 ＋ 下位 7 bit = **値段の基数**
                  ⚠ 「効果の引数」ではない（★例: まどうしのつえ は 15 → 15 × 10² = 1500 G）
```

⚠ 以前は d44 を「効果の引数」と書いていました。★戦闘での効果は d44 ではなく
**別の表** `_bs_item_effect_tbl`（下の `battle_effect`）にあります。

## ⚠⚠ ラベルに騙されない（★2026-09-05 に踏んだ）

```text
`_argC0_mul_9` という名前だが、⚠ **中身は ×10**
   ASL → 保存 → ASL → ASL → 足す ＝ x*8 + x*2 ＝ x*10
★実データ 4 件で裏が取れた（★×9 だと全部ずれる）
```

## ★JP ROM での位置（⚠ 北米版と**バイト単位で完全一致**。1 件ずつ見つかった）

```text
_b0_d40_class_equip_permission_mask_list  file 0x001118   79 バイト
_b0_d41_item_use_list                     file 0x001167   40 バイト
_b0_d42_item_use_effects_list             file 0x00118F  125 バイト
_b0_d44_item_effects_list                 file 0x00120C  125 バイト
_gear_pri_stat_tbl                        file 0x027990   71 バイト（bank 9）
```

## ⚠ 名前はここに持ちません

★`docs/00-project-policy.md` §3。⚠ 名前は実行時にユーザーの ROM から
（`dq3rom/names.py` / `dq3/knowledge/rom_names.py`）。
"""
from __future__ import annotations

import dataclasses

#: ★JP ROM での位置（⚠ 北米版の逆アセンブルのバイト列で一意に決めた）
TABLES = {
    "equip_mask": {"file": 0x001118, "count": 79,
                   "symbol": "_b0_d40_class_equip_permission_mask_list"},
    "use_mask": {"file": 0x001167, "count": 40, "symbol": "_b0_d41_item_use_list"},
    "use_effect": {"file": 0x00118F, "count": 125, "symbol": "_b0_d42_item_use_effects_list"},
    "effect_arg": {"file": 0x00120C, "count": 125, "symbol": "_b0_d44_item_effects_list"},
    "pri_stat": {"file": 0x027990, "count": 71, "symbol": "_gear_pri_stat_tbl"},
}

#: ★分類（⚠ 表ではなく **ID の範囲**。`item_ids.inc` の註釈より）
CATEGORIES = (
    (0x00, 0x1F, "weapon"),
    (0x20, 0x37, "armor"),
    (0x38, 0x3E, "shield"),
    (0x3F, 0x46, "helm"),
    (0x47, 0x4B, "accessory"),
    (0x4C, 0x4F, "tool_class"),     # ★特定の職しか使えない道具
    (0x50, 0x7C, "item"),           # ★いつでも使える品
)

#: ⚠⚠ **ID の範囲から外れる品が 1 つだけある**（RX3-0284 / 2026-09-18）
#
#   ★ゲーム自身の分類は bank 0 `$9C43` で、⚠ いちばん最初が
#   `CMP #$4A / BEQ → 0`（= 武器）です。★おうごんのつめ（$4A）は
#   ID の並びでは装飾品の範囲にありますが、**武器の枠に入ります**
#   （⚠ 装備できるのは職業 6 = ぶとうかだけ / `equip_mask` = $40）。
#   ★こうげき力も表の値ではなく **＋$37（55）固定**（bank 0 $94F1）。
WEAPON_EXCEPTIONS = (0x4A,)

#: ★装備できる分類（⚠ 攻守の表が引けるのもここまで）
GEAR_MAX = 0x46

#: ★装飾品を「使えるか」の表へ写すときのずらし（⚠ 逆アセンブルの `SBC #$27`）
ACCESSORY_SHIFT = 0x27

#: ★装備の可否を見なくなる境目（⚠ `CMP #ITEM_BOOK_OF_SATORI` / BCS で弾く）
EQUIP_SENTINEL = 0x4C

#: ★「使えるか」を表で見る範囲（⚠ 逆アセンブルの定数そのもの）
#   `CPX #ITEM_BLACK_PEPPER / BCS → 常に可`、`CPX #$20 / BCC → 武器の表`、
#   `CPX #ITEM_SACRED_AMULET / BCC → 常に可`、それ以外は `SBC #$27` で後ろへ積む。
USE_ALWAYS_FROM = 0x4F          # ITEM_BLACK_PEPPER
USE_ACCESSORY_FROM = 0x47       # ITEM_SACRED_AMULET

#: ★使用効果のビット（⚠ 逆アセンブルの註釈。★推測ではない）
EFFECT_BITS = {
    0x80: "battle_use",        # ★戦闘で特別な使い道がある
    0x40: "battle_ref",        # ⚠ 戦闘системが参照する（意味は未確定）
    0x10: "cannot_discard",    # ★捨てられない（= 重要品の汎用属性）
    0x08: "cursed",            # ★呪われている
    0x04: "consumed",          # ★使うと減る
}

#: ★値段の桁（⚠ `_argC0_mul_9` は名前に反して ×10）
PRICE_STEP = 10
PRICE_MASK = 0x7F

#: ★職業（⚠ `class_ids.inc` の定数そのもの。★推測ではない）
CLASS_NAMES = {0: "hero", 1: "wizard", 2: "pilgrim", 3: "sage",
               4: "soldier", 5: "merchant", 6: "fighter", 7: "goofoff"}
CLASS_BITS = CLASS_NAMES        # ★装備マスクの bit N ＝ 職業 N（`1 << class`）

#: ★職業と性別が入っている RAM（⚠ `_players_class_gender` / 1 人 1 バイト）
CLASS_GENDER_ADDR = 0x0718
CLASS_MASK = 0x07               # ★下位 3 bit が職業
GENDER_BIT = 0x08               # ★bit3 が性別（1 = 女）

#: ★袋の先頭（⚠⚠ **JP は $076C**。北米版の `_players_inventory_list` は $077C）
#   ★セーブステート 18 本で確かめた（`RX3-0076`）。⚠ 16 バイトずれている。
INVENTORY_ADDR = 0x076C

#: ⚠ 男が装備できないもの（★表ではなく**コードの直書き**。指示書 §13 の CODE_BRANCH）
#   ★`item_ids.inc` の定数（RX3-0083 で id を確定）: $16 / $31 / $32
MALE_BLOCKED = (0x16, 0x31, 0x32)

#: ★装備しているだけで効く特殊効果（⚠ `_equipment_with_buffs_tbl` / 5 件だけ）
#   ★`_party_equipment_buffs` に `ORA` される（⚠ 効果の中身は別調査）
EQUIP_BUFFS = {0x2C: 1, 0x2E: 1, 0x28: 3, 0x48: 2, 0x49: 4}

#: ★使用効果の系統（RX3-0085 / 2026-09-06）
#
#   ⚠⚠ **全部を解析していません**（指示書 8-3: 回復・移動・鍵の 3 系統だけ）。
#   ★根拠は `_items_use_lib` の並び順そのもの: `d44` の bit7 が立つ品を若い順に数えると、
#     北米版の逆アセンブルのハンドラ 42 個と**ちょうど 1 対 1**で並びます。
#   ★ここに載っているのは「ハンドラの名前から系統が明らかなもの」だけです。
#   ⚠ 迷うものは `other` のまま（★推測で分類しない）。
USE_KINDS = {
    # ★回復・強化（⚠ 使うと減るもの）
    0x5F: "boost", 0x60: "boost", 0x61: "boost", 0x62: "boost", 0x63: "boost",
    0x64: "boost",
    0x65: "heal", 0x66: "heal", 0x69: "heal", 0x6C: "heal",
    # ★移動・脱出
    0x68: "travel", 0x76: "travel",
    # ★鍵・扉
    0x58: "key", 0x59: "key", 0x5A: "key",
    # ⚠ ここから下は「戦闘で使う」ことだけ確か（★中身は未解析）
    0x11: "battle", 0x4E: "battle", 0x6D: "battle",
    0x67: "repel",              # ★敵を寄せつけない
}

#: ★系統の見出し（⚠ 分からないものは「その他」）
USE_KIND_LABEL = {"heal": "回復", "boost": "能力を上げる", "travel": "移動",
                  "key": "鍵", "battle": "戦闘で使う", "repel": "敵よけ",
                  "other": "その他"}

#: ★店の品揃え（⚠ 1 店 = 品の並び。**最後の品は bit7 が立つ**）
#   ⚠⚠ 2026-09-06 訂正: はじめ **220 バイト**としていましたが、★途中までしか
#     取れていませんでした（★ポインタが `+243` を指す）。正しくは **248 バイト**です。
SHOP_BLOB = {"file": 0x0368C1, "size": 248, "symbol": "byte_142828..（bank 0D）"}
SHOP_COUNT = 46
SHOP_END_BIT = 0x80

#: ★店番号 → 品揃えの先頭（⚠ `off_1427CC` の並び / RX3-0086）
#
#   ⚠⚠ **同じ並びを複数の店が使います**（★46 軒 → 43 か所 → 38 種類）。
#   ★数字は「品揃えの塊（`SHOP_BLOB`）の先頭からの位置」です。
#   ★根拠: 北米版 `off_1427CC` の 46 個のポインタ（`byte_1428xx`）を、
#     JP の塊の先頭からの差に直したもの。⚠ 塊そのものはバイト完全一致で 1 件。
SHOP_OFFSETS = (
     49,  98,   0,  35,  91,  42,  42,  60,
     54,  14, 105,  72, 111,  21,  28, 118,
     85,  79,  66,   7, 180, 220, 146, 124,
    158, 214, 168, 170, 174, 174, 188, 186,
    134, 134, 163, 199, 140, 226, 205, 232,
    152, 239, 208, 194, 127, 243,
)

#: ★店の種類（⚠ NPC の talk_id から決まる / `dq3/testing/talk_script.py`）
SHOP_ROLES = ("weapon_armor_shop", "item_shop")


class ItemMetaError(ValueError):
    pass


def category_of(item_id: int) -> str:
    """★ID の範囲で分類する（⚠ 表引きではない）。

    ⚠ `WEAPON_EXCEPTIONS` だけ範囲より先に見る（★bank 0 `$9C43` と同じ順）。
    """
    if item_id in WEAPON_EXCEPTIONS:
        return "weapon"
    for low, high, name in CATEGORIES:
        if low <= item_id <= high:
            return name
    return "unknown"


def sell_price(buy: int) -> int:
    """★売値（⚠ `_bD_s13`: 買値 − (買値 + 3) / 4）。"""
    return buy - ((buy + 3) >> 2)


def effect_flags(value: int) -> list[str]:
    return [name for bit, name in sorted(EFFECT_BITS.items(), reverse=True) if value & bit]


def classes_of(mask: int | None) -> list[str]:
    """★bit マスク → 職業の一覧（⚠ 分からなければ空）。"""
    if mask is None:
        return []
    return [CLASS_BITS[i] for i in range(8) if mask & (1 << i)]


@dataclasses.dataclass(frozen=True)
class ItemMeta:
    """★1 つのアイテムについて ROM から取れたもの（⚠ 名前は入れない）。"""

    item_id: int
    category: str
    #: ★攻撃力（武器）/ 守備力（鎧・盾・兜）。⚠ 道具は None
    pri_stat: int | None
    #: ★装備できる職業の bit マスク（⚠ 装備品でなければ None）
    equip_mask: int | None
    #: ★使える職業の bit マスク（⚠ 表に載るものだけ）
    use_mask: int | None
    #: ★d42: 印の bit ＋ 下位 2 bit = 値段の桁
    use_effect: int
    #: ★d44: bit7 = フィールドで使う処理がある印 ＋ 下位 7 bit = 値段の基数
    #:   ⚠ 「効果の引数」ではない（RX3-0213 で訂正）。★戦闘の効果は `battle_effect`
    effect_arg: int
    buy_price: int
    sell_price: int
    flags: tuple
    #: ⚠ 男は装備できない（★コードの直書き 3 件 / RX3-0083）
    female_only: bool = False
    #: ★使い道の系統（⚠ 分からなければ "other" / RX3-0085）
    use_kind: str = "other"
    #: ★装備しているだけで効く特殊効果（⚠ 5 件だけ / 中身は未解析）
    equip_buff: int | None = None

    @property
    def equip_classes(self) -> list[str]:
        return classes_of(self.equip_mask)

    def equippable_by(self, class_id: int, female: bool = True) -> bool:
        """★その人が装備できるか（⚠ 職業の bit ＋ 男の直書き制限）。"""
        if self.equip_mask is None:
            return False
        if not self.equip_mask & (1 << class_id):
            return False
        return female or not self.female_only

    @property
    def can_discard(self) -> bool:
        return "cannot_discard" not in self.flags

    def to_json(self) -> dict:
        got = dataclasses.asdict(self)
        got["flags"] = list(self.flags)
        got["equip_classes"] = self.equip_classes
        return got


def _slice(prg: bytes, key: str) -> bytes:
    spec = TABLES[key]
    start, count = spec["file"], spec["count"]
    got = prg[start:start + count]
    if len(got) != count:
        raise ItemMetaError("%s が ROM の外です（file 0x%06X）" % (spec["symbol"], start))
    return got


def read_tables(prg: bytes) -> dict[str, bytes]:
    return {key: _slice(prg, key) for key in TABLES}


def build(prg: bytes, count: int = 125) -> list[ItemMeta]:
    """★全アイテムの性能（⚠ 名前は含めない）。"""
    t = read_tables(prg)
    equip, use, effect, arg, stat = (t["equip_mask"], t["use_mask"], t["use_effect"],
                                     t["effect_arg"], t["pri_stat"])
    out = []
    for i in range(count):
        cat = category_of(i)
        buy = (arg[i] & PRICE_MASK) * (PRICE_STEP ** (effect[i] & 3))
        # ★装備の可否は、装備品として扱われる範囲だけ（⚠ コードが sentinel で弾く）
        emask = equip[i] if (i < EQUIP_SENTINEL and i < len(equip)) else None
        # ★使えるか: 武器はそのまま、装飾品は $27 引いて後ろへ積む（⚠ 逆アセンブルどおり）
        if i < 0x20:
            umask = use[i]
        elif USE_ACCESSORY_FROM <= i < USE_ALWAYS_FROM:
            umask = use[i - ACCESSORY_SHIFT]
        else:
            umask = None                    # ★常に使える（⚠ 表を引かない）
        out.append(ItemMeta(
            item_id=i, category=cat,
            pri_stat=stat[i] if i <= GEAR_MAX and i < len(stat) else None,
            equip_mask=emask, use_mask=umask,
            use_effect=effect[i], effect_arg=arg[i],
            buy_price=buy, sell_price=sell_price(buy),
            flags=tuple(effect_flags(effect[i])),
            female_only=i in MALE_BLOCKED,
            use_kind=USE_KINDS.get(i, "other"),
            equip_buff=EQUIP_BUFFS.get(i)))
    return out


def shops(prg: bytes) -> list[list[int]]:
    """★店の品揃え（⚠ 1 店 = item_id の並び。最後の品は bit7 が立つ）。

    ⚠⚠ 同じ並びを**複数の店が共有**します（★ポインタ表が同じ所を指す）。
      ここでは「並びの種類」を返します（★46 軒ぶんのポインタ表は別途）。
    """
    start, size = SHOP_BLOB["file"], SHOP_BLOB["size"]
    blob = prg[start:start + size]
    if len(blob) != size:
        raise ItemMetaError("店の品揃えが ROM の外です（file 0x%06X）" % start)
    out, cur = [], []
    for b in blob:
        cur.append(b & 0x7F)
        if b & SHOP_END_BIT:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)                          # ⚠ 終端が来ないまま終わった分
    return out


def shop_of(prg: bytes, shop_index: int) -> list[int]:
    """★店番号（`facility_index`）→ その店の品揃え（RX3-0086）。

    ⚠ 店番号は NPC の `talk_id` から決まります（`dq3/testing/talk_script.py`）。
    """
    if not 0 <= shop_index < len(SHOP_OFFSETS):
        raise ItemMetaError("店番号が範囲の外です: %s" % shop_index)
    start = SHOP_BLOB["file"] + SHOP_OFFSETS[shop_index]
    out = []
    for b in prg[start:start + 16]:
        out.append(b & 0x7F)
        if b & SHOP_END_BIT:
            return out
    raise ItemMetaError("店 %d の並びが終わらない（★終端の bit7 が無い）" % shop_index)


# --- ★戦闘で道具を使ったときの効果（RX3-0213 / 2026-09-12）------------------------------
#
#   ★北米版 bank04 `_bs_pcAction_03_item` → `loc_6AEA2`（:7327〜7371）:
#
#   ```text
#   X = 0 から $7E まで回す（`CPX #$7F`）。d42（use_effect）の bit7 が立つ品に出会うたび Y += 1
#   X が使った品になったら DEY → `_bs_item_effect_tbl`,Y を「唱える呪文」として byte_49 へ
#   d42 bit $04（consumed）が立っていれば袋から消す（★立っていなければ減らない）
#   → `.bs_player_item_as_chant`（:3688）★MP の判定と消費を**通らない** = MP 0
#   ```
#
#   ★表の値は呪文の ID（`dq3/knowledge/spell_info` と同じ番号 / 0 がいちばん安い火の呪文）。
#     ⚠ $41 以上は道具専用の偽の呪文（★回復の草など）。
#   ★JP ROM file 0x013315 / 40 バイト。北米版の並びで検索して **1 件だけ**見つかった。
#   ★長さ 40 は「d42 bit7 の品の数」とちょうど同じ（`battle_effects` が数を突き合わせる）。
#   ⚠ 未確認: 実際のダメージが呪文と同じ式か / 封じ（マホトーン）の最中に使えるか。
BATTLE_EFFECT_TABLE = {"file": 0x013315, "count": 40, "symbol": "_bs_item_effect_tbl"}
#: ★数える範囲（⚠ 逆アセンブルの `CPX #$7F`。★d42 の 125 バイトより 2 つ先まで読む）
BATTLE_SCAN_END = 0x7F
#: ★戦闘で使える印（d42 bit7）/ 使うと減る印（d42 bit2）
BATTLE_USE_BIT = 0x80
CONSUMED_BIT = 0x04


def _battle_scan(prg: bytes) -> bytes:
    """★ROM が数えるのと同じ範囲の d42（⚠ 表の 125 バイトの先まで / `CPX #$7F`）。"""
    start = TABLES["use_effect"]["file"]
    got = prg[start:start + BATTLE_SCAN_END]
    if len(got) != BATTLE_SCAN_END:
        raise ItemMetaError("d42 が ROM の外です（file 0x%06X）" % start)
    return got


def battle_effect_index(use_effect: bytes, item_id: int) -> int | None:
    """★その品が `_bs_item_effect_tbl` の何番目か（⚠ 戦闘で使えない品は None）。

    ★ROM と同じ数え方: 若い ID から順に、d42 bit7 の品を数える。
    ★bit7（袋の中の「装備している」印）は落とす（⚠ 戦闘の どうぐ も `AND #$7F` で落とす）。
    """
    item_id = int(item_id) & 0x7F
    if item_id >= min(BATTLE_SCAN_END, len(use_effect)):
        return None
    if not use_effect[item_id] & BATTLE_USE_BIT:
        return None
    return sum(1 for i in range(item_id) if use_effect[i] & BATTLE_USE_BIT)


def battle_effect_table(prg: bytes) -> bytes:
    start, count = BATTLE_EFFECT_TABLE["file"], BATTLE_EFFECT_TABLE["count"]
    got = prg[start:start + count]
    if len(got) != count:
        raise ItemMetaError("%s が ROM の外です（file 0x%06X）"
                            % (BATTLE_EFFECT_TABLE["symbol"], start))
    return got


def battle_effect(prg: bytes, item_id: int) -> int | None:
    """★戦闘で使うと、どの呪文として働くか（spell_id）。⚠ 戦闘で使えない品は None。"""
    index = battle_effect_index(_battle_scan(prg), item_id)
    if index is None:
        return None
    table = battle_effect_table(prg)
    if index >= len(table):
        raise ItemMetaError("⚠ 戦闘で使える品が表より多い（%d 番目 / 表 %d 件）"
                            % (index, len(table)))
    return table[index]


def battle_effects(prg: bytes) -> dict[int, int]:
    """★戦闘で使える品すべて → spell_id。

    ⚠ 品の数と表の長さが合わなければ止める（★数え方か表の位置が違う / 黙って通さない）。
    """
    scan = _battle_scan(prg)
    ids = [i for i in range(len(scan)) if scan[i] & BATTLE_USE_BIT]
    table = battle_effect_table(prg)
    if len(ids) != len(table):
        raise ItemMetaError("⚠ 戦闘で使える品 %d 件 / 表 %d 件（★数え方か位置が違う）"
                            % (len(ids), len(table)))
    return {item_id: table[k] for k, item_id in enumerate(ids)}


def check(rows: list[ItemMeta]) -> list[str]:
    """⚠ おかしな結果を**黙って通さない**（指示書 §16）。"""
    problems: list[str] = []
    if len(rows) != 125:
        problems.append("件数が 125 でない: %d" % len(rows))
    gear = [r for r in rows if r.pri_stat is not None]
    if not gear:
        problems.append("攻守が 1 件も取れていない")
    elif len({r.pri_stat for r in gear}) < 10:
        problems.append("攻守が %d 種類しかない（★全部同じ値ではないか）"
                        % len({r.pri_stat for r in gear}))
    prices = [r.buy_price for r in rows]
    if len(set(prices)) < 10:
        problems.append("値段が %d 種類しかない" % len(set(prices)))
    if all(r.equip_mask in (None, 0xFF) for r in rows):
        problems.append("全アイテムが誰でも装備できることになっている")
    cats = {r.category for r in rows}
    if "unknown" in cats and sum(1 for r in rows if r.category == "unknown") > 3:
        problems.append("分類が付かないものが多い: %d 件"
                        % sum(1 for r in rows if r.category == "unknown"))
    for name in ("weapon", "armor", "shield", "helm", "item"):
        if not any(r.category == name for r in rows):
            problems.append("分類 %s が 0 件" % name)
    if any(r.buy_price < 0 or r.buy_price > 200000 for r in rows):
        problems.append("値段がありえない: %s" % [r.item_id for r in rows if r.buy_price > 200000])
    return problems


def main(argv=None) -> int:
    import argparse
    import json
    import pathlib
    import sys

    parser = argparse.ArgumentParser(description="アイテムの性能を ROM から起こす")
    parser.add_argument("--rom", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--names", action="store_true", help="★実行時に ROM から名前も引く")
    args = parser.parse_args(argv)

    from dq3rom import profile as P

    root = pathlib.Path(__file__).resolve().parents[1]
    rom = pathlib.Path(args.rom) if args.rom else root / "work" / "rom" / "DQ3_J.nes"
    ident = P.load_and_identify(rom)
    rows = build(ident.rom.prg)
    problems = check(rows)
    if problems:
        for p in problems:
            print("⚠⚠ " + p, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([r.to_json() for r in rows], ensure_ascii=False, indent=1))
        return 0
    name_of = (lambda i: "")
    if args.names:
        from dq3.knowledge import rom_names

        name_of = lambda i: rom_names.item(i) or ""      # noqa: E731
    print("id   分類        攻守  装備できる職業                     買値    売値  印")
    for r in rows:
        print("$%02X  %-10s %4s  %-32s %6d %6d  %s %s" % (
            r.item_id, r.category, r.pri_stat if r.pri_stat is not None else "—",
            ",".join(r.equip_classes) or "—", r.buy_price, r.sell_price,
            "/".join(r.flags) or "—", name_of(r.item_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
