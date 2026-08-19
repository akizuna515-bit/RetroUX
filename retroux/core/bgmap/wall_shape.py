"""壁向き補正（2026-08-02 / `$DE29`-`$DE9B` の写し）。

★★★ **これは世界地図（種別0）専用です。** ★★★

```
DDD6: LDA $1F / BEQ $DDDD    ; ★種別0（世界地図）だけ $DDDD へ
DDDA: JMP $DF7D              ; ★★街・ダンジョンは**全部こっち**
```

⚠⚠ 2026-08-02、私はこれをダンジョンにも当てていました。
★外したところ map `$40` の一致が上がり、依頼者の指摘（湖の中の
  謎の宝箱と赤い枠）も消えました。**ダンジョンから呼ばないでください。**

★ 当たっているように見えたのは「中心が `$04` 以外は素通し」だからで、
  `$04` になるセルだけが余計に書き換わっていました。

★★ **実コードから取りました。観測辞書ではありません。** ★★

⚠ 観測から作った規則表は、別のマップへ渡りませんでした
（`$40` の規則を `$3D` に当てて非単調 0/4）。★実コードに切り替えます。

## 元のコード（bank7）

```
DE29: JSR $DED4          ; ★中心の値を取る
DE2C: CMP #$04 / BNE →   ; ⚠ 中心が 4（壁）でなければ補正しない
DE33: LDY #$00 / STY $D4 / STY $05F4
DE3A: LDA $DEC8,Y / CLC / ADC $12 / STA $0C   ; ★x に近傍のずれ
DE42: LDA $DECC,Y / CLC / ADC $13 / STA $0E   ; ★y に近傍のずれ
DE4A: JSR $DED4          ; ★近傍の値を取る
DE4D: CMP #$04 / BEQ →   ; ★4（壁）なら「つながっている」= ビットを立てない
DE51: CMP #$09 / BEQ →   ; ★9 も同じ扱い
DE55: CMP #$0D / BEQ →   ; ★13 も同じ扱い
DE59: LDA $DED0,Y / ORA $D4 / STA $D4   ; ★つながっていなければビットを立てる
DE63: INC $05F4 / CPY #$04 / BNE $DE3A  ; ★4方向ぶん
DE6D: LDY $D4 / LDA $DEA0,Y / STA $D4   ; ★★ビットの組み合わせ -> 形
DE74: BMI $DE99          ; ⚠ $FF なら「補正なし」（値 4 のまま）
DE76: CMP #$15 / BCS →   ; ★$15 以上ならそのまま採用
DE7A: TAY / LDA $DEB0,Y / ADC $12 ...   ; ★★2段目: 斜めを見る
DE8B: JSR $DED4 / CMP #$04
DE90: BNE $DE99          ; ★★斜めが壁**でなければ** → $04（形は捨てる）
DE92: LDY $D4 / LDA $DEC0,Y             ; ★★角の形に差し替える
DE97: BNE $DE9B          ; ⚠ 角の形が 0 なら、これも $04 になる
DE99: LDA #$04           ; ★補正なし
DE9B: STA $0C            ; ★結果
```

## ⚠⚠ 2026-08-11 の訂正: **形をそのまま返してはいけない**

★`DE90: BNE $DE99` の飛び先は `LDA #$04` です。つまり
**斜めが壁でなければ、形（0-7）は捨てて `$04` に戻ります**。

⚠ 2026-08-02 の写しは、ここで `shape`（0-7）を返していました。
  そのまま変換表を引くと、0→C4C8C3C7 / 1→草原 / 2→砂漠 … と
  **まったく別の地形の絵**になります。

★世界地図の実測（2026-08-11 / 27 マス）で見つかりました。
  索引0 になるはずのマスは、実機では **17/19 が素の海**（`A1 A0 A0 A1`）
  でした。★逆アセンブルし直して裏を取っています。

★★ **出てくる値は `$04` か `$14`-`$1B` だけ**です
（`$DEA0` の中身が `$FF` と 0-7 しかないので、`CMP #$15 / BCS` の道は
この表では通りません）。

## ★ 表（すべて実測）

| 表 | 中身 |
| --- | --- |
| `$DEC8` x のずれ | `0, 1, 0, -1`（上・右・下・左） |
| `$DECC` y のずれ | `-1, 0, 1, 0` |
| `$DED0` ビット | `01, 02, 04, 08`（上・右・下・左） |
| `$DEA0` 形 | `FF 04 05 00 06 FF 01 FF 07 02 FF FF 03 FF FF FF` |
| `$DEB0` 斜め x | `-1,-1, 1, 1, 1,-1,-1, 1` |
| `$DEB8` 斜め y | ` 1,-1, 1,-1, 1, 1,-1,-1` |
| `$DEC0` 角の形 | `16, 1B, 14, 19, 15, 18, 1A, 17` |

## ⚠ 呼ぶ前に

`$DED4`（`upper_field_reader` の相棒）が `$0C`（x）と `$0E`（y）から
**その位置の値**を返します。★ここでは呼び出し側が用意した
`value_at(x, y)` を使います。
"""

from __future__ import annotations

#: 4近傍のずれ（上・右・下・左）。★`$DEC8` / `$DECC`
NEIGHBOUR_DX = (0, 1, 0, -1)
NEIGHBOUR_DY = (-1, 0, 1, 0)
#: 方向ごとのビット。★`$DED0`
NEIGHBOUR_BIT = (0x01, 0x02, 0x04, 0x08)

#: ★壁とみなす値（`CMP #$04` / `#$09` / `#$0D`）
WALL_VALUES = frozenset({0x04, 0x09, 0x0D})
#: ★補正の対象になる中心の値（`DE2C: CMP #$04`）
CENTRE_VALUE = 0x04

#: ビットの組み合わせ → 形。★`$DEA0`。⚠ `$FF` は「補正しない」
SHAPE_TABLE = (0xFF, 0x04, 0x05, 0x00, 0x06, 0xFF, 0x01, 0xFF,
               0x07, 0x02, 0xFF, 0xFF, 0x03, 0xFF, 0xFF, 0xFF)
#: ★これ以上の形は、斜めを見ずにそのまま使う（`DE76: CMP #$15`）
SHAPE_DIRECT = 0x15

#: 2段目（斜め）のずれ。★`$DEB0` / `$DEB8`
DIAGONAL_DX = (-1, -1, 1, 1, 1, -1, -1, 1)
DIAGONAL_DY = (1, -1, 1, -1, 1, 1, -1, -1)
#: 斜めも壁だったときの形。★`$DEC0`
CORNER_SHAPE = (0x16, 0x1B, 0x14, 0x19, 0x15, 0x18, 0x1A, 0x17)


def wall_shape(value_at, x: int, y: int) -> int:
    """壁の向きを決めた値を返す。★`$DE29`-`$DE9B` の写し。

    `value_at(x, y)` は**その位置の値**（`$DED4` の戻り）。
    ⚠ 読めない位置では、呼ぶ側が「壁」を返すか `None` を返すか決めます。

    ★中心が壁でなければ、そのままの値を返します（補正しない）。
    """
    centre = value_at(x, y)
    if centre != CENTRE_VALUE:
        return centre if centre is not None else CENTRE_VALUE

    # --- 4近傍を見て、つながっていない向きのビットを立てる ---------------
    bits = 0
    for i in range(4):
        near = value_at(x + NEIGHBOUR_DX[i], y + NEIGHBOUR_DY[i])
        if near in WALL_VALUES:
            continue                       # ★つながっている
        bits |= NEIGHBOUR_BIT[i]

    shape = SHAPE_TABLE[bits & 0x0F]
    if shape == 0xFF:
        return CENTRE_VALUE                # ⚠ 補正しない（`BMI $DE99`）
    if shape >= SHAPE_DIRECT:
        return shape                       # ★そのまま使う（`BCS $DE9B`）
    if shape >= len(DIAGONAL_DX):
        # ⚠ `$DEB0` の表（8 件）をはみ出す形。★この表には出てきません
        #   （`$DEA0` の中身は `$FF` か 0-7）。念のため補正しない。
        return CENTRE_VALUE

    # --- 2段目: 斜めを見る（`DE7A`-`DE97`）-------------------------------
    near = value_at(x + DIAGONAL_DX[shape], y + DIAGONAL_DY[shape])
    if near != CENTRE_VALUE:
        # ★★ `DE90: BNE $DE99` → `LDA #$04`（2026-08-11 に訂正）★★
        #   ⚠ ここで形（0-7）を返してはいけません。**別の地形の絵**になります。
        return CENTRE_VALUE
    corner = CORNER_SHAPE[shape]
    if not corner:
        return CENTRE_VALUE                # ⚠ `DE97: BNE $DE9B` が不成立
    return corner                          # ★角の形に差し替える
