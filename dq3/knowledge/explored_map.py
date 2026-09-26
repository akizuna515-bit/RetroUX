"""探索済みの升を貯める（RX3-0205 / 2026-09-12 依頼者「DQ3 ダンジョン探索MAP v1」Phase A）。

★★ 3 つの MAP を分けます（指示書 §1）★★

```text
ROM MAP       ROM から起こした地形            ⚠ 通常の画面には出さない（★描き分け・検査だけ）
Visible MAP   いま画面に映っていて、勇者と     ★その場で計算する（`visible_cells`）/ ⚠ 保存しない
              同じ層の升
Explored MAP  一度でも Visible だった升       ★ここ（`work/dq3-knowledge/explored.json`）
```

## ★「見た升」（seen.json / RX3-0023）との違い

★見た升は「画面に映った升」ぜんぶです（⚠ 別の部屋＝**別の層**の升も入る）。
⚠ 町・洞窟では、勇者と別の層の升を**黒く**描きます（RX3-0191 / ゲームの画面と同じ）。
→ ⚠ だから部屋を移ると、前の部屋が黒くなり「いま居る小部屋だけ」が見えていました。

★探索済みは、映った升のうち**勇者と同じ層として見えた升**だけです（★本当に明るく見えた所）。
⚠ 一度入ったら消しません。⚠ 探索済み ⊆ 見た升（★どちらも画面に映った升から作る / ROM は読まない）。

## ★鍵

★見た升と同じ（`L<map_id>`）。⚠ 世界地図は層を持たないので、ここには入れません（★見た升がそのまま探索済み）。
⚠ 1 つの map に何階もある洞窟は、階ごとに座標が離れているので混ざりません（★別の map_id の階は別の鍵）。

## ⚠ 材料

★層を決めるには**実機の升の値**（`$7400` / `map_art`）が要ります。⚠ 今の地図の材料が無いときは記録しません
（★前の地図の値で決めない / `RX3-0046`）。
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib

from dq3rom import viewport

from .. import paths
from .seen_map import SeenMap

#: ★保存先（⚠ `work/` は Git の外 / 見た升とは別のファイル）
DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "explored.json")

#: ★入れ物の種類（⚠ 見た升の記録と取り違えないため）
KIND = "explored"


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def visible_cells(live, party_x: int, party_y: int) -> list[tuple[int, int]]:
    """★Visible MAP: いま画面に映っていて、勇者と**同じ層**の升。

    `live`: 実機の升（`tile_art.RuntimeArt` / `at(x, y)` と `width` `height` を持つもの）。
    ⚠ 勇者の升が読めなければ空（★層が決まらない）。
    """
    from .tile_art import DARK_INDEX, index_of

    hero_raw = live.at(int(party_x), int(party_y))
    if hero_raw is None:
        return []
    view = viewport.Viewport(party_x=int(party_x), party_y=int(party_y),
                             width=int(live.width), height=int(live.height))
    out = []
    for map_x, map_y, _tile_x, _tile_y in view.visible_cells():
        raw = live.at(map_x, map_y)
        if raw is None:
            continue
        # ★黒く描く升（別の層）は入れない（⚠ 層の決まりは `index_of` の 1 か所だけ / RX3-0191）
        if index_of(raw, hero_raw) != DARK_INDEX:
            out.append((map_x, map_y))
    return out


class ExploredMap(SeenMap):
    """map ごとに「探索済みの升」を貯める（★形は見た升と同じ / ⚠ 別のファイル）。"""

    def __init__(self, path=None) -> None:
        super().__init__(path if path is not None else DEFAULT_PATH)
        #: ★その地図で最後に増えた時刻（指示書 §4 updated_at）
        self.updated_at: dict[str, str] = {}

    def mark_cells(self, key: str, cells) -> int:
        """★升をまとめて探索済みにする。戻り値: ★新しく増えた数。"""
        added = 0
        for x, y in cells:
            if self.mark(key, x, y):
                added += 1
        if added:
            self.updated_at[str(key)] = _now()
        return added

    def to_dict(self) -> dict:
        body = super().to_dict()
        body["kind"] = KIND
        for key, row in body["maps"].items():
            if key in self.updated_at:
                row["updated_at"] = self.updated_at[key]
        return body

    @classmethod
    def from_dict(cls, data: dict, path=None) -> "ExploredMap":
        got = super().from_dict(data, path if path is not None else DEFAULT_PATH)
        for key, row in ((data or {}).get("maps") or {}).items() if isinstance(data, dict) else ():
            if isinstance(row, dict) and row.get("updated_at") and str(key) in got.maps:
                got.updated_at[str(key)] = str(row["updated_at"])
        return got

    @classmethod
    def load(cls, path=None) -> "ExploredMap":
        """★読み込む。⚠ 無ければ空（★新しい冒険 / 見た升から後で埋めることはしない）。"""
        target = pathlib.Path(path) if path is not None else DEFAULT_PATH
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(target)
        return cls.from_dict(data, target)


__all__ = ["DEFAULT_PATH", "KIND", "ExploredMap", "visible_cells"]
