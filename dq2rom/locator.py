"""日本版ROMの中で表がどこにあるかを**探して**確かめる。

★★ **アドレスをソースに書き込まない** ★★（指示書 §19-4）

  北米版の逆アセンブル（`work/dq2-disasm/src/us/`）は読めるが、
  **日本版のアドレスは1つも使えない**。日本版の逆アセンブルは
  `src/jp/main.asm` が `.sprintf("JP UNSUPPORTED")` の2行だけで、中身が無い。

  そこでこのプロジェクトで実績のある手順を使う（`research/probes/archived/extract_drops.py` 等）:

      北米版から「データの**形**」（値の並び・間隔）を取り出し、
      その形を日本版ROMのバイト列から検索して位置を割り出す。

  ★見つかった位置は**候補**として扱い、`verify_*` で
    **探索に使っていない列**を見て裏を取る（playbook「候補は候補」）。
    過去に、確率の署名だけで敵をひも付けて1つのIDに2つの名前を
    割り当てた事故がある。

このモジュールが持っているのは**署名（探し方）だけ**で、
見つかった位置は `profiles/*.json` に書き戻す。
"""

from __future__ import annotations

import dataclasses

from .ines import Rom
from .provenance import Confidence, Evidence, Finding

# --- モンスターの絵の索引表 -------------------------------------------
#
# 北米版 `bank4.asm:2678` に「count? + pointer to enemy graphics? +
# pointer to enemy palette」というコメント付きの表がある。1体5バイト。
# 引き方は `bank4.asm:1134-1151`（monster_id を *4 して自身を足す = *5）。
#
# ★署名に使うのは **count バイトだけ**。ポインタは日米でずれるため使えない。
#   逆に count が日米で同じであること自体が「同じ絵が入っている」証拠になる。
MONSTER_GFX_ENTRY_SIZE = 5
MONSTER_GFX_ENTRIES = 0x54          # ID $00..$53
MONSTER_GFX_MAX_ID = 0x52           # コードは `cmp #$53 / bcc` で $53 以上を弾く

_MONSTER_GFX_COUNT_SIGNATURE = (
    0x01, 0x04, 0x0B, 0x0D, 0x06, 0x10, 0x06, 0x0F, 0x06, 0x0D, 0x19, 0x10,
    0x10, 0x0D,
)

# --- マップのヘッダ表 --------------------------------------------------
#
# 北米版 `bank2.asm:58`:
#   「map header info (exterior border tile ID, width, height,
#     pointer low byte, pointer high byte, ?, ?, palette)」
# 1マップ8バイト、109マップ。
#
# ★署名に使うのは (境界タイル, 幅, 高さ) の3バイトだけ。
#   ポインタと 6-7 バイト目は日米で違う（6-7 は北米版でも `?` のまま）。
MAP_HEADER_ENTRY_SIZE = 8
MAP_HEADER_ENTRIES = 109

_MAP_HEADER_SIGNATURE = (
    (0x01, 0x17, 0x17), (0x04, 0xFF, 0xFF), (0x20, 0x09, 0x09),
    (0x01, 0x17, 0x17), (0x05, 0x05, 0x09), (0x01, 0x17, 0x17),
    (0x03, 0x19, 0x19), (0x06, 0x17, 0x17), (0x04, 0x07, 0x07),
    (0x08, 0x13, 0x13), (0x05, 0x05, 0x06), (0x01, 0x19, 0x19),
    (0x01, 0x1D, 0x13), (0x20, 0x07, 0x07), (0x20, 0x07, 0x07),
    (0x01, 0x17, 0x17), (0x01, 0x17, 0x17), (0x03, 0x13, 0x1F),
    (0x02, 0x05, 0x05), (0x06, 0x09, 0x09), (0x05, 0x17, 0x18),
    (0x03, 0x19, 0x19), (0x08, 0x19, 0x19), (0x21, 0x0F, 0x0D),
)

_DISASM = "work/dq2-disasm（Nathan-R-Og/dq2、北米版のみ）"


class LocateError(LookupError):
    """表が見つからない、または候補が複数ある。"""


@dataclasses.dataclass(frozen=True)
class Located:
    """見つかった表の位置。"""

    prg_offset: int
    bank: int
    cpu_address: int
    finding: Finding

    def to_json(self) -> dict:
        return {
            "prg_offset": f"0x{self.prg_offset:05X}",
            "bank": self.bank,
            "cpu_address": f"0x{self.cpu_address:04X}",
            **self.finding.to_json(),
        }


def _search_strided(prg: bytes, stride: int,
                    pattern: list[tuple[int, ...]]) -> list[int]:
    """`stride` バイト間隔で、各エントリの先頭数バイトが一致する位置を全部返す。

    ★**全部**返すのが大事。1個目で打ち切ると「候補が1つだった」のか
      「他にもあったのに見ていない」のか区別できなくなる。
    """
    span = stride * len(pattern)
    hits: list[int] = []
    first = pattern[0]
    for base in range(len(prg) - span + 1):
        # 先頭バイトで足切りしてから全体を見る（総当たりは遅いため）
        if prg[base] != first[0]:
            continue
        ok = True
        for i, expect in enumerate(pattern):
            off = base + i * stride
            for j, value in enumerate(expect):
                if prg[off + j] != value:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            hits.append(base)
    return hits


def _one(hits: list[int], what: str) -> int:
    if not hits:
        raise LocateError(
            f"{what} が見つかりません。"
            "この ROM は解析対象と違う版かもしれません（--force で続けても位置は出ません）")
    if len(hits) > 1:
        # ★複数当たったら選ばない。**選ぶと必ず間違える**。
        raise LocateError(
            f"{what} の候補が {len(hits)} 個あります: "
            + ", ".join(f"0x{h:05X}" for h in hits)
            + "。署名を長くして絞り込んでください")
    return hits[0]


def locate_monster_graphics_table(rom: Rom) -> Located:
    """モンスターの絵の索引表を探す。"""
    hits = _search_strided(
        rom.prg, MONSTER_GFX_ENTRY_SIZE,
        [(c,) for c in _MONSTER_GFX_COUNT_SIGNATURE])
    offset = _one(hits, "モンスターの絵の索引表")
    bank, cpu = rom.cpu_address(offset)
    return Located(
        prg_offset=offset, bank=bank, cpu_address=cpu,
        finding=Finding(
            name="monster_graphics_pointer_table",
            confidence=Confidence.PROBABLE,
            evidence=(
                Evidence(
                    type="disassembly_symbol",
                    source=_DISASM,
                    note="bank4.asm:2678「count? + pointer to enemy graphics? "
                         "+ pointer to enemy palette」。1体5バイト、"
                         "引き方は bank4.asm:1134-1151（monster_id * 5）",
                ),
                Evidence(
                    type="byte_signature",
                    rom_offset=offset, bank=bank, cpu_address=cpu,
                    note=f"5バイト間隔の count 列 "
                         f"{len(_MONSTER_GFX_COUNT_SIGNATURE)} 個が一致。"
                         "日本版ROM内で候補は1か所のみ",
                ),
            ),
        ),
    )


def locate_map_header_table(rom: Rom) -> Located:
    """マップのヘッダ表を探す。"""
    hits = _search_strided(rom.prg, MAP_HEADER_ENTRY_SIZE,
                           list(_MAP_HEADER_SIGNATURE))
    offset = _one(hits, "マップのヘッダ表")
    bank, cpu = rom.cpu_address(offset)
    return Located(
        prg_offset=offset, bank=bank, cpu_address=cpu,
        finding=Finding(
            name="map_header_table",
            confidence=Confidence.PROBABLE,
            evidence=(
                Evidence(
                    type="disassembly_symbol",
                    source=_DISASM,
                    note="bank2.asm:58「map header info (exterior border tile ID, "
                         "width, height, pointer low byte, pointer high byte, "
                         "?, ?, palette)」。1マップ8バイト",
                ),
                Evidence(
                    type="byte_signature",
                    rom_offset=offset, bank=bank, cpu_address=cpu,
                    note=f"8バイト間隔の (境界タイル, 幅, 高さ) "
                         f"{len(_MAP_HEADER_SIGNATURE)} 組が一致。"
                         "日本版ROM内で候補は1か所のみ",
                ),
            ),
        ),
    )


# --- 表を読む ---------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class MonsterGraphicsEntry:
    monster_id: int
    count: int
    graphics_addr: int          # bank 1 の CPU アドレス
    palette_addr: int           # bank 4 の CPU アドレス
    in_range: bool              # ゲームがこの ID を処理するか（$00..$52）

    def to_json(self) -> dict:
        return {
            "monster_id": self.monster_id,
            "count": self.count,
            "graphics_addr": f"0x{self.graphics_addr:04X}",
            "palette_addr": f"0x{self.palette_addr:04X}",
            "in_range": self.in_range,
        }


def read_monster_graphics_table(rom: Rom, base: int) -> list[MonsterGraphicsEntry]:
    """索引表を全部読む。

    ★範囲外のポインタは**捨てずに `in_range=False` で残す**。
      「84エントリのうち $53 だけがおかしい」という事実自体が、
      コードの `cmp #$53 / bcc`（$53 以上は処理しない）の裏付けになる。
    """
    end = base + MONSTER_GFX_ENTRIES * MONSTER_GFX_ENTRY_SIZE
    if end > len(rom.prg):
        raise LocateError(f"索引表が PRG の外へはみ出します: 0x{end:X}")

    out: list[MonsterGraphicsEntry] = []
    for i in range(MONSTER_GFX_ENTRIES):
        o = base + i * MONSTER_GFX_ENTRY_SIZE
        gfx = rom.prg[o + 1] | (rom.prg[o + 2] << 8)
        pal = rom.prg[o + 3] | (rom.prg[o + 4] << 8)
        out.append(MonsterGraphicsEntry(
            monster_id=i,
            count=rom.prg[o],
            graphics_addr=gfx,
            palette_addr=pal,
            in_range=i <= MONSTER_GFX_MAX_ID,
        ))
    return out


def verify_monster_graphics_table(entries: list[MonsterGraphicsEntry]) -> list[str]:
    """★探索に使っていない列（ポインタ）で裏を取る。

    count 列だけで場所を決めたので、**ポインタ列が筋の通った値か**を
    別途確かめる。問題があれば理由の一覧を返す（空なら合格）。
    """
    problems: list[str] = []
    live = [e for e in entries if e.in_range]

    bad = [e for e in live
           if not (0x8000 <= e.graphics_addr <= 0xBFFF)
           or not (0x8000 <= e.palette_addr <= 0xBFFF)]
    if bad:
        problems.append(
            "切り替えバンクの窓 $8000-$BFFF の外を指すエントリがあります: "
            + ", ".join(f"ID {e.monster_id:02X}" for e in bad[:5]))

    # ★パレットは1体1個のはず（色違いは絵を共有してもパレットは別）
    pal = [e.palette_addr for e in live]
    if len(set(pal)) != len(pal):
        problems.append("パレットのポインタが重複しています")

    # ★パレットのポインタは表の中で単調増加のはず（順に並べたデータ）
    if any(b <= a for a, b in zip(pal, pal[1:])):
        problems.append("パレットのポインタが単調増加ではありません")

    return problems


@dataclasses.dataclass(frozen=True)
class MapHeader:
    map_id: int
    border_tile: int
    width: int
    height: int
    data_addr: int
    unknown_5: int              # ⚠ 北米版の逆アセンブルでも `?` のまま
    unknown_6: int
    palette: int

    def to_json(self) -> dict:
        return {
            "map_id": self.map_id,
            "border_tile": self.border_tile,
            "width": self.width,
            "height": self.height,
            "data_addr": f"0x{self.data_addr:04X}",
            "unknown_5": self.unknown_5,
            "unknown_6": self.unknown_6,
            "palette": self.palette,
        }


def read_map_header_table(rom: Rom, base: int) -> list[MapHeader]:
    end = base + MAP_HEADER_ENTRIES * MAP_HEADER_ENTRY_SIZE
    if end > len(rom.prg):
        raise LocateError(f"マップのヘッダ表が PRG の外へはみ出します: 0x{end:X}")

    out: list[MapHeader] = []
    for i in range(MAP_HEADER_ENTRIES):
        o = base + i * MAP_HEADER_ENTRY_SIZE
        out.append(MapHeader(
            map_id=i,
            border_tile=rom.prg[o],
            width=rom.prg[o + 1],
            height=rom.prg[o + 2],
            data_addr=rom.prg[o + 3] | (rom.prg[o + 4] << 8),
            unknown_5=rom.prg[o + 5],
            unknown_6=rom.prg[o + 6],
            palette=rom.prg[o + 7],
        ))
    return out
