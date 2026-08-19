"""そのマップが何階なのかを決める（2026-07-30 / マッパー仕様 フェーズ5）。

★★ **出どころが3つあり、強さが違う** ★★

| # | 出どころ | 強さ | 中身 |
| --- | --- | --- | --- |
| 1 | 人が入れた値（`MapFloorOverride`） | `confirmed` | **最優先** |
| 2 | ROM 由来の対応表（`map_bindings.yaml`） | `probable` | 北米版のコメント |
| 3 | 上下移動からの推定（`MapTransition`） | `provisional` | 遊んで溜まる |

⚠⚠ **食い違ったら黙って片方を選ばない。** ⚠⚠
  `conflict` に両方を入れて返し、画面に出す。
  地図の階層を静かに間違えると、あとの自動移動が**別の階へ行こうとする**。

## 推定のしかた（3番目）

    階段を下りて入ってきた（stairs_down） -> 来た階 - 1
    階段を上がって入ってきた（stairs_up）  -> 来た階 + 1
    落ちて入ってきた（pitfall）            -> 来た階 - 1

★それ以外（出入口・扉・旅の扉）からは**階層を推定しない**。
  町の出口が何階かは、上下移動ではないので言えない。

⚠ 来たほうの階層が分からなければ、当然こちらも分からない。
  推定は**1段だけ**たどる（何段もたどると、途中の1つの間違いが全体に広がる）。
"""

from __future__ import annotations

import dataclasses

from .models import Confidence, TransitionType

#: 階層が1つ変わる遷移。★これ以外からは推定しない
_FLOOR_DELTA = {
    TransitionType.STAIRS_DOWN: -1,
    TransitionType.STAIRS_UP: +1,
    TransitionType.PITFALL: -1,
}


def label_for(index: int | None) -> str | None:
    """階番号から表示用のラベル。`-2 -> "B2"` / `3 -> "3F"`。

    ⚠ `0` は使わない前提（ゲームに0階は無い）。来たら**そのまま出す**
      （勝手に 1F へ丸めると、間違いが見えなくなる）。
    """
    if index is None:
        return None
    if index < 0:
        return f"B{-index}"
    if index == 0:
        return "0?"
    return f"{index}F"


@dataclasses.dataclass(frozen=True)
class FloorEstimate:
    """階層の答え。**出どころと食い違いを一緒に返す。**"""

    map_id: int
    map_ptr: int
    index: int | None
    label: str | None
    #: `manual` / `binding` / `inferred` / `unknown`
    source: str
    confidence: Confidence
    #: ⚠ 食い違った出どころ `[(source, index), ...]`。**空でなければ画面に出す**
    conflict: tuple = ()
    #: 推定の根拠（画面に出して人が判断できるように）
    reason: str | None = None

    @property
    def known(self) -> bool:
        return self.index is not None

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflict)

    @property
    def display(self) -> str:
        """画面に出す文字列。★食い違いは**隠さない**。"""
        if self.index is None:
            return "階層不明"
        text = self.label or str(self.index)
        if self.conflict:
            others = " / ".join(f"{s}:{label_for(i)}" for s, i in self.conflict)
            return f"{text} ⚠食い違い（{others}）"
        return text


class FloorEstimator:
    """マップの階層を、出どころの強い順に決める。

    ⚠ **無いものは無いと言う。** 分からない階層を 1F で埋めない。
    """

    def __init__(self, repository=None, dictionary=None) -> None:
        #: 人の指定と遷移の記録を読む（`NavigationRepository`）。None でも動く
        self.repo = repository
        #: ROM 由来の対応表（`LocationDictionary`）。None でも動く
        self.dictionary = dictionary

    # --- 出どころごと ------------------------------------------------

    def _manual(self, map_id: int, map_ptr: int):
        if self.repo is None:
            return None
        try:
            row = self.repo.floor_override(map_id, map_ptr)
        except Exception:                              # noqa: BLE001
            return None
        if row is None or row.get("floor_index") is None:
            return None
        return int(row["floor_index"]), row.get("floor_label")

    def _binding(self, map_id: int):
        if self.dictionary is None:
            return None
        binding = self.dictionary.bindings.get(map_id)
        if binding is None or binding.floor_index is None:
            return None
        return binding.floor_index, binding.floor_label

    def _inferred(self, map_id: int, map_ptr: int):
        """上下移動から推定する。**1段だけ**たどる。

        ★同じ答えが何回観測されたかを数え、**一番多く見たものを採る**。
          途中で1回だけ変な遷移が入っても、それに引っ張られない。
        """
        if self.repo is None:
            return None
        try:
            rows = self.repo.transitions_into(map_id, map_ptr)
        except Exception:                              # noqa: BLE001
            return None
        votes: dict[int, int] = {}
        reasons: dict[int, str] = {}
        for row in rows:
            kind = _parse_type(row.get("transition_type"))
            delta = _FLOOR_DELTA.get(kind)
            if delta is None:
                continue
            # `from_map_id` / `from_map_ptr` は NOT NULL（schema）なので
            # ここで None を気にしなくてよい。
            source_map = int(row["from_map_id"])
            # ★来たほうは **ROM 由来と人の指定だけ**で決める。
            #   推定から推定へ渡すと、1つの間違いが全体に広がる。
            base = (self._manual(source_map, int(row["from_map_ptr"]))
                    or self._binding(source_map))
            if base is None:
                continue
            index = base[0] + delta
            weight = int(row.get("observed_count") or 1)
            votes[index] = votes.get(index, 0) + weight
            reasons[index] = (
                f"map ${int(source_map):02X}"
                f"（{label_for(base[0])}）から"
                f"{'下りて' if delta < 0 else '上がって'}来た"
                f"（{kind.value} を {weight} 回）")
        if not votes:
            return None
        # ★同数なら地上に近いほうを採る（決め方を固定しておく。
        #   決めておかないと実行ごとに答えが変わって、原因が追えなくなる）。
        best = max(votes, key=lambda i: (votes[i], -abs(i)))
        return best, label_for(best), reasons[best]

    # --- 入口 ---------------------------------------------------------

    def estimate(self, map_id, map_ptr=0) -> FloorEstimate:
        """階層を決める。**分からなければ `index=None`**。"""
        map_id = int(map_id)
        map_ptr = int(map_ptr or 0)
        manual = self._manual(map_id, map_ptr)
        binding = self._binding(map_id)
        inferred = self._inferred(map_id, map_ptr)

        # ★出どころを強い順に並べる
        candidates = []
        if manual is not None:
            candidates.append(("manual", manual[0], manual[1],
                               Confidence.CONFIRMED, "人が指定した値"))
        if binding is not None:
            candidates.append(("binding", binding[0], binding[1],
                               Confidence.PROBABLE,
                               "ROM 由来の対応表（map_bindings.yaml）"))
        if inferred is not None:
            candidates.append(("inferred", inferred[0], inferred[1],
                               Confidence.PROVISIONAL, inferred[2]))

        if not candidates:
            return FloorEstimate(map_id, map_ptr, None, None, "unknown",
                                 Confidence.PROVISIONAL,
                                 reason="階層の材料がありません")

        source, index, label, confidence, reason = candidates[0]
        # ⚠ ほかの出どころが**違う値**を言っていたら、それを持って返す
        conflict = tuple((s, i) for s, i, _l, _c, _r in candidates[1:]
                         if i != index)
        return FloorEstimate(
            map_id=map_id, map_ptr=map_ptr, index=index,
            label=label or label_for(index), source=source,
            confidence=confidence, conflict=conflict, reason=reason)

    def conflicts(self, keys) -> list:
        """食い違っているマップだけを並べる（画面の警告用）。

        ⚠ `keys` は **`(map_id, map_ptr)` の並び**。`map_id` だけだと
          人の指定（ポインタも鍵）が引けず、食い違いを**見落とす**。
        """
        found = []
        for key in keys:
            map_id, map_ptr = (key if isinstance(key, (tuple, list))
                               else (key, 0))
            estimate = self.estimate(map_id, map_ptr)
            if estimate.has_conflict:
                found.append(estimate)
        return found


def _parse_type(value) -> TransitionType:
    """遷移種別。**読めなければ `UNKNOWN`**（勝手に階段扱いしない）。"""
    try:
        return TransitionType(str(value))
    except (TypeError, ValueError):
        return TransitionType.UNKNOWN
