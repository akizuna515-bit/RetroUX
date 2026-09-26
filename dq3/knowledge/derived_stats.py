"""こうげき力・しゅび力・装備こみの素早さを**ゲームと同じ式で**出す（RX3-0284 / 2026-09-18）。

依頼者 2026-09-18:

    装備を入れ替えた時（装備コマンド）完了後、ステータスが変わるようにしたい。
    DQ2 だとそうなっていた。
    多分素の値を表示している。装備が考慮されていない。
    ほしふるうでわの素早さ倍も反映されていない

## ⚠⚠ なぜ RAM の `$07E9` / `$07F1` ではだめなのか

★`$07F1`（こうげき力）と `$07E9`（しゅび力）は**戦闘バンクだけが書く**値です。

```text
bank 4 $8238-$829C   ★戦闘の頭で 4 人ぶんまとめて作り直す
                       $07E5  = 装備こみの素早さ（1 バイト）
                       $07E9  = しゅび力（2 バイト）
                       $07F1  = こうげき力（2 バイト）
```

⚠ ROM 全体を探しても、この 3 か所に書く命令は **bank 4 にしかありません**。
→ ★つまり町で装備を替えても、**次の戦闘が始まるまで古い値のまま**です。
  ⚠ 「素の値」ではなく「**前の戦闘のときの値**」でした。

★実測（`tests/test_dq3_derived_stats.py::test_セーブの装備から求めた値がRAMと一致する`）:
セーブ 15 本 60 人のうち **55 人が一致**し、⚠ 外れた 5 人はすべて
「前の戦闘のあとに装備を買い替えた人」で、**旧装備の値を入れると RAM とぴたり合います**
（例: `town_romaria_arena_hearing` p2 は てつのやり ＋28 を買った直後で、
RAM の 27 は どうのつるぎ ＋7 のときの値）。

## ★ゲーム自身の式（⚠ 逆アセンブルで確かめた / JP ROM）

```text
bank 0 $9647   ★装備を**分類の順**に 4 つ拾う → $04 武器 / $05 よろい / $06 たて / $07 かぶと
               ⚠ そうしょくひんは拾わない（= しゅび力に入らない）
bank 0 $9465   ★装備こみの素早さ
                 品 $4B（ほしふるうでわ）を装備していれば `ASL` で 2 倍
                 ⚠ 桁あふれしたら $FF で頭打ち
bank 0 $951F   ★しゅび力 = 装備こみの素早さ ÷ 2 ＋ よろい ＋ たて ＋ かぶと
bank 0 $94AE   ★こうげき力 = ちから ＋ 武器
                 ⚠ 武器を持っていなければ ちから のみ
                 ⚠⚠ 職業 6（ぶとうか）だけ別扱い:
                       てつのつめ（$09）        → そのまま足す
                       おうごんのつめ（$4A）    → ＋$37（55）★表の値ではない
                       それ以外の武器          → **ちから − 武器 ÷ 2**（0 で止まる）
bank15 $CCE8   ★攻守の値の表（bank 9 $B990 / `Y` = item_id。★攻守で同じ 1 本）
bank15 $C04B / $C035   ★16 bit の足し算・引き算
```

⚠ ここでは表を持ちません（★`item_info` 経由で ROM から引く）。
⚠ ROM が無ければ `None` を返します（★呼ぶ側は今までどおり RAM の値に戻る）。
"""
from __future__ import annotations

import dataclasses

from . import item_info

#: ★装備すると素早さが 2 倍になる品（ほしふるうでわ）。⚠ 名前は ROM から引くこと
DOUBLE_AGILITY_ITEM = 0x4B

#: ⚠ 2 倍にしたときの頭打ち（★bank 0 $947F が `LDA #$FF`）
AGILITY_MAX = 0xFF

#: ★ぶとうか（`class_ids.inc` の 6）
MONK_CLASS = 6

#: ★ぶとうかでも**そのまま足せる**武器（てつのつめ）
MONK_FULL_WEAPON = 0x09

#: ★ぶとうかが持つと表の値ではなく固定値になる武器（おうごんのつめ → ＋55）
MONK_FIXED_WEAPON = 0x4A
MONK_FIXED_VALUE = 0x37

#: ★`$9647` が拾う順（⚠ この 4 分類だけ。そうしょくひんは入らない）
GEAR_ORDER = ("weapon", "armor", "shield", "helm")

#: ★しゅび力に足す分類
DEFENCE_CATEGORIES = ("armor", "shield", "helm")

#: ⚠ 装備中の印（★`$076C` の bit7）／空き枠
EQUIPPED_BIT = 0x80
EMPTY_SLOT = 0xFF


@dataclasses.dataclass(frozen=True)
class Derived:
    """★装備こみの値（⚠ 画面に出す用の内訳つき）。"""

    attack: int
    defence: int
    agility: int
    #: ★素の素早さ（⚠ 2 倍になっているかを画面で説明するため）
    agility_base: int
    agility_doubled: bool
    strength: int
    #: ★item_id（⚠ 無ければ None）
    weapon: int | None
    #: ★`(分類, item_id, 値)` の並び（よろい・たて・かぶと）
    armor: tuple
    #: ★武器の加算（⚠ ぶとうかの減算なら負）
    weapon_value: int
    #: ⚠ ぶとうかが つめ 以外を持っている（★減っている）
    monk_penalty: bool


def equipped_ids(items) -> list:
    """★装備中の item_id（⚠ 空き枠と持っているだけの品は除く）。"""
    out = []
    for raw in items or ():
        if not isinstance(raw, int) or raw == EMPTY_SLOT:
            continue
        if raw & EQUIPPED_BIT:
            out.append(raw & 0x7F)
    return out


def gear(items, rom_path=None) -> dict:
    """★`$9647` と同じ拾い方（分類ごとに**最初の 1 つ**）。

    ⚠ 同じ分類を 2 つ装備している状態は作れませんが、
      ★ゲームも先頭から探して 1 つで打ち切るので、そこに合わせます。
    """
    ids = equipped_ids(items)
    out = {}
    for category in GEAR_ORDER:
        for item_id in ids:
            got = item_info.meta(item_id, rom_path)
            if got is not None and got.category == category:
                out[category] = item_id
                break
    return out


def _stat(item_id, rom_path=None) -> int:
    got = item_info.meta(item_id, rom_path)
    if got is None or got.pri_stat is None:
        return 0
    return int(got.pri_stat)


def effective_agility(agility, items, rom_path=None) -> tuple:
    """★`(装備こみの素早さ, 2 倍になったか)`（bank 0 $9465）。"""
    base = int(agility or 0)
    if DOUBLE_AGILITY_ITEM in equipped_ids(items):
        return (min(base * 2, AGILITY_MAX), True)
    return (base, False)


def _name(item_id, rom_path=None) -> str:
    """★品の名前（⚠ ROM から。読めなければ番号）。"""
    from . import rom_names

    got = rom_names.item(item_id, rom_path) if item_id is not None else None
    return got or ("品 %s" % item_id)


def explain(got, rom_path=None) -> dict:
    """★画面のヒント用の内訳（⚠ 画面に `dq3rom` を触らせないためここで作る）。

    ⚠ `got` が None なら空の辞書（★呼ぶ側はヒントを出さない）。
    """
    if got is None:
        return {}
    if got.weapon is None:
        attack = "こうげき力 %d ＝ ちから %d（武器なし）" % (got.attack, got.strength)
    elif got.monk_penalty:
        attack = ("こうげき力 %d ＝ ちから %d − %s の半分（⚠ ぶとうかは つめ 以外だと下がる）"
                  % (got.attack, got.strength, _name(got.weapon, rom_path)))
    else:
        attack = ("こうげき力 %d ＝ ちから %d ＋ %s %d"
                  % (got.attack, got.strength, _name(got.weapon, rom_path),
                     got.weapon_value))
    parts = ["すばやさ %d の半分 %d" % (got.agility, got.agility // 2)]
    parts += ["%s %d" % (_name(i, rom_path), v) for _c, i, v in got.armor]
    defence = "しゅび力 %d ＝ %s" % (got.defence, " ＋ ".join(parts))
    if got.agility_doubled:
        agility = ("すばやさ %d ＝ %d の 2 倍（%s）"
                   % (got.agility, got.agility_base,
                      _name(DOUBLE_AGILITY_ITEM, rom_path)))
    else:
        agility = "すばやさ %d" % got.agility
    note = "★装備から計算しています（⚠ ゲームの内部値は次の戦闘まで古いまま）"
    return {"attack": attack + "\n" + note,
            "defence": defence + "\n" + note,
            "agility": agility + "\n" + note}


def compute(member, rom_path=None):
    """★`state.json` の 1 人 → `Derived`（⚠ 読めなければ None）。

    ⚠ `member` は辞書でも属性つきでも受けます（★`_Dq3Member` をそのまま渡せる）。
    """
    def pick(name):
        if isinstance(member, dict):
            return member.get(name)
        return getattr(member, name, None)

    items = pick("items")
    if not items or not item_info.available(rom_path):
        return None
    strength = pick("strength")
    agility = pick("agility")
    if strength is None or agility is None:
        return None
    class_id, _female = item_info.split_class_gender(pick("class_gender"))

    got = gear(items, rom_path)
    agility_eff, doubled = effective_agility(agility, items, rom_path)

    weapon = got.get("weapon")
    strength = int(strength)
    if weapon is None:
        weapon_value = 0
        monk_penalty = False
    elif class_id != MONK_CLASS or weapon == MONK_FULL_WEAPON:
        weapon_value = _stat(weapon, rom_path)
        monk_penalty = False
    elif weapon == MONK_FIXED_WEAPON:
        weapon_value = MONK_FIXED_VALUE
        monk_penalty = False
    else:
        # ⚠⚠ ぶとうかが つめ 以外を持つと**減る**（★bank 0 $94F5-$9504）
        weapon_value = -(_stat(weapon, rom_path) // 2)
        monk_penalty = True

    armor = tuple((c, got[c], _stat(got[c], rom_path))
                  for c in DEFENCE_CATEGORIES if c in got)
    return Derived(
        attack=max(0, strength + weapon_value),
        defence=agility_eff // 2 + sum(v for _c, _i, v in armor),
        agility=agility_eff,
        agility_base=int(agility),
        agility_doubled=doubled,
        strength=strength,
        weapon=weapon,
        armor=armor,
        weapon_value=weapon_value,
        monk_penalty=monk_penalty,
    )
