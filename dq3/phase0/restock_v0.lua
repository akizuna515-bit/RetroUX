-- 補充（リストック）v0 — 店で足りない道具を買い足す（RX3-0066 / RX3-0119 / 2026-09-08）。
--
-- ## ★実機で確かめた手順（2026-09-08 / レーベのどうぐや）
--
--   ```text
--   店主に話す → 売買選択（かいにきた / うりにきた）
--     → A        品揃え（★ROM と同じ並び。値段と所持金が同じ窓に出る）
--     → 上下 → A ★品を選んだ確認の窓
--     → 持ち主   ★誰が持つかを尋ねる窓（⚠ 本文は写しません / RX3-0433）
--     → 上下 → A ★確定
--   ⚠ 個数は聞かれない（★1 回 1 個）
--   ```
--
-- ## ⚠⚠ ここは「配線」に近い
--
--   ★何をいくつ買うかは Python が決めます（`dq3/knowledge/restock.py`）。
--   ⚠ Lua が持つのは「窓を確かめて、行を探して、押して、買えたか見る」だけです。
--
--     restock  trade="<かいにきた のタイル>" items="<品のタイル>:<個数>:<値段>,..."
--              carrier="<0-3>" carriers="<0-3>,<0-3>,..." full="<もてない のタイル>"
--
-- ## ⚠⚠ 持ち主は 1 個ごとに変える（RX3-0202 / 2026-09-12）
--
--   > 「save8 補充で誰かの持ち物がいっぱいな時の対応がない。
--   >   DQ2のような対応が必要（平均的に所持）」
--
--   ★k 個目は `carriers` の k 番目（⚠ 無ければ `carrier`）。★決めるのは Python です。
--   ⚠ ただし押す前に RAM を見て、その人の袋が満杯なら**選び直します**
--     （★空きが最も多い人 / DQ2 の `_pick_carrier` と同じ決まり）。
--   ⚠⚠ それでも「もてない」（★照合に使う語）と聞かれたら、★いいえ（B）で答えて
--     `carrier_full` で止まります（⚠ 以前は窓を開けたまま `not_bought` で止まった）。
--
-- ## ★守っていること（まんたん / 戦闘での失敗から）
--
--   1. ⚠⚠ **想定の窓が出ていなければ、1 つも押さない**
--   2. ⚠ カーソルは**点滅する**。「見えない＝無い」としない
--   3. ★行番号を計算しない。**タイル列を画面から探して**位置を決める
--   4. ⚠ 迷ったら**押さずに止まる**（★理由を必ず残す）
--   5. ⚠⚠ 買えたことは **所持金と所持数の両方**で確かめる（★片方では足りない）
--   6. ★すべての繰り返しに上限を置く

-- ⚠⚠ 開発機のパスへ落ちない（RX3-0466 / 2026-09-29）
local root = os.getenv("RETROUX_ROOT")
if root == nil or root == "" then
  error("RETROUX_ROOT が立っていません（★起動は DQ3.cmd から / RX3-0466）")
end
local write_root = os.getenv("RETROUX_WRITE_ROOT") or root

local Core = dofile(root .. "/dq3/phase0/core.lua")

local ok_cfg, CFG = pcall(require, "dq3_phase0")
if not ok_cfg or type(CFG) ~= "table" then CFG = {} end

local ME = "restock_v0"
local HOST = rawget(_G, "DQ3_DEV")

local logfile = Core.open_log(write_root .. "/work/dq3-probe/restock_v0.log", "補充の記録")
local function say(line)
  if logfile ~= nil then logfile:write(line .. string.char(10)); logfile:flush() end
end

local BUTTONS = (HOST and HOST.buttons) or Core.new_buttons({say = say})
local COLS, ROWS = CFG.columns or 32, CFG.rows or 30
local CURSOR = CFG.cursor_tile or 0x72
local PARTY = CFG.party or {}
local GOLD = CFG.gold or {}
--: ★★ 戦闘の状態は dev.lua の 1 つを借りる（RX3-0166 / DQ3 自身の式）。
--   ⚠ `$62` では見ない（★にげた後は FF のまま / 勝った後は 1〜7 が残る / RX3-0165）。
--   ⚠ 足場で単独に読むときだけ、自分で作る（★番地は battle_state.lua の 1 か所）。
local Battle = (HOST ~= nil and HOST.battle)
  or dofile(root .. "/dq3/phase0/battle_state.lua").new({cfg = CFG.battle_state})

--: ★決めごと（⚠ どれも上限つき）
local OPEN_GAP = 45          --: ★窓が出るのを待つ（まんたんの実測）
local MOVE_GAP = 8           --: ★カーソルを 1 行ずらす間隔
local MOVE_TRIES = 12        --: ⚠ これだけ押しても届かなければ止める
local WAIT_WINDOW = 240      --: ⚠ 窓が出るのを待つ上限（フレーム）
local WAIT_BUY = 300         --: ⚠ 買えたかを見る上限
local NO_BLINK_MAX = 180     --: ⚠ 点滅を捕まえられない上限
local CLOSE_PRESSES = 6      --: ★終わりに閉じる回数
--: ★★ 1 個買ったあと、⚠ **落ち着くまで押さない**
--
--   ⚠⚠ DQ2 でも同じところで踏んでいます（`restock.lua` の `settle_frames`）:
--     「メニューが開く途中に A を押すと、ゲームに飲まれて購入が成立しない」。
--   ★DQ3 では買ったあとに「まいど…」の段があり、⚠ そこへ押すと
--     次の品を選んだつもりで**メッセージを送っただけ**になりました
--     （実機 2026-09-08: 2 個目で `carrier_not_on_screen`）。
local SETTLE = 120

local run = nil
local status = {active = false, phase = "idle", reason = "", bought = 0, seq = nil,
                spent = 0, message = ""}

local function publish()
  -- ⚠ 途中の数も出す（★終わるまで 0 だと、画面には「何も買っていない」と見える）
  if run ~= nil then
    status.bought, status.spent = run.bought, run.spent
  end
  if HOST ~= nil then HOST.restock_status = status end
end

----------------------------------------------------------------------
-- ★画面を読む（⚠ まんたんと同じ見方。★同じ判定を 2 か所に書かない…が、
--   ⚠ まんたんは局所関数で外へ出していないので、★ここでは最小限だけ持つ）
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

--- ★いま**点滅している**カーソルの位置（⚠ 見えないフレームがある）。
--
-- ## ⚠⚠ 画面の ▶ を数えてはいけない（2026-09-08 実機 / RX3-0119）
--
--   ★コマンド窓の ▶ は**静止**します（⚠ 点滅するのは下位メニューだけ）。
--   店主に話した直後はコマンド窓も残っているので、⚠ タイルを数えると
--   **止まっている ▶** を掴み、★売買選択の行へ永遠に近づけません
--   （実機で `cursor_stuck:trade` になりました）。
--   → ★`HOST.cursor`（書き込みを見張る点滅の追跡）に聞きます。
local function cursor_at(nt)
  if HOST ~= nil and HOST.cursor ~= nil then
    local ok, x, y = pcall(HOST.cursor.active)
    if ok and x ~= nil then return x, y end
    return nil                      -- ⚠ 追跡があるなら、★その答えを信じる
  end
  if nt == nil then return nil end
  for y = 0, ROWS - 1 do
    for x = 0, COLS - 1 do
      if at(nt, x, y) == CURSOR then return x, y end
    end
  end
  return nil
end

--- ★タイル列を画面から探す。⚠ カーソルに**近いもの**を採る。
--
-- ⚠⚠ 前の窓が残っていて、同じ語が 2 か所に出ることがあります
--   （★まんたんで踏んだ: 古い窓の「エルシト」を先に拾って 9 回押した）。
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
        local d
        if cx == nil then
          d = y * COLS + x
        else
          d = math.abs(x - (cx + 1)) * 8 + math.abs(y - cy)
        end
        if best == nil or d < best then bx, by, best = x, y, d end
      end
    end
  end
  return bx, by
end

----------------------------------------------------------------------
-- ★所持金と袋（⚠ 買えたことは**両方**で確かめる）
----------------------------------------------------------------------

local function gold_now()
  if GOLD.address == nil then return nil end
  -- ★`size` のぶんだけ回す（⚠ 既定は 3 / RX3-0369。★2 だと 65535 で巻き戻る）
  local v = 0
  for i = 0, (GOLD.size or 3) - 1 do
    v = v + memory.readbyte(GOLD.address + i) * (256 ^ i)
  end
  return v
end

--: ⚠ 空き枠は `0xFF`（★`0` は「ひのきのぼう」。DQ2 と違う / RX3-0066）
local EMPTY = 0xFF

local function bag_count()
  if PARTY.items == nil then return nil end
  local slots = PARTY.item_slots or 8
  local n = 0
  for i = 0, (PARTY.slots or 4) - 1 do
    for k = 0, slots - 1 do
      if memory.readbyte(PARTY.items + i * slots + k) ~= EMPTY then n = n + 1 end
    end
  end
  return n
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

--- ★その人の袋の空き（⚠ `0xFF` だけ）。⚠ 番地が無ければ nil（★推測で空きにしない）。
local function free_of(index)
  if PARTY.items == nil or index == nil then return nil end
  local slots = PARTY.item_slots or 8
  local n = 0
  for k = 0, slots - 1 do
    if memory.readbyte(PARTY.items + index * slots + k) == EMPTY then n = n + 1 end
  end
  return n
end

--- ★持ち主を RAM から選び直す（RX3-0202 / DQ2 の `_pick_carrier` と同じ決まり）。
--
--   空きが最も多い人 → 同じなら生きている人（HP > 0）→ さらに同じなら並びの早い人。
--   ⚠ 居ない枠（最大 HP が 0）は選ばない（★空き 8 に見えて、真っ先に選ばれてしまう）。
--   ★誰にも空きが無ければ nil。
local function pick_carrier()
  local stride = PARTY.entry_size or 2
  local function word(base, i)
    if base == nil then return nil end
    return memory.readbyte(base + i * stride) + memory.readbyte(base + i * stride + 1) * 256
  end
  local best, best_free, best_alive = nil, 0, false
  for i = 0, (PARTY.slots or 4) - 1 do
    local here = (word(PARTY.hp_max, i) or 1) > 0
    local alive = (word(PARTY.hp_current, i) or 1) > 0
    local free = free_of(i) or 0
    if here and free > 0
        and (free > best_free or (free == best_free and alive and not best_alive)) then
      best, best_free, best_alive = i, free, alive
    end
  end
  return best
end

----------------------------------------------------------------------
-- ★止める / 終わる
----------------------------------------------------------------------

local function finish(reason, ok)
  if run == nil then return end
  BUTTONS.release(ME)
  status.active, status.phase, status.reason = false, "done", reason
  status.bought = run.bought
  status.spent = run.spent
  say(string.format("=== RESTOCK %s reason=%s 買った=%d 使った=%dG ===",
      ok and "DONE" or "STOP", reason, run.bought, run.spent))
  say(ok and "RESTOCK_V0_DONE" or ("RESTOCK_V0_STOP " .. reason))
  run = nil
  publish()
end

local function stop(reason) finish(reason, false) end

----------------------------------------------------------------------
-- ★押す
----------------------------------------------------------------------

local function press(key, gap)
  BUTTONS.press(ME, key)
  run.cool = gap or OPEN_GAP
end

--- ★その窓の**カーソルの列**を見る（⚠ 画面ぜんぶを見ない）。
--
-- ## ⚠⚠ 「点滅を追う」だけでは足りなかった（2026-09-08 実機 / RX3-0119）
--
--   ★売買選択（かいにきた / うりにきた）の ▶ は**点滅しません**。
--   ⚠ 点滅の追跡に聞くと `cursor_not_blinking` で止まり、
--   ⚠ 画面ぜんぶの ▶ を数えると**コマンド窓の静止した ▶** を掴みました。
--
--   → ★狙う語の**すぐ左の列**だけを見ます。
--     ⚠ そこに ▶ が無ければ「点滅で消えている」とみなして**待ちます**（上限つき）。
local function cursor_row_in(nt, col)
  if nt == nil or col < 0 then return nil end
  for y = 0, ROWS - 1 do
    if at(nt, col, y) == CURSOR then return y end
  end
  return nil
end

--- ★カーソルをその行へ寄せる。★届いたら true。
local function move_to(nt, want_x, want_y, why)
  local col = want_x - 1
  local cy = cursor_row_in(nt, col)
  if cy == nil then
    -- ⚠ 点滅で消えているだけかもしれない。★見えたときだけ判断する
    run.no_blink = run.no_blink + 1
    if run.no_blink > NO_BLINK_MAX then stop("cursor_not_blinking:" .. why) end
    return false
  end
  run.no_blink = 0
  if cy == want_y then return true end
  if run.moves >= MOVE_TRIES then
    stop("cursor_stuck:" .. why)
    return false
  end
  run.moves = run.moves + 1
  press(cy < want_y and "down" or "up", MOVE_GAP)
  return false
end

----------------------------------------------------------------------
-- ★局面
----------------------------------------------------------------------

--- ★売買選択の窓に「かいにきた」が出ているか。
local function tick_check(nt)
  local x, y = find_near(nt, run.trade, cursor_at(nt))
  if x == nil then
    run.waited = run.waited + 1
    if run.waited > WAIT_WINDOW then
      -- ⚠⚠ 想定の窓が出ていない。★1 つも押さずに終わる
      stop("no_shop_window")
    end
    return
  end
  run.trade_x, run.trade_y = x, y
  run.waited, run.moves, run.no_blink = 0, 0, 0
  run.phase = "trade"
  say(string.format("★売買選択の窓を見つけた（%d,%d）", x, y))
end

local function tick_trade(nt)
  if move_to(nt, run.trade_x, run.trade_y, "trade") then
    press("A")
    run.phase, run.waited, run.moves, run.no_blink = "list", 0, 0, 0
  end
end

local function want()
  return run.items[run.i]
end

local function tick_list(nt)
  local it = want()
  if it == nil then run.phase, run.waited = "more", 0; return end
  local cx, cy = cursor_at(nt)
  local x, y = find_near(nt, it.tiles, cx, cy)
  if x == nil then
    run.waited = run.waited + 1
    if run.waited > WAIT_WINDOW then stop("item_not_on_screen") end
    return
  end
  if move_to(nt, x, y, "list") then
    run.gold_before, run.bag_before = gold_now(), bag_count()
    press("A")
    run.phase, run.waited, run.moves, run.no_blink = "carrier", 0, 0, 0
    run.who = nil                       -- ★RX3-0202: 持ち主は 1 個ごとに決め直す
  end
end

--- ★k 個目の持ち主を決める（RX3-0202）。★決めたら true。
--
--   ★Python の `carriers` の k 番目（⚠ 無い / 短いときは `carrier`）。
--   ⚠⚠ 押す前に RAM を見て、満杯なら**選び直す**（★「平均的に所持」/ 依頼者 2026-09-12）。
local function choose_carrier()
  local k = run.bought + 1
  local who = run.carriers[k] or run.carrier
  if (free_of(who) or 1) <= 0 then
    local again = pick_carrier()
    if again == nil then
      -- ⚠ 誰にも空きが無い。★押さずに止める（迷ったら押さない）
      stop("carrier_full")
      return false
    end
    say(string.format("  ⚠ 持ち主 %d は袋がいっぱい → ★%d に持たせる（空きが最も多い人）",
        who, again))
    who = again
  end
  run.who, run.carrier_tiles = who, member_name(who) or {}
  if #run.carrier_tiles == 0 then
    stop("carrier_name_unreadable")
    return false
  end
  say(string.format("  ★%d 個目の持ち主 %d（空き %s）", k, who, tostring(free_of(who))))
  return true
end

local function tick_carrier(nt)
  if run.who == nil and not choose_carrier() then return end
  local cx, cy = cursor_at(nt)
  local x, y = find_near(nt, run.carrier_tiles, cx, cy)
  if x == nil then
    run.waited = run.waited + 1
    if run.waited > WAIT_WINDOW then stop("carrier_not_on_screen") end
    return
  end
  if move_to(nt, x, y, "carrier") then
    press("A")
    run.phase, run.waited = "verify", 0
  end
end

--- ⚠⚠ 買えたかは **所持金と所持数の両方**で見る。
--
--   ★片方だけだと「押したつもり」で先へ進みます（DQ2 の restock と同じ約束）。
local function tick_verify(nt)
  local g, b = gold_now(), bag_count()
  local it = want()
  if g ~= nil and b ~= nil and run.gold_before ~= nil and run.bag_before ~= nil then
    local spent = run.gold_before - g
    if spent > 0 and b > run.bag_before then
      run.bought = run.bought + 1
      run.spent = run.spent + spent
      run.left = run.left - 1
      say(string.format("  ★買えた（%dG / 袋 %d→%d / 残り %d 個）",
          spent, run.bag_before, b, run.left))
      if run.left <= 0 then
        run.i = run.i + 1
        run.left = (want() ~= nil) and want().count or 0
      end
      -- ⚠⚠ **買ったあとに「はい／いいえ」が出ます**（2026-09-08 実機で撮った）。
      --   ★「まだ なにか おもとめですか？」の段です。
      --   ⚠ ここを品揃えだと思って押すと、★次の品を選んだつもりで
      --     **返事をしただけ**になり、持ち主の窓が出ませんでした。
      run.phase, run.waited, run.moves, run.no_blink = "more", 0, 0, 0
      run.cool = SETTLE                 -- ⚠ 落ち着くまで押さない
      return
    end
  end
  -- ⚠⚠ その人はもう持てない、と聞き返された（★照合に使う語は `もてない` / RX3-0202）
  --   ★いいえ（B）で答えて止める。⚠ 以前はここで 300 フレーム待ち、窓を開けたまま
  --     `not_bought` で止まっていました（★save8 / 依頼者 2026-09-12）。
  if #run.full > 0 and find_near(nt, run.full, nil) ~= nil then
    say("  ⚠⚠ 「もてない」と言われた → ★いいえ（B）で答えて止める")
    run.phase, run.waited, run.pressed = "full", 0, 0
    run.cool = OPEN_GAP                 -- ⚠ はい／いいえ が出るまで待つ
    return
  end
  run.waited = run.waited + 1
  if run.waited > WAIT_BUY then
    -- ⚠⚠ 押したのに買えていない。★ここで止める（無駄な操作を続けない）
    stop("not_bought")
  end
end

--- ★買ったあとの「はい／いいえ」に答える。
--
-- ⚠ 出ていなければ**押しません**（★店によって出ないかもしれない）。
--   ★まだ買うなら「はい」、もう無いなら「いいえ」。
local function tick_more(nt)
  local more = want() ~= nil
  local seq = more and run.yes or run.no
  if seq == nil or #seq == 0 then
    run.phase = more and "list" or "close"
    run.pressed = 0
    return
  end
  local x, y = find_near(nt, seq, nil)
  if x == nil then
    run.waited = run.waited + 1
    if run.waited > WAIT_WINDOW then
      -- ⚠ 聞かれなかった。★そのまま次へ（押していないので害はない）
      say("  ⓘ 「はい／いいえ」は出ませんでした")
      run.phase, run.waited, run.moves, run.no_blink = more and "list" or "close", 0, 0, 0
      run.pressed = 0
    end
    return
  end
  if move_to(nt, x, y, "more") then
    say(more and "  ★まだ買うので「はい」" or "  ★もう買わないので「いいえ」")
    press("A")
    run.phase, run.waited, run.moves, run.no_blink = more and "list" or "close", 0, 0, 0
    run.pressed = 0
    run.cool = SETTLE
  end
end

--- ⚠⚠ 「もてない」の はい／いいえ に**いいえ（B）**で答えて止める（RX3-0202）。
--
--   ⚠ B を押した直後に止めると、★`release` が押しかけの B を捨てます
--     （core.lua の `B.release`）。→ ★押し終わった次の番で止めます。
local function tick_full(nt)
  if run.pressed > 0 then
    stop("carrier_full")
    return
  end
  if find_near(nt, run.no, nil) == nil then
    -- ⚠ まだ文が出ている途中かもしれない。★上限まで待ってから B
    run.waited = run.waited + 1
    if run.waited <= WAIT_WINDOW then return end
  end
  press("B")
  run.pressed = 1
end

local function tick_close()
  run.pressed = run.pressed + 1
  if run.pressed > CLOSE_PRESSES then
    finish(run.bought > 0 and "bought" or "nothing_to_buy", true)
    return
  end
  press("B", 30)
end

----------------------------------------------------------------------
-- ★受け取る
----------------------------------------------------------------------

local function split_items(text)
  local out = {}
  for chunk in (text or ""):gmatch("[^,]+") do
    local hex, count, price = chunk:match("^(%x+):(%d+):(%d+)$")
    if hex ~= nil then
      local tiles = {}
      for two in hex:gmatch("%x%x") do tiles[#tiles + 1] = tonumber(two, 16) end
      out[#out + 1] = {tiles = tiles, count = tonumber(count), price = tonumber(price)}
    end
  end
  return out
end

local function hex_tiles(text)
  local out = {}
  for two in (text or ""):gmatch("%x%x") do out[#out + 1] = tonumber(two, 16) end
  return out
end

local function start(params, seq)
  params = params or {}
  if Battle.in_encounter() then
    say("⚠ 戦闘中なので何もしません")
    return
  end
  if run ~= nil then finish("replaced", false) end
  local items = split_items(params.items)
  local trade = hex_tiles(params.trade)
  if #items == 0 or #trade == 0 then
    say("⚠ 買うものが決まっていません（★何も押しません）")
    status.reason, status.phase = "no_plan", "done"
    publish()
    return
  end
  if not BUTTONS.claim(ME) then
    say("⚠⚠ ボタンを握れません（★ほかの機能が使っています）")
    status.reason, status.phase = "buttons_busy", "done"
    publish()
    return
  end
  local carrier = tonumber(params.carrier or "0") or 0
  local yes, no = hex_tiles(params.yes), hex_tiles(params.no)
  -- ★RX3-0202: 1 個ごとの持ち主（⚠ 無ければ空の表 → `carrier` を使う）
  local order = {}
  for d in (params.carriers or ""):gmatch("%d+") do order[#order + 1] = tonumber(d) end
  run = {
    seq = seq, items = items, i = 1, left = items[1].count, trade = trade,
    yes = yes, no = no, carrier = carrier, carriers = order, who = nil,
    full = hex_tiles(params.full),
    carrier_tiles = member_name(carrier) or {}, phase = "check",
    waited = 0, moves = 0, no_blink = 0, cool = 0, pressed = 0,
    bought = 0, spent = 0, gold_before = nil, bag_before = nil,
  }
  if #run.carrier_tiles == 0 then
    stop("carrier_name_unreadable")
    return
  end
  status.active, status.phase, status.reason, status.seq = true, "check", "", seq
  status.bought, status.spent = 0, 0
  say(string.format("=== RESTOCK start %s seq=%s 品 %d 種 / 持ち主 %d（順 %s）/ 所持金 %s ===",
      os.date("%H:%M:%S"), tostring(seq), #items, carrier,
      (#order > 0) and table.concat(order, ",") or "-", tostring(gold_now())))
  publish()
end

----------------------------------------------------------------------
-- ★毎フレーム
----------------------------------------------------------------------

local function frame()
  if HOST ~= nil and HOST.wants ~= nil then
    if HOST.wants("restock") then
      local req = HOST.last_request or {}
      start(req.params or {}, req.seq)
    end
    if HOST.wants("restock_stop") then
      if run ~= nil then stop("stopped_by_user") end
    end
  end
  if run == nil then return end
  if Battle.in_encounter() then
    stop("battle")
    return
  end
  if BUTTONS.busy() then return end
  if run.cool > 0 then
    run.cool = run.cool - 1
    return
  end
  local nt = read_nt()
  if nt == nil then
    run.waited = run.waited + 1
    if run.waited > WAIT_WINDOW then stop("screen_unreadable") end
    return
  end
  if run.phase == "check" then tick_check(nt)
  elseif run.phase == "trade" then tick_trade(nt)
  elseif run.phase == "list" then tick_list(nt)
  elseif run.phase == "carrier" then tick_carrier(nt)
  elseif run.phase == "verify" then tick_verify(nt)
  elseif run.phase == "full" then tick_full(nt)
  elseif run.phase == "more" then tick_more(nt)
  elseif run.phase == "close" then tick_close()
  end
  status.phase = run and run.phase or status.phase
  publish()
end

local function on_exit()
  if run ~= nil then finish("exit", false) end
  pcall(function() logfile:close() end)
end

if HOST ~= nil and HOST.features ~= nil then
  HOST.features[#HOST.features + 1] = {name = ME, frame = frame, on_exit = on_exit}
end

return {name = ME, frame = frame, start = start, status = status,
        _split_items = split_items, _hex_tiles = hex_tiles}
