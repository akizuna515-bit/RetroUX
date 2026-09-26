"""誰がどの呪文を覚えているか（RX3-0071 / 2026-09-07）。

## ★配列（confirmed / ROM のコード）

```text
bank0 $9A29  LDA $CE / ASL x3 / STA $13    ; ★$13 = 人 x 8
bank0 $9A30  LDA $42 / PHA / AND #$07      ; ★$0E = 呪文の枠 & 7
bank0 $9A38  PLA / LSR x3 / CLC / ADC $13  ; ★Y  = (枠 >> 3) + 人 x 8
bank0 $9A3F  LDA $078C,Y / STA $0F         ; ★その 1 バイト
bank0 $9A44  LDA $42 / AND #$18 / LSR x2   ; ★頁 = 枠の bit4-3
bank0 $9A4A  LDA $9C76,X → $10/$11         ; ★頁 → 8 個ぶんの表
```

    人 c / 枠 n の在り処 = ($078C + c * 8 + (n >> 3)) の bit (n & 7)    ← ★LSB から

⚠⚠ ビットの向きは `$998A` が決めています。

```text
$998A  LDY $0E / CPY #$08 / BCS 無効
$9990  INY / ROR $0F / DEY / BNE          ; ★(枠 & 7) + 1 回 **右**シフト
$9996  BCC 無効                           ; ★桁上がり = もとの bit (枠 & 7)
```

⚠ `dq3rom/chest_flags.py`（宝箱）は **MSB から**です。★同じ ROM で並びが 2 通りあります。

## ⚠⚠ ビットは「呪文 ID」ではありません

★これが `RX3-0069` で仮説のまま止まった理由でした。

> ⚠ page0 bit0 = id 0x00（メラ）になり、★勇者が覚えるはずのない呪文が立つ

⚠ 立っているビットは**枠**で、★呪文そのものは表を 1 段引いた先にあります。

```text
$998A  LDA ($10),Y     ; ★Y = 枠 & 7 → ここで初めて呪文の番号が出る
```

★表は `$A2BA` から **8 個 x 12 ブロック**。⚠ ブロックは職業ごとに束ねられています。

```text
ブロック 0-3   ★勇者   （⚠ ライデイン / ギガデイン が入る = 勇者専用）
ブロック 4-7   ★魔法使い
ブロック 8-11  ★僧侶
ブロック 2     ⚠ 全部 $FF（★**勇者のページ 2 だけ**が空）
```

⚠⚠ ブロック 2 が空なのは**勇者だけ**です。★魔法使い（6）・僧侶（10）のページ 2 には
戦闘呪文が詰まっています（`BATTLE_PAGES` の註 / RX3-0326）。

## ⚠ まだ決まっていないこと

⚠⚠ **人の 8 バイトの何番目が、12 ブロックのどれになるか**は未確定です。

```text
★分かった  $9C76 の表（ブロック 0,1,2,3…）と $9C7E の表（ブロック 4,5,6,7…）の 2 本がある
⚠ 未確定  そのどちらを使うかを決めているのは `$D0` らしい（★職業？）が、追い切っていない
```

★だから、⚠ **この module は「どのビットが立っているか」までしか返しません**。
呪文の名前まで欲しいときは、`blocks()` を自分で引いてください（★責任の境目）。

## ★裏取り（2026-09-07 / ⚠ 依頼者の作業は要らなかった）

⚠ `RX3-0069` は「覚える前後のセーブを 2 つ撮ってもらう」で止まっていました。
★固定した写しのセーブ 10 本を読み直したら、**育っていく途中が全部入っていました**。

```text
人0  ―  ⊂  {0-0}  ⊂  {0-0, 0-1, 3-0}  ⊂  {0-0, 0-1, 0-2, 3-0}
人1  ―（★どのセーブでも空。⚠ 呪文を覚えない職）
人2  ―  ⊂  {4-1, 7-0}  ⊂  {4-1, 4-2, 4-5, 7-0}  ⊂  {…, 4-6}
人3  ―  ⊂  {0-0}  ⊂  {0-0, 0-2}  ⊂  {0-0, 0-2, 0-4}
```

⚠ どの人も**減りません**（★包含の鎖になる）。★覚えたものが消えないのと合います。
"""
from __future__ import annotations

#: ★RAM の先頭（⚠ `$078C`。★WRAM ではなく RAM）
BASE = 0x078C
#: ★1 人ぶんのバイト数
STRIDE = 8
#: ★人の数（⚠ パーティは 4 人 / `RX3-0019`）
SLOTS = 4
#: ★枠の総数（⚠ 1 人あたり `STRIDE * 8`）
FRAMES = STRIDE * 8

#: ★呪文の表（bank0 `$A2BA` から 8 個 x 12）。⚠ `$FF` は未使用
BLOCK_BASE = 0xA2BA
BLOCK_SIZE = 8
BLOCK_COUNT = 12
#: ★頁 → 表 の pointer（bank0）。⚠ 2 本ある（★どちらを使うかは未確定）
PAGE_TABLES = (0x9C76, 0x9C7E)
#: ⚠ 使われていない印
NO_SPELL = 0xFF


def bit_of(slot: int, frame: int) -> tuple[int, int]:
    """★`(人, 枠)` → `(RAM の番地, ビットのマスク)`。⚠ ビットは **LSB から**。"""
    if not 0 <= slot < SLOTS:
        raise ValueError("⚠ 人は 0..%d です: %r" % (SLOTS - 1, slot))
    if not 0 <= frame < FRAMES:
        raise ValueError("⚠ 枠は 0..%d です: %r" % (FRAMES - 1, frame))
    return BASE + slot * STRIDE + (frame >> 3), 1 << (frame & 7)


def learned(ram, slot: int) -> list[int] | None:
    """★その人が持っている枠の一覧。⚠ RAM が短ければ `None`（★空と混ぜない）。"""
    if ram is None or len(ram) < BASE + SLOTS * STRIDE:
        return None
    return [n for n in range(FRAMES)
            if ram[BASE + slot * STRIDE + (n >> 3)] & (1 << (n & 7))]


def raw(ram, slot: int) -> bytes | None:
    """★その人の 8 バイトそのもの（⚠ 一次情報を捨てない）。"""
    if ram is None or len(ram) < BASE + SLOTS * STRIDE:
        return None
    off = BASE + slot * STRIDE
    return bytes(ram[off:off + STRIDE])


def blocks(prg: bytes, prg_bank: int = 0) -> list[tuple[int, ...]]:
    """★`$A2BA` の 12 ブロック（★8 個ずつ）を返す。

    ⚠ ここが返すのは**呪文の番号**です。★名前は `dq3rom/names.py` の担当。
    """
    start = prg_bank * 0x4000 + (BLOCK_BASE - 0x8000)
    got = prg[start:start + BLOCK_SIZE * BLOCK_COUNT]
    if len(got) < BLOCK_SIZE * BLOCK_COUNT:
        raise ValueError("⚠ PRG が短すぎます")
    return [tuple(got[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE]) for i in range(BLOCK_COUNT)]


#: ★勇者の職業番号（⚠ `item_meta.CLASS_NAMES` と同じ）
HERO_CLASS = 0

#: ★ブロックの割り当て（★2026-09-08 / RX3-0125 で確定）
#:
#:   ```text
#:   勇者      bytes 0-3 → ブロック 0-3（★勇者だけの表 `_hero_spells_index`）
#:   それ以外  bytes 0-3 → ブロック 4-7（魔法使い系）/ bytes 4-7 → ブロック 8-11（僧侶系）
#:   ```
#:
#:   ⚠ 北米版 bank0 `_get_spell_related_data_ptr`: `Y = 人×8 + 系統×4 + (枠>>3)`、
#:     系統 = `($D0 & 3) - 1`（0 = 魔法使い / 1 = 僧侶）。★勇者は別の道で `人×8 + (枠>>3)`。
#:   ★固定セーブ 20 本すべてで Lv と一致した（勇者 Lv6 = メラ ホイミ ニフラム など）。
#:   ⚠ 転職しても bit は残るので、★元僧侶の戦士が回復を覚えている、が読める。
HERO_BLOCKS = (0, 1, 2, 3)
MAGE_BLOCKS = (4, 5, 6, 7)
PILGRIM_BLOCKS = (8, 9, 10, 11)

#: ★★ 戦闘で使えるのは各系統の**ページ 0・1・2**（⚠ ページ 3 が移動・メニュー用）。
#:
#:   ⚠⚠ 2026-09-20（RX3-0326）訂正: ここは長らく `(0, 1)` で、註にも
#:     「ページ 2 は未使用」と書いてありました。★**事実として誤り**です。
#:
#:   ★ROM の 12 ブロックを名前まで出して確かめました（`work/rom/DQ3_J.nes`）:
#:
#:   ```text
#:   block  2 勇p2  ★全部 $FF（⚠ **勇者だけ**が空。ここから全職へ一般化したのが誤りの元）
#:   block  6 魔p2  メラゾーマ メダパニ マヒャド ドラゴラム ベギラゴン モシャス イオナズン パルプンテ
#:   block 10 僧p2  フバーハ ベホマ ★ザラキ ベホマラー バギクロス ザオラル メガンテ ザオリク
#:   block  7 魔p3  リレミト ルーラ インパス トラマナ ラナルータ シャナク レムオル アバカム  ← ★移動
#:   block 11 僧p3  ホイミ キアリー ベホイミ キアリク ザオラル ベホマ ベホマラー ザオリク    ← ★メニュー用
#:   ```
#:
#:   → ⚠ この 1 行のせいで、★**ザラキ・イオナズン・ベギラゴン・ベホマラー・ザオリク等が
#:     AI からも呪文一覧からも見えていませんでした**。
#:   ⚠ ページ 3 は今までどおり外します（★`Catalog.field_spells` の担当 / RX3-0161）。
BATTLE_PAGES = (0, 1, 2)


def learned_ids(bytes8, class_id: int, blocks_table, *, battle_only: bool = True) -> list[int]:
    """★その人の 8 バイト + 職業 → 覚えている呪文 ID（RX3-0125 / CONFIRMED）。

    `bytes8`        … `raw(ram, slot)` の 8 バイト
    `class_id`      … `$0718` の下位 3 bit（★0 = 勇者）
    `blocks_table`  … `blocks(prg)`
    `battle_only`   … ★戦闘で使えるページだけ（⚠ 移動呪文は落とす）
    """
    if bytes8 is None or len(bytes8) < 8:
        return []
    pages = BATTLE_PAGES if battle_only else (0, 1, 2, 3)
    if int(class_id) & 7 == HERO_CLASS:
        plan = [(bytes8[p], HERO_BLOCKS[p]) for p in pages]
    else:
        plan = ([(bytes8[p], MAGE_BLOCKS[p]) for p in pages]
                + [(bytes8[4 + p], PILGRIM_BLOCKS[p]) for p in pages])
    out = []
    for byte, block in plan:
        row = blocks_table[block]
        for bit in range(8):
            if byte >> bit & 1 and row[bit] != NO_SPELL:
                out.append(row[bit])
    return out


__all__ = ["BASE", "STRIDE", "SLOTS", "FRAMES", "BLOCK_BASE", "BLOCK_SIZE",
           "BLOCK_COUNT", "PAGE_TABLES", "NO_SPELL", "HERO_CLASS", "HERO_BLOCKS",
           "MAGE_BLOCKS", "PILGRIM_BLOCKS", "BATTLE_PAGES",
           "bit_of", "learned", "raw", "blocks", "learned_ids"]
