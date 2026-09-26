"""DQ3 のエリアマップ（町・城・洞窟）243 件を展開する（RX3-0005 / 2026-08-23）。

## ディレクトリ（調査資料 §7.1 / 2026-08-23 実測で全件一致）

    file 0x01C04E 〜 0x01C327（exclusive）= 243 × 3 bytes
    entry: byte0-1 = CPU ポインタ（little-endian）/ byte2 = tileset ID
    pointer == 0 → 未使用（39 件）

    bank の決め方: tileset >= 0x0C → bank 7 / それ未満 → bank 6
    file = 0x10 + bank * 0x4000 + (pointer - 0x8000)

## デコーダ

    ★DQ2 の MDEC デコーダ（`dq2rom.maps.decoder`）を**そのまま**使う。
      2026-08-23 に「bank 6/7 の 16KB 窓を渡せば無改造で 204/204」と裏を取った。
      入口を `decode_window(window, cpu, semantics=DQ3)` に広げ、
      **意味づけ**（ヘッダ下位 5 bit = 背景 / 第 2 パス = OR）だけ差し替える。

    ⚠ DQ3 の意味づけは北米版公開コード由来で**実機の見え方は未確認**。
      寸法・消費 byte・命令数は confirmed だが、`phase2` の合成が正しいかは
      Phase 6 で復号 RAM（`$7400`）と比べるまで high-confidence 止まり。
"""

from __future__ import annotations

import dataclasses

from dq2rom.maps import decoder as mdec

from .profile import Identified

ENTRY_SIZE = 3
TILESET_BANK7_FROM = 0x0C


@dataclasses.dataclass(frozen=True)
class Entry:
    map_id: int
    pointer: int
    tileset: int

    @property
    def used(self) -> bool:
        return self.pointer != 0

    @property
    def bank(self) -> int | None:
        if not self.used:
            return None
        return 7 if self.tileset >= TILESET_BANK7_FROM else 6


@dataclasses.dataclass(frozen=True)
class AreaMap:
    entry: Entry
    file_offset: int
    decoded: mdec.DecodedMap | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.decoded is not None

    def to_meta(self) -> dict:
        """243 件の一覧用（指示書 §8「出力」の項目）。"""
        e = self.entry
        meta = {
            "map_id": e.map_id,
            "used": e.used,
            "pointer": f"0x{e.pointer:04X}" if e.used else None,
            "tileset": f"0x{e.tileset:02X}",
            "bank": e.bank,
            "file_offset": f"0x{self.file_offset:06X}" if e.used else None,
        }
        if self.decoded is not None:
            d = self.decoded
            meta.update({
                "width": d.width, "height": d.height,
                "consumed_bytes": d.bytes_consumed,
                "command_count": d.commands,
                "background_tile": d.background,
                "fill_tile": d.fill_tile,
                "second_pass": d.has_phase2,
                "tile_id_bits": d.tile_id_bits,
                "decode_result": "ok",
            })
        else:
            meta["decode_result"] = self.error or ("unused" if not e.used else "failed")
        return meta


def read_directory(ident: Identified) -> list[Entry]:
    t = ident.table("area_directory")
    start = ident.table_prg("area_directory")
    n = int(t["entries"])
    end = ident.table_prg("area_directory", "end_file_exclusive")
    if start + n * ENTRY_SIZE != end:
        raise ValueError(
            f"ディレクトリの終端が合いません: 0x{start + n * ENTRY_SIZE:X} != 0x{end:X}")
    prg = ident.rom.prg
    out = []
    for i in range(n):
        e = prg[start + i * ENTRY_SIZE: start + (i + 1) * ENTRY_SIZE]
        out.append(Entry(map_id=i, pointer=int.from_bytes(e[0:2], "little"),
                         tileset=e[2]))
    return out


def decode_entry(ident: Identified, entry: Entry) -> AreaMap:
    if not entry.used:
        return AreaMap(entry=entry, file_offset=0, decoded=None, error=None)
    bank = entry.bank
    file_off = ident.file_offset(bank, entry.pointer)
    try:
        d = mdec.decode_window(ident.window(bank), entry.pointer,
                               semantics=mdec.DQ3,
                               prg_base=bank * mdec.WINDOW_SIZE, prg_bank=bank)
        return AreaMap(entry=entry, file_offset=file_off, decoded=d, error=None)
    except mdec.MapDecodeError as exc:
        return AreaMap(entry=entry, file_offset=file_off, decoded=None,
                       error=f"failed: {exc}")


def decode_all(ident: Identified) -> list[AreaMap]:
    return [decode_entry(ident, e) for e in read_directory(ident)]


def summary(maps: list[AreaMap]) -> dict:
    return {
        "decoded": sum(1 for m in maps if m.ok),
        "failed": sum(1 for m in maps if m.entry.used and not m.ok),
        "unused": sum(1 for m in maps if not m.entry.used),
        "max_cells": max((m.decoded.width * m.decoded.height
                          for m in maps if m.ok), default=0),
    }
