-- フィールドで道具を使う（RX3-0159 / 2026-09-11）。★まずは鍵で扉を開ける。
--
-- ## ★実機で通った手順（`scripts/dq3_door_probe_run.py` / slot 4）
--
--   A        → コマンド（はなす じゅもん / つよさ どうぐ / そうび しらべる）
--   どうぐ    → 誰の？（あかり ハンソロ エルシド ロミオ）
--   あかり    → あかりの袋（★袋の並び = RAM の並び）
--   とうぞくのかぎ → どうする？（▶つかう / わたす / すてる）
--   つかう    → ★扉が消える（⚠ 文の窓は写らなかった）
--
-- ## ⚠⚠ 決め打ちの手数では押しません
--
--   ⚠ 「どうする？」の 3 番目は **すてる** です。★1 つずれて押すと鍵を捨てます。
--   → ★どの段も「**カーソルが目当ての名前を指しているときだけ** A」（まんたん・補充と同じ約束）。
--     ⚠ 指していなければ上下左右で寄せ直す。⚠ 見つからなければ**押さずに止まる**。
--
-- ## ★頼み方
--
--   use_item  member="<1-4>"  item="<道具の名前のタイル>"  choose="<つかう のタイル>"
--
--   ⚠⚠ `action` という名前にしない（★Python の `commands.send(action, **params)` と衝突して
--     TypeError になる / 2026-09-11 に検査で踏んだ）
--
--   ★語はタイル列で受け取ります（⚠ Lua は文字コード表を持たない / 補充と同じ）。
--   ★「誰に？」の段は `target="<1-4>"` で頼む（RX3-0174 / やくそう・どくけしそう / 2026-09-11 実機で通った）。
--     ★▶ は人の名前の窓へ移るので、▶ が誰かの名前を指すまで待ってから寄せる。
--   ★まんたんは頼みのファイルではなく `HOST.item_use.start` で直接頼む（★置き場が 1 つなので）。
--
-- ## ⚠ 画面を読む部品は、まんたん・補充と同じ見方を**最小限だけ**持ちます
--
--   ★まんたんは局所関数で外へ出していないため（`restock_v0.lua` と同じ事情）。
--   ⚠ 窓の四隅の番号は**設定から**取ります（★`dq3rom/window.py` が正本 / dev.lua と同じ）。

-- ⚠⚠ 開発機のパスへ落ちない（RX3-0466 / 2026-09-29）
local root = os.getenv("RETROUX_ROOT")
if root == nil or root == "" then
  error("RETROUX_ROOT が立っていません（★起動は DQ3.cmd から / RX3-0466）")
end
local write_root = os.getenv("RETROUX_WRITE_ROOT") or root
local Core = dofile(root .. "/dq3/phase0/core.lua")
local Cursor = dofile(root .. "/dq3/phase0/cursor.lua")
local ok_cfg, CFG = pcall(require, "dq3_phase0")
if not ok_cfg or type(CFG) ~= "table" then CFG = {} end

local ME = "item_use_v0"
local HOST = rawget(_G, "DQ3_DEV")
local logfile = Core.open_log(write_root .. "/work/dq3-probe/item_use_v0.log", "道具を使う記録")
local function say(line)
  if logfile ~= nil then logfile:write(line .. string.char(10)); logfile:flush() end
end

local BUTTONS = (HOST and HOST.buttons) or Core.new_buttons({say = say})
local COLS, ROWS = CFG.columns or 32, CFG.rows or 30
local PARTY = CFG.party or {}
local FIELD = CFG.field or {}
local MENU = FIELD.menu_tiles or {}
local WINDOWS = FIELD.windows or {}
local WIN = CFG.window or {}

--: ★決めごと（★まんたん・補充の実測に合わせた値）
local OPEN_GAP = 45          --: ★窓が出るのを待つ（まんたんの実測 25 フレーム + 余裕）
local MOVE_GAP = 12          --: ★カーソルを 1 つずらす間隔
local MOVE_TRIES = 12        --: ⚠ これだけ寄せても届かなければ止める（★袋は 8 行まで）
local WAIT_WINDOW = 240      --: ⚠ 窓・語が出るのを待つ上限（フレーム）
local NO_BLINK_MAX = 240     --: ⚠ 点滅を捕まえられない上限
local CLEAR_TRIES = 6        --: ★始める前に B で閉じる上限
local AFTER_WAIT = 60        --: ★つかったあと、画面が落ち着くまで
local CLOSE_TRIES = 6        --: ★終わりに文の窓を閉じる上限

local run = nil
local status = {active = false, phase = "idle", reason = "", seq = nil, message = false}

local function publish()
  if HOST ~= nil then HOST.item_status = status end
end

----------------------------------------------------------------------
-- ★画面を読む（⚠ 最小限）
----------------------------------------------------------------------

local function read_nt()
  if HOST == nil or HOST.screen == nil then return nil end
  local ok, nt = pcall(HOST.screen.read)
  if not ok then return nil end
  return nt
end

local function at(nt, x, y)
  if nt == nil or x < 0 or y < 0 or x >= COLS or y >= ROWS then return nil end
  return nt[y * COLS + x + 1]
end

--- ★枠つきの窓の左上をぜんぶ（⚠ 並びの文字列にして「変わったか」を見るため）。
local function windows_text(nt)
  local tl, tr = WIN.top_left, WIN.top_right
  local bl, br = WIN.bottom_left, WIN.bottom_right
  if nt == nil or tl == nil then return "" end
  local parts = {}
  for y = 0, ROWS - 3 do
    for x = 0, COLS - 3 do
      if at(nt, x, y) == tl then
        local right = nil
        for k = x + 2, COLS - 1 do
          if at(nt, k, y) == tr then right = k; break end
          if at(nt, k, y) == tl then break end
        end
        if right ~= nil then
          for yy = y + 2, ROWS - 1 do
            if at(nt, x, yy) == bl and at(nt, right, yy) == br then
              parts[#parts + 1] = string.format("(%d,%d)", x, y)
              break
            end
          end
        end
      end
    end
  end
  return table.concat(parts, " ")
end

local function window_at(nt, name)
  local w = WINDOWS[name]
  if w == nil or WIN.top_left == nil then return false end
  return at(nt, w[1], w[2]) == WIN.top_left
end

--- ★目当ての語（タイル列）を、カーソルにいちばん近いところで探す。
local function find_near(nt, seq, cx, cy)
  if nt == nil or seq == nil or #seq == 0 then return nil end
  local bx, by, best = nil, nil, nil
  for y = 0, ROWS - 1 do
    for x = 0, COLS - #seq do
      local hit = true
      for k = 1, #seq do
        if at(nt, x + k - 1, y) ~= seq[k] then hit = false; break end
      end
      if hit then
        local d = (cx == nil) and (y * COLS + x)
          or (math.abs(x - (cx + 1)) * 8 + math.abs(y - cy))
        if best == nil or d < best then bx, by, best = x, y, d end
      end
    end
  end
  return bx, by
end

--- ★点滅しているカーソル（⚠ 見えないフレームがある / 追跡は dev.lua の 1 つ）。
local function cursor_at(nt)
  if HOST == nil or HOST.cursor == nil then return nil end
  local track = HOST.cursor
  local sc = HOST.screen
  if sc ~= nil then
    pcall(track.set_scroll, sc.scroll_x, sc.scroll_y, (sc.ctrl or 0) % 4)
  end
  if nt ~= nil then pcall(track.update, nt) end
  local ok, x, y = pcall(track.active)
  if ok and x ~= nil then return x, y end
  return nil
end

local function forget()
  if HOST ~= nil and HOST.cursor ~= nil then pcall(HOST.cursor.forget) end
end

local function member_name(index)
  if PARTY.name == nil then return nil end
  local nsize = PARTY.name_size or 4
  local out = {}
  for k = 0, nsize - 1 do
    local b = memory.readbyte(PARTY.name + index * nsize + k)
    if b ~= 0 then out[#out + 1] = b end
  end
  return out
end

local function hex_tiles(text)
  local out = {}
  for two in (text or ""):gmatch("%x%x") do out[#out + 1] = tonumber(two, 16) end
  return out
end

----------------------------------------------------------------------
-- ★進み方
----------------------------------------------------------------------

local function finish(reason, ok)
  if run == nil then return end
  BUTTONS.release(ME)
  status.active, status.phase, status.reason = false, "done", reason
  say(string.format("%s reason=%s 押した=%d",
      ok and "ITEM_USE_V0_DONE" or "ITEM_USE_V0_STOP", reason, run.pressed))
  run = nil
  publish()
end

local function stop(reason) finish(reason, false) end

local function press(key, gap)
  BUTTONS.press(ME, key)
  run.pressed = run.pressed + 1
  run.cool = gap or OPEN_GAP
end

--- ★★ カーソルが `tiles` を指していれば A。⚠ 指していなければ寄せる（押さない）。
--
--   ⚠⚠ 「すてる」を押さないための**唯一の関門**です。★A はここでしか押しません。
local function choose(nt, tiles, why)
  local cx, cy = cursor_at(nt)
  if cx == nil then
    run.no_blink = run.no_blink + 1
    if run.no_blink > NO_BLINK_MAX then stop("cursor_not_blinking:" .. why) end
    return false
  end
  run.no_blink = 0
  if Cursor.starts_with(Cursor.label_at(nt, cx, cy), tiles) then
    say(string.format("  ★%s を選んだ（カーソル %d,%d）", why, cx, cy))
    press("A", OPEN_GAP)
    forget()
    run.moves, run.waited = 0, 0
    return true
  end
  local x, y = find_near(nt, tiles, cx, cy)
  if x == nil then
    run.waited = run.waited + 1
    if run.waited > WAIT_WINDOW then stop(why .. "_not_on_screen") end
    return false
  end
  run.waited = 0
  if run.moves >= MOVE_TRIES then
    stop("cursor_stuck:" .. why)
    return false
  end
  run.moves = run.moves + 1
  local want_x = x - 1
  if cy < y then press("down", MOVE_GAP)
  elseif cy > y then press("up", MOVE_GAP)
  elseif cx < want_x then press("right", MOVE_GAP)
  else press("left", MOVE_GAP) end
  forget()
  return false
end

--- ★始める前に、開いている窓を B で閉じる。
--   ⚠ 立ち止まると出る**状態の窓**は B では消えません（★nav と同じ）。
--   → ★B で窓の並びが変わらなくなったら、閉じ終えたとみなして進む。
local function tick_clear(nt)
  local now = windows_text(nt)
  if now == "" then run.phase = "open"; run.waited = 0; return end
  if now == run.last_windows then
    run.unchanged = run.unchanged + 1
  else
    run.unchanged, run.last_windows = 0, now
  end
  if run.unchanged >= 2 or run.cleared >= CLEAR_TRIES then
    say("  ★閉じられる窓は閉じた（残り: " .. now .. "）")
    run.phase, run.waited = "open", 0
    return
  end
  run.cleared = run.cleared + 1
  press("B", OPEN_GAP)
end

local function tick_open(nt)
  if window_at(nt, "command") then
    run.phase, run.waited = "command", 0
    forget()
    return
  end
  run.waited = run.waited + 1
  if run.waited > 4 then stop("menu_not_opened"); return end
  press("A", OPEN_GAP)            -- ⚠ 窓が出るまで待つ（★押し直しは 45 フレームおき）
end

--- ★つかったあと。⚠ 文の窓が出たら B で閉じる（★鍵が扉に効かなかったとき）。
local function tick_after(nt)
  run.waited = run.waited + 1
  if run.waited < AFTER_WAIT then return end
  local now = windows_text(nt)
  if now == "" then
    finish("used", true)
    return
  end
  -- ⚠ 窓が残っている（★文が出た / 状態の窓）。B で閉じる
  status.message = true
  if now == run.last_windows then
    run.unchanged = run.unchanged + 1
  else
    run.unchanged, run.last_windows = 0, now
  end
  if run.unchanged >= 2 or run.closed >= CLOSE_TRIES then
    finish("used", true)          -- ★閉じられるものは閉じた（状態の窓だけ残る）
    return
  end
  run.closed = run.closed + 1
  run.waited = AFTER_WAIT - 1
  press("B", OPEN_GAP)
end

--- ★★ 誰に使うか（RX3-0174 / やくそう・どくけしそう）。
--
--   ⚠ フィールドでは、誰にの一覧は新しい窓ではなく**人の名前の窓**へ ▶ が戻ってくる（まんたんの呪文と同じ実測）。
--   → ★▶ が誰かの名前を指すまで待つ（⚠ その前に寄せると、道具・どうするの窓で ▶ を動かしてしまう）。
local function tick_target(nt)
  local cx, cy = cursor_at(nt)
  local on_person = false
  if cx ~= nil then
    local label = Cursor.label_at(nt, cx, cy)
    for i = 0, (PARTY.slots or 4) - 1 do
      local name = member_name(i)
      if #name > 0 and Cursor.starts_with(label, name) then on_person = true; break end
    end
  end
  if not on_person then
    run.waited = run.waited + 1
    if run.waited > WAIT_WINDOW then stop("target_not_offered") end
    return
  end
  if choose(nt, run.target_tiles, "target") then run.phase, run.waited = "after", 0 end
end

local function start(params, seq)
  params = params or {}
  if HOST ~= nil and HOST.in_battle ~= nil and HOST.in_battle() == true then
    say("⚠ 戦闘中なので何もしません")
    status.active, status.phase, status.reason, status.seq = false, "done", "battle", seq
    publish()
    return
  end
  if run ~= nil then finish("replaced", false) end
  local member = tonumber(params.member or "") or 0
  local item, action = hex_tiles(params.item), hex_tiles(params.choose)
  --: ★誰に使うか（RX3-0174 / やくそう・どくけしそう）。⚠ 無ければ鍵と同じ（★誰にの段が無い）
  local target = tonumber(params.target or "") or 0
  status.active, status.phase, status.reason, status.seq = true, "clear", "", seq
  status.message = false
  run = {seq = seq, phase = "clear", waited = 0, moves = 0, no_blink = 0, cool = 0,
         pressed = 0, cleared = 0, closed = 0, unchanged = 0, last_windows = nil,
         member = member, item = item, action = action, target = target,
         member_tiles = (member >= 1) and member_name(member - 1) or {},
         target_tiles = (target >= 1) and member_name(target - 1) or nil}
  say(string.format("=== ITEM_USE start %s seq=%s 人 %d / 道具 %d 字 / 選ぶ語 %d 字 / 誰に %s ===",
      os.date("%H:%M:%S"), tostring(seq), member, #item, #action,
      target >= 1 and tostring(target) or "なし"))
  if member < 1 or #run.member_tiles == 0 then stop("member_unreadable"); return end
  if target >= 1 and (run.target_tiles == nil or #run.target_tiles == 0) then
    stop("target_unreadable"); return
  end
  if #item == 0 or #action == 0 then stop("words_missing"); return end
  if MENU.item == nil then stop("item_command_unknown"); return end
  publish()
end

----------------------------------------------------------------------
-- ★毎フレーム
----------------------------------------------------------------------

local function frame()
  if HOST ~= nil and HOST.wants ~= nil then
    if HOST.wants("use_item") then
      local req = HOST.last_request or {}
      start(req.params or {}, req.seq)
    end
  end
  if run == nil then return end
  if not BUTTONS.claim(ME) then return end        -- ⚠ 他の機能が押している間は待つ
  BUTTONS.tick()
  if BUTTONS.busy() then return end
  local nt = read_nt()
  -- ★点滅は間隔の間も観る（⚠ 45 フレーム待つので、観ないと取りこぼす）
  if nt ~= nil then cursor_at(nt) end
  if run.cool > 0 then
    run.cool = run.cool - 1
    return
  end
  if nt == nil then
    run.waited = run.waited + 1
    if run.waited > WAIT_WINDOW then stop("screen_unreadable") end
    return
  end
  local phase = run.phase
  if phase == "clear" then tick_clear(nt)
  elseif phase == "open" then tick_open(nt)
  elseif phase == "command" then
    if choose(nt, MENU.item, "item_command") then run.phase = "member" end
  elseif phase == "member" then
    if choose(nt, run.member_tiles, "member") then run.phase = "item" end
  elseif phase == "item" then
    if choose(nt, run.item, "item") then run.phase = "action" end
  elseif phase == "action" then
    if choose(nt, run.action, "action") then
      run.phase, run.waited = (run.target_tiles ~= nil) and "target" or "after", 0
    end
  elseif phase == "target" then tick_target(nt)
  elseif phase == "after" then tick_after(nt)
  end
  if run ~= nil then status.phase = run.phase end
  publish()
end

local function on_exit()
  if run ~= nil then finish("exit", false) end
  pcall(function() logfile:close() end)
end

publish()
if HOST ~= nil and HOST.features ~= nil then
  HOST.features[#HOST.features + 1] = {name = ME, frame = frame, on_exit = on_exit}
end
--: ★ほかの機能（まんたん）から直接頼む入口（RX3-0174）。⚠ 頼みのファイルは使わない（★置き場が 1 つ）
if HOST ~= nil then
  HOST.item_use = {start = start, status = function() return status end}
end

return {name = ME, frame = frame, start = start, status = status, _hex_tiles = hex_tiles}
