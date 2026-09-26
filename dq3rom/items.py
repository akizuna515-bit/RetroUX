"""アイテムの ID と分類、袋の読み方（RX3-0041 / 2026-09-01）。

## ⚠⚠ 名前はここに持ちません

★`docs/00-project-policy.md` §3:

    原作テキストを同梱しない。⚠ 文言は実行時にユーザーの ROM から読む。

⚠ DQ3 の ROM テキストは**圧縮**されています（`RX3-0013` の実測: 素のかな列は
無く、フォントも CHR-RAM にしか無い）。★確立している道は「**画面から読む**」で、
敵の名前と同じ仕組みです（`dq3/knowledge/enemies_seen.py`）。

→ ★ここが持つのは **ID・分類・袋の場所**という**構造**だけです。
  ⚠ 名前は `dq3/knowledge/item_names.py` が、遊びながら覚えます。

## ★分類の根拠（⚠ 逆アセンブルの註釈そのもの）

```text
;the classification system used in the code relies on their numerical values
;for example, something will be classified as armor if its ID is >= $20 and <= $37.
```

★つまり**分類は ID の範囲そのもの**で、⚠ 表引きではありません。
（`item_ids.inc` の節見出しから起こしました。★文言ではなく構造です。）

## ★袋（`_players_inventory_list = $077C`）

```text
u8[4][8]   4 人 x 8 枠
bit7       ★装備中
0xFF       ⚠ 空き枠
0x7F       ⚠ 「品なし」（★ITEM_SWORD_HORNED を流用）
```

⚠⚠ **実データで裏を取りました**（★セーブステート 8 本）。

```text
81 = 装備 + 0x01  → weapons（0x00-0x1F）
A0 = 装備 + 0x20  → armor  （0x20-0x37）
B8 = 装備 + 0x38  → shields（0x38-0x3E）
```

★DQ3 の初期装備は「ぶき・よろい・たて」の 3 つで、⚠ 上の 3 バイトは
**別々の 3 つの範囲**にきれいに落ちます。番地がずれていれば、こうはなりません。
⚠ （★品の名前はここに書きません。方針 §3 / `test_名前をソースに持っていない`）
"""

from __future__ import annotations

#: ★袋の先頭（⚠ 逆アセンブルの `_players_inventory_list`）
INVENTORY_ADDR = 0x077C
#: ★1 人ぶんの枠
SLOTS_PER_PC = 8
#: ★人数
PARTY_SIZE = 4

#: ⚠ 空き枠
EMPTY_SLOT = 0xFF
#: ★装備中の旗
EQUIP_BIT = 0x80
#: ★ID を取り出すマスク（⚠ `ITEM_TYPE_MASK = $7F`）
TYPE_MASK = 0x7F
#: ⚠ 「品なし」（★`ITEM_SWORD_HORNED = $7F` の流用）
NO_ITEM_ID = 0x7F

#: ★★ 分類 ― `(最小, 最大, 名前)`。⚠ **範囲そのものが分類**（表引きではない）
CATEGORIES: tuple[tuple[int, int, str], ...] = (
    (0x00, 0x1F, "ぶき"),
    (0x20, 0x37, "よろい"),
    (0x38, 0x3E, "たて"),
    (0x3F, 0x46, "かぶと"),
    (0x47, 0x4B, "そうしょくひん"),
    (0x4C, 0x4F, "どうぐ"),
    (0x50, 0x7C, "どうぐ"),
)

#: ★装備できる分類（⚠ `bit7` が立ちうるもの）
EQUIPPABLE = ("ぶき", "よろい", "たて", "かぶと", "そうしょくひん")


def category_of(item_id) -> str:
    """★その ID の分類。⚠ 分からなければ `不明`（**名前を作らない**）。"""
    if item_id is None:
        return "なし"
    value = int(item_id) & TYPE_MASK
    if value == NO_ITEM_ID:
        return "なし"
    for low, high, name in CATEGORIES:
        if low <= value <= high:
            return name
    return "不明"                          # ⚠ 0x7D..0x7E など


def is_equippable(item_id) -> bool:
    """⚠ 装備できる分類か（★`bit7` の意味を確かめるときに使う）。"""
    return category_of(item_id) in EQUIPPABLE


def label_of(item_id, name=None) -> str:
    """★画面に出す 1 行。⚠ 名前を知らなければ**知らないと分かる形**で出す。

    ```text
    覚えている    （画面で見た名前をそのまま）
    まだ見ていない たて（品 0x38）
    品なし        （なし）
    ```

    ⚠⚠ 「品 56」のような**裸の番号だけ**にしません。
      ★何の種類かは ROM の構造から分かるので、そこまでは出します。
    """
    if item_id is None or (int(item_id) & TYPE_MASK) == NO_ITEM_ID:
        return "（なし）"
    if name:
        return str(name)
    value = int(item_id) & TYPE_MASK
    return "%s（品 0x%02X）" % (category_of(value), value)


def slot_of(byte: int) -> dict | None:
    """★袋の 1 枠を解く。⚠ 空きなら `None`。"""
    if byte is None or byte == EMPTY_SLOT:
        return None
    value = int(byte)
    item_id = value & TYPE_MASK
    if item_id == NO_ITEM_ID:
        return None
    return {
        "raw": value,
        "item_id": item_id,
        "equipped": bool(value & EQUIP_BIT),
        "category": category_of(item_id),
    }


def inventory_of(ram, *, addr: int = INVENTORY_ADDR) -> list[list[dict]]:
    """★4 人ぶんの袋（⚠ 空き枠は落とす）。

    @param ram  ★2KB の作業 RAM（セーブステートの `RAM` でよい）
    """
    out = []
    for pc in range(PARTY_SIZE):
        base = addr + pc * SLOTS_PER_PC
        slots = []
        for i in range(SLOTS_PER_PC):
            index = base + i
            if index >= len(ram):
                break
            got = slot_of(ram[index])
            if got is not None:
                got["slot"] = i
                slots.append(got)
        out.append(slots)
    return out


def known_ids(ram, *, addr: int = INVENTORY_ADDR) -> list[int]:
    """★いま袋にある品の ID（⚠ 並び順のまま。名前を覚えるときに使う）。"""
    out = []
    for slots in inventory_of(ram, addr=addr):
        out.extend(s["item_id"] for s in slots)
    return out
