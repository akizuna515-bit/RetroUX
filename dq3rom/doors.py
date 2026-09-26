"""扉を全件起こし、必要な鍵を付ける（RX3-0009 / 2026-08-24）。

## ★扉の判定（日本版 ROM のコードで確認）

実機は目の前のマスを `AND #$1F` → `collision[タイルID]` → `AND #$0F` で見て、
**`$0B` / `$0C` / `$0D` の 3 種**を扉として扱う。⚠ 以前は北米版由来の推定
（`inferred`）だったが、日本版の次の 3 か所に同じ比較が実在する:

    bank12 $98A2  BD E0 6D / 29 0F / C9 0B / C9 0C / C9 0D   （開ける動作）
    bank14 $B813  BD E0 6D / 29 0F / C9 0B / C9 0C / C9 0D   （開けた扉の記録）
    bank12 $982B  BD E0 6D / 29 0F / C9 0D … C9 0C … C9 0B   （★鍵の判定）

## ★鍵の強さ（bank12 $982B。ここが要）

鍵を使うと `$B6` に **0 / 1 / 3** のいずれかが入る（bank12 $97E4/$97E8/$97EC）。
判定はこうなっている:

    扉 $0D:  LSR $B6 → 結果が 0 でなければ開く   → ★$B6 = 3 だけ
    扉 $0C:  LSR $B6 → はみ出したビットが 1 なら開く → ★$B6 = 1 か 3
    扉 $0B:  無条件で開く                          → ★どの鍵でも

つまり **鍵は 3 段の階層**で、強い鍵は弱い扉も開ける。

## ⚠ item ID との対応は inferred のまま

`$B6` を入れる 3 つの入口（`$97E4` / `$97E8` / `$97EC`）が **どの道具から呼ばれるか**は
追えていない。⚠ 「どの item ID がどれか」は北米版由来（`KEY_ITEM_IDS`）で、
**日本版未確認**。そのため `requirements` の確度は `inferred` にしてある。

> ⚠ 2026-08-24 訂正: ここには「分岐表（bank12 $8000 のワード表）の 13/14/15 番に
> 並ぶので、道具 ID も連番のはず」と書いていた。★ワード表の位置は事実だが、
> **その表を引く道具側の入口が見つからない**（固定バンクの `$C501` から引かれる
> 索引は `$FD3E` 由来で、13〜15 番には当たらない）。⚠ 「連番だから連番」は
> 根拠になっていなかったので取り下げる。

★確定させる道は 2 つ。

1. 実機で鍵 3 種 × 扉 3 種を試す（⚠ さいごのかぎまで進める必要がある）
2. 道具の使用処理から `$97E4` 系への入口を静的に追う（未着手）
"""

from __future__ import annotations

import collections
import dataclasses

from . import collision as col
from . import door_keys as _dk
from .profile import Identified

#: 扉の collision 下位ニブル → 必要な鍵の段（1 が最弱）。★日本版コードで確認
DOOR_RANK = {
    col.DOOR_ANY: 1,
    col.DOOR_MAGIC: 2,
    col.DOOR_FINAL: 3,
}

#: 鍵の道具 ID → 段（1 が最弱）。
#:
#: ## ★2026-09-07（RX3-0014）: `inferred` → **confirmed**
#:
#:   ⚠ ここは長いあいだ「北米版由来」でした。★日本版 ROM で辿り直して確定しました。
#:   ⚠⚠ **ID を 2 か所に書かない**ので、`dq3rom/door_keys.py` から引きます。
#:   ★あちらは実機の段位（`$B6` = 0 / 1 / 3）、⚠ こちらは並び（1 / 2 / 3）です。
#:   ★どちらで数えても「どの鍵がどの扉を開けるか」は同じで、
#:     ⚠ `tests/test_dq3_door_keys.py` が**突き合わせて**います。
KEY_RANK = {item_id: rank + 1 for rank, item_id
            in enumerate(sorted(_dk.KEY_ITEMS, key=lambda i: _dk.KEY_ITEMS[i]))}


@dataclasses.dataclass(frozen=True)
class Door:
    map_id: int
    index: int                   # その map の中で何番目か（走査順）
    x: int
    y: int
    nibble: int                  # $0B / $0C / $0D
    tile_id: int

    @property
    def kind(self) -> str:
        return col.DOOR_KINDS[self.nibble]

    @property
    def rank(self) -> int:
        return DOOR_RANK[self.nibble]

    @property
    def object_id(self) -> str:
        return f"door_{self.map_id:04d}_{self.index:03d}"

    def to_json(self) -> dict:
        keys = sorted(i for i, r in KEY_RANK.items() if r >= self.rank)
        return {
            "object_id": self.object_id,
            "type": "door",
            "map_id": self.map_id,
            "x": self.x,
            "y": self.y,
            "kind": self.kind,
            "tile_id": self.tile_id,
            "collision": f"0x{self.nibble:02X}",
            "min_key_rank": self.rank,
            "requirements": [{
                # ★強い鍵は弱い扉も開ける（bank12 $982B の LSR $B6 で確認）
                "type": "item",
                "item_ids": keys,
                "any_of": True,
                # ★2026-09-07（RX3-0014）: 日本版 ROM で確定（`dq3rom/door_keys.py`）
                "confidence": "confirmed",
            }],
            # 扉の位置と種別は ROM から確定。⚠ 鍵の ID だけが推定
            "confidence": "confirmed",
            "source": "jp_rom",
        }


def build(ident: Identified, area_maps) -> list[Door]:
    """全 map の扉を走査順（左→右・上→下）に拾う。"""
    overrides = col.read_overrides(ident)
    out: list[Door] = []
    for m in area_maps:
        if not m.ok:
            continue
        mid = m.entry.map_id
        table = col.table_for(ident, m.entry.tileset, mid, overrides)
        want = {i: (v & 0x0F) for i, v in enumerate(table) if (v & 0x0F) in DOOR_RANK}
        if not want:
            continue
        n = 0
        for y, row in enumerate(m.decoded.tiles):
            for x, t in enumerate(row):
                if t in want:
                    out.append(Door(map_id=mid, index=n, x=x, y=y,
                                    nibble=want[t], tile_id=t))
                    n += 1
    return out


def summary(doors: list[Door]) -> dict:
    kinds = collections.Counter(d.kind for d in doors)
    return {
        "total": len(doors),
        "kinds": dict(kinds),
        "maps": len({d.map_id for d in doors}),
    }
