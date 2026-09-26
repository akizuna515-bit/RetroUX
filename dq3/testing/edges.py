"""実機 walker の edge と ROM の予測を突き合わせる（RX3-0051 / 指示書 §6〜§13 §17）。

## ★edge とは

```text
(map_id, from_x, from_y, direction)  →  actual: PASS / BLOCK / SPECIAL
```

★1 升は 4 方向を持ち、⚠ 方向ごとに独立した検証対象（指示書 §17 edge coverage）。

## ⚠⚠ 「届かなかった」を壁にしない（指示書 §7）

```text
ok:true                         → PASS（★動いた＝届いた）
ok:false かつ delivered:true    → BLOCK
ok:false で delivered が無い/false → ⚠ 除外（★入力が届いた証拠がない）
map / kind が変わった            → SPECIAL（★通常床の判定から分ける / §8 §18）
```

## ★出すもの

```text
work/dq3-probe/passability/edges_009.jsonl        ★edge ごとに 1 行（予測 / 実測 / 一致）
work/dq3-probe/passability/mismatches_009.json    ⚠ 不一致（★周辺 3x3 / tile / collision / NPC）
work/dq3-probe/passability/report_009.json        ★混同行列 / 一致率 / coverage
```
"""

from __future__ import annotations

import collections
import json
import pathlib

from . import passability as P

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
EVIDENCE = paths.lazy_work("evidence")

#: ⚠ NPC が塞いでいたかを見る時間幅（フレーム）
NPC_WINDOW = 90


def load_rows(dirs=None, *, map_id: int, kind: int = 1) -> list[dict]:
    """★`run.jsonl` の「歩」の行を、run 名と seed を添えて集める。"""
    dirs = list(dirs) if dirs is not None else sorted(EVIDENCE.glob("2026*"))
    out = []
    for d in dirs:
        d = pathlib.Path(d)
        p = d / "run.jsonl"
        if not p.exists():
            continue
        seed = None
        meta = d / "metadata.json"
        if meta.exists():
            try:
                seed = json.loads(meta.read_text(encoding="utf-8")).get("seed")
            except ValueError:
                pass
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "step" not in r:
                continue
            # ★from の地図で判定する（⚠ 動いた先で map が変わることがある）
            #   ⚠⚠ 2026-09-02: 「動いた先が別の地図なら通す」にしていて、map 109 の集計に
            #     map 9 の 7,000 歩が全部 SPECIAL として混ざった。★from の地図が分かる行だけ。
            if "from_map_id" in r:
                from_kind, from_map = r.get("from_kind"), r.get("from_map_id")
            elif not r.get("ok"):
                from_kind, from_map = r.get("kind"), r.get("map_id")     # ★動いていないので同じ地図
            else:
                dx = abs((r.get("x") or 0) - (r.get("from_x") or 0))
                dy = abs((r.get("y") or 0) - (r.get("from_y") or 0))
                if dx + dy == 1:
                    from_kind, from_map = r.get("kind"), r.get("map_id")  # ★1 升だけ動いた = 同じ地図
                else:
                    continue                                               # ⚠ 飛んだ。元の地図が分からない
            if from_kind != kind or from_map != map_id:
                continue
            r["_run"], r["_seed"] = d.name, seed
            out.append(r)
    return out


#: ★対照を探す範囲（⚠ 同じ升から動けた行が、この行数以内にあれば「入力は生きていた」）
CONTROL_LOOKAHEAD = 3


def actual_of(row: dict, map_id: int, next_rows=None) -> str | None:
    """★1 歩の実測。⚠ 判定できなければ None（除外）。

    ## ⚠⚠ 壁の証拠は「対照」（★`dq3_passability_test.lua` の考え方 / RX3-0010）

      ★DQ3 は**壁にぶつかった押しも `$16` に出ない**ので、`delivered` では
      「届かなかった」と「壁」を分けられない（2026-09-02 実機）。
      → ⚠ 動けなかった 1 歩を BLOCK と数えるのは、**同じ升からの次の 1 歩で動けた**とき
        （★その瞬間、入力は生きていた）だけ。⚠ さらに `input_dead` の時間は除外。
    """
    fx, fy = row.get("from_x"), row.get("from_y")
    if fx is None or fy is None or row.get("input") not in P.DIRS:
        return None
    if row.get("ok"):
        if row.get("map_id") != map_id or row.get("kind") != 1:
            return P.SPECIAL
        dx, dy = P.DIRS[row["input"]]
        if (row["x"], row["y"]) == (fx + dx, fy + dy):
            return P.PASS
        return P.SPECIAL                          # ⚠ 座標が飛んだ（warp）
    if row.get("input_dead"):
        return None                               # ⚠ 入力が死んでいる時間
    if isinstance(next_rows, dict):
        next_rows = [next_rows]
    for nr in (next_rows or [])[:CONTROL_LOOKAHEAD]:
        if nr.get("_run") != row.get("_run"):
            break
        if (nr.get("from_x"), nr.get("from_y")) != (fx, fy):
            break                                 # ⚠ 別の升へ移った
        if nr.get("ok"):
            return P.BLOCK                        # ★対照: 同じ升から動けた（入力は生きていた）
    return None                                   # ⚠ 対照が無い


def predict(rom: P.RomMap, fx, fy, direction) -> str:
    dx, dy = P.DIRS[direction]
    k = rom.klass(fx + dx, fy + dy)
    if k == P.DOOR:
        return P.BLOCK                            # ⚠ 扉は開けるまで壁（★別に数える）
    if k == P.CHEST:
        return P.PASS
    return k


def _npc_at(oam_rows, cell, frame) -> bool | None:
    """★その升に NPC 候補が居たか（⚠ OAM が無ければ None）。"""
    if not oam_rows or frame is None:
        return None
    from . import oam as O

    ax, ay = O.PLAYER_ANCHOR
    for s in oam_rows:
        f = s.get("frame")
        if f is None or abs(f - frame) > NPC_WINDOW:
            continue
        px, py = s.get("px"), s.get("py")
        if px is None:
            continue
        for ch in O.group_characters(s["s"]):
            if (ch["x"], ch["y"]) == (ax, ay):
                continue
            cx = px + round((ch["x"] - ax) / O.CELL)
            cy = py + round((ch["y"] - ay) / O.CELL)
            if (cx, cy) == tuple(cell):
                return True
    return False


def compare(rows: list[dict], rom: P.RomMap, *, oam_by_run: dict | None = None) -> dict:
    """★★ 予測と実測を突き合わせる。"""
    edges = []
    matrix = collections.Counter()
    mismatches = []
    seen_edges = set()
    per_edge = collections.defaultdict(list)
    quarantine = {}                    # run → あと何歩は見ないか
    for i, r in enumerate(rows):
        actual = actual_of(r, rom.map_id, rows[i + 1:i + 1 + CONTROL_LOOKAHEAD])
        if actual is None:
            continue
        # ⚠⚠ warp の直後 2 歩は見ない（RX3-0051）。
        #   ★座標は先に変わり `$8B`（map 番号）は数フレーム遅れる。⚠ 階段で map 109 に
        #   移った直後の数歩が「map 9 の (6,4)」として記録され、9 件の不一致が全部これだった。
        left = quarantine.get(r["_run"], 0)
        if actual == P.SPECIAL:
            quarantine[r["_run"]] = 2
        elif left > 0:
            quarantine[r["_run"]] = left - 1
            continue
        fx, fy, d = r["from_x"], r["from_y"], r["input"]
        pred = predict(rom, fx, fy, d)
        dx, dy = P.DIRS[d]
        tx, ty = fx + dx, fy + dy
        # ★★ warp は「その升に着いた」ことで起きる（RX3-0049 で実測）。
        #   ⚠ 階段へ動けた 1 歩は PASS と記録され、地図が変わるのは**次の 1 歩**の記録に出る。
        #   → ★階段（SPECIAL）へ着いた PASS は「着けた」= 一致、
        #     ★階段の升から始まる SPECIAL は「遅れて出た warp」= 一致 とみなす。
        if pred == P.SPECIAL and actual == P.PASS:
            actual = P.SPECIAL
        if actual == P.SPECIAL and rom.klass(fx, fy) == P.SPECIAL:
            pred = P.SPECIAL
        key = (fx, fy, d)
        seen_edges.add(key)
        per_edge[key].append(actual)
        match = pred == actual
        matrix[(pred, actual)] += 1
        row = {"map_id": rom.map_id, "x": fx, "y": fy, "direction": d,
               "to_x": tx, "to_y": ty, "rom_tile": rom.tile(tx, ty),
               "rom_collision": rom.collision(tx, ty),
               "rom_prediction": pred, "runtime_result": actual, "match": match,
               "run": r["_run"], "seed": r["_seed"], "step": r.get("step"),
               "frame": r.get("frame"), "delivered": r.get("delivered")}
        edges.append(row)
        if not match:
            npc = None
            if oam_by_run and r["_run"] in oam_by_run:
                npc = _npc_at(oam_by_run[r["_run"]], (tx, ty), r.get("frame"))
            mismatches.append(dict(row, neighbourhood=rom.neighbourhood(tx, ty),
                                   npc_at_target=npc))
    total = sum(matrix.values())
    agree = sum(v for (p, a), v in matrix.items() if p == a)
    # ★方向つきの coverage（指示書 §17）
    all_edges = rom.width * rom.height * 4
    report = {
        "map_id": rom.map_id, "steps_used": total,
        "edges_verified": len(seen_edges), "edges_total": all_edges,
        "edge_coverage": round(len(seen_edges) / all_edges, 4) if all_edges else None,
        "matrix": {"%s/%s" % k: v for k, v in sorted(matrix.items())},
        "agreement": round(agree / total, 4) if total else None,
        "mismatches": len(mismatches),
        "by_prediction": {
            k: {"total": sum(v for (p, a), v in matrix.items() if p == k),
                "match": matrix.get((k, k), 0)}
            for k in (P.PASS, P.BLOCK, P.SPECIAL)},
    }
    # ⚠ 同じ edge で結果がぶれたもの（★NPC が塞いだ疑い）
    flaky = {k: collections.Counter(v) for k, v in per_edge.items() if len(set(v)) > 1}
    report["flaky_edges"] = [{"x": k[0], "y": k[1], "direction": k[2], "results": dict(c)}
                             for k, c in flaky.items()]
    return {"edges": edges, "mismatches": mismatches, "report": report}


def load_oam(dirs) -> dict:
    from . import oam as O

    out = {}
    for d in dirs:
        d = pathlib.Path(d)
        if (d / "oam.jsonl").exists():
            out[d.name] = O.load(d / "oam.jsonl")
    return out


def run(map_id: int, dirs=None, out_dir=None) -> dict:
    """★★ 既存 Evidence を全部なめて、報告を書く。"""
    out_dir = pathlib.Path(out_dir) if out_dir else P.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    dirs = list(dirs) if dirs is not None else sorted(EVIDENCE.glob("2026*"))
    rom = P.from_rom(map_id)
    rows = load_rows(dirs, map_id=map_id)
    got = compare(rows, rom, oam_by_run=load_oam(dirs))
    with (out_dir / ("edges_%03d.jsonl" % map_id)).open("w", encoding="utf-8") as fh:
        for e in got["edges"]:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    (out_dir / ("mismatches_%03d.json" % map_id)).write_text(
        json.dumps(got["mismatches"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out_dir / ("report_%03d.json" % map_id)).write_text(
        json.dumps(got["report"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return got
