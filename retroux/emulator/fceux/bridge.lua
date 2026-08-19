-- RetroUX / FCEUX ブリッジ本体（MVP1: DQ2 通常戦闘の自動倍速）
--
-- このファイルはモジュール。無限ループは持たない。
--   本番の入口     : retroux/emulator/fceux/run.lua
--   開発用の駆動   : scripts/dev_autowalk.lua（自動で歩いて戦闘を起こす）
-- 1フレーム分の処理は Bridge:step() に閉じてあり、外から駆動できる。
--
-- 責務分割（D-1 / DEV-1）:
--   リアルタイム判断（戦闘検知・倍速ON/OFF・自動入力）はこの Lua に閉じる。
--   Python は SQLite 記録と GUI 表示に徹する。
--   これにより Python が落ちてもゲームは正常動作し、ログだけが欠落する。
--
-- IPC（D-3 / DEV-3）:
--   Lua -> Python : work/events.jsonl へ JSON Lines を追記
--   Python -> Lua : work/command.json を N フレームごとにポーリング
--
-- 実装上の注意（docs/50-playbook.md）:
--   - emu.frameadvance() は pcall の内側で呼べない
--   - gui.savescreenshotas() の書き出しは次フレームに遅延する

local Bridge = {}
Bridge.__index = Bridge

--- 画面へ渡した要求を、何フレーム待ったら諦めるか（2026-08-01 / 課題 #56）。
--
-- ★60フレーム＝約1秒。画面は 200ms ごとに見ているので、5回ぶんの余裕がある。
-- ⚠ 短すぎると連打の守りにならず、長すぎると画面が落ちたとき操作できない。
Bridge.GUI_ACTION_TIMEOUT_FRAMES = 60

-- 戦闘中のメニューID（memory_map.yaml の menu_layouts と対応。判定にだけ使う）。
-- ★戦闘コマンド(0x09)は config から取れるのでここには置かない。
-- 画面表示の位置（NES の画面は 256x240）。
-- ★上端ぴったりだと文字が見切れる（依頼者の指摘）。少し下げてある。
local OVERLAY_LEFT = 4
local OVERLAY_TOP  = 10
local OVERLAY_STEP = 9    -- 1行ぶん

-- ★パーティを読めないときの理由（dq2.lua の is_danger が返す文字列と揃える）。
--   タイトル画面など、まだセーブを読み込んでいない場面で出る。
local UNREADABLE_PARTY = "パーティ状態を読めない"

local SPELL_LIST_MENU   = 0x07   -- 戦闘中の呪文リスト（★2列メニュー）
local ENEMY_TARGET_MENU = 0x0A   -- 敵の対象選択
local ALLY_TARGET_MENU  = 0x0B   -- 味方の対象選択（回復・補助を決めた直後）

----------------------------------------------------------------------
-- パス解決とモジュール読み込み
----------------------------------------------------------------------

function Bridge.resolve_root()
  local root = os.getenv("RETROUX_ROOT")
  if root == nil or root == "" then
    root = "F:/Projects/260721_RetroUX"
  end
  return (root:gsub("\\", "/"):gsub("/$", ""))
end

--- ★★★ **書き込み先だけを別にする**（2026-08-13 / 製品版ログ整理 Phase 2）★★★
---
--- ## ⚠⚠ なぜ要るか
---
---   検査（`research/probes/`）は実 Lua で `Bridge.new` を呼ぶ。そのとき
---   **本物の `work/events.jsonl` と `work/retroux.log` へ追記していた**。
---
---     実測: `pytest tests/test_lua_harnesses_actually_run.py`（19件）だけで
---           events.jsonl +1,251 バイト / retroux.log +5,883 バイト
---
---   ⚠ `events.jsonl` は `recorder` が SQLite へ取り込む。
---     つまり**検査の記録が製品の DB に入っていた**（`session_start` 2,847 件の
---     大半、同一秒に最大 13 件）。
---   ⚠ さらに「ログが多い」の分母が汚れるので、**削減の Before/After を
---     正直に測れない**。
---
--- ## ★ 読み込み元（root）とは分ける
---
---   ⚠ `root` ごと差し替えると `work/generated/memory_map.lua` が読めなくなる
---     （生成物は本物の場所にしか無い）。★**書く先だけ**を切り替える。
---
---   未設定なら `root` と同じ。**つまり実機の動きは何も変わらない。**
function Bridge.resolve_write_root(fallback)
  local root = os.getenv("RETROUX_WRITE_ROOT")
  if root == nil or root == "" then
    return fallback
  end
  return (root:gsub("\\", "/"):gsub("/$", ""))
end

local function load_module(root, rel)
  local chunk, err = loadfile(root .. "/" .. rel)
  if chunk == nil then
    error("読み込めません: " .. rel .. " (" .. tostring(err) .. ")\n"
       .. "RETROUX_ROOT が正しいか、generate_lua.py を実行済みか確認してください。")
  end
  return chunk()
end

----------------------------------------------------------------------
-- JSON 出力（Lua に JSON ライブラリがないため最小限の実装）
----------------------------------------------------------------------

local function json_escape(s)
  return (tostring(s):gsub('[\\"]', "\\%0"):gsub("\n", "\\n"))
end

local function json_value(v)
  if v == nil then return "null" end
  if type(v) == "number"  then return tostring(v) end
  if type(v) == "boolean" then return v and "true" or "false" end
  if type(v) == "table" then
    -- ★★★ **配列と連想配列を見分ける**（2026-08-08 に踏んだ）★★★
    --
    --   ⚠⚠ 以前は `ipairs` だけで回していたので、
    --     `{ id = "samaltria", hp = 40 }` のような**キー付きのテーブルが
    --     `[]` に潰れていました**。
    --
    --   ★実機の判断の記録がこうなっていました:
    --       "party": [[],[],[]]   ← ⚠ 3人ぶん**全部が空**
    --
    --   ⚠ 出ていたので「動いている」と見えましたが、**中身がありません**でした。
    --     ★「出た／出ない」だけでなく**中身を見る**こと。
    local n = 0
    for _ in pairs(v) do n = n + 1 end
    if n == #v then
      -- ★1..n が詰まっている ＝ 配列（⚠ 空のときもこちら）
      local parts = {}
      for i, x in ipairs(v) do parts[i] = json_value(x) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, x in pairs(v) do
      parts[#parts + 1] =
        '"' .. json_escape(tostring(k)) .. '":' .. json_value(x)
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return '"' .. json_escape(v) .. '"'
end

--- ★検査から呼べるようにしておく（⚠ `Bridge.new` はファイルを開くので、
---   人が遊んでいる最中に動かせません。★ここだけなら安全に試せます）。
Bridge.json_value = json_value

--- ★ロード直後に地図の材料採取を止めるフレーム数（2026-08-11）。
--   ⚠ Pボタン等のロードで画面が暗転し、その暗い画面を「見た地形」として
--     記録すると**世界地図が黒塗り**になる（依頼者の指摘）。★暗転と再描画
--     （フェードイン）が済むまでの目安。倍速でも frame 単位なので同じだけ待つ。
local MAP_LOAD_SKIP_FRAMES = 30

----------------------------------------------------------------------
-- 生成
----------------------------------------------------------------------

function Bridge.new(opts)
  opts = opts or {}
  local self = setmetatable({}, Bridge)

  self.root       = opts.root or Bridge.resolve_root()
  -- ★書く先だけ別にできる（`Bridge.resolve_write_root` の説明を参照）。
  --   ⚠ 未設定なら `root` と同じ。実機の動きは変わらない。
  self.write_root = opts.write_root or Bridge.resolve_write_root(self.root)
  self.memory_map = load_module(self.root, "work/generated/memory_map.lua")
  self.config     = load_module(self.root, "work/generated/config.lua")
  local Throttle  = load_module(self.root, "retroux/emulator/fceux/throttle.lua")
  local DQ2       = load_module(self.root, "retroux/plugins/dq2/dq2.lua")

  -- ★ログの下限は**一番先に**決める（⚠ 下の初期化がもう self:log を呼ぶ）
  self.log_min_rank = Bridge.resolve_log_min((self.config.logging or {}).mode)

  self.game = DQ2.new(self.memory_map, self.config)
  -- スロットルの安全弁が作動したらログとイベントに残す。
  -- 黙って遅くなると原因を追えないため。
  self.throttle = Throttle.new({
    mode = (self.config.speed or {}).mode or "turbo",
    on_guard = function(message)
      self:log("[スロットル] " .. message)
      self:emit("throttle_guard", { message = message })
    end,
  })

  -- ★★ 追記していく2本だけ `write_root` を使う（2026-08-13）★★
  --   ⚠ 検査が本物の記録を汚していたのはこの2本だけ（実測で確認）。
  --     他（command.json / encountered.txt / caution.txt）は Python と
  --     やり取りする窓口なので、**本物の場所のまま**にする。
  self.events_path      = self.write_root .. "/" .. self.config.logging.events_path
  self.command_path     = self.root .. "/" .. self.config.logging.command_path
  self.encountered_path = self.root .. "/work/encountered.txt"
  -- ★ゲームパッドの NES ボタン状態（RetroUX が毎フレーム書く / RX-0076）。
  --   `<seq> <mask>` の1行。⚠ seq が止まったら RetroUX 停止とみなし解除する。
  self.gamepad_input_path = self.root .. "/work/gamepad_input.txt"
  self.gamepad_last_seq   = nil
  self.gamepad_stale      = 0
  self.gamepad_mask       = 0
  self.log_path         = self.write_root .. "/work/retroux.log"
  -- ★「いまの状態」は events.jsonl へ書かない（MVP2 Phase 2）。
  --   events.jsonl は**起きたこと**の記録で、そのまま DB に入る。
  --   毎秒の HP/MP をそこへ流すと、記録が現在値で埋まって意味が変わるうえ、
  --   ファイルも DB も肥大化する。**現在値は別のファイルに、上書きで**置く。
  self.state_path       = self.root .. "/work/state.json"
  -- FCEUX の Lua コンソールは UTF-8 を扱えず日本語が文字化けする。
  -- 読ませたい内容（特に安全に関わる警告）はこのログファイルへ UTF-8 で書き、
  -- コンソールには英数字だけの短い案内を出す。
  --
  -- ★ログはハンドルを持たない（Bridge:log を参照）。
  --   Python 側がローテーションするため、開きっぱなしにできない。

  -- ★_load_encountered_cache が壊れた行を警告として積むため、先に用意する
  self.warnings = {}

  -- ★★ events もハンドルを持たない（2026-08-13 / §25）★★
  --   ⚠ 持ったままだと Python 側の世代交代で**静かに壊れる**
  --     （`Bridge:emit` の説明を参照。ログで既に踏んだのと同じ形）。
  --   ★置き場が作られているかだけ、ここで確かめておく。
  local probe = io.open(self.events_path, "a")
  if probe then
    probe:close()
  else
    self.warnings[#self.warnings + 1] = {
      code = "events_unwritable",
      message = "イベントの記録先を開けません: " .. tostring(self.events_path)
             .. "（★戦闘の記録が残りません）",
    }
  end

  -- ★★★ セッション識別子（2026-08-13 / §7・§27）★★★
  --
  --   ⚠ `decision_id` に入れて、**セッションをまたいだ衝突**を防ぐ。
  --     実測で 3,497 件に対しユニーク 833 個しかなかった。
  --
  --   ★作り方: 起動時刻（秒）＋ 乱数。
  --     ⚠ **秒だけでは足りない**。実測で `session_start` が
  --       **同じ秒に最大 13 件**あった（検査が実 Lua を並べて起動するため）。
  --     ★`os.time()` は秒までしか無いので、乱数で埋める。
  --   ⚠ 乱数の種は時刻。★同じ秒に始まっても、`os.clock()` を混ぜてずらす。
  --
  --   ⚠⚠ **同じプロセスで2つ作ると乱数も同じ**になる（検査で実際に起きた）。
  --     ★連番（`Bridge._session_seq`）も混ぜて、確実に分ける。
  math.randomseed(os.time() + math.floor((os.clock() or 0) * 1000000))
  Bridge._session_seq = (Bridge._session_seq or 0) + 1
  self.session_id = string.format("%x%04x%02x", os.time(),
                                  math.random(0, 0xFFFF),
                                  Bridge._session_seq % 256)

  -- 遭遇済みモンスター。正は Python 側の SQLite だが、
  -- Python が動いていなくても単体で機能するようファイルにも残す。
  -- ★command.json で渡された集合は**合併**する（上書きしない）。
  --   Python 側は events.jsonl の取り込み待ちで常に遅れうるため、
  --   上書きすると Lua が登録した分が消え、同じモンスターが何度も
  --   「初遭遇」になって自動入力が無効化され続ける。_poll_command のコメント参照。
  self.encountered = {}
  self:_load_encountered_cache()

  -- 警戒リスト（逃げた/負けた相手）。詳細は _load_caution_cache のコメント。
  self.caution_path = self.root .. "/work/caution.txt"
  self.caution = {}
  self:_load_caution_cache()
  -- レベルアップの検出用。★警戒リストの解除条件（config の caution）
  self.caution_cfg = self.config.caution or {}
  self.levels = nil          -- 最初の戦闘終了時に基準を取る

  self.state = {
    in_battle       = false,
    battle_started  = 0,
    enemy_ids       = {},
    first_encounter = false,
    is_boss         = false,
    is_caution      = false,
    saw_victory     = false,
    manual_latched  = false,
    danger          = false,
  }

  self.command_poll_interval = 30
  self.last_poll = 0

  -- 単発の操作要求（まんたん等）。command.json から受け取る。
  -- ブリッジは要求を**受け取るだけ**で実行しない。実行は入口（run.lua）が行う。
  -- 同じ要求を毎ポーリングで繰り返さないよう request_id で重複を排除する。
  self.pending_action = nil
  self.last_action_id = nil
  -- ★★ 速度の担当（2026-08-01 のリファクタ §4.2）★★
  --   `turbo_enabled` と現在倍率と演出等速は**この人が持つ**。
  --   ⚠ bridge は自分で持たない（同じ状態を2か所で代入しない / §4.4）。
  self.speed = load_module(
    self.root, "retroux/emulator/fceux/speed_controller.lua").new(
    self.config, function(msg, notice, level) self:log(msg, notice, level) end)
  -- まんたんの回復目標モード（config の mantan.mode を command.json で上書き可能）。
  -- ★GUI から切り替えるための受け口。GUI 実装時は書き込むだけで済む。
  self.mantan_mode = nil

  -- ホットキー（キーボード）。ゲームパッドではなくキーボードで受けるのは、
  -- ブリッジが joypad.set を握っているためゲームパッド側の読みが混ざるから。
  -- input.get() でキー名が true になる（実測 work/input_api_probe.txt）。
  -- ⚠ numlock のようなロック状態も true で入る。**押した瞬間だけ**を見る。
  self.hotkeys = self:_load_hotkeys()
  self.hotkey_prev = {}
  -- ★画面へ渡した要求が、何フレーム返事待ちか（2026-08-01 / 課題 #56）。
  --   ⚠ 画面が落ちていても永久に詰まらないよう、時間で諦める。
  self.gui_action_frames = 0
  -- ★★ AUTO（AIに操作を任せるか）。**速度とは別の軸**（2026-07-31 の指示書 §2）★★
  --
  --   | 軸 | 状態 | 変える人 |
  --   | --- | --- | --- |
  --   | **誰が操作するか** | `auto_enabled` | キーボード A / 画面の AUTO |
  --   | **どの速度で動かすか** | `turbo_enabled` | 画面の高速化 |
  --
  --   ⚠⚠ **片方を変えても、もう片方は変えない**（指示書の不変条件）。
  --     以前は A キーが両方を変えていたため、
  --     「等速で AUTO」「高速化を保ったまま手動へ」が選べなかった。
  --
  --   ★★ AUTO の担当（2026-08-01 のリファクタ §4.2）★★
  --     `auto_enabled` / `force_auto` / `manual_latched` は**この人が持つ**。
  self.battle = load_module(
    self.root, "retroux/emulator/fceux/battle_controller.lua").new(
    self.config, function(msg, notice, level) self:log(msg, notice, level) end)

  -- ★★ command.json の読み手（同 §4.2）★★
  --   最後に処理した `request_id` は**この人が持つ**。
  --   ⚠ `require` ではなく `loadfile`（= `load_module`）を使う。実測で
  --     FCEUX でも動くことを確かめた（`research/probes/reusable/module_probe_fceux.lua`）。
  --     `require` は `package.path` の書き換えが要り、他へ影響する。
  self.commands = load_module(
    self.root, "retroux/emulator/fceux/command_reader.lua").new(
    self.command_path, function(msg, notice, level) self:log(msg, notice, level) end)
  -- 画面に数秒だけ出す短い通知。
  -- ★ホットキーの結果がログとコンソールにしか出ておらず、
  --   利用者から見ると「押しても何も起きない」ように見えていた。
  --   gui.text は日本語を出せないため英数字のみ。詳細はログを見てもらう。
  self.notice = nil
  self.notice_left = 0
  -- 自動操作の実行中だけ倍率が入る。nil なら通常の判定に従う。
  -- 設定するのは action_driver。★終了時に必ず nil へ戻すこと。
  self.action_multiplier = nil

  -- 自動入力の順序機械。
  --
  -- 単純な「A を一定周期で押す」では戦闘が終わらなかった（B-7）。
  -- 解析用スクリプト collect7 では61戦闘が正常完了しており、
  -- そちらは A を押した後にフェーズが残っていれば B も押していた。
  -- そのパターンを移植する。
  --
  --   a_hold -> a_gap -> (フェーズが残っていれば b_hold -> b_gap) -> a_hold ...
  --
  -- 1フレームだけの入力は取りこぼされるため hold は複数フレーム必要。
  local ai = self.config.auto_input or {}
  self.input_state  = "a_hold"
  self.input_left   = 0
  self.input_frames = {
    a_hold = ai.a_hold_frames or 5,
    a_gap  = ai.a_gap_frames  or 16,
    b_hold = ai.b_hold_frames or 4,
    b_gap  = ai.b_gap_frames  or 8,
  }

  -- ★勝利メッセージ中は押下を短く・間隔を長くする。
  --
  -- 実機ログ（work/postbattle/real.txt）で判明した問題:
  --   勝利メッセージを閉じた A が離される前にフィールドで読まれ、
  --   コマンドメニューが開いていた。戦闘終了の2フレーム後に必ず開く。
  --   a_hold=5 のため、メッセージを閉じた後も最大4フレーム A が残る。
  -- 短く押せば、フィールドに戻った時点では既に離れている。
  self.victory_frames = {
    a_hold = ai.victory_a_hold_frames or 2,
    a_gap  = ai.victory_a_gap_frames  or 24,
  }
  -- 勝利メッセージを送るボタン。既定 B（理由は _claim_battle_input のコメント）。
  self.victory_button = ai.victory_button or "B"
  self.was_victory = false

  -- 戦闘終了直後に全ボタンを明示的に離す期間（フレーム）。
  -- 何も送らない（joypad.set を呼ばない）とプレイヤーの入力に戻せるが、
  -- 直前の押下が残っているかどうかを制御できない。
  -- ここだけは明示的に「全部離す」を送って断ち切る。
  self.release_frames_after_battle = ai.release_frames_after_battle or 8
  self.release_left = 0

  -- AI操作OFF の人の番が回ってきた直後、全ボタンを離す期間（フレーム）。
  -- ★この期間が終わったら **joypad.set を呼ぶのをやめる**（人が押せる）。
  --   ⚠ 0 にしないこと。直前まで AI が押していたボタンが1フレーム残る。
  --   ⚠ 長くしないこと。その間は人が押しても効かない（実機 T-5 の症状）。
  self.manual_release_frames = ai.manual_release_frames or 8
  self.manual_release_left = 0

  -- 戦闘直後にフィールドメニューが開いた場合の後始末を試みる期間（フレーム）。
  -- ⚠ 90 では足りなかった（実機ログで期限切れ後に方向キーが吸われ続けた）。
  -- この期間はメニューが開いている間だけ消費されるので、長めでも
  -- プレイヤーの操作を邪魔する時間が増えるわけではない。
  self.menu_cleanup_frames = ai.menu_cleanup_frames or 600
  self.menu_cleanup_left   = 0
  self.menu_cleanup_tick   = 0
  -- 戦闘終了から何フレーム以内に開いたメニューを「誤爆」とみなすか。
  -- 自動入力の最後の A 押下による誤爆は直後に起きるため短くてよい。
  -- 長くするとプレイヤーが自分で開いたメニューを閉じてしまう。
  self.menu_cleanup_detect_frames = ai.menu_cleanup_detect_frames or 45
  self.menu_cleanup_active = false
  self.frames_since_battle = 1e9

  -- 倒す順の優先指定（作戦）。敵選択メニューでカーソルを寄せる。
  self.target_priority = ai.target_priority or {}
  self.target_menu = ai.target_menu            -- nil のあいだは行数の一致で判定
  self.target_seek_hold = ai.target_seek_hold or 6
  self.target_seek_gap = ai.target_seek_gap or 12
  self.target_seek_left = 0
  self.target_seek_button = nil

  -- ★★ 無駄撃ちを避ける（2026-07-31 / 依頼者の要望）★★
  --   > 攻撃のときに、敵モンスターの残りHPを予測して、無駄な攻撃をしない
  --   ⚠ `overkill_margin` は**安全側へ倒す係数**。
  --     1.0 = 目安どおり（依頼者の指定 / 無駄は最小だが、たまに倒しきれない）
  --     1.2〜1.5 = 少し多めに殴る（取りこぼしにくいが無駄が残る）
  self.overkill_avoid = ai.overkill_avoid ~= false
  self.overkill_margin = ai.overkill_margin or 1.0
  self.overkill_booked = {}
  self.overkill_hp_total = nil
  -- ★演出のための等速復帰は `speed_controller` が持つ（リファクタ §4.4）。
  self.speed_events = self.config.speed_events or {}
  self.speed_levels = nil
  self.speed_alive = nil

  -- 戦闘中に使う道具（杖）。詳細は _claim_battle_item のコメント。
  local bi = ai.battle_items or {}
  self.battle_item_enabled = bi.enabled ~= false
  self.battle_item_list = bi.items or {}
  self.battle_item_max = bi.max_uses_per_battle or 12
  self.bi_hold = bi.seek_hold or 6
  self.bi_gap = bi.seek_gap or 12
  self.bi_settle_frames = bi.settle_frames or 20
  self.bi_left, self.bi_button = 0, nil
  self.bi_member, self.bi_tried, self.bi_uses = nil, false, 0
  self.bi_settle = nil
  -- ★★ 道具を使う条件（2026-08-01 / 課題 #62）★★
  --   ⚠ 判定は別ファイル。RAM を知らないので、画面も実機も無しで試せる。
  self.item_conditions = load_module(
    self.root, "retroux/emulator/fceux/item_conditions.lua")
  -- ★★ 攻撃呪文（2026-08-03 / 「ガンガン行こうぜ」）★★
  --   ⚠ どれも RAM を知らない。画面も実機も無しで試せる。
  self.damage_estimate = load_module(
    self.root, "retroux/emulator/fceux/damage_estimate.lua")
  self.attack_candidates = load_module(
    self.root, "retroux/emulator/fceux/attack_candidates.lua")
  self.attack_plan = load_module(
    self.root, "retroux/emulator/fceux/attack_plan.lua")
  if self.attack_plan ~= nil and self.damage_estimate ~= nil then
    self.attack_plan.use(self.damage_estimate)
  end
  -- ⚠⚠ **道具にも同じ規則を差す**（2026-08-07）。★杖は呪文と同じ効果
  --   なのに、耐性を見ていませんでした（★「片側だけ」の状態）。
  if self.item_conditions ~= nil and self.damage_estimate ~= nil
    and self.item_conditions.use ~= nil then
    self.item_conditions.use(self.damage_estimate)
  end
  -- ★★ 三層構造の受け皿（2026-08-04 / 戦闘AI再設計 Phase 1）★★
  --   ⚠ ここも RAM を知らない。画面も実機も無しで試せる。
  --   ★Phase 1 では**受け皿があるだけ**で、判断はまだ legacy のままです。
  self.battle_types = load_module(
    self.root, "retroux/emulator/fceux/battle_types.lua")
  self.battle_engine = self:_resolve_engine(ai.engine)
  -- ★★ 責務別のモジュール（Phase 2）★★
  --   ⚠ どれも RAM を知らない。**答えは変えていません**
  --     （`battle_ai_baseline_test.lua` の14項目が見張っています）。
  self.actor_decision = load_module(
    self.root, "retroux/emulator/fceux/actor_decision.lua")
  self.tactics_commander = load_module(
    self.root, "retroux/emulator/fceux/tactics_commander.lua")
  self.battle_assessment = load_module(
    self.root, "retroux/emulator/fceux/battle_assessment.lua")
  -- ★★ 戦術の自動選択（2026-08-06 / Phase 5）★★
  --   ⚠⚠ **選ぶだけで、判断は変えません。** `engine: legacy` のままなら
  --     これまでどおりです（★効かせるのは layered のときだけ）。
  self.tactics_selector = load_module(
    self.root, "retroux/emulator/fceux/tactics_selector.lua")
  --: いま採っている戦術（★振動よけに使う / §10 IT-007）
  self.current_plan = nil
  -- ★★ 個人の役割と貢献（2026-08-07 / Phase 6）★★
  --   ⚠⚠ **候補を出すだけで、判断は変えません。**
  --   ★役割は名前ではなく**できること**（MP・攻撃力・覚えた呪文）
  --     から組み立てます。
  self.actor_roles = load_module(
    self.root, "retroux/emulator/fceux/actor_roles.lua")
  -- ★★ 補助行動の評価（2026-08-08 / Phase 7・8）★★
  --   ⚠⚠ **候補を出すだけで、まだ効かせていません**（★Phase 5・6 と同じ段）。
  --   ★ルカナン・スクルト・マヌーサ・ラリホー・ザキ・マホトーンを
  --     「推計ターンが何ターン縮む／延びるか」で評価します。
  self.support_plan = load_module(
    self.root, "retroux/emulator/fceux/support_plan.lua")
  self.support_config = ai.support or {}
  local Coordinator = load_module(
    self.root, "retroux/emulator/fceux/party_coordinator.lua")
  if Coordinator ~= nil and self.battle_types ~= nil then
    self.party_coordinator = Coordinator.new(self.battle_types)
  end

  -- ★設定。⚠ **既定は無効**（設定しなければこれまでと同じ挙動）
  self.attack_spell_config = ai.attack_spells or {}
  self:_reset_battle_attack()
  --: この戦闘で何回使ったか（`once_per_battle` の判定に使う）
  self.bi_used_ids = {}
  --: 見送った理由。★同じ理由を何度も書かないための控え
  self.bi_skip_notes = {}
  -- ★直近に出した「誰が・どの道具を・どの位置で」の組み合わせ（下の説明を参照）
  self.bi_logged = nil

  -- 行動単位ログ（MVP2 Phase 3）
  self.battle_log = self.config.battle_log or {}
  self.turn_no, self.turn_seq, self.log_count = 0, 0, 0
  self.log_prev, self.saw_command_menu = nil, false

  -- 戦闘中の回復呪文（P3）。詳細は _claim_battle_heal のコメント。
  local heal = ai.heal or {}
  self.heal_enabled = heal.enabled ~= false
  -- 使う回復呪文（優先順）。**呪文ID**で書く。行番号は書かない（計算する）。
  self.heal_spells = heal.spells or { { id = 0x09, name = "ホイミ" } }
  -- 回復を始めるHPの割合。危険状態(0.25)より手前で動く必要がある（仕様4章）
  self.heal_threshold = heal.threshold or 0.5
  self.heal_max = heal.max_uses_per_battle or 8
  -- 1人1ターンで押してよい回数の上限（進まないときの歯止め）。
  -- 内訳の目安: コマンドで最大3回 + 呪文リストで列1・行3 + 対象で3 + 決定2。
  self.heal_max_presses = heal.max_presses_per_turn or 16
  -- 効いたかを見張るフレーム数。★ターンは全員の入力が済んでから解決するので
  -- 短いと必ず「確認できなかった」になる（7人の敵が居る戦闘を見込んで長めに取る）。
  self.heal_watch_frames = heal.watch_frames or 1200
  -- MPが減ってから**HPが動くまで**の待ち。唱えた後のメッセージ送りぶん。
  self.heal_hp_watch_frames = heal.hp_watch_frames or 600
  self.bh_watch = nil
  self.bh_hold = heal.seek_hold or 6
  self.bh_gap = heal.seek_gap or 12
  self.bh_settle_frames = heal.settle_frames or 20
  self.bh_uses = 0
  self.bh_logged = false
  self:_reset_battle_heal()

  -- --- キャラクター別戦術プロフィール（2026-07-30 / 仕様書 15章）---------
  --
  -- ★★ **利用者が設計した戦術をそのまま実行する。** ★★
  --   AI が勝手に方針を変えたり最適化したりしない（仕様書 2.1）。
  --
  -- ⚠ **プロフィールが無ければ、これまでとまったく同じ挙動**にする。
  --   下の `_tactic_*` は「見つからなければ config の値」を返す形にしてある。
  --   「入れたら壊れた」を起こさないための線（仕様書 2.4）。
  --
  -- ★反映は**次のターンから**（仕様書 15.3 の推奨）。
  --   戦闘の途中で入れ替わると、同じターンの前半と後半が別の戦術で動く。
  --   その挙動は説明できない。
  self.tactics = nil            -- いま効いている表（ターン中は固定）
  self.tactics_revision = nil   -- 効いている表の版
  self.tactics_pending = nil    -- 読み直したがまだ効かせていない表
  self.tactics_wanted = nil     -- command.json が言ってきた版
  -- ★「AI操作OFF」を知らせた相手。同じ人の番で毎フレーム出さないため
  self.manual_notice = nil
  -- 代替行動（防御など）の入力の状態。★誰の番かで作り直す
  self.fb_member, self.fb_presses, self.fb_tried = nil, 0, false
  self.fb_left, self.fb_button = 0, nil
  self.tactics = self:_load_tactics()
  if self.tactics ~= nil then
    self.tactics_revision = self.tactics.revision
    self:log(string.format("戦術プロフィール: %s（効くのはフェーズ %s）",
      tostring(self.tactics.profile_name),
      table.concat(self.tactics._phases or {}, "・")),
      "tactics: " .. tostring(self.tactics.profile_id), "DEBUG")
  end

  -- モンスターの絵を画面から撮る（詳細は _arm_monster_art のコメント）
  self.monster_art = self.config.monster_art or {}
  -- ★研究用の採取（§22）。⚠ 既定は切。`research.capture: true` で入る
  self.research = self.config.research or {}
  self.art_pending = nil
  -- ★この起動で絵が用意できた敵。二度撮りを防ぐ。
  --   ⚠ 切り出しは Python が0.5秒ごとに回すので、撮った直後は
  --     まだファイルが無い。その隙間をこれで埋める。
  self.art_done = {}

  -- 遷移タイルの写真（マッパー仕様 フェーズ4）。人が頼んだときだけ動く。
  -- ★自動では撮れない（気づいたときには画面が次のマップに変わっている）。
  self.tile_shot = nil

  -- --- 行動の優先順（Phase 6 P5 / 依頼者の項目1・7）--------------------
  --
  -- ★設定の名前を**起動時に1度だけ**関数へ解決する。
  --   毎フレーム文字列を照合すると、知らない名前を毎フレーム警告することになる
  --   （「毎回出る通知は読まれない通知」/ playbook #4）。
  --
  -- ⚠ 知らない名前は**飛ばして警告し、残りはそのまま使う**。
  --   設定を丸ごと捨てて既定に戻すと、直したつもりの並びが黙って無視される
  --   （playbook #45「設定を変えたのに何も変わらない」と同じ形）。
  self.battle_priority = self:_resolve_battle_priority(ai.priority)

  self.target_menu_logged = false
  self.target_lock_logged = false
  -- ⚠ 戦闘ごとに戻す。★戻さないと2戦目以降ずっと黙ります。
  self.aim_skip_logged = false
  -- 敵選択メニューに入った直後、行数($0081)が前のメニューのままのことがある。
  -- その間は**何も押さない**で落ち着くのを待つ（下の _claim_target_selection 参照）。
  self.target_settle_frames = ai.target_settle_frames or 20
  self.target_settle = nil
  -- この敵選択画面での寄せが済んだか。メニューを離れるまで再度寄せない。
  self.target_done = false

  -- ★★ ロード直後は地図の材料採取を止める（2026-08-11 / 依頼者の指摘）★★
  --   Pボタン等でセーブステートをロードすると画面が暗転し、その暗い画面を
  --   「見た地形」として記録して**世界地図が黒塗り**になっていた。
  --   ⚠ ロードは savestate.registerload で拾う。★落ちても本体は止めない。
  self.map_load_until_frame = nil
  if savestate ~= nil and savestate.registerload ~= nil then
    pcall(function()
      savestate.registerload(function()
        if emu ~= nil and emu.framecount ~= nil then
          self.map_load_until_frame = emu.framecount() + MAP_LOAD_SKIP_FRAMES
        end
      end)
    end)
  end

  self:_startup_checks()
  self:_install_exit_guard()
  return self
end

-- ★重要: スクリプトが停止したときに必ず等速へ戻す。
--
-- emu.speedmode("maximum") は FCEUX 側の状態であり、Lua スクリプトが
-- 止まっても解除されない。倍速中に Stop を押したりスクリプトが落ちると、
-- **FCEUX が最高速のまま残りプレイ不能になる**（実機で発生。
-- 画面に EMULATION SPEED 6400% と表示され操作を受け付けなくなった）。
--
-- emu.registerexit はスクリプト停止時に呼ばれるので、ここで後始末する。
function Bridge:_install_exit_guard()
  if emu == nil or emu.registerexit == nil then return end
  emu.registerexit(function()
    emu.speedmode("normal")
    self:log("スクリプト終了: エミュレータ速度を等速へ戻しました")
    -- ★events はハンドルを持たなくなったので閉じるものが無い（2026-08-13 / §25）。
    --   ⚠ 書き込みを止めたいので、行き先だけ消す。
    self.events_path = nil
  end)
end

----------------------------------------------------------------------
-- 内部
----------------------------------------------------------------------

-- 人間に読ませるメッセージ。日本語はログファイルへ、コンソールへは英数字のみ。
-- FCEUX のコンソールは UTF-8 非対応で、日本語を print すると文字化けして読めない。
-- ★★ 書くたびに開き直す（開いたままにしない）★★
--
--   Python 側（core/logging_setup.py）が同じ work/retroux.log を
--   **ローテーション**する。ハンドルを持ったままだと:
--     ・Windows では Python の rename が失敗しうる
--     ・成功しても、こちらは**名前が変わった側**に書き続ける
--       （＝新しいログに何も出なくなる。しかもエラーは起きないので気づけない）
--
--   開き直す代償はごく小さい。ここが呼ばれるのは戦闘ごとに数回で、
--   毎フレームではない（フレーム単位の記録は events.jsonl 側）。
--- ★★★ **段階（レベル）を持つ**（2026-08-13 / 製品版ログ整理 Phase 2）★★★
---
--- ## ⚠⚠ なぜ要るか
---
---   `work/retroux.log` の **63%（実測 33,578 行）がこちら側**で、
---   ⚠ **段階を1つも持っていなかった**。
---   そのため Python 側で `logging.level: INFO` にしても、
---   **6割の行は出続けた**（＝指示書 §3 の方針が成立していなかった）。
---
--- ## ★ 呼び出し側を壊さない
---
---   ⚠ `self:log(...)` は 115 箇所ある。★**第3引数を足すだけ**にして、
---     省略時は INFO とする。既存の呼び出しは1つも直さなくても動く。
---     段階を下げたい所だけ `self:log(..., "DEBUG")` へ書き換える。
Bridge.LEVELS = { DEBUG = 10, INFO = 20, WARNING = 30, ERROR = 40 }

--- 出す下限を決める（指示書 §19 の 2 モード）。
---
---   normal      … INFO 以上（§20）
---   diagnostic  … DEBUG 以上（§21）
---
--- ⚠ 綴り違いで落とさない。★読めない値は normal 扱い（静かなほうへ倒す）。
function Bridge.resolve_log_min(mode)
  if tostring(mode):lower() == "diagnostic" then
    return Bridge.LEVELS.DEBUG
  end
  return Bridge.LEVELS.INFO
end

--- ★★ ログへ出すパスを短くする（2026-08-13 / 製品版ログ整理 §26）★★
---
--- ## ⚠⚠ なぜ要るか
---
---   ログは GitHub の Issue などへ貼られる前提。⚠ 絶対パスを出すと
---   **利用者名が混ざる**（`C:\Users\<名前>\...` に置いた場合）。
---
---   ⚠ この開発環境では `C:\projects\` にあるため名前が出ておらず、
---     **grep だけでは危険が見えない**（実測 0 件）。
---   ★危険が「出ていない」のは置き場所のおかげであって、直ったからではない。
---
---   実測: `work/caution.txt` のフルパスが **1,359 行**に出ていた。
---
--- ★プロジェクト直下からの相対にする。⚠ 外にあるパスはそのまま返す
---   （★勝手に切ると、どこの話か分からなくなる）。
---
--- ## ⚠⚠ **メソッドにしないこと**（2026-08-13 に2度踏んだ）
---
---   `research/probes/` は **必要な鍵だけを持つ擬似テーブル**を bridge の
---   代わりに渡す。`self:short_path(...)` と書くと、そこに無いので
---
---       attempt to call method 'short_path' (a nil value)
---
---   で落ちる（★`self:debug(...)` を足したときと**同じ壊れ方**）。
---   ★状態を持たない補助は**モジュール内の関数**にして、`root` を引数で渡す。
local function short_path(root, path)
  if path == nil then return nil end
  local text = tostring(path):gsub("\\", "/")
  root = tostring(root or ""):gsub("\\", "/")
  if root ~= "" then
    -- ⚠ 大文字小文字が違うことがある（Windows）。★両方を小文字にして比べる
    local lower_text, lower_root = text:lower(), root:lower()
    if lower_text:sub(1, #lower_root) == lower_root then
      return (text:sub(#lower_root + 1):gsub("^/", ""))
    end
  end
  return text
end

--- ★検査から呼べるようにしておく（⚠ `self:` では呼ばない）
Bridge.short_path = short_path

function Bridge:log(message, ascii_hint, level)
  level = level or "INFO"
  local rank = Bridge.LEVELS[level] or Bridge.LEVELS.INFO
  -- ★下限に届かなければ**何もしない**（⚠ 画面への英字も出さない）
  if rank < (self.log_min_rank or Bridge.LEVELS.INFO) then return end
  local fh = io.open(self.log_path, "a")
  if fh then
    -- ★Python 側と同じ並びにする（`logging_setup.py` の LOG_FORMAT）:
    --     2026-07-26 13:11:22 [INFO] record battle=12 event=battle_end ...
    --   ⚠ 出所が分かるように名前は `lua` で固定する。
    fh:write(os.date("%Y-%m-%d %H:%M:%S ") .. "[" .. level .. "] lua "
             .. message .. "\n")
    fh:close()
  end
  if ascii_hint then print(ascii_hint) end
end

-- ★★★ ⚠⚠ `self:debug(...)` のような**別の入口を作らないこと** ★★★
--
--   一度作って、実 Lua の検査 15 件が落ちた（2026-08-13）:
--
--       attempt to call method 'debug' (a nil value)
--
--   ⚠ `research/probes/` は **`log` だけを持つ擬似テーブル**を bridge の
--     代わりに渡す（実測 24 本 / 31 箇所。★`debug` を持つものは 0）:
--
--       local shim = { battle_types = T, log = function() end }
--
--   ★probe が `log` を差し替えられるのは「入口が1つ」だから。
--     入口を増やすと、**全部の probe を直して回る**ことになる。
--
--   → 段階は**第3引数**で渡す:
--
--       self:log("...", "hint")                -- INFO（既定）
--       self:log("...", "hint", "DEBUG")       -- 調査用
--       self:log("...", "hint", "WARNING")
--       self:log("...", "hint", "ERROR")

-- 画面に短い通知を出す（英数字のみ / 既定3秒）。
-- ★詳細は work/retroux.log に日本語で出す。ここは「効いたかどうか」を
--   その場で分かるようにするためのもの。
function Bridge:notify(text, frames)
  self.notice = tostring(text)
  self.notice_left = frames or 180
end

-- ★イベントには**起きた時刻**を入れる（2026-07-26）。
--
--   Python 側は取り込んだ時点の時計で記録していた。取り込みが追いついている
--   間は同じことだが、**溜まったぶんを後からまとめて処理すると全部が同じ時刻**
--   になる。実際、4820件を追いついたとき 1400 戦闘すべてが 14:03 になった。
--   起きた時刻はここでしか分からないので、ここで入れる。
--   （フレーム番号はセッションをまたぐと 0 に戻るので時刻の代わりにならない）
-- 「いまの状態」を work/state.json へ書く（GUI が読む / MVP2 Phase 2）。
--
-- ★events.jsonl と役割を分ける:
--     events.jsonl … 起きたこと（追記・DBへ・消えない）
--     state.json   … いまの値（上書き・表示用・消えてよい）
--   混ぜると「記録」と「表示」がどちらも中途半端になる。
--
-- ★一時ファイルへ書いてから置き換える。GUI が読んでいる最中に
--   半端な内容を掴まないため（command.json と同じ方式）。
-- 行動単位ログ: **観測できた事実**だけを events.jsonl へ出す（Phase 3）。
--
-- ★「誰の攻撃で誰が減ったか」は出さない。DQ2 は行動順を RAM に出しておらず、
--   同じフレームに複数の変化が起きる。対応づけは推測になる。
--   **HPがこう変わった**という事実だけを、ターン番号とともに残す。
--
-- ★ターンは「戦闘コマンドが開いて $00A8 が先頭を指した回数」で数える。
--   DQ2 は全員の入力が済んでから解決するので、これが1ターンの区切りになる。
function Bridge:_track_battle_log()
  if not self.state.in_battle then
    self.log_prev = nil
    return
  end
  local cfg = self.battle_log or {}
  if cfg.enabled == false then return end

  local a = self.memory_map.addresses
  local menu = memory.readbyte(a.menu_id.addr)
  local cmd = a.menu_id.values.battle_menu

  -- ターンの区切り
  if menu == cmd then
    if not self.saw_command_menu then
      self.saw_command_menu = true
      local m, idx = self.game:battle_input_member()
      if idx == 0 or m == nil then
        self.turn_no = self.turn_no + 1
        self.turn_seq = 0
        self:emit("battle_turn", { turn = self.turn_no })
      end
    end
  else
    self.saw_command_menu = false
  end

  -- いまの値をまとめて取る
  local now = { party = {}, enemy = {} }
  local p = a.party
  for _, m in ipairs(self.game:active_party()) do
    now.party[m.index] = {
      name = m.name, hp = m.hp,
      mp = memory.readbyte(p.fields.current_mp.offset + m.index * p.member_stride),
    }
  end
  for _, e in ipairs(self.game:enemy_instances()) do
    now.enemy[e.index] = { name = e.name, hp = e.hp }
  end

  if self.log_prev == nil then
    self.log_prev = now
    return
  end

  -- ★上限を置く。1戦闘のログが無限に増えないようにする（playbook #9）。
  local limit = cfg.max_rows_per_battle or 200

  local function record(kind, index, name, before, after)
    if self.log_count >= limit then return end
    self.log_count = self.log_count + 1
    self.turn_seq = self.turn_seq + 1
    self:emit("battle_observation", {
      turn = self.turn_no, seq = self.turn_seq, kind = kind,
      index = index, name = name,
      before = before, after = after, delta = after - before,
    })
  end

  for index, cur in pairs(now.party) do
    local was = self.log_prev.party[index]
    if was ~= nil then
      if cur.hp ~= was.hp then record("party_hp", index, cur.name, was.hp, cur.hp) end
      if cur.mp ~= was.mp then record("party_mp", index, cur.name, was.mp, cur.mp) end
    end
  end
  for index, cur in pairs(now.enemy) do
    local was = self.log_prev.enemy[index]
    -- ★倒した個体の枠は別用途へ回るので、増えた変化は捨てる（ゴミを記録しない）
    if was ~= nil and cur.hp < was.hp then
      record("enemy_hp", index, cur.name, was.hp, cur.hp)
    end
  end
  -- ★居なくなった敵は「倒した」として残す。
  --   倒れると枠が空く（IDが 0xFF になる）ので、HPが 0 へ減る様子は
  --   見えないことがある。**消えたという事実**を記録する。
  for index, was in pairs(self.log_prev.enemy) do
    if now.enemy[index] == nil then
      record("enemy_defeated", index, was.name, was.hp, 0)
    end
  end

  self.log_prev = now
end

----------------------------------------------------------------------
-- 画面の色を1マスずつ拾う（2026-07-29 / 依頼者の指摘）
----------------------------------------------------------------------
--
-- > マップが、周りが記憶出来ていないように思える（画面とMAPの色が違う）
--
-- ★地図が一色の帯だと、陸と海の区別が付かない。
--   **画面に出ている色そのもの**を1マス1色で拾って、地図に写す。
--
-- ⚠ 拾うのは色だけ。地形の種類（壁・扉）は分からないままで、
--   それは正直に画面へ書いてある。
--
-- ⚠ 画面の割り付け（1マス16px / 主人公が中央）は
--   **256x240 ÷ 16 という計算から出したもので、実機で測ってはいない**。
--   `config.yaml` の `map.view_radius` と合わせて調整できる。

local TILE_PX = 16
local SCREEN_W, SCREEN_H = 256, 240

--- 画面のうち**マップが映っている行数**（16px 単位 / 2026-08-01）。
---
--- ⚠⚠ 画面の下 1/4 は**ステータス窓**（なまえ・LV・HP・MP）。
---   そこを地形として読むと、**窓の白や枠の青**を地形の色として記録する。
---   実際に描いてみて気づいた（`work/` の 15x15 の下側が白くなった）。
---
--- ★読まない。⚠ そのぶん主人公より下は見える範囲が狭くなるが、
---   **本当に見えていない**のだから正しい（推測で埋めない）。
---
--- ★★ **11 -> 10 に直した**（2026-08-01 / 依頼者の save2 で実測）★★
---   `status_window_probe.lua` で、窓の文字にしか使われないタイルIDが
---   **8px 行 20-27**（= 16px マス行 **10** から）に出ることを確かめた。
---   ⚠ 11 だとマス行 10 を地形として読み、**窓の白と枠**を拾っていた。
---     依頼者の「MAPの色が違うのではないか」の一因。
local MAP_ROWS_WINDOW_OPEN = 10

--- 窓が**閉じている**ときに読めるマス行数（2026-08-02 / 課題 #65）。
---
--- 画面 240px ÷ 16px = 15 マス行。★窓が無いなら全部が地形。
local MAP_ROWS_WINDOW_SHUT = 15

--- ステータス窓が占める 8px 行（実測 20-27。29 まで見て取りこぼさない）。
local WINDOW_ROW_FROM, WINDOW_ROW_TO = 20, 29

--- いま地形として読めるマス行数を返す（2026-08-02 / 課題 #65）。
---
--- 依頼者:
---   > 動けば窓消えるし、止まれば窓が出るはず
---
--- ★そのとおりだったので、**窓が出ているかを見て**読む範囲を変える。
---   ⚠ 固定で 10 にしていると、窓が閉じている間もマス行 10-14 を捨てる。
---
--- ⚠ タイルIDの一覧は `config.yaml` の `map.status_window_tiles` が正本。
---   無ければ**安全側**（常に 10）に倒す。推測で広げない。
function Bridge:_map_rows()
  local ids = ((self.config or {}).map or {}).status_window_tiles
  if ids == nil or ppu == nil or ppu.readbyte == nil then
    return MAP_ROWS_WINDOW_OPEN
  end
  self._window_ids = self._window_ids or (function()
    local set = {}
    for _, id in ipairs(ids) do set[id] = true end
    return set
  end)()

  local addrs = (self.memory_map or {}).addresses or {}
  local ax, ay = addrs.scroll_x, addrs.scroll_y
  if ax == nil or ay == nil then return MAP_ROWS_WINDOW_OPEN end
  local sx = math.floor(memory.readbyte(ax.addr) / 8)
  local sy = math.floor(memory.readbyte(ay.addr) / 8)

  for row = WINDOW_ROW_FROM, WINDOW_ROW_TO do
    for col = 0, 31 do
      local c64 = (col + sx) % 64
      local base = (c64 < 32) and 0x2000 or 0x2400
      local ok, v = pcall(ppu.readbyte,
        base + ((row + sy) % 30) * 32 + (c64 % 32))
      if ok and v ~= nil and self._window_ids[v] then
        return MAP_ROWS_WINDOW_OPEN         -- ★窓が出ている
      end
    end
  end
  return MAP_ROWS_WINDOW_SHUT               -- ★窓は無い。下まで地形
end

--- これ以下の明るさ（R+G+B）は「黒」とみなす（2026-08-01 / 課題 #65）。
---
--- ★★ 依頼者の決定「特色（黒を除いた画素の平均）でやってみて」★★
---
--- ⚠ DQ2 の地形は「黒地にまばらな点」が多い。黒を平均に入れると点が消え、
---   地図が一様に暗くなる（実測: ロンダルキア 3F の 88% が真っ黒だった）。
--- ⚠ しきい値を上げすぎると、本当に暗い地形まで「黒」になる。
---   120（1色あたり 40）は、NES の暗い色（$0F=黒 / $00=灰）を分ける値。
local BLACK_LEVEL = 120

--- 64点のうち、これ未満しか明るくなければ「黒」とみなす（2026-08-01）。
---
--- ⚠⚠ 1点だけ明るいと、黒を除いた平均は**その1点の色**になる。
---   実機で**緑のブロック**が出た（主人公の服の緑が1画素混ざっただけ）。
--- ★地形なら明るい画素はもっと広がっている。
local MIN_LIT = 4

-- 主人公を中心とした (2r+1)x(2r+1) マスの色を "RGB444" で並べた文字列を返す。
-- 読めなければ nil。
function Bridge:map_seen_colors(radius)
  radius = radius or 7
  local frame = emu.framecount()
  -- ★毎フレームやらない。画素を数百回読むので間隔を空ける。
  --   歩く速さ（1マス十数フレーム）に対しては十分。
  if self._colors_frame ~= nil and frame - self._colors_frame < 15 then
    return self._colors_cache
  end
  self._colors_frame = frame

  -- 画面の中心のマス（主人公が居ると仮定する位置）
  local cx = math.floor(SCREEN_W / TILE_PX / 2)
  local cy = math.floor(SCREEN_H / TILE_PX / 2)
  -- ★窓が出ているかを見て、読める行数を決める（2026-08-02 / 課題 #65）
  local map_rows = self:_map_rows()
  local out = {}
  for dy = -radius, radius do
    for dx = -radius, radius do
      local col, row = cx + dx, cy + dy
      local px0, py0 = col * TILE_PX, row * TILE_PX
      local hex = "___"                    -- ★画面の外は「分からない」
      -- ⚠ ステータス窓は地形ではないので読まない
      if px0 >= 0 and py0 >= 0 and row < map_rows
        and px0 + TILE_PX <= SCREEN_W and py0 + TILE_PX <= SCREEN_H then
        -- ★★ **特色 = 黒を除いた画素の平均**（2026-08-01 / 依頼者の決定）★★
        --
        --   ⚠⚠ これまでは**中心の1画素**だけを読んでいた。洞窟の床は
        --     「黒地にまばらな赤い点」なので中心はほぼ黒に当たり、
        --     ロンダルキア 3F では **511 マス中 451（88%）が真っ黒**だった。
        --     さらに**主人公自身の色**（緑の服・白）まで地形として拾っていた。
        --
        --   ★黒を外して平均すると、点の色が残って地形の特徴が出る。
        --     ⚠ 平均に黒を入れると点が薄まって消える（実際に潰れた）。
        --   ★全部黒なら**黒のまま**返す（＝そういう地形。嘘をつかない）。
        --
        --   ★★ **8x8 の格子（64点）**で見る（2026-08-01 に実測）★★
        --     ⚠ 「重そうだから 4x4」と控えめにしていたが、**推測だった**。
        --       測ったら 8x8 でも 20回ぶんの走査が **1フレーム内**で終わる:
        --         1x1  4,500画素 / 2x2 18,000 / 4x4 72,000 / 8x8 288,000
        --         -> どれも経過 1 フレーム（`work/color_cost.txt`）
        --     ★実際の呼び出しは 15 フレームに1回なので、さらに余裕がある。
        local sr, sg, sb, lit, ok_all = 0, 0, 0, 0, true
        for sy = 0, 7 do
          if not ok_all then break end
          for sx = 0, 7 do
            local ok, r, g, b = pcall(emu.getscreenpixel,
                                      px0 + sx * 2 + 1, py0 + sy * 2 + 1,
                                      false)
            if not ok or r == nil then ok_all = false break end
            -- ★黒は数に入れない（地の色を数えると点が消える）
            if r + g + b > BLACK_LEVEL then
              sr, sg, sb, lit = sr + r, sg + g, sb + b, lit + 1
            end
          end
        end
        if ok_all then
          -- ⚠⚠ **明るい画素が少なすぎるものは黒とみなす**（2026-08-01）★★
          --
          --   64点のうち1点だけ明るいと、黒を除いた平均は**その1点の色**に
          --   なる。実機で**緑のブロック**が出た（主人公の服の緑が1画素
          --   混ざっただけのマス / 依頼者の画面で確認）。
          --
          --   ★地形なら、明るい画素はもっと広がっている。
          --   ⚠ しきい値を上げすぎると、まばらな点の床まで黒になる。
          --     4/64（6%）は「点が数個ある」を残し「1点の紛れ」を落とす値。
          if lit < MIN_LIT then
            hex = "000"                   -- ★黒＝そういう地形（嘘をつかない）
          else
            hex = string.format("%X%X%X",
                                math.floor(sr / lit / 16),
                                math.floor(sg / lit / 16),
                                math.floor(sb / lit / 16))
          end
        end
      end
      out[#out + 1] = hex
    end
  end
  self._colors_cache = table.concat(out)
  return self._colors_cache
end

--- 主人公を中心とした (2r+1)x(2r+1) マスの**タイルID**を 16進2文字で並べる。
---
--- ★★ 色の1画素サンプリングをやめるため（2026-08-01 / 課題 #65）★★
---
--- 依頼者:
---   > ダンジョンの土と壁が複雑ないろなので分かりづらい。
---   > キャラクタパターンを作って、切り替わらないようにすると良い
---
--- ⚠⚠ いままでは各マスの**中心の1画素**を読んでいた。実測すると:
---
---   ・ロンダルキア 3F は 511 マス中 451（88%）が `000`（真っ黒）だった。
---     洞窟の床は「黒地に赤い点」なので、中心はほぼ黒に当たる。
---   ・**主人公自身の色を地形として記録していた**（`090` = 緑の服、
---     `FFF` = 白）。スプライトは地形ではない。
---
--- ★ネームテーブルのタイルIDなら:
---   ・同じ床は必ず同じID（実測 960/960 一致 = **ぶれない**）
---   ・主人公はスプライトなので**混ざらない**
---   ・IDから絵（8x8 の模様）を引ける
---
--- ⚠ 1マス = 16x16 画素 = 2x2 タイル。**左上の1つ**を代表とする
---   （床は4つとも同じ。壁は4つ違うが、左上だけで種類は決まる）。
function Bridge:map_seen_tiles(radius)
  if ppu == nil or ppu.readbyte == nil then return nil end
  radius = radius or 7
  local frame = emu.framecount()
  if self._tiles_frame ~= nil and frame - self._tiles_frame < 15 then
    return self._tiles_cache
  end
  self._tiles_frame = frame

  -- ★★ スクロールを足す（2026-08-01 / 課題 #65）★★
  --   ⚠ 以前はここを足しておらず、391マス中 362 が空白タイルになっていた。
  --   ★ネームテーブル $2000 は 32×30 の**固定の入れ物**で、
  --     画面はその中を**巡回して**映す。ずれを知らずに読めば当然合わない。
  --   ★実測（scroll_confirm_probe）:
  --       左に1マス動かすと $0005 が 32 -> 16 に減り、
  --       当てはめで求めたずれも 4 タイル -> 2 タイルへ**予想どおり**動いた。
  --       ずれ（画素）は $0005 / $0006 の値と**完全に一致**（一致率 98〜99%）。
  --   ⚠ 番地は `memory_map.yaml` が正本。ここに数字を書かない。
  local addrs = (self.memory_map or {}).addresses or {}
  local ax, ay = addrs.scroll_x, addrs.scroll_y
  if ax == nil or ay == nil then return nil end   -- ★分からないものは出さない
  local sx = math.floor(memory.readbyte(ax.addr) / 8)
  local sy = math.floor(memory.readbyte(ay.addr) / 8)

  local cx = math.floor(SCREEN_W / TILE_PX / 2)
  local cy = math.floor(SCREEN_H / TILE_PX / 2)
  -- ⚠⚠ **ここに行の制限が無かった**（2026-08-02 に気づいた）。
  --   `map_seen_colors` は窓を避けていたのに、こちらは全 30 行を読み、
  --   **窓の文字のタイルIDを地形として記録していた**。
  --   ★同じ物差しで切る。
  local map_rows = self:_map_rows()
  local out = {}
  for dy = -radius, radius do
    for dx = -radius, radius do
      -- ★ネームテーブルは 8x8 の格子。1マスは 2x2 なので2倍する
      local col = (cx + dx) * 2
      local row = (cy + dy) * 2
      local hex = "__"                     -- ★画面の外は「分からない」
      if col >= 0 and col < 32 and row >= 0 and (cy + dy) < map_rows then
        -- ★★ **ネームテーブルは2枚が左右に並ぶ（64列）** ★★
        --
        --   ⚠⚠ 最初は「1枚で % 32」と決めていた。依頼者の save2
        --     （横スクロール 208画素 = 26列）でそれが露わになった:
        --       $2000 だけ 44% / $2400 だけ 86% / ★64列 98%
        --   ★実測で $2000 == $2800 かつ $2400 == $2C00 ＝ 垂直ミラーリング。
        --     2枚は**左右**に並ぶ（横スクロール用）。画面 32 列は 64 列の窓。
        --   ★左が $2000 であることも実測（左右を入れ替えると 32% / 69%）。
        --   ⚠ たては 1枚の中で % 30。こちらは save2/save3 とも合っている。
        local c64 = (col + sx) % 64
        local base = (c64 < 32) and 0x2000 or 0x2400
        local nr = (row + sy) % 30
        local ok, v = pcall(ppu.readbyte, base + nr * 32 + (c64 % 32))
        if ok and v ~= nil then hex = string.format("%02X", v) end
      end
      out[#out + 1] = hex
    end
  end
  self._tiles_cache = table.concat(out)
  self:_dump_tile_art(out, cx, cy, radius)
  return self._tiles_cache
end

--- 1マスぶんを **4枚＋パレット組**で読む（2026-08-02 / 課題 #65）。
---
--- ★★ **なぜ 4枚いるのか** ★★
---
---   `map_seen_tiles` は1マスの**左上だけ**を記録していました。
---   ⚠ それでは 16×16 の絵が組めません。実測（2026-08-02）で、
---     残り3枚の決まり方が**マップごとに違う**と分かったからです:
---
---       ダンジョン  右上 +4 / 左下 -1 / 右下 +3
---       街          右上 +2 / 左下 -1 / 右下 +1
---       ⚠ しかも街には例外がある（$D9 は 2 通り、$F9 は変則）
---
---   ★規則を1つに決めると、街の飾りで間違えます。**4枚とも読みます。**
---
--- ★★ **パレット組も要る** ★★
---   同じ絵でも組が違えば色が違います。属性テーブル（`$23C0`）から読みます。
---   ⚠ 属性1バイトは 4×4 タイルぶん。2ビットずつ、下位から
---     左上・右上・左下・右下 の順です。
---
--- 形式は1マス **9文字**（タイルID 2文字 × 4 ＋ 組 1文字）。
--- ★分からないところは `_`（0 と混ぜない）。
---
--- ⚠ `map_seen_tiles` は**残してあります**（指示書 §15.5
---   「新方式が安定するまで現行表示を削除しない」）。
function Bridge:map_seen_cells(radius)
  if ppu == nil or ppu.readbyte == nil then return nil end
  radius = radius or 7
  local frame = emu.framecount()
  if self._cells_frame ~= nil and frame - self._cells_frame < 15 then
    return self._cells_cache
  end
  self._cells_frame = frame

  local addrs = (self.memory_map or {}).addresses or {}
  local ax, ay = addrs.scroll_x, addrs.scroll_y
  if ax == nil or ay == nil then return nil end   -- ★分からないものは出さない
  local px, py = memory.readbyte(ax.addr), memory.readbyte(ay.addr)

  -- ★★ **動いている最中は出さない**（2026-08-02 / 課題 #65）★★
  --
  --   ⚠ 1マス（2×2 タイル）は属性テーブルの1区画に収まりますが、
  --     それは **16 画素の格子に揃っているとき**だけです。
  --     動いている最中は区画をまたぎ、**別の色**を当ててしまいます。
  --
  --   ★止まっているときのスクロールは **16 の倍数**（実測 / 既知）。
  --     採取データ4件でも「またぎ」は 0 件でした。
  --   ⚠ ここで出さなければ、受け取る側は「静止した絵」だけを見られます。
  if px % 16 ~= 0 or py % 16 ~= 0 then
    self._cells_cache = nil
    return nil
  end

  local sx = math.floor(px / 8)
  local sy = math.floor(py / 8)

  local cx = math.floor(SCREEN_W / TILE_PX / 2)
  local cy = math.floor(SCREEN_H / TILE_PX / 2)
  local map_rows = self:_map_rows()
  local out = {}
  for dy = -radius, radius do
    for dx = -radius, radius do
      local col = (cx + dx) * 2
      local row = (cy + dy) * 2
      local cell = "_________"           -- ★9文字。画面の外は「分からない」
      if col >= 0 and col < 32 and row >= 0 and (cy + dy) < map_rows then
        local ids, group, ok_all = {}, nil, true
        for _, d in ipairs({{0, 0}, {1, 0}, {0, 1}, {1, 1}}) do
          -- ★ネームテーブルは2枚が左右に並ぶ（64列）。`map_seen_tiles` と同じ
          local c64 = (col + d[1] + sx) % 64
          local base = (c64 < 32) and 0x2000 or 0x2400
          local nr = (row + d[2] + sy) % 30
          local nc = c64 % 32
          local ok, v = pcall(ppu.readbyte, base + nr * 32 + nc)
          if ok and v ~= nil then
            ids[#ids + 1] = string.format("%02X", v)
          else
            ok_all = false
            break
          end
          -- ★パレット組は左上のぶんだけ読む。
          --   ⚠ 静止時のスクロールは 16 の倍数なので、2×2 は同じ区画に入る
          --     （実測4件とも「またぎ」0件 / 2026-08-02）。
          if group == nil then
            local aok, av = pcall(ppu.readbyte,
              base + 0x3C0 + math.floor(nr / 4) * 8 + math.floor(nc / 4))
            if aok and av ~= nil then
              local shift = (math.floor(nr % 4 / 2) * 2
                           + math.floor(nc % 4 / 2)) * 2
              group = math.floor(av / (2 ^ shift)) % 4
            else
              ok_all = false
              break
            end
          end
        end
        if ok_all and group ~= nil then
          cell = table.concat(ids) .. tostring(group)
        end
      end
      out[#out + 1] = cell
    end
  end
  self._cells_cache = table.concat(out)
  return self._cells_cache
end

--- ★★★ マップ採取は「動いたときだけ」（2026-08-07 / 軽量化指示書 §4）★★★
---
--- 依頼者の指示書（`input/RetroUX_UI監視処理_軽量化差分更新_実装指示_*.md` §4.1）:
---
---   > 主人公が新しい座標へ移動した場合のみマップ情報を採取する。
---   > 立ち止まっている間は、同じマップ情報を何度も観測しない。
---
--- ⚠ これまでは 0.5 秒ごとに**必ず** 3種類を採り直していました。
---   `map_seen_colors` は 1マス 64 画素 × 225マス ＝ **1万回超の画素読み**です。
---   立ち止まっている（＝画面を触っている）あいだ中それをやるので、
---   ★依頼者の言う「もっさり」の主因になり得ます。
---
--- ## ⚠⚠ ここが罠（★「動いたら1回」だけでは足りない）
---
---   `map_seen_cells` は**スクロールが 16 の倍数のときしか出ません**
---   （動いている最中は nil）。★歩いた直後に1回だけ採ると、
---   ⚠ その 1回がたまたま移動中で **nil のまま固定**され、
---     そのマスの絵が**永久に採れません**。
---
---   → ★出るまで採り直す。⚠ ただし**上限つき**（`retry_limit`）。
---     `ppu` が無い環境では何度やっても出ないので、黙って回り続けない。
---
--- ## ★ 何を鍵にするか（§4.2）
---
---     map_id / x / y
---
---   ⚠ 街・洞窟・階段・旅の扉では **x/y が同じでも map_id が変わり得る**ので、
---     `map_id` は必ず入れます。
---
--- ⚠ 半径も鍵に入れます（★設定を変えたら採り直すべきなので）。
local MAP_SAMPLE_RETRY = 8

--- 採取の設定を読む。⚠ 設定が無ければ**従来どおり全部採る**。
function Bridge:_map_observe_config()
  local m = self.config ~= nil and self.config.map or nil
  local o = m ~= nil and m.observe or nil
  return {
    on_move_only = (o == nil or o.on_move_only ~= false),
    retry_limit = (o ~= nil and o.retry_limit) or MAP_SAMPLE_RETRY,
    legacy_colors = (o == nil or o.legacy_colors ~= false),
    legacy_tiles = (o == nil or o.legacy_tiles ~= false),
    cells = (o == nil or o.cells ~= false),
  }
end

--- 画面がいま真っ黒（暗転中）か（2026-08-11 / 依頼者「なぜ黒塗りに」）。
---
--- ★★ 世界地図は ROM の完全地図ではなく「画面に映った地形」を貼って作る。
---   ⚠ だから画面が暗転している一瞬に採ると、その黒を「見た地形」として
---     記録してしまう（黒塗り）。ロードだけでなく、画面切替・フェード・
---     メニュー等でも一瞬暗転する。★**真っ黒なら採らない**で全部を防ぐ。
--- ⚠ 主人公はスプライトで色があるので、通常プレイ中は中央が黒くならない
---   （＝暗い洞窟でも暗転と誤検知しない）。rendering が切れた時だけ全点が黒。
--- ★`getemuscreen=true`＝ゲーム画面そのもの（Lua の文字表示は混ぜない）。
function Bridge:_screen_looks_blank()
  if emu == nil or emu.getscreenpixel == nil then return false end
  local pts = { {128, 112}, {64, 80}, {192, 80}, {64, 160}, {192, 160} }
  local ok, blank = pcall(function()
    for _, p in ipairs(pts) do
      local r, g, b = emu.getscreenpixel(p[1], p[2], true)
      if ((r or 0) + (g or 0) + (b or 0)) > 24 then return false end
    end
    return true
  end)
  return ok and blank == true
end

--- いまのマスのマップ材料を返す（★動いていなければ前回のものを返す）。
---
--- 戻り値は `{ colors = ..., tiles = ..., cells = ... }`。
--- ⚠ **書き出す内容は変えません**。★変わるのは「採り直すかどうか」だけです。
function Bridge:_map_sample(map_id, x, y, radius)
  -- ★★ ロード直後の暗転を「見た地形」に記録しない（2026-08-11 / 依頼者）★★
  --   ⚠ 採り直さず、前回の材料をそのまま返す（＝黒い画面を記録しない）。
  --     初回で前回が無ければ、色・タイル・絵の無い空を返す（何も記録されない）。
  if self.map_load_until_frame ~= nil and emu ~= nil
     and emu.framecount ~= nil
     and emu.framecount() < self.map_load_until_frame then
    self.map_sample_skipped = (self.map_sample_skipped or 0) + 1
    return self.map_sample or { key = nil, tries = 0, done = false }
  end
  -- ★★ 暗転中（画面が真っ黒）の材料は記録しない（2026-08-11 / 依頼者）★★
  --   ⚠ ロード以外（画面切替・フェード）でも一瞬暗転する。★真っ黒なら採らない。
  if self:_screen_looks_blank() then
    self.map_sample_skipped = (self.map_sample_skipped or 0) + 1
    return self.map_sample or { key = nil, tries = 0, done = false }
  end

  local cfg = self:_map_observe_config()
  local key = table.concat({ tostring(map_id), tostring(x), tostring(y),
                             tostring(radius) }, "/")
  local s = self.map_sample
  if s == nil or s.key ~= key or not cfg.on_move_only then
    s = { key = key, tries = 0 }
    self.map_sample = s
  elseif s.done then
    -- ★立ち止まっている。⚠ 採り直さずに前回の材料をそのまま返す
    self.map_sample_skipped = (self.map_sample_skipped or 0) + 1
    return s
  end

  s.tries = s.tries + 1
  s.colors = cfg.legacy_colors and self:map_seen_colors(radius) or nil
  s.tiles = cfg.legacy_tiles and self:map_seen_tiles(radius) or nil
  s.cells = cfg.cells and self:map_seen_cells(radius) or nil
  -- ★16×16 の絵が採れたら、そのマスは完了。⚠ 採れないうちは上限まで粘る
  --   （★止まればスクロールが 16 の倍数になり、たいてい 1〜2 回で出ます）
  s.done = (not cfg.cells) or (s.cells ~= nil) or (s.tries >= cfg.retry_limit)
  if s.done and s.cells == nil and cfg.cells
     and not self.map_cells_give_up_logged then
    -- ⚠⚠ **黙って諦めない**（★指示書の作法 / playbook #35）。
    --   1回だけ残します（毎マス出すとログが埋まります）。
    self.map_cells_give_up_logged = true
    self:log(string.format(
      "マップの絵を %d 回試しても採れませんでした（★色とタイルIDだけで記録します）",
      cfg.retry_limit), "map cells unavailable; falling back", "DEBUG")
  end
  return s
end

--- 出てきたタイルの**絵を画面から読む**（2026-08-01 / 課題 #65）。
---
--- 依頼者:
---   > 俺的にはタイル拡大表示だと思っていたのだが。
---
--- ★★ **CHR ではなく画面の画素を読む。** ★★
---
---   ⚠ CHR（`ppu.readbyterange`）で読める絵は **0..3 の番号**だけで、
---     色がありません。色にするにはパレット（$3F00-）と属性テーブル
---     （$23C0-）を組み合わせる必要があり、間違えると別の色になります。
---
---   ★画面の画素（`emu.getscreenpixel`）なら**実際に出ている色**そのもの。
---     パレットの計算が要らず、間違えようがありません。
---
--- ⚠ 重いので**初めて見たタイルだけ**読みます（1タイル 64 画素）。
---   同じタイルIDでもマップが変わると色が変わるので、`マップID:タイルID`
---   を鍵にします。
---
--- ⚠⚠ 主人公はスプライトなので、その上のタイルを読むと**服の色**が混ざります。
---   ★主人公の居るマスとその隣は**読みません**。
function Bridge:_dump_tile_art(ids, cx, cy, radius)
  if emu == nil or emu.getscreenpixel == nil then return end
  -- ⚠⚠ `self.state.map_id` は**存在しない**（一度そう書いて絵が1枚も
  --   取れなかった）。★ゲームから直に読む（`_write_state` と同じ出口）。
  local ok_id, map_id = pcall(function() return self.game:map_id() end)
  if not ok_id or map_id == nil then return end

  self._art_seen = self._art_seen or {}
  local lines = {}
  local i = 0
  for dy = -radius, radius do
    for dx = -radius, radius do
      i = i + 1
      local hex = ids[i]
      -- ★主人公の居るマスとその隣は飛ばす（スプライトが乗っている）
      local near_hero = (dx >= -1 and dx <= 1 and dy >= -1 and dy <= 1)
      if hex ~= nil and hex ~= "__" and not near_hero then
        local key = string.format("%02X:%s", map_id, hex)
        if self._art_seen[key] == nil then
          local px0 = (cx + dx) * TILE_PX
          local py0 = (cy + dy) * TILE_PX
          if px0 >= 0 and py0 >= 0
            and px0 + TILE_PX <= SCREEN_W and py0 + TILE_PX <= SCREEN_H then
            -- ★★ **16x16 を全部読んで、2x2 の平均で 8x8 にする** ★★
            --
            --   ⚠⚠ 最初は「2画素おきに間引く」形にした。洞窟の床は
            --     「黒地に**まばらな**赤い点」なので、**点を外して真っ黒**
            --     だけを拾い、地図が一様に暗くなった（実際にそうなった）。
            --   ★平均なら点が薄まって残る。潰さずに縮める。
            --
            --   ⚠ 読むのは 256 回だが、**初めて見たタイルだけ**なので
            --     1マップあたり数十回で終わる。
            local cells, ok_all = {}, true
            for y = 0, 7 do
              if not ok_all then break end
              for x = 0, 7 do
                -- ⚠⚠ **平均にしない。**「4画素のうち1つだけ赤い点」を
                --   平均すると A00 が 2A0000 になり、ほぼ黒に潰れる
                --   （実際そうなり、地図が一様に暗くなった）。
                -- ★**一番明るい画素**を採る。点が消えない。
                local br, bg, bb, best = 0, 0, 0, -1
                for oy = 0, 1 do
                  for ox = 0, 1 do
                    local ok, r, g, b = pcall(emu.getscreenpixel,
                                              px0 + x * 2 + ox,
                                              py0 + y * 2 + oy, false)
                    if not ok or r == nil then ok_all = false break end
                    local lum = r + g + b
                    if lum > best then br, bg, bb, best = r, g, b, lum end
                  end
                  if not ok_all then break end
                end
                if not ok_all then break end
                cells[#cells + 1] = string.format("%02X%02X%02X", br, bg, bb)
              end
            end
            if ok_all then
              self._art_seen[key] = true
              lines[#lines + 1] = key .. "\t" .. table.concat(cells, "")
            end
          end
        end
      end
    end
  end
  if #lines == 0 then return end
  local fh = io.open(self.root .. "/work/generated/tile_art.txt", "a")
  if fh == nil then return end
  fh:write(table.concat(lines, "\n") .. "\n")
  fh:close()
end

function Bridge:_write_state()
  local s = self.state
  local parts = {}
  local function add(key, value)
    parts[#parts + 1] = '"' .. key .. '":' .. json_value(value)
  end

  add("frame", emu.framecount())
  add("time", os.time())
  -- ★所持ゴールド（2026-07-31）。パーティ共通なので人ごとの表には入れない。
  --   ⚠ 2バイト・リトルエンディアン。上位を忘れると 255 で頭打ちになる。
  --   ★`$0624` は「公開資料由来・未検証」だったが、「つよさ」の画面の
  --     キャプチャと突き合わせて確認できた（130 + 61×256 = 15746）。
  local gold_addr = (self.memory_map.addresses.gold or {}).addr
  if gold_addr ~= nil then
    add("gold", memory.readbyte(gold_addr) + memory.readbyte(gold_addr + 1) * 256)
  end
  add("in_battle", s.in_battle == true)
  add("speed", self.throttle.multiplier)
  add("danger", s.danger == true)
  add("danger_reason", s.danger_reason)
  add("auto_input", self:auto_input_allowed() == true)
  add("force_auto", self.battle:get_status().force_auto)
  -- ★★ AUTO と 高速化 は**独立して**出す（2026-07-31 の指示書 §5.5）★★
  --   画面が2つのトグルを別々に描けるようにするため。
  --   ⚠ 片方から他方を推測させない（「速いなら AUTO だろう」は成り立たない）。
  add("auto_enabled", self.battle:is_auto_enabled())
  add("turbo_enabled", self.speed:is_enabled())

  -- ★★★ 推論の4段を画面へ渡す（2026-08-07 / Phase 9・§18）★★★
  --
  --   目的 -> 戦況 -> 戦術 -> 役割
  --
  -- ⚠⚠ **「届いていない」と「0」を分ける。** ★nil のまま出します。
  --   0 を入れると、画面は「測った結果ゼロ」と表示してしまい、
  --   ⚠ **測れていないことに永久に気づけません**（19件が unknown だった
  --     ときも、数字を見るまで気づけませんでした）。
  --
  -- ★★ `engine` も必ず出す。⚠ これが無いと「省資源と書いてあるのに
  --   MPを使っている」に見え、**必ず誤解されます**。
  --   Phase 1〜9 は判断を変えていません（`legacy` のあいだは説明だけ）。
  add("battle_engine", self.battle_engine)
  local view = self.last_assessment_view
  if view ~= nil then
    add("battle_balance", view.balance)
    add("battle_length", view.length)
    add("battle_turns_to_win", view.turns_to_win)
    add("battle_turns_to_lose", view.turns_to_lose)
    add("battle_tags", view.tags)
    add("battle_plan", view.plan_label)
    add("battle_plan_score", view.plan_score)
    -- ★次点との差。⚠ 小さいなら「次のターンに変わりうる」ということ。
    add("battle_plan_margin", view.plan_margin)
    add("battle_plan_reasons", view.plan_reasons)
    -- ★誰が何をしようとしているか（★全員同じなら区別できていない）
    add("battle_roles", view.roles)
  else
    -- ⚠ 戦闘していない・見立てが取れないときは**全部 nil**。
    --   ★前の戦闘の値を残さない（「いまの値」でなくなるため）。
    for _, key in ipairs({ "battle_balance", "battle_length",
        "battle_turns_to_win", "battle_turns_to_lose", "battle_tags",
        "battle_plan", "battle_plan_score", "battle_plan_margin",
        "battle_plan_reasons", "battle_roles" }) do
      add(key, nil)
    end
  end
  -- ★キーで頼まれた画面側のアクション（2026-08-01）。
  --   ⚠ **通し番号を一緒に出す。** 名前だけだと、同じキーを2回押したときに
  --     画面が「変わっていない」と見て2回目を無視する。
  if self.requested_action ~= nil then
    add("requested_action", self.requested_action)
    add("requested_action_seq", self.requested_action_seq or 0)
  end
  add("manual_latched", self.battle:is_manual_latched())
  add("caution", s.is_caution == true)

  -- パーティ（加入している人だけ）
  local members = {}
  -- ⚠ `self.a` は **DQ2 側（dq2.lua）のフィールド**で、Bridge には無い。
  --   ここで self.a.party と書いて実機で落ちた（2026-07-26）。
  --   Bridge からアドレスを引くときは memory_map を通す。
  local p = self.memory_map.addresses.party
  for _, m in ipairs(self.game:active_party()) do
    local mp     = memory.readbyte(p.fields.current_mp.offset + m.index * p.member_stride)
    local max_mp = memory.readbyte(p.fields.max_mp.offset + m.index * p.member_stride)
    local level  = memory.readbyte(p.fields.level.offset + m.index * p.member_stride)
    -- ★ちから・すばやさ・こうげき力・しゅび力（2026-07-31 / 依頼者の要望）。
    --   ★すばやさは「つよさ」の画面のキャプチャから特定できた
    --     （あかりで9項目すべて一致 / `memory_map.yaml` の説明を参照）。
    --   ⚠ 「ちから」と「こうげき力」は**別物**（こうげき力 = ちから + 武器）。
    --   ⚠⚠ **項目が無い memory_map でも落ちないこと。**
    --     古い設定ファイルのまま起動されると `p.fields.strength` が nil になり、
    --     `attempt to index field 'strength'` で**状態の書き出しごと止まる**。
    --     ★表示のための処理で本体を止めない（ゲームは遊べるべき）。
    --     読めないものは `nil` を書く（Python 側は「届いていない」と出す）。
    local function stat(name)
      local field = p.fields[name]
      if field == nil or field.offset == nil then return nil end
      return memory.readbyte(field.offset + m.index * p.member_stride)
    end
    local strength = stat("strength")
    local agility  = stat("agility")
    local attack   = stat("attack")
    local defense  = stat("defense")
    members[#members + 1] = table.concat({
      '{"name":' .. json_value(m.name),
      '"index":' .. m.index,
      '"hp":' .. m.hp,
      '"max_hp":' .. m.max_hp,
      '"mp":' .. mp,
      '"max_mp":' .. max_mp,
      '"level":' .. level,
      -- ★`json_value` は nil を `null` にする（0 と混ぜない）
      '"strength":' .. json_value(strength),
      '"agility":' .. json_value(agility),
      '"attack":' .. json_value(attack),
      '"defense":' .. json_value(defense),
      '"exp":' .. self.game:experience(m.index),
      '"next_level":' .. json_value(select(1, self.game:next_level(m.index))),
      '"exp_to_next":' .. json_value(select(3, self.game:next_level(m.index))),
      '"alive":' .. (m.alive and "true" or "false"),
      '"poisoned":' .. (m.poisoned and "true" or "false"),
      '"status":' .. m.status .. "}",
    }, ",")
  end
  parts[#parts + 1] = '"party":[' .. table.concat(members, ",") .. "]"
  -- ★ゲーム内で付けた名前の**生バイト列**。文字にするのは Python 側
  --   （文字コード表を Lua に複製しない / `retroux/core/text.py`）
  add("party_name_bytes", self.game:party_name_bytes())

  -- 敵（グループ単位）
  local groups = {}
  for _, g in ipairs(self.game:enemy_groups()) do
    groups[#groups + 1] = string.format('{"id":%d,"count":%d,"name":%s}',
      g.id, g.count, json_value(self.game:monster_name(g.id)))
  end
  parts[#parts + 1] = '"enemy_groups":[' .. table.concat(groups, ",") .. "]"

  -- 敵（個体ごと。HPは 2026-07-26 に特定 / memory_map の enemy_battle）。
  --
  -- ★最大HPは RAM に無い（ROM のステータス表にしかない）ので、
  --   **戦闘開始時のHPを覚えておいて分母にする**。
  --   それがプレイヤーの見ている「満タン」であり、推測の最大値ではない。
  local instances = {}
  for _, e in ipairs(self.game:enemy_instances()) do
    local first = self.enemy_hp_start and self.enemy_hp_start[e.index]
    if first == nil or e.hp > first then
      -- 開始時に取り損ねた場合や、増えた場合は基準を取り直す
      self.enemy_hp_start = self.enemy_hp_start or {}
      self.enemy_hp_start[e.index] = e.hp
      first = e.hp
    end
    -- ★脅威度: 「この敵の一撃で、いちばん危ない味方が何発耐えられるか」。
    --   点数ではなく**発数**にする。点数は基準が無いと読めないが、
    --   「あと2発」は誰でも分かる（指示書の「脅威度」をこの形で満たす）。
    local worst_hits, worst_dmg, worst_name = nil, nil, nil
    for _, m in ipairs(self.game:active_party()) do
      if m.alive then
        local dmg = self.game:estimated_damage(e.id, m.index)
        if dmg ~= nil and dmg > 0 then
          local hits = math.ceil(m.hp / dmg)
          if worst_hits == nil or hits < worst_hits then
            worst_hits, worst_dmg, worst_name = hits, dmg, m.name
          end
        end
      end
    end
    instances[#instances + 1] = string.format(
      '{"index":%d,"id":%d,"name":%s,"hp":%d,"hp_start":%d,"max_hp":%s,'
      .. '"status":%d,"threat_hits":%s,"threat_damage":%s,"threat_target":%s}',
      e.index, e.id, json_value(e.name), e.hp, first,
      json_value(e.max_hp), e.status,
      json_value(worst_hits), json_value(worst_dmg), json_value(worst_name))
  end
  parts[#parts + 1] = '"enemies":[' .. table.concat(instances, ",") .. "]"

  -- いま入力を求められている人（分からなければ null）
  local actor = nil
  if s.in_battle then
    local m = self.game:battle_input_member()
    if m ~= nil then actor = m.name end
  end
  add("actor", actor)
  -- ★戦闘中に**呼び出された敵**も足す（倒しても減らさない）。
  --   `enemy_groups` は生き残りしか映さないので、ここで足しておかないと
  --   撃破のたびに種が消える（2026-07-27 に一度直した話と同じ）。
  if s.in_battle then
    for _, g in ipairs(self.game:enemy_groups()) do
      if g.id ~= nil and g.id ~= 0 then
        local dup = false
        for _, had in ipairs(self.state.battle_species or {}) do
          if had == g.id then dup = true end
        end
        if not dup then
          self.state.battle_species = self.state.battle_species or {}
          self.state.battle_species[#self.state.battle_species + 1] = g.id
        end
      end
    end
  end
  -- ★戦闘の通し番号と、その戦闘で出会った種。
  --   GUI が戦闘中の瞬間を見逃しても切り替えられるようにするため。
  add("battle_seq", self.state.battle_seq)
  do
    local sp = {}
    for _, id in ipairs(self.state.battle_species or {}) do
      sp[#sp + 1] = tostring(id)
    end
    parts[#parts + 1] = '"battle_species":[' .. table.concat(sp, ",") .. "]"
  end
  -- AI が直近に決めたこと
  add("ai_action", self.last_ai_action)
  add("ai_reason", self.last_ai_reason)

  -- ★★ **3人ぶんの判断**（2026-07-31 / 依頼者の指摘）★★
  --   > ３人分表示する（行動者毎に切り替えしない）
  --   ⚠ 加入している人は**必ず1行出す**（判断がまだ無ければ空で出す）。
  --     行が消えると「この人はどうなっているのか」が分からない。
  local decisions = {}
  for _, m in ipairs(self.game:active_party()) do
    local d = (self.ai_decisions or {})[m.index]
    decisions[#decisions + 1] = string.format(
      '{"index":%d,"name":%s,"action":%s,"reason":%s,"turn":%s}',
      m.index, json_value(m.name),
      json_value(d and d.action), json_value(d and d.reason),
      json_value(d and d.turn))
  end
  parts[#parts + 1] = '"ai_decisions":[' .. table.concat(decisions, ",") .. "]"

  -- --- いまどこに居るか（2026-07-29 / 地図のため）---------------------
  --
  -- ★★ 「自分が歩いた所だけ」の地図を作るための材料 ★★
  --   依頼者の決定（Q3）: 完全地図は出さない。**探索を潰さない**。
  --
  -- ⚠ 戦闘中の座標は書かない。戦闘に入ると別の意味の値になりうるし、
  --   戦闘中に歩いてはいないので、記録すると嘘の足跡になる。
  if not s.in_battle then
    -- ⚠ `map_id` は下の `_map_sample` でも使うので、いったん受けます
    local map_id = self.game:map_id()
    add("map_id", map_id)
    local x, y = self.game:map_position()
    add("map_x", x)
    add("map_y", y)
    add("map_data_pointer", self.game:map_data_pointer())
    -- ★画面の色を1マスずつ（地図に写すため）。半径は設定から
    local mapcfg = self.config ~= nil and self.config.map or nil
    local radius = mapcfg ~= nil and mapcfg.view_radius or 7
    add("map_view_radius", radius)
    -- ★いま押されている方向。「進もうとして進めなかった」を観測するため
    add("input_direction", self.game:input_direction())
    -- ★★ 採り直すのは**動いたときだけ**（2026-08-07 / 軽量化指示書 §4.1）★★
    --   ⚠ 出す中身は前と同じです。立ち止まっている間、前回の材料を
    --     そのまま書きます（★画面から見れば何も変わりません）。
    local sample = self:_map_sample(map_id, x, y, radius)
    add("map_colors", sample.colors)
    -- ★タイルIDも渡す（2026-08-01 / 課題 #65）。色より確かで、ぶれない。
    add("map_tiles", sample.tiles)
    -- ★16×16 を組むには4枚とパレット組が要る（2026-08-02 / 課題 #65）
    add("map_cells", sample.cells)
  else
    add("map_id", nil)
    add("map_x", nil)
    add("map_y", nil)
    add("map_data_pointer", nil)
    add("map_view_radius", nil)
    add("input_direction", nil)
    add("map_colors", nil)
    add("map_tiles", nil)
    add("map_cells", nil)
  end

  local body = "{" .. table.concat(parts, ",") .. "}"
  local tmp = self.state_path .. ".tmp"
  local fh = io.open(tmp, "w")
  if fh == nil then return end
  fh:write(body)
  fh:close()
  -- ⚠⚠ **ここで state.json が一瞬だけ消える**（2026-08-01 に判明）。
  --
  --   Windows の `os.rename` は宛先があると失敗するので、先に消すしかない。
  --   その隙間に読むと「ファイルが無い」状態に当たる。
  --
  --   ★画面（`StateReader`）は同じ読み手を使い続けるので**前回の値**が返り、
  --     実害は無い。⚠ ただし**毎回新しく作る**と、まっさらな初期値
  --     （全部 nil）になる。実際 evidence の A-3 がそれで落ちた（偽の NG）。
  --
  --   ⚠ 直すなら Lua だけでは足りない（原子的な置換の手段が無い）。
  --     読む側が「消えている一瞬」を待つ形にしてある。
  os.remove(self.state_path)
  os.rename(tmp, self.state_path)
end

--- ★★★ **書くたびに開き直す**（2026-08-13 / 製品版ログ整理 §25）★★★
---
--- ## ⚠⚠ なぜ変えたか
---
---   ⚠ 以前は起動時に開いたハンドルを持ち続けていた。Python 側が
---     `events.jsonl` を**世代交代**（rename）させると:
---
---       ・Windows では rename が失敗しうる
---       ・成功しても、こちらは**名前が変わった側**に書き続ける
---         （★新しいファイルに何も出なくなる。しかもエラーが起きない）
---
---   ★これは `work/retroux.log` で既に踏んだのと**同じ壊れ方**（`Bridge:log`
---     のコメント参照）。片方だけ直しても意味がない。
---
--- ## ★ 代償は測ってある
---
---     開いたまま : 1.2 us/回
---     開き直す   : 99.0 us/回      （実測 / 5,000 回）
---
---   ⚠ 82 倍だが、**イベントの頻度が低い**ので効かない:
---     実測で 1 戦闘あたり `battle_observation` は 4.7 件、
---     1戦闘の上限は 200 件（`max_rows_per_battle`）。
---     ★最悪でも 1 戦闘で 20ms、通常は 1ms 未満。
---   ⚠ 毎フレーム出すイベントを足すなら、ここを測り直すこと。
function Bridge:emit(event_type, fields)
  if self.events_path == nil then return end
  local parts = {
    '"type":"' .. event_type .. '"',
    '"frame":' .. emu.framecount(),
    '"time":' .. os.time(),
  }
  for k, v in pairs(fields or {}) do
    parts[#parts + 1] = '"' .. k .. '":' .. json_value(v)
  end
  local fh = io.open(self.events_path, "a")
  if fh == nil then return end          -- ⚠ 書けなくても本体は止めない
  fh:write("{" .. table.concat(parts, ",") .. "}\n")
  fh:close()
end

-- IDの集合を1行1件のテキストから読む。遭遇済みと警戒リストで共用する。
-- 戻り値: 集合, 読めなかった行数
--
-- ★数字だけの行以外は捨てる。改行が落ちて "2" と "4" が "24" に
--   繋がった実害があったため、素直に tonumber せず形を検査する。
--- モンスターIDとして意味のある値か。
---
--- ⚠⚠⚠ **読む側と書く側で規則が違っていました**（2026-08-08 に判明）。
---
---   読む側 … `id >= 1 and id <= 255`
---   書く側 … ★**何も見ていなかった**
---
---   その結果 `work/encountered.txt` の先頭に `0` が入り、
---   ⚠ 起動のたびに「読めない行が 1 件ありました」と出ていました
---   （★依頼者の画面写真 `input/cap1.bmp`）。
---
---   ⚠ ID 0 は「敵が居ない枠」です。DB 側にも空IDが多数あります
---     （`docs/30-command-log.md` 2026-07-22「188件中178件が空ID」）。
---     ★そこから Python 経由で流れ込んでいました。
---
--- → ★規則をここ**1か所**に寄せます（⚠ 測り方を2か所に書かない）。
local function valid_monster_id(id)
  return type(id) == "number" and id >= 1 and id <= 255 and id % 1 == 0
end

local function load_id_set(path)
  local set, broken = {}, 0
  local fh = io.open(path, "r")
  if fh == nil then return set, 0 end
  for line in fh:lines() do
    local digits = line:match("^%s*(%d+)%s*$")
    local id = digits and tonumber(digits)
    if valid_monster_id(id) then
      set[id] = true
    elseif line:match("%S") then
      broken = broken + 1
    end
  end
  fh:close()
  return set, broken
end

-- IDの集合を丸ごと書き直す。遭遇済みと警戒リストで共用する。
--
-- ★追記(append)ではなく毎回書き直す理由:
--   追記の途中でプロセスが落ちると改行が失われ、次の追記と繋がって
--   別のIDに化ける。実際に "2" と "4" が "24" になり、
--   おおナメクジの登録が消えて存在しないID 24 が登録された。
--   一時ファイルに書いて置き換えれば、壊れても「古い完全な内容」が残る。
local function save_id_set(path, set)
  local ids = {}
  for id in pairs(set) do ids[#ids + 1] = id end
  table.sort(ids)

  local tmp = path .. ".tmp"
  local fh = io.open(tmp, "w")
  if fh == nil then return end
  for _, id in ipairs(ids) do fh:write(tostring(id) .. "\n") end
  fh:close()

  -- os.rename は既存ファイルがあると Windows では失敗するため先に消す。
  os.remove(path)
  os.rename(tmp, path)
end

--- 読めない行があったら**その場で書き直す**（2026-08-08）。
---
--- ⚠⚠ 直さないと、⚠ **起動のたびに同じ警告が出続けます**。
---   実際、依頼者の画面（`input/cap1.bmp`）に毎回出ていました。
---   ★中身（`0`）は過去の不具合が書いたもので、直しようがありません。
---
--- ⚠ 黙って直しません。★何件どうしたかを画面へ出します。
function Bridge:_repair_id_set(path, set, broken, code, label)
  if broken <= 0 then return end
  save_id_set(path, set)
  self.warnings[#self.warnings + 1] = {
    code = code,
    message = string.format(
      "%sに読めない行が %d 件ありました。★その行を除いて書き直しました（%s）",
      label, broken, path),
  }
end

function Bridge:_load_encountered_cache()
  local set, broken = load_id_set(self.encountered_path)
  self.encountered = set
  self:_repair_id_set(self.encountered_path, set, broken,
    "encountered_cache_broken", "遭遇済みキャッシュ")
end

-- 警戒リスト: **逃げた/負けた相手**。次回以降も等速＋手動のままにする。
--
-- なぜ必要か（依頼者の指摘より）:
--   遭遇済みの登録は戦闘開始時に行う（見た＝初見体験は済んだ、という理屈）。
--   そのため**逃げた相手も遭遇済みになり、次回は倍速＋自動たたかうが有効**になる。
--   ところが自動入力は「たたかう」しか押さないので逃げるという選択ができない。
--   「勝てないから逃げた」相手に自動で殴りかかることになり、
--   DEV-8（ボスに敗北後の再戦）と同じ穴だった。
--   実ログでは141戦闘のうち34戦が勝利表示なし（逃走/敗北）で、
--   その相手（Big Cobra など）はすべて遭遇済みに入っていた。
--
--   ビジョンは「難易度と初見体験には触れない」。逃げるのはプレイヤーの
--   難易度判断なので、それを自動戦闘で上書きしない。
--   その相手に**勝った時点で解除**する（もう勝てるのだから倍速でよい）。
function Bridge:_load_caution_cache()
  local set, broken = load_id_set(self.caution_path)
  self.caution = set
  self:_repair_id_set(self.caution_path, set, broken,
    "caution_cache_broken", "警戒リスト")
end

-- 逃走/敗北した相手を警戒リストへ加える。戻り値: 新たに加えたID
function Bridge:_note_retreat(ids)
  local added = {}
  for _, id in ipairs(ids or {}) do
    if not self.caution[id] then
      self.caution[id] = true
      added[#added + 1] = id
    end
  end
  if #added > 0 then save_id_set(self.caution_path, self.caution) end
  return added
end

-- 勝った相手を警戒リストから外す。戻り値: 外したID
function Bridge:_note_victory(ids)
  local cleared = {}
  for _, id in ipairs(ids or {}) do
    if self.caution[id] then
      self.caution[id] = nil
      cleared[#cleared + 1] = id
    end
  end
  if #cleared > 0 then save_id_set(self.caution_path, self.caution) end
  return cleared
end

-- 加入者のレベルを控える。レベルアップの検出に使う。
-- レベルは $063E（間隔 0x12）。画面の「あかり LV8」と一致を確認済み。
function Bridge:_level_snapshot()
  local out = {}
  local p = self.memory_map.addresses.party
  local spec = p.fields.level
  if spec == nil then return out end
  for _, m in ipairs(self.game:active_party()) do
    out[m.index] = memory.readbyte(spec.offset + m.index * p.member_stride)
  end
  return out
end

-- レベルが上がったら警戒リストを空にする。
--
-- ★理由: 逃げたのは「そのとき弱かった」から。強くなったなら再挑戦させる。
--   これが無いと一度入った相手は勝つまで抜けられず、しかも警戒中は
--   自動入力が切れるため常に手動＝「プレイヤーが操作していた」と判定され、
--   その戦闘で敵が逃げても抜けられない。行き止まりになっていた。
function Bridge:_check_level_up()
  if self.caution_cfg.clear_on_level_up == false then return end
  local now = self:_level_snapshot()
  if self.levels == nil then self.levels = now; return end

  local leveled = nil
  for index, lv in pairs(now) do
    local before = self.levels[index]
    if before ~= nil and lv > before then leveled = { index = index, from = before, to = lv } end
  end
  self.levels = now
  if leveled == nil then return end

  local cleared = 0
  for _ in pairs(self.caution) do cleared = cleared + 1 end
  if cleared > 0 then
    self.caution = {}
    save_id_set(self.caution_path, self.caution)
    self:log(string.format(
      "レベルが上がったので警戒リストを空にしました（%d件解除 / LV%d -> %d）",
      cleared, leveled.from, leveled.to), "caution reset by level up")
    self:emit("caution_reset", { reason = "level_up", cleared = cleared })
  end
end

-- 強制AUTO の入り切り。
--
-- ★安全機構（危険状態 / 初遭遇 / 警戒中 / 手動ラッチ）を意図的に潰す。
--   利用者が「消化試合を早く終わらせる」ために明示的に入れるスイッチなので、
--   黙って効かせず、ログと画面に必ず出す。
function Bridge:_set_force_auto(on)
  -- ★★ 状態は `battle_controller` が持つ（リファクタ §4.4）★★
  local changed = self.battle:set_force_auto(on, function(now)
    -- ★同じキーのトグルなので「いまどちら側か」を必ず画面に出す。
    self:notify("FORCE AUTO: " .. (now and "ON" or "OFF"))
  end)
  if changed then self:emit("force_auto", { enabled = on == true }) end
end

function Bridge:_set_auto_enabled(on, why)
  if self.battle:set_auto(on, why) then
    self:emit("auto_enabled", { enabled = on == true, source = why })
  end
end

function Bridge:_toggle_auto_from_hotkey()
  local on = self.battle:toggle_from_hotkey(self:_safety_context(),
    function(now) self:notify("FORCE AUTO: " .. (now and "ON" or "OFF")) end)
  self:notify("AUTO: " .. (on and "ON" or "OFF"))
  self:emit("auto_enabled",
            { enabled = self.battle:is_auto_enabled(), source = "キーボード" })
end

--- 安全停止の判断に要るものを1つの表にまとめる。
---
--- ★★ `battle_controller` は**ゲームを覗かない**（リファクタ §4.2）★★
---   覗くとゲームの内部構造を知ることになり、別のゲームへ持っていけない。
function Bridge:_safety_context()
  local s = self.state
  return {
    danger = s.danger, danger_reason = s.danger_reason,
    first_encounter = s.first_encounter,
    is_boss = s.is_boss, is_caution = s.is_caution,
  }
end

--- いまの戦況の見立て（2026-08-04 / 戦闘AI再設計 Phase 2）。
---
--- ★★ **Phase 2 では「読むだけ」です。** ★★
---   `battle_assessment.lua` が現行の安全判定をそのまま写します。
---   ⚠ ここで判断を変えていません。推計ターン・脅威度は Phase 4 です。
---
--- ★理由ログ（§17）に出すため、また Phase 4 の足場として先に作ります。
function Bridge:_assess_battle()
  if self.battle_assessment == nil or self.battle_types == nil then
    return nil
  end
  local party = {}
  if self.game ~= nil and self.game.active_party ~= nil then
    party = self.game:active_party()
  end
  local got = self.battle_assessment.from_safety(
    self.battle_types, self:_safety_context(), party)

  -- ★★ 推計ターン・脅威・戦況（2026-08-05 / Phase 4）★★
  --   ⚠⚠ **見立てるだけです。判断は変えていません。**
  --     狙う順へ効かせるのは Phase 5 以降です。
  local cfg = ((self.config or {}).auto_input or {}).assessment
  if cfg ~= nil and self.game.enemy_groups_hp ~= nil then
    local enemies = self:_assess_enemy_view()
    if #enemies > 0 then
      got = self.battle_assessment.estimate(
        self.battle_types, party, enemies, cfg, got)
    end
  end
  return got
end

--- 見立てに渡す敵の姿（★ROM の図鑑と、いまのHPを合わせる）。
---
--- ⚠ 図鑑に無い敵は `stats` を **nil のまま**にします。
---   ★「弱い」ではなく「分からない」として扱われます。
---
--- ⚠⚠ **名前を分けてある**（2026-08-11 に発覚した不具合の再発防止）★★
---   以前はこれも `_enemy_view` という名前で、下の方（道具・攻撃用の
---   `_enemy_view`）に**上書きされて呼ばれていませんでした**。あちらは
---   `stats`（attack 等）を付けないので、戦況が**毎回「能力が分からない」**に
---   なっていました（依頼者の実機指摘「既知の敵なのに unknown_enemy」）。
---   ★見立て用はこちら（ROM の `monster_stats` を丸ごと `stats` に載せる）。
function Bridge:_assess_enemy_view()
  local out = {}
  local ok_, groups = pcall(function()
    return self.game:enemy_groups_hp()
  end)
  if not ok_ or groups == nil then return out end
  -- ⚠⚠ **`addresses` の下ではありません**（2026-08-06 に踏んだ）。
  --   ★`monster_stats` は memory_map の**トップレベル**です。
  --     間違えると全部 nil になり、実機で「1体の能力が分からない」が
  --     毎戦闘出ました（★落ちないので気づきにくい）。
  local stats = self.memory_map.monster_stats
    or (self.memory_map.addresses or {}).monster_stats or {}
  for _, g in ipairs(groups) do
    local info = stats[g.id]
    out[#out + 1] = {
      id = g.id, name = g.name or tostring(g.id),
      hp = g.hp, stats = info,
      -- ★回復する敵・止めてくる敵か（★図鑑の行動から分かる範囲で）
      heals = (info ~= nil and info.heals == true) or nil,
      disables = (info ~= nil and info.disables == true) or nil,
    }
  end
  return out
end

--- ★見立てをログへ1行で出す（指示書 §17・Phase 4 完了条件5）。
---
--- ⚠ 毎ターン出すと埋まるので、**戦闘の始めに1回だけ**。
function Bridge:_log_assessment()
  local a = self:_assess_battle()
  if a == nil then return end
  local head = string.format("[戦況] %s", tostring(a.balance))
  if a.enemy_defeat_turns ~= nil and a.party_collapse_turns ~= nil then
    head = head .. string.format("（敵撃破 %.1fターン / 味方崩壊 %.1fターン）",
      a.enemy_defeat_turns, a.party_collapse_turns)
  end
  if #a.tags > 0 then
    head = head .. " / " .. table.concat(a.tags, "・")
  end
  if #a.unknown > 0 then
    head = head .. " / ⚠ " .. table.concat(a.unknown, "・")
  end
  self:log(head, "assessment", "DEBUG")

  -- ★★ どの戦術が選ばれるかも出す（2026-08-06 / Phase 5・§17）★★
  --   ⚠⚠ **選ぶだけで、まだ効かせていません。**
  --     ★「もし layered だったらこうする」を先に見せることで、
  --       効かせる前に人が確かめられます。
  if self.tactics_selector ~= nil then
    local choice = self.tactics_selector.choose(
      self.battle_types, a, self:_mission(), self.current_plan,
      ((self.config or {}).auto_input or {}).tactics_selector)
    -- ★画面へ渡す用に取っておく（Phase 9）。⚠ choice が nil でも
    --   ★戦況までは渡す（「分からないので選ばない」も情報です）。
    self:_remember_assessment(a, choice)
    -- ★統合の材料（2026-08-14 / RX-0040）。⚠ ここでは出さない
    self.start_view = self.start_view or {}
    if choice == nil then
      self.start_view.plan = nil
      self:log("[戦術] ⚠ 戦況が分からないので選びません", "plan: unknown", "DEBUG")
    else
      self.current_plan = choice.id
      local margin = self.tactics_selector.margin(choice)
      self.start_view.plan = choice.label
      self.start_view.plan_score = choice.score
      self.start_view.plan_margin = margin
      self:log(string.format(
        "[戦術] %s（適合度 %.1f%s）%s",
        choice.label, choice.score,
        margin and string.format(" / 次点との差 %.1f", margin) or "",
        -- ⚠⚠ **固定文言にしない**（2026-08-07 に踏んだ）。
        --   ★`layered` にしても「まだ効かせていません」と出ていて、
        --     ⚠ 実機ログを読むとき**私自身が迷いました**。
        self:_use_layered() and "★この戦術で判断します"
          or "※まだ効かせていません"),
        "plan: " .. choice.id, "DEBUG")
      self:_log_contributions(a, choice.directive)
      -- ★★★ **このターンの指示として固定する**（Phase 10A / 2026-08-07）★★★
      --
      --   相談回答の指摘:
      --   > HPが1変わるたびに戦術を再評価するより、ターン単位の方が
      --   > 挙動が安定し、戦術の振動も防げる
      --
      -- ⚠⚠ **同じターンでは上書きしません。** ★行動の途中で指示が
      --   変わると、「1フレーム目は許可・2フレーム目は拒否」になり、
      --   呪文メニューの途中で放棄する事故が起きます。
      if self.turn_directive_turn ~= self.turn_no then
        self.turn_directive_turn = self.turn_no
        self.turn_directive = choice.directive
      end
    end
    -- ★材料がそろったので、戦闘開始の1行を出す（2026-08-14 / RX-0040）
    self:_log_battle_start_summary()
  end
end

--- ★★★ 戦闘開始を**1行**にまとめる（2026-08-14 / RX-0040）★★★
---
--- ## ⚠⚠ なぜまとめるか
---
---   実機（2026-08-14 / 16分・4戦闘）で、戦闘のたびに **INFO が3行**出ていた:
---
---       [INFO] lua [敵] しびれくらげ×2
---       [INFO] lua [戦術] 省資源（適合度 4.5 / 次点との差 0.5）★この戦術で判断します
---       [INFO] lua [役割] lorasia:attack(2.0) / samaltria:attack(1.1) / ...
---
---   ★1戦闘3行 × 4戦闘 = **12行**（その日の INFO 39 行の 31%）。
---   ⚠ 判定は3件とも **MERGE** だったが、**実装していなかった**
---     （`apply_lua_log_levels.py` の対応表に MERGE が無かった）。
---
--- ## ★ 出す形
---
---       戦闘開始: しびれくらげ×2 / 戦術=省資源 / 役割=攻攻道
---
---   ⚠ 詳細（適合度・次点との差・点数）は DEBUG の3行に残る。
---     ★調べたいときは `logging.mode: diagnostic`。
---
--- ## ⚠ 1戦闘に1回だけ
---
---   見立ては**毎ポーリング**走る。★印を置かないと同じ行が並ぶ
---   （⚠ 「鳴りすぎも壊れ方」を何度も踏んでいる）。
function Bridge:_log_battle_start_summary()
  local v = self.start_view
  if v == nil then return end
  -- ★1戦闘1回（⚠ battle_seq が変わるまで出さない）
  local seq = (self.state or {}).battle_seq
  if self.start_logged_seq == seq then return end
  self.start_logged_seq = seq

  local parts = {}
  parts[#parts + 1] = v.enemies or "⚠ 敵を読めていません"
  if v.plan ~= nil then
    parts[#parts + 1] = "戦術=" .. tostring(v.plan)
  end
  if v.roles ~= nil then
    -- ★役割は短くする（⚠ 点数までは DEBUG の行にある）
    parts[#parts + 1] = "役割=" .. tostring(v.roles):gsub("%(.-%)", "")
  end
  self:log("戦闘開始: " .. table.concat(parts, " / "), "battle start")
end

--- ★このターンの指示（⚠ 無ければ nil）。
--
-- ⚠⚠ **`engine: legacy` のあいだは nil を返します。** ★これが
--   「まだ効かせていない」の実体です。設定を変えたときだけ効きます。
function Bridge:_current_directive()
  if not self:_use_layered() then return nil end
  -- ⚠⚠⚠ **ターン番号で捨ててはいけません**（2026-08-07 に踏んだ）★★★
  --
  --   最初はここで `turn_directive_turn ~= turn_no` なら nil を返して
  --   いました。⚠ ところが**見立てはターンが進む前**に走り、
  --   **行動の入力は進んだ後**に来ます。★番号が食い違い、
  --   実機で拒否が**1件も効きませんでした**（20:46 の3戦で確認）。
  --
  --   ★相談回答の意図は「**同じターン中に上書きしない**」であって、
  --     ⚠ 「番号が変わったら捨てる」ではありません。
  --   → 最後に見立てた指示を**保持**し、上書きだけ抑えます
  --     （★上書きの抑止は `_log_assessment` 側にあります）。
  --
  -- ⚠ 戦闘が終われば `_on_battle_end` が消すので、持ち越しません。
  return self.turn_directive
end

--- ★★★ その行動をしてよいか（Phase 10A の中核）★★★
--
-- 相談回答の指摘:
--   > layered の拒否判定は「行動開始前」だけ行う。
--   > 一度 claim を開始したら、完了または明示的に安全な abort までは
--   > その claim に処理を任せる。
--
-- ⚠⚠ **途中で呼ばないこと。** ★呪文は「メニュー移動 → 一覧 → カーソル →
--   A → 敵選択 → A」と**複数フレームにまたがります**。途中で拒否すると
--   別の claim が入力して事故ります。
--
-- 戻り値: `(してよいか, 断る理由)`
function Bridge:_may_act(kind)
  local d = self:_current_directive()
  if d == nil or d.may_act == nil then return true, nil end
  if d:may_act(kind) then return true, nil end
  return false, string.format("戦術「%s」により %s を使いません",
    tostring(d.primary_plan or "?"), tostring(kind))
end

--- 補助行動の候補をログへ出す（2026-08-08 / Phase 7・8）。
---
--- ⚠⚠ **候補を出すだけで、まだ効かせていません。**
---   ★Phase 5（戦術）・Phase 6（役割）と同じ段です。
---   ⚠ 効かせるときは Phase 10A と同じ規律（**拒否点は行動開始前の1か所**）
---     を守ってください。★`layered_veto_test.lua` が数を見張っています。
---
--- ★★ 実機で確かめられるようにするのが目的です。
---   ⚠ 「作ったけれど一度も通っていない」を避けます
---     （`docs/design/handoff-20260807.md` §5 の1番・6番）。
function Bridge:_log_support(assessment)
  if self.support_plan == nil or self.battle_types == nil then return end
  local cfg = self.support_config or {}
  local spells = cfg.spells
  if type(spells) ~= "table" then return end

  local enemies = self.game.enemy_instances ~= nil
    and self.game:enemy_instances() or {}
  local alive = 0
  for _, m in ipairs(self.game:active_party()) do
    if m.alive then alive = alive + 1 end
  end

  -- ★誰が唱えられるかは人によって違うので、**人ごとに**見ます。
  local lines = {}
  for _, m in ipairs(self.game:active_party()) do
    if m.alive then
      local usable = {}
      for id, effect in pairs(spells) do
        -- ⚠ 覚えているか（★覚えていない呪文を候補にしない）
        local row = self.game.find_spell_pos ~= nil
          and self.game:find_spell_pos(id, m.index, "battle") or nil
        if row ~= nil then
          local info = self.game.spell_info ~= nil
            and self.game:spell_info(id) or nil
          usable[#usable + 1] = {
            id = id,
            name = (info and info.name) or self.game:spell_name(id),
            mp_battle = (info and info.mp_battle) or 0,
            effect = effect,
          }
        end
      end
      if #usable > 0 then
        local best = self.support_plan.evaluate(self.battle_types, {
          spells = usable, assessment = assessment, enemies = enemies,
          alive_allies = alive, mp = self:_mp_of(m.index),
          risk = cfg.risk, damage = self.damage_estimate,
        })
        if best[1] ~= nil then
          lines[#lines + 1] = string.format("%s:%s（%s）",
            tostring(m.name), tostring(best[1].name), best[1].reason)
        end
      end
    end
  end

  if #lines > 0 then
    self:log("[補助] " .. table.concat(lines, " / ")
      .. "　※まだ効かせていません", "support candidates", "DEBUG")
  end
end

--- 各人が「この番どう貢献できるか」を出す（2026-08-07 / Phase 6・§17）。
--
-- ⚠⚠ **候補を出すだけで、まだ効かせていません。**
--   ★「もし layered だったら誰が何をするか」を先に見せます。
function Bridge:_log_contributions(assessment, directive)
  if self.actor_roles == nil or self.battle_types == nil then return end

  -- ★いちばん減っている味方（⚠ 回復の要否はこれで決まる）
  local hurt, worst = nil, 1.0
  for _, m in ipairs(self.game:active_party()) do
    if m.hp ~= nil and m.max_hp ~= nil and m.max_hp > 0 then
      local ratio = m.hp / m.max_hp
      if ratio < worst then hurt, worst = m, ratio end
    end
  end

  local parts = {}
  for _, m in ipairs(self.game:active_party()) do
    -- ★★ **できることを実測して渡す**（⚠ 名前で決めない）。
    local max_mp = self:_max_mp_of(m.index)
    local caps = {
      max_mp = max_mp,
      mp = self:_mp_of(m.index),
      attack = self:_attack_of(m.index),
      role_weight = self:_role_weight(m),
      -- ⚠ MPがあるだけでは足りない。★覚えているかを見る。
      can_heal = self:_can_heal(m),
      can_attack_spell = self:_attack_spell_enabled(m),
      -- ⚠ 第1引数は**添字**、第2引数が本人（2026-08-07 に間違えた）。
      --   ★`m` を渡すと `inventory()` の中で「テーブルに掛け算」で落ちます。
      can_use_item = (self:_find_battle_item(m.index, m) ~= nil),
    }
    local list = self.actor_roles.contributions(self.battle_types, {
      actor = m.name, caps = caps, hurt_ally = hurt,
      directive = directive, assessment = assessment,
    })
    local top = list[1]
    if top ~= nil then
      parts[#parts + 1] = string.format("%s:%s%s", tostring(m.name),
        tostring(top.action),
        top.contribution_score
          and string.format("(%.1f)", top.contribution_score) or "(?)")
      -- ★★ 機械処理できる形でも覚える（2026-08-13 / §6・§9）★★
      --
      --   ⚠ これまで役割は **human log の `[役割]` にしか無かった**ため、
      --     §9 の「役割分布」を数えられなかった（★文面を grep するしかない）。
      --
      --   ⚠ **events を膨らませない**ため、持つのは1人につき:
      --       ・一番の役割（`action`）
      --       ・その点数（`score`）
      --       ・2番手との差（`margin`）★判断が僅差だったかが分かる
      --     ⚠ 候補の全件は持たない（★1戦闘で数十件になる）。
      self.role_view = self.role_view or {}
      local second = list[2]
      self.role_view[m.name] = {
        action = top.action,
        score = top.contribution_score,
        margin = (top.contribution_score and second
                  and second.contribution_score)
                 and (top.contribution_score - second.contribution_score)
                 or nil,
        candidates = #list,
      }
    end
  end

  if #parts > 0 then
    -- ★統合の材料（2026-08-14 / RX-0040）
    self.start_view = self.start_view or {}
    self.start_view.roles = table.concat(parts, " / ")
    self:log("[役割] " .. table.concat(parts, " / ")
      .. (self:_use_layered() and "　★参考（拒否のみ効きます）"
          or "　※まだ効かせていません"), "contributions", "DEBUG")
  end
  -- ★画面へ渡す用に取っておく（Phase 9）。⚠ 無ければ nil のまま。
  self.last_assessment_view = self.last_assessment_view or {}
  self.last_assessment_view.roles =
    (#parts > 0) and table.concat(parts, " / ") or nil

  -- ★★ 補助行動の候補（2026-08-08 / Phase 7・8）★★
  --   ⚠ 落ちても本体を止めない。★ただし**理由は1回だけ残す**
  --     （2026-08-07 に `pcall` が握りつぶして「0件」になった / §5 の1番）。
  local ok_support, err = pcall(function() self:_log_support(assessment) end)
  if not ok_support and not self.support_log_failed then
    self.support_log_failed = true
    self:log("⚠ 補助行動の見立てに失敗しました（表示だけの機能なので続けます）: "
      .. tostring(err), "support log failed", "WARNING")
  end
end

--- 画面へ渡す「いまの見立て」を組み直す（2026-08-07 / Phase 9）。
--
-- ⚠⚠ **分からない項目は nil のまま置く。** ★0 で埋めない。
function Bridge:_remember_assessment(a, choice)
  local view = { roles = (self.last_assessment_view or {}).roles }
  if a ~= nil then
    view.balance = a.balance
    view.length = a.length
    -- ⚠⚠ **項目名を推測で書かない**（2026-08-07 に踏んだ）。
    --   ★`turns_to_win` と書いていて、実機で `null` になりました。
    --     正しくは `enemy_defeat_turns` / `party_collapse_turns` です。
    --   ⚠ ログには「敵撃破 1.3ターン」と出ていたので、**画面だけが
    --     空欄**という気づきにくい形になりました。
    view.turns_to_win = a.enemy_defeat_turns
    view.turns_to_lose = a.party_collapse_turns
    if a.tags ~= nil and #a.tags > 0 then
      view.tags = table.concat(a.tags, "・")
    end
  end
  if choice ~= nil then
    view.plan_label = choice.label
    view.plan_score = choice.score
    view.plan_margin = self.tactics_selector
      and self.tactics_selector.margin(choice) or nil
    local d = choice.directive
    if d ~= nil and d.reasons ~= nil and #d.reasons > 0 then
      view.plan_reasons = table.concat(d.reasons, "／")
    end
  end
  self.last_assessment_view = view
end

function Bridge:_set_turbo(on, why)
  -- ★★ 状態は `speed_controller` が持つ（リファクタ §4.4）★★
  --   ⚠ ここで AUTO を触らない（2026-07-31 の指示書 §5.1）。
  if self.speed:set_enabled(on, why) then
    self:emit("turbo", { enabled = on == true, source = why })
  end
end

function Bridge:_force_auto_active()
  return self.battle:force_auto_active(self.state.is_boss)
end

function Bridge:_load_hotkeys()
  local made = {}

  -- 1. config.yaml の `hotkeys`（まんたん・補充など、まだアクション化して
  --    いないもの）。⚠ こちらは1キーだけなので表に包む。
  for action, key in pairs(self.config.hotkeys or {}) do
    if type(key) == "string" and key ~= "" then
      made[action] = { key }
    end
  end

  -- 2. 生成されたキーバインド。★**あれば優先**（利用者が設定画面で直せる）。
  local path = self.root .. "/work/generated/keybindings.lua"
  local chunk = loadfile(path)
  if chunk == nil then
    self:log("キーバインドの生成ファイルがありません（config.yaml の hotkeys"
             .. " を使います）: " .. path, "keybindings: fallback", "WARNING")
    return made
  end
  local ok, data = pcall(chunk)
  if not ok or type(data) ~= "table" or type(data.keys) ~= "table" then
    self:log("キーバインドを読めませんでした（config.yaml の hotkeys を"
             .. "使います）: " .. tostring(data), "keybindings: broken", "WARNING")
    return made
  end
  for action, keys in pairs(data.keys) do
    if type(keys) == "table" then made[action] = keys end
  end
  -- ★Lua が自分で実行するアクション。それ以外は画面へ渡す。
  self.hotkey_handled = data.handled or {}
  return made
end

--- 修飾キーの名前。★`input.get()` が返す綴り（lua-engine.cpp:2500 で確認）。
--- ⚠ 設定側は `Ctrl` と書くが、FCEUX は `control` と返す。
local MODIFIER_NAMES = { ctrl = "control", control = "control",
                         shift = "shift", alt = "alt" }

--- `"Ctrl+Shift+M"` を `基のキー, {control=true, shift=true}` に分ける。
local function split_hotkey(spec)
  local want = {}
  local base = spec
  while true do
    local head, rest = string.match(base, "^([^+]+)%+(.+)$")
    if head == nil then break end
    local name = MODIFIER_NAMES[string.lower(head)]
    if name == nil then break end       -- 修飾ではない（キー名に + が入る）
    want[name] = true
    base = rest
  end
  return base, want
end

--- 修飾キーの状態が、求めているものと**ぴったり**同じか。
---
--- ★★ 余っていても足りなくても駄目（2026-08-01 / 課題 #48）★★
---
---   ⚠⚠ これが無いと `Ctrl+M` が「M」として発火する。実機で
---     「メモ（Ctrl+M）を押すと まんたん が動く」が起きていた。
---   ⚠ 逆に、`M` の割り当てが `Ctrl+M` でも発火してしまう。
local function modifiers_match(pressed, want)
  for _, name in pairs(MODIFIER_NAMES) do
    local now = (pressed[name] == true)
    if now ~= (want[name] == true) then return false end
  end
  return true
end

Bridge.split_hotkey = split_hotkey
Bridge.modifiers_match = modifiers_match

-- ホットキーの押下（立ち上がり）を見て、対応する操作を要求する。
--
-- ★押しっぱなしで連続実行しないよう、前フレームの状態と比べる。
--   input.get() は numlock のようなロック状態も true で返すため、
--   「今 true」だけを条件にすると起動直後に暴発する。
--
-- 値が true のものだけをキーとして扱う（xmouse など数値項目が混ざる）。
function Bridge:_poll_hotkeys()
  if input == nil or input.get == nil then return end
  local pressed = input.get()
  if type(pressed) ~= "table" then return end

  -- ★1つのアクションに複数のキーを割り当てられる（設定はリスト）。
  for action, keys in pairs(self.hotkeys) do
    for _, key in ipairs(keys) do
      -- ★★ 修飾キーを見る（2026-08-01 / 課題 #48・#56）★★
      --   ⚠⚠ `input.get()` は `"Ctrl+M"` という名前を**返さない**。
      --     基のキー（M）と修飾（control）を別々に見るしかない。
      --     これが無かったため、修飾つきの割り当ては一度も発火せず、
      --     代わりに**修飾なしの同じ文字が発火**していた。
      local base, want = split_hotkey(key)
      local now = (pressed[base] == true) and modifiers_match(pressed, want)
      local was = (self.hotkey_prev[key] == true)
      if now and not was then
        -- ★状態の切り替えは単発の操作要求にしない。
        -- action_driver は precheck/tick/done を持つ「実行するもの」を扱うので、
        -- 単なるスイッチをそこへ流すと余計な仕組みが要る。ここで即座に反映する。
        -- ★AUTO は同じキーで入り切りする（トグル）。依頼者の要望:
        --   「Auto終了はもう１回Aでもいいや。トグルにしよう。」
        --   解除用の別キーを覚える必要がなく、FCEUX の予約キーとの衝突も避けられる
        --   （Q は MOVIE IS READ+WRITE、M と R も予約済みだった）。
        --
        -- ⚠⚠ **速度には触らない**（2026-07-31 の指示書 §3.1）。
        --   このキーが切り替えるのは「誰が操作するか」だけ。
        --
        -- ★★ アクション名で分岐する（2026-08-01 の指示書 §15.1）★★
        --   ⚠ `force_auto` は config.yaml の古い名前。設定画面から来るのは
        --     `toggle_auto`。**両方受ける**（古い設定のままの人を切らない）。
        -- release_auto は「切る専用」のキーとして残す（設定していれば使える）。
        if action == "toggle_auto" or action == "force_auto" then
          self:_toggle_auto_from_hotkey()
        elseif action == "toggle_turbo" then
          -- ★高速化は AUTO とは別の軸（2026-07-31 の指示書 §2）。
          self:_set_turbo(not self.speed:is_enabled(), "キーボード")
          self:notify("TURBO: " .. (self.speed:is_enabled() and "ON" or "OFF"))
        elseif action == "emergency_manual" then
          -- ★いますぐ手動へ。⚠ トグルではない（危ないときに確実に止める）。
          self:_set_auto_enabled(false, "すぐ手動へ")
          self:_set_force_auto(false)
          self:notify("MANUAL")
        elseif action == "release_auto" then
          self:_set_auto_enabled(false, "解除キー")
          self:_set_force_auto(false)
        elseif (self.hotkey_handled or {})[action] == nil
               and self.config.hotkeys[action] == nil then
          -- ★★ **画面がやるアクション**（地図を開く 等 / 2026-08-01）★★
          --
          --   ⚠⚠ キーを拾えるのは Lua だけ。遊んでいる間フォーカスは
          --     FCEUX にあるので、**画面側はキーを1つも見られない**。
          --     当初これを「画面の担当」として渡していなかったため、
          --     G キーが押しても何も起きない状態だった（実機で判明）。
          --
          --   ★ここでは実行しない（窓を作るのは Qt の仕事）。
          --     「押された」とだけ書き、画面が拾って実行する。
          --
          -- ★★ **同じものを続けて投げない**（2026-08-01 / 課題 #56）★★
          --
          --   ⚠ 実機で「ホットキー F」が2秒に11回出た。`toggle_map_follow`
          --     は押されるたびに追従を**反転**するので、11回反転して
          --     どちらで止まったか分からなくなる（害がある）。
          --   ⚠ なぜ立ち上がりが何度も立つのかは**まだ分かっていない**。
          --     ★だが原因が何であれ、**同じ要求を投げ直すのは間違い**。
          --   ★兄弟の分岐（`pending_action`）には既にこの守りがある。
          --     ここだけ抜けていた。
          --
          --   ⚠ 画面が落ちている場合に永久に無視しないよう、
          --     しばらく返事が無ければ諦めて次を通す。
          local waited = self.gui_action_frames or 0
          local outstanding = (self.requested_action ~= nil)
                              and (waited < self.GUI_ACTION_TIMEOUT_FRAMES)
          if outstanding then
            -- ★黙って捨てない。何を無視したかを書く
            self:log(string.format(
              "ホットキー %s を無視しました（%s が未処理 / %d フレーム待ち）",
              key, tostring(self.requested_action), waited),
              "hotkey gui busy", "DEBUG")
          else
            self.requested_action = action
            self.requested_action_seq = (self.requested_action_seq or 0) + 1
            self.gui_action_frames = 0
            self:log(string.format("ホットキー %s: %s を画面へ渡しました",
                                   key, action), "hotkey -> gui " .. action, "DEBUG")
          end
        elseif self.pending_action == nil then
          self.pending_action = action
          self:log(string.format("ホットキー %s: %s を要求しました", key, action),
                   "hotkey " .. tostring(action), "DEBUG")
        else
          -- 直前の要求がまだ処理されていない。取りこぼしを黙って捨てない
          self:log(string.format(
            "ホットキー %s を無視しました（%s の要求が未処理）", key,
            tostring(self.pending_action)), "hotkey busy", "DEBUG")
        end
      end
      self.hotkey_prev[key] = now
    end
  end
end

-- 出現中の敵に警戒中のものが居るか
function Bridge:_is_caution(ids)
  for _, id in ipairs(ids or {}) do
    if self.caution[id] then return true end
  end
  return false
end

function Bridge:_save_encountered_cache()
  save_id_set(self.encountered_path, self.encountered)
end

-- 戻り値: 新規に登録したか（= 初遭遇だったか）
function Bridge:_remember(id)
  -- ⚠ 読む側と同じ規則で門を作る（★これが無いと 0 が書き込まれます）
  if not valid_monster_id(id) then return false end
  if self.encountered[id] then return false end
  self.encountered[id] = true
  self:_save_encountered_cache()
  return true
end

-- `discard_actions` が真なら、単発の操作要求は**読んだことにするだけ**で
-- 実行しない（起動時に古い要求が暴発するのを防ぐ / 下の dispatch を参照）。
--- command.json の高速化の値を適用する。
---
--- ★判定（立ち上がり）は `speed_controller` の中。ここは知らせるだけ。
function Bridge:_apply_turbo_command(want)
  if self.speed:apply_command(want, "画面のボタン") then
    self:emit("turbo", { enabled = self.speed:is_enabled(),
                         source = "画面のボタン" })
  end
end

--- command.json の AUTO の値を適用する。
function Bridge:_apply_auto_command(want)
  if self.battle:apply_command(want, "画面のボタン") then
    self:emit("auto_enabled", { enabled = self.battle:is_auto_enabled(),
                                source = "画面のボタン" })
  end
end

function Bridge:_poll_command(discard_actions)
  -- ★★ 読むのは `command_reader`（リファクタ §4.2）★★
  --   ⚠ `request_id` の重複排除もあちらが持つ。ここで持つと2か所になる。
  local reader = self.commands:poll(discard_actions)
  if reader == nil then return end
  local body = reader.body

  -- MVP1 で必要なのは遭遇済みIDの集合と倍率のみ。
  -- 完全な JSON パースは行わず、必要なフィールドだけ拾う。
  --
  -- ★合併する（上書きしない）。
  --   以前は self.encountered = fresh と丸ごと入れ替えていたが、これは誤り。
  --   Lua は戦闘開始の瞬間に登録するのに対し、Python は events.jsonl を
  --   0.5秒間隔で取り込んでから DB に入れるため、**Python 側は常に遅れうる**。
  --   上書きすると Lua が登録した分が 30 フレームごとに消え、
  --   同じモンスターが何度も「初遭遇」になり自動入力が無効化され続ける。
  --   実害: command.json が [1,2] だけの状態で、ドラキー(4)・アイアンアント(3)・
  --   ゴーストマウス(7) が毎回初遭遇扱いになり自動戦闘が動かなかった
  --   （encountered.txt に 3 が重複記録されていたのがその痕跡）。
  --
  --   リセットしたい場合は "reset_encountered": true を明示すること。
  --   意図しない忘却と、意図したリセットを区別できるようにしてある。
  local reset = body:match('"reset_encountered"%s*:%s*true') ~= nil
  local ids = body:match('"encountered"%s*:%s*%[([^%]]*)%]')
  if reset then
    self.encountered = {}
    self:log("遭遇済みリストをリセットしました（reset_encountered）")
  end
  if ids then
    local added = 0
    -- ⚠⚠ **ここが `0` の入口でした**（2026-08-08）。Python 側の DB には
    --   空IDの記録が多数あり、★門が無いのでそのまま書き込んでいました。
    local dropped = 0
    for num in ids:gmatch("%d+") do
      local id = tonumber(num)
      if not valid_monster_id(id) then
        dropped = dropped + 1
      elseif not self.encountered[id] then
        self.encountered[id] = true
        added = added + 1
      end
    end
    -- ★黙って捨てない（⚠ 何件落としたかは知りたい）。1回だけ。
    if dropped > 0 and not self.encountered_drop_logged then
      self.encountered_drop_logged = true
      self:log(string.format(
        "遭遇済みとして受け取った %d 件を捨てました（★1〜255 以外のID）",
        dropped), "dropped out-of-range monster ids", "WARNING")
    end
    -- Python 側だけが知っているID（前回セッション分）を取り込んだら記録も更新する
    if added > 0 or reset then self:_save_encountered_cache() end
  end
  local mult = body:match('"battle_multiplier"%s*:%s*([%d%.]+)')
  if mult then self.config.speed.battle_multiplier = tonumber(mult) end

  -- ★★ AUTO と 高速化 の適用は担当モジュールへ渡す（リファクタ §4.4）★★
  --   ⚠ **立ち上がり判定**はそれぞれの `apply_command` の中にある。
  --     ここで判定を書くと同じ規則が2か所になり、戻り不具合が復活する。
  self:_apply_turbo_command(reader.turbo_enabled)
  self:_apply_auto_command(reader.auto_enabled)

  -- まんたんの回復目標モード。GUI からの切り替え用。
  -- ★これは状態の変更であって単発の操作ではないので request_id は要らない。
  --   毎回同じ値が来ても害がない（同じモードを設定し直すだけ）。
  -- 戦術プロフィールの版（2026-07-30）。
  -- ★値が変わったら読み直す。**効かせるのは次のターンから**（仕様書 15.3）。
  --   ⚠ ここで即座に効かせると、戦闘の途中で戦術が入れ替わる。
  local rev = tonumber(body:match('"tactics_revision"%s*:%s*(%d+)') or "")
  if rev ~= nil and rev ~= self.tactics_wanted then
    self.tactics_wanted = rev
    if rev ~= self.tactics_revision then
      self:_stage_tactics()
      -- ★戦闘中でなければ、待たせる意味が無いのでその場で効かせる
      if not self.state.in_battle then self:_apply_pending_tactics() end
    end
  end

  local mode = body:match('"mantan_mode"%s*:%s*"([%w_]+)"')
  if mode ~= nil and mode ~= self.mantan_mode then
    self.mantan_mode = mode
    self:log("まんたんの回復目標を切り替えました: " .. mode, "mantan mode: " .. mode)
  end

  -- ★★ 単発の操作要求（リファクタ §4.2）★★
  --   ⚠ `request_id` の重複排除と、起動時に残っていた要求を捨てる判断は
  --     `command_reader` が済ませている。**ここで二度見ない。**
  local action = reader.action
  if action ~= nil then
    if action == "save_state" then
      -- ★保存は**入力を伴わない**のでここで即座に済ませる。
      self:_save_state(reader.save_slot)
    elseif action == "load_state" then
      -- ★読み込みも入力を伴わないので即座に。★ゲームパッドの LB から。
      self:_load_state(reader.save_slot)
    elseif action == "capture_tile" then
      self:_arm_tile_shot()
    else
      self.pending_action = action
    end
  end
end

----------------------------------------------------------------------
-- 遷移タイルの写真（2026-07-30 / マッパー仕様 フェーズ4）
----------------------------------------------------------------------
--
-- ★★ **なぜ「人が押したときだけ」撮るのか** ★★
--
--   遷移（階段を降りた等）に**気づいたあと**では、画面はもう次のマップに
--   変わっている。だから「踏んだタイル」は自動では撮れない。
--   → **その上に立っているうちに人が押す。** 押した時点の画面と座標が
--     一致していることは確かなので、証拠として使える。
--
-- ⚠ 自動で「着いた先」を撮って「踏んだタイル」と名前を付けてはいけない。
--   別のものに正しそうな名前が付くのがいちばん困る。
--
-- ⚠ 座標は**Lua が読む**（Python から受け取らない）。
--   Python の値は state.json 経由で最大0.5秒古い。
--   写真と座標がずれた記録は、あとから直せない。
--
-- ⚠ `gui.savescreenshotas` の書き出しは次フレームに遅延する（playbook #2）。
--   だから「撮る」ではなく「撮る予約」にして step() から進める。
function Bridge:_arm_tile_shot()
  if self.state.in_battle then
    self:log("遷移タイルの写真は撮りません: 戦闘中です", "tile shot: in battle", "DEBUG")
    return
  end
  local map_id = self.game:map_id()
  local x, y = self.game:map_position()
  if map_id == nil or x == nil or y == nil then
    self:log("遷移タイルの写真は撮りません: 位置を読めていません",
             "tile shot: no position", "DEBUG")
    return
  end
  local dir = (self.config.map or {}).tile_shot_dir
             or "work/map-observations/stair_tiles"
  local path = string.format("%s/%s/%02X_%d_%d.png", self.root, dir, map_id, x, y)
  self.tile_shot = { path = path, map_id = map_id, x = x, y = y,
                     saved = false, check = 30 }
end

-- 予約された遷移タイルの写真を進める。step() から毎フレーム呼ぶ。
function Bridge:_tick_tile_shot()
  local p = self.tile_shot
  if p == nil then return end

  if not p.saved then
    gui.savescreenshotas(p.path)
    p.saved = true
    return
  end

  -- 「撮った」と「撮れた」は別。★ファイルの有無で確かめる
  local fh = io.open(p.path, "rb")
  if fh ~= nil then
    fh:close()
    -- ★パスは相対で残す（⚠ 利用者名が混ざらないように / §26）
    local shot_path = short_path(self.root, p.path)
    self:log(string.format("遷移タイルの写真を撮りました: map %02X (%d,%d) -> %s",
      p.map_id, p.x, p.y, shot_path), nil, "DEBUG")
    self:emit("tile_shot", { map_id = p.map_id, x = p.x, y = p.y,
                             path = shot_path })
    self.tile_shot = nil
    return
  end

  p.check = p.check - 1
  if p.check <= 0 then
    -- ★黙って諦めない（置き場が無いのが普通の原因）
    self:log(string.format(
      "⚠ 遷移タイルの写真を書き出せませんでした: %s（置き場はありますか）", p.path), nil, "DEBUG")
    self.tile_shot = nil
  end
end

-- 指定スロットへセーブステートを保存する（GUI の「終了」から呼ばれる）。
--
-- ★★ スロットは**上書き**される ★★
--   だから GUI 側で必ず確認を取る。ここは押された結果を実行するだけ。
--   上書きしても、世代バックアップ（savestate_backup）が直前の内容を
--   世代として残すので**戻せる**。この2つは対で意味を持つ。
--
-- ⚠ スロット0は使ってはいけない。savestate.object(0) は FCEUX をハングさせる
--   （実測。docs/design/ai-batchiri-spec.md にも記録がある）。
function Bridge:_save_state(slot)
  if savestate == nil or savestate.object == nil then
    self:log("セーブステートを保存できません（この FCEUX には savestate API がありません）",
             "savestate: unavailable", "ERROR")
    return
  end
  if slot == nil or slot < 1 or slot > 9 then
    self:log(string.format("セーブステートのスロット指定が不正です: %s（1〜9）",
             tostring(slot)), "savestate: bad slot", "ERROR")
    return
  end

  -- ★★★ **`persist` を呼ばないとディスクに書かれない**（2026-07-31 実測）★★★
  --
  --   `savestate.save()` だけだと FCEUX の**メモリ上のスロット**に入るだけで、
  --   `<ROM名>.fc<番号>` のファイルは**変わらない**。
  --   それなのに例外は出ないので、こちら側は「保存できた」と思ってしまう。
  --
  --   ⚠⚠ 実機で起きたこと（P-3）:
  --     「保存して終了」→ スロット1 をロード → **5日前の状態が出てくる**。
  --     ログには「保存しました」と書いてあるのに、ファイルの時刻は5日前。
  --
  --   ★同じ実行の中で並べて確かめた（`research/probes/archived/savestate_persist_probe.lua`）:
  --     | 呼び方 | 結果 |
  --     | --- | --- |
  --     | `save` だけ | **書かれない** |
  --     | `save` + `persist` | **書かれた** |
  --
  --   ⚠ FCEUX の説明では `persist` は「無名のセーブステートを残す」用だが、
  --     番号つきスロットでも**これが無いとファイルにならない**。
  --     説明ではなく**実測に従う**。
  local ok, err = pcall(function()
    local obj = savestate.object(slot)
    savestate.save(obj)
    -- ★古い FCEUX には無いかもしれないので、あるときだけ呼ぶ
    if savestate.persist ~= nil then savestate.persist(obj) end
  end)
  if not ok then
    self:log("セーブステートの保存に失敗しました: " .. tostring(err),
             "savestate: failed", "ERROR")
    self:emit("savestate_saved", { slot = slot, ok = false })
    return
  end
  self:log(string.format("セーブステートをスロット%d へ保存しました", slot),
           string.format("savestate saved: slot %d", slot))
  self:emit("savestate_saved", { slot = slot, ok = true })
end

-- 指定スロットからセーブステートを読み込む（★ゲームパッドの LB から）。
--
-- ★★ **保存と対で使う。** ★★ 同じ slot をロードする。
--   ⚠ ロード直後は画面が一瞬暗転する（FCEUX の仕様）。地図の取り込みは
--     `savestate.registerload` の既存ハンドラが自動で一時停止するので、
--     ここでは特別なことはしない（人が P キーで読んだときと同じ扱い）。
-- ⚠ スロット0は使わない（`savestate.object(0)` は FCEUX をハングさせる）。
function Bridge:_load_state(slot)
  if savestate == nil or savestate.object == nil or savestate.load == nil then
    self:log("セーブステートを読み込めません（この FCEUX には savestate API がありません）",
             "loadstate: unavailable", "ERROR")
    return
  end
  if slot == nil or slot < 1 or slot > 9 then
    self:log(string.format("セーブステートのスロット指定が不正です: %s（1〜9）",
             tostring(slot)), "loadstate: bad slot", "ERROR")
    return
  end
  local ok, err = pcall(function()
    local obj = savestate.object(slot)
    savestate.load(obj)
  end)
  if not ok then
    self:log("セーブステートの読み込みに失敗しました: " .. tostring(err),
             "loadstate: failed", "ERROR")
    self:emit("savestate_loaded", { slot = slot, ok = false })
    return
  end
  self:log(string.format("セーブステートをスロット%d から読み込みました", slot),
           string.format("savestate loaded: slot %d", slot))
  self:emit("savestate_loaded", { slot = slot, ok = true })
end

-- 生成物(work/generated/*.lua)が生成元(YAML)より古くないかを見る。
--
-- ★2026-07-26 に実際に起きた事故:
--   依頼者が config.yaml の mode を throttled に変えて試したが
--   「変わらない」という結果になった。原因は**生成し直していなかった**こと。
--   YAML はマスタだが Lua が読むのは生成物なので、
--   生成しない限り**設定を変えても黙って無視される**。
--
--   「生成し忘れ」は必ず起きる。**起きたときに気づけること**が対策。
--   黙って古い設定で動くのが最悪で、利用者は自分の変更が効かない理由を
--   自力で突き止めることになる。
--
-- Lua には stat が無く更新時刻を読めないので、
-- 生成時に埋めた指紋（バイト数＋加算チェックサム）と実物を突き合わせる。
function Bridge:_check_generated_fresh(name, data)
  local want = data and data.__source_fingerprint
  if want == nil then
    -- 指紋の無い古い生成物。生成し直せば付く
    self.warnings[#self.warnings + 1] = {
      code = "generated_no_fingerprint",
      message = string.format(
        "%s.lua に生成元の指紋がありません。生成し直してください"
        .. "（uv run python -m retroux.core.config.generate_lua）", name),
    }
    return
  end
  local path = self.root .. "/retroux/plugins/dq2/" .. name .. ".yaml"
  local fh = io.open(path, "rb")
  if fh == nil then return end            -- 読めないなら判定しない（誤警告を出さない）
  local raw = fh:read("*a") or ""
  fh:close()
  local sum = 0
  for i = 1, #raw do sum = (sum + raw:byte(i)) % 0x100000000 end
  local got = string.format("%d:%08x", #raw, sum)
  if got ~= want then
    self.warnings[#self.warnings + 1] = {
      code = "generated_stale",
      message = string.format(
        "★%s.yaml を変更した後に生成していません。**いまの設定は反映されていません**。"
        .. "uv run python -m retroux.core.config.generate_lua を実行してから"
        .. "起動し直してください（生成物=%s / 実物=%s）", name, want, got),
    }
    -- 画面にも出す。ログだけだと気づかれない
    self:notify("CONFIG STALE - run generate_lua", 600)
  end
end

function Bridge:_startup_checks()
  self:_check_generated_fresh("config", self.config)
  self:_check_generated_fresh("memory_map", self.memory_map)

  local bosses = self.config.boss_monster_ids
  if bosses == nil or #bosses == 0 then
    -- DEV-8: 遭遇済み登録が戦闘開始時のため、ボスに敗北して再戦すると
    -- 遭遇済み扱いになり、倍速＋自動たたかうで確実に負ける。
    --
    -- code は重複除去のキー。GUI 側も起動直後に同じ警告を出すため、
    -- 文言ではなく code で同一と判定させる（文言を揃える運用は壊れやすい）。
    self.warnings[#self.warnings + 1] = {
      code = "boss_ids_empty",
      message = "boss_monster_ids が未設定です。ボス戦を通常戦闘として扱うため、"
             .. "ボスに敗北後の再戦で倍速と自動入力が有効になります。",
    }
  end

  -- ★起動時に残っていた古い要求は捨てる。
  -- 前回終了時の command.json をそのまま実行すると、起動しただけで
  -- 意図しない操作（やくそうの消費など）が走る。
  --
  -- ⚠⚠ **引数で「実行しない」と伝える**（2026-07-30 に直した）。
  --   以前はここで普通に読んでから `pending_action = nil` で捨てていたが、
  --   `save_state` と `capture_tile` は dispatch の中で**即座に実行される**
  --   ので、後から捨てても手遅れだった（実 Lua のテストで実証）。
  self:_poll_command(true)
  self.pending_action = nil
  self:emit("session_start", {
    -- ★これが `decision_id` の頭に入る（§7・§27）。
    --   ⚠ 入れておかないと、どのセッションの判断か後から辿れない。
    session_id = self.session_id,
    rom        = self.memory_map.rom.title,
    crc32      = self.memory_map.rom.prg_crc32,
    multiplier = self.config.speed.battle_multiplier,
  })
  for _, w in ipairs(self.warnings) do
    self:emit("warning", { code = w.code, message = w.message })
    self:log("[警告] " .. w.message, nil, "WARNING")
  end

  -- ★起動時に警戒リストの中身をログへ出す。
  -- 出していなかったため「自動戦闘がきかない」ときに利用者が
  -- 原因（居座っているモンスター）を確認できなかった。
  local caution_ids = {}
  for id in pairs(self.caution) do caution_ids[#caution_ids + 1] = id end
  table.sort(caution_ids)
  if #caution_ids > 0 then
    local names = {}
    for _, id in ipairs(caution_ids) do
      names[#names + 1] = string.format("%s(%d)", self.game:monster_name(id), id)
    end
    -- ★パスは相対にする（⚠ 利用者名が混ざらないように / §26）
    self:log("警戒リスト（この相手は等速＋手動。勝つと解除）: "
             .. table.concat(names, " / ")
             .. "  一覧: " .. tostring(short_path(self.root, self.caution_path)),
             string.format("caution list: %d monster(s)", #caution_ids), "DEBUG")
  else
    self:log("警戒リストは空です", nil, "DEBUG")
  end

  -- ★ホットキーの割り当てをログとコンソールに出す。
  -- 出していなかったため「まんたんはホットキーで動くのか」が分からなかった。
  local hk = {}
  for action, key in pairs(self.hotkeys) do
    if type(key) == "string" and key ~= "" then
      hk[#hk + 1] = string.format("%s=%s", key, action)
    end
  end
  table.sort(hk)
  if #hk > 0 then
    self:log("ホットキー: " .. table.concat(hk, " / "),
             "hotkeys: " .. table.concat(hk, " "), "DEBUG")
  else
    self:log("ホットキーは設定されていません（config の hotkeys）", nil, "DEBUG")
  end

  -- コンソールへは英数字のみ。日本語は work/retroux.log を見てもらう。
  if #self.warnings > 0 then
    print(string.format("RetroUX: %d WARNING(S). See work/retroux.log for details.",
                        #self.warnings))
  end
  print(string.format("RetroUX ready. battle speed x%s. log: work/retroux.log",
                      tostring(self.config.speed.battle_multiplier)))
end

----------------------------------------------------------------------
-- 判断
----------------------------------------------------------------------

function Bridge:decide_multiplier()
  -- ★★ 判断は `speed_controller` が行う（リファクタ §4.2）★★
  --   ここは**いまのゲームの様子を集めて渡すだけ**。
  local s = self.state
  return self.speed:decide_multiplier({
    in_battle = s.in_battle,
    manual_latched = self.battle:is_manual_latched(),
    danger = s.danger,
    first_encounter = s.first_encounter,
    is_boss = s.is_boss,
    is_caution = s.is_caution,
    force_auto = self:_force_auto_active(),
    action_multiplier = self.action_multiplier,
  })
end

function Bridge:auto_input_allowed()
  return self.battle:auto_input_allowed(self:_safety_context())
end

function Bridge:_auto_input_allowed_now()
  return self.battle:auto_input_allowed_now(self:_safety_context())
end

function Bridge:_on_battle_start()
  local ids = self.game:enemy_ids()
  self.state.enemy_ids = ids
  self.state.battle_started = emu.framecount()

  -- ★★★ **誰と戦っているかを必ず残す**（2026-08-07 / 依頼者の指摘）★★★
  --
  --   > キラーマシーン単体と戦闘。魔道士の杖を使っている？
  --
  -- ⚠⚠ このとき私は**ログから敵を確かめられませんでした**。
  --   ★「警戒中の相手」など**一部の場面でしか**名前が出ていなかったためです。
  --   ⚠ 敵が分からないと、判断が正しかったかを後から検証できません。
  do
    local names = {}
    for _, g in ipairs(self.game.enemy_groups
      and self.game:enemy_groups() or {}) do
      names[#names + 1] = string.format("%s×%d",
        self.game:monster_name(g.id), g.count or 1)
    end
    -- ★★ 統合の材料として覚えておく（2026-08-14 / RX-0040）★★
    --   ⚠ ここでは**出さない**。戦況・戦術・役割がそろってから1行にする
    --     （`_log_battle_start_summary`）。
    self.start_view = { enemies = (#names > 0)
                        and table.concat(names, " / ") or nil }
    -- ★詳細は調査用に残す（⚠ normal では出ない / §18C）
    if #names > 0 then
      self:log("[敵] " .. table.concat(names, " / "), "battle enemies", "DEBUG")
    else
      -- ⚠ 読めないことも残す（★黙ると「出ていないだけ」と区別できない）
      self:log("[敵] ⚠ 読めていません", "battle enemies unknown", "DEBUG")
    end
  end

  -- ★★ 戦術プロフィールは**戦闘の始まりで固定する**（仕様書 15.3）★★
  --   > 戦闘開始時またはターン開始時に、適用プロフィールをスナップショット化する
  --
  --   ⚠ ここに置く理由: `_check_battle_log` のターン判定は
  --     `battle_log.enabled` が false だと動かない。設定を1つ切っただけで
  --     戦術の切り替えが効かなくなるのは、**隠れた依存**で分かりにくい。
  --     戦闘開始は必ず通る。
  self:_apply_pending_tactics()

  -- ★★ 戦闘の通し番号（2026-07-29 / 依頼者の指摘）★★
  --
  -- > 偶に出会った敵で切り替わらない場合がある。オート戦闘だから
  -- > タイミング障害かもだが
  --
  -- そのとおりだった。GUI は 0.5 秒ごとに state.json を見るが、
  -- **倍速（約35倍）だと戦闘まるごと1回が 0.5 秒に収まる**ことがあり、
  -- GUI が `in_battle=true` を一度も見ないまま次のフィールドになる。
  -- すると「新しい戦闘が始まった」と気づけず、前の敵が出たままになる。
  --
  -- → **戦闘の数を Lua が数えて渡す。** GUI はこの番号が変わったことで
  --   新しい戦闘だと分かる（戦闘中の瞬間を見ていなくてよい）。
  self.state.battle_seq = (self.state.battle_seq or 0) + 1
  -- この戦闘で出会った種（**倒しても減らさない**。呼び出された敵は足す）
  self.state.battle_species = {}
  for _, id in ipairs(ids) do
    local dup = false
    for _, had in ipairs(self.state.battle_species) do
      if had == id then dup = true end
    end
    if not dup and id ~= 0 then
      self.state.battle_species[#self.state.battle_species + 1] = id
    end
  end
  -- 実時間の計測は Lua 側で行う。Python 側の時計だと「イベントを処理した時刻」に
  -- なり、ポーリング間隔(0.5秒)より短い戦闘で所要時間がほぼ 0 になってしまう。
  -- 「削減できた待ち時間」はこのプロジェクトの中心指標なので正確に測る。
  self.state.started_clock = os.clock()

  -- 初遭遇判定は戦闘開始時に登録（C-2）。1体でも未遭遇なら初遭遇扱い（F-3）。
  local first, names = false, {}
  for i, id in ipairs(ids) do
    if self:_remember(id) then first = true end
    names[i] = self.game:monster_name(id)
  end
  self.state.first_encounter = first
  self.state.is_boss = self.game:is_boss(ids)
  -- ★前に逃げた/負けた相手か。等速＋手動のままにする
  self.state.is_caution = self:_is_caution(ids)
  -- 報酬は勝利表示中しか読めないので、戦闘ごとにクリアして step() で捕まえる
  self.state.exp_gained = nil
  self.state.gold_gained = nil
  -- 手動ラッチはこの戦闘の中だけ有効。戦闘ごとに解除する。
  self.state.manual_latched = false
  self.target_menu_logged = false
  self.target_lock_logged = false
  -- ⚠ 戦闘ごとに戻す。★戻さないと2戦目以降ずっと黙ります。
  self.aim_skip_logged = false
  self:_reset_target_seek()
  -- 杖の使用回数は戦闘ごとに数え直す
  self:_reset_battle_item()
  self.bi_uses = 0
  -- ★戦闘ごとに数え直す（`once_per_battle` は**この戦闘で**1回 / 課題 #62）
  self.bi_used_ids = {}
  -- ★見送りの理由も捨てる。⚠ 持ち越すと、次の戦闘で条件が変わっても
  --   「同じ理由なので書かない」となり、黙って見送ることになる。
  self.bi_skip_notes = {}
  -- ★bi_logged はここで戻さない（毎戦闘 同じ行が出ていた）。
  --   下の _claim_battle_item を参照。
  -- 回復呪文も戦闘ごとに数え直す（P3）
  self.last_ai_action, self.last_ai_reason = nil, nil
  -- ★3人ぶんの判断も戦闘ごとに捨てる（前の戦闘の判断が残ると誤解する）
  self.ai_decisions = {}
  -- ★敵HPの基準（戦闘開始時の値）は戦闘ごとに取り直す
  self.enemy_hp_start = {}
  -- ★無駄撃ち回避の予約も戦闘ごとに捨てる
  --   ⚠ 持ち越すと、次の戦闘の1ターン目で「もう足りている」と誤解する
  self.overkill_booked = {}
  self.overkill_hp_total = nil
  -- 行動単位ログ（Phase 3）。ターンと、前フレームの値。
  self.turn_no = 0
  self.turn_seq = 0
  self.log_prev = nil
  self.log_count = 0
  self.saw_command_menu = false
  self:_reset_battle_heal()
  self:_reset_battle_attack()
  self.bh_uses = 0
  self.bh_logged = false

  -- 勝利表示を見たか。勝敗の判定に使う。
  -- ★exp_gained では判定しない。⚠ 逃げた場面での動きが読めず、勝敗の
  --   根拠にすると誤判定が警戒リストに波及する。
  --   （B-9「アドレス未確定」は 2026-07-31 に解決済み。理由は別）
  self.state.saw_victory = false
  -- この戦闘中にプレイヤーへ操作が渡った場面があったか。
  -- 「プレイヤーが逃げた」と「敵が逃げた」を区別するために使う（_on_battle_end）。
  self.state.player_had_control = false

  self:emit("battle_start", {
    enemy_ids          = ids,
    enemy_count        = #ids,
    names              = table.concat(names, ","),
    is_first_encounter = first,
    is_boss            = self.state.is_boss,
    is_caution         = self.state.is_caution,
  })
  if self.state.is_caution then
    self:log("警戒中の相手のため等速＋手動にします: " .. table.concat(names, ","),
             "caution: manual")
  end

  self:_arm_monster_art(ids)

  -- ★★ 戦況の見立てを1行だけ出す（2026-08-05 / Phase 4 完了条件5）★★
  --   ⚠⚠ **見立てるだけで、判断は変えていません。**
  --   ⚠ 落ちても戦闘を止めない（★見立ては「あると嬉しい」もの）。
  --
  -- ⚠⚠⚠ **黙って捨てない**（2026-08-07 に踏んだ）★★★
  --   元は `pcall(...)` の戻り値を捨てていました。そのため Phase 6 で
  --   足した `[役割]` が**1行も出ないのに、何のエラーも残りません**でした。
  --   ★`[戦況]` と `[戦術]` は出ていたので、余計に気づけませんでした。
  --   ⚠ 毎フレーム出すと雑音になるので、**同じ理由は1度だけ**出します。
  local ok, err = pcall(function() self:_log_assessment() end)
  if not ok then
    local why = tostring(err)
    if self._assess_error ~= why then
      self._assess_error = why
      self:log("⚠ 戦況の見立てで落ちました（判断には影響しません）: " .. why,
        "assessment error", "WARNING")
    end
  end
end

----------------------------------------------------------------------
-- モンスターの絵を画面から撮る（2026-07-27 / 依頼者の要望）
----------------------------------------------------------------------
--
-- > モンスターグラフィック表示は、データがなかったら画面から取得する論理でいい
-- > エミュ画面から、キャプチャを自動的に取れない？
--
-- ★取れる。⚠ 2026-08-12 訂正: ここには「**ROM の絵の形式は未解読**」と
-- 書いてありましたが、**2026-07-29 に解読済み**です（82体 / 38枚を静的展開し、
-- 実機の撮影と画素まで一致）。`dq2rom monsters extract` を参照。だが、
--   このROMは **UNROM = CHR-RAM** なので、絵は実行時に PPU へ展開される。
--   つまり**画面に出ているものを撮れば、形式を解読しなくてよい**。
--
-- ★**ファイルが無いときだけ撮る**（依頼者の指定の論理）。
--   毎戦闘撮ると倍速の邪魔になるし、同じ絵を上書きし続ける意味も無い。
--
-- ⚠⚠ **1種だけの戦闘でしか撮らない。**
--   複数種が並んでいると、画面のどの絵がどの敵かを**画像だけでは決められない**。
--   位置を推測して切り出すと、違う敵の絵を図鑑に載せることになる
--   （杖の位置を推測して きんのカギ を使った事故と同じ形 / DEV-24）。
--   1種の戦闘は普通に起きるので、遊ぶほど埋まっていく。
--
-- ⚠ `gui.savescreenshotas` の書き出しは**次フレームに遅延する**（playbook #2）。
--   撮ったあとフレームを進める必要があるので、
--   「撮る」ではなく「**撮る予約をする**」形にして step() から進める。
-- 敵IDの並びを raw のファイル名にする。
--
-- ★★ ファイル名が**画面の並び順**を持つ ★★
--   `$0162` は「画面上の並び順どおりに1バイトずつ格納する配列」なので、
--   その並びをそのまま名前にすれば、切り出し側が
--   「左から i 番目のかたまり = ids[i] の敵」と対応づけられる。
--     1種  -> "0C"        （何体でも同じ）
--     複数種 -> "12-06-06"（画面の左からこの順）
local function art_name(ids)
  local kinds = {}
  local seen = {}
  for _, id in ipairs(ids) do
    if not seen[id] then seen[id] = true; kinds[#kinds + 1] = id end
  end
  if #kinds <= 1 then
    return string.format("%02X", ids[1])
  end
  local parts = {}
  for _, id in ipairs(ids) do parts[#parts + 1] = string.format("%02X", id) end
  return table.concat(parts, "-")
end

function Bridge:_arm_monster_art(ids)
  local cfg = self.monster_art
  if cfg == nil or cfg.enabled == false then return end
  -- ★★★ **研究用の採取は通常運用では走らせない**（2026-08-13 / §22）★★★
  --
  -- ## ⚠ なぜ切るか
  --
  --   指示書 §20・§21 は NORMAL でも DIAGNOSTIC でも
  --   **research capture を OFF** と定めている（§22 は専用ツールへ寄せる）。
  --
  --   ⚠ これは「絵を撮るのをやめる」話ではない。★絵は
  --     `python -m dq2rom monsters extract`（ROM から）で 82 体そろっており、
  --     実機の撮影 10 枚と画素まで一致している。
  --     ★画面からの採取は**その確かめのため**の研究作業。
  --
  -- ## ★ 入れ方
  --
  --   `user_config.yaml`:
  --
  --       research:
  --         capture: true       # ★既定は false
  --
  --   ⚠ ログの段階（`logging.mode`）とは**別**にした。
  --     ★研究は「ログを多く出す」ことではなく「別の仕事をする」ことなので、
  --       第3のログレベルにすると混ざる（§22）。
  if not ((self.research or {}).capture == true) then
    if not self.art_off_told then
      self.art_off_told = true
      self:log("モンスターの絵は撮りません（研究用の採取は既定で切）"
               .. "　★`research.capture: true` で入ります",
               "monster art: research off", "DEBUG")
    end
    return
  end
  if ids == nil or #ids == 0 then return end

  -- ⚠ 1体だけに限る設定（既定は false）。
  --   ★もともとは複数体だと集合写真になるので true にしていたが、
  --     **5戦闘すべて撮れず**効率が悪かった（2026-07-27 の実機）。
  --     いまは切り出し側でかたまりに分けるので、限る必要が無い。
  if cfg.single_individual_only == true and #ids > 1 then
    self.art_pending = nil
    return
  end

  -- ★★ まだ絵が無い敵が1体でも居れば撮る（複数種でも撮る）★★
  --
  --   以前は「1種だけの戦闘」に限っていたため、10戦闘で0枚という走行があった。
  --   `$0162` が画面の並び順を持つので、**かたまりの数と体数が合えば**
  --   どれがどの敵かを対応づけられる（切り出し側で判定する）。
  --
  -- ★見るのは**切り出し後**のファイル。そこに絵があれば図鑑は埋まっている。
  --   ⚠ 切り出しは Python（GUI）が0.5秒ごとに回すので、撮った直後の
  --     ごく短い間だけ「まだ無い」と見える。その間に同じ戦闘が続いても
  --     `art_done` で二度撮りを防ぐ。
  local out_dir = cfg.dir or "work/monster-art"
  local missing = {}
  for _, id in ipairs(ids) do
    if not self.art_done[id] then
      local fh = io.open(string.format("%s/%s/%02X.png", self.root, out_dir, id), "rb")
      if fh == nil then
        missing[#missing + 1] = id
      else
        fh:close()
        self.art_done[id] = true      -- 次からはファイルを開かない
      end
    end
  end
  if #missing == 0 then
    self.art_pending = nil
    return
  end

  local raw_dir = cfg.raw_dir or (out_dir .. "/raw")
  local path = string.format("%s/%s/%s.png", self.root, raw_dir, art_name(ids))

  -- ★演出（敵が現れる動き）が終わるのを待ってから撮る。
  --   すぐ撮ると出現途中の絵になる。待つフレーム数は設定で変えられる。
  self.art_pending = { ids = ids, id = ids[1], path = path,
                       missing = missing,
                       wait = cfg.settle_frames or 90, saved = false }
end

-- 予約された撮影を進める。step() から毎フレーム呼ぶ。
function Bridge:_tick_monster_art()
  local p = self.art_pending
  if p == nil then return end

  -- ⚠ 戦闘から抜けたら諦める（フィールドの絵を撮らない）
  if not self.state.in_battle then
    self.art_pending = nil
    return
  end

  if p.wait > 0 then
    p.wait = p.wait - 1
    return
  end

  if not p.saved then
    -- ⚠⚠ **撮る直前にもう一度数える。**
    --   戦闘開始の瞬間は `$0162` の枠がまだ埋まっていないことがあり、
    --   「1体だと思ったら3体だった」が起こりうる。
    --   実際 よろいムカデ4体の集合写真を撮ってしまっている（2026-07-27）。
    --
    -- ★並びが変わっていたら**名前を付け直す**。ファイル名が画面の並びを
    --   表しているので、ずれたまま保存すると切り出し側が取り違える。
    local cfg = self.monster_art or {}
    local now = self.game:enemy_ids()
    if #now == 0 then
      self:log("モンスターの絵は撮りません: 敵が読めない", nil, "DEBUG")
      self.art_pending = nil
      return
    end
    if cfg.single_individual_only == true and #now > 1 then
      self:log(string.format("モンスターの絵は撮りません: %d 体いる（1体の戦闘に限る設定）",
        #now), nil, "DEBUG")
      self.art_pending = nil
      return
    end
    local raw_dir = cfg.raw_dir or ((cfg.dir or "work/monster-art") .. "/raw")
    p.ids = now
    p.id = now[1]
    p.path = string.format("%s/%s/%s.png", self.root, raw_dir, art_name(now))

    -- ★ここで撮る。書き出しは次フレームなので、まだ確認しない
    gui.savescreenshotas(p.path)
    p.saved = true
    p.check = 30            -- 書き出しを待つ上限（playbook #9: 上限を置く）
    return
  end

  -- 書き出せたかを**ファイルの有無で**確かめる（「撮った」と「撮れた」は別）
  local fh = io.open(p.path, "rb")
  if fh ~= nil then
    fh:close()
    local names = {}
    local seen = {}
    for _, id in ipairs(p.ids or { p.id }) do
      if not seen[id] then
        seen[id] = true
        names[#names + 1] = self.game:monster_name(id)
        -- ★この戦闘で撮ったことを覚える。同じ戦闘で撮り直さない
        self.art_done[id] = true
      end
    end
    -- ★パスは相対で残す（§26）
    local art_path = short_path(self.root, p.path)
    self:log(string.format("モンスターの絵を撮りました: %s（%s）",
      table.concat(names, ", "), art_path), nil, "DEBUG")
    self:emit("monster_art", { monster_id = p.id, path = art_path })
    self.art_pending = nil
    return
  end

  p.check = p.check - 1
  if p.check <= 0 then
    -- ★黙って諦めない。次に同じ敵に会えばまた試す
    self:log(string.format(
      "⚠ モンスターの絵を書き出せませんでした: %s（次に会ったときに再挑戦します）",
      self.game:monster_name(p.id)), nil, "DEBUG")
    self.art_pending = nil
  end
end

function Bridge:_on_battle_end()
  -- ⚠⚠ **このターンの指示を持ち越さない**（2026-08-07）。
  --   ★次の戦闘まで残ると、⚠ 戦況を見ていない指示で拒否してしまいます。
  self.turn_directive = nil
  self.turn_directive_turn = nil
  -- ⚠ 却下を出したかの印も戦闘ごとに消す（★次の戦闘で黙らないように）。
  self.veto_logged = nil
  self.priority_bias_logged = nil
  -- ⚠ 回復量で並べ替えたときの印も消す（★次の戦闘で黙らないように）
  self.heal_order_logged = nil
  -- ★★ 最後の人の「たたかう」を確定させる（2026-08-08）★★
  --   ⚠ 戦闘が終わると番が変わらないので、ここで流さないと**落ちます**。
  pcall(function() self:_flush_physical() end)
  self.turn_actor = nil
  -- ⚠ 判断の記録の印も消す（★次の戦闘で1件も出なくなります）
  self.snapshot_done = nil
  self.action_logged = nil

  local elapsed_ms = nil
  if self.state.started_clock ~= nil then
    elapsed_ms = math.floor((os.clock() - self.state.started_clock) * 1000 + 0.5)
  end

  -- ★★ 強制AUTO は**その戦闘だけ**（2026-07-31 の指示書 §4）★★
  --   安全機構を潰す状態なので、次の戦闘へ持ち越さない。
  --   ⚠ AUTO そのもの（`auto_enabled`）は解除しない。あれは設定であって
  --     「この戦闘の例外」ではない。混ぜると A キーを押すたびに
  --     AUTO 設定が戦闘ごとに勝手に戻る。
  self:_set_force_auto(false)

  -- ★★★ **戦闘が終わった時刻は「ここ」で決める**（2026-08-07）★★★
  --
  -- ⚠⚠ `frames_since_battle` は名前のとおり「戦闘が終わってからの
  --   フレーム数」のつもりでしたが、実際に 0 に戻していたのは
  --   `_apply_input()` の「**自動入力が主張したとき**」だけでした。
  --   ★名前と中身が食い違っています。
  --
  -- そのため **AUTO が効いていない戦闘**（手動・危険状態でAUTO見送り・
  -- キャラ別AI操作OFF）では 1度も 0 に戻らず、⚠ 戦闘が終わるころには
  -- 数千フレームに膨らんでいました。実測:
  --
  --     ハーネスの計測    戦闘終了の 4〜6 フレーム後にメニューが開いた
  --     bridge の計測     戦闘終了から 1401 / 2301 / 2279 フレーム
  --
  -- ⚠⚠ すると `_claim_menu_cleanup()` が「しきい値(45)より後に開いた＝
  --   **プレイヤーが自分で開けた**」と判断して手を出さず、★B を押して
  --   閉じる仕組みが**1度も動きません**でした（実機22戦中3戦）。
  --   依頼者の「ずっとメニューでたまま」がこれです。
  --
  -- ★戦闘が終わったかどうかは、自動入力が働いたかとは**無関係**です。
  --   立ち下がりのここで数え直します。
  -- ★★ 戦闘が終わっても見立てを**消しません**（2026-08-07 / 依頼者の指示）★★
  --
  --   > 戦況、役割は戦闘終了後クリアしなくて良い。
  --
  -- ⚠ 最初は「`state.json` はいまの値だから消すべき」と考えて消していました。
  --   ★しかし戦闘は数秒で終わるので、**消すと読む間がありません**。
  --     直前の戦闘で何が選ばれたかを見直せるほうが役に立ちます。
  -- ⚠⚠ ただし「いつの値か」が分からなくなるのは別の問題なので、
  --   ★戦闘が終わったことは `in_battle` で分かるようにしてあります。
  self.frames_since_battle = 0
  self.menu_cleanup_left = self.menu_cleanup_frames
  self.menu_cleanup_active = false
  self.release_left = self.release_frames_after_battle

  -- 戦闘の結末を決める。
  --
  -- ★当初は「勝利表示が出なかった＝勝てなかった」として警戒リストへ入れていたが、
  --   **それは誤りだった。** DQ2 では敵が逃げることがあり、その場合も勝利表示は
  --   出ない。実ログでは retreat と判定した2件がどちらも 31〜33倍速中、つまり
  --   自動戦闘が動いている最中だった。自動入力は毎フレーム入力を上書きするので
  --   **プレイヤーは逃げられない**＝あれは敵が逃げた戦闘だった。
  --   その結果 Wild Mouse(5) のような雑魚が警戒リストに入り、
  --   「自動戦闘が効かなくなった」という不具合になった（判定は全件が誤り）。
  --
  -- 区別の根拠:
  --   勝利表示あり            -> win        警戒リストから外す
  --   生存者が居ない          -> lose       負けたので警戒
  --   途中で手動になっていた  -> flee       プレイヤーが逃げられた場面がある
  --   上記以外                -> enemy_fled 敵が逃げた。**警戒しない**
  --
  -- flee の判定は「プレイヤーに操作が渡っていたか」で代用している。
  -- どのコマンドを選んだかは読めないため、
  -- 「逃げられた場面があったなら逃げたかもしれない」と安全側に倒す。
  local ids = self.state.enemy_ids or {}
  local members = self.game:active_party()
  local alive = 0
  for _, m in ipairs(members) do
    if m.alive then alive = alive + 1 end
  end

  local outcome
  if self.state.saw_victory then
    outcome = "win"
  -- ★「加入者が0人」と「全滅」を区別する。
  --   加入者が0人なのはパーティ状態を読めていない場合であり、全滅ではない。
  --   区別せず全滅扱いにすると、読み取りに失敗しただけで敗北と判定し、
  --   その相手を警戒リストへ入れてしまう。
  elseif #members > 0 and alive == 0 then
    outcome = "lose"
  elseif self.state.player_had_control then
    outcome = "flee"
  else
    outcome = "enemy_fled"
  end

  if outcome == "win" then
    local cleared = self:_note_victory(ids)
    if #cleared > 0 then
      self:log("勝ったので警戒リストから外しました: " ..
               table.concat(cleared, ","), "caution cleared", "DEBUG")
    end
  elseif outcome == "enemy_fled" then
    -- ★警戒しない。プレイヤーは負けても逃げてもいない
    self:log("敵が逃げました（警戒リストには入れません）: " ..
             table.concat(ids, ","), "enemy fled", "DEBUG")
  else
    local added = self:_note_retreat(ids)
    if #added > 0 then
      self:log(string.format(
        "%s のため警戒リストへ入れました（次回も等速＋手動）: %s",
        (outcome == "lose") and "敗北" or "逃走", table.concat(added, ",")),
        "caution added", "DEBUG")
    end
  end

  -- ⚠ 戦闘中にセーブステートをロードすると `framecount` が巻き戻り、
  --   引き算が**負**になる（「戦闘時間 -1200 フレーム」という記録が残る）。
  --   ★分からないものは**書かない**（0 を入れると「一瞬で終わった」に見える）。
  local frames = nil
  if self.state.battle_started ~= nil then
    local delta = emu.framecount() - self.state.battle_started
    if delta >= 0 then frames = delta end
  end

  self:emit("battle_end", {
    outcome         = outcome,
    duration_frames = frames,
    duration_ms     = elapsed_ms,   -- Lua 側の実測。Python の時計より正確
    enemy_ids       = self.state.enemy_ids,
    -- sample() は進行中の区間をその場で計測する。measured_multiplier() だと
    -- 1区間ぶん古い値（戦闘前のフィールド区間など）を報告してしまう。
    speed_applied   = self.throttle:sample() or 1.0,
    -- 勝利表示中に捕まえた値。逃走/敗北では表示が出ないので nil のまま
    exp_gained      = self.state.exp_gained,
    gold_gained     = self.state.gold_gained,
  })
  self.state.enemy_ids = {}
  self.state.first_encounter = false
  self.state.is_boss = false
  self.state.is_caution = false
  self.state.saw_victory = false
  self.state.player_had_control = false
  self.state.manual_latched = false

  -- ★戦闘後にレベルアップを確認する（経験値は戦闘でしか入らない）。
  -- 警戒リストの解除はここで行う。
  self:_check_level_up()
end

----------------------------------------------------------------------
-- 入力の所有権
----------------------------------------------------------------------
--
-- ★ `joypad.set` を呼ぶのは このブリッジだけ。外部は意図を登録するだけ。
--
-- なぜ一元化したか（MVP1 で同種の不具合を3回踏んだ）:
--   `joypad.set` は**最後に呼んだ側が勝つ**。ブリッジとテストハーネスが
--   別々に呼んでいたため、以下が繰り返し起きた。
--     1. 戦闘が終わらない     — ハーネスの方向キーが戦闘中も押されたまま残った
--     2. 勝利メッセージが止まる — ハーネスが A=false を明示し誰も A を押さなくなった
--     3. メニューが操作を奪う  — ハーネスの方向キーがブリッジの B 押下を打ち消した
--   ブリッジ側だけ直してもハーネスが上書きすれば無意味なので、
--   所有者を1つにして優先順位で解決する形に変えた。
--
-- 優先順位:
--   1. 戦闘中の自動入力（「たたかう」）
--   2. 戦闘直後のメニュー後始末（開いてしまったコマンドメニューを閉じる）
--   3. 外部からの要求（歩行など）
--
-- ⚠ ブリッジが何も主張せず外部要求も無い場合は **`joypad.set` を呼ばない**。
--   毎フレーム全ボタンを明示すると**プレイヤーの実機操作を完全に奪ってしまう**。

local ALL_BUTTONS = { "A", "B", "start", "select", "up", "down", "left", "right" }

-- 指定されていないボタンを明示的に false で埋める。
-- ⚠ 部分指定のままにすると、含めなかったボタンは前の状態が残る。
-- 実際に歩行時の方向キーが戦闘中も押されたままになり（$002F=0x40 = Left）、
-- メニューカーソルが延々とスクロールした（B-7 の原因の一つ）。
local function full_button_set(partial)
  local out = {}
  for _, name in ipairs(ALL_BUTTONS) do
    out[name] = (partial[name] == true)
  end
  return out
end

-- ★★ 「手を出さない」を表す目印（2026-07-31 / 実機 T-5）★★
--
-- 入力の主張には**3つ**の意味がある。`nil` と `{}` の2つでは足りない:
--
--   | 返り値 | 意味 | joypad.set |
--   | --- | --- | --- |
--   | `nil` | 主張しない → **下の判断へ落ちる**（最後は「たたかう」） | 呼ばない |
--   | `{...}` / `{}` | このボタンを送る（`{}` は**全部離す**） | 呼ぶ |
--   | `HANDS_OFF` | 主張しない、**かつ下へも落とさない** | 呼ばない |
--
-- ⚠⚠ **`{}` を「人に返す」意味で使ってはいけない。**
--   `full_button_set({})` は8ボタン全部を `false` にする。FCEUX の
--   `joypad.set` で `false` は「離れている」ではなく **「強制的に離す」**。
--   毎フレーム送ると、人がキーを押しても**そのフレームで打ち消される**。
--   FCEUX の入力表示には出るのにゲームへ届かない、という形になる。
--
--   実機 T-5 で発生: AI操作OFF（見本「手動中心」）にすると
--   キーボードが一切効かなくなった。原因はここ。
--
-- ★`{}` にも使い道はある（戦闘直後の `release_left`）。
--   「直前の押下を数フレームだけ断ち切る」用途は**期限つきなら正しい**。
--   誤りは、期限の無い「ずっと `{}`」をプレイヤーへの返却に使ったこと。
local HANDS_OFF = setmetatable({}, { __tostring = function() return "HANDS_OFF" end })

-- ★試験から同じ目印を参照できるようにする（`==` で確かめられる）。
Bridge.HANDS_OFF = HANDS_OFF

-- 外部から「こう入力したい」という意図を登録する。1フレームで消費される。
-- ブリッジがより優先度の高い入力を主張している場合は無視される。
--
-- kind は要求の種類。既定の "explicit" は**呼び出し側が状況を理解している**
-- 前提で、メニューが開いていてもそのまま通す（マクロのメニュー操作など）。
function Bridge:request_input(buttons, kind)
  self.requested_input = buttons
  self.requested_kind = kind or "explicit"
end

-- 「フィールドを歩きたい」という意図。
-- ⚠ walk は**メニューが開いている間は破棄される**。
-- メニュー中に方向キーを送るとカーソル操作に吸われてしまうため
-- （実機で「メニューが開いて上下左右が拾われる」状態になった）。
-- 意図的にメニューを操作したい場合は request_input() を使う。
function Bridge:request_walk(direction)
  self:request_input({ [direction] = true }, "walk")
end

-- 戦闘中の自動入力（「たたかう」）の主張。押さない場合は nil。
--
-- ⚠ 実機トレースで判明した落とし穴（work/b7-input-trace.txt）:
--   **戦闘のコマンドメニューでは B を押してはいけない。** B は「キャンセル」であり、
--   A で「たたかう」を選び B で取り消す ABAB の無限ループになって
--   戦闘が永久に終わらなくなる（B-7 の主因）。
--   入力レジスタ $002F の集計では B が 141 フレーム、A がわずか 7 フレームだった。
--   方向キーも押さない。カーソルは「たたかう」から動かない。
--
-- ★ただし**勝利メッセージの送りだけは B を使う**（矛盾していないので戻さないこと）。
--   勝利メッセージにはキャンセルする対象が無く、B でも送れる。
--   A で送ると、メッセージを閉じた押下がそのままフィールドのコマンドメニューを
--   開いてしまう（戦闘終了の2フレーム後に必ず開いた）。詳細は DEV-14。
--   キャンセルが問題になるのはコマンドメニュー中だけであり、
--   showing_victory() が true の間に限って B を使う。
----------------------------------------------------------------------
-- キャラクター別戦術プロフィール（2026-07-30 / 仕様書 15章）
----------------------------------------------------------------------
--
-- ★★ **設定の出どころは2段。** ★★
--
--     プロフィール（キャラクターごと）  ← あれば優先
--     config.yaml（全員共通）           ← これまでの値。無ければこちら
--
--   ⚠ **プロフィールが無い環境では、これまでとまったく同じ挙動**になる。
--     `_tactic_num` / `_tactic_flag` が「無ければ config の値」を返すため。
--
-- ★渡し方: Python が `work/generated/tactics.lua` を書く。
--   `config.lua` と同じ「Lua のテーブルを返すファイル」。
--
-- ⚠ 読み込みは必ず pcall で包む。壊れたファイルで**戦闘が止まってはいけない**
--   （表示や設定の処理で本体を止めない / playbook #10）。

--- `work/generated/tactics.lua` を読む。読めなければ nil のまま。
function Bridge:_load_tactics()
  local path = self.root .. "/work/generated/tactics.lua"
  local fh = io.open(path, "rb")
  if fh == nil then
    -- ★無いのは普通（プロフィールを使っていない）。警告しない
    return nil
  end
  fh:close()

  local chunk, load_err = loadfile(path)
  if chunk == nil then
    self:log("⚠ 戦術プロフィールを読めません（config.yaml の値で動きます）: "
      .. tostring(load_err), "tactics: loadfile failed", "WARNING")
    return nil
  end
  local ok, data = pcall(chunk)
  if not ok or type(data) ~= "table" or type(data.characters) ~= "table" then
    self:log("⚠ 戦術プロフィールの中身が変です（config.yaml の値で動きます）",
      "tactics: bad table", "WARNING")
    return nil
  end
  return data
end

--- 読み直して「次のターンから効かせる」ところへ置く。
---
--- ★★ **ここでは効かせない**（仕様書 15.3）★★
---   戦闘の途中で入れ替えると、同じターンの前半と後半が別の戦術になる。
function Bridge:_stage_tactics()
  local data = self:_load_tactics()
  self.tactics_pending = data
  if data == nil then
    -- ★消された = プロフィールを使わない状態に戻す
    if self.tactics ~= nil then
      self:log("戦術プロフィールを外しました（config.yaml の値で動きます）",
        "tactics: cleared", "DEBUG")
    end
    self.tactics = nil
    self.tactics_revision = nil
    self.tactics_pending = nil
  end
end

--- ターンの区切りで、待たせていた表を効かせる。
function Bridge:_apply_pending_tactics()
  local data = self.tactics_pending
  if data == nil then return end
  self.tactics_pending = nil
  self.tactics = data
  self.tactics_revision = data.revision
  -- ★★ 大目的も一緒に出す（2026-08-05 / Phase 3）★★
  --   ⚠ これが無いと「目的を変えたのに効いているのか」が**追えません**。
  --     予約の倍率は「MPが足りないとき」しか文に出ないので、
  --     ★普段は目的が届いているかどうかすら分かりませんでした。
  local mission = ""
  if type(data.mission) == "table" then
    mission = string.format("／目的: %s（MP予約 ×%s）",
      tostring(data.mission.mission),
      tostring(data.mission.mp_reserve_scale))
  end
  self:log(string.format(
    "戦術プロフィールを適用しました: %s（効くのはフェーズ %s）%s",
    tostring(data.profile_name), table.concat(data._phases or {}, "・"),
    mission),
    "tactics: " .. tostring(data.profile_id), "DEBUG")
end

--- そのキャラクターの設定表。無ければ nil。
---
--- ⚠ 名前は `memory_map.yaml` の `party.members`（lorasia / samaltria /
---   moonbrooke）。Python 側の `CHARACTER_IDS` と同じ綴り。
function Bridge:_tactics_for(name)
  local t = self.tactics
  if t == nil or name == nil then return nil end
  return t.characters[tostring(name)]
end

--- 数値の設定を引く。**無ければ `fallback`**（config の値）。
function Bridge:_tactic_num(name, section, key, fallback)
  local c = self:_tactics_for(name)
  if c == nil then return fallback end
  local body = (section == nil) and c or c[section]
  if type(body) ~= "table" then return fallback end
  local value = body[key]
  if type(value) ~= "number" then return fallback end
  return value
end

--- true/false の設定を引く。**無ければ `fallback`**（config の値）。
function Bridge:_tactic_flag(name, section, key, fallback)
  local c = self:_tactics_for(name)
  if c == nil then return fallback end
  local body = (section == nil) and c or c[section]
  if type(body) ~= "table" then return fallback end
  local value = body[key]
  if type(value) ~= "boolean" then return fallback end
  return value
end

--- 文字列の設定を引く。**無ければ `fallback`**。
function Bridge:_tactic_text(name, section, key, fallback)
  local c = self:_tactics_for(name)
  if c == nil then return fallback end
  local body = (section == nil) and c or c[section]
  if type(body) ~= "table" then return fallback end
  local value = body[key]
  if type(value) ~= "string" then return fallback end
  return value
end

--- その人を AI で操作してよいか（仕様書 4.4）。
---
--- ★★ **既定は true。** ★★ プロフィールが無い環境で自動戦闘が
---   止まってはいけない（これまでの挙動を変えない）。
function Bridge:_tactic_ai_enabled(name)
  return self:_tactic_flag(name, nil, "enabled", true)
end

--- いま入力を待たれている人が AI操作OFF か（2026-07-31 / 実機 T-5）。
---
--- ★★ **コマンドメニュー以外でも使う判定。** ★★
---   `_claim_manual_character` はコマンドメニュー（`battle_menu`）でしか
---   判断しない。⚠ そのため人が自分で「たたかう」を押して**敵選択が開いた
---   瞬間から素通り**になり、AI がカーソルを動かして A を押していた。
---   「AI操作OFF にしたのに勝手に敵を選ばれる」という形の事故。
---
--- ⚠ 読めないときは **false**（＝これまでどおり AI が動く）。
---   true にすると、名前が読めない環境で自動戦闘が丸ごと止まる。
function Bridge:_current_member_ai_off()
  if self.tactics == nil then return false end
  if self.game.battle_input_member == nil then return false end
  local m = self.game:battle_input_member()
  if m == nil or m.name == nil then return false end
  return not self:_tactic_ai_enabled(m.name)
end

--- 回復を始めるHPの割合（0.0〜1.0）。自分と仲間で別（仕様書 5.2）。
---
--- ⚠ プロフィールは**%（0〜100の整数）**で持つ。config は**割合**（0.5）。
---   単位が違うので、ここで必ず変換する。混ぜると 50 倍ずれる。
function Bridge:_tactic_heal_ratio(name, who)
  local key = (who == "self") and "self_hp_threshold" or "ally_hp_threshold"
  local percent = self:_tactic_num(name, "healing", key, nil)
  if percent == nil then return self.heal_threshold end
  return percent / 100.0
end

-- ⚠ `_tactic_emergency_ratio` はここにあったが、
--   **緊急回復の廃止（2026-07-31）に伴い削除**した。
--   理由は `_plan_battle_heal` の中の説明を参照（既定では発動しなかった）。

-- 設定の優先順（名前の並び）を、実際に呼ぶ関数の並びへ解決する。
--
-- ★戻り値は関数の配列。`_claim_battle_input` は名前を知らないままこれを回す。
--   分岐を増やさずに作戦を表現するための土台（仕様書 4.1）。
--
-- 既定は [heal, item, target] で、**P3 までの実装順と同じ**。
--
-- ⚠ target を最後に置くのは順番の好みではない。target は「行動を決める」のではなく
--   「敵選択の画面でカーソルを寄せる」ものなので、heal / item が成立しなかった
--   ときにだけ意味を持つ。前に置くと敵選択の画面で回復の判断が回らなくなる。
--   ★だから **target が最後でない並びは警告して最後へ回す**。
--     利用者の指定を黙って書き換えるのではなく、書き換えたことを言う。
local BATTLE_CLAIMS = {
  heal   = function(self) return self:_claim_battle_heal() end,
  -- ★★ 攻撃呪文（2026-08-03 / 「ガンガン行こうぜ」）
  --   ⚠ 設定が無ければ何も主張しない（既定は無効）
  attack = function(self) return self:_claim_battle_attack() end,
  item   = function(self) return self:_claim_battle_item() end,
  target = function(self) return self:_claim_target_selection() end,
}
-- ★★ `attack` は既定に**入れる**（2026-08-03 / 依頼者の指定）★★
--
--   以前は「設定した人だけが使う」ために外していました。しかし
--   ガンガン行こうぜが作戦設定画面から選べるようになったので、
--   **画面で ON にしたのに priority も直さないと動かない**という
--   二段構えになってしまいます。⚠ これは必ず「ONにしたのに効かない」を生みます。
--
--   ★安全なのは、**入り口を1つに絞る**こと:
--     ・priority には常に attack を入れておく（順番の宣言でしかない）
--     ・使うかどうかは作戦設定画面のチェック（★既定 OFF）だけで決まる
--
--   ⚠ `heal` を `attack` より**前**に置くのは依頼者の指定です。
--     HP が減っていれば先に回復します（ガンガンでも全滅しにくいように）。
local DEFAULT_BATTLE_PRIORITY = { "heal", "attack", "item", "target" }

--- どの判断エンジンを使うか（2026-08-04 / 戦闘AI再設計 Phase 1）。
---
--- ★★ **既定は `legacy`。触らなければこれまでとまったく同じです。** ★★
---
--- ⚠⚠ 知らない名前を書いたときは**警告して legacy を使います**。
---   ★黙って別のエンジンで戦わせない。設定の打ち間違いは
---     「効かない」ではなく「**気づける**」が正解です
---     （`_resolve_battle_priority` が知らない行動名を警告するのと同じ）。
function Bridge:_resolve_engine(want)
  local Types = self.battle_types
  if Types == nil then return "legacy" end
  local got = Types.parse(Types.Engine, want)
  if want ~= nil and got == nil then
    self:log(string.format(
      "⚠ 知らない判断エンジン %s を指定されたため legacy を使います"
      .. "（使えるのは %s）",
      tostring(want), table.concat(Types.names(Types.Engine), " / ")),
      "engine: unknown -> legacy", "WARNING")
    return Types.Engine.LEGACY
  end
  return got or Types.Engine.LEGACY
end

--- 三層構造で判断するか。
--
-- ## ★ いま何が効いているか（2026-08-08 時点）
--
--   | Phase | どこで効くか |
--   | --- | --- |
--   | 10A | ★攻撃呪文の**拒否**（`_plan_battle_attack` の1か所だけ） |
--   | 10C | ★行動の**優先順**（省資源なら道具を攻撃より先に） |
--
--   ⚠⚠ **拒否点を増やさないこと**（★相談回答の最重要指摘）。
--     呪文は「メニュー -> 一覧 -> カーソル -> A -> 敵選択 -> A」と
--     複数フレームにまたがります。⚠ 2か所目を足すと、
--     **行動の途中で拒否して別の claim が入力する事故**が起きます。
--     ★`layered_veto_test.lua` が `_may_act(` の数を見張っています。
--
-- ## ⚠⚠ `engine: legacy` は **消しません**（2026-08-08 に判断）
--
--   ★Phase 10 で消したのは「モジュールが読めない環境のための控え」で、
--     ⚠ **この設定とは別物**です。
--
--   ⚠ ここを消す ＝ すべての利用者で layered を既定にする、という意味です。
--     相談回答 §12 の条件のうち、★まだ満たしていないものがあります:
--
--       3. veto 後 -> 無行動 0 / menu stuck 0 / 意図しない逃走 0   ⚠ 未測定
--       4. 実機 monkey -> 重大回帰 0                               ⚠ 未実施
--       5. 手動介入率 -> legacy 比で悪化していない                 ⚠ 未測定
--
--   ★これらは**実機で測るしかありません**。測るまでは安全弁として残します。
--
function Bridge:_use_layered()
  return self.battle_engine == "layered"
end

--- ★このターンの優先順（Phase 10C / 2026-08-07）。
--
-- ⚠ 指示が無ければ**設定どおり**（★従来の挙動）。
--
-- ★★ いま効かせるのは1つだけ: **MPを温存するなら道具を先に**。
--   ⚠ 省資源のとき「呪文は却下 → 道具」の順で降りていましたが、
--     ★杖はMPを使わないので、**先に試すほうが速い**です。
--   ⚠⚠ 禁止（10A）より柔らかい形。★使えない場面では素通りします。
function Bridge:_battle_priority_now()
  local d = self:_current_directive()
  if d == nil or d.resource_policy ~= "preserve_mp" then
    return self.battle_priority
  end
  -- ★item を attack より前へ（⚠ 他の順番は変えない）
  local out, item_fn = {}, nil
  for i, fn in ipairs(self.battle_priority) do
    if self.battle_priority_names ~= nil
      and self.battle_priority_names[i] == "item" then
      item_fn = fn
    end
  end
  if item_fn == nil then return self.battle_priority end
  -- ⚠⚠ **黙って並べ替えない**（★playbook #35 / 今日も何度も踏んだ）。
  --   ⚠ 順番が変わったことが分からないと、実機ログで
  --     「効いているのか」を**確かめようがありません**。
  --   ★1戦闘に1回だけ出します（⚠ 毎ターンだとログが埋まります）。
  if not self.priority_bias_logged then
    self.priority_bias_logged = true
    self:log(string.format(
      "[順番] 戦術「%s」でMPを温存するため、道具を攻撃より先に試します",
      tostring(d.primary_plan or "?")), "priority bias: item first", "DEBUG")
  end
  for i, fn in ipairs(self.battle_priority) do
    local name = self.battle_priority_names
      and self.battle_priority_names[i] or nil
    if name == "item" then
      -- ⚠ ここでは足さない（★attack の前に入れる）
    elseif name == "attack" then
      out[#out + 1] = item_fn
      out[#out + 1] = fn
    else
      out[#out + 1] = fn
    end
  end
  return out
end

function Bridge:_resolve_battle_priority(names)
  if names == nil or #names == 0 then names = DEFAULT_BATTLE_PRIORITY end

  local out, seen, unknown, dup = {}, {}, {}, {}
  local order = {}
  for _, name in ipairs(names) do
    local key = tostring(name)
    if BATTLE_CLAIMS[key] == nil then
      unknown[#unknown + 1] = key
    elseif seen[key] then
      dup[#dup + 1] = key
    else
      seen[key] = true
      order[#order + 1] = key
    end
  end

  -- ★書かれていない行動は**末尾に足す**（消さない）。
  --   priority に heal だけ書いた人が、杖と倒す順を失うのは意図と違う。
  --   「並べ替えの設定」であって「有効にする設定」ではない
  --   （有効/無効はそれぞれの enabled が持っている）。
  local added = {}
  for _, key in ipairs(DEFAULT_BATTLE_PRIORITY) do
    if not seen[key] then
      seen[key] = true
      order[#order + 1] = key
      added[#added + 1] = key
    end
  end

  -- target を最後へ回す（上のコメントの理由）
  local moved = false
  for i, key in ipairs(order) do
    if key == "target" and i ~= #order then
      table.remove(order, i)
      order[#order + 1] = "target"
      moved = true
      break
    end
  end

  -- ★★ 名前も覚える（Phase 10C / 2026-08-07）。
  --   ⚠ 関数だけだと「どれが item か」が分からず、順番を入れ替えられません。
  self.battle_priority_names = {}
  for _, key in ipairs(order) do
    out[#out + 1] = BATTLE_CLAIMS[key]
    self.battle_priority_names[#self.battle_priority_names + 1] = key
  end

  -- ★解決した結果を必ず1行出す。黙って並べ替えない（playbook #35）。
  self:log("戦闘の行動の優先順: " .. table.concat(order, " -> "),
    "battle priority: " .. table.concat(order, " -> "), "DEBUG")
  if #unknown > 0 then
    self:log(string.format(
      "⚠ 知らない行動名を飛ばしました: %s"
      .. "（使えるのは heal / attack / item / target）",
      table.concat(unknown, ", ")), nil, "WARNING")
  end
  if #dup > 0 then
    self:log("⚠ 優先順に同じ行動が2回書かれていました: " .. table.concat(dup, ", "), nil, "WARNING")
  end
  if #added > 0 then
    self:log("優先順に書かれていない行動を末尾に足しました: " .. table.concat(added, ", "), nil, "DEBUG")
  end
  if moved then
    self:log("⚠ target は対象を選ぶだけなので**末尾**に回しました"
      .. "（前に置くと回復の判断が回りません）", nil, "DEBUG")
  end
  return out
end

--- AI操作OFF のキャラクターの番なら、その番を**プレイヤーへ返す**（仕様書 4.4）。
---
--- 戻り値: `{}`（最初の数フレームだけ全部離す） / `HANDS_OFF`（人に返す）
---         / nil（AI で操作してよい）
---
--- ★★ **なぜ3つあるのか**（2026-07-31 / 実機 T-5 で作り直した）★★
---
---   nil を返すと下へ落ちて「たたかう」の A 連打になる。OFF にしたのに
---   勝手に戦うので、nil ではいけない。ここまでは最初から正しかった。
---
---   ⚠⚠ **だが `{}` を返し続けたのが誤りだった。**
---     `{}` は「全ボタンを強制的に離す」を毎フレーム送る指示なので、
---     人がキーを押しても**同じフレームで打ち消される**。
---     結果、AI操作OFF にすると**キーボードが一切効かなくなった**
---     （FCEUX の入力表示には出るのにゲームへ届かない = 実機 T-5 の症状）。
---
---   そこで `HANDS_OFF` を足した。「主張しない、かつ下へも落とさない」。
---   `joypad.set` を呼ばないので、人の入力がそのままゲームへ届く。
---
--- ★最初の数フレームだけ `{}` を送るのは残す。番が変わる直前まで AI が
---   押していたボタンを断ち切るため（戦闘終了直後の `release_left` と同じ考え）。
---   **期限つきなら正しい**。誤りは期限の無い `{}` を返却に使ったこと。
---
--- ⚠ 誰の番か読めないときは nil（これまでどおり）。ここで止めると、
---   入力待ちが読めない環境で**自動戦闘が丸ごと動かなくなる**。
--- ★★ 固定戦略（ユーザー指定1）の、いまの番のキャラの指定行動を返す。
---   （2026-08-11 / UI整理 Phase 4）
---
--- 戻り値:
---   nil            … 固定戦略ではない／番が読めない → 通常のAI
---   "attack"       … たたかう
---   { item = id }  … その道具を毎ターン使う
---
--- ⚠ 中身（誰が何を）は config.lua の `user_strategies`。ここは
---   `tactics.lua` の `strategy` 目印（有効かどうか）と突き合わせるだけ。
function Bridge:_fixed_action_for_current()
  local strat = self.tactics and self.tactics.strategy
  if strat == nil or strat.type ~= "fixed" then return nil end
  local us = (self.config.user_strategies or {})[strat.id]
  if us == nil then return nil end
  local m = self.game:battle_input_member()
  if m == nil then return nil end                 -- ★番が読めない→手を出さない
  local spec = (us.actors or {})[m.name]
  if spec == nil then return "attack" end         -- ★指定が無ければ たたかう
  if spec.action == "item" and spec.item ~= nil then
    -- ★fallback: 道具が持ち物に無いときの代替（defend 等 / 2026-08-11）
    return { item = spec.item, fallback = spec.fallback }
  end
  return "attack"
end

function Bridge:_claim_manual_character()
  if self.tactics == nil then return nil end        -- プロフィール未使用
  local a = self.memory_map.addresses
  local menu = memory.readbyte(a.menu_id.addr)
  -- ★コマンドメニュー以外（メッセージ・演出）では判断しない。
  --   その画面の A は「送り」なので、止めると戦闘が進まなくなる。
  if menu ~= a.menu_id.values.battle_menu then return nil end

  local m = self.game:battle_input_member()
  if m == nil or m.name == nil then return nil end

  -- ★★ 誰の番かを覚える（2026-08-08 / 資産化）★★
  --   ⚠ 番が変わったら、前の人の「たたかう」を確定させます。
  --   ★ここは戦闘コマンドメニューで**毎ポーリング**通ります。
  self:_track_turn_actor(m)

  -- ★番が変わったら代替行動の歯止めをやり直す（同じ人の中では数え続ける）
  if self.fb_member ~= m.index then
    self.fb_member = m.index
    self.fb_presses, self.fb_tried, self.fb_left = 0, false, 0
    -- ★番が変わった直後だけ「全部離す」を送る予約（上の解説を参照）
    self.manual_release_left = self.manual_release_frames
  end

  local why = (not self:_tactic_ai_enabled(m.name)) and "AI操作OFF" or nil

  -- ★★ 役割「手動」（仕様書 4.4 の role: manual）★★
  --
  --   ⚠ 仕様書は role: manual の**中身を書いていない**ので、こちらで決めた:
  --     AI操作ON ＋ 役割「手動」 = **AI は代替行動しかしない**。
  --     （例: 代替行動を「防御」にすれば、その人はずっと防御する）
  --   ★AI操作OFF との違い: OFF は**一切押さない**（人が押す）。
  --     役割「手動」は AI が押すが、選ぶのは代替行動だけ。
  --   合わないなら変えてください（この関数1つだけ直せば済みます）。
  if why == nil and not self.fb_tried
    and self:_tactic_text(m.name, nil, "role", "") == "manual" then
    return self:_claim_fallback_action(m, "役割が「手動」")
  end

  if why == nil then return nil end       -- AI で操作してよい

  -- ★同じ人の番の間に何度も出さない（毎フレーム出ると読まれない通知になる）
  if self.manual_notice ~= m.name then
    self.manual_notice = m.name
    self:log(string.format("%s は%sのため手動です（戦術プロフィール）",
      tostring(m.name), why), "tactics: manual " .. tostring(m.name), "DEBUG")
  end
  return self:_release_then_hands_off()
end

--- 番の頭だけ「全部離す」を送り、そのあとは人に返す。
--- ★AI操作OFF と 代替行動「手動」の**両方**が使う（同じ扱いにする）。
function Bridge:_release_then_hands_off()
  local left = self.manual_release_left or 0
  if left > 0 then
    self.manual_release_left = left - 1
    return {}                     -- 直前の押下を断ち切る（期限つき）
  end
  return HANDS_OFF                -- 以降は joypad.set を呼ばない = 人が押せる
end

--- 代替行動（仕様書 4.4 の fallback_action）を実行する。
---
--- | 設定 | すること |
--- | --- | --- |
--- | `attack` | 何もしない（nil を返す）→ 従来どおり「たたかう」 |
--- | `defend` | 行2「ぼうぎょ」へ寄せて A |
--- | `manual` | 番の頭だけ全部離し、あとは人に返す（`HANDS_OFF`） |
---
--- ★「ぼうぎょ」が行2 なのは **memory_map の実測**（0x09 の rows）。
---   ⚠ 行1 は人によって「にげる / じゅもん」と変わるが、**行2 は共通**。
---   だから行2 は誰にでも押して安全（行1 を押すとローレシアが逃げ出す）。
---
--- ⚠ 押しても進まないときの歯止めを入れる（playbook #9）。
---   入れないと、画面が変わらないまま押し続けてターンが終わらない。
function Bridge:_claim_fallback_action(m, why)
  local action = self:_tactic_text(m.name, "safety", "fallback_action", "attack")
  if action == "attack" then return nil end        -- 従来どおり

  if self.manual_notice ~= m.name then
    self.manual_notice = m.name
    self:log(string.format("%s は%sのため%sします（戦術プロフィール）",
      tostring(m.name), why,
      (action == "defend") and "防御" or "手動へ戻"),
      "tactics: fallback " .. tostring(action), "DEBUG")
  end
  -- ★manual: 人に返す。⚠ `{}` ではなく `HANDS_OFF`。
  --   `{}` を返し続けると人のキーを毎フレーム打ち消す（実機 T-5）。
  if action ~= "defend" then return self:_release_then_hands_off() end
  return self:_claim_defend(m)
end

--- 「ぼうぎょ」を押す（行2「ぼうぎょ」へ寄せて A）。
---
--- ★★ 2026-08-11: **1か所に寄せた**。役割「手動:防御」と、亀の子戦術で
---   道具が持ち物に無いときの代替（fallback: defend）の**両方**が使う。
--- ⚠ `fb_*` の状態は番ごとに `_claim_manual_character` が戻す。
---   ★戦闘コマンドメニューでは必ず通る（下の門番でそこしか来ないため）。
--- 戻り値: 入力テーブル（押下中）／`{}`（待ち）／nil（諦め＝従来どおりへ）。
function Bridge:_claim_defend(m)
  local a = self.memory_map.addresses

  -- ★★ 戦闘コマンドメニュー以外では何も主張しない（2026-08-12）★★
  --
  --   ⚠⚠ **`cursor_x == 255` は「コマンドが開いている」の目印になりません。**
  --     memory_map.yaml の `menu_cursor_x` に「**戦闘中は 0xFF（無効値）に
  --     なる**」と書いてあるとおり、メッセージ・演出の間もずっと 255 です。
  --
  --   ⚠ 門番が無かったため、演出中に方向キーを押し続けて歯止め（16回）を
  --     使い切り、**コマンドが開く前に諦めて**いました。実機ログの
  --     「防御の入力が 17 回で進まないため、この番は従来どおりにします」が
  --     これで、亀の子は実質「全員たたかう」になっていました。
  --     ★再現と回帰: `research/probes/active/defend_input_test.lua`。
  --
  --   ⚠ 返すのは `{}` ではなく **nil**。`{}` は「全ボタンを離す」なので、
  --     メッセージ送りの A まで毎フレーム打ち消して戦闘が止まります
  --     （固定戦略の呼び出し元は `{}` をそのまま返すため）。
  --     ★兄弟の `_claim_battle_heal` / `_claim_battle_item` も同じ場面で nil。
  if memory.readbyte(a.menu_id.addr) ~= a.menu_id.values.battle_menu then
    return nil
  end

  -- ★★ 番が変わったら数え直す（★この関数が自分で持つ / 2026-08-12）★★
  --
  --   ⚠⚠ 以前は「`_claim_manual_character` が戻す（そこを**必ず通る**）」と
  --     書いてありましたが、あの関数は `menu ~= battle_menu` で早期 return
  --     するので、**通らない場面がありました**。前提が崩れると:
  --       ・前の人の押下数を引き継いで、すぐ諦める
  --       ・⚠⚠ 前の人の押下サイクル（`fb_left`）が残り、次の人の番に
  --         **行0（たたかう）で A を押す**（probe の 4 で実際に踏んだ）
  --   ★呼び出し順に依存しないよう、ここでも同じ判定を持ちます。
  --   ⚠ `_claim_manual_character` は必ず先に走るので、二重に戻しても
  --     同じ添字を見るだけで、片方が空振りするだけです。
  if self.fb_member ~= m.index then
    self.fb_member = m.index
    self.fb_presses, self.fb_tried, self.fb_left = 0, false, 0
    self.fb_button = nil
  end

  local cx = memory.readbyte(a.menu_cursor_x.addr)
  local cy = memory.readbyte(a.menu_cursor_y.addr)
  -- 入力を受け付ける状態になるまで押さない（cursor_x=255 が目印）
  if cx ~= 255 then return {} end

  -- 押下中／離し中は続ける（hold で押して gap で離す）
  if (self.fb_left or 0) > 0 then
    local n = self.fb_left
    self.fb_left = n - 1
    if n > self.bh_gap and self.fb_button ~= nil then
      return { [self.fb_button] = true }
    end
    return {}
  end

  self.fb_presses = (self.fb_presses or 0) + 1
  if self.fb_presses > self.heal_max_presses then
    -- ★諦めて従来どおりにする（戦闘が止まる方が害が大きい）
    self:log(string.format(
      "防御の入力が %d 回で進まないため、この番は従来どおりにします（%s）",
      self.fb_presses, tostring(m.name)), "tactics: defend give up", "DEBUG")
    self.fb_tried = true
    return nil
  end

  local DEFEND_ROW = 2
  self.fb_button = (cy ~= DEFEND_ROW)
    and ((cy < DEFEND_ROW) and "down" or "up") or "A"
  self.fb_left = self.bh_hold + self.bh_gap
  return { [self.fb_button] = true }
end

function Bridge:_claim_battle_input()
  if not (self.state.in_battle and self:auto_input_allowed()) then
    self.input_state = "a_hold"
    self.input_left  = 0
    self.was_victory = false
    return nil
  end

  -- ★★ キャラクター別「AI操作」（2026-07-30 / 仕様書 4.4）★★
  --
  --   > AI操作OFFの場合、そのキャラクターの入力は自動実行しない。
  --   > キャラクター単位でAIと手動を混在可能にする。
  --
  -- ⚠ **nil ではなく `{}` を返す。** nil を返すと下へ落ちて「たたかう」の
  --   A 連打になり、OFF にしたのに勝手に戦う。`{}` は全ボタンを離す指示なので、
  --   その人の番は**プレイヤーが自分で押せる**。
  --
  -- ⚠ 誰の番か読めないときは**これまでどおり**にする（何もしないと戦闘が止まる）。
  local ai_off = self:_claim_manual_character()
  if ai_off ~= nil then return ai_off end

  -- ★★ ユーザー指定戦略（固定行動 / 2026-08-11 / Phase 4）★★
  --
  --   custom_1 が有効なら、そのキャラの**指定行動**を実行する。
  --   ⚠ 通常の優先順（heal/attack/item/target）は**回さない**（横取り）。
  --     ・item 指定  → 指定の道具を条件なしで使う（`_forced_item`）
  --     ・attack 指定 → 何も主張せず「たたかう」へ落ちる
  --   ★指定の道具が使えない（在庫切れ等）ときも「たたかう」へ落ちる。
  self._forced_item = nil
  local fixed = self:_fixed_action_for_current()
  local skip_priority = false
  if fixed ~= nil then
    skip_priority = true              -- ★固定戦略: 優先順は回さない
    if type(fixed) == "table" and fixed.item ~= nil then
      self._forced_item = fixed.item
      local claim = self:_claim_battle_item()
      self._forced_item = nil
      if claim ~= nil then return claim end
      -- ⚠ 指定の道具が使えなかった（在庫切れ等）。★fallback があれば代替へ。
      --   `defend` = ぼうぎょ（亀の子。盾を切らしても身を守る / 2026-08-11）。
      if fixed.fallback == "defend" and not self.fb_tried then
        local dm = self.game:battle_input_member()
        if dm ~= nil then
          if self.fixed_defend_notice ~= dm.name then
            self.fixed_defend_notice = dm.name
            self:log(string.format(
              "%s は指定の道具が無いので防御します（亀の子戦術）",
              tostring(dm.name)), "fixed: defend (no item)", "DEBUG")
          end
          local d = self:_claim_defend(dm)
          if d ~= nil then return d end
        end
      end
      -- ⚠ fallback 無し／防御も進まない → 下の「たたかう」へ落ちる
    end
    -- ★"attack" もしくは道具切れ → 優先順を飛ばし、下の A 連打（たたかう）へ
  end

  -- ★作戦（Phase 6 P5）: **設定した順**に評価し、最初に成立したものを実行する。
  --
  --   heal   … 回復呪文（P3 / MPを使う）
  --   item   … 戦闘中の道具（杖など。MPも在庫も使わない / DEV-24）
  --   target … 敵選択メニューで倒す順の優先指定へ寄せる（DEV-19）
  --
  --   どれも nil を返せば従来どおり「たたかう」になる。
  --
  -- ★既定 [heal, item, target] は**P3 までの実装順そのまま**。
  --   設定を変えなければ挙動は変わらない（DEV の作法）。
  --   リソース維持優先（依頼者の項目7）は [item, heal, target] にする。
  --
  -- ⚠ 名前の解決は起動時に済ませてある（self.battle_priority）。
  --   毎フレーム文字列を照合すると、知らない名前を**毎フレーム**警告することになる。
  -- ★★★ **戦術で順番を入れ替える**（2026-08-07 / Phase 10C）★★★
  --
  --   相談回答 §15C「Priority Bias」:
  --   > heal / attack_spell / item / physical_attack / defend などの候補に、
  --   > layered 側から優先度補正を与える。
  --
  -- ⚠⚠ **ここは「順番」だけを変えます。** ★各 claim の中身は触りません。
  --   拒否（Phase 10A）と同じで、⚠ 行動の途中では変わりません
  --   （★順番はターン単位で決まり、`_current_directive()` が固定します）。
  for _, claim_fn in ipairs(skip_priority and {} or self:_battle_priority_now()) do
    local claim = claim_fn(self)
    if claim ~= nil then return claim end
  end

  local victory = (self.game.showing_victory ~= nil) and self.game:showing_victory() or false

  -- ★勝利メッセージが閉じた瞬間に押下を打ち切る。
  -- 押しっぱなしのままフィールドへ戻ると、その A がコマンドメニューを開く
  -- （実機ログ work/postbattle/real.txt で確認。戦闘終了の2フレーム後に必ず開いた）。
  if self.was_victory and not victory then
    self.was_victory = false
    self.input_state = "a_gap"
    self.input_left  = self.input_frames.a_gap
    return {}                       -- 全ボタンを離す（明示）
  end
  self.was_victory = victory

  -- 勝利メッセージ中は短く押して長く離す。
  -- メッセージ送りは取りこぼしても次の周期で押し直せるが、
  -- 押しっぱなしがフィールドへ漏れる方は取り返しがつかない。
  local frames = victory and self.victory_frames or self.input_frames

  if self.input_left <= 0 then
    self.input_state = (self.input_state == "a_hold") and "a_gap" or "a_hold"
    self.input_left = frames[self.input_state] or 1
  end
  self.input_left = self.input_left - 1

  local pressing = (self.input_state == "a_hold")

  -- ★勝利メッセージの送りだけ B を使う。
  --
  -- 戦闘のコマンドメニューでは B は「キャンセル」なので押してはいけない（B-7）。
  -- しかし勝利メッセージにはキャンセルする対象が無く、B でも送れる。
  --
  -- なぜ A を避けるか: メッセージを閉じた A 押下がそのままフィールドの
  -- コマンドメニューを開いてしまう（戦闘終了の2フレーム後に必ず開いた）。
  -- ボタンを離しても、入力ラッチ($002F)を空にしても防げなかった
  -- ＝ゲーム内部で1回の A が「メッセージを閉じる」と「メニューを開く」の
  -- 両方に使われている。**フィールドで無害なボタンで送るのが唯一の解**。
  -- B はフィールドで何も開かない。
  if victory and self.victory_button == "B" then
    return { B = pressing }
  end
  return { A = pressing }
end

-- 演出を尊重した等速復帰（速度制御バックログ 3章 / 2段構成版）。
--
-- ★背景: 反復作業は速くしたいが、**達成感のある演出まで速くしたくない**。
--   レベルアップやレアドロップが一瞬で流れると、嬉しさごと削ってしまう。
--
-- ★B-8 が決着したため、速度は **normal と turbo の2段**しか使えない
--   （任意倍率は FCEUX Lua では遊べる形で実現できない / open_questions B-8）。
--   バックログの speed_profiles（8.0倍/2.0倍…）は実装できないが、
--   **「この瞬間だけ等速に戻す」という中核は2段でも成立する。**
--   諦めるのは刻みの作り分けだけで、体験の狙いは達成できる。
--
-- いま検知できるもの（RAMから確実に読めるものだけ。推測で増やさない）:
--   ・レベルアップ … レベル値($063E + 添字*0x12)の増加。警戒リスト解除で実績あり
--   ・仲間の死亡   … 生存者数の減少
--
-- まだ検知できないもの（実装しない。憶測でイベントを作らない）:
--   ・レアドロップ / 通常ドロップ … ドロップの記録場所が未特定
--   ・ふくびきの当たり … 当たり判定の場所が未特定（ゴールド変化では外れと区別できない）
--   ・会心の一撃 … 未特定
--   これらは検知手段が見つかってから足す。
function Bridge:_check_speed_events()
  local cfg = self.speed_events
  if cfg == nil or cfg.enabled == false then return end

  -- レベルアップ
  -- ⚠ _check_level_up() とは**別のスナップショット**を持つ。
  --   同じ変数を使うと、先に見た方が変化を食べてしまい他方が発火しない。
  if cfg.level_up ~= false then
    local now = self:_level_snapshot()
    if self.speed_levels == nil then
      self.speed_levels = now
    else
      for index, lv in pairs(now) do
        local before = self.speed_levels[index]
        if before ~= nil and lv > before then
          -- ★レベルアップは長く等速を保つ（ステータス/呪文習得まで / RX-0070）
          self:_fire_speed_event(string.format("レベルアップ（LV%d -> %d）", before, lv),
            "LEVEL UP", cfg.level_up_hold_frames)
        end
      end
      self.speed_levels = now
    end
  end

  -- 仲間の死亡
  if cfg.member_death ~= false then
    local alive = 0
    for _, m in ipairs(self.game:active_party()) do
      if m.alive then alive = alive + 1 end
    end
    if self.speed_alive ~= nil and alive < self.speed_alive then
      self:_fire_speed_event(string.format("仲間が倒れた（生存 %d -> %d 人）",
        self.speed_alive, alive), "MEMBER DOWN")
    end
    self.speed_alive = alive
  end

  -- ★等速保持の残りを1フレーム進める（持ち主は speed_controller）
  self.speed:tick()
end

function Bridge:_fire_speed_event(reason, label, hold)
  -- ★★ 保持そのものは `speed_controller` の仕事（リファクタ §4.4）★★
  --   ⚠ hold を渡すとその長さで保つ（レベルアップは長め / RX-0070）。
  if self.speed:begin_normal_speed(reason, hold) then
    self:log("演出のため等速に戻します: " .. reason,
             "event normal: " .. tostring(label))
    self:notify(tostring(label), 180)
    self:emit("speed_event", { reason = reason })
  end
end

function Bridge:_reset_battle_heal()
  self.bh_left, self.bh_button = 0, nil
  self.bh_member, self.bh_tried = nil, false
  self.bh_settle = nil
  self.bh_plan = nil
  self.bh_presses = 0
end

-- ボタンを1回押す（hold 押して gap 離す）。押した回数も数える。
--
-- ★回数を数えるのは**上限を置くため**（playbook #9「すべてのループに上限」）。
--   例えば「じゅもん」を決定したのに呪文リストが開かない状況では、
--   画面が 0x09 のままなので A を押し続けてしまう。
--   何回押しても進まないなら前提が違う。その番は諦めて殴る。
function Bridge:_bh_press(button)
  self.bh_button = button
  self.bh_left = self.bh_hold + self.bh_gap
  self.bh_presses = (self.bh_presses or 0) + 1
  return { [button] = true }
end

-- この番の人が唱えるべき回復呪文と対象を決める。
-- 戻り値: 計画のテーブル / 唱えないなら nil, 理由
--
-- ★「回復が必要な人が居る」だけでは足りない。**唱えられる人の番**でなければ
--   何もしない。誰の番かを見ずに行1を押すとローレシアが逃げ出す（O-1）。
-- ★★ AI判断を**人ごとに**覚える（2026-07-31 / 依頼者の指摘）★★
--
--   > ３人分表示する（行動者毎に切り替えしない）
--   > 選択が（回復の出番なし。たたかう）だらけな気がする
--
--   ⚠⚠ **以前は「回復を実行したときだけ」記録していた。**
--     しないときの理由（MP不足・回復不要・マホトーン）は
--     **1戦闘に1回ログへ出すだけ**で、画面には何も届いていなかった。
--     だから毎回「回復の出番なし。たたかう」しか出なかった。
--
--   ★記録は**人ごと**に持つ。1つの箱に入れると、最後に入力した人の
--     判断で上書きされ、他の2人が見えない（それが「切り替わる」の正体）。
--- ★★★ AI が決めた行動を1件だけ残す（2026-08-08 / 資産化）★★★
---
--- ## ⚠⚠ なぜ作ったか
---
---   `battle_cases survey` で分かったこと（★2026-08-08 より前の姿）:
---
---       action events 523 … ★**全部が回復**
---       物理攻撃 0 / 攻撃呪文 0 / 道具 0
---
---   ⚠ 記録していたのが**回復の1か所だけ**だったためです。
---   ★ログを貯めても、再生できるケースは回復しか作れませんでした。
---
--- ## ★★ 解消済み（2026-08-13 に実測で確認）★★
---
---   呼び出し元は4か所（物理 `_flush_physical` / 回復 / 攻撃呪文 / 道具）。
---   実測 3,296 件の内訳:
---
---       たたかう 2,851 / 道具 202 / 攻撃呪文 136 / 回復呪文 107
---
---   ★上の「全部が回復」は**当時の記録**として残してあります
---     （⚠ 消すと、なぜこの形にしたのかが分からなくなるため）。
---
--- ## ★ 1人1ターン1件（⚠ 押下の道は毎ポーリング通ります）
---
---   ⚠⚠ 印を置かないと、**同じ行動が何十件も並びます**。
---     ★判断の記録（`_emit_decision_snapshot`）と**同じ数**になるのが正しい形です。
---
--- ## ⚠ 手動入力は記録しません
---
---   ★何を押したか分からないので、「AI が決めた」とは書けません
---     （⚠ 分からないものを記録すると、ケースが嘘になります）。
---
--- 戻り値: 記録したか（⚠ 2回目以降は false）
function Bridge:_record_action(member, action, target, reason)
  if member == nil or member.index == nil then return false end
  local mark = string.format("%s/%s", tostring(self.turn_no or 0),
                             tostring(member.index))
  self.action_logged = self.action_logged or {}
  if self.action_logged[mark] then return false end
  self.action_logged[mark] = true

  -- ★★★ **判断の記録が無ければ、ここで作ります**（2026-08-08）★★★
  --
  --   ⚠⚠ 実機で **35件の行動に `decision_id` が付いていません**でした。
  --     ★`_note_decision` を通らない道から `_record_action` が呼ばれると、
  --       印がまだ無いためです。
  --   ⚠ 判断IDの無い行動は**再生ケースになりません**（★対にできない）。
  --
  --   ★`_emit_decision_snapshot` は1人1ターン1件なので、
  --     すでにあればそのIDを返すだけです（⚠ 二重に出ません）。
  local decision_id = (self.snapshot_done or {})[mark]
  if decision_id == nil then
    local ok_snap = pcall(function()
      decision_id = self:_emit_decision_snapshot(member)
    end)
    if not ok_snap then decision_id = nil end
  end

  self.turn_seq = (self.turn_seq or 0) + 1
  self:emit("battle_action", {
    turn = self.turn_no or 0, seq = self.turn_seq,
    actor = member.name, action = action, target = target,
    selected_by = "ai", reason = reason,
    decision_id = decision_id,       -- ★これで必ず対になります
  })
  return true
end

--- 「たたかう」を確定させる（2026-08-08 / 資産化）。
---
--- ## ⚠⚠ **その人の番が終わってから**呼びます
---
---   ★順番は `heal -> attack -> item -> target`。
---   ⚠ 早く呼ぶと、**道具を使ったのに「たたかう」と記録**されます
---     （`_record_action` は1人1ターン1件なので、先に立ったほうが勝つ）。
---
---   ⚠⚠ 最初は `_claim_battle_item` の中で呼んでいましたが、
---     ★あそこには**早期 return が多く**（道具が無効・上限・メニュー違い・
---     既に試した…）、**たどり着かない道がありました**。
---     実機で「判断はあるが行動が無い」が **25件**出て分かりました。
---
---   → ★**入力を求められる人が変わった時点**で、前の人ぶんを確定します。
---     ⚠ そこまで何も記録されていなければ、残るのは「たたかう」です。
function Bridge:_flush_physical()
  local prev = self.turn_actor
  if prev == nil then return false end
  local mark = string.format("%s/%s", tostring(prev.turn),
                             tostring(prev.index))
  if (self.action_logged or {})[mark] then return false end
  -- ⚠ ターンをまたいでいるので、印は当時のものを使います
  local saved = self.turn_no
  self.turn_no = prev.turn
  -- ⚠⚠ 理由は**その人自身の判断**からだけ取る（2026-08-11）。
  --   ★以前は `prev.reason`（＝番が始まった時点の `last_ai_reason`）を
  --     使っていたが、これは**直前に行動した別の人の理由**（例: サマルの
  --     「ちからのたて（固定行動）」）が入り込む。ローレシアの素の
  --     「たたかう」に他人の道具理由が付いて紛らわしかった（依頼者のログ確認）。
  --   ★素の「たたかう」は理由なし（nil）。自分で「たたかう」を選んだ判断を
  --     残していれば、その理由だけを使う。
  local own = (self.ai_decisions or {})[prev.index]
  local reason = nil
  if own ~= nil and own.turn == prev.turn then
    reason = own.reason
  end
  local done = self:_record_action(prev, "たたかう", nil, reason)
  self.turn_no = saved
  return done
end

--- いま入力を求められている人を覚える（★番が変わったら前の人を確定）。
function Bridge:_track_turn_actor(member)
  if member == nil or member.index == nil then return end
  local prev = self.turn_actor
  if prev ~= nil and (prev.index ~= member.index
                      or prev.turn ~= (self.turn_no or 0)) then
    -- ⚠ 落ちても本体は止めない（★記録だけの機能）
    pcall(function() self:_flush_physical() end)
  end
  if prev == nil or prev.index ~= member.index
     or prev.turn ~= (self.turn_no or 0) then
    -- ⚠ ここで `last_ai_reason` を覚えない（2026-08-11）。
    --   番が始まった時点の理由は**直前の別の人**のもので、素の「たたかう」に
    --   紛れ込む。理由は `_flush_physical` が本人の判断から取り直す。
    self.turn_actor = { index = member.index, name = member.name,
                        turn = self.turn_no or 0 }
  end
end

--- ★★★ 判断の直前の状態を1件だけ残す（2026-08-08 / 資産化 Phase 4）★★★
---
--- 指示書 §8:
---   > AIが「1人分の行動を決める直前」に snapshot を出す。
---   > **毎フレーム出さない。** 1 actor の判断直前に1件のみ。
---
--- ## ★ 何のために出すのか
---
---   ⚠⚠ いまのログからは **回復のケースしか作れません**
---     （`battle_cases survey` で判明。★行動を記録しているのが回復だけ）。
---   ★この snapshot があれば、⚠ **ゲームを起動せずに** AI へ同じ入力を
---     与えて、同じ判断をするか試せます（＝回帰試験）。
---
--- ## ⚠⚠ 1人1ターン1件だけ（★性能要件 §20）
---
---   判断の道は**毎ポーリング**通ります。★印を置いて1回に絞ります。
---   ⚠ ここを外すと、フレームごとに全状態を書き出すことになります（禁止）。
---
--- ## ⚠ ROM から引けるものは入れません（§11.4）
---
---   ★`monster_id` と `rom_hash` を持たせ、使うときに図鑑から補います。
---   ⚠ そのぶんログが小さくなります。
function Bridge:_emit_decision_snapshot(member)
  if member == nil or member.index == nil then return nil end

  -- ★1人1ターン1件（⚠ 毎フレーム出さないための門）
  local mark = string.format("%s/%s", tostring(self.turn_no or 0),
                             tostring(member.index))
  self.snapshot_done = self.snapshot_done or {}
  if self.snapshot_done[mark] ~= nil then
    return self.snapshot_done[mark]        -- ★同じ判断IDを返す
  end

  -- ★★★ **セッションをまたいで一意にする**（2026-08-13 / §7・§27）★★★
  --
  -- ## ⚠⚠ 何が起きていたか（実測）
  --
  --     battle_decision_snapshot イベント数 : 3,497
  --       ユニークな decision_id            :   833   ⚠ 1 ID あたり 4.2 回
  --
  --   ID は `b{battle_seq}_t{turn}_{name}` で、`battle_seq` は
  --   **セッションごとに 1 から振り直される**。★別セッションの別の判断が
  --   同じ ID になる。
  --
  --   ⚠ さらに `bnil_t1_samaltria` が **201 件**（battle_seq が nil のまま）。
  --
  -- ## ⚠ 「100% 対になる」は健全性の証明にならない
  --
  --   `battle_action` 3,296 件すべてに対の snapshot があったが、
  --   ★**衝突した相手と結ばれても成立する**。
  --
  -- ## ★ 直し方
  --
  --   セッション識別子（`self.session_id`）を前に付ける。
  --   ⚠ `battle_seq` が無いときは **ID を作らない**（★nil を返す）。
  --     「nil という名前の戦闘」を作らないため。
  local battle_seq = (self.state or {}).battle_seq
  if battle_seq == nil then
    -- ⚠ 戦闘の通し番号が無い＝どの戦闘か言えない。★記録しない。
    --   ⚠⚠ ただし**黙って消さない**。実測で 201 件この道を通っていた
    --     （以前は `bnil_t1_samaltria` という**偽の ID** を作っていた）。
    --   ★1回だけ知らせる（毎ターン鳴らさない）。
    if not self.seq_missing_told then
      self.seq_missing_told = true
      self:log("⚠ 戦闘の通し番号が無いため、判断を記録できません"
               .. "（★battle_start より前に判断が走っています）",
               "decision: no battle_seq", "WARNING")
    end
    return nil
  end
  local decision_id = string.format("%s_b%s_t%s_%s",
    tostring(self.session_id or "s0"), tostring(battle_seq),
    tostring(self.turn_no or 0), tostring(member.name))
  self.snapshot_done[mark] = decision_id

  -- ★味方（⚠ AI が見ている値だけ。RAM 全体は出しません）
  local party = {}
  for _, m in ipairs(self.game:active_party()) do
    party[#party + 1] = {
      id = m.name, index = m.index,
      hp = m.hp, max_hp = m.max_hp,
      mp = self:_mp_of(m.index), max_mp = self:_max_mp_of(m.index),
      alive = m.alive, attack = self:_attack_of(m.index),
    }
  end

  -- ★敵（⚠ 能力は `monster_id` から引けるので入れません / §11.4）
  local enemies = {}
  for i, e in ipairs(self:_enemy_view()) do
    enemies[#enemies + 1] = { slot = i - 1, monster_id = e.id, hp = e.hp }
  end

  -- ★戦術・大目的（⚠ **これがログに無いのが survey の指摘でした**）
  local mission = self:_mission()
  local strategy = {
    engine = self.battle_engine,
    profile = self.current_plan,
    mission = mission ~= nil and mission.id or nil,
    reserve_mp = self:_tactic_num(member.name, "resources", "reserve_mp", nil),
    risk = (self.support_config or {}).risk,
  }

  -- ★★ 役割（2026-08-13 / §6・§9）★★
  --   ⚠ これまで human log の `[役割]` にしか無く、**数えられなかった**。
  --   ★1人につき「一番の役割・点数・2番手との差」だけを持つ
  --     （⚠ 候補の全件は入れない。1戦闘で数十件になる）。
  --   ⚠ 見立てが走っていなければ nil（★空の表を作らない）。
  local role = (self.role_view or {})[member.name]

  self:emit("battle_decision_snapshot", {
    decision_id = decision_id,
    turn = self.turn_no or 0,
    actor = member.name,
    rom_hash = (self.memory_map.rom or {}).prg_crc32,
    party = party,
    enemies = enemies,
    strategy = strategy,
    role = role,
  })
  return decision_id
end

function Bridge:_note_decision(member, action, reason)
  if member == nil then return end
  -- ★★ 判断の直前の状態を1件だけ残す（2026-08-08 / Phase 4）★★
  --   ⚠ 落ちても本体は止めない。★ただし理由は1回だけ残す。
  local ok_snap, snap_err = pcall(function()
    self:_emit_decision_snapshot(member)
  end)
  if not ok_snap and not self.snapshot_failed then
    self.snapshot_failed = true
    self:log("⚠ 判断の記録に失敗しました（記録だけの機能なので続けます）: "
      .. tostring(snap_err), "snapshot failed", "WARNING")
  end
  self.ai_decisions = self.ai_decisions or {}
  self.ai_decisions[member.index] = {
    name = member.name,
    index = member.index,
    action = action,
    reason = reason,
    turn = self.turn_no or 0,
  }
  -- ★従来の1つぶんも残す（既存の表示・テストが使っている）
  self.last_ai_action, self.last_ai_reason = action, reason
end

-- ★★★ 「いのちをだいじに」（2026-08-04 / 指示書 §8〜§11）★★★
--
--   > ローレシアを主攻撃役として維持し、
--   > サマルトリアとムーンブルクが回復を担当する。
--
-- ⚠⚠ **既定では何も変わりません。**
--   `healing.protect_target` が `none`（既定）なら、以下はすべて
--   素通りして従来どおり「最も減っている人」を回復します。
--   ★作戦を「いのちをだいじに」にした人だけが、この判断順になります。

--- 二重回復を避けるための予約（指示書 §11）。
--
-- ★★ **先に決めた人の回復見込みを、次の人が見る。** ★★
--
--     ローレシア 最大HP100 / 現在HP40
--       サマル: ベホイミ(見込み45) -> 予約 -> 予約後HP 85
--       ムーン: 予約後HP 85 で判断 -> 回復不要 -> 攻撃へ
--
-- ⚠ 予約は**ターンごとに捨てます**。持ち越すと、前のターンに
--   回復したつもりのHPで次のターンを判断してしまいます（§7 予約情報）。
--- ★★ 中身は `party_coordinator.lua` へ移しました（Phase 2）★★
---   ⚠ 名前は残します。**呼ぶ側を一度に書き換えない**（指示書 §18・§21）。
---   ★答えは変わっていません（Phase 0 のハーネスが見張っています）。
--- ⚠⚠ **控えは 2026-08-08 に消しました**（Phase 10 / 相談回答 §12）。
---   `load_module` は読み込めないと `error()` を投げます。★nil を返しません。
---   つまり控えは **production では絶対に動かないコード**でした。
---   ★答えは `battle_ai_baseline_test.lua` の GOLDEN 36通りが見張ります。
function Bridge:_heal_reservations()
  return self.party_coordinator:healing_reservations(self.turn_no)
end

--- 予約ぶんを足したHP。★予約が無ければ現在HPそのもの。
function Bridge:_hp_after_reserved(who)
  if who == nil then return 0 end
  return self.party_coordinator:hp_after_reserved(self.turn_no, who)
end

--- 回復を予約する。★決めた直後に呼びます。
function Bridge:_reserve_heal(who, amount)
  if who == nil or amount == nil or amount <= 0 then return end
  self.party_coordinator:reserve_healing(self.turn_no, who, amount)
end

--- 「いのちをだいじに」の判断順（指示書 §10）。
--
--   1. 自分のHP <= 緊急自己回復  -> **自分**
--   2. 守る相手 <= 保護しきい値  -> **その人**
--   3. 自分のHP <= 自分の回復開始 -> **自分**
--   4. どれでもなければ nil（★従来の探し方へ落ちる）
--
-- ★この順にする理由（§10 末尾）:
--   **回復役自身が瀕死のままローレシアだけを回復して共倒れになる**のを防ぐ。
--
-- 戻り値: `対象, 不足HP, 理由` / 当てはまらなければ `nil`
function Bridge:_protect_target(m, party, self_on, ally_on, self_ratio)
  -- ★★ 中身は `actor_decision.lua` にあります（Phase 2）★★
  --   ⚠ 名前と引数は残します。**呼ぶ側を一度に書き換えない**（§18・§21）。
  --
  -- ⚠⚠ **控えは 2026-08-08 に消しました**（Phase 10 / 相談回答 §12）。
  --   ここには「1. 自分が緊急 -> 2. 守る相手 -> 3. 自分」を**もう一度**
  --   書いた 60 行がありました。★同じ規則が2か所にある状態です。
  --   ⚠ `load_module` は読み込めないと `error()` を投げる（nil を返さない）ので、
  --     その 60 行は **production では絶対に動きませんでした**。
  --   ★答えは `battle_ai_baseline_test.lua` の GOLDEN 36通りが見張ります。
  return self.actor_decision.protect_target(
    party, self:_actor_in(party, m),
    self:_healing_policy(m, self_on, ally_on, self_ratio),
    self:_heal_reservations())
end

--- いまの大目的（2026-08-05 / 戦闘AI再設計 Phase 3）。
---
--- ★★ **価値基準であって命令ではありません**（指示書 §5）。
---   `tactics.lua` に相乗りして届きます。⚠ 無ければ nil。
function Bridge:_mission()
  local t = self.tactics
  if t == nil or type(t.mission) ~= "table" then return nil end
  return t.mission
end

--- MPの予約に大目的の倍率をかける。
---
---   レベル上げ 0.5 … 時間を優先し、MPを使いやすくする
---   ダンジョン 1.0 … ★これまでどおり（既定なので挙動を変えない）
---   ボス       0.0 … 全力投入（指示書 §4.3）
---
--- ⚠⚠ **戦術プロフィールを上書きしません。** 設定した予約量に
---   倍率をかけるだけです。★人が決めた「最低残存MP」は残ります。
---
--- ⚠ 倍率が読めない・1.0 のときは**何もしません**（従来の値をそのまま）。
function Bridge:_scale_reserve(reserve, breakdown)
  if reserve == nil or reserve <= 0 then return reserve, breakdown end
  local mission = self:_mission()
  if mission == nil then return reserve, breakdown end
  local scale = tonumber(mission.mp_reserve_scale)
  -- ⚠ 範囲の外は使わない（★1 を超えると予約が増えて呪文を使わなくなる）
  if scale == nil or scale < 0 or scale > 1 or scale == 1 then
    return reserve, breakdown
  end
  local scaled = math.floor(reserve * scale + 0.5)
  if scaled == reserve then return reserve, breakdown end
  -- ★理由に**目的のせいだと分かる印**を残す（§17）。
  --   ⚠ これが無いと「なぜ予約が減ったのか」を追えません。
  local note = string.format("%s / 目的「%s」で %d -> %d",
    tostring(breakdown or "予約"), tostring(mission.mission),
    reserve, scaled)
  return scaled, note
end

--- パーティの中から本人を引く。⚠ 見つからなければ nil。
function Bridge:_actor_in(party, m)
  for _, other in ipairs(party or {}) do
    if other.index == m.index then return other end
  end
  return nil
end

--- 回復の方針を設定から組み立てる（形は `tactics_commander.lua` が決める）。
---
--- ★★ **ここが「設定の読み方」を知っている唯一の場所です。** ★★
---   ⚠ 判断側（`actor_decision.lua`）はプロフィールの形を知りません。
---     知らせると、判断を試すのに設定ファイルの用意が要ります。
function Bridge:_healing_policy(m, self_on, ally_on, self_ratio)
  local values = {
    self_enabled = self_on,
    ally_enabled = ally_on,
    self_ratio = self_ratio,
    ally_ratio = self:_tactic_heal_ratio(m.name, "ally"),
    protect_target = self:_tactic_text(
      m.name, "healing", "protect_target", "none"),
    protect_ratio = self:_tactic_num(
      m.name, "healing", "protect_hp_threshold", 50) / 100,
    emergency_ratio = self:_tactic_num(
      m.name, "healing", "emergency_self_hp_threshold", 25) / 100,
    avoid_duplicate = self:_tactic_flag(
      m.name, "healing", "avoid_duplicate_healing", true),
  }
  return self.tactics_commander.healing_policy(values)
end

--- 回復で戻す目標（最大HPに対する割合）。★既定は 9割。
---
--- ⚠⚠ **数字は「まんたん」の設定を borrow します**（★測り方を2か所に書かない）。
---   依頼者の言葉が「９割（満タン設定）」だったとおり、⚠ 戦闘と戦闘外で
---   目標が食い違うのは分かりにくいためです。
---   ★`config/mantan.yaml` の `target_hp_percent` を変えれば両方動きます。
---
--- ⚠ 「いつ回復に動くか」（`heal.threshold`）とは**別の数**です。混ぜないこと。
function Bridge:_heal_goal_ratio()
  local mcfg = (self.config or {}).mantan or {}
  local percent = mcfg.target_hp_percent
  if type(percent) == "number" and percent >= 1 and percent <= 100 then
    return percent / 100
  end
  -- ⚠ 設定が読めないときは 9割（★`mantan.lua` の既定と同じ）
  return 0.9
end

--- 不足HPに合わせて回復呪文の試す順を組み替える（2026-08-08）。
---
--- ## ⚠⚠ 何が壊れていたか
---
---   これまでは `config` に書いた順（ホイミ -> Healmore）を
---   **そのまま**上から試し、唱えられた最初のものを使っていました。
---   ★不足が 107 でも、ホイミ（32）が唱えられればホイミでした。
---
--- ## ★ どう並べ替えるか
---
---     1. 足りるもの        … ★期待回復が不足以上。**小さいほうから**
---                             （⚠ 無駄な回復と無駄なMPを減らす）
---     2. 分からないもの    … ⚠ 期待回復が設定に無い。★設定順のまま
---     3. 足りないもの      … ★期待回復が**大きいほうから**（少しでも埋める）
---
--- ⚠⚠ **「分からない」を 0 と混ぜない。** 期待回復が書かれていない呪文を
---   「回復量 0」と見なすと、⚠ 必ず最後に回ります。★判断材料が無いだけなので、
---   足りないと分かっているものより前に置きます。
---
--- ⚠ 並べ替えるだけです。★候補を減らしません（唱えられるかは呼ぶ側が見ます）。
function Bridge:_heal_spells_for(deficit, m)
  local list = self.heal_spells or {}
  -- ★不足が分からないときは**従来どおり**（⚠ 推測で並べ替えない）
  if type(deficit) ~= "number" or deficit <= 0 then return list end

  local ranked = {}
  for order, want in ipairs(list) do
    local expect = tonumber(want.expected_heal)
    local group, key
    if expect == nil then
      group, key = 1, order                 -- ⚠ 分からない -> 設定順のまま
    elseif expect >= deficit then
      group, key = 0, expect                -- ★足りる -> 小さいほうから
    else
      group, key = 2, -expect               -- ★足りない -> 大きいほうから
    end
    ranked[#ranked + 1] =
      { want = want, order = order, group = group, key = key }
  end
  table.sort(ranked, function(a, b)
    if a.group ~= b.group then return a.group < b.group end
    if a.key ~= b.key then return a.key < b.key end
    return a.order < b.order
  end)

  local out = {}
  for i, e in ipairs(ranked) do out[i] = e.want end

  -- ★★ 並べ替えたことを残す（⚠ 黙って順番を変えない / playbook #35）★★
  --   ⚠ 1戦闘に1回だけ。★毎ターン出すとログが埋まります。
  if ranked[1] ~= nil and ranked[1].order ~= 1 then
    -- ⚠ `self.battle_seq` は**存在しません**（★`self.state.battle_seq` です）。
    --   ⚠⚠ nil のままだと全員が同じ印になり、1人ぶんしか出ません。
    local mark = tostring(m and m.name) .. "@"
      .. tostring(self.state and self.state.battle_seq)
    self.heal_order_logged = self.heal_order_logged or {}
    if self.heal_order_logged[mark] == nil then
      self.heal_order_logged[mark] = true
      self:log(string.format(
        "[回復量] 不足HP %d なので %s を先に試します（目標 %d%%）",
        math.floor(deficit + 0.5),
        tostring(ranked[1].want.name or ranked[1].want.id),
        math.floor(self:_heal_goal_ratio() * 100 + 0.5)),
        "heal spell reordered by deficit", "DEBUG")
    end
  end
  return out
end

function Bridge:_plan_battle_heal(m)
  -- 最大MPが 0 なら行1は「にげる」。ここで必ず落とす。
  local p = self.memory_map.addresses.party
  local max_mp = memory.readbyte(p.fields.max_mp.offset + m.index * p.member_stride)
  -- ★理由を返さない（nil）。この人は**そもそも呪文を覚えない**ので、
  --   毎戦闘「MPを持たない」と報告しても直しようがない。上の説明を参照。
  if max_mp <= 0 then
    -- ★画面には出す（ログには出さない）。「この人は呪文を覚えない」は
    --   ログでは毎戦闘出る雑音だが、画面では**知りたいこと**。
    return nil, nil, "呪文を覚えない（ローレシア）"
  end

  -- ★マホトーンで封じられていたら呪文を諦める（2026-07-26 / Phase 6 P4-0）。
  --   これが無いと呪文リストが開かない画面で max_presses_per_turn（16回）まで
  --   押してから諦める。壊れはしないが、そのターンを無駄にする。
  --   ⚠ 理由は返す。「MPを持たない」と違って**毎ターン出るものではない**
  --     （封じられている間だけ）。利用者から見て「なぜ回復しないのか」が要る。
  --   ⚠ silence(0x01) は ROM 由来だが**実測前**なので、
  --     「立っていたら止める」側にだけ使う（外れても被害は「唱えない」で済む）。
  if self.game.spell_blocked ~= nil then
    local blocked = self.game:spell_blocked(m.index)
    if blocked ~= nil then return nil, blocked end
  end

  local cur_mp = memory.readbyte(p.fields.current_mp.offset + m.index * p.member_stride)

  -- 回復が必要な人を探す（最も減っている人 / 仕様4章）
  --
  -- ★★ キャラクター別の回復設定（2026-07-30 / 仕様書 5.2）★★
  --   自分と仲間で**別のしきい値**を持てる。ON/OFF も別。
  --   ⚠ プロフィールが無ければ `self.heal_threshold`（config の値）が
  --     両方に使われる＝**これまでとまったく同じ挙動**。
  local self_on = self:_tactic_flag(m.name, "healing", "self_enabled", true)
  local ally_on = self:_tactic_flag(m.name, "healing", "ally_enabled", true)
  local self_ratio = self:_tactic_heal_ratio(m.name, "self")
  -- ⚠ 仲間側のしきい値は `_healing_policy` が読み直します（★ここでは使いません）。
  --   控えを消したときに**使わない変数だけ**が残っていました（2026-08-08）。

  -- ★★ **緊急回復は廃止した**（2026-07-31 / 依頼者の判断）★★
  --
  --   ⚠ 既定では**構造的に発動しなかった**。
  --     危険状態（`danger.hp_ratio_threshold` = 0.25）と
  --     緊急回復の既定（25%）が**同じ点**で、先に危険状態が成立する。
  --     危険状態になると `auto_input_allowed()` が false になり、
  --     `_claim_battle_input` が early return するので、
  --     **回復の判断まで到達しない**（コードで確認 / 実機の指摘が発端）。
  --
  --   ★安全網は**危険時手動復帰**が担う。HPが減ったら人へ操作が渡る。
  --     二重に安全網を持つと設定が煩雑になるだけなので、片方に寄せた。
  --
  --   ⚠ これに伴い「緊急時は予約MPを使う」も**同時に外した**。
  --     緊急の判定が無くなると、あれは**何も起こさない設定**になるため。
  local party = self.game:active_party()
  local rows = {}
  for pos, other in ipairs(party) do
    rows[other.index] = pos - 1            -- 0x0B の行 = 加入者の並び順
  end

  -- ★★ 誰を回復するかは `actor_decision.lua` が決めます（Phase 2）★★
  --
  --   1. 自分が緊急 -> 2. 守る相手 -> 3. 自分 -> 4. 最も減っている人
  --
  --   ⚠ `protect_target` を決めていなければ 1〜3 は素通りし、
  --     **これまでどおり「最も減っている人」**になります。
  --   ★答えは変えていません（Phase 0 のハーネス14項目が見張っています）。
  -- ⚠⚠ **控えは 2026-08-08 に消しました**（Phase 10 / 相談回答 §12）。
  --   ★「最も減っている人を探す」ループが**もう一度**ここにありました。
  --   ⚠ `load_module` は失敗すると `error()` を投げるので、
  --     `self.actor_decision` は nil になり得ず、★控えは動きませんでした。
  local worst, _worst_missing, worst_why = self.actor_decision.heal_target(
    party, m, self:_healing_policy(m, self_on, ally_on, self_ratio),
    self:_heal_reservations())
  -- ★回復不要。⚠ **ログには出さないが、画面には出す**（下の `_note_decision`）。
  --   ログは毎ターン出すと埋まるが、AI判断の欄は
  --   「なぜ殴っただけなのか」を知るための場所なので、書かないと意味が無い。
  if worst == nil then
    return nil, nil, "全員のHPがしきい値以上（回復不要）"
  end

  -- ★★★ 自己回復は「ちからのたて」が最優先（指示書 §9.1）★★★
  --
  --     自己回復: ちからのたて ＞ 回復呪文 ＞ やくそう
  --
  --   理由（§9.1）: ちからのたては**自己回復専用**で、MPを使わず
  --   何度でも使えます。★燃費が一番よいので、呪文より先に使います。
  --
  -- ⚠⚠ しかし行動の優先順は `heal -> attack -> item -> target` で、
  --   **回復呪文（heal）のほうが道具（item）より先**に主張します。
  --   ★そこで「自分を回復する番で、使える道具があるなら**譲る**」。
  --   譲れば、次に `item` が主張して ちからのたて を使います。
  --
  -- ⚠ 譲るのは**自分を回復するときだけ**です。ちからのたては本人しか
  --   回復できないので、他者回復では候補に入れません（§9.2・§16）。
  -- ⚠⚠ **2026-08-04 の実機ログで見つけた穴**（記録）:
  --   最初はここで `_find_battle_item` をそのまま呼んでいた。しかしあれは
  --   **設定順で最初に使える道具**を返すので、自己回復の番なのに
  --   ★いかづちのつえ（攻撃）に譲ってしまう。
  --   → `heals_self: true` の印が付いた道具**だけ**を探す。
  if worst ~= nil and worst.index == m.index
    and self:_tactic_flag(m.name, "items", "reusable", true) then
    local slot, _id, item_name = self:_find_self_heal_item(m.index, m)
    if slot ~= nil then
      return nil, nil, string.format(
        "自己回復は %s を優先（MPを使わず何度でも使えるため）",
        tostring(item_name))
    end
  end

  -- ★★★ どれだけ足りないかを先に出す（2026-08-08 / 依頼者の指摘）★★★
  --
  --   > 戦闘時の回復が弱い。９割（満タン設定）を狙うようにしたい。
  --   > 残り３０なのにホイミを使ったりしている
  --
  -- ⚠⚠ **「いつ回復するか」と「どこまで戻すか」は別の数**です。
  --   ここを1つの数で兼ねていたのが、回復が弱かった原因です。
  --
  --       いつ  … `heal.threshold`（既定 50%）。★下回ったら回復に動く
  --       どこまで … `mantan.target_hp_percent`（既定 90%）。★戻す目標
  --
  --   ⚠ 以前は「不足 ＝ 最大HP × **しきい値** − 現在HP」でした。
  --     ★つまり **50% まで戻せば足りる**という計算です。
  --     HP 29/152 なら不足 47 と見なされ、⚠ ホイミ（32）でも
  --     「まあ足りる」ことになっていました。
  --   ★90% を目標にすると不足は 107。→ Healmore（50）が選ばれます。
  local goal = self:_heal_goal_ratio()
  local deficit = (worst.max_hp or 0) * goal - self:_hp_after_reserved(worst)

  -- 唱えられる回復呪文を優先順に探す（設定は呪文ID。行番号ではない）
  local why = "設定した回復呪文を覚えていない（config の auto_input.heal.spells）"
  for _, want in ipairs(self:_heal_spells_for(deficit, m)) do
    local id = want.id or want
    -- ★拒否リストは**位置を探す前**に見る（Phase 6 P4-0）。
    --   ここで落とすのは「設定に書かれた呪文」。計算結果の側は下で改めて見る。
    local denied = self.game.spell_denied ~= nil and self.game:spell_denied(id) or nil
    local row, col, entry = nil, nil, nil
    if denied == nil then
      row, col, entry = self.game:find_spell_pos(id, m.index, "battle")
    else
      why = string.format("%s は唱えない指定になっている（%s）",
        self.game:spell_name(id), denied)
    end
    if row ~= nil then
      local info = entry.info or {}
      -- ★計算した先に何があるかでもう一度見る。上とは**別のことを見ている**
      --   （設定の呪文 vs 実際にその位置にある呪文）。計算が壊れたときに効く。
      --   ⚠ 枠7 は メガンテ / パルプンテ になる（仕様書 2.4）。
      local at_pos = (entry.id ~= nil and self.game.spell_denied ~= nil)
        and self.game:spell_denied(entry.id) or nil
      if at_pos ~= nil then
        why = string.format("計算した位置(列%d,行%d)に %s があり唱えない（%s）",
          col, row, tostring(entry.name), at_pos)
      -- ★ROM の Base Target で「味方を狙う呪文か」を確かめる。
      --   味方狙い = 決定後に 0x0B が出る（O-5 の実測と一致）。
      elseif info.heal and self.game:spell_target_menu(id) == ALLY_TARGET_MENU then
        -- ⚠ ふしぎなぼうし を装備しているとMPは表より安く済む。
        --   多めに要求する側なので「唱えられるのに唱えない」で終わる（安全側）。
        local cost = info.mp_battle or 0
        -- ★MPの予約（Phase 6 P5）。ルーラ・リレミトのぶんは残す。
        --   判定は DQ2:mp_reserve に集約してある（まんたんと同じ数字を使う）。
        -- ★★ キャラクター別の「最低残存MP」（2026-07-30 / 仕様書 5.5）★★
        --
        --   ⚠ 既存の `mp_reserve` は「ルーラ・リレミトのぶんを残す」もので、
        --     **意味が違う**。片方を捨てず、**大きいほうを採る**。
        --     足し合わせると「ルーラのぶん + 最低残存MP」になり、
        --     利用者が指定した数より多く残してしまう（設定と違う挙動）。
        --
        --   ★★ 2026-08-01: その「大きいほうを採る」規則を
        --     `DQ2:reserved_mp` へ移した。⚠ ここにしか無かったため、
        --     まんたんでは最低残存MPが効いていなかった（依頼者の報告）。
        local floor_mp = self:_tactic_num(m.name, "resources", "reserve_mp", nil)
        -- ボス戦では温存を解除する設定（仕様書 5.5）。★戦闘だけの話なので
        --   ここに残す（まんたんは戦闘外でしか動かない）。
        -- ⚠ 「緊急時は予約MPを使う」はここにあったが、緊急回復の廃止に伴い外した
        --   （緊急の判定が無いので、あっても何も起こさない設定になる）。
        if floor_mp ~= nil and self.state.is_boss
          and self:_tactic_flag(m.name, "resources",
                                "ignore_reserve_on_boss", false) then
          floor_mp = 0
        end
        local reserve, breakdown = 0, nil
        if self.game.reserved_mp ~= nil then
          reserve, breakdown = self.game:reserved_mp(m.index, floor_mp)
        elseif self.game.mp_reserve ~= nil then
          reserve, breakdown = self.game:mp_reserve(m.index)
        end
        -- ★★ 大目的で予約の重みが変わる（2026-08-05 / Phase 3）★★
        --   レベル上げ 0.5 / ダンジョン 1.0 / ボス 0.0
        --   ⚠ 戦術プロフィールを**上書きしません**。設定した予約量に
        --     倍率をかけるだけです（指示書 §5「価値基準を変える」）。
        reserve, breakdown = self:_scale_reserve(reserve, breakdown)
        if cur_mp >= cost + reserve then
          local target_row = rows[worst.index]
          if target_row ~= nil then
            -- ★★ 二重回復を避けるため、決めた回復を予約する（§11）★★
            --   ⚠ 「二重回復を避ける」が OFF の人は予約しません。
            --     その場合、次の人は素のHPで判断します（＝従来の挙動）。
            if self:_tactic_flag(m.name, "healing",
                                 "avoid_duplicate_healing", true) then
              local expect = (entry.info or {}).expected_heal
                or (want.expected_heal)
              self:_reserve_heal(worst, expect)
            end
            -- ★★ AI判断の理由をログへ（指示書 §14）★★
            --   ⚠ 「いのちをだいじに」で選んだときだけ、その理由を書く。
            --     従来の「最も減っている人」は今までどおり静かにする。
            if worst_why ~= nil then
              self:log(string.format(
                "回復: %s が %s を回復（%s / HP %d/%d）",
                tostring(m.name), tostring(worst.name), worst_why,
                worst.hp or 0, worst.max_hp or 0),
                string.format(
                  "[AI] strategy=life_first actor=%s action=heal target=%s",
                  tostring(m.name), tostring(worst.name)), "DEBUG")
            end
            return {
              spell_id = id, name = entry.name, row = row, col = col,
              cost = cost, caster = m, target = worst, target_row = target_row,
              reserve = reserve, reserve_detail = breakdown,
              reason = worst_why,
            }
          end
        elseif reserve > 0 and cur_mp >= cost then
          -- ★「MPは足りているが予約で使えない」を**MP不足と混ぜない**。
          --   混ぜると利用者は「MPが無いのか」と思って宿屋へ行き、
          --   戻ってきても同じことが起きる（直しようがない報告になる）。
          why = string.format(
            "%s は唱えられるが %s のMPを残すため使わない（残り%d / 必要%d + 予約%d）",
            tostring(entry.name), breakdown or "予約", cur_mp, cost, reserve)
          -- ★★ この理由は**上書きさせない**（2026-08-04 / Phase 0 の発見）★★
          --   ⚠⚠ 呪文を2つ以上書くと、後の呪文（高いほう）が
          --     必ず「MPが足りない」で上書きしてしまいます。
          --     ★Healmore を足した瞬間、「予約で使わない」という
          --       **一番知りたい理由が消えました**（ハーネスが捕まえた）。
          --   ⚠ 利用者は「MPが無い」と思って宿屋へ行き、戻ってきても
          --     同じことが起きる（直しようがない報告になる）。
          reserve_why = why
        else
          why = string.format("MPが足りない（%s / 残り%d < 必要%d%s）",
            tostring(entry.name), cur_mp, cost,
            reserve > 0 and string.format(" + 予約%d", reserve) or "")
        end
      end
    end
  end
  -- ★★ 「予約で使わない」を優先して返す（MP不足と混ぜない）★★
  return nil, reserve_why or why
end

function Bridge:_claim_battle_heal()
  if not self.heal_enabled then return nil end
  if not self.state.in_battle then self:_reset_battle_heal(); return nil end
  if self.bh_uses >= self.heal_max then return nil end
  if self.game.find_spell_pos == nil then return nil end   -- 古い dq2.lua

  local a = self.memory_map.addresses
  local menu = memory.readbyte(a.menu_id.addr)
  local cx = memory.readbyte(a.menu_cursor_x.addr)
  local cy = memory.readbyte(a.menu_cursor_y.addr)
  local cmd = a.menu_id.values.battle_menu          -- 0x09

  -- 押下中／離し中は続ける（hold で押して gap で離す）
  if self.bh_left > 0 then
    local n = self.bh_left
    self.bh_left = n - 1
    if n > self.bh_gap and self.bh_button ~= nil then
      return { [self.bh_button] = true }
    end
    return {}
  end

  -- 関係するのはこの3画面だけ。それ以外では何も主張しない。
  if menu ~= cmd and menu ~= SPELL_LIST_MENU and menu ~= ALLY_TARGET_MENU then
    self.bh_settle = nil
    -- ⚠ 呪文を決めた直後に**敵の対象選択**が出たら前提が崩れている。
    --   B で戻さず、この番は諦める（壊れ方を「効かない」に限定する）。
    if menu == ENEMY_TARGET_MENU and self.bh_plan ~= nil then
      self:log(string.format(
        "回復のつもりが敵の対象選択(%02X)になったため、この番は手を出しません（%s）",
        menu, tostring(self.bh_plan.name)), "heal: unexpected enemy target", "DEBUG")
      self.bh_plan = nil
      self.bh_tried = true
    end
    return nil
  end

  -- ★誰の番かを確認する。分からなければ手を出さない（O-2 の交差検証つき）
  local m, idx = self.game:battle_input_member()
  if m == nil then
    -- ★次の番を「新しい番」として扱えるようにする。
    --   添字の変化だけで試行をやり直すと、**同じ人が連続で入力する状況**
    --   （相方が死んでいる2人パーティなど）で添字が動かず、
    --   最初のターン以降ずっと回復しなくなる。
    --   ここを通るのは入力待ちが読めない場面（メッセージ・演出中）なので、
    --   そこで一度たたんでおけば次の入力が新しい番になる。
    self.bh_member = nil
    return nil
  end
  if self.bh_member ~= idx then
    self.bh_member = idx
    self.bh_tried = false
    self.bh_plan = nil
    self.bh_presses = 0
  end
  if self.bh_tried then return nil end

  -- ★押しても進まないときの歯止め。この番は諦めて従来どおり殴る。
  if (self.bh_presses or 0) > self.heal_max_presses then
    self:log(string.format(
      "回復の入力が %d 回で進まないため、この番は手を出しません（menu=%02X）",
      self.bh_presses, menu), "heal: give up", "DEBUG")
    self.bh_tried = true
    self.bh_plan = nil
    return nil
  end

  if menu == cmd then
    -- 入力を受け付ける状態になるまで押さない（cursor_x=255 が目印）
    if cx ~= 255 then return nil end
    if self.bh_plan == nil then
      local plan, why, quiet_why = self:_plan_battle_heal(m)
      if plan == nil then
        self.bh_tried = true                -- この番は殴る
        -- ★★ **画面には必ず理由を出す**（2026-07-31）★★
        --   ログに出す理由（`why`）と、出さない理由（`quiet_why`）の
        --   **どちらでも画面には書く**。画面は「なぜ殴っただけか」を
        --   知るための場所なので、黙ると存在意義が無い。
        self:_note_decision(m, "たたかう", why or quiet_why or "回復しない")
        -- ⚠ ここではまだ記録しません。★このあと攻撃呪文や道具に
        --   変わることがあるためです（`_claim_battle_attack` / `_claim_battle_item`）。
        --   ★「たたかう」で確定するのは、**攻撃呪文も見送ったとき**です。
        -- ★出すのは「直せること」だけ（依頼者の指摘 / 2026-07-26）。
        --
        --   以前は「戦闘の回復呪文: MPを持たない ため使いません」と出していた。
        --   これは**ローレシアの番では毎回起きる当たり前のこと**で、
        --   しかも誰の話か書いていなかったため、
        --   「回復機能が丸ごと使えない」と読めてしまった。
        --   毎戦闘こう出ると、本当に見たい行（回復を確認/効果なし）が埋もれる。
        --
        --   MPを持たない人（ローレシア）は**構造的にそうである**だけなので出さない。
        --   出すのは MP不足・呪文が無い といった、状況で変わるものに限る。
        if why ~= nil and not self.bh_logged then
          self.bh_logged = true
          self:log(string.format("回復呪文を使いません: %s は%s",
            tostring(m.name), why), "heal: skip", "DEBUG")
        end
        return nil
      end
      self.bh_plan = plan
      -- ★画面（AI判断パネル）に出すために覚えておく
      self:_note_decision(m,
        string.format("%s -> %s", plan.name, plan.target.name),
        string.format("%s のHPが最大の%d%%未満",
          plan.target.name, math.floor(self.heal_threshold * 100)))
      -- ★AI が決めたことは**確実に分かる**ので行動として残す（Phase 3）。
      --   プレイヤーの手動入力は内容が分からないので記録しない。
      -- ⚠ 2026-08-08 に `_record_action` へ寄せました（★3種類とも同じ形）。
      self:_record_action(plan.caster, plan.name, plan.target.name,
                          self.last_ai_reason)
      self:log(string.format(
        "戦闘で回復します: %s が %s に %s（0x07 の 列%d,行%d / MP %d -> 対象は行%d）",
        plan.caster.name, plan.target.name, plan.name,
        plan.col, plan.row, plan.cost, plan.target_row),
        string.format("heal: spell=%02X (col=%d,row=%d) target_row=%d",
          plan.spell_id, plan.col, plan.row, plan.target_row), "DEBUG")
      self:notify("HEAL", 120)
    end
    -- 行1「じゅもん」へ寄せる。★ここに来るのは最大MP>0 の人だけ
    if cy ~= 1 then
      return self:_bh_press((cy < 1) and "down" or "up")
    end
    return self:_bh_press("A")
  end

  local plan = self.bh_plan
  if plan == nil then return nil end        -- 自分が開いた画面ではない

  -- ★開いた直後は位置が確定していない。落ち着くまで何も押さない
  --   （0x0A / 0x07 / 0x08 で同じ穴を踏んでいる）
  if self.bh_settle == nil then self.bh_settle = self.bh_settle_frames end
  if self.bh_settle > 0 then
    self.bh_settle = self.bh_settle - 1
    return {}
  end

  if menu == SPELL_LIST_MENU then
    -- 0x07 は2列。列 -> 行の順に寄せる
    if cx ~= plan.col then
      return self:_bh_press((cx < plan.col) and "right" or "left")
    end
    if cy ~= plan.row then
      return self:_bh_press((cy < plan.row) and "down" or "up")
    end
    -- ★決定の直前にもう一度、その位置にあるのが狙った呪文かを確かめる
    --   （DEV-12 / まんたんの _row_still_matches と同じ位置づけ）
    local row, col = self.game:find_spell_pos(plan.spell_id, plan.caster.index, "battle")
    if row ~= plan.row or col ~= plan.col then
      -- ★手を引いた後どうなるか（ここを曖昧にしない）:
      --   主張をやめると従来の「A を押す」に戻る。カーソルは寄せた位置に
      --   残っているので、その呪文が唱えられて 0x0B が出て、行0 の味方に効く。
      --   **B で戻さない。** 戻すと 0x09 でまた行1が押され ABAB になる（B-7）。
      self:log("呪文の位置が変わったため決定しません", "heal: position changed", "DEBUG")
      self.bh_plan = nil
      self.bh_tried = true
      return nil
    end
    self.bh_settle = nil
    return self:_bh_press("A")
  end

  -- menu == 0x0B（味方の対象選択 / 行数 = 加入者数）
  if cy ~= plan.target_row then
    return self:_bh_press((cy < plan.target_row) and "down" or "up")
  end
  -- 狙う相手に着いた。決定してこの番は終わり
  self.bh_tried = true
  self.bh_uses = self.bh_uses + 1
  -- ★効いたかを後で確かめるための基準（_check_heal_result）
  -- 全員のHPを控える。**狙った人以外が回復していないか**を見るため。
  local hp = {}
  for _, other in ipairs(self.game:active_party()) do
    hp[other.index] = { name = other.name, hp = self:_hp_of(other.index) }
  end
  self.bh_watch = {
    caster = plan.caster, target = plan.target, name = plan.name,
    mp = self:_mp_of(plan.caster.index), hp = hp,
    phase = "cast", left = self.heal_watch_frames,
  }
  self.bh_plan = nil
  self.bh_settle = nil
  return self:_bh_press("A")
end

function Bridge:_mp_of(index)
  local p = self.memory_map.addresses.party
  return memory.readbyte(p.fields.current_mp.offset + index * p.member_stride)
end

function Bridge:_hp_of(index)
  local p = self.memory_map.addresses.party
  return memory.readbyte(p.fields.current_hp.offset + index * p.member_stride)
end

--- 最大MP（2026-08-07 / Phase 6）。⚠ 0 なら**呪文を覚えない人**。
function Bridge:_max_mp_of(index)
  local p = self.memory_map.addresses.party
  local f = p.fields.max_mp
  if f == nil then return nil end          -- ⚠ 分からないなら nil
  return memory.readbyte(f.offset + index * p.member_stride)
end

--- 攻撃力（2026-08-07 / Phase 6）。⚠ 記録が無ければ nil。
function Bridge:_attack_of(index)
  local p = self.memory_map.addresses.party
  local f = p.fields.attack
  if f == nil then return nil end
  return memory.readbyte(f.offset + index * p.member_stride)
end

--- 主力度（2026-08-07 / Phase 6）。★0〜1。
--
-- ⚠⚠ **名前の表で「ローレシアが主力」と決めない。**
--   ★パーティの中でいちばん攻撃力が高い人を 1.0 として、その比で出します。
--     ローレシアが主火力になるのは「ローレシアだから」ではなく
--     ★**実際に攻撃力がいちばん高いから**です。
--   ⚠ 攻撃力が読めなければ nil を返します（★0.5 で埋めない）。
function Bridge:_role_weight(m)
  local mine = self:_attack_of(m.index)
  if mine == nil then return nil end
  local top = 0
  for _, other in ipairs(self.game:active_party()) do
    local got = self:_attack_of(other.index) or 0
    if got > top then top = got end
  end
  if top <= 0 then return nil end          -- ⚠ 全員 0 は「読めていない」
  return mine / top
end

--- 回復呪文を唱えられるか（2026-08-07 / Phase 6）。
--
-- ⚠ 「MPがある」だけでは足りません。★**覚えているか**を見ます。
function Bridge:_can_heal(m)
  local max_mp = self:_max_mp_of(m.index)
  if max_mp == nil or max_mp <= 0 then return false end
  if self.game.find_spell_pos == nil then return false end
  for _, want in ipairs(self.heal_spells or {}) do
    local row = self.game:find_spell_pos(want.id or want, m.index, "battle")
    if row ~= nil then return true end
  end
  return false
end

----------------------------------------------------------------------
-- ★★ 攻撃呪文（2026-08-03 / 「ガンガン行こうぜ」Phase 1）
--
-- ⚠⚠ **回復（`_bh_*`）とは状態を分けます**（`_ba_*`）。
--   同じ変数を使い回すと、回復の途中で攻撃が割り込んだときに
--   カーソルの位置を取り違えます。
--
-- ★判断そのものは3つの部品に分けてあり、ここは**橋渡しだけ**です:
--
--     attack_candidates.lua … 誰が何を唱えられるか（MP・封じ・回復除外）
--     damage_estimate.lua   … どれくらい効くか
--     attack_plan.lua       … ★サマル＋ムーンの連携
--
--   ⚠ どれも RAM を読まないので、実機なしで試せます。
----------------------------------------------------------------------

function Bridge:_reset_battle_attack()
  self.ba_left, self.ba_button = 0, nil
  self.ba_tried = false
  self.ba_settle = nil
  self.ba_plan = nil
  self.ba_presses = 0
  -- ⚠⚠ **印を必ず消す**（2026-08-07）。★残ると、次の人の**物理攻撃**まで
  --   「呪文が効かない敵を避ける」ようになり、⚠ 殴れる敵を素通りします。
  self.ba_avoid_immune = false
  self.ba_avoid_immune_for = nil
  -- ★このターンの連携結果（★2人ぶんを1回で決める）
  self.ba_turn_plan = nil
  self.ba_turn_no = nil
end

function Bridge:_ba_press(button)
  self.ba_button = button
  self.ba_left = self.bh_hold + self.bh_gap
  self.ba_presses = (self.ba_presses or 0) + 1
  return { [button] = true }
end

--- ★「ガンガン行こうぜ」が有効か。
--
-- ⚠ 既定は **false**（★設定しなければこれまでと同じ挙動）。
--- 「ガンガン行こうぜ」が効いているか。
---
--- ★★ **人ごとに決まります**（2026-08-03 / 依頼者の要望）★★
---
---   > 今の物理＋道具＋回復とガンガン行こうぜは切り分けられるようにしたい
---
---   作戦設定画面の「攻撃呪文を使う（ガンガン行こうぜ）」が出典です。
---   ⚠ 既定は **OFF**。触らなければ従来どおり「たたかう＋杖＋回復呪文」。
---
---   `m` を渡さないときは config.yaml の値だけを見ます（画面を持たない
---   環境や、まだ誰の番か決まっていない場面のため）。
function Bridge:_attack_spell_enabled(m)
  local cfg = self.attack_spell_config or {}
  local base = (cfg.enabled == true)
  if m == nil or m.name == nil then return base end
  -- ★プロフィールが無ければ config.yaml の値がそのまま残る（従来の挙動）
  return self:_tactic_flag(m.name, "actions", "attack_spell", base)
end

--- ★誰か1人でも使う可能性があるか（戦闘中の早期打ち切り用）。
---
--- ⚠⚠ ここで config.yaml だけを見てはいけません。
---   `attack_spells.enabled: false` のままでも、画面で誰かが ON にして
---   いれば動かす必要があります（依頼者の指定: 画面のチェックだけで動く）。
--- ★誰の番かはまだ分からないので、**人ごとの判断は `_plan_battle_attack`
---   に任せ**、ここは「全員 OFF と言い切れるか」だけを見ます。
function Bridge:_attack_spell_possible()
  if (self.attack_spell_config or {}).enabled == true then return true end
  local t = self.tactics
  if t == nil or type(t.characters) ~= "table" then return false end
  for _, c in pairs(t.characters) do
    if type(c) == "table" and type(c.actions) == "table"
      and c.actions.attack_spell == true then
      return true
    end
  end
  return false
end

--- その人の攻撃呪文の候補をこしらえる。
--
-- ⚠ RAM を読むのはここだけ。判断は `attack_candidates` に任せます。
function Bridge:_attack_candidates_for(m)
  if self.attack_candidates == nil then return {}, {} end
  local entries = self.game:learned_spells(m.index, "battle")
  if entries == nil or #entries == 0 then return {}, {} end

  local p = self.memory_map.addresses.party
  local cur_mp = memory.readbyte(
    p.fields.current_mp.offset + m.index * p.member_stride)

  -- ★MP の予約（ルーラ・リレミトのぶん＋最低残存MP）。回復と同じ数を使う
  local floor_mp = self:_tactic_num(m.name, "resources", "reserve_mp", nil)
  if floor_mp ~= nil and self.state.is_boss
    and self:_tactic_flag(m.name, "resources", "ignore_reserve_on_boss", false)
  then
    floor_mp = 0
  end
  local reserve = 0
  if self.game.reserved_mp ~= nil then
    reserve = self.game:reserved_mp(m.index, floor_mp) or 0
  end

  -- ⚠ マホトーンで封じられていたら、この人は呪文を使えない
  if self.game.spell_blocked ~= nil then
    local blocked = self.game:spell_blocked(m.index)
    if blocked ~= nil then return {}, { { name = "（全部）", reason = blocked } } end
  end

  local spells = (self.memory_map or {}).spells or {}
  return self.attack_candidates.build(entries, spells, {
    actor = m.name,
    current_mp = cur_mp,
    reserve = reserve,
    index = 1,
    denied_of = function(id)
      if self.game.spell_denied == nil then return nil end
      return self.game:spell_denied(id)
    end,
  })
end

--- ★★ このターンの連携をまとめて決める（指示書 §7）。
--
-- ⚠ 1人ずつ決めると「ムーンが倒せるか」が分からないので、
--   **サマルとムーンの候補を同時に見て**から割り当てます。
--
-- ★1ターンに1回だけ計算し、結果を覚えておきます。
function Bridge:_attack_turn_plan()
  if self.ba_turn_plan ~= nil and self.ba_turn_no == self.turn_no then
    return self.ba_turn_plan
  end
  if self.attack_plan == nil then return nil end

  local samar, moon = nil, nil
  for _, m in ipairs(self.game:active_party()) do
    if m.alive then
      if m.index == 1 then samar = m elseif m.index == 2 then moon = m end
    end
  end

  local a_list, a_dropped = {}, {}
  local b_list, b_dropped = {}, {}
  if samar ~= nil then a_list, a_dropped = self:_attack_candidates_for(samar) end
  if moon ~= nil then b_list, b_dropped = self:_attack_candidates_for(moon) end

  local enemies = self:_enemy_view()

  local plan = self.attack_plan.coordinate(a_list, b_list, enemies)
  plan.samar, plan.moon = samar, moon
  plan.dropped = { samar = a_dropped, moon = b_dropped }
  self.ba_turn_plan = plan
  self.ba_turn_no = self.turn_no
  return plan
end

--- この番の人が唱える攻撃呪文。⚠ 唱えないなら nil, 理由。
function Bridge:_plan_battle_attack(m)
  -- ★★★ **ここが Phase 10A の唯一の拒否点**（2026-08-07）★★★
  --
  --   相談回答の推奨:
  --   > まず `attack_spell` にだけ実際の拒否権を与える
  --   > 拒否されたら次の legacy claim へ進む
  --   > 行動途中では拒否しない
  --
  -- ⚠⚠ **ここは「まだ何も押していない」場所です。** ★決めた後
  --   （`ba_plan` が入った後）に拒否すると、呪文メニューの途中で
  --   放棄することになり、別の claim が入力して事故ります。
  --
  -- ★nil を返すと、呼ぶ側は「攻撃呪文は使わない」として
  --   **次の claim（item → target → たたかう）へ進みます**。
  --   ⚠ 「たたかう」に落とすのではありません。★chain に任せます。
  -- ⚠ そもそも呪文を使えない人には、却下も要りません（2026-08-07）。
  --   ★ローレシアは MP を持たないので、37件のうち約1/3が無駄でした。
  --   ⚠⚠ **判定の順番が大事**: 先に「使えるか」を見てから拒否します。
  if not self:_attack_spell_enabled(m) then
    return nil, nil, string.format(
      "%s は「ガンガン行こうぜ」が OFF", tostring(m.name))
  end
  -- ⚠⚠⚠ **設定の ON/OFF だけでは足りません**（2026-08-07 に踏んだ）★★★
  --   ★`_attack_spell_enabled` は**設定**を見るだけです。
  --     ローレシアは設定 ON でも **MP を持たない**ので呪文を使えません。
  --   ⚠ それでも却下ログが出て、実機で37件のうち約1/3が無駄でした。
  local max_mp = self:_max_mp_of(m.index)
  if max_mp ~= nil and max_mp <= 0 then
    return nil, nil, string.format(
      "%s は呪文を覚えません（MPを持たない）", tostring(m.name))
  end

  local may, why = self:_may_act("attack_spell")
  if not may then
    -- ★★ 却下したことは**必ず残す**（⚠ 理由が無いと追えない）。
    --
    --   相談回答は3点を求めています:
    --     LEGACY candidate / DIRECTIVE veto reason / EXECUTED action
    --
    --   ⚠⚠ **1点目（何を選ぼうとしたか）は原理的に出せません。**
    --     ★拒否点は**候補を作る前**にあるためです（相談回答の
    --       「行動途中では拒否しない」を守ると、こうなります）。
    --     ⚠ 候補だけ先に作ると副作用（MP予約・使用回数）の恐れがあり、
    --       ★「拒否したのに数えた」という別の壊れ方になります。
    --   → ★残せる2点（種類と理由）を残し、実際の行動は
    --     このあと `_note_decision` が記録します。
    -- ⚠⚠ **1人1ターン1回だけ出す**（2026-08-07 / 実機で37件出た）。
    --   ★毎フレーム判定するので、同じ却下が何度も並びます。
    --     21:02:58 の1秒だけで6件出て、⚠ 他の記録が読めませんでした。
    --   ⚠ 「鳴りすぎも壊れ方」を、今日また踏むところでした。
    local mark = string.format("%s@%d", tostring(m.name), self.turn_no or 0)
    self.veto_logged = self.veto_logged or {}
    if self.veto_logged[mark] == nil then
      self.veto_logged[mark] = true
      -- ⚠ ターン番号も出す（2026-08-07）。★これが無いと
      --   「重複」なのか「ターンが進んだ」のか**区別できません**。
      --   実機ログで同じ秒に2回出て、⚠ 私は判断できませんでした。
      self:log(string.format("[veto] T%d %s の attack_spell を却下: %s",
        self.turn_no or 0, tostring(m.name), tostring(why)),
        "veto: attack_spell", "DEBUG")
      -- ★★ イベントにも残す（2026-08-13 / §6・§9）★★
      --   ⚠ これまで human log にしか無く、§9 の「veto 発生ケース」を
      --     **数えられなかった**（★文面を grep するしかない）。
      --   ★human log と同じ「1人1ターン1回」の門の内側なので、増えない。
      --   ⚠ `decision_id` は**まだ無い**ことがある（★却下は候補を作る前）。
      --     そのときは nil のまま出す（★対にできないことを隠さない）。
      local mark_id = string.format("%s/%s", tostring(self.turn_no or 0),
                                    tostring(m.index))
      self:emit("battle_veto", {
        turn = self.turn_no or 0,
        actor = m.name,
        kind = "attack_spell",
        reason = why,
        decision_id = (self.snapshot_done or {})[mark_id],
      })
      self.veto_count = (self.veto_count or 0) + 1
    end
    return nil, why
  end

  if not self:_attack_spell_enabled(m) then
    -- ★誰が OFF なのかを書く。「サマルだけ ON」にしたとき、
    --   ムーンが呪文を使わない理由がログで分かるように。
    return nil, nil, string.format(
      "%s は「ガンガン行こうぜ」が OFF", tostring(m.name))
  end
  local turn = self:_attack_turn_plan()
  if turn == nil then return nil, nil, "連携を計算できない" end

  local choice = nil
  if turn.samar ~= nil and m.index == turn.samar.index then
    choice = turn.a
  elseif turn.moon ~= nil and m.index == turn.moon.index then
    choice = turn.b
  else
    -- ★ローレシアなど。呪文を使わない
    return nil, nil, "攻撃呪文を覚えない"
  end

  if choice == nil then
    -- ⚠ 「使えない」のか「あえて使わない」のかを分けて伝える
    local dropped = (turn.dropped or {})[
      (turn.samar ~= nil and m.index == turn.samar.index) and "samar" or "moon"]
    local detail = self.attack_candidates.describe_dropped(dropped or {})
    if detail ~= "" then
      return nil, nil, detail
    end
    return nil, nil, turn.reason or "攻撃呪文を使わない"
  end

  local c = choice.candidate
  return {
    spell_id = c.spell_id, name = (c.spell or {}).name, row = c.row,
    col = c.col, cost = (c.spell or {}).mp_battle or 0, caster = m,
    reason = turn.reason, detail = self.attack_plan.describe(choice),
  }
end

--- ★攻撃呪文の主張（`BATTLE_CLAIMS.attack`）。
--
-- ⚠ 回復（`_claim_battle_heal`）とほぼ同じ流れですが、
--   決定したあとに出るのが **敵の対象選択（$0A）** である点が違います。
function Bridge:_claim_battle_attack()
  if not self.state.in_battle then self:_reset_battle_attack(); return nil end
  -- ⚠ ここでは**まだ誰の番か分かりません**。人ごとの ON/OFF は下の
  --   `_plan_battle_attack(m)` が見ます（そちらは理由もログに残します）。
  if not self:_attack_spell_possible() then return nil end

  -- 押下中／離し中は続ける
  if self.ba_left > 0 then
    local n = self.ba_left
    self.ba_left = n - 1
    if n > self.bh_gap and self.ba_button ~= nil then
      return { [self.ba_button] = true }
    end
    return {}
  end

  -- ⚠⚠ 2026-08-03: ここで `self.game:menu_id()` と書いて実機で落ちた。
  --   そんなメソッドは無い。★回復側（`_claim_battle_heal`）と同じく
  --   `memory.readbyte` で読む。
  local a = self.memory_map.addresses
  local menu = memory.readbyte(a.menu_id.addr)
  local cmd = a.menu_id.values.battle_menu          -- 0x09
  -- 関係するのはこの3画面だけ
  if menu ~= cmd and menu ~= SPELL_LIST_MENU and menu ~= ENEMY_TARGET_MENU then
    self.ba_settle = nil
    -- ⚠ 攻撃のつもりが**味方の対象選択**になったら前提が崩れている
    if menu == ALLY_TARGET_MENU and self.ba_plan ~= nil then
      self:log(string.format(
        "攻撃のつもりが味方の対象選択(%02X)になったため、この番は手を出しません（%s）",
        menu, tostring(self.ba_plan.name)), "attack: unexpected ally target", "DEBUG")
      self.ba_plan = nil
      self.ba_tried = true
    end
    return nil
  end

  local m = self.game:battle_input_member()
  if m == nil then return nil end
  if self.ba_member ~= m.index then
    self.ba_member = m.index
    self.ba_tried = false
    self.ba_plan = nil
    self.ba_presses = 0
  end
  if self.ba_tried then return nil end

  -- ★押しても進まないときの歯止め
  if (self.ba_presses or 0) > self.heal_max_presses then
    self:log(string.format(
      "攻撃呪文の入力が %d 回で進まないため、この番は手を出しません（menu=%02X）",
      self.ba_presses, menu), "attack: give up", "DEBUG")
    self.ba_tried = true
    self.ba_plan = nil
    return nil
  end

  if menu == cmd then
    -- 入力を受け付ける状態になるまで押さない（cursor_x=255 が目印）
    if memory.readbyte(a.menu_cursor_x.addr) ~= 255 then return nil end
    if self.ba_plan == nil then
      local plan, why, quiet = self:_plan_battle_attack(m)
      if plan == nil then
        self.ba_tried = true
        self:_note_decision(m, "たたかう", why or quiet or "攻撃呪文を使わない")
        -- ⚠ ここではまだ記録しません。★このあと**道具**を試すためです
        --   （順番は heal -> attack -> item -> target）。
        --   ⚠⚠ ここで「たたかう」と決め打つと、**道具が記録されません**。
        --   ★記録するのは道具も見送ったとき（`_claim_battle_item` の入口）。
        return nil
      end
      self.ba_plan = plan
      self:_note_decision(m, string.format("%s（攻撃呪文）", plan.name),
                          plan.reason or plan.detail or "")
      -- ★行動として残す（2026-08-08 / ⚠ ここが無くて攻撃呪文が0件だった）
      --   ⚠ 狙う相手はこのあと決まるので、★ここでは書きません
      --     （分からないものを書かない）。
      self:_record_action(m, plan.name, nil,
                          plan.reason or plan.detail or "")
      self:log(string.format("攻撃呪文: %s が %s（0x07 の 列%d,行%d / MP %d）",
        m.name, tostring(plan.name), plan.col, plan.row, plan.cost),
        string.format("attack: spell=%02X (col=%d,row=%d)",
          plan.spell_id, plan.col, plan.row), "DEBUG")
    end
    -- 行1「じゅもん」へ寄せる
    local cy = memory.readbyte(a.menu_cursor_y.addr)
    if cy ~= 1 then
      return self:_ba_press((cy < 1) and "down" or "up")
    end
    return self:_ba_press("A")
  end

  local plan = self.ba_plan
  if plan == nil then return nil end        -- 自分が開いた画面ではない

  if self.ba_settle == nil then self.ba_settle = self.bh_settle_frames end
  if self.ba_settle > 0 then
    self.ba_settle = self.ba_settle - 1
    return {}
  end

  if menu == SPELL_LIST_MENU then
    local cx = memory.readbyte(a.menu_cursor_x.addr)
    local cy = memory.readbyte(a.menu_cursor_y.addr)
    if cx ~= plan.col then
      return self:_ba_press((cx < plan.col) and "right" or "left")
    end
    if cy ~= plan.row then
      return self:_ba_press((cy < plan.row) and "down" or "up")
    end
    -- ★決定の直前にもう一度、その位置にあるのが狙った呪文か確かめる
    local row, col = self.game:find_spell_pos(plan.spell_id, plan.caster.index,
                                              "battle")
    if row ~= plan.row or col ~= plan.col then
      self:log("呪文の位置が変わったため決定しません", "attack: position changed", "DEBUG")
      self.ba_plan = nil
      self.ba_tried = true
      return nil
    end
    self.ba_settle = nil
    return self:_ba_press("A")
  end

  -- menu == 0x0A（敵の対象選択）
  --
  -- ★★★ **狙い先は `_claim_target_selection` に任せます**（2026-08-07）★★★
  --
  --   ⚠⚠ 以前はここで**カーソルを動かさず A を押していました**。
  --     そのため「ゲームが置いた既定の位置」に当たり、判断側が
  --     `index = 1`（先頭）で計算した結果とずれていました。
  --     → 依頼者の報告「キラーマシン（呪文きかない）のに攻撃呪文使っている」。
  --
  --   ★行を寄せる仕組みは**既にあります**（物理攻撃用に作ったもの）。
  --     判断の優先順は `heal -> attack -> item -> target` なので、
  --     ⚠ ここで nil を返せば `target` が拾って寄せてくれます。
  --
  --   ⚠ 呪文が効かない敵を避けたいことを伝えるため、印を置きます。
  self.ba_avoid_immune = true
  self.ba_avoid_immune_for = (m ~= nil) and m.index or nil
  self.ba_tried = true
  self.ba_plan = nil
  self.ba_settle = nil
  return nil
end

-- 回復呪文が本当に効いたかを追う。
--
-- ★「押せた」と「効いた」は別（まんたん DEV-17 と同じ規律）。
--   ログに経路しか残っていないと、カーソルが正しく動いたことは分かっても
--   **ホイミが発動したかは分からない**。実際、実機ログ（2026-07-26 12:41）は
--   入力の経路だけが残り、HP/MP が残っていなかったため確認できなかった。
--
-- ★DQ2 は**全員のコマンドを入力してからターンが解決する**（P3 の途中経過で
--   踏んだ誤り）。決定した直後に測っても何も変わっていない。
--   だから一定フレーム見張り、変化したら記録する。
--
-- ⚠ 敵の攻撃で同じ人のHPが減る／別の回復が混ざるため、
--   ここは**合否の判定ではなく観測の記録**として扱う。
--   自動で止めたりはしない（誤検知で戦闘を止めるほうが害が大きい）。
--
-- ★★ 2段階で見る（1段階では測り損ねた）★★
--   最初の実装は「MPが減った瞬間にHPを読む」だったが、実機では
--   **MPが減ってもHPが +0 のまま**という記録が並んだ（12:47-12:51）。
--   MPの引き落としとHPの回復は同じフレームではない
--   （唱えた -> メッセージ -> 回復、と段がある）。
--   そこで「唱えたか(MP)」と「効いたか(HP)」を分けて見る。
--
-- ★HPは**全員ぶん**見る。狙った人以外が回復していたら、
--   0x0B の行と人の対応がずれているということで、これは大きな発見になる。
--   「効かない」で終わらせず、**誰に効いたか**まで残す。
function Bridge:_check_heal_result()
  local w = self.bh_watch
  if w == nil then return end
  w.left = w.left - 1

  local ended = not self.state.in_battle

  if w.phase == "cast" then
    local mp = self:_mp_of(w.caster.index)
    if mp < w.mp then
      -- 唱えたことは確定（MPを払った）。ここからHPの変化を追う。
      w.phase = "heal"
      w.mp_after = mp
      w.left = self.heal_hp_watch_frames
      return
    end
    if w.left <= 0 or ended then
      self.bh_watch = nil
      -- ★戦闘が先に終わるのは**普通に起きる**（敵が先に倒れた）。
      --   そこに ⚠ を付けると、本当に困る「時間切れ」が埋もれる。
      -- ★★ 段階を分ける（2026-08-13 / 製品版ログ整理 §3・§18E）★★
      --   ⚠ 「戦闘が先に終わった」は**普通に起きる**（敵が先に倒れた）。
      --     ★これを WARNING にすると、本当に困る「時間切れ」が埋もれる。
      --   ⚠ 同じ事実は直後の `battle_heal` イベントにも出る（§23）。
      --     ★人向けには、困ったときだけ残す。
      self:log(ended and string.format(
        "回復は間に合いませんでした（%s の %s / 戦闘が先に終わった）",
        w.caster.name, w.name)
        or string.format(
        "⚠ 回復呪文が発動しませんでした（%s の %s / MP %d のまま / 時間切れ）",
        w.caster.name, w.name, w.mp),
        "heal: not cast",
        ended and "DEBUG" or "WARNING", "DEBUG", "DEBUG", "DEBUG")
      self:emit("battle_heal", { caster = w.caster.name, target = w.target.name,
        spell = w.name, cast = false })
    end
    return
  end

  -- phase == "heal": 誰かのHPが増えるのを待つ
  --
  -- ★★★ **狙った人を先に見る**（2026-08-08 / 実機ログで誤検知が出た）★★★
  --
  --   ⚠⚠ 以前は `pairs(w.hp)` の**最初に見つかった人**を採っていました。
  --     ★`pairs` の順番は Lua では**決まっていません**。
  --
  --   実機ログ（09:16:34）で、同じターンに回復が2つ入りました:
  --
  --       samaltria  -> moonbrooke に Healmore
  --       moonbrooke -> samaltria  に Healmore
  --
  --   ⚠ 両方が効くと**2人ともHPが増えます**。そこで moonbrooke の唱えた
  --     ぶんを見張っていた側が、たまたま moonbrooke（＝相手に回復された側）
  --     を先に拾い、★**「行と人の対応がずれている可能性」と報告**しました。
  --
  --   ⚠⚠⚠ **これは嘘です。** 狙いは正しく飛んでいました。
  --     ★「鳴りすぎも壊れ方」（playbook）。⚠ 本物の不具合と見分けが
  --       つかなくなるので、誤検知は不具合として直します。
  --
  --   → ★狙った人が増えていれば**それを採る**。
  --     ⚠ 狙った人が増えず、別の人だけが増えたときだけ「ずれ」と言います。
  local gained_name, gained_before, gained_after = nil, nil, nil
  local aimed = w.hp[w.target.index]
  if aimed ~= nil and self:_hp_of(w.target.index) > aimed.hp then
    gained_name, gained_before, gained_after =
      aimed.name, aimed.hp, self:_hp_of(w.target.index)
  else
    for index, before in pairs(w.hp) do
      local now = self:_hp_of(index)
      if now > before.hp then
        gained_name, gained_before, gained_after = before.name, before.hp, now
        break
      end
    end
  end

  if gained_name ~= nil then
    self.bh_watch = nil
    local as_planned = (gained_name == w.target.name)
    self:log(string.format(
      "回復を確認: %s の %s -> %s のHP %d -> %d（%+d）/ MP %d -> %d%s",
      w.caster.name, w.name, gained_name, gained_before, gained_after,
      gained_after - gained_before, w.mp, w.mp_after,
      as_planned and "" or string.format(
        "  ★狙ったのは %s。**行と人の対応がずれている可能性**", w.target.name)),
      string.format("heal ok: %s hp %d->%d%s", as_planned and "target" or "OTHER",
        gained_before, gained_after, as_planned and "" or " MISMATCH"),
      -- ★狙いどおりなら DEBUG（★同じ事実は下の `battle_heal` に出る / §18E）。
      -- ⚠ 行と人の対応がずれた疑いは**残す**（§3 の「異常な状態遷移」）。
      as_planned and "DEBUG" or "WARNING", "DEBUG", "DEBUG", "DEBUG")
    self:emit("battle_heal", {
      caster = w.caster.name, target = w.target.name, healed = gained_name,
      spell = w.name, hp_before = gained_before, hp_after = gained_after,
      mp_before = w.mp, mp_after = w.mp_after, as_planned = as_planned,
    })
    return
  end

  if w.left <= 0 or ended then
    self.bh_watch = nil
    -- ★唱えたのにHPが増えなかった。満タン・対象の死亡・行のずれが候補。
    --   数字を残しておけば次に追える。
    local now = self:_hp_of(w.target.index)
    local before = w.hp[w.target.index].hp
    -- ⚠⚠ **「増えなかった」と「倒された」を混ぜない**（2026-08-06）。
    --   ★HP が 36 -> 0 なら、唱える前に相手が倒れています。
    --     こちらの不具合ではなく、**ゲームの仕様どおり空振り**です。
    --   ⚠ 同じ文言で出すと、追う相手を間違えます。
    -- ★段階も一緒に決める（2026-08-13 / §3）。
    --   ⚠ 「倒れた」「攻撃が上回った」は**ゲームの成り行き**で、
    --     RetroUX が期待どおり動いていないわけではない → DEBUG。
    --   ★「唱えたのに増えない」は説明が付かない → WARNING。
    local kind, hint, level
    if now <= 0 then
      kind = "⚠ 回復が間に合いませんでした（唱える前に倒れた）"
      hint = "heal: target died first"
      level = "DEBUG"
    elseif now < before then
      kind = "⚠ 回復より攻撃が上回りました（HPが減っている）"
      hint = "heal: outpaced by damage"
      level = "DEBUG"
    else
      kind = "⚠ 唱えたのにHPが増えませんでした"
      hint = "heal: cast but no hp gain"
      level = "WARNING"
    end
    self:log(string.format(
      "%s（%s の %s / %s のHP %d -> %d / MP %d -> %d / %s）",
      kind, w.caster.name, w.name, w.target.name, before, now,
      w.mp, w.mp_after, ended and "戦闘が終わった" or "時間切れ"), hint, level, "DEBUG", "DEBUG", "DEBUG", "DEBUG")
    self:emit("battle_heal", {
      caster = w.caster.name, target = w.target.name, spell = w.name,
      hp_before = w.hp[w.target.index].hp, hp_after = now,
      mp_before = w.mp, mp_after = w.mp_after, healed = false,
    })
  end
end

-- 戦闘中に「杖」を使う（DEV-24）。
--
-- 依頼者の要望:
--   「まどうしの杖、イカヅチの杖を持っていたらAUTO戦闘で使ってほしい」
--   「まどうしの杖、いかづちの杖は減らない。」
--
-- ★「戦闘中の道具は使わない」という決定の理由は**在庫が減るから**だった。
--   杖は減らないので理由が当てはまらない（DEV-24）。消費資源ゼロ。
--
-- ★実測で確定した経路（work/staff/map.txt）:
--   0x09 戦闘コマンド 行3「どうぐ」（★行3は全員共通なので安全。
--        行1 は MPが無い人では「にげる」なので絶対に押さない）
--     -> 0x08 戦闘中のどうぐ（**2列メニュー**）
--        **持ち物の行 = カーソル行 * 2 + カーソル列**（行優先）
--        逆に解くと 行 = floor(slot/2) / 列 = slot % 2
--
-- ⚠ 位置を推測して押すと**別の道具を使ってしまう**。
--   実際に (列0,行2) を杖だと思って押したら きんのカギ だった
--   （画面に「マリアは きんのカギを つかった。」と出た / work/staff/staff_02_after_select.png）。
--   だから**持ち物を実際に読んでスロット番号から位置を計算する**。
--
-- ⚠ 在庫が減らないので「代価を払ったか」では検証できない。
--   使えたかどうかは画面のメッセージで判断する（検証スクリプト側で照合する）。
--
-- 壊れ方を「効かない」に限定する作り:
--   ・杖を持っていなければ何も主張しない（従来どおり A を押すだけ）
--   ・入力を受け付ける状態（cursor_x=255）になるまで押さない
--   ・1人1ターンにつき1回しか試さない（失敗しても押し続けない）
--   ・1戦闘の使用回数に上限を置く
function Bridge:_reset_battle_item()
  self.bi_left, self.bi_button = 0, nil
  self.bi_member, self.bi_tried = nil, false
  self.bi_settle = nil
end

-- 指定メンバーが持っている杖を探す。戻り値: 持ち物のスロット番号, アイテムID, 名前
--- 条件の判定に渡す材料をまとめる（2026-08-01 / 課題 #62）。
---
--- ★RAM を読むのはここまで。判定そのものは `item_conditions.lua`。
--- 判断に使う「敵の見立て」を作る（2026-08-08 に1つへ寄せました）。
---
--- ⚠⚠ **以前は `_attack_turn_plan` と `_item_context` の2か所で
---   同じものを組み立てていました。** ★守備力を足そうとしたときに
---   「同じ行が2つある」ことで気づきました。
---   ⚠ 片方だけ直すと、攻撃と道具で**違う敵が見えます**。
---
--- ⚠ 読めない項目は nil のまま（★0 で埋めない）。
function Bridge:_enemy_view()
  local enemies = {}
  local ok = pcall(function()
    for _, e in ipairs(self.game:enemy_instances() or {}) do
      local stats = e.stats or {}
      -- ★★ resist も渡す（2026-08-03 / 依頼者の実機指摘）
      --   ⚠ これが抜けていて、呪文が効かないキラーマシーン
      --     （`spell_damage: 7`）にギラ・イオナズンを撃っていた。
      -- ★★ defense も渡す（2026-08-08 / 依頼者の指摘）
      --   ⚠ 通常攻撃と比べるのに要ります。
      enemies[#enemies + 1] = { id = e.id, hp = e.hp,
                                max_hp = stats.max_hp,
                                defense = stats.defense,
                                resist = stats.resist }
    end
  end)
  if not ok then return {} end
  return enemies
end

function Bridge:_item_context(member)
  local enemies = self:_enemy_view()
  -- ★★ 通常攻撃の強さ（2026-08-08 / 依頼者の指摘）★★
  --   ⚠ 読めなければ nil のまま（★条件のほうが「比べない」に倒れます）。
  local attack_power, hits = nil, nil
  if member ~= nil and member.index ~= nil then
    local ok_atk = pcall(function()
      attack_power = self:_attack_of(member.index)
      hits = self:_attack_hits(member.index)
    end)
    if not ok_atk then attack_power, hits = nil, nil end
  end

  return {
    user = { hp = member and member.hp, max_hp = member and member.max_hp },
    enemies = enemies,
    used = self.bi_used_ids or {},
    attack_power = attack_power,
    attack_hits = hits,
  }
end

--- 1ターンに何回殴るか（2026-08-08 / 依頼者の指摘）。
---
--- ★★ **はやぶさのけんは2回攻撃**です。ROM で確かめました:
---   `bank4.asm:5654  lda #$49 ; Item ID #$49: Falcon Sword (equipped)`
---   ★`0x49` は `0x09 | 0x40` で、**bit6 が「装備中」**の印です。
---   ⚠ 攻撃力の加算は **+5 だけ**（`bank4.asm:9748`）。
---     ★2回殴ることが値打ちです。
---
--- ⚠ 装備していなければ 1。★持っているだけでは2回になりません。
function Bridge:_attack_hits(index)
  local cfg = (self.config.auto_input or {}).multi_hit_weapons
  if type(cfg) ~= "table" then return 1 end
  local inv = self.game.inventory ~= nil and self.game:inventory(index) or {}
  for _, entry in ipairs(cfg) do
    local want = tonumber(entry.id)
    local hits = tonumber(entry.hits) or 1
    if want ~= nil then
      for _, got in pairs(inv) do
        -- ⚠⚠ **装備中（bit6）でなければ数えません。**
        if got == (want + 0x40) then return hits end
      end
    end
  end
  return 1
end

--- ★自分を回復する道具だけを探す（2026-08-04 / 指示書 §9.1）。
---
--- ★★ `heals_self: true` が付いたものだけを見ます。 ★★
---   ⚠⚠ 条件（`when: self_hp_below`）から推測してはいけません。
---     あれは「いつ使うか」であって「何をする道具か」ではありません。
---     ★別の道具に同じ条件を書いた瞬間、それが回復道具になってしまいます。
---
--- ⚠ `_find_battle_item` を使い回さない理由（**実機ログで見つけた穴**）:
---   あちらは**設定順で最初に使える道具**を返すので、
---   ★自己回復の番なのに いかづちのつえ（攻撃）を返します。
function Bridge:_find_self_heal_item(who, member)
  local spec = self.memory_map.addresses.inventory
  local slots = (spec and spec.slots) or 8
  local inv = self.game:inventory(who)
  local ctx = self:_item_context(member)
  for _, want in ipairs(self.battle_item_list or {}) do
    if want.heals_self == true then
      local allow = self.item_conditions.allow(want, ctx)
      if allow then
        for i = 0, slots - 1 do
          local got = inv[i]
          -- ★装備中は bit6(0x40) が立つ（`_find_battle_item` と同じ扱い）
          if got ~= nil and got ~= 0 and got % 0x40 == want.id % 0x40 then
            return i, want.id, want.name or self.game:item_name(want.id)
          end
        end
      end
    end
  end
  return nil, nil, nil
end

function Bridge:_find_battle_item(who, member, forced)
  local spec = self.memory_map.addresses.inventory
  local slots = (spec and spec.slots) or 8
  local inv = self.game:inventory(who)

  -- ★★ 固定戦略（2026-08-11 / Phase 4）★★
  --   指定された道具ID（`forced`）を、条件を見ずに持ち物から探す。
  --   ⚠ 装備中は bit6(0x40) が立つので、40 で割った余りで一致を見る
  --     （下の通常経路と同じ対策）。
  if forced ~= nil then
    for i = 0, slots - 1 do
      local got = inv[i]
      if got ~= nil and got ~= 0 and got % 0x40 == forced % 0x40 then
        return i, forced, self.game:item_name(forced)
      end
    end
    return nil, nil, nil               -- ★持っていない（在庫切れ等）
  end

  -- ★★ 条件を見る（2026-08-01 / 課題 #62）★★
  --   ⚠ 条件を書いていない道具は従来どおり（杖はこれ）。
  local ctx = self:_item_context(member)
  -- 設定の並び順を優先する（上に書いたものを先に使う）
  for _, want in ipairs(self.battle_item_list) do
    local allow, why = self.item_conditions.allow(want, ctx)
    -- ⚠⚠ `goto` は使えない（**FCEUX の Lua は 5.1**。5.2 からの機能）。
    --   一度書いて `luacheck` が捕まえた。★入れ子で書く。
    if not allow then
      -- ★理由を残す。⚠ 毎ターン出すと埋もれるので、変わったときだけ。
      self:_note_item_skip(want, why)
    else
    for i = 0, slots - 1 do
      local got = inv[i]
      -- ★装備中のアイテムは bit6(0x40) が立つ。完全一致で探すと見つからない。
      --   実際に踏んだ: いかづちのつえ(0x04) を装備していたため持ち物には
      --   **0x44** で入っており、「持っていない」と判定していた
      --   （work/staff/thunder.txt の1回目）。
      --   まどうしのつえ が動いたのは装備していなかっただけ。
      --   restock.lua の _have() が同じ対策をしているので揃える。
      if got ~= nil and got ~= 0 and got % 0x40 == want.id % 0x40 then
        return i, want.id, want.name or self.game:item_name(want.id)
      end
    end
    end                                   -- if not allow / else
  end
  return nil, nil, nil
end

--- 「使えるのに条件で見送った」を書き残す。
---
--- ⚠ 毎ターン出すと同じ行がログを埋め、本当に見たい行が沈む
---   （playbook #4 / 依頼者の指摘と同じ話）。**変わったときだけ**出す。
--- ★黙って見送ると「設定したのに効かない」に見える（playbook #46）。
function Bridge:_note_item_skip(item, why)
  if why == nil then return end
  local name = item.name or tostring(item.id)
  local line = name .. ": " .. why
  self.bi_skip_notes = self.bi_skip_notes or {}
  if self.bi_skip_notes[name] == why then return end
  self.bi_skip_notes[name] = why
  self:log("戦闘で " .. line .. "（設定した条件に合いません）",
           "item skip " .. name, "DEBUG")
end

function Bridge:_claim_battle_item()
  -- ★★ 固定戦略（ユーザー指定1 / 2026-08-11 / Phase 4）★★
  --   `self._forced_item` が入っていると、その道具を**条件なし**で使う。
  --   ⚠ 通常の歯止め（有効か／一覧にあるか／回数上限／`items.reusable`）は
  --     固定戦略では飛ばす（利用者が「これを毎ターン」と明示したため）。
  local forced = self._forced_item
  if forced == nil then
    if not self.battle_item_enabled then return nil end
    if #self.battle_item_list == 0 then return nil end
  end
  if not self.state.in_battle then self:_reset_battle_item(); return nil end
  if forced == nil and self.bi_uses >= self.battle_item_max then return nil end

  local a = self.memory_map.addresses
  local menu = memory.readbyte(a.menu_id.addr)
  local cx = memory.readbyte(a.menu_cursor_x.addr)
  local cy = memory.readbyte(a.menu_cursor_y.addr)
  local BATTLE_ITEM_MENU = 0x08
  local cmd = a.menu_id.values.battle_menu          -- 0x09

  -- 押下中／離し中は続ける（hold で押して gap で離す。離さないと次が新しい押下にならない）
  if self.bi_left > 0 then
    local n = self.bi_left
    self.bi_left = n - 1
    if n > self.bi_gap and self.bi_button ~= nil then
      return { [self.bi_button] = true }
    end
    return {}
  end

  -- 戦闘コマンドか どうぐ の画面以外では何も主張しない
  if menu ~= cmd and menu ~= BATTLE_ITEM_MENU then
    self.bi_settle = nil
    return nil
  end

  -- ★誰の番かを確認する。分からなければ手を出さない（O-2 の交差検証つき）
  local m, idx = self.game:battle_input_member()
  if m == nil then return nil end
  if self.bi_member ~= idx then
    self.bi_member = idx
    self.bi_tried = false                 -- 番が変わったので試行をやり直せる
  end
  if self.bi_tried then return nil end    -- この番では既に試した

  -- ★★ キャラクター別「非消耗道具を使用する」（2026-07-30 / 仕様書 5.6）★★
  --
  --   ⚠ ここで扱うのは**杖だけ**（`battle_items.items` に減る道具を書かない
  --     という既存の決めごと / DEV-24）。だから見るのは `items.reusable`。
  --   ⚠ `items.consumable`（消耗品）は**まだ AI へ渡していない**
  --     （フェーズ3以降）。渡していないものをここで読むと、
  --     設定した気になって効かない項目ができる（仕様書 20章）。
  -- ⚠ 固定戦略のときは `items.reusable` の歯止めを見ない（明示指定のため）
  if forced == nil
    and not self:_tactic_flag(m.name, "items", "reusable", true) then
    self.bi_tried = true                  -- この番は道具を使わない
    return nil
  end

  -- ★★ `m` も渡す（2026-08-01 / 課題 #62）★★
  --   `self_hp_below`（ちからのたては本人へのベホイミ）を見るのに、
  --   **使う本人の HP** が要る。⚠ 一番HPが低い人ではない。
  -- ★固定戦略では、指定された道具を条件なしで探す（`forced`）。
  local slot, item_id, item_name = self:_find_battle_item(m.index, m, forced)
  if slot == nil then return nil end      -- 使える道具が無い（条件も含む）

  -- ★★★ **呪文と同じ効果の道具なら、狙いも呪文と同じ扱いにする**
  --   （2026-08-07 / 依頼者の実機ログで発覚）★★★
  --
  --     戦闘で まどうしのつえ を使います（samaltria）
  --     [狙い] samaltria -> 行1 キラーマシーン（物理）  ← ⚠⚠ 効かない敵
  --
  -- ⚠⚠ 印（`ba_avoid_immune`）を**攻撃呪文の経路にだけ**置いていました。
  --   ★veto で攻撃呪文が却下されると、その経路を通らずに道具が使われ、
  --     ⚠ 印が立たないまま対象選択へ行って**効かない敵を選んで**いました。
  --
  -- ★どの道具が呪文と同じかは、設定の `when: spell_may_damage` が目印です
  --   （⚠ 道具の名前をここへ書き写さない）。
  do
    local same_as_spell = false
    for _, want in ipairs(self.battle_item_list or {}) do
      if want.id == item_id and want.when == "spell_may_damage" then
        same_as_spell = true
      end
    end
    -- ⚠⚠ **誰の印かを覚える**（2026-08-07 / 実機ログで発覚）。
    --   ★以前は真偽値だけでした。道具を使った人の印が残り、
    --     ⚠ **次の人の物理攻撃まで**「呪文が効かない敵を避ける」に
    --       なっていました（★物理は効くので損）。
    if same_as_spell then
      self.ba_avoid_immune = true
      self.ba_avoid_immune_for = m.index
    end
  end

  local want_row = math.floor(slot / 2)
  local want_col = slot % 2

  if menu == cmd then
    -- ★入力を受け付ける状態になるまで押さない（cursor_x=255 が目印）
    if cx ~= 255 then return nil end
    -- ★毎戦闘ではなく、**内容が変わったときだけ**出す（2026-07-26）。
    --
    --   以前は戦闘ごとに1回出していたので、同じ行がログを埋めた:
    --     「戦闘で いかづちのつえ を使います（moonbrooke / 持ち物の行3 …）」
    --   毎回出る通知は読まれない通知になり、本当に見たい行
    --   （回復を確認 / ⚠ 効果なし）が埋もれる（依頼者の指摘と同じ話）。
    --
    --   誰が・どの道具を・どの位置で使うかが変わったときは知りたいので、
    --   その組み合わせを覚えておいて、違ったときだけ出す。
    -- ★画面（AI判断）にも出す。**道具を使ったのに「たたかう」と出ていた**
    --   （2026-07-31 の指摘）。判断を記録するのは回復だけではない。
    -- ★固定戦略（ユーザー指定1）で使う道具は、通常の「在庫が減らない道具を
    --   AI が選んだ」ものと**理由が違う**。ログで見分けられるようにする
    --   （2026-08-11 / 依頼者の指摘: 実機ログで両者が同じ理由に見えた）。
    local item_reason
    if forced ~= nil then
      item_reason = "ユーザー指定1（固定行動: この道具を毎ターン使う）"
    else
      item_reason = "戦闘で使える道具（在庫が減らないもの）"
    end
    self:_note_decision(m, string.format("どうぐ: %s", tostring(item_name)),
                        item_reason)
    -- ★行動として残す（2026-08-08 / ⚠ ここが無くて道具が0件だった）
    self:_record_action(m, tostring(item_name), nil, item_reason)

    local signature = string.format("%s/%02X/%d", tostring(m.name), item_id, slot)
    if self.bi_logged ~= signature then
      self.bi_logged = signature
      -- ⚠ 第2引数は FCEUX の Lua コンソールへ出る。
      --   **コンソールは UTF-8 非対応で日本語が文字化けする**（依頼者の報告）。
      --   ここに日本語のアイテム名を渡していたのが原因。
      --   コンソール向けは英数字だけにし、日本語は work/retroux.log に出す。
      local tag = (forced ~= nil) and "［固定］" or ""
      self:log(string.format(
        "%s戦闘で %s を使います（%s / 持ち物の行%d -> 0x08 の 列%d,行%d）",
        tag, tostring(item_name), tostring(m.name), slot, want_col, want_row),
        string.format("battle item%s: id=%02X slot=%d (col=%d,row=%d)",
          (forced ~= nil) and " [fixed]" or "", item_id, slot, want_col, want_row), "DEBUG")
    end
    -- 行3「どうぐ」へ寄せる（★行1 は押さない。端でラップしないので決定的）
    if cy ~= 3 then
      self.bi_button = (cy < 3) and "down" or "up"
      self.bi_left = self.bi_hold + self.bi_gap
      return { [self.bi_button] = true }
    end
    self.bi_button = "A"
    self.bi_left = self.bi_hold + self.bi_gap
    return { A = true }
  end

  -- menu == 0x08（戦闘中のどうぐ / 2列）
  -- ★開いた直後は位置が確定していないので落ち着くまで何も押さない。
  --   0x0A（敵選択）や 0x07（呪文）で同じ穴を踏んだ。
  if self.bi_settle == nil then self.bi_settle = self.bi_settle_frames end
  if self.bi_settle > 0 then
    self.bi_settle = self.bi_settle - 1
    return {}
  end

  if cx ~= want_col then
    self.bi_button = (cx < want_col) and "right" or "left"
    self.bi_left = self.bi_hold + self.bi_gap
    return { [self.bi_button] = true }
  end
  if cy ~= want_row then
    self.bi_button = (cy < want_row) and "down" or "up"
    self.bi_left = self.bi_hold + self.bi_gap
    return { [self.bi_button] = true }
  end
  -- 狙う位置に着いた。決定して、この番の試行は終わりにする
  self.bi_tried = true
  self.bi_uses = self.bi_uses + 1
  -- ★どの道具を何回使ったか（`once_per_battle` の判定に使う / 課題 #62）
  self.bi_used_ids = self.bi_used_ids or {}
  self.bi_used_ids[item_id] = (self.bi_used_ids[item_id] or 0) + 1

  -- ★★★ 回復する道具も**予約する**（2026-08-05 / 実機ログで発見）★★★
  --
  -- ⚠⚠ **実際に踏んだ**（2026-08-05 07:27:18-19 のログ）:
  --
  --     戦闘で ちからのたて を使います（samaltria）      ← 本人が自己回復
  --     戦闘で回復します: moonbrooke が samaltria に Healmore
  --     回復を確認: samaltria のHP 22 -> 80
  --
  --   ★同じターンに samaltria へ**2回回復**していた。
  --   道具の使用が `_reserve_heal` を呼んでいなかったため、
  --   ムーンブルクは「samaltria はもう回復する予定」を**知らなかった**。
  --
  -- ⚠ 指示書 §11 の二重回復防止は「回復手段」全部が対象です。
  --   ★呪文だけ予約しても、道具で抜けます。
  local heal_amount = nil
  for _, want in ipairs(self.battle_item_list or {}) do
    if want.id == item_id and want.heals_self == true then
      heal_amount = want.expected_heal
    end
  end
  if heal_amount ~= nil
    and self:_tactic_flag(m.name, "healing",
                          "avoid_duplicate_healing", true) then
    self:_reserve_heal(m, heal_amount)
  end
  self.bi_button = "A"
  self.bi_left = self.bi_hold + self.bi_gap
  return { A = true }
end

-- 倒す順の優先指定（作戦）。敵選択メニューで優先する敵の行へ寄せる。
--
-- 敵選択メニューは **0x0A で確定**（2026-07-25 / work/battlemenu/p0.txt）。
-- config の target_menu が nil のあいだは「行数が敵グループ数と一致する画面」
-- という緩い条件で動く（誤って別のコマンドを選ばないための保険）。
--
-- ★★ 押さないことも「主張」である ★★
--   実測（work/battlemenu/target_test.txt のフレーム追跡）: 敵選択メニューに
--   入った直後の数フレームは**行数($0081)が敵グループ数と合わない**
--   （0x0A なのに行数が 1 や 4 を返す過渡状態がある）。
--   ここで nil を返すと呼び出し元の A 押下周期がそのまま A を通し、
--   行0（先頭の敵）を確定してしまう。
--   メニューIDが変わった＝入力を受け付ける準備ができた、ではない（playbook）。
--
--   そこで敵選択メニューに居るあいだは、行数が落ち着くまで {} を返して
--   **何も押させない**。落ち着いたら寄せて、狙う行に着いてから A を通す。
--   落ち着かないまま target_settle_frames を過ぎたら諦めて従来どおりにする
--   （待ち続けて戦闘が進まなくなる方が害が大きい）。
--
-- ★★ 寄せは敵選択メニューを離れたら即座にやめる ★★
--   実測: 決定した後もメニューIDは 6フレームほど 0x0A のままで、その間に
--   **カーソルが行0へ戻る**。これを「新しい敵選択」と誤認して down を押し始め、
--   押下期間(hold+gap)を数え切るまで押し続けたため、
--   **menu が 0x09（戦闘コマンド）になった後も down を押していた**。
--   0x09 の行1 は ローレシアでは「にげる」なので、これは
--   **勝手に逃げ出す事故につながる**（memory_map の 0x09 の警告を参照）。
--   幸いこの実測では押しっぱなしが新しい押下として拾われず被害は無かったが、
--   「たまたま助かった」を仕様にはしない。
--   対策は2つ:
--     1. 毎フレーム、敵選択メニューに居るかを確認してから押す
--     2. 狙う行に着いたら「この画面での寄せは済んだ」と記録し、
--        メニューを離れるまで二度と寄せない（1回の表示で1回だけ寄せる）
function Bridge:_reset_target_seek()
  self.target_seek_left = 0
  self.target_seek_button = nil
  self.target_settle = nil
  self.target_done = false
end

function Bridge:_claim_target_selection()
  if not self.state.in_battle then self:_reset_target_seek(); return nil end

  -- ★AI操作OFF の人の番では敵選択にも手を出さない（実機 T-5 / 上の解説参照）。
  --   ⚠ 途中まで寄せていた状態は捨てる。残すと、次に AI の人の番が来たとき
  --     押しかけのボタンから再開してしまう。
  if self:_current_member_ai_off() then self:_reset_target_seek(); return nil end

  local spec = self.memory_map.addresses.menu_id
  if spec == nil then return nil end
  local menu = memory.readbyte(spec.addr)

  -- ★メニューの確認を押下より先に行う。順番が逆だと、離れた後も押し続ける。
  if menu == spec.values.battle_menu then
    -- ⚠⚠ **ここが人と人の境目**（2026-08-07）。★呪文を撃つ番の印を消します。
    --   残すと、次の人の**物理攻撃**まで「呪文が効かない敵を避ける」ように
    --   なり、⚠ 殴れる敵を素通りします。
    self.ba_avoid_immune = false
    self.ba_avoid_immune_for = nil
    self:_reset_target_seek()
    return nil
  end
  local on_target_menu = (self.target_menu ~= nil and menu == self.target_menu)
  if self.target_menu ~= nil and not on_target_menu then
    self:_reset_target_seek()
    return nil
  end

  -- 押下中／離し中は続ける。
  -- ★離す期間が必要。hold+gap をすべて押しっぱなしにすると、次の押下が
  --   「新しい押下」として認識されず2行以上の移動ができない。
  if self.target_seek_left > 0 then
    local n = self.target_seek_left
    self.target_seek_left = n - 1
    if n > self.target_seek_gap and self.target_seek_button ~= nil then
      return { [self.target_seek_button] = true }      -- 先頭 hold フレームは押す
    end
    return {}                                          -- 残り gap フレームは離す
  end

  -- この画面での寄せは済んだ。メニューを離れるまで何も主張しない。
  -- （決定後にカーソルが行0へ戻るのを新しい敵選択と誤認しないため）
  if self.target_done then return nil end
  -- ⚠ 以前はここで `#self.target_priority == 0 なら return` していた。
  --   そのため**優先する敵がいないと何も主張せず、カーソルは行0＝左端のまま**。
  --   ＝「左の敵に全員で殴りかかる」の正体（実機で指摘された / 2026-07-31）。
  --   ★無駄撃ち回避が入ったので、優先指定が無くても狙う行を決める。
  -- ⚠ 呪文を撃つ番なら、優先指定が無くても寄せます（★効かない敵を避ける）。
  if #self.target_priority == 0 and not self.overkill_avoid
    and not self.ba_avoid_immune then return nil end

  local groups = self.game.enemy_groups and self.game:enemy_groups() or {}
  local rows = self.game.menu_row_count and self.game:menu_row_count() or 0

  -- ★行数が敵グループ数と合うまで何も押さない（上の説明のとおり）。
  if on_target_menu and #groups >= 2 and rows ~= #groups then
    if self.target_settle == nil then self.target_settle = self.target_settle_frames end
    if self.target_settle > 0 then
      self.target_settle = self.target_settle - 1
      return {}                       -- 何も押さない。A を通さないことが目的
    end
  end

  -- ⚠⚠ **降りた理由を残す**（2026-08-07）。★1戦闘に1回だけ。
  --   「[狙い]」の行が出ないとき、⚠ **寄せに行かなかった**のか
  --   **寄せたが記録が漏れた**のかを区別できませんでした。
  --   ★「無いこと」を根拠にして誤った結論を出したので、そこを塞ぎます。
  local function decline(why)
    if on_target_menu and not self.aim_skip_logged then
      self.aim_skip_logged = true
      self:log("[狙い] ⚠ 寄せません: " .. why, "aim skipped", "DEBUG")
    end
    return nil
  end

  -- ⚠⚠⚠ **0 と 1 を混ぜない**（2026-08-07 / 依頼者の実機ログで発覚）★★★
  --   最初は `#groups < 2` をまとめて「敵は1グループだけ（0）」と出して
  --   いました。★**0 は「1グループ」ではなく「敵が読めていない」**です。
  --   ⚠ 自分で「0 と不明を混ぜない」と書いておきながら踏みました。
  if #groups == 0 then
    -- ⚠ 何行あるかも一緒に残す（2026-08-07）。★行数だけあって敵が0なら
    --   「過渡状態」、⚠ 行数も0なら「そもそも対象選択ではない」。
    --   ★実機で戦闘中に出ており、**まだ理由が分かっていません**。
    return decline(string.format(
      "⚠ 敵が読めていません（行数 %d / ★1グループという意味ではない）",
      rows))
  end
  -- ★敵が1グループなら寄せる必要がありません（★正常）。
  if #groups < 2 then
    return decline(string.format("敵は1グループだけ（%s）",
      self.game:monster_name(groups[1].id)))
  end
  -- ⚠ 行数と敵の数が合わないうちは触りません（★過渡状態）。
  if rows ~= #groups then
    return decline(string.format("行数 %d と敵グループ %d が合わない",
      rows, #groups))
  end

  -- ★★★ **無駄撃ちを避ける**（2026-07-31 / 依頼者の要望）★★★
  --
  --   > 攻撃のときに、敵モンスターの残りHPを予測して、無駄な攻撃をしない
  --
  --   DQ2 は3人ぶんのコマンドを**先に入れてから**まとめて実行するので、
  --   全員が同じ敵を狙うと**倒れたあとの攻撃が空振り**する。
  --   ★このターンで既に割り当てた見込みダメージを覚えておき、
  --     足りているグループは飛ばして次の敵へ移る。
  --
  --   ⚠ ダメージは**目安**（公開されている近似式）。外したときの向きが違う:
  --     過大 -> 早く移る -> **倒しきれずに残る**
  --     過小 -> 重ねて攻撃（無駄は残るが安全）
  --   ★`overkill_margin` で安全側へ倒せる（1.0 = 目安どおり / 依頼者の指定）。
  --     倒しきれない場面が出たら 1.2〜1.5 に上げる。
  local hp_groups = (self.overkill_avoid and self.game.enemy_groups_hp)
      and self.game:enemy_groups_hp() or nil

  -- ★★ **ターンが変わったら予約を捨てる。** ★★
  --   DQ2 は3人ぶん入れてから実行するので、予約が効くのは**そのターンだけ**。
  --   ⚠ 持ち越すと、次のターンで「もう足りている」と誤解して**誰も殴らない**。
  --   ★合図は「敵の合計HPが減った」＝攻撃が当たった＝ターンが実行された。
  --     入力中はHPが動かないので、これで綺麗に切れる。
  if hp_groups ~= nil then
    local total = 0
    for _, g in ipairs(hp_groups) do total = total + g.hp end
    if self.overkill_hp_total == nil or total < self.overkill_hp_total then
      self.overkill_booked = {}
    end
    self.overkill_hp_total = total
  end
  local booked = self.overkill_booked or {}

  -- ★★★ **呪文が効かない敵を狙わない**（2026-08-07 / 依頼者の実機指摘）★★★
  --
  --   > キラーマシン（呪文きかない）のに攻撃呪文使っている
  --
  -- ⚠ 呪文を撃つ番だけ効きます（`ba_avoid_immune`）。物理攻撃は素通りです。
  -- ⚠⚠ 耐性が読めない敵は**避けません**（★読めないことを理由に外すと、
  --   初遭遇の敵に何もできなくなります）。
  local function spell_useless(i)
    if not self.ba_avoid_immune then return false end
    -- ⚠⚠ **その印が「いまの人」のものか**を見る（2026-08-07）。
    --   ★違う人の印で避けると、物理攻撃が効く敵を素通りします。
    local who = self.game.battle_input_member
      and self.game:battle_input_member() or nil
    if self.ba_avoid_immune_for ~= nil and who ~= nil
      and who.index ~= self.ba_avoid_immune_for then
      return false
    end
    if self.damage_estimate == nil then return false end
    local g = groups[i]
    if g == nil then return false end
    local stats = (self.memory_map or {}).monster_stats
    local st = stats and stats[g.id] or nil
    if st == nil or st.resist == nil then return false end   -- ⚠ 読めない
    local rate = self.damage_estimate.spell_rate({ resist = st.resist })
    return rate ~= nil and rate <= 0
  end

  local function still_needs(i)
    -- ★そのグループにまだ攻撃が要るか（要らなければ次の敵へ）
    if spell_useless(i) then return false end   -- ⚠ 呪文が効かない敵は飛ばす
    if hp_groups == nil then return true end
    local g = hp_groups[i]
    if g == nil or g.hp <= 0 then return false end
    return (booked[i] or 0) < g.hp * self.overkill_margin
  end

  -- 優先する敵の行を決める（上から順に探す）
  -- ★優先指定があっても、**足りているなら次の候補へ**（無駄撃ちしない）
  local want_row, want_id = nil, nil
  for _, prio in ipairs(self.target_priority) do
    for i, g in ipairs(groups) do
      if g.id == prio and still_needs(i) then
        want_row, want_id = i - 1, g.id
        break
      end
    end
    if want_row ~= nil then break end
  end

  -- ★優先指定に該当が無ければ、**まだ攻撃が要る先頭のグループ**を狙う。
  --   ⚠ これが無いと行0（左端）に全員が集まる。
  if want_row == nil and self.overkill_avoid then
    for i, g in ipairs(groups) do
      if still_needs(i) then
        want_row, want_id = i - 1, g.id
        break
      end
    end
  end
  if want_row == nil then
    -- ⚠ 全部のグループが「もう足りている」と判断された。★正常なこともある。
    return decline("狙う先が決まらない（★全部足りている / 効かない）")
  end

  if not self.target_menu_logged then
    self.target_menu_logged = true
    -- ★config に target_menu が書いてあるなら勧めない。
    --   書いてあるのに「書けば厳密になります」と出続けていた（実機ログ 12:51）。
    --   直せる助言だけを出す。常に出る助言は読み飛ばされるようになる。
    local hint = ""
    if self.target_menu == nil then
      hint = string.format("（config の target_menu に %02X を書けば厳密になります）", menu)
    end
    self:log(string.format(
      "敵選択メニューの候補: menu=%02X 行数=%d グループ=%d / %s を行%d で狙います%s",
      menu, rows, #groups, self.game:monster_name(want_id), want_row, hint),
      string.format("target menu candidate: %02X", menu), "DEBUG")
  end

  local cy = memory.readbyte(self.memory_map.addresses.menu_cursor_y.addr)
  if cy == want_row then
    -- 狙う行に着いた。A を押させる（nil = 主張しない）。
    -- ★この画面での寄せは済んだと記録する。決定後にカーソルが行0へ戻っても
    --   もう一度寄せに行かない（上の説明のとおり事故の元になる）。
    self.target_done = true

    -- ★★★ **当たり先を必ず残す**（2026-08-07 / 依頼者の指摘の本題）★★★
    --
    --   > キラーマシン（呪文きかない）のに攻撃呪文使っている
    --
    -- ⚠⚠ これまで「★は★を狙います」は**ダメージを見積もれたときだけ**
    --   出ていました。★道具はダメージを推計していないので `dmg` が nil、
    --   物理でも図鑑に無い敵なら nil。→ ⚠ **出ないほうが普通**でした。
    --   そのため実機ログを見て「まどうしのつえに狙い先が無い＝合わせて
    --   いない」と**誤って結論**しました（★「無いこと」を根拠にした）。
    --
    -- ★ここは寄せが**確定した**場所なので、⚠ 見積もりの有無に関係なく
    --   「誰が・何行目の・どの敵を狙ったか」を1行残します。
    do
      local who = self.game.battle_input_member
        and self.game:battle_input_member() or nil
      self:log(string.format(
        "[狙い] %s -> 行%d %s（%s）",
        who and tostring(who.name) or "⚠ 誰の番か不明",
        want_row, self.game:monster_name(want_id),
        (self.ba_avoid_immune and who ~= nil
          and self.ba_avoid_immune_for == who.index)
          and "呪文/道具" or "物理"),
        string.format("aim: row=%d id=%d", want_row, want_id), "DEBUG")
    end

    -- ★★ このターンぶんの見込みダメージを**予約する** ★★
    --   次の人はこれを見て、足りていれば別の敵へ回る。
    --   ⚠ 誰の番か分からないときは予約しない（推測で埋めない）。
    if self.overkill_avoid and hp_groups ~= nil then
      local member = self.game.battle_input_member
          and self.game:battle_input_member() or nil
      local dmg = nil
      if member ~= nil and self.game.estimated_damage_to ~= nil then
        dmg = self.game:estimated_damage_to(member.index, want_id)
      end
      if dmg ~= nil and dmg > 0 then
        local i = want_row + 1
        self.overkill_booked = self.overkill_booked or {}
        self.overkill_booked[i] = (self.overkill_booked[i] or 0) + dmg
        local g = hp_groups[i]
        self:log(string.format(
          "%s は %s を狙います（残り約%d / この攻撃で約%d / 予約 計%d）",
          member.name, self.game:monster_name(want_id),
          g and g.hp or 0, dmg, self.overkill_booked[i]),
          "target booked", "DEBUG")
      end
    end

    -- 既定(行0)から動かしたときだけ、戦闘ごとに1回ログに出す。
    -- 毎人・毎ターン出すとログが埋まって他の記録が読めなくなる。
    if want_row ~= 0 and not self.target_lock_logged then
      self.target_lock_logged = true
      self:log(string.format("倒す順の作戦: %s（行%d）から狙います",
        self.game:monster_name(want_id), want_row), "target locked", "DEBUG")
    end
    return nil
  end

  -- 端でラップしないので寄せ方は決定的
  self.target_seek_button = (cy < want_row) and "down" or "up"
  self.target_seek_left = self.target_seek_hold + self.target_seek_gap
  return { [self.target_seek_button] = true }
end

-- 戦闘直後にフィールドのコマンドメニューが開いた場合の後始末の主張。
--
-- 自動入力の最後の A 押下がフィールド復帰直後に届くと、意図せずコマンドメニューが
-- 開く。放置すると**その後の方向キーがメニュー操作に吸われて移動できなくなる**
-- （実機で発生。利用者が「メニューが表示されて上下左右が拾われる」と報告）。
--
-- プレイヤーが自分で開いたメニューを勝手に閉じないよう、
-- 戦闘を抜けた直後の限られたフレーム数だけに絞ってある。
function Bridge:_claim_menu_cleanup()
  -- マクロなどが意図的にメニューを操作している間は後始末しない。
  -- 開いたメニューを勝手に閉じてしまうため。
  if self.suppress_menu_cleanup then return nil end
  if self.menu_cleanup_left == nil or self.menu_cleanup_left <= 0 then return nil end

  local open = self.game.showing_field_menu and self.game:showing_field_menu()
  if not open then
    -- メニューが開いていない間は期限を消費しない。
    -- 消費してしまうと、戦闘終了から数フレーム遅れてメニューが開いた場合に
    -- 期限切れで閉じられなくなる（それが再発の一因だった）。
    self.menu_cleanup_active = false
    return nil
  end

  -- ★「自動入力が誤って開いたメニュー」だけを閉じる。
  -- プレイヤーが自分で開いたメニューを勝手に閉じてはいけない。
  -- 誤爆は自動入力の最後の A 押下によるものなので**戦闘終了の直後**に起きる。
  -- そこで「戦闘終了から detect フレーム以内に開いたか」で区別する。
  -- （この区別が無いと、戦闘後にプレイヤーがメニューを開くたびに
  --   ブリッジが B を送って邪魔をする）
  if not self.menu_cleanup_active then
    if (self.frames_since_battle or 1e9) > self.menu_cleanup_detect_frames then
      return nil                      -- プレイヤーが後から開いたものと判断
    end
    self.menu_cleanup_active = true
  end

  self.menu_cleanup_left = self.menu_cleanup_left - 1

  -- 押下パターン: 8フレーム押して8フレーム離す。
  -- 実機ログ（work/menudiag/）で、12フレーム周期・5フレーム押下では
  -- $002F に B が届いているのにメニューが閉じきらず、90フレームの期限を
  -- 使い切って方向キーが吸われ続ける状態になった。
  -- 押下を長くし、期限も後述のとおり延ばしてある。
  self.menu_cleanup_tick = ((self.menu_cleanup_tick or 0) + 1) % 16
  return { B = (self.menu_cleanup_tick < 8) }
end

-- ゲームパッドの NES ボタン（十字/A/B/Start/Select）を人の入力として登録する。
--
-- ★★ 依頼者 2026-08-19 / RX-0076: FCEUX 側の割当を不要にし、RetroUX が読んだ
--   パッド状態をここで注入する（「挿すだけ」）。★独自機能（ロード等）は
--   RetroUX が直接処理するので、ここは NES の8ボタンだけを見る。
--
-- ★優先順位は `_apply_input` が解決する（final = claim or requested）。だから
--   ここは「押していれば要求を出す」だけでよい:
--     ・自動戦闘中 → claim が勝ち、パッドは無視（AI が操作）
--     ・非戦闘 / AUTO OFF → requested（パッド）が採用される
-- ⚠ 押していないフレームは request_input を呼ばない（非アサート＝キーボードも生存）。
-- ⚠⚠ seq が進まない＝RetroUX が書いていない。数フレームで 0 とみなし解除する
--   （押しっぱなしのボタンが刺さったままにならないように）。
local NES_BITS = {
  { 0x01, "up" }, { 0x02, "down" }, { 0x04, "left" }, { 0x08, "right" },
  { 0x10, "A" }, { 0x20, "B" }, { 0x40, "start" }, { 0x80, "select" },
}
-- ★これだけ seq が止まったら解除する（＝約 0.5 秒）。
--   ⚠⚠ 短くしすぎると歩行が途中で止まる（2026-08-19 実機）。RetroUX の書き込みは
--     GUI のメインスレッド上のタイマなので、`refresh`（500ms ごとに地図/戦況を
--     再描画）で**数百ms ブロック**されることがある。その間 seq は進まないが、
--     入力は保持し続けたい。30 フレーム（0.5秒）あればその穴を越えられる。
--   ★本当に RetroUX が落ちたときは 0.5 秒で解除される（押しっぱなしが残らない）。
local GAMEPAD_STALE_LIMIT = 30

function Bridge:_poll_pad_input()
  local handle = io.open(self.gamepad_input_path, "r")
  if handle == nil then return end          -- ファイルが無い＝パッド無効/未接続
  local body = handle:read("*a")
  handle:close()
  local seq, mask = (body or ""):match("(%d+)%s+(%d+)")

  -- ★半端読み（seq==nil）のときは**前回の入力を保持**する（1フレームの穴を作らない）。
  --   ⚠ ここで return して非アサートにすると、書き込みと読み取りが競合した
  --     フレームだけ方向キーが離れ、歩行がガクつく／止まる。
  if seq ~= nil then
    seq = tonumber(seq); mask = tonumber(mask)
    -- ★生存判定: seq が変わっていれば RetroUX は書き続けている
    if seq ~= self.gamepad_last_seq then
      self.gamepad_last_seq = seq
      self.gamepad_stale = 0
      self.gamepad_mask = mask
    else
      self.gamepad_stale = self.gamepad_stale + 1
      if self.gamepad_stale >= GAMEPAD_STALE_LIMIT then
        self.gamepad_mask = 0               -- 本当に止まった → 全部離す
      end
    end
  end

  if self.gamepad_mask == 0 then return end -- 押していない → 非アサート（キーボード優先）

  local buttons = {}
  for _, bit in ipairs(NES_BITS) do
    if math.floor(self.gamepad_mask / bit[1]) % 2 == 1 then
      buttons[bit[2]] = true
    end
  end
  -- ★人の入力として登録。explicit＝メニューでもそのまま通す（キーボードと同じ）。
  self:request_input(buttons, "explicit")
end

-- 優先順位に従って最終的な入力を決め、必要なときだけ送る。
function Bridge:_apply_input()
  local claim = self:_claim_battle_input()

  -- ★「手を出さない」は**戦闘中の主張として扱う**（下の if へ入る）。
  --   後始末の期限や `release_left` の予約は戦闘中と同じにしたい。
  --   ⚠ ただしボタンは送らない。ここで nil へ落として `joypad.set` を防ぐ。
  local hands_off = (claim == HANDS_OFF)

  if claim ~= nil then
    -- 戦闘中は後始末の期限をリセット（戦闘を抜けた直後から数え始める）
    self.menu_cleanup_left = self.menu_cleanup_frames
    self.menu_cleanup_active = false
    self.frames_since_battle = 0
    -- 戦闘を抜けた直後に「全部離す」を送るための予約
    self.release_left = self.release_frames_after_battle
  else
    self.frames_since_battle = (self.frames_since_battle or 1e9) + 1

    -- ★戦闘を抜けた直後だけ、全ボタンを明示的に離す。
    -- 何も送らないとプレイヤーに操作を返せる反面、直前の押下が残っているか
    -- どうかを制御できない。ここで断ち切っておく。
    -- 後始末(B)より先に行う。開いてしまったメニューを閉じるのはその後でよい。
    if self.release_left > 0 then
      self.release_left = self.release_left - 1
      claim = {}
    else
      claim = self:_claim_menu_cleanup()
    end
  end

  -- ★ここで目印を落とす。以降は「主張なし」と同じ扱い＝ボタンを送らない。
  if hands_off then claim = nil end

  local requested = self.requested_input
  local kind = self.requested_kind
  self.requested_input = nil          -- 意図は1フレームで消費する
  self.requested_kind = nil

  -- 歩行の要求だけは、メニューが開いている間は捨てる。
  -- ⚠ 送ってしまうと方向キーがメニューのカーソル操作に吸われる。
  -- 後始末の期限が尽きた後にこれが起きて「操作を奪われた」状態になった
  -- （実機ログ work/menudiag/ で確認）。閉じられなくても、少なくとも
  -- 意図しないメニュー操作は起こさない。
  --
  -- 一方 "explicit"（マクロのメニュー操作など）は通す。ここを区別せずに
  -- 一律で捨てていたため、マクロがメニューを操作できない不具合になった。
  if claim == nil and requested ~= nil and kind == "walk"
     and self.game.showing_field_menu and self.game:showing_field_menu() then
    requested = nil
  end

  -- ★"hands_off" は "none" と分けて出す。診断で
  --   「読めなくて何もしなかった」と「意図して人に返した」を混ぜないため。
  -- ⚠ 並びは **実際に採用される順**（final = claim or requested）と揃える。
  --   hands_off を requested より前に置くと、要求を送ったのに
  --   「人に返した」と記録される（診断が嘘をつく）。
  local source = claim and "bridge"
                 or (requested and "request")
                 or (hands_off and "hands_off")
                 or "none"
  local final = claim or requested

  -- 入力の決定を外から観測できるようにする（診断用。既定では無効）。
  -- 入力の競合はこのプロジェクトで繰り返し問題になったため、
  -- 「誰の入力が採用されたか」を後から追える手段を残しておく。
  if self.on_input_decided then
    self.on_input_decided(source, final, self.menu_cleanup_left)
  end

  -- 何も主張しない場合は joypad.set を呼ばない。
  -- 呼ぶとプレイヤーの実機入力を上書きして操作不能になる。
  if final == nil then return end

  joypad.set(1, full_button_set(final))
end

----------------------------------------------------------------------
-- 1フレーム分の処理。emu.frameadvance() の「前」に呼ぶこと。
----------------------------------------------------------------------

function Bridge:step()
  local s = self.state
  -- 入口は敵個体番号 + 敵先頭ID + $0400、開始後は $0400 で継続を追う。
  local now_battle
  if s.in_battle then
    now_battle = self.game:in_battle()
  else
    now_battle = self.game:battle_started()
  end

  if now_battle and not s.in_battle then
    s.in_battle = true
    self:_on_battle_start()
  elseif (not now_battle) and s.in_battle then
    s.in_battle = false
    self:_on_battle_end()
  end

  -- 勝利表示が出ている間に報酬を捕まえる。戦闘終了後は値が失われるため、
  -- battle_end を待たずにここで読んでおく。
  if s.in_battle and self.game.showing_victory and self.game:showing_victory() then
    -- ★勝敗の根拠はこれ。経験値の値では判定しない。
    -- ⚠ 2026-08-12 訂正: 理由に「アドレス未確定 / B-9」と書いてありましたが、
    --   **2026-07-31 に確定**しています（2880行目に同じ訂正あり）。★使わない理由は
    --   「経験値0の勝利があるから」で、アドレスの有無とは関係ありません。
    s.saw_victory = true
    local exp, gold = self.game:reward()
    if exp ~= nil then s.exp_gained = exp end
    if gold ~= nil then s.gold_gained = gold end
  end

  -- ★危険判定は**手動ラッチより先**に行う。
  --   後にすると、ラッチが理由を読むときに1フレーム前の値を見てしまい、
  --   戦闘に入った最初のフレームで「理由不明」になりうる。
  local danger, reason = self.game:is_danger()
  if danger ~= s.danger then
    s.danger = danger
    self:emit(danger and "danger_enter" or "danger_exit", { reason = reason or "" })
  end
  -- ★理由も持っておく（画面の出し分けに使う）。
  --   タイトル画面ではパーティ領域がまだ意味を持たず、安全機構が
  --   「読めない＝危険」と倒す。これは正しいが、画面に DANGER と出ると
  --   壊れているように見える。**読めていないだけ**と区別して出す。
  s.danger_reason = danger and (reason or "") or nil

  -- ★戦闘中にプレイヤーへ操作が渡った場面を覚えておく。
  -- 「プレイヤーが逃げた」と「敵が逃げた」の区別に使う。
  -- 自動入力が動いている間は毎フレーム入力を上書きするため、
  -- プレイヤーは「にげる」を選べない。操作が渡っていない戦闘で
  -- 勝利表示なく終わったなら、それは敵が逃げたということ。
  if s.in_battle and not self:auto_input_allowed() then
    s.player_had_control = true
  end

  -- ★手動へ落ちたら、その戦闘の間は手動のままにする。
  -- 「いまの条件」で判定してからラッチを立てる（ラッチ自身を見ると常に真になる）。
  if s.in_battle and (self.config.auto_input.latch_manual_for_battle ~= false)
     and not s.manual_latched then
    local allowed, why = self:_auto_input_allowed_now()
    if not allowed then
      s.manual_latched = true
      -- ★理由を必ず添える。「手動のままにします」だけでは何をすればよいか分からない。
      self:log(string.format(
        "この戦闘は手動のままにします。理由: %s。回復しても自動には戻りません。",
        tostring(why or "不明")), "manual latched (see log for reason)")
      self:emit("manual_latched", { reason = why or "auto_input_disabled" })
    end
  end

  local mult, why = self:decide_multiplier()
  if mult ~= self.throttle.multiplier then
    self.throttle:set(mult)
    self:emit("speed_change", { multiplier = mult, reason = why })
  end

  -- ★ゲームパッドの NES ボタンを人の入力として登録する（RX-0076）。
  --   ⚠ _apply_input の**前**に呼ぶ（requested_input はこの後すぐ消費される）。
  self:_poll_pad_input()

  -- 入力の適用。優先順位の解決とボタン送出はすべて _apply_input() に集約してある
  -- （「入力の所有権」の節を参照）。ここで joypad.set を直接呼んではいけない。
  --
  -- 補足: 自動入力はフェーズ（$0073）に依存しない。当初は $0073 が COMMAND の
  -- ときだけ押す実装にしていたが、実機でコマンドウィンドウ表示中も 0 のままに
  -- なる場合があり、入力されずに戦闘が停止した（docs/memory_map.md の注記）。
  self:_apply_input()

  -- ★演出のイベントは毎フレーム見る。
  --   レベルアップは1フレームで起きるので、間引くと取りこぼす。
  self:_check_speed_events()
  -- モンスターの絵の撮影（予約されているときだけ動く）
  self:_tick_monster_art()
  -- 遷移タイルの写真（人が頼んだときだけ動く / マッパー仕様 フェーズ4）
  self:_tick_tile_shot()

  -- 回復呪文が本当に効いたかを追う（効果での検証 / 仕様7章）
  self:_check_heal_result()

  -- 行動単位ログ（Phase 3）。★毎フレーム見る。0.5秒ごとだと
  --   1フレームで起きる変化（ダメージ）を取り逃す。
  local ok, err = pcall(function() self:_track_battle_log() end)
  if not ok and not self.battle_log_failed then
    self.battle_log_failed = true
    self:log("戦闘ログの記録に失敗しました（記録だけの機能なので続行します）: "
             .. tostring(err), "battle log failed (see log)", "WARNING")
  end

  -- ★画面へ渡した要求の返事待ちを数える（2026-08-01 / 課題 #56）。
  --   ⚠ 返事の口が無いので**時間で諦める**。諦めたら次の押下を通す。
  if self.requested_action ~= nil then
    self.gui_action_frames = (self.gui_action_frames or 0) + 1
    if self.gui_action_frames >= self.GUI_ACTION_TIMEOUT_FRAMES then
      self.requested_action = nil
      self.gui_action_frames = 0
    end
  end

  -- ホットキーは毎フレーム見る（押下を取りこぼさないため）
  self:_poll_hotkeys()

  -- ★★★ **セーブステートをロードすると `emu.framecount()` は巻き戻る。** ★★★
  --
  --   フレームカウンタは**セーブステートに含まれている**ので、
  --   古い状態を読み込むと今より小さい値に戻る。
  --   引き算のまま比べると差が**負**になり、
  --   `>= 30` が**二度と成立しない**＝**command.json を永久に読まなくなる**。
  --
  --   ⚠⚠ 実機で踏んだ形（2026-07-31 / P-3）:
  --     1. 起動して遊ぶ（framecount が増える）
  --     2. スロット1 をロードする（framecount が巻き戻る）
  --        ★ログの「レベルアップ（LV16 -> 19）」がその瞬間だった
  --     3. 以後、**保存も倍速の設定変更も戦術の切り替えも届かなくなる**
  --        （どれも command.json 経由なので、まとめて死ぬ）
  --     4. 「保存して終了」が5秒待って諦める
  --   ★1回目の保存だけ成功していたのは、**まだロードしていなかった**から。
  --
  --   ⚠ `state.json` の書き出しも同じ塊にあるので、
  --     画面の表示も一緒に止まる（＝GUI が固まったように見える）。
  local now = emu.framecount()
  if now < self.last_poll then
    -- ★巻き戻ったら基準を今に合わせる（次のフレームから普通に再開する）
    self:log(string.format(
      "セーブステートのロードを検知しました（フレーム %d -> %d）。監視を続けます",
      self.last_poll, now), "framecount rewound; poll resynced", "DEBUG")
    self.last_poll = now
    -- ⚠ ロードで**同じ座標のまま別の場所**になり得ます。★採り直させる
    self.map_sample = nil
  end

  if now - self.last_poll >= self.command_poll_interval then
    self.last_poll = now
    self:_poll_command()
    -- ★状態の書き出しも同じ間隔（0.5秒）。GUI の更新間隔と揃えてある。
    --   これより速く書いても画面は追いつかず、ディスクを削るだけ。
    --
    -- ★★ 表示用の処理で本体を止めない ★★
    --   state.json は**画面に出すためだけ**のもの。ここで落ちても
    --   ゲームの進行・倍速・記録には関係がない。それなのに
    --   実際に `self.a.party` の書き間違いで**エラーダイアログが出て止まった**
    --   （2026-07-26）。壊れても黙って落ちないよう、1回だけ理由を残して続ける。
    local ok, err = pcall(function() self:_write_state() end)
    if not ok and not self.state_write_failed then
      self.state_write_failed = true
      self:log("状態の書き出しに失敗しました（画面表示だけの機能なので続行します）: "
               .. tostring(err), "state write failed (see log)", "WARNING")
    end
  end

  if gui and gui.text then
    -- 画面表示は英数字のみ（FCEUX の gui.text は日本語を出せない）
    --
    -- ★★ 出す行だけを上から詰める ★★
    --
    --   以前は y を固定（4 / 12 / 20 / 28）にしていた。すると
    --   DANGER も CAUTION も出ていないとき、FIELD と FORCE AUTO のあいだに
    --   **3行ぶんの空白**ができ、離れて見えた（依頼者の指摘）。
    --   出す行だけを順に積めば、常に1行間隔で並ぶ。
    --
    -- ★開始位置を 4 -> 10 へ下げた。4 だと画面の上端で**文字が見切れていた**
    --   （テレビのオーバースキャンで上端が欠けるのと同じ理由）。
    local line_y = OVERLAY_TOP
    local function say(text)
      gui.text(OVERLAY_LEFT, line_y, text)
      line_y = line_y + OVERLAY_STEP
    end

    if s.in_battle then
      say("BATTLE x" .. tostring(self.throttle.multiplier))
    elseif self.action_multiplier ~= nil then
      say("AUTO x" .. tostring(self.throttle.multiplier))
    else
      say("FIELD")
    end
    if s.danger then
      -- 日本語は出せないので英数字で区別する（読めていないだけ / 本当に危険）
      if s.danger_reason == UNREADABLE_PARTY then
        say("NO SAVE LOADED")
      else
        say("DANGER")
      end
    end
    -- ★警戒中であることを画面に出す。
    -- 出していなかったため「自動戦闘がきかない」原因が利用者に分からなかった。
    -- 倍速も自動入力も止まる条件は、必ず理由が見える形にする。
    if s.is_caution then say("CAUTION (fled before)") end
    -- ★強制AUTO は安全機構を潰すので、入っている間は必ず出す
    if self.battle.force_auto then
      local boss = (self.config.auto_input.force_auto_includes_boss == true)
      say("FORCE AUTO" .. (boss and "" or " (boss:off)"))
    end
    -- 直近のホットキー操作の結果（数秒だけ）
    if self.notice_left > 0 and self.notice ~= nil then
      gui.text(OVERLAY_LEFT, 220, self.notice)
      self.notice_left = self.notice_left - 1
    end
  end
end

-- emu.frameadvance() の「直後」に呼ぶ。倍率に合わせて待つ。
function Bridge:after_frame()
  self.throttle:tick()
end

return Bridge
