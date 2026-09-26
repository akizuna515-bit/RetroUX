"""扉と鍵（RX3-0014 / RX3-0078 / 2026-09-07）。

## ★実機なしで解けました

⚠ `RX3-0014` は「鍵の道具 ID を**実機で**確定する」で **BLOCKED** でした。
★ROM を辿ったら、⚠ **道具 ID も段位も静的に取れました**。

```text
とうぞくのかぎ  道具 88  → 段位 0  → ★$0B（どの鍵でも）の扉だけ
まほうのかぎ    道具 89  → 段位 1  → ★$0B と $0C
さいごのかぎ    道具 90  → 段位 3  → ★全部（$0D を含む）
```

## ★辿った道（⚠ 4 つが 1 本に繋がった）

```text
① bank12 $982E   扉のタイル型の下位ニブルで分岐（$0B / $0C / $0D）
                 ⚠ 段位 $B6 を LSR しながら見る
② bank12 $97E4   段位を作る入口 3 本（LDA #$03 / #$01 / #$00 → STA $B6）
③ ★BRK の飛び先表  arg 186 → $97E4 / 185 → $97E8 / 184 → $97EC
④ bank0  $AE80   `BRK 184; RTS` / `$AE84` = 185 / `$AE88` = 186（★小さな踏み台）
⑤ bank0  $B06D   ★道具を使ったときの script 表（3 バイト `<印> <ptr lo> <ptr hi>`）
                 ⚠ **索引 = 道具 ID - 73**
```

★⑤の裏取り: 索引 0..29 を道具の名前に直すと、⚠ **すべて「使える道具」**でした
（`しあわせのくつ`(73) … `やくそう`(101) / `どくけしそう`(102)）。
★武器・防具（0..72）は 1 つも入りません。⚠ 30 件が並んで合うので、偶然ではありません。

## ⚠ 段位ごとに開く扉（bank12 `$982E` をなぞった結果）

```text
段位 0 → $0B だけ
段位 1 → $0B と $0C
段位 3 → $0B と $0C と $0D
```

⚠ `$B6 = 2` は入口が作らない値です（★作れば `$0B` と `$0D` になりますが、使われません）。
"""
from __future__ import annotations

#: ★扉のタイル型の下位ニブル（`RX3-0007`）
DOOR_ANY, DOOR_MAGIC, DOOR_FINAL = 0x0B, 0x0C, 0x0D
DOOR_NIBBLES = (DOOR_ANY, DOOR_MAGIC, DOOR_FINAL)

#: ★鍵の道具 ID → 段位（⚠ 名前は ROM から引く。★ここには書かない）
KEY_ITEMS = {88: 0, 89: 1, 90: 3}

#: ★段位を作る入口（bank 12）と、そこへ飛ぶ BRK の arg
RANK_ENTRY = {0x97EC: 0, 0x97E8: 1, 0x97E4: 3}
RANK_BRK_ARG = {184: 0, 185: 1, 186: 3}
#: ★bank0 の踏み台（`BRK arg; RTS`）
RANK_STUB = {0xAE80: 0, 0xAE84: 1, 0xAE88: 3}

#: ★道具を使ったときの script 表（bank 0）。⚠ **索引 = 道具 ID - 73**
USE_TABLE_CPU = 0xB06D
USE_TABLE_BANK = 0
USE_TABLE_FIRST_ITEM = 73
USE_TABLE_STRIDE = 3


def rank_of(item_id: int) -> int | None:
    """★その道具の段位。⚠ 鍵でなければ `None`（★0 と混ぜない）。"""
    return KEY_ITEMS.get(int(item_id))


def party_rank(item_ids) -> int:
    """★持ち物ぜんぶから、いちばん強い段位（⚠ 鍵が無ければ -1）。"""
    got = [rank_of(i) for i in item_ids]
    got = [r for r in got if r is not None]
    return max(got) if got else -1


def opens(nibble: int, rank: int) -> bool:
    """★その段位でその扉が開くか（bank12 `$982E` のとおり）。

    ⚠ 扉でないタイルは `False`（★「通れる」とは言いません。★通行可否は別の話）。
    """
    a = int(nibble) & 0x0F
    if a == DOOR_FINAL:
        return (int(rank) >> 1) != 0          # ⚠ LSR $B6 → BNE
    if a == DOOR_MAGIC:
        return bool(int(rank) & 1)            # ⚠ LSR $B6 → BCS
    if a == DOOR_ANY:
        return True
    return False


def needed_key(nibble: int) -> int | None:
    """★その扉を開けるのに要る、いちばん弱い道具 ID。⚠ 扉でなければ `None`。"""
    a = int(nibble) & 0x0F
    if a not in DOOR_NIBBLES:
        return None
    for item_id, rank in sorted(KEY_ITEMS.items(), key=lambda kv: kv[1]):
        if opens(a, rank):
            return item_id
    return None                                # pragma: no cover ⚠ ありえない


def use_script_index(item_id: int) -> int | None:
    """★`$B06D` の表の索引。⚠ 表の外なら `None`。"""
    got = int(item_id) - USE_TABLE_FIRST_ITEM
    return got if got >= 0 else None


def read_use_table(prg: bytes, count: int) -> list[tuple[int, int]]:
    """★`$B06D` の表を `(印, 飛び先)` で読む（⚠ 中身の意味は未確定）。"""
    start = USE_TABLE_BANK * 0x4000 + (USE_TABLE_CPU - 0x8000)
    out = []
    for k in range(int(count)):
        a = start + k * USE_TABLE_STRIDE
        if a + 3 > len(prg):
            break
        out.append((prg[a], prg[a + 1] | (prg[a + 2] << 8)))
    return out


__all__ = ["DOOR_ANY", "DOOR_MAGIC", "DOOR_FINAL", "DOOR_NIBBLES", "KEY_ITEMS",
           "RANK_ENTRY", "RANK_BRK_ARG", "RANK_STUB", "USE_TABLE_CPU",
           "USE_TABLE_BANK", "USE_TABLE_FIRST_ITEM", "USE_TABLE_STRIDE",
           "rank_of", "party_rank", "opens", "needed_key",
           "use_script_index", "read_use_table"]
