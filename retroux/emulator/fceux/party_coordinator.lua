--- 最終調整（2026-08-04 / 戦闘AI再設計 Phase 2）。
--
-- 指示書 §18 Phase 2 の `PartyCoordinator`:
--   > 予約ダメージ / 予約回復 / オーバーキル防止 / 二重回復防止
--
-- ★★ **ここは RAM もメニューも知りません。** ★★
--
-- ## ⚠⚠ 予約はターンをまたがない（指示書 §7「予約情報」）
--
--   持ち越すと、**前のターンに回復したつもりのHP**で次のターンを
--   判断します。★ターン番号が変われば中身を捨てます。
--
--   > 作戦変更後、新しい行動計画を作る前に、
--   > 前ターン・前作戦の予約情報を持ち越さない。
--
-- ## なぜ `battle_types.lua` の `PartyPlan` を包むのか
--
--   `PartyPlan` は「1ターンぶんの計画」そのものです。
--   ⚠ しかし `bridge.lua` は**ターンの切れ目を知っている**唯一の場所で、
--     `PartyPlan` に持たせると RAM を知ることになります。
--   ★そこで「いまのターンの計画を出す」だけをここが受け持ちます。

local Coordinator = {}
Coordinator.__index = Coordinator

--- 作る。`types` は `battle_types.lua`。
function Coordinator.new(types)
  return setmetatable({ types = types, turn = nil, plan = nil }, Coordinator)
end

--- いまのターンの計画。★ターンが変わったら**作り直します**。
--
-- ⚠ `turn_no` が nil のときも1つの計画として扱います
--   （ターンを数えられない環境で予約が効かなくなるより、
--   ★同じ戦闘の中で共有されるほうが安全です）。
function Coordinator:for_turn(turn_no)
  if self.plan == nil or self.turn ~= turn_no then
    self.turn = turn_no
    self.plan = self.types.party_plan({ turn = turn_no })
  end
  return self.plan
end

--- 回復を予約する。★決めた直後に呼びます。
function Coordinator:reserve_healing(turn_no, actor, amount)
  if actor == nil then return self end
  self:for_turn(turn_no):reserve_healing(actor.index, amount)
  return self
end

--- 予約の表（`actor_index -> 見込み回復量`）。
--
-- ★判断側（`actor_decision.lua`）へ渡すのはこの素の表です。
--   ⚠ 計画そのものを渡すと、判断側が予約を**書けて**しまいます。
function Coordinator:healing_reservations(turn_no)
  return self:for_turn(turn_no).reserved_healing
end

--- 予約を足したHP。
function Coordinator:hp_after_reserved(turn_no, who)
  if who == nil then return 0 end
  return self:for_turn(turn_no):hp_after_reserved_healing(
    who.index, who.hp or 0, who.max_hp)
end

--- ★戦闘が終わったら捨てる。⚠ 次の戦闘へ持ち越さない。
function Coordinator:reset()
  self.turn = nil
  self.plan = nil
  return self
end

return Coordinator
