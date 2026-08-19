"""保存済みの地図知識を、経路探索が使える形にする（2026-07-30 / 指示書 9章）。

★今回は**最低限**（隣接リストを作るところまで）。
  A* と自動移動は次フェーズだが、**足せる形**にしてある。

## 3つの高さのグラフ（マッパー仕様 フェーズ7）

| クラス | 節 | 辺の出どころ | 何に使うか |
| --- | --- | --- | --- |
| `MapGraph` | マス `(x, y)` | `MapEdge`（通れた） | 1つのマップの中を歩く |
| `WorldGraph` | マップ `(map_id, map_ptr)` | `MapTransition`（遷移） | 「どのマップ経由で行くか」 |
| `LocationGraph` | ロケーション | 同じ遷移をまとめたもの | 「どの町を通るか」 |

★下の段（マス）が無くても上の段は作れる。
  「ローレシアからルプガナへは○○を通る」だけなら遷移の記録で足りる。

## 次フェーズで A* を足すときの接続点

    graph = MapGraph.load(repository, map_id, map_ptr)
    graph.neighbors((x, y))     -> [((nx, ny), コスト), ...]
    graph.is_blocked((x, y), direction)

    world = WorldGraph.load(repository)
    world.route(start_key, goal_key)   -> [キー, ...]（幅優先）

これだけあれば A* は書ける。`neighbors` が返すのは
**実際に通れたと観測した辺だけ**なので、
「知らない道は通らない」という安全側の挙動になる。

⚠ 未探索のマスへは行けない（知識が無いので当然）。
  「知らない所へ行きたい」は探索の話で、経路探索とは別の機能。

⚠⚠ **遷移は片方向として扱う。** 「AからBへ行けた」は
  「BからAへ戻れる」を意味しない（落とし穴・一方通行の階段がある）。
  戻り道は**戻ったときに記録される**。
"""

from __future__ import annotations

import collections
import dataclasses

from .models import Confidence, Direction


@dataclasses.dataclass
class MapGraph:
    """1つのマップぶんの通行グラフ。"""

    map_id: int
    map_ptr: int
    #: {(x, y): [((nx, ny), コスト, 方向)]}
    adjacency: dict = dataclasses.field(default_factory=dict)
    #: {(x, y, 方向): 確度}
    blocked: dict = dataclasses.field(default_factory=dict)

    @classmethod
    def load(cls, repository, map_id: int, map_ptr: int) -> "MapGraph":
        graph = cls(map_id=map_id, map_ptr=map_ptr)
        for row in repository.edges(map_id, map_ptr):
            direction = Direction.parse(row.get("direction"))
            src = (int(row["from_x"]), int(row["from_y"]))
            dst = (int(row["to_x"]), int(row["to_y"]))
            cost = float(row.get("movement_cost") or 1.0)
            graph.adjacency.setdefault(src, []).append((dst, cost, direction))
        for row in repository.blocked(map_id, map_ptr):
            direction = Direction.parse(row.get("direction"))
            if direction is None:
                continue
            graph.blocked[(int(row["x"]), int(row["y"]), direction)] = \
                Confidence(row.get("confidence") or Confidence.PROVISIONAL.value)
        return graph

    def neighbors(self, node: tuple) -> list:
        """そのマスから**実際に通れたと観測した**隣接マス。"""
        return [(dst, cost) for dst, cost, _d in self.adjacency.get(node, [])]

    def is_blocked(self, node: tuple, direction: Direction,
                   min_confidence: Confidence = Confidence.PROBABLE) -> bool:
        """その方向が「通れない」と言えるか。

        ★既定は `probable` 以上のときだけ True。
          **1回失敗しただけの `provisional` では通れないと言わない**
          （指示書 2.4）。
        """
        found = self.blocked.get((node[0], node[1], direction))
        if found is None:
            return False
        # ★確度の順は `Confidence.rank` 1箇所だけ（写すとずれる / models.py）
        return found.rank >= min_confidence.rank

    @property
    def node_count(self) -> int:
        nodes = set(self.adjacency)
        for edges in self.adjacency.values():
            nodes.update(dst for dst, _c, _d in edges)
        return len(nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self.adjacency.values())


def breadth_first(neighbors, start, goal) -> list | None:
    """`start` から `goal` までの道順。**無ければ None**。

    ★★ **幅優先**（`popleft`）。★★ マップ間・ロケーション間は本数が
      少ないので、これで足りる（重み付きの探索が要るのはマスの段）。
      深さ優先にすると、短い道があるのに**遠回りを返す**。

    ⚠⚠ **見つからないときに「近いところ」を返さない。**
      途中までの道順を返すと、呼ぶ側が着いたと思ってしまう。

    ⚠ 一度見た節はもう積まない。**輪があると止まらなくなる**
      （ローレシア 1F ⇄ 2F のような行き来は普通にある）。

    ★マップの段とロケーションの段で**同じ関数を使う**。
      写すと、片方だけ直して答えが食い違う。
    """
    if start == goal:
        return [start]
    seen = {start}
    queue = collections.deque([[start]])
    while queue:
        path = queue.popleft()
        for target in neighbors(path[-1]):
            if target in seen:
                continue
            if target == goal:
                return path + [target]
            seen.add(target)
            queue.append(path + [target])
    return None


@dataclasses.dataclass(frozen=True)
class WorldLink:
    """マップからマップへの1本（`MapTransition` 1行ぶん）。"""

    #: 出るマップ `(map_id, map_ptr)`
    source: tuple
    #: 入るマップ `(map_id, map_ptr)`
    target: tuple
    #: 出る座標・入る座標。★どこに立てば移れるかが分からないと歩けない
    from_xy: tuple
    to_xy: tuple
    kind: str
    confidence: Confidence
    observed_count: int = 1


@dataclasses.dataclass
class WorldGraph:
    """マップとマップのつながり（マッパー仕様 フェーズ7）。

    ★節は `(map_id, map_ptr)`。⚠ `map_id` だけにしない
      （同じ ID で別の階があるので、混ぜると別の階へ行こうとする）。
    """

    #: {出るマップ: [WorldLink, ...]}
    links: dict = dataclasses.field(default_factory=dict)

    @classmethod
    def load(cls, repository, min_confidence: Confidence | None = None
             ) -> "WorldGraph":
        """記録から作る。`min_confidence` を渡すとそれ以上だけ。

        ⚠ 既定では**全部**入れる。1回しか見ていない遷移も「そこは通れた」
          という観測なので捨てない。絞りたい側が絞る。
        """
        graph = cls()
        try:
            rows = repository.transitions()
        except Exception:                              # noqa: BLE001
            return graph
        for row in rows:
            link = _link(row)
            if link is None:
                continue
            if (min_confidence is not None
                    and link.confidence.rank < min_confidence.rank):
                continue
            graph.links.setdefault(link.source, []).append(link)
        return graph

    def neighbors(self, key: tuple) -> list:
        """そのマップから**実際に移れたと観測した**マップ。"""
        return [link.target for link in self.links.get(tuple(key), [])]

    def links_between(self, source: tuple, target: tuple) -> list:
        """2つのマップをつなぐ遷移（どこに立てば移れるか）。"""
        return [link for link in self.links.get(tuple(source), [])
                if link.target == tuple(target)]

    def route(self, start: tuple, goal: tuple) -> list | None:
        """マップの並びとしての道順。**無ければ None**。"""
        return breadth_first(self.neighbors, tuple(start), tuple(goal))

    @property
    def node_count(self) -> int:
        nodes = set(self.links)
        for links in self.links.values():
            nodes.update(link.target for link in links)
        return len(nodes)

    @property
    def link_count(self) -> int:
        return sum(len(v) for v in self.links.values())


@dataclasses.dataclass
class LocationGraph:
    """ロケーションとロケーションのつながり（マッパー仕様 フェーズ7）。

    ★★ **これは人に見せるための段。** ★★
      「ローレシア → 世界地図 → ルプガナ」のように、
      階を気にせず「どの町を通るか」を言うのに使う。

    ⚠ 自動移動は `WorldGraph`（階まで区別する段）を使う。
      こちらは同じロケーションの別の階を**1つにまとめてしまう**ので、
      これで歩かせると別の階へ行こうとする。
    """

    #: {ロケーションID: {つながるロケーションID}}
    links: dict = dataclasses.field(default_factory=dict)
    #: ⚠ 辞書に無い map_id があった数。**0 でなければ画面に出す**
    unknown_maps: int = 0

    @classmethod
    def load(cls, repository, dictionary) -> "LocationGraph":
        graph = cls()
        if dictionary is None:
            return graph
        try:
            rows = repository.transitions()
        except Exception:                              # noqa: BLE001
            return graph
        for row in rows:
            source = cls._location_of(dictionary, row.get("from_map_id"))
            target = cls._location_of(dictionary, row.get("to_map_id"))
            if source is None or target is None:
                # ⚠ 辞書に無いマップ。**近いロケーションに寄せない**
                graph.unknown_maps += 1
                continue
            if source == target:
                # ★同じロケーションの中の階段。ここでは辺にしない
                #   （「ローレシア → ローレシア」は道順として意味が無い）
                continue
            graph.links.setdefault(source, set()).add(target)
        return graph

    @staticmethod
    def _location_of(dictionary, map_id):
        if map_id is None:
            return None
        binding = dictionary.bindings.get(int(map_id))
        return binding.location_id if binding is not None else None

    def neighbors(self, location_id: str) -> list:
        return sorted(self.links.get(location_id, ()))

    def route(self, start: str, goal: str) -> list | None:
        """ロケーションの並びとしての道順。**無ければ None**。"""
        return breadth_first(self.neighbors, start, goal)

    @property
    def node_count(self) -> int:
        nodes = set(self.links)
        for targets in self.links.values():
            nodes.update(targets)
        return len(nodes)

    @property
    def link_count(self) -> int:
        return sum(len(v) for v in self.links.values())


def _link(row) -> WorldLink | None:
    """1行から `WorldLink`。**読めなければ None**（推測で埋めない）。"""
    try:
        source = (int(row["from_map_id"]), int(row["from_map_ptr"]))
        target = (int(row["to_map_id"]), int(row["to_map_ptr"]))
        from_xy = (int(row["from_x"]), int(row["from_y"]))
        to_xy = (int(row["to_x"]), int(row["to_y"]))
    except (KeyError, TypeError, ValueError):
        return None
    # ★読めない確度は **provisional**（勝手に上げない）
    confidence = Confidence.parse(row.get("confidence"), Confidence.PROVISIONAL)
    return WorldLink(
        source=source, target=target, from_xy=from_xy, to_xy=to_xy,
        kind=str(row.get("transition_type") or "unknown"),
        confidence=confidence,
        observed_count=int(row.get("observed_count") or 1))
