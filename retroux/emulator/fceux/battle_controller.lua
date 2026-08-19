-- AUTO の担当（2026-08-01 のリファクタ指示書 §4.2）。
--
-- ★★ **この人が持つのは「誰が操作するか」だけ。** ★★
--
--   | 状態 | 所有 |
--   | --- | --- |
--   | `auto_enabled`（AUTO の入り切り） | **ここ** |
--   | `force_auto`（この戦闘だけ安全停止を外す） | **ここ** |
--   | `manual_latched`（この戦闘は手動のまま） | **ここ** |
--
-- ⚠⚠ **速度を変えてはならない。** 速度は `speed_controller.lua` の持ち物。
--   2026-07-31 に「A キーが速度も変えていた」問題を直したばかりなので、
--   ここから速度を触ると**同じ穴に戻る**。
--
-- ★安全停止の理由（危険・初遭遇・ボス・警戒）は `context` で受け取る。
--   ⚠ 自分でゲームを覗かない。覗くとゲームの内部構造を知ることになる。

local BattleController = {}
BattleController.__index = BattleController

--- @param config table `config.auto_input`
--- @param logger function|nil `logger(message, notice)` の形
function BattleController.new(config, logger)
  local self = setmetatable({}, BattleController)
  self.config = config or {}
  self.auto = self.config.auto_input or {}
  self._log = logger

  -- ★AUTO（AIに操作を任せるか）。**速度とは別の軸**（指示書 §2）。
  --   既定は config の `auto_input.enabled`。実行中はここが正になる。
  self.auto_enabled = self.auto.enabled ~= false
  -- command.json で最後に見た値（立ち上がり判定 / `apply_command` 参照）
  self.auto_commanded = nil

  -- 強制AUTO（消化試合用）。★**その戦闘の間だけ**（戦闘終了で解除）。
  -- ⚠ これは「AUTO の3つ目のモード」ではない。利用者に見せる概念は
  --   AUTO と 高速化 の2つだけ（指示書 §4）。理由の欄に出すにとどめる。
  self.force_auto = false

  -- 一度手動へ落ちたら、その戦闘の間は手動のまま。
  -- ⚠ 危険状態はHPが戻ると解除されるため、ホイミで回復した瞬間に
  --   自動戦闘が復活し、変えた作戦を無視して同じ敵を殴りに戻っていた。
  self.manual_latched = false
  return self
end

-- ★段階（レベル）を素通しする（2026-08-13 / Phase 2）。
--   ⚠ 省略時は INFO。既存の呼び出しは直さなくてよい。
function BattleController:log(message, notice, level)
  if self._log ~= nil then self._log(message, notice, level) end
end


-- --- AUTO の入り切り -------------------------------------------------

--- AUTO を切り替える。**唯一の入口**。
--- @return boolean 実際に変わったか
function BattleController:set_auto(on, why)
  on = (on == true)
  if self.auto_enabled == on then return false end
  self.auto_enabled = on
  self:log(string.format("AUTO を%sにしました（%s）",
    on and "入" or "切", tostring(why)),
    "auto " .. (on and "on" or "off"), "DEBUG")
  return true
end

function BattleController:is_auto_enabled()
  return self.auto_enabled == true
end

function BattleController:is_manual_latched()
  return self.manual_latched == true
end

--- command.json から来た値を適用する（立ち上がり判定 / speed と同じ理由）。
function BattleController:apply_command(want, why)
  if want == nil then return false end
  want = (want == true)
  if want == self.auto_commanded then return false end
  self.auto_commanded = want
  local changed = self:set_auto(want, why or "画面のボタン")
  -- ⚠ 画面から切ったときは強制AUTO も解除する。
  --   残すと「AUTO を切ったのに安全機構だけ潰れている」状態になる。
  if not want then self:set_force_auto(false) end
  return changed
end

-- --- 強制AUTO（この戦闘だけ安全停止を外す）---------------------------

function BattleController:set_force_auto(on, notify)
  on = (on == true)
  if self.force_auto == on then return false end
  self.force_auto = on
  if on then
    local boss = (self.auto.force_auto_includes_boss == true)
    self:log(string.format(
      "強制AUTO を入れました（危険状態・初遭遇・警戒中・手動ラッチを無視します"
      .. " / ボス戦は%s）", boss and "含む" or "対象外"), "FORCE AUTO on", "DEBUG")
  else
    self:log("強制AUTO を解除しました（通常の安全判定に戻ります）",
             "FORCE AUTO off", "DEBUG")
  end
  if notify ~= nil then notify(on) end
  return true
end

--- 強制AUTO がいま効くか。★ボス戦は既定で対象外。
function BattleController:force_auto_active(is_boss)
  if not self.force_auto then return false end
  if is_boss and self.auto.force_auto_includes_boss ~= true then
    return false
  end
  return true
end

-- --- 手動ラッチ ------------------------------------------------------

function BattleController:latch_manual(reason)
  if self.manual_latched then return false end
  self.manual_latched = true
  self:log("この戦闘は手動のままにします: " .. tostring(reason),
           "manual latch", "DEBUG")
  return true
end

function BattleController:clear_latch(reason)
  if not self.manual_latched then return false end
  self.manual_latched = false
  self:log("手動ラッチを解除しました（" .. tostring(reason) .. "）",
           "manual latch cleared", "DEBUG")
  return true
end

-- --- 自動入力してよいか ----------------------------------------------

--- いま AI が入力してよいか。戻り値: `使えるか, 使えない理由`。
---
--- `context` に要るもの:
---   danger / danger_reason / first_encounter / is_boss / is_caution
---
--- ★★ 理由を返すのは、止まった原因を人に見せるため。 ★★
---   ⚠ 「この戦闘は手動のままにします」とだけ出していたが、
---     **なぜ手動になったのかが分からない**と利用者は直しようがない。
function BattleController:auto_input_allowed_now(context)
  local ctx = context or {}
  local ai = self.auto
  -- ⚠ 見るのは**実行中の値**。config の値ではない
  --   （画面や A キーで切っても効かなくなる）。
  if not self.auto_enabled then return false, "AUTO が切ってあります" end
  -- ⚠⚠ **高速化は AUTO を止める理由にしない**（指示書 §5.3）。
  --   `turbo_enabled` はフレーム倍率だけの話。ここでは一切見ない。
  if ai.disable_when_danger and ctx.danger then
    return false, "危険状態（" .. tostring(ctx.danger_reason or "理由不明") .. "）"
  end
  if ai.disable_when_first_encounter and ctx.first_encounter then
    return false, "初遭遇のモンスターが居る"
  end
  if ai.disable_when_boss and ctx.is_boss then return false, "ボス戦" end
  -- ★逃げた相手には自動で殴りかからない。自動入力は「たたかう」しか
  --   押せず逃げる選択ができないため、勝てなかった相手に押し付けない。
  if ai.disable_when_caution ~= false and ctx.is_caution then
    return false, "警戒中の相手（前に逃げた/負けた）"
  end
  return true, nil
end

--- ラッチも含めた最終判断。
function BattleController:auto_input_allowed(context)
  local ctx = context or {}
  -- ★強制AUTO は手動ラッチより強い（利用者が明示的に取り返した主導権）
  -- ⚠ ただし AUTO そのものを切ってあれば動かない（`auto_enabled` が上位）。
  if self:force_auto_active(ctx.is_boss) then
    return self.auto_enabled == true
  end
  if self.manual_latched then return false end
  return self:auto_input_allowed_now(ctx)
end

-- --- キーで切り替える ------------------------------------------------

--- キーボードで AUTO を切り替える（指示書 §3）。
---
--- ★★ **見るのは「いま AI が操作しているか」**（設定の値ではない）★★
---
---   単純に `auto_enabled` を反転させると、手動ホイミからの復帰が壊れる:
---     危険判定で手動化（`manual_latched`）→ 人が手動でホイミ → キー
---     このとき `auto_enabled` は**まだ true のまま**なので、
---     反転させると ⚠ **AUTO を切ってしまう**（復帰したいのに逆）。
---
--- ⚠ 速度には一切触らない。復帰後は**それ以前の高速化設定のまま**。
--- @return boolean 入れたか（false なら切った）
function BattleController:toggle_from_hotkey(context, notify)
  if self:auto_input_allowed(context) then
    self:set_auto(false, "キーボード")
    -- ★強制AUTO も一緒に解除する（指示書 §4）。
    self:set_force_auto(false, notify)
    return false
  end

  -- ★止まっている理由を消してから入れる。どれが効いていたか分からないので
  --   **3つとも**外す（設定・この戦闘のラッチ・安全機構）。
  self:set_auto(true, "キーボード")
  self:clear_latch("キーボード / AUTO へ復帰")
  -- 強制AUTO は**この戦闘の間だけ**（`on_battle_end` で解除）。
  self:set_force_auto(true, notify)
  return true
end

-- --- 戦闘の始まりと終わり --------------------------------------------

function BattleController:on_battle_start()
  -- ★戦闘ごとにラッチをやり直す（前の戦闘の手動を持ち越さない）
  self.manual_latched = false
end

function BattleController:on_battle_end()
  -- ★★ 強制AUTO は**その戦闘だけ**（指示書 §4）★★
  --   安全機構を潰す状態なので、次の戦闘へ持ち越さない。
  --   ⚠ AUTO そのもの（`auto_enabled`）は解除しない。あれは設定であって
  --     「この戦闘の例外」ではない。混ぜるとキーを押すたびに
  --     AUTO 設定が戦闘ごとに勝手に戻る。
  self:set_force_auto(false)
  self.manual_latched = false
end

--- 画面や診断に出す形。
function BattleController:get_status()
  return {
    auto_enabled = self.auto_enabled == true,
    force_auto = self.force_auto == true,
    manual_latched = self.manual_latched == true,
  }
end

return BattleController
