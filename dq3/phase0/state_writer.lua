-- いまの値を画面へ渡す（RX3-0019 / 2026-08-29）。
--
-- ★★ ここが Lua と画面の継ぎ目 ★★
--
--     Lua  →  work/state.json  →  state_reader.GameState  →  画面
--
-- ⚠ この形は DQ2 で既に動いているもので、**`GameState` に DQ2 固有のものは無い**。
--   ★同じ形で書けば、画面（`retroux/ui`）はそのまま使える。
--
-- ## ⚠ events.jsonl とは役割が違う
--
--     events.jsonl  起きたこと    追記   ⚠ 消えると記録が失われる
--     state.json    いまの値      上書き ★消えても次で書き直される
--
--   ⚠ 毎秒の HP/MP を events へ流すと、記録が現在値で埋まって意味が変わる。
--
-- ## ⚠⚠ 重くしない
--
--   DQ2 で踏んだ実測: 地図の描き直しが 1 回 **137.8 ms**（1 歩ごと）。
--   ★267 ms の枠で 138 ms を使い、録画が乗ると FCEUX が 1 フレーム落ちた。
--   → ⚠ **毎フレームは書かない。** 30 フレーム（0.5 秒）に 1 回。
--
-- ## ⚠ 書いている途中を読ませない
--
--   ★一時ファイルへ書いてから置き換える。⚠ 直接書くと、読む側が欠けを拾う
--   （`state_reader` は前回値を返すので落ちはしないが、★無駄に古くなる）。

local M = {}

--- ⚠ 画面側と名前が違うもの（★上で書き換え済みなので、二度写さない）。
local RENAMED = {slot = true, hp_max = true, mp_max = true, name = true}

--: ★共有部分（⚠ JSON はここに 1 つだけ / RX3-0031）
local Core = dofile((os.getenv("RETROUX_ROOT") or "C:/Projects/260721_RetroUX")
                    :gsub(string.char(92), "/"):gsub("/$", "")
                    .. "/dq3/phase0/core.lua")

--- ★書き出す道具を 1 つ作る。
--
-- ⚠ `opts.path` は書き出し先。★`opts.every` は何フレームおきか。
--
-- ★`opts.busy` が `true` を返すあいだは `opts.busy_every` を使います
--   （RX3-0065 / 2026-09-03）。
--   ⚠⚠ 実測で、敵の**全行が見える瞬間は 52 枚に 1 枚**しかありませんでした。
--     ★見えている時間が短いので、⚠ 0.5 秒おきでは取りこぼします。
function M.new(opts)
  opts = opts or {}
  local W = {}
  local path = opts.path
  local every = opts.every or 30
  --- ⚠ 忙しいあいだだけ詰める（★既定は同じ ＝ 何も変わらない）
  local busy = opts.busy
  local busy_every = opts.busy_every or every
  local say = opts.say or function() end
  local party_of = opts.party or function() return {} end
  local extra = opts.extra or function() return {} end
  --- ★いまどこに居るか（⚠ 番地を知っているのは呼び出し側）
  local where = opts.where or function() return {} end

  W.wrote = 0
  W.failed = 0
  W.rewinds = 0                    --: ★フレーム数が巻き戻った回数（RX3-0167）
  W.last_error = nil

  --: ⚠ 前に書いたフレーム（★間隔を守るため）
  local last_at = -1

  --- ★JSON にする（⚠ 外部ライブラリを増やさない）。
  --
  -- ⚠ DQ3 の名前は**生のタイル番号**で渡す（★文字にするのは Python 側）。
  --   文字コード表はまだ直る見込みがあるので、**加工前を渡す**
  --   （`RX3-0016` の「raw を捨てない」と同じ考え）。
  -- ⚠⚠ **中身は `core.lua` の 1 つだけ**（RX3-0031 / 2026-08-31）。
  --   ★ここには同じ JSON の書き出しが写してありました。
  --   ⚠ 2 か所に書くと片方だけ古くなる（★`text_of` で実際に踏んだ）。
  W.encode = Core.json

  --- ★いまの値を組み立てる。
  function W.snapshot()
    local party = {}
    for _, m in ipairs(party_of()) do
      local row = {
        name = m.slot,                 -- ⚠ 表示名はまだ無い（★下の name_tiles）
        index = #party,
        hp = m.hp, max_hp = m.hp_max,
        mp = m.mp, max_mp = m.mp_max,
        -- ★生のタイル番号のまま渡す（⚠ 文字にするのは Python 側）
        name_tiles = m.name,
      }
      -- ★★ 名前の違うもの以外は**そのまま通す**。
      --
      -- ⚠⚠ ここを決め打ちの一覧にしていたせいで、⚠ Lua が読んだ
      --   ちから・すばやさ・こうげき力・職業が**黙って捨てられて**いた
      --   （2026-08-29。★画面には HP と MP しか出ず、原因がここだと分からなかった）。
      --   → ★増えた値が自動で届くように、**残り全部**を写す。
      for k, v in pairs(m) do
        if RENAMED[k] == nil and row[k] == nil then row[k] = v end
      end
      party[#party + 1] = row
    end
    local out = {
      frame = emu.framecount(),
      game = "dq3",
      party = party,
    }
    for k, v in pairs(where() or {}) do out[k] = v end
    for k, v in pairs(extra() or {}) do out[k] = v end
    return out
  end

  --- ★毎フレーム呼ぶ。⚠ 実際に書くのは `every` フレームに 1 回。
  function W.tick()
    if path == nil then return false end
    local now = emu.framecount()
    local gap = every
    if busy ~= nil then
      local ok, yes = pcall(busy)
      if ok and yes then gap = busy_every end
    end
    -- ⚠⚠ セーブを読むとフレーム数が**巻き戻る**（RX3-0167 / 実測 1,454,020 → 1,417,640）。
    --   ★差だけで見ると、戻った分（何分も）書かなくなり、右画面の位置も地図も止まる
    --   （2026-09-11 依頼者「save1 マップと歩いているところの同期が取れない。マップが黒い」）。
    --   → ★前より小さくなったら巻き戻りとみなし、すぐ書く（★1 行だけ残す）。
    if last_at >= 0 and now < last_at then
      W.rewinds = (W.rewinds or 0) + 1
      say(string.format("★フレーム数が巻き戻った（%d → %d / セーブを読んだ）。すぐ書き直す", last_at, now))
    elseif last_at >= 0 and now - last_at < gap then
      return false
    end
    last_at = now

    local text = W.encode(W.snapshot())
    -- ★一時ファイルへ書いてから置き換える（⚠ 読む側に欠けを見せない）
    local tmp = path .. ".tmp"
    local f = io.open(tmp, "w")
    if f == nil then
      W.failed = W.failed + 1
      if W.last_error == nil then
        W.last_error = "書けません: " .. tostring(tmp)
        say("  ⚠⚠ state を書けません: " .. tostring(tmp))
      end
      return false
    end
    f:write(text)
    f:close()
    -- ⚠ Lua 5.1 の `os.rename` は、置き換え先があると Windows で失敗する。
    --   ★先に消してから移す。消せなくても、次の 0.5 秒でやり直す。
    os.remove(path)
    local ok = os.rename(tmp, path)
    if not ok then
      W.failed = W.failed + 1
      if W.last_error == nil then
        W.last_error = "置き換えられません"
        say("  ⚠ state を置き換えられませんでした（★次で作り直します）")
      end
      return false
    end
    W.wrote = W.wrote + 1
    return true
  end

  return W
end

return M
