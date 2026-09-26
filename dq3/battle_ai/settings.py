"""戦闘 AI の設定（RX3-0126 / RX3-0127 / 2026-09-08）。

## ★人が触るのは 3 つだけ（指示書 §3 / §8 / §13）

```text
作戦     速攻 / リソース節約 / 生存優先              ★右画面と AI 設定の窓（毎日変える）
役割     各キャラの 第1 / 第2（5 つから）            ★AI 設定の窓
MP 制約  おまかせ / 半分程度残す / 使用禁止           ★AI 設定の窓（★作戦より優先）
```

★RX3-0198（2026-09-12）: 画面の「レベル上げ」は「速攻」へ（⚠ 内部の語 `leveling` は保つ）。
★作戦・MP 制約・役割は**別々の軸**（⚠ 作戦ごとに役割や MP を持たない / 指示書 §4）。
★人が決めた役割は**第1・第2 を別々に**覚える（§15 / 保存は `battle_ai.v2`、`v1` から移し替える）。

⚠⚠ **数値は置かない**（指示書 §16）。★内部の閾値は Lua 側の設定に持つ。

## ⚠ 役割は「制限」ではなく「優先度」（§8）

★第1 → 第2 → 必要ならその他の実行可能な役割、の順で割り当てる。
⚠ 「元僧侶の戦士」が緊急時に臨時ヒールになれる、を表現するため。
"""
from __future__ import annotations

import dataclasses

#: ★作戦（★内部の語。⚠ 画面には `STRATEGY_LABELS`）
LEVELING = "leveling"
ECONOMY = "economy"
SURVIVAL = "survival"
STRATEGIES = (LEVELING, ECONOMY, SURVIVAL)
#: ⚠⚠ 2026-09-20（RX3-0327）: 「速攻」→「**最短撃破**」。
#:   ★内部の語 `leveling` は変えません（⚠ 保存・記録・生成物・過去のログが全部これ）。
#:   ★過去のログの読み替えは `dq3/battle_ai/coverage.py` の `STRATEGY_ALIASES`。
STRATEGY_LABELS = {LEVELING: "最短撃破", ECONOMY: "リソース節約", SURVIVAL: "生存優先"}
STRATEGY_NOTES = {
    LEVELING: ("リソース消費を考慮せず、現在の戦闘をできるだけ早く終わらせます。"
               + chr(10) + "★MP 制約は使いません（⚠ 呪文がかき消される場所では唱えません）"),
    ECONOMY: "MP と消費アイテムを残します。★呪文は効果がはっきり大きい時だけ（⚠ 禁止ではありません）",
    SURVIVAL: "死者・全滅を避けます。★回復・支援を早めに、危険な敵から倒します",
}

#: ★作戦の意味（指示書 §6 / AI 設定の窓の「この作戦では」に常時出す）。⚠ 判断は Lua 側、ここは人向けの言葉
BEHAVIOR_ROWS = ("攻撃魔法", "回復", "支援", "MP消費", "狙う敵")
STRATEGY_BEHAVIOR = {
    LEVELING: ("手数が減るなら", "終わらせられる時は後回し", "手数が減るなら", "考慮しない",
               "倒しやすい敵から"),
    ECONOMY: ("必要な時だけ", "やや遅め", "長引く時", "抑える", "倒しやすい敵から"),
    SURVIVAL: ("危険を減らす時", "早め", "早め", "生存のため使用", "危険な敵から"),
}

#: ★役割（5 つ / §6）
PHYSICAL = "physical"
MAGIC = "magic"
SUPPORT = "support"
HEAL = "heal"
DEFEND = "defend"
ROLES = (PHYSICAL, MAGIC, SUPPORT, HEAL, DEFEND)
ROLE_LABELS = {PHYSICAL: "物理攻撃", MAGIC: "魔法攻撃", SUPPORT: "支援", HEAL: "ヒール",
               DEFEND: "防御"}

#: ★MP 制約（§13）
MP_AUTO = "auto"
MP_SAVE = "save"
MP_FORBID = "forbid"
MP_POLICIES = (MP_AUTO, MP_SAVE, MP_FORBID)
MP_LABELS = {MP_AUTO: "おまかせ", MP_SAVE: "半分程度残す", MP_FORBID: "使用禁止"}
MP_NOTES = {MP_AUTO: "★作戦に任せます（足りれば使います）",
            MP_SAVE: "★使ったあとに最大 MP の半分が残る時だけ使います（⚠ 蘇生は例外）",
            MP_FORBID: "⚠ 呪文を一切使いません（回復は やくそう）。★生存優先でも解除しません"}

#: ★★ 最短撃破で MP 制約を使わないときの注記（RX3-0327 / 依頼者 §12-2）
MP_UNUSED_NOTE = "★最短撃破ではMP制約を使用しません（⚠ 設定は残します）"

#: ★MP 制約を使わない作戦（⚠ ここ 1 か所で決める / 画面と生成物の両方が見る）
MP_FREE_STRATEGIES = (LEVELING,)


def effective_mp(strategy: str, mp_policy: str) -> str:
    """★★ Lua へ渡す **実効の** MP 制約（RX3-0327）。

    依頼者 2026-09-20:

        最短撃破では おまかせ / 半分程度残す / 使用禁止 を無視する。
        ただし、設定値そのものは保存しておく。別作戦へ戻した際に元の設定を復元する。

    ⚠⚠ **保存値は書き換えません。** ★渡す値だけを差し替えます
      （役割の `touched` と同じ思想 / ⚠ 作戦を往復すると人の選択が消える事故を防ぐ）。

    ⚠⚠ ゲーム側の `forbid`（呪文がかき消される床 / `auto_v0.lua` が実行時に入れる）は
      **ここを通りません**。★あれは人の設定ではなく「唱えられない」という事実です。
    """
    if strategy in MP_FREE_STRATEGIES:
        return MP_AUTO
    return mp_policy


def mp_is_used(strategy: str) -> bool:
    """★その作戦で MP 制約の欄を触れるか（⚠ 画面の非活性はこれで決める）。"""
    return strategy not in MP_FREE_STRATEGIES

#: ★パーティの枠
SLOTS = ("p1", "p2", "p3", "p4")
#: ★役割の欄（第1 / 第2）
FIRST = "first"
SECOND = "second"
TIERS = (FIRST, SECOND)

#: ★設定の置き場（`work/dq3-ui-settings.json` の節）
SECTION = "battle_ai"


@dataclasses.dataclass(frozen=True)
class RolePref:
    """★1 人の 第1 / 第2 役割（⚠ 無ければ None = AI が提案する）。"""

    first: str | None = None
    second: str | None = None

    def as_list(self) -> list:
        return [self.first or "", self.second or ""]

    def tier(self, tier: str):
        return self.first if tier == FIRST else self.second

    def with_tier(self, tier: str, role) -> "RolePref":
        role = role if role in ROLES else None
        return dataclasses.replace(self, **{FIRST if tier == FIRST else SECOND: role})


def _touch_key(slot, tier) -> tuple:
    return (slot, tier)


def _clean_touched(pairs) -> tuple:
    """★(枠, 欄) の組を並べ直す（⚠ 知らない枠・欄は捨てる）。"""
    got = {(s, t) for s, t in pairs if s in SLOTS and t in TIERS}
    return tuple(sorted(got, key=lambda p: (SLOTS.index(p[0]), TIERS.index(p[1]))))


@dataclasses.dataclass(frozen=True)
class BattleAiSettings:
    strategy: str = ECONOMY
    mp_policy: str = MP_AUTO
    roles: dict = dataclasses.field(default_factory=dict)     #: slot -> RolePref
    #: ★人が触った役割の欄 = (枠, 欄) の組（⚠ AI の提案で上書きしない / §15・§17）。
    #:   ★第1 だけ触ったなら、第2 は提案のまま変わり続ける
    touched: tuple = ()
    #: ★★ 作戦ごとに「**AI に使わせない呪文**」の ID（RX3-0370 / 2026-09-22）。
    #:
    #:   ⚠⚠ 依頼者「勇者がギガデインを使いすぎる。AI 判断は難しいので、
    #:     **使わない呪文をモード毎に設定**するのが良い」。
    #:
    #:   ★`{作戦: frozenset(呪文 ID)}`。⚠ **無い ＝ 使ってよい**（★新しく覚えた呪文は自動で使える）。
    #:   ⚠ 「使う呪文の一覧」ではなく「**使わない呪文の一覧**」で持つのは、
    #:     ★そうしないと転職・レベルアップのたびに人が付け直すことになるためです。
    banned: dict = dataclasses.field(default_factory=dict)

    def role_of(self, slot: str) -> RolePref:
        got = self.roles.get(slot)
        return got if isinstance(got, RolePref) else RolePref()

    def is_touched(self, slot: str, tier: str | None = None) -> bool:
        """★人が決めた欄か（`tier` を省くと、どちらかの欄）。"""
        if tier is None:
            return any(s == slot for s, _t in self.touched)
        return _touch_key(slot, tier) in self.touched

    def with_strategy(self, value: str) -> "BattleAiSettings":
        return dataclasses.replace(self, strategy=value if value in STRATEGIES else self.strategy)

    def with_mp(self, value: str) -> "BattleAiSettings":
        return dataclasses.replace(self, mp_policy=value if value in MP_POLICIES else self.mp_policy)

    def with_role(self, slot: str, first, second) -> "BattleAiSettings":
        """★第1・第2 の両方を人が決める。"""
        return self.with_tier(slot, FIRST, first).with_tier(slot, SECOND, second)

    def with_tier(self, slot: str, tier: str, role) -> "BattleAiSettings":
        """★1 つの欄だけ人が決める（⚠ もう片方の欄は触らない / §15）。"""
        if slot not in SLOTS or tier not in TIERS:
            return self
        roles = dict(self.roles)
        roles[slot] = self.role_of(slot).with_tier(tier, role)
        touched = _clean_touched(set(self.touched) | {_touch_key(slot, tier)})
        return dataclasses.replace(self, roles=roles, touched=touched)

    def without_tier(self, slot: str, tier: str) -> "BattleAiSettings":
        """★1 つの欄だけ AI の提案に戻す（§15）。"""
        roles = dict(self.roles)
        if slot in roles:
            roles[slot] = self.role_of(slot).with_tier(tier, None)
            if not (roles[slot].first or roles[slot].second):
                del roles[slot]
        touched = _clean_touched(set(self.touched) - {_touch_key(slot, tier)})
        return dataclasses.replace(self, roles=roles, touched=touched)

    def without_roles(self) -> "BattleAiSettings":
        """★全員の役割を AI の提案に戻す。"""
        return dataclasses.replace(self, roles={}, touched=())

    # ------------------------------------------------------------------
    # ★★ 使わせない呪文（RX3-0370）
    # ------------------------------------------------------------------

    def bans_of(self, strategy: str) -> frozenset:
        """★その作戦で使わせない呪文の ID（⚠ 知らない作戦なら空）。"""
        got = self.banned.get(strategy)
        return got if isinstance(got, frozenset) else frozenset(got or ())

    def is_banned(self, strategy: str, spell_id: int) -> bool:
        return int(spell_id) in self.bans_of(strategy)

    def with_ban(self, strategy: str, spell_id: int, banned: bool) -> "BattleAiSettings":
        """★1 つの呪文を、その作戦で使う / 使わないに切り替える。

        ⚠ 知らない作戦は**そのまま返します**（★勝手に節を作らない）。
        """
        if strategy not in STRATEGIES:
            return self
        got = set(self.bans_of(strategy))
        if banned:
            got.add(int(spell_id))
        else:
            got.discard(int(spell_id))
        rows = dict(self.banned)
        if got:
            rows[strategy] = frozenset(got)
        else:
            rows.pop(strategy, None)        # ★空の節は残さない（⚠ 保存が膨らむ）
        return dataclasses.replace(self, banned=rows)

    def without_bans(self, strategy: str | None = None) -> "BattleAiSettings":
        """★除外を全部戻す（`strategy` を省くと**全作戦**）。"""
        if strategy is None:
            return dataclasses.replace(self, banned={})
        rows = dict(self.banned)
        rows.pop(strategy, None)
        return dataclasses.replace(self, banned=rows)

    def to_json(self) -> dict:
        touched: dict = {}
        for slot, tier in self.touched:
            touched.setdefault(slot, []).append(tier)
        out = {"strategy": self.strategy, "mp_policy": self.mp_policy,
               "roles": {k: v.as_list() for k, v in self.roles.items()},
               "touched": touched}
        # ★使わせない呪文（RX3-0370）。⚠ 空なら欄ごと出さない（★古い版でも読める）
        banned = {k: sorted(v) for k, v in self.banned.items() if v}
        if banned:
            out["banned"] = banned
        return out

    @classmethod
    def from_json(cls, data) -> "BattleAiSettings":
        """★`v2`（touched = {"p1": ["first"]}）も `v1`（touched = ["p1"]）も読む。

        ⚠ `v1` の枠は第1・第2 を**まとめて**人が決めていた → ★両方の欄を人が決めたとみなす。
        """
        if not isinstance(data, dict):
            return cls()
        roles = {}
        for slot, pair in (data.get("roles") or {}).items():
            if slot in SLOTS and isinstance(pair, (list, tuple)) and len(pair) >= 2:
                roles[slot] = RolePref(pair[0] if pair[0] in ROLES else None,
                                       pair[1] if pair[1] in ROLES else None)
        strategy = data.get("strategy") if data.get("strategy") in STRATEGIES else ECONOMY
        mp = data.get("mp_policy") if data.get("mp_policy") in MP_POLICIES else MP_AUTO
        raw = data.get("touched") or []
        pairs = []
        if isinstance(raw, dict):
            for slot, tiers in raw.items():
                if isinstance(tiers, (list, tuple)):
                    pairs.extend((slot, t) for t in tiers)
        elif isinstance(raw, (list, tuple)):
            pairs.extend((slot, t) for slot in raw for t in TIERS)
        # ★使わせない呪文（RX3-0370 / ⚠ 知らない作戦・数でない値は捨てる）
        banned = {}
        for name, ids in (data.get("banned") or {}).items():
            if name not in STRATEGIES or not isinstance(ids, (list, tuple, set)):
                continue
            got = frozenset(int(i) for i in ids if isinstance(i, (int, float)))
            if got:
                banned[name] = got
        return cls(strategy=strategy, mp_policy=mp, roles=roles,
                   touched=_clean_touched(pairs), banned=banned)


def load(settings) -> BattleAiSettings:
    """★`UiSettings` から読む（⚠ 無ければ既定）。★`v2` が無ければ `v1` から移し替える。"""
    if settings is None:
        return BattleAiSettings()
    got = settings.get(SECTION, "v2", None)
    if got is None:
        got = settings.get(SECTION, "v1", None)
    return BattleAiSettings.from_json(got)


def save(settings, value: BattleAiSettings) -> None:
    """★`v2` に書く（⚠ `v1` は残す = 古い版に戻しても設定が消えない）。"""
    if settings is not None:
        settings.set(SECTION, "v2", value.to_json())


# ----------------------------------------------------------------------
# ★役割の提案（§17）— ⚠ 職業だけで決めない
# ----------------------------------------------------------------------

def suggest_roles(members, rom_path=None) -> dict:
    """★`state.json` の party（`equip_members()` 相当）→ `slot -> RolePref`。

    ```text
    回復呪文がある            → 第1 ヒール（★回復力 = 回復量の合計で決める）
    攻撃呪文が豊富            → 第1 魔法攻撃
    攻撃力が高い              → 第1 物理攻撃
    第2 は「次に向いている」   ★支援呪文があれば支援、なければ防御
    ```

    ⚠ 呪文を読めない環境では全員 物理攻撃 / 防御（★推測しない）。
    """
    from ..knowledge import spell_info as SI

    out = {}
    rows = [m for m in (members or ()) if isinstance(m, dict)]
    attacks = [int(m.get("attack") or 0) for m in rows]
    top_attack = max(attacks) if attacks else 0
    for i, m in enumerate(rows):
        slot = m.get("slot") or (SLOTS[i] if i < len(SLOTS) else None)
        if slot is None:
            continue
        spells = [SI.info(sid, rom_path) for sid in SI.learned_for(m, rom_path)]
        spells = [s for s in spells if s is not None]
        heal_power = sum((s.avg or 0) for s in spells if s.kind == "heal")
        attack_power = sum((s.avg or 0) for s in spells if s.kind == "attack")
        has_support = any(s.kind in ("buff", "debuff") for s in spells)
        attack = int(m.get("attack") or 0)
        scores = {
            HEAL: heal_power,
            MAGIC: attack_power,
            PHYSICAL: attack if top_attack == 0 else attack * 60.0 / top_attack,
        }
        first = max(scores, key=lambda k: scores[k])
        if scores[first] <= 0:
            first = PHYSICAL
        rest = [r for r in (HEAL, MAGIC, PHYSICAL) if r != first and scores[r] > 0]
        if has_support:
            second = SUPPORT
        elif rest:
            second = max(rest, key=lambda k: scores[k])
        else:
            second = DEFEND
        out[slot] = RolePref(first, second)
    return out


def effective_roles(value: BattleAiSettings, members, rom_path=None) -> dict:
    """★実際に使う役割（⚠ 人が触った欄は提案で上書きしない / §15・§17）。

    ★欄ごとに合わせる: 人が決めた欄は人の値、ほかの欄は AI の提案。
    ⚠ 画面の表示と Lua の生成物は、**同じ members で**これを呼ぶ（`AiSettingsHub` / §17）。
    """
    suggested = suggest_roles(members, rom_path)
    out = {}
    for slot in SLOTS:
        pref = value.role_of(slot)
        base = suggested.get(slot) or (pref if (pref.first or pref.second)
                                       else RolePref(PHYSICAL, DEFEND))
        got = base
        for tier in TIERS:
            if value.is_touched(slot, tier) and pref.tier(tier):
                got = got.with_tier(tier, pref.tier(tier))
        out[slot] = got
    return out


__all__ = ["BattleAiSettings", "RolePref", "load", "save", "suggest_roles", "effective_roles",
           "effective_mp", "mp_is_used", "MP_FREE_STRATEGIES", "MP_UNUSED_NOTE",
           "STRATEGIES", "STRATEGY_LABELS", "STRATEGY_NOTES", "STRATEGY_BEHAVIOR", "BEHAVIOR_ROWS",
           "ROLES", "ROLE_LABELS", "MP_POLICIES", "MP_LABELS", "MP_NOTES", "SLOTS", "SECTION",
           "FIRST", "SECOND", "TIERS",
           "LEVELING", "ECONOMY", "SURVIVAL", "PHYSICAL", "MAGIC", "SUPPORT", "HEAL", "DEFEND",
           "MP_AUTO", "MP_SAVE", "MP_FORBID"]
