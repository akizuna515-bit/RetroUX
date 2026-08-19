-- 単発の操作要求（まんたん等）を受け取って実行する。
--
-- 役割分担:
--   bridge.lua      command.json から要求を**受け取るだけ**（ゲーム非依存を保つ）
--   action_driver   要求を実行し、実行中の面倒を見る（1つずつ・上限つき）
--   run.lua         起動して毎フレーム tick を呼ぶだけ
--
-- ★このモジュールを切り出した理由:
--   以前は run.lua の無限ループの中に処理が書かれており、
--   **検証しようとするとループを写して二重管理になる**（写した方だけ直る事故が起きる）。
--   ここに閉じたので run.lua と検証スクリプトが同じコードを通る。
--
-- 実行中の runner に求める約束（まんたんが満たしている）:
--   precheck() -> ok, reason   入力を1つも押す前に可否を判定する
--   tick()                     毎フレーム呼ばれる
--   done()                     終了したか
--   summary()                  結果のテーブル

local ActionDriver = {}
ActionDriver.__index = ActionDriver

-- opts.bridge     : Bridge
-- opts.handlers   : { 名前 = function(bridge) -> runner }
-- opts.on_event   : function(kind, message, fields) 任意。ログ・イベント出力用
-- opts.multiplier : 実行中の倍率。省略時は config.speed.action_multiplier
function ActionDriver.new(opts)
  local self = setmetatable({}, ActionDriver)
  self.bridge = opts.bridge
  self.handlers = opts.handlers or {}
  self.on_event = opts.on_event
  local cfg_speed = (opts.bridge.config and opts.bridge.config.speed) or {}
  self.multiplier = opts.multiplier or cfg_speed.action_multiplier
  self.active = nil
  self.active_name = nil
  self.saved_suppress = nil
  -- 検証用の集計。要求を取りこぼしていないか・重複実行していないかを見る
  self.counts = { received = 0, started = 0, skipped = 0,
                  unknown = 0, busy = 0, finished = 0 }
  return self
end

local function notify(self, kind, message, fields)
  if self.on_event then self.on_event(kind, message, fields or {}) end
end

function ActionDriver:busy()
  return self.active ~= nil
end

function ActionDriver:_start(name, handler)
  local runner = handler(self.bridge)
  if runner == nil then
    self.counts.skipped = self.counts.skipped + 1
    notify(self, "skipped", name .. ": 実行できません", { action = name })
    return
  end

  -- ★事前確認に通らなければボタンを一切押さない。
  -- 「開いてみたが無かったので閉じる」という無駄な操作をしないため。
  local ok, reason = runner:precheck()
  if not ok then
    self.counts.skipped = self.counts.skipped + 1
    notify(self, "skipped", name .. " を実行しません: " .. tostring(reason),
      { action = name, reason = reason })
    return
  end

  -- 実行中はメニュー閉じ動作に邪魔させない。
  -- 横から B を押されると経路が崩れる（入力の所有者はブリッジ一つだが、
  -- ブリッジ自身の後始末動作と競合しうる）。
  self.saved_suppress = self.bridge.suppress_menu_cleanup
  self.bridge.suppress_menu_cleanup = true

  -- 実行中は倍速にする（中身は待ち時間そのもの）。
  -- ブリッジ側が戦闘中はこれを無視するため、安全判定は損なわれない。
  if self.multiplier ~= nil and self.multiplier > 1.0 then
    self.bridge.action_multiplier = self.multiplier
  end

  self.active = runner
  self.active_name = name
  self.counts.started = self.counts.started + 1
  notify(self, "start", name .. " 開始: " .. tostring(reason),
    { action = name, detail = reason, multiplier = self.bridge.action_multiplier })
end

function ActionDriver:_finish()
  local s = self.active:summary()
  local name = self.active_name
  -- ★必ず元へ戻す。戻し忘れるとメニュー閉じ動作が永久に無効になる
  self.bridge.suppress_menu_cleanup = self.saved_suppress
  -- ★倍率も必ず戻す。戻し忘れるとフィールドが倍速のままになる
  -- （スクリプトが落ちた場合は bridge の registerexit が等速へ戻す）
  self.bridge.action_multiplier = nil
  self.active = nil
  self.active_name = nil
  self.counts.finished = self.counts.finished + 1
  s.action = name
  notify(self, "done", string.format("%s 終了(%s): %s",
    name, tostring(s.status), tostring(s.reason)), s)
end

function ActionDriver:_handle_pending()
  local action = self.bridge.pending_action
  if action == nil then return end
  self.bridge.pending_action = nil
  self.counts.received = self.counts.received + 1

  local handler = self.handlers[action]
  if handler == nil then
    -- 知らない要求は黙って捨てずに記録する（設定ミスに気づけるように）
    self.counts.unknown = self.counts.unknown + 1
    notify(self, "unknown", "未知の操作要求を無視しました: " .. tostring(action),
      { action = action })
    return
  end
  if self:busy() then
    -- 同時実行はしない。入力の取り合いになる
    self.counts.busy = self.counts.busy + 1
    notify(self, "busy", tostring(self.active_name) .. " が実行中のため無視しました",
      { action = action })
    return
  end
  self:_start(action, handler)
end

-- 毎フレーム、bridge:step() の**前**に呼ぶ。
-- （runner が入力を要求し、その後ブリッジが最終的な入力を確定する順序）
function ActionDriver:tick()
  self:_handle_pending()
  if self.active ~= nil then
    self.active:tick()
    if self.active:done() then self:_finish() end
  end
end

return ActionDriver
