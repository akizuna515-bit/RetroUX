-- 点滅しているカーソルを捕まえる（RX3-0015 / 2026-08-27）。
--
-- ## ★★ 依頼者の着想
--
--   「窓が開いている場合、カーソルが点滅しているのだけど、
--    そのカーソルが点滅している、というのを捕まえられない？
--    その点滅の右がコマンドの内容なんだけど」
--
-- ## ★実測で裏が取れた（`work/dq3-probe/ppu_trace.txt`）
--
--   VRAM への書き込みを数えると、**動いているものと止まっているもの**が
--   はっきり分かれる。
--
--     $2289 = 画面(9,20)   72 を 24 回 / 00 を 19 回  → ★点滅している
--     $228D = 画面(13,20)  72 を 16 回 / 00 を 14 回  → ★点滅している
--     $22C5 = 画面(5,22)   72 を  1 回 / 00 を  0 回  → ⚠ **点いたまま**
--
--   時系列も `72×8 → 00×8 → 72×8` ときれい。
--
-- ⚠⚠ **これが分かると、座標の計算を捨てられる。**
--
--   これまで: 目当ての文字を探し → その 1 つ左を計算し → カーソルと比べる
--             ⚠ 画面に ▶ が複数あると、どれが本物か分からなかった
--             （★実際、静止した ▶ を本物と勘違いして 何も進まなかった）
--
--   これから: **点滅している 1 つ**を本物とみなす。
--             ★その右を読めば「いま何が選ばれているか」がそのまま分かる。
--
-- ## ⚠ 気をつけること
--
--   - 点滅を見分けるには**何フレームか観る**必要がある（★1 枚では決まらない）
--   - カーソルが動くと、前の位置は点滅を止める
--     → ★**いちばん最近変化した**ところを本物とする

local M = {}

--: ★▶ 右向き三角。**点滅する**のがこれ（⚠ 実測で確認）
M.CURSOR = 0x72
--: ★▼ 下向き三角 ＝ **メッセージ送り**。A か B で送る（2026-08-27 / 依頼者）
M.MORE = 0x73
--: ⚠ → 別画面への誘導。★カーソルと混同しない
M.LINK = 0x84
M.COLS = 32
M.ROWS = 30

--: ★文字のタイルはここ未満（⚠ 0x70 以上は記号と枠）
M.TEXT_MAX = 0x70
--: ★★ 例外: 0x70 以上でも文字（RX3-0209 / 2026-09-12 依頼者「save1 まんたんでキアリーが中断される」）。
--:   ★長音「ー」は 0x7F（キアリー = 41 3D 32 7F）。⚠ カーソル（72）・枠（76〜7E）は文字にしない
--:   ★生成物の名前の表で 0x70 以上なのは 0x7F だけ（2026-09-12 に数えた）
M.TEXT_EXTRA = {[0x7F] = true}

--: ⚠ これだけ「点いた・消えた」を見たら点滅とみなす
M.BLINKS_NEEDED = 2

--: ⚠ 見た値をどれだけ覚えておくか（★古い点滅を引きずらない）
M.FORGET_AFTER = 240


local function at(nt, x, y)
  if nt == nil or x < 0 or y < 0 or x >= M.COLS or y >= M.ROWS then return nil end
  return nt[y * M.COLS + x + 1]
end

M.at = at


--- ★カーソルの右にある文字を読む（生のタイルのまま）。
--
--   ⚠ 文字にするのはあとから。★ここでは並びだけ返す。
--   空白（0）や枠に当たったら終わり。
function M.label_at(nt, x, y, limit)
  local out = {}
  for k = 1, (limit or 12) do
    local v = at(nt, x + k, y)
    if v == nil then break end
    if v == 0 or (v >= M.TEXT_MAX and not M.TEXT_EXTRA[v]) then
      -- ⚠ 語の間の空白 1 つは飛ばす（★「たたかう  にげる」の間）
      if #out > 0 then break end
    else
      out[#out + 1] = v
    end
  end
  return out
end



--- ★VRAM の番地を画面の升に直す（⚠ スクロールを効かせる）。
--
--   ⚠⚠ DQ3 の鏡写しは **vertical**（`DREG[0] & 3 == 2`）。
--   ★2 つの面が**横に並ぶ**ので、$2400 側は右隣の面になる。
--   ⚠ $2800 / $2C00 は $2000 / $2400 と**同じ場所**（★鏡写し）。
--
--   戻り値: 画面の x, y（⚠ 画面の外／属性の番地なら nil）
function M.to_screen(addr, sx, sy, base)
  if addr == nil or addr < 0x2000 or addr >= 0x3000 then return nil end
  local page = math.floor((addr - 0x2000) / 0x400) % 2   -- ★鏡写しで 2 面
  local off = (addr - 0x2000) % 0x400
  if off >= 0x3C0 then return nil end                    -- ⚠ 属性は文字ではない
  local col, row = off % 32, math.floor(off / 32)
  -- ⚠⚠ **面 0 が左とは限らない。**
  --
  --   ★左上に映る面は `$2000` の下位 2 ビットが決める（`screen.lua` の `base`）。
  --   ⚠ ここを 0 と決めつけていたので、⚠ 面 1 を映しているあいだ
  --     **カーソルが「画面の外」になり、まんたんが「点滅していない」と諦めた**
  --     （2026-08-29 / 実機。`$2083=(nil,nil)` と記録が残った）。
  --   ★実測: 左上が面 1、横スクロール 23 升のとき、
  --     `$2083`（面 0 の 3 列目）は**画面の 12 列目**＝「じゅもん」の位置。
  local rel = (page - ((base or 0) % 2)) % 2
  local wx = rel * 32 + col
  local cx = (wx - math.floor((sx or 0) / 8)) % 64
  local cy = (row - math.floor((sy or 0) / 8)) % 30      -- ⚠ 縦は 30 行で回る
  if cx >= M.COLS or cy >= M.ROWS then return nil end
  return cx, cy
end

--- ★見張りを作る。
function M.new()
  local self = {
    last = {},          -- 位置 -> 直前に見えていたか
    blinks = {},        -- 位置 -> 「点いた・消えた」を見た回数
    changed = {},       -- 位置 -> 最後に変わったフレーム
    frames = 0,
    -- ★書き込みから見るほう（⚠ こちらが本命）
    wrote = {},         -- VRAM 番地 -> 直前に書かれた値
    vram_blinks = {},   -- VRAM 番地 -> 入れ替わりを見た回数
    vram_changed = {},  -- VRAM 番地 -> 最後に入れ替わったフレーム
    by_writes = false,  -- ★hook を入れた
    hook_alive = false,
    sx = 0, sy = 0,     -- ⚠ 画面の升に直すのに要る
    base = 0,           -- ⚠⚠ 左上に映っている面（★0 とは限らない）
  }

  --- ⚠ いまのスクロールを教える（★`screen.lua` の `where()` から）。
  function self.set_scroll(sx, sy, base)
    self.sx, self.sy = sx or 0, sy or 0
    -- ⚠ 面を渡さない呼び出しは、★前に教わった面をそのまま使う
    if base ~= nil then self.base = base % 2 end
  end

  --- ★毎回呼ぶ。⚠ 呼ばないと点滅を見つけられない。
  function self.update(nt)
    if nt == nil then return end
    self.frames = self.frames + 1
    -- ★書き込みが**実際に届いているなら**、画面の走査は要らない。
    --   ⚠ 毎フレーム 960 マス比べるのは実機で重い（★60fps で 5.7 万回/秒）。
    --
    -- ⚠⚠ 「hook を入れた」ではなく「**届いた**」で切り替えること。
    --   ★入れただけで切り替えたら、張りぼての `registerwrite` を渡された
    --   足場で**何も見えなくなりました**（2026-08-27 に実際に踏んだ）。
    if self.hook_alive then return end
    for y = 0, M.ROWS - 1 do
      for x = 0, M.COLS - 1 do
        local pos = y * M.COLS + x
        local on = at(nt, x, y) == M.CURSOR
        local was = self.last[pos]
        if was == nil then
          -- ★初めて見た位置。⚠ ここで数えると「出現」を点滅と誤解する
          self.last[pos] = on
        elseif was ~= on then
          self.last[pos] = on
          self.blinks[pos] = (self.blinks[pos] or 0) + 1
          self.changed[pos] = self.frames
        end
      end
    end
  end

  --- ★★ CPU が PPU に書く様子から点滅を捕まえる。
  --
  --   ⚠⚠ 依頼者の指摘（2026-08-27）:
  --     「点滅については CPU が PPU に指令を送っているはずだから、
  --      動きで捉えられると思うんだよな」
  --
  --   ★そのとおりで、こちらのほうが**速くて確実**。
  --     画面を眺める方法は「点いた・消えた」を 2 回見るまで
  --     ⚠ 最短でも十数フレームかかる（★点滅の周期が 8 フレーム）。
  --     書き込みなら **72 と 00 が同じ番地に来た瞬間**に決まる。
  --
  --   ⚠ 実証済み: `research/probes/active/dq3_ppu_trace.lua` が
  --     この仕掛けで `work/dq3-probe/ppu_trace.txt` を採っている。
  function self.install_writes()
    if memory == nil or memory.registerwrite == nil then return false end
    local latch, vram = 0, 0
    memory.registerwrite(0x2006, 1, function(_, _, value)
      if latch == 0 then
        vram = (value * 256) % 16384
        latch = 1
      else
        vram = (vram - (vram % 256)) + value
        latch = 0
      end
    end)
    memory.registerwrite(0x2007, 1, function(_, _, value)
      -- ★ここに来た＝hook が本当に効いている（⚠ 入れただけでは分からない）
      self.hook_alive = true
      self.saw_write(vram, value)
      -- ⚠ 進む量は $2000 の bit2 で 1 か 32。★文字を書くときは 1
      vram = (vram + 1) % 16384
    end)
    self.by_writes = true
    return true
  end

  --- ★1 回の書き込みを覚える。⚠ カーソルの出し入れだけ拾う。
  function self.saw_write(addr, value)
    if value ~= M.CURSOR and value ~= 0 then return end
    local was = self.wrote[addr]
    self.wrote[addr] = value
    if was ~= nil and was ~= value then
      -- ★同じ番地が 72 → 00 → 72 と動いた。⚠ これが点滅
      self.vram_blinks[addr] = (self.vram_blinks[addr] or 0) + 1
      self.vram_changed[addr] = self.frames
    end
  end

  --- ★書き込みから見た、点滅しているカーソルの番地。⚠ 無ければ nil。
  function self.active_vram()
    local best, best_at = nil, -1
    for addr, n in pairs(self.vram_blinks) do
      if n >= M.BLINKS_NEEDED then
        local when = self.vram_changed[addr] or 0
        if self.frames - when <= M.FORGET_AFTER and when > best_at then
          best, best_at = addr, when
        end
      end
    end
    return best
  end

  --- ★点滅しているカーソルの位置。⚠ 見つからなければ nil。
  --
  --   複数あれば**いちばん最近変わったもの**を返す
  --   （★カーソルが動くと、前の位置は点滅を止めるため）。
  function self.active(sx, sy)
    -- ★★ 書き込みから分かるなら、そちらを先に使う（⚠ 速くて確実）
    local addr = self.active_vram()
    if addr ~= nil then
      local x, y = M.to_screen(addr, sx or self.sx, sy or self.sy,
                               self.base)
      if x ~= nil then return x, y end
      -- ⚠ 画面の外なら、画面を眺めるほうへ落ちる
    end
    local best, best_at = nil, -1
    for pos, n in pairs(self.blinks) do
      if n >= M.BLINKS_NEEDED then
        local when = self.changed[pos] or 0
        if self.frames - when <= M.FORGET_AFTER and when > best_at then
          best, best_at = pos, when
        end
      end
    end
    if best == nil then return nil end
    return best % M.COLS, math.floor(best / M.COLS)
  end

  --- ★いま選ばれているものの文字（生のタイル）。⚠ 分からなければ nil。
  function self.selected(nt)
    local x, y = self.active()
    if x == nil then return nil end
    return M.label_at(nt, x, y), x, y
  end

  --- ⚠ 段が変わったら忘れる（★前の段の点滅を引きずらない）。
  function self.forget()
    self.last = {}
    self.blinks = {}
    self.changed = {}
    self.wrote = {}
    self.vram_blinks = {}
    self.vram_changed = {}
  end

  --- ★いま何を見張っているか（⚠ 記録に残すため）。
  function self.report()
    local parts = {}
    for addr, n in pairs(self.vram_blinks) do
      if n >= M.BLINKS_NEEDED then
        local x, y = M.to_screen(addr, self.sx, self.sy, self.base)
        parts[#parts + 1] = string.format("$%04X=(%s,%s)x%d", addr,
          tostring(x), tostring(y), n)
      end
    end
    for pos, n in pairs(self.blinks) do
      if n >= M.BLINKS_NEEDED then
        parts[#parts + 1] = string.format("(%d,%d)x%d",
          pos % M.COLS, math.floor(pos / M.COLS), n)
      end
    end
    table.sort(parts)
    if #parts == 0 then
      return self.by_writes and "点滅なし（★書き込みを見張り中）" or "点滅なし"
    end
    return table.concat(parts, " ")
  end

  return self
end


--- ★2 つのタイル列が同じか。
function M.same(a, b)
  if a == nil or b == nil then return false end
  if #a ~= #b then return false end
  for i = 1, #a do
    if a[i] ~= b[i] then return false end
  end
  return true
end


--- ★片方がもう片方で始まっているか（⚠ 後ろに別の語が続く並びのため）。
function M.starts_with(a, b)
  if a == nil or b == nil or #b == 0 or #a < #b then return false end
  for i = 1, #b do
    if a[i] ~= b[i] then return false end
  end
  return true
end




--- ★メッセージ送りの ▼ が出ているか。⚠ 出ていれば A か B で送れる。
function M.waiting_message(nt)
  if nt == nil then return nil end
  for y = 0, M.ROWS - 1 do
    for x = 0, M.COLS - 1 do
      if at(nt, x, y) == M.MORE then return x, y end
    end
  end
  return nil
end

return M
