"""戦術プロフィールの語彙（2026-07-30 / 仕様書 4章・5章・10章）。

★ここには**言葉の定義と既定値だけ**を置く。
  保存は `profile_repository.py`、検証は `profile_validator.py`、
  実際の判断は Lua（`bridge.lua`）。

## この機能の芯（仕様書 2.1 / 23章）

    ✗ AI が勝手に賢くなる
    ✓ **利用者が戦術を設計し、AI がその意図を再現可能な形で実行する**

だから「AI が状況を見て最適化する」ような項目は作らない。
設定は**条件と優先度**であって、確率ではない（仕様書 2.3）。

## ⚠⚠ フェーズを混ぜない

仕様書 20章:

  > Phase 3以降の設定項目は、データモデル上は追加可能にしておくが、
  > **未実装の判断ロジックを動作するように見せない。**

→ 各項目に `phase` を持たせ、**いまのフェーズより先の項目は
  読み込んで保持するが AI へは渡さない**（`IMPLEMENTED_PHASES`）。
  画面はグレーアウトして「今後のフェーズで対応」と出す。

⚠ 「あとで効くようにする」つもりで先に渡すと、
  設定したのに効かない項目ができ、**設定画面全体が信用されなくなる**。
"""

from __future__ import annotations

import dataclasses
import enum

#: いまのフェーズで**実際に AI が使う**項目のフェーズ番号。
#   ★ここを増やすときは、必ず Lua 側の実装と同時に増やすこと。
IMPLEMENTED_PHASES = (1, 2)

#: プロフィールの形式の版（仕様書 10.3）。★必須項目
SCHEMA_VERSION = 1

#: キャラクターの並び。★`memory_map.yaml` の `party.members` と同じ順・同じ綴り。
#   ⚠ ここを勝手に変えると Lua 側の引き当てが外れる。
CHARACTER_IDS = ("lorasia", "samaltria", "moonbrooke")

#: 画面に出す名前。★英語の値をそのまま出さない
CHARACTER_LABELS = {
    "lorasia": "ローレシア王子",
    "samaltria": "サマルトリア王子",
    "moonbrooke": "ムーンブルク王女",
}


class Role(str, enum.Enum):
    """役割（仕様書 4.4）。**行動カテゴリの基本優先度**として使う。

    ⚠ 役割は「その行動しかしない」という意味ではない。
      加点・減点であって、禁止ではない（禁止は各 `enabled` が持つ）。
    """

    ATTACK = "attack"
    BALANCED = "balanced"
    HEALER = "healer"
    SUPPORT = "support"
    CONSERVE_MP = "conserve_mp"
    MANUAL = "manual"

    @classmethod
    def parse(cls, value, default=None):
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


ROLE_LABELS = {
    Role.ATTACK: "攻撃重視",
    Role.BALANCED: "バランス",
    Role.HEALER: "回復重視",
    Role.SUPPORT: "補助重視",
    Role.CONSERVE_MP: "MP温存",
    Role.MANUAL: "手動",
}


class FallbackAction(str, enum.Enum):
    """有効な行動が無いときにどうするか（仕様書 4.4）。"""

    ATTACK = "attack"
    DEFEND = "defend"
    MANUAL = "manual"

    @classmethod
    def parse(cls, value, default=None):
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


FALLBACK_LABELS = {
    FallbackAction.ATTACK: "通常攻撃",
    FallbackAction.DEFEND: "防御",
    FallbackAction.MANUAL: "手動へ戻す",
}


class SpellPolicy(str, enum.Enum):
    """回復呪文の選び方（仕様書 5.4）。"""

    LOWEST_MP = "lowest_mp"
    HIGHEST_HEAL = "highest_heal"
    MINIMUM_SUFFICIENT = "minimum_sufficient"

    @classmethod
    def parse(cls, value, default=None):
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


SPELL_POLICY_LABELS = {
    SpellPolicy.LOWEST_MP: "MP消費が少ないもの",
    SpellPolicy.HIGHEST_HEAL: "回復量が多いもの",
    SpellPolicy.MINIMUM_SUFFICIENT: "必要量を満たす最小のもの",
}


class ProtectTarget(str, enum.Enum):
    """守る相手（2026-08-04 /「いのちをだいじに」/ 指示書 §10）。

    ★★ **その人のHPが下がったら、他の誰より先に回復します。** ★★
      「いのちをだいじに」では、攻撃役のローレシアを立たせ続けるのが狙いです。

    ⚠ `NONE` は「守る相手を決めない」＝ 既存の仲間回復の条件だけで動く、
      という意味です。**0 と混ぜない**ために別の値にしています。
    """

    NONE = "none"
    LORASIA = "lorasia"
    SAMALTRIA = "samaltria"
    MOONBROOKE = "moonbrooke"

    @classmethod
    def parse(cls, value, default=None):
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (TypeError, ValueError):
            return default


PROTECT_TARGET_LABELS = {
    ProtectTarget.NONE: "決めない（従来どおり）",
    ProtectTarget.LORASIA: "ローレシア王子",
    ProtectTarget.SAMALTRIA: "サマルトリア王子",
    ProtectTarget.MOONBROOKE: "ムーンブルク王女",
}


@dataclasses.dataclass(frozen=True)
class Field:
    """設定項目1つの定義。

    ★★ **画面・検証・Lua への受け渡しが、この1つの表を見る。** ★★
      3か所に別々に書くと、片方だけ直したときに黙って食い違う
      （playbook「順番や対応の表は写さない」）。
    """

    #: `characters.<id>.<section>.<key>` の `section` と `key`
    section: str
    key: str
    #: 画面に出す名前
    label: str
    #: `bool` / `int` / `enum`
    kind: str
    default: object
    #: このフェーズで実装される（`IMPLEMENTED_PHASES` に無ければ AI へ渡さない）
    phase: int
    #: 数値の範囲（`kind == "int"` のとき）。**外れたら自動補正せずエラー**
    minimum: int | None = None
    maximum: int | None = None
    #: `kind == "enum"` のときの enum クラス
    enum_cls: object | None = None
    #: 画面の補足（なぜこの設定があるか）
    note: str | None = None
    #: ★フェーズより**先に**実装が入った項目（2026-08-03）
    #
    #  ⚠⚠ `IMPLEMENTED_PHASES` にフェーズ番号を足して済ませてはいけません。
    #    「ガンガン行こうぜ」は仕様書の Phase 3 ですが、実際に動くのは
    #    **`actions.attack_spell` だけ**です。3 を足すと、同じ Phase 3 の
    #    `group_spell_min_enemies` / `avoid_spell_overkill` / 対象選択の
    #    6項目まで**動くように見えてしまいます**（実際は何もしません）。
    #    → 動く項目だけをここで名指しします。
    shipped: bool = False

    @property
    def implemented(self) -> bool:
        return self.shipped or self.phase in IMPLEMENTED_PHASES


#: 設定項目の一覧。★**ここが唯一の出典**。
#
# ⚠ Phase 3 以降の項目も**載せてある**（読み込んで保持するため）。
#   `phase` が `IMPLEMENTED_PHASES` に無いものは AI へ渡らない。
FIELDS: tuple[Field, ...] = (
    # --- Phase 1: 基本 ---
    Field("root", "enabled", "このキャラクターをAI操作する", "bool", True, 1,
          note="OFF にすると、この人の番では自動入力しません（手動と混在できます）"),
    Field("root", "role", "役割", "enum", Role.BALANCED, 1, enum_cls=Role,
          note="行動カテゴリの基本優先度。禁止ではなく加点・減点です"),
    Field("safety", "return_to_manual_on_danger", "危険時に手動へ戻す",
          "bool", True, 1,
          note="既存の危険判定（HP25%以下など）を使います"),
    Field("safety", "fallback_action", "有効な行動が無い場合", "enum",
          FallbackAction.ATTACK, 1, enum_cls=FallbackAction),

    # --- Phase 2: 回復 ---
    Field("healing", "self_enabled", "自分を回復する", "bool", True, 2),
    Field("healing", "self_hp_threshold", "自分の回復開始HP（%）", "int",
          40, 2, minimum=0, maximum=100),
    Field("healing", "ally_enabled", "仲間を回復する", "bool", True, 2),
    Field("healing", "ally_hp_threshold", "仲間の回復開始HP（%）", "int",
          50, 2, minimum=0, maximum=100),
    # ⚠⚠ **「緊急回復HP（%）」はここにあったが廃止した**（2026-07-31）。
    #   既定では**構造的に発動しなかった**（危険状態と同じ 25% で、
    #   先に危険状態が成立して自動入力ごと止まるため）。
    #   ★安全網は**危険時手動復帰**が担う。二重に持つと設定が煩雑になる。
    # ⚠⚠ **`spell_policy`（回復呪文の選び方）は削除しました**（2026-08-10 / UI整理）。
    #   棚卸し（docs/strategy-parameter-audit.md）で **Lua が読んでいない**
    #   ことが確定（§11 の疑い）。★mantan 側の `spell_policy` とは別物です
    #   （あちらは動くので消していません）。

    # --- ★★「いのちをだいじに」（2026-08-04 / 指示書 §10・§12）------------
    #
    # ★★ **判断順**（§10）:
    #
    #     1. 自分のHP  <= 緊急自己回復   -> 自分を回復
    #     2. 守る相手のHP <= 保護しきい値 -> その人を回復
    #     3. 自分のHP  <= 自分の回復開始HP -> 自分を回復
    #     4. それ以外は既存の仲間回復の条件
    #     5. 回復が要らなければ既存の攻撃・補助
    #
    #   ★この順にする理由（§10 末尾）:
    #     **回復役自身が瀕死のままローレシアだけを回復して共倒れになる**
    #     のを防ぐためです。
    #
    # ⚠ `self_heal_threshold`（§10 の 3 番）は**新しく作りません**。
    #   すでにある `healing.self_hp_threshold`（自分の回復開始HP）が
    #   まったく同じ意味です。★2つ持つと必ず食い違います（§13・§16）。
    Field("healing", "protect_target", "守る相手", "enum",
          ProtectTarget.NONE, 2, enum_cls=ProtectTarget, shipped=True,
          note="この人のHPが下がったら、他の誰より先に回復します。"
               "「決めない」なら従来どおりの仲間回復です"),
    Field("healing", "protect_hp_threshold", "守る相手を回復するHP（%）",
          "int", 50, 2, minimum=0, maximum=100, shipped=True,
          note="★「守る相手」を決めているときだけ効きます"),
    # ⚠⚠ **既定 25% は、そのままでは発動しません。**
    #
    #   2026-07-31 に「緊急回復HP」を廃止したのと同じ理由です:
    #   ★**危険状態（HP25%以下）が先に成立し、自動入力ごと止まります。**
    #   （`safety.return_to_manual_on_danger` が人へ操作を返すため）
    #
    #   ⚠ 指示書 §10 の既定値をそのまま入れていますが、実際に効かせるには
    #     その人の「危険時に手動へ戻す」を OFF にする必要があります。
    #   ★それでも**順番そのものには意味があります**（1 が 2 より先）。
    #     しきい値を 30〜40% に上げれば、危険状態の手前で自己回復します。
    Field("healing", "emergency_self_hp_threshold", "自分を緊急回復するHP（%）",
          "int", 25, 2, minimum=0, maximum=100, shipped=True,
          note="★守る相手より自分を優先する境目。⚠ 25%のままだと"
               "「危険時に手動へ戻す」が先に働くため、実際には発動しません"),
    Field("healing", "avoid_duplicate_healing", "二重回復を避ける", "bool",
          True, 2, shipped=True,
          note="サマルとムーンが同じ人を続けて回復しないようにします"),
    # ⚠ `consider_expected_healing`（回復見込み量を考慮する）は削除
    #   （2026-08-10 / UI整理）。★プリセットの既定値以外どこも読んでおらず、
    #   値を変えても挙動に出ませんでした（CONFIG_ONLY）。

    # --- Phase 2: MP ---
    Field("resources", "reserve_mp", "最低残存MP", "int", 15, 2, minimum=0,
          note="呪文を使うとこれを下回る場合、原則として使いません"),
    # ⚠ 「緊急時は予約MPを使う」も**同時に廃止**（緊急の判定が無くなったため、
    #   残しても何も起こさない設定になる）。
    Field("resources", "ignore_reserve_on_boss", "ボス戦ではMP温存を解除する",
          "bool", False, 2),

    # --- Phase 2: 道具 ---
    Field("items", "reusable", "非消耗道具を使用する", "bool", True, 2,
          note="杖など。★MPも在庫も減りません"),
    # ⚠ `consumable`（消耗品を使用する）と `protect_rare_items`
    #   （貴重品を自動使用しない）は削除（2026-08-10 / UI整理）。
    #   ★どちらも Lua が読まず、行動に出ませんでした。消耗品の使用は
    #     まんたん設定が担います（`core/mantan`）。

    # --- Phase 3: 攻撃（★攻撃呪文だけ AI へ渡す。ほかは削除済み）---
    #   ★機能は残す。⚠ 2026-08-11: ラベルから「（ガンガン行こうぜ）」を外した
    #     （依頼者「ラベルが不要。機能は残す」）。
    #   ★既定 OFF なので、**触らなければこれまでどおり**
    #     「たたかう＋杖＋回復呪文」だけで戦います。
    #   ★ON にした人だけ、その人の攻撃呪文が候補に入ります。
    Field("actions", "attack_spell", "攻撃呪文を使う",
          "bool", False, 3, shipped=True,
          note="OFF なら従来どおり「たたかう＋杖＋回復呪文」だけ。"
               "ON にするとサマル・ムーンの攻撃呪文を連携して選びます"),

    # ⚠⚠ **2026-08-10 に 19 項目を削除しました**（UI整理 Phase 2）★★
    #
    #   棚卸し（docs/strategy-parameter-audit.md）で「UNUSED / FUTURE」と
    #   分類したものです。★どれも Lua が読んでおらず、設定しても行動に
    #   出ませんでした。指示書 §9-C・§17「未実装・未使用を UI に出さない」。
    #
    #   削除したもの:
    #     actions   : physical_attack / group_spell_min_enemies /
    #                 avoid_spell_overkill /
    #                 support_spell / support_on_boss / support_on_normal /
    #                 support_max_uses / avoid_duplicate_support
    #     targeting : focus_fire / prefer_low_hp / prefer_healer /
    #                 prefer_dangerous / prefer_spellcaster / prefer_summoner
    #                 （⚠ 「集中攻撃」等の挙動は Lua に**ハードコードで別途
    #                   存在**します。トグルが制御していなかっただけで、
    #                   消しても挙動は変わりません）
    #     teamwork  : avoid_duplicate_heal /
    #                 avoid_duplicate_support_with_party / avoid_overkill
    #
    #   ⚠ 古い戦術プロフィール YAML にこれらのキーが残っていても、
    #     読み込みは**未知の項目として無視**します（落ちません）。
    #     ★`targeting` と `teamwork` はセクションごと無くなりました。
)

#: `(section, key)` から `Field` を引く
FIELD_BY_PATH = {(f.section, f.key): f for f in FIELDS}

#: 画面の折りたたみの見出し（仕様書 14.2）
SECTION_LABELS = {
    "root": "基本",
    "safety": "安全",
    "healing": "回復",
    "resources": "MP",
    "items": "道具",
    "actions": "攻撃",
    # ⚠ 2026-08-10: `targeting`（対象選択）と `teamwork`（連携）は
    #   全項目を削除したのでセクションごと廃止（UI整理 Phase 2）。
}


#: ⚠⚠ **そのキャラクターには意味が無い項目**（仕様書 5.7 / 14.1）。
#
# ★ローレシアは DQ2 では**呪文を覚えない**（`memory_map.yaml` の
#   `menu_layouts` 0x09 のコメント: MP 0 なので行1 が「にげる」になる）。
#   ⚠ 理由は「いま MP が 0 だから」ではなく「**覚えないから**」。
#     宿屋で回復しても変わらない。
#
# ★★ ここに置く理由: これは**DQ2 の知識**であって画面の都合ではない。 ★★
#   画面側に置くと、既定値を作るときに同じ表がもう1つ必要になり、
#   片方だけ直したときに黙って食い違う（playbook「表は写さない」）。
NOT_APPLICABLE = {
    "lorasia": {
        ("healing", "self_enabled"): "回復呪文を使用できません",
        ("healing", "self_hp_threshold"): "回復呪文を使用できません",
        ("healing", "ally_enabled"): "回復呪文を使用できません",
        ("healing", "ally_hp_threshold"): "回復呪文を使用できません",
        # ★「いのちをだいじに」の項目（2026-08-04）。
        #   ⚠ ローレシアは**回復役ではなく守られる側**なので、
        #     「誰を守るか」も「自分をいつ回復するか」も意味を持ちません。
        ("healing", "protect_target"): "回復呪文を使用できません（守られる側です）",
        ("healing", "protect_hp_threshold"): "回復呪文を使用できません",
        ("healing", "emergency_self_hp_threshold"): "回復呪文を使用できません",
        ("healing", "avoid_duplicate_healing"): "回復呪文を使用できません",
        ("resources", "reserve_mp"): "MPを持ちません",
        ("resources", "ignore_reserve_on_boss"): "MPを持ちません",
        ("actions", "attack_spell"): "呪文を使用できません",
        # ⚠ 2026-08-10: 削除したフィールド（support_* / group_spell_min_enemies
        #   / consider_expected_healing / spell_policy）の行は一緒に消しました。
    },
}


def not_applicable(character_id: str, section: str, key: str):
    """その人にその項目が意味を持たない理由。意味を持つなら None。"""
    return (NOT_APPLICABLE.get(character_id) or {}).get((section, key))


def default_character(all_phases: bool = False,
                      character_id: str | None = None) -> dict:
    """1キャラクター分の既定値。★`FIELDS` から作る（表を写さない）。

    ★★ **既定では実装済みフェーズの項目だけを入れる。** ★★

      ⚠ 未実装の項目まで入れると、同梱の見本を検証しただけで
        「いまは効きません」の警告が**54件**出た（実際に出した）。
        毎回出る通知は読まれない通知になり、本当に見たい警告が埋もれる。

      → 未実装の項目は「利用者（またはインポートしたファイル）が
        **実際に設定したとき**だけ」present になる。そのときの警告は意味がある。

    `all_phases=True` は画面用（グレーアウトした項目に何を出すか決めるため）。

    ★`character_id` を渡すと、**その人に意味が無い項目を入れない**
      （ローレシアに「回復開始HP」を持たせない）。
      ⚠ 入れると、YAML を読んだ人が「なぜローレシアに回復設定が？」となる。
    """
    out: dict = {}
    for field in FIELDS:
        if not all_phases and not field.implemented:
            continue
        if character_id is not None and not_applicable(
                character_id, field.section, field.key):
            continue
        value = field.default
        if isinstance(value, enum.Enum):
            value = value.value
        if field.section == "root":
            out[field.key] = value
        else:
            out.setdefault(field.section, {})[field.key] = value
    return out


def get_value(character: dict, section: str, key: str):
    """1項目を読む。**無ければ既定値**（古いプロフィールでも動く）。"""
    field = FIELD_BY_PATH.get((section, key))
    default = None
    if field is not None:
        default = field.default
        if isinstance(default, enum.Enum):
            default = default.value
    if section == "root":
        return character.get(key, default)
    return (character.get(section) or {}).get(key, default)


def set_value(character: dict, section: str, key: str, value) -> None:
    """1項目を書く。★enum は値（文字列）で入れる（YAML に出すため）。"""
    if isinstance(value, enum.Enum):
        value = value.value
    if section == "root":
        character[key] = value
    else:
        character.setdefault(section, {})[key] = value
