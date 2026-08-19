-- 操作マクロの記録と再現。
--
-- ねらい:
--   利用者が実際にやった操作を**読める形**で記録し、**そのログをそのまま指示として**
--   再現できるようにする。アドレス解析を細かく進めなくても機能を作れるため、
--   「1タイトルごとに解析コストが線形に積み上がる」という本プロジェクト最大の
--   弱点（docs/10-research-notes.md のコンセプト評価）への対策になる。
--
-- 記録するのは**生のボタン列ではなく「意図」**。
--   生の入力を再生する方式（TAS的）は、タイミング・乱数・パーティ状態が変われば崩れる。
--   ここでは各ステップを「この状態になったら、このボタンを押す」という
--   **目標状態＋操作**として記録する。再現時は目標状態まで自分で寄せるので、
--   ズレても自己修正できる（実測: カーソルを目標へ寄せるのに2試行で到達）。
--
-- ログ形式（JSON Lines・人が読んで編集できる）:
--   {"step":1,"menu":0,"cursor":[2,0],"press":"A","note":"コマンドメニューを開く"}
--   {"step":2,"menu":6,"cursor":[1,1],"press":"A","note":"どうぐ"}
--
--   menu    : そのとき開いていたメニューID（$0059）
--   cursor  : カーソル位置 [列, 行]（$0082, $0083）
--   press   : そこで押したボタン
--   note    : 人が読むためのメモ（画面から推測した項目名など）

local Macro = {}

----------------------------------------------------------------------
-- 共通: ゲーム状態の読み取り
----------------------------------------------------------------------

-- DQ2 プラグインから「今どのメニューでカーソルがどこか」を取る。
-- プラグイン側に menu_state() があればそれを使い、無ければアドレスから直接読む。
local function read_state(game)
  if game.menu_state then return game:menu_state() end
  local a = game.a
  local menu = a.menu_id and memory.readbyte(a.menu_id.addr) or 0
  local cx = a.menu_cursor_x and memory.readbyte(a.menu_cursor_x.addr) or 0
  local cy = a.menu_cursor_y and memory.readbyte(a.menu_cursor_y.addr) or 0
  return { menu = menu, cx = cx, cy = cy }
end

local function json_escape(s)
  return (tostring(s):gsub('[\\"]', "\\%0"):gsub("\n", "\\n"))
end

----------------------------------------------------------------------
-- 記録
----------------------------------------------------------------------

local Recorder = {}
Recorder.__index = Recorder

-- opts.path : 出力先
-- opts.game : DQ2 プラグイン
function Macro.recorder(opts)
  local self = setmetatable({}, Recorder)
  self.game = opts.game
  self.file = io.open(opts.path, "w")
  self.step = 0
  self.prev_input = 0
  self.input_addr = (opts.game.a.input and opts.game.a.input.addr) or 0x2F
  -- ★1フレーム前の状態を保持する。理由は tick() のコメントを参照。
  self.prev_state = read_state(opts.game)
  return self
end

-- 毎フレーム呼ぶ。A/B の**押した瞬間**を検出して1ステップとして残す。
-- 押しっぱなしの間は記録しない（同じ操作が何十行にもなるのを防ぐ）。
--
-- ⚠ 記録するのは**押す直前の状態**（1フレーム前）。
--   押した後の状態を記録すると再現に使えない。
--   実際に踏んだ失敗: menu=06 cursor=(1,0) で A を押したのに、
--   記録されたのは遷移後の menu=04 cursor=(0,0) だった。
--   $002F の立ち上がりは frameadvance の後に読むため、
--   その時点でゲームは既に遷移している。
function Recorder:tick()
  local input = memory.readbyte(self.input_addr)
  local pressed_now = {}
  -- $002F のビット割り当て: B0=A B1=B B2=Select B3=Start B4=Up B5=Down B6=Left B7=Right
  for name, bit in pairs({ A = 1, B = 2 }) do
    local was = (self.prev_input % (bit * 2)) >= bit
    local now = (input % (bit * 2)) >= bit
    if now and not was then pressed_now[#pressed_now + 1] = name end
  end
  self.prev_input = input

  for _, btn in ipairs(pressed_now) do
    local st = self.prev_state          -- ★押す直前の状態を使う
    self.step = self.step + 1
    local note = self.game.menu_item_name and self.game:menu_item_name(st) or ""

    -- ★内容が可変なメニュー（どうぐ等）では、行番号ではなく**アイテムID**を残す。
    -- 行番号だけで記録すると所持品が変わった時点で別の物を選んでしまう。
    local item_field = ""
    local layout = self.game.map and self.game.map.menu_layouts
                   and self.game.map.menu_layouts[st.menu]
    if layout and layout.row_source == "inventory" and self.game.inventory then
      local id = self.game:inventory(0)[st.cy]
      if id ~= nil and id ~= 0 then
        item_field = string.format(',"item":%d', id)
      end
    end

    self.file:write(string.format(
      '{"step":%d,"menu":%d,"cursor":[%d,%d]%s,"press":"%s","frame":%d,"note":"%s"}\n',
      self.step, st.menu, st.cx, st.cy, item_field, btn, emu.framecount(),
      json_escape(note)))
    self.file:flush()
  end

  self.prev_state = read_state(self.game)
end

function Recorder:close()
  if self.file then self.file:close(); self.file = nil end
end

----------------------------------------------------------------------
-- 再現
----------------------------------------------------------------------

local Player = {}
Player.__index = Player

-- ログを読み込む。JSON パーサは持たないので必要なフィールドだけ拾う。
local function load_steps(path)
  local steps = {}
  local fh = io.open(path, "r")
  if fh == nil then return steps end
  for line in fh:lines() do
    local menu = tonumber(line:match('"menu"%s*:%s*(%-?%d+)'))
    local cx, cy = line:match('"cursor"%s*:%s*%[%s*(%d+)%s*,%s*(%d+)%s*%]')
    local press = line:match('"press"%s*:%s*"([^"]+)"')
    local note = line:match('"note"%s*:%s*"([^"]*)"')
    local item = tonumber(line:match('"item"%s*:%s*(%d+)'))
    if menu and cx and press then
      steps[#steps + 1] = {
        menu = menu, cx = tonumber(cx), cy = tonumber(cy),
        item = item,          -- ★あれば行番号よりこちらを優先して探す
        press = press, note = note or "",
      }
    end
  end
  fh:close()
  return steps
end

-- opts.path         : ログ
-- opts.game         : DQ2 プラグイン
-- opts.bridge       : 入力はブリッジ経由で要求する（所有者一元化のため）
-- opts.on_progress  : 進捗の通知（任意）
function Macro.player(opts)
  local self = setmetatable({}, Player)
  self.game = opts.game
  self.bridge = opts.bridge
  self.steps = load_steps(opts.path)
  self.index = 1
  self.hold = 0
  self.seek_tries = 0
  self.on_progress = opts.on_progress
  self.max_seek = opts.max_seek or 30
  self.press_frames = opts.press_frames or 8
  self.gap_frames = opts.gap_frames or 10
  self.phase = "seek"
  return self
end

function Player:done()
  return self.index > #self.steps
end

function Player:current()
  return self.steps[self.index]
end

local function report(self, message)
  if self.on_progress then self.on_progress(self.index, message) end
end

-- 毎フレーム呼ぶ。完了したら true を返す。
--
-- 各ステップは「目標状態へ寄せる → 押す → 離す」の3相で進む。
-- ⚠ 入力は必ず bridge:request_input() 経由。joypad.set を直接呼んではいけない
--   （入力の所有者はブリッジ一つ。docs/50-playbook.md 参照）。
function Player:tick()
  if self:done() then return true end
  local step = self:current()
  local st = read_state(self.game)

  if self.phase == "seek" then
    -- メニューが目標と違う場合は待つ。前のステップの押下で遷移するはず。
    if st.menu ~= step.menu then
      self.seek_tries = self.seek_tries + 1
      if self.seek_tries > self.max_seek * 4 then
        report(self, string.format(
          "中断: メニューが %d にならない（現在 %d）", step.menu, st.menu))
        self.index = #self.steps + 1
      end
      return false
    end

    -- ★アイテムIDが記録されている場合は、**その時の実データから行を探し直す**。
    -- 行番号をそのまま使うと、所持品や店の品揃えが変わった時点で
    -- 別の物を選んでしまう。
    -- どうぐメニューなら持ち物から、店なら品揃えから探す（メニュー定義で切替）。
    local target_cy = step.cy
    if step.item ~= nil then
      local layouts = self.game.map and self.game.map.menu_layouts
      local layout = layouts and layouts[step.menu]
      local source = layout and layout.row_source
      local row

      if source == "shop_list" and self.game.find_shop_row then
        row = self.game:find_shop_row(step.item)
      elseif source == "inventory" and self.game.find_item_row then
        row = self.game:find_item_row(step.item, 0)
      end

      if source ~= nil then
        if row == nil then
          report(self, string.format(
            "中断: アイテム 0x%02X が %s に無い", step.item, source))
          self.index = #self.steps + 1
          return false
        end
        target_cy = row
      end
    end

    -- カーソルを目標へ寄せる。端でラップしないので寄せ方は決定的。
    if st.cy ~= target_cy or st.cx ~= step.cx then
      self.seek_tries = self.seek_tries + 1
      if self.seek_tries > self.max_seek then
        report(self, string.format(
          "中断: カーソルが (%d,%d) に寄らない（現在 (%d,%d)）",
          step.cx, step.cy, st.cx, st.cy))
        self.index = #self.steps + 1
        return false
      end
      local dir
      if st.cy < target_cy then dir = "down"
      elseif st.cy > target_cy then dir = "up"
      elseif st.cx < step.cx then dir = "right"
      else dir = "left" end
      self.bridge:request_input({ [dir] = true })
      self.phase = "seek_gap"
      self.hold = self.press_frames
      return false
    end

    -- 目標状態に到達したので押す
    self.phase = "press"
    self.hold = self.press_frames
    self.seek_tries = 0
    return false
  end

  if self.phase == "seek_gap" then
    -- 方向キーを離す時間。押しっぱなしは取りこぼしと連続移動の原因になる。
    self.hold = self.hold - 1
    if self.hold <= 0 then
      self.hold = self.gap_frames
      self.phase = "seek_wait"
    end
    return false
  end

  if self.phase == "seek_wait" then
    self.hold = self.hold - 1
    if self.hold <= 0 then self.phase = "seek" end
    return false
  end

  if self.phase == "press" then
    self.bridge:request_input({ [step.press] = true })
    self.hold = self.hold - 1
    if self.hold <= 0 then
      self.phase = "press_gap"
      self.hold = self.gap_frames
    end
    return false
  end

  -- press_gap: 離してから次のステップへ
  self.hold = self.hold - 1
  if self.hold <= 0 then
    report(self, string.format("完了: menu=%d cursor=(%d,%d) %s %s",
      step.menu, step.cx, step.cy, step.press,
      (step.note ~= "" and ("[" .. step.note .. "]") or "")))
    self.index = self.index + 1
    self.phase = "seek"
    self.seek_tries = 0
  end
  return self:done()
end

return Macro
