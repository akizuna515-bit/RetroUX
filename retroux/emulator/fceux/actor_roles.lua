--- 各個人が「作戦へどう貢献できるか」を返す（2026-08-07 / Phase 6）。
--
-- 指示書 §11:
--   > 各キャラクターは、具体的コマンドではなく、自分が作戦へ
--   > **どのように貢献できるか**を候補として返す。
--   > 各個人は上位3候補程度を返す。⚠ 全候補の総当たり探索は実施しない。
--
-- ★★ **ここは RAM もメニューも知りません。** ★★
--
-- ## ⚠⚠ 役割を「名前の表」で決めない
--
--   「サマルは回復役」と名前で決め打つと、⚠ **回復呪文を覚える前**や
--   **MPが尽きた後**も回復役のままになります。
--   ★できること（`caps`）から役割を組み立てます。
--     ローレシアが主火力なのは「ローレシアだから」ではなく
--     ★**MPを持たず攻撃力が高いから**です。
--
-- ## ★ 役割は4段（指示書 §18 Phase 6 の `ActorRoleProfile`）
--
--     primary    いちばん向いている
--     secondary  次に向いている
--     fallback   ⚠ 本職が要らないときの受け皿（★これが無いと棒立ち）
--     weak       ⚠ 向いていない（★禁止ではない。点を下げるだけ）

local Roles = {}

--- 役割の種類。⚠ 貢献の種類（`Types.Contribution`）とは別物です。
--   ★役割は「その人が何者か」、貢献は「この番に何をするか」。
Roles.ROLE = {
  ATTACKER = "attacker",     -- 主火力
  HEALER   = "healer",       -- 回復
  SUPPORT  = "support",      -- 補助（杖・道具）
  DEFENDER = "defender",     -- 守る・耐える
}

----------------------------------------------------------------------
-- ★ できることから役割を組み立てる
----------------------------------------------------------------------

--- `caps` の形（★呼ぶ側が実測して渡す）:
--
--     can_heal        回復呪文を唱えられるか
--     can_attack_spell 攻撃呪文を唱えられるか
--     can_use_item    戦闘で使える道具を持っているか
--     mp              いまのMP
--     max_mp          最大MP（⚠ 0 なら「呪文を覚えない人」）
--     attack          攻撃力
--     role_weight     主力度（★戦況分析と同じ値）
--
-- ⚠⚠ **分からない項目は nil のまま渡すこと。** ★0 を入れない。
function Roles.profile(caps)
  caps = caps or {}
  local p = { primary = {}, secondary = {}, fallback = {}, weak = {},
              action_preferences = {} }

  local max_mp = tonumber(caps.max_mp)
  local weight = tonumber(caps.role_weight) or 0.5

  -- ★★ 呪文を覚えない人は主火力（⚠ 名前ではなく MP で決める）
  if max_mp ~= nil and max_mp <= 0 then
    p.primary[#p.primary + 1] = Roles.ROLE.ATTACKER
    -- ⚠ 回復できないので、回復は weak（★禁止ではない。道具はある）
    p.weak[#p.weak + 1] = Roles.ROLE.HEALER
  elseif caps.can_heal == true then
    -- ★回復できる人。⚠ ただし**主力度が高ければ攻撃も primary**
    p.primary[#p.primary + 1] = Roles.ROLE.HEALER
    if weight >= 0.9 then
      p.primary[#p.primary + 1] = Roles.ROLE.ATTACKER
    else
      p.secondary[#p.secondary + 1] = Roles.ROLE.ATTACKER
    end
  else
    -- ⚠ 回復できないが呪文は使える（★攻撃呪文だけ覚えている段階）
    p.primary[#p.primary + 1] = Roles.ROLE.ATTACKER
    p.secondary[#p.secondary + 1] = Roles.ROLE.SUPPORT
  end

  if caps.can_use_item == true then
    p.secondary[#p.secondary + 1] = Roles.ROLE.SUPPORT
  end

  -- ★★ **fallback が無いと棒立ちになります**（指示書 Phase 6 の
  --   「サマルが常に回復するのではなく、不要時は攻撃や防御を選べる」）。
  p.fallback[#p.fallback + 1] = Roles.ROLE.ATTACKER
  p.fallback[#p.fallback + 1] = Roles.ROLE.DEFENDER

  -- ⚠ 主力度が低い人は「守る」に向いている（★亀の子で効く）
  if weight < 0.8 then
    p.secondary[#p.secondary + 1] = Roles.ROLE.DEFENDER
  else
    -- ⚠⚠ **主力が守ると、誰も敵を削りません。**
    p.weak[#p.weak + 1] = Roles.ROLE.DEFENDER
  end

  return p
end

--- その役割を持っているか（★どの段かも返す）。
function Roles.has(profile, role)
  for _, key in ipairs({ "primary", "secondary", "fallback" }) do
    for _, got in ipairs(profile[key] or {}) do
      if got == role then return true, key end
    end
  end
  for _, got in ipairs(profile.weak or {}) do
    if got == role then return false, "weak" end
  end
  return false, nil
end

--- 段ごとの重み。⚠ weak も 0 にしない（★「絶対にしない」ではない）。
local TIER = { primary = 1.0, secondary = 0.7, fallback = 0.4, weak = 0.15 }

local function tier_of(profile, role)
  local _ok, key = Roles.has(profile, role)
  return TIER[key or "weak"] or 0.15
end

----------------------------------------------------------------------
-- ★★ 貢献の候補を出す（指示書 §11）
----------------------------------------------------------------------

--- 候補を1つ作る小道具。
local function candidate(types, actor, action, kind, score, why, extra)
  local c = types.actor_contribution({
    actor_id = actor, action = action, contribution_type = kind,
    contribution_score = score,
  })
  c:why(why)
  for k, v in pairs(extra or {}) do c[k] = v end
  return c
end

--- この番の貢献候補（★上位 `limit` 件だけ返す / 既定 3）。
--
-- `ctx` の形:
--     actor        名前
--     caps         `Roles.profile` と同じもの
--     profile      `Roles.profile()` の結果
--     hurt_ally    いちばん減っている味方（無ければ nil）
--     directive    `BattleDirective`（★戦術の指示 / 無くてもよい）
--     assessment   `BattleAssessment`（★無くてもよい）
--
-- ⚠⚠ **総当たりをしません**（指示書 §21）。★役割ごとに1〜2件だけ作り、
--   点数で並べて上位を返します。
function Roles.contributions(types, ctx, limit)
  ctx = ctx or {}
  local T = types
  local profile = ctx.profile or Roles.profile(ctx.caps)
  local caps = ctx.caps or {}
  local actor = ctx.actor
  local d = ctx.directive
  local plan = d and d.primary_plan or nil
  local got = {}

  -- ★守る相手に指名されているか（⚠ 指示は名前ひとつで表さない / §21）
  local protecting = (d ~= nil and d.protects ~= nil and ctx.hurt_ally ~= nil
                      and d:protects(ctx.hurt_ally.name)) or false

  ------------------------------------------------------------------
  -- 1. 回復
  ------------------------------------------------------------------
  if caps.can_heal == true and ctx.hurt_ally ~= nil then
    local ally = ctx.hurt_ally
    local missing = nil
    if ally.hp ~= nil and ally.max_hp ~= nil and ally.max_hp > 0 then
      missing = 1.0 - (ally.hp / ally.max_hp)
    end
    -- ⚠ 減り具合が分からないなら点も出さない（★0 にしない）
    local score = missing and (missing * 2.0 * tier_of(profile,
      Roles.ROLE.HEALER)) or nil
    -- ★★ 守る相手に指名されていれば強く効く（Phase 5 の指示を受ける）
    if score ~= nil and protecting then score = score + 1.0 end
    -- ⚠ 「回復を優先」の指示があれば上げる
    if score ~= nil and d ~= nil and d.recovery_policy == "heal_first" then
      score = score + 0.5
    end
    got[#got + 1] = candidate(T, actor, "heal", T.Contribution.HEALING,
      score, string.format("%s のHPが減っている", tostring(ally.name)),
      { target = ally.name })
  end

  ------------------------------------------------------------------
  -- 2. 攻撃
  ------------------------------------------------------------------
  do
    -- ★攻撃力そのものではなく「役割としての向き」×「火力」で点にする。
    local tier = tier_of(profile, Roles.ROLE.ATTACKER)
    local power = tonumber(caps.attack)
    -- ⚠ 火力が分からないなら点は出さない。★候補は残す（捨てない）。
    local score = power and (tier * (1.0 + power / 100.0)) or nil
    -- ⚠⚠ **亀の子では、非主力の攻撃を下げる**（指示書 §9.3）
    if score ~= nil and plan == "亀の子"
       and (tonumber(caps.role_weight) or 0.5) < 0.8 then
      score = score - 1.0
    end
    got[#got + 1] = candidate(T, actor, "attack",
      T.Contribution.DIRECT_DAMAGE, score, "通常攻撃で敵を削る")
  end

  ------------------------------------------------------------------
  -- 3. 攻撃呪文
  ------------------------------------------------------------------
  if caps.can_attack_spell == true then
    local score = 0.8 * tier_of(profile, Roles.ROLE.ATTACKER)
    -- ⚠ MPを温存する指示なら下げる（★禁止ではない）
    if d ~= nil and d.resource_policy == "preserve_mp" then
      score = score - 0.6
    end
    -- ★物理が通らないなら、呪文の価値が上がる
    if ctx.assessment ~= nil and ctx.assessment.has_tag ~= nil
       and ctx.assessment:has_tag("physical_damage_ineffective") then
      score = score + 1.5
    end
    got[#got + 1] = candidate(T, actor, "attack_spell",
      T.Contribution.AREA_DAMAGE, score, "呪文でまとめて削る")
  end

  ------------------------------------------------------------------
  -- 4. 道具（★MPを使わずに同じ効果 / 指示書 §12）
  ------------------------------------------------------------------
  if caps.can_use_item == true then
    local score = 0.7 * tier_of(profile, Roles.ROLE.SUPPORT)
    -- ★MP温存の指示があるときこそ道具の出番
    if d ~= nil and d.resource_policy == "preserve_mp" then
      score = score + 0.8
    end
    got[#got + 1] = candidate(T, actor, "item",
      T.Contribution.ITEM_SUBSTITUTION, score, "MPを使わずに同じ効果を出す")
  end

  ------------------------------------------------------------------
  -- 5. ★★ 防御（指示書 Phase 6「亀の子作戦で非主力が防御できる」）
  ------------------------------------------------------------------
  do
    local tier = tier_of(profile, Roles.ROLE.DEFENDER)
    local score = 0.3 * tier
    -- ★★ 亀の子では、非主力の守りが**主役**になります。
    if plan == "亀の子" then score = score + 1.6 end
    -- ⚠ 劣勢でも守りの価値が上がる
    if ctx.assessment ~= nil
       and ctx.assessment.balance == T.Balance.DISADVANTAGE then
      score = score + 0.4
    end
    got[#got + 1] = candidate(T, actor, "defend",
      T.Contribution.DEFENSIVE_WAIT, score, "身を守って回復コストを減らす")
  end

  return T.top_contributions(got, limit or 3)
end

return Roles
