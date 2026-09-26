-- DQ3 Auto 戦闘 v0（RX3-0015 / 2026-08-25）。
--
-- ★★ これは戦術 AI ではありません。 ★★
--   設定に書かれたコマンドを毎ターン出すだけの**単純マクロ**です。
--   ⚠ 敵の種類・弱点・戦況を**一切見ません**（指示書 §2.1）。
--   ★DQ3 の戦術仕様が固まったら、このファイルごと捨てます。
--
-- ## ★状態を「画面」から取る
--
--   ⚠ DQ3 の戦闘 RAM（カーソル位置・手番）は未解明です。★でも解かなくてよい。
--
--     「たたかう」が画面にある  →  戦闘コマンド待ち
--     ★**点滅している** ▶ の右 →  いま選んでいる項目
--       （⚠ 静止した ▶ は飾り。★`cursor.lua` / RX3-0020）
--     窓の上に出ている名前      →  ★**誰の手番か**（RAM の名前と突き合わせる）
--
--   ⚠ 指示書 §2.4「ターゲット仕様のために ROM 解析を追加しない」を満たします。
--
-- ## ★設定でできること（`config/dq3_phase0.yaml`）
--
--     primary   第一優先のコマンド
--     fallback  ⚠ primary ができないときに代わりに出すコマンド
--     spell     呪文名（★画面に出るとおり。⚠ 同梱していません）
--     min_mp    ⚠ MP がこれ未満なら primary をあきらめて fallback へ
--
--   ★MP は RAM から読むので、**唱える前に**足りるか分かる
--   （⚠「MPがたりない」を見てから直す、という面倒が要らない）。
--
-- ## ⚠ 不明なら入力しない（指示書 §2.6）
--
--   賢く復旧するより**安全に止まる**ことを優先します。
--   分からない画面では**ボタンを 1 つも押しません**。
--
-- 起動（絶対パス）:
--   fceux64.exe -lua <この file> <DQ3_J.nes>
--
-- 操作: Q … Auto の入り切り

-- ★読む場所と書く場所を分ける。
--   ⚠ 実機なしの検査では、生成物は本物の場所にあり、書き込みだけ隔離先へ向く
--   （`research/probes/reusable/lua_run.py` の作法）。
local function clean(p) return (p:gsub("\\", "/"):gsub("/$", "")) end
local root = os.getenv("RETROUX_ROOT")
if root == nil or root == "" then root = "C:/Projects/260721_RetroUX" end
root = clean(root)
local write_root = os.getenv("RETROUX_WRITE_ROOT")
write_root = (write_root ~= nil and write_root ~= "") and clean(write_root) or root

package.path = root .. "/work/generated/?.lua;" .. package.path
local ok_cfg, CFG = pcall(require, "dq3_phase0")
if not ok_cfg or CFG == nil then
  error("設定が読めません。★先に `python -m dq3.phase0.generate_lua` を実行してください")
end

-- ★★ 共有部分（RX3-0018 / 2026-08-29）。
--   ⚠⚠ `joypad.set` は後勝ちなので、押す権利は **1 か所**が持つ。
--   ★`dev.lua` から動かすときは、その 1 つを 2 つの機能で分け合う。
local Core = dofile(root .. "/dq3/phase0/core.lua")
--: ★`dev.lua` が置いていく入れ物（⚠ 単独で起動したときは nil）
local HOST = rawget(_G, "DQ3_DEV")
--: ★この機能の名前（⚠ ボタンの持ち主として使う）
local ME = "auto"

--: ★★ 画面は**スクロールを反映して**組む（RX3-0020 / 2026-08-30）。
--
--   ⚠⚠ ここは長らく `ppu.readbyterange(0x2000, 960)` の**生読み**だった。
--     ★戦闘中のセーブ 5 つは scroll=(0,0) / 面 0 なので、たまたま一致していた。
--     ⚠ しかし勝利のあとの画面（セーブ 0）は **scroll=(16,0)** で、
--       2 マスずれる。★点滅の番地を升に直すのに、ここが合っていないと
--       まるごと違う場所を指す（まんたんが 2026-08-29 に実機で踏んだ）。
local Screen = dofile(root .. "/dq3/phase0/screen.lua")
local screen_reader = (HOST and HOST.screen) or Screen.new()
if HOST == nil or HOST.screen == nil then pcall(screen_reader.install) end

--: ★★ 点滅している ▶ **だけ**を本物とみなす（RX3-0020 / 2026-08-30）。
--
--   ⚠⚠ まんたん側は `RX3-0015` でこちらへ移し、**静止した ▶ に釣られる**
--     問題が消えた。★戦闘側は座標で選ぶ古いままだったので、ここで揃える。
--
--   ⚠ 見張りは `dev.lua` が 1 つだけ持つ。`memory.registerwrite` は
--     **番地ごとに 1 つ**しか覚えないので、2 つ作ると片方が黙る。
local Cursor = dofile(root .. "/dq3/phase0/cursor.lua")
local track = (HOST and HOST.cursor) or Cursor.new()
if HOST == nil or HOST.cursor == nil then track.install_writes() end

local AUTO = CFG.auto_battle or {}
local PARTY = CFG.party or {}
local MENU = CFG.menu_tiles or {}
local COLS, ROWS = CFG.columns or 32, CFG.rows or 30
local CURSOR = CFG.cursor_tile
local SLOTS = {"p1", "p2", "p3", "p4"}

----------------------------------------------------------------------
-- 画面を読む
----------------------------------------------------------------------

--- ★いま映っている 32x30。⚠ 読めなければ nil。
--
-- ⚠ 中身は `screen.lua`（★スクロールと面を反映する）。
local function read_nametable()
  local ok, tiles = pcall(screen_reader.read)
  if not ok then return nil end
  return tiles
end

--- ★点滅の見張りへ、いまの画面とスクロールを渡す。
--
-- ⚠⚠ **毎フレーム呼ぶこと。** ★`cooldown` の間も呼ばないと、
--   点滅をまるごと取りこぼす（まんたん側で実際に踏んだ）。
local function watch(nt)
  track.set_scroll(screen_reader.scroll_x, screen_reader.scroll_y,
                   (screen_reader.ctrl or 0) % 4)
  if nt ~= nil then track.update(nt) end
end

-- その並びが何行目にあるか。⚠ 見つからなければ nil（★0 を返さない）
--- ★語の並びを画面から探す。`whole` なら**語として丸ごと**一致する所だけ（RX3-0270）。
--
--   ⚠⚠ RX3-0270（2026-09-14 実機）: 部分一致のままだと「メラ」が先に出ている「メラミ」の頭に当たり、
--     ★メラを頼んだのにメラミを唱えた（MP 6）。「ホイミ」は「ベホイミ」の後ろにも当たる。
--     → ★前後の升が字なら外す（★まんたんの `MX.find_word` / RX3-0163 と同じ考え。字かどうかは `Cursor.label_at` と同じ）
local function find_row(nt, seq, whole)
  if nt == nil or seq == nil or #seq == 0 then return nil end
  local function text(x, y)
    if x < 0 or x >= COLS then return false end
    local v = nt[y * COLS + x + 1]
    return v ~= nil and v ~= 0 and (v < Cursor.TEXT_MAX or (Cursor.TEXT_EXTRA or {})[v] ~= nil)
  end
  for y = 0, ROWS - 1 do
    for x = 0, COLS - #seq do
      local hit = not whole or (not text(x - 1, y) and not text(x + #seq, y))
      for k = 1, #seq do
        if not hit then break end
        if nt[y * COLS + x + k] ~= seq[k] then hit = false end
      end
      if hit then return y, x end
    end
  end
  return nil
end

--: ★コマンド窓に出うる語（⚠ **探すのは 5 つ全部**）。
--   ★カーソルが にげる や どうぐ の行に居ることもあるので、
--   ⚠ 「見つける」ための語と「選ぶ」ための語は**別**にする。
local MENU_WORDS = {}
for _, k in ipairs({"attack", "flee", "defend", "item", "spell"}) do
  if MENU[k] ~= nil then MENU_WORDS[#MENU_WORDS + 1] = MENU[k] end
end

--- ★★ コマンド窓の ▶ を見つける。⚠ 無ければ nil。
--
-- ⚠⚠ **コマンド窓の ▶ は点滅しない**（★2026-08-30 実機で判明 / RX3-0020）。
--   `work/dq3-probe/ppu_trace.txt` を数え直した実測:
--
--     $2289 (9,20)   72×24 / 00×20  ★点滅している（呪文の一覧）
--     $228D (13,20)  72×16 / 00×16  ★点滅している（対象）
--     $22C5 (5,22)   72× 1 / 00× 0  ⚠⚠ **点いたきり**（コマンド窓）
--
--   ★点滅するのは**下位のメニュー**だけ。コマンド窓の ▶ は
--   「いまここ」の目印として置きっぱなしになる。
--
--   ⚠ ここを点滅で探した版は、実機で 4 手番だけ動いて止まった
--   （★窓の描き直しがたまたま 72→00→72 に見えていただけ）。
--
-- ★代わりに「**右にコマンドの語がある ▶**」を本物とする。
--   ⚠ 敵の窓の ▶ は右が敵の名前なので、これで外れる
--   （実測: 止まった画面に ▶ が (5,20) と (13,20) の 2 つ出ていた）。
local function command_cursor(nt, at_x, at_y)
  if nt == nil then return nil end
  -- ★位置を渡したら、その ▶ がコマンド窓の ▶ か（★右の語で見る / ⚠ ▶ の字が点滅で消えていてもよい / RX3-0233）
  if at_x ~= nil then
    local label = Cursor.label_at(nt, at_x, at_y)
    for _, word in ipairs(MENU_WORDS) do
      if Cursor.starts_with(label, word) then return at_x, at_y end
    end
    return nil
  end
  for y = 0, ROWS - 1 do
    for x = 0, COLS - 1 do
      if nt[y * COLS + x + 1] == CURSOR then
        local label = Cursor.label_at(nt, x, y)
        for _, word in ipairs(MENU_WORDS) do
          if Cursor.starts_with(label, word) then return x, y end
        end
      end
    end
  end
  return nil
end

--- ★★ いま点滅している ▶ の右にある語（⚠ 生のタイルのまま）。
--
-- ⚠⚠ ここには以前、座標でカーソルを探す道具が 4 つ並んでいた
--   （`add_cursors` / `new_cursor` / `has_entry_above` / `cursor_row`）。
--   ★どれも「▶ があれば本物」を前提にしていたので、⚠ **静止した ▶**
--   （つよさの窓など）に釣られた。`cursor.lua` に寄せて全部捨てた。
--
--   ★依頼者の着想（2026-08-27）:
--     「その点滅の右がコマンドの内容なんだけど」

-- ★画面の指紋。⚠ 「進んでいるか」を見るのに使う
--- ★画面が変わったかを見るための数（⚠ 中身の比較ではない）。
--
-- ⚠⚠ 2026-08-29: ここは **7 マスに 1 つ**しか見ていなかった（`i = 1, 960, 7`）。
--   ★変化がその網の目に乗らないと、**動いているのに「止まっている」**と判断する。
--   ⚠ 終わりの処理はこれで「送っても進まない」と誤解しうる。
--   → ★全部見る。`count_tiles` が毎フレーム 960 マス数えているので、費用は同じ桁。
--
-- ⚠⚠ 2026-08-30（RX3-0020）: **カーソルのマスは数に入れない。**
--
--   ★カーソルは 8 フレーム周期で点滅する。⚠ 数に入れると、
--   **画面が完全に止まっていても digest が毎回変わる**。
--   → `d == last_seen` が成立せず、`screen_frozen` の歯止めは
--     ⚠⚠ **実機では 1 度も効いていなかった**。
--   ★足場の画面は点滅しないので、検査だけが緑だった
--     （⚠「0 件は通っていないだけ」の形）。
local function digest(nt)
  if nt == nil then return 0 end
  local h = 0
  for i = 1, COLS * ROWS do
    local v = nt[i] or 0
    if v == CURSOR then v = 0 end
    h = (h * 31 + v) % 4294967296
  end
  return h
end

----------------------------------------------------------------------
-- パーティ
----------------------------------------------------------------------

--: ★★ 戦闘 AI v1 の入れ物（RX3-0126 / 2026-09-08）。⚠ 中身は下で入れる。
--   ★`frame` が触る外の変数を増やさないため、AI の状態と関数は**この 1 つ**に置く
--   （⚠ Lua 5.1 は 1 つの関数につき upvalue 60 個まで。★2026-08-29 に超えた）。
local AIX = {}

local function w16(addr)
  return memory.readbyte(addr) + memory.readbyte(addr + 1) * 256
end

--- ★袋の中の やくそう の数（⚠ 番地が設定に無ければ 0。★推測しない）。
--   ★bit7（装備の印）は落として比べる（RX3-0213）。⚠ やくそうは装備できない品なので
--   数は変わらない。★空き（$FF）は落とすと $7F になるので先に外す（⚠ $7F の品は無い）
local function count_herbs(i)
  local herb = AIX.herb_id and AIX.herb_id() or nil
  if PARTY.items == nil or herb == nil then return 0 end
  local n, slots = 0, PARTY.item_slots or 8
  for k = 0, slots - 1 do
    local b = memory.readbyte(PARTY.items + i * slots + k)
    if b ~= 0xFF and b % 128 == herb then n = n + 1 end
  end
  return n
end

--- ★袋に入っている品の ID の集合（RX3-0213）。⚠ 番地が設定に無ければ nil（★分からない）。
--   ★bit7（装備の印）は落とす: 戦闘の どうぐ は装備の bit を落として使う（`AND #$7F`）ので、
--   装備中の まどうしのつえ も「持っている」に数える。
--   ⚠ upvalue 60 の上限すれすれなので、★新しい local は作らず AIX に置く。
function AIX.bag_ids(i)
  if PARTY.items == nil then return nil end
  local out, slots = {}, PARTY.item_slots or 8
  for k = 0, slots - 1 do
    local b = memory.readbyte(PARTY.items + i * slots + k)
    if b ~= 0xFF then out[b % 128] = true end
  end
  return out
end

local function read_party()
  local out = {}
  local n = PARTY.slots or 4
  local size = PARTY.entry_size or 2
  local nsize = PARTY.name_size or 4
  for i = 0, n - 1 do
    local o = i * size
    local m = {
      slot = SLOTS[i + 1], index = i + 1,
      hp = w16(PARTY.hp_current + o), hp_max = w16(PARTY.hp_max + o),
      mp = w16(PARTY.mp_current + o), mp_max = w16(PARTY.mp_max + o),
      name = {},
    }
    for k = 0, nsize - 1 do
      m.name[k + 1] = memory.readbyte(PARTY.name + i * nsize + k)
    end
    -- ★戦闘 AI が見る数字（RX3-0126）。⚠ 番地が設定に無ければ入れない（★推測しない）
    local ds = PARTY.derived_stride or 2
    if PARTY.attack ~= nil then m.attack = w16(PARTY.attack + i * ds) end
    if PARTY.defence ~= nil then m.defense = w16(PARTY.defence + i * ds) end
    if PARTY.class_gender ~= nil then
      m.class_id = memory.readbyte(PARTY.class_gender + i) % 8
    end
    if PARTY.spells ~= nil then
      local st = PARTY.spell_stride or 8
      m.spells = {}
      for k = 0, 7 do m.spells[k + 1] = memory.readbyte(PARTY.spells + i * st + k) end
    end
    m.herbs = count_herbs(i)
    -- ★戦闘で使える道具を持っているか（RX3-0213 / まどうしのつえ など）。⚠ 番地が無ければ nil
    m.battle_items = AIX.bag_ids(i)
    -- ★★ 状態（RX3-0135 / 2026-09-09）。⚠⚠ **裏の取れた旗だけ**が `status_flags` に来ます。
    --   ★来なかった旗は**入れません**（= 分からない / nil）。
    --   ⚠ `false`（そうでないと確かめた）と混ぜないため（指示書 v1.1 §12-2）。
    if PARTY.status ~= nil and PARTY.status_flags ~= nil then
      local ss = PARTY.status_size or 2
      local raw = {}
      for k = 0, ss - 1 do raw[k] = memory.readbyte(PARTY.status + i * ss + k) end
      local st = {}
      for name, f in pairs(PARTY.status_flags) do
        local byte = raw[f.byte or 0]
        if byte ~= nil then
          st[name] = math.floor(byte / (2 ^ (f.bit or 7))) % 2 == 1
        end
      end
      m.status = st
      m.status_raw = raw
    end
    -- ⚠ 最大 HP が 0 の枠は「居ない」
    if m.hp_max > 0 then out[#out + 1] = m end
  end
  return out
end

--: ★戦闘中の敵（★`dev.lua` の `read_enemies` と同じ読み方 / RX3-0033）
local ENE = CFG.battle_enemies or {}

--- ★群ごとの {id, n, hp[], alive[], def[]}。⚠ 番地が無ければ nil（★AI は「分からない」に倒す）。
--   ★def … 1 体ずつの**いまの**守備力（RX3-0226 / profile `battle_enemies.defense` = $0520 WORD×8）。
--     ROM の表の値から始まり、敵の スクルト で上がる（JP bank 9 $88EE / 999 で頭打ち）。
--     ⚠ 番地が設定に無ければ入れない（★AI は表の守備力のまま = 今までどおり）
--- ★★ 群ごとのスロット（RX3-0268）。戻り値: {[群] = {スロット, ...}}。⚠ 使用中の旗が 1 つも無ければ nil
--   （★呼ぶ側が今までどおり先頭から数える）。
--   ★群は状態の 1 バイト目（$0530+2i）の bit3-2・使用中は bit7（JP bank 4 $BB75 / profile `battle_enemies.group_shift`）。
--   ⚠ 以前は「群のスロットが先頭から数だけ並ぶ」とみなしていた → 援軍（空いたスロットに入る）の後に HP・MP・守備がずれうる
function AIX.enemy_slots()
  if ENE.status == nil or ENE.used_bit == nil or ENE.group_shift == nil then return nil end
  local by, any = {}, false
  for slot = 0, (ENE.hp_slots or 8) - 1 do
    local b0 = memory.readbyte(ENE.status + slot * (ENE.status_size or 2))
    if b0 >= ENE.used_bit then
      local g = math.floor(b0 / (2 ^ ENE.group_shift)) % 4
      by[g] = by[g] or {}
      by[g][#by[g] + 1] = slot
      any = true
    end
  end
  return any and by or nil
end

--- ★その敵の状態（RX3-0268）。⚠ 裏の取れた旗だけ（profile の `status_flags` の confirmed）/ 来ていない旗は入れない（= 分からない）
function AIX.enemy_status(slot)
  if ENE.status == nil or ENE.status_flags == nil then return nil end
  local base = ENE.status + slot * (ENE.status_size or 2)
  local st = {}
  for name, f in pairs(ENE.status_flags) do
    st[name] = math.floor(memory.readbyte(base + (f.byte or 0)) / (2 ^ (f.bit or 7))) % 2 == 1
  end
  return st
end

local function read_enemies()
  if ENE.ids == nil then return nil end
  local out = {}
  local first = 0
  local slots_of = AIX.enemy_slots()
  for i = 0, (ENE.groups or 4) - 1 do
    local id = memory.readbyte(ENE.ids + i)
    if id ~= (ENE.empty or 0xFF) then
      local n = memory.readbyte(ENE.counts + i)
      local g = {id = id, n = n}
      -- ★★ RX3-0268: この群のスロットは ROM の群の bit で決める（⚠ 旗が無ければ今までどおり先頭から数だけ）
      local slots = slots_of ~= nil and slots_of[i] or nil
      if slots == nil then
        slots = {}
        for k = 0, n - 1 do slots[#slots + 1] = first + k end
      end
      if ENE.hp_current ~= nil then
        g.hp, g.alive = {}, {}
        if ENE.defense ~= nil then g.def = {} end
        -- ★今の MP（RX3-0260 / profile `battle_enemies.mp` = $0510 BYTE×8 / ★JP ROM のマホトラの処理と戦闘中のセーブ 21 本で確かめた）
        --   ★マホトラが効くか（今の MP 0 の相手からは吸えない）だけに使う。⚠ 番地が設定に無ければ入れない
        if ENE.mp ~= nil then g.mp = {} end
        -- ★状態（RX3-0268 / 眠り・封じ・幻）。⚠ 旗が設定に無ければ入れない
        if ENE.status_flags ~= nil then g.status = {} end
        for idx, slot in ipairs(slots) do
          local k = idx - 1
          if g.status ~= nil then g.status[k + 1] = AIX.enemy_status(slot) end
          if slot < (ENE.hp_slots or 8) then
            g.hp[k + 1] = w16(ENE.hp_current + slot * (ENE.hp_size or 2))
            if g.def ~= nil then g.def[k + 1] = w16(ENE.defense + slot * (ENE.defense_size or 2)) end
            if g.mp ~= nil then g.mp[k + 1] = memory.readbyte(ENE.mp + slot) end
            if ENE.status ~= nil then
              local st = memory.readbyte(ENE.status + slot * (ENE.status_size or 2)
                                         + (ENE.alive_byte or 1))
              g.alive[k + 1] = (st % 256 >= (ENE.alive_bit or 0x80))
            end
          end
        end
      end
      out[#out + 1] = g
      first = first + n
    end
  end
  return out
end

--: ★検査から群とスロットの対応を見るため（RX3-0268 / ⚠ frame の upvalue は増やさない）
AIX.read_enemies = read_enemies

local function party_text(members)
  local parts = {}
  for _, m in ipairs(members) do
    parts[#parts + 1] = string.format("%d/%d %d/%d", m.hp, m.hp_max, m.mp, m.mp_max)
  end
  return table.concat(parts, "  ")
end

-- ★いま誰の手番か。窓の上に出ている名前を、RAM の名前と突き合わせる。
--   ⚠ 分からなければ nil（★推測で 1 人目にしない）。
local function actor_of(nt, attack_y, members)
  if attack_y == nil or attack_y < 1 then return nil end
  for _, m in ipairs(members) do
    local seq = {}
    for _, b in ipairs(m.name) do
      if b == 0 then break end          -- 名前は 0 で終わる
      seq[#seq + 1] = b
    end
    if #seq > 0 then
      for y = math.max(0, attack_y - 3), attack_y - 1 do
        for x = 0, COLS - #seq do
          local hit = true
          for k = 1, #seq do
            if nt[y * COLS + x + k] ~= seq[k] then hit = false; break end
          end
          if hit then return m end
        end
      end
    end
  end
  return nil
end

----------------------------------------------------------------------
-- 状態
----------------------------------------------------------------------

local enabled = AUTO.enabled == true
local interval = AUTO.press_interval or 8
local stuck_limit = AUTO.stuck_frames or 600
local submenu_wait = AUTO.submenu_wait or 240
-- ★下位メニューでの押す間隔。⚠ 短いと効かない（実機で判明）
local SUBMENU_GAP = AUTO.submenu_gap or 30
--: ★AUTO を入れたらターボにするか（⚠ 既定は入れる）
local TURBO_WITH_AUTO = AUTO.turbo_with_auto ~= false
--: ★★ 数え方を分ける（RX3-0153 / 2026-09-10）★★
--
--   ⚠⚠ **これまで `turns` は 2 重に誤っていました**（★2026-09-10 実測）:
--     ① 1 人 1 回の**行動**ごとに増える（★4 人なら 1 ターン = 4 行動）
--     ② ⚠ `finish()` で**戻していない**ので、戦闘をまたいで積み上がる
--        （★実測: 同じ run で 8 → 16 → 24 → 32）
--     → 画面には「1戦 / 36ターン」と出ていました（⚠ 4 倍かつ累積）。
--
--   ```text
--   actions  ★1 人 1 回の行動      ⚠ 戦闘ごとに 0 へ戻す
--   rounds   ★全員が 1 回動く区切り ⚠ 同上（★人が「ターン」と呼ぶのはこちら）
--   ```
local cooldown = 0
--: ⚠⚠ **1 つの表にまとめる**（★数も、数え方も）。
--  ⚠ Lua 5.1 は 1 つの関数が見れる upvalue が **60 まで**です。
--  ★毎フレームの関数はもう上限すれすれなので、local を 1 つ増やしただけで
--  `has more than 60 upvalues` で読めなくなりました（2026-09-10 実測）。
--: last は直前に動いた人の番号（★戻ったら新しいターン / `AIX.decide` と同じ見方）
--: ★★ 戦闘のまとめ（RX3-0198 / 2026-09-12 依頼者「戦闘後に作戦・行動の内訳・MP 消費」）★★
--   kinds    ★**実際に押した**行動（`AUTO_V0 turn=` の行）を種類ごとに数える
--            attack=通常攻撃 / magic=攻撃呪文 / heal=回復（呪文・蘇生・やくそう）/ support=支援 /
--            defend=防御 / other=種類の分からない呪文（⚠ AI を使わない v0 の設定の呪文）
--   mp_start ★その戦闘で最初に押した瞬間の、パーティの MP の和（⚠ 呪文が効くのは全員が決めたあと）
--   strategy ★最後に立てた計画の作戦（⚠ 途中で ai_reload したら後のほう）
--   battle   ★戦闘の番号（⚠ 変わったら数え直す: 止まった・人が切った戦闘の数を次へ持ち越さない）
--   ⚠ upvalue 60 の上限すれすれなので、★新しい local は作らず COUNT に足す。
local COUNT = { actions = 0, rounds = 0, last = nil, kinds = {}, mp_start = nil, strategy = nil,
                battle = nil }
COUNT.KINDS = {"attack", "magic", "heal", "support", "defend", "other"}

--- ★パーティの MP の和（⚠ 読めなければ nil）
function COUNT.mp_of(members)
  if members == nil or #members == 0 then return nil end
  local sum = 0
  for _, m in ipairs(members) do sum = sum + (m.mp or 0) end
  return sum
end

--- ★押した行動の種類（★呪文は `AIX.decide` が付けた `tally` / ⚠ 窓に無くて落とした後の kind で見る）
function COUNT.kind_of(plan)
  local k = plan and plan.kind
  if k == "attack" or k == "defend" then return k end
  -- ★やくそう = heal / ★攻撃の道具（まどうしのつえ など）は tally = magic（RX3-0213 / `AIX.tally_of`）
  if k == "item" then return plan.tally or "heal" end
  if k == "spell" then return plan.tally or "other" end
  return "other"
end

--- ★1 行動ぶん数える（⚠ 数え方を 3 か所に書かない / Python は `dq3/battle_count.py`）。
function COUNT.add(slot, plan, members)
  local no = AIX.battle ~= nil and AIX.battle.battle_no or nil
  if COUNT.battle ~= nil and no ~= nil and no ~= COUNT.battle then COUNT.reset() end
  COUNT.battle = no
  if COUNT.actions == 0 then COUNT.mp_start = COUNT.mp_of(members) end
  COUNT.actions = COUNT.actions + 1
  local idx = tonumber(tostring(slot or ""):match("%d+") or "") or 0
  if COUNT.last == nil or idx <= COUNT.last then
    COUNT.rounds = COUNT.rounds + 1
  end
  COUNT.last = idx
  local kind = COUNT.kind_of(plan)
  COUNT.kinds[kind] = (COUNT.kinds[kind] or 0) + 1
  if plan ~= nil and plan.strategy ~= nil then COUNT.strategy = plan.strategy end
  -- ⚠⚠ 2 つ返します（RX3-0429 / P-17）: ★行動の通し番号と、★**本当のターン数**。
  --   ⚠ ログの `turn=` は長らく**行動の通し番号**でした（★読み違えの元）。
  return COUNT.actions, COUNT.rounds
end

--- ★次の戦闘は 1 ターン目から（⚠⚠ 2026-09-10 までこれが無く、累積していました）。
function COUNT.reset()
  COUNT.actions, COUNT.rounds, COUNT.last = 0, 0, nil
  COUNT.kinds, COUNT.mp_start, COUNT.strategy, COUNT.battle = {}, nil, nil, nil
end

--- ★終わりの行の後ろに付ける `key=value`（★`dq3/battle_count.py` の DONE が読む / ⚠ 旧い読み方は
--   rounds= actions= で終わる行しか読めなかったので、Python 側を先に広げてある）。
--   ★mp_used = 最初に押した瞬間の MP の和 − いまの MP の和。⚠ レベルアップ・回復の泉などで増えたら 0
--   （★マイナスは出さない）。⚠ 1 度も押していなければ mp_used は付けない（★分からない）。
function COUNT.fields(members)
  local parts = {}
  if COUNT.strategy ~= nil then parts[#parts + 1] = "strategy=" .. tostring(COUNT.strategy) end
  for _, k in ipairs(COUNT.KINDS) do parts[#parts + 1] = k .. "=" .. (COUNT.kinds[k] or 0) end
  local now = COUNT.mp_of(members)
  if COUNT.mp_start ~= nil and now ~= nil then
    parts[#parts + 1] = "mp_used=" .. math.max(0, COUNT.mp_start - now)
  end
  return " " .. table.concat(parts, " ")
end

--- ★人が読む形（⚠ 依頼者の指定 2026-09-10:「9ターン（36行動）」）。
function COUNT.text()
  return string.format("%dターン（%d行動）", COUNT.rounds, COUNT.actions)
end
local last_seen, same_frames = nil, 0
--: ★★ 点滅が見つからなかった回数（⚠ `same_frames` と**分ける**）。
--
--   ⚠⚠ 共用すると、片方が毎フレーム 0 に戻して**永遠に待ち続ける**か、
--     逆に**先に別の理由で止まって**本当の原因が隠れる。
--   ★まんたん側で 2026-08-27 に踏んだ形（`no_blink`）。
local no_blink = 0

--: ⚠⚠ **止まった理由だけでは足りない。★そのときの画面を残すため覚える。**
--   2026-08-30: `command_missing:p4=defend` が 22 戦闘に 1 度出ていたが、
--   ⚠ **何が出ていたのか記録に無く**、半月ちかく原因が分からなかった。
--   ★まんたん側は最初からこれを残していて、実際に何度も助かっている。
local last_nt = nil
--: ★戦闘フラグが降りてから数えるフレーム（⚠ すぐには終わりと決めない）
local outro_frames = 0
--: ⚠ 同じ ▼ を何度も記録しないための印
local sent_more = false
--: ★勝利のあとの画面で、止まっているかを見るための digest と回数
--: ⚠ `outro.pokes` は**連続して無駄だった**回数（★進んだら 0 に戻す）
--   `outro.total` はこの戦闘終わりで送った**総数**（⚠ 念のための歯止め）
--: ⚠⚠ **1 つの表にまとめる。** Lua 5.1 は 1 つの関数が触れる外の変数を
--   **60 個まで**しか許さない（★超えると FCEUX が読み込みで落ちる）。
--   ⚠ 実際に 2026-08-29 に超えた。★足した構文検査が手前で捕まえた。
local outro = {seen = nil, still = 0, pokes = 0, total = 0}
--: ★レベルアップの手がかり（⚠ 推定）。最大 HP を覚えておく
local last_max_hp = nil
local stopped_reason = nil
local step = "choose"          -- choose → (spell なら) pick_spell → target
local plan = nil
local waited = 0

local logfile = Core.open_log(write_root .. "/work/dq3-probe/auto_v0.log",
                              "自動戦闘の記録")
local function say(line)
  if logfile ~= nil then logfile:write(line .. "\n"); logfile:flush() end
end
say("=== AUTO_V0 start " .. os.date("%Y-%m-%d %H:%M:%S") .. " ===")

--: ★★ ボタンと速度は**共有**する。⚠ 2 つ持つと必ずずれる。
local BUTTONS = (HOST and HOST.buttons)
  or Core.new_buttons({say = say, hold_max = CFG.hold_max or 7})
local SPEED = (HOST and HOST.speed) or Core.new_speed({say = say})

-- ★戦闘に入るたび、画面をそのまま 1 回だけ書き出す（⚠ 毎フレームは重い）
local trace = Core.open_log(
  write_root .. "/work/dq3-probe/auto_v0_screens.txt", "画面の控え")
local traced_battle = false

local function dump_screen(nt, members)
  if trace == nil then return end
  trace:write(string.format("# frame=%d map=%d party=%s\n",
    emu.framecount(), memory.readbyte(0x8B), party_text(members)))
  for y = 0, ROWS - 1 do
    local cells, blank = {}, true
    for x = 1, COLS do
      local v = nt[y * COLS + x] or 0
      cells[#cells + 1] = string.format("%02X", v)
      if v ~= 0 then blank = false end
    end
    if not blank then trace:write(y .. ": " .. table.concat(cells, " ") .. "\n") end
  end
  trace:flush()
end

--- ★AUTO と一緒に速度を切り替える。
--
--   依頼者「Q でターボ化」（2026-08-26）。⚠ レベル上げのときは速いほどよい。
--
-- ⚠ Lua から出せる速度は **normal と turbo（と maximum）だけ**。
--   ★150% や 200% のような段階は Lua からは指定できない
--   （`docs/research/fceux-speed-control.md`。⚠ メニューの `WM_COMMAND` が要る）。
--
-- ⚠ `emu.speedmode` が無い環境でも落ちないように `pcall` で包む
--   （★実機なしの検査では偽の API を置いているため）。
--: ★★ キー割り当て（⚠ DQ2 に合わせる / 依頼者 2026-08-27）
--
--   ⚠⚠ **キーボードのキー**であって、ゲームの A ボタンではない。
--   ★NES の A ボタンは `F`（`retroux/config/default_keybindings.yaml`
--     2026-08-01 実機確認）。だからキーボードの `A` は空いている。
--
--   ⚠⚠ **`Q` は使えない。** FCEUX の「ムービーの読み取り専用切替」に予約済み。
local KEYS = CFG.keys or {}
local KEY_AUTO = KEYS.toggle_auto or "A"
local KEY_TURBO = KEYS.toggle_turbo or "T"

--: ★★ 速度のスイッチは `core.lua` が 1 つだけ持つ（RX3-0018）。
--
-- ⚠⚠ 以前はここと `mantan_v0.lua` の**両方**が `set_speed` を持っていた。
--   ★手で入れたターボを、もう片方が勝手に戻す事故が起きうる形だった。
-- ⚠⚠ 2026-09-11（RX3-0166）: **AUTO を入れただけではターボにしません。**
--   ★速くするのは「既知・安全」と決まった戦闘だけで、決めるのは `battle_speed.lua`（`AIX.fast`）。

--: ★★ ゲームが「新しく押された」と判断した結果が入る番地。
--
-- ⚠⚠ 2026-08-27 実機（まんたん）: **1 フレーム押しでは A がすり抜けた。**
--   ★戦闘側も同じ 1 フレーム押しだったので、同じ直しを入れる。
--
-- ★ROM を読んで分かったこと（`$CB16` / `$C341` / `$CB25`）:
--
--     $CB1A  JSR $C341   ; ★1 フレーム待つ（$06D2 が変わるまで）
--     $CB1D  JSR $CB25   ; ★コントローラを読む
--     $CB20  LDA $14     ; 新しく押されたボタン
--     $CB22  BEQ $CB1A   ; ⚠ 無ければ戻る
--
--   ⚠ **読むのは 1 フレームに 1 回、NMI を待った直後の一瞬だけ。**
--   ⚠ ラグフレームは実測 25.9%（セーブステートの `LAGC / FHCN`）。
--     ★1 フレームの `joypad.set` はその一瞬とすれ違って消える。
--
-- ⚠⚠ 長く押すのも駄目。同じルーチンに連射がある:
--
--     $CB4C  LDY #$08    ; ★0 なら 8 を装填
--     $CB53  LDY #$0B    ; ⚠ 以後 11 フレームごと
--
--   → **8 フレーム押し続けると 2 回選ばれる**。
--
-- ★だから「届いたら離す」。⚠ めくら撃ちにしない（依頼者の指摘 2026-08-27）。
local INPUT_NEW = 0x14
local INPUT_HELD = 0x16
local HOLD_MAX = CFG.hold_max or 7

--- ★押す。⚠ 実際に押されるのは次のフレームから、届くまで。
--
-- ⚠⚠ 押す権利は `core.lua` の 1 つが持つ（RX3-0018）。
--   ★持ち主でなければ押さず、**拒んだことを記録**する。
local function press(key)
  return BUTTONS.press(ME, key)
end

--- ★毎フレームの先頭で呼ぶ。⚠ `cooldown` の中でも呼ぶこと。
--
-- ⚠ 中身は `core.lua` にある。★2 つの機能が同じフレームに押さないよう、
--   実際に `joypad.set` を呼ぶのは**あちらの 1 か所だけ**。
local function keep_pressing()
  BUTTONS.tick()
end

----------------------------------------------------------------------
-- ★★ 戦闘 AI v1（RX3-0126 / 2026-09-08）
--
--   ★判断は `dq3/phase0/ai/pipeline.lua`（⚠ RAM も画面も読まない）。
--   ここは「RAM を ctx に組む」「ターンの区切りを見る」「対象へ ▶ を寄せる」だけ。
--
--   ⚠ 生成物 `work/generated/dq3_ai.lua` が無ければ AI を使わず、
--     ★今までどおり設定（`auto_battle.commands`）で動く。
----------------------------------------------------------------------

--: ★対象の窓が出ないコマンド（自分 / 全体 / 群が 1 つの たたかう）を、
--   これだけ待って点滅が無ければ「選ぶ段は無かった」とみなす（★実測 5-8 フレームで出る）
AIX.OPTIONAL_WAIT = AUTO.target_optional_wait or 45
--: ★敵の窓の群は 2 行おき（★実測 `auto_v0_screens.txt` frame 20250: y=20 と y=22）
AIX.ROW_STEP = AUTO.target_row_step or 2
--: ⚠ 寄せても ▶ が動かない回数の上限（★そこで諦めて、いまの位置で決める）
AIX.STUCK_MAX = 3

AIX.pipe = nil
--: ★押す直前の見直し（RX3-0134）。⚠ 読めなければ `nil` = 今までどおり計画のまま押す
AIX.legality = nil
AIX.plan = nil
AIX.turn = 0
AIX.last_index = nil
AIX.confirmed = {}
AIX.aim_state = nil

-- ★★ 敵が実際に何をしたかの見張り（RX3-0371 / ⚠ 記録だけ。判断には使わない）。
--   ⚠ 読み込めない版でも動くように `pcall`（★機能が増えて壊れるのを避ける）。
local EnemyWatch = nil
do
  local ok, W = pcall(dofile, root .. "/dq3/phase0/enemy_watch.lua")
  if ok then EnemyWatch = W end
end
AIX.watch = EnemyWatch ~= nil and EnemyWatch.new() or nil

--- ★行動 ID → 分類（★生成物から / ⚠ 無ければ nil）。
function AIX.move_category(move)
  local cat = AIX.pipe and AIX.pipe.cat
  local rows = cat and cat.move_names or nil
  return rows ~= nil and rows[move] or nil
end

--- ★1 フレーム見る（⚠ `frame()` から / ★戻り値は書き出す 1 行 か nil）。
function AIX.watch_step(party_hp)
  if EnemyWatch == nil or AIX.watch == nil then return nil end
  return EnemyWatch.step(AIX.watch, memory.readbyte, party_hp, AIX.move_category)
end

--- ★ターンの頭で締める（⚠ 最後の 1 行を落とさない）。
function AIX.watch_begin(battle_no, turn, party_hp)
  if EnemyWatch == nil or AIX.watch == nil then return nil end
  return EnemyWatch.begin(AIX.watch, battle_no, turn, party_hp, AIX.move_category)
end

function AIX.herb_id()
  local cat = AIX.pipe and AIX.pipe.cat
  return cat and cat.items and cat.items.herb and cat.items.herb.id or nil
end

function AIX.enabled()
  return AIX.pipe ~= nil and AIX.pipe.ok == true
end

do
  local ok, P = pcall(dofile, root .. "/dq3/phase0/ai/pipeline.lua")
  if ok and type(P) == "table" then
    -- ★検査から生成物の場所を差し替えられる（⚠ 無い場所を指せば AI は切れる）
    local ok2, pipe = pcall(P.new, root, {say = say, path = rawget(_G, "DQ3_AI_PATH")})
    if ok2 then AIX.pipe = pipe else say("AI ⚠ 読み込めない: " .. tostring(pipe)) end
  else
    say("AI ⚠ pipeline を読めない: " .. tostring(P))
  end
  -- ★押す直前の見直し（⚠ AI が使えなくても、計画が有るときだけ働く）
  local ok3, L = pcall(dofile, root .. "/dq3/phase0/ai/legality.lua")
  if ok3 and type(L) == "table" then
    AIX.legality = L
  else
    say("AI ⚠ legality を読めない: " .. tostring(L))
  end
end

----------------------------------------------------------------------
-- ★状態（★`state.json` の `auto`）— RX3-0147 / 2026-09-10
----------------------------------------------------------------------
--
-- ⚠⚠ **`nav` / `walk` / `restock` は前から publish していて、戦闘 AI だけが例外**でした
--   （★2026-09-10 の棚卸しで判明）。⚠ そのため右画面は**ログを tail するしかなく**、
--   ★同じ事実を 2 通りの道で読む形になっていました。
--
-- ★ここで置くのは**判断の結果だけ**です（⚠ 理由の全文はログのまま）。
--   `pipeline.lua` は触りません（★純粋なまま）。
AIX.status = {active = false, turn = 0, situation = nil, strategy = nil,
              mp_policy = nil, slots = {}, notes = {}}
if HOST ~= nil then HOST.auto_status = AIX.status end

----------------------------------------------------------------------
-- ★★ 戦闘の状態と高速化（RX3-0166 / 2026-09-11）
----------------------------------------------------------------------
--
--   ★状態は dev.lua の 1 つを借りる（⚠ 単独で起動したときだけ自分で作る）。
--   ★高速化は `battle_speed.lua`（⚠ ここは材料を渡すだけ / 依頼者 §27 の責務分離）。
--   ⚠ 毎フレームの関数は upvalue 60 すれすれ → ★どちらも AIX に持たせる。
AIX.battle = (HOST ~= nil and HOST.battle)
  or dofile(root .. "/dq3/phase0/battle_state.lua").new({say = say, cfg = CFG.battle_state})
do
  local BattleSpeed = dofile(root .. "/dq3/phase0/battle_speed.lua")
  local fast_cfg = AUTO.fast or {}
  AIX.fast = BattleSpeed.new({
    speed = SPEED,
    say = say,
    cfg = {enabled = TURBO_WITH_AUTO and fast_cfg.enabled ~= false,
           situations = fast_cfg.situations},   -- ★RX3-0225: 独自の HP 30%（danger_hp）は外した
    -- ★窓の色の番地と人へ返す色（RX3-0225 / profile の runtime.window_color → 生成物）
    window = CFG.window_color,
    -- ★既知の敵（★Python が倒した敵を書く / ⚠ 戦闘の頭で 1 回だけ読む）
    load_book = function()
      return dofile(write_root .. "/work/generated/dq3_enemy_book.lua")
    end,
  })
end

--- ★★ 窓の色（RX3-0225）。★ゲームが HP と状態から決めた 1 バイト（`$06E0` / 番地は `AIX.fast.window`）。
--   ⚠ 読めなければ nil（★人へ返す判断はしない / 自動で入る判断は「入らない」に倒す）
function AIX.window_color()
  local ok, v = pcall(memory.readbyte, AIX.fast.window.address)
  return ok and v or nil
end

--- ★★ Auto 中は毎フレーム、窓の色を battle_speed へ渡す（★オレンジ / 緑なら印 take_manual が立つ）。
function AIX.watch_window()
  local ok, err = pcall(AIX.fast.on_window, AIX.window_color())
  if not ok then say("FAST ⚠ 窓の色で落ちた: " .. tostring(err)) end
end

--- ★★ 人が TURBO を押した（★TURBO ボタン / T キー / RX3-0237）。★TURBO だけ切り替える（AUTO は変えない）。
--
--   ★2026-09-13: AUTO OFF でも効く（★「手動操作・高速」/ ⚠ RX3-0169 は Auto 中だけだった）。
--   ⚠ 戦闘の本体（ACTIVE）でだけ効く（★フィールド・町の Turbo は触らない / RX3-0169 §14 / RX3-0170）。
function AIX.turbo_request(source)
  if AIX.battle.phase() ~= "ACTIVE" then
    say("[TURBO] ⚠ Turbo は戦闘中（ACTIVE）に使えます（source=" .. tostring(source) .. " / 何もしない）")
    return false
  end
  return AIX.fast.user_toggle(AIX.window_color())
end

--- ★A キー / Auto ボタンが効く場面か（★戦闘の本体 ACTIVE だけ / RX3-0169 §11・§14）。
--
--   ⚠ RESULT 以降・フィールドでは A を Auto として扱わない（★ゲームの A として押せるように）。
function AIX.may_toggle(source)
  local ph = AIX.battle.phase()
  if ph == "ACTIVE" then return true end
  say(string.format("[AUTO] ⚠ 戦闘中（ACTIVE）でないので切り替えない（段階 %s / source=%s）",
                    ph, tostring(source)))
  return false
end

if HOST ~= nil then
  HOST.battle_speed_status = AIX.fast.view
  HOST.turbo_toggle = AIX.turbo_request
  --- ★いま Auto か（★state.json の auto_enabled / 右画面の A ボタン）
  HOST.auto_enabled = function() return enabled == true end
  --- ★いまのターン（⚠ `enemy_watch2` が鍵に使う / RX3-0383）
  HOST.ai_turn = function() return AIX.turn or 0 end
  --- ★行動 ID → 分類（⚠ 生成物の `move_names` から / 無ければ nil）
  HOST.ai_move_category = function(move) return AIX.move_category(move) end
  if HOST.on_load ~= nil then
    -- ★セーブを読んだら Auto も Turbo も OFF（RX3-0169 §17）
    HOST.on_load[#HOST.on_load + 1] = function()
      if enabled then
        enabled = false
        BUTTONS.release(ME)
        say("[AUTO] ON -> OFF source=LOAD")
        say("AUTO_V0 OFF（セーブを読んだ）")
      end
      AIX.result_sending = false
      AIX.fast.abort("セーブを読んだ", "LOAD")
    end
  end
end
--: ★★ 勝ったあと（RX3-0166 → 2026-09-11 依頼者「単純な戦闘完了は、ボタンを押さないでも良い感じに」）
--
--   ```text
--   simple     ★既定。ファンファーレを聞かせてから結果の文も送り、フィールドまで戻す。
--              ⚠ レベルアップ・アイテム・いつもと違う曲が出たら、そこで人に返す
--   hand_back  勝ったらすぐ人に返す（★結果の文は全部人が送る）
--   advance    ⚠ 無人の run だけ。何が起きても結果の文を全部送る
--   ```
AIX.result_mode = "simple"
AIX.RESULT_MODES = {simple = true, hand_back = true, advance = true}
--: ★勝利のファンファーレ（★RX3-0165: 勝った 4 戦とも $16）
AIX.VICTORY_TRACK = 0x16
--: ★レベルアップの曲（★RX3-0165 の実機: $00 → $01 と頼み、同じ時にレベルのバイトが増えた）
AIX.LEVEL_TRACKS = {[0x00] = true, [0x01] = true}
--: ★ファンファーレを聞かせる間（⚠ 最初の文を送ると場所の曲へ切り替わるので、少し待つ / 目安）
AIX.RESULT_WAIT = tonumber(AUTO.result_wait) or 150
--: ★勝ったあとの控え（★RESULT に入ったフレームで撮る / ⚠ 戦闘中の道具で袋は変わるので戦闘の頭では撮らない）
AIX.result = {no = nil, since = nil, levels = nil, items = nil, why = nil}

--- ★この AUTO で結果をどう扱うか（★画面の頼み `auto result=...` がその 1 回だけ上書きする）。
function AIX.pick_result_mode(by_ui)
  local mode = AUTO.result or "simple"
  local req = (by_ui and HOST ~= nil) and HOST.last_request or nil
  if req ~= nil and req.action == "auto" and type(req.params) == "table"
      and req.params.result ~= nil then
    mode = tostring(req.params.result)
  end
  if not AIX.RESULT_MODES[mode] then mode = "simple" end
  return mode
end

--- ★パーティのレベル（4 バイト）と袋（4 x 8 バイト）。
function AIX.party_bytes()
  local P = CFG.party or {}
  local levels, items = {}, {}
  local n, slots = P.slots or 4, P.item_slots or 8
  for i = 0, n - 1 do
    levels[#levels + 1] = P.level and memory.readbyte(P.level + i * (P.stat_size or 1)) or 0
    for k = 0, slots - 1 do
      items[#items + 1] = P.items and memory.readbyte(P.items + i * slots + k) or 0
    end
  end
  return levels, items
end

--: ★袋の空き枠（⚠ `0` は ひのきのぼう。★空きは `0xFF` だけ / `dq3/knowledge/restock.py` と同じ）
AIX.BAG_EMPTY = 0xFF

--- ★袋に空きが 1 つも無いか（⚠ 読めないときは `nil` =「分からない」）。
--
--   ★`AIX.party_bytes()` が返す袋のバイト列をそのまま見ます。
--   ⚠ 居ない枠は `0` で埋まります（★`0xFF` ではない）ので、空きには数えません。
function AIX.bag_full(items)
  local P = CFG.party or {}
  if P.items == nil or items == nil or #items == 0 then return nil end
  for _, v in ipairs(items) do
    if v == AIX.BAG_EMPTY then return false end
  end
  return true
end

--- ★勝ったあと「いつもと違うこと」が起きたか。⚠ 一度起きたら覚えておく（★レベルのバイトは途中で揺れる）。
function AIX.result_unusual()
  local R = AIX.result
  if R.why ~= nil then return R.why end
  local B = AIX.battle
  local trk = B.track()
  if AIX.LEVEL_TRACKS[trk] then R.why = "レベルアップ"; return R.why end
  local levels, items = AIX.party_bytes()
  for i, v in ipairs(levels) do
    if R.levels ~= nil and R.levels[i] ~= nil and v > R.levels[i] then
      R.why = "レベルアップ"; return R.why
    end
  end
  for i, v in ipairs(items) do
    if R.items ~= nil and R.items[i] ~= v then R.why = "アイテムを手に入れた"; return R.why end
  end
  if trk ~= AIX.VICTORY_TRACK and B.field_track ~= nil and trk ~= B.field_track
      and not (AIX.battle.spec.tracks[trk] == true) then
    R.why = string.format("いつもと違う曲 %02X", trk); return R.why
  end
  return nil
end

--- ★RESULT の 1 フレーム。戻り値: 人に返す理由（nil = 返さない）, いまは待つか。
function AIX.result_step(mode)
  local R = AIX.result
  local now = emu.framecount()
  local no = AIX.battle.battle_no
  if R.since == nil or R.no ~= no or now < R.since then
    R.no, R.since, R.why = no, now, nil
    R.levels, R.items = AIX.party_bytes()
  end
  if mode == "hand_back" then return "hand_back", false end
  -- ★★ 袋が満タンなら、**どのモードでも**人に返します（RX3-0406 / 依頼者 2026-09-23）。
  --
  --   ⚠⚠ すぐ下の「アイテムを手に入れた」（`result_unusual`）は、★品が**入ったあと**の
  --     変化で見ています。⚠ 満タンだと品は**入らない**ので 1 バイトも動きません。
  --   ⚠⚠ 2026-09-23 に実機で踏みました: 無人の run（`advance`）が
  --     「なにか すてますか?」の**一覧**に A を **41 回**押していました
  --     （★`work/dq3-probe/battle_ai_run/20260923-105601/economy_auto_b7_end.png`）。
  --   → ★捨てるのは戻せないので、⚠ **無人でも押さずに返します**。
  local _levels, bag = AIX.party_bytes()
  if AIX.bag_full(bag) == true then
    R.why = "もちものがいっぱい"
    return R.why, false
  end
  if mode == "advance" then return nil, false end
  local why = AIX.result_unusual()
  if why ~= nil then return why, false end
  -- ★ファンファーレが鳴っている間だけ待つ（★実機: ゲームが自分で 79 フレーム後に場所の曲へ戻す）。
  --   ⚠ `RESULT_WAIT` は上限（★曲が戻らなくても、そこから先は送る）
  return nil, AIX.battle.track() == AIX.VICTORY_TRACK and (now - R.since) < AIX.RESULT_WAIT
end

--- ★この戦闘で勝利の結果を見たか（★終わりの言葉を「勝利」にする）。
function AIX.result_seen()
  return AIX.result.since ~= nil and AIX.result.no == AIX.battle.battle_no
end

--: ★★ 結果の文を送っているか（RX3-0169 §18）。
--   ★戦闘 AI の Auto は RESULT で終わる（Auto OFF / Turbo OFF）。⚠ その後の
--     「ファンファーレを待って経験値・ゴールドを送る」は**別の処理**としてここで持つ。
AIX.result_sending = false
--: ★勝ったときの終わりの言葉（★モードごと）
AIX.RESULT_TAIL = {simple = "（結果は自動で送る）", hand_back = "（ここから手で送る）",
                   advance = "（結果も全部送る）"}

--- ★結果の文を送るのをやめる（★送り終わった / 人に返す / 送れない）。
function AIX.result_end(why)
  if not AIX.result_sending then return end
  AIX.result_sending = false
  BUTTONS.release(ME)
  say("RESULT " .. tostring(why))
end

--- ★ターンの頭（★AI が作戦を立てた直後）に、高速化を決める / 見直す。
function AIX.speed_plan(plan, ctx)
  local sit = plan ~= nil and plan.situation or nil
  local ids = {}
  for _, g in ipairs((ctx and ctx.enemies) or {}) do
    if g.id ~= nil and (g.n or 0) > 0 then ids[#ids + 1] = g.id end
  end
  local B = AIX.battle
  -- ⚠⚠ 戦闘の種類は入口で 1 回だけ決める（RX3-0344）。★食い違いが出たら 1 戦闘 1 行だけ残す
  --   （⚠ 判断には使わない / ★どの番地が動くのかを次の実機 run で掴むため）
  if B.special_drift ~= nil then pcall(B.special_drift) end
  local ok, err = pcall(AIX.fast.on_plan, {
    battle_no = B.battle_no, phase = B.phase(), auto = true, ai_ok = plan ~= nil,
    enemy_ids = ids, situation = sit ~= nil and sit.kind or nil,
    dead = sit ~= nil and #(sit.dead or {}) or nil, worst = sit ~= nil and sit.worst or nil,
    special = B.special(), turn = ctx and ctx.turn or nil,
    -- ★膠着の見張り（RX3-0327 §11）: 行動の種類を問わない敵 HP 合計
    enemy_hp = sit ~= nil and sit.enemy_hp or nil})
  if not ok then
    say("FAST ⚠ 判断で落ちた: " .. tostring(err))
    pcall(AIX.fast.abort, "エラー")
  end
end

--- ★毎フレーム（★段階を読み、高速化の戻し漏れを防ぐ）。戻り値: いまの段階。
function AIX.speed_tick(on)
  local B = AIX.battle
  -- ★単独のとき（dev.lua 無し）に段階を進めるのは frame の頭（⚠ ここだと A で入れた TURBO が同じフレームの
  --   「新しい戦闘」で消えた / RX3-0237）
  local ph = B.phase()
  local ok, err = pcall(AIX.fast.tick, {frame = emu.framecount(), phase = ph, auto = on,
                                        battle_no = B.battle_no})
  if not ok then
    say("FAST ⚠ 見張りで落ちた: " .. tostring(err))
    pcall(AIX.fast.abort, "エラー")
  end
  -- ★AI が使えない（設定の v0）ときも、戦闘ごとに「通常の速さ」と決めて残す
  --   ★戦闘開始時「自動」が入れた TURBO（origin AUTO）は、AI の判断が無いので戻す（⚠ 人の A・T の TURBO は戻さない / RX3-0237）
  if on and ph == "ACTIVE" and (AIX.fast.mode == nil or AIX.fast.origin == "AUTO") and not AIX.enabled() then
    pcall(AIX.fast.on_plan, {battle_no = B.battle_no, phase = ph, auto = true, ai_ok = false})
  end
  return ph
end

--: ★★ 倒したことのある敵だけなら、人が A を押さなくても Auto に入る（2026-09-11 依頼者
--   「勝利済のモンスターの場合は自動的にオート・ターボ戦闘に入ってほしい」）。
--   ★戦闘の本体（ACTIVE）に入ったフレームで**1 回だけ**見る（⚠ 人が手動に戻したら入れ直さない）。
--   ★入り切りは戦闘AI設定画面「戦闘開始時 自動 / 手動」（RX3-0237）→ `work/generated/dq3_battle_auto.lua`
--     （⚠ 無ければ YAML の `auto_battle.auto_start_known` / 既定 true）。⚠ upvalue を増やさない（AIX に置く）
AIX.known_auto = {no = nil}

function AIX.load_known_auto()
  local on = AUTO.auto_start_known
  if on == nil then on = true end
  local ok, got = pcall(dofile, write_root .. "/work/generated/dq3_battle_auto.lua")
  if ok and type(got) == "table" and got.auto_known ~= nil then on = got.auto_known == true end
  return on
end

--- ★この戦闘で自動で Auto に入るか（★戦闘ごとに 1 回だけ true になりうる）。
function AIX.known_start(on)
  local B = AIX.battle
  if B.phase() ~= "ACTIVE" or AIX.known_auto.no == B.battle_no then return false end
  AIX.known_auto.no = B.battle_no
  if on or AIX.result_sending or not AIX.load_known_auto() then return false end
  -- ⚠ 戦闘中のセーブを読んだときは、この戦闘の図鑑の写しがまだ無い（★NONE → ACTIVE が 1 フレーム）
  if AIX.fast.battle_no ~= B.battle_no then pcall(AIX.fast.begin, B.battle_no) end
  local ids = {}
  for _, g in ipairs(read_enemies() or {}) do
    if g.id ~= nil and (g.n or 0) > 0 then ids[#ids + 1] = g.id end
  end
  local ok, go, why = pcall(AIX.fast.may_auto_start,
                            {enemy_ids = ids, special = B.special(), party = read_party(),
                             -- ★窓の色（RX3-0225 / ⚠ 以前は死者・HP 30% を数えていた）
                             window_color = AIX.window_color()})
  if not ok then
    say("[AUTO] ⚠ 自動で入るかを決められない: " .. tostring(go))
    return false
  end
  say(string.format("[AUTO] 倒したことのある敵か: %s（%s）",
      go and "はい → Auto に入る" or "いいえ → 手動のまま", tostring(why)))
  return go == true
end

--: ★内部の語 → 人が読む言い方（⚠ 画面へ出す言葉はここだけ / RX3-0123 と同じ作法）
local SITUATION_UI = {mop = "消化戦", advantage = "優勢", even = "均衡",
                      disadvantage = "劣勢"}
local ROLE_UI = {physical = "物理", magic = "魔法", support = "支援",
                 heal = "ヒール", defend = "防御"}
local ACTION_UI = {attack = "こうげき", defend = "ぼうぎょ", spell = "じゅもん",
                   item = "どうぐ"}

--- ★1 手ぶんを、画面が出せる形へ（⚠ 生の値を混ぜない）。
local function slot_view(slot, assign, action, member)
  local target = nil
  if action ~= nil and action.target ~= nil then
    if action.target.group ~= nil then target = "g" .. action.target.group end
    if action.target.ally ~= nil then target = action.target.ally end
  end
  return {
    slot = slot,
    role = assign ~= nil and (ROLE_UI[assign.role] or assign.role) or nil,
    tier = assign ~= nil and assign.tier or nil,
    command = action ~= nil and (ACTION_UI[action.kind] or action.kind) or nil,
    name = action ~= nil and action.name or nil,     -- ★呪文・道具の名前
    target = target,
    hp = member ~= nil and member.hp or nil,
    hp_max = member ~= nil and member.hp_max or nil,
  }
end

--- ★計画 1 つぶんを `AIX.status` へ写す（⚠ 判断はしない。★写すだけ）。
function AIX.publish(plan, ctx)
  local st = AIX.status
  st.active = true
  st.turn = (ctx and ctx.turn) or 0
  st.strategy = (ctx and ctx.strategy) or nil
  st.mp_policy = (ctx and ctx.mp_policy) or nil
  local sit = plan ~= nil and plan.situation or nil
  st.situation = sit ~= nil and (SITUATION_UI[sit.kind] or sit.kind) or nil
  st.win = sit ~= nil and sit.win or nil
  st.lose = sit ~= nil and sit.lose or nil
  --: ★必要な役割（⚠ 「HP低下 → 回復優先」等の要約の材料）
  local needs = {}
  for _, n in ipairs(plan ~= nil and plan.needs or {}) do
    needs[#needs + 1] = ROLE_UI[n.role] or n.role
  end
  st.needs = needs
  --: ⚠ 手が足りない / 動けない（★そのまま短く出す）
  local notes = {}
  for _, m in ipairs(sit ~= nil and sit.alive or {}) do
    local why = AIX.pipe ~= nil and AIX.pipe.mods.roles.blocked_by(m) or nil
    if why ~= nil then notes[#notes + 1] = m.slot .. "=" .. why end
  end
  st.notes = notes
  local by_slot = {}
  for _, m in ipairs((ctx and ctx.party) or {}) do by_slot[m.slot] = m end
  local slots = {}
  for _, slot in ipairs({"p1", "p2", "p3", "p4"}) do
    local action = plan ~= nil and plan.actions[slot] or nil
    if action ~= nil then
      slots[#slots + 1] = slot_view(slot, plan.assigned[slot], action, by_slot[slot])
    end
  end
  st.slots = slots
end

--- ★戦闘が終わった / AUTO を切った（⚠ 中身は残す。★`active` だけ倒す）。
function AIX.publish_idle()
  AIX.status.active = false
end

function AIX.reload()
  if AIX.pipe == nil then return false end
  return AIX.pipe:reload()
end

--- ★戦闘のはじめ / 終わりで忘れる。
function AIX.reset()
  AIX.plan, AIX.last_index, AIX.turn, AIX.confirmed, AIX.aim_state = nil, nil, 0, {}, nil
  if AIX.pipe ~= nil then AIX.pipe:reset_battle() end
  -- ★戦闘が終わったら「いま戦っていない」に倒す（⚠ 中身は残す / 直前の戦闘を見せる）
  if AIX.publish_idle ~= nil then AIX.publish_idle() end
end

--- ★この人の手番の実コマンド。⚠ AI が使えなければ nil（★呼ぶ側が設定へ落とす）。
--
--   ★ターンの区切りは「前より前の人の手番が来た」か、
--   「同じ人が、決めたあとにもう一度来た」（★1 人パーティ）。
function AIX.decide(actor, members)
  if not AIX.enabled() then return nil end
  local idx = actor.index or 0
  local new_round = AIX.plan == nil or AIX.last_index == nil or idx < AIX.last_index
    or (idx == AIX.last_index and AIX.confirmed[actor.slot] == true)
  if new_round then
    AIX.turn = AIX.turn + 1
    AIX.confirmed = {}
    -- ★★ 呪文がかき消される場所では、呪文を 1 つも積まない（RX3-0320 / 2026-09-20）
    --   ⚠⚠ 依頼者「呪文をかきけすダンジョンでは、呪文をつかわないようにしたい」。
    --   ★実機は **MP を引いてから**消すので、⚠ 唱えるだけ損です。
    --   ★`mp_policy = "forbid"` にすると `Roles.caps` が呪文を積みません（roles.lua）。
    local no_magic = Core.no_magic_here(CFG.no_magic)
    local ctx = {turn = AIX.turn, party = members, enemies = read_enemies(),
                 no_magic = no_magic,
                 -- ★予測と実測を結びつける鍵（RX3-0371 / ⚠ フレーム数は使わない）
                 battle_no = AIX.battle ~= nil and AIX.battle.battle_no or nil,
                 mp_policy = no_magic and "forbid" or nil}
    -- ★前のターンの最後の行動を締める（RX3-0371 / ⚠ 落とさない）
    do
      local hp = 0
      for _, m in ipairs(members or {}) do hp = hp + (m.hp or 0) end
      local ok2, tail, per_turn = pcall(AIX.watch_begin, ctx.battle_no, ctx.turn, hp)
      if ok2 then
        if tail ~= nil then say(tail) end
        -- ★前のターンに**受けた合計**（RX3-0372 / ⚠ 1 行動ごとより確か）
        if per_turn ~= nil then say(per_turn) end
      end
    end
    local ok, plan = pcall(AIX.pipe.plan_turn, AIX.pipe, ctx)
    if not ok then
      say("AI ⚠ 判断で落ちた: " .. tostring(plan))
      AIX.plan = nil
      return nil
    end
    AIX.plan = plan
    -- ★判断が決まったこの瞬間に、1 度だけ写す（⚠ 毎手番ではない）
    pcall(AIX.publish, plan, ctx)
    -- ★★ ターンの頭で高速化を決める / 見直す（RX3-0166 / 依頼者 §12・§24）
    AIX.speed_plan(plan, ctx)
  end
  AIX.last_index = idx
  local a = AIX.plan and AIX.plan.actions[actor.slot] or nil
  if a == nil then return nil end

  -- ★★ 押す直前に「まだ実行できるか」だけ見る（RX3-0134 / 指示書 v1.1 §5）。
  --   ⚠⚠ **再計画ではありません。** 戦況分類も作戦も見直しません。
  --   ★`members` はこの手番で読み直したものなので、⚠ 計画時から動いた分がここに出ます。
  if AIX.legality ~= nil then
    local now = {party = members, enemies = read_enemies()}
    local me = nil
    for _, m in ipairs(members or {}) do
      if m.slot == actor.slot then me = m end
    end
    local caps = AIX.plan and AIX.plan.caps and AIX.plan.caps[actor.slot] or nil
    -- ⚠ 作戦・MP 方針・道具の表も渡す（RX3-0429 / P-14・P-16 / ★見直しでも制約を守る）
    local lcat = AIX.pipe and AIX.pipe.cat or nil
    local lctx = AIX.plan ~= nil
      and {mp_policy = AIX.plan.mp_policy, strategy = AIX.plan.strategy,
           tuning = lcat and lcat.tuning or nil,
           items = lcat and lcat.items or nil} or nil
    local ok2, fixed, lines = pcall(AIX.legality.check, a, now, me or actor, caps, lctx)
    if ok2 and fixed ~= nil then
      for _, line in ipairs(lines or {}) do say(line) end
      a = fixed
    elseif not ok2 then
      say("AI ⚠ 直前の見直しで落ちた: " .. tostring(fixed))   -- ⚠ 計画のまま押す
    end
  end

  -- ★tally / strategy は戦闘のまとめ用（RX3-0198 / `COUNT.add`）。⚠ 押し方は変えない
  -- ★spell: 呪文の ID（★呪文の窓の何ページ目かを引く / RX3-0240）
  return {kind = a.kind, spell_tiles = a.spell_tiles, item_tiles = a.item_tiles, spell = a.spell,
          target = a.target, why = a.why or "", primary = a.kind,
          fallback = a.fallback or "attack", ai = true, tally = AIX.tally_of(a),
          strategy = AIX.plan and AIX.plan.strategy or nil}
end

--- ★呪文の種類 → まとめの種類（★生成物の表の kind / ⚠ 分からなければ役割で）。
function AIX.tally_of(a)
  if a == nil then return nil end
  -- ★道具: 攻撃の道具（まどうしのつえ など）は magic、それ以外（やくそう）は heal（RX3-0213）
  if a.kind == "item" then return (a.item == "attack") and "magic" or "heal" end
  if a.kind ~= "spell" then return nil end
  local cat = AIX.pipe and AIX.pipe.cat
  local s = cat and cat.spells and cat.spells[a.spell] or nil
  local k = s and s.kind or nil
  if k == "attack" then return "magic" end
  if k == "heal" or k == "revive" then return "heal" end
  -- ★★ 即死（ザキ / ザラキ）は**攻撃**として数えます（RX3-0330 / 2026-09-21）。
  --   ⚠⚠ 実機ログで見つけた誤り: ★`kind == "instant"` がここで「支援」に落ちていたため、
  --     「ザラキを 13 回撃ったのに、まとめは `support=11`」になっていました。
  --   ★判断の道も攻撃と同じです（`caps.instant` → `attack_pool` → `judge_magic`）。
  --   ⚠ ラリホー・マヌーサ（`sleep` / `surround`）は今までどおり支援です。
  if k == "instant" and s.effect == "beat" then return "magic" end
  if k ~= nil then return "support" end
  return ({magic = "magic", heal = "heal", support = "support"})[a.role or ""]
end

--- ★道具の一覧で、名前のすぐ左に文字の印があるか（★装備中の E など / RX3-0213）。
--
--   ⚠⚠ 未確認: 戦闘の どうぐ の窓で、装備中の品に印が出るか・どの升か（★実機の窓を撮っていない）。
--   ★印が文字のタイルなら ▶ は印のさらに左に来て、▶ の右は「印 ＋ 名前」になる
--     → ★寄せる升を 1 つ左へ、合わせる語を画面の「印 ＋ 名前」にする。
--   ★印が枠・空白のタイルなら `Cursor.label_at` が飛ばすので、今までどおり（★何もしない）。
--   `x` は `find_row` の戻り値（★0 始まりの列）。戻り値: want_x, want_tiles
function AIX.item_mark(nt, x, y, tiles)
  if x == nil or x < 2 then return x, tiles end
  local left = nt[y * COLS + x]                     -- ★列 x - 1（0 始まり）の升
  if left == nil or left == 0 or left == CURSOR then return x, tiles end
  if left >= Cursor.TEXT_MAX and not Cursor.TEXT_EXTRA[left] then return x, tiles end
  return x - 1, Cursor.label_at(nt, x - 2, y)
end

--- ★味方の一覧で、その人の名前がある行（★▶ の右の列だけを見る。⚠ 上の状態窓と混同しない）。
local function ally_row(nt, cx, cy, member)
  if member == nil then return nil end
  local seq = {}
  for _, b in ipairs(member.name or {}) do
    if b == 0 then break end
    seq[#seq + 1] = b
  end
  if #seq == 0 then return nil end
  local best, best_d = nil, nil
  for y = 0, ROWS - 1 do
    if Cursor.starts_with(Cursor.label_at(nt, cx, y), seq) then
      local d = math.abs(y - cy)
      if best == nil or d < best_d then best, best_d = y, d end
    end
  end
  return best
end

--- ★点滅している ▶ を、計画の対象へ寄せる。★着いていれば true（呼ぶ側が A を押す）。
--
--   ⚠ 動かないときは数回で諦めて、いまの位置で決める（★永久に回らない）。
function AIX.aim(nt, cx, cy, plan, members)
  local t = plan.target
  if t == nil then return true end
  local st = AIX.aim_state
  if st == nil then
    st = {base_y = cy, last_y = cy, stuck = 0, want_y = nil}
    AIX.aim_state = st
    if t.group ~= nil then
      st.want_y = cy + (t.group - 1) * AIX.ROW_STEP
    elseif t.ally ~= nil then
      local who = nil
      for _, m in ipairs(members or {}) do if m.slot == t.ally then who = m end end
      st.want_y = ally_row(nt, cx, cy, who)
      if st.want_y == nil then
        say("  target ⚠ 味方の一覧に " .. tostring(t.ally) .. " が見つからない。★いまの位置で決める")
        return true
      end
    end
  end
  if st.want_y == nil or cy == st.want_y then return true end
  if st.pressed and cy == st.last_y then
    st.stuck = st.stuck + 1
    if st.stuck >= AIX.STUCK_MAX then
      say(string.format("  target ⚠ ▶ が (%d) から動かない。★いまの位置で決める", cy))
      return true
    end
  end
  st.last_y = cy
  st.pressed = true
  if cy < st.want_y then press("down") else press("up") end
  return false
end

rawset(_G, "DQ3_AUTO_AI", AIX)

--: ★▼（メッセージ送り）。⚠ A か B で送れる（依頼者 2026-08-27）
local MORE_TILE = 0x73
--: ⚠ ▼ を送る間隔
local MORE_GAP = CFG.more_gap or 20
--: ★戦闘フラグが降りてから、この回数だけ様子を見てから終わる
local OUTRO_SETTLE = CFG.outro_settle or 60
--: ⚠ 画面がこの回数だけ止まっていたら A を送る（★演出中は触らない）
local OUTRO_POKE = CFG.outro_poke or 30
--: ⚠⚠ 送っても進まないなら止める（★永遠に押し続けない）
--: ⚠⚠ 40 にしていたら、フィールドで**40 回メニューを開け閉めした**（実機）。
--   ★数回で止める。⚠ 進まないなら、それは想定外の画面。
--: ⚠⚠ **連続して**無駄だった回数の上限（★進めば 0 に戻る）。
--
-- ⚠ 2026-08-29 実機: ここを「総数」として数えていたため、
--   **画面はちゃんと進んでいるのに** 6 回で `outro_stuck` と言って止まった
--   （★1 回の戦闘終わりに 2 度起きた。依頼者が A を押し直していた）。
--   → ★進んだら 0 に戻す。⚠ 「止まっている」の勘定は、止まっている間だけ数える。
local OUTRO_MAX_POKES = CFG.outro_max_pokes or 6
--: ⚠ それでも青天井にしない（★総数の歯止め）。
--   ⚠⚠ フィールドの判定（地形 500 マス）が先に効くので、ここは保険。
local OUTRO_MAX_TOTAL = CFG.outro_max_total or 40
-- ⚠ ここから下で増やすときは、`luacheck.py` が upvalue 超過を捕まえる。
--: ⚠ レベルアップを記録に残すためだけの語（★空なら使わない）
local LEVEL_TILES = CFG.level_up_tiles

--- ★★ 気持ちよく終わる（⚠ 止まるのとは違う）。
--
-- ⚠⚠ 2026-08-27 依頼者:
--   「自動戦闘は、終了の処理が甘い。戦闘が終わった場合と、
--    レベルアップして終わった場合は通常に終了させたい」
--
-- ★これまでは戦闘コマンドが消えたら**何もせず返していた**ので、
--   ⚠ ON のまま・ターボのまま・メッセージも送らずに放置していた。
local function finish(reason, source)
  if not enabled then return end
  enabled = false
  step = "choose"
  stopped_reason = nil
  -- ★終わったので手を離す（⚠ 押しかけも捨てる）
  BUTTONS.release(ME)
  -- ⚠⚠ ターボのまま返さない（★人がまともに操作できなくなる / ★元の速さへ）
  AIX.fast.auto_off(source or "DONE")
  say("[AUTO] ON -> OFF source=" .. tostring(source or "DONE"))
  -- ⚠⚠ **戦闘ごとの数**として出す（★2026-09-10 まで累積のままでした / RX3-0153）
  -- ★RX3-0198: 後ろに作戦・行動の内訳・MP 消費（`COUNT.fields`）。⚠ rounds= actions= の並びは変えない
  say(string.format("AUTO_V0_DONE %s rounds=%d actions=%d%s", reason,
                    COUNT.rounds, COUNT.actions, COUNT.fields(read_party())))
  -- ★次の戦闘は 1 ターン目から（★支援の「1 戦闘に 1 度」も忘れる）
  COUNT.reset()
  AIX.reset()
end

local function stop(reason)
  if not enabled then return end
  enabled = false
  stopped_reason = reason
  step = "choose"
  -- ⚠⚠ 止まったのにターボのままだと、人が操作できない（★元の速さへ）
  AIX.fast.abort("止まった: " .. tostring(reason), "ERROR")
  say("[AUTO] ON -> OFF source=ERROR")
  say("AUTO_V0_STOP reason=" .. reason)
  -- ⚠⚠ **止まった理由だけでは足りない。★そのときの画面を残す。**
  --   （まんたん側と同じ。⚠ 推測で直さないために要る）
  if last_nt ~= nil then
    say("  ★画面（32x30 / 上から）:")
    for y = 0, ROWS - 1 do
      local row = {}
      for x = 0, COLS - 1 do
        local v = last_nt[y * COLS + x + 1]
        row[#row + 1] = string.format("%02X", (type(v) == "number") and v or 0)
      end
      say(string.format("    y=%02d %s", y, table.concat(row, " ")))
    end
  end
end

--: ★キーの立ち上がり（⚠ 中身は `core.lua`。押しっぱなしで暴れないように）
--: ⚠ ゲーム画面への重ね書き（★依頼者 2026-08-29「一旦いらない」）。
--   ★右の画面で同じことが見えるようになったため。
--   ⚠ 設定 `ui.overlay: true` で戻せる。
local OVERLAY = (CFG.ui or {}).overlay == true
local function show(x, y, text)
  if OVERLAY then gui.text(x, y, text) end
end

local edge = Core.new_edge()

----------------------------------------------------------------------
-- ★設定から「何をするか」を決める
----------------------------------------------------------------------

local function decide(actor, members)
  -- ★★ 戦闘 AI v1 が使えるなら、そちらの判断（RX3-0126）。⚠ 使えなければ設定へ
  local got = AIX.decide(actor, members)
  if got ~= nil then return got end
  local spec = (AUTO.commands or {})[actor.slot]
  if spec == nil then return {kind = "attack", why = "既定"} end
  local kind = spec.primary or "attack"
  local why = "primary"
  -- ★HP が減っていたら fallback へ（依頼者の案「HP を見て切り替える」）。
  --   ⚠ 割合で見る（最大 HP は人ごとに違う）。
  local below = spec.hp_below or 0
  if below > 0 and actor.hp_max > 0 and actor.hp * 100 < actor.hp_max * below then
    kind = spec.fallback or "attack"
    why = string.format("HP%d/%d<%d%%", actor.hp, actor.hp_max, below)
  end
  -- ⚠ MP が足りなければ fallback へ（★唱えてから「MPがたりない」を見ない）
  if kind == "spell" and (spec.min_mp or 0) > 0 and actor.mp < spec.min_mp then
    kind = spec.fallback or "attack"
    why = string.format("MP%d<%d", actor.mp, spec.min_mp)
  end
  -- ★★ `primary` と `fallback` も持ち帰る（RX3-0020 / 2026-08-30）。
  --   ⚠ 「窓にそのコマンドが無い」ときの落とし先に要る。
  -- ★`spell` は呪文の ID（⚠ 賢者の系統を決めるのに要る / RX3-0293）。
  --   ⚠ 名前から引けなかった設定では nil（★そのときは系統の窓で押さずに止まる）
  return {kind = kind, spell_tiles = spec.spell_tiles, why = why, spell = spec.spell_id,
          primary = spec.primary, fallback = spec.fallback}
end

--- ★レベルアップらしさを**記録に残す**（⚠ 制御には使わない）。
--
-- ⚠⚠ 依頼者は「『レベルがあがった』的な文字で判断できる」と言ったが、
--   ★DQ3 は濁点を **1 行上の別タイル**で描くので、`ベ` が文字表に無い。
--   → 「レベル」はそのままでは照合できない（★実際に生成が落ちた）。
--
-- ★代わりに**最大 HP が増えたか**で見る。⚠ 数字なので取り違えない。
--   ⚠ ただし「必ずレベルアップ」ではないので、**推定**として書く。
local function level_note(members)
  if members == nil then return "" end
  local total = 0
  for _, m in ipairs(members) do total = total + (m.hp_max or 0) end
  local note = ""
  if last_max_hp ~= nil and total > last_max_hp then
    note = string.format(" / ★レベルが上がったらしい（最大HP %d → %d）",
      last_max_hp, total)
  end
  last_max_hp = total
  return note
end

--- ★★ フィールドに戻ったか（⚠ 戻ったら**絶対に押さない**）。
--
-- ⚠⚠ 2026-08-27 実機: `$62` で「戦闘中か」を判断して**大失敗した**。
--   依頼者「戦闘は終わったが、無駄な画面が何回か出た」。
--   ★フィールドで A を 40 回叩き、メニューを開け閉めしていた。
-- ⚠ その後は画面のマス数（500 未満 = 戦闘）で見ていたが、⚠ 建物の中が「戦闘」に見える
--   （RX3-0157）。
-- ★★ 2026-09-11（RX3-0166）: **DQ3 自身の段階**で見る（`battle_state.lua`）。
--   NONE / EXITING  = 戦闘の外（⚠ 押さない）
--   RESULT          = 勝ったあとの結果（★既定は人に返す / advance のときだけ送る）

--- ★▼ が出ているか。⚠ 出ていれば A で送れる。
--
-- ★★ レベルアップも「けいけんち」も、**全部これで通る**。
--   ⚠ 文字を読む必要がない（★濁点が 1 行上の別タイルなので、
--     「レベル」のような語はそのままでは照合できない）。
local function find_more(nt)
  if nt == nil then return nil end
  for y = 0, ROWS - 1 do
    for x = 0, COLS - 1 do
      if nt[y * COLS + x + 1] == MORE_TILE then return x, y end
    end
  end
  return nil
end

--: ★コマンドと、窓に出ている語の対応。
--   ⚠⚠ `item`（どうぐ）と `flee`（にげる）は**入れない**。
--     ★押すと下位のメニューへ入ってしまい、戻り方を知らない。
local COMMAND_TILES = {attack = MENU.attack, defend = MENU.defend,
                       spell = MENU.spell}
--: ★★ 戦闘 AI だけが押せる語（RX3-0126）。⚠ 設定の戦闘には出さない。
--   ★どうぐ は「一覧 → 対象」の戻り方が呪文と同じ形なので、AI の計画でだけ押す。
AIX.COMMAND_TILES = {item = MENU.item}

local function row_of(nt, kind, plan)
  if kind == nil then return nil end
  local tiles = COMMAND_TILES[kind]
  if tiles == nil and plan ~= nil and plan.ai then tiles = AIX.COMMAND_TILES[kind] end
  return find_row(nt, tiles)
end

--- ★★ 窓にある中から、この手番で出すコマンドを選ぶ。
--
-- ⚠⚠ **窓に出るのは、その人がいま使えるコマンドだけ**（★実測 / RX3-0020）。
--   実機で撮った戦闘画面 123 枚のうち、描き終わっている 24 枚を数えると:
--
--     19 枚  たたかう / じゅもん / にげる / どうぐ   ⚠⚠ ぼうぎょ が無い
--      4 枚  たたかう / にげる / ぼうぎょ / どうぐ   ★呪文を覚える前
--      1 枚  たたかう / じゅもん / ぼうぎょ / どうぐ
--
--   ★呪文を覚えると じゅもん が枠に入り、**ぼうぎょ が押し出される**。
--   ⚠ これを「止まる」で扱っていたのが `command_missing:p4=defend` の正体。
--
-- ★落とす順番: いま出したいもの → `fallback` → `primary`。
--   ⚠ どれも窓に無ければ nil（★これまでどおり止まる。暴走はしない）。
local function pick_row(nt, plan)
  local order = {plan.kind}
  if plan.fallback ~= nil then order[#order + 1] = plan.fallback end
  if plan.primary ~= nil then order[#order + 1] = plan.primary end
  local seen = {}
  for _, kind in ipairs(order) do
    if not seen[kind] then
      seen[kind] = true
      local y, x = row_of(nt, kind, plan)
      if y ~= nil then return y, kind, x end
    end
  end
  return nil
end

--- ★点滅している ▶ を目標へ寄せるか、着いていれば決定する。★決定したら true
--
-- ⚠⚠ **着いたかどうかは座標で決めない。**
--   ★`▶` の右にある語が目当てのものと一致したときだけ押す
--   （依頼者「その点滅の右がコマンドの内容」）。
--   ⚠ 行だけで見ていたので、隣の窓の ▶ に引きずられていた。
--
-- ⚠⚠ **横にも動かすこと。** ★呪文の一覧は **2 列**ある。
--   実測（`work/dq3-probe/ppu_trace.txt`）: 同じ y=20 の行に
--   `$2289=(9,20)` と `$228D=(13,20)` の 2 か所へ 72 が書かれている。
--   ⚠ 縦にしか動かさないと、右の列の呪文は**永久に決まらない**。
--
-- ★`want_x` は**カーソルの升**（⚠ 文字の 1 つ左）。
--
-- ★★ 呪文の窓（`grid`）は横を先に寄せ、⚠ 押しても ▶ が動かなければ別の向きを試す（RX3-0242 / `AIX.grid_press`）。
local function move_or_confirm(nt, cx, cy, want_x, want_y, want_tiles, grid)
  -- ★呪文の窓（grid）は ▶ の右の語が**丸ごと**同じときだけ決める（RX3-0270）。
  --   ⚠ 頭が同じだけ（▶ が「メラミ」で、欲しいのが「メラ」）で A を押していた
  local label = Cursor.label_at(nt, cx, cy)
  if Cursor.starts_with(label, want_tiles) and (not grid or #label == #want_tiles) then
    AIX.grid_move = nil
    press("A")
    return true
  end
  local v = (cy > want_y and "up") or (cy < want_y and "down") or nil
  local h = (cx > want_x and "left") or (cx < want_x and "right") or nil
  if grid then return AIX.grid_press(cx, cy, v, h) end
  -- ⚠ 同じ升に居るのに右の字が違う ＝ **別の窓の ▶ を見ている**。
  --   ★押さない（呼び出し側の歯止めが拾う）。
  if (v or h) == nil then return false end
  press(v or h)
  return false
end

--- ★★ 呪文の窓で ▶ を 1 つ寄せる（RX3-0242 / 2026-09-13 依頼者「save7 2ページ目で止まってしまう場合がある」）。
--
--   ★実機（RX3-0240 の証跡 work/evidence/20260913-150623-spell-pages の .blink）:
--     縦は空いた升を飛ばして同じ列の次の呪文へ（⚠ 下に無ければ**動かない**）/ 横はもう片方の列の呪文へ（★行が違っても）/
--     いちばん上から「上」で → へ / → から「下」で左の列の最初の呪文へ。
--   ⚠ 2 ページ目は空いた升が多い。2 ページ目で唱えた次の戦闘は 2 ページ目・右の列の ▶ で開き、
--     縦を先に押して動かないまま spell_cursor_stuck で止まった（→ から縦に行き来して右の列へ行けないこともあった）。
--   → ★横を先に。押しても同じ升のままなら、その向きは「動かない」と覚えて 横 → 縦 → 上（→）の順に次を試す。
--   ★状態は AIX.grid_move（⚠ frame の upvalue を増やさない）。★戻り値は false（★決めるのは move_or_confirm）
AIX.GRID_RETRY_FRAMES = 240     --: ★この間に同じ升から押した向きを「動かなかった」とみなす
function AIX.grid_press(cx, cy, v, h)
  local m = AIX.grid_move
  local now = emu.framecount()
  if m == nil or m.x ~= cx or m.y ~= cy or now - m.at > AIX.GRID_RETRY_FRAMES then
    m = {x = cx, y = cy, tried = {}, at = now}   -- ★動いた（または初めて）→ 数え直す
  elseif m.key ~= nil then
    m.tried[m.key] = true                        -- ⚠ 同じ升のまま = 前に押した向きでは動かなかった
  end
  AIX.grid_move = m
  local key = nil
  for _, k in ipairs({h or false, v or false, "up"}) do
    if k and not m.tried[k] then key = k; break end
  end
  if key == nil then return false end            -- ⚠ 打つ手が無い（★呼ぶ側の上限で止める）
  if m.key ~= nil and m.tried[m.key] then
    say(string.format("  pick_spell ⚠ %s で ▶ が動かない (%d,%d) → %s を試す", m.key, cx, cy, key))
  end
  m.key, m.at = key, now
  press(key)
  return false
end

--- ★★ 呪文の窓の 2 ページ目へ（RX3-0240 / 2026-09-13 依頼者「ページを変えるには、上の→を選択する」）。
--
--   ★実機（隔離先 / work/evidence/20260913-150623-spell-pages）: 窓の上の枠に → （タイル 0x84）。
--     一覧のいちばん上の行で「上」→ ▶ が → の左の升へ / そこで A → ページが入れ替わる（▶ は → のまま / A でまた戻る）。
--     ★→ は 2 ページ目に呪文を持つ人の窓にだけ出る。⚠ 左右ではページは替わらない。
--   ★出ているページに呪文が無いとき、pick_spell が呼ぶ。戻り値:
--     true  = 押した（★この frame はここまで）/ nil = ▶ がまだ見えない（★呼ぶ側の上限で待つ）
--     false = もう打つ手が無い（→ が無い / 2 回替えても無い / ▶ を寄せられない）→ 呼ぶ側が spell_not_found で止める
--   ★数えるのは AIX.page（⚠ frame の upvalue を増やさない）。★計画が変わったら数え直す
AIX.PAGE_GAP = 30          --: ★ページを替えた・▶ を動かしたあと、次に見るまで（★実測 +4 で描き終わる / 余裕を見て 30）
AIX.PAGE_SWITCH_MAX = 2    --: ★ページを替える上限（★2 ページなので 2 回で元のページへ戻る）
AIX.PAGE_UP_MAX = 6        --: ★▶ を → へ寄せる「上」の上限

function AIX.spell_page(nt, plan)
  local pg = AIX.page
  if pg == nil or pg.plan ~= plan then
    pg = {plan = plan, switches = 0, ups = 0}
    AIX.page = pg
  end
  if pg.switches >= AIX.PAGE_SWITCH_MAX then
    if not pg.told then pg.told = true; say("  pick_spell ⚠ 2 ページとも探したが無い") end
    return false
  end
  local cx, cy = track.active()
  if cx == nil then return nil end
  -- ★▶ の行か、それより上にある → のうち、いちばん近いもの（⚠ ほかの窓の → を掴まない）
  --   ⚠ ▶ が → の左へ来ると、→ は ▶ と**同じ行**（★「上だけ」を探して、寄せた直後に見失った）
  local ax, ay, best = nil, nil, nil
  for y = 0, cy do
    for x = 1, COLS - 1 do
      if (nt[y * COLS + x + 1] or 0) % 256 == Cursor.LINK then
        local d = (cy - y) * 100 + math.abs(cx - (x - 1))
        if best == nil or d < best then ax, ay, best = x, y, d end
      end
    end
  end
  if ax == nil then
    if not pg.told then pg.told = true; say(string.format("  pick_spell ⚠ 窓に → が無い（▶ (%d,%d)）", cx, cy)) end
    return false
  end
  if cx == ax - 1 and cy == ay then
    press("A")
    pg.switches, pg.ups = pg.switches + 1, 0
    track.forget()                     -- ★ページが替わっても ▶ は同じ升（⚠ 新しい点滅は出ない → 覚え直す）
    say(string.format("  pick_spell ★→ でページを替えた（%d 回目 / → (%d,%d)）", pg.switches, ax, ay))
    return true
  end
  if pg.ups >= AIX.PAGE_UP_MAX then
    if not pg.told then pg.told = true; say("  pick_spell ⚠ ▶ を → へ寄せられない") end
    return false
  end
  pg.ups = pg.ups + 1
  say(string.format("  pick_spell ★→ へ ▶ を寄せる（上 %d 回目 / ▶ (%d,%d) → (%d,%d)）", pg.ups, cx, cy, ax - 1, ay))
  press("up")
  track.forget()
  return true
end

--- ★★ 賢者の「呪文の系統を選ぶ窓」（RX3-0293 / 2026-09-18 依頼者「けんじゃの…呪文選択に対応できていない」）。
--
--   ⚠⚠ 賢者は魔法使いと僧侶の**両方**を覚えるので、`じゅもん` のあとに 1 段挟まります。
--   ★実測（依頼者の save1 / 窓(4,22)）:
--
--       じゅもん          ← 窓の上の枠
--       ▶まほうつかい
--        そうりょ
--
--   ⚠ この窓には呪文名が 1 つも無いので、今までは探し続けて `spell_not_found` で止まっていました。
--
--   ★見分け方は**職業ではなく画面**（⚠ 転職した人を職業から当てにいくと外れる）:
--     「まほうつかい」と「そうりょ」が**両方**出ている窓 ＝ 系統の窓。
--     ⚠ 片方だけなら系統の窓ではない（★つよさの窓などに 1 語だけ出ることはある）。
--   ★どちらを押すかは **ROM のブロック**（`ai/catalog.lua` の `family_of` / RX3-0125）。
--
--   戻り値: nil      = 系統の窓ではない（★今までどおり呪文を探す）
--           "wait"   = 系統の窓だが ▶ がまだ点滅していない（⚠ 呪文として探しにいかせない）
--           true     = 押した・動かした（★この frame はここまで）
--           false, 理由 = 打つ手が無い（★呼ぶ側が止める）
AIX.FAMILY_GAP = 30        --: ★系統を決めたあと、呪文の一覧が描かれるまで待つ（★ページ送りと同じ 30）
AIX.FAMILY_PRESS_MAX = 1   --: ⚠ 系統を決めるのは 1 戦 1 回（★押しても変わらないなら止める）
AIX.FAMILY_MOVE_MAX = 8    --: ⚠ ▶ を寄せる上限（★永久に押し続けない）

function AIX.spell_family(nt, plan)
  local rows = {}
  for _, family in ipairs({"mage", "pilgrim"}) do
    local seq = (CFG.spell_family_tiles or {})[family]
    if seq ~= nil then
      local y, x = find_row(nt, seq, true)
      if y ~= nil then rows[family] = {y = y, x = x, tiles = seq} end
    end
  end
  -- ⚠ **両方**出ていて初めて系統の窓（★片方だけの行に釣られない）
  if rows.mage == nil or rows.pilgrim == nil then
    AIX.family = nil
    return nil
  end
  local fam = AIX.family
  if fam == nil or fam.plan ~= plan then
    fam = {plan = plan, presses = 0, moves = 0}
    AIX.family = fam
  end
  if fam.presses >= AIX.FAMILY_PRESS_MAX then
    return false, "spell_family_stuck"        -- ⚠ 押したのに窓が変わらない
  end
  -- ★系統の規則は `ai/catalog.lua` に 1 つだけ（⚠ ここに書き写さない）
  local pipe = AIX.pipe
  local Cat = pipe and pipe.mods and pipe.mods.catalog or nil
  local want = Cat ~= nil and Cat.family_of(pipe.cat, plan.spell) or nil
  if want == nil or rows[want] == nil then
    return false, "spell_family_unknown"      -- ⚠ どちらの系統か決められない（★押さない）
  end
  local cx, cy = track.active()
  if cx == nil then return "wait" end         -- ★点滅がまだ（⚠ 呼ぶ側の上限が拾う）
  local row = rows[want]
  if move_or_confirm(nt, cx, cy, row.x - 1, row.y, row.tiles) then
    fam.presses = fam.presses + 1
    track.forget()
    say(string.format("  pick_spell ★系統 %s を決定 (%d,%d)", want, row.x - 1, row.y))
    return true
  end
  fam.moves = fam.moves + 1
  if fam.moves > AIX.FAMILY_MOVE_MAX then
    return false, "spell_family_stuck"
  end
  track.forget()
  return true
end

----------------------------------------------------------------------
-- 毎フレーム
----------------------------------------------------------------------

--- ★毎フレームの処理。
--
-- ⚠ `dev.lua` から動かすときは、あちらが 1 つの `registerafter` から呼ぶ。
--   ★単独で起動したときは、この下で自分で登録する。
local function frame()
  -- ★★ T でターボだけを入り切りする（依頼者 2026-08-27 / ★DQ2 に合わせる）
  --   ⚠ 自動戦闘とは**別のスイッチ**。★戦闘を目で追いたいときに切れる。
  --
  -- ⚠⚠ `dev.lua` から動かすときは、**あちらが T を見る**。
  --   ★ここでも見ると、1 回押しただけで 2 回反転して元に戻る
  --   （足場が捕まえた: 「1 回のタップで 2 回反転している」/ 2026-08-29）。
  if HOST == nil and edge(KEY_TURBO) then
    -- ★T は Turbo ボタンと同じ（★Auto 中の速さ / RX3-0169）
    AIX.turbo_request("T_KEY")
  end

  -- ★キーでも、画面のボタンでも同じことが起きる（RX3-0019）。
  --   ⚠ `wants` は**取り出したら消える**ので、2 回きかない。
  -- ⚠ どちらの経路で来たかを残す（★実機でしか出ない不具合を追うため）
  -- ★単独のとき（dev.lua 無し）は、ここで戦闘の段階を進める（★A・自動で入れる判断より先 / RX3-0237）。
  --   ⚠ dev.lua があるときは dev.lua が機能より先に進めている
  if HOST == nil then pcall(AIX.battle.tick) end
  local by_key = edge(KEY_AUTO)
  local by_ui = (not by_key) and HOST ~= nil and HOST.wants("auto")
  -- ★★ A キーと Auto ボタンは同じ（RX3-0169）。⚠ 戦闘の本体（ACTIVE）でだけ効く
  if (by_key or by_ui) and not AIX.may_toggle(by_key and "A_KEY" or "UI") then
    by_key, by_ui = false, false
  end
  -- ★倒したことのある敵だけなら、押さなくても入る（★戦闘ごとに 1 回だけ / 2026-09-11 依頼者）
  local by_known = (not by_key) and (not by_ui) and AIX.known_start(enabled)
  if by_key or by_ui or by_known then
    enabled = not enabled
    stopped_reason = nil
    same_frames = 0
    step = "choose"
    -- ★入り切りのたびに手を離す（⚠ ON 側はこのあと毎フレーム握り直す）
    BUTTONS.release(ME)
    -- ⚠⚠ 入れ直したのに前の勘定が残っていると、**その場で終わる**。
    --   ★足場で踏んだ（Q で ON にした次のフレームに AUTO_V0_DONE が出た）。
    outro_frames = 0
    sent_more = false
    outro.seen, outro.still, outro.pokes, outro.total = nil, 0, 0, 0
    last_max_hp = nil
    no_blink = 0
    -- ⚠ 前に見ていた点滅を引きずらない（★切っている間の分）
    --   ⚠ 見張りはまんたんと**共有**している。★向こうが動いている最中に
    --   忘れさせても、あちらは十数フレーム待って捕まえ直すだけで済む
    --   （`no_blink` が 0 に戻る）。⚠ 押しはしないので安全側。
    track.forget()
    -- ★★ Auto を入れたら TURBO も ON / 切ったら TURBO も OFF（RX3-0237 仕様 §3）。
    --   ★人（A_KEY / UI）は判断を越える / 戦闘開始時「自動」（AUTO_KNOWN）は危険化で TURBO だけ戻す
    local source = by_key and "A_KEY" or (by_ui and "UI" or "AUTO_KNOWN")
    if enabled then
      AIX.result_mode = AIX.pick_result_mode(by_ui)
      AIX.result_sending = false
      -- ★いまの窓の色も渡す（RX3-0225: 窓の色は「変わった瞬間」で見る → ★緑のまま人が入れた Auto は続く）
      AIX.fast.auto_on(AIX.battle.battle_no, source, AIX.window_color())
    else
      AIX.fast.auto_off(source)
    end
    say(string.format("[AUTO] %s source=%s", enabled and "OFF -> ON" or "ON -> OFF", source))
    -- ★入り切りのたびに AI の勘定も 1 ターン目へ戻す
    AIX.reset()
    say("AUTO_V0 " .. (enabled and "ON" or "OFF")
      .. (enabled and (" / 結果 " .. AIX.result_mode) or "")
      .. (AIX.enabled() and " / AI v1" or ""))
  end

  -- ★★ 窓の色がオレンジ / 緑なら Auto を切って人へ返す（RX3-0225 / 2026-09-12 依頼者「３割という別論理ではなく、
  --   赤黄色ないし緑に画面がなったら止める（等速化ではなく、オート解除）」）。★Auto 中は毎フレーム見る
  --   （⚠ 以前の RX3-0199 / RX3-0219 はターンの頭の劣勢・死者・HP 30% だった）。
  --   ★決めるのは battle_speed（印 take_manual）、切るのはここ（finish / source=DANGER / Turbo も OFF）。
  --   ★人が入れた Auto も自動で入った Auto も、人が押した Turbo の戦闘も切る。⚠ upvalue を増やさない（AIX 経由）
  --   ★AUTO OFF・TURBO ON（人が T で速くして手で戦っている / RX3-0237）も見る → 危ない色で TURBO だけ OFF
  if enabled or AIX.fast.fast then AIX.watch_window() end
  if enabled and AIX.fast.take_manual ~= nil then
    local why = AIX.fast.take_manual
    AIX.fast.take_manual = nil
    finish(why .. "（ここから手で戦う）", "DANGER")
  end

  -- ★画面で作戦や役割を変えたら、生成物を読み直す（★反映は次のターンから）
  if HOST ~= nil and HOST.wants("ai_reload") then
    say("AI 設定を読み直す（ai_reload）")
    AIX.reload()
  end

  -- ★★ 段階と高速化（RX3-0166）。⚠ AUTO を切っている間も見る（★戻し漏れを起こさない）
  local ph = AIX.speed_tick(enabled)

  local head = enabled and "AUTO v0: ON" or
    ("AUTO v0: OFF" .. (stopped_reason and (" (" .. stopped_reason .. ")") or ""))
  show(4, 14, head .. "  " .. COUNT.text())
  local members = read_party()
  show(4, 24, "HP/MP " .. party_text(members))
  show(4, 34, KEY_AUTO .. " = 入り切り / " .. KEY_TURBO .. " = ターボ" .. (SPEED.manual and "（ON）" or ""))

  -- ★★ 敵が**実際に何をしたか**を見る（RX3-0371 / ⚠ 判断には使わない / 記録だけ）。
  --   ⚠ 戦っている間だけ。★`AI predict` と `battle` / `turn` で結びつきます。
  if ph == "ACTIVE" then
    local hp = 0
    for _, m in ipairs(members or {}) do hp = hp + (m.hp or 0) end
    local ok, line = pcall(AIX.watch_step, hp)
    if ok and line ~= nil then say(line) end
  end

  if not enabled and not AIX.result_sending then
    -- ★切っている間は手を離しておく（⚠ もう片方の機能が握れるように）
    BUTTONS.release(ME)
    return
  end

  -- ★★ ボタンを握る。⚠ もう片方の機能が握っていれば**何も押さない**。
  --
  --   ⚠⚠ `joypad.set` は後勝ちなので、両方が押すと片方が黙って消える。
  --   ★ここで待つほうが、消えるより 100 倍ましです（理由が画面に出る）。
  if not BUTTONS.claim(ME) then
    show(4, 44, "⚠ " .. tostring(BUTTONS.owner) .. " が操作中のため待機")
    return
  end

  -- ★★ 勝利・結果（RX3-0166）。⚠ 速さは `speed_tick` が先に元へ戻している。
  --   simple     ★ファンファーレを待ってから結果の文を送る。⚠ レベルアップ・アイテム・
  --              いつもと違う曲が出たら、押しかけも捨てて**人に返す**
  --   hand_back  すぐ人に返す / advance  全部送る（⚠ 無人の run だけ）
  if ph == "RESULT" then
    if enabled then
      -- ★★ 戦闘 AI の Auto はここで終わる（Auto OFF / Turbo OFF / RX3-0169 §18）
      local trk = AIX.battle.track()
      local mode = AIX.result_mode
      BUTTONS.cancel(ME)
      finish((trk == AIX.VICTORY_TRACK and "勝利" or string.format("戦闘の結果（曲 %02X）", trk))
        .. (AIX.RESULT_TAIL[mode] or ""), "RESULT")
      AIX.result_sending = mode ~= "hand_back"
      if not AIX.result_sending or not BUTTONS.claim(ME) then return end
    end
    local why, hold = AIX.result_step(AIX.result_mode)
    if why ~= nil then
      BUTTONS.cancel(ME)
      AIX.result_end(why .. " → ここから手で送る")
      return
    end
    if hold then
      BUTTONS.cancel(ME)             -- ★ファンファーレの間は押さない（⚠ 最初の文を送ると曲が切れる）
      return
    end
  end

  -- ★★ 押しているボタンを、届くまで押し続ける（⚠ めくら撃ちにしない）
  --   ⚠ `cooldown` の中でも続ける。★でないと 1 フレームに戻ってしまう
  keep_pressing()

  if cooldown > 0 then
    cooldown = cooldown - 1
    -- ⚠⚠ **間隔の間も画面を観る。** ★何十フレームも待つので、
    --   ここで観ないと点滅をまるごと取りこぼす（まんたん側と同じ）。
    watch(read_nametable())
    return
  end

  local nt = read_nametable()
  if nt == nil then stop("ppu_unavailable"); return end
  watch(nt)
  -- ★止まったときに残す画面は、ここで覚える（RX3-0240 / ⚠ 下の選ぶ段だけで覚えていたので、呪文の一覧で止まると
  --   **押す前のコマンド窓**が残り、一覧が開いていないように見えた）
  last_nt = nt

  local attack_y = find_row(nt, MENU.attack)

  if attack_y ~= nil and not traced_battle then
    traced_battle = true
    dump_screen(nt, members)
  elseif attack_y == nil and ph == "NONE" then
    traced_battle = false
  end

  ------------------------------------------------------------------
  -- 呪文の一覧を選んでいる途中
  ------------------------------------------------------------------
  -- ★どうぐ の一覧も同じ形（RX3-0126）。⚠ 探す語だけが違う
  if step == "pick_spell" or step == "pick_item" then
    waited = waited + 1
    -- ★★ 賢者は「系統を選ぶ窓」が 1 段挟まる（RX3-0293）。⚠ 呪文の一覧だと決め打ちしない
    if step == "pick_spell" then
      local done, why = AIX.spell_family(nt, plan)
      if done == false then stop(why); return end
      if done == "wait" then
        -- ⚠ 系統の窓だが ▶ がまだ点滅していない（★呪文の一覧として探しにいかない）
        if waited > submenu_wait then stop("spell_family_cursor_not_blinking") end
        cooldown = 1
        return
      end
      if done == true then cooldown = AIX.FAMILY_GAP; return end
    end
    local list_tiles = (step == "pick_item") and plan.item_tiles or plan.spell_tiles
    -- ★呪文は語として丸ごと（RX3-0270）。⚠ 道具は左に装備の印が付くので今までどおり（RX3-0213）
    local want_y, want_x = find_row(nt, list_tiles, step == "pick_spell")
    -- ★道具の一覧: 名前の左に文字の印（装備の E など）があれば印ごと合わせる（RX3-0213）
    if want_y ~= nil and step == "pick_item" then
      want_x, list_tiles = AIX.item_mark(nt, want_x, want_y, list_tiles)
    end
    if want_y == nil then
      -- ★★ RX3-0240: 出ているページに無ければ、上の → でページを替えて探す（★呪文だけ / 道具は今までどおり）
      if step == "pick_spell" and AIX.spell_page(nt, plan) then
        cooldown = AIX.PAGE_GAP
        return
      end
      -- ⚠ そもそも一覧に出ない（覚えていない・名前が違う）。★押さずに止まる
      if waited > submenu_wait then
        stop((step == "pick_item") and "item_not_found" or "spell_not_found")
      end
      cooldown = 1
      return
    end

    -- ★★ 点滅している ▶ だけを見る（RX3-0020 / 2026-08-30）。
    --
    --   ⚠⚠ 以前はここが 2 度ひっくり返っている:
    --     ① 「カーソルが出るまで待つ」→ 消えている瞬間を見て**永久に待った**
    --     ② 「一番上の候補なら押す」 → ★一番上でなければ**進めなかった**
    --   ★点滅を捕まえられるようになったので、⚠ **寄せて決められる**。
    local cx, cy = track.active()
    if cx == nil then
      if waited % 60 == 1 then
        say("  pick_spell ⚠ 点滅している ▶ がまだ出ない / " .. track.report())
      end
      if waited > submenu_wait then stop("spell_cursor_not_blinking") end
      cooldown = 1
      return
    end

    -- ★呪文の窓は 2 列の升（★空いた升を飛ばす / RX3-0242）。⚠ 道具の一覧は今までどおり
    local moved = move_or_confirm(nt, cx, cy, (want_x or 1) - 1, want_y, list_tiles, step == "pick_spell")
    -- ⚠ 一覧の ▶ は**点滅する**ので、動かしたら覚え直す
    --   （★前の位置の点滅を引きずらない）。
    track.forget()
    if moved then
      say(string.format("  %s ★決定 want=(%d,%d)", step, want_x or -1, want_y))
      step = "target"
      waited = 0
      AIX.aim_state = nil
      -- ★対象の窓に**新しく**出る点滅を捕まえたいので、いったん忘れる
      track.forget()
      -- ⚠ 一覧が閉じて対象の窓が出るまで少し待つ（★実測で 5-8 フレーム）
      cooldown = SUBMENU_GAP
    else
      -- ⚠⚠ **届かないまま回り続けないこと。** ★同じ升に居るのに
      --   右の字が違うと、`move_or_confirm` は何も押さずに戻る。
      --   ⚠ ここに歯止めが無いと、そのまま**永久に回る**
      --   （まんたん側の `MAX_MOVES` と同じ役目）。
      if waited > submenu_wait then stop("spell_cursor_stuck") end
      cooldown = SUBMENU_GAP
    end
    return
  end

  ------------------------------------------------------------------
  -- 対象を選ぶ（★画面が最初に選んでいる相手をそのまま決める / 指示 §2.4）
  --
  -- ⚠⚠ 2026-08-26: **ここが「呪文が決まらない」の正体だった。**
  --
  --   呪文を決めたあと、「誰に／どの敵に」を選ぶ**もう 1 段**がある。
  --   ★依頼者に普通に遊んでもらい、人の手順を記録して判明した
  --   （`work/dq3-probe/battle_record.txt`）。
  --
  --     回復（ホイミ） … ★味方の一覧が**別窓**で開く（[20_18_08_10]）
  --     攻撃（メラ）   … ⚠ **敵の窓にカーソルが付く**（新しい窓は開かない）
  --
  --   ⚠ 以前はここで**いきなり A を押していた**。対象の窓が出る前に押すので
  --   取りこぼし、そのまま噛み合わなくなっていた。
  --   ★**カーソルが見えてから**押す。見えなければ押さずに止まる。
  ------------------------------------------------------------------
  if step == "target" then
    -- ★呪文を決めた直後に見張りを忘れているので、
    --   **新しく点滅し始めたもの**がそのまま対象の ▶ になる。
    --
    --     味方を選ぶ … 味方の一覧に出る（実測 (21,20)）
    --     敵を選ぶ   … 敵の窓に出る（実測 (13,20)）
    waited = waited + 1
    local tx, ty = track.active()
    -- ⚠⚠ RX3-0233（2026-09-13 依頼者「save3 よくわからない理由で自動戦闘が中断」）: 全員にかける呪文（ピオリム）は
    --   選ぶ段が無く、すぐ次の人のコマンド窓が描き直される。⚠ その書き込みを点滅と見て、コマンドの ▶ (5,20) で A を押していた
    --   → 次の人が「たたかう」になり、敵を選ぶ画面と噛み合わず screen_frozen。★右にコマンドの語がある ▶ は相手の ▶ ではない
    if tx ~= nil and command_cursor(nt, tx, ty) ~= nil then tx, ty = nil, nil end
    if tx == nil then
      -- ★★ AI のコマンドには「選ぶ段が無い」ものがある（RX3-0126）:
      --   自分 / 味方全体 / 敵全体の呪文、群が 1 つのときの たたかう。
      --   ⚠ 点滅が出ないまま次の人の窓（静止した ▶）になるので、
      --   ★少し待って無ければ「選ぶ段は無かった」として次へ進む。
      if plan.ai and waited > AIX.OPTIONAL_WAIT then
        local n_act, n_round = COUNT.add(plan.slot, plan, members)
        say(string.format("AUTO_V0 turn=%d act=%d slot=%s action=%s target=none (%s) hp_mp=%s",
          n_round, n_act, tostring(plan.slot), plan.kind, plan.why or "",
          party_text(members)))
        step = "choose"
        waited = 0
        AIX.aim_state = nil
        cooldown = interval
        return
      end
      if waited % 60 == 1 then
        say("  target ⚠ 点滅している ▶ がまだ出ない / " .. track.report())
      end
      if waited > submenu_wait then stop("target_not_shown"); return end
      cooldown = 1        -- ★点滅するので何度も見る
      return
    end

    -- ★AI は対象を選ぶ（★群 k / 味方の名前）。⚠ 設定の戦闘は画面が選んでいる相手のまま
    if plan.ai and not AIX.aim(nt, tx, ty, plan, members) then
      track.forget()
      if waited > submenu_wait then stop("target_unreachable"); return end
      cooldown = SUBMENU_GAP
      return
    end

    press("A")
    local n_act, n_round = COUNT.add(plan.slot, plan, members)
    say(string.format("AUTO_V0 turn=%d act=%d slot=%s action=%s target=(%d,%d) (%s) hp_mp=%s",
      n_round, n_act, tostring(plan.slot), plan.kind, tx, ty, plan.why or "",
      party_text(members)))
    step = "choose"
    waited = 0
    AIX.aim_state = nil
    track.forget()
    -- ⚠ 決めたあとは演出が入る。★長めに何もしない
    cooldown = SUBMENU_GAP * 2
    return
  end
  ------------------------------------------------------------------
  -- コマンドを選ぶ
  ------------------------------------------------------------------
  if attack_y == nil then
    -- ★戦闘コマンド待ちではない（メッセージ中・戦闘が終わった後など）。
    --   ⚠⚠ 以前はここで数えていたため、**戦闘が終わっただけで止まっていた**。
    --   ⚠⚠ そして 2026-08-27 まで、ここで**何もせず返していた**ので、
    --     ON のまま・ターボのまま放置していた（依頼者の指摘）。
    same_frames = 0

    -- ★⓪ **戦闘の外に出ていないか**を最初に見る（★DQ3 自身の段階 / RX3-0166）。
    --   ⚠⚠ ここを間違えると、フィールドで A を叩いてメニューを開け閉めする。
    if ph == "NONE" or ph == "EXITING" then
      -- ★戦闘の外（または出口の最中）。⚠ 押しかけていたものも取り消す
      --   （★ただし手は離さない。まだ終わりの処理の途中）
      BUTTONS.cancel(ME)
      outro_frames = outro_frames + 1
      if outro_frames > OUTRO_SETTLE and ph == "NONE" then
        if AIX.result_sending then
          -- ★結果の文を送り切った（★シンプルな勝利 / RX3-0168）
          AIX.result_end("結果の文を送り終わった" .. level_note(members))
        else
          finish(string.format("戦闘が終わった（段階 %s）%s", ph, level_note(members)), "EXIT")
        end
      end
      return
    end
    outro_frames = 0

    -- ★① ▼ が出ていれば送る
    local mx, my = find_more(nt)
    if mx ~= nil then
      if not sent_more then
        sent_more = true
        say(string.format("  outro ★▼ が出た (%d,%d)%s", mx, my,
          level_note(members)))
      end
      press("A")
      cooldown = MORE_GAP
      return
    end
    sent_more = false

    -- ⚠⚠ 2026-08-27 実機: **勝利のあとの画面に ▼ は出ない。**
    --
    --   セーブ 0（8 ゴールドを手に入れて、経験値と G を見せている画面）:
    --
    --     $62 = 2          ⚠ 「255 か 0」ではない（★戦闘の**段階**を持つ）
    --     ▼ (0x73) = 0 個  ⚠⚠ 継続矢印は出ていない
    --     窓(8,10) 経験値と G の一覧 / 窓(4,18)「…8 ゴールドを てにいれた！」
    --
    --   ★人はここで A を押す。⚠ こちらは ▼ を待って永久に止まっていた。
    -- ★② 戦闘の画面のまま、コマンドも ▼ も無い。
    --   ★勝利のあとの「経験値と G」がこれ（⚠ ▼ を出さない。実測）。
    --   ⚠ 画面が**止まっていれば**送る（★動いている間は演出中なので触らない）。
    local d = digest(nt)
    if d ~= outro.seen then
      -- ★★ 画面が変わった＝**送りが効いた**。⚠ 無駄打ちの勘定を 0 に戻す。
      --   （⚠ 戻し忘れると、進んでいるのに「進まない」と言って止まる）
      outro.seen = d
      outro.still = 0
      outro.pokes = 0
      return
    end
    outro.still = outro.still + 1
    if outro.still > OUTRO_POKE then
      outro.pokes = outro.pokes + 1
      outro.total = outro.total + 1
      if outro.pokes > OUTRO_MAX_POKES then
        -- ⚠⚠ **同じ画面のまま**何度送っても動かない。★押し続けない
        local text = string.format("outro_stuck（段階 %s / 曲 %02X / 連続 %d 回）",
          ph, AIX.battle.track(), outro.pokes)
        if AIX.result_sending then AIX.result_end("⚠ " .. text .. " → ここから手で送る")
        else stop(text) end
        return
      end
      if outro.total > OUTRO_MAX_TOTAL then
        -- ⚠ 進んではいるが、いくらなんでも長い（★保険）
        local text = string.format("outro_too_long（送った総数 %d / 段階 %s）", outro.total, ph)
        if AIX.result_sending then AIX.result_end("⚠ " .. text .. " → ここから手で送る")
        else stop(text) end
        return
      end
      say(string.format(
        "  outro ★画面が止まっている。A で送る（連続 %d / 通算 %d / 段階 %s）%s",
        outro.pokes, outro.total, ph, level_note(members)))
      press("A")
      cooldown = MORE_GAP
      outro.still = 0
    end
    return
  end
  outro_frames = 0
  sent_more = false
  outro.seen, outro.still, outro.pokes, outro.total = nil, 0, 0, 0

  -- ★止まったときに残せるよう、いまの画面を覚えておく（⚠ 参照だけ）
  last_nt = nt

  -- ⚠ 押しているのに画面がまったく変わらないなら、それが本当の stuck
  --   ★`digest` はカーソルを数に入れない（⚠ 点滅は「進んだ」ではない）
  --
  -- ⚠⚠ **点滅を探すより先に見る。** ★寄せるたびに見張りを忘れるので、
  --   点滅を捕まえ直すまで何フレームか「▶ が無い」状態が続く。
  --   先に点滅を見ると、⚠ 止まった画面でも `cursor_not_blinking` が
  --   先に立ち、**本当の理由（screen_frozen）が隠れる**。
  local d = digest(nt)
  if d == last_seen then
    same_frames = same_frames + 1
    if same_frames > stuck_limit then stop("screen_frozen"); return end
  else
    last_seen = d
    same_frames = 0
  end

  -- ★★ コマンド窓の ▶ を探す（⚠ **ここは点滅しない**。実測 $22C5）。
  --   ★右にコマンドの語がある ▶ だけを本物とする。
  local cx, cy = command_cursor(nt)
  if cx == nil then
    no_blink = no_blink + 1
    if no_blink % 120 == 1 then
      say("  ⚠ コマンド窓の ▶ が見つからない")
    end
    if no_blink > stuck_limit then
      stop("cursor_not_found")
    end
    return
  end
  no_blink = 0

  local actor = actor_of(nt, attack_y, members)
  if actor == nil then
    -- ⚠ 誰の手番か分からない。★推測で押さない
    same_frames = same_frames + 1
    if same_frames > stuck_limit then stop("actor_unknown") end
    return
  end

  plan = decide(actor, members)
  local want_y, want_kind, want_x = pick_row(nt, plan)
  if want_y == nil then
    -- ⚠ どの候補もこの人の窓に無い。
    --   ⚠⚠ ただし**窓が描き終わる前**にも同じことが起きる（実機で 1 度踏んだ）。
    --   ★少し待ってから止める。それでも無ければ本当に無い。
    same_frames = same_frames + 1
    if same_frames > 30 then
      stop("command_missing:" .. actor.slot .. "=" .. plan.kind)
    end
    return
  end
  -- ⚠⚠ **誰の手番かを控える。** ★呪文は段をまたぐので、
  --   対象を決める段では `actor` が見えない。
  --   ⚠ 2026-08-30 実機: 呪文の手番だけ `slot=` が無く、
  --     **誰が唱えたのか記録から追えなかった**（★5 回とも）。
  plan.slot = actor.slot
  if want_kind ~= plan.kind then
    -- ⚠⚠ 窓に無かったので落とした（★実測: ぼうぎょ は 24 枚中 19 枚で無い）。
    --   ★理由は手番の行に出るので、記録を見れば**黙って変わっていない**。
    plan.why = plan.why .. "/⚠窓に" .. plan.kind .. "が無い"
    plan.kind = want_kind
  end

  if move_or_confirm(nt, cx, cy, (want_x or 1) - 1, want_y,
                     COMMAND_TILES[plan.kind] or (plan.ai and AIX.COMMAND_TILES[plan.kind])) then
    -- ★この人の手番は決めた（★AI がターンの区切りを見るのに使う）
    AIX.confirmed[actor.slot] = true
    if plan.kind == "spell" or plan.kind == "item" then
      -- ★呪文の一覧に**新しく**出る点滅を捕まえたいので、いったん忘れる
      track.forget()
      step = "pick_spell"
      if plan.kind == "item" then step = "pick_item" end     -- ★どうぐ は一覧の語が違うだけ
      waited = 0
      -- ⚠⚠ ここで次のフレームから判定していたため、**一覧が描かれる前**に
      --   押していた。★探索スクリプトは「A → 30 フレーム待ち」で通っている。
      --   → 決定したあとは**長めに何もしない**。
      cooldown = SUBMENU_GAP * 2
      return
    elseif plan.ai and plan.kind == "attack" and plan.target ~= nil then
      -- ★AI の たたかう は群を選ぶ（★群が 1 つなら選ぶ段は出ない → `target` が待って進む）
      track.forget()
      step = "target"
      waited = 0
      AIX.aim_state = nil
      cooldown = SUBMENU_GAP
      return
    else
      local n_act, n_round = COUNT.add(actor.slot, plan, members)
      say(string.format("AUTO_V0 turn=%d act=%d slot=%s action=%s (%s) hp_mp=%s",
        n_round, n_act, actor.slot, plan.kind, plan.why, party_text(members)))
    end
  end
  cooldown = interval
end

local function on_exit()
  say(string.format("=== AUTO_V0 end rounds=%d actions=%d ===",
    COUNT.rounds, COUNT.actions))
  pcall(function() trace:close() end)
  pcall(function() logfile:close() end)
end

-- ★★ `dev.lua` から読まれたときは、**自分では登録しない**。
--   ⚠⚠ 両方が `registerafter` すると、FCEUX は後のものしか覚えない
--   （★片方が黙って動かなくなる。エラーは出ない）。
if HOST ~= nil then
  HOST.features = HOST.features or {}
  HOST.features[#HOST.features + 1] = {
    name = ME, frame = frame, on_exit = on_exit,
  }
  return {name = ME, frame = frame, on_exit = on_exit}
end

emu.registerafter(frame)
emu.registerexit(on_exit)
