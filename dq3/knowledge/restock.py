"""補充（リストック）の**計画**（RX3-0066 / 2026-09-08）。

★DQ2 には完成した補充があります（`retroux/plugins/dq2/restock.lua` / 853 行）。
⚠ ゼロから別仕様を作らず、★そこから**考え方**だけを移しました。

```text
★移した      欲しい数 / いまの数 / 差分 / 削り方 / 安全停止の並び / ログの粒度
⚠ 移さない   DQ2 固有の RAM 番地・窓番号・行の並び（★DQ3 とは違う）
```

## ⚠⚠ ここは**ボタンを 1 つも押しません**

```text
★この層          いまの数 → 目標との差分 → 買う計画 → 安全停止 → 1 行サマリー
★restock_v0.lua  店主に話す / 窓を選ぶ / 買う / 買えたか確かめる（RX3-0119）
```

⚠ 押すのは Lua です。★ここは「何をいくつ買うか」だけを決め、
`to_params()` で**語のタイル列**として渡します（⚠ Lua は文字コード表を持たない）。

## ★DQ2 との差（⚠ 移植でつまずくところ）

```text
              DQ2                          DQ3
装備中の印    bit6（0x40）                 ⚠⚠ **bit7（0x80）**
空き枠        nil または 0                 ⚠⚠ **0xFF**（★0 は「ひのきのぼう」）
袋            1 人 8 枠                    ★同じ 8 枠
持ち主        買うたびに聞かれる           ⚠ 未確認（★`RX3-0119` で見る）
```

⚠⚠ **`& 0x3F` をそのまま持ってこないこと。** ★DQ3 で使うと、
`0x40` 以上の道具（★鍵・オーブなど）が**全部ずれます**。

## ★安全停止の並び（⚠ DQ2 と同じ考え）

⚠ 「押してから気づく」をやめます。★**押す前に**すべて決めます。

```text
1 戦闘中            ⚠ 触らない
2 補充リストが空    ⚠ 何を買うか決まっていない
3 店が扱っていない  ⚠ ボタンを 1 つも押さずに終わる
4 もう足りている    ★同上
5 所持金が足りない  ⚠ 買える数まで削る（★0 なら止まる）
6 袋に空きが無い    ⚠ 同上
```
"""

from __future__ import annotations

import dataclasses

#: ⚠⚠ **bit7 = 装備中**（★DQ2 は bit6。ここが移植の落とし穴）
EQUIPPED_BIT = 0x80

#: ⚠⚠ **空き枠は `0xFF`**（★`0` は「ひのきのぼう」= 実在の道具）
EMPTY_SLOT = 0xFF

#: ★1 人ぶんの袋の枠数（⚠ `dev.lua` の `PARTY.item_slots` と同じ）
ITEM_SLOTS = 8

#: ★1 回の補充で買う上限（⚠ 際限なく押し続けない / DQ2 と同じ考え）
MAX_PURCHASES = 12

#: ★v0 の対象（⚠ 消耗品だけ。★装備品の自動購入は対象外 / WI の Scope）
#:
#: ⚠ ID は 2026-09-08 に ROM から採りました（★推測ではありません）。
#: ★名前が合っているかは `test_dq3_restock.py` が ROM に聞いて確かめます。
HERB = 101          #: やくそう
ANTIDOTE = 102      #: どくけしそう
HOLY_WATER = 103    #: せいすい
WING = 104          #: キメラのつばさ

#: ★目標の数（⚠ 人が決めるもの / Non-Goals。★ここは既定値だけ）
DEFAULT_WANTS = ((HERB, 6), (ANTIDOTE, 2), (WING, 1))

#: ★安全停止の理由（⚠ **内部の語**。人へはこのまま出さない）
NO_WANTS = "no_wants"
IN_BATTLE = "in_battle"
NOT_SOLD = "not_sold"
ENOUGH = "enough"
NO_GOLD = "no_gold"
NO_SLOT = "no_slot"

#: ★人へ出す言い方（⚠ `action_log` の「生の値を出さない」に合わせる）
STOP_TEXT = {
    NO_WANTS: "何を買うか決まっていません",
    IN_BATTLE: "戦闘中なので何もしません",
    NOT_SOLD: "この店は欲しいものを扱っていません",
    ENOUGH: "足りているので買いません",
    NO_GOLD: "お金が足りません",
    NO_SLOT: "袋がいっぱいです",
}


@dataclasses.dataclass(frozen=True)
class Want:
    """★「これを何個持っていたい」（⚠ 何を買うかは人が決める / Non-Goals）。"""

    item_id: int
    want: int


@dataclasses.dataclass(frozen=True)
class Line:
    """★買う計画 1 品。"""

    item_id: int
    name: str
    price: int
    have: int
    need: int
    buy: int

    @property
    def cost(self) -> int:
        return self.price * self.buy


@dataclasses.dataclass
class Plan:
    """★計画ぜんぶ（⚠ 画面へはこれだけを渡す）。"""

    lines: list = dataclasses.field(default_factory=list)
    #: ⚠ 買えなかったもの・足りているもの（★理由つき）
    notes: list = dataclasses.field(default_factory=list)
    #: ⚠ 1 個も買えないときの理由（★`STOP_TEXT` の鍵）
    stop: str | None = None
    gold: int = 0
    free_slots: int = 0

    @property
    def total_cost(self) -> int:
        return sum(l.cost for l in self.lines)

    @property
    def total_buy(self) -> int:
        return sum(l.buy for l in self.lines)

    def is_empty(self) -> bool:
        """★1 個も買わない（⚠ **ボタンを押さずに終わる**）。"""
        return not self.lines

    def summary(self) -> str:
        """★人へ出す 1 行（⚠ 数字は「個」「G」だけ。★生の値を混ぜない）。

        ⚠⚠ `action_log` が `key=value` や `0x1F` を弾くので、
        ★ここでも同じ書き方をします（⚠ 内部の理由語は出さない）。
        """
        if self.is_empty():
            return STOP_TEXT.get(self.stop or "", "買うものがありません")
        bits = ["%s %d個" % (l.name, l.buy) for l in self.lines]
        head = "%s（%d G）" % ("／".join(bits), self.total_cost)
        return head + ("　※ " + "／".join(self.notes) if self.notes else "")

    def status(self):
        """★`ActionSummary` の状態（⚠ 買えない = 失敗ではない / 「停止」）。"""
        from ..action_log import CANCELLED, PARTIAL, SUCCESS

        if self.is_empty():
            return CANCELLED
        return PARTIAL if self.notes else SUCCESS

    def as_summary(self):
        """★`ActionSummary` 1 件（⚠ 内部の値は `detail` へ / RX3-0110）。"""
        from ..action_log import ActionSummary

        return ActionSummary(
            action="restock", status=self.status(), message=self.summary(),
            detail={"stop": self.stop, "gold": self.gold, "free_slots": self.free_slots,
                    "lines": [dataclasses.asdict(l) for l in self.lines]})


# ----------------------------------------------------------------------
# ★袋を読む（⚠ 装備中の印と空き枠の値が DQ2 と違う）
# ----------------------------------------------------------------------

def _bag(member) -> list:
    got = member.get("inventory") if isinstance(member, dict) else None
    return list(got or ())[:ITEM_SLOTS]


def count_have(members, item_id: int) -> int:
    """★パーティ全体で何個持っているか（⚠ 装備中も 1 個と数える）。

    ⚠⚠ DQ2 は `& 0x3F` でしたが、★DQ3 は **bit7** です。
    ⚠ `0x3F` で切ると、★`0x40` 以上の道具が別の道具になります。
    """
    want = int(item_id) & ~EQUIPPED_BIT
    n = 0
    for m in members or ():
        for raw in _bag(m):
            try:
                got = int(raw)
            except (TypeError, ValueError):
                continue
            if got == EMPTY_SLOT:
                continue
            if (got & ~EQUIPPED_BIT) == want:
                n += 1
    return n


def free_slots(members) -> int:
    """★袋の空き（⚠ `0xFF` だけが空き。★`0` は道具）。"""
    n = 0
    for m in members or ():
        bag = _bag(m)
        n += sum(1 for raw in bag if _is_empty(raw))
        # ⚠ 送られてこなかった枠は**空きと見なさない**（★推測で買わない）
    return n


def _is_empty(raw) -> bool:
    try:
        return int(raw) == EMPTY_SLOT
    except (TypeError, ValueError):
        return False


def _free_of(member) -> int:
    """★1 人ぶんの空き（⚠ `0xFF` だけ。★送られてこない枠は数えない）。"""
    return sum(1 for raw in _bag(member) if _is_empty(raw))


def _alive_of(member):
    """★生きているか（⚠ 分からなければ `None`。★推測で決めない）。

    ⚠ `view_model.equip_members()` は今のところ HP を載せていません。
    → ★`alive` か `hp` が来たときだけ使い、⚠ 来なければ「並びの早い人」に倒します。
    """
    if not isinstance(member, dict):
        return None
    if member.get("alive") is not None:
        return bool(member.get("alive"))
    hp = member.get("hp")
    if hp is None:
        return None
    try:
        return int(hp) > 0
    except (TypeError, ValueError):
        return None


def carriers(members, n: int) -> list:
    """★買う 1 個ごとの持ち主（RX3-0202 / 2026-09-12）。★戻り値は並びの位置の列。

    > 「save8 補充で誰かの持ち物がいっぱいな時の対応がない。
    >   DQ2のような対応が必要（平均的に所持）」（依頼者 2026-09-12）

    ⚠⚠ 以前は `carrier()` の **1 人**を全部の購入に使っていました。
      ★その人が途中で満杯になると、実機は
      「でも ○○さんは それいじょう ものを もてないようですよ。」と聞き返し、
      ⚠ Lua はそれを知らずに `not_bought` で止まっていました。

    ★DQ2 の `_pick_carrier`（`retroux/plugins/dq2/restock.lua`）と同じ決まりを、
      **1 個ごとに**当てはめます（⚠ 選んだ人の空きを 1 つ減らしてから次を選ぶ）:

    ```text
    1 空きが最も多い人（⚠ 空き 0 の人は選ばない）
    2 同じなら生きている人（★分かるときだけ）
    3 さらに同じなら並びの早い人
    ```

    例（save8）: 空き あかり 2 / ハンソロ 3 / エルシト 4 / ロミオ 0 で 6 個
      → エルシト, ハンソロ, エルシト, あかり, ハンソロ, エルシト

    ⚠ 空きが尽きたら**そこで短くなります**（★`n` 個に届かない = 袋がいっぱい）。
    """
    rows = list(members or ())
    free = [_free_of(m) for m in rows]
    alive = [_alive_of(m) for m in rows]
    out = []
    for _ in range(max(0, int(n or 0))):
        best = None
        for pos, got in enumerate(free):
            if got <= 0:
                continue
            if (best is None or got > free[best]
                    or (got == free[best] and alive[pos] is True and alive[best] is not True)):
                best = pos
        if best is None:
            break                                   # ⚠ 誰にも空きが無い（★推測で押さない）
        out.append(best)
        free[best] -= 1
    return out


def carrier(members):
    """★買ったものを持たせる相手（⚠ 空きが最も多い人 / DQ2 の依頼者要望）。

    ⚠ これは **1 個目**の持ち主だけです（RX3-0202）。★2 個目からは `carriers()` が
      1 個ごとに選び直します（⚠ 同じ人に積み続けると満杯で止まる）。

    戻り値: `(並びの位置, 名前, 空き数)`。⚠ 空きが無ければ `(None, None, 0)`。
    """
    got = carriers(members, 1)
    if not got:
        return (None, None, 0)
    m = list(members)[got[0]]
    return (got[0], (m.get("name") if isinstance(m, dict) else None), _free_of(m))


# ----------------------------------------------------------------------
# ★計画（⚠⚠ **ボタンを押す前に全部決める** / DQ2 と同じ）
# ----------------------------------------------------------------------

def build_plan(members, shop_items, wants=None, *, gold: int = 0, keep_gold: int = 0,
               max_purchases: int = MAX_PURCHASES, in_battle: bool = False,
               rom_path=None) -> Plan:
    """★何を何個買うかを決める（⚠ 実際には買いません）。

    `members`    … `view_model.equip_members()` の形（`{"name", "inventory"}`）
    `shop_items` … ★その店の品揃え（`item_info.Shop.items`）
    `wants`      … ★`Want` か `(item_id, 個数)` の並び（⚠ 空なら止まる）
    `keep_gold`  … ⚠ 残しておくお金（★宿代などに使う）
    """
    from . import item_info as II

    plan = Plan(gold=int(gold or 0), free_slots=free_slots(members))
    if in_battle:
        plan.stop = IN_BATTLE
        return plan
    rows = _wants(wants)
    if not rows:
        plan.stop = NO_WANTS
        return plan

    sold = {int(i) for i in (shop_items or ())}
    budget = plan.gold - max(0, int(keep_gold or 0))
    reasons = []
    for want in rows:
        have = count_have(members, want.item_id)
        need = max(0, int(want.want) - have)
        got = II.info(want.item_id, rom_path)
        name = got.label if got is not None else ("品 %d" % want.item_id)
        if want.item_id not in sold:
            if need > 0:
                plan.notes.append("%s は置いていません" % name)
                reasons.append(NOT_SOLD)
            continue
        if need == 0:
            reasons.append(ENOUGH)
            continue
        price = int(getattr(got, "buy_price", 0) or 0)
        # ⚠ 買える数まで削る（★お金 → 袋 → 1 回の上限。⚠ 削っても止めない）
        affordable = (budget - plan.total_cost) // price if price > 0 else 0
        buy = max(0, min(need, affordable,
                         plan.free_slots - plan.total_buy,
                         max_purchases - plan.total_buy))
        if buy > 0:
            plan.lines.append(Line(item_id=want.item_id, name=name, price=price,
                                   have=have, need=need, buy=buy))
        if buy < need:
            plan.notes.append("%s は %d個 足りません" % (name, need - buy))
            reasons.append(NO_GOLD if affordable < need else NO_SLOT)
    if plan.is_empty():
        # ★「なぜ 1 個も買わないか」を 1 つだけ選ぶ（⚠ 並びが優先順）
        for why in (NOT_SOLD, NO_GOLD, NO_SLOT, ENOUGH):
            if why in reasons:
                plan.stop = why
                break
        else:
            plan.stop = ENOUGH
    return plan


def to_params(plan: Plan, members=None, *, carrier_pos=None, trade_word: str = "かいにきた",
              rom_path=None) -> dict:
    """★計画 → 実機への頼みごと（RX3-0119 / 2026-09-08）。

    ```text
    restock  trade="<かいにきた のタイル>"
             items="<品のタイル>:<個数>:<値段>,..."
             carrier="<0-3>"                 ★1 個目の持ち主（⚠ 古い Lua 向けに残す）
             carriers="<0-3>,<0-3>,..."      ★1 個ごとの持ち主（RX3-0202）
             full="<もてない のタイル>"      ⚠ 満杯と聞き返されたら いいえ で止める
    ```

    ## ⚠ なぜタイル列を渡すのか

      ★Lua は文字コード表を持ちません。⚠ 行番号を計算すると、
      並びが違ったときに**別の品を買います**。
      → ★語のタイル列を渡し、⚠ Lua は**画面から探して**その行へ寄せます
        （まんたんと同じ約束）。

    ## ⚠⚠ 持ち主は「空きがいちばん多い人」

      ★先頭のまま押すと、実機はこう言いました（2026-09-08 実測）:
      「でも あかりさんは それいじょう ものを もてないようですよ。」

    ## ⚠⚠ 持ち主は **1 個ごとに**選び直す（RX3-0202 / 2026-09-12）

      > 「save8 補充で誰かの持ち物がいっぱいな時の対応がない。
      >   DQ2のような対応が必要（平均的に所持）」

      ★`carriers` に購入の数だけ並べます（`carriers()` / DQ2 の `_pick_carrier`）。
      ⚠ `build_plan` は袋の空きの合計までしか買わないので、★列の長さ = 買う数です。
      ⚠ `carrier_pos` で名指ししたときは列を送りません（★Lua は `carrier` を使い、
        満杯なら RAM を見て選び直します）。
    """
    from ..phase0.generate_lua import tile_bytes

    charset = _charset()
    order = [] if carrier_pos is not None else carriers(members, plan.total_buy)
    if carrier_pos is not None:
        pos = carrier_pos
    else:
        pos = order[0] if order else None
    rows = []
    for line in plan.lines:
        tiles = tile_bytes(line.name, charset)
        rows.append("%s:%d:%d" % ("".join("%02X" % b for b in tiles), line.buy, line.price))
    def hexed(word):
        return "".join("%02X" % b for b in tile_bytes(word, charset))

    return {"trade": hexed(trade_word), "items": ",".join(rows),
            "carrier": str(int(pos or 0)),
            # ★RX3-0202: 1 個ごとの持ち主（⚠ `carrier` と同じ「並びの位置」）
            "carriers": ",".join(str(int(p)) for p in order),
            # ⚠ それでも満杯と言われたら「いいえ」で答えて止める（★窓を開けたままにしない）
            "full": hexed("もてない"),
            # ⚠ 買ったあと「まだ なにか おもとめですか？」と聞かれます（★実機 2026-09-08）
            "yes": hexed("はい"), "no": hexed("いいえ")}


def _charset() -> dict:
    """★文字コード表（⚠ 画面を読むのと**同じもの** / `dq3rom` の profile）。"""
    import json
    import pathlib

    from retroux.core.text import Charset

    root = pathlib.Path(__file__).resolve().parents[2]
    got = json.loads((root / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
                     .read_text(encoding="utf-8"))["text"]
    return Charset(got).table


def _wants(wants) -> list:
    out = []
    for row in (wants if wants is not None else DEFAULT_WANTS):
        if isinstance(row, Want):
            got = row
        elif isinstance(row, dict):
            got = Want(int(row["item_id"]), int(row.get("want") or 0))
        else:
            item_id, want = row
            got = Want(int(item_id), int(want))
        if got.want > 0:
            out.append(got)
    return out


__all__ = ["Want", "Line", "Plan", "build_plan", "count_have", "free_slots", "carrier",
           "carriers",
           "STOP_TEXT", "ITEM_SLOTS", "EQUIPPED_BIT", "EMPTY_SLOT", "MAX_PURCHASES",
           "NO_WANTS", "IN_BATTLE", "NOT_SOLD", "ENOUGH", "NO_GOLD", "NO_SLOT"]
