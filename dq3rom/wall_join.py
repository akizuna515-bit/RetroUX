"""壁の自動つなぎ（RX3-0010 / 2026-08-24）。

## ★何をしているか

実機は地図を展開したあと、**もう一度なめて壁のタイルを差し替える**。
⚠ この処理を知らずに ROM から展開した地図を使うと、実機と食い違う。

    map 9（26x26）で実測: ★63 マス（9.3%）が違っていた
    ずれは全部同じ形で、ROM で tile 11 の所が実機では tile 27 だった

★建物の輪郭を見ると、**横に伸びる壁**だけが差し替わっていた。

## 処理（bank14 `$B745`-`$B7FE`。日本版 ROM のバイト列から復号）

まず collision 表をなめて、**差し替え先**を 3 つ拾う。

    上位 3 bit（`AND #$70`）が $50 / $60 / $70 のタイル → クラス 0 / 1 / 2
    ⚠ 後に出てきたものが勝つ（`STX $06,Y` を上書きしながら回す）

つぎに 1 マスずつ見て、上位 3 bit が **$10 / $20 / $30** のタイルだけを対象にする。

    真下のマス（★最終行なら「範囲外タイル」`$8A`）を見て、
      層（上位 3 bit）が同じ  → 下も壁系（$70 が 0 でない）なら差し替えない
      層が違う               → tileset >= $19  下が範囲外タイルなら上と同じ判定、
                                                 でなければ差し替えない
                                tileset >= $0C  差し替える
                                それ未満        自分の層が 0 なら差し替えない
    差し替えるときは**層（上位 3 bit）を保ったまま**タイル ID だけ入れ替える

## 裏取り

★セーブステートの WRAM から実機の地図バッファ（`$7400`）を取り出して比べた。

    map 9 / tileset 5 / 26x26 → **676/676 一致**（2026-08-24）

## ⚠ 宝箱・扉には影響しない

差し替えは `$90→$D0` / `$A0→$E0` / `$B0→$F0` の 3 通りだけで、
★下位ニブル（宝箱 3 / 扉 $B-$D）は**どちらの側にも現れない**（全 204 map で確認）。
そのため宝箱・扉の抽出結果は変わらない。⚠ これはテストで見張っている。
"""

from __future__ import annotations

#: 差し替えの対象になる上位 3 bit
CONVERTIBLE = (0x10, 0x20, 0x30)
#: 差し替え先の上位 3 bit
TARGETS = (0x50, 0x60, 0x70)
#: tileset の分かれ目（$B7BF / $B7C3）
TILESET_OOB_RULE_FROM = 0x19
TILESET_ALWAYS_FROM = 0x0C


def target_tiles(table: list[int]) -> dict[int, int]:
    """クラス（0/1/2）→ 差し替え先のタイル ID。"""
    out: dict[int, int] = {}
    for i, v in enumerate(table):
        c = v & 0x70
        if c in TARGETS:
            # ⚠ 実機は上書きしながら回すので、**後に出てきたものが勝つ**
            out[(c - TARGETS[0]) >> 4] = i
    return out


def apply(decoded, table: list[int], tileset: int) -> list[list[int]]:
    """展開済みの地図に壁つなぎを当てて、**実機と同じ**タイル並びを返す。

    ⚠ `decoded.tiles` は変更しない（新しい表を返す）。
    ★実機は上から下へ 1 行ずつ処理するので、**真下はまだ差し替わっていない**。
    """
    tiles = [row[:] for row in decoded.tiles]
    tgt = target_tiles(table)
    h, w = decoded.height, decoded.width
    for y in range(h):
        for x in range(w):
            cls = table[decoded.tiles[y][x]] & 0x70
            if cls not in CONVERTIBLE:
                continue
            layer = decoded.phase2[y][x]
            if y + 1 >= h:
                below, same_layer = decoded.background, True
            else:
                below = decoded.tiles[y + 1][x]
                same_layer = decoded.phase2[y + 1][x] == layer
            if same_layer:
                convert = (table[below] & 0x70) == 0
            elif tileset >= TILESET_OOB_RULE_FROM:
                convert = (below == decoded.background
                           and (table[below] & 0x70) == 0)
            elif tileset >= TILESET_ALWAYS_FROM:
                convert = True
            else:
                convert = layer != 0
            k = (cls - CONVERTIBLE[0]) >> 4
            if convert and k in tgt:
                tiles[y][x] = tgt[k]
    return tiles


def changes(decoded, table: list[int], tileset: int) -> int:
    """差し替わったマスの数。★どれだけ効いているかを測るため。"""
    after = apply(decoded, table, tileset)
    return sum(1 for y in range(decoded.height) for x in range(decoded.width)
               if after[y][x] != decoded.tiles[y][x])
