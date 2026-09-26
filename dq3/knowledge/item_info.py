"""アイテムの性能を**製品から引く唯一の入口**（RX3-0083 / 2026-09-06）。

```text
dq3rom/item_meta.py   ★ROM の表を読む（構造と番地）
      ↓ ここ
info(item_id)         ★名前 ＋ 分類 ＋ 攻守 ＋ 装備できる人 ＋ 値段 ＋ 印
compare(...)          ★いま装備しているものとの差（＋X / −X）
shop_items(...)       ★店の品揃え
```

## ⚠⚠ 守ること

```text
⚠ ROM が無くても落ちない        ★`available()` が False になるだけ（`rom_names` と同じ作法）
⚠ 名前は repo に持たない        ★実行時に `rom_names` から
⚠ 知らない品の中身を出さない     ★No-Spoiler は**呼ぶ側**が決める（下の注記）
```

## ★No-Spoiler の考え方（⚠ ここでは伏せない）

★性能そのものは「持っている品・店に並んでいる品」を見るためのもので、
⚠ **プレイヤーが見られる場面でしか呼ばれません**（袋・店・装備画面）。
→ ★この層では伏せず、⚠ 「まだ知らない品を一覧で出す」ような使い方をしないこと。
（★敵の図鑑と違い、⚠ 品は「持っていれば必ず見られる」ため。）
"""
from __future__ import annotations

import dataclasses
import pathlib

from dq3rom import item_meta as IM

_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_ROM = _ROOT / "work" / "rom" / "DQ3_J.nes"

_rows: dict | None = None
_shops: list | None = None
_tried = False
last_error: str | None = None


def _load(rom_path=None):
    """★1 度だけ読む。⚠ ROM が無ければ None（★黙らず `last_error` に残す）。"""
    global _rows, _shops, _tried, last_error
    if _tried and rom_path is None:
        return _rows
    _tried = True
    target = pathlib.Path(rom_path) if rom_path else DEFAULT_ROM
    if not target.exists():
        last_error = "ROM がありません: %s" % target
        _rows = _shops = None
        return None
    try:
        from dq3rom import profile as P

        prg = P.load_and_identify(target).rom.prg
        rows = IM.build(prg)
        problems = IM.check(rows)
        if problems:
            raise ValueError("; ".join(problems))
        _rows = {r.item_id: r for r in rows}
        _shops = IM.shops(prg)
        last_error = None
    except Exception as exc:                               # noqa: BLE001 - ★理由を残して None
        last_error = "アイテムの性能を読めません: %s" % exc
        _rows = _shops = None
    return _rows


def available(rom_path=None) -> bool:
    return _load(rom_path) is not None


def reset() -> None:
    """⚠ 検査用（★別の ROM を読み直す）。"""
    global _rows, _shops, _tried, last_error
    _rows = _shops = None
    _tried = False
    last_error = None


#: ★職業の名前（⚠ `class_ids.inc` の定数。★画面から `dq3rom` を触らせないためここにも置く）
CLASS_NAMES = dict(IM.CLASS_NAMES)


def split_class_gender(value) -> tuple:
    """★RAM の 1 バイト → `(職業, 女か)`（⚠ `& 7` と bit3 / RX3-0083）。

    ⚠ 画面（`dq3/ui/`）から `dq3rom` を直に触らせないための入口です
      （★`test_UIはROMの正解を読まない` が見ています）。
    """
    if not isinstance(value, int):
        return (None, True)
    return (value & IM.CLASS_MASK, bool(value & IM.GENDER_BIT))


def meta(item_id, rom_path=None):
    """★生の `ItemMeta`（⚠ 無ければ None）。"""
    rows = _load(rom_path)
    if rows is None or item_id is None:
        return None
    return rows.get(int(item_id) & 0x7F)


@dataclasses.dataclass(frozen=True)
class ItemInfo:
    """★画面に出せる形（⚠ 名前は実行時に ROM から）。"""

    item_id: int
    name: str | None
    category: str
    category_label: str
    pri_stat: int | None
    equip_classes: tuple
    female_only: bool
    buy_price: int
    sell_price: int
    flags: tuple
    equip_buff: int | None

    @property
    def label(self) -> str:
        return self.name or "品 %d" % self.item_id

    @property
    def is_gear(self) -> bool:
        return self.pri_stat is not None

    @property
    def stat_label(self) -> str:
        """★武器なら「攻撃 +N」、防具なら「守備 +N」（⚠ 道具は空）。"""
        if self.pri_stat is None:
            return ""
        head = "攻撃" if self.category == "weapon" else "守備"
        return "%s %d" % (head, self.pri_stat)


#: ★分類の見出し（⚠ 画面用）
CATEGORY_LABEL = {"weapon": "武器", "armor": "よろい", "shield": "たて", "helm": "かぶと",
                  "accessory": "そうしょくひん", "tool_class": "どうぐ（職業）",
                  "item": "どうぐ", "unknown": "？"}

#: ★印の見出し
FLAG_LABEL = {"battle_use": "戦闘で使える", "battle_ref": "戦闘が参照",
              "cannot_discard": "捨てられない", "cursed": "呪い", "consumed": "使うと減る"}

#: ★職業の見出し（⚠ `class_ids.inc` の並び）
CLASS_LABEL = {"hero": "勇", "wizard": "魔", "pilgrim": "僧", "sage": "賢",
               "soldier": "戦", "merchant": "商", "fighter": "武", "goofoff": "遊"}


def info(item_id, rom_path=None) -> ItemInfo | None:
    """★画面に出せる形で 1 件（⚠ 無ければ None）。"""
    from dq3.knowledge import rom_names

    row = meta(item_id, rom_path)
    if row is None:
        return None
    return ItemInfo(
        item_id=row.item_id, name=rom_names.item(row.item_id),
        category=row.category, category_label=CATEGORY_LABEL.get(row.category, row.category),
        pri_stat=row.pri_stat, equip_classes=tuple(row.equip_classes),
        female_only=row.female_only, buy_price=row.buy_price, sell_price=row.sell_price,
        flags=tuple(row.flags), equip_buff=row.equip_buff)


def flag_labels(flags) -> list[str]:
    return [FLAG_LABEL.get(f, f) for f in flags]


def class_labels(classes) -> list[str]:
    return [CLASS_LABEL.get(c, c) for c in classes]


# --- ★装備の比較（指示書 8-1）-------------------------------------------------------

#: ★どの分類がどの枠に入るか（⚠ 1 人 1 枠ずつ）
SLOTS = ("weapon", "armor", "shield", "helm")
SLOT_LABEL = {"weapon": "ぶき", "armor": "よろい", "shield": "たて", "helm": "かぶと"}


@dataclasses.dataclass(frozen=True)
class Compare:
    """★「いま装備しているもの」と「候補」の差。"""

    slot: str
    slot_label: str
    current_id: int | None
    current_name: str | None
    current_stat: int
    candidate_id: int
    candidate_name: str | None
    candidate_stat: int
    equippable: bool
    reason: str = ""

    @property
    def delta(self) -> int:
        return self.candidate_stat - self.current_stat

    @property
    def delta_label(self) -> str:
        """★「+12」「−3」「±0」（⚠ 装備できないなら理由）。"""
        if not self.equippable:
            return self.reason or "装備できない"
        if self.delta > 0:
            return "+%d" % self.delta
        if self.delta < 0:
            return "−%d" % -self.delta
        return "±0"


def all_key_ids() -> list[int]:
    """★鍵の道具 ID ぜんぶ（⚠ 「鍵さえあれば届くか」を試すのに使う）。"""
    from dq3rom import door_keys as _dk

    return sorted(_dk.KEY_ITEMS)


def keys_in(members) -> list[int]:
    """★パーティの袋から、持っている**鍵**の道具 ID（RX3-0078 / 2026-09-07）。

    ⚠⚠ 画面（`dq3/ui/`）は `dq3rom` を直に触りません（`test_UIはROMの正解を読まない`）。
    ★番地とビットの意味はここで引き受けます。

    ⚠ `members` は `view_model.equip_members()` の形（`{"inventory": [...]}`）。
    ⚠ 読めなければ空（★推測で「持っている」ことにしない）。
    """
    from dq3rom import door_keys as _dk

    got: set[int] = set()
    try:
        for row in members or ():
            for item in (row.get("inventory") if isinstance(row, dict) else None) or ():
                # ⚠ bit7 は「装備中」の印（★落としてから見る / RX3-0007）
                item_id = int(item) & 0x7F
                if _dk.rank_of(item_id) is not None:
                    got.add(item_id)
    except (TypeError, ValueError):
        return []
    return sorted(got)


def equipped_ids(inventory: list[int]) -> dict:
    """★袋のバイト列 → 枠ごとの「いま装備しているもの」（⚠ bit7 が立っているものだけ）。"""
    got = {}
    for raw in inventory or ():
        if raw == 0xFF or not (raw & 0x80):
            continue
        item_id = raw & 0x7F
        cat = IM.category_of(item_id)
        if cat in SLOTS:
            got.setdefault(cat, item_id)
        elif cat == "accessory":
            got.setdefault("accessory", item_id)
    return got


def compare(candidate_id, inventory, class_id, female=True, rom_path=None) -> Compare | None:
    """★候補を、その人がいま装備しているものと比べる（⚠ 装備品でなければ None）。"""
    from dq3.knowledge import rom_names

    row = meta(candidate_id, rom_path)
    if row is None or row.category not in SLOTS:
        return None
    slot = row.category
    now_id = equipped_ids(inventory).get(slot)
    now = meta(now_id, rom_path) if now_id is not None else None
    ok = row.equippable_by(class_id, female)
    reason = ""
    if not ok:
        reason = ("その人は装備できない" if row.equip_mask is None
                  or not row.equip_mask & (1 << class_id) else "女性しか装備できない")
    return Compare(
        slot=slot, slot_label=SLOT_LABEL[slot],
        current_id=now_id, current_name=rom_names.item(now_id) if now_id is not None else None,
        current_stat=(now.pri_stat or 0) if now else 0,
        candidate_id=row.item_id, candidate_name=rom_names.item(row.item_id),
        candidate_stat=row.pri_stat or 0, equippable=ok, reason=reason)


def compare_party(candidate_id, members, rom_path=None) -> list[Compare]:
    """★パーティ全員ぶん（⚠ `members` = [{class_id, female, inventory}, ...]）。"""
    out = []
    for m in members or ():
        got = compare(candidate_id, m.get("inventory"), m.get("class_id", 0),
                      m.get("female", True), rom_path)
        if got is not None:
            out.append(got)
    return out


def best_for(candidate_id, members, rom_path=None) -> Compare | None:
    """★いちばん得をする人（⚠ 装備できる人の中から）。"""
    rows = [c for c in compare_party(candidate_id, members, rom_path) if c.equippable]
    return max(rows, key=lambda c: c.delta) if rows else None


# --- ★店（指示書 8-2 の材料）---------------------------------------------------------

#: ★店の種類の見出し
SHOP_ROLE_LABEL = {"weapon_armor_shop": "ぶきや・ぼうぐや", "item_shop": "どうぐや"}


@dataclasses.dataclass(frozen=True)
class Shop:
    """★1 軒の店（⚠ どの map に居るか / 何番の品揃えか）。"""

    map_id: int
    role: str
    shop_index: int
    items: tuple
    location_id: str = ""
    place_name: str | None = None
    visited: bool = False
    #: ⚠ 物語で NPC 表が差し替わる map の店（★条件は HYPOTHESIS / RX3-0090）
    conditional: bool = False

    @property
    def role_label(self) -> str:
        return SHOP_ROLE_LABEL.get(self.role, self.role)

    @property
    def label(self) -> str:
        """★「アリアハン の ぶきや・ぼうぐや」（⚠ 名前を知らなければ map 番号）。

        ⚠ 条件つきの店（★差し替えのある map）には印を付けます。★確かな店と混ぜない。
        """
        where = self.place_name or ("map %d" % self.map_id)
        mark = "⚠ " if self.conditional else ""
        return "%s%s の %s" % (mark, where, self.role_label)


def shops_by_map(rom_path=None) -> dict:
    """★map → その map にある店（⚠ NPC の talk_id から決まる / RX3-0086）。

    ```text
    NPC の talk_id → talk_script.classify → facility_index（★店番号）
                  → item_meta.shop_of    → 品揃え
    ```
    ⚠ NPC 台帳が読めない map は入りません（★推測で足さない）。
    """
    rows = _load(rom_path)
    if rows is None:
        return {}
    from dq3.knowledge import npc_master as NM

    from dq3rom import profile as P

    target = pathlib.Path(rom_path) if rom_path else DEFAULT_ROM
    prg = P.load_and_identify(target).rom.prg
    got: dict = {}
    for map_id in range(NM_MAP_MAX):
        for time_byte in NM.TIMES:                         # ★昼と夜（⚠ RX3-0087）
            try:
                # ★差し替えのある map も既定の表を読む（⚠ 条件つき / RX3-0090）
                master = NM.default_master_for(map_id, time_byte)
            except Exception:                              # noqa: BLE001
                continue
            _collect_shops(got, map_id, master, prg,
                           conditional=master.get("status") != "DEFAULT")
    return got


def shop_of_npc(shops, role: str, talk_id):
    """★店の人（talk_id）の品揃え（RX3-0257 / ★同じ種類の店が 2 軒ある町）。

    ★店番号は `shops_by_map` と同じ道（talk_id → `talk_script.classify` → facility_index）で決める。
    ⚠ 店番号が分からなければ、その種類の先頭（★今までどおり）/ その種類が無ければ None。
    """
    same = [x for x in shops if x.role == role]
    if not same:
        return None
    from dq3.testing import talk_script as TS

    try:
        index = TS.classify(int(talk_id or 0)).get("facility_index")
    except Exception:                                      # noqa: BLE001 ★分からないだけ（先頭へ）
        index = None
    if index is None:
        return same[0]
    return next((x for x in same if getattr(x, "shop_index", None) == index), same[0])


def _collect_shops(got: dict, map_id: int, master: dict, prg: bytes,
                   conditional: bool = False) -> None:
    """★1 つの台帳から店を拾って `got` に足す（⚠ 同じ店番号は 1 回だけ）。"""
    from dq3.testing import talk_script as TS

    for npc in master.get("npcs", []):
        info_ = TS.classify(npc.get("talk_id") or 0)
        if info_.get("role") not in IM.SHOP_ROLES:
            continue
        index = info_.get("facility_index")
        if index is None:
            continue
        try:
            items = IM.shop_of(prg, index)
        except IM.ItemMetaError:
            continue                                       # ⚠ 範囲の外は黙って足さない
        row = Shop(map_id=map_id, role=info_["role"], shop_index=index,
                   items=tuple(items), conditional=conditional)
        if not any(x.shop_index == index for x in got.get(map_id, ())):
            got.setdefault(map_id, []).append(row)


#: ⚠ NPC 台帳を見る map の上限（★DQ3 は 243 面）
NM_MAP_MAX = 250


def visited_shops(book=None, rom_path=None) -> list:
    """★**行った街の店だけ**（⚠ 依頼者の求め / 2026-09-06）。

    ★場所の名前は `location_book` から取ります（⚠ 地名の判定を 2 か所に書かない）。
    ⚠ `book` を渡さなければ、その場で読みます。
    """
    if book is None:
        from dq3.knowledge.location_book import LocationBook

        book = LocationBook.load()
    out = []
    for map_id, rows in sorted(shops_by_map(rom_path).items()):
        loc = book.get_location(map_id)
        if not loc.visited:
            continue                                       # ⚠ 行っていない街は出さない
        for row in rows:
            out.append(dataclasses.replace(
                row, location_id=loc.location_id, place_name=loc.name(detailed=True),
                visited=True))
    return out


def all_shops(book=None, rom_path=None) -> list:
    """★全部の店（⚠ 行っていない街も含む。★管理用）。"""
    if book is None:
        from dq3.knowledge.location_book import LocationBook

        book = LocationBook.load()
    out = []
    for map_id, rows in sorted(shops_by_map(rom_path).items()):
        loc = book.get_location(map_id)
        for row in rows:
            out.append(dataclasses.replace(
                row, location_id=loc.location_id,
                place_name=loc.name(detailed=True) if loc.visited else None,
                visited=loc.visited))
    return out


def shop_lists(rom_path=None) -> list[list[int]]:
    """★店の品揃え（⚠ 並びの種類。★同じ並びを複数の店が使う）。"""
    _load(rom_path)
    return list(_shops or [])


def shop_for(items, rom_path=None) -> list[ItemInfo]:
    """★item_id の並び → 画面に出せる形。"""
    got = [info(i, rom_path) for i in items or ()]
    return [g for g in got if g is not None]


def find_shop(item_ids, rom_path=None) -> int | None:
    """★その並びが何番目の品揃えか（⚠ 見つからなければ None）。"""
    want = list(item_ids or ())
    for i, row in enumerate(shop_lists(rom_path)):
        if row == want:
            return i
    return None
