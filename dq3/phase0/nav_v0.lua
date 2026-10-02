-- ★街ナビ（RX3-0058 / 2026-09-02）。⚠ `dev.lua` が読み込む製品側の機能。
--
-- ## ★やること
--
--   画面（Python）が BFS で作った経路を受け取り、実機で再生する。
--   着いたら（頼まれていれば）NPC の方を向き、A → はなす → 会話、B で閉じる。
--
--   ```text
--   navigate   keys="up,up,right" cells="8:17,8:16,9:16" face="up" talk="1" npc_slot="10" close="1" grid="<path>"
--   nav_stop   ★いまの 1 操作を安全に止める（ボタンを離す / 次へ進まない）
--   ```
--
-- ## ★★ ここは「配線」に近い ★★
--
--   歩き方の判断（通行可否 / 経路）は Python の service が持つ。⚠ Lua が持つのは
--   「塞がれたら待って押し直す / 通行可否の表で BFS をやり直す / 動く NPC の隣へ近づき直す」だけ。
--   ★状態は `HOST.nav_status` に置き、`state.json` の `nav` として画面へ渡す。
--
-- ## ⚠⚠ 「A を押した」を会話の成功にしない
--
--   ★会話が始まったかは Python が `state.json` の窓（`conversation_on_screen`）で見る。
--   ★誰と話したかは `$828B`（`$F507` の直後）で写した slot / talk_id（`HOST.last_talk`）。
--
-- ## ⚠ 製品ログ（指示書 §27）
--
--   ★1 歩ごとの記録は書かない。書くのは 開始 / 終了 / 局面の変わり目 だけ。

-- ⚠⚠ 開発機のパスへ落ちない（RX3-0466 / 2026-09-29）
local root = os.getenv("RETROUX_ROOT")
if root == nil or root == "" then
  error("RETROUX_ROOT が立っていません（★起動は DQ3.cmd から / RX3-0466）")
end
local write_root = os.getenv("RETROUX_WRITE_ROOT") or root

local Core = dofile(root .. "/dq3/phase0/core.lua")

local ok_cfg, CFG = pcall(require, "dq3_phase0")
if not ok_cfg or type(CFG) ~= "table" then CFG = {} end

local ME = "nav_v0"
local HOST = DQ3_DEV

local logfile = Core.open_log(write_root .. "/work/dq3-probe/nav_v0.log", "街ナビの記録")
local function say(line)
  if logfile ~= nil then logfile:write(line .. string.char(10)); logfile:flush() end
end

local BUTTONS = (HOST and HOST.buttons) or Core.new_buttons({say = function() end})
--: ★★ 戦闘の状態は dev.lua の 1 つを借りる（RX3-0166 / DQ3 自身の式）。
--   ⚠ `$62` では見ない（★にげた後は FF のまま / 勝った後は 1〜7 が残る / RX3-0165）。
--   ⚠ 足場で単独に読むときだけ、自分で作る（★番地は battle_state.lua の 1 か所）。
local Battle = (HOST ~= nil and HOST.battle)
  or dofile(root .. "/dq3/phase0/battle_state.lua").new({cfg = CFG.battle_state})
local A_FACING = 0x0644
local A_BANK = 0x06D5
local KEY_INDEX = {up = 0, right = 1, down = 2, left = 3}
local DIRS = {{"up", 0, -1}, {"down", 0, 1}, {"left", -1, 0}, {"right", 1, 0}}

--: ★決めごと（RX3-0052 / RX3-0056 で実機に合わせた値）
local STEP_FRAMES, BLOCK_WAIT, BLOCK_RETRIES, MAX_REPLANS = 40, 30, 3, 3
--: ★★ 1 歩進んだと認めるまでに、同じ升が何フレーム続くか（RX3-0177 / 2026-09-16 実測）。
--
--   ⚠⚠ 人にぶつかると、位置（`$30/$31`）は **1 フレームだけ行き先の升に見えて**、次のフレームで戻ります
--     （★隔離先の save1: 上 → f007 (3,4) → f008 (3,5) / 右 → f006 (4,5) → f007 (3,5)）。
--   ⚠ これを「1 歩進んだ」と数えると、次の歩で升が合わず `path_deviation` で**聞き込みごと打ち切って**いました
--     （★依頼者の実機 2026-09-12 / アリアハンの城で 2 回）。
local MOVE_STABLE = 2
local FACE_HOLD, FACE_TRIES = 30, 3
local TALK_MENU_GAP, TALK_WAIT = 60, 300
local CLOSE_GAP, CLOSE_PRESSES = 40, 6
--: ★★ 窓が**まだ見えている**あいだは、ここまで B を押し続ける（RX3-0157 / 2026-09-11）。
--
--   ⚠⚠ 冒険者の登録所の受付（talk_id 3 / special_3）は文が長く、★6 回の B を
--     **ページ送りで使い切ったあと**に「はい / いいえ」が出ていました。
--     → ⚠ 窓が残ったまま「閉じた」ことにして、画面が「窓が閉じません」で聞き込みを止めた
--     （★依頼者「冒険者の登録所で聞き込み中断されてしまう」）。
--   ★B は「いいえ（キャンセル）」です（`$8756 CMP #$FF` / RX3-0121）。⚠ **押すボタンは増やしません**。
local CLOSE_MAX = 16
--: ★★ 「はい／いいえ」の窓が繰り返し出たら止める（RX3-0273）。
--
--   ⚠ 「いいえ」（B）で同じことを聞き直す相手（アッサラームの押しの強い商人 / RX3-0217）は B では抜けられない。
--   → ★話しかけてから、はい／いいえ の窓が CHOICE_MAX 回**新しく出たら** B をやめ、窓を人に返す（choice_repeated）。
--
--   ⚠⚠ 2026-09-18（依頼者「save0 再聞き込みで途中で窓が開きっぱなし」）: 最初は **bank14 `$8743` の実行**を
--     数えていたが、★`$8743` は「はい／いいえ」専用ではなく**窓を開く共通処理**（店・教会・起動メニュー・会話）で、
--     ⚠ ふつうの会話でも鳴る → 話しかけた直後に 3 回に達し、**B を 1 回も押さずに**止めていた
--     （実測: 07:48 以降の聞き込み 4 件すべて `choice_repeated` / `B 0 回`）。
--   → ★画面で数える（`yes_no_window` = はい の 1〜2 行下に いいえ）。⚠ 「見えている」ではなく**新しく出た**で数える
--     （[[project_retroux_two_writers_edge_trigger]] / 点滅するものは 1 枚で決めない と同じ形）。
--   ⚠ はい／いいえ の字（`params.yes` / `params.no`）が来ていなければ、この歯止めは**働かない**（★今までどおり B で閉じる）。
local CHOICE_MAX = 3
--: ★★ **すぐ旅立つかを尋ねる窓**に はい で 1 回だけ答える（RX3-0194 / 2026-09-12）。
--
--   ⚠⚠ 依頼者「イシス（save6）でやはり再発する『またすぐにたびたつつもりですか？』系をとらまえてYesを押す論理が必要」
--   ★王様（とイシスの女王）は記録（Q1）のあと、bank 13 の `$BB9D` で Q2 を聞く（`talk_script.DEPART_QUESTION`）。
--   ⚠ Q2 に B（= いいえ）で答えると `$BBCC` で自分へ JMP し、**ゲームが終わる**。
--   ★聞き込みは王様に話しかけない（ROM の表 / `town_service.rom_save_kings`）。★ここは**それを抜けた相手**への備え。
--   ★Q1（記録するか）は今までどおり B = いいえ（⚠ 冒険の書を自動で書き換えない）。
local DEPART_WAIT = 600      --: ⚠ はい／いいえ の窓を待つ上限（フレーム）。★出なければ**何も押さずに**止める
local DEPART_SETTLE = 20     --: ★見張りが鳴ってから窓を見始めるまで（★押しかけの B を捨てたあと）
local DEPART_GAP = 30        --: ★押したあと、次に窓を見るまで
local DEPART_MOVES = 3       --: ⚠ ▶ を はい へ寄せる上限
local COLS, ROWS = CFG.columns or 32, CFG.rows or 30
local CURSOR = CFG.cursor_tile or 0x72
--: ★★ 施設の人の最初の台詞で高速化を解き、施設ごとに止める（RX3-0241 / 2026-09-13）。
--
--   ⚠⚠ 依頼者の小WI「自動移動後の施設会話停止位置と引継ぎを整理」（`docs/design/dq3-facility-stop-spec.md`）:
--     「最初のメッセージが発生した瞬間に高速化を解除する」（⚠ 着いた・A を送った・一定フレームではない）。
--   ★最初の台詞 = はなす のあと `$828B` の見張りが鳴り（★相手がいる）、画面の下半分の会話の窓に字が出た。
--   ★街移動（`stop_at="first_message"`）だけ。⚠ 聞き込み・補充は今までどおり。
--   ★宿屋（`facility="inn"`）だけは泊まるかの問いに はい まで進む（下の `$A55C`）。ほかの施設はそこで止める。
local FIRST_MIN_Y = math.floor(ROWS / 2)   --: ⚠ 会話の窓の上辺はこれより下（★上のコマンド・状態の窓を掴まない）
--: ★★ 宿屋の「おとまりに なりますか？」（bank 13 / RX3-0241 / 2026-09-13 逆アセンブル / `talk_script.INN_QUESTION`）
--
--   `$A51F` 宿屋の処理: 挨拶（メッセージ $17 昼 / $18 夜）→ 値段 → `$A556` 問い（$19）→ ★`$A55C` BRK 20 17（はい／いいえ）
--   → いいえ / B は `$A51B`（またどうぞ）/ はい はお金を見て泊まる（⚠ 足りなければ `$A518`）。
--   ★宿屋の処理の はい／いいえ は `$A55C` の 1 か所だけ（⚠ 誤った相手・別の問いでは鳴らない）。
local INN_QUESTION = 0xA55C
local INN_WAIT = 600         --: ⚠ 最初の台詞から問いまでの上限（フレーム）。★来なければ**何も押さずに**止める
local INN_B_MAX = 4          --: ⚠ ▼ を B で送る上限（★挨拶は 1 ページ）
--: ★★ 歩き出す前に窓を閉じる（RX3-0115 / 2026-09-08 依頼者「移動が吸われている」）。
--
--   ⚠⚠ 窓（コマンド / ステータス / 会話）が開いていると、方向キーは**窓が食べます**。
--     ★歩数だけ減って一歩も動かず、⚠ `path_blocked` として返っていました。
--   ★`CLEAR_TRIES` 回まで B を押し、⚠ それでも閉じなければ**歩かずに止めます**
--     （★黙って `path_blocked` にしない）。
local CLEAR_GAP, CLEAR_TRIES = 24, 6
--: ⚠ 窓が**読めない**とき、押す回数（★押しすぎない。B は場面では無害）
local CLEAR_BLIND = 2
local NPC_WAIT_LIMIT, MAX_APPROACHES, APPROACH_EVERY = 2400, 8, 120
--: ⚠ 話しかける前に動く相手が離れたとき、待ち直す上限（RX3-0170）
local MAX_RETALKS = 3
--: ★世界地図（$2F）— ⚠ **ここ以外はすべて「地図の中」**（RX3-0311）
--
--   ⚠⚠ 2026-09-20 依頼者「ラダトームで聞き込みがきかない」「バラモスを倒したが、きかない」。
--     ★実機の `state.json`: `loc_kind = 3` / `map_id = 7`（ラダトーム）、
--     ⚠ `nav = {reason = "not_local"}` / `town_speed.last_off = "HEARING_ERROR"`。
--
--   ★ここは長らく `KIND_LOCAL = 1` **ちょうど**を見ていました。
--   ⚠ アレフガルドの町は **kind 3**、洞窟は 5 なので、⚠⚠ **街移動も聞き込みも全部断って**いました。
--
--   ★同じ判断は `map_art.lua`（RX3-0103）と `dq3/knowledge/seen_map.py` で
--     **既に直っています**。⚠ ここだけ取り残されていました（★2 か所に書いた判定の片方）。
local KIND_WORLD = 0      -- ★上の世界
local KIND_ALEFGARD = 2   -- ★アレフガルドの世界地図

--- ★「地図の中」か（⚠ 世界地図の 2 つ以外はすべて地図の中）。
local function is_local(kind)
  return kind ~= nil and kind ~= KIND_WORLD and kind ~= KIND_ALEFGARD
end

--- ★いまの場所（⚠ `dev.lua` の 1 つを使う）。
local function where()
  if HOST == nil or type(HOST.where) ~= "function" then return nil end
  local ok, got = pcall(HOST.where)
  if not ok or type(got) ~= "table" or got.loc_kind == nil then return nil end
  return {kind = got.loc_kind, map_id = got.map_id, x = got.map_x, y = got.map_y}
end

----------------------------------------------------------------------
-- ★誰と話したか（$828B: bank 14 の `JSR $F507` の直後。★RX3-0053 §10）
----------------------------------------------------------------------
HOST.last_talk = nil
local talk_hook = pcall(function()
  memory.registerexec(0x828B, 1, function()
    if memory.readbyte(A_BANK) ~= 14 then return end
    HOST.last_talk = {frame = emu.framecount(), slot = math.floor(memory.readbyte(0x6C) / 4),
                      talk_id = memory.readbyte(0x05) * 256 + memory.readbyte(0x04)}
  end)
end)

----------------------------------------------------------------------
-- ★★ **すぐ旅立つかを尋ねる窓**（bank 13 $BB9D / RX3-0194）
----------------------------------------------------------------------
--   ★`$BB9D` は記録の処理 `$BB61` の中からだけ入る（Q1 の いいえ → BNE / 記録のあと → JMP）。
--   ★ここでは「通った」フレームだけ写す。⚠ 答えるのは聞き込みの閉じる段（`tick_close`）だけ。
--   ⚠ 未確認: `$BB9D` を通るとき `$06D5` が 13 か（★`$828B` の見張りの「14」と同じ決まりで見る）。
--     ★違えば鳴らないだけ（⚠ A は押さず、今までどおり B で閉じる）。
local depart_at = nil
local depart_hook = pcall(function()
  memory.registerexec(0xBB9D, 1, function()
    if memory.readbyte(A_BANK) ~= 13 then return end
    depart_at = emu.framecount()
  end)
end)

--: ★★ 宿屋の はい／いいえ（bank 13 $A55C / RX3-0241）。★通ったフレームだけ写す（⚠ 答えるのは宿屋の段 `tick_inn` だけ）
local inn_ask_at = nil
local inn_hook = pcall(function()
  memory.registerexec(INN_QUESTION, 1, function()
    if memory.readbyte(A_BANK) ~= 13 then return end
    inn_ask_at = emu.framecount()
  end)
end)


----------------------------------------------------------------------
-- ★通行可否の表（★Python が書く。⚠ 判断の正本は Python）
----------------------------------------------------------------------
local GRID, GW, GH = nil, 0, 0
local function load_grid(path)
  GRID, GW, GH = nil, 0, 0
  if path == nil or path == "" then return false end
  local fh = io.open(path, "r")
  if fh == nil then return false end
  local w, h = (fh:read("*l") or ""):match("(%d+)%s+(%d+)")
  GW, GH = tonumber(w) or 0, tonumber(h) or 0
  GRID = {}
  for _ = 1, GH do GRID[#GRID + 1] = fh:read("*l") or "" end
  fh:close()
  return GW > 0 and GH > 0
end
--   ★O = 鍵を使って開けた扉（door_open / RX3-0263 / Python がこの場で開けた扉だけ書く）。
--   ⚠ D = 閉じた扉（door_closed）は壁のまま（★開けていない扉へは突っ込まない）
--   ★H = ダメージ床（RX3-0277 / 歩けるが HP が減る）。`avoid_hurt` のときだけ壁と同じに見る
local function passable(x, y, extra_block, avoid_hurt)
  if GRID == nil or x < 0 or y < 0 or x >= GW or y >= GH then return false end
  if extra_block ~= nil and extra_block[x .. ":" .. y] then return false end
  local c = GRID[y + 1]:sub(x + 1, x + 1)
  return c == "P" or c == "C" or c == "O" or (c == "H" and not avoid_hurt)
end
--: ★カウンター（★Python が `K` で書く / RX3-0182）。⚠ 通れないのは壁と同じ（`passable` は P / C だけ）
local function is_counter(x, y)
  if GRID == nil or x < 0 or y < 0 or x >= GW or y >= GH then return false end
  return GRID[y + 1]:sub(x + 1, x + 1) == "K"
end
--- ★カウンター越しに真っすぐ 2 升先か（RX3-0182 / 2026-09-12 依頼者「カザーブの酒場で聞き込みできない」）。
--   ⚠⚠ 動く相手は「隣（1 升）」でしか話さなかった → カウンターの奥を動く酒場の人とは**一度も**話せなかった。
--   ★店員と同じく、間がカウンターなら 2 升先でも話せる（RX3-0053）。
local function across_counter(ax, ay, nx, ny)
  local dx, dy = nx - ax, ny - ay
  if not ((math.abs(dx) == 2 and dy == 0) or (dx == 0 and math.abs(dy) == 2)) then return false end
  return is_counter(ax + dx / 2, ay + dy / 2)
end
local function bfs_once(sx, sy, gx, gy, extra_block, avoid_hurt)
  local prev = {[sx .. ":" .. sy] = false}
  local queue, head = {{sx, sy}}, 1
  while head <= #queue do
    local cx, cy = queue[head][1], queue[head][2]; head = head + 1
    for _, d in ipairs(DIRS) do
      local nx, ny = cx + d[2], cy + d[3]
      local k = nx .. ":" .. ny
      if prev[k] == nil and (nx == gx and ny == gy or passable(nx, ny, extra_block, avoid_hurt)) then
        prev[k] = {cx .. ":" .. cy, d[1], nx, ny}
        if nx == gx and ny == gy then
          local keys, cells = {}, {}
          local cur = k
          while prev[cur] do
            local p = prev[cur]
            table.insert(keys, 1, p[2]); table.insert(cells, 1, {x = p[3], y = p[4]})
            cur = p[1]
          end
          return keys, cells
        end
        queue[#queue + 1] = {nx, ny}
      end
    end
  end
  return nil
end
--- ★経路（RX3-0277）: まずダメージ床（H）を通らずに探し、⚠ 道が無ければ通る。
--   ★Python の `RomMap.bfs` と同じ規則（⚠ 片側だけ直さない）。H の無い地図では今までの BFS と同じ経路
local function bfs(sx, sy, gx, gy, extra_block)
  if sx == gx and sy == gy then return {}, {} end
  local keys, cells = bfs_once(sx, sy, gx, gy, extra_block, true)
  if keys ~= nil then return keys, cells end
  return bfs_once(sx, sy, gx, gy, extra_block, false)
end

----------------------------------------------------------------------
-- ★状態（★`state.json` の `nav`）
----------------------------------------------------------------------
local status = {active = false, phase = "idle", reason = nil, seq = nil}
HOST.nav_status = status

local run = nil
local runs = 0

----------------------------------------------------------------------
-- ★★ 会話のページを 1 枚ずつ拾う（RX3-0229 / 2026-09-13）
----------------------------------------------------------------------
--   ⚠⚠ 依頼者「save1 老人の話が 2 段目から 以降話が続いているが、メモに残っておらず
--     後で見てもわからない ※長尺メッセージの時にうまくとれてない？」
--   ★原因: 画面は Python が `state.json` を読むとき（0.5 秒おき）にしか見ていなかった。
--     ⚠ Turbo では B を 40 フレームおきに押すので、1 ページが 1 回の読みより短い
--     → ★ページごと飛んだ / 打ちかけで切れた / 重ならない断片が別々のメモになった（1 人の話が 3 件）。
--   → ★ここ（4 フレームおき）で会話の窓を見て、⚠ **消える前の 1 枚**を `run.pages` に残す。
--     `state.json` の `nav.talk_pages`（★dev.lua が `nav` ごと送る）→ Python が 1 件のメモにつなぐ。
--     残すのは ① 字が書き換わる直前（★送り = 上の行が消える / 窓が消える）② B を押す直前。
--     ⚠ 空白 → 字（打っている途中）と ▼ の点滅は「書き換わり」に数えない。
--   ★B は ▼ が**新しく出てから**押す（⚠ 打ちかけを切らない）。▼ が出なければ、画面が止まってから。
local MORE = 0x73                                            --: ★▼ メッセージ送り（`cursor.lua` の M.MORE）
local WIN_TL, WIN_TR, WIN_BL, WIN_BR = 0x79, 0x7C, 0x7A, 0x7E  --: ★窓の四隅（`dq3rom/window.py` と同じ）
local PAGE_POLL = 4          --: ★窓を見る間隔（フレーム）
local PAGE_MIN_W = 16        --: ★会話の窓とみなす幅（⚠ はい／いいえ・お金の窓は狭い）
local PAGE_STABLE = 16       --: ★▼ が出ないとき、画面がこれだけ止まったら B
local PAGE_MIN_GAP = 8       --: ★B のあと、次の B までの最小（フレーム）
local PAGE_WAIT_MAX = 240    --: ⚠ 画面が止まらなくても、ここで B（★止まったままにしない）
local PAGE_MAX = 32          --: ⚠ 1 回の会話で残す上限（★越えたら記録に残し、`talk_pages_full` を立てる）

--- ★画面のタイル（⚠ 読めなければ nil）。★`HOST.screen.read` は 32 × 30 を 1 から並べる。
local function read_nt()
  if HOST == nil or HOST.screen == nil or HOST.screen.read == nil then return nil end
  local ok, nt = pcall(HOST.screen.read)
  if not ok or type(nt) ~= "table" then return nil end
  return nt
end

--- ★会話の窓（⚠ いちばん下にある、幅 PAGE_MIN_W 以上の窓）を 1 枚に写す。⚠ 無ければ nil。
--   `hex` は窓の上辺の行から画面の下まで（★Python が 32 × 30 へ戻し、今と同じ読み方で文字にする）。
--   `inner` は窓の中（⚠ ▼ は -1）。`blank` は中でいちばん多いタイル（★空白とみなす）。
local function page_snapshot(nt)
  if nt == nil or #nt < COLS * ROWS then return nil end
  local function t(x, y) return (nt[y * COLS + x + 1] or 0) % 256 end
  local top, left, right = nil, nil, nil
  for y = ROWS - 3, 0, -1 do
    for x = 0, COLS - PAGE_MIN_W do
      if t(x, y) == WIN_TL then
        for k = x + 2, COLS - 1 do
          local v = t(k, y)
          if v == WIN_TR then
            if k - x + 1 >= PAGE_MIN_W then top, left, right = y, x, k end
            break
          end
          if v == WIN_TL then break end
        end
      end
      if top ~= nil then break end
    end
    if top ~= nil then break end
  end
  if top == nil then return nil end
  local bottom = ROWS - 1
  for y = top + 2, ROWS - 1 do
    if t(left, y) == WIN_BL and t(right, y) == WIN_BR then bottom = y; break end
  end
  local hex, inner, count, more = {}, {}, {}, false
  for y = top, ROWS - 1 do
    for x = 0, COLS - 1 do
      local v = t(x, y)
      hex[#hex + 1] = string.format("%02X", v)
      if y > top and y < bottom and x > left and x < right then
        if v == MORE then more, v = true, -1 end      -- ⚠ ▼ は点滅する（中身に数えない）
        inner[#inner + 1] = v
        if v >= 0 then count[v] = (count[v] or 0) + 1 end
      end
    end
  end
  local blank, most, filled = nil, 0, 0
  for v, c in pairs(count) do
    filled = filled + c
    if c > most then blank, most = v, c end
  end
  return {y = top, hex = table.concat(hex), inner = inner, key = table.concat(inner, ","),
          blank = blank, more = more, empty = (most == filled)}
end

--- ★前の 1 枚の字が書き換わったか（★送り / 窓が変わった）。⚠ 空白 → 字 と ▼ の点滅は数えない。
local function overwrote(prev, snap)
  if #prev.inner ~= #snap.inner then return true end
  for i = 1, #prev.inner do
    local a = prev.inner[i]
    if a >= 0 and a ~= prev.blank and a ~= snap.inner[i] then return true end
  end
  return false
end

--- ★1 枚を残す（⚠ 同じ中身は 1 枚だけ / 空の窓は残さない / 上限つき）。
local function keep_page(snap)
  if run == nil or snap == nil or snap.kept then return end
  snap.kept = true
  if snap.empty or snap.key == run.page_last then return end
  if #run.pages >= PAGE_MAX then
    if not run.pages_full then
      run.pages_full = true
      say(string.format("⚠ 会話のページが %d 枚を越えた（★ここから先はメモに残らない）", PAGE_MAX))
    end
    return
  end
  run.pages[#run.pages + 1] = {y = snap.y, hex = snap.hex}
  run.page_last = snap.key
end

--- ★窓を見て、消える前の 1 枚を残す。★いまの 1 枚を返す（⚠ 窓が無ければ nil）。
local function watch_page(nt)
  local snap = page_snapshot(nt)
  local prev = run.page_prev
  if prev ~= nil and not prev.kept
      and (snap == nil or snap.y ~= prev.y or overwrote(prev, snap)) then
    keep_page(prev)
  end
  if snap ~= nil and prev ~= nil and prev.y == snap.y and prev.key == snap.key then snap.kept = prev.kept end
  run.page_prev = snap
  return snap
end

--- ★窓が無いときの指紋（⚠ ▼ の点滅は数えない）。
local function nt_key(nt)
  local h = 0
  for i = 1, #nt do
    local v = (nt[i] or 0) % 256
    if v == MORE then v = 0 end
    h = (h * 31 + v) % 2147483647
  end
  return tostring(h)
end

local function publish()
  if run == nil then return end
  status.talk_pages = run.pages
  status.talk_pages_full = run.pages_full
  status.active = true
  status.phase = run.phase
  status.seq = run.seq
  status.step = run.i
  status.steps = #run.keys
  status.replans = run.replans
  status.blocks = run.blocks
  status.approaches = run.approaches
  status.talk_frame = run.talk_frame
  status.closed = run.closed
  status.first_message = run.first_message   -- ★RX3-0241: 最初の台詞のフレーム（★画面が速度・音を開始前へ戻す）
  status.facility = run.facility
  status.reason = nil
end

local function finish(why, extra)
  if run == nil then return end
  local at = where() or {}
  say(string.format("★終了 %s 歩いた %d / %d いま (%s,%s) 待ち %d replan %d 近づき %d%s", why, run.i, #run.keys,
      tostring(at.x), tostring(at.y), run.blocks, run.replans, run.approaches, extra and (" / " .. extra) or ""))
  status.active = false
  status.phase = "done"
  status.reason = why
  status.step = run.i
  status.steps = #run.keys
  status.talk_frame = run.talk_frame
  status.closed = run.closed
  status.first_message = run.first_message
  status.facility = run.facility
  keep_page(run.page_prev)     -- ★窓が開いたまま終わった（★はい／いいえ など）→ 最後の 1 枚も残す
  status.talk_pages = run.pages
  status.talk_pages_full = run.pages_full
  status.finished_at = emu.framecount()
  BUTTONS.release(ME)
  run = nil
end

local function press(key, hold)
  BUTTONS.press(ME, key, {hold = hold or 24, watch_held = true})
end

local function split(text, pat)
  local out = {}
  for k in (text or ""):gmatch(pat) do out[#out + 1] = k end
  return out
end

--- ★`"CDC0"` → `{0xCD, 0xC0}`（★Python の `tile_bytes` を 16 進で受け取る / RX3-0194）。
local function tiles_of(hex)
  local out = {}
  for h in (hex or ""):gmatch("%x%x") do out[#out + 1] = tonumber(h, 16) end
  return out
end

--- ★頼みを受けて歩き始める。
local function start(params, seq)
  params = params or {}
  status.first_message, status.facility = nil, nil   -- ⚠ 前の頼みの「最初の台詞」を残さない（RX3-0241）
  local at = where()
  if at == nil or not is_local(at.kind) then
    status.active, status.phase, status.reason, status.seq = false, "done", "not_local", seq
    say("⚠ 町の中でないので歩きません")
    return
  end
  if run ~= nil then finish("replaced") end
  if not BUTTONS.claim(ME) then
    status.active, status.phase, status.reason, status.seq = false, "done", "buttons_busy", seq
    say("⚠⚠ ボタンを握れません（★ほかの機能が使っています）")
    return
  end
  runs = runs + 1
  local keys = split(params.keys, "[^,]+")
  local cells = {}
  for x, y in (params.cells or ""):gmatch("(%d+):(%d+)") do cells[#cells + 1] = {x = tonumber(x), y = tonumber(y)} end
  local grid_ok = load_grid(params.grid)
  local npc_slot = tonumber(params.npc_slot or "")
  if npc_slot ~= nil and npc_slot < 0 then npc_slot = nil end
  run = {
    seq = seq, keys = keys, cells = cells, i = 0, from = nil, waited = 0, blocked_tries = 0,
    -- ★1 歩進んだと認めるまでの数え（RX3-0177 / ⚠ 人にぶつかると 1 フレームだけ行き先の升に見える）
    moved_key = nil, moved_hold = 0,
    replans = 0, blocks = 0, approaches = 0, phase = "clear", start_map = at.map_id,
    face = (params.face ~= nil and params.face ~= "") and params.face or nil,
    talk = params.talk == "1", close = params.close == "1", npc_slot = npc_slot,
    talk_frame = nil, closed = nil, face_tries = 0,
    -- ★Q2 の窓を探す字（★無ければ窓を見つけられず、A を押さない / RX3-0194）
    yes = tiles_of(params.yes), no = tiles_of(params.no), depart = nil, depart_done = false,
    -- ★会話のページ（RX3-0229）。★`state.json` の `nav.talk_pages`
    pages = {}, page_prev = nil, page_last = nil, pages_full = nil,
    -- ★最初の台詞で止める（RX3-0241 / ★街移動だけ）/ 施設（★宿屋だけ はい まで）
    stop_first = params.stop_at == "first_message",
    facility = (params.facility ~= nil and params.facility ~= "") and params.facility or nil,
    first_message = nil, inn_b = 0, inn_pressed = nil,
    -- ★はい／いいえ が新しく出た回数（RX3-0273 / ⚠ 頼みごとに 0 から）
    choices = 0, choice_seen = false,
  }
  HOST.last_talk = nil
  depart_at = nil
  inn_ask_at = nil
  say(string.format("=== NAV start %s run=%d seq=%s map=%d (%d,%d) 歩数=%d face=%s talk=%s npc_slot=%s close=%s grid=%s hook=%s depart_hook=%s yes=%d ===",
      os.date("%H:%M:%S"), runs, tostring(seq), at.map_id, at.x, at.y, #keys, tostring(run.face), tostring(run.talk),
      tostring(npc_slot), tostring(run.close), tostring(grid_ok), tostring(talk_hook), tostring(depart_hook), #run.yes))
  if run.stop_first or run.facility ~= nil then
    say(string.format("  ★最初の台詞で止める=%s 施設=%s inn_hook=%s", tostring(run.stop_first), tostring(run.facility),
        tostring(inn_hook)))
  end
  publish()
end

----------------------------------------------------------------------
-- ★局面ごとの 1 フレーム
----------------------------------------------------------------------
local function arrive(at)
  if run.npc_slot ~= nil then
    run.phase, run.waited = "wait_npc", 0
    say(string.format("★着いた (%d,%d)。動く NPC（slot %d）が隣に来るのを待つ", at.x, at.y, run.npc_slot))
    return
  end
  if run.face ~= nil then run.phase, run.waited = "face", 0
  else run.phase, run.waited = "after", 0 end
end

local function replan(at, block_cell)
  local last = run.cells[#run.cells]
  if last == nil then return false end
  local extra = {[block_cell.x .. ":" .. block_cell.y] = true}
  local keys, cells = bfs(at.x, at.y, last.x, last.y, extra)
  if keys == nil then return false end
  local nk, nc = {}, {}
  for k = 1, run.i do nk[k] = run.keys[k]; nc[k] = run.cells[k] end
  for k = 1, #keys do nk[#nk + 1] = keys[k]; nc[#nc + 1] = cells[k] end
  run.keys, run.cells = nk, nc
  run.replans = run.replans + 1
  say(string.format("★replan %d: (%d,%d) から %d 歩（(%d,%d) を避ける）", run.replans, at.x, at.y, #keys, block_cell.x, block_cell.y))
  return true
end

local function tick_walk(at)
  if run.from == nil then
    if run.i >= #run.keys then arrive(at); return end
    run.i = run.i + 1
    run.from, run.waited, run.blocked_tries = {x = at.x, y = at.y}, 0, 0
    press(run.keys[run.i])
    return
  end
  run.waited = run.waited + 1
  local want = run.cells[run.i]
  if at.x ~= run.from.x or at.y ~= run.from.y then
    -- ★★ 1 フレームだけ行き先の升に見えることがある（RX3-0177 / ★人にぶつかると次のフレームで戻る）。
    --   ⚠ 1 枚で決めると「1 歩進んだ」と数えてしまい、次の歩で升が合わず打ち切っていました。
    local key = at.x .. ":" .. at.y
    if run.moved_key ~= key then run.moved_key, run.moved_hold = key, 0 end
    run.moved_hold = run.moved_hold + 1
    if run.moved_hold < MOVE_STABLE then return end          -- ⚠ 同じ升が続くまで待つ
    run.moved_key, run.moved_hold = nil, 0
    if want ~= nil and (at.x ~= want.x or at.y ~= want.y) then
      -- ★ずれ（★動く NPC に押し出された等）。⚠ 打ち切らず、いま居る升から引き直す（RX3-0177）
      if run.replans < MAX_REPLANS and replan(at, want) then
        run.from = nil
        return
      end
      finish("path_deviation", string.format("期待 (%d,%d) 実際 (%d,%d)", want.x, want.y, at.x, at.y)); return
    end
    run.from = nil
    return
  end
  run.moved_key, run.moved_hold = nil, 0        -- ★同じ升に戻った（⚠ ぶつかり）→ 数え直す
  if run.waited >= STEP_FRAMES then
    run.blocked_tries = run.blocked_tries + 1
    run.blocks = run.blocks + 1
    if run.blocked_tries <= BLOCK_RETRIES then
      run.waited = STEP_FRAMES - BLOCK_WAIT
      press(run.keys[run.i])
      return
    end
    if run.replans >= MAX_REPLANS or want == nil or not replan(at, want) then
      finish("path_blocked", string.format("(%d,%d) へ進めない", want and want.x or -1, want and want.y or -1)); return
    end
    run.from = nil
  end
end

local function tick_wait_npc(at)
  run.waited = run.waited + 1
  local o = 0x0100 + run.npc_slot * 4
  local nx, ny, st = memory.readbyte(o), memory.readbyte(o + 1), memory.readbyte(o + 3)
  local dx, dy = nx - at.x, ny - at.y
  local beside = math.abs(dx) + math.abs(dy) == 1
  -- ★カウンター越し（真っすぐ 2 升先 / RX3-0182）も「隣」と同じに扱う
  if (beside or across_counter(at.x, at.y, nx, ny)) and (st % 128) < 64 then
    run.face = (dx > 0 and "right") or (dx < 0 and "left") or (dy > 0 and "down") or "up"
    say(string.format("★NPC（slot %d）が%s (%d,%d) → %s を向く（待ち %d）", run.npc_slot,
        beside and "隣" or "カウンター越し", nx, ny, run.face, run.waited))
    run.phase, run.waited = "face", 0
    return
  end
  if run.waited % APPROACH_EVERY == 0 and (st % 128) < 64 then
    local best_n, best_keys, best_cells = nil, nil, nil
    for _, d in ipairs(DIRS) do
      local ax, ay = nx + d[2], ny + d[3]
      -- ★隣の升。⚠ 隣がカウンターなら、その向こう（2 升先）へ行く（RX3-0182）
      if is_counter(ax, ay) then ax, ay = nx + 2 * d[2], ny + 2 * d[3] end
      if passable(ax, ay, nil) then
        local keys, cells = bfs(at.x, at.y, ax, ay, {[nx .. ":" .. ny] = true})
        if keys ~= nil and (best_n == nil or #keys < best_n) then best_n, best_keys, best_cells = #keys, keys, cells end
      end
    end
    if best_keys ~= nil and #best_keys > 0 then
      run.approaches = run.approaches + 1
      if run.approaches > MAX_APPROACHES then finish("skip_unreachable_now", string.format("NPC は (%d,%d)", nx, ny)); return end
      for k = 1, #best_keys do run.keys[#run.keys + 1] = best_keys[k]; run.cells[#run.cells + 1] = best_cells[k] end
      say(string.format("★NPC（slot %d）は (%d,%d) → %d 歩で近づく（%d 回目）", run.npc_slot, nx, ny, #best_keys, run.approaches))
      run.phase, run.waited, run.from = "walk", 0, nil
      return
    end
  end
  if run.waited >= NPC_WAIT_LIMIT then finish("skip_unreachable_now", string.format("NPC は (%d,%d)", nx, ny)) end
end

local function tick_face(at)
  run.waited = run.waited + 1
  if run.waited == 1 then
    run.face_pos = {x = at.x, y = at.y}; run.face_tries = 1
    press(run.face, FACE_HOLD)
  elseif run.waited % 60 == 0 then
    if at.x ~= run.face_pos.x or at.y ~= run.face_pos.y then
      -- ★動く相手が向く瞬間に離れ、空いた升へ 1 歩出た（RX3-0170 / 実機）。★その場から待ち直す
      if run.npc_slot ~= nil and (run.retalks or 0) < MAX_RETALKS then
        run.retalks = (run.retalks or 0) + 1
        say(string.format("★向く間に相手（slot %d）が離れて 1 歩出た → (%d,%d) から待ち直す（%d 回目）",
            run.npc_slot, at.x, at.y, run.retalks))
        run.phase, run.waited = "wait_npc", 0
        return
      end
      finish("face_moved", "向くだけのはずが動いた")
      return
    end
    local turned = (memory.readbyte(A_FACING) == KEY_INDEX[run.face])
    if turned or run.face_tries >= FACE_TRIES then
      if run.talk then run.phase, run.waited = "talk", 0 else run.phase, run.waited = "after", 0 end
    else
      run.face_tries = run.face_tries + 1
      press(run.face, FACE_HOLD)
    end
  end
end

--- ★動く相手が、いま向いている方向の隣にいるか（⚠ 動かない相手は見ない）。
local FACE_STEP = {up = {0, -1}, down = {0, 1}, left = {-1, 0}, right = {1, 0}}
local function npc_in_front(at)
  local d = FACE_STEP[run.face or ""]
  if run.npc_slot == nil or d == nil then return true end
  local o = 0x0100 + run.npc_slot * 4
  local x, y = memory.readbyte(o), memory.readbyte(o + 1)
  if x == at.x + d[1] and y == at.y + d[2] then return true end
  -- ★カウンター越し（★正面がカウンターで、その向こうに相手 / RX3-0182）
  return x == at.x + 2 * d[1] and y == at.y + 2 * d[2] and is_counter(at.x + d[1], at.y + d[2])
end

--- ★★ 施設の人の最初の台詞が出たか（RX3-0241）。★出たら高速化を解き、施設ごとの次へ進める。
--
--   ★出た = ① `$828B`（誰と話したか）がこの会話の中で鳴った（⚠ 見張りが無い環境では見ない）
--            ② 会話の窓（幅 PAGE_MIN_W 以上）が画面の下半分にある ③ 窓の中に字が 1 つ以上ある
--   ★高速化を解くのは Lua の `town_speed.first_message`（⚠ 画面の 0.5 秒を待たない）。
--   ★宿屋は `inn`（泊まるかの問いへ）、ほかの施設はここで止める（first_message / ⚠ 窓は開いたまま）。
local function first_message(snap)
  if run.first_message ~= nil or snap == nil or snap.empty or snap.y < FIRST_MIN_Y then return false end
  local talk = HOST.last_talk
  if talk_hook and (type(talk) ~= "table" or run.talk_frame == nil or (talk.frame or -1) < run.talk_frame) then
    return false                 -- ⚠ 相手が決まっていない（★誰もいない / 見張りの前の窓）
  end
  run.first_message = emu.framecount()
  local ts = HOST.town_speed
  local ok, got = false, nil
  if type(ts) == "table" and ts.first_message ~= nil then ok, got = pcall(ts.first_message) end
  say(string.format("★★ 最初の台詞（はなす から %d フレーム / 窓の上辺 %d / talk_id %s）→ 高速化を解いた（%s）→ %s",
      run.waited - TALK_MENU_GAP, snap.y, tostring(type(talk) == "table" and talk.talk_id or nil),
      ok and tostring(got) or "town_speed が無い", run.facility == "inn" and "宿屋は問いへ" or "ここで止める"))
  if run.facility == "inn" then
    run.phase, run.waited = "inn", 0
  else
    finish("first_message", tostring(run.facility))
  end
  return true
end

local function tick_talk(at)
  run.waited = run.waited + 1
  -- ★はなす のあとは窓を見て、送られて消える前の 1 枚を残す（RX3-0229）。
  --   ⚠ 閉じる段まで待つと、長い 1 ページ目は頭が送られて消えている
  if run.waited > TALK_MENU_GAP and run.waited % PAGE_POLL == 0 then
    local nt = read_nt()
    local snap = (nt ~= nil) and watch_page(nt) or nil
    -- ★★ 最初の台詞で高速化を解き、施設ごとに止める（RX3-0241 / ★街移動だけ）
    if run.stop_first and first_message(snap) then return end
  end
  if run.waited == 1 then
    -- ★★ 押す直前に、動く相手がまだ正面にいるかを見る（RX3-0170 / 2026-09-11 実機）。
    --   ⚠ 「隣に来た」から向きの確認（60 フレーム）の間に 1 マス動かれ、★誰もいない方へ話しかけて
    --     会話にならなかった（聞き込み 1 回で 2〜3 人 / Turbo の run で目立った）。
    --   → ★離れていたら押さずに待ち直す（⚠ 何度も離れるなら止める）。
    if not npc_in_front(at) then
      run.retalks = (run.retalks or 0) + 1
      if run.retalks > MAX_RETALKS then
        finish("face_moved", "話しかける前に相手が離れた（" .. run.retalks .. " 回）")
        return
      end
      say(string.format("★話しかける前に相手（slot %d）が離れた → 待ち直す（%d 回目）", run.npc_slot, run.retalks))
      run.phase, run.waited = "wait_npc", 0
      return
    end
    press("A", 8)
    depart_at = nil            -- ★この会話より前の「また たびだつか」は見ない（⚠ セーブを読むとフレーム数が戻る）
    inn_ask_at = nil           -- ★宿屋の問いも同じ（RX3-0241）
    run.talk_frame = emu.framecount()
  elseif run.waited == TALK_MENU_GAP then
    -- ⚠⚠ DQ3 はコマンドの窓を開いている間も NPC が動く（2026-09-11 実機: (17,30) → (18,30)）。
    --   ★「はなす」の直前にもう一度見て、離れていたら窓を閉じてから待ち直す（★clear が B で閉じる）
    if not npc_in_front(at) then
      run.retalks = (run.retalks or 0) + 1
      if run.retalks > MAX_RETALKS then
        finish("face_moved", "はなす の前に相手が離れた（" .. run.retalks .. " 回）")
        return
      end
      say(string.format("★はなす の前に相手（slot %d）が離れた → 窓を閉じて待ち直す（%d 回目）",
          run.npc_slot, run.retalks))
      run.phase, run.waited, run.from = "clear", 0, nil
      return
    end
    press("A", 8)
    -- ★動く相手は、押した瞬間にまだ隣にいるかを残す（RX3-0170 / ⚠ 会話にならなかったわけを追う）
    local extra = ""
    if run.npc_slot ~= nil then
      local o = 0x0100 + run.npc_slot * 4
      extra = string.format("（相手 slot %d は (%d,%d) st=%02X / 自分 (%d,%d) 向き %d）", run.npc_slot,
          memory.readbyte(o), memory.readbyte(o + 1), memory.readbyte(o + 3), at.x, at.y,
          memory.readbyte(A_FACING))
    end
    say("★はなす を選んだ（⚠ 会話が始まったかは画面が窓で見る）" .. extra)
  elseif run.waited == TALK_WAIT then
    if run.close then run.phase, run.waited = "close", 0 else run.phase, run.waited = "after", 0 end
  end
end

--- ★★ 歩き出す前に、開いている窓を閉じる（RX3-0115）。
--
-- ⚠ 窓が読めない環境（★`HOST.window_open` が無い / 画面が取れない）では、
--   ★数回 B を押してから歩き出します（⚠ 押しすぎない）。
local function tick_clear(at)
  -- ⚠⚠ `a and b or c` は書かないこと。★`b` が `false` のとき `c` を返します
  --   （2026-09-08 に踏んだ: 「窓は無い」が「読めない」に化けて、B を余計に 2 回押した）。
  local open = nil
  if HOST ~= nil and HOST.window_open ~= nil then open = HOST.window_open() end
  if open == false then
    if run.cleared_by ~= nil then
      say(string.format("★窓を閉じた（B を %d 回）", run.cleared_by))
    end
    run.phase, run.waited = "walk", 0
    return
  end
  run.waited = run.waited + 1
  if run.waited % CLEAR_GAP ~= 0 then return end
  local n = run.waited / CLEAR_GAP
  -- ⚠ 窓が読めるなら「閉じるまで」、読めないなら**少しだけ**（★押しすぎない）
  local limit = (open == nil) and CLEAR_BLIND or CLEAR_TRIES
  if n > limit then
    if open == nil then
      -- ⚠ 窓が読めない。★押すだけ押したので、歩き出す（黙って止めない）
      say("⚠ 窓が読めません。★B を " .. CLEAR_BLIND .. " 回押してから歩き出します")
      run.phase, run.waited = "walk", 0
      return
    end
    -- ⚠⚠ 2026-09-08: ここで **止めていました**。★城で聞き込みが全滅しました。
    --   ⚠ 「窓が出ている」と「入力が吸われる」は**別**です。
    --     ★DQ3 はフィールドでもパーティのステータス窓を出したままにすることがあり、
    --     ⚠ そのときは入力は吸われません（★実際、城では歩けていました）。
    --   → ★閉じなくても**歩き出します**（⚠ 吸われていれば、今までどおり
    --     `path_blocked` になるだけで、**悪くはなりません**）。
    say("⚠ B を " .. CLEAR_TRIES .. " 回押しても窓が消えません。★そのまま歩き出します")
    run.phase, run.waited = "walk", 0
    return
  end
  run.cleared_by = n
  press("B", 8)
end

--- ★画面の指紋（⚠ 読めなければ nil）。★B を押して「何か変わったか」を見るだけ。
local function screen_digest()
  if HOST == nil or HOST.screen == nil or HOST.screen.read == nil then return nil end
  local ok, tiles = pcall(HOST.screen.read)
  if not ok or tiles == nil then return nil end
  local h = 0
  for i = 1, #tiles do h = (h * 31 + ((tiles[i] or 0) % 256)) % 2147483647 end
  return h
end

--: ★画面のタイルは `read_nt`（★会話のページの段で定義 / RX3-0229 で上へ移した）
local function tile_at(nt, x, y)
  if nt == nil or x < 0 or y < 0 or x >= COLS or y >= ROWS then return nil end
  return nt[y * COLS + x + 1]
end

local function seq_at(nt, seq, x, y)
  for k = 1, #seq do
    if tile_at(nt, x + k - 1, y) ~= seq[k] then return false end
  end
  return true
end

--- ★はい／いいえ の窓（★はい の 1〜2 行下に いいえ が**同じ列**で並ぶ）。⚠ 無ければ nil。
--   ★文の中の「はい」（はいる など）を掴まないように、いいえ と組で見る（★濁点の行を挟むので 2 行下もある）。
local function yes_no_window(nt)
  if nt == nil or #run.yes == 0 or #run.no == 0 then return nil end
  for y = 0, ROWS - 1 do
    for x = 1, COLS - #run.yes do
      if seq_at(nt, run.yes, x, y) then
        for dy = 1, 2 do
          if seq_at(nt, run.no, x, y + dy) then return x, y, y + dy end
        end
      end
    end
  end
  return nil
end

--- ★★ Q2**すぐ旅立つかを尋ねる窓**に はい で 1 回だけ答える（RX3-0194）。
--
--   ⚠⚠ A を押すのは、次の 3 つが**そろったときだけ**:
--     ① `$BB9D` の見張りが**この会話の中で**鳴った（bank 13）
--     ② はい／いいえ の窓が見える（★はい の下に いいえ）
--     ③ ▶ が はい の左にある
--   ⚠ 窓が出ないまま DEPART_WAIT を越えたら、**何も押さずに**止める（depart_question_unanswered）。
--   ⚠ A のあと窓が消えなければ、★B を押さずに止める（⚠ B = いいえ = ゲームが終わる）。
--   ⚠ 未確認: ▶ が はい から始まるか（★いいえ にあれば 上 で寄せる / DEPART_MOVES まで）。
local function tick_depart()
  local d = run.depart
  -- ★宿屋の問い（RX3-0241）も同じ手で答える。⚠ 違うのは 答えたあと（★宿屋はそこで止める）と 止まるわけの名前だけ
  local inn = d.kind == "inn"
  local unanswered = inn and "inn_question_unanswered" or "depart_question_unanswered"
  d.waited = d.waited + 1
  if d.cool > 0 then d.cool = d.cool - 1; return end
  -- ★press は予約（★届くまで次を決めない / ⚠ 押した直後に次を押すと 1 フレーム押しになる）
  if BUTTONS.busy ~= nil and BUTTONS.busy() then return end
  local nt = read_nt()
  local x, y, ny = yes_no_window(nt)
  if d.answered ~= nil then
    -- ★はい を押した。★窓が消えたら、ふつうの閉じ方（B）へ戻る（★宿屋はここで止める = 泊まる流れは人へ）
    if x == nil and inn then
      finish("inn_yes", string.format("はい の窓が消えた（%d フレーム）", d.waited - d.answered))
    elseif x == nil then
      say(string.format("★はい の窓が消えた（%d フレーム）→ ★B で閉じる", d.waited - d.answered))
      run.depart, run.depart_done, run.waited, run.close_digest = nil, true, 0, nil
      run.close_presses = 0      -- ★ここから数え直す（★決まった回数の B をもう一度 / 今までと同じ）
    elseif d.waited - d.answered > DEPART_WAIT then
      finish(unanswered, "はい を押したが窓が消えない（⚠ B は押さない）")
    end
    return
  end
  if x ~= nil and tile_at(nt, x - 1, y) == CURSOR then
    press("A", 8)
    d.answered, d.cool = d.waited, DEPART_GAP
    say(string.format("★★「%s」に はい（A）で答えた（はい (%d,%d) / 見張りから %d フレーム）",
        inn and "おとまりに なりますか" or "また たびだつか", x, y, emu.framecount() - d.since))
    return
  end
  if x ~= nil and tile_at(nt, x - 1, ny) == CURSOR then
    if d.moves >= DEPART_MOVES then
      finish(unanswered, "▶ を はい へ寄せられない（★A は押していない）")
      return
    end
    d.moves, d.cool = d.moves + 1, DEPART_GAP
    press("up", 8)
    say(string.format("★▶ が いいえ にある → 上（%d 回目）", d.moves))
    return
  end
  -- ⚠ 窓がまだ出ていない / ▶ が点滅で消えている。★見えるまで待つ（上限つき）
  if d.waited > DEPART_WAIT then
    finish(unanswered, (x == nil and "はい／いいえ が出ない" or "▶ が見えない") .. "（★何も押していない）")
  end
end

--- ★★ 宿屋: 最初の台詞のあと、泊まるかの問いまで ▼ を B で送り、はい で答える（RX3-0241）。
--
--   ⚠⚠ B は ▼ が**新しく出た**ときだけ押す（★はい／いいえ の窓に B = いいえ）。
--   ★`$A55C`（宿屋の はい／いいえ / bank 13）の見張りが**この会話の中で**鳴ったら、B をやめて はい を探す
--     （★`tick_depart` と同じ手: 窓の字 ＋ ▶ が はい の左）。はい の窓が消えたら inn_yes で止める。
--   ⚠ 問いが来ないまま INN_WAIT を越えたら、**何も押さずに**止める（inn_question_unanswered）。
local function tick_inn()
  if run.depart ~= nil then tick_depart(); return end
  if inn_ask_at ~= nil and run.talk_frame ~= nil and inn_ask_at >= run.talk_frame then
    if BUTTONS.cancel ~= nil then BUTTONS.cancel(ME) end
    run.depart = {waited = 0, moves = 0, cool = DEPART_SETTLE, since = inn_ask_at, kind = "inn"}
    say(string.format("★★ $A55C（宿屋の おとまりに なりますか？）を通った（フレーム %d / ▼ を B で %d 回送った）→ はい を探す",
        inn_ask_at, run.inn_b))
    return
  end
  run.waited = run.waited + 1
  if run.waited > INN_WAIT then
    finish("inn_question_unanswered", string.format("宿屋の問いが来ない（★はい は押していない / ▼ の B %d 回）", run.inn_b))
    return
  end
  if run.waited % PAGE_POLL ~= 0 or run.inn_b >= INN_B_MAX then return end
  if BUTTONS.busy ~= nil and BUTTONS.busy() then return end
  local nt = read_nt()
  if nt == nil then return end
  local snap = watch_page(nt)
  -- ★▼ が出ていて、しかも前に B を押したページではない（⚠ 押した B が届く前に同じページへ 2 度押さない）
  if snap == nil or not snap.more or snap.key == run.inn_pressed then return end
  keep_page(snap)
  press("B", 8)
  run.inn_b, run.inn_pressed = run.inn_b + 1, snap.key
end

--- ★★ 次の B を押してよいか（RX3-0229）。★押す前の 1 枚は `run.page_prev` に入っている。
--
--   ① ▼ が**新しく出た**（★前の B のあと中身が変わってから / ⚠ 点滅は 1 枚で決めない → 4 フレームおきに見直す）
--   ② ▼ が出ないまま CLOSE_GAP を過ぎ、画面が PAGE_STABLE 止まった（★最後のページ / 窓が消えたあとの B）
--   ③ ⚠ それでも決まらなければ PAGE_WAIT_MAX で押す（★止まったままにしない）
--   ⚠ 画面が読めなければ今までどおり CLOSE_GAP おき。★press は予約（⚠ 届く前に次を決めない）。
local function close_ready()
  if BUTTONS.busy ~= nil and BUTTONS.busy() then return false end
  if run.waited % PAGE_POLL ~= 0 then return false end
  local nt = read_nt()
  if nt == nil then return run.waited >= CLOSE_GAP end
  local snap = watch_page(nt)
  local key = (snap ~= nil) and snap.key or nt_key(nt)
  if key ~= run.close_key then run.close_key, run.close_still = key, 0
  else run.close_still = (run.close_still or 0) + PAGE_POLL end
  if key ~= run.close_pressed then run.close_armed = true end
  if run.waited < PAGE_MIN_GAP then return false end
  if snap ~= nil and snap.more and run.close_armed then
    run.close_by_more = (run.close_by_more or 0) + 1
    return true
  end
  if run.waited < CLOSE_GAP then return false end
  return run.close_still >= PAGE_STABLE or run.waited >= PAGE_WAIT_MAX
end

local function tick_close(at)
  if run.depart ~= nil then tick_depart(); return end
  if not run.depart_done and depart_at ~= nil and run.talk_frame ~= nil and depart_at >= run.talk_frame then
    -- ★★ 「また たびだつか」の見張りが鳴った → ⚠ B をやめる（★押しかけの B も捨てる）
    --   ⚠ 未確認: 窓が開く瞬間に B を押したままだと取り消し（= いいえ）になるか → ★押さないで待つ
    if BUTTONS.cancel ~= nil then BUTTONS.cancel(ME) end
    run.depart = {waited = 0, moves = 0, cool = DEPART_SETTLE, since = depart_at}
    say(string.format("★★ $BB9D（また たびだつか）を通った（フレーム %d / B は %d 回押した）→ ⚠ B をやめて はい を探す",
        depart_at, run.close_presses or 0))
    return
  end
  -- ★★ はい／いいえ が繰り返し出た（RX3-0273）: B は「いいえ」で、同じことを聞き直す相手は B では抜けられない
  --   → ⚠ B をやめて止め、窓は開いたまま人に返す（★宿屋の問いと Q2 は別の段で答えるので、ここには来ない）
  --   ⚠ 「新しく出た」で数える（★見えている間ずっと数えると、1 回の問いで 3 回に達する）
  --   ⚠ 画面を読むのは `PAGE_POLL`（4 フレーム）ごと（★毎フレーム読まない / 窓は 4 フレームより長く出る）
  if run.waited % PAGE_POLL == 0 then
    local seen = yes_no_window(read_nt()) ~= nil
    if seen and not run.choice_seen then
      run.choices = (run.choices or 0) + 1
      say(string.format("★はい／いいえ の窓が出た（%d 回目 / B %d 回）", run.choices, run.close_presses or 0))
    end
    run.choice_seen = seen
    if (run.choices or 0) >= CHOICE_MAX then
      if BUTTONS.cancel ~= nil then BUTTONS.cancel(ME) end
      finish("choice_repeated", string.format("はい／いいえ が %d 回出た（B %d 回 / ★窓は人に返す）",
          run.choices, run.close_presses or 0))
      return
    end
  end
  run.waited = run.waited + 1          -- ★前の B から（★B を押すたびに 0 へ）
  if not close_ready() then return end
  local n = (run.close_presses or 0) + 1
  -- ★決まった回数を押したあとも、⚠ 窓が**見えていて、しかも画面が動いている**なら
  --   CLOSE_MAX まで続ける。
  --   ⚠⚠ 「窓が見えている」だけで続けると、★立ち止まると出る**パーティの状態の窓**
  --     （B では消えない）で毎回 16 回押していました（2026-09-11 実測 / 1 人 2 秒の遅れ）。
  --   → ★前に見たときから画面が**変わっていない**なら、B はもう効いていない。止める。
  local still = false
  if n > CLOSE_PRESSES and n <= CLOSE_MAX
      and HOST ~= nil and HOST.window_open ~= nil then
    local d = screen_digest()
    still = HOST.window_open() == true and (d == nil or d ~= run.close_digest)
    run.close_digest = d
  end
  if n <= CLOSE_PRESSES or still then
    keep_page(run.page_prev)     -- ★送る前の 1 枚（⚠ 最後のページは B で窓ごと消える）
    press("B", 8)
    run.close_presses = n
    run.close_pressed, run.close_armed, run.waited = run.close_key, false, 0
  else
    if n > CLOSE_PRESSES + 1 then
      say(string.format("★窓が消えるまで B を %d 回押した", run.close_presses or n))
    end
    say(string.format("★会話のページ %d 枚（▼ を見て送った B %d 回）", #run.pages, run.close_by_more or 0))
    run.closed = true          -- ⚠ 「押した」だけ。★閉じたかは画面が窓で見る
    run.phase, run.waited = "after", 0
  end
end

local function frame()
  if HOST ~= nil and HOST.wants ~= nil then
    if HOST.wants("navigate") then
      local req = HOST.last_request or {}
      start(req.params or {}, req.seq)
    end
    if HOST.wants("nav_stop") then
      if run ~= nil then finish("stopped_by_user") end
    end
    -- ★開発用: ゲーム画面を撮る（gui.savescreenshotas / ⚠ 証跡用。params.path に書く）
    if HOST.wants("screenshot") then
      local req = HOST.last_request or {}
      local path = (req.params or {}).path
      if path ~= nil and path ~= "" then
        local ok, err = pcall(function() gui.savescreenshotas(path) end)
        status.screenshot = {path = path, ok = ok, err = ok and nil or tostring(err), frame = emu.framecount()}
        say(string.format("★画面を撮った: %s（%s）", path, ok and "OK" or tostring(err)))
      end
    end
    -- ★開発用: セーブステートを読む（⚠ 実機確認の driver が使う。★読むだけで、書かない）
    if HOST.wants("load_state") then
      local req = HOST.last_request or {}
      local slot = tonumber(((req.params or {}).slot) or "")
      local ok_ai, AI = pcall(dofile, root .. "/dq3/phase0/ai_state.lua")
      if slot ~= nil and ok_ai and type(AI) == "table" and type(AI.load) == "function" then
        if run ~= nil then finish("replaced") end
        local ok, why = AI.load(slot)
        say(string.format("★セーブ %d を読み込み: %s", slot, ok and "OK" or tostring(why)))
        -- ★高速化などを残さない（RX3-0166 / ⚠ 中身は dev.lua の HOST.loaded）
        if HOST.loaded ~= nil then HOST.loaded(slot) end
        -- ★seq と理由も出す（RX3-0486 / ★パッドの LB の結果を画面が番号で突き合わせる）
        status.loaded = {slot = slot, ok = ok, frame = emu.framecount(), seq = req.seq,
                         why = (not ok) and tostring(why) or nil}
      end
    end
  end
  if run == nil then return end
  -- ★遭遇したら止まる（★ENTERING から / RX3-0166）
  if Battle.in_encounter() then finish("battle"); return end
  local at = where()
  if at == nil then return end
  if not is_local(at.kind) or at.map_id ~= run.start_map then finish("map_changed"); return end
  if run.phase == "clear" then tick_clear(at)
  elseif run.phase == "walk" then tick_walk(at)
  elseif run.phase == "wait_npc" then tick_wait_npc(at)
  elseif run.phase == "face" then tick_face(at)
  elseif run.phase == "talk" then tick_talk(at)
  elseif run.phase == "close" then tick_close(at)
  elseif run.phase == "inn" then tick_inn()
  elseif run.phase == "after" then
    finish(run.talk and "talk_done" or "arrived")
    return
  end
  publish()
end

local function on_exit()
  if run ~= nil then finish("exit") end
  pcall(function() logfile:close() end)
end

if HOST ~= nil and HOST.features ~= nil then
  HOST.features[#HOST.features + 1] = {name = ME, frame = frame, on_exit = on_exit}
end

return {frame = frame, start = start, status = status, _bfs = bfs, _load_grid = load_grid}
