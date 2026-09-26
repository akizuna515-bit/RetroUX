-- 開発中の機能を**1 本で**動かす（RX3-0018 / 2026-08-29）。
--
-- ★★ なぜこれを作ったか ★★
--
--   依頼者「別々に確認すると手間なので、開発中の機能として、
--           両方含めた lua で進めたい」（2026-08-29）
--
--   依頼者「今後、勇者のメモやマップ表示、仮 UI を表示する感じの
--           WI を追加して進めたい」（同）
--
-- ⚠⚠ 手間の話だけではありません。**技術的に 1 本でないと壊れます。**
--
--   `joypad.set` は**後勝ち**です。2 本を同時に起動すると、
--   ★同じフレームに書いたほうしか残らず、もう片方は**無かったことになります**。
--   ⚠ エラーは 1 つも出ません。実機では
--   「12,000 フレームで HP 変化 0 回」という形でしか出ませんでした。
--
--   → いままでは「2 本同時に起動しない」という**運用の約束**で避けていました。
--     ★ここで、約束が要らない形にします。
--
-- ## ★構え
--
--     core.lua    ボタン（持ち主は 1 人）と 速度（スイッチは 1 つ）
--     auto_v0     戦闘（★`A` で入り切り）
--     mantan_v0   まんたん（★`M` で開始）
--     この dev.lua  ⚠ `registerafter` は**ここ 1 つだけ**
--
-- ⚠⚠ `registerafter` を 2 つの機能が別々に呼ぶと、FCEUX は後のものしか
--   覚えません（★片方が黙って動かなくなります）。だから 1 つに束ねます。
--
-- ## ★これから足すもの（⚠ 中身は別 WI）
--
--   下の `draw()` が**表示の差し込み口**です。
--   勇者のメモ / マップ / 仮 UI は、ここに足していきます。
--
-- 使い方:
--   python scripts/run_probe.py dev

local function clean(p) return (p:gsub(string.char(92), "/"):gsub("/$", "")) end
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

local Core = dofile(root .. "/dq3/phase0/core.lua")
local Screen = dofile(root .. "/dq3/phase0/screen.lua")
local Cursor = dofile(root .. "/dq3/phase0/cursor.lua")

----------------------------------------------------------------------
-- ★記録（⚠ 共有部分のぼやきは、機能ごとではなくここへ集める）
----------------------------------------------------------------------

--: ⚠⚠ **閉じたあとに書かないこと。**
--
--   `registerexit` で閉じたあと、まだ動いているものが `say` を呼ぶと
--   ★"attempt to use a closed file" で落ちる。
--   ⚠ 実機では**モーダル窓が出て FCEUX が閉じなくなる**（2026-08-28 に
--   `emu.exit()` で同じ形を踏み、プロセスが 35 個残った）。
--   → ★閉じる**前に** nil にする。以後の `say` は静かに捨てる。
--: ★★ ⚠⚠ **記録が開けないときは、黙って進まない**（RX-0114 / 2026-08-30）★★
--
--   ⚠ `work/dq3-probe/` が無いと `io.open` は nil を返し、`say` は
--     以後すべて捨てられます。★そこまでは意図どおりです。
--
--   ⚠⚠ ところが `load_feature` の失敗も `say` で書いていたため、
--     **機能が 1 つ落ちたことが、どこにも出ませんでした**。
--
--   ★実際に踏んだ形（検査を並列にしたとき）:
--
--       ⚠⚠ 乗っている機能が 1 件（2 のはず）
--       ★理由はどこにも出ない（記録が開けていないため）
--
--   → ★開けなかったことだけは `print` で残します
--     （⚠ FCEUX の Lua 窓に出ます。実機で気づける唯一の場所）。
local LOG = Core.open_log(write_root .. "/work/dq3-probe/dev.log",
                          "開発用 1 本の記録")
local function say(line)
  if LOG == nil then return end
  local ok = pcall(function() LOG:write(line .. "\n"); LOG:flush() end)
  if not ok then LOG = nil end        -- ⚠ 一度でも駄目なら、以後は書かない
end

--- ★記録を閉じる（⚠ 閉じる**前に** nil にする）。
local function shut()
  if LOG == nil then return end
  local f = LOG
  LOG = nil
  pcall(function() f:close() end)
end
say("=== DEV start " .. os.date("%Y-%m-%d %H:%M:%S") .. " ===")

----------------------------------------------------------------------
-- ★★ 共有するもの ― 各機能を読む**前**に置く
----------------------------------------------------------------------

--: ★★ 機能はこの入れ物を見て、「自分では登録しない」と判断する。
--   ⚠ 名前を変えるときは `auto_v0.lua` / `mantan_v0.lua` の `HOST` も直すこと。
--: ★★ 画面の読み手も**1 つだけ**（RX3-0019 / 2026-08-29）。
--
-- ⚠⚠ `memory.registerwrite` は**番地ごとに 1 つ**しか覚えない。
--   ★`Screen` を 2 つ作ると、あとに `install()` したほうが
--   前のを**黙って潰す**。潰されたほうはスクロールを受け取れず、
--   ⚠ `scroll_x = 0` のまま**生のネームテーブルの座標**を返す。
--
--   実機で踏んだ（2026-08-29）: まんたんが窓を `(8,20)` と言い、
--   ★Python は `(6,20)` と言った。**スクロール 16px ＝ 2 マスぶんのずれ**。
--   ⚠ そのため「閉じる」を 10 回押しても、狙いの場所が違って閉じなかった。
--
--   → ★`registerafter` と同じ。**持ち主は 1 つ**にする。
local screen_reader = Screen.new()
pcall(screen_reader.install)

--: ★★ 点滅の見張りも**1 つだけ**（RX3-0020 / 2026-08-30）。
--
-- ⚠⚠ `memory.registerwrite` は**番地ごとに 1 つ**しか覚えない。
--   ★`Cursor.new()` を 2 つ作って両方が `install_writes()` すると、
--   ⚠ あとに読まれたほう（まんたん）が前を**黙って潰す**。
--   潰されたほう（自動戦闘）は書き込みを 1 つも受け取れず、
--   ★毎フレーム 960 マスを眺めるほうへ落ちる（⚠ ターボ中は重い）。
--
--   → ★`screen` と同じ。**持ち主は 1 つ**にする。
local cursor_track = Cursor.new()
local cursor_writes = cursor_track.install_writes()

DQ3_DEV = {
  buttons = Core.new_buttons({say = say, hold_max = CFG.hold_max or 7}),
  speed = Core.new_speed({say = say}),
  screen = screen_reader,
  cursor = cursor_track,
  say = say,
  features = {},
}
local HOST = DQ3_DEV

--: ★★ 戦闘の状態は**ここの 1 つだけ**（RX3-0166 / DQ3 自身の式 `$32 == $FD かつ $60B7 & $20`）。
--   ⚠ 機能の側で `$62` や画面のマス数から戦闘を決めないこと（★RX3-0165 で両方外れた）。
--   ★機能より先に作る（⚠ 機能は読み込みの時点で HOST.battle を受け取る）。
local BattleState = dofile(root .. "/dq3/phase0/battle_state.lua")
local battle = BattleState.new({say = say, cfg = CFG.battle_state})
HOST.battle = battle
--- ★段階（NONE / ENTERING / ACTIVE / RESULT / EXITING）。
function HOST.battle_phase() return battle.phase() end
--- ★遭遇してから出るまで（★歩き・街ナビ・補充はここで止まる）。
function HOST.in_encounter() return battle.in_encounter() end
--: ★セーブを読んだあとに呼ぶ（★高速化を残さない / RX3-0166）。⚠ 読んだ側（nav_v0）が呼ぶ
HOST.on_load = {}
function HOST.loaded(slot)
  for _, fn in ipairs(HOST.on_load) do
    local ok, err = pcall(fn, slot)
    if not ok then say("⚠ セーブを読んだあとの処理が落ちた: " .. tostring(err)) end
  end
end

----------------------------------------------------------------------
-- ★★ 画面からの頼みごと（RX3-0019）
----------------------------------------------------------------------

--: ⚠ まだ処理していない頼み（★1 回きり。取り出したら消える）
--   ★値は「その頼みの seq」（⚠ キーボードから来たものは 0）。
local pending = {}

--: ★★ 頼みが**どこまで**進んだか（RX3-0130 / 2026-09-08）。
--
--   ⚠⚠ 1 つの数字で「読んだ / やった / state に出した」を全部表すのはやめました。
--     ★`ai_reload` の直後に `load_state` を送って**前の作戦のまま戦った**のが元です。
--
--     received  ★`command_reader` が読んだ（⚠ まだ誰も処理していない）
--     applied   ★担当の機能が取り出した（`HOST.wants` が true を返した瞬間）
--     state     ⚠ この 2 つを載せた `state.json` を書いた時刻（★書き手が入れる）
HOST.ack = {received = 0, applied = 0, action = nil,
            received_frame = 0, applied_frame = 0}

--- ★その頼みが来ているか。⚠ **取り出したら消える**（2 回きかない）。
--
--   ★取り出した瞬間を「やった（applied）」とみなします。
--   ⚠ これ以上細かく（本当に効いたか）は機能ごとに違うので、ここでは持ちません。
function HOST.wants(name)
  local got = pending[name]
  if got ~= nil then
    pending[name] = nil
    if type(got) == "number" and got > HOST.ack.applied then
      HOST.ack.applied = got
      HOST.ack.applied_frame = emu.framecount()
      say(string.format("CMD seq=%d action=%s applied", got, name))
    end
    return true
  end
  return false
end

--- ⚠ 内部用。★受け取った頼みを積む（`seq` はファイル経由のときだけ）。
function HOST.push(name, seq)
  pending[name] = seq or 0
end

local CommandReader = dofile(root .. "/dq3/phase0/command_reader.lua")
local commands = CommandReader.new({
  path = write_root .. "/work/dq3-command.json",
  every = (CFG.ui or {}).command_every or 30,
  say = say,
})
HOST.commands = commands

--: ★★ 街の自動操作（聞き込み・街移動・補充）の Turbo（RX3-0170）。⚠ 戦闘の Turbo とは別の要求。
--   ★入れるのは画面の頼み（turbo="1"）、★切るのは town_end / 遭遇 / セーブ / 人の B / 画面が黙った。
local TownSpeed = dofile(root .. "/dq3/phase0/town_speed.lua")
local function task_active(name)
  local got = HOST[name]
  return type(got) == "table" and got.active == true
end
local town_speed = TownSpeed.new({
  speed = HOST.speed, battle = battle, say = say, cfg = CFG.town_turbo,
  busy = function()
    return task_active("nav_status") or task_active("restock_status") or task_active("item_status")
  end,
  phase = function()
    local nav = HOST.nav_status
    return (type(nav) == "table" and nav.active) and nav.phase or nil
  end,
  stop_tasks = function(seq)
    HOST.push("nav_stop", seq)
    HOST.push("restock_stop", seq)
  end,
  wants = function(name) return HOST.wants(name) end,
  -- ★人が握っているパッド（⚠ Lua の joypad.set を含まない。★無い版では B で止めない）
  pad = (joypad ~= nil and joypad.getimmediate ~= nil)
    and function() return joypad.getimmediate(1) end or nil,
})
HOST.town_speed = town_speed
HOST.on_load[#HOST.on_load + 1] = function() town_speed.stop("LOAD") end

----------------------------------------------------------------------
-- ★機能を読む（⚠ ここで `HOST.features` に自分を足してくる）
----------------------------------------------------------------------

--: ⚠ 落ちても他の機能まで道連れにしない。★どれが駄目だったかを残す
local function load_feature(name)
  local ok, err = pcall(function()
    dofile(root .. "/dq3/phase0/" .. name .. ".lua")
  end)
  if not ok then
    -- ⚠⚠ **記録にだけ書くと、記録が開けていないとき何も残りません。**
    --   ★両方に出します（`print` は FCEUX の Lua 窓）。
    local line = "⚠⚠ " .. name .. " を読めませんでした: " .. tostring(err)
    say(line)
    print(line)
  end
  return ok
end

load_feature("auto_v0")
load_feature("mantan_v0")
-- ★歩く（RX3-0031）。⚠ `HOST.where` を**あとで**受け取る作り
load_feature("walk_v0")
-- ★街ナビ（RX3-0058）。★経路は画面（Python）が作り、ここは再生と会話の押し
load_feature("nav_v0")
-- ★補充（RX3-0066 / RX3-0119）。★何を買うかは Python、ここは窓の操作だけ
load_feature("restock_v0")
-- ★道具を使う（RX3-0159）。★まずは鍵で扉を開ける。⚠ 誰の・どれをは Python が決める
load_feature("item_use_v0")
-- ★呪文の結果を見る（RX3-0271）。★ゲーム自身の耐性の判定を見るだけ（⚠ 押さない / registerafter を使わない）
load_feature("spell_watch")
-- ★敵の行動を**命令**で見る（RX3-0383 / Observation v2）。⚠ `auto_v0` の**あと**に読む
--   （★`HOST.ai_turn` / `HOST.ai_move_category` を使う）。⚠⚠ v1 とは**別の記録**に書く
load_feature("enemy_watch2")

say("★カーソルは" .. (cursor_writes and "書き込みで見張る"
                      or "⚠ 画面を眺める（書き込みを見張れない）"))
say(string.format("★動かす機能: %d 件", #HOST.features))
for _, f in ipairs(HOST.features) do say("   ・" .. f.name) end

----------------------------------------------------------------------
-- ★★ 画面へ渡す（RX3-0019）
----------------------------------------------------------------------

--: ★`work/state.json` を書く。⚠ 画面（`dq3/ui`）はこれだけを見る。
--   ⚠⚠ 毎フレームは書かない（★DQ2 で描き直しが 138 ms 掛かった実測がある）。
local StateWriter = dofile(root .. "/dq3/phase0/state_writer.lua")
local PARTY = CFG.party or {}
local SLOTS = {"p1", "p2", "p3", "p4"}

--: ★★ 職業の頭文字（⚠ 番地は**分かっていない**）。
--
--   ★ゲーム自身が「パーティの状態」の窓に出している（`ゆ： 4  せ： 5 …`）。
--   ⚠ その窓が出ているときだけ読めるので、**読めたら覚えておく**。
--   ★職業は temple 以外で変わらないので、覚えたままで困らない。
--
--   実測（セーブ 0）: `76 2F 74 00 05 00 18 74 ...`
--   → ★「：」（`0x74`）の**手前**が頭文字（`2F`=ゆ `18`=せ `19`=そ `29`=ま）。
local COLON_TILE = 0x74
local job_tiles = {}
--: ⚠ 落ちた理由は 1 度だけ出す（★毎フレーム出すと記録が埋まる）
local jobs_complained = false

--- ⚠ 状態の窓が出ていれば、職業の頭文字を拾って覚える。
--
-- ⚠⚠ **画面の升の数はここで自前に持つ。**
--   ★下のほうにある `local COLS, ROWS` は**この関数より後ろ**にあるので、
--   ⚠ ここから見ると（局所ではなく）**大域の nil** になっていた。
--   `ROWS - 1` で落ちるが、★呼び出しが `pcall` なので**何も言わずに**
--   職業だけが空のままだった（2026-08-29 / 実機で「職」が全部 `—`）。
local function remember_jobs(tiles)
  if tiles == nil then return end
  local cols = CFG.columns or 32
  local rows = CFG.rows or 30
  for y = 0, rows - 1 do
    local found = {}
    for x = 1, cols - 1 do
      if tiles[y * cols + x + 1] == COLON_TILE then
        found[#found + 1] = tiles[y * cols + x]     -- ★「：」の手前
      end
    end
    -- ★4 人ぶん並んでいる行だけを信じる（⚠ 会話文の「：」を拾わないため）
    if #found == (PARTY.slots or 4) then
      job_tiles = found
      return
    end
  end
end

--- ★パーティを読む（⚠ `auto_v0` と同じ番地。★設定から取る）。
--
-- ⚠⚠ 能力値の並びは**画面と RAM で違う**（★RAM は 力/速/賢/運/体）。
--   だから位置ではなく**名前**で読む（2026-08-29 に確定）。
local function read_party()
  local out = {}
  local n = PARTY.slots or 4
  local size = PARTY.entry_size or 2
  local nsize = PARTY.name_size or 4
  local ssize = PARTY.stat_size or 1
  local dstride = PARTY.derived_stride or 2
  local function w16(a)
    return memory.readbyte(a) + memory.readbyte(a + 1) * 256
  end
  local function stat(base, i)
    if base == nil then return nil end
    return memory.readbyte(base + i * ssize)
  end
  local function derived(base, i)
    if base == nil then return nil end
    return w16(base + i * dstride)
  end
  for i = 0, n - 1 do
    local o = i * size
    local m = {
      slot = SLOTS[i + 1],
      hp = w16(PARTY.hp_current + o), hp_max = w16(PARTY.hp_max + o),
      mp = w16(PARTY.mp_current + o), mp_max = w16(PARTY.mp_max + o),
      -- ★2026-08-29 に確定（依頼者の「つよさ」画面と 12 項目が一致）
      level = stat(PARTY.level, i),
      strength = stat(PARTY.strength, i),
      agility = stat(PARTY.agility, i),
      wisdom = stat(PARTY.wisdom, i),
      luck = stat(PARTY.luck, i),
      stamina = stat(PARTY.stamina, i),
      attack = derived(PARTY.attack, i),
      defence = derived(PARTY.defence, i),
      -- ★職業の頭文字（⚠ 覚えていなければ nil）
      job_tile = job_tiles[i + 1],
      name = {},
    }
    local function u24(base, stride)
      if base == nil then return nil end
      local a = base + i * stride
      return memory.readbyte(a) + memory.readbyte(a + 1) * 256
        + memory.readbyte(a + 2) * 65536
    end
    m.exp = u24(PARTY.exp, PARTY.exp_stride or 3)
    -- ★覚えている呪文の bit（RX3-0125）。★生のまま渡す（⚠ 解くのは Python / Lua の AI）
    if PARTY.spells ~= nil then
      m.spells = {}
      local sstride = PARTY.spell_stride or 8
      for k = 0, sstride - 1 do
        m.spells[k + 1] = memory.readbyte(PARTY.spells + i * sstride + k)
      end
    end
    -- ★状態（RX3-0125）。★u16 のまま渡す（⚠ bit の意味は Python 側）
    if PARTY.status ~= nil then
      m.status = w16(PARTY.status + i * (PARTY.status_size or 2))
    end
    -- ★★ 次のレベルに要る**累計**を、ゲーム自身が持っている
    --   （⚠ `$6A3F` はカートリッジ側の RAM。★こちらで表を持たなくてよい）。
    --   ⚠ ここで**残り**にして渡す（★画面に引き算をさせない）。
    local goal = u24(PARTY.next_exp, PARTY.next_exp_stride or 3)
    if goal ~= nil and m.exp ~= nil then
      local left = goal - m.exp
      -- ⚠ 上がりきっていると 0 未満になりうる（★負の数を出さない）
      m.to_next = left > 0 and left or 0
    end
    for k = 0, nsize - 1 do
      m.name[k + 1] = memory.readbyte(PARTY.name + i * nsize + k)
    end
    -- ★所持品（RX3-0076 / 2026-09-05）: 1 人 8 枠。★生のまま渡す
    --   （⚠ bit7 = 装備中 / $FF = 空き。★落とすのは Python 側 `progress.py`）。
    --   ⚠ 居ない枠は 0 で埋まっている（= ひのきのぼう に見える）ので、
    --   ★下の「最大 HP が 0 の枠は居ない」で丸ごと捨てる。
    if PARTY.items ~= nil then
      m.items = {}
      local islots = PARTY.item_slots or 8
      for k = 0, islots - 1 do
        m.items[k + 1] = memory.readbyte(PARTY.items + i * islots + k)
      end
    end
    -- ★職業と性別（RX3-0083 / 2026-09-06）: 1 人 1 バイト。
    --   ⚠ 生のまま渡す（★下位 3 bit = 職業 / bit3 = 性別。★分けるのは Python 側）。
    if PARTY.class_gender ~= nil then
      m.class_gender = memory.readbyte(PARTY.class_gender + i)
    end
    -- ⚠ 最大 HP が 0 の枠は「居ない」
    if m.hp_max > 0 then out[#out + 1] = m end
  end
  return out
end

--: ★★ 戦闘中かどうかは **DQ3 自身の式**で見る（RX3-0166 / 2026-09-11）。
--
--   ★`$32 == $FD かつ $60B7 & $20`（固定バンク $C8F8 がこの式で分岐する）。
--   ★中身は `battle_state.lua` の 1 か所（⚠ ここで番地を読まない）。
--
-- ⚠⚠ 以前は **画面のマス数 ＋ `$62 == 255`** でした（RX3-0157）。RX3-0165 で両方外れました:
--
--   ```text
--   画面のマス数   ⚠ 建物の中が 200〜400 マスで「戦闘」（誤検出 302 / 5,084 枚）
--   $62 == 255     ⚠ 最初の行動の実行で FF でなくなる → 2 手目以降ずっと「戦闘ではない」（318 枚）
--                  ⚠ にげた後のフィールドで FF のまま（632 枚）
--   ```
--
--   ★旧い判定は**診断にだけ**残します（⚠ 製品の判断には使わない / 依頼者 §31）。
--     食い違ったときだけ dev.log へ 1 行（★段階・曲・速度・AUTO も添える）。
local FIELD_TILES = (CFG.auto_battle or {}).field_tiles or 500
local COLS, ROWS = CFG.columns or 32, CFG.rows or 30
--: ⚠ 旧い判定の `$62`（★診断だけ）
local LEGACY_FLAG = 0x62
--: ★食い違いを 1 回ずつ記録する（⚠ 30 フレームごとに同じ行を出さない）
local battle_disagree = { key = nil }
--: ★戦闘が終わってから、地図の絵を採るまで待つフレーム（⚠ CHR が敵の絵のままかもしれない）
local MAP_ART_HOLD = (CFG.ui or {}).map_art_battle_hold or 120

--: ⚠⚠ **ネームテーブル 1 枚は「画面」ではない。**
--
--   ★フィールドはスクロールしているので、`$2000` から 960 バイト読むと
--   ⚠ **映っていない面**を数えてしまう。★`screen.lua`（スクロールを反映して 32x30 を組む）を使う。

--- ⚠ 旧い見立て（★診断だけ）。戻り値: `screen`（画面が戦闘に見える）, `flag`（`$62`）, `n`（非 0 マス）
--
--   ★ついでに職業の頭文字を拾う（⚠ 画面はもう読んでいるので、ただ）。
local function legacy_view()
  local ok, tiles = pcall(screen_reader.read)
  if not ok or tiles == nil then return nil end
  --   ⚠⚠ **黙って飲み込まない。** ★2026-08-29 に、ここで落ちていたのに
  --   何も出ず、「職業の番地が違うのでは」と番地を疑って時間を溶かした。
  local ok_jobs, why = pcall(remember_jobs, tiles)
  if not ok_jobs and not jobs_complained then
    jobs_complained = true
    say("  ⚠⚠ 職業を読めません: " .. tostring(why))
  end
  local n = 0
  for i = 1, COLS * ROWS do
    local v = tiles[i]
    if type(v) ~= "number" then v = 0 end
    if v ~= 0 then n = n + 1 end
  end
  return n < FIELD_TILES, memory.readbyte(LEGACY_FLAG), n
end

--- ★★ 戦闘中か（★DQ3 自身の式 / ACTIVE と RESULT）。
--
-- ⚠ 30 フレームに 1 回しか呼ばれない（★旧い見立ての 960 マスもそのとき数える）。
local function in_battle_now()
  local now = battle.is_in_battle()
  local screen, flag, n = legacy_view()
  if screen ~= nil then
    local legacy = screen and flag == 255
    local key = (legacy == now) and "agree" or string.format("new=%s legacy=%s", tostring(now),
      tostring(legacy))
    if key ~= battle_disagree.key then
      if key ~= "agree" then
        say(string.format("  ★戦闘の判定: %s（段階 %s / 画面 %s・非0マス %d / $62=%d / 曲=%02X"
          .. " / ターボ %s / AUTO %s）", key, battle.phase(), tostring(screen), n, flag,
          battle.track(), tostring(HOST.speed.manual or HOST.speed.wanted),
          tostring(HOST.auto_status ~= nil and HOST.auto_status.active)))
      end
      battle_disagree.key = key
    end
  end
  return now
end

--- ⚠ CHR が敵の絵かもしれないか（★地図の絵を採る前に見る / **安全側**）。
--
--   ★戦闘の段階（ENTERING〜EXITING）と、出てから `MAP_ART_HOLD` フレームの間は見送る。
--   ⚠ 見送りすぎのほうが安全です（★見送っても次の機会に採るだけ / ⚠ 採りすぎると敵の絵が混ざる）。
local function chr_may_be_enemy_now()
  return battle.recently(MAP_ART_HOLD)
end

--- ★★ いまどこに居るか（RX3-0023 / 2026-08-29）。
--
-- ⚠⚠ **世界地図とローカルで、座標の番地が違う。**
--
--     kind ($2F)  0 = 世界地図 / 1 = ローカル / 2 = アレフガルド
--     世界地図    $2A / $2B
--     ローカル    $30 / $31
--
--   ⚠ `map_no`（$8B）と寸法（$88/$89）は**ローカルのときだけ意味がある**。
--     ★世界地図に出ても**前のローカルの値が残ったまま**
--     （実測: セーブ 10 個中 8 個が世界地図なのに map_no=9 / 26x26 だった）。
--
-- ★あわせて、いま映っている升の**地形**も送る。
--   ⚠ ゲーム自身が復号した地図が `$7400` にある（`raw & 0x1F` が地形）。
--   ★これを送れば、画面側は ROM を読まずに「見たとおり」を描ける。
-- ⚠⚠ 地形そのものは**送りません**。★ROM から起こせるためです
--   （世界地図 256x256 / アレフガルド 158x138 / エリア 243 件）。
--   ⚠ `$7400` の地図バッファは、世界地図に出ると**前の地図のまま**でした
--     （2026-08-29 実測: 世界地図に居るのに map 9 の中身が残っていた）。
--   ★「見た所だけ」は、画面側が**見た升の記録**で覆い隠します。
local LOC = CFG.location or {}

--- ★★ いま出ている敵（RX3-0021 / 2026-08-29）。
--
--   $056D + i   敵の種類（⚠ $FF は空）
--   $0571 + i   その群の数
--
-- ⚠ 名前は送らない。★ROM で圧縮されているうえ、
--   **原作テキストを成果物へ焼かない**約束（`RX3-0011` 決定 ③）がある。
--   → ★画面に出ている窓の**生タイル**を送り、文字にするのは Python 側。
local ENE = CFG.battle_enemies or {}

local function read_enemies()
  if ENE.ids == nil then return nil end
  local out = {}
  local first = 0                                 -- ★個体の枠は群の順に詰まっている
  for i = 0, (ENE.groups or 4) - 1 do
    local id = memory.readbyte(ENE.ids + i)
    if id ~= (ENE.empty or 0xFF) then
      local n = memory.readbyte(ENE.counts + i)
      -- ⚠⚠ 個体ごとの HP は **state.json に載せない**（RX3-0126 / 2026-09-08）。
      --   ★No-Spoiler（敵の HP は AI の内部判断だけ / 依頼者 OK）に加えて、
      --   ⚠ `retroux/core/bridge/state_reader.py` は `enemies[].hp` を **int** として読む。
      --   ★配列を載せた途端に右画面が起動できなくなった（実機 run で踏んだ）。
      --   → 敵の HP と生存は `auto_v0.lua` が RAM から直に読む（`read_enemies`）。
      local g = {id = id, n = n}
      out[#out + 1] = g
      first = first + n
    end
  end
  return out
end

--- ★戦闘中の画面（32x30 の生タイル）。⚠ 戦闘中だけ送る。
--
-- ⚠⚠ **文字にはしない。** ★原作テキストを成果物へ焼かない約束
--   （`RX3-0011` 決定 ③）があるので、生のタイル番号のまま渡し、
--   文字にするのは Python 側（`dq3rom/window.py` + 文字表）。
--
-- ★画面ぜんぶを送る理由: 窓の探し方も文字表も **Python 側に既にある**。
--   ⚠ Lua でもう一度書くと、2 か所で食い違う（★何度も踏んだ形）。
--
-- ⚠ フィールドでは送らない（★state.json が 4 倍に膨らむ）。
local HEX = "0123456789ABCDEF"

--: ★タイル列を 16 進の文字列にする（⚠ 画面へ渡す形）
local function as_hex(tiles)
  local out = {}
  for i = 1, #tiles do
    out[i] = string.format("%02X", tiles[i] % 256)
  end
  return table.concat(out)
end

--: ★窓が出ているかの**安い見分け**（⚠ 切り出しはしない）
--
--   ⚠⚠ 枠のタイル番号は `dq3rom/window.py` が正本です。
--     ★生成した設定から受け取ります（ここに数字を書かない）。
local WIN = (CFG.window or {})
--- ★枠つきの窓が出ているか（★見つけたら左上の座標も返す）。
--
-- ⚠⚠ **タイル 1 個や 2 個で決めてはいけません**（RX3-0131 / 2026-09-08 実測）。
--   ★もとは「左上の角が 1 個でもあれば窓」でした。⚠ 世界地図の**地形**に
--     同じ番号（121 / 124）が出るため、窓が無いのに「ある」と答え、
--     walker が「窓が閉じない」と言って 1 歩も歩けませんでした。
--
-- ★`dq3rom/window.py` と**同じ形**で見ます:
--   左上の角 → 同じ行に右上の角 → その下に「左下の角と右下の角」が揃う行。
local function find_window(tiles)
  local tl, tr = WIN.top_left, WIN.top_right
  local bl, br = WIN.bottom_left, WIN.bottom_right
  if tl == nil or tr == nil or bl == nil or br == nil then return nil end
  local cols = CFG.columns or 32
  local rows = CFG.rows or 30
  local function at(x, y) return (tiles[y * cols + x + 1] or 0) % 256 end
  for y = 0, rows - 3 do
    for x = 0, cols - 3 do
      if at(x, y) == tl then
        local right = nil
        for k = x + 2, cols - 1 do
          if at(k, y) == tr then right = k; break end
          if at(k, y) == tl then break end        -- ⚠ 次の窓が始まった
        end
        if right ~= nil then
          for yy = y + 2, rows - 1 do
            if at(x, yy) == bl and at(right, yy) == br then
              return x, y, right, yy              -- ★四隅が揃った
            end
          end
        end
      end
    end
  end
  return nil
end

local function has_window(tiles)
  return find_window(tiles) ~= nil
end

--: ★★ 窓が出ているか（⚠ 他の機能が「入力を吸われる」のを避けるために使う / RX3-0115）。
--
--   ⚠⚠ 2026-09-08 依頼者:「メッセージが表示中で移動が吸われている」
--     ★窓（コマンド / ステータス / 会話）が開いていると、方向キーは**窓が食べます**。
--     ⚠ 街ナビはそれに気づかず歩き続け、`path_blocked` になっていました。
--
--   ⚠ 読めなければ `nil`（★`false` と混ぜない。「窓が無い」と言い切らない）。
function HOST.window_open()
  local ok, tiles = pcall(screen_reader.read)
  if not ok or tiles == nil then return nil end
  return has_window(tiles)
end

--- ★★ いま戦闘中か（★DQ3 自身の式 / RX3-0166）。
--
--   ⚠ `$62` でも画面のマス数でもない（RX3-0165）。★判定は `battle_state.lua` の 1 つだけ。
--   ⚠ 毎フレーム呼ばれてよい（★RAM を 2 バイト読むだけ / 旧い見立ての比較は state を書くときだけ）。
function HOST.in_battle()
  return battle.is_in_battle()
end

--- ⚠ CHR が敵の絵かもしれないか（★地図の絵を採る側が使う / 安全側 / RX3-0157 → RX3-0166）。
function HOST.chr_may_be_enemy()
  return chr_may_be_enemy_now()
end

--- ⚠ 誤検知を疑うときに「どこを窓と見たか」を言う（★推測で直さないため / RX3-0131）。
function HOST.window_where()
  local ok, tiles = pcall(screen_reader.read)
  if not ok or tiles == nil then return nil end
  local x, y, right, bottom = find_window(tiles)
  if x == nil then return nil end
  return string.format("(%d,%d)-(%d,%d)", x, y, right, bottom)
end

local function battle_screen(tiles)
  if tiles == nil then return nil end
  local out = {}
  for i = 1, (CFG.columns or 32) * (CFG.rows or 30) do
    local v = tiles[i]
    if type(v) ~= "number" then v = 0 end
    v = v % 256
    out[#out + 1] = HEX:sub(math.floor(v / 16) + 1, math.floor(v / 16) + 1)
    out[#out + 1] = HEX:sub(v % 16 + 1, v % 16 + 1)
  end
  return table.concat(out)
end

--- ★★ 世界地図の入口・出口の升（RX3-0275）。★`where()` が毎フレーム覚え、表に添える（entry_x/y・exit_x/y）
--   ⚠ Python の 0.5 秒おきの位置では、町へ入る 1〜2 歩手前の升を場所の升にしていた（依頼者「◯があるが、何もない」）
local WorldEdges = dofile(root .. "/dq3/phase0/world_edges.lua")
local world_edges = WorldEdges.new()

local function where()
  if LOC.kind == nil then return {} end
  local kind = memory.readbyte(LOC.kind)
  local out = {loc_kind = kind}
  -- ★向き（0=上 / 1=右 / 2=下 / 3=左）。⚠ 会話の相手を決めるのに要る（RX3-0133）
  if LOC.facing ~= nil then out.facing = memory.readbyte(LOC.facing) % 4 end
  -- ⚠⚠ 2026-09-07（RX3-0103）: `kind == 1` だけを見ていたので、
  --   ★洞窟（kind = 5）で **map 番号も座標も送っていません**でした。
  --   → MAP は真っ黒、場所の名前も付けられない。
  --   ★実測（DQ3_J.fc6）: kind=5 / map_no=45 / 58x40。⚠ ROM の area map 45 も
  --   **58x40** で一致 → ★番号も寸法も正しい。→ 世界以外は地図の中として扱う。
  if kind ~= 0 and kind ~= 2 then
    out.map_id = LOC.map_no and memory.readbyte(LOC.map_no) or nil
    out.map_x = memory.readbyte(LOC.local_x)
    out.map_y = memory.readbyte(LOC.local_y)
    out.map_w = memory.readbyte(LOC.map_width)
    out.map_h = memory.readbyte(LOC.map_height)
  else
    -- ★世界地図（0）とアレフガルド（2）。⚠ map_no は当てにしない
    out.map_id = nil
    out.map_x = memory.readbyte(LOC.world_x)
    out.map_y = memory.readbyte(LOC.world_y)
    out.map_w = nil
    out.map_h = nil
  end
  -- ★入口・出口の升（RX3-0275）。⚠ where() は毎フレーム呼ばれる（place_tick）→ ここで覚える
  world_edges.note(kind, out.map_x, out.map_y, emu.framecount())
  return world_edges.decorate(out)
end

----------------------------------------------------------------------
-- ★いまの場所を出す（RX3-0013 の実機確認 / 2026-08-31）
----------------------------------------------------------------------
--: ⚠⚠ 依頼者「座標はどこにも表示されない。★ログに出すか FCEUX の画面に
--   出すかが要る」（2026-08-31 の実機確認）。→ ★**両方**入れます。
--
--   ```text
--   画面   毎フレーム。⚠ ASCII だけ（`gui.text` に日本語は出ない）
--   ログ   ⚠ **地図が変わったときだけ**。★毎歩書くと dev.log が埋まる
--   ```
--
--: ★入口の行き先を確かめるのに要るのは「どの地図の、どの升か」だけ。
--   ⚠ 歩いた跡が要るなら `state.json` に毎回入っている。
--: ★FCEUX の画面に座標（map 43 (24,13)）を出すか。⚠ 2026-09-12 依頼者「FCEUXの座標表示はいらない」
--   → ★既定は出さない（RX3-0195）。★調べるときだけ設定の ui.position = true
local SHOW_POS = (CFG.ui or {}).position == true
local last_place = nil

--- ★「地図の中」か（⚠ 世界地図 0 とアレフガルド 2 以外はすべて地図の中 / RX3-0311）。
--   ⚠ ここは記録に出す字だけですが、★判断を 2 通りに書かない（`map_art.lua` と同じ形）。
local function is_local_kind(kind)
  return kind ~= nil and kind ~= 0 and kind ~= 2
end

local function place_text(w)
  if w.loc_kind == nil then return nil end
  if is_local_kind(w.loc_kind) then
    return string.format("map %d (%d,%d)",
      w.map_id or -1, w.map_x or -1, w.map_y or -1)
  end
  -- ⚠ 世界地図（0）とアレフガルド（2）は map_no が当てにならない
  return string.format("world%d (%d,%d)",
    w.loc_kind, w.map_x or -1, w.map_y or -1)
end

local function place_tick()
  local ok, w = pcall(where)
  if not ok or type(w) ~= "table" then return end
  local text = place_text(w)
  if text == nil then return end
  if SHOW_POS then gui.text(4, 222, text) end
  -- ★地図が変わった瞬間だけ残す（⚠ 座標は変わっても書かない）
  local place = is_local_kind(w.loc_kind) and ("map " .. tostring(w.map_id))
                                           or ("world" .. tostring(w.loc_kind))
  if place ~= last_place then
    if last_place ~= nil then
      say("  ⓘ " .. last_place .. " → " .. text)
    else
      say("  ⓘ いま " .. text)
    end
    last_place = place
  end
end

--: ★★ いまの場所を渡す口（⚠ **ここ 1 つだけ**）。
--   ⚠ 機能側が自分で $2F/$8B/$30/$31 を読むと、
--   ★「世界地図では map_no が残り値」の判断が 2 か所に散ります。
HOST.where = where

--: ★★ MAP をゲーム内のタイルで描くための材料（RX3-0043 / 2026-09-01）。
--
--   ⚠⚠ `state.json` とは**分けます**（指示書 §3.3）。
--     ★CHR だけで 8KB あり、⚠ 混ぜると `state.json` が毎回 8KB になります。
--
--   ```text
--   work/dq3-probe/map_art.json   ★小さい情報（⚠ 地図が変わったときだけ）
--   work/dq3-probe/map_art.bin    ⚠ CHR 8KB（★中身が変わったときだけ）
--   ```
local MapArt = dofile(root .. "/dq3/phase0/map_art.lua")
local map_art = MapArt.new({
  dir = write_root .. "/work/dq3-probe",
  every = (CFG.ui or {}).map_art_every or 30,
  say = say,
  json = Core.json,
  -- ⚠ 戦闘中は CHR が敵の絵に入れ替わっています（★地図の絵ではない / RX3-0046）
  --   ⚠⚠ ここは `in_battle_now` ではなく**安全側**（★段階が NONE でない間 ＋ 出てから少し / RX3-0166）。
  in_battle = chr_may_be_enemy_now,
})
--: ★足場から「安全側が渡っているか」を見られるように（⚠ 中身は触らせない）
HOST.map_art = map_art

local state = StateWriter.new({
  path = write_root .. "/work/state.json",
  every = (CFG.ui or {}).state_every or 30,
  -- ★戦闘中だけ細かく書く（RX3-0065 / 2026-09-03）。
  --   ⚠ 敵の一覧が全部見える時間が短く、0.5 秒おきでは取りこぼしていた。
  --   ⚠ `busy` は**毎フレーム**呼ばれる → ★RAM だけの判定（⚠ 画面を数えない）
  busy = battle.is_in_battle,
  busy_every = (CFG.ui or {}).battle_state_every or 10,
  say = say,
  where = where,
  party = read_party,
  extra = function()
    local gold = nil
    local G = CFG.gold
    if G ~= nil and G.address ~= nil then
      -- ⚠⚠ 2026-09-22（RX3-0369）: ここは **2 バイトまで**でした。
      --   ★所持金は 3 バイトです（`_b0_s1B_player_gold_read` が `+2` まで読む）。
      --   ⚠ 65535 を超えると下 2 バイトだけを見て**巻き戻ります**
      --     （★依頼者の save6: 画面 66970 → 誤表示 1434）。
      --   → ★`size` のぶんだけ回します（⚠ 決め打ちにしない）。
      gold = 0
      for i = 0, (G.size or 3) - 1 do
        gold = gold + memory.readbyte(G.address + i) * (256 ^ i)
      end
    end
    local fighting = in_battle_now()
    local out = {
      gold = gold,
      in_battle = fighting,
      -- ★段階（RX3-0166）: NONE / ENTERING / ACTIVE / RESULT / EXITING
      battle_phase = battle.phase(),
      -- ★戦闘の高速化（RX3-0166）: mode / reason / fast（⚠ AUTO が居なければ nil）
      battle_speed = HOST.battle_speed_status,
      -- ⚠ 戦闘の Turbo（★右画面の「タ」）。⚠ 街の自動操作の Turbo は入れない（RX3-0170 / 依頼者 §3）
      turbo_enabled = HOST.speed.manual or HOST.speed.wanted,
      -- ★FCEUX にいま送っている語（turbo / normal）と、normal を送った回数（RX3-0170）。
      --   ⚠ normal で FCEUX は 100% に戻るので、画面はこれが増えたら人の倍率を送り直す
      speed_mode = HOST.speed.mode,
      speed_normal_count = HOST.speed.normal_count,
      -- ★街の自動操作の Turbo（RX3-0170）: turbo / requested / source / slow / last_off / cancels
      town_speed = town_speed.status(),
      -- ★いま Auto か（RX3-0169 / 右画面の A ボタン）。⚠ 結果の文を送っている間は false
      auto_enabled = HOST.auto_enabled ~= nil and HOST.auto_enabled() or false,
      blocked = HOST.buttons.blocked,
      missed = HOST.buttons.missed,
      -- ★街ナビ（RX3-0058）: 進み具合 / 誰と話したか / NPC の表（$0110-$0177 = 104 バイト）/ 時間帯
      nav = HOST.nav_status,
      walk = HOST.walk_status,
      -- ★自動戦闘の判断（RX3-0147）。⚠ 理由の全文はログのまま（★ここは結果だけ）
      auto = HOST.auto_status,
      -- ★補充（RX3-0066 / RX3-0119）: 局面 / 買った数 / 使った額
      restock = HOST.restock_status,
      -- ★道具を使う進み具合（RX3-0159）
      item = HOST.item_status,
      last_talk = HOST.last_talk,
      time_byte = memory.readbyte(0x06DF),
      -- ★窓の色（RX3-0225 / $06E0）: $27 オレンジ（死者あり）/ $2A 緑（HP 1/4 未満）/ $21 夜 / $30 白。
      --   ★Auto を人へ返した理由を右画面・記録で説明するため（⚠ 生の値だけ / 番地は生成物 CFG.window_color）
      window_color = (CFG.window_color ~= nil and CFG.window_color.address ~= nil)
        and memory.readbyte(CFG.window_color.address) or nil,
      -- ★物語の旗（RX3-0210 / RX3-0211）: $60B7（bit2 = ノアニールが目覚めた / ROM 13:B20E・6:B666）
      --   ⚠ 意味づけは Python（dq3/knowledge/story.py / data/dq3/story-flags.csv）。★生の値だけ渡す
      --   ⚠⚠ 2026-09-19（RX3-0297）: **番地をここに直書きするのをやめました**。
      --     ★表（`data/dq3/story-flags.csv`）に足しても Lua が読まず、
      --     ⚠ 「旗が立っているのに気づかない」が起きていました（★6 つのオーブ）。
      --   ★いまは生成物の `CFG.story_flags`（番地の並び）を回して `story_<16 進>` を作ります。
      story_60b7 = memory.readbyte(0x60B7),
      -- ★船を手に入れた印（$60B8 bit7 / RX3-0249）。⚠ 意味は data/dq3/story-flags.csv（★ここでは決めない）
      story_60b8 = memory.readbyte(0x60B8),
      -- ★ゲーム自身が持つ「戻れる町」（RX3-0113 / `$0750`）。
      --   ⚠⚠ **どの町かはここでは決めません。** ★生のビットをそのまま渡し、
      --     ⚠ 意味づけ（表と突き合わせる）は Python 側の仕事です。
      --   ★人ごとに 3 バイト x 4 人 = 12 バイトを 16 進で。
      rura = (function()
        local R = CFG.rura
        if R == nil or R.address == nil then return nil end
        local n = (R.players or 4) * (R.stride or 3)
        local ok, raw = pcall(memory.readbyterange, R.address, n)
        if not ok or type(raw) ~= "string" or #raw ~= n then return nil end
        return (raw:gsub(".", function(c) return string.format("%02x", c:byte()) end))
      end)(),
      -- ★★ 宝箱を開けた印（RX3-0207 / ダンジョン探索MAP v1 Phase C）。WRAM $608E から **26 バイト**。
      --   ★0〜192 が宝箱（25 バイト）/ ⚠ 200〜207 は「しらべる」で取った隠し道具（★26 バイト目 / RX3-0281）。
      --   ⚠⚠ **どの宝箱かはここでは決めません**（★生のビット / 意味づけは Python の chest_book / dq3rom/chest_flags.py）
      chest_bits = (function()
        local ok, raw = pcall(memory.readbyterange, 0x608E, 26)
        if not ok or type(raw) ~= "string" or #raw ~= 26 then return nil end
        return (raw:gsub(".", function(c) return string.format("%02x", c:byte()) end))
      end)(),
    }
    -- ★★ 物語の旗（RX3-0297）: 表にある番地を**全部**送る。
    --   ⚠⚠ 上の `story_60b7` / `story_60b8` は直書きで、★表に足した番地は送られていませんでした。
    --   ★ここで `CFG.story_flags` を回すので、⚠ 表に足すだけで効きます（Lua を直さなくてよい）。
    for _, address in ipairs(CFG.story_flags or {}) do
      out[string.format("story_%04x", address)] = memory.readbyte(address)
    end
    if not fighting then
      local ok_t, tbl = pcall(memory.readbyterange, 0x0110, 0x68)
      if ok_t and type(tbl) == "string" then
        out.npc_tbl = (tbl:gsub(".", function(c) return string.format("%02x", c:byte()) end))
      end
      -- ★★ 見た目の枠 → 見た目 id（RX3-0304 / WRAM $6ABE から 16 個）。
      --   ⚠⚠ 実機の表の 3 バイト目は**見た目そのものではなく「枠の番号」**です。
      --     ★これを解く表を送っていなかったので、⚠ 相手が分かっても**札を出せません**でした
      --     （★依頼者「王様とイベントセリフを話すが、？になっている」）。
      --   ★生のまま渡す（⚠ 意味づけは Python 側 / `data/dq3/npc-appearance-labels.json`）。
      local ok_a, app = pcall(memory.readbyterange, 0x6ABE, 0x10)
      if ok_a and type(app) == "string" then
        out.npc_appearance = (app:gsub(".", function(c) return string.format("%02x", c:byte()) end))
      end
    end
    -- ★★ 画面を送るのは「戦っているとき」と「窓が出ているとき」だけ
    --   （RX3-0021 → RX3-0016 で条件を 1 つ足した）。
    --
    --   ⚠ **いつも送ると `state.json` が 4 倍に膨らみます。**
    --     ★歩いているだけの間は送りません。
    --
    --   ⚠⚠ ここでやるのは「窓があるか」の**安い見分けだけ**です。
    --     ★どこからどこまでが窓かは Python（`dq3rom.window`）が決めます。
    --     ⚠ 両方で切り出すと、片方だけ直したときに食い違います
    --     （2026-08-29 に実際に踏んだ）。
    -- ★★ 頼みがどこまで進んだか（RX3-0130）。⚠ 画面側は「次の頼み」の前にこれを待つ。
    --   ★置き場は 1 つなので、読まれる前に次を書くと**前のが消える**（実機 run で踏んだ）。
    out.command_seq = HOST.ack.received      -- ⚠ 旧名（★互換）
    out.command = {received = HOST.ack.received, applied = HOST.ack.applied,
                   action = HOST.ack.action, received_frame = HOST.ack.received_frame,
                   applied_frame = HOST.ack.applied_frame}
    if fighting then
      out.enemies = read_enemies()
      local ok, tiles = pcall(screen_reader.read)
      if ok then out.screen = battle_screen(tiles) end
    else
      local ok, tiles = pcall(screen_reader.read)
      if ok and has_window(tiles) then out.screen = as_hex(tiles) end
    end
    return out
  end,
})
HOST.state = state

----------------------------------------------------------------------
-- ★★ 表示の差し込み口（⚠ 中身はこれから / 別 WI）
----------------------------------------------------------------------

--: ★足していく表示。⚠ それぞれ `draw(ctx)` を持つ表だけを入れること。
local panels = {}

--- ★表示を足す（⚠ 勇者のメモ / マップ / 仮 UI はここへ）。
local function add_panel(panel)
  if type(panel) ~= "table" or type(panel.draw) ~= "function" then
    say("⚠ draw を持たないものは足せません")
    return false
  end
  panels[#panels + 1] = panel
  return true
end
HOST.add_panel = add_panel

--: ★★ FCEUX の文字はここでしか出せない。⚠ **日本語は出ません**
--   （`gui.text` は 8 バイト固定のビットマップを 1:1 で描くだけ。倍率も無い）。
--   → メモや地名を見せるなら、⚠ 画面内ではなく**別窓**が要ります。
--: ⚠ ゲーム画面への重ね書き（★依頼者 2026-08-29「一旦いらない」）。
--   ★右の画面で同じことが見えるようになったため。
--   ⚠ 設定 `ui.overlay: true` で戻せる（★戻し方を残しておく）。
local OVERLAY = (CFG.ui or {}).overlay == true

local function draw()
  if not OVERLAY then return end
  -- ⚠⚠ ボタンを誰かが「持ち主でないのに押そうとした」なら、それは設計の壊れ。
  --   ★黙って進めず、画面に出す。
  local b = HOST.buttons
  if b.blocked > 0 then
    gui.text(4, 4, "!! blocked=" .. b.blocked)
  end
  for _, p in ipairs(panels) do
    pcall(function() p.draw() end)
  end
end

----------------------------------------------------------------------
-- ★★ 毎フレーム ― `registerafter` は**ここ 1 つだけ**
----------------------------------------------------------------------

--: ★★ ターボの `T` は**ここだけ**が見る（RX3-0018 / 2026-08-29）。
--
-- ⚠⚠ 最初は各機能に見させていた。★1 回押すと 2 つが反転させて**元に戻った**。
--   （足場の「1 回のタップで 2 回反転している」が捕まえた）
--   → 共有するスイッチは、**見る場所も 1 つ**にする。
local KEY_TURBO = (CFG.keys or {}).toggle_turbo or "T"
local KEY_WALK = (CFG.keys or {}).toggle_walk or "K"
local edge = Core.new_edge()
local edge_walk = Core.new_edge()

emu.registerafter(function()
  -- ★画面からの頼みを取り込む（⚠ 中で 30 フレームに 1 回しか見ない）
  local req = commands.tick()
  if req ~= nil then
    HOST.last_request = req            -- ★引数つきの頼み（街ナビ / RX3-0058）
    HOST.last_seq = req.seq            -- ⚠ 旧名（★互換のため残す。中身は received と同じ）
    HOST.ack.received = req.seq
    HOST.ack.action = req.action
    HOST.ack.received_frame = emu.framecount()
    say(string.format("CMD seq=%d action=%s received", req.seq, req.action))
    HOST.push(req.action, req.seq)
    -- ★街の Turbo は頼みを受け取った瞬間に決める（RX3-0170 / ⚠ 機能が取り出すのを待たない）
    local ok_ts, err_ts = pcall(town_speed.on_command, req)
    if not ok_ts then say("⚠ 街の Turbo を決められませんでした: " .. tostring(err_ts)) end
  end

  -- ★歩きの入り切り（⚠ 見る場所は 1 つ。`HOST.push` 経由で渡す）
  --   ⚠⚠ 既定は `K`。★最初 `W` にしていたら **FCEUX が使っていました**
  --     （依頼者 2026-08-31「W だとスナップショットセーブが走る」）。
  if edge_walk(KEY_WALK) then HOST.push("walk") end

  -- ★★ T / TURBO ボタンは戦闘の速さだけ（RX3-0237）。★AUTO OFF でも効く（「手動操作・高速」）/ ⚠ 戦闘の本体でだけ
  --   （★フィールド・町の Turbo は触らない / 速度のスイッチを直接は触らない）
  local by_t = edge(KEY_TURBO)
  if by_t or HOST.wants("turbo") then
    if HOST.turbo_toggle ~= nil then
      HOST.turbo_toggle(by_t and "T_KEY" or "UI")
    else
      say("DEV turbo ⚠ 自動戦闘が読み込まれていないので何もしない")
    end
  end

  -- ★戦闘の段階の変わり目を覚える（⚠ 機能より先 / RX3-0166）
  local ok_b, err_b = pcall(battle.tick)
  if not ok_b then say("⚠ 戦闘の段階を読めませんでした: " .. tostring(err_b)) end

  -- ★押しているボタンを進める。⚠ 実際に `joypad.set` を呼ぶのはここ 1 回。
  --   （★機能側も呼ぶが、フレーム番号で見張っているので 2 回にはならない）
  HOST.buttons.tick()

  for _, f in ipairs(HOST.features) do
    -- ⚠ 1 つが落ちても、もう 1 つは動かす（★どちらが落ちたか残す）
    local ok, err = pcall(f.frame)
    if not ok then
      say("⚠⚠ " .. f.name .. " が落ちました: " .. tostring(err))
    end
  end

  -- ★街の Turbo（RX3-0170）。⚠ 機能の**後**（★nav の局面が今フレームのもの / 遭遇はこのフレームで戻す）
  local ok_ts, err_ts = pcall(town_speed.tick)
  if not ok_ts then say("⚠ 街の Turbo を見られませんでした: " .. tostring(err_ts)) end

  draw()
  -- ⚠ `draw()` の外に置く（★`ui.overlay` を切っても場所は出したい）
  local ok_pos, err_pos = pcall(place_tick)
  if not ok_pos then say("⚠ 場所を出せませんでした: " .. tostring(err_pos)) end

  -- ★画面へ渡す（⚠ 中で 30 フレームに 1 回だけ書く）
  local ok, err = pcall(state.tick)
  if not ok then say("⚠⚠ state を書けませんでした: " .. tostring(err)) end

  -- ★MAP のタイルの材料（⚠ 中で「地図が変わったとき」しか書かない）
  local ok_art, err_art = pcall(map_art.tick)
  if not ok_art then
    say("⚠ MAP の材料を書けませんでした: " .. tostring(err_art))
  end
end)

emu.registerexit(function()
  for _, f in ipairs(HOST.features) do
    if type(f.on_exit) == "function" then pcall(f.on_exit) end
  end
  -- ⚠⚠ ターボのまま返さない（★人がまともに操作できなくなる）
  HOST.speed.reset()
  say(string.format("=== DEV end blocked=%d missed=%d state=%d/%d ===",
    HOST.buttons.blocked, HOST.buttons.missed, state.wrote, state.failed))
  say("★MAP の材料: " .. map_art.report())
  shut()
end)
