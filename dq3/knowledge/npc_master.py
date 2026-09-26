"""NPC の Master（ROM）と Runtime（RAM）を製品側へ渡す service（RX3-0058）。

## ★責務の分離（指示書 §26 / §28）

```text
Master    ROM の記録: npc_id / 初期座標 / 見た目 / 固定・移動 / talk_id / role     ← ここが読む
Runtime   RAM の表: 現在位置 / 向き / 歩行中                                       ← state.json の npc_tbl
Heard     実際に話した事実（dq3/knowledge/npc_heard.py）
```

⚠ UI は ROM / RAM の番地を知らない。★この module の関数だけを呼ぶ。
⚠ 解析の中身（記録の文法 / 振り分け表）は `dq3/testing/npc_rom.py` / `talk_script.py` が正本で、
  ここは**読み替えるだけ**（★同じ表を 2 か所に持たない）。
"""
from __future__ import annotations

from dq3.testing import npc_rom as _rom
from dq3.testing import talk_script as _talk

#: ★施設 role の表示名（★UI コードにはこの表を経由させる）
ROLE_LABELS = {"inn": "宿屋", "item_shop": "道具屋", "weapon_armor_shop": "武器防具屋", "church": "教会"}
ROLE_ORDER = ("inn", "item_shop", "weapon_armor_shop", "church")

#: ★`master_for` に渡す時間帯。⚠⚠ 片方だけ見ると、もう片方に居る NPC は
#:   **エラーも出さずに消えます**（★RX3-0087 で夜だけの武器屋 2 軒を落としていた）。
TIME_DAY = 0
TIME_NIGHT = _rom.NIGHT_FROM
TIMES = (TIME_DAY, TIME_NIGHT)

_LISTS = None


def _lists():
    global _LISTS
    if _LISTS is None:
        _LISTS = _rom.parse_lists(_rom._prg(None))
    return _LISTS


def is_night(time_byte: int | None) -> bool:
    return bool(time_byte is not None and _rom.is_night(int(time_byte)))


def variant_status(map_id: int) -> str:
    """★`DEFAULT` か `UNKNOWN`（差し替えのある map。★安全側に倒す / 指示書 §25）。"""
    return _rom.effective_table_id(map_id)[1]


def master_for(map_id: int, time_byte: int | None, npc_tbl_hex: str | None = None) -> dict:
    """★その map・時間帯の Master（role 付き）。⚠ 差し替え map は `status = UNKNOWN` で npcs を空にする。

    ★★ ただし、実機の NPC の表（`npc_tbl_hex`）が**既定の表と完全に一致**すれば既定の表を使う
    （RX3-0175 / 2026-09-11 依頼者「ロマリアで聞き込みがきかない」）。
    ⚠ 差し替え先の表とも一致する（見分けがつかない）なら、今までどおり空。
    ★★ 差し替え先の表の**ちょうど 1 つ**とだけ一致し、全員を既定の表の同じ人へ直せれば、その表を使う
    （RX3-0231 / `variant_master_for`）。⚠ 直せなければ空（★npc_id が既定の表とぶつかり、heard が取り違える）。
    """
    if variant_status(map_id) != "DEFAULT":
        if npc_tbl_hex and runtime_confirms_default(map_id, time_byte, npc_tbl_hex):
            led = default_master_for(map_id, time_byte)
            led["status"], led["confirmed_by"] = "DEFAULT", "runtime"
            return led
        led = variant_master_for(map_id, time_byte, npc_tbl_hex) if npc_tbl_hex else None
        if led is not None:
            return led
        # ★位置だけずれている表（★イベントで門番が道をあける / RX3-0288）
        led = moved_master_for(map_id, time_byte, npc_tbl_hex) if npc_tbl_hex else None
        if led is not None:
            return led
        return _empty(map_id, time_byte, "UNKNOWN")
    return default_master_for(map_id, time_byte)


def runtime_variant_tables(map_id: int, time_byte: int | None, npc_tbl_hex: str | None) -> list:
    """★実機の表と**全員一致する**差し替え先の表を全部（★番号の小さい順 / RX3-0286）。

    ⚠ 既定の表と一致するときは空（★そちらを使う / `runtime_confirms_default`）。
    """
    slots = {s["slot"]: s for s in runtime_slots(npc_tbl_hex)}
    lists = _lists()
    if not slots or not (0 <= map_id < len(lists)):
        return []
    night = is_night(time_byte)
    if _table_matches(_rom.map_ledger(map_id, lists[map_id], night)["npcs"], slots):
        return []
    hits = set()
    for m in _rom.variants()["maps"]:
        if m["map_id"] != map_id:
            continue
        for v in m["variants"]:
            tid = v["npc_table_id"]
            if 0 <= tid < len(lists) and _table_matches(_rom.map_ledger(map_id, lists[tid], night)["npcs"], slots):
                hits.add(tid)
    return sorted(hits)


def runtime_variant_table(map_id: int, time_byte: int | None, npc_tbl_hex: str | None) -> int | None:
    """★実機の表が、差し替え先の表の**ちょうど 1 つ**とだけ一致すれば、その表番号（RX3-0231）。

    ⚠ 既定の表と一致する（→ `runtime_confirms_default`）/ 2 つ以上と一致する / どれとも合わない → None。
    """
    hits = runtime_variant_tables(map_id, time_byte, npc_tbl_hex)
    return hits[0] if len(hits) == 1 else None


#: ★表を見比べるときに「同じ人」と見なすために見る欄（⚠ 台詞 `talk_id` は**わざと外す**）
TABLE_KEYS = ("slot", "initial_x", "initial_y", "appearance_id", "movement")


def talk_only_difference(map_id: int, time_byte: int | None, tids) -> bool:
    """★その表どうしの違いが**台詞だけ**か（RX3-0286 / 2026-09-18）。

    ⚠ 位置・見た目・動く/動かない が 1 つでも違えば False（★別の人の並びなので選べない）。
    """
    lists = _lists()
    night = is_night(time_byte)
    shapes = []
    for tid in tids:
        if not (0 <= tid < len(lists)):
            return False
        npcs = _rom.map_ledger(map_id, lists[tid], night)["npcs"]
        shapes.append([tuple(n.get(k) for k in TABLE_KEYS) for n in npcs])
    return len(shapes) > 1 and all(s == shapes[0] for s in shapes[1:])


def ambiguous_variant_table(map_id: int, time_byte: int | None, npc_tbl_hex: str | None) -> int | None:
    """★2 つ以上の差し替え表と一致しても、**違いが台詞だけ**なら、いちばん小さい番号で進める。

    ## ⚠⚠ なぜ必要か（RX3-0286 / 2026-09-18）

      依頼者「save8 サマンオサで聞き込みできない。イベント中だからか？」
      ★サマンオサ（map 6）の実機の表は、差し替え先の **243 と 249 の両方**と全員一致する。
      ⚠ 「2 つ以上と一致 → 決められない」で候補 0（`UNKNOWN`）になっていた。

      ```text
      表 243 と 249 の違い   ★11 人中 4 人の talk_id だけ（716/724・715/723・713/254・714/722）
      同じもの               位置・見た目・動く/動かない・役割（教会 / 道具屋）
      ```

      → ★**歩く・話しかける・施設を指す**のに要る情報はどちらでも同じなので、進めてよい。
      ⚠ どちらの台詞かは**分からない**（★条件の意味は HYPOTHESIS のまま使わない / RX3-0231）。
        ★`npc_id` は表番号を含むので、後でもう一方だと分かれば**その人たちは聞き直し**になる
        （⚠ 台詞が変わったら聞き直す = RX3-0231 の決まりと同じ向き）。
    """
    hits = runtime_variant_tables(map_id, time_byte, npc_tbl_hex)
    if len(hits) < 2 or not talk_only_difference(map_id, time_byte, hits):
        return None
    return hits[0]


def _shape_matches(npcs: list[dict], slots: dict) -> bool:
    """★**人数と 動く/動かない** だけで見る（⚠ 位置は見ない / RX3-0288）。

    ⚠ `_table_matches` との違いは「動かない人の位置」を**問わない**ことだけ。
    """
    if not npcs or len(npcs) != len(slots):
        return False
    real = 0
    for n in npcs:
        s = slots.get(n.get("slot"))
        if s is None:
            return False
        if is_hidden(s):
            continue
        if (n.get("movement") == "fixed") != bool(s.get("fixed")):
            return False
        real += 1
    # ⚠ 全員消えている表は何とも比べられない（★`_table_matches` と同じ決まり）
    return real > 0


def moved_table(map_id: int, time_byte: int | None, npc_tbl_hex: str | None) -> tuple | None:
    """★位置だけずれている表（★候補がちょうど 1 つのときだけ / RX3-0288）。戻り値 `(表番号, ずれた人数)`。

    ## ⚠⚠ なぜ必要か（2026-09-18）

      依頼者「サマンオサの城でも同様（save0）」。★map 97 の実機の表（12 人）は:

      ```text
      既定の表 97   13 人      ⚠ 人数から合わない
      表 244        12 人      ★動き方は全員一致 / ⚠ 位置が 2 人だけずれる
                               slot 4 (15,27) → (16,27)   slot 5 (13,27) → (12,27)
                               ★見た目 8・talk 396 の**門番 2 人が 1 升ずつ外へ**寄っている
      ```

      ⚠ 「動かない人の位置も全員一致」を要求していたので、どの表とも一致せず候補 0 だった。
      → ★イベントで**動かない人が動く**ことがある（★門番が道をあける）。
        位置は RAM のほうが正しい（`merged` は現在位置に RAM を使う）ので、
        ★**人数と動き方**で表を決め、⚠ **ほかに候補が無いときだけ**使う。
    """
    slots = {s["slot"]: s for s in runtime_slots(npc_tbl_hex)}
    lists = _lists()
    if not slots or not (0 <= map_id < len(lists)):
        return None
    night = is_night(time_byte)
    candidates = [map_id]
    for m in _rom.variants()["maps"]:
        if m["map_id"] == map_id:
            candidates += [v["npc_table_id"] for v in m["variants"]]
    hard = [tid for tid in dict.fromkeys(candidates)
            if 0 <= tid < len(lists)
            and _shape_matches(_rom.map_ledger(map_id, lists[tid], night)["npcs"], slots)]
    if len(hard) != 1:
        return None                                          # ⚠ 決められない（★今までどおり空）
    tid = hard[0]
    npcs = _rom.map_ledger(map_id, lists[tid], night)["npcs"]
    moved, stayed = 0, 0
    for n in npcs:
        s = slots.get(n.get("slot"))
        if s is None or is_hidden(s) or n.get("movement") != "fixed":
            continue
        if (n.get("initial_x"), n.get("initial_y")) != (s.get("x"), s.get("y")):
            moved += 1
        else:
            stayed += 1
    # ⚠⚠ **ずれている人のほうが多ければ使わない**（★それは別の人の並び）。
    #   ★「イベントで何人かが動いた」だけを受け入れる（門番 2 人 / 18 人中 1 人 …）。
    if moved >= stayed:
        return None
    return tid, moved


def _person_key(n: dict) -> tuple:
    """★表をまたいで同じ人を見分ける鍵: 初期位置・見た目・動く/動かない（⚠ 台詞 talk_id は変わってよい）。"""
    return (n.get("initial_x"), n.get("initial_y"), n.get("appearance_id"), n.get("movement"))


#: ★新しく出てきた人の番号（RX3-0243）: 表番号 × 256 ＋ 表での番号（★既定の表の npc_id は 0〜63 なのでぶつからない）
VARIANT_ID_SHIFT = 8


def variant_npc_id(table_id: int, table_npc_id: int) -> int:
    """★差し替え先の表にだけ居る人の npc_id（RX3-0243 / ★表ごとに決まり、次に読んでも同じ）。"""
    return (int(table_id) << VARIANT_ID_SHIFT) | int(table_npc_id)


def renumber(variant_npcs: list[dict], default_npcs: list[dict], table_id: int | None = None) -> list[dict] | None:
    """★差し替え先の表の人を、既定の表の**同じ人**の npc_id へ直す（RX3-0231）。

    ⚠⚠ 差し替え先の表の npc_id（記録の順）は既定の表の npc_id と**ぶつかる**。そのまま使うと、
      聞いた人の台帳（map ごと・npc_id ごと）で別人を「聞いた」と取り違える。
    ★鍵（`_person_key`）で既定の表の人が**ちょうど 1 人**に決まるときだけ直す。⚠ 2 人以上・既に使った人 → None。
    ★直した人には `table_npc_id`（差し替え先の表での番号）と `default_talk_id`（既定の表の台詞）を添える。

    ★★ どの人にも当たらない人（★新しく出てきた人）は、`table_id` を渡されたときだけ
      表ごとの番号（`variant_npc_id`）で別人として扱う（RX3-0243 / 2026-09-13 依頼者「save8 バハラタにはいったとき、
      自動移動がオフになっているときがある」: 0xC2 は 15 人中 14 人が決まり、slot 6 の 1 人だけ既定の表に居ない）。
      ⚠ `table_id` が無ければ今までどおり None（★RX3-0231 の決まり）。
    """
    by: dict = {}
    for n in default_npcs:
        by.setdefault(_person_key(n), []).append(n)
    out, used = [], set()
    for n in variant_npcs:
        got = by.get(_person_key(n), [])
        if not got and table_id is not None:
            out.append(dict(n, npc_id=variant_npc_id(table_id, n["npc_id"]), table_npc_id=n["npc_id"],
                            default_talk_id=None, new_in_table=True))
            continue
        if len(got) != 1 or got[0]["npc_id"] in used:
            return None
        used.add(got[0]["npc_id"])
        out.append(dict(n, npc_id=got[0]["npc_id"], table_npc_id=n["npc_id"], default_talk_id=got[0].get("talk_id")))
    return out


def variant_master_for(map_id: int, time_byte: int | None, npc_tbl_hex: str | None) -> dict | None:
    """★いま効いている差し替え先の表の Master（npc_id は既定の表の番号 / RX3-0231）。⚠ 決まらなければ None。

    ⚠⚠ 2026-09-13 依頼者「save4 バハラタで、街移動がアクティブになっていない。聞き込みで表が読めません。と出る。」:
      グプタのイベントのあと、バハラタ（map 14）の町の人は差し替え先の表 0xC0（15 人）に替わる。
      ⚠ 既定の表（17 人）とは人数から合わず、差し替え先の表は「使わない」決まりだったので UNKNOWN（候補 0）になっていた。
    ★実機の表（15 人）は 0xC0 とだけ全員一致し、0xC0 の 15 人は既定の表の 15 人へ 1 対 1 で決まる（★初期位置・見た目・動く/動かない）。
    ⚠ 条件の意味（`$60CA` bit2 など）は HYPOTHESIS なので**使わない**（★実機の表だけで決める）。
    """
    tid = runtime_variant_table(map_id, time_byte, npc_tbl_hex)
    ambiguous = False
    if tid is None:
        # ★2 つ以上と一致しても、違いが台詞だけなら進める（RX3-0286 / サマンオサ）
        tid = ambiguous_variant_table(map_id, time_byte, npc_tbl_hex)
        ambiguous = tid is not None
    if tid is None:
        return None
    lists = _lists()
    night = is_night(time_byte)
    led = _rom.map_ledger(map_id, lists[tid], night)
    npcs = renumber(led["npcs"], _rom.map_ledger(map_id, lists[map_id], night)["npcs"], tid)
    if npcs is None:
        return None
    led["npcs"] = npcs
    led = _talk.annotate({"maps": [led]})["maps"][0]
    led["status"], led["table_id"] = "DEFAULT", tid
    # ⚠ どの表か決まりきっていないことを残す（★黙って 1 つに決めない / RX3-0286）
    led["confirmed_by"] = "runtime-talk-ambiguous" if ambiguous else "runtime"
    return led


def moved_master_for(map_id: int, time_byte: int | None, npc_tbl_hex: str | None) -> dict | None:
    """★位置だけずれている表の Master（RX3-0288）。⚠ 決まらなければ None。

    ★`moved_table` が「人数と動き方で候補がちょうど 1 つ」と言ったときだけ使います。
    ⚠ どれだけずれていたかを `moved` に残します（★黙って合わせない）。
    """
    got = moved_table(map_id, time_byte, npc_tbl_hex)
    if got is None:
        return None
    tid, moved = got
    lists = _lists()
    night = is_night(time_byte)
    if tid == map_id:                                        # ★既定の表そのもの
        led = default_master_for(map_id, time_byte)
    else:
        led = _rom.map_ledger(map_id, lists[tid], night)
        npcs = renumber(led["npcs"], _rom.map_ledger(map_id, lists[map_id], night)["npcs"], tid)
        if npcs is None:
            return None
        led["npcs"] = npcs
        led = _talk.annotate({"maps": [led]})["maps"][0]
    led["status"], led["table_id"] = "DEFAULT", tid
    led["confirmed_by"], led["moved"] = "runtime-moved", moved
    return led


#: ★イベントで消えた NPC が RAM の表に残す位置（RX3-0228 / RX3-0230 / 2026-09-13）。
#:
#:   ⚠⚠ 依頼者「save1 バハラタで村人に話したら表示が？」「聞き込みが途中できかなくなって、街移動もできない」:
#:     老人と話すとグプタ（map 14 / slot 10）が (0x80,0x80) に移り、★表が既定の表と「1 人ずれ」になって
#:     `master_for` が UNKNOWN（候補 0）を返していた → 勇者メモ「？」/ 聞き込み即 0 人 / 目的地「―――」。
#:
#:   ★根拠（コード）: NA 版の逆アセンブル bank0C `loc_1280E5`。NPC の動きの台本
#:     （`_bC_s0_npc_anim_script_init`）が終わると、その人の x と y に `#$80` を書く（★台本の flag bit2 が
#:     立っていなければ）。★バハラタの老人（`_npc_hndl18_baharata_granddad`）は台本 1 を始める。
#:   ⚠ UNCONFIRMED（一般の「消えた人」の印としては未確定）: 実データはバハラタの 1 件だけ
#:     （★セーブ 107 本で (0x80,0x80) は save1 の写し 2 本のみ / JP 版の ROM では台本の終わりを未確認）。
#:   ⚠ 別の消し方（x と状態の byte だけ `$80` / `_npc_hndlD`・`_npc_hndl64`）は**扱わない**。
#:   → ★(0x80,0x80) **ちょうど**だけを「消えた人」とみなす（⚠ 広げない）。
HIDDEN_XY = (0x80, 0x80)


def is_hidden(slot: dict | None) -> bool:
    """★RAM の slot が「イベントで消えた人」か（`HIDDEN_XY` ちょうど / ⚠ UNCONFIRMED の決まり）。"""
    return slot is not None and (slot.get("x"), slot.get("y")) == HIDDEN_XY


def _table_matches(npcs: list[dict], slots: dict) -> bool:
    """★表の NPC が、実機の表と**全員**一致するか（★動く / 動かない と、動かない人の位置）。

    ★イベントで消えた人（`HIDDEN_XY`）は、表のその人と一致したとみなす（RX3-0228 / RX3-0230）。
    ⚠ ただし消えていない人が 1 人も一致しなければ一致としない（★全員消えた表は何とも比べられない）。
    ⚠ 人数が違えば今までどおり不一致（★差し替え先の表 0xC0 / 0xC2 はバハラタの既定の表と人数が違う）。
    """
    if not npcs or len(npcs) != len(slots):
        return False
    real = 0
    for n in npcs:
        s = slots.get(n.get("slot"))
        if s is None:
            return False
        if is_hidden(s):
            continue
        fixed = n.get("movement") == "fixed"
        if fixed != bool(s.get("fixed")):
            return False
        if fixed and (n.get("initial_x"), n.get("initial_y")) != (s.get("x"), s.get("y")):
            return False
        real += 1
    return real > 0


def runtime_confirms_default(map_id: int, time_byte: int | None, npc_tbl_hex: str | None) -> bool:
    """★差し替えのある map で、いま効いているのが既定の表だと実機の表から言えるか（RX3-0175）。

    ★ロマリア（map 1）の実測: 既定の表とは 動く/動かない 18/18・動かない人の位置 9/9 が一致、
      差し替え先（表 0xAD / `$60B7` bit6）とは 6/18・0/9。⚠ 条件の意味（HYPOTHESIS）には頼らない。
    """
    slots = {s["slot"]: s for s in runtime_slots(npc_tbl_hex)}
    lists = _lists()
    if not slots or not (0 <= map_id < len(lists)):
        return False
    night = is_night(time_byte)
    if not _table_matches(_rom.map_ledger(map_id, lists[map_id], night)["npcs"], slots):
        return False
    for m in _rom.variants()["maps"]:
        if m["map_id"] != map_id:
            continue
        for v in m["variants"]:
            tid = v["npc_table_id"]
            if 0 <= tid < len(lists) and _table_matches(_rom.map_ledger(map_id, lists[tid], night)["npcs"], slots):
                return False                   # ⚠ 差し替え先とも一致する → 見分けられない
    return True


def default_master_for(map_id: int, time_byte: int | None) -> dict:
    """★**既定の表**（表番号 = map_id）をそのまま読む（RX3-0090）。

    ⚠⚠ 「差し替えがある」ことと「既定の表が読めない」ことは**別**です。
    ★差し替えのある map でも既定の表は読めます。⚠ ただし、その map で本当に
    この表が効くかは分かりません（★条件は `variants()` の HYPOTHESIS）。
    → ★`status` は `UNKNOWN` のまま返します。⚠ 呼ぶ側が「条件つき」と分かる形で使うこと。
    """
    lists = _lists()
    status = variant_status(map_id)
    if not (0 <= map_id < len(lists)):
        return _empty(map_id, time_byte, status)
    led = _rom.map_ledger(map_id, lists[map_id], is_night(time_byte))
    led = _talk.annotate({"maps": [led]})["maps"][0]
    led["status"] = status
    return led


def _empty(map_id: int, time_byte: int | None, status: str) -> dict:
    return {"map_id": map_id, "time": "night" if is_night(time_byte) else "day", "status": status,
            "npc_count": 0, "npcs": []}


def runtime_slots(npc_tbl_hex: str | None, appearance_hex: str | None = None) -> list[dict]:
    """★state.json の `npc_tbl`（$0110〜 の hex）→ slot の一覧。

    ★`appearance_hex`（`npc_appearance` / WRAM `$6ABE` から 16 個）を渡すと、
    ⚠ slot に **`appearance_id`** が入ります（RX3-0304）。

    ## ⚠⚠ なぜ要るか

      ★実機の表の 3 バイト目は「見た目そのもの」ではなく **枠の番号**です。
      ⚠ 解く表を渡さないと、★相手が分かっても**札（`王` など）を出せません**
      （★依頼者 2026-09-20「王様とイベントセリフを話すが、？になっている」）。
    """
    if not npc_tbl_hex:
        return []
    try:
        tbl = bytes.fromhex(npc_tbl_hex)
    except ValueError:
        return []
    wram = None
    if appearance_hex:
        try:
            got = bytes.fromhex(appearance_hex)
        except ValueError:
            got = b""
        if got:
            # ⚠ `ram_slots` は `wram[APPEARANCE_SLOTS - 0x6000 + 枠]` を引く
            wram = bytes(_rom.APPEARANCE_SLOTS - 0x6000) + got
    ram = bytes(0x0110) + tbl
    return _rom.ram_slots(ram, wram)


def runtime_appearance(slot: int, npc_tbl_hex: str | None,
                       appearance_hex: str | None) -> int | None:
    """★その slot の**実機の見た目 id**（⚠ 表がどれか分からなくても出せる / RX3-0304）。"""
    for s in runtime_slots(npc_tbl_hex, appearance_hex):
        if s.get("slot") == slot:
            return s.get("appearance_id")
    return None


def merged(master: dict, slots: list[dict]) -> list[dict]:
    """★Master + Runtime。★現在位置は RAM を優先（指示書 §4-1 / §7）。

    ⚠ イベントで消えた人（`HIDDEN_XY`）は入れない（RX3-0228 / RX3-0230）。
    ★誰も (128,128) を目指さない・正面の人に数えない・話せる人の数に入れない。
    """
    rows = _rom.runtime_view(master.get("npcs", []), slots)
    out = []
    for r in rows:
        if is_hidden(r["runtime"]):
            continue
        m = r["master"]
        out.append({
            "npc_id": m["npc_id"], "slot": m.get("slot"), "x": r["current_x"], "y": r["current_y"],
            "facing": r["current_facing"], "walking": r["walking"], "position_source": "ram" if r["runtime"] else "rom",
            "movement": m["movement"], "appearance_id": m["appearance_id"], "talk_id": m["talk_id"],
            "role": m.get("role"), "role_status": m.get("role_status"),
            # ★差し替え先の表から直した人（RX3-0231 / ★聞いたかは台詞の番号まで見る）
            "variant": m.get("table_npc_id") is not None,
        })
    return out


def role_label(role: str | None) -> str | None:
    return ROLE_LABELS.get(role) if role else None
