"""DQ3 の ROM を**版まで**識別し、表の位置を profile から引く（RX3-0002 / 2026-08-23）。

★★ **未知の hash は「たぶん動く」で進めない**（指示書 §2.3）★★

  Rev 0A（payload CRC32 `A49B48B8`）の offset を、後期版（`869501CA`）へ
  無条件に当ててはいけない。版が違えば表の位置がずれている可能性があり、
  ⚠ ずれたまま読むと**もっともらしい数字が出てしまう**（落ちない分たちが悪い）。

  → 識別は `payload_hashes`（ヘッダ抜き）で行い、合わなければ
    `UnsupportedRom` を投げる。`--force` でも表の位置は使わせない。

★CPU アドレス → ファイル位置は、**bank と window を必ず伴う**（指示書 §5）。
  ⚠ これは静的解析の約束。実行時の MMC1 mode は未確認なので、
    実行時コードにこの式を持ち込まないこと。
"""

from __future__ import annotations

import dataclasses
import pathlib

from dq2rom import ines
from dq2rom.rom_profile import Profile, ProfileError

PROFILE_DIR = pathlib.Path(__file__).resolve().parent / "profiles"
DEFAULT_GAME_ID = "dq3_fc_jp_rev0a"

#: iNES ヘッダの大きさ（ファイル位置 = ヘッダ + PRG 位置）
HEADER = ines.HEADER_SIZE
BANK = ines.PRG_BANK_SIZE
SWITCH_WINDOW = 0x8000
FIXED_WINDOW = 0xC000


class UnsupportedRom(ProfileError):
    """対応していない ROM（版違い・別ゲーム・壊れたダンプ）。

    ⚠ 呼び出し側は**握りつぶさない**。何が合わなかったかを人に見せる。
    """


@dataclasses.dataclass(frozen=True)
class Identified:
    """識別できた ROM。★profile と実体を一緒に持ち回る。"""

    rom: ines.Rom
    profile: Profile

    @property
    def game_id(self) -> str:
        return self.profile.game_id

    # --- 位置の変換（静的解析の約束）-----------------------------------

    def file_offset(self, bank: int, cpu_addr: int) -> int:
        """`(bank, CPU アドレス)` → ヘッダ込みのファイル位置。

        ★window を CPU アドレスから決めるが、**bank は呼び出し側が持つ**。
          `$C000-$FFFF` は固定バンクなので `bank` は無視される——
          ⚠ 黙って無視せず、固定窓に切替バンクを指定したら断る。
        """
        if not SWITCH_WINDOW <= cpu_addr <= 0xFFFF:
            raise ProfileError(f"ROM の窓の外です: ${cpu_addr:04X}")
        if cpu_addr >= FIXED_WINDOW:
            fixed = self.rom.fixed_bank
            if bank not in (fixed, None):
                raise ProfileError(
                    f"${cpu_addr:04X} は固定窓（bank {fixed}）です。"
                    f"bank {bank} を指定しても効きません")
            return HEADER + fixed * BANK + (cpu_addr - FIXED_WINDOW)
        if not 0 <= bank < self.rom.prg_banks:
            raise ProfileError(
                f"バンク番号が範囲外です: {bank}（0..{self.rom.prg_banks - 1}）")
        return HEADER + bank * BANK + (cpu_addr - SWITCH_WINDOW)

    def prg_offset(self, bank: int, cpu_addr: int) -> int:
        """`(bank, CPU アドレス)` → ヘッダ抜きの PRG 位置。"""
        return self.file_offset(bank, cpu_addr) - HEADER

    def window(self, bank: int) -> bytes:
        """そのバンクの 16KB。★MDEC デコーダへ「窓」として渡す用。"""
        if not 0 <= bank < self.rom.prg_banks:
            raise ProfileError(f"バンク番号が範囲外です: {bank}")
        return self.rom.prg[bank * BANK:(bank + 1) * BANK]

    # --- 表の位置 --------------------------------------------------------

    def table(self, name: str) -> dict:
        """profile の `tables[name]`。⚠ 無ければ断る（推測で読まない）。"""
        tables = self.profile.data.get("tables") or {}
        if name not in tables:
            raise ProfileError(f"profile に表がありません: {name}")
        return tables[name]

    def table_file(self, name: str, key: str = "file") -> int:
        """表のファイル位置（ヘッダ込み）を int で。"""
        return int(str(self.table(name)[key]), 16)

    def table_prg(self, name: str, key: str = "file") -> int:
        return self.table_file(name, key) - HEADER

    def confidence(self, name: str) -> str:
        return str(self.profile.data.get("confidence", {}).get(name, "unknown"))


def load_profile(game_id: str = DEFAULT_GAME_ID) -> Profile:
    return Profile.load(PROFILE_DIR / f"{game_id}.json")


def identify(rom: ines.Rom, game_id: str = DEFAULT_GAME_ID) -> Identified:
    """ROM を版まで識別する。合わなければ `UnsupportedRom`。

    順番:
      1. mapper / PRG / CHR の構成（★ここが違えばそもそも別物）
      2. payload hash（★版の識別）
      3. ⚠ 既知の他版なら、その旨を添えて断る
    """
    profile = load_profile(game_id)
    layout = profile.layout_mismatches(rom)
    if layout:
        raise UnsupportedRom(
            f"{profile.game_id} と構成が違います: " + " / ".join(layout))

    known = {k.lower(): v for k, v in
             (profile.data.get("known_other_revisions") or {}).items()}
    if rom.prg_crc32.lower() in known:
        raise UnsupportedRom(
            f"payload CRC32 {rom.prg_crc32.upper()} は既知の別版です: "
            f"{known[rom.prg_crc32.lower()]}")

    mismatches = profile.hash_mismatches(rom)
    if mismatches:
        raise UnsupportedRom(
            f"{profile.game_id} ではありません（未知の版）: "
            + " / ".join(mismatches))
    return Identified(rom=rom, profile=profile)


def load_and_identify(path: str | pathlib.Path,
                      game_id: str = DEFAULT_GAME_ID) -> Identified:
    return identify(ines.load(path), game_id)


def describe(ident: Identified) -> dict:
    """`inspect` が出す情報。★実測 hash と profile の判定を両方出す。"""
    info = ines.describe(ident.rom)
    info["profile"] = {
        "game_id": ident.game_id,
        "revision": ident.profile.data.get("revision"),
        "confidence": ident.profile.data.get("confidence"),
    }
    return info
