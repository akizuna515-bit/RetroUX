"""日本版DQ2のマップを **ROM から展開する**（2026-08-02 / Stop 1'）。

★★ **ゲーム自身の処理 `$E03C` を Python へ写したものです。** ★★

⚠ 北米版の移植（`dq2rom/maps/decoder.py`）とは**別物**です。
  あちらは展開結果を WRAM へ置く方式で、日本版には WRAM がありません。

## ★★ これは「使われていないコード」ではありません（2026-08-12 に明記）

⚠⚠ `docs/history/RETROUX_BACKLOG.md` の技術負債2 は、これを
  「`dungeon_map.py` と重複／本体から import されていない」としています。
  ★**本体から呼ばれないのは正しい**のですが、**役割があります**。

★これは**手で写したほう**です。`tests/test_cpu6502.py` が、
  ROM のコードを**そのまま動かした結果**（`cpu6502.py` / [D-10]）と
  ここの `terrain_at()` を突き合わせ、**写し間違いが無いこと**を見ています。

    ROM を実行した答え  ==  手で写した答え   → ★写し間違いは無い
    一致するのに画面と合わない → ⚠ 追っているルーチンが違う

⚠ **消すと、この答え合わせができなくなります。**
  ★`dungeon_map.py`（本体が使う実装）とは**役割が違う**ので、
    「重複」ではありません。

⚠ ただし `map_kind()` は `dungeon_map.py` と**本当に同じ**です
  （どちらも `$E20C` の写し）。★そこだけは1つに寄せる余地があります。

## 元のコード（bank7 / CPU `$E03C`）

```
E03C: A5 1F     LDA $1F        ; マップ種別
E03E: C9 02     CMP #$02
E040: 90 04     BCC $E046
E042: 46 12     LSR $12        ; ★種別 2 以上なら X を 1/2
E044: 46 13     LSR $13        ; ★         Y を 1/2
E046: A5 1F     LDA $1F
E048: C9 02     CMP #$02
E04A: A9 3F     LDA #$3F
E04C: 90 02     BCC $E050
E04E: A9 0F     LDA #$0F
E050: 85 0F     STA $0F        ; 連の長さのマスク
E052: A5 25     LDA $25
E054: 05 26     ORA $26
E056: D0 05     BNE $E05D
E058: A9 00     LDA #$00
E05A: 85 0D     STA $0D        ; ★ポインタが無ければ 0
E05C: 60        RTS
E05D: A5 21     LDA $21
E05F: C5 12     CMP $12
E061: 90 F5     BCC $E058      ; ★幅より外なら 0
E063: A5 22     LDA $22
E065: C5 13     CMP $13
E067: 90 EF     BCC $E058      ; ★高さより外なら 0
E069-E06C:      TYA/PHA/TXA/PHA
E06D: 20 95 FE  JSR $FE95      ; ★バンク 2 へ切り替え
E070: A0 FF     LDY #$FF
E072: A2 00     LDX #$00
E074: E4 13     CPX $13        ; 行が見つかったか
E076: F0 09     BEQ $E081
E078: E8        INX            ; 次の行へ
E079: C8        INY
E07A: B1 25     LDA ($25),Y
E07C: 30 F6     BMI $E074      ; ★bit7 が立っていたら行の終わり
E07E: 4C 79 E0  JMP $E079
E081: A9 FF     LDA #$FF
E083: 85 0E     STA $0E        ; 累積 = -1
E085: C8        INY
E086: B1 25     LDA ($25),Y
E088: AA        TAX
E089: 25 0F     AND $0F        ; ★下位＝連の長さ
E08B: 38        SEC
E08C: 65 0E     ADC $0E        ; 累積 += 長さ + 1
E08E: 85 0E     STA $0E
E090: C5 12     CMP $12
E092: B0 05     BCS $E099      ; ★累積が X に届いたら、そのタイル
E094: 8A        TXA
E095: 10 EE     BPL $E085      ; bit7 が 0 なら行の最後
E097: A2 00     LDX #$00       ; ★行が尽きたら 0
E099: 8A        TXA
E09A: 29 7F     AND #$7F
E09C: 4A        LSR A          ; ★マスクのビット数だけ落として上位＝タイル
E09D: 46 0F     LSR $0F
E09F: D0 FB     BNE $E09C
E0A1: 85 0D     STA $0D        ; ★結果
E0A3-E0A6:      PLA/TAX/PLA/TAY
E0A7: 60        RTS
```

## ★ ここで解けたこと

- **`LSR` が「ヘッダ寸法が実測の約半分」の正体**。
  種別 2 以上（ダンジョン）は、マップデータ 1 マスが**画面 2×2 マス**。
- **マップ種別は `map_id` だけで決まる**（`$E20A`）:

  | `map_id` | 種別 | 座標を 1/2 するか | 連の長さのマスク |
  | --- | --- | --- | --- |
  | `$01` | 0（世界地図） | しない | `$3F` |
  | `< $2B` | 1（街・城） | しない | `$3F` |
  | `$2B`-`$43` | 2（ダンジョン） | ★する | `$0F` |
  | `>= $44` | 3 | ★する | `$0F` |

  ⚠ 同じ値が `$0C`（タイルセット番号）にも入ります。

## ⚠⚠ 地形データの位置は**まだ分かっていません**

★RAM から分かったこと（セーブステートを直接読んで実測 / 2026-08-02）:

```
map $3F のヘッダ = 24 13 17 B3 A0 26 B4 5B
RAM の $20-$27  = 24 13 17 B3 A0 26 B4 5B   ★ヘッダ8バイトがそのまま
```

つまり `$21`=幅 / `$22`=高さ / `$25`,`$26`= byte5/byte6 で、
`$E03C` は `($25),Y` を読みます。**ここまでは確かです。**

⚠⚠ ですが byte5/byte6 の中身は地形に見えません:

```
map $3F byte5/6 -> 22 10 05 54 90 | 22 10 05 54 90 | 22 10 05 54 90
                   ★5バイト周期の繰り返し
map $3F byte3/4 -> E6 E6 E1 E2 E2 07 E0 E0 E7 07 45 …
                   ★こちらのほうがランレングスらしい
```

★考えられること:

1. `$25`/`$26` は**作業用**で、セーブステートの瞬間は別の用途の値
   （`$E03C` を呼ぶ直前に別の値が入る）
2. 5バイト周期のデータが実は地形で、私の展開の仕方が違う

## ⚠⚠ **2回続けて誤りました**（記録）

1回目: byte3/byte4 を地形だと思った
2回目: 「行の合計が幅+1 になる」ので byte5/byte6 だと思った
       → ★実は**各行が1バイト**で、たまたま合っていただけ
       → 展開すると街の地形がほぼ全部 0 になった

★**「数字が合った」だけで決めない。中身の形も見る。**

## ⚠ いまの `terrain_at()` は正しくありません

★逆アセンブルの写しとしては素直ですが、入力（`$25`/`$26` が指す先）が
定まっていないため、出てくる地形は信用できません。
"""

from __future__ import annotations

import dataclasses

from .rom_tiles import MAP_HEADER, MAP_HEADER_SIZE

#: bank2 が写る CPU アドレスの先頭（`JSR $FE95` が bank2 を選ぶ）
BANK_WINDOW = 0x8000
#: bank2 の PRG 内の位置
BANK2_PRG = 0x08000
#: bank2 の大きさ
BANK_SIZE = 0x4000

#: ★マップ種別の境目（`$E20A` の `CMP #$2B` / `CMP #$44`）
KIND_TOWN_MAX = 0x2B
KIND_DUNGEON_MAX = 0x44
#: ★これ以上の種別は座標を 1/2 する（`CMP #$02 / BCC`）
KIND_HALVED = 2
#: 連の長さのマスク（種別で変わる）
MASK_WIDE = 0x3F
MASK_NARROW = 0x0F


def map_kind(map_id: int) -> int:
    """`map_id` からマップ種別（`$1F`）を出す。★`$E20A` そのまま。"""
    if map_id == 0x01:
        return 0
    if map_id < KIND_TOWN_MAX:
        return 1
    if map_id < KIND_DUNGEON_MAX:
        return 2
    return 3


@dataclasses.dataclass(frozen=True)
class MapHeader:
    """マップヘッダ表の1件（PRG `0x08000` から 8 バイト）。

    ⚠ byte1/byte2 を幅・高さ、byte3/byte4 をデータ位置と**仮定**しています。
      ★照合で確かめます（`tests/test_rom_map_decoder.py`）。
    """

    map_id: int
    border_tile: int
    #: `$21` に入ると見ている値（マップデータ内の幅）
    width: int
    #: `$22` に入ると見ている値（マップデータ内の高さ）
    height: int
    #: ★★ 地形データの位置（`$25`/`$26`）= ヘッダ **byte5/byte6**。
    #:
    #: ⚠⚠ 2026-08-02、最初 byte3/byte4 だと思って外しました。
    #:   ★行ごとの連の合計を幅と突き合わせて見分けました:
    #:       map $0B  byte3/4 -> 38 48 40 …（幅26と不一致）
    #:                byte5/6 -> 26 26 26 …★**8行とも幅+1 に一致**
    #:       map $3D  byte5/6 -> 16 16 16 …★同じく一致（幅15+1）
    #:   ⚠ byte5/byte6 は「日米で値が違い、北米版の逆アセンブルでも ?」
    #:     とされていた欄でした。
    pointer: int
    #: ⚠ byte3/byte4。**地形ではありません**（用途は未解明）
    other_pointer: int
    palette_index: int

    @property
    def kind(self) -> int:
        return map_kind(self.map_id)

    @property
    def halved(self) -> bool:
        """★座標を 1/2 するか（種別 2 以上）。"""
        return self.kind >= KIND_HALVED

    @property
    def mask(self) -> int:
        """連の長さのマスク。"""
        return MASK_NARROW if self.kind >= KIND_HALVED else MASK_WIDE

    @property
    def screen_size(self) -> tuple[int, int]:
        """★**画面のマス**での大きさ。⚠ ヘッダの値そのままではない。

        種別 2 以上は、マップデータ 1 マスが画面 2×2 マスになる。
        """
        if self.halved:
            return ((self.width + 1) * 2, (self.height + 1) * 2)
        return (self.width + 1, self.height + 1)


def read_header(prg: bytes, map_id: int) -> MapHeader | None:
    """ヘッダ表から1件読む。⚠ 範囲外なら None。"""
    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    if off + MAP_HEADER_SIZE > len(prg):
        return None
    return MapHeader(
        map_id=map_id,
        border_tile=prg[off],
        width=prg[off + 1],
        height=prg[off + 2],
        pointer=prg[off + 5] | (prg[off + 6] << 8),
        other_pointer=prg[off + 3] | (prg[off + 4] << 8),
        palette_index=prg[off + 7],
    )


def _data_offset(pointer: int) -> int | None:
    """CPU アドレス → PRG の位置。⚠ bank2 の窓の外なら None。"""
    if not BANK_WINDOW <= pointer < BANK_WINDOW + BANK_SIZE:
        return None
    return BANK2_PRG + (pointer - BANK_WINDOW)


def terrain_at(prg: bytes, header: MapHeader, x: int, y: int) -> int:
    """その画面座標の**地形番号**を返す。⚠ 範囲外は 0。

    ★`$E03C` をそのまま写しています。**推測を足していません。**

    ⚠ 戻り値は「地形番号」であって、画面のタイルID（`$90`-`$CF`）では
      ありません。★その対応は別に確かめます。
    """
    if x < 0 or y < 0:
        return 0
    # ★種別 2 以上は、マップデータが 2 マス単位（`LSR $12` / `LSR $13`）
    if header.halved:
        x >>= 1
        y >>= 1
    mask = header.mask

    base = _data_offset(header.pointer)
    if base is None or header.pointer == 0:
        return 0                      # ★ポインタが無い（`$E052`）
    # ⚠ `CMP` は符号なし比較。`$21 < x` なら 0（`$E05D`）
    if header.width < x or header.height < y:
        return 0

    # --- 行を y まで飛ばす（`$E070`-`$E07E`）------------------------------
    #   ★bit7 が立っているバイトが「その行の最後」。
    row, pos = 0, -1
    limit = len(prg)
    while row != y:
        row += 1
        while True:
            pos += 1
            if base + pos >= limit:
                return 0              # ⚠ データの外。★推測で埋めない
            if prg[base + pos] & 0x80:
                break                 # ★行の終わり
            # ⚠ 元のコードは INY だけして読み直す（X は増やさない）

    # --- その行を x まで走る（`$E081`-`$E097`）----------------------------
    total = -1
    value = 0
    while True:
        pos += 1
        if base + pos >= limit:
            return 0
        value = prg[base + pos]
        # ★下位＝連の長さ。`SEC` があるので +1 される
        total = (total + (value & mask) + 1) & 0xFF
        if total >= x:
            break
        # ⚠⚠ **bit7 が立っていたら、そこが行の最後**（`E095: BPL` は
        #   bit7=0 のとき続く）。★2026-08-02、ここを逆に書いて外しました。
        if value & 0x80:
            return 0                  # ★行が尽きた（`$E097`）
    # --- 上位＝タイル（`$E099`-`$E0A1`）----------------------------------
    out = value & 0x7F
    shift = mask
    while shift:
        out >>= 1
        shift >>= 1
    return out


def decode_map(prg: bytes, map_id: int, width: int | None = None,
               height: int | None = None):
    """1マップぶんを画面座標で展開する。`[[地形番号, ...], ...]` を返す。

    ⚠ 範囲を指定しなければ、ヘッダから求めた**画面のマス**の大きさを使う。
    """
    header = read_header(prg, map_id)
    if header is None:
        return None
    w, h = header.screen_size
    w = width if width is not None else w
    h = height if height is not None else h
    return [[terrain_at(prg, header, x, y) for x in range(w)]
            for y in range(h)]
