"""モンスターの絵を ROM から起こす（RX3-0035 / 2026-08-31）。

★★ `monster_id` は `_pak_data_lib` の**索引そのもの**でした。 ★★

⚠ `RX3-0033` は「23 バイトに `graphic_id` が無い」で止まっていましたが、
★別の表を `monster_id` で直に引くのが正解でした（指示書 §6 の仮説A）。

## ★経路（⚠ 北米版の逆アセンブル + JP ROM の実測）

```text
monster_id
  → _pak_data_lib[id]        5 バイト: tiles / data(2) / param(2)
  → data   ★圧縮された絵（bank 2 か 3。⚠ ビット表で選ぶ）
  → param  ★パレット（bank 2）
```

## ★展開（`sub_39C5F` を写したもの）

```text
① 見出しの要素を読み飛ばす
     b = 次の 1 バイト（★読むと 1 進む）
     bit6 が 0 なら もう 1 進む / さらに 1 進む
     bit7 が立ったら終わり
② その b で埋め方が決まる
     bit3 が立つ → bit0 が立てば「埋める値」を 1 バイト読む
                   続けて 16 bit のマスクを 2 バイト（★下位が先）
     bit3 が立たない → 埋める値 0 / マスクは全部 1
③ 16 バイト作る（★1 タイル）
     マスクの上位ビットから見て、1 なら 1 バイト読む / 0 なら埋める値
```

⚠⚠ **実機で答え合わせ済み**: 戦闘中のセーブ 4 本に写っている CHR-RAM と
★**54 タイルすべてが 1 バイトも違わず一致**しました。

## ★★ 置き方（RX3-0223 / 2026-09-12）

⚠ 1 枚のタイルに見出しが**いくつも**付きます。★見出し 1 つ ＝ 升 1 つ。

```text
見出し bit6  立つ → 次の 1 バイトが (行 << 4) | 列（★升を 1 つ埋める）
       bit1  → 左右反転した写しを置く   ★`sub_39C5F` が 1 枚から
       bit2  → 上下反転した写しを置く     4 通りの写しを作る
```

⚠⚠ 前は**最後の見出し**しか読まず、左右対称の敵（片側だけを持ち、
もう片側は反転して置く）が**半分**になっていました（★ハンターフライ ほか）。
"""
from __future__ import annotations

import dataclasses

from .profile import Identified

#: ★1 タイルは 16 バイト（⚠ NES の 2bpp）
TILE_BYTES = 16
#: ⚠ 絵の本体が置かれているバンク（★ビットが立てば後者）
DATA_BANKS = (2, 3)
#: ★param が置かれているバンク
PARAM_BANK = 2
#: ⚠ 実機が通す `monster_id` の上限（`CMP #$A7`）
MAX_ID = 0xA7


class MonsterGfxError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Placement:
    """★見出し 1 つ ＝ 1 枚のタイルを 1 つの升に置く指示（RX3-0223）。

    ⚠⚠ 1 枚のタイルに見出しが**いくつも**付くことがあります。
    ★左右対称の敵は片側だけを持ち、もう片側には同じタイルを
      **左右反転して**置きます（139 体中 47 体）。
    """

    tile: int                #: ★`Graphic.tiles` の番号
    col: int
    row: int                 #: ⚠ 見出しのままの行（★`top_row` を引く前）
    hflip: bool = False      #: ★見出し bit1（左右反転）
    vflip: bool = False      #: ★見出し bit2（上下反転）


@dataclasses.dataclass(frozen=True)
class Graphic:
    """1 体ぶんの絵の材料。"""

    monster_id: int
    bank: int
    tiles: tuple            #: ★16 バイトのタイル
    sprite_palettes: tuple  #: ⚠ 3 色 × n（★NES の色番号）
    bg_palettes: tuple

    width: int = 0           #: ★何列（★見出しから実測）
    height: int = 0          #: ★何行
    #: ★タイルごとの**最初の**置き場 `(列, 行)`。⚠ 無いものは None
    #: （⚠ 置き場が 2 つ以上あるタイルは `placements` を見る）
    cells: tuple = ()
    placements: tuple = ()   #: ★置き場ぜんぶ（`Placement`。⚠ 見出しの順）

    @property
    def tile_count(self) -> int:
        return len(self.tiles)

    #: ★実測の上限（⚠ いちばん大きい敵で 10 列 × 8 行）
    MAX_COLS, MAX_ROWS = 10, 8

    @property
    def plausible(self) -> bool:
        """⚠ その形が画面に収まるか（★収まらないなら読み方が違う）。

        ⚠⚠ 最初は `8 × 8` にしていて、★大きい敵 5 体を「ありえない」と
        言っていました。実際は 9〜10 列の敵が居ます（★私の思い込み）。
        """
        return (1 <= self.width <= self.MAX_COLS
                and 1 <= self.height <= self.MAX_ROWS)

    @property
    def top_row(self) -> int:
        """★いちばん上の行（⚠ 画面のどこから描き始めるか）。"""
        rows = [p.row for p in self.placements] or [
            c[1] for c in self.cells if c is not None]
        return min(rows) if rows else 0

    def placed(self) -> tuple:
        """★置き場ぜんぶ（⚠ `placements` が無い古い作り方なら `cells` から）。"""
        if self.placements:
            return self.placements
        return tuple(Placement(i, pos[0], pos[1])
                     for i, pos in enumerate(self.cells) if pos is not None)

    def cell(self, col: int, row: int) -> bytes | None:
        """★`(列, 行)` のタイル（⚠ 見出しの位置で引く。無ければ None）。

        ⚠ 反転して置く升は、**反転した後の** 16 バイトを返します。
        """
        want = (col, row + self.top_row)
        for p in self.placed():
            if (p.col, p.row) == want:
                return flip_tile(self.tiles[p.tile], p.hflip, p.vflip)
        return None


#: ★1 バイトのビットを逆順にした表（⚠ 左右反転 = 実機の `ASL` / `ROR` × 8）
_REVERSED = bytes(int(f"{b:08b}"[::-1], 2) for b in range(256))


def flip_tile(tile: bytes, hflip: bool = False, vflip: bool = False) -> bytes:
    """★実機と同じ反転（RX3-0223）。⚠ 反転しないなら**同じもの**を返す。

    ★`sub_39C5F` は 1 枚から 4 通りの写しを作ります。

    ```text
    +$00 そのまま / +$10 各バイトのビットを逆順（★左右反転）
    +$20 / +$30   上の 2 つの 8 行を逆順（★上下反転 / 上下左右）
    ```
    """
    if not (hflip or vflip):
        return tile
    out = bytearray()
    for plane in (tile[0:8], tile[8:16]):
        rows = plane[::-1] if vflip else plane
        out += bytes(_REVERSED[b] for b in rows) if hflip else rows
    return bytes(out)


def _table(ident: Identified) -> tuple[int, int, int]:
    t = ident.table("monster_graphics")
    return (ident.table_prg("monster_graphics"),
            int(t["entries"]), int(t["entry_size"]))


def entry_of(ident: Identified, monster_id: int) -> tuple[int, int, int]:
    """`(タイル数, data の CPU 番地, param の CPU 番地)`。"""
    start, n, size = _table(ident)
    if not 0 <= monster_id < n:
        raise MonsterGfxError(f"monster_id が範囲外です: {monster_id}（0..{n - 1}）")
    raw = ident.rom.prg[start + monster_id * size:
                        start + (monster_id + 1) * size]
    return raw[0], raw[1] | raw[2] << 8, raw[3] | raw[4] << 8


def bank_of(ident: Identified, monster_id: int) -> int:
    """★絵の本体があるバンク（`_get_pak_data_bank` を写したもの）。

    ⚠ 1 体につき 1 ビット。`banks_list[id >> 3]` の **bit(7 - id % 8)**。
    """
    if not 0 <= monster_id <= MAX_ID:
        raise MonsterGfxError(f"monster_id が範囲外です: {monster_id}")
    at = ident.table_prg("monster_graphics", "banks_list")
    byte = ident.rom.prg[at + (monster_id >> 3)]
    bit = (byte >> (7 - (monster_id & 7))) & 1
    return DATA_BANKS[bit]


def decode_tiles(prg: bytes, bank: int, cpu: int, count: int) -> list:
    """★圧縮された絵を `count` 枚のタイルへ（⚠ `sub_39C5F` そのまま）。"""
    if not 0x8000 <= cpu <= 0xBFFF:
        raise MonsterGfxError(f"窓の外を指しています: ${cpu:04X}")
    at = bank * 0x4000 + (cpu - 0x8000)
    end = (bank + 1) * 0x4000
    out = []

    def read() -> int:
        nonlocal at
        if at >= end:
            raise MonsterGfxError("バンクの終わりを越えました（★形が違う）")
        got = prg[at]
        at += 1
        return got

    for _ in range(count):
        fill, mask_lo, mask_hi = 0, 0xFF, 0xFF
        head = 0
        for _ in range(64):
            head = read()
            if not head & 0x40:
                at += 1
            at += 1
            if head & 0x80:
                break
        else:
            raise MonsterGfxError("見出しが終わりません（★形が違う）")
        if head & 0x08:
            if head & 0x01:
                fill = read()
            mask_lo = read()
            mask_hi = read()
        tile = bytearray()
        for _ in range(TILE_BYTES):
            take = (mask_hi >> 7) & 1
            mask_hi = ((mask_hi << 1) | ((mask_lo >> 7) & 1)) & 0xFF
            mask_lo = (mask_lo << 1) & 0xFF
            tile.append(read() if take else fill)
        out.append(bytes(tile))
    return out


def read_palettes(prg: bytes, cpu: int) -> tuple[tuple, tuple]:
    """`param` の先頭から `(スプライト側, 背景側)` の 3 色組を読む。

    ⚠ 1 バイト目の**下位ニブル**がスプライト側の数、**上位ニブル**が背景側。
    ★実機の PRAM と突き合わせて確かめてあります。
    """
    if not 0x8000 <= cpu <= 0xBFFF:
        raise MonsterGfxError(f"窓の外を指しています: ${cpu:04X}")
    at = PARAM_BANK * 0x4000 + (cpu - 0x8000)
    head = prg[at]
    at += 1
    lo, hi = head & 0x0F, (head >> 4) & 0x0F

    def take(n):
        nonlocal at
        got = tuple(tuple(prg[at + i * 3: at + i * 3 + 3]) for i in range(n))
        at += n * 3
        return got

    return take(lo), take(hi)


def read_placements(prg: bytes, bank: int, cpu: int, count: int) -> list:
    """★タイルごとの置き場（`Placement` の組）。⚠ 位置を持たない見出しは入れない。

    ## ★★ 1 枚に見出しが**いくつも**付く（RX3-0223 / 2026-09-12）

      ⚠ 前は見出しを読み流して**最後の 1 つ**しか覚えていませんでした。
      ★実機（`loc_39CEF` / `loc_39F19`）は見出し**ごとに**升を 1 つ埋めます。

      ```text
      b bit6 が立つ → 次の 1 バイトが (行 << 4) | 列（★升を 1 つ埋める）
        bit1       → ★左右反転した写しを置く（+$10）
        bit2       → ★上下反転した写しを置く（+$20）
      ```

      ⚠ 左右対称の敵は片側のタイルに「そのまま」と「左右反転」の 2 つの
      見出しを付けています。★1 つしか読まないと**絵が半分**になりました。
    """
    at = bank * 0x4000 + (cpu - 0x8000)
    end = (bank + 1) * 0x4000
    out = []

    def read() -> int:
        nonlocal at
        if at >= end:
            raise MonsterGfxError("バンクの終わりを越えました（★形が違う）")
        got = prg[at]
        at += 1
        return got

    for index in range(count):
        places = []
        head = 0
        for _ in range(64):
            head = read()
            if head & 0x40:
                got = read()
                places.append(Placement(index, got & 0x0F, (got >> 4) & 0x0F,
                                        hflip=bool(head & 0x02),
                                        vflip=bool(head & 0x04)))
            else:
                at += 2
            if head & 0x80:
                break
        else:
            raise MonsterGfxError("見出しが終わりません（★形が違う）")
        out.append(tuple(places))
        if head & 0x08:
            if head & 0x01:
                read()
            mask_lo, mask_hi = read(), read()
        else:
            mask_lo, mask_hi = 0xFF, 0xFF
        at += bin(mask_hi << 8 | mask_lo).count("1")
    return out


def read_cells(prg: bytes, bank: int, cpu: int, count: int) -> list:
    """★タイルごとの**最初の** `(列, 行)`。⚠ 位置を持たない要素は `None`。

    ⚠⚠ 置き場が 2 つ以上あるタイルがあります（★`read_placements`）。
    絵にするときは `read_placements` を使ってください（RX3-0223）。

    ## ★★ 見出しの 2 バイト目が **位置そのもの**でした（2026-09-01）

      ⚠ 最初は「先頭に見出しが 1 つ」と読み違えていました。
      ★正しくは **タイル 1 枚ごとに見出しが 1 つ**あります。

      ```text
      b（1 バイト目） bit6 が立つ → 次の 1 バイトが (行 << 4) | 列
                      bit6 が落ちる → 次の 2 バイトは別のもの（★位置ではない）
                      bit7 が立ったら、そのタイルの見出しは終わり
      ```

      ⚠ 実機は `loc_39CEF` で低ニブルの最大を `byte_C4` に集め、
      ★`sub_39E39` でそれを窓の幅にしています（`INC byte_C4` ＝ 幅）。

    ⚠⚠ **実機のネームテャブルで測った形と一致します**
      （id0 = 行 5-6 / 列 0-1、id2 = 行 3-6 / 列 0-4）。
    """
    return [(p[0].col, p[0].row) if p else None
            for p in read_placements(prg, bank, cpu, count)]


def build(ident: Identified, monster_id: int) -> Graphic:
    """★1 体ぶんの材料をまとめて返す。

    ★幅は**置き場ぜんぶ**の列の最大 + 1
      （⚠ 実機の `loc_39CEF` も見出しぜんぶの列を `byte_C4` に集めます）。
    """
    count, data, param = entry_of(ident, monster_id)
    bank = bank_of(ident, monster_id)
    spr, bg = read_palettes(ident.rom.prg, param)
    groups = read_placements(ident.rom.prg, bank, data, count)
    placements = tuple(p for group in groups for p in group)
    if placements:
        rows = [p.row for p in placements]
        w = max(p.col for p in placements) + 1
        h = max(rows) - min(rows) + 1
    else:
        w = h = 0
    return Graphic(monster_id=monster_id, bank=bank,
                   tiles=tuple(decode_tiles(ident.rom.prg, bank, data, count)),
                   sprite_palettes=spr, bg_palettes=bg, width=w, height=h,
                   cells=tuple((g[0].col, g[0].row) if g else None
                               for g in groups),
                   placements=placements)


# --- ★絵にする（⚠ 画面の持ち物にしない / 指示書 §22）----------------------

#: ⚠ 透ける色（★NES の「色なし」。背景は呼ぶ側が決める）
BACKDROP = 0x0F

#: ★★ 絵の中身が変わったら上げる（⚠ 置き場の PNG を作り直す合図）★★
#:   1 = 見出しを 1 つしか読まない（⚠ 左右対称の敵が半分に切れていた）
#:   2 = 見出しぜんぶ + 反転（RX3-0223 / 2026-09-12）
ART_VERSION = 2


def to_pixels(graphic: Graphic, palette=None, scale: int = 1):
    """★`(画素, 幅, 高さ)`。⚠ 画素は RGB の 3 バイト並び。

    ★1 枚のタイルを見出しの数だけ置き、旗どおりに反転します（RX3-0223）。

    ⚠ 位置を持たない見出し（bit6 が落ちる）は**置きません**
    （★スプライトで重ねる部品。`loc_39F19` / ⚠ 未対応）。
    """
    from .render import NES_PALETTE

    if palette is None:
        palette = (graphic.bg_palettes or graphic.sprite_palettes
                   or ((0x30, 0x15, 0x1C),))[0]
    cols = [NES_PALETTE[BACKDROP]] + [NES_PALETTE[c & 0x3F] for c in palette]
    w = max(1, graphic.width) * 8 * scale
    h = max(1, graphic.height) * 8 * scale
    px = bytearray(w * h * 3)
    for i in range(0, len(px), 3):
        px[i:i + 3] = bytes(cols[0])
    for p in graphic.placed():
        tile = flip_tile(graphic.tiles[p.tile], p.hflip, p.vflip)
        ox, oy = p.col * 8, (p.row - graphic.top_row) * 8
        for y in range(8):
            lo, hi = tile[y], tile[y + 8]
            for x in range(8):
                bit = 7 - x
                col = cols[((lo >> bit) & 1) | (((hi >> bit) & 1) << 1)]
                for sy in range(scale):
                    for sx in range(scale):
                        at = (((oy + y) * scale + sy) * w
                              + (ox + x) * scale + sx) * 3
                        if 0 <= at and at + 3 <= len(px):
                            px[at:at + 3] = bytes(col)
    return px, w, h

