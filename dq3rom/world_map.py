"""DQ3 の世界地図（メイン 256×256 / アレフガルド 158×139）の RLE を展開する。

RX3-0004 / 2026-08-23。★DQ2 の世界地図処理は**流用しない**（指示書 §7 / §14）。

## 形（調査資料 §6 を実データで確かめた / `docs/design/dq3-findings.md`）

    ポインタ表: 行ごとの CPU ポインタ（little-endian）。bank 5 の切替窓
    file = cpu_pointer + 0xC010   （= 0x10 + 5*0x4000 + (cpu - 0x8000)）

    1 byte の読み方:
      $00-$E7  %TTTLLLLL  tile = 上位 3 bit（0..7）、run = 下位 5 bit + 1（1..32）
               ★$E0-$E7 は「tile 7 の run 1..8」で**同じ式**に収まる
                 （調査資料は「swamp 系 run」と別扱いで書くが、式は同じ）
      $E8-$FF  special tile **1 個**
               ⚠ 何のタイルかは**未確定**。ID は `8 + (byte - 0xE8)`（8..31）を
                 仮に振り、`special` の印を付ける。★名前は付けない

    ★2026-08-23 実測: この 2 段構えで main 255/255 行・アレフガルド 138/138 行が
      期待幅に展開した。⚠ 「$E0 以上を全部 1 tile」だと 236/255、
      「全部 run」だと 176/255 にしかならない。**両方が要る**。

## 終端（指示書 §7.3「曖昧なまま放置しない」）

    ★★ ポインタ表は **rows + 1 個**ある（2026-08-23 実測）★★
      最後の 1 個は「最終行の終端」を指す**番兵**で、これで**全行**が
      次ポインタで検証できる。最終行の特別扱いは要らない。

      実測の根拠:
        main: 256 個目の直後の 2 byte = $9A99 → file 0x015AA9
              = アレフガルド表の先頭。行 255（0x015AA1〜）は 8 byte で 256 tile、全部海
        ale : 139 個目 = $A3F3 → file 0x016403。行 0 と行 137 が両方「全部海」
              （上端・下端）。⚠ 0x016403 の先は地形が入り乱れた別のデータ

    ⚠⚠ 調査資料 §6.2 の「139 行」は**番兵を行と数えた**もの。
      **アレフガルドは 158 × 138**。「138/138 行が検証できた」という資料の数字は
      正しく、検証できたのが全部だった。→ `docs/design/dq3-findings.md` に記録

## 出力

    tile ID の 2 次元配列（0..31）。★描画の色は `logical_palette()` の仮色。
    ⚠ 実ゲームの tile graphics / palette の再現は後工程（Phase 7 以降）。
"""

from __future__ import annotations

import dataclasses

from .profile import Identified

SPECIAL_FROM = 0xE8
SPECIAL_BASE_TILE = 8
TILE_SHIFT = 5
RUN_MASK = 0x1F


class WorldMapError(ValueError):
    """展開できない／幅が合わない。⚠ 呼び出し側は黙って握りつぶさない。"""


@dataclasses.dataclass(frozen=True)
class Row:
    index: int
    tiles: tuple
    src_file: int                 # この行のデータの先頭（ヘッダ込み file）
    bytes_consumed: int
    specials: int                 # $E8+ の出現数


@dataclasses.dataclass(frozen=True)
class WorldMap:
    name: str
    width: int
    height: int
    rows: tuple                   # Row × height
    end_file: int                 # ★番兵が指す終端（次のデータの先頭）

    @property
    def tiles(self) -> list[list[int]]:
        return [list(r.tiles) for r in self.rows]

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "rows_verified_by_next_pointer": len(self.rows),   # ★番兵で全行
            "specials_total": sum(r.specials for r in self.rows),
            "data_file": f"0x{self.rows[0].src_file:06X}",
            "end_file": f"0x{self.end_file:06X}",
            "tiles": self.tiles,
            "_tile_note": "0..7 = 通常 / 8..31 = special（$E8+。意味は未確定）",
        }


def decode_row(data: bytes, expected_width: int) -> tuple:
    """1 行ぶん展開する。戻り値 `(tiles, consumed, specials)`。

    ★**ちょうど期待幅で終わる**ことを要求する（終端は次ポインタで決まる）。
    ⚠ 幅を超えたら断る（run が行をまたぐ形は想定しない）。
    """
    tiles: list[int] = []
    specials = 0
    consumed = 0
    for b in data:
        consumed += 1
        if b >= SPECIAL_FROM:
            tiles.append(SPECIAL_BASE_TILE + (b - SPECIAL_FROM))
            specials += 1
        else:
            tile = b >> TILE_SHIFT
            run = (b & RUN_MASK) + 1
            tiles.extend([tile] * run)
        if len(tiles) > expected_width:
            raise WorldMapError(
                f"行が期待幅 {expected_width} を超えました（{len(tiles)}）")
    if len(tiles) != expected_width:
        raise WorldMapError(
            f"行の幅が {len(tiles)}（期待 {expected_width}）")
    return tuple(tiles), consumed, specials


def _pointers(raw: bytes, table_file: int, rows: int) -> list[int]:
    out = []
    for i in range(rows):
        at = table_file + i * 2
        out.append(int.from_bytes(raw[at:at + 2], "little"))
    return out


def decode(ident: Identified, name: str) -> WorldMap:
    """profile の `tables[name]` を使って地図を展開する。

    ★ポインタは rows + 1 個読む（最後は番兵）。⚠ 番兵が ROM の外や
      単調性を破る位置を指していたら、それは表の数え方が違う印なので断る。
    """
    t = ident.table(name)
    table_file = int(str(t["pointer_table_file"]), 16)
    rows = int(t["rows"])
    width = int(t["expected_width"])
    bank = int(t["prg_bank"])
    raw = ident.rom.raw

    ptrs = _pointers(raw, table_file, rows + 1)       # ★番兵込み
    if any(ptrs[i] > ptrs[i + 1] for i in range(rows)):
        raise WorldMapError(f"{name}: ポインタが単調非減少ではありません")

    files = [ident.file_offset(bank, p) for p in ptrs]
    first_want = t.get("first_data_file")
    if first_want and int(str(first_want), 16) != files[0]:
        raise WorldMapError(
            f"{name}: 先頭データ 0x{files[0]:06X} が profile の {first_want} と違います")
    end_want = t.get("end_file")
    if end_want and int(str(end_want), 16) != files[rows]:
        raise WorldMapError(
            f"{name}: 番兵 0x{files[rows]:06X} が profile の {end_want} と違います")

    out = []
    for i in range(rows):
        tiles, consumed, sp = decode_row(raw[files[i]:files[i + 1]], width)
        out.append(Row(index=i, tiles=tiles, src_file=files[i],
                       bytes_consumed=consumed, specials=sp))
    return WorldMap(name=name, width=width, height=rows, rows=tuple(out),
                    end_file=files[rows])


# --- 仮色（★地形の識別用。実ゲームの色ではない）------------------------------

def logical_palette() -> dict[int, tuple[int, int, int]]:
    """tile ID → RGB（仮色）。⚠ 見た目を「それっぽく」しない（指示書 §9）。

    0..7 は資料に tile の意味が無いので、**識別できる 8 色**を機械的に割る。
    8..31（special）は灰系のグラデーションで「未確定」と分かるようにする。
    """
    base = [(0, 48, 160), (40, 160, 60), (200, 180, 90), (120, 80, 40),
            (60, 60, 60), (220, 220, 220), (160, 40, 160), (40, 120, 120)]
    pal = {i: c for i, c in enumerate(base)}
    for i in range(SPECIAL_BASE_TILE, 32):
        g = 90 + (i - SPECIAL_BASE_TILE) * 6
        pal[i] = (g, g, g)
    return pal
