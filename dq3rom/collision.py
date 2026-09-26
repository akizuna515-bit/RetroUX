"""map ごとの collision[32] を、日本版 ROM の生成手順どおりに組み立てる（RX3-0009）。

## ★何をしているか

実機は map を読み込むたびに、WRAM `$6DE0-$6DFF` に 32 バイトの表を**作り直す**。
「タイル ID（0〜31）→ 通行判定」の対応表で、宝箱・扉の判定はここを見る。

⚠ RX3-0008 では「tileset → どの 32 バイトか」を**データから推測**しようとして
行き詰まった（宝箱の個数だけでは窓が一意に決まらず、扉が 27 tileset 中 25 で複数解）。
★今回は推測をやめ、**日本版の生成ルーチンをそのまま読んで写した**。

## 生成ルーチン（日本版 Rev 0A / 固定バンク 15。★ROM のバイト列から復号）

    $F64E  LDA $9A            ; ★tileset（エリア表の 3 バイト目）
    $F650  BEQ  ...           ; 0 なら世界地図の道へ
    $F652  CMP #$09
    $F654  BCC  $F668         ; 1〜8 は「4 グループ」の道へ
    $F656  SEC / SBC #$08     ; 9 以上: (tileset - 8)
    $F659  ASL / ASL          ;   × 4
    $F65B  CLC / ADC #$12     ;   + 18
    $F65E  LDX #$20 / STX $54 ;   ★32 タイルを一気に（= 連続 4 グループ）
    $F668  ASL / PHA          ; 1〜8: A = tileset*2
           JSR $F82D          ;   グループ tileset*2
           LDA #$00 / JSR     ;   グループ 0
           PLA / TAX / INX    ;
           TXA  / JSR         ;   グループ tileset*2+1
           LDA #$01 / JSR     ;   グループ 1

グループ 1 個 = **8 タイル × 3 バイト = 24 バイト**。読み出し位置は

    $F7A1  A*3 を 3 回 ASL   → A * 24        （グループ番号 → バイト位置）
    $F834  LDA $A3F3         → 基準ポインタ（= CPU $A3F5 / file 0x016405）
    $F84F  STA $6DE0,X       → ★3 バイト目だけを表に書く

## map 単位の上書き（$F752）

    $F752  LDA $8B                  ; map 番号
    $F756  CMP $AD34,X (4 バイト刻み / 17 件)
    $F765  a=$AD35,X b=$AD36,X c=$AD37,X
    $F77A  STA $6DE0,Y              ; ★collision[b] = c
    $F77D  $7300[b] = $7300[a]      ;   見た目の定義もコピー
    $F791  $7200[b*4+i] = $7200[a*4+i]  (i=0..3)

⚠ **最初に一致した 1 件だけ**適用してすぐ抜ける（表に同じ map は 1 度しか出ない）。
★`a` が `$20`/`$21`（= 32/33）の 3 件は collision を変えず**見た目だけ**差し替える。

## 裏取り

- 実機実測の 32 バイトと **2/2 一致**（世界地図 tileset 0 / 町 map 0 tileset 1）
- グループ表の大きさが `(0x016D44 - 0x016405) / 24 = 98` で、
  ★tileset 最大 27 → グループ 94〜97 と**ぴったり尽きる**
- 上書き 17 件のうち 14 件が実際に値を変え、うち 5 件は
  ⚠「宝箱タイルが数百個ある」という異常をちょうど消す（`03` → `00`）
- 宝箱の個数表と **199/204 map** で一致（残り 5 件は下記）

## ★合わなかった map（⚠ 2026-09-16 に**全部片付いた** / RX3-0012）

| map | tileset | 個数表 | この表で数えた数 | 答え |
| --- | --- | --- | --- | --- |
| 47 | 12 | 0 | 2 | ★map 48 と**同じポインタ**（同一地図）。表が 48 側に 2 を割り当てている |
| 117 | 4 | 4 | 2 | ★**2 マス × 2 状態**。bank12 `$9D93` が条件つきで**局所番号**を +2 する |
| 23 | 11 | 1 | 0 | ★個数表に残っただけで、**ゲーム中から到達できない** |
| 98 | 2 | 1 | 0 | ★同上（⚠ (13,6) のイベントは別の旗で動く / bank0 `$AE3A`） |
| 235 | 27 | 1 | 0 | ★同上 |

⚠⚠ **collision 表のほうは最初から正しかった**（★宝箱タイルは全件取れていた）。
個数表の末尾 3 対が到達できない残りだった、という話です。
根拠は `docs/design/dq3-findings.md`「汎用イベント表が見つかった」（★逃げ道を 5 本ふさいだ）。

## ★ダメージ床（⚠ 通行可否とは別 / RX3-0262）

collision の値 `0x05` / `0x06` は**歩けるが HP が減る**升です（2 / 15）。
★読み方は `dq3rom/damage_floors.py`。⚠ 通行可否の判定は変えていません。
"""

from __future__ import annotations

import dataclasses

from .profile import Identified

#: グループ 1 個ぶんのバイト数（8 タイル × 3 バイト）
GROUP_BYTES = 24
#: 1 タイルのレコード長。★3 バイト目が collision
TILE_RECORD = 3
#: 表の大きさ
TABLE_SIZE = 32
#: tileset 9 以上の道で使う下駄（$F65B の `ADC #$12`）
HIGH_BASE_GROUP = 18
#: 4 グループの道と 32 連続の道の境目（$F652 の `CMP #$09`）
HIGH_TILESET_FROM = 9

#: collision の下位ニブルの意味。⚠ 扉 3 種は北米版由来で **inferred**（実機未確認）
CHEST = 0x03
DOOR_ANY = 0x0B
DOOR_MAGIC = 0x0C
DOOR_FINAL = 0x0D
DOOR_KINDS = {
    DOOR_ANY: "any_key",
    DOOR_MAGIC: "magic_key",
    DOOR_FINAL: "final_key",
}


class CollisionError(ValueError):
    """collision 表を作れなかった。"""


def group_indices(tileset: int) -> list[int]:
    """tileset から、使うグループ番号 4 つを返す（$F64E の分岐そのまま）。"""
    if tileset == 0:
        # ★世界地図: 18 から 32 タイルぶん連続で読む
        return [HIGH_BASE_GROUP + i for i in range(4)]
    if tileset < HIGH_TILESET_FROM:
        # ★1〜8: 別々の 4 グループ。⚠ 並びは [2n, 0, 2n+1, 1] で連続しない
        return [2 * tileset, 0, 2 * tileset + 1, 1]
    first = (tileset - 8) * 4 + HIGH_BASE_GROUP
    return [first + i for i in range(4)]


@dataclasses.dataclass(frozen=True)
class Override:
    """map 単位の上書き 1 件（$AD34 の 4 バイト）。"""

    map_id: int
    source_index: int            # a: 見た目のコピー元（★32/33 は表の外＝オブジェクト用）
    target_index: int            # b: 書き換える先のタイル ID
    value: int                   # c: 新しい collision 値

    @property
    def visual_source_in_table(self) -> bool:
        """見た目のコピー元が 32 タイルの中か。

        ⚠ これは **collision が変わるかどうかではない**。`a` が 32/33 の 11 件は
        表の外（$7320 以降＝オブジェクト用の定義）から見た目を持ってくる。
        ★そのうち map 199 のように collision も変える件はある。
        """
        return self.source_index < TABLE_SIZE

    def to_json(self) -> dict:
        return {
            "map_id": self.map_id,
            "source_index": self.source_index,
            "target_index": self.target_index,
            "value": f"0x{self.value:02X}",
        }


def read_overrides(ident: Identified) -> dict[int, Override]:
    """上書き表を読む。★同じ map は 1 件だけ（実機も最初の 1 件で抜ける）。"""
    prg = ident.rom.prg
    start = ident.table_prg("tile_overrides")
    n = int(ident.table("tile_overrides")["entries"])
    out: dict[int, Override] = {}
    for i in range(n):
        o = start + i * 4
        mid = prg[o]
        if mid in out:
            continue                       # ⚠ 実機は最初の 1 件で抜ける
        out[mid] = Override(map_id=mid, source_index=prg[o + 1],
                            target_index=prg[o + 2], value=prg[o + 3])
    return out


def group_count(ident: Identified) -> int:
    """タイル定義表に入っているグループの数。★境界の裏取りに使う。"""
    start = ident.table_file("tile_definitions")
    end = ident.table_file("tile_overrides")
    return (end - start) // GROUP_BYTES


def base_table(ident: Identified, tileset: int) -> list[int]:
    """上書き前の collision[32]。"""
    prg = ident.rom.prg
    base = ident.table_prg("tile_definitions")
    limit = group_count(ident)
    out: list[int] = []
    for g in group_indices(tileset):
        if not 0 <= g < limit:
            raise CollisionError(
                f"tileset {tileset} のグループ {g} が表の外です（0〜{limit - 1}）")
        o = base + g * GROUP_BYTES
        out += [prg[o + i * TILE_RECORD + 2] for i in range(8)]
    return out


def table_for(ident: Identified, tileset: int, map_id: int,
              overrides: dict[int, Override] | None = None) -> list[int]:
    """その map で実機が持つ collision[32]。"""
    if overrides is None:
        overrides = read_overrides(ident)
    t = base_table(ident, tileset)
    ov = overrides.get(map_id)
    if ov is not None and ov.target_index < TABLE_SIZE:
        t[ov.target_index] = ov.value
    return t


def tiles_with(table: list[int], low_nibble: int) -> set[int]:
    """下位ニブルが指定値のタイル ID。★実機も `AND #$0F` で見ている。"""
    return {i for i, v in enumerate(table) if (v & 0x0F) == low_nibble}


def find(decoded, table: list[int], low_nibble: int) -> list[tuple[int, int]]:
    """地図を**先頭から 1 バイトずつ**走査して座標を拾う（左→右・上→下）。"""
    want = tiles_with(table, low_nibble)
    return [(x, y)
            for y, row in enumerate(decoded.tiles)
            for x, t in enumerate(row) if t in want]
