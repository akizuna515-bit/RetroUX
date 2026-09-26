"""図鑑に出す 1 件を組み立てる（RX3-0040 / 2026-09-01）。

★`RX3-0039` で行動・耐性・ドロップが解けたので、⚠ **出してよいかの判断**を
ここ 1 か所に集めます。

## ⚠⚠ 開示の段階（★No-Spoiler / RX3-0021）

```text
会っていない   ⚠ 一覧に出さない（★存在も伏せる）
会った(met)    ★名前・絵・基本性能
倒した(defeated) ★＋ 行動・耐性・ドロップ
```

⚠ 「会った」で基本性能まで出すのは、★戦闘中の帯が**既に出している**ためです
（指示書 §2.2「取得できた値をそのまま表示してよい」）。
⚠⚠ ここだけ隠しても、**戦えば見えてしまいます**。それは隠したことになりません。

★一方、行動・耐性・ドロップは戦闘中の帯に出していません。
⚠ こちらは「倒した敵だけ」に絞ります（`EnemyBook.knows_details()`）。

## ⚠ ROM が無くても落ちません

★`details_of` / `master_of` と同じで、⚠ 引けなければその欄を空にします。
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib

#: ★一覧に出す並び順の既定（⚠ 敵 ID 順が ROM の並びで、だいたい強さ順）
ORDER_BY_ID = "id"

#: ★★ 耐性の見せ方（RX3-0269 / 2026-09-14 依頼者「S9,S10は提案通りでOK。耐性表示はログのモンスター表示は
#:   簡易的に 一文字で工夫」＋ 1 文字の表）。★依頼者の表そのまま: 5 つのまとまり × (耐性の名前, 見出し, 札の 1 文字)。
#:
#:   ★RX3-0266 で 14 カテゴリすべてを JP ROM の呼び出し元と実機で確かめた（⚠ unresolved / inferred は 1 つも無い）。
#:   ⚠ 攻撃呪文の × は「ダメージ 0（効かない）」（★半減ではない / RX3-0267）。
#:   ★根拠と推奨: `docs/design/dq3-resistance-analysis.md` §9
RESIST_GROUPS: tuple = (
    ("攻撃呪文", (("damage_reduction", "メラ・ギラ・イオ", "炎"), ("ice_spells", "ヒャド", "氷"),
                  ("wind_spells", "バギ", "風"), ("lightning_spells", "デイン", "雷"))),
    ("眠り・混乱", (("sleep", "ラリホー", "眠"), ("chaos", "メダパニ", "乱"),
                   ("surround", "マヌーサ", "幻"), ("stopspell", "マホトーン", "黙"))),
    ("能力を下げる", (("sap", "ルカニ・ルカナン", "軟"), ("limbo_slow", "ボミオス・バシルーラ", "遅"))),
    ("即死・消える", (("beat", "ザキ・ザラキ", "死"), ("sacrifice", "メガンテ", "メ"),
                     ("expel_fairywater", "ニフラム・せいすい", "聖"))),
    ("MP", (("robmagic", "マホトラ", "Ｍ"),)),
)

#: ★耐性のうち、⚠ **名前が確定しているものだけ**を図鑑に出す（★RX3-0269 から上の表を平らにしたもの）。
#:
#:   ⚠⚠ `unresolved` / `inferred` を出すと、★「そう決まっている」ように
#:     読まれます（`RX3-0039` の確度をここで崩さない）。
#:   ★出さないだけで、`raw` は `EnemyBookEntry.detail` に残ります。
#:   ⚠⚠ RX3-0266: 以前 ("numboff", "しびれ") があったが、耐性 2 は**バギ系の攻撃呪文**だった（★いまは「バギ」）。
#:   ⚠⚠ RX3-0245（依頼者「ヘルコンドルがニフラムを使うと言っているが、バシルーラを使った」）:
#:     limbo = 呪文 22 バシルーラ（＋ 24 ボミオス）/ expel = 呪文 21 ニフラム（★ROM の呪文名で確かめた）。
SHOWN_RESISTANCES: tuple[tuple[str, str], ...] = tuple(
    (key, label) for _group, rows in RESIST_GROUPS for key, label, _char in rows)

#: ★段 0〜3 の記号とことば（RX3-0269 / 報告 §9.3）。⚠ 内部の 2bit・index は画面に出さない
RESIST_SYMBOL: tuple[str, ...] = ("◎", "○", "△", "×")
RESIST_WORD: tuple[str, ...] = ("よく効く", "効く", "効きにくい", "効かない")
#: ★図鑑の凡例（★「7 割ほど」はここにだけ / ⚠ 数字を前に出すと「70% 丁度」に読める = 本当は 69.9%）
#:   ⚠ 短い行に分ける: 図鑑の行は折り返すので、長い 1 行は「中身の高さ」を測った後に 2〜3 行へ増え、
#:     部品が重なる（★`test_詳細で部品が重ならない` で踏んだ / 必要 675 に 633）
RESIST_LEGEND: tuple[str, ...] = (
    "◎ よく効く（必ず）　○ 効く（7 割ほど）",
    "△ 効きにくい（3 割ほど）　× 効かない",
    "⚠ 攻撃呪文の × はダメージ 0（半減ではない）",
)


@dataclasses.dataclass(frozen=True)
class EnemyBookEntry:
    """図鑑 1 件。⚠ 出してよいものだけが入る。"""

    enemy_id: int
    name: str
    art: object = None            #: `pathlib.Path` か None
    met: bool = False
    defeated: bool = False
    master: tuple = ()            #: ★基本性能（会っていれば出す）
    actions: tuple = ()           #: ★行動（⚠ 倒していれば）
    resistances: tuple = ()       #: ★耐性（⚠ 倒していれば）
    resistance_groups: tuple = ()  #: ★耐性を 5 つのまとまりで（RX3-0269 / ⚠ 倒していれば）
    tries: tuple = ()             #: ★あなたが唱えた結果 `(見出し, 試した, 効いた)`（RX3-0271 / ⚠ 観測だけ）
    drop: dict = dataclasses.field(default_factory=dict)
    drop_label: str = ""          #: ★落とす品の見せ方（⚠ 名前 or 分類＋番号）
    detail: object = None         #: ⚠ raw を含む `EnemyDetail`（★捨てない）

    @property
    def locked(self) -> bool:
        """★中身をまだ出していない（⚠ 会ったが倒していない）。"""
        return not self.defeated


def _rom_of(rom_path=None) -> pathlib.Path:
    """★読む ROM（⚠ 省けば `work/rom/DQ3_J.nes`）。"""
    return pathlib.Path(rom_path) if rom_path else (
        pathlib.Path(__file__).resolve().parents[2] / "work" / "rom"
        / "DQ3_J.nes")


def _detail_of(enemy_id: int, rom_path=None):
    """★`RX3-0039` の解析結果（⚠ ROM が無ければ None）。"""
    try:
        from dq3rom import enemies as en
        from dq3rom import enemy_detail as det
        from dq3rom import profile as dq3
    except ImportError:                                # pragma: no cover
        return None
    target = _rom_of(rom_path)
    try:
        rows = en.read_all(dq3.load_and_identify(target))
    except Exception:                                  # noqa: BLE001
        return None                        # ⚠ ROM が無い環境でも落ちない
    index = int(enemy_id)
    if not (0 <= index < len(rows)):
        return None
    return det.EnemyDetail.from_raw(index, rows[index].raw)


#: ★行動の日本語名。⚠ **1 つの ID に 1 つの関数**が対応しているものだけ。
#:
#:   ⚠⚠ `breath_0A`〜`0F` や `spell_single_13`〜 のように、
#:     ★複数の ID が同じ関数を共有しているものは**入れません**
#:     （`RX3-0039`: 関数名だけでは どれがどれか決まらない）。
#:     → ⚠ 分類 ＋ 番号で出します（★嘘の名前を付けない）。
#:
#:   ★ただし攻撃呪文（`spell_damage` / 0x13〜0x1E）は、共有の関数が
#:     **ROM の表**（`_bs_attackspell_single_tbl` / `_multiple_tbl`）で 行動 ID → 呪文 ID を
#:     引いていると分かりました（RX3-0224 / `dq3rom.enemy_detail.attack_spell_table`）。
#:     → ★`move_label` が その表 ＋ `rom_names.spell` で**実行時に** ROM の呪文名を出します。
#:     ⚠ ここには書きません（★名前は ROM から / No-Spoiler）。⚠ 引けなければ今までどおり「こうげき呪文(17)」。
MOVE_LABEL: dict[str, str] = {
    "assessing": "ようすをみる",
    "protects_itself": "ぼうぎょ",
    "regular_attack": "こうげき",
    "attack_maybe_crit": "こうげき（会心あり）",
    "attack_maybe_sleep": "こうげき（ねむり）",
    "attack_maybe_poison": "こうげき（どく）",
    "attack_maybe_numb": "こうげき（まひ）",
    "try_flee": "にげる",
    "reinforce_own_type": "なかまをよぶ",
    "curious_dance": "あやしいおどり",
    "sweet_breath": "あまいいき",
    "toxic_breath": "どくのいき",
    "scorching_breath": "やけつくいき",
    "chant_sacrifice": "メガンテ",
    "chant_sleep": "ラリホー",
    "chant_stopspell": "マホトーン",
    "chant_sap": "ルカニ",
    "chant_defence": "スカラ",
    "chant_surround": "マヌーサ",
    "chant_robmagic": "マホトラ",
    "chant_chaos": "メダパニ",
    "chant_slow": "ボミオス",
    "chant_limbo": "バシルーラ",          # ⚠ RX3-0245: 以前は「ニフラム」（★limbo = 呪文 22 = バシルーラ）
    "chant_bounce": "マホカンタ",
    "chant_increase": "スクルト",
    "chant_increase2": "スクルト（強）",
    "chant_vivify": "ザオラル",
    "chant_revive": "ザオリク",
    "zoma_freeze_beam": "こごえるふぶき",
}

#: ★分類の日本語（⚠ 名前が付けられないときの受け皿）
CATEGORY_LABEL: dict[str, str] = {
    "wait": "ようすみ", "defend": "ぼうぎょ", "attack": "こうげき",
    "flee": "にげる", "reinforce": "なかまをよぶ", "dance": "おどり",
    "breath": "ブレス", "spell_damage": "こうげき呪文",
    "spell_instadeath": "即死呪文", "spell_status": "状態呪文",
    "special": "特殊", "spell_buff": "補助呪文",
    "spell_revive": "そせい", "heal": "かいふく",
}


@functools.lru_cache(maxsize=4)
def _attack_spells(rom_key: str) -> dict:
    """★ROM の攻撃呪文の表（RX3-0224）。⚠ ROM ごとに 1 度だけ読む / 読めなければ空。"""
    try:
        from dq3rom import enemy_detail as det
        from dq3rom import profile as dq3

        return det.attack_spells(dq3.load_and_identify(pathlib.Path(rom_key)))
    except Exception:                                  # noqa: BLE001
        return {}                          # ⚠ ROM が無い環境でも落ちない


def attack_spell_name(move_id: int, rom_path=None) -> str | None:
    """★攻撃呪文の行動 → 唱える呪文の名前（RX3-0224）。⚠ 表か名前が引けなければ None。

    ★番号は ROM の表（`dq3rom.enemy_detail.attack_spell_table`）、
      名前は ROM の名前辞書（`rom_names.spell`）。⚠ どちらも実行時に ROM から（★repo に名前を書かない）。
    """
    spell_id = _attack_spells(str(_rom_of(rom_path))).get(int(move_id))
    if spell_id is None:
        return None
    from dq3.knowledge import rom_names

    return rom_names.spell(spell_id, rom_path)


@functools.lru_cache(maxsize=4)
def _breaths(rom_key: str) -> dict:
    """★ROM のブレスの種類と幅（RX3-0278）。⚠ ROM ごとに 1 度だけ読む / 読めなければ空。"""
    try:
        from dq3rom import enemy_detail as det
        from dq3rom import profile as dq3

        ident = dq3.load_and_identify(pathlib.Path(rom_key))
        got = {m: det.breath_damage(ident, m) for m in range(det.BREATH_FIRST, det.BREATH_LAST + 1)}
        return {m: v for m, v in got.items() if v is not None}
    except Exception:                                  # noqa: BLE001
        return {}                          # ⚠ ROM が無い環境でも落ちない


#: ★ブレスの種類の見出し（⚠ 原作の技の名前は付けない / 種類と強さだけ）
BREATH_KIND_LABEL = {"fire": "炎ブレス", "cold": "冷気ブレス"}
#: ★同じ種類の中の強さ（★依頼者 2026-09-16「炎と冷気は、弱中強とかでいいや」）
BREATH_TIER_LABEL = ("弱", "中", "強")


def breath_label(move_id: int, rom_path=None, with_range: bool = False) -> str | None:
    """★ブレス 0x0A〜0x0F → `炎ブレス(中)`（RX3-0278）。⚠ 引けなければ None。

    ★種類とダメージの幅は ROM の表（`dq3rom.enemy_detail.breath_damage`）。
    ★`with_range` でヒント用の `炎ブレス(中) 30〜39`。⚠ 幅は防ぐ前の値。
    """
    from dq3rom import enemy_detail as det

    got = _breaths(str(_rom_of(rom_path))).get(int(move_id))
    if got is None:
        return None
    kind, low, high = got
    text = "%s(%s)" % (BREATH_KIND_LABEL[kind], BREATH_TIER_LABEL[det.breath_tier(move_id)])
    return "%s %d〜%d" % (text, low, high) if with_range else text


@functools.lru_cache(maxsize=4)
def _shared_targets(rom_key: str) -> dict:
    """★回復・即死・仲間を呼ぶの中身（RX3-0278）。⚠ ROM ごとに 1 度だけ / 読めなければ空。"""
    try:
        from dq3rom import enemy_detail as det
        from dq3rom import profile as dq3

        ident = dq3.load_and_identify(pathlib.Path(rom_key))
        got = {m: det.shared_move_target(ident, m) for m in (0x1F, 0x20, *range(0x31, 0x40))}
        return {m: v for m, v in got.items() if v is not None}
    except Exception:                                  # noqa: BLE001
        return {}


def shared_move_label(move_id: int, rom_path=None) -> str | None:
    """★`かいふく(33)` → `ベホマ` / `なかまをよぶ(3C)` → `なかまをよぶ(だいまじん)`（RX3-0278）。

    ★番号は ROM の表、名前は ROM の名前辞書（⚠ repo に名前を書かない）。⚠ 引けなければ None。
    """
    got = _shared_targets(str(_rom_of(rom_path))).get(int(move_id))
    if got is None:
        return None
    from dq3.knowledge import rom_names

    kind, entity = got
    if kind == "spell":
        return rom_names.spell(entity, rom_path)
    name = rom_names.monster(entity, rom_path)
    return None if name is None else "なかまをよぶ(%s)" % name


def move_label(name: str, move_id: int, category: str, rom_path=None) -> str:
    """★画面に出す行動名。⚠ 分からないものに**名前を付けない**。

    ★攻撃呪文は ROM の表と名前辞書で呪文名にする（RX3-0224）。⚠ 引けなければ「こうげき呪文(17)」。
    ★ブレス 0x0A〜0x0F は ROM の表で種類と強さ（`炎ブレス(中)`）にする（RX3-0278）。⚠ 引けなければ「ブレス(0B)」。
    ★回復・即死・仲間を呼ぶも ROM の表で呪文名 / 呼ぶ敵にする（RX3-0278）。⚠ 引けなければ「かいふく(33)」。
    """
    got = MOVE_LABEL.get(name)
    if got:
        return got
    if category == "spell_damage":
        spell = attack_spell_name(move_id, rom_path)
        if spell:
            return spell
    if category == "breath":
        breath = breath_label(move_id, rom_path)
        if breath:
            return breath
    if category in ("heal", "spell_instadeath", "reinforce"):
        shared = shared_move_label(move_id, rom_path)
        if shared:
            return shared
    return "%s(%02X)" % (CATEGORY_LABEL.get(category, category), move_id)


def action_summary(detail, rom_path=None) -> tuple:
    """★行動を「種類ごとにまとめた」形にする（⚠ 8 枠のまま出さない）。

    戻り値は `(表示名, 枠の数)` の並び。

    ## ⚠⚠ 確率としては出しません

      ★8 枠の重複は、そのまま `n/8` にはなりません
      （`RX3-0039`: 選択は重み表 `off_68406` を使う）。
      ⚠ ここでは**枠の数**として出し、「確率」とは書きません。

      → ★画面では `こうげき（6枠）` と書きます（`slot_text()`）。
        ⚠ `x6` だと「6 倍」「6 割」と読まれかねません。
    """
    if detail is None:
        return ()
    counted: dict[str, int] = {}
    for act in detail.actions:
        label = move_label(act["name"], act["move_id"], act["category"], rom_path)
        counted[label] = counted.get(label, 0) + 1
    # ★多い順、同数なら名前順（⚠ 並びが毎回変わらないように）
    return tuple(sorted(counted.items(), key=lambda kv: (-kv[1], kv[0])))


def slot_text(count: int) -> str:
    """★枠の数の書き方。⚠ **確率と誤読されない形**にする（指示書 §11）。

    ```text
    ⚠ 避ける   こうげき x6      （★「6 倍」「6 割」に見える）
    ★使う     こうげき（6枠）
    ```
    """
    return "" if count <= 1 else "（%d枠）" % count


#: ★戦闘の札（ログのモンスターの帯）に出す耐性の 1 文字（★RX3-0269 依頼者の表 / キーは耐性の名前 / 凡例はヒントに）
RESIST_SHORT: dict[str, str] = {key: char for _group, rows in RESIST_GROUPS for key, _label, char in rows}
#: ★札の凡例（★ヒントに出す / ⚠ 攻撃呪文の × の意味も書く）
CARD_LEGEND = ("耐性 ×=効かない △=3 割ほどしか効かない（"
               + " ".join("%s=%s" % (char, label) for _group, rows in RESIST_GROUPS for _key, label, char in rows)
               + "）⚠ 攻撃呪文の × はダメージ 0")
#: ★特技として出さない大分類（★ふつうの攻撃・様子見・防御・逃走）
PLAIN_CATEGORIES = ("attack", "wait", "defend", "flee")


def card_extras(detail, rom_path=None) -> dict:
    """★戦闘の札の 1 行（RX3-0060 / 依頼者「DQ2 の表示を参考に耐性・特殊攻撃」）。

    ```text
    resist   耐性が**ある**ものだけ: 効かない = 字×、3 割ほど = 字△（★7 割・必ず効く は出さない / 場所節約）
             ★字は依頼者の表の 1 文字（RX3-0269: 炎 氷 風 雷 / 眠 乱 幻 黙 / 軟 遅 / 死 メ 聖 / Ｍ）
    special  ふつうの攻撃・様子見・防御・逃走以外の行動（枠の多い順 / ★攻撃呪文は ROM の呪文名 / RX3-0224）
    ```
    """
    if detail is None:
        return {"resist": "", "special": "", "legend": "", "tip": ""}
    parts = []
    by_level: dict[int, list[str]] = {3: [], 2: []}
    for _group, rows in RESIST_GROUPS:
        for key, label, char in rows:
            got = detail.resistances.get(key)
            if got is None or got["level"] < 2:
                continue
            level = 3 if got["level"] >= 3 else 2
            parts.append("%s%s" % (char, "×" if level == 3 else "△"))
            by_level[level].append("%s（%s）" % (char, label))
    specials: dict[str, int] = {}
    tip_words: dict[str, str] = {}          # ★ヒントだけブレスの幅を足す（札は「炎ブレス(中)」）
    for act in detail.actions:
        if act["category"] in PLAIN_CATEGORIES:
            continue
        lab = move_label(act["name"], act["move_id"], act["category"], rom_path)
        specials[lab] = specials.get(lab, 0) + 1
        if act["category"] == "breath":
            tip_words[lab] = breath_label(act["move_id"], rom_path, with_range=True) or lab
    order = sorted(specials.items(), key=lambda kv: (-kv[1], kv[0]))
    special_words = [k for k, _v in order]
    return {"resist": " ".join(parts), "special": " ".join(special_words), "legend": CARD_LEGEND,
            "tip": card_tip(by_level, [tip_words.get(w, w) for w in special_words])}


#: ★ヒントの耐性 1 行に並べる数
TIP_PER_LINE = 4


def card_tip(by_level: dict, specials: list) -> str:
    """★札のヒント（RX3-0278 / 依頼者「耐性が多いときに省略表示されてしまう。ツールチップ表示させたい」）。

    ```text
    耐性
      × 効かない        乱（メダパニ）
      △ 3 割ほど効く    炎（メラ・ギラ・イオ） 氷（ヒャド） …
    特技
      マヒャド / 炎ブレス(中) 30〜39 / …
    ⚠ 攻撃呪文の × はダメージ 0 ／ ブレスの幅は防ぐ前の値
    ```

    ⚠ 札の 1 行は「…」で切れても、★ここには**全部**出す（1 行に長く並べない）。
    """
    rows = ["耐性"]
    if not (by_level.get(3) or by_level.get(2)):
        rows.append("  なし（どれも 7 割以上効く）")
    for level, head in ((3, "× 効かない"), (2, "△ 3 割ほど効く")):
        words = by_level.get(level) or []
        for i in range(0, len(words), TIP_PER_LINE):          # ⚠ 長い 1 行にしない（★4 つずつ）
            rows.append("  %s　%s" % (head if i == 0 else "　" * len(head),
                                     "　".join(words[i:i + TIP_PER_LINE])))
    rows.append("特技")
    rows.append("  " + (" / ".join(specials) if specials else "なし"))
    notes = ["⚠ 攻撃呪文の × はダメージ 0"]
    if any("ブレス(" in s and "〜" in s for s in specials):
        notes.append("ブレスの幅は防ぐ前の値")
    rows.append(" ／ ".join(notes))
    return chr(10).join(rows)


def resistance_rows(detail) -> tuple:
    """★出してよい耐性だけ（⚠ `unresolved` / `inferred` は出さない）。

    戻り値は `(見出し, 段階 0..3, 効き方の言葉)`（★言葉は「◎ よく効く」の形 / RX3-0269）。
    ⚠⚠ **raw の 0〜3 を画面へ出しません**（指示書 §13 / ★段は色分けにだけ使う）。
    """
    if detail is None:
        return ()
    out = []
    for key, label in SHOWN_RESISTANCES:
        got = detail.resistances.get(key)
        if got is None:                                # pragma: no cover
            continue
        lv = int(got["level"]) & 3
        out.append((label, lv, "%s %s" % (RESIST_SYMBOL[lv], RESIST_WORD[lv])))
    return tuple(out)


def resistance_groups(detail) -> tuple:
    """★耐性を 5 つのまとまりで（RX3-0269 / 依頼者の表 / 報告 §9）。

    戻り値は `((まとまり, ((見出し, 1 文字, 段階 0..3, 記号, ことば), ...)), ...)`。
    ⚠⚠ **raw の 0〜3 を画面へ出しません**（★段は色分けにだけ使う）。
    """
    if detail is None:
        return ()
    out = []
    for group, rows in RESIST_GROUPS:
        items = []
        for key, label, char in rows:
            got = detail.resistances.get(key)
            if got is None:                            # pragma: no cover
                continue
            lv = int(got["level"]) & 3
            items.append((label, char, lv, RESIST_SYMBOL[lv], RESIST_WORD[lv]))
        if items:
            out.append((group, tuple(items)))
    return tuple(out)


def resist_key_of(index) -> str | None:
    """★耐性の番号 → 名前（RX3-0271 / ⚠ 画面の側は ROM を読まないので、ここで引く）。⚠ 知らない番号は None。"""
    from dq3rom import enemy_detail as det

    for i, _off, _shift, name, _conf in det.RESISTANCES:
        if i == int(index):
            return name
    return None


def book_word(book, enemy_id, index) -> str | None:
    """★図鑑のことば（効きにくい など / RX3-0271 のログに添える）。

    ⚠⚠ **倒した敵だけ**（★図鑑が開いていない敵には添えない = No-Spoiler）。⚠ 引けなければ None。
    """
    if book is None or not book.knows_details(enemy_id):
        return None
    key = resist_key_of(index)
    got = (getattr(_detail_of(int(enemy_id)), "resistances", None) or {}).get(key) if key else None
    if got is None:
        return None
    return RESIST_WORD[int(got["level"]) & 3]


def tries_rows(book, enemy_id) -> tuple:
    """★あなたが唱えた結果（RX3-0271 / 図鑑の「あなたの記録」/ 報告 §10.4）。

    戻り値は `((見出し, 試した, 効いた), ...)`（★依頼者の表の並び / 試したものだけ）。
    ⚠⚠ 観測だけ（★ROM の耐性とは混ぜない）。⚠ 会った敵なら倒していなくても出す（★自分で見たことなので No-Spoiler に触れない）。
    """
    rows = (getattr(book, "tries", None) or {}).get(int(enemy_id)) or {}
    out = []
    for _group, items in RESIST_GROUPS:
        for key, label, _char in items:
            got = rows.get(key)
            if got:
                out.append((label, int(got[0]), int(got[1])))
    return tuple(out)


def entry_of(book, enemy_id, *, rom_path=None, art_lookup=None,
             item_names=None) -> EnemyBookEntry | None:
    """★図鑑 1 件を組み立てる。⚠ 会っていない敵は `None`。

    @param book        `dq3.knowledge.enemies_seen.EnemyBook`
    @param item_names  `dq3.knowledge.item_names.ItemNames`（⚠ 省くと読み込む）
    """
    key = int(enemy_id)
    if key not in getattr(book, "met", ()):
        return None                        # ⚠ 会っていない敵は存在も伏せる

    from dq3.knowledge.enemies_seen import master_of

    if art_lookup is None:
        from dq3.knowledge import monster_art
        art_lookup = monster_art.path_of

    defeated = bool(book.knows_details(key))
    master = master_of(key, rom_path) or ()
    detail = _detail_of(key, rom_path) if defeated else None
    # ⚠ `label()` は戦闘用で「ー N ひき」が付きます（★図鑑では邪魔）。
    #   ★名前だけを引き、⚠ 知らなければ `label()` と同じ出し方に揃えます。
    # ★ROM の名前を先に（primary / RX3-0069 §8）→ ⚠ ROM が無ければ画面で読めた名前 → それも無ければ番号
    from dq3.knowledge import rom_names

    name = rom_names.monster(key) or book.names.get(key) or ("？（敵 %d）" % key)
    return EnemyBookEntry(
        enemy_id=key,
        name=name,
        art=art_lookup(key),
        met=True,
        defeated=defeated,
        master=tuple(master),
        actions=action_summary(detail, rom_path),
        resistances=resistance_rows(detail),
        resistance_groups=resistance_groups(detail),
        tries=tries_rows(book, key),
        drop=dict(detail.drop) if detail is not None else {},
        drop_label=drop_label(detail, item_names),
        detail=detail,
    )


def drop_label(detail, item_names=None) -> str:
    """★落とす品の見せ方。⚠ 名前を知らなければ**分類 ＋ 番号**。

    ⚠⚠ 原作テキストを同梱しないので（`docs/00-project-policy.md` §3）、
      ★名前は「遊んで見たもの」だけです。⚠ 見ていなければ、
      **見ていないと分かる形**で出します（★裸の番号にしない）。
    """
    if detail is None:
        return ""
    from dq3rom import items as it

    item_id = detail.drop.get("item_id")
    if item_names is None:
        from dq3.knowledge.item_names import ItemNames

        item_names = ItemNames.load()
    from dq3.knowledge import rom_names

    seen = (item_names.names.get(int(item_id) & it.TYPE_MASK)
            if item_id is not None else None)
    # ★ROM の品名を先に（primary / RX3-0069 §8）→ ⚠ ROM が無ければ画面で読めた品名 → 分類＋番号
    return it.label_of(item_id, rom_names.item(item_id) or seen)


def entries(book, *, rom_path=None, art_lookup=None,
            item_names=None) -> list[EnemyBookEntry]:
    """★会った敵ぜんぶ（⚠ ID 順）。"""
    if item_names is None:
        from dq3.knowledge.item_names import ItemNames

        item_names = ItemNames.load()      # ★1 度だけ読む（⚠ 敵ごとに読まない）
    out = []
    for key in sorted(int(k) for k in getattr(book, "met", ())):
        got = entry_of(book, key, rom_path=rom_path, art_lookup=art_lookup,
                       item_names=item_names)
        if got is not None:
            out.append(got)
    return out


def counts(book) -> dict:
    """★「何体まで見たか」（⚠ 全体数は出しません）。

    ⚠⚠ 「139 体中 12 体」と出すと、★**まだ会っていない数が分かります**。
      指示書 §10 の No-Spoiler に反するので、**会った数と倒した数だけ**。
    """
    met = {int(k) for k in getattr(book, "met", ())}
    defeated = {int(k) for k in getattr(book, "defeated", ())}
    return {"met": len(met), "defeated": len(defeated)}
