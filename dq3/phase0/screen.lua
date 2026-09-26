-- スクロールを反映して画面（32x30）を組み立てる（RX3-0016 / 2026-08-26）。
--
-- ## ⚠⚠ ネームテーブル 1 枚は「画面」ではない
--
--   窓は 30 行で折り返す。★折り返した窓は下辺が見つからないので、
--   ⚠ 検出器は「窓が無かった」として**黙って何も返さない**。
--   実測: NPC と会話中の画面で、会話窓が**丸ごと取れていなかった**。
--
-- ## ★なぜ部品にしたか
--
--   ⚠ 同じ計算を Lua と Python に別々に書くと、**片方だけ直る**。
--   ★ここに 1 本だけ置いて、`tests/test_dq3_screen_lua.py` が
--     **この Lua をそのまま動かして** `dq3rom/ppu.py` と突き合わせる。
--
-- ## スクロールの採り方
--
--   $2005 に書いているのは $CAEE（横）と $CAF4（縦）の 2 か所だけ（実測）。
--   ⚠ ラッチの順番で見分けるとずれることがあるので、★PC で見分ける。
--
-- 使い方:
--   local Screen = dofile(root .. "/dq3/phase0/screen.lua")
--   local screen = Screen.new()
--   screen.install()            -- ★$2005 / $2000 を見張る
--   local tiles = screen.read() -- ★32x30（1 始まり）

local M = {}

M.COLS = 32
M.ROWS = 30
M.PAGE = 1024

--: $2005 に書いているコード（★実測。`docs/design/dq3-findings.md`）
M.PC_SCROLL_X = 0xCAEE
M.PC_SCROLL_Y = 0xCAF4

local function toggle_h(n) if n % 2 == 0 then return n + 1 else return n - 1 end end
local function toggle_v(n) if n < 2 then return n + 2 else return n - 2 end end

--- 2 面ぶんのタイルから、いま映っている 32x30 を作る。
--
-- @param src   1 始まりの配列（2048 要素 = $2000-$27FF）
-- @param sx    横のスクロール（ピクセル）
-- @param sy    縦のスクロール（ピクセル）
-- @param base  左上の面（$2000 の下位 2 ビット）
--
-- ⚠ 8 ドット未満のずれは切り捨てる（★升目より細かいので読み取りに影響しない）。
-- ⚠ DQ3 は縦ミラー（MMC1 制御 = 0x0E / 実測）なので、面は `n % 2` で 2 枚に落ちる。
function M.compose(src, sx, sy, base)
  local COLS, ROWS = M.COLS, M.ROWS
  local tx0 = math.floor(sx / 8)
  local ty0 = math.floor(sy / 8)
  local out = {}
  for row = 0, ROWS - 1 do
    local ty, n = ty0 + row, base
    if ty >= ROWS then ty = ty - ROWS; n = toggle_v(n) end
    for col = 0, COLS - 1 do
      local tx, m = tx0 + col, n
      if tx >= COLS then tx = tx - COLS; m = toggle_h(m) end
      out[row * COLS + col + 1] = src[(m % 2) * M.PAGE + ty * COLS + tx + 1] or 0
    end
  end
  return out
end

--- 生の読み出し結果（文字列でも配列でも）を 1 始まりの配列にする。
function M.to_array(raw)
  if raw == nil then return nil end
  if type(raw) ~= "string" then return raw end
  local t = {}
  for i = 1, #raw do t[i] = raw:byte(i) end
  return t
end

function M.new()
  local self = {scroll_x = 0, scroll_y = 0, ctrl = 0}

  --- $2005 への書き込み。★PC で横縦を見分ける。
  function self.on_scroll(value, pc)
    if pc == M.PC_SCROLL_X then self.scroll_x = value
    elseif pc == M.PC_SCROLL_Y then self.scroll_y = value end
  end

  function self.on_ctrl(value) self.ctrl = value end

  function self.install()
    memory.registerwrite(0x2005, 1, function(addr, size, value)
      self.on_scroll(value, memory.getregister("pc"))
    end)
    memory.registerwrite(0x2000, 1, function(addr, size, value)
      self.on_ctrl(value)
    end)
  end

  --- いま映っている 32x30 を読む。⚠ 失敗したら nil。
  function self.read()
    local ok, raw = pcall(ppu.readbyterange, 0x2000, 2 * M.PAGE)
    if not ok then return nil end
    local src = M.to_array(raw)
    if src == nil then return nil end
    return M.compose(src, self.scroll_x, self.scroll_y, self.ctrl % 4)
  end

  --- 記録用（★どこを映していたかを後から辿れるように）。
  function self.where()
    return string.format("scroll=(%d,%d) nt=%d", self.scroll_x, self.scroll_y, self.ctrl % 4)
  end

  return self
end

return M
