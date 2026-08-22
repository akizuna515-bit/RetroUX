-- `command.json` を読む担当（2026-08-01 のリファクタ指示書 §4.2）。
--
-- ★★ **この人が持つのは「画面から何を頼まれたか」だけ。** ★★
--
--   | 状態 | 所有 |
--   | --- | --- |
--   | 最後に処理した `request_id` | **ここ** |
--
-- ⚠⚠ **キー名や GUI のボタン名は返さない**（指示書 §4.2）。
--   返すのは**アクション名と値**だけ。そうしておけば、
--   将来ゲームパッドが増えても Lua 側は何も変えなくてよい。
--
-- ★★ 本物の JSON パーサではない。 ★★
--   FCEUX の Lua には JSON が無く、入れ子も配列も扱わない前提で
--   **パターン抽出**している（`docs/design/phase6-tactics-spec.md` 5.3）。
--   ⚠ だから書く側（`CommandService`）は**平たい1階層**で書く約束。

local CommandReader = {}
CommandReader.__index = CommandReader

--- @param path string `command.json` の場所
--- @param logger function|nil `logger(message, notice)` の形
function CommandReader.new(path, logger)
  local self = setmetatable({}, CommandReader)
  self.path = path
  self._log = logger
  -- ★最後に処理した通し番号。⚠ これが無いと、command.json は消えないので
  --   **巡回のたびに同じ操作を実行する**。
  self.last_request_id = nil
  return self
end

-- ★段階（レベル）を素通しする（2026-08-13 / Phase 2）。
--   ⚠ 省略時は INFO。既存の呼び出しは直さなくてよい。
function CommandReader:log(message, notice, level)
  if self._log ~= nil then self._log(message, notice, level) end
end


--- ファイルを丸ごと読む。読めなければ nil。
---
--- ⚠ 書き換えの一瞬に当たることがある。**そのときは静かに諦める**
---   （次の巡回で読めればよい。ここで騒ぐと毎回の警告になる）。
function CommandReader:_read()
  local handle = io.open(self.path, "r")
  if handle == nil then return nil end
  local body = handle:read("*a")
  handle:close()
  if body == nil or body == "" then return nil end
  return body
end

-- --- 値の取り出し（平たい1階層だけ）----------------------------------

--- @return boolean|nil
function CommandReader.flag(body, key)
  local found = body:match('"' .. key .. '"%s*:%s*(%a+)')
  if found == nil then return nil end
  return found == "true"
end

--- @return number|nil
function CommandReader.number(body, key)
  return tonumber(body:match('"' .. key .. '"%s*:%s*(-?%d+)') or "")
end

--- @return string|nil
function CommandReader.text(body, key)
  return body:match('"' .. key .. '"%s*:%s*"([^"]*)"')
end

-- --- 巡回 -------------------------------------------------------------

--- いまの `command.json` を読む。
---
--- 戻り値は表:
--- ```lua
--- {
---   body = "生の中身",          -- ★呼ぶ側が追加の項目を拾うため
---   action = "save_state",      -- 一度きりの操作（無ければ nil）
---   request_id = 123,           -- その通し番号
---   auto_enabled = true,        -- 状態（無ければ nil）
---   turbo_enabled = false,
---   force_auto = true,          -- 強制AUTO（無ければ nil）
--- }
--- ```
---
--- ★★ `action` は**新しい要求のときだけ**入る。 ★★
---   ⚠ 同じ `request_id` を2回返すと、Lua が同じ操作を繰り返す。
---
--- @param discard_actions boolean|nil true なら要求を「処理済み」にして捨てる
---        （起動直後。⚠ 前回終了時の要求が残っているため）
function CommandReader:poll(discard_actions)
  local body = self:_read()
  if body == nil then return nil end

  local made = {
    body = body,
    auto_enabled = CommandReader.flag(body, "auto_enabled"),
    turbo_enabled = CommandReader.flag(body, "turbo_enabled"),
    -- ★強制AUTO（パッドの X 長押し / RX-0082）。⚠ 無ければ nil（触らない）
    force_auto = CommandReader.flag(body, "force_auto"),
    tactics_revision = CommandReader.number(body, "tactics_revision"),
    mantan_mode = CommandReader.text(body, "mantan_mode"),
    save_slot = CommandReader.number(body, "save_slot"),
    reset_encountered = CommandReader.flag(body, "reset_encountered"),
  }

  local action = CommandReader.text(body, "action")
  local request_id = CommandReader.number(body, "request_id")
  if action ~= nil and action ~= "" and request_id ~= nil
     and request_id ~= self.last_request_id then
    self.last_request_id = request_id
    if discard_actions then
      -- ★起動直後は捨てる。⚠ 前回の終了時に残った要求を
      --   立ち上がりざまに実行すると、意図しない保存やロードが起きる。
      self:log("起動時に残っていた要求を捨てました: " .. tostring(action),
               "stale command dropped", "DEBUG")
    else
      made.action = action
      made.request_id = request_id
    end
  end
  return made
end

return CommandReader
