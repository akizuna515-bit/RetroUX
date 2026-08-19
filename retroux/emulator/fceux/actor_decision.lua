--- 個人の判断（2026-08-04 / 戦闘AI再設計 Phase 2）。
--
-- 指示書 §18 Phase 2 の `ActorDecisionEngine`:
--   > 現行のキャラクター別判断を移設（回復候補・攻撃候補・呪文候補・
--   > 道具候補・防御候補）
--
-- ★★ **ここは RAM もメニューも知りません。** ★★
--   渡された数字を見て「誰を回復すべきか」を返すだけです。
--   ⚠ 知ってしまうと、判断を1つ試すのに実機が要ります。
--
-- ## ⚠⚠ Phase 2 の約束: **答えを変えない**
--
--   ここは `bridge.lua` の `_plan_battle_heal` から**そのまま切り出した**
--   ものです。★同じ入力に同じ答えを返します
--   （`battle_ai_baseline_test.lua` の 14 項目が見張っています）。
--
--   新しい判断（脅威度・推計ターン）は **Phase 4 以降**です。
--   ⚠ ここで賢くすると、Phase 0 の基準と比べる意味が無くなります。

local Decision = {}

--- 回復の方針。★`bridge.lua` が設定から組み立てて渡します。
--
--   ```
--   {
--     self_enabled = true,      -- 自分を回復するか
--     ally_enabled = true,      -- 仲間を回復するか
--     self_ratio = 0.4,         -- 自分の回復開始HP（割合）
--     ally_ratio = 0.5,         -- 仲間の回復開始HP（割合）
--     protect_target = "lorasia",   -- ★守る相手（nil / "none" なら従来）
--     protect_ratio = 0.5,
--     emergency_ratio = 0.25,
--     avoid_duplicate = true,       -- 予約を見るか
--   }
--   ```

--- 予約を足したHP。⚠ 予約が無ければ現在HPそのもの。
--
-- ★`reserved` は `actor_index -> 見込み回復量` の表です。
--   nil を渡せば「予約を見ない」＝素のHPで判断します。
local function hp_with_reserved(who, reserved)
  local hp = who.hp or 0
  if reserved == nil then return hp end
  local extra = reserved[who.index]
  if extra == nil then return hp end
  local got = hp + extra
  -- ⚠ 最大HPを超えて数えない（超えると「もう十分」と誤判定する）
  if who.max_hp ~= nil and got > who.max_hp then got = who.max_hp end
  return got
end

--- その人にどれだけ足りないか。⚠ 足りていれば nil。
local function missing_for(who, ratio, reserved)
  if who == nil or not who.alive or (who.max_hp or 0) <= 0 then return nil end
  local missing = who.max_hp * ratio - hp_with_reserved(who, reserved)
  if missing > 0 then return missing end
  return nil
end

--- ★★「いのちをだいじに」の判断順（指示書 §10）★★
--
--   1. 自分のHP <= 緊急自己回復  -> **自分**
--   2. 守る相手 <= 保護しきい値  -> **その人**
--   3. 自分のHP <= 自分の回復開始 -> **自分**
--   4. どれでもなければ nil（★従来の探し方へ落ちる）
--
-- ★この順にする理由（§10 末尾）:
--   **回復役自身が瀕死のままローレシアだけを回復して共倒れになる**のを防ぐ。
--
-- 戻り値: `対象, 不足HP, 理由` / 当てはまらなければ `nil`
function Decision.protect_target(party, me, policy, reserved)
  local want = policy.protect_target
  if want == nil or want == "none" then return nil end

  -- ⚠ 「二重回復を避ける」が OFF なら予約を見ない（従来の挙動）
  local seen = policy.avoid_duplicate and reserved or nil

  local protectee = nil
  for _, other in ipairs(party or {}) do
    if other.name == want then protectee = other end
  end

  -- 1. 自分が緊急（★守る相手より先）
  if policy.self_enabled and me ~= nil then
    local ratio = policy.emergency_ratio or 0.25
    local missing = missing_for(me, ratio, seen)
    if missing ~= nil then
      return me, missing, string.format(
        "自分のHPが緊急しきい値(%d%%)以下なので、自分を先に回復",
        math.floor(ratio * 100 + 0.5))
    end
  end

  -- 2. 守る相手
  -- ⚠ 居なければ何もしない（§15「保護対象が戦闘メンバーにいない場合は
  --   安全に通常戦術へフォールバック」）。★ムーンが仲間になる前など。
  local is_self = (me ~= nil and protectee ~= nil
                   and me.index == protectee.index)
  local allowed = is_self and policy.self_enabled
    or ((not is_self) and policy.ally_enabled)
  if allowed and protectee ~= nil then
    local ratio = policy.protect_ratio or 0.5
    local missing = missing_for(protectee, ratio, seen)
    if missing ~= nil then
      return protectee, missing, string.format(
        "守る相手（%s）のHPが %d%% 以下なので回復",
        tostring(protectee.name), math.floor(ratio * 100 + 0.5))
    end
  end

  -- 3. 自分が通常の回復開始HP以下
  if policy.self_enabled and me ~= nil then
    local missing = missing_for(me, policy.self_ratio, seen)
    if missing ~= nil then
      return me, missing, string.format(
        "守る相手は無事だが、自分のHPが %d%% 以下なので自己回復",
        math.floor(policy.self_ratio * 100 + 0.5))
    end
  end

  return nil
end

--- 誰を回復するか（★現行 `_plan_battle_heal` の探し方をそのまま）。
--
-- ★まず「いのちをだいじに」の判断順を試し、当てはまらなければ
--   **最も減っている人**を選びます（＝これまでの挙動）。
--
-- 戻り値: `対象, 不足HP, 理由`（理由は「いのちをだいじに」のときだけ）
function Decision.heal_target(party, me, policy, reserved)
  local worst, worst_missing, worst_why =
    Decision.protect_target(party, me, policy, reserved)
  if worst ~= nil then return worst, worst_missing, worst_why end

  -- ⚠ ここから下は**従来どおり**。★答えを変えないこと。
  local seen = policy.avoid_duplicate and reserved or nil
  worst_missing = 0
  for _, other in ipairs(party or {}) do
    if other.alive and (other.max_hp or 0) > 0 then
      local is_self = (other.index == me.index)
      local allowed = is_self and policy.self_enabled
        or ((not is_self) and policy.ally_enabled)
      local ratio = is_self and policy.self_ratio or policy.ally_ratio
      if allowed then
        local missing = other.max_hp * ratio - hp_with_reserved(other, seen)
        if missing > 0 and missing > worst_missing then
          worst, worst_missing = other, missing
        end
      end
    end
  end
  return worst, worst_missing, nil
end

--- 自己回復で道具へ譲るか（指示書 §9.1）。
--
--     自己回復: ちからのたて ＞ 回復呪文 ＞ やくそう
--
-- ★ちからのたては**自己回復専用**で、MPを使わず何度でも使えます。
--   ⚠ ただし行動の優先順は `heal -> attack -> item -> target` で
--     **呪文のほうが道具より先**に主張するため、「譲る」形にしています。
--
-- ⚠⚠ 譲るのは**自分を回復するときだけ**。他者回復では譲りません
--   （ちからのたては本人しか回復できない / §9.2・§16）。
function Decision.should_yield_to_item(target, me, has_self_heal_item)
  if target == nil or me == nil then return false end
  if target.index ~= me.index then return false end
  return has_self_heal_item == true
end

return Decision
