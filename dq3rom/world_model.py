"""解析結果を 1 つの World Model にまとめる（RX3-0008 / 2026-08-24）。

★ここが「一本のパイプライン」の合流点（指示 §1）。
  個々の Decoder は自分の形で出し、ここで**共通 ID で相互参照できる形**に直す。

⚠ 攻略の意味づけ（地名・重要度・推奨レベル）はここに入れない（指示 §19）。
⚠ 北米版由来の意味は `confidence: inferred` / `source: north_america_disassembly`。
"""

from __future__ import annotations

import collections
import dataclasses

from . import area_maps as am
from . import chests as chests_mod
from . import collision as collision_mod
from . import doors as doors_mod
from . import entrances as en
from . import flags as flags_mod
from . import search_spots as spots_mod
from .profile import Identified

SCHEMA_VERSION = 1
GAME = "dq3_famicom_jp"

#: ⚠ 北米版由来。日本版では ID の一致まで確認済みだが**名前は付けない**（指示 §12）
KEY_ITEM_IDS = (0x58, 0x59, 0x5A)


def _location_id(map_id: int) -> str:
    return f"loc_{map_id:04d}"


def _location(map_id: int, connections: list[dict] | None = None) -> dict:
    return {
        "location_id": _location_id(map_id),
        "name": None,                    # ⚠ 推測した地名を入れない
        "map_ids": [map_id],
        "type": "unknown",
        "connections": connections or [],
    }


def _connections(ident: Identified, ok: list) -> dict[int, list[dict]]:
    """入口表を `Connection` にする（RX3-0013 ② / 2026-08-31）。

    ★実機と同じ走査順で升を拾い、表の行と索引で突き合わせる。
    ⚠ 数が合わない map（★2026-08-31 時点で 12 件）は、対応が付いた
      ぶんだけ出し、余った升は `to` を `null` で残す（★黙って消さない）。
    """
    blocks = en.read_blocks(ident)
    arrivals = en.read_arrival_tables(ident)
    overrides = collision_mod.read_overrides(ident)
    out: dict[int, list[dict]] = {}
    for m in ok:
        map_id = m.entry.map_id
        table = collision_mod.table_for(ident, m.entry.tileset, map_id, overrides)
        rows = []
        for i, site in enumerate(en.sites(m.decoded, table, blocks[map_id])):
            e = site.entrance
            a = None if e is None else en.arrival_of(e, arrivals)
            rows.append({
                "connection_id": f"conn_{map_id:04d}_{i:02d}",
                "from_map_id": map_id,
                "x": site.x,
                "y": site.y,
                "to": None if e is None else _location_id(e.dest_map),
                "to_map_id": None if e is None else e.dest_map,
                "kind": None if e is None else e.kind,
                "kind_band": None if e is None else e.band,
                "arrival": None if a is None else {
                    "where": a.where,
                    "to_map_id": a.to_map,
                    "to_index": a.to_index,
                    "x": a.x,
                    "y": a.y,
                    "facing": a.facing,
                    "world": a.world,
                },
                "confidence": "confirmed" if e is not None else "unknown",
                "source": "jp_rom",
            })
        # ★地図の端から歩き出る行（RX3-0081 / 2026-09-17）。⚠ 升を持たない（x / y は None）
        edge = en.edge_exit(blocks[map_id], len(rows))
        if edge is not None:
            a = en.arrival_of(edge, arrivals)
            rows.append({
                "connection_id": f"conn_{map_id:04d}_edge",
                "from_map_id": map_id,
                "x": None,
                "y": None,
                "via": "edge",
                "to": _location_id(edge.dest_map),
                "to_map_id": edge.dest_map,
                "kind": edge.kind,
                "kind_band": edge.band,
                "arrival": {"where": a.where, "to_map_id": a.to_map, "to_index": a.to_index,
                            "x": a.x, "y": a.y, "facing": a.facing, "world": a.world},
                "confidence": "confirmed",
                "source": "jp_rom",
            })
        if rows:
            out[map_id] = rows
    return out


def _map(m) -> dict:
    d = m.decoded
    return {
        "map_id": m.entry.map_id,
        "width": d.width,
        "height": d.height,
        "tileset": m.entry.tileset,
        "bank": m.entry.bank,
        "background_tile": d.background,
        "second_pass": d.has_phase2,
        "confidence": "confirmed",
        "source": "jp_rom",
    }


def _items(objects: list[dict]) -> list[dict]:
    """World Model の中で参照されている item を集める。

    ★参照されている ID だけを出す（⚠ 全 ID の表を作るのは別の話）。
    """
    used = set()
    for o in objects:
        r = o.get("reward") or {}
        if r.get("type") == "item":
            used.add(r["item_id"])
        for req in o.get("requirements") or []:
            # ★1 個でも複数候補でも同じ形で拾う（⚠ どちらかが欠けても落ちないように）
            if req.get("item_id") is not None:
                used.add(req["item_id"])
            used.update(req.get("item_ids") or [])
    out = []
    for i in sorted(used):
        out.append({
            "item_id": i,
            "key": f"item_{i:02x}",
            "name": None,                # ⚠ 北米版の名前をコピーしない
            "category": "key" if i in KEY_ITEM_IDS else "unknown",
            "category_confidence": "inferred" if i in KEY_ITEM_IDS else "unresolved",
        })
    return out


def build(ident: Identified, doors: list | None = None) -> dict:
    """★宝箱と扉を 1 本のパイプラインで出す（指示 §1）。

    `doors` を渡すと差し替えられる。⚠ 既定では ROM から起こす。
    """
    area = am.decode_all(ident)
    ok = [m for m in area if m.ok]
    objects: list[dict] = [c.to_json() for c in chests_mod.build(ident, area)]
    if doors is None:
        doors = [d.to_json() for d in doors_mod.build(ident, area)]
    objects.extend(doors)
    conns = _connections(ident, ok)
    map_ids = sorted({m.entry.map_id for m in ok}
                     | {o["map_id"] for o in objects})
    return {
        "version": SCHEMA_VERSION,
        "game": GAME,
        "source": {
            "rom_payload_crc32": ident.rom.prg_crc32,
            "game_id": ident.game_id,
        },
        "locations": [_location(i, conns.get(i)) for i in map_ids],
        "maps": [_map(m) for m in ok],
        "objects": objects,
        "items": _items(objects),
        # ★2026-09-16: 「しらべる」の升表を載せた（RX3-0012 / bank12 $9ECF）。
        # ⚠ これは「イベントの全部」ではありません。★調べて何かが起きる升
        #   27 件だけです（会話・戦闘・宝箱は別の仕組み）。
        "events": spots_mod.to_json(ident),
        "flags": flags_mod.to_json(ident),
    }


# --- 整合性の検査（指示 §20）------------------------------------------------

def check(model: dict) -> list[str]:
    """⚠ 問題を**黙って直さず**列挙する。空なら整合。"""
    problems: list[str] = []
    objs = model["objects"]

    ids = collections.Counter(o["object_id"] for o in objs)
    dup = [k for k, n in ids.items() if n > 1]
    if dup:
        problems.append(f"object_id が重複: {dup[:5]}")

    map_ids = {m["map_id"] for m in model["maps"]}
    unknown = sorted({o["map_id"] for o in objs} - map_ids)
    if unknown:
        problems.append(f"maps に無い map_id を参照: {unknown[:5]}")

    by_location = {loc["location_id"]: loc for loc in model["locations"]}
    loc_ids = set(by_location)
    for loc in model["locations"]:
        for c in loc["connections"]:
            if c["to"] is not None and c["to"] not in loc_ids:
                problems.append(
                    f"{c['connection_id']}: locations に無い行き先 {c['to']}")
            if c["from_map_id"] != loc["map_ids"][0]:
                problems.append(f"{c['connection_id']}: from_map_id が場所と違う")
            a = c.get("arrival")
            if a is None:
                continue
            if a["where"] == "entrance":
                dest = by_location.get(_location_id(a["to_map_id"]))
                if dest is None:
                    problems.append(f"{c['connection_id']}: 行き先の場所が無い")
                elif a["to_index"] >= len(dest["connections"]):
                    problems.append(
                        f"{c['connection_id']}: 行き先に {a['to_index']} 番目の入口が無い")

    item_ids = {i["item_id"] for i in model["items"]}
    for o in objs:
        r = o.get("reward") or {}
        if r.get("type") == "item" and r["item_id"] not in item_ids:
            problems.append(f"{o['object_id']}: items に無い item_id {r['item_id']}")
        for req in o.get("requirements") or []:
            ids = list(req.get("item_ids") or [])
            if req.get("item_id") is not None:
                ids.append(req["item_id"])
            for i in ids:
                if i not in item_ids:
                    problems.append(f"{o['object_id']}: items に無い item_id {i}")

    # 宝箱まわり
    cs = [o for o in objs if o["type"] == "chest"]
    if len(cs) != 193:
        problems.append(f"宝箱が {len(cs)} 件（193 のはず）")
    gi = collections.Counter(o["global_index"] for o in cs)
    if any(n > 1 for n in gi.values()):
        problems.append("global_index が重複")
    if sorted(gi) != list(range(len(cs))):
        problems.append("global_index が 0..N-1 で連続していない")
    by_map: dict = collections.defaultdict(list)
    for o in cs:
        by_map[o["map_id"]].append(o["local_index"])
    for mid, locals_ in by_map.items():
        if sorted(locals_) != list(range(len(locals_))):
            problems.append(f"map {mid}: local_index が連続していない")
    pos = collections.Counter((o["map_id"], o["x"], o["y"]) for o in cs
                              if o["x"] is not None)
    dupe_pos = [k for k, n in pos.items() if n > 1]
    if dupe_pos:
        problems.append(f"同じ位置に複数の宝箱: {dupe_pos[:5]}")
    kinds = {o["reward"]["type"] for o in cs}
    unknown_kind = kinds - {"item", "gold", "mimic", "empty"}
    if unknown_kind:
        problems.append(f"知らない reward type: {unknown_kind}")
    # ⚠ 座標が無いこと自体は「未解決」として出してよい（`dq3rom/chests.py` の表）。
    #   ★ここで見張るのは**黙って落ちた**もの、つまり confirmed なのに座標が無い件。
    silent = [o["object_id"] for o in cs
              if o["x"] is None and o.get("confidence") != "unresolved"]
    if silent:
        problems.append(f"座標が無いのに未解決と書いていない宝箱 {len(silent)} 件: {silent[:3]}")

    # フラグまわり（RX3-0012）
    fl = model.get("flags") or []
    fids = collections.Counter(f["flag_id"] for f in fl)
    dupf = [k for k, n in fids.items() if n > 1]
    if dupf:
        problems.append(f"flag_id が重複: {dupf[:5]}")
    for f in fl:
        loc = flags_mod.address_of(f["number"])
        if f["address"] != f"0x{loc.address:04X}" or f["bit"] != loc.bit:
            problems.append(f"{f['flag_id']}: 在り処が式と合わない")
        # ⚠ ルーチン自身の退避先に当たる番号は、立てた瞬間に壊れる。
        #   ★黙って通さない（`dq3rom/flags.py` の「分かっていないこと」）。
        if loc.on_scratch:
            problems.append(f"{f['flag_id']}: 退避先 ${loc.address:04X} に当たる")
        if not f.get("set_by"):
            problems.append(f"{f['flag_id']}: set_by が空")

    # 扉まわり
    ds = [o for o in objs if o["type"] == "door"]
    for o in ds:
        if o.get("x") is None or o.get("y") is None:
            problems.append(f"{o['object_id']}: 座標が無い")
        if not o.get("requirements"):
            problems.append(f"{o['object_id']}: requirements が空")
    return problems


def summary(model: dict) -> dict:
    kinds = collections.Counter(o["type"] for o in model["objects"])
    conf = collections.Counter(o.get("confidence") for o in model["objects"])
    return {
        "locations": len(model["locations"]),
        "maps": len(model["maps"]),
        "objects": dict(kinds),
        "items": len(model["items"]),
        "flags": len(model.get("flags") or []),
        "events": len(model.get("events") or []),
        "confidence": dict(conf),
    }
