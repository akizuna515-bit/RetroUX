-- 抽象コマンド → 実コマンド（RX3-0126 / 2026-09-08）— ★指示書 §10〜§13。
--
-- ```text
-- 役割      抽象コマンド              実コマンド
-- ヒール    回復 / 蘇生               spell:ホイミ→p2 / item:やくそう→p2 / defend
-- 魔法攻撃  群 / 全体 / 単体を焼く    spell:ギラ→g2 / attack（★物理のほうが強い）
-- 支援      守りを上げる / 敵を弱める spell:スクルト / spell:ルカナン→g1 / attack
-- 物理攻撃  一番早く減らせる群を殴る  attack→g1
-- 防御      耐える                    defend（⚠ 窓に無ければ attack）
-- ```
--
-- ## ★DQ2 から継いだもの
--
--   - 物理の目安 … `Damage.physical`
--   - 支援の得   … `Support.turn_gain`（★整数ターンで数える。端数の得は 0）
--   - 予約       … `party_plan.reserve_damage`（⚠ 同じ群に全員が向かない）
--
-- ## ⚠ 実コマンドの `target`
--
--   `{group = k}` … 敵の窓の k 番目の群（★1 始まり）
--   `{ally = slot}` … 味方の一覧のその人
--   nil            … 選ぶ窓が出ない（自分 / 味方全体 / 敵全体）

local Actions = {}

local Catalog, Damage, Support, Roles = nil, nil, nil, nil
function Actions.use(mods)
  Catalog = mods.catalog or Catalog
  Damage = mods.damage or Damage
  Support = mods.support or Support
  -- ⚠ 「資源を使わない手か」の規則は `roles.lua` の 1 か所だけ（★ここに写さない / RX3-0396）
  Roles = mods.roles or Roles
end

--: ★作戦の内部の語（⚠ 画面の名前は pipeline / settings が持つ。ここは判断だけ）
local LEVELING, ECONOMY, SURVIVAL = "leveling", "economy", "survival"

local function avg_of(s, hp_max)
  if s.base == 255 then return hp_max or 255 end
  return (s.base or 0) + (s.delta or 0) / 2
end

local function tuned(t, key, sub, default)
  local v = (t or {})[key]
  if type(v) == "table" then v = v[sub] end
  return tonumber(v) or default
end

--- ★MP の制約で、その呪文を今使ってよいか。
--
--   おまかせ … 足りれば使う（★床 `mp_floor.auto` = 0.0）
--   温存     … 使ったあとも最大 MP の半分が残るとき（⚠ 緊急なら使う）
--              ★画面の名前は「半分程度残す」（RX3-0198）。⚠ 攻撃呪文の禁止ではない:
--              「速攻＋半分程度残す」は、床より上なら攻撃呪文も使う（依頼者の指示書）
--   使用禁止 … 使わない（★緊急でも解除しない / §13 / ⚠ 床ではなく先に抜ける）
--
--   ★RX3-0198: 床は MP 制約ごとに `mp_floor[policy]` から読む（⚠ 以前は save だけ読み、
--   auto の 0.0 は死んでいた）。⚠ forbid の床は置かない（★ここで先に抜けるので読む所が無い）。
function Actions.mp_allows(member, spell, ctx, urgent)
  local policy = ctx.mp_policy or "auto"
  if policy == "forbid" then return false, "MP使用禁止" end
  local cost = spell.mp or 0
  if cost > (member.mp or 0) then return false, "MP不足" end
  if not urgent then
    local floor = tuned(ctx.tuning, "mp_floor", policy, policy == "save" and 0.5 or 0.0)
    if floor > 0 and (member.mp - cost) < (member.mp_max or 0) * floor then
      return false, "MP温存"
    end
  end
  return true, nil
end

local function spell_action(s, target, why)
  return {kind = "spell", spell = s.id, spell_tiles = s.tiles, name = s.name,
          target = target, fallback = "attack", why = why}
end

local function attack_action(group, why)
  return {kind = "attack", target = group and {group = group} or nil, why = why}
end

--- ★その人の物理の倍率（★マヌーサで当たる率 × 実測の比 / RX3-0226）。⚠ 戦況に無ければ 1.0
local function phys_scale(member, sit)
  local s = sit and sit.phys_scale and sit.phys_scale[member.slot]
  return tonumber(s) or 1.0
end

--- ★その人がその群を殴ったときの見込み。
--   ★RX3-0226: 群の**いまの**守備力（`group.def` / ⚠ 無ければ表）と、その人の倍率を入れる
--   ⚠⚠ 2026-09-20（RX3-0327 §5）: **残り HP で頭打ちにします**。
--     ★攻撃呪文（`spell_effect`）は `min(avg, h)` で頭打ちしていたのに、
--     ⚠ 物理だけ残り HP を超えて数えていました（＝ 物理が**過大評価**）。
--     ★依頼者の例: 敵残 HP 20 / 通常攻撃の期待値 80 → **20** と数える。
--   ★頭打ちの相手は `first_hp`（生きている先頭の敵）。⚠ 単体の呪文と**同じ相手**にして、
--     初めて物理と呪文が公平に比べられます（`situation.lua` の `first_hp` の註）。
local function physical_avg(member, sit, group)
  if Damage == nil then return 0 end
  local def = (group and (group.def or (group.stats and group.stats.defense))) or sit.enemy_def
  local est = Damage.physical(member.attack, def)
  local avg = (est and est.avg or 0) * phys_scale(member, sit)
  local cap = group and (group.first_hp or group.hp_sum)
  if cap ~= nil and cap > 0 and avg > cap then avg = cap end
  return avg
end

----------------------------------------------------------------------
-- 物理攻撃
----------------------------------------------------------------------

--- ★どの群を殴るか。★残り HP が少ない群から片付ける（⚠ 生存優先は脅威の大きい群）。
--
--   `plan.reserve_damage` を使い、⚠ もう倒れる見込みの群には向かわない。
--   ★3 つ目の戻り値は理由の語（★開発用の判断ログ / RX3-0198）:
--     heals_itself / highest_threat / lowest_remaining_hp / all_reserved
function Actions.pick_group(member, ctx, sit, plan)
  local best, best_key, my, why = nil, nil, 0, nil
  for _, g in ipairs(sit.groups) do
    if g.alive_n > 0 then
      local remain = g.hp_sum
      if plan ~= nil then remain = plan:hp_after_reserved_damage(g.index, g.hp_sum) end
      if remain > 0 then
        local key, reason
        if ctx.strategy == SURVIVAL and g.threat ~= nil then
          key, reason = -g.threat * 1000 + remain, "highest_threat"
        else
          key, reason = remain, "lowest_remaining_hp"
        end
        -- ★★ 回復する敵は先に片づける（RX3-0136 / 指示書 v1.1 §6）。
        --   ⚠⚠ 削っても戻されるので、★他の群より残り HP が多くても先に向かいます。
        --   ⚠ 数字は足しません。★順番の鍵を 1 段下げるだけ（= 必ず先に来る）。
        if g.can_heal == true then key, reason = key - 1000000, "heals_itself" end
        if best == nil or key < best_key then best, best_key, why = g, key, reason end
      end
    end
  end
  if best == nil then
    -- ⚠ 全部に予約が入っている: 一番残りが多い群へ
    for _, g in ipairs(sit.groups) do
      if g.alive_n > 0 and (best == nil or g.hp_sum > best.hp_sum) then best, why = g, "all_reserved" end
    end
  end
  if best ~= nil then
    my = physical_avg(member, sit, best)
    if plan ~= nil then plan:reserve_damage(best.index, my) end
  end
  return best, my, why
end

--- ★開発用の判断ログの 1 行ぶん（★`AI tune` の行 / pipeline が作戦名を前に付ける）
local function attack_tune(g, why)
  return string.format("target=%s decision=attack reason=%s",
                       g and ("enemy_group_" .. g.index) or "none", why or "no_target")
end

--- ★★ リソース節約の防御 — その人が**このターンに受ける見込み**（RX3-0391）。
--
--   ⚠⚠ `sit.enemy_dpt` は**パーティ全体**の値です。★誰が狙われるかは分かりません。
--   → ⚠ v1 は**生きている人数で均等**に割ります（★近似であることを名前で示す）。
--   ★`Enemy Action Model v1` が本番になれば、⚠ ここを狙われやすさに差し替えられます。
function Actions.defend_expected_incoming(sit)
  local n = #(sit.alive or {})
  if n <= 0 then return 0 end
  return (tonumber(sit.enemy_dpt) or 0) / n
end

--: ★★ 防御で減る割合（⚠ ROM の事実 / JP bank 4 `loc_6A58C`）。
--
--   ```asm
--   LDA _player_battle_order_and_flags,X
--   AND #$20                     ★防御の旗
--   LSR word_4+1 / ROR word_4    ★被害を **1/2**
--   JSR _bs_run_PC_Damage        ★JP $A668（⚠ 被害の共通口）
--   ```
--
--   ⚠ 物理だけではありません（★敵の呪文・ブレスも**この合流点**を通ります）。
Actions.DEFEND_CUT = 0.5

--- ★★ 「戻る HP」を**パーティ 1 ターン**の尺度へ（RX3-0397 / 2026-09-23）。
--
--   ⚠⚠ **単位が 2 つ混ざっていました。**
--
--   ```text
--   ⚠ 回復・防御側  戻る量 ÷ 回復 1 手番ぶん  … **1 人ぶんの手**（actions）
--   ⚠ 攻撃側        物理 ÷ パーティ 1 ターン   … **パーティ 1 ターン**
--   ```
--
--   ★1 ターン ＝ **生きている人数ぶんの手**。→ ⚠ 回復側を `alive_n` で割ってそろえます。
--   ⚠⚠ **4 で固定しません**（★3 人なら 1/3 / 相談相手 §13）。
--
--   ⚠ `alive_n` が 0 / 回復の手立てが無ければ **nil**（★0 で割らない）。
function Actions.heal_turn_gain(amount, ctx, sit)
  local n = #((sit or {}).alive or {})
  if n <= 0 then return nil end
  local per = Actions.heal_per_action(ctx)
  if per == nil or per <= 0 then return nil end
  if (tonumber(amount) or 0) <= 0 then return 0 end
  return amount / per / n
end

--- ★★ その人が持っている「資源を使わない全体回復」（RX3-0398 / 2026-09-23）。
--
--   ⚠⚠ **パーティに石がある、では候補にしません**（★相談相手 §9）。
--     ★その人自身が持っていて、⚠ **使える**手だけです（`caps.heal` に入っている）。
--   ★★ 2026-09-23（RX3-0411）: **狙い方で絞れる**ようにしました。
--     ⚠ 以前は全体回復（`self_party`）しか探せず、★ちからのたて（`ally_single`）は
--       `heal_at` を割るまで 1 度も候補になりませんでした（依頼者 §3）。
function Actions.free_heal_of(caps, target)
  local best = nil
  for _, s in ipairs((caps or {}).heal or {}) do
    if s.target == target and Roles ~= nil
        and Roles.resource_free ~= nil and Roles.resource_free(s) then
      if best == nil or (s.base or 0) > (best.base or 0) then best = s end
    end
  end
  return best
end

--- ★全体の無料回復（⚠ 呼ぶ側の名前は据え置き / RX3-0398）
function Actions.free_party_heal(caps)
  return Actions.free_heal_of(caps, Actions.PARTY_HEAL_TARGET)
end

--: ★単体の無料回復の狙い方（⚠ ROM 実測 / ちからのたて は `ally_single`）
Actions.SINGLE_HEAL_TARGET = "ally_single"

--- ★★ FREE_HEAL_UNIT ― 「無料回復 1 回ぶんの値打ち」（RX3-0411 / 依頼者 §2）。
--
--   ⚠⚠ **手置きの 85 を作りません。** ★その手**自身**の ROM の期待回復量です
--     （★ちからのたて なら ベホイミ の `base` / `delta` がそのまま出ます）。
--   ★欠けがこれ以上あれば、⚠ 1 回ぶんが**溢れずに丸ごと活きます**。
--
--   ⚠ 固定の「HP 60%」のような比率は置きません（★依頼者 §2）。
function Actions.free_heal_unit(s, hp_max)
  if s == nil then return nil end
  return avg_of(s, hp_max)
end

--- ★★ いちばん傷んでいる人（⚠ 生きている人の中で HP 比が最小 / RX3-0411）。
--
--   ⚠ `roles.lua` の予防の回復と**同じ規則**です（★2 か所に書かない）。
function Actions.most_hurt(sit)
  local worst, worst_ratio = nil, nil
  for _, m in ipairs((sit or {}).alive or {}) do
    local r = (m.hp or 0) / math.max(m.hp_max or 1, 1)
    if worst == nil or r < worst_ratio then worst, worst_ratio = m, r end
  end
  return worst
end

--- ★★ 「無料の全体回復を 1 手」と「攻撃を 1 手」を比べる（RX3-0398 / 相談相手 §3〜§6）。
--
--   ```text
--   stone_gain  = Actions.heal_turn_gain(実際に戻る量, ctx, sit)   ★party 1 turn
--   attack_gain = その人の物理 ÷ sit.our_dpt                        ★party 1 turn
--   → ⚠⚠ **`stone_gain > attack_gain` の純比較**（★下駄は置きません / §6）
--   ```
--
--   ⚠⚠ **新しい HP の閾値は作りません**（★相談相手 §2）。
--     ⚠ 90% なら戻る量が小さく、★自然に `attack` が勝ちます。
--
--   ⚠ 使わない場面:
--   ```text
--   ⚠ 作戦が economy でない        （★§16）
--   ⚠ その人が無料の全体回復を持っていない（★§9）
--   ⚠ 戻る量が 0（★満タン）
--   ⚠ 尺度が出せない（`alive_n` が 0 / 回復の手立てが無い）
--   ```
--
--   戻り値: `(使うか, 内訳の表)`
function Actions.proactive_heal(member, caps, ctx, sit)
  local info = {}
  if ctx.strategy ~= ECONOMY then
    info.why = "not_economy"
    return false, info
  end
  -- ★★ ① 全体の無料回復（RX3-0398 / ⚠ ここは今までどおり = 門を足しません）。
  --
  --   ⚠⚠ **石に HP の門を足しませんでした**（★依頼者 §6 の「候補条件」）。
  --     ★RX3-0398 が「新しい HP の閾値は作らない」と決めており、⚠ 依頼者 §7
  --       「かなり積極的でよい」/ §8「毎ターン石でも構わない / 人工的な制約は置かない」
  --       とも、**門を足すほうが反します**（★足すと今より消極的になる）。
  --     ★軽傷で撃たないのは、⚠ 戻る量が小さく `attack_gain` に負けるため（自然停止）。
  local s = Actions.free_party_heal(caps)
  local heal = nil
  if s ~= nil then
    info.scope = "party"
    heal = Actions.party_heal_gain(s, sit)
  else
    -- ★★ ② 単体の無料回復（RX3-0411 / ★ちからのたて / 依頼者 §3〜§5）。
    s = Actions.free_heal_of(caps, Actions.SINGLE_HEAL_TARGET)
    if s == nil then
      -- ⚠ 名前は据え置き（★`roles.lua` が「そもそも持っていない」の印に読む）
      info.why = "no_free_party_heal"
      return false, info
    end
    info.scope = "single"
    -- ⚠⚠ **使い手ではなく、いちばん傷んでいる人**を見ます。
    --   ★`ally_single` は狙う相手を選べます（⚠ ROM の事実 / `Actions.heal` も
    --     `assign.target` へ撃ちます）。→ ★使い手が満タンでも、傷んだ人へ渡せます。
    local worst = Actions.most_hurt(sit)
    if worst == nil then
      info.why = "no_scale"
      return false, info
    end
    info.target = worst.slot
    local unit = Actions.free_heal_unit(s, worst.hp_max)
    local missing = (worst.hp_max or 0) - (worst.hp or 0)
    -- ★★ 「減りそう」も見る（★依頼者 §4 / ⚠ 殴られてから戻すのではない）。
    --   ⚠ 見込みは既存の近似をそのまま使います（★Enemy Action Model へ戻らない）。
    local projected = missing + Actions.defend_expected_incoming(sit)
    info.missing, info.projected, info.unit = missing, projected, unit
    if unit ~= nil and projected < unit then
      -- ⚠ 1 回ぶんが溢れる（★軽傷 / 依頼者 §5「満タン近くなら使わない」）
      info.why = "too_shallow"
      return false, info
    end
    -- ⚠ 実際に戻る量（★溢れる分は数えない / `party_heal_gain` と同じ考え）
    heal = math.min(unit or 0, missing)
  end
  info.item = s.item_name or s.item_id
  info.effective_heal = heal
  if heal <= 0 then
    info.why = "nothing_to_heal"              -- ⚠ 満タンなら使わない
    return false, info
  end
  local gain = Actions.heal_turn_gain(heal, ctx, sit)
  info.heal_per_action = Actions.heal_per_action(ctx) or 0
  info.alive = #((sit or {}).alive or {})
  if gain == nil then
    info.why = "no_scale"
    return false, info
  end
  local our = tonumber(sit.our_dpt) or 0
  local g = Actions.pick_group(member, ctx, sit, nil)   -- ⚠ 予約しない（★見るだけ）
  local dmg = g ~= nil and physical_avg(member, sit, g) or 0
  local attack_gain = (our > 0) and (dmg / our) or 0
  info.stone_gain, info.attack_gain = gain, attack_gain
  -- ⚠⚠ **下駄は置きません**（★同じ尺度なので純比較 / 相談相手 §6）
  if gain > attack_gain then
    info.why = "free_heal_beats_attack"
    return true, info
  end
  info.why = "attack_is_better"
  return false, info
end

--- ★診断の 1 行（⚠ 相談相手 §34）
function Actions.proactive_tune(slot, info, decision)
  -- ★★ `scope` / `unit` / `projected` は RX3-0411 で足しました。
  --   ⚠ 「全体を見たのか単体を見たのか」「1 回ぶんに届いたのか」が読めないと、
  --     ★`too_shallow` と `no_free_party_heal` を取り違えます。
  --
  -- ⚠⚠ **全体回復には `unit` / `projected` がありません**（★単体の門なので）。
  --   ⚠ そこを `0` と書くと「1 回ぶんに 1 も届かなかった」に見えます
  --     （★2026-09-23 の実機で `scope=party ... unit=0 projected=0` と出た）。
  --   → ★**分からないものは `-`**（⚠ `dq3_economy_baseline` と同じ作法）。
  local function num(v)
    return v == nil and "-" or tostring(math.floor(v + 0.5))
  end
  return string.format(
    "AI proactive_heal actor=%s scope=%s item=%s target=%s effective_heal=%d unit=%s"
    .. " projected=%s heal_per_action=%d alive=%d"
    .. " stone_gain=%.3f attack_gain=%.3f decision=%s reason=%s",
    tostring(slot), tostring(info.scope or "none"), tostring(info.item or "none"),
    tostring(info.target or "party"),
    math.floor((info.effective_heal or 0) + 0.5),
    num(info.unit), num(info.projected),
    math.floor((info.heal_per_action or 0) + 0.5), info.alive or 0,
    info.stone_gain or 0, info.attack_gain or 0,
    decision or "skip", tostring(info.why))
end

--: ★★ 同程度なら攻撃（⚠ バタつきを止めるためだけの値 / 相談相手 §13）。
--
--   ⚠⚠ **`SUPPORT_EPS`（0.05）は、ここでは大きすぎました**（RX3-0393 / 2026-09-22）。
--     ★実機で、⚠ **防御のほうが 3〜4 倍得な場面が `attack_is_better` になっていました**:
--
--     ```text
--     attack_gain=0.007  defend_gain=0.024   ⚠ 0.024 > 0.007 + **0.05** は偽
--     attack_gain=0.009  defend_gain=0.042   ⚠ 0.042 > 0.009 + **0.05** は偽
--     ```
--
--     ★この 2 つの「得」は実測で **0.00〜0.35** に収まります。⚠ そこへ 0.05 を足すと、
--     **範囲の 1/7** が下駄になり、★寄与の小さい人ほど**永久に防御できません**。
--   → ★実用の幅の **1% 程度**にします（⚠ 大きな下駄にしない）。
Actions.DEFEND_EPS = 0.005

--- ★★ リソース節約で「攻撃より防御が得か」（RX3-0391 / 相談相手 §12）。
--
--   ```text
--   defend_gain = ★防げる被害 ÷ 回復 1 手番ぶんの HP   … ★浮く回復の手番
--   attack_gain = ★殴った見込み ÷ パーティ 1 ターンの火力 … ★縮む戦闘の手番
--   → ⚠⚠ `defend_gain > attack_gain + SUPPORT_EPS` なら防御
--   ```
--
--   ⚠⚠ **防御は無料ではありません。** ★MP も消耗品も使いませんが、
--     ⚠ **そのターンの攻撃機会**を失います。→ ★だから手番どうしで比べます。
--
--   ⚠ 使わない場面（★どれも「防御しても得が無い」）:
--   ```text
--   ⚠ 作戦が economy でない        （★最短撃破・生存優先は今までどおり / §16・§17）
--   ⚠ 敵からほぼ受けない           （★`prevented` が 0 / §14）
--   ⚠ 回復の手立てが無い           （★`heal_per_action` が nil や 0 / §11）
--   ⚠ その一撃で前の敵を倒せる     （★とどめは殴る / §15）
--   ```
--
--   戻り値: `(防御するか, 内訳の表)`
function Actions.economy_defend(member, ctx, sit, g, dmg)
  local info = {attack_damage = dmg or 0}
  if ctx.strategy ~= ECONOMY then
    info.why = "not_economy"
    return false, info
  end
  local incoming = Actions.defend_expected_incoming(sit)
  info.incoming = incoming
  local prevented = incoming * Actions.DEFEND_CUT
  info.prevented = prevented
  if prevented <= 0 then
    info.why = "no_incoming"                 -- ⚠ 受けないなら防いでも得は無い
    return false, info
  end
  local per = Actions.heal_per_action(ctx)
  info.heal_per_action = per or 0
  info.alive = #((sit or {}).alive or {})
  if per == nil or per <= 0 then
    info.why = "no_heal_scale"               -- ⚠ 0 で割らない（★相談相手 §11）
    return false, info
  end
  -- ★★ とどめは殴る（⚠ 相談相手 §15 / `physical_avg` は残り HP で頭打ち済み）
  local front = g and (g.first_hp or g.hp_sum) or nil
  if front ~= nil and front > 0 and (dmg or 0) >= front then
    info.why = "can_kill"
    return false, info
  end
  local our = tonumber(sit.our_dpt) or 0
  info.our_dpt = our
  local attack_gain = (our > 0) and ((dmg or 0) / our) or 0
  -- ⚠⚠ **パーティ 1 ターンの尺度へそろえます**（RX3-0397 / ★`/ alive_n`）。
  --   ⚠ そろえる前は「1 人ぶんの手」で数えていて、★**生存人数ぶん過大**でした。
  local defend_gain = Actions.heal_turn_gain(prevented, ctx, sit)
  if defend_gain == nil then
    info.why = "no_heal_scale"
    return false, info
  end
  info.attack_gain, info.defend_gain = attack_gain, defend_gain
  -- ⚠⚠ **同程度なら攻撃**（★`DEFEND_EPS` の註に、⚠ なぜ `SUPPORT_EPS` では駄目かを書いた）
  if defend_gain > attack_gain + Actions.DEFEND_EPS then
    info.why = "saves_heal_actions"
    return true, info
  end
  info.why = "attack_is_better"
  return false, info
end

--: ★診断の 1 行（⚠ **防御したときだけ**ログへ / ★しなかった分は `tune` に残る）
--- ★★ その人を「**他の人が**」回復する予定か（RX3-0412 / 依頼者 §9・§17・§29）。
--
--   ⚠⚠ `plan.reserved_healing` は**量**しか持ちません。★「誰から誰へ」は
--     割り当て（`Roles.assign`）にしかないので、⚠ `pipeline` が `ctx._assigned`
--     へ出しています（★producer）。⚠ 片側だけだと実機で静かに nil になります。
--
--   ⚠ 自分で自分を回復する人は**数えません**（★依頼者 §17）。
--   ⚠ 蘇生（`job == "revive"`）も数えません（★死者は別の話）。
--
--   戻り値: `(回復する人の枠, その理由)`。⚠ 居なければ `nil`。
function Actions.healer_for(ctx, slot)
  for who, a in pairs((ctx or {})._assigned or {}) do
    if who ~= slot and a ~= nil and a.role == "heal" and a.job ~= "revive"
        and a.target == slot then
      return who, a.why
    end
  end
  return nil
end

--- ★★ 生存優先: 回復が来るまで防御して耐える（RX3-0412 / 依頼者 §8〜§19）。
--
--   ⚠⚠ **2026-09-23 に変更前のコードを実機観測して分かったこと**
--     （`work/dq3-probe/field_sampler/20260923-171140`）:
--
--   ```text
--   ① ⚠ 既存の防御は `defend_kinds = {disadvantage, even}` → ★優勢・消化戦では出ない
--   ② ⚠ 既存の防御は `ratio < critical`（0.15）→ ★p2 は 0.26〜0.39 で届かない
--   ③ ⚠ 消化戦は `heal_line` が critical まで落ちる → ★回復が要るにすら入らない
--   ④ ⚠⚠ `even` は `(disadvantage or not healed)` → **回復が来ると、かえって防御しない**
--   ```
--
--   ★④ が依頼者の症状です。⚠ いまの作りは「回復が来る**から**殴ってよい」、
--     依頼者が欲しいのは「回復が来る**まで**耐える」。★向きが逆でした。
--
--   ⚠⚠ **新しい HP の定数は作りません**（★既存の `danger_hp` / 依頼者 §10）。
--   ⚠ `DEFEND_EPS` も触りません（★依頼者 §33）。
--
--   ⚠ 使わない場面:
--   ```text
--   ⚠ 作戦が survival でない      （★§20・§21）
--   ⚠ 本人が危なくない             （★§19 / 全員防御にしない）
--   ⚠ 他者からの回復が無い         （★§18 / 自分で回復するのは別 / §17）
--   ⚠ 受ける見込みが 0
--   ⚠ その一撃で前の敵を倒せる     （★§13 / 倒せば次の被害は 0）
--   ```
--
--   戻り値: `(防御するか, 内訳の表)`
function Actions.survival_wait_defend(member, ctx, sit, g, dmg)
  local info = {attack_damage = dmg or 0}
  if ctx.strategy ~= SURVIVAL then
    info.why = "not_survival"
    return false, info
  end
  -- ⚠⚠ **見る値は先に全部そろえます**（★2026-09-23 の実機で踏んだ）。
  --   ⚠ 早い return のあとに測ると、★見送った行の `expected_incoming` が
  --     いつも `0.00` になり、**「敵から受けない」と読み違えます**。
  local incoming = Actions.defend_expected_incoming(sit)
  info.incoming = incoming
  -- ★危ないか（⚠ 既存の `danger_hp` をそのまま引く / ★ここに数字を書かない）
  local danger = tuned(ctx.tuning or {}, "danger_hp", "", 0.3)
  local cap = math.max(member.hp_max or 1, 1)
  local ratio = (member.hp or 0) / cap
  info.hp, info.hp_max, info.ratio, info.danger = member.hp or 0, cap, ratio, danger
  if ratio >= danger then
    info.why = "healthy"                       -- ⚠ 生存優先でも全員防御にはしない
    return false, info
  end
  -- ★**他の人から**回復が来る予定か（⚠ 自分で回復するのは対象外）
  local healer, heal_why = Actions.healer_for(ctx, member.slot)
  info.healer, info.heal_action = healer, heal_why
  if healer == nil then
    info.why = "no_heal_reserved"              -- ⚠ 既存の判断へ戻す（★§18）
    return false, info
  end
  if incoming <= 0 then
    info.why = "no_incoming"                   -- ⚠ 受けないなら防いでも得は無い
    return false, info
  end
  -- ★★ とどめは殴る（⚠ `economy_defend` と**同じ見方**にする / §13）
  local front = g and (g.first_hp or g.hp_sum) or nil
  info.can_kill = (front ~= nil and front > 0 and (dmg or 0) >= front)
  if info.can_kill then
    info.why = "can_kill"
    return false, info
  end
  info.why = "wait_for_heal"
  return true, info
end

--- ★診断の 1 行（⚠ 依頼者 §28）
function Actions.wait_tune(info, decision)
  return string.format(
    "decision=%s reason=%s hp=%d/%d ratio=%.3f danger=%.2f expected_incoming=%.2f"
    .. " healer=%s can_kill=%s attack_damage=%.2f",
    decision or "defend", tostring(info.why), info.hp or 0, info.hp_max or 0,
    info.ratio or 0, info.danger or 0, info.incoming or 0,
    tostring(info.healer or "none"), tostring(info.can_kill == true),
    info.attack_damage or 0)
end

local function defend_tune(info)
  -- ⚠ `alive` を必ず出します（★相談相手 §31 / 単位がそろっているか読めるように）
  return string.format(
    "decision=defend reason=%s attack_damage=%.2f attack_gain=%.3f"
    .. " incoming=%.2f prevented=%.2f heal_per_action=%.2f alive=%d defend_gain=%.4f",
    tostring(info.why), info.attack_damage or 0, info.attack_gain or 0,
    info.incoming or 0, info.prevented or 0, info.heal_per_action or 0,
    info.alive or 0, info.defend_gain or 0)
end

function Actions.physical(member, ctx, sit, plan)
  -- ⚠⚠ **先に「殴るか防ぐか」を決めます**（RX3-0391）。
  --   ★`pick_group` は `plan` を渡すと**被害を予約**します。⚠ 防御に倒れたのに
  --     予約だけ残ると、★他の人が「もう倒れる」と見て別の群へ行きます。
  --   → ★比べるときは `plan` を渡さず（予約しない）、⚠ 殴ると決めてから予約します。
  -- ⚠⚠ **作戦の門は `economy_defend` の中の 1 か所だけ**にします。
  --   ★ここにも `strategy == ECONOMY` を書くと**二重の歯止め**になり、
  --   ⚠ 片方を壊しても検査が緑のままになります（★2026-09-22 の壊す実験で実際に踏んだ）。
  do
    local dry_g, dry_dmg = Actions.pick_group(member, ctx, sit, nil)
    local yes, info = Actions.economy_defend(member, ctx, sit, dry_g, dry_dmg)
    if yes then
      local a = {kind = "defend", fallback = "attack",
                 why = string.format("節約の防御（殴って約%d / 回復 %.1f 手番ぶんを防ぐ）",
                                     math.floor((info.attack_damage or 0) + 0.5),
                                     info.defend_gain or 0)}
      a.tune = {defend_tune(info)}
      a.defend_info = info
      return a
    end
  end
  -- ★★ 生存優先: 回復が来るまで耐える（RX3-0412 / 依頼者 §8）。
  --   ⚠⚠ **作戦の門は `survival_wait_defend` の中の 1 か所だけ**にします
  --     （★ここにも `== SURVIVAL` を書くと二重の歯止めになり、片方を壊しても緑）。
  do
    local dry_g, dry_dmg = Actions.pick_group(member, ctx, sit, nil)   -- ⚠ 予約しない
    local yes, info = Actions.survival_wait_defend(member, ctx, sit, dry_g, dry_dmg)
    if yes then
      local a = {kind = "defend", fallback = "attack",
                 why = string.format("回復を待って防御（HP %d/%d ・%s が回復）",
                                     info.hp or 0, info.hp_max or 0,
                                     tostring(info.healer))}
      a.tune = {Actions.wait_tune(info, "defend")}
      a.defend_info = info
      return a
    end
  end
  local g, dmg, why = Actions.pick_group(member, ctx, sit, plan)
  if g == nil then return attack_action(nil, "敵が見えない") end
  local a = attack_action(g.index, string.format("g%d 残り%d に約%d", g.index, g.hp_sum,
                                                 math.floor(dmg + 0.5)))
  a.tune = {attack_tune(g, why)}
  -- ⚠ **防御しなかった理由も残します**（★相談相手 §23 / ログを汚さないよう 1 行だけ）
  --   ⚠ 作戦の判定は `economy_defend` の中だけ（★`not_economy` なら何も出さない）。
  do
    local _no, info = Actions.economy_defend(member, ctx, sit, g, dmg)
    if info.why ~= "not_economy" then
      a.tune[#a.tune + 1] = string.format(
        "defend_check=%s attack_gain=%.3f defend_gain=%.4f alive=%d",
        tostring(info.why), info.attack_gain or 0, info.defend_gain or 0,
        info.alive or 0)
    end
    -- ⚠⚠ **生存優先で防御しなかった理由も残します**（RX3-0412 / 依頼者 §28）。
    --   ★0 行だと「場面が来ていない」のか「条件で落ちた」のか区別できません
    --     （⚠ `RX3-0404` で同じ読み違えをした）。
    local _n2, w = Actions.survival_wait_defend(member, ctx, sit, g, dmg)
    if w.why ~= "not_survival" then
      -- ⚠⚠ ここに `decision=` / `reason=` を**書きません**。★狙いの判断ログと
      --   字面がぶつかり、⚠ 既存の検査が**こちらを拾ってしまいます**
      --   （2026-09-23 に実際に赤くなった）。→ ★`defend_check=` と同じ作法にします。
      a.tune[#a.tune + 1] = string.format(
        "wait_check=%s hp=%d/%d ratio=%.3f expected_incoming=%.2f healer=%s can_kill=%s",
        tostring(w.why), w.hp or 0, w.hp_max or 0, w.ratio or 0,
        w.incoming or 0, tostring(w.healer or "none"), tostring(w.can_kill == true))
    end
  end
  a.phys_dmg = dmg                 -- ★見込み（★次のターンに実際の減りと比べる / RX3-0226）
  return a
end

----------------------------------------------------------------------
-- 回復 / 蘇生
----------------------------------------------------------------------

local function find_member(ctx, slot)
  for _, m in ipairs(ctx.party or {}) do
    if m.slot == slot then return m end
  end
  return nil
end

--: ★全体回復の印（⚠ ROM 実測でベホイマ系は `self_party` / `dq3rom/spells.py`）。
Actions.PARTY_HEAL_TARGET = "self_party"

--- ★回復の手を作る（⚠ 呪文と**道具**で窓の道が違う / RX3-0346）。
--
--   ★道具（ちからのたて / けんじゃのいし）は `item_id` を持ちます。
--   ⚠ 「どうぐ → その品」で押すので、★`kind = "item"` です（★攻撃の道具と同じ作法 / RX3-0213）。
local function heal_action(s, target, why)
  if s.item_id == nil then return spell_action(s, target, why) end
  return {kind = "item", item = "heal", item_id = s.item_id, item_tiles = s.item_tiles,
          name = s.item_name, target = target, fallback = "defend",
          why = string.format("%s（%s / MP 0）%s", s.item_name or ("道具" .. s.item_id),
                              s.name or ("呪文" .. tostring(s.id)), why)}
end

--- ★★ 全体回復で**実際に戻る** HP の合計（RX3-0335 / 2026-09-21）。
--
--   ⚠⚠ 溢れる分は数えません。★満タンの人に 70 かけても 0 です。
--   → ★これで「1 人しか傷んでいないなら単体回復のほうが得」が**式から出ます**
--     （⚠ 「2 人以上なら全体」のような人数の決め打ちを置かない）。
--
--   戻り値: 戻る合計 HP, 傷んでいる人数。
function Actions.party_heal_gain(s, sit)
  local total, hurt = 0, 0
  for _, m in ipairs((sit or {}).alive or {}) do
    local missing = (m.hp_max or 0) - (m.hp or 0)
    if missing > 0 then
      -- ★ベホマズン（`base == 255`）はその人の欠けぶんを全部戻す
      total = total + math.min(avg_of(s, m.hp_max), missing)
      hurt = hurt + 1
    end
  end
  return total, hurt
end

--- ★★ 回復の判断を 1 行で残す（RX3-0356 / 2026-09-21 依頼者「ログで確認して」）。
--
--   ⚠⚠ 回復には**判断ログがありませんでした**。★攻撃（`magic_tune`）やマホトラ（`drain_tune`）
--     には在るのに、⚠ 回復だけ「何を持っていて、なぜそれを選んだか」が**残りません**でした。
--   → ★「道具を使っていない」のが**負けたから**なのか、⚠ **そもそも見えていない**のか
--     区別できませんでした（依頼者「ちからのたて … リソース節約で使われている？」）。
--
--   ```text
--   AI tune p3 heal_target=p2 missing=120 hand=ベホマ,ちからのたて:item,けんじゃのいし:item
--     pick=ベホマ gain=120 / party=けんじゃのいし gain=140 hurt=2 wanted=2 / decision=use
--   ```
--: ★手の名前（⚠ **道具は道具の名前**で出す / ★依頼者は「ちからのたて」を探すので）
local function heal_name(s)
  if s == nil then return "none" end
  if s.item_id ~= nil then
    return (s.item_name or ("道具" .. tostring(s.item_id))) .. ":item"
  end
  return s.name or ("呪文" .. tostring(s.id))
end

local function heal_tune(member, caps, target, missing, pick, party, party_gain, hurt, wanted,
                         decision, reason)
  local hand = {}
  for _, s in ipairs(caps.heal or {}) do hand[#hand + 1] = heal_name(s) end
  if caps.herb then hand[#hand + 1] = "やくそう:herb" end
  -- ⚠⚠ 2026-09-24（RX3-0429 / P-18）: ★接頭辞（`AI tune <slot> …`）は**付けません**。
  --   ⚠ 付けるのは `pipeline.lua` の 1 か所だけです。★ここでも付けていたので、
  --     実機ログが `AI tune p1 … AI tune p1 heal_target=…` と**2 回**出ていました。
  return string.format(
    "heal_target=%s missing=%d hand=%s pick=%s gain=%d party=%s party_gain=%d "
    .. "hurt=%d wanted=%d decision=%s reason=%s",
    target.slot, math.floor((missing or 0) + 0.5),
    (#hand > 0 and table.concat(hand, ",") or "none"),
    heal_name(pick),
    math.floor((pick and math.min(avg_of(pick, target.hp_max), missing or 0) or 0) + 0.5),
    heal_name(party), math.floor((party_gain or 0) + 0.5), hurt or 0, wanted or 0,
    decision or "?", reason or "?")
end

--- ★回復の線を割っている人の数（⚠ = 誰かが手番を使って回復する相手 / RX3-0335）。
--
--   ★線は `roles.lua` の `heal_at` と**同じもの**を引きます（⚠ ここで別の数を置かない）。
--- ★★ 回復の線（⚠ **式は `roles.lua` の 1 か所だけ** / RX3-0429 / P-5）。
--
--   ⚠⚠ ここに式を写してはいけません。★2026-09-24 まで行動の側は `heal_at` を
--     そのまま使い、⚠ 役割の側だけが MP 方針・消化戦で下げていました
--     （= 同じ場面で「回復は要らない」と「回復が要る」が同時に出る）。
--   ⚠ `Roles` がまだ渡っていなければ、★今までどおり `heal_at` で動きます（落とさない）。
function Actions.heal_line(ctx, sit)
  if Roles ~= nil and Roles.heal_line ~= nil then return Roles.heal_line(ctx, sit) end
  return tuned((ctx or {}).tuning or {}, "heal_at", (ctx or {}).strategy or "", 0.35)
end

function Actions.heal_wanted_count(ctx, sit)
  -- ⚠ 線は `Roles.heal_line` の 1 本だけ（RX3-0429 / P-5）
  local line = Actions.heal_line(ctx, sit)
  local n = 0
  for _, m in ipairs((sit or {}).alive or {}) do
    if (m.hp or 0) / math.max(m.hp_max or 1, 1) < line then n = n + 1 end
  end
  return n
end

--- ★★ 全体回復が「いま要る分」を満たすか（RX3-0394 / 相談相手 §8）。
--
--   ⚠⚠ **最大 HP まで戻すことは求めません。** ★求めるのは
--     「**回復の線を割っている人を、全員 線まで戻せるか**」だけです。
--   ★線は `heal_at`（⚠ `roles.lua` と同じものを引く / ここで別の数を置かない）。
--
--   ⚠ 誰も線を割っていなければ **`true`**（★「要る分が無い ＝ 満たしている」）。
--     ⚠⚠ ただし、そもそも回復するかどうかは `heal_wanted_count` の側が決めます。
--
--   戻り値: `(満たすか, いちばん足りない人の不足量)`
--   ★★ 2026-09-23（RX3-0419）: `margin` を足せるようにしました。
--     ⚠ 「回復したあと、★**次のターンの被害を引いても**線を保てるか」を見るため。
--     ⚠⚠ 既存の呼び出しは 3 引数のままなので、★`margin = 0` で**今までどおり**です。
function Actions.party_heal_sufficient(s, ctx, sit, margin)
  local line = Actions.heal_line(ctx, sit)
  local keep = tonumber(margin) or 0
  local worst = 0
  local ok = true
  for _, m in ipairs((sit or {}).alive or {}) do
    local cap = math.max(m.hp_max or 1, 1)
    if (m.hp or 0) / cap < line then
      local need = line * cap - (m.hp or 0) + keep
      local got = math.min(avg_of(s, m.hp_max), (m.hp_max or 0) - (m.hp or 0))
      if got < need then
        ok = false
        if need - got > worst then worst = need - got end
      end
    end
  end
  return ok, worst
end

--- ★★ 無料の全体回復だけで、★**次のターンまで線を保てる**か（RX3-0419 / 2026-09-23）。
--
--   ⚠⚠ **戻る HP の多い / 少ないでは決めません。** ★見るのは「安全か」だけです。
--
--   ```text
--   ⚠ 実機（save9 / 両方の直しが入った run の 4 件中 2 件）
--      欠け 259 / 無料(全体) 258 / 有料(単体) 259 → ⚠ spell:ベホマ（7 MP）
--      欠け 331 / 無料(全体) 271 / 有料(単体) 331 → ⚠ spell:ベホマ（7 MP）
--   ★1 HP のために 7 MP を払っていました（`party_gain > single_gain` だけの比較）。
--   ```
--
--   ★判定は `party_heal_sufficient` に**被害の見込みを足すだけ**です
--     （⚠ 同じ規則を 2 か所に書かない / 依頼者 §2）。
--   ⚠ 見るのは「**回復が必要な人**」だけ（★合計 HP では決めない / 依頼者 §4）。
function Actions.free_party_keeps_safe(s, ctx, sit)
  if s == nil then return false end
  local ok = Actions.party_heal_sufficient(s, ctx, sit,
                                           Actions.defend_expected_incoming(sit))
  return ok
end

--- ★★ その回復の「消費資源」（RX3-0394 / 相談相手 §10）。
--
--   ```text
--   ★減らない道具 → **0**（⚠ ROM は道具の効果で MP を払わない / RX3-0346）
--   ★呪文         → MP
--   ```
--
--   ⚠ 消耗品はまだ表に入っていません（★`generate.py` が `consumed` を落としている）。
function Actions.heal_resource(s)
  if s == nil then return 0 end
  if s.item_id ~= nil then return 0 end
  return tonumber(s.mp) or 0
end

--- ★回復。★足りる中で一番安い呪文。⚠ 無ければ やくそう、それも無ければ防御。
--
--   ★★ 2026-09-21（RX3-0335）: **全体回復も唱えます**。
--     ⚠⚠ それまでは `ally_single` しか見ておらず、★全体回復しか持たない人は
--       「回復できる」と数えられたのに **やくそう か 防御に落ちて**いました。
--     ★選び方は「1 手番で戻る HP が多いほう」だけです（⚠ 人数の決め打ちはしない）。
--     ⚠ 同じなら単体（★MP が安く、今までどおり）。
function Actions.heal(member, caps, assign, ctx, sit, used)
  -- ★★ 防御戦術が名指しした無料回復（RX3-0429 / 依頼者 §4〜§8）。
  --
  --   ⚠⚠ ここは**比べません**。★役割の側が「この人がこれを出す」と決めています
  --     （`Roles.defensive_formation`）。⚠ 下の損得の式を通すと、
  --     ★「1 ポイントだけ減っている」場面で全体回復が単体回復に負けます（§4-1 に反する）。
  --
  --   ⚠ 出せなければ**黙って下の通常の道へ落ちます**（★道具を落としていた等）。
  if assign.free_scope == "party" or assign.free_scope == "single" then
    local party_scope = assign.free_scope == "party"
    local s = party_scope and Actions.free_party_heal(caps)
             or Actions.free_heal_of(caps, Actions.SINGLE_HEAL_TARGET)
    if s ~= nil then
      if party_scope and used ~= nil then used.party_heal = true end
      local a = heal_action(s, party_scope and nil or {ally = member.slot},
                            party_scope and "（全体 / 防御戦術の予防回復）"
                            or "（自分 / 防御戦術の無料回復）")
      -- ⚠ 判断の 1 行は**ここで**付けます（★下の `traced` は後ろの値に頼るので使えない）
      a.tune = {string.format(
        "defensive_heal actor=%s item=%s scope=%s decision=use reason=%s",
        tostring(member.slot), tostring(s.item_name or s.name or "?"),
        assign.free_scope, party_scope and "someone_hurt" or "self_hurt")}
      return a
    end
    -- ⚠ 出せなかった（★道具を落とした等）→ ★下の通常の道へ落ちます
  end

  local target = find_member(ctx, assign.target) or member
  local missing = (target.hp_max or 0) - (target.hp or 0)
  local ratio = (target.hp or 0) / math.max(target.hp_max or 1, 1)
  local critical = tonumber((ctx.tuning or {}).critical_hp) or 0.15
  local urgent = ratio < critical

  local pick, pick_why = nil, nil
  local best_short = nil
  --: ★★ 無料の単体回復のうち、いちばん戻るもの（RX3-0411 / ⚠ economy だけが使う）
  local free_single = nil
  local party, party_gain = nil, 0
  --: ★リソース節約の並べ替えに使う（⚠ 足りるか / 消費資源）
  local party_fits, party_cost = false, math.huge
  for _, s in ipairs(caps.heal or {}) do
    local ok, deny
    if s.item_id ~= nil then
      -- ★回復の道具は MP を払わない（RX3-0346 / ⚠ ROM は道具の効果で MP の判定と消費を通らない）
      ok = true
    else
      ok, deny = Actions.mp_allows(member, s, ctx, urgent)
    end
    if ok then
      local avg = avg_of(s, target.hp_max)
      local single = (s.target == Actions.SINGLE_HEAL_TARGET)
      if single then
        -- ★無料の手を覚えておく（RX3-0411 / ⚠ 下の「無料で足りるなら無料」で使う）
        if Roles ~= nil and Roles.resource_free ~= nil and Roles.resource_free(s)
            and (free_single == nil or avg > avg_of(free_single, target.hp_max)) then
          free_single = s
        end
        if avg >= missing * 0.8 then
          if pick == nil or (s.mp or 0) < (pick.mp or 0) then pick = s end
        elseif best_short == nil or avg > avg_of(best_short, target.hp_max) then
          best_short = s
        end
      elseif s.target == Actions.PARTY_HEAL_TARGET then
        local gain = Actions.party_heal_gain(s, sit)
        -- ★★ リソース節約は「**足りる中でいちばん安い**」（RX3-0394 / 相談相手 §7・§9）。
        --
        --   ⚠⚠ これまでは**戻る量が多い順**でした。→ ★けんじゃのいし（MP 0）で
        --     足りていても、⚠ もっと戻る **ベホマズン（MP 大）**に負けていました。
        --   ★単体回復は前から「足りる中で最小 MP」なので、⚠ **考え方を揃えます**。
        --
        --   ⚠ 足りる候補が 1 つも無ければ、★今までどおり**いちばん戻る**ものを選びます
        --     （⚠ 石では足りないほど危ないなら、★ベホマズンを普通に使う / §12）。
        --   ⚠⚠ 最短撃破・生存優先は**今までどおり**（★§14 / 生存優先は「多く戻る」に意味がある）。
        local better_here
        if ctx.strategy == ECONOMY then
          local fits = Actions.party_heal_sufficient(s, ctx, sit)
          local cost = Actions.heal_resource(s)
          if party == nil then
            better_here = true
          elseif fits ~= party_fits then
            better_here = fits                       -- ★足りるほうが強い
          elseif cost ~= party_cost then
            better_here = cost < party_cost          -- ★同じなら安いほう
          else
            better_here = gain > party_gain          -- ★それも同じなら戻る量
          end
          if better_here then
            party_fits, party_cost = fits, cost
          end
        else
          -- ★戻る量が多いほう。⚠ 同じなら安いほう（★今までどおり）
          better_here = gain > party_gain
            or (party ~= nil and gain == party_gain and (s.mp or 0) < (party.mp or 0))
        end
        if better_here then
          party, party_gain = s, gain
        end
      end
    else
      pick_why = deny
    end
  end
  if pick == nil then pick = best_short end

  -- ★★ リソース節約は「無料で足りるなら無料」（RX3-0411 / 依頼者 §9・§10・§16）。
  --
  --   ⚠⚠ **これが依頼者の踏んだ場面そのものです**（★指示書 §0 / 実機で確認済み）:
  --
  --   ```text
  --   ★欠け 150 / ちからのたて 約85（MP 0） / ベホマ（MP 7）
  --     ⚠ 85 >= 150 x 0.8 は偽  → ちからのたて は best_short へ落ちる
  --     ★ベホマ は「足りる」    → pick になり、⚠ MP 0 の手があるのに 7MP を払う
  --   ```
  --
  --   ⚠⚠ **ベホマを禁止しません**（★依頼者 §9）。★無料の単体回復で
  --     **次のターンまで線を保てる**ときだけ、⚠ 有料の手を退けます。
  --
  --   ```text
  --   保てる   hp + 期待回復 - 被害見込み >= heal_at x hp_max
  --   ```
  --
  --   ★線は `heal_at`（⚠ `roles.lua` と同じものを引く / ここで別の数を置かない）。
  --   ⚠ 瀕死でも同じ式です（★無料で線まで戻らなければ、そのまま有料へ上がります）。
  local free_first = false
  if ctx.strategy == ECONOMY and free_single ~= nil and pick ~= nil
      and Actions.heal_resource(pick) > 0 then
    local line = Actions.heal_line(ctx, sit)
    local cap = target.hp_max or 0
    local after = math.min((target.hp or 0) + avg_of(free_single, cap), cap)
    if after - Actions.defend_expected_incoming(sit) >= line * cap then
      pick, free_first = free_single, true
    end
  end

  -- ★★ 全体回復のほうが得なら、そちらへ（RX3-0335）。
  --
  --   ★2 つとも満たすときだけです:
  --
  --   ```text
  --   ① ★戻る量が多い          （⚠ 溢れる分は数えない）
  --   ② ★手番が減る            （⚠ 回復の線を割っている人が 2 人以上）
  --   ```
  --
  --   ⚠⚠ ② が無いと、★**かすり傷 3 人**（欠け 5 ずつ）でも「合計 15 > 単体 5」で
  --     全体回復を撃ちました（★2026-09-21 の検査で踏んだ）。⚠ 高い呪文の無駄打ちです。
  --   ★全体回復の値打ちは「1 手で何人分も片づく」ことなので、⚠ **片づける相手が
  --     2 人以上いる**ことを見ます。
  --
  --   ⚠ ただし**単体回復を 1 つも持たないなら**、★相手が 1 人でも唱えます
  --     （⚠ そこでの比較対象は やくそう か 防御です）。
  --
  --   ⚠⚠ 1 ターンに 2 回は唱えません（★回復役は 2 人まで立つ / `roles.lua`）。
  --     ⚠ 2 人目が同じ呪文を重ねても、1 人目で満タンになった人には 0 しか戻りません。
  local single_gain = 0
  if pick ~= nil then single_gain = math.min(avg_of(pick, target.hp_max), missing) end
  local wanted = Actions.heal_wanted_count(ctx, sit)
  -- ⚠⚠ **予防の無料回復は、この門を通します**（RX3-0398）。
  --   ★`roles.needed` が既に「全体回復 1 手 > 攻撃 1 手」を確かめています。
  --   ⚠ ここで `wanted >= 2`（★回復の線を割った人が 2 人）を求めると、
  --     **線を割っていないのが前提**の予防の回復は**永久に通りません**。
  -- ★★ economy の「資源を使わない・減らない全体回復」も通します（RX3-0418 / 2026-09-23）。
  --
  --   ⚠⚠ `wanted >= 2` の歯止めは、★**払うもの**があるから意味があります
  --     （`RX3-0335` / `SH④`: かすり傷 3 人に高い全体回復を撃たない）。
  --   ⚠ ところが `けんじゃのいし` は **MP 0・減らない**ので、
  --     ★1 人しか線を割っていなくても**払うものがありません**。
  --
  --   ```text
  --   ⚠ save9 実測（RX3-0417 のあと）: hurt=3 wanted=1 → reason=no_turn_saved
  --      ★石は candidates に並び selected にもなったのに、押下まで行かなかった
  --   ```
  --
  --   ⚠⚠ **`wanted >= 2` を撤廃はしません**（★依頼者 §7）。
  --     ★有料の全体回復（ベホマラー / ベホマズン）は**今までどおり**です（§4）。
  --   ⚠ 判定は `Roles.resource_free` の 1 か所だけ（★MP 0 ＋ 減らない / §5）。
  --   ⚠⚠ **`wanted >= 1` は外せません**（★2026-09-23 に `FP-G` が捕まえた）。
  --     ⚠ 付け忘れると、★**かすり傷 3 人（欠け 10 ずつ / `wanted=0`）**でも
  --       `party_gain 30 > single 10` で石が出ます ＝ `SH④` の壊れ方そのもの。
  --     ★新しい閾値ではなく、⚠ **既に数えている `wanted`** を使うだけです。
  local free_party = party ~= nil and ctx.strategy == ECONOMY and wanted >= 1
    and Roles ~= nil and Roles.resource_free ~= nil and Roles.resource_free(party)
  local saves_a_turn = (pick == nil) or wanted >= 2 or (assign or {}).proactive == true
    or free_party
  local _, hurt = Actions.party_heal_gain(party or {base = 0, delta = 0}, sit)
  -- ★★ 判断を 1 行残す（RX3-0356）。⚠ どの道を通っても**必ず**付けます
  local function traced(action, decision, reason)
    action.tune = {heal_tune(member, caps, target, missing, pick, party, party_gain,
                             hurt, wanted, decision, reason)}
    -- ★★ 全体回復の**候補ごとの内訳**（RX3-0394 / 相談相手 §22）。
    --   ⚠⚠ 「なぜ石ではなく呪文を選んだのか」を後から読めるように。
    --   ⚠ リソース節約のときだけ（★ログを汚さない）。
    if ctx.strategy == ECONOMY then
      local rows = {}
      for _, s in ipairs(caps.heal or {}) do
        if s.target == Actions.PARTY_HEAL_TARGET then
          local fits, short = Actions.party_heal_sufficient(s, ctx, sit)
          rows[#rows + 1] = string.format(
            "%s heal=%d resource=%d sufficient=%s short=%d", heal_name(s),
            math.floor(Actions.party_heal_gain(s, sit) + 0.5),
            Actions.heal_resource(s), tostring(fits), math.floor(short + 0.5))
        end
      end
      if #rows > 0 then
        -- ⚠⚠ **`selected=` は「全体回復の候補の中で最良」でしかありませんでした**
        --   （★2026-09-23 / これを「実際に押した手」と読み違えかけた）。
        --   → ★`party_candidate=`（候補）と `final_selected=`（実際の手）に分けます。
        action.tune[#action.tune + 1] = string.format(
          "heal_select party_candidate=%s final_selected=%s candidates=[%s]",
          heal_name(party), tostring(action.name or action.kind or "?"),
          table.concat(rows, " | "))
      end
    end
    return action
  end

  -- ★★ economy: 無料の全体回復で線を保てるなら、⚠ **有料の単体を退ける**（RX3-0419）。
  --
  --   ⚠⚠ `party_gain > single_gain` は**戻る HP だけ**の比較で、★資源の項がありません。
  --     ⚠ 実機で **258 対 259 ― 1 HP の差で 7 MP** を払っていました。
  --   ★`RX3-0411`（無料の**単体**で線を保てるなら有料を退ける）と**同じ考え**を、
  --     ⚠ 無料の**全体**にも広げます。
  --
  --   ⚠⚠ **`party_gain > single_gain` は撤廃しません**（★依頼者 §7）。
  --     ⚠ 退けるのは「有料の手」だけ（★`heal_resource(pick) > 0`）。
  --     ⚠ `free_party` には `wanted >= 1` が入っているので、★軽傷では動きません（§12）。
  local free_beats_paid = free_party and pick ~= nil
    and Actions.heal_resource(pick) > 0
    and Actions.free_party_keeps_safe(party, ctx, sit)
  if party ~= nil and (party_gain > single_gain or free_beats_paid) and saves_a_turn
      and not (used ~= nil and used.party_heal) then
    if used ~= nil then used.party_heal = true end
    -- ⚠ どの道で通ったかを残す（★効いた回を数えられるように）
    local why_party = "party_heal"
    if free_party and wanted < 2 then why_party = "free_party_heal" end
    if free_beats_paid and party_gain <= single_gain then
      why_party = "free_party_beats_paid"          -- ★RX3-0419 が効いた回
    end
    return traced(heal_action(party, nil,
      string.format("%s（全体 / %d 人に 約%d 戻る）", party.name or ("呪文" .. party.id),
                    hurt, math.floor(party_gain + 0.5))), "use", why_party)
  end

  if pick ~= nil then
    -- ⚠ なぜ全体でなかったのかを残す（★依頼者が「使われている？」を読めるように）
    local why = "single_best"
    if free_first then
      -- ★無料で足りたので有料を退けた（RX3-0411 / ⚠ 依頼者が読む所）
      why = "free_heal_first"
    elseif party == nil then
      why = "no_party_heal"
    elseif used ~= nil and used.party_heal then
      why = "party_heal_used_this_turn"
    elseif party_gain <= single_gain then
      why = "single_restores_more"
    elseif not saves_a_turn then
      why = "no_turn_saved"
    end
    return traced(heal_action(pick, {ally = target.slot},
      string.format("%s HP %d/%d に %s（約%d）", target.slot, target.hp, target.hp_max,
                    pick.name or ("呪文" .. pick.id),
                    math.floor(avg_of(pick, target.hp_max) + 0.5))), "use", why)
  end
  if caps.herb then
    return traced({kind = "item", item = "herb",
                   item_tiles = (ctx.items or {}).herb and ctx.items.herb.tiles,
                   target = {ally = target.slot}, fallback = "attack",
                   why = string.format("%s HP %d/%d に やくそう（%s）", target.slot,
                                       target.hp, target.hp_max,
                                       pick_why or "回復呪文なし")},
                  "use", "herb")
  end
  return traced({kind = "defend", fallback = "attack",
                 why = string.format("回復できない（%s / やくそう無し）",
                                     pick_why or "回復呪文なし")},
                "skip", pick_why and "mp" or "no_heal")
end

function Actions.revive(member, caps, assign, ctx)
  local target = find_member(ctx, assign.target)
  local pick = nil
  for _, s in ipairs(caps.revive or {}) do
    if Actions.mp_allows(member, s, ctx, true) then
      if pick == nil or (s.mp or 0) < (pick.mp or 0) then pick = s end
    end
  end
  if pick == nil or target == nil then
    return Actions.physical(member, ctx, ctx._sit, ctx._plan)
  end
  return spell_action(pick, {ally = target.slot},
    string.format("%s を %s で起こす", target.slot, pick.name or ("呪文" .. pick.id)))
end

----------------------------------------------------------------------
-- 魔法攻撃
----------------------------------------------------------------------

--- ★状態をかける呪文が効く確率（⚠ 分からなければ 1.0 = 止めない）。
local function rate_for(cat, g, field)
  if Catalog == nil or g.stats == nil or field == nil then return 1.0 end
  local r = Catalog.success_rate((g.stats.resist or {})[field])
  return r == nil and 1.0 or r
end

--- ★その呪文をその群に撃ったときの見込み（★1 体ずつ、残り HP を超えた分は数えない）。
--
--   ★★ RX3-0267（2026-09-14）: 攻撃呪文は**効く / 効かない の二択**（JP bank 4 `$A4BF`〜`$A4DE` / RX3-0266 の実機で確認）。
--     呪文の番号で耐性 0〜3（炎 / 氷 / 風 / 雷）を選び、状態の呪文と**同じ確率の表**（100 / 70 / 30 / 0 %）で効くかを決める。
--     → ★見込み = 効く確率 × min(平均, 残り HP)。耐性は呪文が ROM から持っている `s.resist`（`dq3rom/spells.py`）。
--   ⚠⚠ RX3-0137 は「ダメージは倍率（段 3 でも 50% 通る）」と見ていた = **誤り**（倍率表を使うのはブレスだけ）。
--   ★倒せる数は**必ず効くとき**（確率 1）だけ数える（⚠ 7 割でも外れれば倒れない / 全滅できるかの判断に使う）。
--   ★戻り値: 見込み, 当たる数, 倒せる数, 1 ターン目の頭に入るダメージ {[群] = {[k] = dmg}}
--     （★3 つ目からは RX3-0198。⚠ 1 つ目だけ使う呼び方もそのまま動く）
--   ★単体の呪文は**生きている先頭の敵**に当てて見る（`g.hps[1]` / ⚠ 以前は `g.hp[1]` = 倒れた敵の 0）
--: ★★ 即死（ザキ / ザラキ）を撃ってよい最低の成功率（RX3-0322 / 2026-09-20）
--
--   ⚠⚠ 「効く確率 × 残り HP」だけで見ると、★HP の高いボスに**低い確率で連打**します。
--   → ★確率がこれ未満なら候補にしません（⚠ `drain_min_rate` と同じ考え方）。
--   ★DQ3 の耐性は 4 段（100% / 70% / 30% / 0%）なので、★0.5 は「70% 以上だけ」を意味します。
Actions.BEAT_MIN_RATE = 0.5

--- ★即死の見込み（RX3-0322）。★= 効く確率 × その敵の残り HP。⚠ 確率が低ければ 0。
--
--   ⚠⚠ 今まで `spell_effect` は `base` / `delta`（ダメージ）しか見ておらず、
--     ★ザキ・ザラキは `base = nil` なので **`val = 0` → `no_effect` で黙って落ちて**いました。
local function beat_effect(s, g, sit, cat, min_rate)
  local floor = tonumber(min_rate) or Actions.BEAT_MIN_RATE
  local total, hits, kills, pre = 0, 0, 0, {}
  local function hit(grp, only_first)
    local p = rate_for(cat, grp, s.resist)
    -- ⚠ 低い確率で連打しない。★最短撃破では床が 0（= 見込み `gain` で自然に負けさせる / RX3-0327 §6）
    if p < floor then return end
    local hps = grp.hps or {}
    if #hps == 0 and grp.alive_n > 0 then
      local n = only_first and 1 or grp.alive_n
      total = total + p * grp.hp_sum * (n / grp.alive_n)
      hits = hits + n
      return
    end
    local row = {}
    for k, h in ipairs(hps) do
      if (not only_first) or k == 1 then
        row[k] = h * p                               -- ★倒せば残り HP すべてを削ったのと同じ
        total = total + p * h
        hits = hits + 1
        if p >= 1 then kills = kills + 1 end          -- ⚠ 確実に効くときだけ「倒す」と数える
      end
    end
    pre[grp.index] = row
  end
  if s.scope == "all" then
    for _, other in ipairs(sit.groups) do
      if other.alive_n > 0 then hit(other, false) end
    end
  elseif s.scope == "group" then
    hit(g, false)
  else
    hit(g, true)
  end
  return total, hits, kills, pre
end

--- ★その呪文をその群に撃ったときの見込み。
--   `min_rate` … ⚠ 即死だけに効く「候補に入れる最低の成功率」（★無ければ `BEAT_MIN_RATE`）
function Actions.spell_effect(s, g, sit, cat, min_rate)
  -- ★即死は「ダメージ」ではないので、★別の数え方（RX3-0322）
  if s.kind == "instant" and s.effect == "beat" then
    return beat_effect(s, g, sit, cat, min_rate)
  end
  local avg = avg_of(s)
  local total, hits, kills, pre = 0, 0, 0, {}
  local function hit(grp, only_first)
    local p = rate_for(cat, grp, s.resist)
    local hps = grp.hps or {}
    if #hps == 0 and grp.alive_n > 0 then            -- ⚠ 1 体ずつが無い（古い呼び方）: 合計で見る
      local n = only_first and 1 or grp.alive_n
      total = total + p * math.min(avg * n, grp.hp_sum)
      hits = hits + n
      return
    end
    local row = {}
    for k, h in ipairs(hps) do
      if (not only_first) or k == 1 then
        row[k] = avg * p
        total = total + p * math.min(avg, h)
        hits = hits + 1
        if h <= avg and p >= 1 then kills = kills + 1 end
      end
    end
    pre[grp.index] = row
  end
  if s.scope == "all" then
    for _, other in ipairs(sit.groups) do
      if other.alive_n > 0 then hit(other, false) end
    end
  elseif s.scope == "group" then
    hit(g, false)
  else
    hit(g, true)
  end
  return total, hits, kills, pre
end

----------------------------------------------------------------------
-- ★★ 攻撃呪文を撃つか（RX3-0198 / 2026-09-12 依頼者の指示書「魔法の評価 v1.1」）
----------------------------------------------------------------------
--
-- ⚠⚠ 2026-09-12 依頼者「速攻でも結構魔術師が魔法使わない」（save3）。★調べた原因:
--
--   ```text
--   save3  敵 2 体（HP 35 ずつ / 合計 70）× 4 人の物理 1 ターン合計 69
--          → 敵撃破 1.0T ≦ 2 → 「消化戦」→ ⚠ レベル上げ（速攻）は魔法の役を作らない
--          ★実際は 1 体目を倒し過ぎ（25+21=46 > 35）、2 体目に 18+5=23 < 35 → 2 ターンかかる
--          → 魔術師（物理 5）は 2 ターン殴るだけ。★イオ（1 体 16）なら 1 ターンで終わっていた
--   ```
--
--   ⚠ 疑い (a) 敵 2 体以上でないと魔法の役を作らない / (b) 消化戦で作らない /
--     (c) 物理の見込みに HP の頭打ちが無い（合計でしか見ない）/ (d) 単体の見込みが倒れた敵の 0
--   → ★判断を「戦況の名前」ではなく**何ターン短くなるか**で決める。
--
-- ## ★見るもの（★呪文ごと・群ごとの候補）
--
--   ```text
--   val        呪文の見込み（1 体ずつ残り HP で頭打ち / 耐性は倍率）
--   phys       その人が殴ったときの見込み（★比べる相手）
--   rounds     1 ターン目にこの呪文を入れて、物理だけで片づくまでのターン（★1 体ずつ数える）
--   saved      物理だけのターン − rounds（★整数）
--   gain       (val × magic_bonus[作戦] − phys) / こちらの物理 1 ターン分   ★指示書の「短くなるターン」
--   kills      倒せる数 / kills_group は群（全体なら全員）を倒し切るか
--   ```
--
-- ## ★作戦ごとの決め方（★数字は `generate.py` の TUNING / ⚠ 画面には出さない）
--
--   ```text
--   どの作戦も撃たない  物理だけでこのターンに片づく（magic_skip_rounds.group = 1）
--                       敵 1 体で物理 2 ターン以内（magic_skip_rounds.single = 2 / 弱い単体に MP を捨てない）
--                       単体で、その人の物理がもう倒せる / 呪文 × 重み ≦ 物理
--                       単体で、呪文 < 物理 × magic_single_ratio（★「はっきり強い」でない）
--   速攻（leveling）    saved ≧ 1 か gain ≧ magic_min_gain.leveling（0.5）→ 撃つ
--   節約（economy）     saved ≧ 1 かつ gain ≧ magic_min_gain.economy（0.5 / 重み 0.6）→ 撃つ
--                       または 群を倒し切れて、物理ではこのターンに倒し切れない → 撃つ
--   生存（survival）    戦況が均衡・劣勢のときだけ（★今までどおり）。危険な群を倒せるなら removes_threat
--   ```
--
--   ⚠ MP 制約は作戦より上（★`mp_allows` で先に落とす）: 使用禁止は候補が 0、温存は床より上だけ。

--- ★物理（平均）だけで、敵を全部倒すのに何ターンかかるか（★1 体ずつの HP で / 目安）。
--
--   ★一番 HP の少ない敵から殴る（⚠ 会心・ばらつき・敵の回復・逃げは見ない）。
--   `pre`  … 1 ターン目の頭に入る呪文のダメージ（`spell_effect` の 4 つ目）/ nil
--   `idle` … 1 ターン目に殴らない人（★呪文を唱える人）
--   ⚠ 1 体ずつの HP が分からない群があれば nil（★分からないで返す / 推測しない）。
--   ★`idle` は 1 人（slot）でも、集まり（`{[slot] = true}`）でもよい（★RX3-0260: マホトラの人を 2 人以上休ませて見る）
local function is_idle(idle, slot)
  if type(idle) == "table" then return idle[slot] == true end
  return slot == idle
end

function Actions.clear_rounds(sit, caps_by_slot, pre, idle, limit)
  limit = limit or 10
  local foes = {}
  for _, g in ipairs(sit.groups or {}) do
    if g.alive_n > 0 then
      if g.hps == nil or #g.hps == 0 then return nil end
      -- ★RX3-0226: 1 体ずつの**いまの**守備力（`g.defs[k]`）→ 群の値 → 表（⚠ 無ければ今までどおり）
      local def = g.def or (g.stats and g.stats.defense) or sit.enemy_def
      for k, h in ipairs(g.hps) do
        local d = (pre and pre[g.index] and pre[g.index][k]) or 0
        if h - d > 0 then foes[#foes + 1] = {hp = h - d, def = (g.defs and g.defs[k]) or def} end
      end
    end
  end
  if #foes == 0 then return 0 end
  local hitters = {}
  for _, m in ipairs(sit.alive or {}) do
    local caps = (caps_by_slot or {})[m.slot]
    if not (caps and caps.blocked) then hitters[#hitters + 1] = m end
  end
  for round = 1, limit do
    for _, m in ipairs(hitters) do
      if not (round == 1 and is_idle(idle, m.slot)) then
        local best = nil
        for _, f in ipairs(foes) do
          if f.hp > 0 and (best == nil or f.hp < best.hp) then best = f end
        end
        if best == nil then return round end
        local est = Damage and Damage.physical(m.attack, best.def)
        best.hp = best.hp - ((est and est.avg) or 0) * phys_scale(m, sit)
      end
    end
    local left = false
    for _, f in ipairs(foes) do if f.hp > 0 then left = true; break end end
    if not left then return round end
  end
  return limit + 1
end

--: ★物理だけでこれより長くかかる = 「片づかない」（★`clear_rounds` の既定の上限と同じ / RX3-0226）
Actions.STALL_ROUNDS = 10

--- ★その候補を撃つか（★決め方は上の表）。戻り値: "use" / "skip", 理由の語。
function Actions.judge_magic(c, ctx, sit, phys_rounds)
  local t = ctx.tuning
  local strategy = ctx.strategy or ECONOMY
  -- ★★ 最短撃破（RX3-0327 / 依頼者「MP節約用の足切りを撤廃」）。
  --   ⚠ MP を節約するための見送りを**当てません**。★見るのは「手数が減るか」だけ。
  local shortest = (strategy == LEVELING)
  if (c.val or 0) <= 0 then return "skip", "no_effect" end
  if phys_rounds ~= nil then
    -- ⚠⚠ 「敵 1 体で物理 2 ターン以内なら撃たない」は**最短撃破では見ません**（§4-1）。
    --   ★依頼者「呪文で1ターン短縮できるなら候補にする」
    --
    -- ★★ 2026-09-21（RX3-0347）: ⚠ **道具にも当たっていました**。
    --   ★この門の理由は「弱い単体に **MP を捨てない**」ですが、
    --   ⚠ 道具は MP を払いません（★ROM は道具の効果で MP の判定と消費を通らない）。
    --   → ⚠⚠ 理由が当てはまらないのに、★下の「道具だけの分岐」へ**辿り着く前に**
    --     返っていました（★依頼者のログ: `item=いなづまのけん reason=weak_single_enemy`）。
    if not shortest and not c.item and (sit.enemy_alive or 0) <= 1
        and phys_rounds <= tuned(t, "magic_skip_rounds", "single", 2) then
      return "skip", "weak_single_enemy"
    end
    -- ★これは**どの作戦でも見ます**（⚠ 物理でこのターン終わるなら、撃ってもターンは減らない）
    if phys_rounds <= tuned(t, "magic_skip_rounds", "group", 1) then
      return "skip", "physical_finishes_this_turn"
    end
  end
  if c.hits <= 1 and c.phys >= (c.target_hp or math.huge) then return "skip", "physical_enough" end
  -- ★★ 道具の攻撃（まどうしのつえ など / RX3-0213 / 依頼者「リソース節約で使えるようになる」）。
  --   ★MP を払わないので、作戦の重み・「はっきり強い」の倍率・生存優先の戦況は見ない:
  --     1 ターン短くなる（saved ≧ 1）か、その人の物理より強い（gain > 0）なら使う。
  --   ⚠ 上の見送りはそのまま（物理でこのターンに片づく / 弱い敵 1 体 / 物理で倒せる単体）
  if c.item then
    if (c.saved or 0) >= 1 then return "use", "item_saves_turn" end
    if (c.gain or 0) > 0 then return "use", "item_stronger_than_physical" end
    return "skip", "physical_stronger"
  end
  if c.val * c.bonus <= c.phys then return "skip", "physical_stronger" end
  -- ⚠⚠ 「単体呪文は物理の 2 倍ないと撃たない」は**最短撃破では効きません**（RX3-0327 §4-2）。
  --   ★依頼者「倍率ではなく、戦闘終了までの手数が減るかを優先する」
  --   ⚠ 止め方は**データ 1 本**です（`magic_single_ratio.leveling = 1.0`）。
  --     ★ここに `not shortest` を足すと**二重の歯止め**になり、⚠ 片方を壊しても
  --       検査が緑のままになります（2026-09-20 の壊す実験で実際に踏んだ）。
  if c.hits <= 1 and not c.beat
      and c.val < c.phys * tuned(t, "magic_single_ratio", strategy, 2.0) then
    return "skip", "single_target_not_clearly_stronger"
  end
  -- ★★ 物理では片づかない（RX3-0226 / 依頼者「守備力をめちゃ上げる敵 … 消化戦になって負ける」）。
  --   ★物理の見込みを補正した（いまの守備力 / マヌーサ / 実測）うえで、物理だけでは
  --   `STALL_ROUNDS` ターン以内に倒し切れないなら、どの作戦も gain が足りれば撃つ。
  --   ⚠ 補正の材料が無いときは見ない（★今までどおり / `clear_rounds` の上限 10 は 1 ターン目の呪文しか数えない）
  if sit.phys_adjusted == true and phys_rounds ~= nil and phys_rounds > Actions.STALL_ROUNDS
      and (c.gain or 0) >= tuned(t, "magic_min_gain", strategy, 0.5) then
    return "use", "physical_stalled"
  end
  if strategy == SURVIVAL then
    -- ★生存優先は今までどおり「均衡・劣勢で危険を減らす」だけ（⚠ 優勢・消化戦は物理）
    if sit.kind ~= "even" and sit.kind ~= "disadvantage" then return "skip", "situation_safe" end
    if c.gain < tuned(t, "magic_min_gain", SURVIVAL, 0.0) then return "skip", "not_worth_turn_gain" end
    return "use", c.removes_threat and "removes_threat" or "reduce_danger"
  end
  local min_gain = tuned(t, "magic_min_gain", strategy, 0.5)
  -- ★★ ⚠⚠ ターン数は**整数**なので、長期戦では全候補が同じになります（RX3-0322 ③）。
  --
  --   ★実測（依頼者の save1 / クラーゴン 3 体）: 敵 HP 1350 / こちらの 1 ターン 212
  --     → ⚠ 7 ターン戦。呪文 1 発（75〜240）では `rounds` が動かず **saved が 0 のまま**。
  --     → ⚠⚠ 「1 ターン縮める」という強い理由が**永遠に立たない**。
  --
  --   ★`gain` は同じことを**実数**で表しています（= (見込み×重み − 物理) / 1 ターンの火力）。
  --   → ★整数の `saved` が 0 でも、⚠ 実数で 1 ターン以上縮むなら同じ扱いにします。
  local saved = math.max(c.saved or 0, c.gain or 0)
  if shortest then
    -- ★★ 最短撃破（RX3-0327 §4-3）。⚠ MP 節約のための 0.5 ターン足切りは**撤廃**。
    --   ★ここへ来た時点で `c.val * c.bonus > c.phys`（上で見送り済み）＝ **gain > 0**。
    --   → ★「その人の物理より手数が減る」なら撃ちます。
    if saved >= 1 or (c.gain or 0) > min_gain then
      return "use", (c.hits <= 1) and "clearly_stronger" or "expected_turn_reduction"
    end
    return "skip", "not_worth_turn_gain"
  end
  -- ★リソース節約（⚠ 魔法の禁止ではない / 依頼者の指示書）
  if saved >= 1 and c.gain >= min_gain then return "use", "expected_turn_reduction" end
  if c.kills_group and c.hits >= 2 and c.group_hp > (sit.our_dpt or 0) and c.gain > 0 then
    return "use", "group_wipe"
  end
  return "skip", "resource_cost_not_worth_turn_gain"
end

--: ★「ほぼ同じ強さ」とみなす幅（RX3-0322 / ⚠ ここより差が小さいときだけ道具を優先）
--
--   ★10%。⚠ これより大きく違えば、**強いほうを選びます**（= 依頼者の困りごとの本体）。
local ITEM_TIE = 0.10

--: ★★ 「長期戦」とみなすターン数（RX3-0322 / 2026-09-20）
--
--   ⚠⚠ ここが今回の肝です。**短い戦いと長い戦いで、正しい答えが逆になります**。
--
--   ```text
--   短い戦い（2〜3 ターン）★ターン数は本当に意味がある
--     ⚠ 呪文が強くても、**終わるターンが変わらないなら MP の無駄**
--     → ★同じターン数なら道具（= `RX3-0213` の判断。★これは正しい）
--
--   長い戦い（4 ターン以上）⚠⚠ ターン数が**整数なので飽和**する
--     ★実測（依頼者の save1 / クラーゴン 3 体）: 敵 HP 1350 / こちらの 1 ターン 212
--       → 7 ターン戦。⚠ 呪文 1 発（75〜240）では rounds が動かず**全候補が 7 で並ぶ**
--       → ⚠⚠ 見込み 240（ライデイン）が 126（つえ）に負ける
--     → ★見込みで比べる（⚠ 削った分はちゃんと効いている）
--   ```
--
--   ⚠ 依頼者「HP が高い敵で長期戦になるので不具合に近い」。
local LONG_FIGHT = 4

--: ★正味 MP が「同じくらい」とみなす幅（RX3-0365）。
--  ⚠ 差し引きは連続値なので、★0.5 MP の差で順番が入れ替わると説明できません。
--  → ★これ以内なら次の物差し（見込み）で決めます。
local NET_MP_TIE = 1.0

--- ★候補の並べ方（★速攻 = 見込み → 同じくらいなら道具 / 節約 = 安い / 生存 = 危険な群）
local function better(strategy, a, b)
  if b == nil then return true end
  if strategy == SURVIVAL then
    if a.threat_val ~= b.threat_val then return a.threat_val > b.threat_val end
    return (a.spell.mp or 0) < (b.spell.mp or 0)
  end
  local ra, rb = a.rounds or 99, b.rounds or 99
  if ra ~= rb then return ra < rb end
  -- ★★ ⚠⚠ 2026-09-20（RX3-0322）: **ここで道具を優先していました**。
  --
  --   ⚠ 依頼者「save1 でクラーゴン戦で…速攻なのにイカヅチのつえを使う。何故だろうか。」
  --
  --   ```text
  --   ⚠ 今まで  ターン数が同じ → **見込みを見る前に道具が勝つ**
  --   ★実測     敵 HP 1350 / こちらの 1 ターン 212 の**7 ターン戦**では
  --             呪文 1 発では rounds が動かず、⚠ **全候補が 7 で並ぶ**
  --             → ★見込み 240（ライデイン）でも 126（つえ）に負ける
  --   ```
  --
  --   ★`RX3-0213` の判断（同じターン数なら MP を残す）自体は正しいのですが、
  --   ⚠ 想定が「2〜3 ターンで終わる戦い」でした。★長期戦では整数のターン数が飽和します。
  --
  --   → ★**見込みを先に比べ、近いときだけ道具を優先**します。
  -- ⚠⚠ 物差しは判定（`judge_magic`）と**同じ**にします（RX3-0322 ②）。
  --   ★今までは 判定は作戦の重み込み・選抜は重み無視、という**二重基準**でした。
  local aw = (a.val or 0) * (a.bonus or 1)
  local bw = (b.val or 0) * (b.bonus or 1)
  -- ★★ リソース節約 v2（RX3-0365 / 案A）: ⚠ **正味の MP** で比べます。
  --
  --   ⚠⚠ 2026-09-22 訂正（RX3-0367）: ★ここは下の「道具」より**あと**に置いていました。
  --     → ⚠ 長期戦（4 ターン以上）では**下の「はっきり強いほう」で先に決まってしまい**、
  --       ★正味の MP が**一度も見られませんでした**。⚠ 案A の ② は
  --       「①を通った中で正味の MP が最小のものを選ぶ」なので、**ここが正しい位置**です。
  --     ⚠ 長期戦の見込み優先（`RX3-0322`）は**最短撃破の**直しでした
  --       （★依頼者「速攻なのにイカヅチのつえを使う」）。節約には当てません。
  --   ★`net_mp` は `magic_eval` が入れます（⚠ 無ければ今までどおり素の MP）。
  if strategy == ECONOMY then
    local am = a.net_mp or (a.spell.mp or 0)
    local bm = b.net_mp or (b.spell.mp or 0)
    if math.abs(am - bm) > NET_MP_TIE then return am < bm end
  end
  local long = ra >= LONG_FIGHT
  if long and math.abs(aw - bw) > math.max(aw, bw) * ITEM_TIE then
    return aw > bw                                  -- ★長期戦: はっきり強いほうを選ぶ
  end
  -- ★道具の攻撃（MP 0 / RX3-0213）は、同じターン数なら呪文より先
  --   （★同じだけ早く終わるなら MP を残す）。⚠ 呪文のほうが 1 ターン早ければ上で呪文が勝つ
  if (a.item == true) ~= (b.item == true) then return a.item == true end
  if aw ~= bw then return aw > bw end
  if a.val ~= b.val then return a.val > b.val end
  return (a.spell.mp or 0) < (b.spell.mp or 0)
end

--- ★足場から `better` を確かめるための口（RX3-0322）。
--   ⚠ 画面を通さずに並べ方だけを見たい（★戦況を作らずに済む）。
function Actions.magic_better(strategy, a, b) return better(strategy, a, b) end

--- ★見立てに使う攻撃の候補（★MP の制約を通った呪文 ＋ 道具の攻撃）。戻り値: 候補, 断った理由
--
--   ★道具（まどうしのつえ など / RX3-0213）は `mp_allows` を通さない:
--     ROM は道具の効果で MP の判定と消費を通らない（`.bs_player_item_as_chant`）。
--     → ★MP 使用禁止でも、温存の床を割っていても候補に残る。
local function attack_pool(member, caps, ctx)
  local pool, deny = {}, nil
  for _, s in ipairs(caps.attack or {}) do
    local ok, why = Actions.mp_allows(member, s, ctx, false)
    if ok then pool[#pool + 1] = s else deny = why end
  end
  -- ★即死（ザキ / ザラキ / RX3-0322）。⚠ MP を払うので、攻撃呪文と同じ制約を通す
  for _, s in ipairs(caps.instant or {}) do
    local ok, why = Actions.mp_allows(member, s, ctx, false)
    if ok then pool[#pool + 1] = s else deny = why end
  end
  for _, s in ipairs(caps.attack_items or {}) do pool[#pool + 1] = s end
  return pool, deny
end

--- ★1 人ぶんの見立て（★唱えられる攻撃呪文・道具の攻撃 × 群）。戻り値は下の `ev`。
--
--   ev = {slot, spell, group, val, phys, hits, kills, rounds, saved, gain, decision, reason, item}
--   ★道具の攻撃は `spell.item_id` を持ち、`c.item = true`・重みは `magic_bonus_item`（RX3-0213）。
--   ⚠ 候補が無ければ spell = nil（reason = mp_floor / mp_short）。
function Actions.magic_eval(member, caps, ctx, sit, cat, phys_rounds, caps_by_slot)
  local strategy = ctx.strategy or ECONOMY
  local bonus = tuned(ctx.tuning, "magic_bonus", strategy, 1.0)
  local bonus_item = tuned(ctx.tuning, "magic_bonus_item", strategy, 1.0)
  local _, phys_best = Actions.pick_group(member, ctx, sit, nil)
  local top_threat = 0
  for _, g in ipairs(sit.groups) do
    if g.alive_n > 0 and (g.threat or 0) > top_threat then top_threat = g.threat end
  end
  local pool, deny = attack_pool(member, caps, ctx)
  local cands = {}
  for _, s in ipairs(pool) do
    local item = s.item_id ~= nil
    local weight = item and bonus_item or bonus
    for _, g in ipairs(sit.groups) do
      if g.alive_n > 0 then
        -- ★即死の下限は作戦ごと（⚠ 最短撃破は 0 = 固定の足切りをしない / RX3-0327 §6）
        local beat_floor = tuned(ctx.tuning, "beat_min_rate", strategy, Actions.BEAT_MIN_RATE)
        local val, hits, kills, pre = Actions.spell_effect(s, g, sit, cat, beat_floor)
        local c = {slot = member.slot, spell = s, group = g, val = val, hits = hits, kills = kills,
                   bonus = weight, item = item,
                   -- ★即死（RX3-0322）。⚠ 「ダメージ」ではないので、単体の倍率の見送りを当てない
                   beat = (s.kind == "instant" and s.effect == "beat")}
        if s.scope == "all" then
          c.phys, c.target_hp, c.group_hp = phys_best, sit.enemy_hp, sit.enemy_hp
          c.kills_group = kills >= (sit.enemy_alive or 0)
          c.threat_val = val * 2
        else
          c.phys = physical_avg(member, sit, g)
          c.target_hp = (s.scope == "group") and g.hp_sum or (g.first_hp or 0)
          c.group_hp = g.hp_sum
          c.kills_group = kills >= g.alive_n
          local share = (sit.enemy_dpt or 0) > 0 and (g.threat or 0) / sit.enemy_dpt or 0
          c.threat_val = val * (1 + share)
        end
        c.removes_threat = c.kills_group and (s.scope == "all" or g.can_heal == true
          or ((g.threat or 0) >= top_threat and top_threat > 0))
        c.rounds = Actions.clear_rounds(sit, caps_by_slot, pre, member.slot)
        if phys_rounds ~= nil and c.rounds ~= nil then c.saved = phys_rounds - c.rounds end
        local dpt = sit.our_dpt or 0
        if dpt > 0 then
          c.gain = (val * weight - c.phys) / dpt
        else
          c.gain = (val * weight > c.phys) and 99 or 0
        end
        c.decision, c.reason = Actions.judge_magic(c, ctx, sit, phys_rounds)
        -- ★リソース節約 v2（RX3-0365）: ⚠ 正味の MP を候補に持たせる（★ログにも出す）
        if strategy == ECONOMY then
          c.net_mp = Actions.net_mp_cost(c, ctx, sit, ctx._plan)
        end
        cands[#cands + 1] = c
        if s.scope == "all" then break end
      end
    end
  end
  if #cands == 0 then
    return {slot = member.slot, decision = "skip",
            reason = (deny == "MP温存") and "mp_floor" or "mp_short", phys = phys_best}
  end
  -- ★撃つ候補があれば作戦の並べ方で 1 つ。⚠ 無ければ「一番惜しかった」候補（gain 最大）を
  --   理由つきで返す（★判断ログで「なぜ撃たなかったか」を読めるように）
  local best_use, best_miss = nil, nil
  for _, c in ipairs(cands) do
    if c.decision == "use" then
      if better(strategy, c, best_use) then best_use = c end
    elseif best_miss == nil or c.gain > best_miss.gain then
      best_miss = c
    end
  end
  return best_use or best_miss
end

--- ★★ 役割を作る前に、唱えられる人ごとに 1 回だけ見立てる（★pipeline から / RX3-0198）。
--
--   戻り値: {by_slot = {[slot] = ev}, use = {[slot] = true}, n_use, phys_rounds}
--   ⚠ 使用禁止は候補が 0（★`Roles.caps` が攻撃呪文を入れない）→ `forbid = true` だけ立てる。
function Actions.magic_outlook(ctx, sit, caps_by_slot, cat)
  local out = {by_slot = {}, use = {}, n_use = 0, forbid = (ctx.mp_policy == "forbid")}
  out.phys_rounds = Actions.clear_rounds(sit, caps_by_slot, nil, nil)
  for _, m in ipairs(sit.alive or {}) do
    local caps = caps_by_slot[m.slot]
    if caps ~= nil and not caps.blocked then
      -- ★道具の攻撃（まどうしのつえ など）も見立てる（RX3-0213 / ⚠ 使用禁止でも残る）
      -- ★即死（ザキ / ザラキ）も「攻撃の手」に数える（RX3-0322 / ⚠ 足し忘れると黙って消える）
      local knows = #(caps.attack or {}) > 0 or #(caps.attack_items or {}) > 0
        or #(caps.instant or {}) > 0
      if not knows and not out.forbid and Catalog ~= nil then
        -- ★覚えているのに MP が足りない（⚠ 黙って物理にしない。記録に理由を残す）
        for _, sid in ipairs(caps.learned or {}) do
          local s = Catalog.spell(cat, sid)
          if s ~= nil and s.kind == "attack" then
            out.by_slot[m.slot] = {slot = m.slot, decision = "skip", reason = "mp_short"}
            break
          end
        end
      end
      if knows then
        local ev = Actions.magic_eval(m, caps, ctx, sit, cat, out.phys_rounds, caps_by_slot)
        ev.phys_rounds = out.phys_rounds
        out.by_slot[m.slot] = ev
        if ev.decision == "use" then
          out.use[m.slot] = true
          out.n_use = out.n_use + 1
        end
      end
    end
  end
  return out
end

--- ★開発用の判断ログ（★`AI tune` の行の中身 / pipeline が作戦名を前に付ける）
function Actions.magic_tune(ev, decision, reason)
  if ev == nil then return "magic_candidate=none decision=skip reason=" .. tostring(reason or "no_attack_spell") end
  local s, g = ev.spell, ev.group
  local where = "none"
  if s ~= nil then where = (s.scope == "all") and "all" or ("enemy_group_" .. g.index) end
  -- ★道具の攻撃は「item=品名」を添える（RX3-0213 / ⚠ magic_candidate は唱える呪文の名前のまま）
  local via = (s ~= nil and s.item_id ~= nil) and (" item=" .. tostring(s.item_name or s.item_id)) or ""
  -- ★★ 枠を数えたかどうか（RX3-0396 / 相談相手 §30）。
  --   ⚠⚠ 「なぜ 2 人目が通ったのか / 落ちたのか」を後から読めるように。
  if s ~= nil and Roles ~= nil and Roles.resource_free ~= nil then
    local free = Roles.resource_free(s)
    via = via .. string.format(" resource_mp=%d reusable=%s magic_slot_counted=%s",
                               tonumber(s.mp) or 0, tostring(free), tostring(not free))
  end
  -- ★リソース節約 v2（RX3-0365）: ⚠ **正味の MP**（= 呪文の MP − 浮いた回復の MP）。
  --   ★これが無いと「なぜ安いほうを選んだのか」が読めません（`RX3-0356` の教訓）。
  local net = ""
  if ev.net_mp ~= nil then
    net = string.format(" mp=%d net_mp=%.1f", (s and s.mp or 0), ev.net_mp)
  end
  return string.format(
    "magic_candidate=%s%s target=%s decision=%s reason=%s val=%d phys=%d gain=%.2f magic_rounds=%s phys_rounds=%s%s",
    s and (s.name or ("呪文" .. tostring(s.id))) or "none", via, where, decision or ev.decision,
    reason or ev.reason or "?", math.floor((ev.val or 0) + 0.5), math.floor((ev.phys or 0) + 0.5),
    ev.gain or 0, tostring(ev.rounds or "?"), tostring(ev.phys_rounds or "?"), net)
end

function Actions.magic(member, caps, ctx, sit, plan, cat)
  -- ★役割を作ったときの見立てをそのまま使う（⚠ 作り直すと、1 ターンの中で説明が揺れる）
  local look = ctx._magic
  local ev = look and look.by_slot[member.slot] or nil
  if ev == nil then
    local by = ctx._caps or {[member.slot] = caps}
    local rounds = Actions.clear_rounds(sit, by, nil, nil)
    ev = Actions.magic_eval(member, caps, ctx, sit, cat, rounds, by)
    ev.phys_rounds = rounds
  elseif look ~= nil then
    ev.phys_rounds = look.phys_rounds
  end
  local best = ev.spell
  -- ⚠ 見立てのあとに MP が変わっていないか（★同じターンに 2 度数えない）
  --   ★道具の攻撃は MP を見ない（RX3-0213 / ⚠ 使用禁止でも使う）
  local ok = best ~= nil and (best.item_id ~= nil or Actions.mp_allows(member, best, ctx, false))
  if ev.decision ~= "use" or not ok then
    local g, dmg, why = Actions.pick_group(member, ctx, sit, plan)
    local a = attack_action(g and g.index,
      string.format("物理のほうがよい（%s / 呪文 %d × %.1f・物理 %d）", ev.reason or "?",
                    math.floor((ev.val or 0) + 0.5), ev.bonus or 1.0, math.floor(dmg + 0.5)))
    a.tune = {Actions.magic_tune(ev, "skip"), attack_tune(g, why)}
    a.phys_dmg = dmg                 -- ★RX3-0226（★次のターンに実際の減りと比べる）
    return a
  end
  local best_g = ev.group
  -- ★★ 重複撃ちを止める（RX3-0327 §10 / ⚠ 作戦に関係ないバグ）。
  --
  --   ⚠⚠ 見立て（`magic_outlook`）は 1 人ずつ独立に群を選びます。★予約が積まれるのは
  --     ここ（`concrete`）なので、⚠ **2 人目が 1 人目と同じ群へ重ねて撃って**いました。
  --     ★物理は `pick_group` が予約を見ているのに、魔法だけ守られていませんでした。
  --   → ★もう倒れる見込みの群なら、**次の群**へ回します（⚠ どこも埋まっていれば物理へ）。
  -- ★★ 全体呪文も見ます（RX3-0330 / 2026-09-21 の実機ログ）。
  --   ⚠⚠ 実機で **ベギラゴンが同じターンに 2 発**飛んでいました（38 ターン中 4 回）。
  --     ★`scope == "all"` はここの見張りを素通りしていたためです。
  --   → ★どの群ももう倒れる見込みなら、2 人目は物理へ回します。
  if plan ~= nil and best ~= nil and best.scope == "all" then
    local alive_left = false
    for _, g in ipairs(sit.groups) do
      if g.alive_n > 0 and plan:hp_after_reserved_damage(g.index, g.hp_sum) > 0 then
        alive_left = true
        break
      end
    end
    if not alive_left then
      local g, dmg, why = Actions.pick_group(member, ctx, sit, plan)
      local a = attack_action(g and g.index,
        string.format("ほかの人の呪文でもう倒れる見込み（物理 %d）", math.floor(dmg + 0.5)))
      a.tune = {Actions.magic_tune(ev, "skip", "already_reserved"), attack_tune(g, why)}
      a.phys_dmg = dmg
      return a
    end
  end
  if plan ~= nil and best_g ~= nil and best.scope ~= "all" then
    if plan:hp_after_reserved_damage(best_g.index, best_g.hp_sum) <= 0 then
      local alt, alt_remain = nil, nil
      for _, g in ipairs(sit.groups) do
        if g.alive_n > 0 then
          local remain = plan:hp_after_reserved_damage(g.index, g.hp_sum)
          -- ★残りが少ない群から片づける（⚠ `pick_group` と同じ並べ方）
          if remain > 0 and (alt == nil or remain < alt_remain) then alt, alt_remain = g, remain end
        end
      end
      if alt == nil then
        -- ⚠ どの群ももう倒れる見込み → ★手番を捨てず物理へ（`pick_group` が予約を見る）
        local g, dmg, why = Actions.pick_group(member, ctx, sit, plan)
        local a = attack_action(g and g.index,
          string.format("ほかの人の呪文でもう倒れる見込み（物理 %d）", math.floor(dmg + 0.5)))
        a.tune = {Actions.magic_tune(ev, "skip", "already_reserved"), attack_tune(g, why)}
        a.phys_dmg = dmg
        return a
      end
      best_g = alt
    end
  end
  if plan ~= nil then
    if best.scope == "all" then
      -- ⚠ 群の残り HP を超えて予約しない（★3 人目を無駄に締め出さない / RX3-0330）
      for _, g in ipairs(sit.groups) do
        local remain = plan:hp_after_reserved_damage(g.index, g.hp_sum)
        if remain > 0 then
          plan:reserve_damage(g.index, math.min(avg_of(best) * g.alive_n, remain))
        end
      end
    else
      -- ⚠ 群の残り HP を超えて予約しない（★3 人目を無駄に締め出さない）
      local remain = plan:hp_after_reserved_damage(best_g.index, best_g.hp_sum)
      plan:reserve_damage(best_g.index, math.min(ev.val, remain))
    end
  end
  local target = (best.scope ~= "all") and {group = best_g.index} or nil
  local a
  if best.item_id ~= nil then
    -- ★★ 道具の攻撃（RX3-0213）: どうぐ → その品 → 敵の群（⚠ 窓に どうぐ が無ければ たたかう）。
    --   ⚠ 未確認: 道具の一覧の形（装備の印）/ 対象の窓が呪文と同じく敵の窓に付くか
    a = {kind = "item", item = "attack", item_id = best.item_id, item_tiles = best.item_tiles,
         name = best.item_name, target = target, fallback = "attack",
         why = string.format("%s（%s / MP 0）→ g%d 見込み%d（物理 %d / %s）",
                             best.item_name or ("道具" .. best.item_id), best.name or ("呪文" .. best.id),
                             best_g.index, math.floor(ev.val + 0.5), math.floor(ev.phys + 0.5),
                             ev.reason or "?")}
  else
    a = spell_action(best, target,
      string.format("%s → g%d 見込み%d（物理 %d / %s）", best.name or ("呪文" .. best.id),
                    best_g.index, math.floor(ev.val + 0.5), math.floor(ev.phys + 0.5), ev.reason or "?"))
  end
  a.tune = {Actions.magic_tune(ev)}
  return a
end

----------------------------------------------------------------------
-- 支援
----------------------------------------------------------------------

--: ★支援呪文の効き目（★倍率）。
--
--   ⚠⚠ **この倍率は目安のままです**（RX3-0138 / 2026-09-09 に確かめた）。
--     ★ROM の表（威力 0x13546 / 回復 0x1358E）に載っているのは
--     **ダメージ 18 件と回復 6 件だけ**で、⚠ 支援・妨害・即死の **20 件すべてが
--     `base = None`** でした。→ ★効き目はコードの中にあり、表からは出せません。
--     ⚠ 実測（実機で撃って前後のダメージを比べる）が要ります（NEED-FIXTURE）。
--
--   ★2026-09-09 に消せたのは「どの耐性で判定するか」の手置きです。
--     ⚠ `field` は書かず、**呪文が ROM から持っている `resist`** を使います
--     （★`dq3rom/spells.py` の `RESIST_FIELD`）。
--     ⚠⚠ 以前 `sap_group`（ルカニ）に `damage_reduction` と書いていましたが、
--       ★あれは**ダメージの通りやすさ**で、ルカニの耐性ではありません（誤り）。
--       ★RX3-0266 / RX3-0267: ルカニ・ルカナンの耐性は**耐性 8 `sap`**、ボミオスは**耐性 12**（JP ROM と実機で確定）。
--
--   our … こちらの火力の倍率 / enemy … 受けるダメージの倍率
--   status … ★その状態の旗（RX3-0268 / 敵の `statuses`）。⚠ 生きている敵が**全員**もうかかっている群には唱えない
--            （★ROM は既にかかっていれば判定もせず黙って戻る = 手番の無駄 / 眠り $B9F8・幻 $B9AC）
--: ★★ マヌーサ中の敵の物理**命中率**（⚠ **ROM の事実** / RX3-0338）。
--   ★JP bank4 `$8C2E` の `CMP #$A0`: 乱数 0〜255 が 160 未満なら外す
--     → 命中 (256 - 160) / 256 = **0.375** / ミス **5/8 = 0.625**（⚠ 北米版 `bank04.inc:1876` も同じ）。
--   ⚠⚠ ここが**唯一の正本**です（★`SUPPORT_EFFECTS.surround` も下の式もこれを読む）。
--   ⚠ 味方が幻のときの `TUNING.illusion_hit_rate` と同じ値ですが、★あちらは味方側の別経路です。
Actions.ILLUSION_HIT_RATE = 0.375

Actions.SUPPORT_EFFECTS = {
  defense_party = {enemy = 0.75, once = true},
  defense_single = {enemy = 0.85, once = true},
  sap_group = {our = 1.25, per_group = true},
  sap_single = {our = 1.30, per_group = true, single = true},
  attack_up = {our = 1.60, once = true, per_member = true},
  speed = {our = 1.10, once = true},
  slow = {enemy = 0.90, once = true},
  sleep = {disable = true, per_group = true, status = "asleep"},
  -- ★★ マヌーサ（RX3-0339 / 2026-09-21）。⚠⚠ **0.60 は手置きの旧モデルでした**。
  --   ★ROM の事実: 幻の敵の物理は 5/8 で外れる → 残るのは **0.375**
  --     （JP bank4 `$8C2E` の `CMP #$A0` / 北米版 `bank04.inc:1876`）。
  --   ⚠ `phys_only` は「★物理にだけ掛ける」印です。⚠⚠ これが無いと呪文・ブレスまで減ります。
  surround = {enemy = Actions.ILLUSION_HIT_RATE, per_group = true,
              status = "illusion", phys_only = true},
}

--- ★★ v1 の公開版では**選ばせない**支援（RX3-0429 / 2026-09-24 / 依頼者 §14）。
--
--   ⚠⚠ **完成させません。★通常 Auto の経路から外すだけ**です。
--     表そのもの（`SUPPORT_EFFECTS`）は残します（★値の由来が読めるように）。
--
--   ```text
--   slow（ボミオス）  ⚠ 群も耐性も見ていない（★Lv3 の中途半端）
--                     ★効き目 0.90 は手置きで、⚠ ROM から起こしていない
--   ```
--
--   ⚠ ここを空にすれば、★今までどおり全部が候補に戻ります（**戻せる閉じ方**）。
Actions.V1_CLOSED = {slow = true}

--- ★その群の生きている敵が全員、もうその状態か（RX3-0268）。⚠ 1 体でも「分からない」（nil）なら false（★止めない側）
local function all_affected(g, name)
  if g == nil or name == nil or (g.alive_n or 0) == 0 or g.statuses == nil then return false end
  for k = 1, #(g.hps or {}) do
    local st = g.statuses[k]
    if st == nil or st[name] ~= true then return false end
  end
  return #(g.hps or {}) > 0
end
Actions.all_affected = all_affected

--- ★得が一番大きい支援呪文。⚠ 得が 0 なら物理へ。★同じ呪文は 1 戦闘に 1 度。
--- ★その支援がもたらす「効き目」の形（⚠ `Support.turns_after` が読む）。
--   ⚠⚠ `Actions.support` と `Actions.support_outlook` の**両方**が使います
--     （★2 か所に同じ式を書かない / RX3-0331）。
local function support_effect_of(eff, g, sit, alive_n)
  local effect = {}
  if eff.disable and g and sit.enemy_dpt > 0 and g.threat then
    effect.enemy_damage_multiplier = math.max(1 - g.threat / sit.enemy_dpt, 0.05)
  else
    if eff.our then
      local share = (eff.per_group and g) and (g.hp_sum / math.max(sit.enemy_hp, 1)) or 1
      -- ★1 体だけに効く（ルカニ）なら、その 1 体ぶん
      if eff.single and g then share = (g.first_hp or 0) / math.max(sit.enemy_hp, 1) end
      if eff.per_member then share = 1 / math.max(alive_n, 1) end
      effect.our_damage_multiplier = 1 + (eff.our - 1) * share
    end
    if eff.enemy then
      -- ⚠⚠ **`share` は「パーティが受ける量のうち、その支援が届く割合」**です（RX3-0339）。
      --   ★`phys_only`（マヌーサ）は**物理にしか効かない**ので、⚠ 物理の量で見ます。
      --   ⚠⚠ ここを `g.threat` のままにすると、★呪文・ブレスまで 0.375 倍になります。
      --   ⚠ `g` は群を取らない支援では **false** です（★`each_support` が `{false}` を渡す）。
      local share = 1
      if eff.per_group and g then
        local reach = g.threat or 0
        if eff.phys_only then reach = g.phys_threat or g.threat or 0 end
        share = reach / math.max(sit.enemy_dpt, 1)
      elseif eff.phys_only then
        share = (sit.phys_dpt or 0) / math.max(sit.enemy_dpt, 1)
      end
      effect.enemy_damage_multiplier = 1 - (1 - eff.enemy) * share
    end
  end
  return effect
end
--: ★検査から**この式そのもの**を呼べるように出す（⚠ 写して照合しない / RX3-0339）
Actions.support_effect_of = support_effect_of

--- ★その人が使える支援を 1 つずつ見る（⚠ 判定の仕方は呼ぶ側が渡す）。
--   `score(effect, rate, g, alive_n, eff)` … ★その支援の「得」を返す関数
--   ⚠ 第 5 引数 `eff` は `SUPPORT_EFFECTS` の**素の定義**です（RX3-0332）。
--     ★倍率だけでは「何の支援か」が分からないので渡します
--     （⚠ マヌーサ/スクルトは物理だけ・ラリホーは全部、と扱いが違う）。
local function each_support(member, caps, ctx, sit, cat, used, score)
  local alive_n = #sit.alive
  local best, best_g, best_gain, best_why = nil, nil, 0, nil
  for _, s in ipairs(caps.support or {}) do
    local eff = Actions.SUPPORT_EFFECTS[s.effect or ""]
    -- ⚠⚠ v1 では**使わない**と決めた手は、★ここで落とします（RX3-0429 / 依頼者 §14）
    if Actions.V1_CLOSED[s.effect or ""] then eff = nil end
    local ok = eff ~= nil and Actions.mp_allows(member, s, ctx, false)
    if ok then
      local groups = eff.per_group and sit.groups or {false}
      for _, g in ipairs(groups) do
        local key = s.id .. ":" .. tostring(g and g.index or 0)
        if not (g and g.alive_n == 0) and not used[key] and not all_affected(g, eff.status) then
          -- ★どの耐性で判定するかは**呪文が ROM から持っている**（RX3-0138）
          local rate = 1.0
          if g and s.resist then rate = rate_for(cat, g, s.resist) end
          local gain, why = score(support_effect_of(eff, g, sit, alive_n), rate, g, alive_n, eff)
          if (gain or 0) > best_gain then best, best_g, best_gain, best_why = s, g, gain, why end
        end
      end
    end
  end
  return best, best_g, best_gain, best_why
end

function Actions.support(member, caps, ctx, sit, plan, cat, used)
  local assessment = {enemy_defeat_turns = sit.win, party_collapse_turns = sit.lose}
  local best, best_g, best_gain, best_why = each_support(
    member, caps, ctx, sit, cat, used,
    function(effect, rate, _g, alive_n)
      if Support == nil then return 0, nil end
      return Support.turn_gain(assessment, effect, alive_n, rate)
    end)
  if best == nil then
    local g, dmg = Actions.pick_group(member, ctx, sit, plan)
    local a = attack_action(g and g.index, string.format("支援の得が無い → 物理 約%d", math.floor(dmg + 0.5)))
    a.phys_dmg = dmg                 -- ★RX3-0226（★次のターンに実際の減りと比べる）
    return a
  end
  used[best.id .. ":" .. tostring(best_g and best_g.index or 0)] = true
  local target = nil
  if best_g and best.target == "enemy_group" then target = {group = best_g.index} end
  if best.target == "ally_single" then target = {ally = member.slot} end
  return spell_action(best, target,
    string.format("%s%s 得 %.1fT（%s）", best.name or ("呪文" .. best.id),
                  best_g and ("→g" .. best_g.index) or "", best_gain, best_why or ""))
end

----------------------------------------------------------------------
-- ★★ マホトラ（RX3-0260 / 2026-09-14 依頼者の小WI「リソース節約時のマホトラ活用」）
----------------------------------------------------------------------
--
-- ★作戦「リソース節約」の内部ルール（⚠ 新しい設定・専用の役割は足さない / 指示書 §1・§6）。
-- ★役割が**物理に回った人だけ**（★蘇生・回復・防御・支援・魔法の必要は先に割り当て済み = §5 の順が守られる）:
--
--   ```text
--   覚えている       手札の drain（`Roles.caps` / ⚠ 役割ではなく実際に覚えているか / §6）
--   MP が減っている  mp < mp_max
--   戦況             消化戦 / 優勢（⚠ 均衡・劣勢は使わない / §3）
--   攻撃呪文         このターンに撃つ人が居ない（§4「攻撃呪文を使用する必要がない」）
--   寄与が低い       その人を休ませても、物理だけで倒すターンが変わらない（`clear_rounds` の idle / §4・§5）
--                    ★優勢はさらに、その人の物理がこちらの物理 1 ターン分の drain_low_share 以下（§3 条件付き）
--   効く敵           最大 MP 0 は外す / 今の MP が読めれば 0 も外す / 効く確率 < drain_min_rate は外す（§7）
--   ```
--
-- ⚠ MP 方針「半分程度残す」の床は見ない（★消費 0 / 床を当てると MP が半分未満 = 使いたいときに弾く）。
-- ⚠ 使用禁止は手札に入らない（`Roles.caps` が先に抜ける）/ 速攻・生存優先は使わない（§8）。
-- ⚠ 耐性は AI の中だけで使う（★画面には出さない / No-Spoiler / §7）。

--: ★マホトラ 1 回で吸える量の平均（★ROM: 5 + 乱数 0〜5 / 相手の今の MP で頭打ち / JP bank 4 $A73C）
Actions.DRAIN_AVG = 7.5

--- ★その群へ撃ったときの見込み（1 回で吸える MP の期待値）。戻り値: 値（⚠ 効かなければ nil）, 理由
--
--   ★ROM（RX3-0260 / JP bank 4 $9B36 → $A726）: 選んだ群の**生きている 1 体をランダムに**選び、
--     耐性（索引 10 = `pc_damage_10` / 効く確率は段 0〜3 の表）で当たれば min(5〜10, 相手の今の MP) を吸う。
--     ★MP 255 の敵は減らない（★いつでも吸える）/ ⚠ 今の MP 0 の相手からは 0。
--   → ★1 体ずつ min(平均, 今の MP) の平均 × 効く確率。⚠ 今の MP が読めなければ最大 MP で見る
local function drain_value(s, g, ctx, cat)
  local stats = g.stats
  if stats == nil or (stats.mp or 0) <= 0 then return nil, "enemy_no_mp" end
  local rate = rate_for(cat, g, s.resist)
  if rate < tuned(ctx.tuning, "drain_min_rate", nil, 0.5) then return nil, "resisted" end
  local raw = (ctx.enemies or {})[g.index]
  local sum, n = 0, 0
  if raw ~= nil and type(raw.mp) == "table" then
    for k, v in pairs(raw.mp) do
      local alive = not (raw.alive and raw.alive[k] == false) and (raw.hp == nil or (raw.hp[k] or 0) > 0)
      if alive then
        sum = sum + math.min(Actions.DRAIN_AVG, tonumber(v) or 0)
        n = n + 1
      end
    end
  end
  if n == 0 then
    sum, n = math.min(Actions.DRAIN_AVG, stats.mp) * g.alive_n, g.alive_n
  end
  if sum <= 0 then return nil, "enemy_mp_empty" end
  return sum / math.max(n, 1) * rate, nil
end

--- ★開発用の判断ログ（★`AI tune` の行 / ⚠ `magic_candidate=` にしない = 集計が魔法の判断と数える）
local function drain_tune(s, g, decision, reason, member, rounds, phys_rounds)
  return string.format("drain_candidate=%s target=%s decision=%s reason=%s mp=%d/%d idle_rounds=%s phys_rounds=%s",
    s and (s.name or ("呪文" .. tostring(s.id))) or "none", g and ("enemy_group_" .. g.index) or "none",
    decision, reason, member.mp or 0, member.mp_max or 0, tostring(rounds or "?"), tostring(phys_rounds or "?"))
end

--- ★マホトラを使うか。戻り値: 行動（⚠ 使わなければ nil）, 使わなかった理由の判断ログ（⚠ 覚えていなければ nil）
function Actions.drain(member, caps, ctx, sit, plan, cat)
  local list = (caps or {}).drain or {}
  if #list == 0 then return nil, nil end
  local s = list[1]
  local look = ctx._magic or {}
  local phys_rounds = look.phys_rounds
  local function skip(reason, rounds)
    return nil, drain_tune(s, nil, "skip", reason, member, rounds, phys_rounds)
  end
  if (ctx.strategy or ECONOMY) ~= ECONOMY then return skip("strategy_" .. tostring(ctx.strategy)) end
  if (member.mp or 0) >= (member.mp_max or 0) then return skip("mp_full") end
  if sit.kind ~= "mop" and sit.kind ~= "advantage" then return skip("situation_" .. tostring(sit.kind)) end
  if (look.n_use or 0) > 0 then return skip("attack_spell_planned") end
  if phys_rounds == nil or phys_rounds > Actions.STALL_ROUNDS then return skip("rounds_unknown") end
  -- ★その人（と、このターンにもうマホトラへ回した人）を休ませても、倒すターンが変わらないか
  local idle = {}
  for slot in pairs(ctx._drain_idle or {}) do idle[slot] = true end
  idle[member.slot] = true
  local rounds = Actions.clear_rounds(sit, ctx._caps, nil, idle)
  if rounds == nil or rounds > phys_rounds then return skip("attack_needed", rounds) end
  if sit.kind == "advantage" then
    local _, mine = Actions.pick_group(member, ctx, sit, nil)
    if mine > (sit.our_dpt or 0) * tuned(ctx.tuning, "drain_low_share", nil, 0.25) then
      return skip("attack_not_low", rounds)
    end
  end
  local best_g, best_v, why = nil, nil, "no_target"
  for _, g in ipairs(sit.groups) do
    if g.alive_n > 0 then
      local v, no = drain_value(s, g, ctx, cat)
      if v ~= nil then
        if best_v == nil or v > best_v then best_g, best_v = g, v end
      else
        why = no
      end
    end
  end
  if best_g == nil then return skip(why, rounds) end
  ctx._drain_idle = ctx._drain_idle or {}
  ctx._drain_idle[member.slot] = true
  local a = spell_action(s, {group = best_g.index},
    string.format("%s → g%d で MP を回収（MP %d/%d / 殴らなくても %sT で片づく）", s.name or ("呪文" .. s.id),
                  best_g.index, member.mp or 0, member.mp_max or 0, tostring(rounds)))
  a.tune = {drain_tune(s, best_g, "use", "low_contribution", member, rounds, phys_rounds)}
  return a, nil
end

----------------------------------------------------------------------
-- 入口
----------------------------------------------------------------------

--- ★割当 → 実コマンド。
--: ★★ 同程度なら攻撃（RX3-0331 §1-2 / 依頼者「同値は攻撃」）。
--   ⚠ これは**比べる誤差を吸収するだけ**の値です。★大きな下駄にしないこと。
Actions.SUPPORT_EPS = 0.05

--- ★切り上げたターン数（⚠ `support_plan.lua` の `whole_turns` と同じ / ★あちらは local）。
local function whole_turns(value)
  if type(value) ~= "number" or value <= 0 then return nil end
  return math.ceil(value - 1e-9)
end

--- ★★ 最短撃破のための支援の「得」（RX3-0331 §3 / 2026-09-21）。
--
--   ⚠⚠ `Support.turn_gain` は **2 つの成分の和**です:
--
--   ```text
--   ① 倒すまでが縮む      （before_win - after_win）      ★これが「戦闘終了の短縮」
--   ② 崩れるまでが延びる  （after_lose - before_lose）    ⚠ これは**生存**であって短縮ではない
--   ```
--
--   ★最短撃破では **① だけ**を数えます（依頼者 §3-3:
--   「単に生存ターンを伸ばすだけで、戦闘終了時間の短縮を表していない場合は接続しない」）。
--
--   ⚠⚠ この結果、**敵の火力を下げるだけの支援は自動的に 0 になります**
--     （スクルト・スカラ・ボミオス・ラリホー・マヌーサ）。
--     ★名前で除外しているのではなく、**式がそう出す**ようにしてあります。
--   ⚠ 「敵を眠らせる → 回復の手番が減る → 早く終わる」は、
--     ★現行モデルでは**表現できていません**（依頼者 §11 ケースE の註 / 別 WI）。
local function shortest_support_gain(sit, effect, alive_n, rate)
  local before = whole_turns(sit.win)
  local mul = tonumber(effect.our_damage_multiplier)
  if before == nil or mul == nil or mul <= 0 then return 0, nil end
  -- ★支援に 1 手番使うぶん、倒すのが遅れる（⚠ `support_plan.action_cost` と同じ）
  local after = whole_turns(sit.win / mul + 1.0 / math.max(alive_n, 1))
  if after == nil or after >= before then return 0, nil end
  local gain = (before - after) * (rate or 1.0)
  return gain, string.format("倒すまで %d -> %d ターン", before, after)
end

----------------------------------------------------------------------
-- ★★ 最短撃破 v1.2 — 回復の手番が減るぶんを数える（RX3-0332 / 依頼者 §1〜§7）
----------------------------------------------------------------------
--
-- ⚠⚠ **被害を減らすこと自体には価値を与えません**（★それは「生存」で、v1.1 が外した側）。
--   ★価値があるのは、被害が減った結果 **将来の回復手番が減り、攻撃に回せる**ときだけです。
--
-- ```text
-- 被害が減る → 回復に使う手番が減る → 攻撃に回せる → 戦闘が早く終わる
-- ```

--- ★このパーティが「1 手番で回復できる量」（⚠ 実際に唱える呪文から）。
--
--   ⚠⚠ `caps.heal_power` は使いません。★あれは**覚えている呪文の最大**で、
--     ⚠ MP も、唱えられるかも、実際に戻る量も見ていません。
--
--   ★★ 2026-09-21（RX3-0335）: **全体回復も数えます**。
--     ⚠ それまで外していたのは、`Actions.heal` が唱えられなかったからです
--       （★唱えない呪文を見積もりに入れない）。→ ★唱えるようになったので入れます。
--     ⚠⚠ ただし **1 人ぶんの量**で数えます（★安全側）。
--       ★実際には傷んだ人数ぶん戻りますが、⚠ 何人傷むかは**この時点では分かりません**。
--       → ⚠ 人数を掛けると「1 手で 280 戻る」前提になり、**削減量を過大評価**します。
--   ★誰も回復できなければ `nil`（⚠ 減らせる手番が無い ＝ この支援に価値を出さない）。
function Actions.heal_per_action(ctx)
  local best = 0
  for _, caps in pairs(ctx._caps or {}) do
    for _, s in ipairs(caps.heal or {}) do
      if s.target == "ally_single" or s.target == Actions.PARTY_HEAL_TARGET then
        local avg = avg_of(s, nil)
        if s.base == 255 then avg = 255 end        -- ★ベホマ（⚠ 相手の最大 HP は分からないので上限で）
        if avg > best then best = avg end
      end
    end
    -- ⚠ 呪文が無くても やくそう があるなら、その分は回復できる
    if caps.herb then
      local herb = tonumber((ctx.tuning or {}).item_heal) or 30
      if herb > best then best = herb end
    end
  end
  if best <= 0 then return nil end
  return best
end

--- ★いま「回復が始まるまでの余裕」（⚠ 回復の線より上にある HP の合計）。
--
--   ⚠⚠ **このターンに予約済みの回復は足した後**で見ます（★依頼者 §11 の二重計上よけ）。
--     ⚠ そうしないと「いま回復する予定のぶん」まで支援の手柄にしてしまいます。
function Actions.heal_slack(ctx, sit, plan)
  local t = ctx.tuning or {}
  local strategy = ctx.strategy or ""
  local line = Actions.heal_line(ctx, sit)
  local slack = 0
  for _, m in ipairs(sit.alive or {}) do
    local hp = m.hp or 0
    if plan ~= nil and plan.hp_after_reserved_healing ~= nil then
      hp = plan:hp_after_reserved_healing(m.slot, m.hp, m.hp_max)
    end
    local floor_hp = (m.hp_max or 0) * line
    if hp > floor_hp then slack = slack + (hp - floor_hp) end
  end
  return slack
end

--- ★その被害を受けたら、回復に何手番かかるか（⚠ 固定値にはしない / 依頼者 §4-3）。
function Actions.recovery_actions(damage, slack, per_action)
  if per_action == nil or per_action <= 0 then return 0 end
  local need = damage - slack
  if need <= 0 then return 0 end
  return need / per_action
end

--- ★★ 回復 1 手番ぶんの MP（RX3-0365 / 2026-09-22）。
--
--   ★`heal_per_action` が「1 手番で**何 HP** 戻せるか」なので、その相方です。
--   ⚠⚠ **同じ呪文から取ります**（★別々に最大値を取ると、
--     「一番よく戻る呪文の量」と「一番安い呪文の値段」を混ぜた**存在しない呪文**になります）。
--   ★やくそうが一番戻るなら **0**（⚠ 道具は MP を払わない / `RX3-0346`）。
function Actions.heal_mp_per_action(ctx)
  local best, mp = 0, 0
  for _, caps in pairs(ctx._caps or {}) do
    for _, s in ipairs(caps.heal or {}) do
      if s.target == "ally_single" or s.target == Actions.PARTY_HEAL_TARGET then
        local avg = avg_of(s, nil)
        if s.base == 255 then avg = 255 end
        if avg > best then best, mp = avg, (s.item_id ~= nil) and 0 or (s.mp or 0) end
      end
    end
    if caps.herb then
      local herb = tonumber((ctx.tuning or {}).item_heal) or 30
      if herb > best then best, mp = herb, 0 end     -- ★道具なので 0
    end
  end
  if best <= 0 then return nil end
  return mp
end

--- ★★ リソース節約 v2 — その候補の**正味の MP**（RX3-0365 / 案A / 依頼者 §19）。
--
--   ```text
--   net_mp_cost = 呪文の MP − ★戦いが短くなって**要らなくなった回復の MP**
--   ```
--
--   ⚠⚠ **今まで MP / ターン の比はどこにも出てきませんでした**（`RX3-0357` Part B-2）。
--     ★`better()` の MP 比較は「全部同点のときのタイブレーク」でした。
--
--   ```text
--   例  MP  5 で 1 ターン短縮 ／ MP 30 で 2 ターン短縮
--   ⚠ 今まで  ターン数で先に決まり、★MP 30 は**一度も比べられない**
--   ★v2      2 ターン短縮で浮く回復 MP を引いてから、**安いほうを選ぶ**
--   ```
--
--   ⚠ 短縮できない候補（`saved <= 0`）は素の MP。★道具は 0（MP を払わない）。
--   ⚠ 誰も回復できない／傷んでいないときは差し引きません（★`recovery_actions` が 0 を返す）。
function Actions.net_mp_cost(c, ctx, sit, plan)
  if c == nil or c.spell == nil then return 0 end
  if c.item == true then return 0 end                 -- ★道具は MP を払わない
  local cost = c.spell.mp or 0
  local saved = c.saved or 0
  if saved <= 0 then return cost end
  local per_action = Actions.heal_per_action(ctx)
  local mp_each = Actions.heal_mp_per_action(ctx)
  if per_action == nil or mp_each == nil or mp_each <= 0 then return cost end
  local turns = whole_turns(sit and sit.win)
  if turns == nil or turns <= 1 then return cost end  -- ★このターンで終わる → 回復は要らない
  local slack = Actions.heal_slack(ctx, sit, plan)
  local dpt = Actions.effective_enemy_dpt(sit)
  local without = dpt * turns
  local with = math.max(dpt * math.max(turns - saved, 0), 0)
  local cut = Actions.recovery_actions(without, slack, per_action)
    - Actions.recovery_actions(with, slack, per_action)
  if cut <= 0 then return cost end
  return cost - cut * mp_each
end

----------------------------------------------------------------------
-- ★★ 最短撃破 v1.3 — 敵の複数回行動と、状態異常の**実測した**効き方（RX3-0337）
----------------------------------------------------------------------
--
-- ## ⚠⚠ 状態の旗は 3 つとも別もの（★RX3-0338 で取り違えを正した）
--
--   ```text
--   マヌーサ  $0530 bit4  ★物理攻撃に追加のミス判定（5/8 で外す）
--   メダパニ  $0531 bit4  ⚠ 行動／対象の変更（★敵同士の攻撃はこちら）
--   ラリホー  $0531 bit5  ★行動そのものを止める
--   ```
--
--   ⚠⚠ **マヌーサで同士討ちは起きません**（★実機 41 回で 0 回 / RX3-0338）。

--: ⚠ `Actions.ILLUSION_HIT_RATE`（★マヌーサの命中率 0.375）は**上の支援表の手前**で定義しています。
--   ★`SUPPORT_EFFECTS.surround.enemy` もそれを読むので、⚠ 値は 1 か所だけです（RX3-0339）。

--: ★眠りが続くターン数の期待値（⚠ **ROM の事実** / JP bank4 `$8BC3` ＋ 表 `$B4F3`）。
--   ★1T 0.254 / 2T 0.376 / 3T 0.279 / 4T 0.091 → 期待 2.207（⚠ 中央値は 2）。
Actions.SLEEP_EXPECTED_TURNS = 2.207

--: ★`per_turn`（ROM の 2bit）→ **1 ターンの期待行動回数**（⚠ RX3-0336 で確定）。
--   ⚠⚠ **値そのものを掛けてはいけません**（★0 は「0 回」ではなく「1 回」）。
Actions.ACTIONS_PER_TURN = {[0] = 1.0, [1] = 1.5, [2] = 2.125, [3] = 2.0}

--- ★`per_turn` の分類値を期待行動回数へ（⚠ 知らない値は**ふつうの敵**として 1.0）。
function Actions.expected_actions_per_turn(per_turn)
  local n = tonumber(per_turn)
  if n == nil then return 1.0 end
  return Actions.ACTIONS_PER_TURN[n] or 1.0
end

--- ★その群が 1 ターンに出す**物理**の量（⚠ 複数回行動を数えたもの）。
--
--   ⚠⚠ 掛ける先は**物理の土台だけ**です（★依頼者 §4-2）。
--     `g.threat` には全体攻撃・状態異常の割増が既に乗っているので、
--     ⚠ そちらへ掛けると**二重**になります。
function Actions.effective_physical_threat(g)
  if g == nil or g.phys_threat == nil then return 0 end
  local acts = (g.stats or {}).acts or {}
  return g.phys_threat * Actions.expected_actions_per_turn(acts.per_turn)
end

--- ★その群が 1 ターンに出す**すべて**の量（⚠ 物理は複数回行動を数え、非物理の割増はそのまま）。
function Actions.effective_threat(g)
  if g == nil or g.threat == nil then return 0 end
  local extra = g.threat - (g.phys_threat or 0)     -- ★非物理の割増（⚠ 回数は掛けない）
  return Actions.effective_physical_threat(g) + extra
end

--- ★パーティが 1 ターンに受ける量（⚠ **最短撃破の支援評価だけ**が使う）。
--
--   ⚠⚠ `sit.enemy_dpt` は**書き換えません**（★戦況・回復・生存・マホトラ・右画面が読むため）。
--     ★複数回行動を数えるのはここ 1 か所だけです（依頼者 §4-1）。
function Actions.effective_enemy_dpt(sit)
  local total = 0
  for _, g in ipairs((sit or {}).groups or {}) do
    if (g.alive_n or 0) > 0 then total = total + Actions.effective_threat(g) end
  end
  if total <= 0 then return sit and sit.enemy_dpt or 0 end   -- ⚠ 群が読めないときは今までどおり
  return total
end

--- ★その支援で「1 ターンあたり何ダメージ減るか」と「何ターンぶん効くか」。
--
--   ⚠⚠ ここが物理／非物理を分ける所です（★依頼者 §6-3）。
--
--   ```text
--   ラリホー  disable   ★その群の**すべて**（⚠ 行動そのものが止まる）/ ★2.207 ターン
--   マヌーサ  surround  ★その群の**物理だけ** × (1 - 0.375) / ★戦闘終了まで
--   スクルト  defense   ★パーティ全体の**物理だけ** × (1 - 0.75) / ★戦闘終了まで
--   ```
--
--   ⚠ どれも残りターン数で頭打ちにします（★短期戦で過大評価しない / 依頼者 §11）。
function Actions.support_damage_cut(eff, g, sit, ctx, turns)
  if eff.disable then
    -- ★眠らせる: その群が動かない（⚠ 非物理も止まる）
    if g == nil or g.threat == nil then return 0, 0 end
    return Actions.effective_threat(g), math.min(Actions.SLEEP_EXPECTED_TURNS, turns)
  end
  if eff.status == "illusion" then
    -- ★★ マヌーサ: **物理だけ**が 5/8 で外れる（⚠ 敵の数は見ない / 依頼者 §6-5）
    --   ⚠⚠ 同士討ちの加点は**入れません**（★実機で 0 回 / 依頼者 §6-6）。
    local phys = Actions.effective_physical_threat(g)
    if phys <= 0 then return 0, 0 end
    return phys * (1 - Actions.ILLUSION_HIT_RATE), turns   -- ★自然解除が無い → 残り全部
  end
  if eff.enemy == nil then return 0, 0 end
  local phys
  if eff.per_group then
    phys = Actions.effective_physical_threat(g)       -- ★その群の物理だけ
  else
    -- ★スクルト: パーティ全体が受ける物理（⚠ 群ごとに複数回行動を数える / 依頼者 §8）
    phys = 0
    for _, gg in ipairs(sit.groups or {}) do
      if (gg.alive_n or 0) > 0 then
        phys = phys + Actions.effective_physical_threat(gg)
      end
    end
  end
  if phys <= 0 then return 0, 0 end
  -- ⚠ 解除の無い強化（スクルト）は残りターンぶん
  return phys * (1 - eff.enemy), turns
end

--- ★★ 「回復の手番が減る」ぶんの得（⚠ 単位はターン。★攻撃側と揃える）。
--
--   ```text
--   recovery_gain = (減らせる回復手番 - 支援に使う 1 手番) / 生きている人数
--   ```
--
--   ⚠ 短期戦では 0（★依頼者 §5-4・§7-3）。⚠ 誰も回復できないなら 0。
function Actions.recovery_support_gain(sit, ctx, plan, eff, g, rate, alive_n)
  local turns = whole_turns(sit.win)
  if turns == nil or turns <= 1 then return 0, nil end   -- ★このターンで終わる → 支援しない
  if sit.kind == "mop" then return 0, nil end            -- ⚠ 消化戦は回復しない
  local per_action = Actions.heal_per_action(ctx)
  if per_action == nil then return 0, nil end            -- ⚠ 誰も回復できない → 減らせる手番も無い

  local cut, span = Actions.support_damage_cut(eff, g, sit, ctx, turns)
  if cut <= 0 or span <= 0 then return 0, nil end

  local slack = Actions.heal_slack(ctx, sit, plan)
  -- ⚠⚠ ここだけ**複数回行動を数えた**脅威を使う（★`sit.enemy_dpt` は触らない / 依頼者 §4-1）。
  --   ★`situation.lua` の戦況（`kind` / `lose`）は v1.2 のまま動きます。
  local without = Actions.effective_enemy_dpt(sit) * turns
  local saved_damage = cut * span * (rate or 1.0)
  local with = math.max(without - saved_damage, 0)

  local a_without = Actions.recovery_actions(without, slack, per_action)
  local a_with = Actions.recovery_actions(with, slack, per_action)
  local saved = a_without - a_with
  if saved <= 0 then return 0, nil end

  -- ★支援に 1 手番使う（⚠ `shortest_support_gain` の `1/alive_n` と同じ数え方）
  local gain = (saved - 1) / math.max(alive_n, 1)
  if gain <= 0 then return 0, nil end
  -- ★★ 判断の根拠を 1 行に（⚠ 依頼者 §12）。★何で減ったかが後から追えるように。
  local acts = (g and (g.stats or {}).acts) or {}
  return gain, string.format(
    "回復手番 %.1f -> %.1f（%s duration=%.2fT actions_per_turn=%.3f"
    .. " per_turn_class=%s success=%.2f threat=%.1f->%.1f）",
    a_without, a_with,
    eff.disable and "sleep" or (eff.status == "illusion" and "illusion" or "defense"),
    span, Actions.expected_actions_per_turn(acts.per_turn),
    tostring(acts.per_turn), rate or 1.0,
    without / math.max(turns, 1), with / math.max(turns, 1))
end

--- ★★ 最短撃破だけ: 支援のほうが手数を減らせるなら支援へ（RX3-0331 §5・§6）。
--
--   ⚠ 戻り値は実コマンド / `nil`（★`nil` なら今までどおりの道へ）。
--   ★比べるのはどちらも「何ターン縮むか」です（⚠ 単位が同じ）。
function Actions.shortest_support(member, caps, assign, ctx, sit, plan, cat, used)
  if (ctx.strategy or "") ~= LEVELING then return nil end
  -- ⚠ 回復・蘇生・防御は**安全網**なので横取りしません（★依頼者 §9 の安全網を残す）
  local role = assign.role
  if role ~= "physical" and role ~= "magic" then return nil end
  if #(caps.support or {}) == 0 then return nil end

  -- ★★ 火力向上型（v1.1）と回復手番削減型（v1.2）を**同じ単位**で比べる（RX3-0332 §9）。
  --   ⚠ どちらも「何ターン縮むか」。★大きいほうをその支援の得とする。
  local best, best_g, best_gain, best_why = each_support(
    member, caps, ctx, sit, cat, used,
    function(effect, rate, g, alive_n, eff)
      local gain, why = shortest_support_gain(sit, effect, alive_n, rate)
      local r_gain, r_why = Actions.recovery_support_gain(sit, ctx, plan, eff, g, rate, alive_n)
      if (r_gain or 0) > (gain or 0) then return r_gain, r_why end
      return gain, why
    end)
  if best == nil or best_gain <= 0 then return nil end

  -- ★攻撃側の「得」（⚠ 物理はその人の基準なので 0）
  local attack_gain = 0
  local look = ctx._magic
  local ev = look and look.by_slot and look.by_slot[member.slot] or nil
  if role == "magic" and ev ~= nil and ev.decision == "use" then
    attack_gain = ev.gain or 0
  end
  -- ⚠⚠ **同程度なら攻撃**（依頼者 §1-2「同値は攻撃」）
  if best_gain <= attack_gain + Actions.SUPPORT_EPS then return nil end

  used[best.id .. ":" .. tostring(best_g and best_g.index or 0)] = true
  local target = nil
  if best_g and best.target == "enemy_group" then target = {group = best_g.index} end
  if best.target == "ally_single" then target = {ally = member.slot} end
  local a = spell_action(best, target,
    string.format("%s%s 得 %.1fT（%s / 攻撃 %.1fT）", best.name or ("呪文" .. best.id),
                  best_g and ("→g" .. best_g.index) or "", best_gain,
                  best_why or "", attack_gain))
  -- ★★ 「なぜこの支援が最短撃破に寄与するのか」を 1 行で残す（RX3-0332 / 依頼者 §16）。
  --   ⚠ `best_why` が種別を語ります（★「回復手番 2.0 -> 0.8」or「倒すまで 4 -> 3 ターン」）。
  local kind_of = string.find(tostring(best_why), "回復手番") and "recovery" or "offense"
  a.tune = {string.format(
    "support_candidate=%s target=%s decision=use reason=shortest_support "
    .. "support_kind=" .. kind_of .. " support_why=\"%s\" "
    .. "support_gain=%.2f attack_gain=%.2f",
    best.name or ("呪文" .. best.id),
    best_g and ("enemy_group_" .. best_g.index) or "party",
    best_why or "", best_gain, attack_gain)}
  return a
end

function Actions.concrete(member, caps, assign, ctx, sit, plan, cat, used)
  ctx._sit, ctx._plan = sit, plan
  -- ★★ 最短撃破だけ: 支援のほうが手数を減らせるならそちらへ（RX3-0331）
  local swap = Actions.shortest_support(member, caps, assign, ctx, sit, plan, cat, used)
  if swap ~= nil then return swap end
  local role = assign.role
  if role == "heal" then
    if assign.job == "revive" then return Actions.revive(member, caps, assign, ctx) end
    return Actions.heal(member, caps, assign, ctx, sit, used)
  elseif role == "magic" then
    return Actions.magic(member, caps, ctx, sit, plan, cat)
  elseif role == "support" then
    return Actions.support(member, caps, ctx, sit, plan, cat, used)
  elseif role == "defend" then
    return {kind = "defend", fallback = "attack", why = assign.why or "耐える"}
  end
  -- ★★ マホトラ（RX3-0260）: 物理に回った人だけ。★使わなければ、理由の判断ログを 1 行添えて物理
  local d, note = Actions.drain(member, caps, ctx, sit, plan, cat)
  if d ~= nil then return d end
  local a = Actions.physical(member, ctx, sit, plan)
  if note ~= nil then
    a.tune = a.tune or {}
    table.insert(a.tune, 1, note)
  end
  return a
end

return Actions
