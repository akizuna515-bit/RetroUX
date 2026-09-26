-- MAP をゲーム内のタイルで描くための材料を書き出す（RX3-0043 / 2026-09-01）。
--
-- ## ⚠⚠ なぜ要るのか
--
--   ★`RX3-0032` で「升 1 バイト → 16x16 の絵」は解けました。
--   ⚠ ですが材料が**全部、実行時の RAM / PPU にしかありません**。
--
--   ```text
--   $7200   tileset       4 バイト x 64        256 バイト
--   $7300   パレット組    1 バイト x 索引       64 バイト
--   $7400   地図          1 升 1 バイト        （地図の広さ）
--   CHR-RAM 絵柄                              8192 バイト
--   $3F00   PPU パレット                        32 バイト
--   ```
--
--   → ★ここが「Lua しか読めないもの」を Python へ渡す唯一の場所です。
--
-- ## ⚠⚠ 0.5 秒ごとに 8KB を送りません（指示書 §3.2）
--
--   ★書くのは **地図が変わったとき**だけです。
--
--   ```text
--   地図が変わった   map_id か kind が変わった
--   CHR が変わった   ⚠ 簡単な checksum で見る（★ハッシュは使わない）
--   ```
--
-- ## ⚠⚠ 「変わった瞬間」に取ってはいけません（RX3-0046 / 2026-09-02）
--
--   ★DQ3 は地図を切り替えるとき**画面を暗転させます**。
--   ⚠ 変わった瞬間に取ると `$3F00` が全部 `$0F`（黒）で、
--     **升は正しいのに絵が真っ黒**になります（★依頼者の実機で発生）。
--
--   → ★地図とパレットが**落ち着いてから**取ります（`M.SETTLE`）。
--   → ⚠ それでも暗転していたら**書かず**、★明るくなってから取り直します。
--
--   ⚠ CHR は**変わったときだけ**別ファイルへ書きます。
--     ★変わっていなければ、`map_art.json` に「前と同じ」とだけ書きます。
--
-- ## ★置き場（⚠ 通常の state.json とは分ける / 指示書 §3.3）
--
--   ```text
--   work/dq3-probe/map_art.json   ★小さい情報（⚠ 毎回書く）
--   work/dq3-probe/map_art.bin    ⚠ CHR 8KB（★変わったときだけ）
--   ```
--
--   ⚠ どちらも「一時ファイルへ書いて置き換える」（★読み途中の欠けを避ける）。

local M = {}

--: ★カートリッジ RAM は $6000 から
local TILESET_ADDR, PALETTE_ADDR, MAP_ADDR = 0x7200, 0x7300, 0x7400
--: ★それぞれの長さ
local TILESET_LEN, PALETTE_LEN = 256, 256
--: ★CHR-RAM
local CHR_LEN = 0x2000
--: ★PPU のパレット
local PRAM_ADDR, PRAM_LEN = 0x3F00, 32

--: ★居場所（⚠ `dq3rom/profiles/…json` と同じ番地）
local A_KIND, A_MAPNO = 0x002F, 0x008B
local A_W, A_H = 0x0088, 0x0089
local KIND_LOCAL = 1
local KIND_WORLD = 0      -- ★上の世界の世界地図（RX3-0061）
--: ★アレフガルド（下の世界）の世界地図
--
--   ⚠⚠ 2026-09-20（RX3-0316）訂正: ここには「★世界タイルの対応表が要る」と
--     書いてありましたが、**ROM と実機セーブで測ったところ誤りでした**。
--
--   ```text
--   $9A tileset      ★アレフガルドでも 0（= 上の世界と同じ道）
--   $7200 / $7300    ★上の世界と**全バイト一致**
--   画面 vs ROM      ★world_alefgard と 181/181 一致（world_main は 118/181 の偶然一致）
--   ```
--
--   → ★対応表（`data/dq3/world-metatiles.json`）は**そのまま使えます**。
--   ⚠ 違うのは **CHR の絵柄とパレット**だけ（★タイル 141〜226 が全部相違）。
--     → ★だから「アレフガルドに居るときに取り直す」だけで済みます。
local KIND_ALEFGARD = 2

--- ★「地図の中」か（⚠ 世界 0 / アレフガルド 2 以外はすべて地図の中）。
--
--   ⚠⚠ 2026-09-07（RX3-0103）: `kind == 1` だけを見ていたので、
--     ★洞窟（kind = 5）で**材料を 1 度も書き出していません**でした。
--     → 依頼者の画面では、⚠ 地図は出るのに **CHR が出ない**。
--   ★実測（DQ3_J.fc6 / fc7）: kind=5 / map_no=45 / 58x40 で、
--     ⚠ ROM の area map 45 と**寸法が一致**（★番号も寸法も正しい）。
local function is_local(kind)
  return kind ~= nil and kind ~= KIND_WORLD and kind ~= KIND_ALEFGARD
end

--- ★「世界地図」か（⚠ 上の世界 0 と アレフガルド 2 / RX3-0316）。
--
--   ⚠⚠ ここが無かったので、★`kind == KIND_WORLD` を**2 か所に別々に**書いていました。
--     → ⚠ アレフガルドは、どちらの門でも黙って落ちていました。
local function is_world(kind)
  return kind == KIND_WORLD or kind == KIND_ALEFGARD
end

--: ⚠ 何フレームに 1 回**見る**か（★書くのは変わったときだけ）
M.EVERY = 30

--: ⚠⚠ 何回続けて同じなら「落ち着いた」とみなすか（RX3-0046 / 2026-09-02）
--
--   ★DQ3 は地図を切り替えるとき **画面を暗転させます**。
--   ⚠⚠ 「地図が変わった瞬間」＝「パレットが真っ黒な瞬間」でした。
--
--   ```text
--   ① map 9 → map 109 (5,21)
--   ★MAP の材料を書きました（1/109/26x26 …）   ⚠ 広さが**前の地図のまま**
--   ★MAP の材料を書きました（1/109/8x6 …）     ⚠ パレットは全部 $0F
--   ```
--
--   ⚠ `$8B`（地図番号）と `$88/$89`（広さ）の更新もずれます。
--   → ★地図とパレットが**続けて同じ**になるまで待ちます。
M.SETTLE = 2

--: ⚠ これだけ見送っても落ち着かなければ、★暗転でなければ書く
--
--   ⚠⚠ 「落ち着くまで待つ」だけにすると、★永遠に書かない道が残ります。
M.PATIENCE = 10

--- ★16 進の文字列にする（⚠ `string.format` を 1 バイトずつ呼ぶと遅い）。
local HEX = "0123456789abcdef"
local function to_hex(s)
  if s == nil then return nil end
  local out = {}
  for i = 1, #s do
    local b = s:byte(i)
    local hi = math.floor(b / 16) + 1
    local lo = (b % 16) + 1
    out[i] = HEX:sub(hi, hi) .. HEX:sub(lo, lo)
  end
  return table.concat(out)
end

--- ★番地から n バイト読む（⚠ 一括。★2026-09-01 実機で確認）。
--
--   ⚠ 1 バイトずつ読むと 8192 回の呼び出しになります。
--   ★`memory.readbyterange` / `ppu.readbyterange` は **string** を返します。
local function read_ram(addr, n)
  local ok, got = pcall(memory.readbyterange, addr, n)
  if not ok or type(got) ~= "string" or #got ~= n then return nil end
  return got
end

--- ★CHR-RAM を読む（⚠ PPU 側の入口。★実機で 8192 バイト取れた）。
local function read_chr()
  local ok, got = pcall(ppu.readbyterange, 0x0000, CHR_LEN)
  if not ok or type(got) ~= "string" or #got ~= CHR_LEN then return nil end
  return got
end

--- ★PPU のパレットを読む。
local function read_pram()
  local ok, got = pcall(ppu.readbyterange, PRAM_ADDR, PRAM_LEN)
  if not ok or type(got) ~= "string" or #got ~= PRAM_LEN then return nil end
  return got
end

--- ★簡単な checksum（⚠ ハッシュは使わない / 指示書 §3.2）。
--
--   ⚠⚠ 足すだけだと、★並べ替えに気づきません。
--     → ★位置で重みを付けます（⚠ それでも「衝突しない」とは言いません）。
function M.checksum(s)
  local a, b = 1, 0
  for i = 1, #s do
    a = (a + s:byte(i)) % 65521
    b = (b + a) % 65521
  end
  -- ⚠⚠ Lua 5.1 の `string.format("%d")` は **32bit で折り返します**。
  --   ★2^31 を超えると JSON に `-2147483648` と書かれました（2026-09-02 実測）。
  --   → ⚠ 31bit に収めます（★変化を見るにはこれで足ります）。
  return (b * 65536 + a) % 2147483648
end

--- ★★ 画面が暗転しているか（RX3-0046 / 2026-09-02）。
--
--   ```text
--   $0F $1F $2F $3F   ★黒
--   $0D $1D $2D $3D   ⚠ 「黒より黒い」
--   ```
--
--   ⚠⚠ **32 個ぜんぶが黒のときだけ**「暗転」とみなします。
--     ★1 つでも色があれば、暗い部屋であって暗転ではありません。
--
--   ⚠ ここで止めないと、64 索引すべての絵が真っ黒になります
--     （★依頼者の実機で実際にそうなった / `pram` = `0f` x 32）。
function M.is_dark(pram)
  if pram == nil or #pram == 0 then return true end
  for i = 1, #pram do
    local c = pram:byte(i) % 16
    if c ~= 0x0F and c ~= 0x0D then return false end
  end
  return true
end

--- ★★ 色が無いか（RX3-0061 / 2026-09-03）。
--
--   ⚠⚠ `is_dark` は「**32 個ぜんぶが黒**」しか弾きません。
--     ★戦闘に入る一瞬の**白い画面**は素通りします。
--
--   ```text
--   2026-09-03 の実機（依頼者「世界地図に色がない」）
--     ローカル  0F 30 11 21 0F 27 37 15 …   ★正しい
--     世界      00 30 00 10 00 10 20 20 …   ⚠ 下位 4bit が全部 0
--                                            ＝ NES パレットの灰色の列
--   ```
--
--   ⚠ 町を出た直後に戦闘へ入る一瞬で取っており、★`map_key` が変わらない
--     ためその回は最後まで白黒のままでした。
--   → ★ここで見送れば、⚠ `last_key` が進まないので**次の tick で取り直します**。
function M.is_colorless(pram)
  if pram == nil or #pram == 0 then return true end
  for i = 1, #pram do
    if pram:byte(i) % 16 ~= 0 then return false end
  end
  return true
end

--- ★書き出す 1 回ぶん。
--
-- @param opts.dir        ★置き場
-- @param opts.say        ⚠ 記録（★省くと黙る）
-- @param opts.json       ★`core.json`
-- @param opts.in_battle  ⚠ 戦闘中かを返す関数（★省くと見ない）
function M.new(opts)
  opts = opts or {}
  local self = {
    dir = opts.dir,
    say = opts.say or function() end,
    json = opts.json,
    every = opts.every or M.EVERY,
    settle = opts.settle or M.SETTLE,
    patience = opts.patience or M.PATIENCE,
    in_battle = opts.in_battle,
    frames = 0,
    -- ⚠ 前回書いたときの目印（★変わっていなければ書かない）
    last_key = nil,
    chr_sum = nil,
    writes = 0,
    chr_writes = 0,
    skipped = 0,
    last_error = nil,
    -- ⚠ 落ち着くまで待つための覚え（★`M.SETTLE`）
    settling = nil,
    settled = 0,
    waiting = 0,
    darks = 0,
    grays = 0,
    -- ⚠ 同じ理由を 30 フレームごとに言わない（★記録が埋まる）
    said_error = nil,
  }

  --- ⚠ 一時ファイルへ書いて置き換える（★読み途中の欠けを避ける）。
  local function put(name, text, mode)
    local tmp = self.dir .. "/" .. name .. ".tmp"
    local fh = io.open(tmp, mode or "w")
    if fh == nil then
      self.last_error = "⚠ 書けません: " .. tmp
      return false
    end
    fh:write(text)
    fh:close()
    os.remove(self.dir .. "/" .. name)
    local ok = os.rename(tmp, self.dir .. "/" .. name)
    if not ok then
      self.last_error = "⚠ 置き換えられません: " .. name
      return false
    end
    return true
  end

  --- ★いまの地図の目印（⚠ これが変わったら書き直す）。
  --
  --   ## ⚠⚠ 世界地図では色も鍵に入れます（RX3-0316 / 2026-09-20）
  --
  --     ★世界地図では `$8B`（map 番号）も `$88/$89`（広さ）も**前の地図の残り**です。
  --     ⚠ だから、世界地図に居るあいだ鍵は**ずっと同じ**になり、
  --     ⚠⚠ **CHR が差し替わっても色が変わっても、材料を 1 度も書き直しません**でした。
  --
  --     ★依頼者「ストーリー的にたしか夜の世界から昼の世界に変わるのでそれもある」。
  --     → ★世界地図のときだけ、**パレットの一部**の checksum を鍵に足します。
  --
  --   ## ⚠⚠ パレット全部を鍵にしてはいけません
  --
  --     ★組 0・組 1（`$3F00`〜`$3F07`）は **海のアニメーション**で毎回変わります
  --     （★実測: 同じ世界の同じ場所でも `0F 30 30 30` / `0F 30 0C 1C` / `0F 30 01 11`）。
  --     ⚠ 全部を鍵にすると**毎 tick 書き直し**になり、「送らない」仕組みが死にます。
  --
  --     → ★動かない **組 2・組 3（`$3F08`〜`$3F0F`／陸・林・山）**だけを見ます。
  --       ★実測: アレフガルドは `0F 00 0F 19` / `0F 19 09 17`、
  --              上の世界は `0F 10 00 2A` / `0F 2A 19 27`（⚠ はっきり違う）。
  --     ⚠ CHR（8192 バイト）は毎回数えると重いので足しません
  --       （★CHR の差は `write_world` の中の `chr_sum` が見ています）。
  local PRAM_STABLE_FROM, PRAM_STABLE_TO = 9, 16   -- ★1 始まり（= $3F08..$3F0F）

  local function map_key()
    local kind = memory.readbyte(A_KIND)
    local tail = ""
    if is_world(kind) then
      local pram = read_pram()
      local part = pram and pram:sub(PRAM_STABLE_FROM, PRAM_STABLE_TO) or nil
      tail = "/p" .. tostring(part and M.checksum(part) or -1)
    end
    return string.format("%d/%d/%dx%d%s",
      kind, memory.readbyte(A_MAPNO),
      memory.readbyte(A_W), memory.readbyte(A_H), tail)
  end

  --- ★★ 1 回書く。⚠ 戻り値は `ok`。
  function self.write_now()
    local kind = memory.readbyte(A_KIND)
    if is_world(kind) then
      -- ★世界地図（RX3-0061 / 2026-09-02）: `$7200`/`$7400` は前の地図の残りなので**使わない**。
      --   ★CHR とパレットだけ書き、升と tileset は Python が ROM の世界地図と `data/dq3/world-metatiles.json` から作る。
      --   ★アレフガルド（2）も同じ道（RX3-0316 / ⚠ 対応表は同じ・CHR とパレットだけ別）。
      return self.write_world(kind)
    end
    local w, h = memory.readbyte(A_W), memory.readbyte(A_H)
    if w == nil or h == nil or w == 0 or h == 0 or w * h > 4096 then
      self.last_error = "⚠ 地図の広さが変です: " .. tostring(w) .. "x" .. tostring(h)
      return false
    end

    -- ⚠ 戦闘中は CHR が**敵の絵**に入れ替わっています（★地図の絵ではない）
    if self.in_battle ~= nil then
      local ok_b, fighting = pcall(self.in_battle)
      if ok_b and fighting then
        self.last_error = "⚠ 戦闘中なので見送りました（★CHR が敵の絵）"
        return false
      end
    end

    local chr = read_chr()
    local pram = read_pram()
    if chr == nil or pram == nil then
      self.last_error = "⚠ CHR / パレットを読めません（★この FCEUX の API）"
      return false
    end

    -- ⚠⚠ **暗転中は取りません**（RX3-0046）。
    --   ★取ると 64 索引すべての絵が真っ黒になります。
    --   ⚠ `last_key` を進めないので、★明るくなれば次の tick で取り直します。
    if M.is_dark(pram) then
      self.last_error = "⚠ 暗転中なので見送りました（★明るくなったら取り直します）"
      self.darks = self.darks + 1
      return false
    end
    if M.is_colorless(pram) then
      self.last_error = "⚠ 色の無い一瞬なので見送りました（★戦闘に入る所など）"
      self.grays = self.grays + 1
      return false
    end

    -- ★CHR は**変わったときだけ**書く（⚠ 8KB を毎回は送らない）
    local sum = M.checksum(chr)
    local chr_written = false
    if sum ~= self.chr_sum then
      if not put("map_art.bin", chr, "wb") then return false end
      self.chr_sum = sum
      self.chr_writes = self.chr_writes + 1
      chr_written = true
    end

    local body = {
      kind = kind,
      map_id = memory.readbyte(A_MAPNO),
      width = w,
      height = h,
      chr_checksum = sum,
      chr_written = chr_written,
      tileset = to_hex(read_ram(TILESET_ADDR, TILESET_LEN)),
      palette_group = to_hex(read_ram(PALETTE_ADDR, PALETTE_LEN)),
      pram = to_hex(pram),
      map = to_hex(read_ram(MAP_ADDR, w * h)),
    }
    if not put("map_art.json", self.json(body)) then return false end
    self.writes = self.writes + 1
    self.last_key = map_key()
    return true
  end

  --- ★世界地図の材料（CHR + パレットだけ）。★RX3-0061
  function self.write_world(kind)
    if self.in_battle ~= nil then
      local ok_b, fighting = pcall(self.in_battle)
      if ok_b and fighting then
        self.last_error = "⚠ 戦闘中なので見送りました（★CHR が敵の絵）"
        return false
      end
    end
    local chr = read_chr()
    local pram = read_pram()
    if chr == nil or pram == nil then
      self.last_error = "⚠ CHR / パレットを読めません（★この FCEUX の API）"
      return false
    end
    if M.is_dark(pram) then
      self.last_error = "⚠ 暗転中なので見送りました（★明るくなったら取り直します）"
      self.darks = self.darks + 1
      return false
    end
    if M.is_colorless(pram) then
      self.last_error = "⚠ 色の無い一瞬なので見送りました（★戦闘に入る所など）"
      self.grays = self.grays + 1
      return false
    end
    local sum = M.checksum(chr)
    local chr_written = false
    if sum ~= self.chr_sum then
      if not put("map_art.bin", chr, "wb") then return false end
      self.chr_sum = sum
      self.chr_writes = self.chr_writes + 1
      chr_written = true
    end
    -- ⚠ 広さは Python が ROM の世界地図から取ります（★ここは記録のため）
    local w, h = 256, 256
    if kind == KIND_ALEFGARD then w, h = 158, 138 end
    local body = {
      kind = kind, map_id = 0, width = w, height = h,
      chr_checksum = sum, chr_written = chr_written,
      tileset = "", palette_group = "", pram = to_hex(pram), map = "",
    }
    if not put("map_art.json", self.json(body)) then return false end
    self.writes = self.writes + 1
    self.last_key = map_key()
    return true
  end

  --- ★毎フレーム呼ぶ。⚠ 変わっていなければ何もしない。
  function self.tick()
    self.frames = self.frames + 1
    if self.frames % self.every ~= 0 then return false end
    local kind_now = memory.readbyte(A_KIND)
    -- ⚠⚠ ここは長らく「ローカル か 上の世界」だけでした（RX3-0316）。
    --   ★アレフガルド（2）は `skipped` になるだけで、⚠ **材料を 1 度も書いていません**でした。
    if not is_local(kind_now) and not is_world(kind_now) then
      self.skipped = self.skipped + 1
      return false
    end
    local key = map_key()
    if key == self.last_key then
      self.skipped = self.skipped + 1
      self.waiting = 0
      return false                      -- ⚠⚠ ここが「送らない」の本体
    end

    -- ⚠⚠ **落ち着くまで待つ**（RX3-0046）。
    --   ★地図番号・広さ・パレットが**続けて同じ**になるまで取りません。
    --   ⚠ 暗転の途中で取ると真っ黒、広さの更新前に取ると前の地図の広さです。
    local now = key .. "/" .. tostring(M.checksum(read_pram() or ""))
    if now ~= self.settling then
      self.settling, self.settled = now, 1
    else
      self.settled = self.settled + 1
    end
    self.waiting = self.waiting + 1
    if self.settled < self.settle and self.waiting < self.patience then
      self.skipped = self.skipped + 1
      return false
    end

    local ok = self.write_now()
    if ok then
      self.waiting, self.said_error = 0, nil
      self.say(string.format("★MAP の材料を書きました（%s / CHR %s）",
        self.last_key,
        self.chr_writes > 0 and ("計 " .. self.chr_writes .. " 回")
          or "なし"))
    elseif self.last_error ~= nil then
      -- ⚠ 同じ理由は 1 度だけ（★30 フレームごとに出ると記録が埋まる）
      if self.last_error ~= self.said_error then
        self.say("⚠ " .. self.last_error)
        self.said_error = self.last_error
      end
    end
    return ok
  end

  --- ★記録に残すためのまとめ。
  function self.report()
    return string.format("書いた %d 回 / CHR %d 回 / 見送り %d 回 / 暗転 %d 回%s",
      self.writes, self.chr_writes, self.skipped, self.darks,
      self.last_error and ("（⚠ " .. self.last_error .. "）") or "")
  end

  return self
end

return M
