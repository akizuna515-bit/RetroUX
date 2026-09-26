"""DQ3 のイベントフラグ領域（RX3-0012 / 2026-08-30）。

## 仕組み（すべて日本版 ROM から。⚠ 表は同梱しない）

汎用の「フラグを立てる」ルーチンが bank13 `$BF94` にある。

    $BF94  STY $60C0        ; ★Y の退避
    $BF97  STX $60C1        ; ★X の退避
    $BF9A  PHA
    $BF9B  AND #$07 → Y     ; ビット番号
    $BF9E  PLA
    $BF9F  LSR ×3   → X     ; バイト番号
    $BFA3  LDA $BFB3,Y      ; ビット表 01 02 04 08 10 20 40 80
    $BFA6  ORA $60B5,X
    $BFA9  STA $60B5,X      ; ★ここで立つ
    $BFAC  LDX $60C1
    $BFAF  LDY $60C0
    $BFB2  RTS

つまり:

    フラグ n の在り処 = ($60B5 + (n >> 3)) の bit (n & 7)

## ★裏取り（独立に見つけた 2 件と一致した）

`RX3-0011` は宝箱のコードから、この式とは**別の道**で 2 つの条件を見つけていた。
その 2 つを、この式に通すと同じ所を指す。

| 見つかっていた条件 | この式で言うと |
| --- | --- |
| map 117: `$60B7` の bit7（bank12 `$9DA0`） | フラグ 23 |
| map 98: `$60CD` の bit5（bank0 `$AE4C`） | フラグ 197 |

★フラグ 23 は bank13 `$B590` / `$B8A8` が `LDA #$17` で立てている。
⚠ つまり「立てる側」と「読む側」が別々に見つかって、同じ番地で合流した。

## ⚠ 分かっていないこと

- ★**配列の長さは確定していない。** 実測で見えるのはフラグ 23〜205
  （`$60B7`〜`$60CE`）。⚠ 「0〜255 が全部使える」とは書かない。
- ⚠ `$60C0` / `$60C1` は**このルーチン自身の退避先**で、配列の中にある。
  そこに当たるフラグ番号は 88〜103。★実測した呼び出しに 88〜103 は 1 つも無い
  （87 の次が 172）。⚠ ただし「無いのを見た」だけで、禁止の根拠は取れていない。
- ⚠ 立てる側しか汎用ルーチンが無い。**読む側は呼び出し場所ごとに直書き**
  （`BIT $60B7` など）なので、ここでは拾えない。

## 出典と確度

- 式・ビット表・退避先 = **confirmed**（日本版 ROM のコードそのもの）
- フラグ番号の一覧 = **confirmed だが網羅ではない**。★`LDA #imm` が直前にある
  呼び出しだけを拾っている（⚠ 番号を計算して渡す道があれば漏れる）
"""

from __future__ import annotations

import dataclasses

from .profile import Identified

#: フラグ配列の先頭（WRAM）
FLAG_BASE = 0x60B5

#: 汎用の「フラグを立てる」ルーチン
SETTER_BANK = 13
SETTER_ADDR = 0xBF94

#: ビット表（ルーチンのすぐ後ろ）
BIT_TABLE_ADDR = 0xBFB3
BIT_TABLE = bytes((0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80))

#: ⚠ ルーチン自身が X / Y を退避する先。★配列の中にある
SCRATCH = (0x60C0, 0x60C1)

#: ★`JSR $BF94` のバイト列。⚠ 他バンクにも同じ 3 バイトは現れる（後述）
_JSR_SETTER = bytes((0x20, SETTER_ADDR & 0xFF, SETTER_ADDR >> 8))

#: 直前の `LDA #imm`
_LDA_IMM = 0xA9

#: ★ルーチンの実体。⚠ ここが 1 バイトでも違ったら、式のほうを疑う
_SETTER_CODE = bytes.fromhex(
    "8cc060"      # STY $60C0
    "8ec160"      # STX $60C1
    "48"          # PHA
    "2907"        # AND #$07
    "a8"          # TAY
    "68"          # PLA
    "4a4a4a"      # LSR ×3
    "aa"          # TAX
    "b9b3bf"      # LDA $BFB3,Y
    "1db560"      # ORA $60B5,X
    "9db560"      # STA $60B5,X
    "aec160"      # LDX $60C1
    "acc060"      # LDY $60C0
    "60"          # RTS
)


class FlagLayoutError(Exception):
    """ROM が想定と違う。⚠ 握りつぶさず、何が違ったかを見せる。"""


@dataclasses.dataclass(frozen=True)
class Location:
    """フラグ 1 つの在り処。"""

    number: int
    address: int
    bit: int

    @property
    def mask(self) -> int:
        return 1 << self.bit

    @property
    def flag_id(self) -> str:
        return f"flag_{self.number:03d}"

    @property
    def on_scratch(self) -> bool:
        """⚠ ルーチン自身の退避先に当たる番号か。"""
        return self.address in SCRATCH

    def to_json(self) -> dict:
        return {
            "flag_id": self.flag_id,
            "number": self.number,
            "address": f"0x{self.address:04X}",
            "bit": self.bit,
            "mask": f"0x{self.mask:02X}",
        }


@dataclasses.dataclass(frozen=True)
class SetCall:
    """`JSR $BF94` の呼び出し 1 件。"""

    bank: int
    address: int
    number: int

    def to_json(self) -> dict:
        return {"bank": self.bank, "address": f"0x{self.address:04X}"}


def address_of(number: int) -> Location:
    """フラグ番号 → 在り処。★ルーチンの計算をそのまま写しただけ。"""
    if not 0 <= number <= 0xFF:
        raise ValueError(f"フラグ番号は 0..255: {number}")
    return Location(number=number,
                    address=FLAG_BASE + (number >> 3),
                    bit=number & 7)


def verify(ident: Identified) -> list[str]:
    """★ROM が想定どおりかを見る。空なら一致。

    ⚠ 「入れ物があるか」ではなく**中身のバイト列**を見る。
    """
    problems: list[str] = []
    prg = ident.rom.prg
    off = ident.prg_offset(SETTER_BANK, SETTER_ADDR)
    got = prg[off:off + len(_SETTER_CODE)]
    if got != _SETTER_CODE:
        problems.append(
            f"bank{SETTER_BANK} ${SETTER_ADDR:04X} のコードが違う: "
            f"{got.hex()} ≠ {_SETTER_CODE.hex()}")
    toff = ident.prg_offset(SETTER_BANK, BIT_TABLE_ADDR)
    table = prg[toff:toff + 8]
    if table != BIT_TABLE:
        problems.append(f"ビット表が違う: {table.hex()} ≠ {BIT_TABLE.hex()}")
    return problems


def set_calls(ident: Identified) -> list[SetCall]:
    """`JSR $BF94` の呼び出しを拾う。

    ⚠ **bank13 の中だけ**を見る。★`$BF94` は切り替え窓（`$8000-$BFFF`）に
    あるので、他のバンクのコードからは届かない。⚠ それでも同じ 3 バイトは
    現れる——bank4 に 3 件ある。★そこは別のルーチン（`LDX $51` から始まる）で、
    拾うと嘘になる。

    ⚠ 直前が `LDA #imm` でない呼び出しは**黙って捨てない**。番号が分からない
    ものは `set_calls` には出ず、`verify_scan` が件数の食い違いとして出す。
    """
    prg = ident.rom.prg
    start = ident.prg_offset(SETTER_BANK, 0x8000)
    end = start + len(ident.window(SETTER_BANK))
    out: list[SetCall] = []
    i = start
    while True:
        i = prg.find(_JSR_SETTER, i, end)
        if i < 0:
            break
        if i - 2 >= start and prg[i - 2] == _LDA_IMM:
            out.append(SetCall(bank=SETTER_BANK,
                               address=0x8000 + (i - start),
                               number=prg[i - 1]))
        i += 1
    return out


def scan_totals(ident: Identified) -> dict:
    """★拾えた数と、拾えなかった数を**両方**返す。

    ⚠ 「N 件見つけた」だけだと、取りこぼしが見えない（`0 件は通っていない
    だけ` の教訓）。
    """
    prg = ident.rom.prg
    start = ident.prg_offset(SETTER_BANK, 0x8000)
    end = start + len(ident.window(SETTER_BANK))
    total = 0
    i = start
    while True:
        i = prg.find(_JSR_SETTER, i, end)
        if i < 0:
            break
        total += 1
        i += 1
    named = set_calls(ident)
    return {"calls": total, "with_literal": len(named),
            "without_literal": total - len(named)}


def build(ident: Identified) -> list[Location]:
    """実測できたフラグを、番号順に返す。

    ⚠ 「使われているフラグの全部」ではない（読む側は直書きなので拾えない）。
    """
    numbers = sorted({c.number for c in set_calls(ident)})
    return [address_of(n) for n in numbers]


def to_json(ident: Identified) -> list[dict]:
    """World Model の `flags` に載せる形。"""
    by_number: dict[int, list[SetCall]] = {}
    for c in set_calls(ident):
        by_number.setdefault(c.number, []).append(c)
    out = []
    for loc in build(ident):
        d = loc.to_json()
        d["set_by"] = [c.to_json() for c in by_number[loc.number]]
        d["confidence"] = "confirmed"
        d["source"] = "jp_rom"
        out.append(d)
    return out
