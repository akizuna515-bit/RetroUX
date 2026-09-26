"""talk_id → script の振り分け → role（RX3-0056 / probe_only）。

## ★導線（2026-09-02 逆アセンブル）

```text
bank 14 $8235  A → はなす: 目の前の slot を探し $04 = slot - 4 → $F507 → $04/$05 = talk_id（10 bit）
bank 14 $82E2  BRK 33 17 → bank 13 $8054（相手の絵を描き直す）
bank 14 $82F4  BRK 27 17 → bank 13 $B183 → $B18A（★会話の振り分け）
```

## ★$B18A の振り分け

```text
talk_id = 0                         → BRK F4 47（何も無い）
表 $B34E（34 件: talk_id → 番号）    → メッセージ 0x369 + 番号（★物語の特別な相手 / HYPOTHESIS）
$AC / $60C9 / $60C5 の状態のとき     → 見た目（$06 = appearance >> 2）で $B2EE の型を引き、型ごとの台詞（★特殊状態）
通常: 表 $B3CC（18 本の下限）を上から見て talk_id >= 下限 の最初の組 → $B3F0 の処理へ（$5C = talk_id - 下限）
```

## ★範囲と処理（$B3CC / $B3F0）

```text
0x001  $AD59  特別 1          0x002  $A9B9  特別 2          0x003  $A1B0  特別 3
0x004  $AC8C  特別 4          0x005  $AF51  特別 5
0x006  $A60E  教会（昼夜の挨拶 → 選択肢）                        ★実機: アリアハン教会 0x006
0x00A  $B4BD  $06FF = 番号      → $A51F 宿屋                     ★実機: 宿屋 0x00B
0x028  $B4CC  $06FF = 番号      → $A1CE 武器防具屋
0x032  $B4DB  $06FF = 番号+0x14 → $A296 道具屋
0x03C  $B4F4  メッセージ 0x28E + 番号（昼夜で +0x0D / +0x1A）
0x050  $B4F1  メッセージ 番号（0x000〜）
0x168  $B414  表 $B43E の script（可変長）
0x1E0  $B4C1  $06FF = 番号+0x15 → $A51F 宿屋
0x1EA  $B4D0  $06FF = 番号+0x02 → $A1CE 武器防具屋              ★実機: 武器防具屋 0x1EB
0x1FE  $B4DF  $06FF = 番号+0x17 → $A296 道具屋                  ★実機: 道具屋 0x1FF
0x21C  $B4FE  メッセージ 0x298 + 番号（昼夜）
0x226  $B4EA  メッセージ 0x0F7 + 番号                          ★ふつうの会話（アリアハンの 5 体）
0x3C0  $B418  表 $B43E の script（+0x4D）
```

⚠ 「特別 1〜5」の中身（ルイーダの酒場 / 預かり所 …）は**未確認** → role = None（other / HYPOTHESIS の注記だけ）。
⚠ talk_id は **script の id** で、文字列 id ではない（★メッセージ番号は範囲ごとに base を足して作る）。
"""
from __future__ import annotations

import json
import pathlib

#: ★$B3CC（下限）/ $B3F0（処理）の写し。★(下限, 処理番地, class, role, 追加の情報)
CLASSES = (
    (0x3C0, 0xB418, "event_script", None, {"table": "$B43E", "offset_add": 0x4D}),
    (0x226, 0xB4EA, "message", None, {"message_base": 0x0F7}),
    (0x21C, 0xB4FE, "message_daynight", None, {"message_base": 0x298}),
    (0x1FE, 0xB4DF, "item_shop", "item_shop", {"routine": 0xA296, "index_add": 0x17}),
    (0x1EA, 0xB4D0, "weapon_armor_shop", "weapon_armor_shop", {"routine": 0xA1CE, "index_add": 0x02}),
    (0x1E0, 0xB4C1, "inn", "inn", {"routine": 0xA51F, "index_add": 0x15}),
    (0x168, 0xB414, "event_script", None, {"table": "$B43E", "offset_add": 0}),
    (0x050, 0xB4F1, "message", None, {"message_base": 0x000}),
    (0x03C, 0xB4F4, "message_daynight", None, {"message_base": 0x28E}),
    (0x032, 0xB4DB, "item_shop", "item_shop", {"routine": 0xA296, "index_add": 0x14}),
    (0x028, 0xB4CC, "weapon_armor_shop", "weapon_armor_shop", {"routine": 0xA1CE, "index_add": 0}),
    (0x00A, 0xB4BD, "inn", "inn", {"routine": 0xA51F, "index_add": 0}),
    (0x006, 0xA60E, "church", "church", {"routine": 0xA60E}),
    (0x005, 0xAF51, "special_5", None, {}),
    (0x004, 0xAC8C, "special_4", None, {}),
    (0x003, 0xA1B0, "special_3", None, {}),
    (0x002, 0xA9B9, "special_2", None, {}),
    (0x001, 0xAD59, "special_1", None, {}),
)

#: ★実機で会話の文と一致した role（2026-09-02 アリアハン）→ CONFIRMED。★それ以外の施設 role は code から（OBSERVED）
ROLE_STATUS = {"inn": "CONFIRMED", "item_shop": "CONFIRMED", "weapon_armor_shop": "CONFIRMED", "church": "CONFIRMED"}
#: ★$B34E の特別な talk_id（★メッセージ 0x369 + 番号 / 物語の相手 = HYPOTHESIS）
SPECIAL_TABLE_IDS = {
    0x21C, 0x227, 0x228, 0x229, 0x22A, 0x22B, 0x22C, 0x053, 0x22D, 0x169, 0x22E, 0x22F, 0x230, 0x056, 0x231,
    0x232, 0x233, 0x234, 0x236, 0x237, 0x238, 0x239, 0x23A, 0x23B, 0x23C, 0x23D, 0x302, 0x2F8, 0x303, 0x304,
    0x313, 0x3DA, 0x31C, 0x3DC,
}
FACILITY_ROLES = ("inn", "item_shop", "weapon_armor_shop", "church")


def classify(talk_id: int) -> dict:
    """★talk_id 1 つの振り分け先。"""
    if talk_id == 0:
        return {"talk_id": talk_id, "class": "none", "handler": None, "role": None, "role_source": None,
                "role_status": None, "offset": None, "note": "BRK F4 47（相手は何も言わない）"}
    for bound, handler, klass, role, extra in CLASSES:
        if talk_id >= bound:
            off = talk_id - bound
            row = {"talk_id": talk_id, "class": klass, "handler": "$%04X" % handler, "bound": bound, "offset": off,
                   "role": role, "role_source": "rom_script" if role else None,
                   "role_status": ROLE_STATUS.get(role) if role else None}
            if "message_base" in extra:
                row["message_id"] = extra["message_base"] + off
            if "index_add" in extra:
                row["facility_index"] = extra["index_add"] + off
            if "routine" in extra:
                row["routine"] = "$%04X" % extra["routine"]
            if "table" in extra:
                row["script_table"] = extra["table"]
                row["script_index"] = extra["offset_add"] + off
            if talk_id in SPECIAL_TABLE_IDS:
                row["special_table_B34E"] = True
                row["note"] = "★$B34E の特別な相手（メッセージ 0x369+番号 / HYPOTHESIS）。範囲の処理より先に選ばれる"
            return row
    return {"talk_id": talk_id, "class": "unknown", "handler": None, "role": None, "role_source": None,
            "role_status": None, "offset": None}


#: ★★ 冒険の書に記録して「また すぐに たびだつ つもりか？」と聞く共通の処理（bank 13 / RX3-0194 / 2026-09-12）
#:
#:   ```text
#:   $BB61  王の番号を $60C3 の下位 3 bit へ → Q1「記録してもよいか」（BRK 20 17 = はい／いいえ）
#:          ⚠ いいえ / B → BNE $BB9D（BRK 65 17 を飛ばす。⚠ BRK 65 17 が記録かは未確認）
#:   $BB9D  Q2「また すぐに たびだつ つもりか？」（LDA #3 / JSR $BEC1 → $BBA2 の BRK 20 17）
#:          はい → $BBCF（メッセージ 4 / ふつうに戻る）
#:          ⚠⚠ いいえ / B → メッセージ 5 → STA $06C8 → $BBCC で自分へ JMP（★ゲームが終わる）
#:   ```
SAVE_KING_BANK = 13
SAVE_KING_ROUTINE = 0xBB61
#: ★Q2 の入口（★`nav_v0.lua` の `$BB9D` 見張りと同じ番地）
DEPART_QUESTION = 0xBB9D
#: ★★ 宿屋の「おとまりに なりますか？」（bank 13 / RX3-0241 / 2026-09-13 逆アセンブル）
#:
#:   ```text
#:   $A51F  宿屋の処理（★$B4BD / $B4C1 から JMP）: $06DF < $78 → 挨拶 BRK 17 87 / それ以外 BRK 18 87
#:   $A52F  値段（$06FF の店番号 → $A84A の表 × 人数）→ $063F
#:   $A556  BRK 19 87      ★問い（★実機の文「ひとばん 8ゴールドですが おとまりに なりますか？」）
#:   $A559  BRK 12 D7
#:   $A55C  BRK 20 17      ★はい／いいえ（bank 14 $8743）← ★`nav_v0.lua` の見張り（宿屋の処理で 1 か所だけ）
#:   $A55F  BNE $A51B      ⚠ いいえ / B → BRK 1D 87（またどうぞ）/ RTS
#:   $A561  JSR $A073 / BCC $A518   ⚠ お金が足りない → BRK 1A 87 → $A51B
#:   ```
INN_ROUTINE = 0xA51F
INN_QUESTION = 0xA55C
#: ★台本の表（$B414 / $B418 の中身）: $B43C = 台本の頭（2 バイト）/ $B43E = 長さ（1 バイトずつ）
_SCRIPT_BASE_PTR = 0xB43C
_SCRIPT_LENGTHS = 0xB43E
#: ★talk_id の範囲 → 台本の番号の足し分（$B414 = +0 / $B418 = +0x4D）
_SCRIPT_RANGES = ((0x168, 0x1DF, 0x00), (0x3C0, 0x3FF, 0x4D))
#: ⚠ 表の位置が合っているかの印（★$B414 の振り分けそのもの / ★$BB61 の頭）。⚠ 違えば読まない
_DISPATCH_BYTES = bytes.fromhex("A900F002A94D18655CAA0AA8AD3CB4855EAD3DB4855F")
_ROUTINE_BYTES = bytes.fromhex("984A38E946855C")
_BRANCH_OPS = frozenset({0x10, 0x30, 0x50, 0x70, 0x90, 0xB0, 0xD0, 0xF0})
DEFAULT_ROM = pathlib.Path(__file__).resolve().parents[2] / "work" / "rom" / "DQ3_J.nes"
_SAVE_KINGS: dict = {}


def _bank_reader(rom: bytes, bank: int):
    def rd(cpu: int, n: int = 1) -> bytes:
        at = 0x10 + bank * 0x4000 + (cpu - 0x8000)
        got = rom[at:at + n]
        if len(got) != n:
            raise ValueError("ROM が短い: $%04X" % cpu)
        return got
    return rd


def _script_starts(rd) -> dict:
    """★台本の番号 → 先頭の番地（★$5E = 頭 + 長さ[0..X] の和 / ⚠ X 自身も足す）。"""
    head = int.from_bytes(rd(_SCRIPT_BASE_PTR, 2), "little")
    top = max(hi - lo + add for lo, hi, add in _SCRIPT_RANGES)
    lengths = rd(_SCRIPT_LENGTHS, top + 2)
    starts, acc = {}, head
    for x in range(top + 2):
        acc += lengths[x]
        starts[x] = acc
    return starts


def _reaches(rd, start: int, end: int, target: int) -> bool:
    """★[start, end) に target への JMP / JSR / 相対分岐があるか（⚠ 生のバイトを見る。★台本は途中に引数を挟む）。"""
    if end <= start:
        return False
    body = rd(start, end - start + 2)
    lo, hi = target & 0xFF, target >> 8
    for k in range(end - start):
        op = body[k]
        if op in (0x4C, 0x20) and body[k + 1] == lo and body[k + 2] == hi:
            return True
        if op in _BRANCH_OPS:
            off = body[k + 1]
            if start + k + 2 + (off - 256 if off & 0x80 else off) == target:
                return True
    return False


def _save_kings_from(rom: bytes) -> frozenset:
    rd = _bank_reader(rom, SAVE_KING_BANK)
    if rd(0xB414, len(_DISPATCH_BYTES)) != _DISPATCH_BYTES or rd(SAVE_KING_ROUTINE, len(_ROUTINE_BYTES)) != _ROUTINE_BYTES:
        raise ValueError("⚠ 版が違う（$B414 / $BB61 の中身が合わない）")
    starts = _script_starts(rd)
    later = sorted(set(starts.values()))
    ids = set()
    for lo, hi, add in _SCRIPT_RANGES:
        for tid in range(lo, hi + 1):
            start = starts[tid - lo + add]
            end = next((s for s in later if s > start), start)
            if start == SAVE_KING_ROUTINE or _reaches(rd, start, end, SAVE_KING_ROUTINE):
                ids.add(tid)
    return frozenset(ids)


def save_king_talk_ids(rom_path=None) -> frozenset:
    """★冒険の書に記録して「また たびだつか」を聞く相手の talk_id（★ROM から / RX3-0194）。

    ★台本が `$BB61` から始まるか、`$BB61` へ跳ぶ / 分岐する相手。⚠ 2026-09-12 の ROM では
    {426 ロマリア, 430 アリアハン, 431〜436}（★433 = イシスの女王。言い回しが違う）。
    ⚠ ROM が無い / 版が違う / 読めないときは空（★呼ぶ側が手の表で補う）。
    """
    target = pathlib.Path(rom_path) if rom_path else DEFAULT_ROM
    try:
        key = (str(target), target.stat().st_mtime_ns)
    except OSError:
        return frozenset()
    if key not in _SAVE_KINGS:
        try:
            _SAVE_KINGS[key] = _save_kings_from(target.read_bytes())
        except (OSError, ValueError, IndexError):
            _SAVE_KINGS[key] = frozenset()
    return _SAVE_KINGS[key]


#: ★★ 選択肢（はい／いいえ）を出す命令（RX3-0124 / RX3-0121）
#:
#:   ```text
#:   00 20 17   BRK $20 cmd=$17 → bank14 $8743（★窓を開く共通処理 / 表の索引 $1D = はい・いいえ）
#:   ```
CHOICE_BRK = bytes.fromhex("002017")

#: ⚠⚠ 所持金を見る処理（★宿屋 `$A561` と同じ）。ここを通る「はい」は**お金が動く**。
MONEY_ROUTINE = 0xA073

#: ★★ 文を出す BRK の基数表（RX3-0124 ④ / 2026-09-19 逆アセンブル）
#:
#:   ```text
#:   BRK の arg は Y に入る（$EF47 TXA/TAY）→ bank13 $B0A3: ADC $B0B4,Y
#:   → ★メッセージ番号 = arg + 基数[Y]
#:   sel $27 → $BFCC → $B05C（Y=6）   sel $47 → $BFD2 → $B072（Y=6）
#:   sel $37 → $BFCF → $B061（Y=8）   sel $57 → $BFD5 → $B07A（Y=8）
#:   ```
#:
#:   ★`Y=2` の基数 `0x0F7` は、`CLASSES` の「ふつうの会話」の `message_base` と**同じ数**（★裏取り）。
_MESSAGE_BASES = 0xB0B4
MESSAGE_BASE_COUNT = 5
#: ★sel → 基数表の索引（⚠ 実機のコードで確かめた JMP 先の `LDY #$nn`）
MESSAGE_SEL_INDEX = {0x27: 6, 0x37: 8, 0x47: 6, 0x57: 8}

_CHOICES: dict = {}


def _script_span(rd):
    """★台本の番号 → `(先頭, 終わり)`（⚠ 終わりは**次の違う先頭**）。

    ⚠⚠ 長さ 0 の欄は**次と同じ先頭**を指します（★同じ台本を共有する talk_id）。
    ★欄の長さをそのまま使うと 0 バイトになり、⚠ 選択肢を見落とします。
    """
    starts = _script_starts(rd)
    later = sorted(set(starts.values()))
    out = {}
    for x, start in starts.items():
        nxt = next((s for s in later if s > start), None)
        out[x] = (start, nxt if nxt is not None else start + 0x100)
    return out


def _choices_from(rom: bytes) -> dict:
    rd = _bank_reader(rom, SAVE_KING_BANK)
    if rd(0xB414, len(_DISPATCH_BYTES)) != _DISPATCH_BYTES:
        raise ValueError("⚠ 版が違う（$B414 の中身が合わない）")
    span = _script_span(rd)
    ask, money = set(), set()
    for lo, hi, add in _SCRIPT_RANGES:
        for tid in range(lo, hi + 1):
            start, end = span[tid - lo + add]
            if end <= start:
                continue
            body = rd(start, end - start)
            if CHOICE_BRK not in body:
                continue
            ask.add(tid)
            if _reaches(rd, start, end, MONEY_ROUTINE):
                money.add(tid)
    bases = rd(_MESSAGE_BASES, MESSAGE_BASE_COUNT * 2)
    return {
        "ask": frozenset(ask),
        "money": frozenset(money),
        "bases": tuple(int.from_bytes(bases[i * 2:i * 2 + 2], "little")
                       for i in range(MESSAGE_BASE_COUNT)),
    }


def _choices(rom_path=None) -> dict:
    target = pathlib.Path(rom_path) if rom_path else DEFAULT_ROM
    empty = {"ask": frozenset(), "money": frozenset(), "bases": ()}
    try:
        key = (str(target), target.stat().st_mtime_ns)
    except OSError:
        return empty
    if key not in _CHOICES:
        try:
            _CHOICES[key] = _choices_from(target.read_bytes())
        except (OSError, ValueError, IndexError):
            _CHOICES[key] = empty
    return _CHOICES[key]


def choice_talk_ids(rom_path=None) -> frozenset:
    """★「はい／いいえ」を聞いてくる相手の talk_id（★ROM から / RX3-0124）。

    ⚠ 台本が**自分の中に** `BRK $20 cmd=$17` を持つものだけです。
      ★施設（宿屋・店・教会）は共通処理へ飛んでから聞くので、ここには**入りません**
      （⚠ `CLASSES` の role で分かります）。
    ⚠ ROM が無い / 版が違うときは空（★呼ぶ側は今までどおり）。
    """
    return _choices(rom_path)["ask"]


def money_choice_talk_ids(rom_path=None) -> frozenset:
    """⚠⚠ 「はい」で**お金が動く**相手の talk_id（★所持金を見る `$A073` を通る）。

    ★2026-09-19 の ROM では talk 411〜421（台本 `$BA80` / 11 件）。
    ⚠ 自動で「はい」を押してよいかの判断に使います（★押さないほうの根拠）。
    """
    return _choices(rom_path)["money"]


def message_bases(rom_path=None) -> tuple:
    """★文を出す BRK の基数（`$B0B4` の 5 つ）。⚠ 読めなければ空。"""
    return _choices(rom_path)["bases"]


def script_analysis() -> dict:
    """★`script-analysis.json`（指示書 §3 の中間表現）。"""
    ranges = []
    ordered = sorted(CLASSES, key=lambda c: c[0])
    for i, (bound, handler, klass, role, extra) in enumerate(ordered):
        hi = ordered[i + 1][0] - 1 if i + 1 < len(ordered) else 0x3FF
        ranges.append({"from": bound, "to": hi, "handler": "$%04X" % handler, "class": klass, "role": role,
                       "operations": _ops(klass, extra)})
    return {
        "source": "bank 13 $B18A / $B3CC / $B3F0（2026-09-02 逆アセンブル）",
        "dispatch": ["BRK 27 17 → bank13 $B183", "talk_id == 0 → BRK F4 47",
                     "$B34E に有れば メッセージ 0x369+番号", "状態（$AC/$60C9/$60C5）なら見た目の型で台詞",
                     "表 $B3CC を上から: talk_id >= 下限 の最初 → $B3F0 の処理（$5C = talk_id - 下限）"],
        "talk_id_meaning": "script id（★文字列 id ではない。メッセージ番号は範囲ごとの base + 番号）",
        "ranges": ranges,
        "special_table_B34E": sorted(SPECIAL_TABLE_IDS),
        "status": {"dispatch": "CONFIRMED(code)", "facility_roles": "CONFIRMED（実機 4 体の会話の文と一致）",
                   "special_1_5": "UNKNOWN", "message_ids": "HYPOTHESIS（本文の場所は未追跡）"},
    }


def _ops(klass: str, extra: dict) -> list[str]:
    if klass in FACILITY_ROLES:
        return ["$06FF = facility_index", "JMP %s（%s の共通処理）" % ("$%04X" % extra["routine"], klass)]
    if klass == "church":
        return ["昼夜で挨拶（BRK 00/01 87）", "選択肢（$A810）"]
    if klass.startswith("message"):
        return ["message_id = 0x%03X + offset" % extra["message_base"]] + (["昼夜で +0x0D / +0x1A"] if "daynight" in klass else []) + ["BRK 04 07（表示）"]
    if klass == "event_script":
        return ["表 $B43E から script の位置", "JMP ($5E)"]
    return ["（未確認）"]


def annotate(master: dict) -> dict:
    """★全 map 台帳に role を足す（指示書 §5）。⚠ 元は変えず、新しい dict を返す。"""
    out = json.loads(json.dumps(master))
    for m in out["maps"]:
        for n in m["npcs"]:
            c = classify(n["talk_id"])
            n["role"] = c["role"]
            n["role_source"] = c["role_source"]
            n["role_status"] = c["role_status"]
            n["talk_class"] = c["class"]
    return out


def talk_index(day: dict, night: dict) -> dict:
    """★`talk-index.json`: 全 NPC の talk_id → class / role。"""
    rows = []
    for lab, d in (("day", day), ("night", night)):
        for m in d["maps"]:
            for n in m["npcs"]:
                c = classify(n["talk_id"])
                rows.append({"map_id": m["map_id"], "time": lab, "npc_id": n["npc_id"], "talk_id": n["talk_id"],
                             "class": c["class"], "role": c["role"], "facility_index": c.get("facility_index"),
                             "message_id": c.get("message_id")})
    by_class: dict[str, int] = {}
    for r in rows:
        by_class[r["class"]] = by_class.get(r["class"], 0) + 1
    return {"count": len(rows), "with_talk_id": sum(1 for r in rows if r["talk_id"]),
            "by_class": dict(sorted(by_class.items())), "rows": rows}


def role_mapping() -> dict:
    return {"roles": {r: {"status": ROLE_STATUS[r], "source": "rom_script", "evidence": "アリアハンの会話の文（2026-09-02）"}
                      for r in FACILITY_ROLES},
            "unresolved": {"special_1": "$AD59", "special_2": "$A9B9", "special_3": "$A1B0", "special_4": "$AC8C",
                           "special_5": "$AF51", "message": "通常の会話（role = null）", "event_script": "物語のイベント（role = null）"}}


def facility_goals(master_map: dict) -> list[dict]:
    """★施設 Navigation の目的地（指示書 §13）。★map を問わず role の付いた NPC を並べる。"""
    out = []
    for n in master_map["npcs"]:
        c = classify(n["talk_id"])
        if c["role"] in FACILITY_ROLES:
            out.append({"role": c["role"], "npc_id": n["npc_id"], "x": n["initial_x"], "y": n["initial_y"],
                        "movement": n["movement"], "talk_id": n["talk_id"], "facility_index": c.get("facility_index")})
    return out


def write_all(root) -> dict:
    root = pathlib.Path(root)
    npcs = root / "work" / "dq3-probe" / "npcs"
    talk = root / "work" / "dq3-probe" / "talk"
    talk.mkdir(parents=True, exist_ok=True)
    day = json.loads((npcs / "all-maps-day.json").read_text(encoding="utf-8"))
    night = json.loads((npcs / "all-maps-night.json").read_text(encoding="utf-8"))
    for name, d in (("all-maps-day.json", day), ("all-maps-night.json", night)):
        (npcs / name).write_text(json.dumps(annotate(d), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    idx = talk_index(day, night)
    (talk / "talk-index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (talk / "script-analysis.json").write_text(json.dumps(script_analysis(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (talk / "role-mapping.json").write_text(json.dumps(role_mapping(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"by_class": idx["by_class"], "count": idx["count"], "with_talk_id": idx["with_talk_id"]}
