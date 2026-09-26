-- ★街の自動操作（聞き込み・街移動・補充）の Turbo（RX3-0170 / 2026-09-11）。⚠ `dev.lua` が 1 つだけ作る。
--
-- ## ★決まったこと（依頼者「聞き込み・街移動 Auto Turbo化」）
--
--   ```text
--   始める   画面が街の頼み（navigate / restock / use_item）に turbo="1" を添える → ここで Turbo
--   終わる   画面の town_end / セーブを読んだ / 遭遇した（ENTERING）/ 人が B を押した / 画面が黙った
--   ```
--
--   ⚠⚠ 戦闘の Turbo（`battle_speed.lua` / `speed.want`）とは**別の要求**として持つ（`speed.hold("TOWN")`）。
--     ★右画面の「タ」は Auto 中の戦闘の速さ。⚠ 聞き込み・街移動の速さを「タ」に混ぜない（依頼者 §3）。
--
-- ## ★★ 戻すのは Lua が先（⚠ 画面を待たない）
--
--   ⚠ 画面は 0.5 秒ごとにしか見ない。★Turbo（約 35〜48 倍）では 0.5 秒 ≒ ゲームの 20 秒。
--   → ★遭遇したフレームで、**ここが**普通の速さへ戻す（⚠ 画面の town_end を待たない）。
--
-- ## ⚠ 頼みの置き場は 1 つ
--
--   ★Turbo の入り切りを別の頼みにすると、直後の navigate に**上書きされて消える**（RX3-0126 で踏んだ形）。
--   → ★街の頼みそのものに turbo="1" を添える。★終わりの town_end は「止める」も兼ねる
--     （⚠ nav_stop を上書きしても、town_end が同じく止めるので**止め損ねない**）。
--
-- ## ★区間減速（依頼者 §8）
--
--   ★`slow_phases` に書いた nav の局面の間だけ普通の速さ（⚠ 既定は実機で決めた値 / YAML）。
--   ★画面は `speed_normal_count` が増えるたびに人の倍率を送り直すので、普通の区間は 400% で進む。

local M = {}

--: ★速度のスイッチに渡す名前（⚠ 戦闘の `wanted` とは別）
M.KEY = "TOWN"
--: ★Turbo を添えてよい頼み（⚠ 画面の `TownNavController` が送るもの）
M.TOWN_ACTIONS = {navigate = true, restock = true, use_item = true}
--: ★既定（⚠ YAML の `town_turbo` で上書き）
M.DEFAULT = {lease_s = 30, slow_phases = {}, cancel_on_b = true}

local function upper(text)
  return string.upper(tostring(text or ""))
end

--- ★作る。
--
--   opts.speed       Core.new_speed の 1 つ（⚠ `dev.lua` の HOST.speed）
--   opts.battle      `in_encounter()` を持つもの（★battle_state.lua）
--   opts.busy        ★いま街の作業（nav / restock / item）が動いているか
--   opts.phase       ★nav の局面（⚠ 無ければ nil）
--   opts.stop_tasks  ★街の作業を止める（nav_stop / restock_stop を積む）
--   opts.wants       ★HOST.wants（town_end を取り出して applied にする）
--   opts.pad         ★人が握っているパッド（⚠ Lua の押しを含まないもの / 無ければ B では止めない）
--   opts.clock       ★壁時計（秒）。⚠ フレーム数はセーブを読むと戻るので使わない（RX3-0167）
function M.new(opts)
  opts = opts or {}
  local speed = opts.speed
  local say = opts.say or function() end
  local cfg = opts.cfg or {}
  local clock = opts.clock or os.time
  local lease = tonumber(cfg.lease_s) or M.DEFAULT.lease_s
  local cancel_on_b = cfg.cancel_on_b
  if cancel_on_b == nil then cancel_on_b = M.DEFAULT.cancel_on_b end
  local slow_set = {}
  for _, p in ipairs(cfg.slow_phases or M.DEFAULT.slow_phases) do slow_set[p] = true end

  local T = {
    on = false,           --: ★画面が Turbo を頼んでいる（⚠ 区間減速の間も true）
    source = nil,         --: ★誰の頼みか（HEARING / MOVE / RESTOCK）
    slow = nil,           --: ★いま区間減速している局面（⚠ 無ければ nil）
    last_off = nil,       --: ★最後に切った理由
    cancels = 0,          --: ★人が B で止めた回数（★画面はこれが増えたら止める）
    idle_since = nil,
    b_down = false,
  }

  local function turbo_now() return speed ~= nil and speed.holding(M.KEY) end

  local function set_turbo(want, source)
    if speed == nil then return end
    local before = turbo_now()
    speed.hold(M.KEY, want)
    if before ~= want then
      say(string.format("[SPEED] %s -> %s source=%s", before and "TURBO" or "NORMAL",
          want and "TURBO" or "NORMAL", tostring(source)))
    end
  end

  function T.start(source)
    T.on, T.source, T.slow, T.idle_since = true, source, nil, nil
    set_turbo(true, source)
  end

  --- ★切る。戻り値: 切ったか（⚠ 入っていなければ何もしない / ログも出さない）。
  function T.stop(source)
    if not T.on and not turbo_now() then return false end
    T.on, T.slow, T.idle_since = false, nil, nil
    T.last_off = source
    set_turbo(false, source)
    return true
  end

  --- ★★ 施設の人の最初の台詞が出た（RX3-0241 / `nav_v0.lua` が呼ぶ）。戻り値: Turbo を頼んでいたか。
  --
  --   ★依頼者「最初のメッセージが発生した瞬間に高速化を解除する」。★Turbo の要求を切り、
  --   ⚠ 区間減速（talk）で既に normal でも、FCEUX へ normal を**もう一度**送る
  --     （★画面が送った区間減速の 400% を、画面の 0.5 秒を待たずに等速へ）。
  --   ★以後は局面が変わっても Turbo へ戻らない（`T.on` が false）。★画面は nav の `first_message` を見て、
  --     速度・音を開始前へ戻す（`auto_env.release`）。⚠ Turbo を頼んでいなければ何もしない。
  function T.first_message()
    local was = T.on or turbo_now()
    if not was then return false end
    T.stop("FIRST_MESSAGE")
    if speed ~= nil and speed.renormal ~= nil then speed.renormal() end
    say("[SPEED] FIRST_MESSAGE（★施設の人の最初の台詞 / 等速へ）")
    return true
  end

  --- ★届いた頼みを見る（⚠ `dev.lua` が受け取った瞬間に 1 回だけ呼ぶ）。
  function T.on_command(req)
    if req == nil then return end
    local action, params = req.action, req.params or {}
    if M.TOWN_ACTIONS[action] then
      if params.turbo == "1" then
        T.start((params.source ~= nil and params.source ~= "") and params.source or "TOWN")
      else
        T.stop("TURBO_OFF")               -- ★高速実行を切った頼み（⚠ 前の Turbo を残さない）
      end
    elseif action == "town_end" then
      if opts.wants ~= nil then opts.wants("town_end") end
      T.stop((params.source ~= nil and params.source ~= "") and params.source or "TOWN_END")
      if opts.stop_tasks ~= nil then opts.stop_tasks(req.seq) end
    elseif action == "load_state" then
      T.stop("LOAD")
    end
  end

  local function b_pressed()
    if not cancel_on_b or opts.pad == nil then return false end
    local ok, got = pcall(opts.pad)
    return ok and type(got) == "table" and got.B == true
  end

  --- ★毎フレーム（⚠ 機能より**後**に呼ぶ: nav の局面が今フレームのものになる）。
  function T.tick()
    local busy = opts.busy ~= nil and opts.busy() or false
    -- ★人が B（キーボードの D）を押した → 街の作業を止める（依頼者 §14）。⚠ 押した瞬間だけ
    local b = b_pressed()
    if b and not T.b_down and (T.on or busy) then
      T.cancels = T.cancels + 1
      say(string.format("[TOWN] 人が B を押したので止める（%d 回目）", T.cancels))
      T.stop("USER_CANCEL")
      if opts.stop_tasks ~= nil then opts.stop_tasks(nil) end
    end
    T.b_down = b
    if not T.on then return end
    -- ★遭遇したら、このフレームで普通の速さへ（依頼者 §15）。⚠ 画面を待たない
    if opts.battle ~= nil and opts.battle.in_encounter() then
      T.stop("BATTLE")
      return
    end
    -- ★区間減速（依頼者 §8）
    local ph = opts.phase ~= nil and opts.phase() or nil
    local slow = (ph ~= nil and slow_set[ph]) and ph or nil
    if slow ~= T.slow then
      T.slow = slow
      set_turbo(slow == nil, slow and ("SLOW_" .. upper(slow)) or T.source)
    end
    -- ⚠ 画面が黙った（★落ちた / 閉じた）ときに Turbo のまま残さない
    if busy then
      T.idle_since = nil
    else
      local now = clock()
      T.idle_since = T.idle_since or now
      if now - T.idle_since > lease then T.stop("LEASE") end
    end
  end

  --- ★state.json の `town_speed`。
  function T.status()
    return {turbo = turbo_now(), requested = T.on, source = T.source, slow = T.slow,
            last_off = T.last_off, cancels = T.cancels}
  end

  return T
end

return M
