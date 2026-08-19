"""街・城・ダンジョンのマップを展開する（北米版 `bank2.asm` の移植）。

★★ **指示書 §11 の記述は、逆アセンブルとほぼ一致していた** ★★
  ただし**呼び名と細部が違う**ので、逆アセンブルのほうを正とした:

| 指示書 | 逆アセンブル | 採った側 |
| --- | --- | --- |
| visibility regions（視界領域） | **roofing phase（屋根）** | 逆アセンブル。名前は決め打ちせず `phase2` として出す |
| ヘッダは 幅・高さ・タイルIDビット長 | **幅・高さ・(タイルIDビット長＋未使用5ビット)** の3バイト | 逆アセンブル |
| スタックは FIFO と書かれた箇所がある | `$616B` を index で push/pop する **LIFO** | 逆アセンブル（指示書 11.4 も「LIFOで実装せよ」としている） |

---

## 形式

### ヘッダ（3バイト・バイト境界）

    byte0  幅
    byte1  高さ
    byte2  bit7-6 → タイルIDのビット数 = (byte2 >> 6) + 2   （2〜5ビット）
           bit4-0 → 未使用（`$6158`。逆アセンブルにも "unused?" とある）

座標のビット数は **幅×高さ から計算**する（ヘッダには無い）:

    ceil(log2(width * height))     ＝ (width*height - 1).bit_length()

### 第1フェーズ（下地）

1. タイルIDを1つ読み、**マップ全体をその値で埋める**
2. 以後、2ビットずつ読んで命令を実行する

| 命令 | 内容 |
| --- | --- |
| `00` | 「いま置くもの」を決める。1x1 か 2x2 か、あるいは**フェーズ終了** |
| `01` | 2点の座標を読み、その矩形を埋める |
| `10` | 1点から線を引く（向きを回しながら。push/pop あり） |
| `11` | 1点に置く |

`00` の詳細（ここが読み間違えやすい）:

    タイルIDを1つ読む → これが「いま置くもの」
    2ビット読む
      != 0 なら **その値を次の命令として実行**する（`00` に戻らない）
      == 0 なら さらに1ビット読む
            1 → **このフェーズを終わる**
            0 → 2x2 ブロックにする。タイルIDを**あと3つ**読む

### 第2フェーズ（屋根 / roofing）

2ビット読み、0 なら第2フェーズ無し。0 以外ならその値が
**第2フェーズでのタイルIDのビット数**になり、同じ命令列を処理する。
書き込み先は同じマスの**上位3ビット**（下位5ビットの地形は保つ）。

    マスの値 = (屋根 << 5) | 地形

★つまり「地形」と「第2フェーズの値」は**同じ配列の別ビット**。
  出力では**別レイヤーに分けて**返す（指示書 §10「別レイヤーにする」）。
"""

from __future__ import annotations

import dataclasses

from ..bitstream import BitReader, BitstreamError, coordinate_bits

BANK2_PRG_BASE = 0x8000
BANK2_PRG_END = 0xC000
WINDOW_BASE = 0x8000

TILE_MASK = 0x1F            # 地形は下位5ビット（`and #$1F` で屋根を落としている）
ROOF_SHIFT = 5

# 命令の上限。★壊れたデータで止まらなくならないように必ず置く
MAX_COMMANDS = 20000
MAX_STEPS = 20000

# 向き（`$6151`）。`$AEBC` の分岐そのまま
DIRECTIONS = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}


class MapDecodeError(ValueError):
    """マップを展開できなかった。"""


@dataclasses.dataclass(frozen=True)
class DecodedMap:
    width: int
    height: int
    tile_id_bits: int
    coord_bits: int
    background: int
    tiles: list[list[int]]          # 地形（0..31）
    phase2: list[list[int]]         # 屋根 / 視界（0..7）。★名前は決め打ちしない
    has_phase2: bool
    phase2_bits: int
    prg_start: int
    prg_end: int
    bytes_consumed: int
    commands: int
    unused_header_bits: int

    def to_json(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "tile_id_bits": self.tile_id_bits,
            "coord_bits": self.coord_bits,
            "background_tile_id": self.background,
            "tiles": self.tiles,
            # ⚠ 指示書は "visibility_regions" と呼ぶが、逆アセンブルは
            #   "roofing phase"。**どちらか断定せず** phase2 で出す
            "phase2_layer": self.phase2,
            "has_phase2": self.has_phase2,
            "phase2_bits": self.phase2_bits,
            "source": {
                "prg_bank": 2,
                "rom_offset_start": f"0x{self.prg_start:05X}",
                "rom_offset_end": f"0x{self.prg_end:05X}",
                "bytes_consumed": self.bytes_consumed,
                "commands": self.commands,
                "unused_header_bits": self.unused_header_bits,
            },
        }


class _Canvas:
    """マップの升目。地形と第2フェーズを**同じ1バイト**で持つ（実機と同じ）。

    ★分けて持つと、第2フェーズが「地形を保ったまま上位ビットだけ差し替える」
      という実機の挙動を写せない。取り出すときに分ける。
    """

    __slots__ = ("width", "height", "cells")

    def __init__(self, width: int, height: int, background: int) -> None:
        self.width = width
        self.height = height
        self.cells = [background & TILE_MASK] * (width * height)

    def write(self, index: int, value: int, roofing: bool) -> None:
        # ★範囲外は**黙って捨てる**。実機は $7800 のバッファへ書くだけなので
        #   はみ出しても止まらない。ここで例外にすると、実機では読める
        #   マップが「展開できない」になってしまう。
        if not 0 <= index < len(self.cells):
            return
        if roofing:
            self.cells[index] = (self.cells[index] & TILE_MASK) | \
                ((value & 0x07) << ROOF_SHIFT)
        else:
            self.cells[index] = (self.cells[index] & ~TILE_MASK & 0xFF) | \
                (value & TILE_MASK)

    def rows(self, mask: int, shift: int) -> list[list[int]]:
        return [[(self.cells[y * self.width + x] >> shift) & mask
                 for x in range(self.width)]
                for y in range(self.height)]


class _Decoder:
    def __init__(self, reader: BitReader, canvas: _Canvas, tile_bits: int,
                 coord_bits: int) -> None:
        self.r = reader
        self.c = canvas
        self.tile_bits = tile_bits
        self.coord_bits = coord_bits
        self.roofing = False
        self.block = [0, 0, 0, 0]
        self.is_2x2 = False
        self.stack: list[tuple[int, int]] = []
        self.commands = 0

    # --- 部品 ---------------------------------------------------------

    def tile_id(self) -> int:
        return self.r.read(self.tile_bits)

    def coord(self) -> int:
        return self.r.read(self.coord_bits)

    def put_block(self, index: int) -> None:
        """いまのブロックを1か所に置く（1x1 なら1マス、2x2 なら4マス）。"""
        self.c.write(index, self.block[0], self.roofing)
        if not self.is_2x2:
            return
        w = self.c.width
        self.c.write(index + 1, self.block[1], self.roofing)
        self.c.write(index + w, self.block[2], self.roofing)
        self.c.write(index + w + 1, self.block[3], self.roofing)

    # --- 命令 ---------------------------------------------------------

    def cmd_set_block(self) -> int | None:
        """`00`: いま置くものを決める。戻り値が命令なら続けてそれを実行する。"""
        self.is_2x2 = False
        self.block[0] = self.tile_id()
        nxt = self.r.read(2)
        if nxt != 0:
            return nxt                       # ★その値が次の命令
        if self.r.read(1):
            return None                      # ★フェーズ終了
        self.is_2x2 = True
        self.block[1] = self.tile_id()
        self.block[2] = self.tile_id()
        self.block[3] = self.tile_id()
        return 0                             # 続ける（次の2ビットを読む）

    def cmd_rect(self) -> None:
        """`01`: 2点の間を埋める。"""
        w = self.c.width
        start = self.coord()
        end = self.coord()
        sx, sy = start % w, start // w
        ex, ey = end % w, end // w
        cols, rows = ex - sx, ey - sy
        if self.is_2x2:
            # ★実機は「差」を2で割る（`lsr`）。**先に差を出してから割る**
            cols >>= 1
            rows >>= 1
        cols += 1
        rows += 1
        step = 2 if self.is_2x2 else 1
        for ry in range(max(rows, 0)):
            for rx in range(max(cols, 0)):
                self.put_block(start + ry * step * w + rx * step)

    def cmd_point(self) -> None:
        """`11`: 1点に置く。"""
        self.put_block(self.coord())

    def cmd_line(self) -> None:
        """`10`: 線を引く。

        ★向きの回し方と push/pop は `$AE48`〜`$AEB3` のとおり。
          スタックは **LIFO**（指示書 11.4 の注意書きと一致）。
        """
        step = 2 if self.is_2x2 else 1
        for _ in range(MAX_STEPS):
            index = self.coord()
            self.put_block(index)
            direction = self.r.read(2)
            for _ in range(MAX_STEPS):
                if not self.r.read(1):
                    index = self._move(index, direction, step)
                    self.put_block(index)
                    continue
                sub = self.r.read(2)
                if sub == 0:
                    direction = (direction + 1) & 3
                elif sub == 1:
                    direction = (direction - 1) & 3
                elif sub == 2:
                    self.stack.append((index, direction))
                    # ★1ビット読んで回す向きを決める（push はもう済んでいる）
                    direction = ((direction - 1) if self.r.read(1)
                                 else (direction + 1)) & 3
                else:
                    if self.r.read(1):
                        if not self.stack:
                            return           # 底を pop したら命令の終わり
                        index, direction = self.stack.pop()
                        continue
                    break                    # 新しい座標から引き直す
                index = self._move(index, direction, step)
                self.put_block(index)
            else:
                raise MapDecodeError("線の命令が終わりません")
        raise MapDecodeError("線の命令の引き直しが終わりません")

    def _move(self, index: int, direction: int, step: int) -> int:
        dx, dy = DIRECTIONS[direction]
        return index + dx * step + dy * step * self.c.width

    # --- まわす -------------------------------------------------------

    def run(self) -> None:
        pending: int | None = 0
        for _ in range(MAX_COMMANDS):
            code = self.r.read(2) if pending == 0 else pending
            pending = 0
            self.commands += 1
            if code == 0:
                nxt = self.cmd_set_block()
                if nxt is None:
                    return
                pending = nxt
            elif code == 1:
                self.cmd_rect()
            elif code == 2:
                self.cmd_line()
            else:
                self.cmd_point()
        raise MapDecodeError(f"命令が {MAX_COMMANDS} 個を超えました")


def decode_map(prg: bytes, cpu_addr: int) -> DecodedMap:
    """1マップぶん展開する。"""
    if not WINDOW_BASE <= cpu_addr <= 0xBFFF:
        raise MapDecodeError(
            f"マップのポインタが切り替えバンクの窓の外です: ${cpu_addr:04X}")
    start = BANK2_PRG_BASE + (cpu_addr - WINDOW_BASE)
    if start + 3 > min(len(prg), BANK2_PRG_END):
        raise MapDecodeError(f"マップの先頭が bank 2 の外です: 0x{start:05X}")

    width = prg[start]
    height = prg[start + 1]
    flags = prg[start + 2]
    if width == 0 or height == 0:
        raise MapDecodeError(f"幅・高さが 0 です（{width}x{height}）")

    tile_bits = (flags >> 6) + 2
    coord = coordinate_bits(width, height)

    reader = BitReader(prg, start + 3, msb_first=True)
    canvas = _Canvas(width, height, 0)

    try:
        dec = _Decoder(reader, canvas, tile_bits, coord)
        background = dec.tile_id()
        canvas.cells = [background & TILE_MASK] * (width * height)
        dec.run()

        # --- 第2フェーズ（屋根 / 視界）---
        phase2_bits = reader.read(2)
        has_phase2 = phase2_bits != 0
        if has_phase2:
            dec.roofing = True
            dec.tile_bits = phase2_bits      # ★このフェーズだけビット数が変わる
            dec.is_2x2 = False
            dec.stack.clear()
            dec.run()
    except BitstreamError as exc:
        raise MapDecodeError(str(exc)) from exc

    end = reader.byte_pos + (1 if reader.bit_pos else 0)
    return DecodedMap(
        width=width, height=height, tile_id_bits=tile_bits, coord_bits=coord,
        background=background,
        tiles=canvas.rows(TILE_MASK, 0),
        phase2=canvas.rows(0x07, ROOF_SHIFT),
        has_phase2=has_phase2, phase2_bits=phase2_bits,
        prg_start=start, prg_end=end,
        bytes_consumed=end - start, commands=dec.commands,
        unused_header_bits=flags & 0x1F,
    )


def consumed_end_addr(decoded: DecodedMap) -> int:
    """展開が終わった CPU アドレス。

    ★これが「ヘッダ表の言う次のマップの位置」と一致するかが**裏取り**。
      （モンスターの絵で使ったのと同じ手）
    """
    return WINDOW_BASE + (decoded.prg_end - BANK2_PRG_BASE)
