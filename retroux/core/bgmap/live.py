"""遊んでいる最中に、見たマスの絵を用意する（2026-08-02 / 課題 #65）。

## 流れ

    bridge.lua  ──(1マス9文字)──▶  ここ  ──▶  PNG と metatile_key
                                      │
                                      └─ 絵は **ROM から**（採取が要らない）

★★ **ここが「歩いた先がそのまま地図になる」の要** ★★

  ⚠ これまでは、採ったセーブステートの周りしか絵がありませんでした。
  ★ROM からマップごとの CHR とパレットが取れるので、
    **見たマスの4枚とパレット組さえ届けば**、その場で絵を作れます。

## ⚠⚠ 守っていること

- **見ていないマスは作らない**（指示書 §2.2）。
  ここへ来るのは Lua が実際に読んだマスだけです。
- **黒観測は保存しない**（指示書 §11.2）。4枚とも地の色なら見送ります。
- **分からないものは飛ばす**。`_` が混ざったマス、まだ確かめていない
  マップは `None` を返します（推測で描かない）。
- **黙って捨てない**。見送った数は `Tally` に残ります。
"""

from __future__ import annotations

import dataclasses

from .catalog import AssetStore
from .rom_assets import RomTileSource

#: 1マスぶんの文字数（タイルID 2文字 × 4 ＋ パレット組 1文字）
CELL_CHARS = 9
#: ★読めなかったマス。⚠ 0 と混ぜない
UNKNOWN_CELL = "_" * CELL_CHARS


@dataclasses.dataclass
class Tally:
    """何を作り、何を見送ったか。★黙って捨てない。"""

    #: 新しく PNG を作った
    made: int = 0
    #: すでにあったので作り直さなかった
    reused: int = 0
    #: 4枚とも地の色だった（指示書 §11.2）
    blank: int = 0
    #: `_` が混ざっていて読めなかった
    unreadable: int = 0
    #: そのマップの絵をまだ用意できない（推測で描かない）
    no_tileset: int = 0

    def merge(self, other: "Tally") -> None:
        self.made += other.made
        self.reused += other.reused
        self.blank += other.blank
        self.unreadable += other.unreadable
        self.no_tileset += other.no_tileset

    def summary(self) -> str:
        return (f"作った {self.made} / 使い回し {self.reused} / "
                f"⚠ 黒 {self.blank} / 読めず {self.unreadable} / "
                f"種類が未確認 {self.no_tileset}")


def parse_cells(packed: str | None, radius: int) -> dict:
    """1マス9文字の並びを `{(dx, dy): (タイル4枚, 組)}` にする。

    ⚠ 読めないマス（`_` が混ざる）は**入れません**。
      ★「0 と不明を混ぜない」。入っていないこと自体が「見ていない」の意。
    """
    if not packed:
        return {}
    side = radius * 2 + 1
    if len(packed) != side * side * CELL_CHARS:
        return {}                      # ⚠ 数が合わない＝形式が違う。使わない
    out: dict = {}
    i = 0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            chunk = packed[i:i + CELL_CHARS]
            i += CELL_CHARS
            if "_" in chunk:
                continue
            try:
                tiles = tuple(int(chunk[n * 2:n * 2 + 2], 16) for n in range(4))
                group = int(chunk[8], 16)
            except ValueError:
                continue               # ⚠ 16進でないものは捨てる（落とさない）
            if group > 3:
                continue               # ⚠ パレット組は 0-3。それ以外は変
            out[(dx, dy)] = (tiles, group)
    return out


class LiveMetatiles:
    """見たマスの絵を、ROM から作って貯める。

    ★同じ組み合わせは覚えておくので、2回目からは何もしません。
    """

    def __init__(self, source: RomTileSource, store: AssetStore,
                 nes_palette) -> None:
        self.source = source
        self.store = store
        self.nes_palette = nes_palette
        # ★(map_id, タイル4枚, 組) -> metatile_key、または None（描けない）
        self._known: dict[tuple, str | None] = {}
        self.tally = Tally()

    def key_for(self, map_id: int, tiles, group: int) -> str | None:
        """そのマスの `metatile_key`。⚠ 描けないものは None。

        ★必要なら PNG も作ります（初回だけ）。
        """
        cache_key = (map_id, tuple(tiles), group)
        if cache_key in self._known:
            key = self._known[cache_key]
            # ★覚えていても数は数える。⚠ 2回目から見えなくなると、
            #   「描けていない」ことに気づけない
            if key is None:
                self.tally.no_tileset += 1
            else:
                self.tally.reused += 1
            return key

        maptiles = self.source.for_map(map_id)
        if maptiles is None:
            # ⚠ まだ確かめていないマップ。★推測で描かない
            self._known[cache_key] = None
            self.tally.no_tileset += 1
            return None

        mt = maptiles.metatile(tiles, group)
        if mt.is_blank:
            # ⚠⚠ 黒観測は地形にしない（指示書 §11.2）。
            #   ★覚えない。次に同じ場所を見たとき、明るければ拾えるように。
            self.tally.blank += 1
            return None

        result = self.store.put_metatile(
            mt, self.nes_palette, chr_data=maptiles.chr_data)
        if result.metatiles:
            self.tally.made += 1
        else:
            self.tally.reused += 1
        self._known[cache_key] = mt.key
        return mt.key

    def keys_for_view(self, map_id: int, packed: str | None,
                      radius: int) -> dict:
        """見えている範囲ぶんを一度に。`{(dx, dy): metatile_key}` を返す。

        ⚠ 描けなかったマスは**入りません**（数は `tally` に残ります）。
        """
        cells = parse_cells(packed, radius)
        # ★読めなかったマスの数も残す（黙って捨てない）。
        #   ⚠ 形式が違って 0 件になったときも、ここで数に出ます。
        side = radius * 2 + 1
        if packed:
            self.tally.unreadable += side * side - len(cells)
        out = {}
        for offset, (tiles, group) in cells.items():
            key = self.key_for(map_id, tiles, group)
            if key is not None:
                out[offset] = key
        return out
