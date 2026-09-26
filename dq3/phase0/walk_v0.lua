-- ★歩く（RX3-0031 §4 / 2026-08-31）。⚠ `dev.lua` から `W` で始める。
--
-- ★★ ここは「配線」だけです。 ★★
--   歩き方そのものは `walker_v0.lua`（⚠ 実機なしで検査済み）。
--   ★このファイルがやるのは、実機の道具とつなぐことだけ:
--
--   ```text
--   where   ★HOST.where（⚠ dev.lua が持つ 1 つ。ここでは作らない）
--   press   ★HOST.buttons（⚠ 持ち主を名乗って押す）
--   stop    ⚠ 戦闘に入ったら止める
--   record  ★1 歩ずつ walker_v0.log へ
--   ```
--
-- ⚠⚠ **セーブステートは書きません。**
--   `ai_state.lua` は 5〜9 を「AI が自由に使ってよい」としていますが、
--   ★依頼者は 5〜9 を**確認用の材料**として使っています
--   （`tests/dq3_states.py` が中身で選ぶ材料）。⚠ 上書きすると消えます。
--   → ★書くかどうかは、`RX3-0031` で依頼者に確かめてから決めます。

local root = os.getenv("RETROUX_ROOT") or "F:/Projects/260721_RetroUX"
local write_root = os.getenv("RETROUX_WRITE_ROOT") or root

local Core = dofile(root .. "/dq3/phase0/core.lua")
local Walker = dofile(root .. "/dq3/phase0/walker_v0.lua")
local Capture = dofile(root .. "/dq3/phase0/capture.lua")

local ok_cfg, CFG = pcall(require, "dq3_phase0")
if not ok_cfg or type(CFG) ~= "table" then CFG = {} end

local ME = "walk_v0"
local HOST = DQ3_DEV

local logfile = Core.open_log(write_root .. "/work/dq3-probe/walker_v0.log",
                              "歩きの記録")
local function say(line)
  if logfile ~= nil then logfile:write(line .. "\n"); logfile:flush() end
end

local BUTTONS = (HOST and HOST.buttons)
  or Core.new_buttons({say = say, hold_max = CFG.hold_max or 7})

--: ⚠ 戦闘中の番地は**設定から**（★`auto_v0` と同じものを見る）
--: ★★ 戦闘の状態は dev.lua の 1 つを借りる（RX3-0166 / DQ3 自身の式）。
--   ⚠ 足場で単独に読むときだけ、自分で作る（★番地は battle_state.lua の 1 か所）。
local Battle = (HOST ~= nil and HOST.battle)
  or dofile(root .. "/dq3/phase0/battle_state.lua").new({cfg = CFG.battle_state})

local WALK = (CFG.walk or {})
local MAX_STEPS = WALK.max_steps or 60

local run = nil            -- ⚠ nil = 歩いていない
local runs = 0
local shots = nil

--- ★いまの場所。⚠ **自分では読まない**（`dev.lua` の 1 つを使う）。
local function where()
  if HOST == nil or type(HOST.where) ~= "function" then return nil end
  local ok, got = pcall(HOST.where)
  if not ok or type(got) ~= "table" or got.loc_kind == nil then return nil end
  return {kind = got.loc_kind, map_id = got.map_id,
          x = got.map_x, y = got.map_y}
end

--- ⚠ 止まるべきか（★理由を返す。無ければ nil）。
--: ★★ 4 方向とも動けなかったときの手当て（RX3-0131 / 2026-09-08）。
--
--   ⚠⚠ **「4 方向とも壁」は、壁とは限りません。**
--     ★メニューやメッセージが開いていると方向キーは窓が食べ、
--       walker は座標しか見ないので**全部壁**と覚えます（★実測で 4 歩で boxed_in）。
--
--   ⚠⚠ かといって「窓が出ていたら歩かない」も**間違い**でした。
--     ★世界地図では HP/MP の状態窓が**いつも出ています**（★2026-09-08 の画面で確認）。
--     ⚠ 窓を門番にすると、世界地図では 1 歩も歩けません。
--
--   → ★真実は「実際に歩けたか」。⚠ 行き詰まったときだけ、
--     **B で窓を閉じて、その升の記憶を消して**やり直します。
local function window_open()
  if HOST == nil or HOST.window_open == nil then return false end
  return HOST.window_open() == true
end

--: ★行き詰まりからの立て直し（⚠ 何度も繰り返さない）
local recovers, recover_frames = 0, 0
local RECOVER_MAX = WALK.recover_max or 3
--: ★B を押してから覚え直すまでの待ち（⚠ 窓が閉じる時間）
local RECOVER_WAIT = WALK.recover_wait or 30

--- ★戦闘に入ったか（★遭遇から / RX3-0166）。
--
-- ⚠⚠ `$62` では見ない（RX3-0131 / RX3-0165）。★勝った後は 1〜7、にげた後は FF が残り、
--   ⚠ walker が「まだ戦闘中」と言って**永久に歩き出せません**でした（266 回空回り）。
-- ⚠ 画面のマス数でも見ない（★建物の中が「戦闘」になった / RX3-0157）。
--   → ★DQ3 自身の式（`battle_state.lua`）で、**遭遇した時点（ENTERING）**から止まる。
local function in_battle()
  return Battle.in_encounter()
end

local function should_stop()
  if in_battle() then return "battle" end
  return nil
end

local function finish(why)
  if run == nil then return end
  BUTTONS.release(ME)                 -- ⚠ 手を離してから終わる
  local at = where() or {}
  say(string.format(
    "WALK_V0_DONE reason=%s steps=%d/%d ok=%d 升=%d 場所=%s(%s,%s) 立て直し=%d 届かず=%d",
    tostring(why), run.steps, MAX_STEPS, run.ok_steps, run.unique(),
    tostring(at.map_id), tostring(at.x), tostring(at.y),
    recovers, run.undelivered or 0))
  if shots ~= nil then shots.named(string.format("walk%02d_end", runs)) end
  say("=== WALK_V0 end ===")
  run = nil
end

local function start()
  runs = runs + 1
  local dir = write_root .. "/work/dq3-evidence"
  shots = Capture.new({dir = dir, say = say})
  say("=== WALK_V0 start " .. os.date("%Y-%m-%d %H:%M:%S")
      .. " run=" .. runs .. " ===")
  local at = where()
  if at == nil then
    say("⚠⚠ いまの場所が読めません（★歩きません）")
    return
  end
  -- ★★ ⚠⚠ **ボタンを握る**（2026-08-31 に抜けていた）。
  --
  --   ★これが無いと `BUTTONS.press` は毎回**断られます**。
  --   ⚠ 実機では「歩いた」と記録に出るのに 1 歩も動かず、
  --     `dev.log` に「持ち主は nil」が 16 回並んでいました。
  --   ★動いて見えた 2 歩は、依頼者ご自身の入力でした。
  if not BUTTONS.claim(ME) then
    say("⚠⚠ ボタンを握れません（★ほかの機能が使っています）")
    return
  end
  say(string.format("★出発 map=%s (%s,%s) kind=%s %s 上限=%d 歩",
    tostring(at.map_id), tostring(at.x), tostring(at.y), tostring(at.kind),
    (at.kind == 0 or at.kind == 2) and "世界地図" or "ローカル", MAX_STEPS))
  recovers, recover_frames = 0, 0
  if window_open() then
    -- ⚠ 世界地図では状態窓がいつも出ています。★止める理由にはしません（記録だけ）
    say("  ⓘ 窓が出ています" .. ((HOST ~= nil and HOST.window_where ~= nil)
        and (" " .. tostring(HOST.window_where())) or "")
        .. "（★世界地図では普通のことです）")
  end
  shots.named(string.format("walk%02d_start", runs))
  run = Walker.new({
    where = where,
    -- ★★ 歩きは押し方が違います（⚠ 2026-09-01 実機）
    --   ⚠ メニューの A は `$14` で届いたと分かりますが、移動の十字キーは
    --     立たないことがあり、7 フレームで「届かなかった」と諦めていました。
    --   → ★`$16`（押されている）を見て、1 歩ぶん長く押します。
    press = function(key)
      BUTTONS.press(ME, key, {hold = WALK.hold or 24, watch_held = true})
    end,
    stop = should_stop,
    max_steps = MAX_STEPS,
    record = function(r)
      say(string.format("  %s %s (%d,%d)→(%s,%s) map=%s %dフレーム",
        r.ok and "★歩いた" or "⚠ 壁", r.input, r.from_x, r.from_y,
        tostring(r.x), tostring(r.y), tostring(r.map_id), r.frames))
    end,
  })
end

local function frame()
  if HOST ~= nil and HOST.wants ~= nil and HOST.wants("walk") then
    if run == nil then start() else finish("stopped_by_user") end
  end
  -- ★管理画面の「自動移動を停止」（RX3-0059）: 止めるだけ。⚠ 止まっているときは何もしない
  if HOST ~= nil and HOST.wants ~= nil and HOST.wants("walk_stop") then
    if run ~= nil then finish("stopped_by_admin") end
  end
  if HOST ~= nil then
    HOST.walk_status = {active = run ~= nil, runs = runs, recovers = recovers}
  end
  if run == nil then return end

  -- ★立て直しの最中は、窓が閉じるのを待つ（⚠ その間は歩かない）
  if recover_frames > 0 then
    recover_frames = recover_frames - 1
    return
  end

  if run.tick() then return end

  -- ★★ 行き詰まった。⚠ `boxed_in` は「窓に入力を食べられた」かもしれない（RX3-0131）
  if run.stopped == "boxed_in" and recovers < RECOVER_MAX then
    recovers = recovers + 1
    local at = HOST.where and where() or nil
    local win = (HOST ~= nil and HOST.window_where ~= nil) and HOST.window_where() or nil
    say(string.format("⚠ 4 方向とも動けませんでした（%d 回目）。★B で窓を閉じて覚え直します%s",
      recovers, win and ("（枠 " .. win .. "）") or ""))
    BUTTONS.press(ME, "B")
    if at ~= nil then run.unblock(at) end
    run.retry()
    recover_frames = RECOVER_WAIT
    return
  end

  finish(run.stopped)
end

local function on_exit()
  if run ~= nil then finish("exit") end
  pcall(function() logfile:close() end)
end

-- ★★ `dev.lua` から読まれたときは、**自分では登録しない**（⚠ 後勝ちになる）。
if HOST ~= nil then
  HOST.features = HOST.features or {}
  HOST.features[#HOST.features + 1] = {
    name = ME, frame = frame, on_exit = on_exit,
  }
  return {name = ME, frame = frame, on_exit = on_exit}
end

emu.registerafter(frame)
emu.registerexit(on_exit)
