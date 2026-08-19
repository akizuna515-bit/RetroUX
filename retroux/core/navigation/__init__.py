"""移動知識ログ（2026-07-30 / 指示書 `input/移動知識ログ・経路記録仕様.md`）。

★★ **保存するのは「どのキーを何回押したか」ではない。** ★★

  > 保存すべきものは、専属マッパーがプレイ結果から確認した
  >   この道は通れる / この方向は今のところ通れない /
  >   この階段は別のマップにつながる
  > という再利用可能な地図知識である。

## 分担（指示書 9章）

| ファイル | 役割 |
| --- | --- |
| `models.py` | 語彙（方向・確度・分類）と `PendingMove` |
| `observer.py` | 状態の変化から「通れた/通れなかった/遷移した」を判定 |
| `repository.py` | UPSERT で集約して保存する |
| `graph.py` | 保存済みの辺を隣接リストにする（次フェーズの経路探索の入口） |

## マッパー機能（2026-07-30 / 「RetroUX マッパー機能 全体仕様書」）

| ファイル | 役割 |
| --- | --- |
| `location_resolver.py` | `map_id` から**ロケーション名 + 階層**を作る（表示だけ） |
| `floor_estimator.py` | 何階かを決める（人の指定 > ROM 由来 > 上下移動からの推定） |

`graph.py` は3つの高さを持つ:

    MapGraph      節 = マス `(x, y)`                … 1つのマップの中を歩く
    WorldGraph    節 = マップ `(map_id, map_ptr)`   … ★自動移動が使う段
    LocationGraph 節 = ロケーション                 … 人に見せる段

⚠ `LocationGraph` は**同じロケーションの別の階を1つにまとめる**。
  これで歩かせると別の階へ行こうとする。歩くのは `WorldGraph` の段。

★★ **名前は表示だけに使う。** ★★ 自動移動が使うのは `map_id` と階層
  （どちらも ROM 由来）なので、名前が間違っていても経路は壊れない。

## 責務の境界（指示書 10章）

    View          … 表示だけ
    ViewModel     … 状態の仲介
    Observer      … 移動結果の判定   ← ここに判定ロジックを閉じる
    Repository    … 永続化

⚠ View に移動判定を書かない。
"""

from .floor_estimator import FloorEstimate, FloorEstimator
from .graph import LocationGraph, MapGraph, WorldGraph, WorldLink
from .location_resolver import (
    LocationDictionary, LocationResolver, ResolvedLocation,
)
from .models import (
    ActionType, Classification, Confidence, Direction, PendingMove,
)
from .observer import NavigationObserver
from .repository import NavigationRepository

__all__ = [
    "ActionType", "Classification", "Confidence", "Direction", "PendingMove",
    "NavigationObserver", "NavigationRepository",
    "FloorEstimate", "FloorEstimator",
    "LocationDictionary", "LocationResolver", "ResolvedLocation",
    "LocationGraph", "MapGraph", "WorldGraph", "WorldLink",
]
