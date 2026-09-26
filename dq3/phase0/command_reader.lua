-- 画面からの頼みごとを受け取る（RX3-0019 / 2026-08-29）。
--
-- ★★ 向きに注意 ★★
--
--     state.json       Lua → 画面（★いまの値。上書き）
--     dq3-command.json 画面 → Lua（★頼みごと。ここ）
--
-- ⚠ DQ2 も同じ形（`work/command.json` を 30 フレームおきに見る / `DEV-3`）。
--
-- ## ⚠⚠ Lua に JSON パーサは無い
--
--   ★必要な項目だけを**正規表現で拾う**。⚠ だから書く側は
--   「1 行・素直な形」で書くこと（ネストや余計な空白を増やさない）。
--
-- ## ⚠ 同じ頼みを 2 回きかない
--
--   ★通し番号（`seq`）で見分ける。⚠ 「押された名前」だけだと、
--   **同じボタンの 2 回目**を取りこぼす（DQ2 で踏んだ形）。

local M = {}

--- ★頼みごとを読む道具を 1 つ作る。
--
-- ⚠ `opts.every` フレームに 1 回しかファイルを見ない（★毎フレームは重い）。
function M.new(opts)
  opts = opts or {}
  local R = {}
  local path = opts.path
  local every = opts.every or 30
  local say = opts.say or function() end

  --: ★最後に処理した通し番号（⚠ これで 2 回きくのを防ぐ）
  --
  -- ⚠⚠ **0 から始めてはいけない。**
  --   頼みごとのファイルは**残る**ので、次に FCEUX を起動したとき
  --   ★最後の頼みをもう一度実行してしまう（2026-08-29 に実機で踏んだ:
  --   起動直後に `mantan（seq=7）` が走り、画面が未描画のまま止まった）。
  --   → ★起動時に**いまの番号まで進めておく**。⚠ 押し直せば必ず先へ行く。
  R.seq = 0
  R.read = 0
  R.handled = 0
  local last_at = -1

  --- ⚠ 見つからなければ nil（★無いことは異常ではない）。
  local function slurp()
    local f = io.open(path, "r")
    if f == nil then return nil end
    local text = f:read("*a")
    f:close()
    return text
  end

  --- ★項目を 1 つ拾う（⚠ 完全な JSON 解析はしない）。
  local function field(text, key)
    return text:match('"' .. key .. '"%s*:%s*"([^"]*)"')
  end

  local function number(text, key)
    local got = text:match('"' .. key .. '"%s*:%s*(-?%d+)')
    return got and tonumber(got) or nil
  end

  --- ★毎フレーム呼ぶ。⚠ 新しい頼みがあれば `{action=..., seq=...}` を返す。
  function R.tick()
    if path == nil then return nil end
    local now = emu.framecount()
    -- ⚠⚠ セーブを読むとフレーム数が巻き戻る（RX3-0167）。★差だけで見ると、戻った分（何分も）
    --   頼みを読まなくなる（★右画面のボタンが効かない）。→ ★前より小さくなったらすぐ読む
    if last_at >= 0 and now >= last_at and now - last_at < every then return nil end
    last_at = now

    local text = slurp()
    if text == nil then return nil end
    R.read = R.read + 1

    local seq = number(text, "seq")
    -- ⚠ 通し番号が無い、または前と同じなら**何もしない**
    if seq == nil or seq <= R.seq then return nil end
    R.seq = seq

    local action = field(text, "action")
    if action == nil or action == "" then return nil end
    R.handled = R.handled + 1
    say("★画面からの頼み: " .. action .. "（seq=" .. seq .. "）")
    -- ★引数（RX3-0058 / 街ナビ）: 文字列の項目を全部拾う（⚠ 1 段だけ / 値に " は入れない）
    local params = {}
    for k, v in text:gmatch('"([%w_]+)"%s*:%s*"([^"]*)"') do
      if k ~= "action" then params[k] = v end
    end
    return {action = action, seq = seq, params = params}
  end

  --- ★起動時に、いまファイルにある番号まで進めておく。
  --
  -- ⚠ ファイルが無ければ 0 のまま（★新しく始めたのと同じ）。
  function R.catch_up()
    if path == nil then return 0 end
    local text = slurp()
    if text == nil then return 0 end
    local seq = number(text, "seq")
    if seq ~= nil and seq > R.seq then
      R.seq = seq
      say(string.format("★前回の頼み（seq=%d）は済んだものとして飛ばします", seq))
    end
    return R.seq
  end

  R.catch_up()
  return R
end

return M
