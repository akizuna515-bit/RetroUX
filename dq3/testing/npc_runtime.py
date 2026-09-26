"""実機で写した NPC の表（$0100〜）と OAM を突き合わせる（RX3-0053 / OBSERVER 側の解析）。

## ★入力（`dq3_npc_observer.lua` が書く）

```text
npc_track.jsonl   {"frame","kind","map_id","px","py","phase","time","tbl":"<$0100-$0177 の hex>","s":[[y,tile,attr,x],...]}
npc_pc.json       {"write_hook","read_hook","writes":{"F3F8":{"n","first","last","offs":{"0":n},"phases":{"load":n}}}, "reads":{...}, "raw_writes":[...]}
```

## ★出す（指示書 §12）

```text
map_NNN_initial.json      読み込み直後の表（★ROM の展開と並べる）
map_NNN_tracking.jsonl    sample × NPC: x / y / state / 見た目 slot / OAM に居るか / 画面内のはずか
npc_write_pc.json         書き込み PC を「読み込み時」「ゲームループ」に分ける（★offs で x/y/見た目/状態）
ram_oam_correlation.json  H1 / H3 / H4 / H5 の判定材料（⚠ 判定は数で示す。CONFIRMED は人が付ける）
```

## ⚠ OAM は検証にだけ使う

★台帳の主情報は RAM の表と ROM の記録。OAM は「画面内なら描かれる」の確かめだけ（指示書 §9）。
"""
from __future__ import annotations

import collections
import json
import pathlib

from dq3.testing import npc_rom as R
from dq3.testing import oam as O

#: ★主人公が描かれる画面座標（`dq3/testing/oam.py` / RX3-0049 で実測）
PLAYER_ANCHOR = (128, 107)
CELL = 16
#: ⚠ 画面内とみなす範囲（★スプライトの左上が入るか）
SCREEN_W, SCREEN_H = 256, 240
#: ⚠ 歩いている途中は升の途中に居る → 1 升ぶんまで許す
TOLERANCE = 12

PARTY_SLOTS = 4


def load_track(path) -> list[dict]:
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
            if isinstance(row, dict) and "tbl" in row:
                out.append(row)
    return out


def slots_of(row: dict) -> list[dict]:
    """★120 バイトの hex を slot（4 バイト）に。⚠ NPC は slot 4 から、x = y = FF で終わり。"""
    tbl = bytes.fromhex(row["tbl"])
    out = []
    for i in range(len(tbl) // 4):
        x, y, b2, b3 = tbl[i * 4:i * 4 + 4]
        if i >= PARTY_SLOTS and x == 0xFF and y == 0xFF:
            break
        out.append({"slot": i, "x": x, "y": y, "appearance_slot": b2, "state": b3,
                    "party": i < PARTY_SLOTS})
    return out


def expected_screen(npc_xy, player_xy) -> tuple[int, int]:
    """★NPC の升 → 画面上の左上（⚠ 主人公の升との差から）。"""
    return (PLAYER_ANCHOR[0] + (npc_xy[0] - player_xy[0]) * CELL,
            PLAYER_ANCHOR[1] + (npc_xy[1] - player_xy[1]) * CELL)


def expected_visible(sx: int, sy: int) -> bool:
    return -CELL < sx < SCREEN_W and -CELL < sy < SCREEN_H - 8


def oam_has_character_at(groups, sx: int, sy: int, tol: int = TOLERANCE) -> bool:
    for g in groups:
        if g.get("whole") and abs(g["x"] - sx) <= tol and abs(g["y"] - sy) <= tol:
            return True
    return False


def track(rows: list[dict]) -> list[dict]:
    """★sample × NPC の行。"""
    out = []
    for row in rows:
        groups = O.group_characters(row.get("s") or [])
        player = (row["px"], row["py"])
        for s in slots_of(row):
            if s["party"]:
                continue
            sx, sy = expected_screen((s["x"], s["y"]), player)
            vis = expected_visible(sx, sy)
            out.append({"frame": row["frame"], "phase": row.get("phase"), "slot": s["slot"],
                        "x": s["x"], "y": s["y"], "state": s["state"],
                        "appearance_slot": s["appearance_slot"], "px": player[0], "py": player[1],
                        "expected_visible": vis,
                        "oam_present": oam_has_character_at(groups, sx, sy) if vis else False})
    return out


def correlation(track_rows: list[dict], rom_npcs: list[dict] | None = None) -> dict:
    """★H1 / H3 / H4 / H5 の材料を数で。"""
    by_slot: dict[int, list[dict]] = collections.defaultdict(list)
    for r in track_rows:
        by_slot[r["slot"]].append(r)
    slots = []
    for slot in sorted(by_slot):
        rs = by_slot[slot]
        positions = {(r["x"], r["y"]) for r in rs}
        vis = [r for r in rs if r["expected_visible"]]
        off = [r for r in rs if not r["expected_visible"]]
        drawn_when_visible = sum(1 for r in vis if r["oam_present"])
        fixed_bit = all(r["state"] & 0x80 for r in rs)
        rom = None
        if rom_npcs is not None and 0 <= slot - R.NPC_FIRST_SLOT < len(rom_npcs):
            rom = rom_npcs[slot - R.NPC_FIRST_SLOT]
        slots.append({
            "slot": slot, "samples": len(rs), "distinct_positions": len(positions),
            "moved": len(positions) > 1, "state_bit7_always": fixed_bit,
            "rom_movement": (None if rom is None else ("fixed" if rom["fixed"] else "moving")),
            "samples_expected_visible": len(vis), "drawn_when_visible": drawn_when_visible,
            "samples_offscreen": len(off),
            "present_in_ram_while_offscreen": len(off),   # ★表に居た（★行がある = 居る）
            "first": {"x": rs[0]["x"], "y": rs[0]["y"], "state": rs[0]["state"]},
            "last": {"x": rs[-1]["x"], "y": rs[-1]["y"], "state": rs[-1]["state"]},
        })
    n_fixed = [s for s in slots if s["state_bit7_always"]]
    n_moving = [s for s in slots if not s["state_bit7_always"]]
    return {
        "npc_slots": len(slots),
        "H1_all_npcs_in_ram_every_sample": all(s["samples"] == slots[0]["samples"] for s in slots) if slots else None,
        "H3_moving_changed_position": sum(1 for s in n_moving if s["moved"]),
        "H3_moving_total": len(n_moving),
        "H4_fixed_never_moved": sum(1 for s in n_fixed if not s["moved"]),
        "H4_fixed_total": len(n_fixed),
        "H5_offscreen_samples": sum(s["samples_offscreen"] for s in slots),
        "H5_visible_samples": sum(s["samples_expected_visible"] for s in slots),
        "H5_drawn_when_visible": sum(s["drawn_when_visible"] for s in slots),
        "rom_vs_state_bit7_agree": sum(1 for s in slots if s["rom_movement"] is not None
                                       and (s["rom_movement"] == "fixed") == s["state_bit7_always"]),
        "slots": slots,
    }


def classify_pcs(pc_json: dict) -> dict:
    """★書き込み PC を読み込み時 / ゲームループ に分ける（⚠ phase は probe が付けた印）。"""
    def split(tbl):
        rows = []
        for pc, e in sorted(tbl.items(), key=lambda kv: -kv[1]["n"]):
            phases = e.get("phases") or {}
            load = phases.get("load", 0)
            play = sum(v for k, v in phases.items() if k != "load")
            offs = {int(k): v for k, v in (e.get("offs") or {}).items()}
            what = "+".join(n for k, n in ((0, "x"), (1, "y"), (2, "app"), (3, "state")) if offs.get(k))
            rows.append({"pc": "$" + pc, "n": e["n"], "load": load, "play": play, "bytes": what,
                         "kind": "load" if play == 0 else ("play" if load == 0 else "both"),
                         "first": e.get("first"), "last": e.get("last")})
        return rows
    return {"write_hook": pc_json.get("write_hook"), "read_hook": pc_json.get("read_hook"),
            "n_writes": pc_json.get("n_writes"), "n_reads": pc_json.get("n_reads"),
            "writes": split(pc_json.get("writes") or {}), "reads": split(pc_json.get("reads") or {})}


def analyze(run_dir, map_id: int, out_dir, rom=None) -> dict:
    run_dir, out_dir = pathlib.Path(run_dir), pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = load_track(run_dir / "npc_track.jsonl")
    night = bool(rows) and R.is_night(rows[-1].get("time", 0))
    rom_npcs = R.npcs_for_map(map_id, night, rom) if rows else []
    # ★読み込み直後 = 最初に NPC が表に居る sample
    initial = next((r for r in rows if len(slots_of(r)) > PARTY_SLOTS), None)
    init_slots = [s for s in slots_of(initial)] if initial else []
    npc_slots = [dict(s, facing=R.FACING[s["state"] & 3], fixed=bool(s["state"] & 0x80))
                 for s in init_slots if not s["party"]]
    cmp = R.compare(rom_npcs, npc_slots) if initial else None
    (out_dir / ("map_%03d_initial.json" % map_id)).write_text(json.dumps({
        "map_id": map_id, "frame": initial["frame"] if initial else None, "night": night,
        "slots": init_slots, "rom": rom_npcs, "compare": cmp}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    tr = track(rows)
    with (out_dir / ("map_%03d_tracking.jsonl" % map_id)).open("w", encoding="utf-8") as fh:
        for r in tr:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    corr = correlation(tr, rom_npcs)
    (out_dir / "ram_oam_correlation.json").write_text(json.dumps(corr, ensure_ascii=False, indent=2) + "\n",
                                                        encoding="utf-8")
    pcs = None
    pc_path = run_dir / "npc_pc.json"
    if pc_path.exists():
        pcs = classify_pcs(json.loads(pc_path.read_text(encoding="utf-8")))
        (out_dir / "npc_write_pc.json").write_text(json.dumps(pcs, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    return {"samples": len(rows), "npcs": len(npc_slots), "compare": cmp, "correlation": corr, "pcs": pcs}


def summarize(result: dict) -> str:
    c = result.get("correlation") or {}
    cmp = result.get("compare") or {}
    lines = ["★NPC の表 × OAM: sample %d / NPC %d" % (result.get("samples", 0), result.get("npcs", 0))]
    if cmp:
        lines.append("  ROM の展開と読み込み直後の表: %d/%d OK（座標一致 %d / 見た目 %d / 固定ビット %d）" % (
            cmp["ok"], cmp["rom_count"], cmp["same_position"], cmp["same_appearance"], cmp["same_fixed"]))
    if c:
        lines.append("  H1 毎 sample に全 NPC が表に居る: %s" % c.get("H1_all_npcs_in_ram_every_sample"))
        lines.append("  H3 動く NPC のうち座標が変わった: %d/%d" % (c.get("H3_moving_changed_position", 0), c.get("H3_moving_total", 0)))
        lines.append("  H4 固定 NPC のうち 1 度も動かない: %d/%d" % (c.get("H4_fixed_never_moved", 0), c.get("H4_fixed_total", 0)))
        lines.append("  H5 画面内のはずの sample で OAM に居た: %d/%d / 画面外の sample（表には居る）: %d" % (
            c.get("H5_drawn_when_visible", 0), c.get("H5_visible_samples", 0), c.get("H5_offscreen_samples", 0)))
    pcs = result.get("pcs") or {}
    if pcs:
        lines.append("  書き込み PC: %d 種（hook write=%s read=%s）" % (len(pcs.get("writes", [])), pcs.get("write_hook"), pcs.get("read_hook")))
        for w in pcs.get("writes", [])[:12]:
            lines.append("    %s x%d load %d / play %d [%s] %s" % (w["pc"], w["n"], w["load"], w["play"], w["bytes"], w["kind"]))
    return "\n".join(lines)
