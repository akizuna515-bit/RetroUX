-- 速度の担当（2026-08-01 のリファクタ指示書 §4.2）。
--
-- ★★ **この人が持つのは「どの速度で動かすか」だけ。** ★★
--
--   | 状態 | 所有 |
--   | --- | --- |
--   | `turbo_enabled`（高速化の入り切り） | **ここ** |
--   | 現在倍率 | **ここ** |
--   | 演出のための等速保持 | **ここ** |
--
-- ⚠⚠ **AUTO の状態を変えてはならない**（指示書 §4.2）。
--   AUTO は `battle_controller.lua` の持ち物。
--   2026-07-31 に「A キーが速度も変えていた」問題を直したばかりなので、
--   ここから AUTO を触ると**同じ穴に戻る**。
--
-- ★判断に要るものは `context` で受け取る（自分でゲームを覗かない）。
--   ⚠ 覗くと、この人がゲームの内部構造を知ることになり、
--     別のゲームへ持っていけなくなる。

local SpeedController = {}
SpeedController.__index = SpeedController

--- @param config table `config.speed` と `config.speed_events`
--- @param logger function|nil `logger(message, notice)` の形
function SpeedController.new(config, logger)
  local self = setmetatable({}, SpeedController)
  self.config = config or {}
  self.speed = self.config.speed or {}
  self.events = self.config.speed_events or {}
  self._log = logger

  -- ★戦闘の倍速の入切。**既定は入**＝これまでどおり。
  --   書き手は画面のボタンと T キーの2つ（2026-07-31 の指示書 §2）。
  self.turbo_enabled = true
  -- command.json で最後に見た値。★「いまの値」とは別に持つ。
  --   ⚠ 混ぜるとキーで切った直後に巡回が入り直す（立ち上がり判定）。
  self.turbo_commanded = nil

  -- 演出のための等速保持（レベルアップ・仲間の死亡など）
  self.event_normal_left = 0
  self.event_normal_reason = nil
  return self
end

-- ★段階（レベル）を素通しする（2026-08-13 / Phase 2）。
--   ⚠ 省略時は INFO。既存の呼び出しは直さなくてよい。
function SpeedController:log(message, notice, level)
  if self._log ~= nil then self._log(message, notice, level) end
end


-- --- 高速化の入り切り ------------------------------------------------

--- 高速化を切り替える。**唯一の入口**。
---
--- ★★ **なぜ1本にまとめたか**（2026-07-31 / 依頼者の指摘）★★
---   > 高速戦闘トグルボタンとAキーによる高速戦闘は同じものであるべき
---
---   以前は速度に口を出すものが2つあり、
---   **ボタンが OFF なのに速い**という食い違いが起きた。
---
--- ⚠ ここで AUTO を触らない（上の解説）。
--- @return boolean 実際に変わったか
function SpeedController:set_enabled(on, why)
  on = (on == true)
  if self.turbo_enabled == on then return false end
  self.turbo_enabled = on
  self:log(string.format("高速化を%sにしました（%s）",
    on and "入" or "切", tostring(why)),
    "turbo " .. (on and "on" or "off"), "DEBUG")
  return true
end

function SpeedController:toggle(why)
  return self:set_enabled(not self.turbo_enabled, why)
end

function SpeedController:is_enabled()
  return self.turbo_enabled == true
end

--- command.json から来た値を適用する。
---
--- ★★ **ファイル側が変わったときだけ効かせる（立ち上がり判定）** ★★
---   ⚠ 「いまの値」と比べると、キーで切った 30 フレーム後に
---     **勝手に入り直す**（書き手が2人いるため）。
--- @return boolean 適用したか
function SpeedController:apply_command(want, why)
  if want == nil then return false end
  want = (want == true)
  -- ⚠⚠ **「効かない時がある」を測れるようにする**（2026-08-07 / 依頼者報告）。
  --
  --     > 高速化ONOFFボタンを押しても利かない時がある
  --
  --   ★推測で直さず、**どこで落ちたか**を残します。捨てる理由は2つ:
  --     1. ファイルの値が前と同じ（★立ち上がりでないので無視するのが正しい）
  --     2. 既にその状態（★何もしなくてよい）
  --   ⚠ 1 と 2 は別物です。混ぜると原因が分かりません。
  -- ⚠⚠⚠ **ここでログを出してはいけない**（2026-08-07 に踏んだ）★★★
  --   ファイルの値は**毎ポーリング**同じなので、ここは
  --   「押していないときに毎回通る道」です。★異常ではありません。
  --   ⚠ 一度ここに警告を書いたら **195件**出てログが埋まりました。
  --     「鳴りすぎも壊れ方」を自分でやった例です。
  --   ★押したかどうかを知りたいなら、**押した側**（画面）で記録します。
  if want == self.turbo_commanded then return false end
  self.turbo_commanded = want
  local changed = self:set_enabled(want, why or "画面のボタン")
  if not changed then
    self:log(string.format(
      "⚠ 高速化は既に %s でした（要求どおりなので何もしません）",
      tostring(want)), "turbo skipped: already", "DEBUG")
  end
  return changed
end

-- --- 演出のための等速 ------------------------------------------------

--- 演出のあいだ等速に戻す（レベルアップ・仲間の死亡など）。
---
--- ★達成感のある瞬間まで速くすると、嬉しさごと削ってしまう。
--- @param hold number|nil 保つフレーム数（省略時は events.hold_frames）
--- @return boolean 新しく始めたか（延長なら false）
function SpeedController:begin_normal_speed(reason, hold)
  local was = self.event_normal_left > 0
  local want = hold or self.events.hold_frames or 240
  -- ⚠ 既に等速保持中なら**短くしない**（長いほうを採る / RX-0070）。
  --   レベルアップ後にすぐ別の演出が来ても、レベルアップの長い保持を保つ。
  self.event_normal_left = math.max(self.event_normal_left, want)
  self.event_normal_reason = reason
  -- ⚠ 既に等速保持中なら延長だけ（重ねて通知しない）
  return not was
end

function SpeedController:end_normal_speed()
  self.event_normal_left = 0
  self.event_normal_reason = nil
end

--- 1フレーム進める（等速保持の残りを減らす）。
function SpeedController:tick()
  if self.event_normal_left > 0 then
    self.event_normal_left = self.event_normal_left - 1
  end
end

function SpeedController:holding_normal()
  return self.event_normal_left > 0
end

-- --- 倍率を決める ----------------------------------------------------

--- いま出すべき倍率を決める。戻り値: `倍率, 理由`。
---
--- `context` に要るもの:
---   in_battle / manual_latched / danger / first_encounter / is_boss
---   / is_caution / force_auto / action_multiplier
---
--- ★★ **順番が仕様そのもの。** ★★ 下から弾こうとすると必ず漏れる。
function SpeedController:decide_multiplier(context)
  local c = self.speed
  local ctx = context or {}
  local normal = c.normal_multiplier or 1.0

  -- ★★ **高速化が切ってあれば、戦闘中は何があっても等速。** ★★
  --   ⚠ 一番手前で返す。倍速にする理由（強制AUTO 等）が
  --     あとから出てくるので、後ろで弾こうとすると必ず漏れる。
  if ctx.in_battle and self.turbo_enabled == false then
    return normal, "高速戦闘オフ"
  end

  -- ★演出のための等速保持。**他のどの判定より先に見る**。
  --   ただし強制AUTO は例外にできる（既定は例外＝等速に戻さない）。
  --   利用者が「いま速くしたい」と明示した場面なので自動判断で覆さない。
  if self.event_normal_left > 0 then
    local respect = self.events.respect_force_auto ~= false
    if not (respect and ctx.force_auto) then
      return normal, "演出（" .. tostring(self.event_normal_reason) .. "）"
    end
  end

  -- 自動操作（まんたん等）の実行中はフィールドでも倍速にする。
  -- ★戦闘中は無視して通常の戦闘判定へ進む（安全判定を上書きしない）。
  if not ctx.in_battle and ctx.action_multiplier ~= nil then
    return ctx.action_multiplier, "自動操作中"
  end

  if not ctx.in_battle then return normal, "フィールド" end

  -- ★強制AUTO 中は倍速も効かせる。消化試合を早く終わらせるための機能。
  if ctx.force_auto then return c.battle_multiplier, "強制AUTO" end

  -- ★★ 不変条件: プレイヤーが操作する戦闘は等速にする ★★
  --   ⚠ 自動入力を止める条件を増やすたびに倍速側も直す、では必ず漏れる。
  --   **「操作している側が誰か」を1か所で見る。**
  if ctx.manual_latched  then return normal, "手動（この戦闘）" end
  if ctx.danger          then return normal, "危険状態" end
  if ctx.first_encounter then return normal, "初遭遇" end
  if ctx.is_boss         then return normal, "ボス戦" end
  -- 前に逃げた/負けた相手。プレイヤーの難易度判断を自動戦闘で上書きしない
  if ctx.is_caution      then return normal, "警戒中" end
  return c.battle_multiplier, "通常戦闘"
end

--- 画面や診断に出す形。
function SpeedController:get_status()
  return {
    turbo_enabled = self.turbo_enabled == true,
    holding_normal = self.event_normal_left > 0,
    normal_reason = self.event_normal_reason,
  }
end

return SpeedController
