"""扉と鍵 — ★どの扉を、誰の、どの鍵で開けるか（RX3-0159 / 2026-09-11）。

## ★依頼者の注意（2026-09-11）

> まだ盗賊の鍵しかないが、扉の種類に応じて使う道具が異なるし、
> 誰がどの鍵を持っているかの把握も必要なので注意。

→ ★この 2 つを**ここで**決めます（⚠ 画面にも Lua にも書き写さない）。

```text
扉の種類   $0B（どの鍵でも）/ $0C（まほうのかぎ以上）/ $0D（さいごのかぎだけ）
鍵の段位   とうぞく 0 / まほう 1 / さいご 3            ★dq3rom/door_keys.py（ROM で確定）
持ち主     ★袋（state.json の party[].items）を 1 人ずつ見る
```

## ★選び方

```text
1 その扉を開けられる鍵だけを候補にする（★ROM の判定 `door_keys.opens`）
2 ★いちばん強い鍵を選ぶ（★鍵は上位互換: さいごのかぎ ＞ まほうのかぎ ＞ とうぞくのかぎ）
3 同じ鍵なら★並びの前の人・袋の前
```

★2026-09-13（RX3-0244）依頼者「ドラクエ３はカギは上位互換 さいごのカギ＞まほうのカギ＞とうぞくのかぎ
聞き込みのときも、そのように動かしたい」: ⚠ 以前は「いちばん弱い鍵」（RX3-0159）。
★上位の鍵は下位の扉も開けるので、扉ごとに鍵や持ち主が変わらず、下位の鍵を手放しても同じに動く。
★経路（`RomMap.bfs` → `door_open`）は前から持っている鍵のいちばん強い段位で見ている（★上位互換は同じ）。

★鍵は使っても**減りません**（★実測 2026-09-11 / slot 4: 使う前後で袋が
`[2, 48, 101, 69, 56, 88, 34]` のまま）。→ ★同じ鍵を何度でも選んでよい。

## ⚠ 画面は dq3rom を直に触りません

★`test_UIはROMの正解を読まない`: `dq3/ui/` からはここを通します（`item_info` と同じ約束）。
"""
from __future__ import annotations

import dataclasses

#: ★道具を使う窓で選ぶ語（⚠ 画面に出るとおり）
USE_WORD = "つかう"


@dataclasses.dataclass(frozen=True)
class KeyHold:
    """★誰の袋の何番目に、どの鍵があるか。"""

    member: int          #: ★並びの番号（0 始まり）
    item_id: int
    rank: int            #: ★段位（とうぞく 0 / まほう 1 / さいご 3）
    bag_row: int         #: ★袋の中の順番（0 始まり / ⚠ 画面の並びと同じ / RX3-0159 実測）
    name: str | None     #: ★ROM の名前（⚠ 引けなければ None）


def key_holders(members) -> list[KeyHold]:
    """★パーティの袋から、鍵を**持ち主つき**で拾う。

    ⚠ `members` は `view_model.equip_members()` の形（`{"inventory": [...]}`）。
    ⚠ 読めなければ空（★推測で「持っている」ことにしない）。
    """
    from dq3rom import door_keys as _dk

    from . import rom_names as RN

    out: list[KeyHold] = []
    for index, row in enumerate(members or ()):
        if not isinstance(row, dict):
            continue
        bag = [int(x) for x in (row.get("inventory") or ()) if int(x) != 0xFF]
        for pos, raw in enumerate(bag):
            item_id = raw & 0x7F                       # ⚠ bit7 は「装備中」の印
            rank = _dk.rank_of(item_id)
            if rank is None:
                continue
            out.append(KeyHold(member=index, item_id=item_id, rank=rank, bag_row=pos,
                               name=RN.item(item_id)))
    return out


def key_for_door(nibble, holders) -> KeyHold | None:
    """★その扉を開けられる鍵のうち、**いちばん強いもの**（⚠ 無ければ None / RX3-0244 上位互換）。"""
    from dq3rom import door_keys as _dk

    if nibble is None:
        return None
    usable = [h for h in holders or () if _dk.opens(int(nibble), h.rank)]
    if not usable:
        return None
    return min(usable, key=lambda h: (-h.rank, h.member, h.bag_row))


def door_on_path(rom, cells, opened=()) -> tuple[int, tuple[int, int], int] | None:
    """★経路の上で、**最初の閉じた扉**（⚠ 無ければ None）。

    戻り値: `(経路の何歩目か, (x, y), 扉の種類)`。
    ⚠ `opened` はこの場で開けた扉（★ROM の地図は扉のままなので、自分で覚える）。
    """
    done = {tuple(c) for c in opened or ()}
    for k, cell in enumerate(cells or ()):
        xy = (int(cell[0]), int(cell[1]))
        if xy in done:
            continue
        nibble = rom.door_nibble(*xy)
        if nibble is not None:
            return k, xy, int(nibble)
    return None


def use_params(hold: KeyHold) -> dict:
    """★Lua の `use_item` へ渡す形（★語はタイル列 / ⚠ 行番号は渡さない）。

    ```text
    use_item  member="<1-4>"  item="<鍵の名前のタイル>"  choose="<つかう のタイル>"
    ```

    ⚠ 行番号を渡さないのは、★並びが違ったときに**別の道具を使う**からです（補充と同じ約束）。
    ★Lua は画面で名前を探し、⚠ **カーソルがその名前を指したときだけ** A を押します。
    """
    from ..phase0.generate_lua import tile_bytes
    from .restock import _charset

    if not hold.name:
        raise ValueError("⚠ 鍵の名前を ROM から引けません（道具 %d）" % hold.item_id)
    charset = _charset()

    def hexed(word: str) -> str:
        return "".join("%02X" % b for b in tile_bytes(word, charset))

    return {"member": str(hold.member + 1), "item": hexed(hold.name),
            "choose": hexed(USE_WORD)}


__all__ = ["KeyHold", "key_holders", "key_for_door", "door_on_path", "use_params",
           "USE_WORD"]
