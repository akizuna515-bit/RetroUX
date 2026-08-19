--- 作戦指示をこしらえる（2026-08-04 / 戦闘AI再設計 Phase 2）。
--
-- 指示書 §18 Phase 2 の `TacticsCommander`:
--   > 現行戦術プロフィールを BattleDirective へ変換
--   > （回復閾値 / MP温存 / 攻撃許可 / 道具使用許可 / リスク設定）
--
-- ★★ **ここは RAM もメニューも知りません。** ★★
--   設定の値を受け取り、「何をしてよいか」を組み立てるだけです。
--
-- ## ⚠⚠ Phase 2 の約束: **答えを変えない**
--
--   いまは戦術プロフィールを**そのまま写す**だけです。
--   ★戦況から作戦を自動で選ぶのは **Phase 5** です（§18）。
--   ⚠ ここで賢くすると、Phase 0 の基準と比べる意味が無くなります。

local Commander = {}

--- 人ごとの回復方針を組み立てる。
--
-- ★`bridge.lua` が `_tactic_*` で引いた値を渡します。
--   ⚠ ここでは設定の**読み方**を知りません（プロフィールの形に依存しない）。
--
--   ```
--   Commander.healing_policy({
--     self_enabled = true, ally_enabled = true,
--     self_ratio = 0.4, ally_ratio = 0.5,
--     protect_target = "lorasia", protect_ratio = 0.5,
--     emergency_ratio = 0.25, avoid_duplicate = true,
--   })
--   ```
--
-- ⚠ 足りない値は**安全側の既定**で埋めます。★設定を書き忘れた人が
--   「回復しない AI」を手にしないため（§20「現行を壊さない」）。
function Commander.healing_policy(values)
  local v = values or {}
  local function flag(name, fallback)
    if type(v[name]) == "boolean" then return v[name] end
    return fallback
  end
  local function ratio(name, fallback)
    local got = tonumber(v[name])
    -- ⚠ 0〜1 の外は使わない（％で渡された値をそのまま使うと 40 倍になる）
    if got == nil or got < 0 or got > 1 then return fallback end
    return got
  end
  return {
    self_enabled = flag("self_enabled", true),
    ally_enabled = flag("ally_enabled", true),
    self_ratio = ratio("self_ratio", 0.5),
    ally_ratio = ratio("ally_ratio", 0.5),
    -- ★「守る相手」は既定 `none`＝従来どおり（§19 受入条件13）
    protect_target = v.protect_target or "none",
    protect_ratio = ratio("protect_ratio", 0.5),
    emergency_ratio = ratio("emergency_ratio", 0.25),
    avoid_duplicate = flag("avoid_duplicate", true),
  }
end

--- 戦術プロフィールから作戦指示を作る（指示書 §10）。
--
-- ⚠⚠ **戦術を一つの名称だけで表現しない。** 戦闘中は、主戦術に加えて
--   制約や優先対象が同時に存在します。
--
--   `types`   … `battle_types.lua`
--   `profile` … `{ name = "いのちをだいじに", protect_target = "lorasia",
--                  attack_spell = {samaltria = true, ...},
--                  reserve_mp = 15, allow_items = true }`
function Commander.directive(types, profile)
  local p = profile or {}
  local d = types.battle_directive({
    primary_plan = p.name,
    resource_policy = (p.reserve_mp ~= nil and p.reserve_mp > 0)
      and "preserve_mp" or nil,
    recovery_policy = p.recovery_policy,
    risk_policy = p.risk_policy,
  })

  -- ★守る相手（「いのちをだいじに」）
  if p.protect_target ~= nil and p.protect_target ~= "none" then
    d.protected_allies[#d.protected_allies + 1] = p.protect_target
    d:why(string.format("%s を守る", tostring(p.protect_target)))
  end

  -- ★攻撃呪文を禁じるか（「ガンガン行こうぜ」が全員 OFF なら）
  local anyone_attacks = false
  for _, on in pairs(p.attack_spell or {}) do
    if on == true then anyone_attacks = true end
  end
  if not anyone_attacks then
    d.prohibited_action_types[#d.prohibited_action_types + 1] = "attack_spell"
    d:why("攻撃呪文は誰も使わない設定")
  end

  -- ★道具を禁じるか
  if p.allow_items == false then
    d.prohibited_action_types[#d.prohibited_action_types + 1] = "item"
    d:why("道具を使わない設定")
  end

  if p.reserve_mp ~= nil and p.reserve_mp > 0 then
    d:why(string.format("MPを %d 残す", p.reserve_mp))
  end
  return d
end

return Commander
