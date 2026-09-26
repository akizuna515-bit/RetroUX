"""固定 NPC への Navigation（RX3-0052 §5 §8 §9 §12 §21）。

## ★責務

```text
npcs_from_ram      RAM $0110 の NPC 表（4 バイト刻み: x, y, b2, b3）を読む（§3 / OBSERVED。⚠ 旧 $0114 は 1 体落としていた）
adjacent_goals     NPC の 4 隣接から、ROM PASS / SPECIAL でない / 他の NPC が居ない升を選ぶ（§8）
                   ★カウンター越し（HYPOTHESIS）も候補にする
plan               既存 BFS（passability.RomMap.bfs）で最短の隣接升と向きを出す（§9）
conversation_open  state.json の `screen`（窓のタイル）から会話の窓が開いたかを見る（§12）
write_navigation   navigation.json（§21）
```

## ★★ NPC 表は RAM `$0114` にあった（2026-09-02 / fc0 = アリアハン）

```text
#00 $0114  08 10 05 92   x=8  y=16  b2=05  b3=92   ★入口の兵士（OAM の (8,16) と一致）
#04 $0124  05 04 05 82   x=5  y=4   b2=05  b3=82   ★奥の兵士（同じ絵 = b2 も同じ 05）
…10 体、以降 FF
```

★b2 は絵（同じ兵士 2 体が 05）。⚠ b3 はセーブごとに違う（92 / 82 / 9E）ので**実行時の状態**
（向き・歩きの勘定の候補）。⚠ ROM に同じ並びは無い（x,y / y,x / 間隔 0〜8 / 16bit で探した）。
→ ★座標は **RAM の表 = OBSERVED**、ROM の元は**見つかっていない**。

## ⚠ カウンター（HYPOTHESIS）

★兵士 3 体の目の前（(8,17) / (5,5) / (16,19)）は tile 14 = collision 0x80 で**壁の形の bit が 0**。
⚠ DQ ではカウンター越しに話せるので、★「collision 0x80 かつ (col & 0x70) == 0 の升」を挟んだ
2 升先も候補にする。⚠ 実機で会話が始まれば OBSERVED。

⚠ passability は OBSERVED（RX3-0051）。★ここでの利用は **probe_only**（指示書 §23）。
"""

from __future__ import annotations

import json
import pathlib

from . import passability as P

#: ★隣接升 (gx, gy) に立って NPC (nx, ny) を見る向き（★差 = NPC - 自分）
FACING = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}

#: ★RAM の NPC 表（⚠ OBSERVED / fc0・fc5・fc8 の 3 セーブで同じ位置に同じ x,y）
#: ⚠⚠ 2026-09-02 訂正（RX3-0053）: ここは `0x0114` でした。★loader（$F369: `LDX #$10; STA $0100,X`）は
#:   slot 4 = **$0110** から書きます。$0100〜$010F は仲間 4 人。⚠ $0114 から読むと NPC #0（アリアハンの (11,2)）を落とします。
NPC_TABLE = 0x0110
NPC_STRIDE = 4
NPC_MAX = 16


def npcs_from_ram(ram: bytes) -> list[dict]:
    """★RAM の NPC 表を読む。⚠ FF FF で終わり。"""
    out = []
    for i in range(NPC_MAX):
        o = NPC_TABLE + i * NPC_STRIDE
        x, y, b2, b3 = ram[o], ram[o + 1], ram[o + 2], ram[o + 3]
        if x == 0xFF and y == 0xFF:
            break
        out.append({"npc_id": i, "x": x, "y": y, "sprite_id": b2, "state": b3,
                    "sprite_status": "HYPOTHESIS", "movement": None,
                    "movement_status": "UNKNOWN", "talk_id": None})
    return out


def is_counter(rom: P.RomMap, x, y) -> bool:
    """★カウンター（HYPOTHESIS）: 通れないが壁の形を持たない升。"""
    c = rom.collision(x, y)
    return c is not None and bool(c & 0x80) and (c & 0x70) == 0 and (c & 0x0F) == 0


def adjacent_goals(rom: P.RomMap, npc, others=()) -> list[dict]:
    """★NPC の 4 隣接（+ カウンター越しの 2 升先）のうち、立てる升。⚠ NPC 自身の升は goal にしない。"""
    nx, ny = npc
    others = {tuple(o) for o in others}
    out = []
    for (dx, dy), face in FACING.items():
        # ★隣接
        gx, gy = nx - dx, ny - dy                   # ⚠ 自分は NPC の反対側に立つ
        if rom.tile(gx, gy) is not None and rom.klass(gx, gy) in (P.PASS, P.CHEST) \
                and (gx, gy) not in others:
            out.append({"goal": [gx, gy], "final_face": face, "class": rom.klass(gx, gy),
                        "via": "adjacent"})
            continue
        # ★カウンター越し（⚠ HYPOTHESIS）
        if is_counter(rom, gx, gy):
            fx, fy = nx - 2 * dx, ny - 2 * dy
            if rom.tile(fx, fy) is not None and rom.klass(fx, fy) in (P.PASS, P.CHEST) \
                    and (fx, fy) not in others:
                out.append({"goal": [fx, fy], "final_face": face, "class": rom.klass(fx, fy),
                            "via": "counter", "counter": [gx, gy], "confidence": "HYPOTHESIS"})
    return out


def plan(rom: P.RomMap, start, npc, others=(), *, keys=(), avoid=()) -> dict | None:
    """★★ 最短で着ける隣接升と経路。⚠ 無ければ None。★隣接を優先し、無ければカウンター越し。

    ★`keys` を渡すと、⚠ **開けられる扉を通る経路**も探します（RX3-0078）。
    ⚠ 渡さなければ今までどおりです（★既定の振る舞いを変えない）。

    ★`avoid`（固定の NPC の升など）は**通りません**（RX3-0176）。
    ⚠ `others` は**着く升**から外すだけで、通る升からは外しません（★通さないのは `avoid`）。
    """
    start = tuple(start)
    best = None
    for cand in adjacent_goals(rom, npc, others):
        goal = tuple(cand["goal"])
        path = rom.bfs(start, goal, keys=keys, blocked=avoid)
        if path is None:
            continue
        score = (0 if cand["via"] == "adjacent" else 1, len(path))
        if best is None or score < best["_score"]:
            best = dict(cand, path=path, cells=[list(c) for c in rom.walk(start, path)],
                        npc=[int(npc[0]), int(npc[1])], start=list(start), _score=score)
    if best is not None:
        best.pop("_score", None)
        # ★経路の途中にある扉（⚠ 「開ける操作が要る」ことを呼び手へ伝える）
        best["doors"] = [list(c) for c in best["cells"] if rom.door_nibble(*c) is not None]
        # ★★ この経路で減る HP（RX3-0277 / 2026-09-18 依頼者「回り込まないが、毒沼超えしか道はない」）。
        #   ⚠ `RomMap.bfs` は**回り込める道があれば避ける**ので、ここが 0 でないのは
        #     「避けられなかった」ということ。★呼び手はそれを人に見せる（黙って踏まない）。
        hurt = [(c, rom.damage(*c)) for c in best["cells"] if rom.damage(*c) is not None]
        best["damage"] = sum(v for _c, v in hurt)
        best["damage_cells"] = [list(c) for c, _v in hurt]
    return best


def screen_tiles(state: dict):
    """★state.json の `screen`（16 進）→ タイルの列。⚠ 無ければ None。"""
    raw = state.get("screen")
    if not raw:
        return None
    try:
        from dq3.knowledge.enemies_seen import unhex

        return list(unhex(raw))
    except Exception:                                            # noqa: BLE001
        return None


def conversation_open(state: dict) -> dict:
    """★会話の窓が開いているか（★既存の `conversation_on_screen` を使う / §12）。

    ⚠ 「A を押した」ではなく「窓が出て文がある」で判定する。
    """
    tiles = screen_tiles(state)
    if tiles is None:
        return {"open": False, "why": "⚠ 窓のタイルが state.json に無い"}
    try:
        from dq3.knowledge.conversation import conversation_on_screen

        got = conversation_on_screen(tiles)
    except Exception as err:                                     # noqa: BLE001
        return {"open": False, "why": "⚠ 読めません: %s" % err}
    if got is None:
        return {"open": False, "why": "⚠ 会話の窓ではない（戦闘・メニュー・無し）"}
    text, digest = got
    return {"open": True, "text": text[:80], "digest": digest}


def fixed_npcs(npc_json) -> list[dict]:
    """★OAM の NPC 候補（`npc_candidates.json`）から、固定らしい個体とその最頻の升。"""
    path = pathlib.Path(npc_json) if npc_json else None
    if path is None or not path.exists():
        return []
    body = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for c in body.get("npc_candidates", []):
        if not c.get("cells"):
            continue
        top = c["cells"][0]
        share = top["seen"] / max(1, c["observed"])
        out.append({"id": c["id"], "x": top["x"], "y": top["y"], "observed": c["observed"],
                    "top_share": round(share, 2), "map_id": c.get("map_id"),
                    "kind": "fixed" if share >= 0.6 else "moving",
                    "status": "OBSERVED"})
    return out


def npc_ledger(map_id: int, ram: bytes, oam_json=None) -> dict:
    """★NPC 台帳（§5）: RAM の表 + OAM の観測（固定 / 移動）を結ぶ。"""
    ram_npcs = npcs_from_ram(ram)
    seen = {(o["x"], o["y"]): o for o in fixed_npcs(oam_json)} if oam_json else {}
    for n in ram_npcs:
        hit = seen.get((n["x"], n["y"]))
        if hit is None:
            # ⚠ 動く NPC は最頻の升が RAM の初期位置とずれる → 近い升を探す
            hit = next((o for (x, y), o in seen.items() if abs(x - n["x"]) <= 1 and abs(y - n["y"]) <= 1), None)
        if hit is not None:
            n["movement"] = hit["kind"]
            n["movement_status"] = "OBSERVED"
            n["oam_id"] = hit["id"]
            n["oam_observed"] = hit["observed"]
    return {"map_id": map_id, "source": "RAM $0114（4 バイト刻み） + OAM",
            "position_status": "OBSERVED", "rom_source": "⚠ 見つかっていない（x,y / y,x / 間隔 0〜8 / 16bit で PRG を探した）",
            "npcs": ram_npcs}


def write_navigation(root, body: dict) -> pathlib.Path:
    p = pathlib.Path(root) / "navigation.json"
    p.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
