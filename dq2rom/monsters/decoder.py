"""敵の絵の圧縮を解く（北米版 `bank4.asm` の `B04_8971` の移植）。

★★ 確かめたこと（推測ではない）★★

  1. **ブロックの区切り方** … 全38枚が「索引表が言う次の絵の位置」で
     **ぴったり終わる**（`research/probes/archived/probe_gfx2.py`）。1バイトもずれない。
  2. **タイルの中身と置き方** … 実機で撮った10枚と
     **スプライトに隠れていないマスが全部一致**（`research/probes/archived/probe_gfx3.py`）。

  どちらも「探索にも展開にも使っていない事実」で裏を取っている。

---

## 形式

絵は「ブロック」の並び。1ブロック = **タイル1枚の絵** ＋ **そのタイルの置き方の列**。

    記録（1バイト目）
        bit7  これが最後の記録
        bit6  1 なら続き1バイト（格子に置く） / 0 なら続き2バイト（画素で置く）
        bit2-1 反転の種類（0=そのまま 1=左右 2=上下 3=両方）

    最後の記録の
        bit3  0 なら「16バイトそのまま読む」
              1 なら ビットマップ方式
        bit0  1 なら「埋める値」を1バイト読む（bit3=1 のときだけ意味を持つ）

    ビットマップ方式:
        16ビットの並びを上位から1ビットずつ見て
            1 … 次の1バイトを読む
            0 … 「埋める値」を置く
        ⚠ 16ビットは **先に読んだバイトが下位**（`asl $DD / rol $DE`）。

    ★★ 反転を4通り作り置きしているのは、**NESの背景タイルは反転できない**から。
       ハード任せにできないので、展開時に4枚に増やしている。

## 置き方

| 記録 | 続き | 置き方 |
| --- | --- | --- |
| bit6=1 | 1バイト | `(行<<4) | 列` の 8x8 格子 → 画素 `(列*8, 行*8)` |
| bit6=0 | 2バイト | 画素 `(1バイト目, 2バイト目 - 0x38)` |

★格子のほう（bit6=1）が**絵の本体**で、実機の撮影と完全一致している。
⚠ bit6=0 のほうは撮影3枚から式を割り出したもので、**確度は一段低い**
  （`docs/rom-analysis-notes.md`）。`confidence` を分けて出す。

## count は敵ごとに違う

索引表の count は「読むブロック数」。**同じ絵でも色違いの上位種のほうが多い**
（例 `$8459`: まじゅつし 25 / 上位種 29）。
絵のデータ領域の大きさは**その絵を使う敵の最大 count** で決まる。
"""

from __future__ import annotations

import dataclasses

BANK1_PRG_BASE = 0x4000      # bank 1 の PRG オフセット
BANK1_PRG_END = 0x8000
WINDOW_BASE = 0x8000         # 切り替えバンクの CPU アドレス

# bit6=0 の記録の Y に足す下駄。★撮影から割り出した（`research/probes/archived/probe_gfx4.py`）
OTHER_Y_BIAS = 0x38

TILE_BYTES = 16
VARIANTS = 4


class DecodeError(ValueError):
    """絵を展開できなかった。"""


@dataclasses.dataclass(frozen=True)
class Placement:
    """タイル1枚をどこに置くか。"""

    x: int
    y: int
    variant: int
    on_grid: bool               # True: 8x8 格子（確認済み） / False: 画素指定
    raw: tuple[int, ...]        # 記録のバイト列（生のまま残す）


@dataclasses.dataclass(frozen=True)
class Block:
    """1ブロック = タイル1枚（4通りの向き）＋ 置き方の列。"""

    prg_start: int
    prg_end: int
    variants: tuple[bytes, ...]
    placements: tuple[Placement, ...]
    fill: int
    bitmap: int
    literal: bool               # True: 16バイトそのまま / False: ビットマップ


class _Reader:
    """bank 1 の中だけを読む。★範囲外は例外（黙って 0 を返さない）。"""

    __slots__ = ("prg", "pos")

    def __init__(self, prg: bytes, cpu_addr: int) -> None:
        if not WINDOW_BASE <= cpu_addr <= 0xBFFF:
            raise DecodeError(
                f"絵のポインタが切り替えバンクの窓の外です: ${cpu_addr:04X}")
        self.prg = prg
        self.pos = BANK1_PRG_BASE + (cpu_addr - WINDOW_BASE)

    def read(self) -> int:
        if not BANK1_PRG_BASE <= self.pos < BANK1_PRG_END:
            raise DecodeError(f"bank 1 の外へ出ました: 0x{self.pos:05X}")
        value = self.prg[self.pos]
        self.pos += 1
        return value

    def skip(self, n: int) -> None:
        self.pos += n


def flip_bits(value: int) -> int:
    """1バイトのビットを逆順にする（＝タイルを左右反転）。"""
    value = ((value & 0xF0) >> 4) | ((value & 0x0F) << 4)
    value = ((value & 0xCC) >> 2) | ((value & 0x33) << 2)
    return ((value & 0xAA) >> 1) | ((value & 0x55) << 1)


def make_variants(tile: bytes) -> tuple[bytes, ...]:
    """そのまま / 左右 / 上下 / 両方 の4枚を作る。

    ★上下反転は「8バイトずつ逆順」。NESのタイルは
      前半8バイトが下位プレーン、後半8バイトが上位プレーンなので、
      **プレーンをまたいで逆順にしてはいけない**。
    """
    if len(tile) != TILE_BYTES:
        raise DecodeError(f"タイルは16バイトのはずです: {len(tile)}")
    h = bytes(flip_bits(b) for b in tile)
    v = bytes(tile[7::-1]) + bytes(tile[15:7:-1])
    hv = bytes(h[7::-1]) + bytes(h[15:7:-1])
    return (bytes(tile), h, v, hv)


def _read_records(reader: _Reader, keep: bool) -> list[tuple[int, list[int]]]:
    """記録の列を読む。`keep=False` なら中身を捨てて位置だけ進める。"""
    out: list[tuple[int, list[int]]] = []
    for _ in range(256):                       # ★上限を置く（無限ループ避け）
        head = reader.read()
        extra_count = 1 if (head & 0x40) else 2
        if keep:
            out.append((head, [reader.read() for _ in range(extra_count)]))
        else:
            reader.skip(extra_count)
            out.append((head, []))
        if head & 0x80:
            return out
    raise DecodeError("記録の列が終わりません（256件を超えました）")


def _to_placement(head: int, extra: list[int]) -> Placement:
    variant = (head >> 1) & 0x03
    if head & 0x40:
        return Placement(x=(extra[0] & 0x0F) * 8, y=(extra[0] >> 4) * 8,
                         variant=variant, on_grid=True, raw=tuple(extra))
    return Placement(x=extra[0], y=extra[1] - OTHER_Y_BIAS,
                     variant=variant, on_grid=False, raw=tuple(extra))


def decode_block(prg: bytes, cpu_addr: int) -> Block:
    """1ブロック読む。"""
    scan = _Reader(prg, cpu_addr)
    start = scan.pos
    records = _read_records(scan, keep=False)

    # --- 末尾の「タイルの作り方」---
    last = records[-1][0]
    fill = 0x00
    bitmap = 0xFFFF
    literal = not (last & 0x08)
    if last & 0x08:
        if last & 0x01:
            fill = scan.read()
        low = scan.read()
        high = scan.read()
        bitmap = (high << 8) | low      # ⚠ 先に読むほうが下位

    tile = bytearray()
    bits = bitmap
    for _ in range(TILE_BYTES):
        take = (bits >> 15) & 1
        bits = (bits << 1) & 0xFFFF
        tile.append(scan.read() if take else fill)
    end = scan.pos

    # --- もう一度先頭から読んで、置き方を取る ---
    again = _Reader(prg, cpu_addr)
    placements = tuple(_to_placement(head, extra)
                       for head, extra in _read_records(again, keep=True))

    return Block(prg_start=start, prg_end=end,
                 variants=make_variants(bytes(tile)),
                 placements=placements, fill=fill, bitmap=bitmap,
                 literal=literal)


def decode_monster(prg: bytes, cpu_addr: int, count: int) -> list[Block]:
    """1体ぶん（count ブロック）を展開する。"""
    if count <= 0:
        raise DecodeError(f"ブロック数が正ではありません: {count}")
    blocks: list[Block] = []
    addr = cpu_addr
    for _ in range(count):
        block = decode_block(prg, addr)
        blocks.append(block)
        addr = WINDOW_BASE + (block.prg_end - BANK1_PRG_BASE)
    return blocks


def consumed_end(blocks: list[Block]) -> int:
    """最後のブロックが終わった CPU アドレス。

    ★これが「索引表が言う次の絵の位置」と一致するかが**区切り方の裏取り**。
    """
    return WINDOW_BASE + (blocks[-1].prg_end - BANK1_PRG_BASE)
