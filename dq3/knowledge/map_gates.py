"""map の中で「入った升から、その出口まで歩けるか / 鍵が要るか」（RX3-0067 / 2026-09-17）。

## ★何をするもので、何をしないか

```text
★する    (map, 入った升, 出口の升) → 要る鍵の段位（-1 = 鍵なしで歩ける / 0 / 1 / 3）か None（★歩いて着けない）
⚠ しない  map から map への道順（★`map_graph.MapGraph.route` が、この表を持って決める）
⚠ しない  扉を開ける操作（★`nav_v0` の担当）
```

## ⚠ 材料は `dq3.testing.passability.RomMap.bfs(keys=)`（RX3-0078）です

★段位は `dq3rom.door_keys`（とうぞく 0 / まほう 1 / さいご 3）。★弱い鍵から順に試し、最初に通った段位を書きます。
⚠ 出口の升そのものは SPECIAL なので、途中の升としては通りません（★ほかの出口を踏むと map が変わる）。

## ⚠⚠ 「着けない」は珍しくありません（★2026-09-17 実測: 198 map のうち 42 で出口が 2 群以上に分かれる）

★レーベ（map 9）の (6,3) は、町の中から歩いて着けない（⚠ 建物の中を通って出る升）。
⚠ これは欠陥ではなく、**入った升によって行ける出口が違う**という事実です。→ ★None のまま持ちます。
"""
from __future__ import annotations

import dataclasses

from dq3rom import door_keys as _dk

#: ★試す鍵（★弱い順 / 道具 ID）。⚠ 名前は書かない
KEY_ORDER = tuple(sorted(_dk.KEY_ITEMS, key=_dk.KEY_ITEMS.get))
#: ★鍵なしで歩ける
FREE = -1


@dataclasses.dataclass(frozen=True)
class Gate:
    map_id: int
    entry: tuple[int, int]
    exit: tuple[int, int]
    rank: int | None          #: ★-1 / 0 / 1 / 3 / ⚠ None = 着けない


def rank_between(rom_map, entry, exit_) -> int | None:
    """★`entry` から `exit_` まで歩くのに要る段位。⚠ どの鍵でも着けなければ None。"""
    entry, exit_ = tuple(entry), tuple(exit_)
    if entry == exit_:
        return FREE
    if rom_map.bfs(entry, exit_) is not None:
        return FREE
    for item in KEY_ORDER:
        if rom_map.bfs(entry, exit_, keys=[item]) is not None:
            return _dk.KEY_ITEMS[item]
    return None


class Gates:
    """★map ごとの (入った升, 出口の升) → 段位。⚠ 載っていない組は「分からない」（★`None` とは別）。"""

    def __init__(self) -> None:
        self._rank: dict[tuple[int, tuple[int, int], tuple[int, int]], int | None] = {}
        self.maps: set[int] = set()
        self.skipped: dict[int, str] = {}          #: ⚠ 地図を起こせなかった map と理由（★黙って落とさない）

    def put(self, gate: Gate) -> None:
        self._rank[(gate.map_id, gate.entry, gate.exit)] = gate.rank
        self.maps.add(gate.map_id)

    def rank(self, map_id: int, entry, exit_):
        """★段位。⚠ 表に無ければ `"unknown"`（★呼ぶ側は今までどおり通す）。"""
        return self._rank.get((int(map_id), tuple(entry), tuple(exit_)), "unknown")

    def passable(self, map_id: int, entry, exit_, party_rank: int) -> bool:
        """★その段位の鍵を持った一行が、`entry` から `exit_` へ歩けるか。⚠ 分からなければ True（今までどおり）。"""
        got = self.rank(map_id, entry, exit_)
        if got == "unknown":
            return True
        return got is not None and party_rank >= got

    def summary(self) -> dict:
        vals = list(self._rank.values())
        return {"maps": len(self.maps), "pairs": len(vals),
                "free": sum(1 for v in vals if v == FREE),
                "keyed": sum(1 for v in vals if v is not None and v >= 0),
                "unreachable": sum(1 for v in vals if v is None),
                "skipped": len(self.skipped)}

    # ------------------------------------------------------------------
    @classmethod
    def compute(cls, graph, rom_loader) -> "Gates":
        """★グラフの出口の升どうしで総当たり。`rom_loader(map_id)` は `RomMap` を返す（⚠ 起こせなければ例外）。

        ⚠ 世界地図の節（負の map）と、升を持たない辺（`world_edge`）は対象外。
        """
        out = cls()
        for map_id in sorted({e.from_map for e in graph.exits if e.from_map >= 0}):
            cells = sorted({(e.x, e.y) for e in graph.exits_of(map_id) if e.x is not None})
            if len(cells) < 2:
                continue
            try:
                rom_map = rom_loader(map_id)
            except Exception as ex:                      # noqa: BLE001 ★表に無い map など
                out.skipped[map_id] = str(ex)
                continue
            for a in cells:
                for b in cells:
                    if a != b:
                        out.put(Gate(map_id, a, b, rank_between(rom_map, a, b)))
        return out


__all__ = ["FREE", "KEY_ORDER", "Gate", "Gates", "rank_between"]
