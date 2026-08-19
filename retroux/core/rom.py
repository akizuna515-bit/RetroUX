"""ROM の同定。

`rom_hash` は **iNES ヘッダ16バイトを除いた PRG データ**のハッシュを使う（DEV-10）。

理由: 対象ROMはヘッダのパディング領域にゴミが入っており、動作させるには
ヘッダ修正版が必要だった。修正前後で PRG は1バイトも同一なのに、ファイル全体の
ハッシュは変わる。ファイル全体をキーにすると、ヘッダを直しただけで
「遭遇済みモンスター」の記録が失われる。
No-Intro / NES Directory といった ROM データベースもヘッダを除いた
ハッシュで同定しており、実際に本ROMの同定もこの方式で成功している。
"""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass
from pathlib import Path

INES_MAGIC = b"NES\x1a"
INES_HEADER_SIZE = 16


class InvalidRomError(ValueError):
    """iNES 形式として解釈できないファイル。"""


@dataclass(frozen=True)
class RomInfo:
    """ROM の同定結果。"""

    path: Path
    prg_sha256: str
    prg_crc32: str
    prg_size: int
    chr_size: int
    mapper: int
    has_dirty_header: bool
    """iNES ヘッダのパディング領域(byte 8-15)にゴミがあるか。

    ゴミがある場合、byte 7 のマッパー上位ニブルも信用できない。
    対象ROMはこれに該当し、そのままではマッパー242と誤認されて起動しない。
    """


def _read(path: Path | str) -> bytes:
    data = Path(path).read_bytes()
    if len(data) < INES_HEADER_SIZE:
        raise InvalidRomError(f"ファイルが小さすぎます: {path}")
    if data[:4] != INES_MAGIC:
        raise InvalidRomError(f"iNES ヘッダがありません: {path}")
    return data


def identify(path: Path | str) -> RomInfo:
    """ROM を読み、ヘッダを除いた PRG データから同定情報を作る。"""
    data = _read(path)
    body = data[INES_HEADER_SIZE:]

    padding = data[8:16]
    dirty = any(b != 0 for b in padding)

    mapper_low = (data[6] & 0xF0) >> 4
    # ヘッダが汚れている場合、byte 7 の上位ニブルはゴミなので採用しない。
    mapper = mapper_low if dirty else ((data[7] & 0xF0) | mapper_low)

    return RomInfo(
        path=Path(path),
        prg_sha256=hashlib.sha256(body).hexdigest().upper(),
        prg_crc32=f"{zlib.crc32(body) & 0xFFFFFFFF:08X}",
        prg_size=data[4] * 16 * 1024,
        chr_size=data[5] * 8 * 1024,
        mapper=mapper,
        has_dirty_header=dirty,
    )


class WrongRomError(InvalidRomError):
    """★★ **求めている ROM ではない**（2026-08-18 / RX-0057）★★

    ⚠⚠ これを見逃すと「動いているように見えて、全部が嘘」になる。

      `memory_map.yaml` の RAM 番地（HP・MP・敵ID・座標）は
      **DQ2 日本版専用**。別の ROM では:

        ・パーティ状態に**でたらめな数値**が出る（★エラーは出ない）
        ・戦闘していないのに戦闘と誤認する
        ・⚠ AUTO と倍速が**見当違いのタイミングでキーを押す**

    ★`iNES ヘッダがあるか`しか見ていなかったので、
      ⚠ **DQ3 を置いても普通に起動していた**（2026-08-18 に実測）。
    """


def check_expected(info: "RomInfo", expected: dict | None) -> None:
    """★期待する ROM かを確かめる。⚠ 違えば `WrongRomError`。

    `expected` は `memory_map.yaml` の `rom:` 節。
    ★`prg_sha256` が書いてあるときだけ見る（⚠ 無ければ何もしない）。

    ⚠⚠ **黙って通さない。** ここを通してしまうと、
      あとから出てくる数値が全部おかしいのに、原因が分からなくなる。
    """
    want = (expected or {}).get("prg_sha256")
    if not want:
        return                      # ★書いていないなら確かめようがない
    got = info.prg_sha256
    if got.upper() == str(want).upper():
        return
    title = (expected or {}).get("title") or "この ROM"
    raise WrongRomError(
        "⚠ 求めている ROM ではありません（" + str(title) + "）。" + chr(10)
        + "  置いてあるもの: " + info.path.name + chr(10)
        + "  PRG SHA-256   : " + got[:16] + "…" + chr(10)
        + "  求めているもの: " + str(want)[:16] + "…" + chr(10)
        + "★RAM の番地が違うので、そのまま動かすと"
        "**数値も自動操作も見当違い**になります。")


def rom_hash(path: Path | str) -> str:
    """SQLite の `rom_hash` として使う値。"""
    return identify(path).prg_sha256
