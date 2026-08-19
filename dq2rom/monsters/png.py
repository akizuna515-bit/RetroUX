"""PNG を書く（外部ライブラリなし）。

★このツールは **RetroUX 本体から独立**している（指示書 §19-9）ので、
  本体が使っている PySide6 に依存させたくない。
  PNG は zlib と struct だけで書けるので自前で持つ。

対応するのは RGBA 8bit の非インターレースだけ。それで足りる。
"""

from __future__ import annotations

import pathlib
import struct
import zlib

Pixel = tuple[int, int, int, int]


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def encode(rows: list[list[Pixel]]) -> bytes:
    """RGBA の2次元配列 → PNG のバイト列。"""
    if not rows or not rows[0]:
        raise ValueError("空の画像は書けません")
    height = len(rows)
    width = len(rows[0])
    if any(len(r) != width for r in rows):
        raise ValueError("行の長さがそろっていません")

    raw = bytearray()
    for row in rows:
        raw.append(0)                      # フィルタなし
        for r, g, b, a in row:
            raw += bytes((r & 0xFF, g & 0xFF, b & 0xFF, a & 0xFF))

    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def scale(rows: list[list[Pixel]], factor: int) -> list[list[Pixel]]:
    """最近傍で拡大する（指示書 6.1）。ぼかさない。"""
    if factor < 1:
        raise ValueError(f"倍率が 1 未満です: {factor}")
    if factor == 1:
        return rows
    out = []
    for row in rows:
        wide = [px for px in row for _ in range(factor)]
        out.extend([list(wide) for _ in range(factor)])
    return out


def write(path: str | pathlib.Path, rows: list[list[Pixel]],
          factor: int = 1) -> pathlib.Path:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(encode(scale(rows, factor)))
    return p
