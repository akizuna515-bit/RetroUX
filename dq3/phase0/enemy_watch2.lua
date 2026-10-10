-- 敵の行動を命令フックで観測する（Observation v2 / RX3-0383 / 2026-09-22）。
--
-- ## ⚠⚠ なぜもう 1 本作ったのか
--
--   ★`enemy_watch.lua`（v1）は毎フレーム RAM を読んで推し量る作りで、
--   ⚠ 4 回直しても**歩留まり 41%・偽が 3 分の 1** でした（`RX3-0382`）。
--   → ★v2 は「行動が決まって `$0558,X` に書かれる**命令**」だけを見ます。
--
-- ## ⚠ v1 と混ぜません（★依頼者 §20）
--
--   ```text
--   v1  work/runtime/dq3-probe/auto_v0.log    `AI actual ...`
--   v2  work/runtime/dq3-probe/enemy_action2.log  `AI action2 ...`   ★こちら
--   ```
--
--   ⚠⚠ 比べる間は**別々の記録**にします（★片方が片方を汚さない）。
--
-- ## ★仕掛ける先（JP bank 4 / ⚠ `enemy_hook.lua` の註に根拠）
--
--   ```text
--   $8AC7 / $8AF9 / $8B12   ★`.bs_enemy_turn` の中の `STA $0558,X`
--                           ⚠⚠ 3 か所（★2 つ目・3 つ目は**多回行動**）
--   ```
--
-- ⚠ `registerafter` は使いません（★dev.lua の 1 つだけ / `spell_watch.lua` と同じ約束）。

local function clean(p) return (p:gsub(string.char(92), "/"):gsub("/$", "")) end
local root = os.getenv("RETROUX_ROOT")
-- ⚠⚠ 開発機のパスへ落ちない（RX3-0466 / 2026-09-29）
if root == nil or root == "" then
  error("RETROUX_ROOT が立っていません（★起動は DQ3.cmd から / RX3-0466）")
end
root = clean(root)
local write_root = os.getenv("RETROUX_WRITE_ROOT")
write_root = (write_root ~= nil and write_root ~= "") and clean(write_root) or root

local Core = dofile(root .. "/dq3/phase0/core.lua")
local Hook = dofile(root .. "/dq3/phase0/enemy_hook.lua")
local HOST = rawget(_G, "DQ3_DEV")

local ME = "enemy_watch2"
local W2 = {}
W2.hook = Hook.new()

local LOG = Core.open_log(write_root .. "/work/runtime/dq3-probe/enemy_action2.log",
                          "敵の行動（命令フック / v2）")
local function write(line)
  if LOG == nil then return end
  local ok = pcall(function() LOG:write(line .. "\n"); LOG:flush() end)
  if not ok then LOG = nil end                 -- ⚠ 一度でも駄目なら、以後は書かない
end

--- ★行動 ID → 分類（⚠ auto_v0 の生成物から / 無ければ nil）。
local function category_of(move)
  if HOST == nil or HOST.ai_move_category == nil then return nil end
  local ok, got = pcall(HOST.ai_move_category, move)
  return ok and got or nil
end

local function battle_no()
  local b = HOST ~= nil and HOST.battle or nil
  return (type(b) == "table" and tonumber(b.battle_no)) or 0
end

--- ★いまのターン（⚠ auto_v0 が数えている / 無ければ 0）。
local function turn_no()
  if HOST == nil or HOST.ai_turn == nil then return 0 end
  local ok, got = pcall(HOST.ai_turn)
  return (ok and tonumber(got)) or 0
end

local last_battle, last_turn = nil, nil

--- ★★ 1 フレーム（⚠ **ここで文字にする** / callback の中ではしない）。
local function frame()
  local b, t = battle_no(), turn_no()
  if b ~= last_battle then
    -- ★戦闘が変わった: ⚠ 前の戦闘の内訳を**必ず**残す（0 件の理由が分かるように）
    if last_battle ~= nil then
      local s = Hook.stats_line(W2.hook)
      if s ~= nil then write(s) end
      -- ⚠⚠ **作り直しません**（★`install` の closure が古い入れ物を掴む / RX3-0383）
      Hook.reset(W2.hook)
    end
    last_battle, last_turn = b, nil
  end
  if t ~= last_turn then
    Hook.begin(W2.hook, b, t)
    last_turn = t
  end
  local rows = Hook.flush(W2.hook, category_of)
  for i = 1, #rows do write(rows[i]) end
  -- ★調べもの: ⚠ 終わりだけに書くと、FCEUX を閉じられたとき**何も残りません**
  if W2.dump_pc ~= nil or W2.dump_choice ~= nil then
    local f = emu.framecount()
    if f - (W2.dumped_at or 0) >= 1800 then
      W2.dumped_at = f
      if W2.dump_pc ~= nil then pcall(W2.dump_pc) end
      if W2.dump_choice ~= nil then pcall(W2.dump_choice) end
    end
  end
end

local function on_exit()
  local s = Hook.stats_line(W2.hook)
  if s ~= nil then write(s) end
  if W2.dump_pc ~= nil then pcall(W2.dump_pc) end   -- ★調べもの（⚠ 既定では無い）
end

--: ⚠⚠ 仕掛けられたか（★「置けなかった」を黙らせない）
local placed = Hook.install(W2.hook, memory, emu)

----------------------------------------------------------------------
-- ★★ 調べもの: **候補**と**採用**の差を測る（依頼者 §17 の A / B / C 判別）
--
--   ⚠⚠ **既定では動きません**（★`RETROUX_CHOICE_PROBE=1` のときだけ）。
--
--   ★JP bank 4 の行動を選ぶ本体（`_bA_s3`）:
--   ```text
--   $8943  JSR $8355   ★枠から 1 つ選ぶ
--   $8946  STA $4F     ← ★**候補**（A = 選ばれた move）
--   $8948  JSR $8466   ★成立するかの判定
--   $894D  BCS $895E   ★成立 → 採用
--   $8953  BNE $8943   ⚠⚠ **不成立 → もう一度選び直す**
--   $8955  LDA #$02    ⚠ 諦めて**通常攻撃**
--   ```
--
--   → ★候補の数と採用の数を比べれば、⚠ **どの行動が何回はじかれたか**が分かります。
----------------------------------------------------------------------
if os.getenv("RETROUX_CHOICE_PROBE") == "1" then
  local cand, giveup = {}, 0
  --: ★その場が本物か（⚠ バンク切り替え）
  local function here(pc, a, b, c)
    return memory.readbyte(pc) == a and memory.readbyte(pc + 1) == b
       and (c == nil or memory.readbyte(pc + 2) == c)
  end
  memory.registerexec(0x8946, 1, function()
    if not here(0x8946, 0x85, 0x4F) then return end
    local m = memory.getregister("a")
    if m ~= nil then cand[m] = (cand[m] or 0) + 1 end
  end)
  memory.registerexec(0x8955, 1, function()
    if not here(0x8955, 0xA9, 0x02) then return end
    giveup = giveup + 1
  end)
  W2.dump_choice = function()
    local rows = {}
    for m, n in pairs(cand) do rows[#rows + 1] = {m, n} end
    table.sort(rows, function(x, y) return x[2] > y[2] end)
    write("=== 候補に挙がった move（★採用とは限らない / 諦めて通常攻撃 "
          .. tostring(giveup) .. " 回）===")
    for _, r in ipairs(rows) do
      write(string.format("CAND move=%-4d n=%d", r[1], r[2]))
    end
  end
end

----------------------------------------------------------------------
-- ★★ 調べもの: `$0558` への書き込みを **PC 別に数える**（依頼者 §18）
--
--   ⚠⚠ **既定では動きません**（★`RETROUX_MOVE_WRITE_PROBE=1` のときだけ）。
--   ★知りたいのは 1 つ: ⚠ **本物の書き込み元を PC で一意に分けられるか**。
--   ⚠ 取りこぼしがあったとき、★どの PC を張り忘れたかが分かります。
----------------------------------------------------------------------
if os.getenv("RETROUX_MOVE_WRITE_PROBE") == "1" then
  local by_pc, seen = {}, 0
  local KNOWN = {[0x8AC7] = "selected_1", [0x8AF9] = "selected_2",
                 [0x8B12] = "selected_3", [0x81E7] = "sort_work",
                 [0x873A] = "force_attack", [0xA135] = "heal_work_1",
                 [0xA17B] = "heal_work_2", [0xA425] = "player_side"}
  --- ⚠ `registerwrite` の PC は**次の命令**（★`STA $0558,X` は 3 バイト）
  local function caller()
    local pc = memory.getregister("pc")
    if pc == nil then return -1 end
    local back = pc - 3
    if memory.readbyte(back) == 0x9D and memory.readbyte(back + 1) == 0x58
       and memory.readbyte(back + 2) == 0x05 then return back end
    return pc                          -- ⚠ 合わなければ**そのまま**（★黙って直さない）
  end
  for i = 0, 11 do
    memory.registerwrite(0x0558 + i, 1, function(addr, _sz, value)
      local pc = caller()
      local row = by_pc[pc]
      if row == nil then row = {n = 0, lo = 255, hi = -1, enemy = 0}; by_pc[pc] = row end
      row.n = row.n + 1
      if value < row.lo then row.lo = value end
      if value > row.hi then row.hi = value end
      local card = memory.readbyte(0x0540 + (addr - 0x0558))
      if card ~= nil and card >= 0x80 then row.enemy = row.enemy + 1 end
      seen = seen + 1
    end)
  end
  W2.dump_pc = function()
    local rows = {}
    for pc, row in pairs(by_pc) do rows[#rows + 1] = {pc, row} end
    table.sort(rows, function(x, y) return x[2].n > y[2].n end)
    write("=== $0558 への書き込み PC 別（total=" .. tostring(seen) .. "）===")
    for _, r in ipairs(rows) do
      write(string.format("PC=$%04X %-14s n=%-5d 敵の枠=%-4d 値 %d..%d",
                          r[1], KNOWN[r[1]] or "⚠unknown", r[2].n, r[2].enemy,
                          r[2].lo, r[2].hi))
    end
  end
end

if HOST ~= nil then
  HOST.features = HOST.features or {}
  HOST.features[#HOST.features + 1] = {name = ME, frame = frame, on_exit = on_exit}
  HOST.enemy_watch2 = W2
  if HOST.say ~= nil then
    HOST.say(string.format("★敵の行動を命令で見る（v2）: %d か所に置いた%s",
                           placed, placed == 3 and "" or "（⚠⚠ 3 か所のはず）"))
  end
end

return W2
