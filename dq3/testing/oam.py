"""OAM の写しから NPC 候補を起こす（RX3-0049 B-2 / B-3 / OBSERVER の後処理）。

## ★入力（`oam.jsonl` / `dq3_oam_observer.lua` が書く）

```json
{"frame":1234,"kind":1,"map_id":9,"px":8,"py":18,"n":16,
 "s":[[107,4,0,128],[107,5,0,136], ...]}      ⚠ s = [y, tile, attr, x]
```

## ★考え方（指示書 §8）

```text
player           ★画面の同じ場所に**ずっと**居るスプライト（DQ3 は主人公が画面中央で固定。
                   2026-09-02 実機: 先頭が (128,107)）
party_follower   ★主人公のすぐ後ろ（2 升以内）に**ほぼ常に**居て、一緒に動くもの（仲間 3 人）
NPC (individual) ★それ以外を、**升の連続性**で 1 体ずつに分けたもの
unknown          ⚠ 1 回しか見えなかったもの（★一時スプライト / 判定できない）
```

## ★★ 「絵」ではなく「場所の連続」で 1 体と数える（2026-09-02 の実測から）

⚠ 最初は tile の組で分けていましたが、★実機では:

```text
歩くと絵が変わる      t96-96-97-98 と t96-96-98-97 は**同じ兵士**の 2 コマ
同じ絵の NPC が 2 体   (8,16) と (5,4) の兵士が**1 つの候補**にまとまり「動いた」に見えた
仲間 3 人            ★主人公を追って画面を動くので 79 候補の大半を占めた
```

→ ★升の連続（1 升ずつしか動かない）で個体を分け、⚠ 絵はその個体の「見えた絵」として
持ちます。★離れた場所の同じ絵は**別の個体**になります（指示書 §24-3「同一外観 NPC」）。
⚠ 隣り合った 2 体は 1 体にまとまります（★ここでは分けない）。

## ★画面 → 地図の升

★主人公の升は分かっている（`px, py`）ので、⚠ scroll を使わずに

```text
npc_map_x = px + round((npc_screen_x - player_screen_x) / 16)
npc_map_y = py + round((npc_screen_y - player_screen_y) / 16)
```

★キャラクタは 16x16（8x8 のスプライト 2x2）。⚠ 左上のスプライトで代表させます。

## ⚠ 仮説として残すもの（追加方針 §4-1）

★アリアハン 1 町の観測では、tile id が `< 0x80` のものは全部パーティ、
`>= 0x80` が NPC でした。⚠ **1 町だけの相関**なので HYPOTHESIS。ここでは使いません
（★判定は場所の連続と主人公との距離だけで行い、tile は結果に添えるだけ）。
"""

from __future__ import annotations

import collections
import json
import pathlib

#: ★16x16 のキャラクタ 1 体 = 8x8 のスプライト 2x2
CELL = 16

#: ⚠ 「画面の同じ場所にずっと居る」と見る割合（★観測のうち）
PLAYER_FIXED_RATIO = 0.9

#: ★主人公（先頭）の画面位置（⚠ 2026-09-02 実機 / `dq3_oam_probe.lua`）
#:
#:   ⚠⚠ 主人公が**歩いていない**観測では、止まっている NPC も画面に固定されて
#:     見えます。★そのときは、この位置に居るものだけを player とみなします。
PLAYER_ANCHOR = (128, 107)

#: ★仲間: 主人公からこの升以内に居る観測が FOLLOWER_RATIO 以上、かつ動いている
#:
#:   ⚠ 4 人が縦に並ぶと、いちばん後ろは主人公から **3 升**（★2 だと取りこぼした / 実機）
FOLLOWER_DIST = 3
FOLLOWER_RATIO = 0.9
FOLLOWER_MIN_CELLS = 3

#: ★同じ個体とみなす升の距離（⚠ NPC は 1 升ずつ動く / 秒 4 回の観測なら 1 升以内）
LINK_DIST = 1

#: ★同じ個体とみなす観測の間隔（フレーム）。⚠ これより離れたら別の track
#:
#:   ⚠⚠ 時間を見ずに升だけで繋ぐと、★300 歩ぶんの NPC の足跡が**全部 1 つ**に
#:     まとまりました（実機: 1,066 観測 / 140 升 が 1 個体）。
LINK_FRAMES = 120


def load(path) -> list[dict]:
    """★`oam.jsonl` を読む（⚠ 壊れた行は飛ばす）。"""
    out = []
    path = pathlib.Path(path)
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and "s" in row:
                out.append(row)
    return out


def group_characters(sprites) -> list[dict]:
    """★8x8 のスプライトを 16x16 のキャラクタにまとめる。

    ★左上（x, y）に対して (x+8, y) / (x, y+8) / (x+8, y+8) があれば 1 体。
    ⚠ 揃わないものは 1 枚ずつ（★窓の飾りや矢印など）。
    """
    left = {(s[3], s[0]): list(s) for s in sprites}
    used = set()
    out = []
    for (x, y), s in sorted(left.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if (x, y) in used:
            continue
        parts = [(x, y)]
        for dx, dy in ((8, 0), (0, 8), (8, 8)):
            if (x + dx, y + dy) in left and (x + dx, y + dy) not in used:
                parts.append((x + dx, y + dy))
        if len(parts) == 4:
            tiles = tuple(left[p][1] for p in parts)
            attrs = tuple(left[p][2] & 0xE3 for p in parts)     # ⚠ 上位の flip/優先だけ
            out.append({"x": x, "y": y, "tiles": tiles, "attrs": attrs, "whole": True})
        else:
            out.append({"x": x, "y": y, "tiles": (s[1],), "attrs": (s[2] & 0xE3,),
                        "whole": False})
            parts = [(x, y)]
        used.update(parts)
    return out


def _key(ch) -> str:
    return "t" + "-".join("%02x" % t for t in ch["tiles"])


def _player_spots(samples, per_sample_chars):
    total = len(samples)
    fixed = collections.Counter()
    for chars in per_sample_chars:
        for ch in chars:
            fixed[(ch["x"], ch["y"])] += 1
    spots = {pos for pos, n in fixed.items() if n >= total * PLAYER_FIXED_RATIO}
    # ⚠⚠ 主人公が歩いていなければ「固定」だけでは NPC と区別できない
    moved = len({(r.get("px"), r.get("py")) for r in samples}) > 1
    if not moved:
        ax, ay = PLAYER_ANCHOR
        spots = {p for p in spots if p[0] == ax and (p[1] - ay) % CELL == 0 and p[1] >= ay}
    # ★先頭 = 決まった位置（PLAYER_ANCHOR）にいちばん近い固定点（⚠ 上から選ぶと仲間を取る）
    ax, ay = PLAYER_ANCHOR
    leader = min(spots, key=lambda p: abs(p[0] - ax) + abs(p[1] - ay)) if spots else None
    return spots, leader


#: ★画面から外れて戻った同じ絵の track を、同じ個体とみなす升の距離
MERGE_DIST = 2

#: ⚠ これより少ない観測は個体にしない（★仲間の絵が重なって出来た欠片が 2〜3 回で出る）
MIN_OBS = 5


def _appearance(t) -> str:
    """★絵の名前。⚠ 歩きの 2 コマは tile の**並び**だけが違うので、★並べ直して同じにする。"""
    key = collections.Counter(o[0] for o in t["rows"]).most_common(1)[0][0]
    return "-".join(sorted(key[1:].split("-")))


def _near(a, b, dist) -> bool:
    return any(abs(x1 - x2) <= dist and abs(y1 - y2) <= dist
               for (x1, y1) in a["cells"] for (x2, y2) in b["cells"])


def _merge_tracks(tracks):
    """★同じ地図・同じ絵・近い升の track をまとめる（⚠ 何度も回して収束させる）。"""
    tracks = [dict(t) for t in tracks]
    for t in tracks:
        t["_app"] = _appearance(t)
        t["cells"] = collections.Counter(t["cells"])
        t["rows"] = list(t["rows"])
    changed = True
    while changed:
        changed = False
        out = []
        while tracks:
            t = tracks.pop(0)
            keep = []
            for u in tracks:
                if u["map"] == t["map"] and u["_app"] == t["_app"] and _near(t, u, MERGE_DIST):
                    t["cells"].update(u["cells"])
                    t["rows"].extend(u["rows"])
                    changed = True
                else:
                    keep.append(u)
            tracks = keep
            out.append(t)
        tracks = out
    return tracks


class _Union:
    def __init__(self):
        self.parent = {}

    def find(self, a):
        self.parent.setdefault(a, a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def join(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def analyze(samples: list[dict]) -> dict:
    """★★ 観測から player / party_follower / NPC 個体 / unknown を起こす。"""
    total = len(samples)
    if total == 0:
        return {"samples": 0, "player": None, "party_followers": [],
                "npc_candidates": [], "unknown": [], "why": "⚠ 観測がありません"}

    per_sample_chars = [group_characters(row["s"]) for row in samples]
    player_spots, leader = _player_spots(samples, per_sample_chars)

    # ① 1 つ 1 つの観測を升へ（★player 以外）
    obs = []                       # (key, map_id, cx, cy, dist, frame, whole)
    for row, chars in zip(samples, per_sample_chars):
        px, py = row.get("px"), row.get("py")
        for ch in chars:
            if (ch["x"], ch["y"]) in player_spots:
                continue
            if leader is None or px is None or py is None:
                continue
            cx = px + round((ch["x"] - leader[0]) / CELL)
            cy = py + round((ch["y"] - leader[1]) / CELL)
            dist = max(abs(cx - px), abs(cy - py))
            obs.append((_key(ch), row.get("map_id"), cx, cy, dist, row.get("frame"), ch["whole"]))

    # ② 仲間: ★主人公の 2 升以内に**ほぼ常に**居て、一緒に動く絵
    by_key = collections.defaultdict(list)
    for o in obs:
        by_key[o[0]].append(o)
    followers = set()
    for key, rows in by_key.items():
        near = sum(1 for o in rows if o[4] <= FOLLOWER_DIST)
        cells = {(o[1], o[2], o[3]) for o in rows}
        if len(rows) >= 2 and near >= len(rows) * FOLLOWER_RATIO and len(cells) >= FOLLOWER_MIN_CELLS:
            followers.add(key)

    # ③ 残りを**升と時間の連続**で個体（track）に分ける（⚠ 絵は個体の属性）
    #
    #   ★観測を時間順に見て、⚠ 直前の観測から LINK_FRAMES 以内・LINK_DIST 以内の
    #   track に繋ぐ。無ければ新しい track。★2x2 に揃わない欠片（窓の飾りなど）は
    #   個体にしない（fragments に数える）。
    rest = sorted((o for o in obs if o[0] not in followers), key=lambda o: (o[5] or 0))
    tracks = []                    # {"map": m, "cells": Counter, "last": (x,y), "last_f": f, "rows": [...]}
    fragments = 0
    for o in rest:
        key, m, cx, cy, _dist, f, whole = o
        if not whole:
            fragments += 1
            continue
        best = None
        for t in tracks:
            if t["map"] != m or (f or 0) - (t["last_f"] or 0) > LINK_FRAMES:
                continue
            if abs(t["last"][0] - cx) <= LINK_DIST and abs(t["last"][1] - cy) <= LINK_DIST:
                if best is None or t["last_f"] > best["last_f"]:
                    best = t
        if best is None:
            best = {"map": m, "cells": collections.Counter(), "rows": [],
                    "last": (cx, cy), "last_f": f}
            tracks.append(best)
        best["cells"][(cx, cy)] += 1
        best["rows"].append(o)
        best["last"], best["last_f"] = (cx, cy), f

    # ★画面から外れて戻ると track が割れる（⚠ 実機: 353 観測で 48 個体に割れた）
    #   → ★**同じ絵**で、⚠ 居た升が MERGE_DIST 以内なら同じ個体とみなしてまとめる。
    #     ⚠ 同じ絵でも離れていれば別（★指示書 §24-3「同一外観 NPC」）。
    merged = _merge_tracks(tracks)

    candidates, unknown = [], []
    for t in merged:
        rows = t["rows"]
        tiles = collections.Counter(o[0] for o in rows)
        frames = [o[5] for o in rows if o[5] is not None]
        row = {
            "id": None,
            "map_id": t["map"],
            "observed": len(rows),
            "distinct_cells": len(t["cells"]),
            "cells": [{"x": x, "y": y, "seen": c} for (x, y), c in t["cells"].most_common(8)],
            "appearances": [k for k, _ in tiles.most_common(6)],
            "frames": [min(frames), max(frames)] if frames else None,
            "kind": ("stationary" if len(t["cells"]) == 1 else "moving") if len(rows) > 1 else "once",
        }
        (candidates if len(rows) >= MIN_OBS else unknown).append(row)
    candidates.sort(key=lambda r: -r["observed"])
    for i, c in enumerate(candidates):
        c["id"] = "npc-%03d" % i
    for i, c in enumerate(unknown):
        c["id"] = "once-%03d" % i

    return {
        "samples": total,
        "player": None if leader is None else {
            "screen": list(leader),
            "fixed_spots": sorted([list(p) for p in player_spots], key=lambda p: (p[1], p[0]))},
        "party_followers": sorted(followers),
        "npc_candidates": candidates,
        "unknown": unknown,
        "fragments": fragments,
    }


def write_report(samples_path, out_path) -> dict:
    """★`oam.jsonl` → `npc_candidates.json`。⚠ 無ければそう書く。"""
    got = analyze(load(samples_path))
    pathlib.Path(out_path).write_text(json.dumps(got, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    return got
