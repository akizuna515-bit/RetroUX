"""戦闘 AI の設定と ROM の表を Lua へ渡す（RX3-0126 / 2026-09-08）。

```text
設定（作戦 / MP 制約 / 役割）      work/dq3-ui-settings.json
ROM の表（呪文 / 習得ブロック / 敵） input/ の ROM
      ↓ ここ
work/generated/dq3_ai.lua            ★Lua の AI が読む 1 本
```

## ★DQ2 と同じ渡し方（`retroux/core/tactics/lua_bridge.py`）

- ★`revision`（書いた時刻）を入れ、⚠ 画面で変えたら `ai_reload` を頼む
- ★反映は**次のターンから**（⚠ 同じターンの前半と後半で作戦が変わると説明できない）
- ⚠ ファイルが無ければ Lua は AI を使わず、★今までどおり `auto_v0` の設定で動く

## ⚠⚠ 敵の表は**内部の判断だけ**に使う（依頼者 OK / 2026-09-08）

★敵の HP・耐性は画面に出しません（No-Spoiler）。⚠ Lua が戦況の見立てに使うだけ。
"""
from __future__ import annotations

import os
import pathlib
import time

from . import settings as S
from .. import paths as P3

ROOT = pathlib.Path(__file__).resolve().parents[2]
#: ★書き先（⚠ 隔離して動くときは sandbox の下 / RX3-0128）
OUT_DIR = P3.work("generated")
MODULE = "dq3_ai"

#: ★内部の閾値（⚠ 人には見せない / 指示書 §5・§16）。★実測で直す前提の目安
#:
#: ★RX3-0198（2026-09-12）の棚卸し — 作戦ごとの値が本当に読まれているか:
#:   heal_at            ★読む（おまかせのとき）。⚠ 半分程度残す（温存）は danger_hp（0.3）で、
#:                      使用禁止は critical_hp（0.15）で頭打ち、消化戦は critical_hp → 作戦の差はおまかせだけ
#:   support_min_turns  ★3 つとも読む（速攻 = 劣勢のとき / 節約 = 均衡・劣勢 / 生存 = 均衡のとき。
#:                      ⚠ 生存の劣勢は長さを見ずに支援 → 生存の 2 は均衡のときだけ効く）
#:   magic_bonus        ★3 つとも読む（`actions.lua` 攻撃呪文の見立て）。⚠ 以前は節約が魔法の役を
#:                      作らず 0.6 は死んでいた → ★節約も「はっきり短くなる」なら撃つので効く
#:   mp_floor           ★auto 0.0 / save 0.5 を読む（`Actions.mp_allows`）。⚠ forbid の 1.1 は消した
#:                      （★使用禁止は床ではなく先に抜ける = 読む所が無かった）
TUNING = {
    "short_turns": 2,          #: ★これ以下で倒せるなら「消化戦」
    "margin": 1.5,             #: ★優勢 / 劣勢の境目（ターン差）
    "danger_hp": 0.3,          #: ★これ未満の HP 比で「危ない」
    "critical_hp": 0.15,       #: ★これ未満で「瀕死」
    #: ★回復に手番を使い始める HP 比。
    #:   ⚠⚠ 2026-09-21（RX3-0327 §9-1）: 最短撃破を **0.40 → 0.25** に下げました。
    #:     ★依頼者「防御で1手捨てるより攻撃で終わるなら攻撃を優先する」
    #:     ⚠ 以前の 0.40 は 3 作戦で**最も早く**回復していました（節約 0.35 より早い）。
    #:   ★`critical_hp`（0.15）は据え置き = 瀕死の安全網は残します。
    "heal_at": {S.LEVELING: 0.25, S.ECONOMY: 0.35, S.SURVIVAL: 0.6},
    "mp_floor": {S.MP_AUTO: 0.0, S.MP_SAVE: 0.5},   #: ★使ったあとに残す MP の比（⚠ forbid は置かない）
    #: ★攻撃呪文の見込みに掛ける作戦の重み（★gain = (見込み × 重み − 物理) / こちらの物理 1 ターン分）
    "magic_bonus": {S.LEVELING: 1.3, S.ECONOMY: 0.6, S.SURVIVAL: 0.9},
    #: ★道具で唱える攻撃（まどうしのつえ など / RX3-0213）に掛ける重み。★どの作戦も 1.0。
    #:   ⚠ 節約の 0.6 は「MP を払う」ことの重み。★道具は MP を使わない
    #:   （ROM は道具の効果で MP の判定と消費を通らない / `dq3rom/item_meta.py` の battle_effect）
    "magic_bonus_item": {S.LEVELING: 1.0, S.ECONOMY: 1.0, S.SURVIVAL: 1.0},
    #: ★撃つのに要る gain（★速攻は「saved ≧ 1 か これ以上」/ 節約は「saved ≧ 1 かつ これ以上」/
    #:   生存は 0 = 物理より強ければ。⚠ saved = 1 体ずつ数えて何ターン短くなるか）
    #: ⚠⚠ 最短撃破の 0.0 は「MP を節約するための足切りをしない」という意味です（RX3-0327 §4-3）。
    "magic_min_gain": {S.LEVELING: 0.0, S.ECONOMY: 0.5, S.SURVIVAL: 0.0},
    #: ★単体の呪文は「物理の何倍」で、はっきり強いとみなすか（★例: 物理 20 / 魔法 70 は 3.5 倍）
    #:   ⚠⚠ 最短撃破では **1.0**（= 倍率の足切りをしない / RX3-0327 §4-2）。
    #:     ★依頼者「倍率ではなく、戦闘終了までの手数が減るかを優先する」
    "magic_single_ratio": {S.LEVELING: 1.0, S.ECONOMY: 2.0, S.SURVIVAL: 1.5},
    #: ★撃たない: 物理だけで group ターン以内に片づく / 敵 1 体で single ターン以内（★弱い単体）
    #:   ⚠⚠ `single` は**最短撃破では見ません**（RX3-0327 §4-1 / `judge_magic` の `shortest`）。
    #:     ★依頼者「物理で2ターン以内だから魔法を使わない、という条件を廃止する」
    #:   ★`group`（物理でこのターン片づく）は**どの作戦でも見ます**
    #:     （⚠ もう終わるので、呪文を撃ってもターンは減らない）。
    "magic_skip_rounds": {"group": 1, "single": 2},
    #: ★★ 即死を候補に入れる最低の成功率（RX3-0322 → RX3-0327 §6）。
    #:   ⚠⚠ 最短撃破は **0.0**（= 固定の足切りをしない）。
    #:     ★依頼者「即死成功率そのものでは切らず、期待効果 gain で比較する。
    #:       極端に低い期待値なら自然に負ける形にする」
    #:   ⚠ ほかの作戦は今までどおり 0.5（★低い確率で MP を捨てない）。
    "beat_min_rate": {S.LEVELING: 0.0, S.ECONOMY: 0.5, S.SURVIVAL: 0.5},
    "support_min_turns": {S.LEVELING: 4, S.ECONOMY: 3, S.SURVIVAL: 2},
    "item_heal": 30,           #: ★やくそうの回復の目安
    # ★★ 敵の行動から出る脅威の割増（RX3-0136 / 2026-09-09）。
    #   ⚠⚠ **これも手置きの目安です**（★どれだけの頻度でその行動を選ぶかは未解析）。
    #   ★ですが「持っているか / 持っていないか」は ROM から出た事実です。
    #   ⚠ 実戦 fixture が増えたら、★指示書 §9 の別 WI で測って直します。
    "enemy_party_attack": 1.5,  #: ★全体攻撃を持つ群（⚠ 1 人でなく全員に届く）
    "enemy_status_threat": 1.2,  #: ★眠り・封じ・混乱を持つ群
    # ★★ 物理の見込みの補正（RX3-0226 / 2026-09-13 依頼者「守備力をめちゃ上げる敵 … 消化戦になって負ける」
    #   「マヌーサ食ったときも … ゴリ押せる状況かが判断出来てない」）。
    #: ★マヌーサ（幻）の人の物理が当たる率。⚠ **目安ではなく ROM の事実**:
    #:   JP bank 8 $96EC `LDA $073C,X / AND #$10 / BEQ / JSR 乱数 / CMP #$A0 / BCS` → 乱数 < $A0 で空振り
    #:   → 当たるのは (256 − 160) / 256 = 0.375（⚠ 依頼者の記憶の 50% より低い）。
    #:   ★`tests/test_dq3_battle_ai_estimate.py` が ROM の CMP の値と突き合わせる
    "illusion_hit_rate": 0.375,
    #: ★前のターンに物理だけが向かった群の減りが、見込みのこの比より小さければ、実測の比で物理を見る
    #:   （⚠ 表・RAM の守備力でも説明できない「通らない」の保険。★手置きの目安）
    "observed_ratio": 0.5,
    #: ★見込みがこれより小さいターンは測らない（⚠ ばらつき・会心・端数で鳴らない）
    "observed_min_expect": 8,
    # ★★ マホトラ（RX3-0260 / 2026-09-14 依頼者の小WI「リソース節約時のマホトラ活用」）。⚠ 手置きの目安
    #: ★優勢のとき、その人の物理がこちらの物理 1 ターン分のこの比以下なら「攻撃の寄与が低い」（⚠ 消化戦は見ない）
    "drain_low_share": 0.25,
    #: ★マホトラが効く確率（★耐性の段 → `Catalog.success_rate`）がこれ未満の敵には使わない（★成功がごく低い）
    "drain_min_rate": 0.5,
    # ★★ 最短撃破 v1.2 — 回復手番の削減（RX3-0332 / 2026-09-21 依頼者の指示書 §12）。
    #: ⚠⚠ **2026-09-21 に役目を終えました**（★RX3-0337 / v1.3）。
    #:   ★眠りと幻の継続は **ROM で確定**したので、`actions.lua` の定数が正本です:
    #:
    #:   ```text
    #:   眠り  Actions.SLEEP_EXPECTED_TURNS = 2.207  （★JP bank4 $8BC3 ＋ 表 $B4F3）
    #:   幻    ★自然解除が無い → 残りターンぶん      （★$0531,X を落とす命令が無い）
    #:   ```
    #:
    #:   ⚠ 消さずに残すのは、★古い生成物（`work/generated/`）がまだ持っているためです。
    #:     ⚠ 読む側はもう居ません（`grep status_effect_turns` は here だけ）。
    "status_effect_turns": 1,
}


#: ★★ 敵の行動 64 種 → AI が使う抽象（RX3-0136 / 2026-09-09 / 指示書 v1.1 §6）。
#:
#:   ⚠⚠ **手で敵ごとの表を作りません。** ★行動 ID は `RX3-0039` が ROM から解いてあり
#:     （139 体 / 未知 0 件）、ここはその**分類の言い換え**だけです。
#:
#:   ```text
#:   physical_damage  殴る（★会心・眠り・毒・麻痺つきも含む）
#:   magic_damage     呪文・息（★`spell_party_*` は**パーティ全体**）
#:   heal             回復・蘇生（⚠ こちらの削りを戻す = 撃破を急ぐ相手）
#:   status           眠り・封じ・混乱・即死など（★threat を足す）
#:   support          自分側を強くする
#:   special          特技・仲間を呼ぶ
#:   escape           逃げる
#:   unknown          ⚠ 分からない（★安全側のまま）
#:   ```
ACTION_CLASS: dict[str, str] = {
    "wait": "other",
    "defend": "other",
    "attack": "physical_damage",
    "flee": "escape",
    "reinforce": "special",
    "dance": "special",
    "breath": "magic_damage",
    "spell_damage": "magic_damage",
    "spell_instadeath": "status",
    "spell_status": "status",
    "special": "special",
    "spell_buff": "support",
    "spell_revive": "heal",
    "heal": "heal",
}

#: ★★ 「パーティ全体へ届く」と分かる行動（⚠ 名前が範囲を持っているものだけ）。
#:
#:   ⚠ 逆アセンブルの関数名が `spell_party_*` で分かれているものは **inferred**、
#:     ★息（`breath_*`）は範囲が名前に出ていないので**入れません**（⚠ 推測しない）。
PARTY_WIDE_PREFIX = "spell_party_"


#: ★★ 行動の選び方の重み（RX3-0357 / ⚠ **ROM の事実** / JP bank4 `$34C7`）。
#:
#:   ⚠⚠ 8 枠は均等ではありません。★敵ごとの 2bit `select_mode` がどれを使うか決めます。
#:   ★`mode 3` は表を使わず**順ぐり**（⚠ 長い目で見れば 1/8 ずつ）。
SELECT_WEIGHTS: dict[int, tuple[int, ...]] = {
    0: (0x20,) * 8,
    1: (0x12, 0x16, 0x1A, 0x1E, 0x22, 0x26, 0x2A, 0x2E),
    2: (2, 4, 6, 8, 0x0A, 0x0C, 0x0E, 0xC8),
    3: (1,) * 8,
}

#: ★成立判定の型（RX3-0358 / ⚠ 旧 `unknown_pair_10_11`）。
#:
#:   ```text
#:   0  ★見せ方の枝（⚠ MP もマホトーンも見ない）
#:   1  ★通常（MP のみ）
#:   2  ★純粋な呪文（MP ＋ **マホトーン**）
#:   3  ★1 と同じ（⚠ ROM は `CMP #2` でしか区別しない）
#:   ```
GATING_SPELL = 2

#: ★呪文の move ID の範囲（⚠ この外は MP を払わない / `_b4_s28` の `CPX #$13` と `#$3B`）
SPELL_MOVE_FIRST, SPELL_MOVE_LAST = 0x13, 0x3A

#: ★成立条件（RX3-0358 / ⚠ v1 で反映するのは**この 4 つだけ**）。
#:
#:   ```text
#:   mp        ⚠ MP が足りなければ不成立（★純粋な呪文のみ）
#:   silence   ⚠ マホトーン（`$0530` bit5）なら不成立（★純粋な呪文のみ）
#:   heal      ⚠ HP が閾値未満の仲間が居なければ不成立
#:   revive    ⚠ 死者が居なければ不成立
#:   ```
#:   ⚠⚠ **耐性は入れません**（★`_b4_s28` は耐性を 1 か所も見ない = 効果失敗であって
#:     行動不成立ではない / RX3-0358 §9）。
NEED_HEAL_TARGET = tuple(range(0x31, 0x3B))        #: ★回復（move $31-$3A）
NEED_DEAD_TARGET = (0x2F, 0x30)                    #: ★蘇生


def _enemy_mp_costs(prg: bytes) -> list[int]:
    """★敵呪文の MP コスト表（RX3-0358 / ⚠ ROM から / move `$13`〜`$3A` の 40 件）。

    ⚠⚠ 表の場所は `_b4_s28` の `LDA _bs_enemy_mp_cost-$13,X` から**逆算**します
      （★番地を書き写さない / 版が変われば命令ごと動く）。
    """
    import re

    # ★`PHA / JSR / PLA / CMP $59 / BEQ / BCC`（⚠ ROM 全体で 1 件 / RX3-0358 で照合済み）
    hits = [m.start() for m in re.finditer(rb"\x48\x20..\x68\xC5\x59\xF0.\x90.", prg, re.S)]
    if len(hits) != 1:
        return []                                   # ⚠ 見つからない版では表を出さない
    op = prg[hits[0] - 3:hits[0]]
    if op[0] != 0xBD:                               # ⚠ LDA abs,X でなければ諦める
        return []
    addr = (op[1] | (op[2] << 8)) + SPELL_MOVE_FIRST
    bank = 4                                        # ★`_b4_s28` は bank4
    off = bank * 0x4000 + (addr - 0x8000)
    n = SPELL_MOVE_LAST - SPELL_MOVE_FIRST + 1
    got = prg[off:off + n]
    return list(got) if len(got) == n else []


def _move_damage(prg: bytes, move_id: int, category: str) -> int:
    """★その行動 1 回の期待ダメージ（⚠ 呪文・ブレスだけ / ★分からなければ 0）。

    ⚠⚠ **推測で埋めません**。★ROM から読めないものは 0 のままにします
      （0 は「ダメージが無い」ではなく「**分からない**」の意味です）。

    ## ⚠⚠ 敵の呪文は**敵の表**から引きます（RX3-0361 / 2026-09-22）

      ★以前は味方の呪文表（`spells` の `base` / `delta`）を使っていました。
      ⚠ これは**味方が唱えたときの威力**で、敵のそれとは別の表です。

      ```text
      例  move 0x19（イオナズン）  ★敵 60..79 → 69   ⚠ 味方表 120..160 → 140
      実測 88 枠すべて過大（★1.22 倍 〜 2.01 倍）
      ```

      ★呪文もブレスも `DAMAGE_RANGE_TABLE` の同じ 18 件から、
      ⚠ **同じ 1 本の命令**（`_DAMAGE_READER`）で引かれます。
    """
    from dq3rom import enemy_detail as ED

    try:
        if category == "breath":
            got = ED.breath_damage(prg, move_id)
            if got is None:
                return 0
            _kind, lo, hi = got
            return int((lo + hi) / 2)
        if category == "spell_damage":
            got = ED.spell_damage(prg, move_id)
            if got is None:
                return 0
            lo, hi = got
            return int((lo + hi) / 2)
    except Exception:                                      # noqa: BLE001 ⚠ 読めない版では 0
        return 0
    return 0


#: ★蘇生の行動（⚠ ザオラル / ザオリク）。★戻る HP は**まだ読めていません**（RX3-0364）。
REVIVE_MOVES = (0x2F, 0x30)


def _regen_of(prg, move_id: int) -> dict:
    """★★ 敵側に HP が戻る行動を 1 枠ぶん（RX3-0363 / 2026-09-22）。

    ```text
    heal_hp     ★1 回で戻る HP（⚠ 0 = 分からない）
    heal_full   ★全回復（⚠ 量は相手の最大 HP 次第なので Lua が決める）
    heal_group  ★群のみんなに届く（ベホマラー / ベホマズン）
    calls       ★呼ぶ敵の ID（⚠ `"self"` = 自分と同じ敵 / nil = 呼ばない）
    revives     ⚠ 蘇生（★戻る HP は未解析 / 数だけ数える）
    ```

    ⚠⚠ **推測で埋めません。** ★読めないものは入れません（`RX3-0361` の教訓）。
    """
    from dq3rom import enemy_detail as ED

    out: dict = {}
    if move_id in REVIVE_MOVES:
        out["revives"] = True
    if prg is None:
        return out
    try:
        # ★★ 蘇生で戻る HP（RX3-0368 / ⚠ 最大 HP に対する割合 × 成功率）
        rev = ED.revive_effect(prg, move_id)
        if rev is not None:
            out["revive_ratio"], out["revive_success"] = rev[0], rev[1]
        got = ED.heal_amount(prg, move_id)
        if got == "full":
            out["heal_full"] = True
            out["heal_group"] = ED.heals_whole_group(move_id)
        elif got is not None:
            out["heal_hp"] = int((got[0] + got[1]) / 2)
            out["heal_group"] = ED.heals_whole_group(move_id)
        if move_id == ED.REINFORCE_SELF_MOVE and ED.reinforce_calls_self(prg):
            out["calls"] = "self"
        else:
            tgt = ED.shared_move_target(prg, move_id)
            if tgt is not None and tgt[0] == "monster":
                out["calls"] = int(tgt[1])
                # ⚠⚠ 呼べるのは**もう場に居る種類**だけ（★JP bank4 $8E1C）。
                #   ★居なければ手番を 1 つ捨てます（⚠ 何も起きない）。
                if ED.reinforce_needs_same_kind_present(prg):
                    out["calls_present_only"] = True
    except Exception:                                      # noqa: BLE001 ⚠ 読めない版では何も入れない
        return out
    return out


#: ★味方の手番を奇う状態（RX3-0373 / ⚠ 毒は奥へ入らない）
#: ★★ 味方の手番を**奪う**状態（RX3-0373 → RX3-0375）。
#:
#:   ⚠ 毒は手番を奪いません。★マヌーサ・マホトーンも「奪う」ではなく**弱める**ので、
#:     ⚠⚠ ここには入れず**別の欄**で持ちます（`weakens`）。
LOST_ACTION_STATUS = ("sleep", "paralyze", "confuse")
#: ★手番は奪わないが、⚠ こちらの手を**弱める**状態（RX3-0375）
#:
#:   ```text
#:   illusion   ⚠ 物理が外れる（★命中 0.375 / `Situation.ILLUSION_HIT`）
#:   stopspell  ⚠ 呪文が使えない
#:   ```
WEAKEN_STATUS = ("illusion", "stopspell")


def _status_of(prg, move_id: int) -> dict:
    """★★ その行動が味方に与える状態異常（RX3-0373 / 2026-09-22）。

    ```text
    status_kind  ★sleep / poison / paralyze（⚠ 読めなければ入れない）
    status_prob  ★運試しの閾値（⚠ `P = (384 - 運) x 閾値 / 65536`）
    steals_turn  ⚠ 手番を奇うか（★眠り・麻痺だけ / ★毒は奇わない）
    ```

    ⚠⚠ **命令から読めたものだけ**入れます。
      ★味方へのラリホー・メダパニ・マホトーンは**まだ未解析**です（`RX3-0374`）。
    """
    from dq3rom import enemy_detail as ED

    if prg is None:
        return {}
    try:
        got = ED.status_of_move(prg, move_id)
        if got is None:
            return {}
        kind, prob = got
        if not ED.luck_formula_ok(prg):
            return {"status_kind": kind}      # ⚠ 確率は入れない
        return {"status_kind": kind, "status_prob": int(prob),
                "steals_turn": kind in LOST_ACTION_STATUS,
                "weakens": kind if kind in WEAKEN_STATUS else None}
    except Exception:                                      # noqa: BLE001 ⚠ 読めない版では何も入れない
        return {}


def _actions_summary(detail, mp_costs=None, prg=None) -> dict:
    """★8 枠の行動を、AI が使う 1 行にまとめる（⚠ 生の ID も残す）。"""
    from dq3rom import enemy_detail as ED

    kinds: dict[str, int] = {}
    party_wide, unknown = 0, 0
    ids = []
    slots = []
    for act in detail.actions:
        move_id = int(act["move_id"])
        ids.append(move_id)
        klass = ACTION_CLASS.get(act["category"])
        if klass is None:
            unknown += 1
            klass = "unknown"
        # ⚠⚠ `kinds` は**legacy が読む旗**（`acts.status` / `acts.party_attack`）の元です。
        #   ★ここは**直しません**（RX3-0371 / 依頼者 §14「製品判断は変えず、shadow 分類のみ」）。
        kinds[klass] = kinds.get(klass, 0) + 1
        # ★★ ダメージを出さない「息」は v1 では **状態異常**（RX3-0371）。
        #
        #   ⚠⚠ 0x10 / 0x11 / 0x12 は ROM で**ダメージを 1 も出しません**（★眠り / 毒 / 麻痺）。
        #     ⚠ 名前（`scorching_breath`）から「灼熱 ＝ 大ダメージ」と思いがちですが、
        #     ★実際は麻痺にするだけです。→ ⚠ **ダメージの穴ではなく分類の誤り**でした。
        #   ★`klass` だけ差し替えます（⚠ `kinds` は上でもう数え終わっています）。
        if prg is not None and klass == "magic_damage":
            try:
                if ED.breath_status(prg, move_id) is not None:
                    klass = "status"
            except Exception:                              # noqa: BLE001 ⚠ 読めない版では触らない
                pass
        wide = str(act["name"]).startswith(PARTY_WIDE_PREFIX)
        if wide:
            party_wide += 1
        # ★★ Enemy Action Model v1 が読む 1 枠（RX3-0359）
        cost = 0
        if (mp_costs and SPELL_MOVE_FIRST <= move_id <= SPELL_MOVE_LAST
                and move_id - SPELL_MOVE_FIRST < len(mp_costs)):
            cost = int(mp_costs[move_id - SPELL_MOVE_FIRST])
        slots.append({
            "move_id": move_id,
            "category": act["category"],
            "klass": klass,
            "mp": cost,
            # ⚠ 呪文・ブレスの 1 回ぶん（★0 = 読めなかった / 推測で埋めない）
            "dmg": (_move_damage(prg, move_id, act["category"])
                    if prg is not None else 0),
            "party_wide": wide,
            # ⚠ 成立条件（★v1 で見るのはこの 3 つだけ / 耐性は見ない）
            "needs_heal_target": move_id in NEED_HEAL_TARGET,
            "needs_dead_target": move_id in NEED_DEAD_TARGET,
            # ★★ 敵の粘り（RX3-0363 / ⚠ 1 回で敵側に戻る HP）
            **_regen_of(prg, move_id),
            # ★★ 味方の手番を奪う行動（RX3-0373）
            **_status_of(prg, move_id),
        })
    control = detail.control or {}
    return {
        "slots": slots,
        # ★行動の選び方（RX3-0357 / ⚠ ROM の 2bit）
        "select_mode": int((control.get("select_mode") or {}).get("value", 0)),
        # ★成立判定の型（RX3-0358 / ⚠ 旧 unknown_pair_10_11）
        "gating_mode": int((control.get("unknown_pair_10_11") or {}).get("value", 0)),
        "kinds": kinds,
        "ids": ids,
        # ★AI がそのまま見る旗（⚠ 意味は上の分類だけ。★敵ごとの攻略ではない）
        "heal": kinds.get("heal", 0) > 0,
        "party_attack": party_wide > 0,
        "status": kinds.get("status", 0) > 0,
        "escape": kinds.get("escape", 0) > 0,
        "reinforce": kinds.get("special", 0) > 0,
        "unknown": unknown,
        # ★1 ターンの行動回数（⚠ `RX3-0039` が high-confidence とした 2bit）
        "per_turn": int(((detail.control or {}).get("actions_per_turn") or {}).get("value", 0)),
    }


def _enemies_table(prg_ident) -> dict:
    """★敵 139 体の 能力・耐性・行動（⚠ 名前は入れない。★ROM の表そのまま）。"""
    from dq3rom import enemies as EN
    from dq3rom import enemy_detail as ED

    rows = EN.read_all(prg_ident)
    details = {d.enemy_id: d for d in ED.read_all(rows)}
    # ★敵呪文の MP コスト表は 1 回だけ引く（RX3-0359 / ⚠ 139 体ぶん引き直さない）
    mp_costs = _enemy_mp_costs(prg_ident.rom.prg)
    out = {}
    for e in rows:
        d = details.get(e.enemy_id)
        resist = {}
        acts = None
        if d is not None:
            for name, got in d.resistances.items():
                resist[name] = int(got.get("level", 0))
            acts = _actions_summary(d, mp_costs, prg_ident.rom.prg)
        out[e.enemy_id] = {"hp": e.hp, "attack": e.attack, "defense": e.defense,
                           "agility": e.agility, "mp": e.mp, "resist": resist}
        if acts is not None:
            out[e.enemy_id]["acts"] = acts
    return out


#: ★★ 表に入れる道具の効き方（RX3-0213 → RX3-0346 / 2026-09-21）。
#:
#:   ⚠⚠ **`attack` しか入れていませんでした。** ★依頼者「力のたてや、けんじゃのいしを
#:     … つかう」で判明。⚠ ROM を全件引くと、★回復になる品が 2 つあります:
#:
#:   ```text
#:   id 58  ちからのたて    ベホイミ    heal  ally_single  ⚠ consumed 無し（★減らない）
#:   id 80  けんじゃのいし  ベホマラー  heal  self_party   ⚠ consumed 無し（★減らない）
#:   ```
#:
#:   ⚠ `instant` / `debuff` / `buff` / `cure`（ゆうわくのけん・くさなぎのけん 等）は
#:     ★まだ入れません（⚠ 支援の式に載せる別の話 / RX3-0346 の Scope）。
BATTLE_ITEM_KINDS = ("attack", "heal")


def _battle_items(prg: bytes, spells: dict, rom_path, charset) -> dict[str, list[dict]]:
    """★戦闘で使うと呪文として働く道具（RX3-0213 / RX3-0346）。効き方ごとに分けて返す。

    ★効果は ROM の `_bs_item_effect_tbl`（`dq3rom/item_meta.battle_effects`）から。
    ★名前は実行時に ROM から（⚠ repo に持たない）。

    ⚠ 使うと減る品は入れない（★減らない品だけ / ⚠ 在庫を黙って減らさない）。
    ⚠ 名前のタイルが作れない品も入れない（★一覧で探せない = 押せない）。
    ★`use_mask` は使える職業の bit（⚠ None は「表を引かない = 誰でも」）。
    ★`target` も渡す（⚠ 回復は `ally_single` と `self_party` で狙い方が違う / RX3-0335）。
    """
    from dq3rom import item_meta as IM
    from ..knowledge import rom_names as RN
    from ..phase0.generate_lua import tile_bytes

    rows = {r.item_id: r for r in IM.build(prg)}
    out: dict[str, list[dict]] = {k: [] for k in BATTLE_ITEM_KINDS}
    for item_id, sid in sorted(IM.battle_effects(prg).items()):
        spell, meta = spells.get(int(sid)), rows.get(item_id)
        if spell is None or meta is None:
            continue
        kind = spell.get("kind")
        if kind not in out:
            continue
        if "consumed" in meta.flags:
            continue
        name = RN.item(item_id, rom_path)
        try:
            tiles = tile_bytes(name, charset) if name else []
        except Exception:                                  # noqa: BLE001
            tiles = []
        if not tiles:
            continue
        out[kind].append({"id": item_id, "name": name, "tiles": tiles, "spell_id": int(sid),
                          "consumed": False, "use_mask": meta.use_mask,
                          "target": spell.get("target")})
    return out


def build(value: S.BattleAiSettings, members=None, rom_path=None) -> dict:
    """★Lua が読む 1 本の中身（⚠ 純粋な関数。★ファイルは書かない）。"""
    from dq3rom import profile as P
    from ..knowledge import rom_names as RN
    from ..knowledge import spell_info as SI
    from ..phase0.generate_lua import tile_bytes
    from retroux.core.text import Charset
    import json

    roles = S.effective_roles(value, members or [], rom_path)
    data = {
        "revision": int(time.time() * 1000),
        "strategy": value.strategy,
        # ★★ 実効の MP 制約（RX3-0327）。⚠ 最短撃破では人の設定を使いません。
        #   ★保存値（`value.mp_policy`）は**そのまま残します**（作戦を戻したら復活する）。
        #   ⚠⚠ 呪文がかき消される床の `forbid` はここを通りません
        #     （★`auto_v0.lua` が実行時に入れる / 絶対に解除しない）。
        "mp_policy": S.effective_mp(value.strategy, value.mp_policy),
        "roles": {slot: roles[slot].as_list() for slot in S.SLOTS},
        # ★★ 作戦ごとに「使わせない呪文」（RX3-0370 / ⚠ 作戦で引けるように全部渡す）。
        #   ⚠⚠ **いまの作戦のぶんだけ渡しません**。★Lua は `ctx.strategy` で引くので、
        #     検査や実行時の切り替えで作戦が変わったときに**表と食い違わない**ようにします。
        "banned": {name: sorted(value.bans_of(name)) for name in S.STRATEGIES
                   if value.bans_of(name)},
        "tuning": TUNING,
        "spells": {},
        "blocks": [],
        "enemies": {},
        "items": {},
        "ok": False,
    }
    target = pathlib.Path(rom_path) if rom_path else RN.DEFAULT_ROM
    if not target.exists():
        data["error"] = "ROM がありません"
        return data
    try:
        ident = P.load_and_identify(target)
        profile = json.loads((ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
                             .read_text(encoding="utf-8"))
        charset = Charset(profile["text"]).table
        table = SI.lua_table(target)
        spells = {}
        for sid, row in table["spells"].items():
            name = RN.spell(sid, target)
            got = dict(row)
            got["name"] = name
            try:
                got["tiles"] = tile_bytes(name, charset) if name else []
            except Exception:                              # noqa: BLE001
                got["tiles"] = []                          # ⚠ 画面で探せない（★使わない）
            spells[int(sid)] = got
        data["spells"] = spells
        data["blocks"] = table["blocks"]
        data["enemies"] = _enemies_table(ident)
        # ★★ 戦闘に入る敵の数の上限（RX3-0368 / ⚠ 仲間呼びはここで頭打ち）。
        #   ⚠ 読めなければ入れません（★推測で埋めない = Lua 側は頭打ちしない）
        from dq3rom import enemy_detail as _ED

        _slots = _ED.reinforce_slot_limit(ident.rom.prg)
        if _slots is not None:
            data["enemy_slots"] = _slots
        # ★★ 行動 ID → 分類（RX3-0371 / ⚠ 実測ログで「何をしたか」を読むため）。
        #   ⚠ 名前（`scorching_breath` など）は入れません。★分類だけで足ります。
        data["move_names"] = {m: _ED.move_category(m) for m in range(64)}
        # ★★ 味方が眠っているターン数（RX3-0373 / ⚠ 敵とは**表が違う**）
        _sleep = _ED.sleep_turns(_ED.party_sleep_table(ident.rom.prg))
        if _sleep is not None:
            data["party_sleep_turns"] = round(_sleep, 3)
        # ★混乱が 1 ターンで覚める確率（RX3-0375 / ⚠ 期待 8 ターン / 戦闘の長さで頭打ち）
        _wake = _ED.confuse_wake_rate(ident.rom.prg)
        if _wake:
            data["party_confuse_turns"] = round(1.0 / _wake, 3)
        # ★戦闘で使う道具（⚠ v1 は やくそう だけ / RX3-0066 の ID）
        from ..knowledge import restock as RS

        herb = RN.item(RS.HERB, target)
        # ★戦闘で使うと呪文として働く道具（RX3-0213 まどうしのつえ / RX3-0346 ちからのたて）
        by_kind = _battle_items(ident.rom.prg, spells, target, charset)
        data["items"] = {"herb": {"id": RS.HERB, "name": herb,
                                  "tiles": tile_bytes(herb, charset) if herb else [],
                                  "heal": TUNING["item_heal"]},
                         "attack": by_kind["attack"],
                         "heal_items": by_kind["heal"]}
        data["ok"] = True
    except Exception as exc:                               # noqa: BLE001 - ★理由を残す
        data["error"] = "表を作れません: %s" % exc
    return data


def write(data: dict, out_dir: pathlib.Path | None = None) -> pathlib.Path:
    """★書きかけを読ませない（`generate_lua.write_lua` と同じ作法）。

    ⚠ 書き先の既定は**呼んだ時の** `OUT_DIR`（★検査が一時フォルダへ向けられるように / RX3-0215）。
    """
    from retroux.core.config.generate_lua import to_lua

    out_dir = pathlib.Path(out_dir) if out_dir is not None else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("%s.lua" % MODULE)
    body = ("-- 自動生成ファイル。直接編集しないこと。\n"
            "-- 生成: dq3/battle_ai/generate.py（★戦闘 AI の設定と ROM の表）\n"
            "return %s\n" % to_lua(data))
    tmp = out_dir / ("%s.%d.tmp" % (MODULE, os.getpid()))
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, out_path)
    return out_path


def regenerate(value: S.BattleAiSettings, members=None, rom_path=None,
               out_dir: pathlib.Path | None = None) -> dict:
    """★設定を変えたら呼ぶ（★画面の窓から）。戻り値は書いた中身。⚠ 書き先の既定は呼んだ時の `OUT_DIR`。"""
    data = build(value, members, rom_path)
    write(data, out_dir)
    return data


__all__ = ["build", "write", "regenerate", "TUNING", "OUT_DIR", "MODULE"]
