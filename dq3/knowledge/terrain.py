"""地図の地形を ROM から起こす（RX3-0023 / 2026-08-29）。

★★ ここは「地形の**素**」を返すだけです ★★

⚠⚠ **見た所だけ描く**の判断はここではしません。
  ★ここは「その地図はどんな形か」を答えるだけで、
  ⚠ 何を出すかは `SeenMap`（見た升の記録）が決めます。

## ★どの地図を出すか

```text
kind 0  世界地図        world_main      256 x 256
kind 2  アレフガルド    world_alefgard  158 x 138
kind 1  ローカル        エリアマップ [map_no]
```

⚠ `map_no`（`$8B`）が**エリアマップの索引そのもの**であることは実測で確定
（2026-08-29: ゲームが復号した地図 `mapbuf_9.txt` と ROM の索引 9 が
**676 升すべて一致**。⚠ 寸法の同じ索引 228 は 442 升が食い違った）。

## ⚠ ROM が無い環境

★`work/rom/DQ3_J.nes` は Git の外です（⚠ 利用者が置くもの）。
無ければ **`None` を返します**。⚠ 落ちません。地図は真っ黒のままになります。

## ⚠ 重くしない

★展開は 1 回だけして覚えておきます（⚠ 世界地図は 256x256 = 65,536 升）。
"""

from __future__ import annotations

import pathlib
import threading

from dq3 import paths as _P3
from dq3.knowledge import seen_map as _seen

#: ★利用者の ROM（⚠ Git の外。無ければ地図を出さない）
#
#   ⚠ 解決は `dq3/paths.py::rom()` の 1 本（RX3-0467）。★任意の場所を指定できます。
DEFAULT_ROM = _P3.lazy_rom()

#: ★居場所の種別（⚠ `seen_map` と同じ値）
KIND_WORLD = 0
KIND_LOCAL = 1
KIND_ALEFGARD = 2

#: ⚠ 種別 → ROM の表の名前（★ローカルはエリアマップなので別）
WORLD_TABLE = {KIND_WORLD: "world_main", KIND_ALEFGARD: "world_alefgard"}


class Terrain:
    """1 つの地図の地形。⚠ 1 升 1 バイト。"""

    __slots__ = ("width", "height", "rows", "kind", "map_id", "tileset")

    def __init__(self, width, height, rows, kind, map_id=None,
                 tileset=None) -> None:
        self.width = width
        self.height = height
        #: ★行ごとの升（⚠ `rows[y][x]`）
        self.rows = rows
        self.kind = kind
        self.map_id = map_id
        #: ★どの絵の組か（⚠ 同じ番号でも tileset が違えば別の地形）
        #:   ⚠ 世界地図には無い（★`None`）
        self.tileset = tileset

    def at(self, x: int, y: int):
        """★その升の地形。⚠ 地図の外なら `None`。"""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        if y >= len(self.rows) or x >= len(self.rows[y]):
            # ⚠ 展開が寸法に足りていない地図がある（★途中で終わる）
            return None
        return self.rows[y][x]


class TerrainSource:
    """ROM から地図を起こす。⚠ 1 回起こしたら覚えておく。"""

    def __init__(self, rom_path=None) -> None:
        self.rom_path = pathlib.Path(rom_path) if rom_path else DEFAULT_ROM
        self._cache: dict = {}
        self._ident = None
        self._tried = False
        self._lock = threading.Lock()
        #: ★読めなかった理由（⚠ 黙って空を返さない）
        self.last_error: str | None = None

    # --- ★ROM を開く ----------------------------------------------------

    def _identify(self):
        if self._tried:
            return self._ident
        self._tried = True
        try:
            from dq3rom import profile as dq3

            self._ident = dq3.load_and_identify(self.rom_path)
        except Exception as exc:                       # noqa: BLE001
            # ⚠ ROM が無い環境でも落ちない（★地図が出ないだけ）
            self.last_error = str(exc)
            self._ident = None
        return self._ident

    @property
    def available(self) -> bool:
        """★地図を出せるか（⚠ ROM が無ければ False）。"""
        return self._identify() is not None

    # --- ★地図を起こす --------------------------------------------------

    def get(self, kind, map_id=None):
        """その地図の地形。⚠ 出せなければ `None`。"""
        key = (kind, map_id if _seen.is_local(kind) else None)
        if key in self._cache:
            return self._cache[key]
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            got = self._build(kind, map_id)
            self._cache[key] = got
            return got

    def _build(self, kind, map_id):
        ident = self._identify()
        if ident is None:
            return None
        try:
            if kind in WORLD_TABLE:
                return self._world(ident, kind)
            if _seen.is_local(kind):
                return self._area(ident, map_id)
        except Exception as exc:                       # noqa: BLE001
            # ⚠ 1 つ起こせなくても、★他の地図は出せる
            self.last_error = "%s (kind=%s map=%s)" % (exc, kind, map_id)
        return None

    @staticmethod
    def _world(ident, kind):
        from dq3rom import world_map as wm

        got = wm.decode(ident, WORLD_TABLE[kind])
        rows = [row.tiles for row in got.rows]
        return Terrain(got.width, len(rows), rows, kind)

    def _area(self, ident, map_id):
        if map_id is None:
            # ⚠ ローカルなのに番号が分からない（★推測しない）
            return None
        from dq3rom import area_maps as am

        if "areas" not in self._cache:
            self._cache["areas"] = {
                m.entry.map_id: m for m in am.decode_all(ident)}
        got = self._cache["areas"].get(int(map_id))
        if got is None or got.decoded is None:
            return None                    # ⚠ 使われていない索引
        d = got.decoded
        return Terrain(d.width, d.height, d.tiles, KIND_LOCAL,
                       int(map_id), got.entry.tileset)
