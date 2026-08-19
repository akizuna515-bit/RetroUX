"""iNES ヘッダの解析と、バンク↔ファイルオフセットの変換。

★★ **マッパーは指示書の記述ではなく ROM ヘッダから読む** ★★

  指示書 2.2 は「DQ2はMapper 1（MMC1）」と書いているが、指示書自身が挙げた
  ハッシュの ROM（＝このプロジェクトの日本版）を実測すると **Mapper 2 (UNROM)**
  だった。指示書の値をそのまま使うと、バンク↔オフセットの変換が全部ずれる。
  （北米版 Dragon Warrior II が MMC1 なので、そちらの値が混ざったと思われる）

  詳細は `docs/design/rom-analysis-tools-spec.md` 1.1。

UNROM (mapper 2) のメモリ配置:

    $8000-$BFFF … 切り替えバンク（0 〜 banks-2）
    $C000-$FFFF … **最終バンク固定**

そのため「CPUアドレス → ファイルオフセット」は**バンク番号が要る**。
バンク番号なしで変換できるのは `$C000-$FFFF` だけ。
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import zlib

HEADER_SIZE = 16
PRG_BANK_SIZE = 0x4000          # 16KB
CHR_BANK_SIZE = 0x2000          # 8KB
MAGIC = b"NES\x1a"

MAPPER_UNROM = 2
MAPPER_MMC1 = 1


class InesError(ValueError):
    """iNES として読めなかった。"""


@dataclasses.dataclass(frozen=True)
class Rom:
    """読み込んだ ROM。

    ★`prg` は**ヘッダを除いた**バイト列。ROM オフセットを言うときは
      「ヘッダ込みのファイル位置」と混ざりやすいので、この型では
      **常に PRG 先頭からの位置**で扱い、ファイル位置が要る場所では
      `file_offset()` を通す。
    """

    path: pathlib.Path | None
    raw: bytes
    prg: bytes
    chr: bytes
    prg_banks: int
    chr_banks: int
    mapper: int
    mirroring: str
    has_battery: bool
    has_trainer: bool
    sha1: str
    md5: str
    crc32: str

    # --- 変換 ---------------------------------------------------------

    @property
    def uses_chr_ram(self) -> bool:
        """CHR-ROM が 0 枚か。0 なら絵は実行時に CHR-RAM へ書かれる。"""
        return self.chr_banks == 0

    @property
    def fixed_bank(self) -> int:
        """`$C000-$FFFF` に居座るバンク番号（UNROM は最終バンク）。"""
        return self.prg_banks - 1

    def file_offset(self, prg_offset: int) -> int:
        """PRG 先頭からの位置 → ファイル先頭からの位置。"""
        return HEADER_SIZE + prg_offset

    def prg_offset(self, bank: int, cpu_addr: int) -> int:
        """バンク番号と CPU アドレスから PRG オフセットを出す。

        ⚠ `$C000-$FFFF` を指定した場合、UNROM では**固定バンク**なので
          `bank` は無視される。黙って無視すると事故るので明示的に扱う。
        """
        if not 0 <= bank < self.prg_banks:
            raise InesError(f"バンク番号が範囲外です: {bank}（0..{self.prg_banks - 1}）")
        if not 0x8000 <= cpu_addr <= 0xFFFF:
            raise InesError(f"CPU アドレスが ROM 領域ではありません: ${cpu_addr:04X}")

        if self.mapper == MAPPER_UNROM and cpu_addr >= 0xC000:
            bank = self.fixed_bank
            return bank * PRG_BANK_SIZE + (cpu_addr - 0xC000)

        window = 0x8000 if cpu_addr < 0xC000 else 0xC000
        return bank * PRG_BANK_SIZE + (cpu_addr - window)

    def cpu_address(self, prg_offset: int) -> tuple[int, int]:
        """PRG オフセット → (バンク番号, CPU アドレス)。

        ★戻す CPU アドレスは**切り替え窓 `$8000` 基準**。
          固定バンクは `$C000` 基準でも読めるが、2通りの答えがあると
          突き合わせで混乱するので片方に統一する。
        """
        if not 0 <= prg_offset < len(self.prg):
            raise InesError(f"PRG の範囲外です: 0x{prg_offset:X}")
        bank, within = divmod(prg_offset, PRG_BANK_SIZE)
        return bank, 0x8000 + within


def _mirroring(flags6: int) -> str:
    if flags6 & 0x08:
        return "four_screen"
    return "vertical" if flags6 & 0x01 else "horizontal"


def parse(data: bytes, path: pathlib.Path | None = None) -> Rom:
    """iNES バイト列を解析する。

    ★壊れた入力で**黙って変な値を返さない**（指示書 M3「境界チェック」）。
    """
    if len(data) < HEADER_SIZE:
        raise InesError(f"ファイルが短すぎます（{len(data)} バイト）")
    if data[:4] != MAGIC:
        raise InesError("iNES のマジック 'NES\\x1a' がありません")

    prg_banks = data[4]
    chr_banks = data[5]
    flags6 = data[6]
    flags7 = data[7]
    if prg_banks == 0:
        raise InesError("PRG バンク数が 0 です")

    has_trainer = bool(flags6 & 0x04)
    mapper = (flags6 >> 4) | (flags7 & 0xF0)

    start = HEADER_SIZE + (512 if has_trainer else 0)
    prg_len = prg_banks * PRG_BANK_SIZE
    chr_len = chr_banks * CHR_BANK_SIZE
    if len(data) < start + prg_len:
        raise InesError(
            f"PRG が足りません（ヘッダは {prg_len} バイトと言っているが "
            f"実体は {len(data) - start} バイト）")

    prg = data[start:start + prg_len]
    chr_data = data[start + prg_len:start + prg_len + chr_len]

    return Rom(
        path=path,
        raw=data,
        prg=prg,
        chr=chr_data,
        prg_banks=prg_banks,
        chr_banks=chr_banks,
        mapper=mapper,
        mirroring=_mirroring(flags6),
        has_battery=bool(flags6 & 0x02),
        has_trainer=has_trainer,
        sha1=hashlib.sha1(data).hexdigest(),
        md5=hashlib.md5(data).hexdigest(),
        crc32=format(zlib.crc32(data) & 0xFFFFFFFF, "08x"),
    )


def load(path: str | pathlib.Path) -> Rom:
    p = pathlib.Path(path)
    if not p.exists():
        raise InesError(f"ROM がありません: {p}")
    return parse(p.read_bytes(), p)


def describe(rom: Rom) -> dict:
    """`inspect` が出す情報。JSON にそのまま入れられる形。"""
    return {
        "path": str(rom.path) if rom.path else None,
        "size_bytes": len(rom.raw),
        "hashes": {"sha1": rom.sha1, "md5": rom.md5, "crc32": rom.crc32},
        "prg_banks": rom.prg_banks,
        "prg_bytes": len(rom.prg),
        "chr_banks": rom.chr_banks,
        "chr_bytes": len(rom.chr),
        "uses_chr_ram": rom.uses_chr_ram,
        "mapper": rom.mapper,
        "mapper_name": {MAPPER_MMC1: "MMC1", MAPPER_UNROM: "UNROM"}.get(
            rom.mapper, f"mapper {rom.mapper}"),
        "mirroring": rom.mirroring,
        "has_battery": rom.has_battery,
        "has_trainer": rom.has_trainer,
        "fixed_bank": rom.fixed_bank,
    }
