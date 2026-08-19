"""近傍から絵を決める規則表（2026-08-02 / 依頼者の指示）。

★★ **観測から作ります。推測で埋めません。** ★★

## ⚠ 名前について

上位3ビットを **`visual_class`（描画分類）** と呼びます。
⚠ `terrain`（地形）とは呼びません。★ここは**観測から作った規則**で、
  ROM から解いた地形ID（`dungeon_map.py`）とは**別物**だからです
  （2026-08-02 に `(b & $E0) >> 3` が地形IDだと分かりました）。
⚠⚠ **このモジュールはデコーダに使いません**（検証専用 / evidence 2.6）。

## 規則の形

```
キー: (中心, 左, 右, 上, 下, 象限)   ← ★まず4近傍だけ
値  : (タイル4枚, 属性, 出現数, 確度)
```

⚠⚠ **最初から8近傍を使いません。** データが疎になって、
「1件しか無いのに一意」という見せかけの規則ができてしまいます。
★4近傍で割れた組**だけ**、斜めを足して見直します。

## 確度

| 確度 | 意味 |
| --- | --- |
| `confirmed` | ★4近傍だけで一意に決まった |
| `diagonal` | ★斜めを足して一意になった |
| `conflict` | ⚠ 斜めを足しても割れる（**推測で選ばない**） |
"""

from __future__ import annotations

import collections
import dataclasses

#: ★象限ごとのずれ（実測 / 2026-08-02）。⚠ 規則表が無いときの手がかり
QUADRANT_OFFSET = {(0, 0): 0, (1, 0): 8, (0, 1): -2, (1, 1): 6}

#: 4近傍の並び（左・右・上・下）
NEIGHBOURS4 = ((-1, 0), (1, 0), (0, -1), (0, 1))
#: 斜め4方向（左上・右上・左下・右下）
DIAGONALS = ((-1, -1), (1, -1), (-1, 1), (1, 1))

CONFIRMED = "confirmed"
DIAGONAL = "diagonal"
CONFLICT = "conflict"


@dataclasses.dataclass(frozen=True)
class Rule:
    """1つの規則。"""

    key: tuple
    """`(中心, 左, 右, 上, 下, 象限)`。★斜めを使う場合は後ろに4つ足す。"""
    tiles: tuple
    """タイル4枚。⚠ `conflict` のときは None。"""
    attribute: int | None
    count: int
    """★その組が観測された回数。"""
    confidence: str

    @property
    def uses_diagonal(self) -> bool:
        return len(self.key) > 6


@dataclasses.dataclass
class RuleTable:
    """規則の集まり。★引けなければ None を返す（推測しない）。"""

    rules: dict = dataclasses.field(default_factory=dict)
    #: ⚠ 割れたまま決まらなかった組（黙って捨てない）
    conflicts: list = dataclasses.field(default_factory=list)

    def lookup(self, key4: tuple, key8: tuple | None = None):
        """規則を引く。⚠ 無ければ None。"""
        if key8 is not None and key8 in self.rules:
            return self.rules[key8]
        return self.rules.get(key4)

    def summary(self) -> str:
        by = collections.Counter(r.confidence for r in self.rules.values())
        return (f"規則 {len(self.rules)} 件"
                f"（★4近傍で決まった {by[CONFIRMED]} / "
                f"★斜めで決まった {by[DIAGONAL]}）"
                f" / ⚠ 割れたまま {len(self.conflicts)} 組")


def make_key(classes: dict, x: int, y: int, diagonal: bool = False):
    """観測から規則のキーを作る。⚠ 近傍が読めなければ None。

    `classes` は `{(セルX, セルY): visual_class}`。
    座標は**画面のマス**で渡し、ここで 1/2 にしてセルへ直します。
    """
    cx, cy = x >> 1, y >> 1
    centre = classes.get((cx, cy))
    if centre is None:
        return None
    around = []
    for dx, dy in NEIGHBOURS4 + (DIAGONALS if diagonal else ()):
        value = classes.get((cx + dx, cy + dy))
        if value is None:
            return None                  # ⚠ 端は規則を作らない（推測しない）
        around.append(value)
    return (centre, *around, (x & 1, y & 1))


def build(observations) -> RuleTable:
    """観測から規則表を作る。

    `observations` は
    `[(classes, x, y, タイル4枚, 属性), ...]`。

    ★まず4近傍だけで集計し、一意な組を `confirmed` にします。
    ⚠ 割れた組**だけ**、斜めを足して見直します。
    """
    tally4 = collections.defaultdict(collections.Counter)
    samples = collections.defaultdict(list)
    for classes, x, y, tiles, attr in observations:
        key = make_key(classes, x, y)
        if key is None:
            continue
        tally4[key][(tuple(tiles), attr)] += 1
        samples[key].append((classes, x, y, tiles, attr))

    table = RuleTable()
    for key, counter in tally4.items():
        if len(counter) == 1:
            (tiles, attr), count = next(iter(counter.items()))
            table.rules[key] = Rule(key=key, tiles=tiles, attribute=attr,
                                    count=count, confidence=CONFIRMED)
            continue
        # ⚠ 割れた。★この組だけ斜めを足して見直す
        tally8 = collections.defaultdict(collections.Counter)
        for classes, x, y, tiles, attr in samples[key]:
            key8 = make_key(classes, x, y, diagonal=True)
            if key8 is not None:
                tally8[key8][(tuple(tiles), attr)] += 1
        solved = 0
        for key8, counter8 in tally8.items():
            if len(counter8) == 1:
                (tiles, attr), count = next(iter(counter8.items()))
                table.rules[key8] = Rule(key=key8, tiles=tiles, attribute=attr,
                                         count=count, confidence=DIAGONAL)
                solved += 1
        if solved < len(tally8) or not tally8:
            # ⚠⚠ 斜めでも決まらない。**推測で選ばない**
            table.conflicts.append(Rule(
                key=key, tiles=None, attribute=None,
                count=sum(counter.values()), confidence=CONFLICT))
    return table
