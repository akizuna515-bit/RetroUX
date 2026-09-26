"""ダメージ床（毒の沼・バリア）の判定（RX3-0262 / 2026-09-16）。

## ★判定そのもの = bank14 `$B4B1`（confirmed / コード）

歩くたびに、⚠ **隊列の一人ひとり**について、その人が立っている升を見ます。

```text
$B4B1  LDY $67          ; ★隊列の番号（0..3）
$B4B3  LDX $93,Y        ; ★その人が立っている升のタイル（$93..$96）
$B4B5  LDA $9A          ; ★tileset
$B4B7  BNE $B4C3        ;   0 以外 = ローカル
   --- 世界地図（tileset 0）---
$B4B9  CPX #$07         ; ★タイル 7
$B4BB  BNE $B4DA        ;   違えば何もしない
$B4BD  LDX #$02         ; ★ダメージ 2
$B4BF  LDY #$16         ; ★効果の種類
$B4C1  BNE $B4EC
   --- ローカル ---
$B4C3  TXA / AND #$1F / TAX
$B4C7  LDA $6DE0,X      ; ★collision[tile & 31]
$B4CA  LDX #$02 / LDY #$16
$B4CE  CMP #$05         ; ★collision == 0x05 → ダメージ 2
$B4D0  BEQ $B4EC
$B4D2  LDX #$0F / LDY #$10
$B4D6  CMP #$06         ; ★collision == 0x06 → ダメージ 15
$B4D8  BEQ $B4EC
$B4DA  INC $67          ; 次の人へ
```

`$B4EC` が `STX $64 / STY $63`（★`$64` = 減る HP / `$63` = 効果の種類）。

## ★裏取り（⚠ 別々の道が 3 本そろった）

```text
① 世界地図の collision 表で 0x05 は **index 7 ただ 1 つ**。
   ★コードは世界地図でタイル番号 7 を直接見る近道をしているが、
   その 7 は「collision が 0x05 の升」そのもの（= ローカルと同じ意味）
② 世界地図のタイル 7 は **69 升**（★調べる前の見立てと一致）
③ 毒（状態異常）で歩くたびに減る枝（`$B3FA`）が **同じ `$64`** に 1 を入れる
   → ⚠ `$64` が「減る HP」であることの裏付け（★毒は 1 ダメージ）
```

## ⚠ 分かっていないこと

- ⚠ `$63`（`$16` / `$10`）は音の選び分けに使われる（`$B528` が `$84` / `$81`）。
  ★「毒の沼」「バリア」という**呼び名は ROM から出していません**。
  ⚠ ここでは**減る HP の量**でしか区別しません。
- ⚠ 実際に HP を減らすのは `$6B3E`（WRAM に写された routine）で、★ROM からは読めません。
- ⚠ アレフガルド（`loc_kind` 2）でも `$9A` が 0 になるかは**実機で未確認**。
  ★0 なら同じ規則（タイル 7）が当たります。
- ⚠ この module は**床のダメージだけ**です。★毒の状態異常（`$B3DE`）は別。
"""

from __future__ import annotations

from .profile import Identified

#: 判定のある場所
BANK = 14
ADDR = 0xB4B1

#: ★ローカルの地図: `collision` の値 → 減る HP
LOCAL: dict[int, int] = {0x05: 2, 0x06: 15}

#: ★世界地図: タイル番号 → 減る HP（⚠ collision ではなくタイル番号を直接見る）
WORLD_TILE = 0x07
WORLD_DAMAGE = 2

#: ⚠ 効果の種類（★音の選び分け。呼び名ではない）
KIND = {0x05: 0x16, 0x06: 0x10}

#: ★隊列の一人ひとりが立っている升のタイル（`$93` + 隊列の番号）
PARTY_TILE_BASE = 0x0093

#: ★判定そのもの。⚠ 1 バイトでも違ったら、式のほうを疑う
_CODE = bytes.fromhex(
    "a467"        # LDY $67
    "b693"        # LDX $93,Y
    "a59a"        # LDA $9A
    "d00a"        # BNE ローカルへ
    "e007"        # CPX #$07      ; ★世界地図のタイル 7
    "d01d"        # BNE 次の人へ
    "a202"        # LDX #$02      ; ★ダメージ 2
    "a016"        # LDY #$16
    "d029"        # BNE 当てる
    "8a"          # TXA
    "291f"        # AND #$1F
    "aa"          # TAX
    "bde06d"      # LDA $6DE0,X   ; ★collision
    "a202"        # LDX #$02      ; ★ダメージ 2
    "a016"        # LDY #$16
    "c905"        # CMP #$05
    "f01a"        # BEQ 当てる
    "a20f"        # LDX #$0F      ; ★ダメージ 15
    "a010"        # LDY #$10
    "c906"        # CMP #$06
    "f012"        # BEQ 当てる
)

#: ★`STX $64 / STY $63`（⚠ ここで「減る HP」と「効果の種類」が決まる）
APPLY_ADDR = 0xB4EC
_APPLY_CODE = bytes.fromhex("86648463")


class DamageLayoutError(Exception):
    """ROM が想定と違う。⚠ 握りつぶさず、何が違ったかを見せる。"""


def verify(ident: Identified) -> list[str]:
    """★ROM が想定どおりかを見る。空なら一致。

    ⚠ 「そういう値がある」ではなく**判定のコードそのもの**を見る。
    """
    problems: list[str] = []
    prg = ident.rom.prg
    for addr, want, name in ((ADDR, _CODE, "ダメージ床の判定"),
                             (APPLY_ADDR, _APPLY_CODE, "減る HP の置き場")):
        off = ident.prg_offset(BANK, addr)
        got = prg[off:off + len(want)]
        if got != want:
            problems.append(f"{name} bank{BANK} ${addr:04X} が違う: "
                            f"{got.hex()} ≠ {want.hex()}")
    return problems


def damage_of(collision: int | None) -> int | None:
    """★ローカルの地図: collision の値 → 減る HP。⚠ ダメージ床でなければ `None`。

    ⚠ 完全一致で見ます（★下位ニブルではない）。bit7 が立つ升は通れないので、
    ここに来る値は 0x05 / 0x06 そのものだけです。
    """
    if collision is None:
        return None
    return LOCAL.get(collision)


def world_damage_of(tile: int | None) -> int | None:
    """★世界地図: タイル番号 → 減る HP。⚠ ダメージ床でなければ `None`。"""
    if tile is None:
        return None
    return WORLD_DAMAGE if tile == WORLD_TILE else None


def is_damage(collision: int | None) -> bool:
    """★ローカルの地図で、その升がダメージ床か。"""
    return damage_of(collision) is not None


__all__ = ["BANK", "ADDR", "APPLY_ADDR", "LOCAL", "WORLD_TILE", "WORLD_DAMAGE",
           "KIND", "PARTY_TILE_BASE", "DamageLayoutError", "verify",
           "damage_of", "world_damage_of", "is_damage"]
