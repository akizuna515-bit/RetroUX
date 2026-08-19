--- 戦術を自動で選ぶ（2026-08-06 / 戦闘AI再設計 Phase 5）。
--
-- 指示書 §9:
--   > 戦術は「戦況タグと大目的への適合度」を返すものとして実装する。
--   > ★**ユーザーが全組み合わせを手動で紐づける方式にはしない。**
--
-- ★★ **ここは RAM もメニューも知りません。** ★★
--   見立て（`BattleAssessment`）と大目的（`MissionProfile`）を受け取り、
--   一番よく合う戦術を返すだけです。
--
-- ## 戦術ごとのかたち（指示書 §18 Phase 5）
--
--     score(assessment, mission) -> 適合度（数値）
--     build_directive(types, assessment, mission) -> BattleDirective
--
-- ⚠⚠ **点数は「その戦況にどれだけ合うか」**であって、強さではありません。
--
-- ## ⚠ 実装できていないもの（★それらしく作らない）
--
--   `亀の子` は**防御が未実装**なので、指示が出ても
--   ★いまは「非主力は攻撃を控える」までしか効きません。
--   `呪文攻勢` も、道具への切り替えは Phase 3（済）ですが
--   ⚠ マヌーサの検出は**味方の状態ビット頼み**です。

local Selector = {}

--- ★戦術の一覧。⚠ 名前だけで分岐しないこと（§21）。
Selector.PLANS = {}

--- 1つ足す。
local function plan(id, label, score, build)
  Selector.PLANS[#Selector.PLANS + 1] = {
    id = id, label = label, score = score, build = build,
  }
end

--- 味方の中でいちばん危ない人（★保護価値が高い順）。
local function most_at_risk(assessment)
  local worst, worst_risk = nil, -1
  for name, p in pairs(assessment.protections or {}) do
    local risk = (p.death_risk or 0) * (p.loss_impact or 1)
    if risk > worst_risk then worst, worst_risk = name, risk end
  end
  return worst, worst_risk
end

--- 大目的の重み（⚠ 無ければ 0.5 を返す。★0 にしない）。
local function value(mission, key)
  if mission == nil then return 0.5 end
  local got = tonumber(mission[key])
  if got == nil then return 0.5 end
  return got
end

----------------------------------------------------------------------
-- ★★ 6つの戦術（指示書 §9）
----------------------------------------------------------------------

-- §9.1 通常速攻
plan("quick", "通常速攻", function(a, mission, T)
  local s = 0
  if a.balance == T.Balance.ADVANTAGE then s = s + 1 end
  if a.length == T.Length.SHORT then s = s + 1 end
  if a:has_tag("many_fragile_enemies") then s = s + 1 end
  -- ★★ **これは「速さ」の戦術**。時間の価値でほぼ決まります（§5）。
  --   ⚠ ここを小さくすると、レベル上げでも省資源が勝ってしまいます。
  s = s + value(mission, "time_value") * 4
  -- ⚠⚠ **回復する敵が居たら速攻できません。** 削っても戻されます。
  --   ★先に排除するのが結局いちばん速い（§9.4 へ譲る）。
  if a:has_tag("enemy_healer_present") then s = s - 2 end
  -- ⚠ 止めてくる敵が居るときも、押し切る前に崩されます。
  if a:has_tag("enemy_disable_user") then s = s - 1 end
  return s
end, function(types, a, mission)
  local d = types.battle_directive({ primary_plan = "通常速攻" })
  d:why("優勢・短期戦なので、確実に倒せる敵から数を減らす")
  -- ⚠ 過剰なMP消費を避ける（§9.1）
  d.resource_policy = "avoid_waste"
  return d
end)

-- §9.2 主力維持
plan("protect", "主力維持", function(a, mission, T)
  local _who, risk = most_at_risk(a)
  -- ★★ 危ないほど強く効く。⚠ 弱いと「MPを惜しんで主力を落とす」。
  local s = risk * 6
  if a.balance == T.Balance.DISADVANTAGE then s = s + 1 end
  s = s + value(mission, "survival_value")
  return s
end, function(types, a, mission)
  local who = most_at_risk(a)
  local d = types.battle_directive({ primary_plan = "主力維持" })
  if who ~= nil then
    d.protected_allies[#d.protected_allies + 1] = who
    d:why(string.format("%s が危ないので、まず立て直す", who))
  end
  d.recovery_policy = "heal_first"
  return d
end)

-- §9.6 省資源
plan("conserve", "省資源", function(a, mission, T)
  local s = 0
  if a.balance == T.Balance.ADVANTAGE then s = s + 1 end
  -- ★MPの価値が高い目的（ダンジョン攻略）で効く
  s = s + value(mission, "mp_value") * 3
  s = s + value(mission, "post_battle_recovery_value") * 0.5
  -- ⚠ 劣勢では温存している場合ではない
  if a.balance == T.Balance.DISADVANTAGE then s = s - 3 end
  -- ⚠⚠ **長期戦で温存すると、かえって高くつきます**（削り切れない）。
  if a.length == T.Length.LONG then s = s - 3 end
  -- ⚠⚠ **回復する敵が居たら温存できません**（★戦闘が終わらない）。
  if a:has_tag("enemy_healer_present") then s = s - 2 end
  return s
end, function(types, a, mission)
  local d = types.battle_directive({ primary_plan = "省資源" })
  d.resource_policy = "preserve_mp"
  d.prohibited_action_types[#d.prohibited_action_types + 1] = "attack_spell"
  d:why("通常攻撃と杖で足りるので、MPを宿屋まで残す")
  return d
end)

-- §9.4 脅威除去
plan("threat", "脅威除去", function(a, mission, T)
  local s = 0
  if a:has_tag("enemy_healer_present") then s = s + 4 end
  if a:has_tag("enemy_disable_user") then s = s + 3 end
  if a.balance == T.Balance.DISADVANTAGE then s = s + 1 end
  return s
end, function(types, a, mission)
  local d = types.battle_directive({ primary_plan = "脅威除去" })
  d:why("放置すると損の大きい敵から先に排除する")
  return d
end)

-- §9.3 亀の子
plan("turtle", "亀の子", function(a, mission, T)
  local s = 0
  if a:has_tag("single_strong_enemy") then s = s + 2 end
  if a.length == T.Length.LONG then s = s + 3 end
  -- ★回復コストを抑える価値が高いほど
  s = s + value(mission, "post_battle_recovery_value") * 0.5
  -- ⚠ 短期で終わるなら守る意味が無い
  if a.length == T.Length.SHORT then s = s - 3 end
  return s
end, function(types, a, mission)
  local d = types.battle_directive({ primary_plan = "亀の子" })
  d:why("単体強敵で長期戦。★主力だけ攻め、非主力は無駄撃ちを避ける")
  -- ⚠⚠ **防御は未実装**（Phase 6）。いまは「無駄撃ちを避ける」まで。
  d:note_unknown("防御が未実装のため、非主力は待機までしかできません")
  d.resource_policy = "preserve_mp"
  return d
end)

-- §9.5 呪文攻勢
plan("spellfire", "呪文攻勢", function(a, mission, T)
  local s = 0
  -- ★物理が当たらない／効かないときに効く
  if a:has_tag("physical_accuracy_reduced") then s = s + 6 end
  if a:has_tag("physical_damage_ineffective") then s = s + 5 end
  return s
end, function(types, a, mission)
  local d = types.battle_directive({ primary_plan = "呪文攻勢" })
  d:why("物理が通らないので、呪文・杖へ切り替える")
  d.resource_policy = "allow_mp"
  return d
end)

----------------------------------------------------------------------

--- いちばん合う戦術を選ぶ（指示書 §18 Phase 5）。
--
-- 戻り値: `{ id, label, score, directive, ranking }`
--   ⚠ 見立てが無ければ nil。★「分からないのに選ぶ」ことはしません。
--
-- `previous` … 前のターンの `id`（★あれば振動よけが効きます）
-- `cfg`      … `auto_input.tactics_selector`
function Selector.choose(types, assessment, mission, previous, cfg)
  if assessment == nil then return nil end
  cfg = cfg or {}

  -- ⚠⚠ **戦況が分からないなら選ばない**（§6.1 / 0 と不明を混ぜない）。
  --   ★材料が無いのに「通常速攻」と決めると、初見の敵に突っ込みます。
  if assessment.balance == types.Balance.UNKNOWN then
    return nil
  end

  local ranking = {}
  for _, p in ipairs(Selector.PLANS) do
    local s = p.score(assessment, mission, types)
    -- ★★ 振動よけ: いま採っている戦術に下駄をはかせる（§10 IT-007）
    --   ⚠ これが無いと、境界で**毎ターン往復**します。
    if previous ~= nil and p.id == previous then
      s = s + (tonumber(cfg.stickiness) or 1.0)
    end
    ranking[#ranking + 1] = { id = p.id, label = p.label, score = s,
                              plan = p }
  end
  table.sort(ranking, function(x, y)
    if x.score == y.score then return x.id < y.id end   -- ★同点は名前順
    return x.score > y.score
  end)

  local best = ranking[1]
  local directive = best.plan.build(types, assessment, mission)
  directive:why(string.format("戦術「%s」を選択（適合度 %.1f）",
    best.label, best.score))
  return {
    id = best.id, label = best.label, score = best.score,
    directive = directive, ranking = ranking,
  }
end

--- 次点との差（★説明に使う / 指示書 §17）。
function Selector.margin(choice)
  if choice == nil or #choice.ranking < 2 then return nil end
  return choice.ranking[1].score - choice.ranking[2].score
end

return Selector
