"""呪文がかき消される場所を ROM から読む（RX3-0320 / 2026-09-20）。

⚠⚠ 依頼者「save9 呪文をかきけすダンジョンでは、呪文をつかわないようにしたい（ROM、RAM解析要）」
★依頼者「おそらくピラミッド地下も出てくると思う」→ ⚠ **そのとおりでした**（`$CF` / `$D0`）。

## ★ゲームの持ち方: **表ではなく、1 本の関数の比較の並び**

⚠ 「場所ごとの属性の表」はありません。★bank 0 の 1 か所に、こう書いてあるだけです。

```text
bank0 CPU $A12C（PRG 0x00212C / JP ROM で 1 か所だけ）

  A5 2F  29 01  F0 ..      LDA $2F / AND #$01 / BEQ → ★世界地図なら使える
  A5 8B                    LDA $8B（map 番号）
  C9 38  F0 ..             CMP #$38 / BEQ → ⚠ 消される
  C9 C3  90 ..             CMP #$C3 / BCC → ★使える（$C3 未満）
  C9 C6  90 ..             CMP #$C6 / BCC → ⚠ 消される（= $C3〜$C5）
  C9 CF  F0 ..             CMP #$CF / BEQ → ⚠ 消される
  C9 D0  D0 ..             CMP #$D0 / BNE → ★使える
  18 60                    CLC / RTS  ＝ ⚠ 呪文が消される
  38 60                    SEC / RTS  ＝ ★呪文が使える
```

## ⚠ だから「読む命令」から**値そのもの**を取り出します

★番号をここに書き写すと、⚠ ROM が違ったときに黙って嘘をつきます。
→ ★上の**骨格**を探し、`CMP #imm` の 5 つの値を**読み出し**ます。
⚠ 骨格が 1 か所に無ければ `None` を返します（★推測しない）。

## ⚠ これは「戦闘のフラグ」ではありません

```text
フィールド  ★毎回この関数を呼ぶだけ（⚠ 対応する RAM のフラグは無い）
戦闘        ★戦闘の初めに RAM $0568 の bit4 へ写す
            ⚠ ただし パルプンテ でも同じ bit が立つ（★場所専用ではない）
```

★だから RetroUX は **`$2F` と `$8B` から自分で計算**します（⚠ ゲームと同じやり方）。

## ⚠⚠ MP は判定より**先に**引かれます

★実機では「唱える → MP が減る → しかし じゅもんは かきけされた！」の順です。
⚠ つまり**唱えるだけ損**なので、★RetroUX は最初から選ばないようにします。
"""
from __future__ import annotations

import re

#: ★居場所の種別（`$2F`）の「地図の中」の bit（⚠ ROM の `AND #$01` から読む）
KIND_ADDR = 0x002F
MAP_ADDR = 0x008B

#: ★判定の骨格（⚠ `CMP #imm` の 5 つだけを読み出す）
#:
#:   ⚠ 分岐の飛び先（`F0 18` など）まで固定します。★そこが違えば別の関数です。
_PATTERN = (rb"\xA5\x2F\x29(.)\xF0\x18\xA5\x8B"
            rb"\xC9(.)\xF0\x10"
            rb"\xC9(.)\x90\x0E"
            rb"\xC9(.)\x90\x08"
            rb"\xC9(.)\xF0\x04"
            rb"\xC9(.)\xD0\x02"
            rb"\x18\x60\x38\x60")


def read_rule(prg: bytes) -> dict | None:
    """★ROM から判定の中身を読む。⚠ 1 か所に無ければ `None`。

    戻り値:

    ```text
    {"at": PRG offset, "kind_mask": 1, "maps": (0x38, 0xC3, 0xC4, 0xC5, 0xCF, 0xD0)}
    ```
    """
    hits = list(re.finditer(_PATTERN, prg, re.S))
    if len(hits) != 1:
        return None                     # ⚠ 0 か所（別の ROM）／2 か所（★骨格が甘い）
    got = hits[0]
    mask = got.group(1)[0]
    eq1, lo, hi, eq2, eq3 = (g[0] for g in got.groups()[1:])
    if not (lo < hi):
        return None                     # ⚠ 範囲が逆（★読み違い）
    maps = [eq1] + list(range(lo, hi)) + [eq2, eq3]
    return {"at": got.start(), "kind_mask": mask,
            "maps": tuple(sorted(set(maps)))}


def no_magic_maps(prg: bytes) -> tuple:
    """★呪文が消される map 番号（⚠ 読めなければ空）。"""
    got = read_rule(prg)
    return got["maps"] if got else ()


def blocks_magic(prg: bytes, loc_kind, map_id) -> bool:
    """★いまの場所で呪文が消されるか（⚠ 読めなければ `False` = 今までどおり）。

    ⚠ ゲームと同じ順で見ます: **地図の中**（`$2F & 1`）かつ **map 番号が一致**。
    """
    got = read_rule(prg)
    if got is None or loc_kind is None or map_id is None:
        return False
    try:
        kind, mid = int(loc_kind), int(map_id)
    except (TypeError, ValueError):
        return False
    if not (kind & got["kind_mask"]):
        return False                    # ★世界地図・アレフガルド広域では使える
    return mid in got["maps"]


__all__ = ["KIND_ADDR", "MAP_ADDR", "read_rule", "no_magic_maps", "blocks_magic"]
