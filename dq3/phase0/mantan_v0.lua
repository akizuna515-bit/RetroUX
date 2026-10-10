-- まんたん v0 — フィールドで HP を回復する（RX3-0015 / 2026-08-27）。
--
-- ★★ 依頼者の指定 ★★
--
--   「満タンは HP をチェックして、9 割切ってたら僧侶がホイミ。ぐらいシンプルに」
--
-- ## ⚠⚠ 推測で書かない
--
--   戦闘の呪文では**推測で書いて 5 回失敗した**。
--   ★今回は依頼者に**普通に回復してもらった記録**（`work/runtime/dq3-probe/battle_record.txt`
--   の f=221601-222024）から、手順をそのまま起こしている。
--
--     A     → コマンド窓 [6,2]
--     right → じゅもん（⚠ **2 列**。★下ではない）
--     A     → 誰の呪文か [10,4]     ⚠ 戦闘には無い段
--     A     → 呪文の一覧 [20,2]     ⚠ 右上（戦闘では下）
--     A     → 対象の一覧 [4,6]
--     A     → 実行 → メッセージ
--     A ×2  → 閉じてコマンド窓へ戻る
--
-- ## ★守っていること（戦闘での失敗から）
--
--   1. ⚠ **想定の窓が出ていなければ、1 つも押さない**
--   2. ⚠ カーソルは**点滅する**。「見えない＝無い」としない。★見えたときだけ判断する
--   3. ★行番号を計算しない。**RAM の名前を画面から探して**位置を決める
--   4. ⚠ 迷ったら**押さずに止まる**（★理由を必ず残す）
--
-- 起動:
--   python scripts/run_probe.py mantan_v0

local function clean(p) return (p:gsub(string.char(92), "/"):gsub("/$", "")) end
local root = os.getenv("RETROUX_ROOT")
-- ⚠⚠ 開発機のパスへ落ちない（RX3-0466 / 2026-09-29）
if root == nil or root == "" then
  error("RETROUX_ROOT が立っていません（★起動は DQ3.cmd から / RX3-0466）")
end
root = clean(root)
local write_root = os.getenv("RETROUX_WRITE_ROOT")
write_root = (write_root ~= nil and write_root ~= "") and clean(write_root) or root

-- ★生成物は **write_root 側を先に**見る（RX3-0466 / 2026-09-29）。
--   ⚠⚠ 書くのは write_root だけ（★program 側には作らない）。
package.path = write_root .. "/work/generated/?.lua;"
             .. root .. "/work/generated/?.lua;" .. package.path
local ok_cfg, CFG = pcall(require, "dq3_phase0")
if not ok_cfg or CFG == nil then
  error("設定が読めません。★先に `python -m dq3.phase0.generate_lua` を実行してください")
end

-- ★★ 共有部分（RX3-0018 / 2026-08-29）。
--   ⚠⚠ `joypad.set` は後勝ち。★押す権利は `core.lua` の 1 つが持つ。
local Core = dofile(root .. "/dq3/phase0/core.lua")
--: ★`dev.lua` が置いていく入れ物（⚠ 単独で起動したときは nil）
local HOST = rawget(_G, "DQ3_DEV")
--: ★この機能の名前（⚠ ボタンの持ち主として使う）
local ME = "mantan"

local M = CFG.mantan or {}
local FIELD = CFG.field or {}
local PARTY = CFG.party or {}
local WINDOWS = FIELD.windows or {}
local MENU = FIELD.menu_tiles or {}
local COLS, ROWS = CFG.columns or 32, CFG.rows or 30
local CURSOR = CFG.cursor_tile
local SLOTS = {"p1", "p2", "p3", "p4"}

local TOP_LEFT = 0x79                 --: ★窓の左上の角（実測）
local TOP_RIGHT = 0x7C                --: ★窓の右上の角（実測）
local BOTTOM_LEFT = 0x7A              --: ★窓の左下の角（実測）
local BOTTOM_RIGHT = 0x7E             --: ★窓の右下の角（実測）
local EDGE_TOP = 0x77                 --: ★上辺の横線（実測）
local EDGE_LEFT = 0x76                --: ★左辺の縦線（実測）
--: ⚠ 窓と認めるいちばん狭い幅・高さ。
--   ★`dq3rom/window.py` の MIN_WIDTH / MIN_HEIGHT と**同じ数**にすること
--   （⚠ 違えると、片方だけが窓と認める食い違いが戻る）
local MIN_WIDTH = 3
local MIN_HEIGHT = 3
local INTERVAL = M.press_interval or 10
local WAIT = M.wait or 240
local MAX_CASTS = M.max_casts or 12
local HP_BELOW = M.hp_below or 90
local MIN_MP = M.min_mp or 0
--: ⚠ 1 つの段でカーソルを動かす上限。★4 人 + 余裕
local MAX_MOVES = M.max_moves or 8
--: ⚠⚠ **窓が出るまでの間**。★A を押しても窓はすぐ出ない。
--  実測: メニューは **25 フレーム**後に出た（f=221005 → f=221030）。
--  ⚠ 間隔が短いと「まだ出ていない」と見て**もう一度 A を押し**、
--  ★その 2 回目が開いたメニューの「はなす」を選んでしまう（実機で発生）。
local OPEN_GAP = M.open_gap or 45

----------------------------------------------------------------------
-- 記録
----------------------------------------------------------------------

local LOG = Core.open_log(write_root .. "/work/runtime/dq3-probe/mantan_v0.log",
                          "まんたんの記録")
local function say(s)
  if LOG == nil then return end
  LOG:write(tostring(s) .. string.char(10)); LOG:flush()
end
local function shut()
  if LOG ~= nil then local f = LOG; LOG = nil; pcall(function() f:close() end) end
end
say("")
say("=== MANTAN_V0 start " .. os.date("%Y-%m-%d %H:%M:%S") .. " ===")

----------------------------------------------------------------------
-- 画面
----------------------------------------------------------------------

--- ★画面を**スクロールを反映して**組み立てる。
--
-- ⚠⚠ 2026-08-27 実機で踏んだ: ここで**生のネームテーブル**を読んでいた。
--
--   窓の位置（`profile` の `field.windows`）は**画面**の座標。
--   ★スクロールしていると、生のネームテーブルでは**別の場所**にある。
--
--     実測（`DQ3_J.fc9` / スクロール 48,32）:
--       ★組み立てた画面   (6,2) = 79 77  → 窓
--       ⚠ 生のNT0そのまま (6,2) = F5 F5  → 地形
--       ⚠ 生では窓は (12,6) にあった
--
--   → 窓が**永久に見つからず**、45 フレームごとに A を押し続けた。
--   ★開いたメニューでは、その A が「はなす」を選ぶ（依頼者の報告どおり）。
--
-- ⚠ 昨日 probe 側では直したのに、**製品側に入れ忘れていた**。
local Screen = dofile(root .. "/dq3/phase0/screen.lua")
--: ★★ 画面の読み手は**共有**する（RX3-0019 / 2026-08-29）。
--
-- ⚠⚠ `memory.registerwrite` は番地ごとに 1 つしか覚えない。
--   ★自分で作ると、`dev.lua` 側の見張りと潰し合って
--   **スクロールを受け取れなくなる**（⚠ 窓の座標が 2 マスずれた）。
local screen_reader = (HOST and HOST.screen) or Screen.new()
if HOST == nil or HOST.screen == nil then screen_reader.install() end

-- ★★ 点滅しているカーソルを本物とみなす（2026-08-27 / 依頼者の着想）
--
--   「カーソルが点滅している、というのを捕まえられない？
--    その点滅の右がコマンドの内容なんだけど」
--
--   ★実測で裏が取れた（`work/runtime/dq3-probe/ppu_trace.txt`）:
--     点滅する ▶ … VRAM へ 72 と 00 を交互に書く
--     ⚠ 静止した ▶ … 1 回書かれたきり
--
--   ⚠⚠ これまで**静止した ▶ を本物と勘違い**して、何も進まなかった。
local Cursor = dofile(root .. "/dq3/phase0/cursor.lua")
--: ★★ 見張りは `dev.lua` が 1 つだけ持つ（RX3-0020 / 2026-08-30）。
--   ⚠⚠ `memory.registerwrite` は番地ごとに 1 つ。★2 つ作ると片方が黙る。
local track = (HOST and HOST.cursor) or Cursor.new()
-- ★★ 点滅は「画面を眺める」より「CPU が PPU に書く様子」で捕まえる。
--
--   ⚠ 依頼者の指摘（2026-08-27）:
--     「CPU が PPU に指令を送っているはずだから、動きで捉えられる」
--
--   ★眺める方法は 72/00 の入れ替わりを 2 回見るまで待つ（⚠ 周期 8 フレーム
--     なので最短でも十数フレーム）。★書き込みなら**その場で決まる**。
--   ⚠ 使えない環境（足場・古い版）では黙って眺めるほうに落ちる。
--: ⚠ 借りたものなら、`dev.lua` が既に入れている（★2 度入れない）
local watching_writes = (HOST ~= nil and HOST.cursor ~= nil)
  and track.by_writes or track.install_writes()
--: ★戦闘中か（RX3-0164）。★`dev.lua` から動かすときは共有の見張り、足場で単独に読むときだけ自分で作る（★nav_v0 と同じ）。
--   ⚠ まんたんはフィールドの手順しか知らない。戦闘中に M を押されると「B で変わらない窓」を見て
--   `window_will_not_close` で止まる**はず**だったが未実測 → ★判定（$32 == $FD かつ $60B7 & $20 / RX3-0166）で先に断る。
local Battle = (HOST ~= nil and HOST.battle)
  or dofile(root .. "/dq3/phase0/battle_state.lua").new({cfg = CFG.battle_state})

local function read_nt() return screen_reader.read() end

local function at(nt, x, y)
  if nt == nil or x < 0 or y < 0 or x >= COLS or y >= ROWS then return nil end
  return nt[y * COLS + x + 1]
end

--- ★その位置から右へ、同じ行に右上の角があるか。
--
-- ⚠⚠ 2026-08-29: **「角の右は必ず横線」は誤りだった。**
--
--   実機のセーブ 0（`tools/fceux/fcs/DQ3_J.fc0`）を描いて数えたところ、
--   ★パーティの状態窓は**上辺に名前が入っていた**:
--
--     y=20 x=6:  79 0B 10 32 00 78 4D 5A 4B 59 78 ... 77 7C
--                 ↑角  ↑⚠ 横線ではなく**文字**（「あかり」）
--
--   ⚠ そのため「窓は無い」と誤認し、★フィールドで A を叩いて暴れた
--   （依頼者 2026-08-29「満タンは暴れてしまうね」）。
--
--   ★`dq3rom/window.py`（Python 側）は**既にこれを知っていた**:
--   「右上角を探す（⚠ 上辺に文字が入る窓もあるので、中身は問わない）」。
--   ⚠⚠ 同じ判定を 2 か所に書いたので、**片方だけ直っていた**。
local function top_right_of(nt, x, y)
  for k = x + MIN_WIDTH - 1, COLS - 1 do
    local v = at(nt, k, y)
    if v == TOP_RIGHT then return k end
    if v == TOP_LEFT then return nil end     -- ⚠ 次の窓が始まった
  end
  return nil
end

--- ★四隅がそろって初めて「窓」と認める。
--
-- ⚠⚠ 2026-08-29（2 度目の直し）: **上辺だけでは緩すぎた。**
--   地形の `0x79` と、行のずっと右にある `0x7C` を結んで
--   ★実在しない窓 `(0,14)` を作り、閉じようとして 10 回 A を叩いた
--   （依頼者「満タンは暴れてしまうね」の 2 度目）。
--
--   ★`dq3rom/window.py` は**下辺（左下・右下の角）まで**見ている。
--   ⚠ 片側だけ真似たのが誤り。→ 同じところまで見る。
local function window_box(nt, x, y)
  local right = top_right_of(nt, x, y)
  if right == nil then return nil end
  for yy = y + MIN_HEIGHT - 1, ROWS - 1 do
    local left_v = at(nt, x, yy)
    if left_v == BOTTOM_LEFT and at(nt, right, yy) == BOTTOM_RIGHT then
      return right, yy
    end
    -- ⚠ 縦線が途切れたら、その窓ではない
    if left_v ~= EDGE_LEFT and left_v ~= BOTTOM_LEFT then return nil end
  end
  return nil
end

local function has_window(nt, x, y)
  return window_box(nt, x, y) ~= nil
end

--: ★★ パーティのステータス表示かどうか（RX3-0019 / 2026-08-29）。
--
--   依頼者:「パーティーのステータス表示は、何もしない時間があると勝手に
--            表示されて A ボタンを押すと消える表示。無視して OK」
--
--   ⚠⚠ B では**消えない**。★実機で B を 10 回押しても窓が変わらなかった。
--   → まんたんは**この窓を数に入れない**。⚠ 邪魔にならないため。
--
--   ★見分けは中身で行う。⚠ 位置や大きさで決め打ちしない（★戦闘中とフィールドで違う）。
--
--   ## ⚠⚠ 2026-09-18 訂正: 「1 行に 3 つ以上」では**一人のとき当たらない**
--
--     依頼者「save6 一人だと、まんたんがつかえない。窓の認識が違うんだと思う」。
--     ★実測（`work/runtime/dq3-probe/mantan_v0.log`）:
--
--       4 人  y=22  76 8C .. 8C .. 8C .. 8C .. 7B   ★H の札が **4 つ**
--             y=24  76 64 .. 64 .. 64 .. 64 .. 7B   ★下の札が **4 つ**
--       一人  y=22  76 00 8C 02 07 03 00 7B         ⚠ H の札は **1 つ**
--             y=24  76 00 64 00 05 05 00 7B         ⚠ 下の札も **1 つ**
--
--     ⚠ 旧い規則（`0x64` が 1 行に 3 つ以上）は**人数が 3 人以上**を勝手に前提にしていた。
--     → ★一人だとステータス表示を「閉じるべき窓」と数え、⚠ B では閉じないので
--       `window_will_not_close` で止まっていた（★依頼者の症状そのもの）。
--
--   → ★**2 種類の札が同じ数だけ並ぶ**で見分ける（⚠ 人数に関わらず成り立つ）。
--     ⚠ 1 種類だけでは弱い（★数字や他の窓に紛れる）ので、**両方そろう**ことを要る。
local HP_TILE = 0x8C                  --: ★「H」の札（実測: 人数ぶん並ぶ）
local LEVEL_TILE = 0x64               --: ★その下の札（実測: 同じ数だけ並ぶ）

local function count_in_row(nt, y, from_x, to_x, tile)
  local n = 0
  for xx = from_x, to_x do
    if at(nt, xx, y) == tile then n = n + 1 end
  end
  return n
end

local function is_status_window(nt, x, y)
  local right, bottom = window_box(nt, x, y)
  if right == nil then return false end
  local hp, level = 0, 0
  for yy = y + 1, bottom - 1 do
    local h = count_in_row(nt, yy, x + 1, right - 1, HP_TILE)
    local l = count_in_row(nt, yy, x + 1, right - 1, LEVEL_TILE)
    if h > hp then hp = h end
    if l > level then level = l end
  end
  -- ★人数ぶん並ぶ（⚠ 一人なら 1 つずつ / 4 人なら 4 つずつ）
  return hp >= 1 and hp == level
end

--- ★その位置に窓の左上の角があるか。
--
-- ⚠ 大きさは見ない。覚えている呪文の数で変わるため（★実測で h=4 だった）。
--
-- ⚠ `0x79` は地形にもある値なので、★1 マスだけでは弱い。
--   → **右上の角まで**見る（⚠ 上辺の中身は問わない）。
local function window_at(nt, name)
  local w = WINDOWS[name]
  if w == nil then return false end
  if at(nt, w[1], w[2]) ~= TOP_LEFT then return false end
  return has_window(nt, w[1], w[2])
end

--- ★画面に出ている窓の左上の角を全部拾う。
--
-- ⚠ 位置を決め打ちしない。★「新しく出た窓」を見分けるのに使う
--   （戦闘の対象選択で同じ手が効いた / 2026-08-26）。
local function window_corners(nt)
  local out = {}
  if nt == nil then return out end
  for y = 0, ROWS - 2 do
    for x = 0, COLS - 2 do
      if at(nt, x, y) == TOP_LEFT and has_window(nt, x, y)
         -- ⚠ ステータス表示は数に入れない（★B で消えない / 依頼者 2026-08-29）
         and not is_status_window(nt, x, y) then
        out[y * COLS + x] = {x, y}
      end
    end
  end
  return out
end

local function corners_text(c)
  local parts = {}
  for _, p in pairs(c) do
    parts[#parts + 1] = string.format("(%d,%d)", p[1], p[2])
  end
  table.sort(parts)
  return table.concat(parts, " ")
end

--- ★タイル列を画面から探す。⚠ 見つからなければ nil。
local function find(nt, seq)
  if nt == nil or seq == nil or #seq == 0 then return nil end
  for y = 0, ROWS - 1 do
    for x = 0, COLS - #seq do
      local hit = true
      for k = 1, #seq do
        if at(nt, x + k - 1, y) ~= seq[k] then hit = false; break end
      end
      if hit then return x, y end
    end
  end
  return nil
end

---- ★★ 点滅しているカーソルに**いちばん近い**ものを探す。
--
-- ⚠⚠ 2026-08-27 実機: `find` は画面を上から見て**最初の一致**を返す。
--   対象の一覧 (4,6) にエルシトが居るのに、
--   ★古い「誰の呪文か」窓 (10,4) のエルシトを先に拾った。
--
--     窓(4,6)  y=12 x=6  エルシト   ← ★本当の行き先（点滅から 3）
--     窓(10,4) y=10 x=13 エルシト   ← ⚠ こちらを拾った（点滅から 8）
--
--   ⚠ 結果、縦並びの一覧で **right を 9 回**押して止まった。
--
-- ★同じ名前が複数出るのは普通（★前の窓が残る）。
--   ⚠ 位置で決め打ちせず、**いま選んでいるものの近く**を採る。
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
          d = y * COLS + x            -- ⚠ 点滅が無ければ従来どおり上から
        else
          -- ★同じ列（＝同じ一覧）を強く優先する
          d = math.abs(x - (cx + 1)) * 8 + math.abs(y - cy)
        end
        if best == nil or d < best then bx, by, best = x, y, d end
      end
    end
  end
  return bx, by
end

-- ★いま見えているカーソルの位置。⚠ 点滅するので、無いこともある。
local function cursor_at(nt)
  if nt == nil then return nil end
  for y = 0, ROWS - 1 do
    for x = 0, COLS - 1 do
      if at(nt, x, y) == CURSOR then return x, y end
    end
  end
  return nil
end

----------------------------------------------------------------------
-- パーティ
----------------------------------------------------------------------

local function w16(a) return memory.readbyte(a) + memory.readbyte(a + 1) * 256 end

local function read_party()
  local out = {}
  local n = PARTY.slots or 4
  local size = (PARTY.entry_size or 2)
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
      local b = memory.readbyte(PARTY.name + i * nsize + k)
      -- ⚠ 名前の後ろの空白は入れない（★画面と比べるときに邪魔）
      if b ~= 0 then m.name[#m.name + 1] = b end
    end
    if m.hp_max > 0 then out[#out + 1] = m end
  end
  return out
end

--: ★★ 道具（やくそう / どくけしそう）の判断と進み具合（2026-09-11 依頼者 / RX3-0174）。
--   ★判断は mantan_items.lua、使う手順は item_use_v0.lua（HOST.item_use）。
--   ⚠ upvalue を増やさないため、ここで持つものは 1 つの表にまとめる（★Lua 5.1 の上限 60）。
local MX = {mi = dofile(root .. "/dq3/phase0/mantan_items.lua"), plan = nil, before = nil, waited = 0}
--: ★★ まんたん v1（RX3-0161 / 0163 / 0162 / 2026-09-12）: 覚えている呪文と呪文の表
--   （★戦闘 AI と同じ生成物 `dq3_ai.lua`）。⚠ 読めなければ v0（今までの決め方）のまま動く
MX.Catalog = dofile(root .. "/dq3/phase0/ai/catalog.lua")
-- ★生成物は **write_root 側を先に**見る（RX3-0466 / 2026-09-29）。
--   ⚠ 隔離して動かす検査では、書き込みだけ隔離先へ向き、★生成物は本物の場所にある
--     （`dq3/phase0/ai/pipeline.lua:52-61` と同じ作法）。だから root を控えに残す。
--   ⚠⚠ 配布 Runtime では program 側に生成物が無いので、★控えは空振りするだけで害はない。
MX.cat = MX.Catalog.load(write_root .. "/work/generated/dq3_ai.lua")
      or MX.Catalog.load(root .. "/work/generated/dq3_ai.lua")

--- ★その人がフィールドで唱えられる呪文（★ページ 3）。⚠ 材料が無ければ nil（= v0）
function MX.field_of(m)
  if MX.cat == nil or PARTY.spells == nil or PARTY.class_gender == nil then return nil end
  local stride, bytes = PARTY.spell_stride or 8, {}
  for k = 0, stride - 1 do
    bytes[#bytes + 1] = memory.readbyte(PARTY.spells + (m.index - 1) * stride + k)
  end
  return MX.Catalog.field_spells(MX.cat, bytes, memory.readbyte(PARTY.class_gender + m.index - 1) % 8)
end

--- ★毒・まひと袋を足す（⚠ 番地は設定から / 足場でも同じ道）。戻り値: 袋。
function MX.snapshot(members)
  local bags = {}
  for _, m in ipairs(members) do
    m.poisoned = MX.mi.poisoned(memory.readbyte, PARTY, m.index)
    -- ★まひ（RX3-0252 / 上位バイトの bit6）。⚠ まひの人は唱える人・持ち主にしない（判断は mantan_items.lua）
    m.paralyzed = MX.mi.paralyzed(memory.readbyte, PARTY, m.index)
    bags[m.index] = MX.mi.bag(memory.readbyte, PARTY, m.index)
    m.field = MX.field_of(m)
    -- ★勇者か（RX3-0214 / 勇者の MP は最後の手段）。★職業は下位 3 bit / 0 = 勇者（`dq3rom/item_meta.py`）
    m.hero = PARTY.class_gender ~= nil and memory.readbyte(PARTY.class_gender + m.index - 1) % 8 == 0
  end
  return bags
end

--- ★★ 語として**丸ごと**一致する所だけ（RX3-0163）。
--   ⚠ 「ホイミ」は「ベホイミ」の後ろ、「ベホマ」は「ベホマラー」の頭と同じ並び
--     → ★前後に字が続く所（もっと長い名前の中）は外す。★近さは find_near と同じ
function MX.find_word(nt, seq, cx, cy)
  if nt == nil or seq == nil or #seq == 0 then return nil end
  local function letter(v) return v ~= nil and v > 0 and v < 0x70 end
  local bx, by, best = nil, nil, nil
  for y = 0, ROWS - 1 do
    for x = 0, COLS - #seq do
      local hit = not letter(at(nt, x - 1, y)) and not letter(at(nt, x + #seq, y))
      for k = 1, #seq do
        if not hit then break end
        if at(nt, x + k - 1, y) ~= seq[k] then hit = false end
      end
      if hit then
        local d = (cx == nil) and (y * COLS + x) or (math.abs(x - (cx + 1)) * 8 + math.abs(y - cy))
        if best == nil or d < best then bx, by, best = x, y, d end
      end
    end
  end
  return bx, by
end

--- ★★ 賢者の「呪文の系統を選ぶ窓」（RX3-0293 / 2026-09-18）。
--
--   ⚠⚠ 賢者は魔法使いと僧侶の**両方**を覚えるので、唱える人を決めたあとに 1 段挟まります。
--   ★見分け方は**職業ではなく画面**（⚠ 転職した人を職業から当てにいくと外れる）:
--     「まほうつかい」と「そうりょ」が**両方**出ている ＝ 系統の窓。
--   ★どちらを押すかは ROM のブロック（`ai/catalog.lua` の `family_of` / ⚠ 規則はあちらに 1 つだけ）。
--
--   戻り値: 行の x, y と系統の名前（⚠ 系統の窓でなければ nil）
function MX.family_row(nt)
  local tiles = CFG.spell_family_tiles or {}
  local rows = {}
  for _, family in ipairs({"mage", "pilgrim"}) do
    local seq = tiles[family]
    if seq ~= nil then
      local x, y = MX.find_word(nt, seq, nil, nil)
      if x ~= nil then rows[family] = {x = x, y = y, tiles = seq} end
    end
  end
  -- ⚠ **両方**出ていて初めて系統の窓（★つよさの窓などに 1 語だけ出ることに釣られない）
  if rows.mage == nil or rows.pilgrim == nil then return nil end
  local want = MX.Catalog.family_of(MX.cat, MX.spell ~= nil and MX.spell.spell_id or nil)
  if want == nil or rows[want] == nil then return nil, "spell_family_unknown" end
  return rows[want], want
end

local function hex_of(tiles)
  local out = {}
  for _, b in ipairs(tiles or {}) do out[#out + 1] = string.format("%02X", b) end
  return table.concat(out)
end

--- ★道具を使い始める（★item_use_v0 に頼む）。戻り値: ok, 止まる理由。
function MX.begin(plan, cfg)
  local use = HOST ~= nil and HOST.item_use or nil
  if use == nil then return false, "item:use_missing" end
  -- ★まひは まんげつそう（RX3-0252）。⚠ 生成物に並びが無ければ空 → words_missing で止まる（★別の道具を頼まない）
  local item = hex_of(({cure = cfg.antidote_tiles, moon = cfg.moon_tiles, herb = cfg.herb_tiles})[plan.kind])
  local choose = hex_of(cfg.use_tiles)
  if item == "" or choose == "" then return false, "item:words_missing" end
  MX.plan, MX.waited = plan, 0
  MX.before = {hp = plan.target.hp, poisoned = plan.target.poisoned, paralyzed = plan.target.paralyzed}
  use.start({member = tostring(plan.holder.index), item = item, choose = choose,
             target = tostring(plan.target.index)}, nil)
  return true
end

--- ★道具を使い終わったか。⚠ まだなら nil / 終わったら {ok, reason}。
function MX.poll(members)
  local st = HOST.item_use.status()
  MX.waited = MX.waited + 1
  if st.active and MX.waited < 3600 then return nil end
  if st.active then return {ok = false, reason = "timeout"} end
  if st.reason ~= "used" then return {ok = false, reason = st.reason} end
  MX.snapshot(members)
  local after = nil
  for _, m in ipairs(members) do
    if m.slot == MX.plan.target.slot then after = m end
  end
  if not MX.mi.worked(MX.plan, MX.before, after) then return {ok = false, reason = "no_effect"} end
  return {ok = true, after = after}
end

local function healer_of(members)
  for _, m in ipairs(members) do
    if m.slot == (M.healer or "p3") then return m end
  end
  return nil
end

--- ★いちばん減っている人。⚠ 誰も減っていなければ nil。
local function neediest(members)
  local worst, worst_ratio = nil, 100
  for _, m in ipairs(members) do
    if m.hp_max > 0 and m.hp > 0 then
      local ratio = m.hp * 100 / m.hp_max
      if ratio < HP_BELOW and ratio < worst_ratio then
        worst, worst_ratio = m, ratio
      end
    end
  end
  return worst
end

----------------------------------------------------------------------
-- 進行
----------------------------------------------------------------------

local enabled, step, stopped = false, "idle", nil
local cooldown, waited, casts = 0, 0, 0
--: ⚠ 点滅を見つけられないまま過ぎたフレーム数
--  ★`waited` と別勘定にする。⚠⚠ `need_window` が毎フレーム `waited` を 0 に戻すため
--  （★これを共用して**永遠に待ち続けた**）
local no_blink = 0
--: ★1 つの段でカーソルを動かした回数（⚠ 届かないときの歯止め）
local moves = 0
--: ⚠ 直前に見た窓の並び（★押しても変わらないことを見分けるため）
local last_corners, unchanged = nil, 0
local target, healer = nil, nil
local hp_before = 0
--: ★キーの立ち上がり（⚠ 中身は `core.lua`）
--: ⚠ ゲーム画面への重ね書き（★依頼者 2026-08-29「一旦いらない」）。
--   ★右の画面で同じことが見えるようになったため。
--   ⚠ 設定 `ui.overlay: true` で戻せる。
local OVERLAY = (CFG.ui or {}).overlay == true
local function show(x, y, text)
  if OVERLAY then gui.text(x, y, text) end
end

local edge = Core.new_edge()

--: ★最後に読んだ画面（⚠ 止まったときに吐くため）
local last_nt = nil
--: ★呪文を決める**直前**に出ていた窓（⚠ 「新しく出た窓」を見分けるため）
local seen_windows = {}

--: ★★ まんたんの間だけターボにする（依頼者の案 / 2026-08-27）
--
-- ⚠ 通常速度だと、8 回唱えるのに何十秒も待つことになる。
-- ⚠⚠ **終わったら必ず戻すこと。** 止まったときも、M で切ったときも。
--   ★ターボのまま放置したら、人がまともに操作できない。
--
-- ⚠ `emu.speedmode` が無い環境でも落ちないように包む（★足場は偽の API）。
local TURBO = M.turbo
if TURBO == nil then TURBO = true end

--- ★★ 画面で変えた値を重ねる（RX3-0160 / 2026-09-11）。⚠ **始めるたびに**読む。
--
--   ★`work/generated/dq3_mantan.lua`（`dq3/phase0/mantan_settings.py` が書く）を
--     設定ファイルの値（`CFG.mantan`）の上に重ねます。⚠ 無ければ今までどおり。
--   ★読むのは M / 満 で**入れた瞬間だけ**（⚠ 毎フレームは開かない）。
--   ⚠ 判断のロジックは変えません（★値を差し替えるだけ / RX3-0158 §14）。
--   ⚠ ここで新しい local を増やさない（★Lua 5.1 の upvalue 上限 / 教訓）。
local function reload_settings()
  local out = {}
  for k, v in pairs(CFG.mantan or {}) do out[k] = v end
  local ok, got = pcall(dofile, write_root .. "/work/generated/dq3_mantan.lua")
  local screen = ok and type(got) == "table"
  if screen then
    for k, v in pairs(got) do out[k] = v end
  end
  M = out
  HP_BELOW = M.hp_below or 90
  MIN_MP = M.min_mp or 0
  MAX_CASTS = M.max_casts or 12
  TURBO = M.turbo
  if TURBO == nil then TURBO = true end
  say(string.format("MANTAN_V0 設定: 回復役 %s / HP %d%% 未満 / 唱えた後に MP %d 残す / ターボ %s / 回復のしかた %s%s",
    tostring(M.healer or "p3"), HP_BELOW, MIN_MP, TURBO and "ON" or "OFF",
    tostring(M.heal_order or "spell_first"), screen and "（★画面の設定を重ねた）" or ""))
  if type(M.casters) == "table" then
    say("MANTAN_V0 唱えてよい人: " .. table.concat(M.casters, ",") .. "（★勇者は ほかに唱えられる人が居ない時だけ）")
  end
end

--: ★★ キー割り当て（⚠ DQ2 に合わせる / 依頼者 2026-08-27）
--   ⚠ キーボードのキー。★NES の A ボタンは `F`。`Q` は FCEUX が予約済み。
local KEYS = CFG.keys or {}
local KEY_MANTAN = KEYS.mantan or "M"
local KEY_TURBO = KEYS.toggle_turbo or "T"

--: ★★ 速度のスイッチは `core.lua` が 1 つだけ持つ（RX3-0018）。
--   ⚠⚠ 以前は戦闘側とここの**両方**が `set_speed` を持っていた（★二重管理）。
local SPEED = (HOST and HOST.speed) or Core.new_speed({say = say})

local function set_speed(on)
  if not TURBO then return end
  SPEED.want(on)
end

local function stop(reason)
  if not enabled then return end
  enabled = false
  step = "idle"
  stopped = reason
  -- ⚠⚠ 止まったのにターボのままだと、人がまともに操作できない
  set_speed(false)
  say("MANTAN_V0_STOP reason=" .. reason)
  -- ⚠⚠ **止まった理由だけでは足りない。★そのときの画面を残す。**
  --   （2026-08-27: `target_window_missing` で止まったが、
  --    ⚠ 何が出ていたのか分からず、推測で直しかけた）
  if last_nt ~= nil then
    say("  ★そのとき出ていた窓: " .. corners_text(window_corners(last_nt)))
    say("  ★画面（32x30 / 上から）:")
    for y = 0, ROWS - 1 do
      local row = {}
      for x = 0, COLS - 1 do
        row[#row + 1] = string.format("%02X", at(last_nt, x, y) or 0)
      end
      say(string.format("    y=%02d %s", y, table.concat(row, " ")))
    end
  end
end

--: ⚠ 終わる理由を覚えておく（★窓を閉じてから言う）
local done_reason = nil

--: ★★ **自分でメニューを開いたか。**
--
-- ⚠⚠ 開けていない窓を閉じてはいけない。
--   ★人が開けたメニューを見ている最中に M を押されることがある。
--   そこで勝手に B を叩いたら、⚠ **人の操作を奪う**ことになる。
--
-- ★片付けるのは、自分が散らかしたときだけ。
local we_opened = false

--- ★★ 終わる。⚠ ただし**窓を開けっぱなしにしない**。
--
-- ⚠⚠ 2026-08-27 実機: 回復には成功したが、**窓が全部開いたまま**終わった。
--   依頼者「最後、俺が A ボタンを押して窓を全部閉じた」。
--   ★遊びの続きは人がやるので、**始めた形に戻して**返すのが筋。
--
-- ⚠ 閉じるのは **B**。★A だと、開いている一覧の項目を選んでしまう。
--   （回復のメッセージ ▼ は A でも B でも送れる ← 依頼者 2026-08-27）
local function done(reason)
  done_reason = reason
  stopped = nil
  if we_opened then
    step = "cleanup"
    waited = 0
  else
    -- ⚠ 自分は何も開けていない。★そのまま返す
    step = "finish"
  end
end

--- ⚠ 止まったときは**閉じない**。★そのときの画面が唯一の手がかりなので。
local function finish_now()
  enabled = false
  step = "idle"
  stopped = nil
  -- ⚠⚠ 速度を戻してから終わる（★ターボのまま返さない）
  set_speed(false)
  say("MANTAN_V0_DONE " .. (done_reason or "?") .. " casts=" .. casts)
  done_reason = nil
  we_opened = false
end

--: ★★ 何フレーム押し続けるか（⚠ 1 では届かない / 8 では 2 回選ばれる）
--
-- ⚠⚠ 2026-08-27 実機: **1 フレーム押しでは A がすり抜けた。**
--   ホイミの上で 300 フレーム点滅し続け、呪文が決まらなかった。
--   ★人が押すと効いたので、押し方のほうが原因だった。
--
-- ★ROM で裏を取った（`$CB16` / `$C341`）:
--
--     $CB1A  JSR $C341   ; ★1 フレーム待つ（$06D2 が変わるまで）
--     $CB1D  JSR $CB25   ; ★コントローラを読む
--     $CB20  LDA $14     ; 新しく押されたボタン
--     $CB22  BEQ $CB1A   ; ⚠ 無ければ戻る
--
--   ⚠ **読むのは 1 フレームに 1 回、NMI を待った直後の一瞬だけ**。
--   ⚠ セーブ 0 は LAGF=1。★ラグは全体の 25.9%（43,891 / 169,296）。
--     ラグフレームでは本編がフレーム境界をまたぐので、
--     ★1 フレームの `joypad.set` はその一瞬とすれ違って消える。
--
-- ⚠⚠ ただし長く押すのも駄目。同じルーチンに**連射**がある:
--
--     $CB4C  LDY #$08    ; ★0 なら 8 を装填
--     $CB51  STY $16,X   ; ⚠ 0 になったら「押しっぱなし」を消す
--     $CB53  LDY #$0B    ; ★以後 11 フレームごと
--
--   → **8 フレーム押し続けると 2 回選ばれる**（★「はなす」の罠と同じ）。
--
-- ★4 フレームなら、ラグを跨いでも読まれ、連射には届かない。
local HOLD = M.hold_frames or 4

--: ★★ ゲームが「新しく押された」と判断した結果が入る番地。
--
-- ⚠⚠ 依頼者の指摘（2026-08-27）:
--   「ボタンを反応したレジスタというかメモリもあるとおもうんだよね。
--    そこが反応するまで押すとか試験すればめくらうちにならない」
--
-- ★そのとおりで、逆アセンブルに**最初から映っていた**のに使っていなかった。
--
--     $CB5D  EOR $CA
--     $CB5F  STA $14,X    ; ★新しく押されたボタン
--     $CB5B  STA $16,X    ; ★押しっぱなしのボタン
--
-- ⚠ 固定フレーム数で押すのは**めくら撃ち**。★届いたら離す。
--: ⚠ ここまで押しても届かなければ諦める（★8 で連射に入る。ROM $CB4C）
local HOLD_MAX = M.hold_max or 7

--: ★★ ボタンは**共有**する（⚠ 2 つ持つと後勝ちで片方が消える）
local BUTTONS = (HOST and HOST.buttons)
  or Core.new_buttons({say = say, hold_max = HOLD_MAX})

local function press(key)
  BUTTONS.press(ME, key)
  cooldown = INTERVAL
end

--- ★次の窓が出るのを待つ押し方。
--
-- ⚠⚠ 実機で踏んだ: A を押しても窓は**すぐには出ない**（実測 25 フレーム）。
--   間隔が短いと「まだ出ていない」と見て**もう一度 A を押し**、
--   ★その 2 回目が開いたメニューの「はなす」を選んでしまった。
local function press_open(key)
  BUTTONS.press(ME, key)
  cooldown = OPEN_GAP
end

--- ★カーソルをその場所へ寄せる。届いたら true。
--
-- ⚠ カーソルが見えないフレームは**何もしない**（点滅）。
--
-- ⚠⚠ 2026-08-27: **諦める仕組みが無く、届かないと押し続けていた。**
--   依頼者「M を押すと、その方向にはなにもいないが連打される」。
--   ★フィールドでは、その連打が**歩き**になる（⚠ いちばん危ない壊れ方）。
--   → **押した回数に上限**を付け、届かなければ止める。
local function move_to(nt, want_x, want_y, why, want_tiles)
  -- ★★ 点滅しているカーソルだけを見る（⚠ 静止した ▶ は無視）
  local cx, cy = track.active()
  if cx == nil then
    -- ⚠ まだ点滅を捕まえていない。★何もしないで観続ける
    --   （⚠ 点滅しないものを押しに行かない。これが安全側）
    no_blink = no_blink + 1
    if no_blink % 120 == 1 then
      say("  ⚠ 点滅しているカーソルが見つからない / " .. track.report())
    end
    if no_blink > WAIT then
      stop("cursor_not_blinking:" .. (why or "?"))
      return false
    end
    cooldown = 1
    return false
  end
  no_blink = 0

  -- ★★ 着いたかどうかは**座標ではなく、いま選ばれているもの**で決める
  --   （依頼者「その点滅の右がコマンドの内容」）。
  --   ⚠ 座標だけで判断していたので、静止した ▶ に引きずられた。
  if want_tiles ~= nil and Cursor.starts_with(
      Cursor.label_at(nt, cx, cy), want_tiles) then
    return true
  end
  if want_tiles == nil and cx == want_x and cy == want_y then return true end

  moves = moves + 1
  if moves > MAX_MOVES then
    say(string.format("  ⚠ 届かない: 点滅(%d,%d) → (%d,%d) を %d 回 / %s",
      cx, cy, want_x, want_y, moves, track.report()))
    stop("cursor_stuck:" .. (why or "?"))
    return false
  end
  if cy < want_y then press("down")
  elseif cy > want_y then press("up")
  elseif cx < want_x then press("right")
  else press("left") end
  -- ⚠ 動かしたら点滅を覚え直す（★前の位置を引きずらない）
  track.forget()
  return false
end

--- ★窓が出るのを待つ。出たら true。⚠ 出なければ止める。
local function await(nt, name, reason)
  if window_at(nt, name) then waited = 0; return true end
  waited = waited + 1
  if waited > WAIT then stop(reason) end
  cooldown = 1
  return false
end

--- ★毎フレームの処理。
--
-- ⚠ `dev.lua` から動かすときは、あちらが 1 つの `registerafter` から呼ぶ。
local function frame()
  -- ★T でターボだけを入り切りする（⚠ まんたんとは別のスイッチ）
  --
  -- ⚠⚠ `dev.lua` から動かすときは、**あちらが T を見る**（★2 回反転を防ぐ）。
  if HOST == nil and edge(KEY_TURBO) then
    -- ⚠ スイッチは `core.lua` に 1 つだけ（★戦闘側と共有する）
    local on, ok = SPEED.toggle()
    say("MANTAN_V0 turbo " .. (on and "ON" or "OFF")
      .. (ok and "" or " ⚠ 変えられなかった"))
  end

  -- ★キーでも、画面のボタンでも同じことが起きる（RX3-0019）。
  --   ⚠ `wants` は**取り出したら消える**ので、2 回きかない。
  -- ⚠ どちらの経路で来たかを残す（★実機でしか出ない不具合を追うため）
  local by_key = edge(KEY_MANTAN)
  local by_ui = (not by_key) and HOST ~= nil and HOST.wants("mantan")
  if by_key or by_ui then
    enabled = not enabled
    -- ★入れるときだけ、画面の設定を読み直す（RX3-0160）。⚠ set_speed より前（ターボを決める）
    if enabled then reload_settings() end
    stopped = nil
    casts = 0
    waited = 0
    cooldown = 0        -- ⚠ 前に押した間隔が残っていると、入れ直した直後の 45 フレームが空回りする（RX3-0280）
    step = enabled and "check" or "idle"
    we_opened = false
    -- ⚠⚠ 入れ直したのに前の勘定が残っていると、★その場で止まる
    last_corners, unchanged = nil, 0
    -- ⚠⚠ M で切ったときも**必ず**通常速度へ戻す（★ターボのまま返さない）
    set_speed(enabled)
    say("MANTAN_V0 " .. (enabled and "ON" or "OFF")
      .. (TURBO and (enabled and " + turbo" or " + normal") or "")
      .. " / " .. (by_key and "キー" or "画面のボタン")
      .. " / カーソルは"
      .. (watching_writes and "★書き込みで見張る" or "⚠ 画面を眺める"))
  end

  local head = enabled and "まんたん: 実行中" or
    ("まんたん: " .. KEY_MANTAN .. " で開始" .. (stopped and (" (" .. stopped .. ")") or ""))
  show(4, 14, head .. "  唱えた回数=" .. casts)

  if not enabled then
    -- ★切っている間は手を離しておく（⚠ 戦闘側が握れるように）
    BUTTONS.release(ME)
    return
  end

  -- ★★ 道具は item_use_v0 に任せている（RX3-0174）。⚠ ボタンは向こうが握るので、ここでは握らない
  if step == "item" then
    local got = MX.poll(read_party())
    if got == nil then return end
    if not got.ok then stop("item:" .. tostring(got.reason)); return end
    casts = casts + 1
    say(string.format("  ★%s（HP %d → %d%s）（%d 回目）", MX.mi.describe(MX.plan), MX.before.hp,
        got.after.hp, (MX.plan.kind == "cure" and " / 毒が消えた") or (MX.plan.kind == "moon" and " / ★まひを治した")
        or "", casts))
    step, waited = "check", 0
    return
  end

  -- ★★ ボタンを握る。⚠ 戦闘側が握っていれば**何も押さない**。
  --
  --   ⚠⚠ `joypad.set` は後勝ちなので、両方が押すと片方が黙って消える。
  --   ★待たせるほうが、消えるより 100 倍ましです（理由が画面に出る）。
  -- ★★ 戦闘中は何も押さずに待つ（RX3-0164）。★M で入れるのも、実行中に戦闘へ入るのも同じ扱い。
  --   ⚠ 止めない（★戦闘が終われば続ける / M を押し直させない）。⚠ 入れたときの「戦闘中は断る」は dev の足場
  --   （戦闘中に M を入れて 2 つの押し合いを見る）とぶつかるのでやめた。
  --   ⚠⚠ 握ってから離すと、持ち主が毎フレーム入れ替わる（★dev の足場「同じ時期に 2 つが握っていた」）→ 握る前に見る。
  --   ★握ったまま戦闘に入っていたら 1 度だけ手放す（⚠ 戦闘側が握れるように）。
  --   ★戦闘側が握っていれば従来どおりの文。握っていない（AUTO OFF）ときも、戦闘の窓へ A を押し続けない
  if Battle.in_encounter() then
    if BUTTONS.owner == ME then BUTTONS.release(ME) end
    show(4, 24, "⚠ " .. tostring(BUTTONS.owner or "戦闘") .. " が操作中のため待機")
    return
  end
  if not BUTTONS.claim(ME) then
    show(4, 24, "⚠ " .. tostring(BUTTONS.owner) .. " が操作中のため待機")
    return
  end

  -- ★★ ゲームが受け取るまで押し続ける（⚠ めくら撃ちにしない）
  --
  --   ⚠ `cooldown` の中でも続ける。★でないと 1 フレームに戻ってしまう。
  --   ★中身は `core.lua`。**実際に押すのはあちらの 1 か所だけ**。
  BUTTONS.tick()

  if cooldown > 0 then
    cooldown = cooldown - 1
    -- ⚠⚠ **間隔の間も画面を観る。** ★45 フレーム待つので、
    --   ここで観ないと点滅をまるごと取りこぼす。
    local peek = read_nt()
    track.set_scroll(screen_reader.scroll_x, screen_reader.scroll_y,
                     (screen_reader.ctrl or 0) % 4)
    if peek ~= nil then track.update(peek) end
    return
  end

  local nt = read_nt()
  if nt == nil then stop("ppu_unavailable"); return end
  last_nt = nt
  -- ⚠ スクロールを渡す（★VRAM の番地を画面の升に直すのに要る）
  track.set_scroll(screen_reader.scroll_x, screen_reader.scroll_y,
                   (screen_reader.ctrl or 0) % 4)
  -- ⚠ 眺めるほうは何フレームか要る。★書き込みが使えるならそちらが先
  track.update(nt)
  local members = read_party()

  ------------------------------------------------------------------
  -- 誰を回復するか決める
  ------------------------------------------------------------------
  if step == "check" then
    healer = healer_of(members)
    local bags = MX.snapshot(members)
    local spells = MX.cat ~= nil and MX.cat.spells or nil
    local v1 = MX.mi.v1_ready(members, {spells = spells})
    -- ⚠ 回復役が読めない（★パーティが読めない / 道具を使わない設定）は、今までどおり止める
    --   ★v1 は覚えている人から選ぶので、設定の回復役が居なくても続ける（RX3-0161）
    if #members == 0 or (not v1 and healer == nil and M.heal_order == "spell_only") then
      stop("healer_missing"); return
    end
    if casts >= MAX_CASTS then done("上限に達した"); return end
    -- ★★ 呪文か道具か（2026-09-11 依頼者「道具を優先 / 呪文を優先 / 道具を使わない を設定で」）
    local plan, why = MX.mi.plan(members, bags, {
      order = M.heal_order, hp_below = HP_BELOW, min_mp = MIN_MP, healer_slot = M.healer or "p3",
      herb_id = M.herb_id, antidote_id = M.antidote_id, moon_id = M.moon_id, spells = v1 and spells or nil,
      casters = M.casters,
      -- ★呪文がかき消される場所では唱えない（RX3-0320 / ⚠ MP だけ損する）
      no_magic = Core.no_magic_here(CFG.no_magic)})
    if plan == nil then
      if why == "回復役がいない" then stop("healer_missing"); return end
      done(why); return
    end
    target = plan.target
    -- ★呪文の種類は mantan_items.lua の表（spell / kiary / kiariku）。⚠ それ以外は道具として item_use_v0 へ
    if not MX.mi.SPELL_KINDS[plan.kind] then
      say(string.format("  まんたん %s（%s）", MX.mi.describe(plan),
          (plan.kind == "cure" and "毒") or (plan.kind == "moon" and "まひ")
          or string.format("HP %d/%d", target.hp, target.hp_max)))
      BUTTONS.release(ME)                -- ★押すのは item_use_v0（⚠ 握ったままだと向こうが待ち続ける）
      local ok, err = MX.begin(plan, M)
      if not ok then stop(err); return end
      step = "item"
      return
    end
    -- ★★ v1: 唱える人・呪文は plan が決める（RX3-0161 / 0163 / 0162）。⚠ v0 は設定の回復役とホイミ
    if plan.holder ~= nil then healer = plan.holder end
    MX.spell, MX.spell_tiles = plan, M.spell_tiles
    if plan.spell_id ~= nil then
      MX.spell_tiles = (M.spell_tiles_by_id or {})[plan.spell_id]
      -- ⚠ 名前の並びが無い呪文は押さない（★別の呪文を唱えない）
      if MX.spell_tiles == nil then stop("spell_tiles_missing"); return end
    end
    hp_before = target.hp
    say(string.format("  まんたん %s(%d/%d%s) %s / %s / 術者 %s MP %d",
      target.slot, target.hp, target.hp_max,
      (target.poisoned and " 毒" or "") .. (target.paralyzed and " まひ" or ""),
      (plan.kind == "kiary" and "の毒を治す") or (plan.kind == "kiariku" and "のまひを治す") or "を回復する",
      MX.mi.describe(plan), healer.slot, healer.mp))
    step = "reset"; moves = 0; track.forget()
    waited = 0
    return
  end

  ------------------------------------------------------------------
  -- ⚠⚠ 始める前に、開いている窓を閉じる（2026-08-27）
  --
  --   ★前に失敗した状態が**そのまま残っている**ことがある。
  --   実測: 「誰の呪文か」窓が開いたまま、カーソルが (12,10) にいた。
  --   ⚠ その状態から始めると、カーソルの位置が想定と全く違う。
  --
  --   → **B で閉じてから**始める。⚠ 歩いているときの B は何も起こさない。
  ------------------------------------------------------------------
  if step == "finish" then finish_now(); return end

  -- ★★ 終わる前に、開いた窓を閉じて返す（⚠ 開けっぱなしにしない）
  if step == "cleanup" then
    local corners = window_corners(nt)
    if next(corners) == nil then
      say("  cleanup ★窓は全部閉じた")
      finish_now()
      return
    end
    waited = waited + 1
    if waited > 12 then
      -- ⚠ 閉じきれなくても、終わること自体は伝える（★黙って消えない）
      say("  cleanup ⚠ 閉じきれない / 残っている窓: " .. corners_text(corners))
      finish_now()
      return
    end
    say("  cleanup ⚠ 窓を閉じる（" .. waited .. " 回目）: " .. corners_text(corners))
    press_open("B")
    return
  end

  if step == "reset" then
    local corners = window_corners(nt)
    if next(corners) == nil then
      say("  reset ★窓は無い。ここから始める")
      step = "open"; moves = 0; track.forget(); waited = 0
      return
    end
    -- ⚠⚠ **B で閉じない窓がある**（2026-08-29 / 実機のセーブ 0 で確定）。
    --
    --   ★正体は**パーティのステータス表示**（22x8 / 中身は実測）:
    --
    --       H 23  H 17  H 11  H 10
    --       L  8  L  0  L 17  L  3
    --       ゆ： 3 せ： 4 そ： 4 ま： 4
    --
    --   ⚠ B を 10 回押しても閉じなかった（★窓の並びが 1 度も変わらなかった）。
    --   → ★**押しても変わらないなら、押し続けない**。理由ごと残す。
    local now = corners_text(corners)
    if now == last_corners then
      unchanged = unchanged + 1
    else
      unchanged = 0
      last_corners = now
    end
    if unchanged >= 3 then
      say("  reset ⚠⚠ B を押しても窓が変わらない: " .. now)
      stop("window_will_not_close")
      return
    end
    waited = waited + 1
    if waited > 10 then
      say("  reset ⚠ 閉じきれない / 残っている窓: " .. now)
      stop("could_not_reset")
      return
    end
    say("  reset ⚠ 窓を閉じる（" .. waited .. " 回目）: " .. now)
    press_open("B")
    return
  end

  ------------------------------------------------------------------
  -- コマンド窓を開く
  ------------------------------------------------------------------
  if step == "open" then
    if window_at(nt, "command") then
      -- ★ここまで来た＝自分でメニューを開いた（⚠ 片付ける責任がある）
      we_opened = true
      step = "to_spell"; waited = 0; return
    end
    waited = waited + 1
    if waited > WAIT then stop("menu_not_opened"); return end
    -- ⚠⚠ A を押したら、**窓が出るまで待つ**。★押し直さない。
    --   （実測 25 フレーム。⚠ 10 フレームで押し直して「はなす」を選んでいた）
    press_open("A")
    return
  end

  ------------------------------------------------------------------
  -- じゅもん を選ぶ（⚠ **2 列**。★右へ動かす）
  ------------------------------------------------------------------
  if step == "to_spell" then
    if not await(nt, "command", "command_window_gone") then return end
    local kx, ky = track.active()
    local x, y = find_near(nt, MENU.spell, kx, ky)
    if x == nil then stop("spell_command_missing"); return end
    if move_to(nt, x - 1, y, "じゅもん", MENU.spell) then
      say(string.format("  to_spell ★じゅもん を決定 カーソル(%d,%d)", x - 1, y))
      press_open("A")
      step = "caster"; moves = 0; track.forget()
      waited = 0
    end
    return
  end

  ------------------------------------------------------------------
  -- 誰の呪文か（⚠ 戦闘には無い段）
  ------------------------------------------------------------------
  if step == "caster" then
    if not await(nt, "caster", "caster_window_missing") then return end
    local kx, ky = track.active()
    local x, y = find_near(nt, healer.name, kx, ky)
    if x == nil then stop("healer_name_missing"); return end
    if move_to(nt, x - 1, y, "僧侶", healer.name) then
      say(string.format("  caster ★%s を決定 カーソル(%d,%d)",
        healer.slot, x - 1, y))
      press_open("A")
      step = "family"; moves = 0; track.forget()
      waited = 0
    end
    return
  end

  ------------------------------------------------------------------
  -- 呪文の系統（⚠ **賢者のときだけ**挟まる / RX3-0293）
  ------------------------------------------------------------------
  if step == "family" then
    -- ★2 つめの戻りは、行が有れば**系統の名前**・無ければ**止まる理由**
    local row, tag = MX.family_row(nt)
    if row == nil and tag ~= nil then stop(tag); return end
    if row == nil then
      -- ★系統の窓が出ていない ＝ 賢者ではない。⚠ 呪文の窓が出るまでは待つ
      if window_at(nt, "spell") or waited > WAIT then
        step = "spell"; moves = 0; waited = 0
      else
        waited = waited + 1
        cooldown = 1
      end
      return
    end
    if move_to(nt, row.x - 1, row.y, "系統", row.tiles) then
      say(string.format("  family ★系統 %s を決定 カーソル(%d,%d)", tag, row.x - 1, row.y))
      press_open("A")
      step = "spell"; moves = 0; track.forget()
      waited = 0
    end
    return
  end

  ------------------------------------------------------------------
  -- 呪文を選ぶ（⚠ 右上に出る）
  ------------------------------------------------------------------
  if step == "spell" then
    if not await(nt, "spell", "spell_window_missing") then return end
    local kx, ky = track.active()
    local tiles = MX.spell_tiles
    -- ★★ 2026-09-12（RX3-0163）: 「一覧の 1 番目でなければ止める」をやめた。★名前で探してその行へ動く
    --   （★戦闘側と同じ）。⚠ 名前は**丸ごと**一致だけ（ホイミ ⊂ ベホイミ / ベホマ ⊂ ベホマラー）
    local x, y = MX.find_word(nt, tiles, kx, ky)
    if x == nil then stop("spell_not_found"); return end
    -- ⚠⚠ 2026-08-27: **ここでカーソルを動かしていなかった。**
    --   実測（止まったときの画面）:
    --     ホイミ (22,4) / ⚠ カーソル (12,10) = **「誰の呪文か」窓の中**
    --   ★そのまま A を押しても「エルシトを選び直す」だけで何も進まない。
    --   → 他の段と同じく、**呪文の 1 つ左まで寄せてから**押す。
    -- ★着いたかは**座標**で見る（⚠ 頭が同じ長い名前の行で「着いた」にしない）→ 着いたら名前を丸ごと確かめる
    if not move_to(nt, x - 1, y, "呪文", nil) then return end
    local label = Cursor.label_at(nt, x - 1, y)
    if #label ~= #tiles or not Cursor.starts_with(label, tiles) then
      stop("spell_label_mismatch"); return
    end
    -- ★押す直前の窓を覚える（⚠ あとで「新しく出たか」を見る）
    seen_windows = window_corners(nt)
    say(string.format("  spell ★決定 カーソル(%d,%d) / 窓: %s",
      x - 1, y, corners_text(seen_windows)))
    press_open("A")
    step = "target"; moves = 0; track.forget()
    waited = 0
    return
  end

  ------------------------------------------------------------------
  -- 対象を選ぶ
  ------------------------------------------------------------------
  if step == "target" then
    -- ⚠⚠ 2026-08-27（実機・2 回目）: **窓を待ってはいけない**。
    --
    --   ★止まったときの画面が答えを持っていた:
    --
    --     y=10  76 00 72 5B 57 45 49 …   ← x=12 に 72（▶）、右は「エルシト」
    --           ↑ 窓(10,4) の中
    --
    --   ⚠ フィールドでは、対象の一覧は**新しい窓ではない**。
    --   ★「誰の呪文か」を選んだ窓 (10,4) が、そのまま対象の一覧になる。
    --
    --   ⚠ 「新しい窓が出る」は**戦闘の記録から持ってきた思い込み**だった。
    --     戦闘は相手が敵なので窓が増えるが、★フィールドは相手が仲間なので
    --     同じ窓を使い回す。
    --
    --   ★★ 見分け方: **点滅している ▶ が誰かの名前を指しているか**。
    --     呪文を決める前は ▶ は呪文窓 (20,2) の中にいる。
    --     決まると ▶ が人の窓へ**戻ってくる**。⚠ これが唯一確かな合図。
    local cx, cy = track.active()
    local on_person = false
    if cx ~= nil then
      local label = Cursor.label_at(nt, cx, cy)
      for _, m in ipairs(members) do
        if Cursor.starts_with(label, m.name) then on_person = true; break end
      end
    end
    if not on_person then
      waited = waited + 1
      if waited % 60 == 1 then
        say("  target ⚠ ▶ がまだ人を指していない / " .. track.report()
            .. " / 窓: " .. corners_text(window_corners(nt)))
      end
      if waited > WAIT then stop("target_not_offered"); return end
      cooldown = 1
      return
    end
    -- ★★ 点滅している ▶ にいちばん近いものを採る（⚠ 古い窓の同名を拾わない）
    local x, y = find_near(nt, target.name, cx, cy)
    if x == nil then stop("target_name_missing"); return end
    if move_to(nt, x - 1, y, "対象", target.name) then
      say(string.format("  target ★%s を決定 カーソル(%d,%d)",
        target.slot, x - 1, y))
      press_open("A")
      step = "cast"; moves = 0; track.forget()
      waited = 0
    end
    return
  end

  ------------------------------------------------------------------
  -- 唱え終わるのを待つ → メッセージを閉じる
  ------------------------------------------------------------------
  if step == "cast" then
    local now, cured = nil, false
    for _, m in ipairs(members) do
      if m.slot == target.slot then
        now = m.hp
        -- ★キアリー（RX3-0162）は毒が消えたら「効いた」
        if MX.spell ~= nil and MX.spell.kind == "kiary" then
          cured = not MX.mi.poisoned(memory.readbyte, PARTY, m.index)
        end
        -- ★キアリク（RX3-0252）は まひ が消えたら「効いた」
        if MX.spell ~= nil and MX.spell.kind == "kiariku" then
          cured = not MX.mi.paralyzed(memory.readbyte, PARTY, m.index)
        end
      end
    end
    if cured or (now ~= nil and now > hp_before) then
      casts = casts + 1
      if cured and MX.spell.kind == "kiariku" then
        say(string.format("  ★まひを治した %s（キアリク / %d 回目）", target.slot, casts))
      elseif cured then
        say(string.format("  ★毒を治した %s（キアリー / %d 回目）", target.slot, casts))
      else
        say(string.format("  ★回復した %s %d → %d（%d 回目）", target.slot, hp_before, now, casts))
      end
      step = "close"; moves = 0; track.forget()
      waited = 0
      cooldown = INTERVAL
      return
    end
    waited = waited + 1
    -- ⚠ 効かなかった（MP 切れ・対象違い）。★押し続けない
    if waited > WAIT then stop("no_effect"); return end
    cooldown = 1
    return
  end

  ------------------------------------------------------------------
  -- 閉じてコマンド窓へ戻る
  ------------------------------------------------------------------
  if step == "close" then
    if window_at(nt, "command") then step = "check"; waited = 0; return end
    waited = waited + 1
    if waited > WAIT then stop("did_not_return"); return end
    -- ⚠ ここも同じ。★送りすぎないよう、間をあける
    press_open("A")
    return
  end
end

local function on_exit()
  -- ⚠⚠ 閉じるときも通常速度へ戻す（★ターボのまま残さない）
  SPEED.reset()
  say("=== MANTAN_V0 end casts=" .. casts .. " ===")
  shut()
end

-- ★★ `dev.lua` から読まれたときは、**自分では登録しない**。
--   ⚠⚠ 両方が `registerafter` すると、FCEUX は後のものしか覚えない。
if HOST ~= nil then
  HOST.features = HOST.features or {}
  HOST.features[#HOST.features + 1] = {
    name = ME, frame = frame, on_exit = on_exit,
  }
  return {name = ME, frame = frame, on_exit = on_exit}
end

emu.registerafter(frame)
emu.registerexit(on_exit)
