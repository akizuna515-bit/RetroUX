"""ダンジョンの地形を読む（2026-08-02 / `$DD9D`-`$DDBA` の写し）。

★★★ **入力契約が確定しました。** ★★★

```
DD9D: LDA $1F / CMP #$02 / BCC $DDBB   ; ⚠ 種別2未満はそのまま
DDA3: LDA $0E / PHA                    ; ★y を退避
DDA5: LDA $0C / PHA                    ; ★x を退避
DDA9: LSR $0C                          ; ★★x を 1/2（論理セル座標）
DDAB: LSR $0E                          ; ★★y を 1/2
DDAD: JSR $DDBB                        ; ★地形を取る（結果は $0C）
DDB0: PLA / LSR                        ; ★退避した x の bit0 を C へ
DDB2: PLA / ROL                        ; ★退避した y を左シフトして C を入れる
DDB4: AND #$03                         ; ★★象限 = (y&1)*2 | (x&1)
DDB6: ORA $0C / STA $0C                ; ★★★地形に象限を **OR** する
```

★つまり:

```
地形ID  = 論理セル (x>>1, y>>1) の値      ← ★(生バイト & $E0) >> 3（**4刻み**）
壁補正  = wall_shape(...) を適用          ← $DE29-$DE9B
象限    = ((y & 1) << 1) | (x & 1)
$0C     = 壁補正の結果 | 象限              ← ★これが $DD64 の索引
```

★★★ **`>> 3`（4刻み）だから下位2ビットが空いていて、そこに象限が入ります。**

⚠⚠ 2026-08-02、`>> 5`（0-7）にして**非単調セルが 0%** になりました。
★`>> 3` に直したところ **82.9〜92.2%** へ跳ねました。
  `>> 5` だと象限のビットが地形と衝突します。

⚠ 私が観測から求めた「差分 `+0 / +8 / -2 / +6`」は、
**5バイト表の隣り合う4件の差**でした
（索引が `地形 | 象限` なので、象限が変わると表の次の行を引く）。

## ⚠ 範囲外の扱い（`$DDBB`）

```
DDBB: LDA $0C / STA $12 / LDA $0E / STA $13   ; ★調べる座標へ写す
DDC3: LDA $21 / CMP $0C / BCC →               ; ⚠ 幅より外なら
DDC9: LDA $20 / STA $0C / RTS                 ; ★★境界タイルID を返す
DDCE: LDA $22 / CMP $0E / BCC →               ; ⚠ 高さより外も同じ
```

★**外は「境界タイルID（`$20`）」**。⚠ 0 ではありません。
"""

from __future__ import annotations

#: ★種別2以上で座標を 1/2 する（`DD9F: CMP #$02`）
HALVED_KIND = 2


def quadrant(x: int, y: int) -> int:
    """象限（0-3）。★`DDB0`-`DDB4` の写し。

    ```
    PLA(x) / LSR      ; x の bit0 が C へ
    PLA(y) / ROL      ; y を左シフトして C を下位へ
    AND #$03
    ```

    ⚠ つまり **`((y & 1) << 1) | (x & 1)`**。
    """
    return ((y & 1) << 1) | (x & 1)


def read_cell(prg, header, x: int, y: int, cell_value) -> int:
    """`$0C` に入る値（地形ID | 象限）を返す。

    `cell_value(cx, cy)` は**論理セル**の値を返す関数。
    ⚠ 範囲外では `None` を返してください（ここで境界タイルへ直します）。

    ★種別2未満（世界地図・街）は 1/2 も象限も**しません**。
    """
    kind = header.kind
    if kind < HALVED_KIND:
        value = cell_value(x, y)
        return header.border_tile if value is None else value

    value = cell_value(x >> 1, y >> 1)
    if value is None:
        # ⚠ 範囲外は境界タイルID（`DDC9: LDA $20`）。★0 ではない
        return header.border_tile
    return value | quadrant(x, y)
