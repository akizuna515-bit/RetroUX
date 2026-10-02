-- RX3-0486: 人のパッド入力（pad_input.lua）と B.tick の調停を、実機なしで確かめる。
-- ★`tests/test_dq3_pad_lua.py` が `lua_run.py` で動かす（⚠ cwd は repo の根）。
-- ⚠ 失敗は error で返す（★終了コード 1 になる）。

local failures = {}
local passed = 0
local function check(cond, msg)
  if cond then
    passed = passed + 1
  else
    failures[#failures + 1] = msg
  end
end

-- ★★ 読み込めるか（⚠ Lua 5.1 の local / upvalue の上限は読み込みで落ちる）
for _, p in ipairs({"dq3/phase0/dev.lua", "dq3/phase0/core.lua",
                    "dq3/phase0/pad_input.lua", "dq3/phase0/human_state.lua"}) do
  local f, err = loadfile(p)
  check(f ~= nil, "compile " .. p .. " " .. tostring(err))
end

local P = dofile("dq3/phase0/pad_input.lua")

-- ★偽のファイルと時計
local body = "0 0"
local opened, closed = 0, 0
local exists = true
local function fake_open(path, mode)
  if not exists then return nil end
  opened = opened + 1
  return {
    seek = function() return 0 end,
    read = function() return body end,
    close = function() closed = closed + 1 end,
  }
end
local t = 0
local R = P.new({path = "pad.txt", clock = function() return t end, open = fake_open})

check(R.tick() == nil, "mask 0 -> nil")
body = "1 17"; t = 0.01
local b = R.tick()
check(b ~= nil and b.up == true and b.A == true and b.B == nil, "up+A")
for k, v in pairs(b or {}) do check(v == true, "true だけ: " .. k) end

-- ★半端に読めたら前の値を保つ
body = "zz"; t = 0.02
b = R.tick()
check(b ~= nil and b.up == true, "half read keeps previous")

-- ★間のフレームは読まない（8 ms）
local before = opened
body = "2 17"; t = 0.021
R.tick()
check(opened == before, "8 ms 以内は開き直さない")

-- ⚠⚠ seq が 0.5 秒止まったら離す
body = "2 17"; t = 0.03
R.tick()                         -- seq 2 を読む（changed_at = 0.03）
t = 0.45
check(R.tick() ~= nil, "0.42 秒はまだ押している")
t = 0.54
check(R.tick() == nil, "0.5 秒止まったら離す")
check(R.stale_releases == 1, "離した回数")
check(closed >= 1, "離したら開き直す")

-- ★ターボ: フレームが速く回っても、seq が進んでいれば途切れない（★実時間で見る）
local seq = 3
local held = true
for i = 1, 3000 do
  t = 1.0 + i * 0.0003            -- ★1 フレーム 0.3 ms（≒ 3300 fps）
  if i % 50 == 0 then seq = seq + 1 end   -- ★15 ms ごとに書く（RetroUX の 60 Hz）
  body = seq .. " 1"
  local got = R.tick()
  if got == nil or got.up ~= true then held = false end
end
check(held, "ターボ中の長押しが途切れない")

-- ★ファイルが無ければ触らない
exists = false
local R2 = P.new({path = "none", clock = function() return 0 end, open = fake_open})
check(R2.tick() == nil, "ファイルが無い -> nil")
exists = true

-- ★reset
R.reset()
check(R.mask == 0, "reset で捨てる")

-- ======================================================================
-- ★B.tick の調停（⚠ joypad.set は 1 か所 / 自動を優先 / false を渡さない）
-- ======================================================================
local frame = 0
emu = {framecount = function() return frame end}
memory = {readbyte = function() return 0 end}
local sets = {}
joypad = {set = function(port, tbl) sets[#sets + 1] = tbl end}
local Core = dofile("dq3/phase0/core.lua")
local B = Core.new_buttons({})
local human = {up = true}
B.pad = function() return human end

frame = 1; B.tick()
check(#sets == 1 and sets[1].up == true, "誰も握っていなければ人の入力を渡す")
B.tick()
check(#sets == 1, "同じフレームで 2 回渡さない")
B.claim("auto"); frame = 2; B.tick()
check(#sets == 1 and B.human_blocked == 1, "自動が握っていれば渡さない")
B.press("auto", "A"); frame = 3; B.tick()
check(#sets == 2 and sets[2].A == true and sets[2].up == nil, "自動は自分のキーだけ")
B.release("auto"); human = nil; frame = 4; B.tick()
check(#sets == 2, "人が押していなければ joypad.set を呼ばない")
for _, tbl in ipairs(sets) do
  for k, v in pairs(tbl) do check(v == true, "false を渡さない: " .. k) end
end
B.pad = function() error("壊れた") end
frame = 5
local ok = pcall(B.tick)
check(ok, "パッドが落ちても B.tick は落ちない")

print(string.format("PAD_TEST passed=%d failed=%d", passed, #failures))
if #failures > 0 then
  error("NG: " .. table.concat(failures, " / "))
end
