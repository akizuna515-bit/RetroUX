--- 戦闘AIの受け皿（2026-08-04 / 戦闘AI再設計 Phase 1）。
--
-- 指示書: `input/RetroUX 戦闘AI再設計・段階的リファクタリング指示書.docx`
--   > Phase 1: 新しい三層構造の受け皿を作る。
--   > この段階では、既存AI結果を新構造へ格納するだけでもよい。
--
-- ★★ **ここは RAM もメニューも知りません。** ★★
--   数字を入れて数字を返すだけです。⚠ 知ってしまうと、
--   判断を1つ試すのに実機が要ります
--   （`damage_estimate.lua` / `attack_plan.lua` と同じ流儀）。
--
-- ## Lua 5.1 での作り方
--
--   ⚠ dataclass も enum もありません。**テーブルで代用**します。
--   ★ただし「知らない値を黙って通す」ことだけは避けます。
--     `parse` は知らない値に **nil** を返し、呼ぶ側が既定を決めます。
--
-- ## ⚠⚠ 0 と「分からない」を混ぜない
--
--   このプロジェクトの原則です。推計ターンが**出せない**ときに 0 を返すと、
--   「0ターンで倒せる」＝**最高の戦況**として扱われます。
--   ★出せないときは `nil` を入れ、`unknown` に理由を積みます。

local Types = {}

----------------------------------------------------------------------
-- 列挙（指示書 Phase 1）
----------------------------------------------------------------------

--- 戦況（優勢 / 均衡 / 劣勢）。
--
-- ⚠⚠ **`UNKNOWN` を必ず持つこと。** ★「まだ分からない」を `EVEN`
--   （均衡）に混ぜると、材料が揃っていないのに「互角だから攻める」
--   という判断が通ってしまいます。
Types.Balance = {
  ADVANTAGE = "advantage",
  EVEN = "even",
  DISADVANTAGE = "disadvantage",
  UNKNOWN = "unknown",
}

--- 戦闘の長さ（短期 / 中期 / 長期）。
Types.Length = {
  SHORT = "short",
  MEDIUM = "medium",
  LONG = "long",
  UNKNOWN = "unknown",
}

--- 大目的（指示書 §4）。★ユーザーが画面で選ぶもの。
Types.Mission = {
  GRINDING = "grinding",         -- レベル上げ・稼ぎ
  DUNGEON = "dungeon",           -- ダンジョン攻略
  BOSS_MANUAL = "boss_manual",   -- ボス戦・手動主体
}

--- 不確実戦術の許容度（指示書 §16）。
--
-- ⚠ 名前は「状態異常使用度」ではありません。★成功率100%の即死・停止は
--   **不確実ではない**ので、`DISABLED` でも通常評価します。
Types.Risk = {
  DISABLED = "disabled",
  CAUTIOUS = "cautious",
  NORMAL = "normal",
  BOLD = "bold",
}

--- 貢献の種類（指示書 §11）。
Types.Contribution = {
  DIRECT_DAMAGE = "direct_damage",
  FINISHING_DAMAGE = "finishing_damage",
  AREA_DAMAGE = "area_damage",
  HEALING = "healing",
  SELF_HEALING = "self_healing",
  DAMAGE_PREVENTION = "damage_prevention",
  ENEMY_DISABLE = "enemy_disable",
  INSTANT_REMOVAL = "instant_removal",
  ENEMY_DEBUFF = "enemy_debuff",
  ALLY_BUFF = "ally_buff",
  RESOURCE_SAVING = "resource_saving",
  DEFENSIVE_WAIT = "defensive_wait",
  ITEM_SUBSTITUTION = "item_substitution",
}

--- どの層が使う判断エンジンか（Phase 1 完了条件「切り替えフラグ」）。
--
-- ★★ **既定は `LEGACY`。** ★★ 触らなければ**これまでと同じ**です。
Types.Engine = {
  LEGACY = "legacy",     -- 現行の bridge.lua の判断
  LAYERED = "layered",   -- 三層構造（Phase 2 以降）
}

--- 知っている値か確かめる。⚠ **知らない値には nil を返す**。
--
-- ★「知らない値を既定へ丸める」ことはしません。設定の打ち間違いが
--   黙って別の意味になるのを避けるためです（呼ぶ側が既定を決める）。
function Types.parse(enum, value)
  if value == nil then return nil end
  local want = tostring(value)
  for _, known in pairs(enum) do
    if known == want then return known end
  end
  return nil
end

--- 知っている値を並べる（設定の警告文に使う）。
function Types.names(enum)
  local out = {}
  for _, known in pairs(enum) do out[#out + 1] = known end
  table.sort(out)
  return out
end

----------------------------------------------------------------------
-- 共通の作り
----------------------------------------------------------------------

--- 理由を積む（指示書 §17「全層で理由を残す」）。
--
-- ★どの構造にも `reasons` を持たせ、**作った側が必ず書く**。
--   ⚠ 理由の無い判断は、あとから直しようがありません。
local function with_reasons(object)
  object.reasons = object.reasons or {}
  function object:why(text)
    if text ~= nil and text ~= "" then
      self.reasons[#self.reasons + 1] = tostring(text)
    end
    return self
  end
  --- ⚠ 「分からない」を積む。★0 と混ぜないための置き場。
  object.unknown = object.unknown or {}
  function object:note_unknown(text)
    if text ~= nil and text ~= "" then
      self.unknown[#self.unknown + 1] = tostring(text)
    end
    return self
  end
  function object:is_certain()
    return #self.unknown == 0
  end
  return object
end

----------------------------------------------------------------------
-- 第1層: 戦況分析（指示書 §6）
----------------------------------------------------------------------

--- 敵1体の脅威（指示書 §7）。
--
-- ★★ **1つの数値にまとめない。** ★★
--   「脅威度 8」では、なぜ優先するのかが説明できません。
--   ⚠ 火力が高いのか、回復するのか、即死を使うのかで**打つ手が違います**。
function Types.threat_vector(fields)
  local t = with_reasons(fields or {})
  -- ⚠ 分からないものは nil のまま（0 にしない）
  t.direct_damage = t.direct_damage
  t.area_damage = t.area_damage
  t.healing = t.healing
  t.buff = t.buff
  t.debuff = t.debuff
  t.disable = t.disable
  t.instant_death = t.instant_death
  t.reinforcement = t.reinforcement
  t.durability = t.durability
  t.action_speed = t.action_speed
  return t
end

--- 味方1人の保護価値（指示書 §8）。
function Types.protection_value(fields)
  local p = with_reasons(fields or {})
  p.actor_id = p.actor_id
  -- ★その人を失ったときの戦力低下（分からなければ nil）
  p.loss_impact = p.loss_impact
  -- ★次の敵行動までに倒される可能性
  p.death_risk = p.death_risk
  return p
end

--- 戦況（指示書 §6）。
--
-- ⚠⚠ `balance` の既定は `UNKNOWN` です。★材料が無いのに
--   「均衡」と言わないため（0 と不明を混ぜない）。
function Types.battle_assessment(fields)
  local a = with_reasons(fields or {})
  a.balance = Types.parse(Types.Balance, a.balance) or Types.Balance.UNKNOWN
  a.length = Types.parse(Types.Length, a.length) or Types.Length.UNKNOWN
  -- ★推計ターン。⚠ 出せないときは nil（0 にしない）
  a.enemy_defeat_turns = a.enemy_defeat_turns
  a.party_collapse_turns = a.party_collapse_turns
  a.threats = a.threats or {}            -- 敵ID -> ThreatVector
  a.protections = a.protections or {}    -- 味方ID -> ProtectionValue
  a.tags = a.tags or {}                  -- 戦況タグ（§6.4）
  -- ★AUTO を続けてよいか（§6 の出力の1つ）。⚠ 既定は「分からない」
  a.auto_continue = a.auto_continue

  --- 戦況タグを足す。⚠ 同じタグを2度入れない。
  function a:tag(name, why)
    if name == nil then return self end
    for _, had in ipairs(self.tags) do
      if had == name then return self end
    end
    self.tags[#self.tags + 1] = name
    if why then self:why(string.format("%s: %s", name, why)) end
    return self
  end

  function a:has_tag(name)
    for _, had in ipairs(self.tags) do
      if had == name then return true end
    end
    return false
  end
  return a
end

----------------------------------------------------------------------
-- ユーザーの大目的（指示書 §5）
----------------------------------------------------------------------

--- 大目的。★**戦術を直接固定しません**（§5）。
--
--   誤: レベル上げ -> 常に速攻
--   正: レベル上げ -> 時間の価値が高く、MP の価値が低い
--
-- ⚠ 同じ「レベル上げ」でも、明らかな劣勢なら防御・回復・AUTO解除を
--   選べること。★ここは**価値基準**であって命令ではありません。
function Types.mission_profile(fields)
  local m = with_reasons(fields or {})
  m.mission = Types.parse(Types.Mission, m.mission) or Types.Mission.DUNGEON
  m.risk = Types.parse(Types.Risk, m.risk) or Types.Risk.NORMAL
  -- ★価値の重み。⚠ 係数はコードに書かず設定から渡す（指示書 §20）
  m.time_value = m.time_value
  m.survival_value = m.survival_value
  m.mp_value = m.mp_value
  m.item_value = m.item_value
  m.post_battle_recovery_value = m.post_battle_recovery_value
  m.wipe_cost = m.wipe_cost
  m.uncertainty_tolerance = m.uncertainty_tolerance
  m.risk_tolerance = m.risk_tolerance
  -- ★ボス目的は AUTO を既定 OFF にできる（§18 Phase 3 完了条件）
  m.auto_enabled = m.auto_enabled
  return m
end

----------------------------------------------------------------------
-- 第2層: 作戦指示（指示書 §10）
----------------------------------------------------------------------

--- 作戦指示。
--
-- ★★ **戦術を一つの名称だけで表現しない**（§10）。 ★★
--   戦闘中は、主戦術に加えて制約や優先対象が同時に存在します。
--   ⚠ 「亀の子」とだけ持つと、誰を守るのかが失われます。
function Types.battle_directive(fields)
  local d = with_reasons(fields or {})
  d.primary_plan = d.primary_plan
  d.secondary_plan = d.secondary_plan
  d.priority_targets = d.priority_targets or {}
  d.protected_allies = d.protected_allies or {}
  d.prohibited_targets = d.prohibited_targets or {}
  d.required_contributions = d.required_contributions or {}
  d.resource_policy = d.resource_policy
  d.recovery_policy = d.recovery_policy
  d.risk_policy = d.risk_policy
  d.allowed_action_types = d.allowed_action_types or {}
  d.prohibited_action_types = d.prohibited_action_types or {}
  d.auto_continue = d.auto_continue

  --- その敵を狙ってよいか（★停止させた敵を殴らないため / §15.4）。
  function d:may_target(enemy_id)
    for _, banned in ipairs(self.prohibited_targets) do
      if banned == enemy_id then return false end
    end
    return true
  end

  --- その行動が許されているか。
  --
  -- ⚠ `allowed_action_types` が空なら**すべて許可**です。
  --   ★「空 = 何も許さない」にすると、指示を書き忘れた瞬間に
  --     全員が何もしなくなります（安全側は「これまでどおり動く」）。
  function d:may_act(kind)
    for _, banned in ipairs(self.prohibited_action_types) do
      if banned == kind then return false end
    end
    if #self.allowed_action_types == 0 then return true end
    for _, allowed in ipairs(self.allowed_action_types) do
      if allowed == kind then return true end
    end
    return false
  end

  function d:protects(actor_id)
    for _, who in ipairs(self.protected_allies) do
      if who == actor_id then return true end
    end
    return false
  end
  return d
end

----------------------------------------------------------------------
-- 第3層: 個人の貢献（指示書 §11）
----------------------------------------------------------------------

--- 個人が「作戦へどう貢献できるか」の候補1つ。
--
-- ⚠ 具体的なコマンドではありません。★コマンドへの変換は最後に行います
--   （指示書 §3 の「DQ2の具体的コマンドへ変換」）。
function Types.actor_contribution(fields)
  local c = with_reasons(fields or {})
  c.actor_id = c.actor_id
  c.action = c.action
  c.target = c.target
  c.contribution_type = Types.parse(Types.Contribution, c.contribution_type)
  -- ★点数。⚠ 出せないときは nil（0 は「価値が無い」という意味になる）
  c.contribution_score = c.contribution_score
  c.expected_effect = c.expected_effect
  c.expected_cost = c.expected_cost
  c.risk = c.risk
  c.confidence = c.confidence
  return c
end

--- 候補を点数順に並べ、上位だけ残す（指示書 §11「上位3候補程度」）。
--
-- ⚠⚠ **全組み合わせの総当たりをしない**（指示書 §21）。
--
-- ★点数が nil のものは**最後に回します**（捨てません）。
--   捨てると「見積もれない手は絶対に選ばれない」ことになり、
--   ⚠ 未知の敵に対して何もできなくなります。
function Types.top_contributions(candidates, limit)
  local out = {}
  for _, c in ipairs(candidates or {}) do
    if type(c) == "table" then out[#out + 1] = c end
  end
  table.sort(out, function(a, b)
    local sa, sb = a.contribution_score, b.contribution_score
    if sa == nil and sb == nil then return false end
    if sa == nil then return false end          -- ★nil は後ろへ
    if sb == nil then return true end
    return sa > sb
  end)
  local n = limit or 3
  while #out > n do table.remove(out) end
  return out
end

----------------------------------------------------------------------
-- 最終調整（指示書 §3「最終調整」）
----------------------------------------------------------------------

--- パーティ全体の計画。★予約はここが持ちます。
--
-- ⚠⚠ **予約はターンをまたがない**（指示書 §7「予約情報」）。
--   持ち越すと、前のターンに倒したつもりの敵で今のターンを判断します。
function Types.party_plan(fields)
  local p = with_reasons(fields or {})
  p.turn = p.turn
  p.actions = p.actions or {}              -- actor_id -> ActorContribution
  p.reserved_damage = p.reserved_damage or {}    -- enemy_id -> 見込みダメージ
  p.reserved_healing = p.reserved_healing or {}  -- actor_id -> 見込み回復量
  p.reserved_removals = p.reserved_removals or {} -- enemy_id -> true（即死・確殺）
  p.disabled_targets = p.disabled_targets or {}   -- enemy_id -> 残り停止ターン

  local function add(table_, key, amount)
    if key == nil or amount == nil or amount <= 0 then return end
    table_[key] = (table_[key] or 0) + amount
  end

  function p:reserve_damage(enemy_id, amount) add(self.reserved_damage, enemy_id, amount); return self end
  function p:reserve_healing(actor_id, amount) add(self.reserved_healing, actor_id, amount); return self end

  --- ★その敵はもう倒れる予定か（オーバーキル回避 / 二重の即死回避）。
  function p:is_removed(enemy_id)
    return self.reserved_removals[enemy_id] == true
  end

  function p:reserve_removal(enemy_id, why)
    if enemy_id == nil then return self end
    self.reserved_removals[enemy_id] = true
    if why then self:why(string.format("removal %s: %s", tostring(enemy_id), why)) end
    return self
  end

  --- ★眠っている敵か（不必要に攻撃しないため / §15.4）。
  function p:is_disabled(enemy_id)
    return (self.disabled_targets[enemy_id] or 0) > 0
  end

  --- 予約を差し引いた見込み。⚠ `nil` はそのまま `nil`（0 にしない）。
  function p:hp_after_reserved_damage(enemy_id, hp)
    if hp == nil then return nil end
    return hp - (self.reserved_damage[enemy_id] or 0)
  end

  function p:hp_after_reserved_healing(actor_id, hp, max_hp)
    if hp == nil then return nil end
    local got = hp + (self.reserved_healing[actor_id] or 0)
    if max_hp ~= nil and got > max_hp then got = max_hp end
    return got
  end
  return p
end

return Types
