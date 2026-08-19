-- RetroUX 本番の入口
--
-- 起動:
--   set RETROUX_ROOT=F:\Projects\260721_RetroUX
--   tools\fceux\fceux64.exe -lua retroux\emulator\fceux\run.lua work\rom\DQ2_J.nes
--
-- 事前に `python -m retroux.core.config.generate_lua` を実行しておくこと。
--
-- 単発の操作要求（まんたん）は work/command.json 経由で受け取る。
-- Python 側からは:
--   write_command(path, encountered=[...], action="mantan", request_id=<毎回変える>)

local root = os.getenv("RETROUX_ROOT")
if root == nil or root == "" then root = "F:/Projects/260721_RetroUX" end
root = root:gsub("\\", "/"):gsub("/$", "")

local Bridge       = assert(loadfile(root .. "/retroux/emulator/fceux/bridge.lua"))()
local ActionDriver = assert(loadfile(root .. "/retroux/emulator/fceux/action_driver.lua"))()
-- まんたんは DQ2 固有の操作。ブリッジは要求を受け取るだけで実行しない。
-- プラグインの動的選択は MVP2 の課題（現状はブリッジも DQ2 を直接読んでいる）。
local Mantan       = assert(loadfile(root .. "/retroux/plugins/dq2/mantan.lua"))()
local Restock      = assert(loadfile(root .. "/retroux/plugins/dq2/restock.lua"))()
local Fukubiki     = assert(loadfile(root .. "/retroux/plugins/dq2/fukubiki.lua"))()
local TalkDispatch = assert(loadfile(root .. "/retroux/plugins/dq2/talk_dispatch.lua"))()

local bridge = Bridge.new({ root = root })

-- 起動メッセージは Bridge が出す（コンソールは英数字のみ。
-- FCEUX の Lua コンソールは UTF-8 非対応で日本語が文字化けするため）。
bridge:log("起動: " .. bridge.memory_map.rom.title
           .. " / 戦闘倍率 " .. tostring(bridge.config.speed.battle_multiplier))

local driver = ActionDriver.new({
  bridge = bridge,
  handlers = {
    mantan = function(br)
      return Mantan.new({
        game = br.game, bridge = br,
        -- 回復手段の優先順（既定は ホイミ -> やくそう）。config の mantan
        config = br.config.mantan or {},
        -- 回復目標モード。command.json で上書きされていればそちらを使う
        -- （GUI からの切り替え用。未指定なら config の mode）
        mode = br.mantan_mode,
        on_progress = function(phase, msg)
          br:log(string.format("[まんたん/%s] %s", phase, msg), nil, "DEBUG")
        end,
      })
    end,
    restock = function(br)
      local cfg = br.config.restock or {}
      if cfg.enabled == false then return nil end
      return Restock.new({
        game = br.game, bridge = br, config = cfg,
        on_progress = function(phase, msg)
          br:log(string.format("[補充/%s] %s", phase, msg), nil, "DEBUG")
        end,
      })
    end,
    fukubiki = function(br)
      local cfg = br.config.fukubiki or {}
      if cfg.enabled == false then return nil end
      return Fukubiki.new({
        game = br.game, bridge = br, config = cfg,
        on_progress = function(phase, msg)
          br:log(string.format("[ふくびき/%s] %s", phase, msg), nil, "DEBUG")
        end,
      })
    end,
    -- ★R キー = 「話しかけて相手に応じたマクロを走らせる」（依頼者の要望）。
    --   はなした直後のメニューIDで相手を見分ける:
    --     0x18 店の売買選択 -> 補充 / 0x19 ふくびきの会話 -> ふくびき
    --   どちらでもなければ何もせず中止する（知らない相手にボタンを押さない）。
    talk = function(br)
      return TalkDispatch.new({
        game = br.game, bridge = br, config = br.config.talk or {},
        routes = {
          [0x18] = { name = "補充", build = function(b)
            local cfg = b.config.restock or {}
            if cfg.enabled == false then return nil end
            return Restock.new({
              game = b.game, bridge = b, config = cfg,
              on_progress = function(phase, msg)
                b:log(string.format("[補充/%s] %s", phase, msg), nil, "DEBUG")
              end,
            })
          end },
          [0x19] = { name = "ふくびき", build = function(b)
            local cfg = b.config.fukubiki or {}
            if cfg.enabled == false then return nil end
            return Fukubiki.new({
              game = b.game, bridge = b, config = cfg,
              on_progress = function(phase, msg)
                b:log(string.format("[ふくびき/%s] %s", phase, msg), nil, "DEBUG")
              end,
            })
          end },
        },
        on_progress = function(phase, msg)
          br:log(string.format("[はなす/%s] %s", phase, msg), nil, "DEBUG")
        end,
      })
    end,
  },
  on_event = function(kind, message, fields)
    -- ★操作の**要約**（開始/終了/skip）は INFO で残す（§18H「最終結果は INFO」/ RX-0065）。
    --   ⚠ 画面が「skipped - see work/retroux.log」と言うのに、DEBUG だと
    --     通常モード（file_level=INFO）でファイルに1行も出なかった。
    --   ★進捗の細行（[まんたん/…] 等）は DEBUG のまま（§18H 途中→DEBUG）。
    bridge:log("[操作] " .. message, "action " .. kind, "INFO")
    bridge:emit("action_" .. kind, fields)
    -- ★結果を画面にも出す。ログとコンソールだけでは
    --   「押しても何も起きない」ように見えてしまう。
    -- gui.text は日本語を出せないので英数字の要約にする。
    local label = {
      start   = "started",
      done    = "done",
      skipped = "skipped - see work/retroux.log",
      busy    = "busy",
      unknown = "unknown action",
    }
    local action = tostring(fields.action or "action")
    bridge:notify(string.format("%s: %s", action, label[kind] or kind))
  end,
})

while true do
  driver:tick()            -- ★bridge:step() の前
  bridge:step()
  emu.frameadvance()
  bridge:after_frame()
end
