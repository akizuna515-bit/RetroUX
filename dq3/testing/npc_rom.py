"""ROM の NPC 記録を読む（RX3-0053 / probe_only）。

## ★どこにあるか（2026-09-02 / 固定バンクの逆アセンブルから）

```text
$F326  NPC の読み込み: JSR $F433（表の場所を決める / RAM の表を空にする）→ JSR $F369（展開）
$F439  bank 9 の $BC80 で $3E = map 番号（⚠ 物語の進みで別の表に差し替える map がある）
       資源 #$FF（bank = $FC70 の下位ニブル = 13 / 索引 = $FD3E[$FF] = 1 → bank13:$8002 のポインタ）
       → その先の 2 バイトが NPC データの先頭（bank 13 $819A）
$F45A  先頭から「0 で終わる表」を $3E 個飛ばす → その map の表
$F369  表の記録を 1 つずつ RAM の表（$0110〜 / 4 バイト刻み）へ展開
```

## ★記録の文法（⚠ 可変長 / flags = 1 バイト目）

```text
長さ      $F4B1[flags & 7] = 05 06 06 07 07 08 08 09
時間帯    $3C = 0x10（昼: $06DF < 0x78）/ 0x08（夜）。(flags & $3C) == 0 の記録は**その時間帯に居ない**
単純形    [0]flags [1]見た目(上6bit) | 向き(下2bit) [2]?（★talk id 候補 / loader は読まない）[3]x [4]y
          x, y の bit7 = 動かない（昼は x の bit7 / 夜は y の bit7 → RAM の状態バイトの bit7）
拡張形    夜で flags & 0x10 も立っているとき: 見た目は [$F4B9[flags&1]] = [1] か [5]、
          x は [$F4BB[flags&7]] = 03 03 03 03 05 06 06 07、y はその次。★動かないは [4] の bit7
```

## ⚠ 確度

★文法は逆アセンブル（CONFIRMED に近い）。★展開の結果はアリアハン 3 セーブで **11/11** 一致（OBSERVED）。
⚠ `[2]` を talk id と呼ぶのは **HYPOTHESIS**（★loader は読まない = 別のコードが読む、まで）。
⚠ 製品の判断には使いません（probe_only）。
"""
from __future__ import annotations

import json
import pathlib

#: ★資源 #$FF（NPC データの先頭ポインタ）の解き方（固定バンク $C501）
FIXED_BANK = 15
RES_BANK_NIBBLES = 0xFC70          # ★$FC70[Y >> 1]（Y が奇数なら下位ニブル）= bank
RES_INDEX = 0xFD3E                 # ★$FD3E[Y] = ポインタ表の索引
NPC_RESOURCE = 0xFF

#: ★記録の長さ / 見た目の位置 / x の位置（$F4B1 / $F4B9 / $F4BB）
REC_LEN = (5, 6, 6, 7, 7, 8, 8, 9)
APP_OFFSET = (1, 5)
X_OFFSET = (3, 3, 3, 3, 5, 6, 6, 7)

#: ★時間帯（$06DF）
TIME_ADDR = 0x06DF
NIGHT_FROM = 0x78
MASK_DAY, MASK_NIGHT = 0x10, 0x08

#: ★RAM の表（⚠ $0100〜$010F は仲間 4 人。NPC は slot 4 = $0110 から）
OBJ_TABLE = 0x0100
OBJ_STRIDE = 4
NPC_FIRST_SLOT = 4
NPC_TABLE = OBJ_TABLE + NPC_FIRST_SLOT * OBJ_STRIDE     # $0110
NPC_MAX = 25                                              # ★$0110〜$0173（$0174 は終端）
APPEARANCE_SLOTS = 0x6ABE                                 # ★WRAM: slot → 見た目 id

FACING = ("up", "right", "down", "left")


def _prg(rom):
    if rom is not None:
        return rom
    from dq3.knowledge import terrain as T

    return T.TerrainSource()._identify().rom.prg


def _cpu_to_prg(bank: int, cpu: int) -> int:
    base = 0xC000 if bank == FIXED_BANK else 0x8000
    return bank * 0x4000 + (cpu - base)


def data_start(prg) -> tuple[int, int]:
    """★NPC データの先頭 (bank, cpu アドレス)。⚠ 固定バンクの表から解く（$C501）。"""
    y = NPC_RESOURCE
    nibbles = prg[_cpu_to_prg(FIXED_BANK, RES_BANK_NIBBLES + (y >> 1))]
    bank = nibbles & 0x0F if (y & 1) else nibbles >> 4
    index = prg[_cpu_to_prg(FIXED_BANK, RES_INDEX + y)]
    p = prg[bank * 0x4000 + 2 * index] | (prg[bank * 0x4000 + 2 * index + 1] << 8)
    start = prg[_cpu_to_prg(bank, p)] | (prg[_cpu_to_prg(bank, p + 1)] << 8)
    return bank, start


#: ★表の数。⚠ ROM に「表がいくつあるか」は書かれていない。
#:
#: ⚠⚠ 2026-09-06 訂正（RX3-0088）: ここは長らく **208** で、注記には
#:   「表 207（$9442）の後は 208〜249 が空」「$BC80 が使う差し替え番号の最大は $CE = 206」
#:   と書いてありました。⚠ **どちらも事実と違います**。
#:
#: ```text
#: 208〜249 に中身のある表が 15 本
#:   216 225 233 235 236 237 238 239 243 244 245 246 247 248 249
#: ★下の MAP_VARIANTS_60CD_BIT5 自身が 0xF3〜0xF9（= 243〜249）を差し替え先に挙げている
#: ```
#:
#: ★境界が 250 である根拠は、数ではなく**記録の flags の散らばり**です。
#:
#: ```text
#: 表   0〜249  flags & 0xF8 が決まった 9〜13 種類しか出ない（★同じ文法）
#: 表 250〜     32 種類すべてが均等に出る（= ★別のデータ）
#: ⚠ 実際 300 まで読むと、46 軒しか無いのに店番号 48 / 49 が出る（= 壊れて読んでいる）
#: ```
LIST_COUNT = 250


def parse_lists(prg, limit: int = LIST_COUNT) -> list[list[dict]]:
    """★「0 で終わる表」を先頭から順に読む。★表 i = map i（⚠ 物語で差し替える map は $BC80）。"""
    bank, a = data_start(prg)
    lists: list[list[dict]] = []
    end = 0xC000
    while a < end and len(lists) < limit:
        recs = []
        while a < end:
            flags = prg[_cpu_to_prg(bank, a)]
            if flags == 0:
                a += 1
                break
            n = REC_LEN[flags & 7]
            raw = bytes(prg[_cpu_to_prg(bank, a + k)] for k in range(n))
            recs.append({"addr": a, "raw": raw, "flags": flags})
            a += n
        lists.append(recs)
    return lists


def is_night(time_byte: int) -> bool:
    return time_byte >= NIGHT_FROM


def expand(recs, night: bool) -> list[dict]:
    """★loader（$F369）と同じ順で、その時間帯に居る NPC を RAM の表の並びに。"""
    mask = MASK_NIGHT if night else MASK_DAY
    out = []
    for rec in recs:
        r, flags = rec["raw"], rec["flags"]
        if not (flags & mask):
            continue
        extended = night and bool(flags & MASK_DAY)
        if not extended:
            app, x, y = r[1], r[3], r[4]
            fixed_bit = (y if night else x) & 0x80
        else:
            app = r[APP_OFFSET[flags & 1]]
            xo = X_OFFSET[flags & 7]
            x, y = r[xo], r[xo + 1]
            fixed_bit = r[4] & 0x80
        out.append({
            "addr": rec["addr"], "raw": r.hex(" "), "flags": flags,
            "x": x & 0x7F, "y": y & 0x7F,
            "appearance_id": app & 0xFC, "facing": FACING[app & 3],
            "fixed": bool(fixed_bit), "extended": extended,
            "talk_id_candidate": r[2],
            "talk_id": talk_id(r, night),
        })
    return out


#: ★夜の会話 id の位置（$F4C3[flags & 3]）
NIGHT_TALK_OFFSET = (2, 2, 5, 6)


def talk_id(r: bytes, night: bool) -> int:
    """★会話 / event の id（10 bit）。★固定バンク `$F507` の写し（2026-09-02 逆アセンブル）。

    ```text
    昼      上位 2 bit = flags の bit7,6 / 下位 = [2]
    夜      flags & 0x02 なら 上位 = (flags & 0x20) >> 5 / 下位 = [$F4C3[flags & 3]]（★昼と別の相手になる）
            ⚠ flags & 0x02 が無ければ昼と同じ
    ```
    """
    flags = r[0]
    hi = (flags & 0xC0) >> 6
    lo_at = 2
    if night and (flags & 0x02):
        hi = (flags & 0x20) >> 5
        lo_at = NIGHT_TALK_OFFSET[flags & 3]
    return (hi << 8) | r[lo_at]


def npcs_for_map(map_id: int, night: bool = False, rom=None) -> list[dict]:
    lists = parse_lists(_prg(rom))
    if map_id >= len(lists):
        return []
    return expand(lists[map_id], night)


def ram_slots(ram: bytes, wram: bytes | None = None) -> list[dict]:
    """★RAM の表（$0110〜）を読む。⚠ x = y = FF で終わり。"""
    out = []
    for i in range(NPC_MAX):
        o = NPC_TABLE + i * OBJ_STRIDE
        x, y, b2, b3 = ram[o], ram[o + 1], ram[o + 2], ram[o + 3]
        if x == 0xFF and y == 0xFF:
            break
        row = {"slot": NPC_FIRST_SLOT + i, "x": x, "y": y, "appearance_slot": b2, "state": b3,
               "facing": FACING[b3 & 3], "fixed": bool(b3 & 0x80)}
        if wram is not None and b2 < 0x10:
            row["appearance_id"] = wram[APPEARANCE_SLOTS - 0x6000 + b2]
        out.append(row)
    return out


def compare(rom_npcs: list[dict], slots: list[dict]) -> dict:
    """★ROM の展開と RAM の表を並べて突き合わせる（⚠ 動く NPC は座標が違ってよい）。"""
    rows = []
    n_ok = n_pos = n_app = n_face = n_fixed = 0
    for i, r in enumerate(rom_npcs):
        s = slots[i] if i < len(slots) else None
        row = {"npc_id": i, "rom": r, "ram": s}
        if s is not None:
            pos = (r["x"], r["y"]) == (s["x"], s["y"])
            app = s.get("appearance_id") is None or s["appearance_id"] == r["appearance_id"]
            fixed = r["fixed"] == s["fixed"]
            face = (not r["fixed"]) or r["facing"] == s["facing"]
            row.update(pos=pos, appearance=app, fixed=fixed, facing=face,
                       verdict="OK" if (pos or not r["fixed"]) and app and fixed else "MISMATCH")
            n_pos += pos
            n_app += app
            n_fixed += fixed
            n_face += face
            n_ok += row["verdict"] == "OK"
        rows.append(row)
    return {"rom_count": len(rom_npcs), "ram_count": len(slots), "ok": n_ok,
            "same_position": n_pos, "same_appearance": n_app, "same_fixed": n_fixed,
            "same_facing_of_fixed": n_face, "rows": rows}


def ledger(map_id: int, night: bool = False, rom=None) -> dict:
    """★NPC 台帳の原型（指示書 §12）。⚠ movement は ROM の bit7（OBSERVED）/ talk_id は候補（HYPOTHESIS）。"""
    npcs = npcs_for_map(map_id, night, rom)
    return {
        "map_id": map_id, "time": "night" if night else "day", "npc_count": len(npcs),
        "source": "ROM bank 13（$F369 の文法）/ probe_only",
        # ★talk_id: $F507 の写し + 実機 2 体（宿屋 0x00B / 道具屋 0x1FF）で一致 → OBSERVED（2026-09-02）
        "status": {"position": "OBSERVED", "appearance_id": "OBSERVED", "movement": "OBSERVED",
                   "facing": "OBSERVED", "talk_id": "OBSERVED", "night": "HYPOTHESIS"},
        "npcs": [{
            "npc_id": i, "slot": NPC_FIRST_SLOT + i, "rom_addr": "$%04X" % n["addr"], "record": n["raw"],
            "initial_x": n["x"], "initial_y": n["y"], "appearance_id": n["appearance_id"],
            "facing": n["facing"], "movement": "fixed" if n["fixed"] else "moving",
            "talk_id": n["talk_id"], "talk_id_candidate": n["talk_id_candidate"],
        } for i, n in enumerate(npcs)],
    }


# ---------------------------------------------------------------------------
# ★全 map（RX3-0054）
# ---------------------------------------------------------------------------

def record_individuals(recs) -> list[dict]:
    """★ROM 記録 = 個体。★npc_id は map の表の中の記録の順（0 から / 昼夜で同じ）。

    ⚠ RAM の slot は「その時間帯に居る記録だけ」を詰めた並びなので、昼と夜で同じ個体でも slot は違い得る。
    """
    out = []
    for i, rec in enumerate(recs):
        flags = rec["flags"]
        day = expand([rec], False)
        night = expand([rec], True)
        out.append({
            "npc_id": i, "rom_addr": "0x%04X" % rec["addr"], "record": rec["raw"].hex(" "),
            "flags": flags, "format": flags & 7, "length": REC_LEN[flags & 7],
            "present": {"day": bool(day), "night": bool(night)},
            "day": _individual_view(day[0]) if day else None,
            "night": _individual_view(night[0]) if night else None,
        })
    return out


def _individual_view(n: dict) -> dict:
    return {"initial_x": n["x"], "initial_y": n["y"], "appearance_id": n["appearance_id"],
            "initial_facing": n["facing"], "movement": "fixed" if n["fixed"] else "random",
            "talk_id": n["talk_id"], "extended": n["extended"]}


def map_ledger(map_id: int, recs, night: bool) -> dict:
    """★指示書 §1 の形（1 map / 1 時間帯）。★npc_id は記録の順（安定）/ slot は展開の順（runtime）。"""
    key = "night" if night else "day"
    npcs = []
    slot = NPC_FIRST_SLOT
    for ind in record_individuals(recs):
        v = ind[key]
        if v is None:
            continue
        npcs.append(dict(npc_id=ind["npc_id"], rom_addr=ind["rom_addr"], record=ind["record"],
                         slot=slot, format=ind["format"], **v))
        slot += 1
    return {"map_id": map_id, "time": key, "npc_count": len(npcs), "npcs": npcs}


def all_maps(night: bool = False, rom=None) -> dict:
    """★全 map の台帳（昼か夜）。★表 i = map i（⚠ `$BC80` の差し替えは `variants()`）。"""
    lists = parse_lists(_prg(rom))
    maps = [map_ledger(i, l, night) for i, l in enumerate(lists) if l]
    maps = [m for m in maps if m["npc_count"]]
    return {"time": "night" if night else "day", "source": "ROM bank 13 $819A〜（$F369 の文法）/ probe_only",
            "npc_id": "map_id + ROM 記録の順（昼夜で同じ記録 = 同じ個体）",
            "status": {"position": "OBSERVED", "appearance_id": "OBSERVED", "movement": "OBSERVED",
                       "talk_id": "OBSERVED", "night": "HYPOTHESIS（実機は RX3-0054 §5 を参照）"},
            "map_count": len(maps), "npc_total": sum(m["npc_count"] for m in maps), "maps": maps}


#: ★`$BC80`（bank 9）の差し替え（★2026-09-02 逆アセンブル。★条件の意味は HYPOTHESIS）
#:   ⚠ 「flag bit7」は `LDX $60xx; BPL` の形（負なら差し替え）。「and」は `LDA; AND #n; BEQ` の形。
MAP_VARIANTS = [
    {"map_id": 0x0E, "variants": [
        {"npc_table_id": 0xC2, "condition_raw": "$60BA bit7 = 1", "priority": 1},
        {"npc_table_id": 0xC0, "condition_raw": "$60BA bit7 = 0 and ($60CA & $04) != 0", "priority": 2}]},
    {"map_id": 0x7D, "variants": [{"npc_table_id": 0xC1, "condition_raw": "$60BA bit7 = 1"}]},
    {"map_id": 0x23, "variants": [{"npc_table_id": 0x95, "condition_raw": "($60CA & $20) != 0"}]},
    {"map_id": 0x47, "variants": [{"npc_table_id": 0xAC, "condition_raw": "$60CB bit7 = 1"}]},
    {"map_id": 0x6B, "variants": [{"npc_table_id": 0xAB, "condition_raw": "$60C5 bit7 = 1"}]},
    {"map_id": 0x17, "variants": [{"npc_table_id": 0xB7, "condition_raw": "$60B9 bit7 = 1"}]},
    {"map_id": 0x8A, "variants": [{"npc_table_id": 0xB8, "condition_raw": "$60B9 bit7 = 1"}]},
    {"map_id": 0x72, "variants": [{"npc_table_id": 0xCD,
                                   "condition_raw": "$60CD != 0 and $60B7 bit7 = 0 and ($60CD & 1) = 1"}]},
    {"map_id": 0x75, "variants": [{"npc_table_id": 0xCE, "condition_raw": "$60CD = $FF and $60B7 bit7 = 0"}]},
    {"map_id": 0x06, "variants": [{"npc_table_id": 0xF3,
                                   "condition_raw": "world ($2A,$2B) = ($D7,$9A) and ($60CD & $20) = 0 and ($60CA & $08) != 0"}]},
]
#: ★$60B7 bit6 が立つと、表 $BD66 の map → $BD74 の表に差し替え（★6 組）
MAP_VARIANTS_60B7_BIT6 = {0x01: 0xAD, 0x4A: 0xAE, 0x4C: 0xAF, 0x4D: 0xB0, 0x49: 0xB1, 0x48: 0xB3}
#: ★world ($2A,$2B) = ($D7,$9A) かつ ($60CD & $20) != 0 のとき、表 $BD66+7 の map → $BD74+7（★6 組）
MAP_VARIANTS_60CD_BIT5 = {0x61: 0xF4, 0x62: 0xF5, 0x5D: 0xF6, 0x60: 0xF7, 0x5F: 0xF8, 0x06: 0xF9}


def variants() -> dict:
    """★指示書 §4 の中間データ。★`$BC80` を逆アセンブルして写した（条件の意味は HYPOTHESIS）。"""
    by_map: dict[int, list[dict]] = {}
    for m in MAP_VARIANTS:
        by_map.setdefault(m["map_id"], []).extend(dict(v) for v in m["variants"])
    for src, dst in MAP_VARIANTS_60B7_BIT6.items():
        by_map.setdefault(src, []).append({"npc_table_id": dst, "condition_raw": "$60B7 bit6 = 1（表 $BD66/$BD74）"})
    for src, dst in MAP_VARIANTS_60CD_BIT5.items():
        by_map.setdefault(src, []).append({"npc_table_id": dst,
                                           "condition_raw": "world ($2A,$2B) = ($D7,$9A) and ($60CD & $20) != 0（表 $BD66+7/$BD74+7）"})
    maps = []
    for map_id in sorted(by_map):
        vs = [dict(v, condition_status="HYPOTHESIS", npc_table_id_hex="0x%02X" % v["npc_table_id"]) for v in by_map[map_id]]
        maps.append({"map_id": map_id, "default_table_id": map_id, "variants": vs, "status": "UNKNOWN_CONDITION_MEANING"})
    return {"source": "bank 9 $BC80-$BD65 の逆アセンブル（2026-09-02）", "status": "code CONFIRMED / condition meaning HYPOTHESIS",
            "note": "★条件が立たなければ表 = map_id。⚠ 差し替え先の表番号（0xAB〜0xF9）は map 番号としては使われない範囲",
            "map_count": len(maps), "maps": maps}


def effective_table_id(map_id: int) -> tuple[int, str]:
    """★製品側の安全な扱い（指示書 §9）: 差し替えのある map は status=UNKNOWN。"""
    for m in variants()["maps"]:
        if m["map_id"] == map_id:
            return map_id, "UNKNOWN"
    return map_id, "DEFAULT"


def map_sizes(rom=None) -> dict[int, tuple[int, int]]:
    """★map_id → (W, H)（★`dq3rom.area_maps` から。⚠ 展開できない map は入らない）。"""
    from dq3.knowledge import terrain as T
    from dq3rom import area_maps as am

    src = T.TerrainSource(rom) if rom else T.TerrainSource()
    ident = src._identify()
    out = {}
    for e in am.read_directory(ident):
        if not e.used:
            continue
        got = am.decode_entry(ident, e)
        if got.decoded is not None:
            out[e.map_id] = (got.decoded.width, got.decoded.height)
    return out


def validate(rom=None, sizes: dict | None = None) -> dict:
    """★指示書 §6: 記録の形式ごとの実例と、展開した座標が map の中に収まるか。"""
    import collections

    lists = parse_lists(_prg(rom))
    sizes = map_sizes(rom) if sizes is None else sizes
    fmt_example: dict[int, dict] = {}
    fmt_count = collections.Counter()
    n_rec = 0
    in_bounds = {"day": 0, "night": 0}
    out_of_bounds = []
    no_size = set()
    movement = {"day": collections.Counter(), "night": collections.Counter()}
    for map_id, recs in enumerate(lists):
        for rec in recs:
            n_rec += 1
            f = rec["flags"] & 7
            fmt_count[f] += 1
            if f not in fmt_example:
                ind = record_individuals([rec])[0]
                fmt_example[f] = dict(map_id=map_id, **ind)
        for key, night in (("day", False), ("night", True)):
            for n in expand(recs, night):
                movement[key]["fixed" if n["fixed"] else "random"] += 1
                if map_id not in sizes:
                    no_size.add(map_id)
                    continue
                w, h = sizes[map_id]
                if n["x"] < w and n["y"] < h:
                    in_bounds[key] += 1
                else:
                    out_of_bounds.append({"map_id": map_id, "time": key, "x": n["x"], "y": n["y"], "size": [w, h],
                                          "rom_addr": "0x%04X" % n["addr"], "record": n["raw"]})
    # ★例外 map（指示書 §10-9）: 展開した座標が area map の大きさに収まらない。⚠ 原因は未解明（y だけが超える）
    exc: dict[int, dict] = {}
    for o in out_of_bounds:
        e = exc.setdefault(o["map_id"], {"map_id": o["map_id"], "size": o["size"], "day": 0, "night": 0,
                                         "status": "UNKNOWN", "note": "★NPC の y が map の高さを超える（x は収まる）"})
        e[o["time"]] += 1
    return {"records": n_rec, "lists": len(lists), "format_counts": dict(sorted(fmt_count.items())),
            "format_examples": {str(k): v for k, v in sorted(fmt_example.items())},
            "movement": {k: dict(v) for k, v in movement.items()},
            "in_bounds": in_bounds, "out_of_bounds": out_of_bounds, "maps_without_size": sorted(no_size),
            "exception_maps": [exc[k] for k in sorted(exc)]}


def runtime_view(master_npcs: list[dict], slots: list[dict]) -> list[dict]:
    """★指示書 §7: Master（ROM）と Runtime（RAM）を分けて 1 体ずつ並べる。

    ★RAM の slot は展開の順 = Master の並び。⚠ 数が違えば（差し替え / 別の時間帯）その分は `runtime = None`。
    ★fixed でも RAM と違えば RAM を優先して `current_*` に出す。
    """
    out = []
    for i, m in enumerate(master_npcs):
        s = slots[i] if i < len(slots) else None
        row = {"npc_id": m["npc_id"], "master": m, "runtime": s}
        if s is not None:
            row["current_x"], row["current_y"] = s["x"], s["y"]
            row["current_facing"] = s["facing"]
            row["walking"] = bool(s["state"] & 0x40)
            row["moved_from_initial"] = (s["x"], s["y"]) != (m["initial_x"], m["initial_y"])
            row["consistent"] = (s["fixed"] == (m["movement"] == "fixed")) and (
                s.get("appearance_id") in (None, m["appearance_id"]))
        else:
            row["current_x"], row["current_y"] = m["initial_x"], m["initial_y"]
            row["current_facing"] = m["initial_facing"]
            row["walking"] = False
            row["moved_from_initial"] = None
            row["consistent"] = None
        out.append(row)
    return out


def write_all(root, rom=None) -> dict:
    """★指示書 §8 の 4 つを書く。"""
    out = pathlib.Path(root) / "work" / "runtime" / "dq3-probe" / "npcs"
    out.mkdir(parents=True, exist_ok=True)
    day, night = all_maps(False, rom), all_maps(True, rom)
    var = variants()
    val = validate(rom)
    for name, body in (("all-maps-day.json", day), ("all-maps-night.json", night),
                       ("map-variants.json", var), ("parser-validation.json", val)):
        (out / name).write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"day": (day["map_count"], day["npc_total"]), "night": (night["map_count"], night["npc_total"]),
            "variants": var["map_count"], "validation": {k: val[k] for k in ("records", "in_bounds", "movement")},
            "out_of_bounds": len(val["out_of_bounds"])}


def write_ledger(root, map_id: int, night: bool = False, rom=None) -> pathlib.Path:
    out = pathlib.Path(root) / "work" / "runtime" / "dq3-probe" / "npcs"
    out.mkdir(parents=True, exist_ok=True)
    path = out / ("map_%03d.json" % map_id)
    path.write_text(json.dumps(ledger(map_id, night, rom), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path
