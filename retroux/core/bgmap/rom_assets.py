"""**ROM だけで**そのマップの絵を用意する（2026-08-02 / 課題 #65）。

## なぜ要るのか

⚠⚠ これまで地図の絵は「採ったセーブステート」からしか作れませんでした。
  つまり **採った場所の周りしか描けない**という縛りがありました。

★ROM 解析で、マップごとの CHR とパレットが取れるようになりました
  （`rom_tiles.py`）。ここはそれを **1マップぶんの道具**にまとめ、
  「タイルID4枚とパレット組」から 16×16 の絵を作れるようにします。

## ★★ 鍵は採ったものと同じになる ★★

鍵は `<CHRハッシュ>:<タイルID>:<パレット署名>` です。
ROM から組んだ CHR とパレットは実機と**同じ中身**なので、
出てくる鍵も同じになります。

  ⚠ つまり、これまでに採って作った PNG も DB の記録も
    **そのまま使えます**。作り直しは要りません。
  ★これはテストで固定してあります（`test_rom_assets.py`）。

## ⚠⚠ これは「先読み」ではない

指示書 §2.2「未表示領域をROM解析だけで先読みして、未探索地形を
自動開示しない」。

★ここが用意するのは **絵（見た目）だけ**です。
  **どのマスに何があるか**は、これまでどおり見た画面からしか
  受け取りません。絵があっても、見ていないマスは描きません。
"""

from __future__ import annotations

import dataclasses
import pathlib

from .characters import Metatile, metatile_of
from .rom_tiles import chr_for_map, load_prg, palette_for_map, read_table

#: ★背景のパターンテーブルは前半（`$0000`）。
#: ⚠ ROM から組んだ CHR は地形を `$0900` に置くので、ずらしません。
#:   実測4件とも前半で一致しました（2026-08-02）。
ROM_PATTERN_HALF = 0


@dataclasses.dataclass(frozen=True)
class MapTiles:
    """1マップぶんの CHR とパレット。

    ★これがあれば、タイルID4枚とパレット組から絵が作れます。
    """

    map_id: int
    #: CHR-RAM 8KB ぶん
    chr_data: bytes
    #: 背景パレット 16 バイト
    palette: bytes
    #: ★背景パターンテーブルの半分（0=前半$0000 / 1=後半$1000）。
    #   ⚠⚠ 2026-08-19 / RX-0072: **塔（種別3）は後半($1000)**（灯台で実測）。
    #     街・洞窟は前半（従来どおり 0）。`for_map` が種別で決める。
    half: int = 0

    def metatile(self, tiles, group: int,
                 x: int = -1, y: int = -1) -> Metatile:
        """タイルID4枚（左上・右上・左下・右下）から 16×16 を作る。"""
        return metatile_of(self.chr_data, self.palette, tiles, group,
                           map_id=self.map_id, x=x, y=y,
                           half=self.half)


class RomTileSource:
    """ROM から、マップごとの絵の材料を出す。

    ⚠ **分からないマップは `None`** を返します（推測で描かない）。
    ★世界地図・街/城（`map_id` < `$2B`）・ダンジョン/塔は全部 ROM から取れる（2026-08-21 訂正 / RX-0010）。
      残るのは表の外（`$6D` 以降）だけ。
      いまのところ `map_id` `$2B`-`$6C`（ダンジョン）と
      街（境界タイルID `$01`）が分かっています。
    """

    def __init__(self, rom_path) -> None:
        self.rom_path = pathlib.Path(rom_path)
        self._prg: bytes | None = None
        self._entries = None
        # ★1マップぶん 8KB あるので、作ったら覚えておく。
        #   ⚠ `functools.lru_cache` はメソッドに付けると self を掴んだままに
        #     なるので使わない（素直な辞書にする）。
        self._cache: dict[int, MapTiles | None] = {}

    @property
    def prg(self) -> bytes:
        if self._prg is None:
            self._prg = load_prg(self.rom_path)
            self._entries = read_table(self._prg)
        return self._prg

    @property
    def entries(self):
        if self._entries is None:
            self.prg          # ★読み込みを起こす
        return self._entries

    def for_map(self, map_id: int) -> MapTiles | None:
        """そのマップの CHR とパレット。⚠ 分からなければ None。"""
        if map_id in self._cache:
            return self._cache[map_id]
        chr_data = chr_for_map(self.prg, self.entries, map_id)
        palette = palette_for_map(self.prg, map_id)
        # ★背景の半分は種別で決まる（RX-0072）。塔(種別3)は後半($1000)。
        from .dungeon_map import map_kind

        half = 1 if map_kind(map_id) == 3 else 0
        made = (None if chr_data is None or palette is None
                else MapTiles(map_id=map_id, chr_data=chr_data,
                              palette=palette, half=half))
        self._cache[map_id] = made
        return made

    def why_not(self, map_id: int) -> str | None:
        """描けない理由を**言葉で**返す。★黙って何もしないのを避ける。"""
        if chr_for_map(self.prg, self.entries, map_id) is None:
            return (f"map ${map_id:02X} は、どのタイルセットを使うか"
                    "まだ確かめていません")
        if palette_for_map(self.prg, map_id) is None:
            return f"map ${map_id:02X} のパレットが読めません"
        return None
