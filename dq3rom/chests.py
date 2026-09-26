"""DQ3 の宝箱 193 個を ROM から起こす（RX3-0008 → RX3-0009 で作り直し / 2026-08-24）。

## 仕組み（すべて日本版 ROM から。⚠ 表は同梱しない）

    個数表 d14  … (map 番号, 個数) の対 × 64。合計 193
    中身表 d15  … 193 個ぶん 1 バイト
        $FF        空
        $FE / $FD  ミミック系（★「敵」であって道具ではない）
        $8x / $7F  ゴールド (v & 0x7F) * 8
        それ以外   アイテム ID
    通し番号 = 表の並び順に、前の map までの個数を足したもの
    局所番号 = **復号済み地図を先頭から 1 バイトずつ**見て、宝箱タイルに当たった順
               （＝左→右・上→下）

## ★宝箱タイルの決め方（2026-08-24 に作り直した）

⚠ 以前はここが唯一の推定だった。「その tileset の宝箱がある map 全部で出現数が
個数表と一致するタイル ID」をデータから解いていた。★一意に決まらない tileset が
多く、扉には同じ手が使えなかった。

いまは `collision` が**日本版の生成ルーチンどおり**に collision[32] を組み立てる。
宝箱は実機と同じ判定（`collision & 0x0F == 3`）で拾う。

## ⚠ 座標が付かない宝箱が 5 件ある（黙って埋めない）

| map | 個数表 | 見つかった | 分かったこと |
| --- | --- | --- | --- |
| 117 | 4 | 2 | ★**2 マス × 2 状態**（bank12 `$9D93` が条件つきで通し番号を +2 する）。
  ⚠ 残り 2 件の中身が `$FF`（空）なのと辻褄が合う |
| 98 | 1 | 0 | ★**(13,6) のイベント**（bank0 `$AE3A`）。タイルではない |
| 23 | 1 | 0 | ⚠ 個別のコードは無い。★汎用のイベント表にあると思われる |
| 235 | 1 | 0 | ⚠ 同上 |

★つまり「タイルの宝箱」としては**全件正しく取れている**。
⚠ 個数表には**イベントで置かれるもの**も含まれており、それは地図には無い。
→ `RX3-0012` でイベント表を見つけたら、`unresolved` を潰す。
★2026-08-30: フラグを立てる側は確定した（`dq3rom/flags.py`）。⚠ 23 / 235 の
入口は未解決のまま。詳しくは `docs/design/dq3-findings.md`。

⚠ それまで**それらしいタイルを当てはめない**（当てはめると偶然でも緑になる）。

## 出典と確度

- 表の位置・符号・走査順 = **confirmed**（日本版 ROM と内部整合で確認）
- 宝箱タイル = collision[32] 由来。⚠ 上の 4 map だけ `unresolved`
"""

from __future__ import annotations

import collections
import dataclasses

from . import collision as col
from .profile import Identified

#: ⚠ 中身表の特別な値（アイテム ID ではない）
EMPTY = 0xFF
MIMIC = (0xFE, 0xFD)
GOLD_UNIT = 8


@dataclasses.dataclass(frozen=True)
class Reward:
    """宝箱の中身。★意味が未確定の値をアイテムに押し込まない（指示 §7）。"""

    type: str                    # "item" / "gold" / "mimic" / "empty"
    item_id: int | None = None
    amount: int | None = None
    raw: int = 0

    @classmethod
    def from_byte(cls, v: int) -> "Reward":
        if v == EMPTY:
            return cls(type="empty", raw=v)
        if v in MIMIC:
            return cls(type="mimic", raw=v)
        if v & 0x80 or v == 0x7F:
            return cls(type="gold", amount=(v & 0x7F) * GOLD_UNIT, raw=v)
        return cls(type="item", item_id=v, raw=v)

    def to_json(self) -> dict:
        out = {"type": self.type, "raw": f"0x{self.raw:02X}"}
        if self.item_id is not None:
            out["item_id"] = self.item_id
        if self.amount is not None:
            out["amount"] = self.amount
        return out


@dataclasses.dataclass(frozen=True)
class Chest:
    global_index: int            # 通し番号（中身表の添字）
    map_id: int
    local_index: int             # その map の中で何番目か（走査順）
    x: int
    y: int
    reward: Reward
    confidence: str              # confirmed / inferred

    @property
    def object_id(self) -> str:
        return f"chest_{self.map_id:04d}_{self.local_index:03d}"

    def to_json(self) -> dict:
        return {
            "object_id": self.object_id,
            "type": "chest",
            "map_id": self.map_id,
            "x": self.x,
            "y": self.y,
            "local_index": self.local_index,
            "global_index": self.global_index,
            "reward": self.reward.to_json(),
            "confidence": self.confidence,
            "source": "jp_rom",
        }


def read_tables(ident: Identified) -> tuple[list[tuple[int, int]], bytes]:
    """(map, 個数) の対と、中身表を ROM から読む。⚠ 内部整合を確かめる。"""
    prg = ident.rom.prg
    t = ident.table("chests_count")
    start = ident.table_prg("chests_count")
    pairs = [(prg[start + i * 2], prg[start + i * 2 + 1])
             for i in range(int(t["entries"]))]
    total = sum(n for _, n in pairs)
    c = ident.table("chests_content")
    cstart = ident.table_prg("chests_content")
    count = int(c["count"])
    if total != count:
        raise ValueError(f"個数の合計 {total} と中身表の長さ {count} が違います")
    return pairs, prg[cstart:cstart + count]


def build(ident: Identified, area_maps) -> list[Chest]:
    """宝箱を全件起こす。★タイルの判定は実機と同じ collision[32] を使う。"""
    pairs, contents = read_tables(ident)
    by_id = {m.entry.map_id: m for m in area_maps if m.ok}
    overrides = col.read_overrides(ident)

    out: list[Chest] = []
    running = 0
    for mid, n in pairs:
        m = by_id.get(mid)
        found: list[tuple[int, int]] = []
        if m is not None and n:
            table = col.table_for(ident, m.entry.tileset, mid, overrides)
            found = col.find(m.decoded, table, col.CHEST)
        for i in range(n):
            # ⚠ 足りないぶんは**埋めない**。それらしいタイルを当てると偶然でも緑になる
            x, y = found[i] if i < len(found) else (None, None)
            out.append(Chest(global_index=running + i, map_id=mid, local_index=i,
                             x=x, y=y, reward=Reward.from_byte(contents[running + i]),
                             confidence="confirmed" if x is not None else "unresolved"))
        running += n
    return out


def summary(chests: list[Chest]) -> dict:
    kinds = collections.Counter(c.reward.type for c in chests)
    conf = collections.Counter(c.confidence for c in chests)
    return {"total": len(chests), "reward_types": dict(kinds),
            "confidence": dict(conf),
            "without_xy": sum(1 for c in chests if c.x is None)}
