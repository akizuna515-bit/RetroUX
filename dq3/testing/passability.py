"""ROM から local map の通行可否を**推定**する（RX3-0051 / 指示書 §2 §5 §21）。

## ★既存解析の再利用（指示書 §3）

```text
dq3rom/area_maps.py    ★地図の展開（confirmed）
dq3rom/wall_join.py    ★壁の自動つなぎ（★map 9 で実機 $7400 と 676/676 一致 / RX3-0010）
dq3rom/collision.py    ★tile → collision バイト（表の位置は confirmed）
```

## ⚠ ここで使う仮説（RX3-0010 / HYPOTHESIS）

```text
collision bit7 (0x80) が立つ        → BLOCK     ⚠ bank14 $80B4 の AND #$80 から「そう見える」だけ
collision 0x05 / 0x06               → ★歩けるが HP が減る（2 / 15）。`damage()` で分かる
                                      ⚠⚠ 分類は PASS のまま（★経路は変えない / RX3-0262）
下位ニブル 1 / A / F                → SPECIAL   ★入口（階段・出口）。表の索引に使う（confirmed）
下位ニブル B / C / D                → DOOR      ⚠ 北米版由来で inferred
下位ニブル 3                        → CHEST     ★宝箱（confirmed / 歩ける）
それ以外で bit7 が無い              → PASS
```

⚠⚠ **この module は仮説を出すだけ**です。★実機の edge との突合は `edges.py`。
⚠ 製品の判断には使いません（指示書 §25）。

## ★成果物（指示書 §5）

```text
work/runtime/dq3-probe/passability/map_009.json   ★1 升 1 行（x / y / tile / collision / rom_class / confidence）
work/runtime/dq3-probe/passability/map_009.txt    ★Lua が読む 1 升 1 文字（P / B / S / D / C）
```
"""

from __future__ import annotations

import collections
import json
import pathlib

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = paths.lazy_work("runtime", "dq3-probe", "passability")

#: ★分類の語（⚠ 指示書 §2 の並び）
PASS, BLOCK, DOOR, CHEST, SPECIAL, UNKNOWN = "PASS", "BLOCK", "DOOR", "CHEST", "SPECIAL", "UNKNOWN"

#: ★Lua へ渡す 1 文字
LETTER = {PASS: "P", BLOCK: "B", DOOR: "D", CHEST: "C", SPECIAL: "S", UNKNOWN: "?"}

BLOCKED_BIT = 0x80
ENTRANCE_NIBBLES = (0x1, 0xA, 0xF)
DOOR_NIBBLES = (0xB, 0xC, 0xD)
CHEST_NIBBLE = 0x3

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def classify(col: int) -> tuple[str, str]:
    """★collision バイト → (分類, 確度)。⚠ 分類の根拠ごとに確度が違う。"""
    low = col & 0x0F
    if low in DOOR_NIBBLES:
        # ★2026-09-07（RX3-0014）: 日本版 ROM で確定した。
        #   ⚠ bank12 `$982E` が `CMP #$0D / #$0C / #$0B` で**このニブルを直接**見ている。
        return DOOR, "CONFIRMED"
    if col & BLOCKED_BIT:
        return BLOCK, "HYPOTHESIS"                # ⚠ bit7 の意味は未確認（RX3-0010）
    if low in ENTRANCE_NIBBLES:
        return SPECIAL, "CONFIRMED"               # ★入口として表を引く（confirmed）
    if low == CHEST_NIBBLE:
        return CHEST, "CONFIRMED"
    return PASS, "HYPOTHESIS"


class RomMap:
    """★ROM から起こした 1 つの local map（⚠ 壁つなぎ済み）。"""

    def __init__(self, map_id: int, tiles, table, tileset: int) -> None:
        self.map_id = map_id
        self.tiles = tiles                        # ★[y][x] の tile id（壁つなぎ済み）
        self.table = table                        # ★collision[32]
        self.tileset = tileset
        self.height = len(tiles)
        self.width = len(tiles[0]) if tiles else 0

    def tile(self, x, y):
        if 0 <= y < self.height and 0 <= x < self.width:
            return self.tiles[y][x]
        return None

    def collision(self, x, y):
        t = self.tile(x, y)
        return None if t is None else self.table[t & 0x1F]

    def damage(self, x, y):
        """★その升を踏むと減る HP（⚠ ダメージ床でなければ `None` / RX3-0262）。

        ⚠⚠ **`klass` は今までどおり `PASS` を返します**（★歩ける床であることは変わらない）。
        ★経路探索を変えるのは別の件（`RX3-0262` の「今回やらないこと」）。
        ⚠ ここはローカルの地図だけ。★世界地図は `damage_floors.world_damage_of`。
        """
        from dq3rom import damage_floors as _dmg

        return _dmg.damage_of(self.collision(x, y))

    def klass(self, x, y) -> str:
        """★その升の分類。⚠ 地図の外は SPECIAL（★出口）。"""
        c = self.collision(x, y)
        if c is None:
            return SPECIAL
        return classify(c)[0]

    def to_json(self) -> dict:
        cells = []
        for y in range(self.height):
            for x in range(self.width):
                t = self.tiles[y][x]
                col = self.table[t & 0x1F]
                k, conf = classify(col)
                row = {"x": x, "y": y, "tile": t, "collision": col,
                       "rom_class": k, "confidence": conf}
                # ★ダメージ床のときだけ足す（⚠ 普通の床の行は今までどおり / RX3-0262）
                dmg = self.damage(x, y)
                if dmg is not None:
                    row["damage"] = dmg
                cells.append(row)
        counts = collections.Counter(c["rom_class"] for c in cells)
        return {"map_id": self.map_id, "width": self.width, "height": self.height,
                "source": "rom", "tileset": self.tileset,
                "collision_table": self.table,
                "hypothesis": "collision bit7 = BLOCK（RX3-0010 / 未確認）",
                "counts": dict(counts), "cells": cells}

    def to_text(self) -> str:
        """★Lua が読む形: 1 行目 `W H`、以降 1 升 1 文字。"""
        lines = ["%d %d" % (self.width, self.height)]
        for y in range(self.height):
            lines.append("".join(LETTER[self.klass(x, y)] for x in range(self.width)))
        return "\n".join(lines) + "\n"

    def neighbourhood(self, x, y, r=1) -> list[list]:
        return [[self.tile(x + dx, y + dy) for dx in range(-r, r + 1)] for dy in range(-r, r + 1)]

    def door_nibble(self, x, y):
        """★その升が扉なら下位ニブル（`$B` / `$C` / `$D`）。⚠ 扉でなければ `None`。"""
        c = self.collision(x, y)
        if c is None:
            return None
        low = c & 0x0F
        return low if low in DOOR_NIBBLES else None

    def door_open(self, x, y, keys=()) -> bool:
        """★持っている鍵でその扉が開くか（RX3-0014 / RX3-0078）。

        ⚠ 扉でない升は `False`（★「通れる」とは言いません。★通行可否は `klass`）。
        """
        low = self.door_nibble(x, y)
        if low is None:
            return False
        from dq3rom import door_keys as _dk

        rank = _dk.party_rank(keys)
        return rank >= 0 and _dk.opens(low, rank)

    def bfs(self, start, goal, *, passable=(PASS, CHEST), keys=(), blocked=(),
            avoid_damage: bool = True, land: bool = False) -> list[str] | None:
        """★★ 最小の経路探索（指示書 §21 / BFS）。⚠ 見つからなければ None。

        ★`passable` の升だけを通る。⚠ SPECIAL（階段）は**通らない**（★踏むと地図が変わる）。

        ## ★`keys` を渡すと、開けられる扉を通ります（RX3-0078 / 2026-09-07）

          ⚠ 渡さなければ**今までどおり**扉は通りません（★既定の振る舞いを変えない）。
          ⚠⚠ 「開けられる」だけで、★**開ける操作は別**です（`nav_v0` の担当）。

        ## ★`blocked` の升は通りません（RX3-0176 / 2026-09-12）

          ★固定の NPC が立っている升。⚠ 地図の上では床なので、渡さないと**人の上を通る経路**を出します
          （★格闘場で受付の升を通り、実機では 1 歩目で受付にぶつかっていた）。
          ⚠ 目的地だけは `blocked` でも着けます（★呼び手は NPC の升を目的地にしないこと）。

        ## ★ダメージ床は、ほかに道があれば通りません（RX3-0277 / 2026-09-17）

          ★まずダメージ床（`damage()` が値を返す升）を通らずに探し、⚠ 道が無ければ今までどおり通る。
          ★ダメージ床の無い地図では 1 回目が今までの BFS と同じなので、**経路は変わりません**。
          ⚠ 避けられないときは最短を採り、減る HP の少ない道は選びません（★Lua の `nav_v0.bfs` と同じ規則）。
          ⚠ 目的地がダメージ床なら着けます。`avoid_damage=False` で今までの BFS。

        ## ⚠⚠ 目的地は**通行判定を外して**あります（★`land=True` で外さない / RX3-0299）

          ★NPC の升・カウンター越し・階段など「**向く**ための升」を狙えるようにするためです。
          ⚠ ところが「その升に**乗る**」つもりで呼ぶと、★実機では**壁に向かって歩きます**。

          ```text
          bfs((6,4) → (6,5))  = ['down']   ⚠ (6,5) は BLOCK（★map 109 レーベの家）
          ★実機: 3 回やり直して `path_blocked`（2026-09-19 に踏んだ）
          ```

          → ★乗るつもりなら `land=True`。⚠ **BLOCK の升なら None** を返します。
          ⚠ 既定は `False`（★今までの呼び手の振る舞いを変えない）。

          ★`SPECIAL`（階段・出入口）は**乗れます**（⚠ 乗るのが目的。`passable` には入っていない）。
          ⚠ `DOOR` は鍵を渡したときだけ（`door_open`）。
        """
        start, goal = tuple(start), tuple(goal)
        if land:
            kind = self.klass(*goal)
            if kind == BLOCK:
                return None
            if kind == DOOR and not (keys and self.door_open(*goal, keys=keys)):
                return None
        if start == goal:
            return []
        blocked = {tuple(c) for c in blocked}
        if avoid_damage:
            got = self._bfs_once(start, goal, passable, keys, blocked, avoid_damage=True)
            if got is not None:
                return got
        return self._bfs_once(start, goal, passable, keys, blocked, avoid_damage=False)

    def _bfs_once(self, start, goal, passable, keys, blocked, *, avoid_damage: bool) -> list[str] | None:
        prev = {start: None}
        queue = collections.deque([start])
        while queue:
            cur = queue.popleft()
            for name, (dx, dy) in DIRS.items():
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt in prev or self.tile(*nxt) is None:
                    continue
                if nxt != goal and nxt in blocked:
                    continue
                if avoid_damage and nxt != goal and self.damage(*nxt) is not None:
                    continue                                    # ★RX3-0277
                if nxt != goal and self.klass(*nxt) not in passable:
                    # ★鍵があれば、開けられる扉は通れる（RX3-0078）
                    if not (keys and self.door_open(*nxt, keys=keys)):
                        continue
                prev[nxt] = (cur, name)
                if nxt == goal:
                    path = []
                    while prev[nxt] is not None:
                        nxt, name = prev[nxt]
                        path.append(name)
                    return list(reversed(path))
                queue.append(nxt)
        return None

    def walk(self, start, path) -> list[tuple[int, int]]:
        """★経路をたどった升の並び（⚠ 実機で「期待する升」として使う）。"""
        x, y = start
        out = []
        for name in path:
            dx, dy = DIRS[name]
            x, y = x + dx, y + dy
            out.append((x, y))
        return out


def from_rom(map_id: int, rom=None) -> RomMap:
    """★ROM から map を起こす（⚠ 壁つなぎ済み）。★ROM が無ければ例外（呼ぶ側が扱う）。"""
    from dq3.knowledge import terrain as T
    from dq3rom import area_maps as am
    from dq3rom import collision, wall_join

    src = T.TerrainSource(rom) if rom else T.TerrainSource()
    ident = src._identify()
    if ident is None:
        raise RuntimeError("⚠ ROM を読めません: %s" % src.last_error)
    entry = next((e for e in am.read_directory(ident) if e.map_id == map_id), None)
    if entry is None or not entry.used:
        raise RuntimeError("⚠ map %d は表にありません" % map_id)
    got = am.decode_entry(ident, entry)
    if got.decoded is None:
        raise RuntimeError("⚠ map %d を展開できません: %s" % (map_id, got.error))
    table = collision.table_for(ident, entry.tileset, map_id)
    tiles = wall_join.apply(got.decoded, table, entry.tileset)
    return RomMap(map_id, tiles, table, entry.tileset)


def write(map_id: int, out_dir=None) -> dict:
    """★`map_NNN.json` / `map_NNN.txt` を書いて、要約を返す。"""
    out_dir = pathlib.Path(out_dir) if out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    m = from_rom(map_id)
    body = m.to_json()
    (out_dir / ("map_%03d.json" % map_id)).write_text(
        json.dumps(body, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / ("map_%03d.txt" % map_id)).write_text(m.to_text(), encoding="utf-8")
    return {"map_id": map_id, "width": m.width, "height": m.height, "counts": body["counts"],
            "json": str(out_dir / ("map_%03d.json" % map_id)),
            "txt": str(out_dir / ("map_%03d.txt" % map_id))}
