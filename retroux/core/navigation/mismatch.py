"""ROM 解析と実プレイの食い違いを見つける（Phase 6 / 指示書 §17）。

## ★ 何のためか

`work/generated/map_passability.json` は **相関にもとづく見立て**です
（`retroux/tools/map_passability.py` の説明を参照）。

    ★確認できた: 属性の上位ニブルは独立した場（逆アセンブル）
    ⚠ 未特定    : 移動処理のどこでそれを見ているか

★ここで実プレイと突き合わせて、**見立てが正しいかを確かめます**。

## ⚠⚠ 成功した歩行は記録しない

指示書 §17:

  > 通常の成功歩行は残さず、静的解析と実プレイが食い違ったときだけ記録

★食い違いだけを残せば、件数がそのまま「見立ての誤り」の量になります。
⚠ 全部残すと、また 2,117 行の山ができます（それをやめたのが Phase 4）。

## ⚠ 「進めなかった」を鵜呑みにしない

`MapBlockedDirection` の観測は「30 フレーム押しても動かなかった」で作ります。
★NPC・演出・入力の取りこぼしが混ざります（実測 235 件が ROM では通れる地形）。

したがって食い違いには**2種類**あり、重みが違います:

| 種類 | 意味 | ★重み |
| --- | --- | --- |
| `walked_but_blocked` | 表は通れないと言ったが**歩けた** | ★★ 見立ての誤り |
| `blocked_but_walkable` | 表は通れると言ったが**進めなかった** | ⚠ NPC の可能性が高い |

★前者は**言い訳が効きません**。1件でも出たら見立てが誤りです。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Mismatch:
    """1件の食い違い。★そのままイベントにできる形にする。"""

    map_id: int
    x: int
    y: int
    direction: str | None
    kind: str                 # walked_but_blocked / blocked_but_walkable
    expected: str             # ROM 解析の判定
    observed: str             # 実プレイ
    terrain_id: int | None
    terrain_class: int | None

    def to_event(self) -> dict:
        return {
            "type": "navigation_mismatch",
            "map_id": self.map_id, "x": self.x, "y": self.y,
            "direction": self.direction,
            "kind": self.kind,
            "expected": self.expected, "observed": self.observed,
            "terrain_id": self.terrain_id,
            "terrain_class": self.terrain_class,
        }


class PassabilityTable:
    """`map_passability.json` を引く。★無ければ**何も言わない**。

    ⚠ 表が無いことを異常にしない。★ROM 解析はまだ全マップを覆っていない
      （世界地図は対象外）。「分からない」と「食い違い」を混ぜないため。
    """

    def __init__(self, data: dict | None) -> None:
        self._cells: dict[tuple[int, int, int], dict] = {}
        if not data:
            return
        for m in data.get("maps", []):
            map_id = m["map_id"]
            for c in m.get("cells", []):
                self._cells[(map_id, c["x"], c["y"])] = c

    @classmethod
    def load(cls, path: Path | str) -> "PassabilityTable":
        p = Path(path)
        if not p.exists():
            return cls(None)
        try:
            return cls(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            # ⚠ 読めなくても本体は動かす（★食い違いが出ないだけ）
            return cls(None)

    def __bool__(self) -> bool:
        return bool(self._cells)

    def at(self, map_id: int, x: int, y: int) -> dict | None:
        return self._cells.get((map_id, x, y))

    def foot(self, map_id: int, x: int, y: int) -> bool | None:
        """歩いて通れるか。⚠ **分からなければ None**（扉・宝箱・表の外）。"""
        cell = self.at(map_id, x, y)
        if cell is None:
            return None
        return (cell.get("passability") or {}).get("foot")


def check_walked(table: PassabilityTable, map_id: int, x: int, y: int,
                 direction: str | None = None) -> Mismatch | None:
    """★実際に歩けたマスを見る。表が「通れない」と言っていたら食い違い。

    ⚠⚠ **これが出たら見立てが誤り**です。言い訳が効きません。
    """
    cell = table.at(map_id, x, y)
    if cell is None:
        return None                                    # ★表の外。何も言わない
    if (cell.get("passability") or {}).get("foot") is not False:
        return None                                    # ★食い違っていない
    return Mismatch(
        map_id=map_id, x=x, y=y, direction=direction,
        kind="walked_but_blocked",
        expected="blocked", observed="walk",
        terrain_id=cell.get("terrain_id"),
        terrain_class=cell.get("terrain_class"))


def check_blocked(table: PassabilityTable, map_id: int, x: int, y: int,
                  direction: str | None = None) -> Mismatch | None:
    """⚠ 進めなかった向きの先を見る。表が「通れる」と言っていたら食い違い。

    ⚠ **NPC・演出の可能性が高い**ので、そのまま表を直す根拠にしない。
      ★件数と場所の偏りを見るための材料。
    """
    cell = table.at(map_id, x, y)
    if cell is None:
        return None
    if (cell.get("passability") or {}).get("foot") is not True:
        return None
    return Mismatch(
        map_id=map_id, x=x, y=y, direction=direction,
        kind="blocked_but_walkable",
        expected="walk", observed="blocked",
        terrain_id=cell.get("terrain_id"),
        terrain_class=cell.get("terrain_class"))
