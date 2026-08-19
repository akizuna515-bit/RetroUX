"""ビット列の読み出し（指示書 16.1「MSB/LSB順を指定できるビットストリーム」）。

★★ **ビット順は推測していない。逆アセンブルで確かめた** ★★

  北米版 `bank2.asm` の「read 1 bit of map data into C」:

      lda #$80          ; ★マスクは **bit7 から**
      ldy $614D         ; いま何ビット目か
      ...  lsr / dey    ; その回数だけ右へずらす

  そして「read A bits」は

      jsr <1ビット読む>
      rol $6D           ; ★先に読んだビットが**上位**に来る
      rol $6E

  -> **MSB ファースト**。複数ビット値は最初に読んだビットが最上位。
  （`docs/design/rom-analysis-tools-spec.md` 2.2）

  モンスターの絵（`B04_8971`）も `asl $DD / rol $DE` で回しており同じ向き。
  それでも **順序を選べるようにしてある**のは、ワールドマップなど
  まだ読んでいない場所で違う可能性を残すため（指示書 16.1）。
"""

from __future__ import annotations


class BitstreamError(ValueError):
    """ビット列の読み出しに失敗した（範囲外・引数不正）。"""


class BitReader:
    """バイト列をビット単位で読む。

    ★**範囲外は必ず例外**にする（指示書 M3「無限ループ・ROM範囲外参照を防ぐ」）。
      黙って 0 を返すと、壊れたポインタを渡したときに
      「それらしいが全部間違っている地図」が出てきて気づけない。
    """

    __slots__ = ("_data", "_start", "_pos", "_bit", "_msb_first")

    def __init__(self, data: bytes, start: int = 0, *, msb_first: bool = True) -> None:
        if start < 0 or start > len(data):
            raise BitstreamError(f"開始位置が範囲外です: {start} / 長さ {len(data)}")
        self._data = data
        self._start = start
        self._pos = start
        self._bit = 0
        self._msb_first = msb_first

    # --- いまどこか -----------------------------------------------------

    @property
    def byte_pos(self) -> int:
        """次に読むバイトの位置（読みかけのバイトを含む）。"""
        return self._pos

    @property
    def bit_pos(self) -> int:
        """読みかけのバイトの中で、いま何ビット目か（0..7）。"""
        return self._bit

    @property
    def bits_read(self) -> int:
        return (self._pos - self._start) * 8 + self._bit

    @property
    def bytes_consumed(self) -> int:
        """★消費バイト数（指示書 4.3 のログ項目）。読みかけは1バイトと数える。"""
        return self._pos - self._start + (1 if self._bit else 0)

    @property
    def exhausted(self) -> bool:
        return self._pos >= len(self._data)

    # --- 読む -----------------------------------------------------------

    def read_bit(self) -> int:
        if self._pos >= len(self._data):
            raise BitstreamError(
                f"ビット列の終端を超えました（{self.bits_read} ビット読んだところ）")
        byte = self._data[self._pos]
        shift = (7 - self._bit) if self._msb_first else self._bit
        value = (byte >> shift) & 1
        self._bit += 1
        if self._bit == 8:
            self._bit = 0
            self._pos += 1
        return value

    def read(self, count: int) -> int:
        """`count` ビットを読んで整数にする。最初に読んだビットが最上位。"""
        if count < 0:
            raise BitstreamError(f"ビット数が負です: {count}")
        if count == 0:
            return 0
        if count > 32:
            # 32ビットを超える読みは、ほぼ確実にビット数の計算間違い。
            # 大きな値を返して先で暴走させるより、ここで止める。
            raise BitstreamError(f"一度に読むには大きすぎます: {count} ビット")
        value = 0
        for _ in range(count):
            value = (value << 1) | self.read_bit()
        return value

    def align_to_byte(self) -> int:
        """読みかけのビットを捨ててバイト境界へ。捨てたビット数を返す。"""
        if self._bit == 0:
            return 0
        skipped = 8 - self._bit
        self._bit = 0
        self._pos += 1
        return skipped

    def read_byte_aligned(self) -> int:
        """バイト境界からそのまま1バイト読む（ヘッダ用）。"""
        if self._bit != 0:
            raise BitstreamError(
                "バイト境界にいません。align_to_byte() を先に呼んでください")
        if self._pos >= len(self._data):
            raise BitstreamError("ビット列の終端を超えました")
        value = self._data[self._pos]
        self._pos += 1
        return value


def coordinate_bits(width: int, height: int) -> int:
    """座標に使うビット数（指示書 11.1）。

        ceil(log2(width * height))

    ★境界を落とさないこと。`width*height` がちょうど2の冪のときは
      `log2` が整数になり、`math.ceil` を素直に使うと**1ビット足りない**
      ように見えるが、一次元インデックスは `0 .. w*h-1` なので
      **これで正しい**（16 マスなら 4 ビットで 0..15）。
      浮動小数の丸めを避けるため整数演算で出す。
    """
    if width <= 0 or height <= 0:
        raise BitstreamError(f"幅・高さが正ではありません: {width}x{height}")
    total = width * height
    if total == 1:
        return 0
    return (total - 1).bit_length()


def index_to_xy(index: int, width: int) -> tuple[int, int]:
    """一次元インデックス → (x, y)（指示書 11.1）。"""
    if width <= 0:
        raise BitstreamError(f"幅が正ではありません: {width}")
    if index < 0:
        raise BitstreamError(f"インデックスが負です: {index}")
    return index % width, index // width
