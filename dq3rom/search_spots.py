"""「しらべる」の升表 ― DQ3 の汎用イベント表（RX3-0012 / 2026-09-16）。

## ★★ これが `RX3-0012` の最後の宿題「汎用のイベント表」でした

⚠ 2026-08-30 の時点では「イベント宝箱の入口には届いたが、通し番号の出方が
合わない」で止まっていました。★止まっていた理由は**配列の長さの見積もり**で、
表そのものは bank12 `$9ECF` にあります。

```text
bank12 $9AB9   屋内の走査。4 バイト x 26 件（★終端は CPX #$68 = 104 バイト）
bank12 $9B94   世界地図の走査。★その直後の 3 バイト 1 件だけ
```

## 表の形（confirmed / コード）

    屋内   { map, x, y|種別, 引数 }         ★map は $8B、x は $30、y は $31 と比べる
    世界   { x, y, 引数 }                   ★x は $2A、y は $2B と比べる

⚠⚠ **種別は y バイトの上位 2 ビット**です（★y 自身は下位 6 ビット）。
走査が 3 通りの比べ方を順に試すので、そこで枝が分かれます。

```text
$9AD1  CMP $31        そのまま一致      → 種別 0 = EVENT   ($9B21 へ / 引数 = 枝 0..4)
$9AD7  AND #$7F       bit7 だけ落とす   → 種別 2 = SCRIPT  ($9AF3 へ / 引数 = 会話など)
$9ADD  AND #$3F       bit7+bit6 を落とす → 種別 1 = ITEM    ($9BB1 へ / ★隠し道具)
```

## ★★ 隠し道具の通し番号（⚠ ここが 2026-08-30 に合わなかったところ）

```text
$9BD5  TXA / LSR / LSR / CLC / ADC #$B6 / STA $60A8
```

X は 4 件目のバイト（`4k+3`）を指しているので `X >> 2 = k`。つまり

    隠し道具 k の通し番号 = k + 182

★種別 ITEM の件は k = 18..25 なので、通し番号は **200..207** です。

⚠⚠ 2026-08-30 に「193 件（0..192）の範囲を超える」と書いて止めたのは、
★**配列を 193 ビットだと思い込んでいた**からでした。実際の配列は
`$608E`..`$60A7` の **26 バイト = 208 ビット**で、200..207 はその中に収まります
（★`$60A8` は「いま見ている通し番号」の置き場で、配列のすぐ後ろ）。

- 0..192   … 個数表の宝箱（`dq3rom/chests.py`）
- 193..199 … ⚠ 使われていない
- 200..207 … ★ここの隠し道具 8 件
- 208      … ⚠ 世界地図の 1 件が `$60A8` に**書く**が、印は読まない
             （★引数の bit7 が立っていて `$9BF9` へ逸れるため）

## ⚠ 分かっていないこと

- ★種別 EVENT の引数 0..4 が何を起こすかは、枝を 1 本しか読んでいません
  （引数 0 = `$9B34` が NPC を 1 体出す）。⚠ 残り 4 本は未確認です。
- ★種別 SCRIPT の引数は会話番号らしい（`$9AF3` → `$9995`）。⚠ 裏取り前。
- ⚠ 道具の名前は出しません。★中身の表は同梱しない方針（`dq3rom/chests.py`）。
"""

from __future__ import annotations

import dataclasses

from .profile import Identified

#: 表のある場所
TABLE_BANK = 12
TABLE_ADDR = 0x9ECF

#: 屋内の走査と、その終端（★`CPX #$68`）
SCAN_ADDR = 0x9AB9
LOCAL_BYTES = 0x68
RECORD = 4

#: 世界地図の走査（★表の 104 バイト目から 3 バイト）
WORLD_SCAN_ADDR = 0x9B94
WORLD_AT = LOCAL_BYTES

#: 通し番号を作る所と、その下駄（`ADC #$B6`）
SERIAL_ADDR = 0x9BD5
SERIAL_BASE = 0xB6

#: 種別（★y バイトの上位 2 ビット）
EVENT, ITEM, SCRIPT = 0, 1, 2
KIND_NAME = {EVENT: "event", ITEM: "item", SCRIPT: "script"}

#: 世界地図の 1 件（⚠ 屋内とは形が違うので分けて呼ぶ）
WORLD = "world"

#: ★走査そのもの。⚠ 1 バイトでも違ったら、式のほうを疑う
_SCAN_CODE = bytes.fromhex(
    "a200"        # LDX #$00
    "bdcf9e"      # LDA $9ECF,X      ; map
    "e8"          # INX
    "c58b"        # CMP $8B
    "d01f"        # BNE +
    "bdcf9e"      # LDA $9ECF,X      ; x
    "e8"          # INX
    "c530"        # CMP $30
    "d018"        # BNE +
    "bdcf9e"      # LDA $9ECF,X      ; y|種別
    "e8"          # INX
    "c531"        # CMP $31          ; 種別 0
    "f04e"        # BEQ event
    "297f"        # AND #$7F
    "c531"        # CMP $31          ; 種別 2
    "f01a"        # BEQ script
    "293f"        # AND #$3F
    "c531"        # CMP $31          ; 種別 1
    "d005"        # BNE +
    "4cb19b"      # JMP $9BB1        ; item
    "e8e8e8"      # INX ×3           ; ★1 件 = 4 バイト
    "e068"        # CPX #$68         ; ★終端
    "d0d2"        # BNE loop
)

#: ★世界地図の走査
_WORLD_CODE = bytes.fromhex(
    "a268"        # LDX #$68
    "bdcf9e"      # LDA $9ECF,X
    "e8"          # INX
    "c52a"        # CMP $2A
    "d007"        # BNE +
    "bdcf9e"      # LDA $9ECF,X
    "c52b"        # CMP $2B
    "f013"        # BEQ $9BB8
)

#: ★通し番号の作り方
_SERIAL_CODE = bytes.fromhex(
    "8a"          # TXA
    "4a4a"        # LSR ×2
    "18"          # CLC
    "69b6"        # ADC #$B6
    "8da860"      # STA $60A8
)


class SpotLayoutError(Exception):
    """ROM が想定と違う。⚠ 握りつぶさず、何が違ったかを見せる。"""


@dataclasses.dataclass(frozen=True)
class Spot:
    """「しらべる」で何かが起きる升 1 つ。"""

    index: int
    kind: str
    map_id: int | None
    x: int
    y: int
    arg: int

    @property
    def item_id(self) -> int | None:
        """★隠し道具の品番（⚠ 種別が ITEM のときだけ）。"""
        return self.arg & 0x7F if self.kind == KIND_NAME[ITEM] else None

    @property
    def serial(self) -> int | None:
        """★取ったかの通し番号（⚠ 種別が ITEM のときだけ）。"""
        return serial_of(self.index) if self.kind == KIND_NAME[ITEM] else None

    def to_json(self) -> dict:
        out = {
            "spot_id": f"spot_{self.index:02d}",
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "arg": f"0x{self.arg:02X}",
        }
        if self.map_id is not None:
            out["map_id"] = self.map_id
        if self.serial is not None:
            out["chest_serial"] = self.serial
            out["item_id"] = self.item_id
        return out


def serial_of(index: int) -> int:
    """★升の番号 → 取ったかの通し番号。ルーチンの計算をそのまま写しただけ。"""
    if not 0 <= index <= WORLD_AT // RECORD:
        raise ValueError(f"升の番号は 0..{WORLD_AT // RECORD}: {index}")
    return index + SERIAL_BASE


def verify(ident: Identified) -> list[str]:
    """★ROM が想定どおりかを見る。空なら一致。

    ⚠ 「表があるか」ではなく**走査のコードそのもの**を見る。★表の位置も
    長さも、このコードが決めている（`CPX #$68` が終端）。
    """
    problems: list[str] = []
    prg = ident.rom.prg
    for addr, want, name in ((SCAN_ADDR, _SCAN_CODE, "屋内の走査"),
                             (WORLD_SCAN_ADDR, _WORLD_CODE, "世界地図の走査"),
                             (SERIAL_ADDR, _SERIAL_CODE, "通し番号の作り方")):
        off = ident.prg_offset(TABLE_BANK, addr)
        got = prg[off:off + len(want)]
        if got != want:
            problems.append(f"{name} bank{TABLE_BANK} ${addr:04X} が違う: "
                            f"{got.hex()} ≠ {want.hex()}")
    return problems


def read_spots(ident: Identified) -> list[Spot]:
    """表を全件起こす。⚠ コードが違っていたら読まずに投げる。"""
    problems = verify(ident)
    if problems:
        raise SpotLayoutError(" / ".join(problems))
    prg = ident.rom.prg
    off = ident.prg_offset(TABLE_BANK, TABLE_ADDR)
    out: list[Spot] = []
    for k in range(WORLD_AT // RECORD):
        mid, x, raw_y, arg = prg[off + k * RECORD: off + k * RECORD + RECORD]
        kind = raw_y >> 6
        if kind not in KIND_NAME:
            # ⚠ 上位 2 ビットが 11 の件は走査の枝が無い。★黙って混ぜない
            raise SpotLayoutError(f"升 {k} の種別が 3（y=0x{raw_y:02X}）")
        out.append(Spot(index=k, kind=KIND_NAME[kind], map_id=mid,
                        x=x, y=raw_y & 0x3F, arg=arg))
    wx, wy, warg = prg[off + WORLD_AT: off + WORLD_AT + 3]
    out.append(Spot(index=WORLD_AT // RECORD, kind=WORLD, map_id=None,
                    x=wx, y=wy, arg=warg))
    return out


def hidden_items(ident: Identified) -> list[Spot]:
    """★隠し道具だけ（⚠ 通し番号 200..207 を持つ 8 件）。"""
    return [s for s in read_spots(ident) if s.kind == KIND_NAME[ITEM]]


def to_json(ident: Identified) -> list[dict]:
    """World Model の `events` に載せる形。"""
    return [s.to_json() for s in read_spots(ident)]


def summary(spots: list[Spot]) -> dict:
    kinds: dict[str, int] = {}
    for s in spots:
        kinds[s.kind] = kinds.get(s.kind, 0) + 1
    return {"total": len(spots), "kinds": kinds,
            "serials": sorted(s.serial for s in spots if s.serial is not None)}


__all__ = ["EVENT", "ITEM", "SCRIPT", "WORLD", "KIND_NAME", "Spot",
           "SpotLayoutError", "serial_of", "verify", "read_spots",
           "hidden_items", "to_json", "summary"]
