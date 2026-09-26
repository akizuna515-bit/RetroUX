"""map をまたぐつながり（RX3-0067 Phase B / 2026-09-07）。

## ★何をするもので、何をしないか

```text
★する    (map, x, y) の升 → どの map のどこへ出るか
          map から map への最短の道順（⚠ 何回乗り換えるか）
          ⚠⚠ 入って出たら元の升に戻るか（★片道になっていないか）
⚠ しない  map の**中**の経路（★`dq3/testing/navigation.py` の担当）
⚠ しない  鍵の条件（★`RX3-0078` / `RX3-0014` が決まってから）
⚠ しない  名前・場所の束ね（★Phase A / `location_book` で済み）
```

## ⚠ 材料は `dq3rom.world_model` の `connections` です

★ROM を直接読みません（⚠ 番地を 2 か所に書かないため）。

```text
world_model.build(ident)  →  locations[].connections[]  →  ★ここ
```

## ⚠⚠ 「行けるかどうか」を、こちらで**盛りません**

★行き先が決まらない升（`arrival.where == "unknown"`）は、
⚠ **道として数えません**。★数に出して、`unknown_exits()` で見られるようにします。

⚠ `RX3-0081` で分かったとおり、⚠ **升と表が 1 つずれる map が 12 あります**。
★対応が付かなかった升は `to` が `None` で来るので、⚠ ここでも道にしません。

## ★★ 世界地図（2026-09-16 / RX3-0067）

★`world=`（`dq3rom.world_entrances.world_links()`）を渡すと、
世界地図を **1 つの節**として張ります（⚠ 渡さなければ昔の形のまま）。

```text
節   WORLD_NODES   world_main = -1 / world_alefgard = -2
辺   world_in      世界地図の升 → map        ★入口表（bank6 $B24C）の行
     world_edge    map → 世界地図（自分の升）  ⚠ 端から歩き出る。★升を持たない（x, y = None）
     world         map の出口 → 世界地図      ★着く升の世界で振り分け（⚠ 決まらなければ unknown）
```

⚠⚠ `world_edge` は **OBSERVED** です。★裏は「世界へ出る出口の着地点 25 件のうち
22 件が、入口表の升そのもの」（★表とは別の ROM の表 / 検査に固定）。
⚠ 町の端から出る処理そのものは読んでいません。

⚠ 世界地図の**中**は 1 節に潰します。★船・島・橋の有無は見ません
（⚠ map の中の経路と同じく、★別の担当）。
"""
from __future__ import annotations

import collections
import dataclasses

#: ★世界地図の節（⚠ ROM の map 番号と重ならないよう負の数）
WORLD_NODES = {"world_main": -1, "world_alefgard": -2}
#: ★世界地図を張ったときに**足した**辺（⚠ ROM の出口表の行ではない）
ADDED_WHERE = ("world_in", "world_edge")


@dataclasses.dataclass(frozen=True)
class Exit:
    """★1 つの出口（⚠ 「そこへ行ける」とまでは言わない）。"""

    from_map: int
    x: int | None         #: ⚠ `world_edge` だけ `None`（★端から出るので升が無い）
    y: int | None
    to_map: int | None
    kind: int | None
    band: str | None
    where: str            #: ★`entrance` / `local` / `world` / `world_in` / `world_edge` / `unknown` / `none`
    to_index: int | None = None
    to_x: int | None = None
    to_y: int | None = None
    rom_dest: int | None = None   #: ★世界地図へ付け替えた出口の、表の行き先 map（⚠ 意味は未確定）

    @property
    def usable(self) -> bool:
        """★行き先が決まっているか。⚠ `unknown` は道にしない。"""
        return self.to_map is not None and self.where in (
            "entrance", "local", "world") + ADDED_WHERE


class MapGraph:
    """★map と map のつながり。⚠ Qt も ROM も知りません。"""

    def __init__(self, exits: list[Exit]) -> None:
        self.exits = list(exits)
        self._by_map: dict[int, list[Exit]] = collections.defaultdict(list)
        for e in self.exits:
            self._by_map[e.from_map].append(e)

    # ------------------------------------------------------------------
    @classmethod
    def from_model(cls, model: dict, world: dict | None = None) -> "MapGraph":
        """★`dq3rom.world_model.build()` の結果から組む。

        ★`world` に `dq3rom.world_entrances.world_links()` を渡すと世界地図も張る。
        """
        got: list[Exit] = []
        for loc in model.get("locations", []):
            for c in loc.get("connections", []):
                a = c.get("arrival") or {}
                e = Exit(
                    from_map=int(c["from_map_id"]),
                    # ★地図の端から歩き出る行（`via = edge` / RX3-0081）は升を持たない
                    x=None if c.get("x") is None else int(c["x"]),
                    y=None if c.get("y") is None else int(c["y"]),
                    to_map=c.get("to_map_id"),
                    kind=c.get("kind"),
                    band=c.get("kind_band"),
                    where=str(a.get("where") or ("none" if c.get("to_map_id") is None else "unknown")),
                    to_index=a.get("to_index"),
                    to_x=a.get("x"), to_y=a.get("y"),
                )
                if world is not None and e.where == "world":
                    e = _to_world(e, world)
                got.append(e)
        if world is not None:
            got.extend(_world_edges(world))
        return cls(got)

    # ------------------------------------------------------------------
    def exits_of(self, map_id: int) -> list[Exit]:
        """★その map の出口（⚠ 走査順のまま ＝ 表の索引順）。"""
        return list(self._by_map.get(int(map_id), []))

    def exit_at(self, map_id: int, x: int, y: int) -> Exit | None:
        """★その升の出口。⚠ 無ければ `None`。"""
        for e in self._by_map.get(int(map_id), []):
            if (e.x, e.y) == (int(x), int(y)):
                return e
        return None

    def unknown_exits(self) -> list[Exit]:
        """⚠ 行き先が決まらない出口（★黙って消さない）。"""
        return [e for e in self.exits if not e.usable]

    def neighbours(self, map_id: int) -> list[int]:
        """★その map から 1 回で行ける map（⚠ 自分は含めない）。"""
        got = {e.to_map for e in self._by_map.get(int(map_id), [])
               if e.usable and e.to_map != int(map_id)}
        return sorted(got)

    # ------------------------------------------------------------------
    def arrival_cell(self, exit_: Exit) -> tuple[int, int] | None:
        """★その出口を通った先で**立つ升**（RX3-0067 / 鍵の条件の起点）。⚠ 決まらなければ None。

        ```text
        entrance   行き先 map の「何番目の入口」の升（★表の行 / 足した辺は数えない）
        local      表の (x, y)
        world / world_in / world_edge   ⚠ None（★世界地図は 1 節 / 町に入った升は表に無い）
        ```
        """
        if exit_.where == "local" and exit_.to_x is not None:
            return (int(exit_.to_x), int(exit_.to_y))
        if exit_.where == "entrance" and exit_.to_index is not None and exit_.to_map is not None:
            rows = [r for r in self._by_map.get(int(exit_.to_map), []) if r.where not in ADDED_WHERE]
            if exit_.to_index < len(rows):
                return (rows[exit_.to_index].x, rows[exit_.to_index].y)
        return None

    def steps(self, map_id: int, at, *, party_rank: int = -1, gates=None):
        """★`map_id` の升 `at` に立っている一行が、次に行ける `(出口, 行き先 map, 着く升)`。

        ★`gates`（`map_gates.Gates`）を渡すと、⚠ その升から歩いて着けない出口・鍵の段位が足りない出口を除く。
        ⚠ `at` が None（★どこに立っているか決まらない）や、升を持たない辺（`world_edge`）は今までどおり通す。
        """
        for e in self._by_map.get(int(map_id), []):
            if not e.usable:
                continue
            if gates is not None and at is not None and e.x is not None:
                if not gates.passable(map_id, at, (e.x, e.y), party_rank):
                    continue
            yield e, e.to_map, self.arrival_cell(e)

    @staticmethod
    def _party_rank(keys) -> int:
        from dq3rom import door_keys as _dk

        return _dk.party_rank(keys or ())

    def route(self, start: int, goal: int, *, limit: int = 64, at=None, keys=(), gates=None) -> list[int] | None:
        """★`start` から `goal` まで、通る map の並び。⚠ 行けなければ `None`。

        ⚠ 返すのは **map の並び**だけです（★升の経路は map の中の BFS の担当）。

        ## ★鍵と、入った升（RX3-0067 / 2026-09-17）

          ★`gates` と `at`（いま立っている升）を渡すと、⚠ 「その升から歩いて着けない出口」と
          「持っている鍵（`keys` = 道具 ID）で開かない扉の先の出口」を通りません。
          ⚠ 渡さなければ**今までどおり**（★map の並びだけを見る）。
        """
        start, goal = int(start), int(goal)
        if start == goal:
            return [start]
        rank = self._party_rank(keys)
        first = (start, tuple(at) if (at is not None and gates is not None) else None)
        seen = {first}
        queue = collections.deque([(first, [start])])
        while queue:
            (m, cell), path = queue.popleft()
            if len(path) > limit:
                continue
            for _e, nxt, nxt_cell in self.steps(m, cell, party_rank=rank, gates=gates):
                if nxt == m:
                    continue
                state = (nxt, nxt_cell if gates is not None else None)
                if state in seen:
                    continue
                if nxt == goal:
                    return path + [nxt]
                seen.add(state)
                queue.append((state, path + [nxt]))
        return None

    def reachable(self, start: int, *, at=None, keys=(), gates=None) -> set[int]:
        """★そこから辿れる map ぜんぶ（⚠ 「まだ行っていない場所」を出す材料）。★`gates` / `keys` は `route` と同じ。"""
        start = int(start)
        rank = self._party_rank(keys)
        first = (start, tuple(at) if (at is not None and gates is not None) else None)
        seen, queue = {first}, collections.deque([first])
        while queue:
            m, cell = queue.popleft()
            for _e, nxt, nxt_cell in self.steps(m, cell, party_rank=rank, gates=gates):
                state = (nxt, nxt_cell if gates is not None else None)
                if state not in seen:
                    seen.add(state)
                    queue.append(state)
        return {m for m, _cell in seen}

    # ------------------------------------------------------------------
    def return_exit(self, exit_: Exit) -> Exit | None:
        """★その出口で行った先から、**元の map へ戻る**出口。

        ⚠⚠ `kind < 0x80` は「行き先の何番目の入口に着くか」なので、
        ★その番目の出口が元へ戻るはずです（`RX3-0013` の「戻り」）。
        ⚠ それ以外の帯（着地点が座標で決まる）は、★索引が無いので `None`。
        """
        if not exit_.usable or exit_.where != "entrance" or exit_.to_index is None:
            return None
        # ⚠ 足した辺は表の行ではない（★混ぜると索引がずれる）
        rows = [r for r in self._by_map.get(int(exit_.to_map), [])
                if r.where not in ADDED_WHERE]
        if exit_.to_index >= len(rows):
            return None
        return rows[exit_.to_index]

    def round_trip_ok(self, exit_: Exit) -> bool | None:
        """★入って出たら元の map へ戻るか。⚠ 判定できなければ `None`。"""
        back = self.return_exit(exit_)
        if back is None:
            return None
        return back.to_map == exit_.from_map

    def one_way(self) -> list[Exit]:
        """⚠⚠ 片道になっている出口（★`RX3-0067` の Tests そのもの）。"""
        return [e for e in self.exits if self.round_trip_ok(e) is False]

    # ------------------------------------------------------------------
    def summary(self) -> dict:
        judged = [e for e in self.exits if self.round_trip_ok(e) is not None]
        return {
            "exits": len(self.exits),
            "usable": sum(1 for e in self.exits if e.usable),
            "unknown": len(self.unknown_exits()),
            "maps": len(self._by_map),
            "round_trip_checked": len(judged),
            "one_way": len(self.one_way()),
        }


def world_of_cell(world: dict, x: int, y: int) -> str | None:
    """★世界地図の升が、どちらの世界か。⚠ 決まらなければ `None`。

    ① その世界で入口の升なら、その世界
    ② ⚠ 片方の地図の中にしか収まらないなら、その世界（★アレフガルドは小さい）
    """
    cells = world["entrance_cells"]
    hits = [n for n in WORLD_NODES if (x, y) in cells.get(n, ())]
    if len(hits) == 1:
        return hits[0]
    inside = [n for n in WORLD_NODES
              if n in world["sizes"] and x < world["sizes"][n][0] and y < world["sizes"][n][1]]
    return inside[0] if len(inside) == 1 else None


def _to_world(e: Exit, world: dict) -> Exit:
    """★世界へ出る出口を、行き先 map ではなく**世界地図の節**へ付け替える。"""
    name = None if e.to_x is None else world_of_cell(world, e.to_x, e.to_y)
    if name is None:
        # ⚠ どちらの世界か決まらない（★黙って主世界に寄せない）
        return dataclasses.replace(e, to_map=None, where="unknown", rom_dest=e.to_map)
    return dataclasses.replace(e, to_map=WORLD_NODES[name], rom_dest=e.to_map)


def _world_edges(world: dict) -> list[Exit]:
    """★入口表の行 1 つから、世界 → map と map → 世界の 2 本。"""
    got: list[Exit] = []
    for r in world["entrances"]:
        node, m = WORLD_NODES[r["world"]], int(r["map_id"])
        got.append(Exit(from_map=node, x=int(r["x"]), y=int(r["y"]), to_map=m,
                        kind=None, band="world_table", where="world_in"))
        got.append(Exit(from_map=m, x=None, y=None, to_map=node,
                        kind=None, band="world_table", where="world_edge",
                        to_x=int(r["x"]), to_y=int(r["y"])))
    return got


__all__ = ["Exit", "MapGraph", "WORLD_NODES", "ADDED_WHERE", "world_of_cell"]
