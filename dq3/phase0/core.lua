-- Phase 0 の機能が共有するもの（RX3-0018 / 2026-08-29）。
--
-- ★★ なぜこれが要るのか ★★
--
--   依頼者「別々に確認すると手間なので、開発中の機能として、
--           両方含めた lua で進めたい」（2026-08-29）
--
-- ⚠⚠ 手間の話だけではありません。**技術的に 1 か所へ寄せないと壊れます。**
--
--   `joypad.set` は**後勝ち**です。同じフレームに 2 つが書くと、
--   ★先に書いたほうが**無かったことになります**。
--
--   ⚠ 実際に踏みました。検証用 probe が製品の入力を上書きし、
--   症状は「**12,000 フレームで HP 変化 0 回**」という形でしか出ませんでした。
--   ★エラーは 1 つも出ません。
--
--   → いままでは「2 本同時に起動しない」という**運用の約束**で避けていました。
--     ⚠ 約束は破れます。★ここで**破れない形**にします。
--
-- ## ★ここが持つもの
--
--     ボタン   誰が押してよいかを 1 人に決める（★`joypad.set` はここだけ）
--     速度     ターボの入り切り（⚠ 2 か所にあると必ずずれる）
--
-- ## ⚠ ここが持たないもの
--
--   画面の読み方・カーソルの見分け・機能ごとの手順。
--   ★それらは `screen.lua` / `cursor.lua` と、各機能が持ちます。

local M = {}

----------------------------------------------------------------------
-- ★★ ボタン ― 持ち主は 1 人だけ
----------------------------------------------------------------------

--: ★★ ゲームが「新しく押された」と判断した結果が入る番地。
--
-- ★ROM を読んで分かったこと（`$CB16` / `$C341` / `$CB25`）:
--
--     $CB1A  JSR $C341   ; ★1 フレーム待つ（$06D2 が変わるまで）
--     $CB1D  JSR $CB25   ; ★コントローラを読む
--     $CB20  LDA $14     ; 新しく押されたボタン
--     $CB22  BEQ $CB1A   ; ⚠ 無ければ戻る
--
--   ⚠ **読むのは 1 フレームに 1 回、NMI を待った直後の一瞬だけ。**
--   ⚠ ラグフレームは実測 25.9%。★1 フレームの `joypad.set` はすれ違って消える。
--
-- ⚠⚠ 長く押すのも駄目。同じルーチンに連射があります:
--
--     $CB4C  LDY #$08    ; ★0 なら 8 を装填
--     $CB53  LDY #$0B    ; ⚠ 以後 11 フレームごと
--
--   → **8 フレーム押し続けると 2 回選ばれます。**
--
-- ★だから「届いたら離す」。⚠ 固定フレーム数はめくら撃ちです。
M.INPUT_NEW = 0x14
M.INPUT_HELD = 0x16

--- ★ボタンの持ち主を決める道具を 1 つ作る。
--
-- ⚠ `opts.hold_max` を超えても `$14` が立たなければ、**諦めて記録**します。
--   ★黙って次へ進めません。
function M.new_buttons(opts)
  opts = opts or {}
  local B = {}
  local hold_max = opts.hold_max or 7
  local say = opts.say or function() end

  --: ⚠ いまボタンを握っている機能の名前（★nil なら誰も握っていない）
  B.owner = nil
  --: ⚠ いま押しているボタンと、何フレーム押したか
  B.holding, B.held_for = nil, 0
  --: ★届かなかった回数
  B.missed = 0
  --: ⚠⚠ **持ち主でないのに押そうとした回数**（★ここが 0 でないなら設計が壊れている）
  B.blocked = 0
  --: ⚠ 同じフレームで 2 回 `tick` されないための目印
  B.ticked_at = -1
  --: ★★ 押し方の注文（⚠ 押すたびに決める / 既定は今までどおり）
  --
  --   ⚠⚠ **歩くときは決まりが違います**（2026-09-01 実機）。
  --     ★メニューの A は `$14`（新しく押された）で届いたと分かりますが、
  --     ⚠ 移動の十字キーは `$14` が立たないことがあり、
  --     7 フレームで「届かなかった」と諦めていました。
  --     → ★歩きは `$16`（押されている）を見て、長く押します。
  B.limit, B.latch = hold_max, M.INPUT_NEW

  --- ★ボタンを握る。⚠ 誰かが握っていれば false。
  function B.claim(who)
    if B.owner ~= nil and B.owner ~= who then return false end
    B.owner = who
    return true
  end

  --- ★手を離す。⚠ 押しかけのものも捨てる（★次の持ち主へ持ち越さない）。
  function B.release(who)
    if B.owner ~= who then return end
    B.owner = nil
    B.holding, B.held_for = nil, 0
  end

  --- ★押しかけているものを取り消す。⚠ 持ち主のままでいる。
  --
  -- ⚠ `release` との違い: こちらは**手を離さない**。
  --   ★「押すのをやめたいが、まだ自分の番」というときに使う
  --   （例: 戦闘が終わってフィールドに戻った直後）。
  function B.cancel(who)
    if B.owner ~= who then return false end
    B.holding, B.held_for = nil, 0
    return true
  end

  --- ★押す。⚠ 実際に押されるのは次のフレームから、届くまで。
  --
  -- ⚠⚠ 持ち主でなければ**押しません**。★黙って無視せず、数えて記録します。
  -- @param opts.hold        ★何フレームまで押すか（⚠ 既定は `hold_max`）
  -- @param opts.watch_held  ⚠ `$16`（押されている）で届いたと見る
  function B.press(who, key, opts)
    opts = opts or {}
    if B.owner ~= who then
      B.blocked = B.blocked + 1
      say(string.format(
        "  ⚠⚠ %s が %s を押そうとした（★持ち主は %s / 累計 %d 回）",
        tostring(who), tostring(key), tostring(B.owner), B.blocked))
      return false
    end
    B.holding, B.held_for = key, 0
    B.limit = opts.hold or hold_max
    B.latch = opts.watch_held and M.INPUT_HELD or M.INPUT_NEW
    return true
  end

  --- ★毎フレーム 1 回だけ呼ぶ。⚠ `joypad.set` を呼ぶのは**ここだけ**。
  --
  -- ⚠ 2 回呼ばれても 2 回は押しません（★フレーム番号で見張ります）。
  --   機能が 2 つあると、どちらも先頭で呼びたくなるためです。
  function B.tick()
    local now = -1
    pcall(function() now = emu.framecount() end)
    if now >= 0 and now == B.ticked_at then return end
    B.ticked_at = now

    if B.holding == nil then return end
    if B.held_for > 0 and memory.readbyte(B.latch) ~= 0 then
      -- ★ゲームが受け取った。⚠ すぐ離す（離さないと 8 フレームで 2 回目）
      if B.held_for > 2 then
        say(string.format("  ⓘ %s は %d フレームで届いた（$14=%02X $16=%02X）",
          B.holding, B.held_for, memory.readbyte(M.INPUT_NEW),
          memory.readbyte(M.INPUT_HELD)))
      end
      B.holding, B.held_for = nil, 0
      return
    end
    joypad.set(1, {[B.holding] = true})
    B.held_for = B.held_for + 1
    if B.held_for >= B.limit then
      -- ⚠⚠ 届かなかった。★黙って進めない
      B.missed = B.missed + 1
      say(string.format("  ⚠⚠ %s が届かなかった（%d フレーム押した / 累計 %d 回）",
        B.holding, B.held_for, B.missed))
      B.holding, B.held_for = nil, 0
    end
  end

  --- ⚠ いま押しかけているか（★機能側が「まだ待つ」を決めるのに使う）。
  function B.busy() return B.holding ~= nil end

  return B
end

----------------------------------------------------------------------
-- ★★ 速度 ― スイッチは 1 つだけ
----------------------------------------------------------------------

--- ★ターボの入り切りを 1 か所で持つ。
--
-- ⚠⚠ これを機能ごとに持つと必ずずれます。実際、戦闘とまんたんが
--   それぞれ `set_speed` を持っていて、**二重管理**になっていました。
--
--   ★手で入れたターボ（`T`）は、機能の入り切りで**勝手に戻しません**。
--   ⚠ 人の指示のほうが強い、という約束です。
function M.new_speed(opts)
  opts = opts or {}
  local S = {}
  local say = opts.say or function() end

  --: ★人が `T` で入れたターボ
  S.manual = false
  --: ⚠ 機能が要求しているターボ
  S.wanted = false
  --: ★最後に実際に送った語（⚠ 同じ語を何度も送らない）
  S.mode = nil
  --: ★名前つきの要求（RX3-0170 / 例: 街の自動操作の `TOWN`）。⚠ 戦闘の `wanted` とは別に持つ
  S.holds = {}
  --: ★"normal" を送った回数（RX3-0170）。⚠ FCEUX は normal で 100% に戻るので、
  --   画面はこれが増えるたびに人の倍率（管理画面の 2 倍速など）を送り直す
  S.normal_count = 0

  local function held()
    for _, on in pairs(S.holds) do
      if on then return true end
    end
    return false
  end

  local function apply()
    local mode = (S.manual or S.wanted or held()) and "turbo" or "normal"
    if mode == S.mode then return true end
    local ok, err = pcall(function() emu.speedmode(mode) end)
    if ok then
      S.mode = mode
      if mode == "normal" then S.normal_count = S.normal_count + 1 end
    else
      say("  ⚠ 速度を変えられなかった: " .. tostring(err))
    end
    return ok
  end

  --- ★機能からの要求（⚠ 手動が入っていれば、切っても戻さない）。
  function S.want(on) S.wanted = on and true or false; return apply() end

  --- ★名前つきの要求（RX3-0170）。⚠ 他の要求を消さない（★どれか 1 つでも入っていればターボ）。
  function S.hold(key, on) S.holds[key] = on and true or nil; return apply() end

  --- ★その名前の要求が入っているか。
  function S.holding(key) return S.holds[key] == true end

  --- ★いまが normal なら、FCEUX へ normal を**もう一度**送る（RX3-0241）。戻り値: 送ったか。
  --   ★FCEUX の normal は 100%。★区間減速で画面が送った倍率（400%）を、画面を待たずに等速へ戻す。
  --   ⚠ ターボの要求が 1 つでも残っていれば何もしない（★戦闘・人の T を消さない）。
  function S.renormal()
    if S.manual or S.wanted or held() or S.mode ~= "normal" then return false end
    local ok = pcall(function() emu.speedmode("normal") end)
    if ok then S.normal_count = S.normal_count + 1 end
    return ok
  end

  --: ★人が速さを変えた回数（★戦闘の高速化が「人の操作」を見分ける / RX3-0166）
  S.user_changes = 0

  --- ★`T` で人が入り切りする。
  function S.toggle()
    S.manual = not S.manual
    S.user_changes = S.user_changes + 1
    local ok = apply()
    return S.manual, ok
  end

  --- ⚠ 終わるときは**必ず**通常速度へ戻す（★ターボのまま返さない）。
  function S.reset()
    S.manual, S.wanted = false, false
    S.holds = {}
    return apply()
  end

  return S
end

----------------------------------------------------------------------
-- ★ 小物（⚠ 両方が同じものを持っていた）
----------------------------------------------------------------------

--- ★2 バイトの数（⚠ DQ3 は下位が先）。
function M.w16(addr)
  return memory.readbyte(addr) + memory.readbyte(addr + 1) * 256
end

--- ★★ Output Console 向けに ASCII だけ残す（RX3-0064 / 2026-09-03）。
--
--   ⚠⚠ FCEUX 2.6.6 の Output Console は **cp932** で読みます。
--     ★Lua は UTF-8 で書くので、日本語が化けます。
--
--   ```text
--   実際の表示   繝ｻ隰ｻ邱ｩ勵◆ / 邏ｽ險ｺ・16 蝗槫｡ｼ 笞・笞・up …
--   読めていた所  up / down / left / right / (176,191) / AUTO ON / $62: 2
--   ```
--
--   ★ASCII だけが読めていました。⚠ そこで **Console へ渡す行だけ**を
--     ASCII に落とします。⚠⚠ **ファイルの記録（`test.log`）は UTF-8 のまま**です
--     （★そちらは読めているので、両方を落とすと情報が減ります）。
--
--   ⚠ 落とした所は 1 個の空白にまとめ、★数字・座標・向きだけが残るようにします。
--     ⚠ 何も残らない行は `nil` を返すので、呼ぶ側は**出さないでください**。
function M.ascii(s)
  if s == nil then return nil end
  local out, gap = {}, false
  for i = 1, #s do
    local b = s:byte(i)
    if b >= 0x20 and b <= 0x7E then
      out[#out + 1] = string.char(b)
      gap = false
    elseif not gap then
      out[#out + 1] = " "
      gap = true
    end
  end
  local text = table.concat(out)
  text = text:gsub("^%s+", ""):gsub("%s+$", ""):gsub("%s%s+", " ")
  -- ⚠ 記号と空白しか残らなかった行は出さない（★意味が無い）
  if text:find("[%w]") == nil then return nil end
  return text
end

--- ★キーが「新しく押された」ときだけ true。
--
-- ⚠ 押しっぱなしで毎フレーム反応させない（★入り切りが暴れる）。
--
-- ## ⚠⚠ フレームではなく**実時間**で間を置く（2026-08-29）
--
--   実機で「まんたんが暴れる」（`M` を 1 回押すと ON→OFF）が出た。
--   ★ターボ中は 1 秒に数千フレーム進むので、`input.get()` が
--   **押しっぱなしの途中で 1 度でも false を返す**と、離して押し直したと見て
--   2 回目が発火する。⚠ フレーム数で間を置いても、ターボでは一瞬で過ぎる。
--
--   → ★発火したら `debounce` 秒のあいだ、同じキーは見ない。
--   ⚠ `os.clock()` は CPU 時間だが、FCEUX の Lua では十分に進む。
--
-- ⚠ `opts.clock` を渡せる（★足場が時間を進められるように）。
--   実機では `os.clock`。⚠ 足場で本物を使うと、時間が進まず**全部**捨てられる。
function M.new_edge(opts)
  opts = opts or {}
  local prev = {}
  local fired = {}
  local off_polls = {}
  local debounce = opts.debounce or 0.20
  --: ⚠⚠ 「本当に離した」と認めるまでに要る、離れて見えた回数。
  --   ★1 フレームだけのちらつきでは足りない数にする。
  local release_polls = opts.release_polls or 4
  local clock = opts.clock
  return function(name)
    local keys = input.get()
    local now = keys[name] ~= nil
    local was = prev[name] == true
    prev[name] = now

    -- ★離れて見えた回数を数える（⚠ ちらつきと本当の離しを見分けるため）
    --   ⚠⚠ **0 に戻す前の値**を控える。★戻したあとで見ると必ず 0 になり、
    --   押し直しが永久に通らなくなる（実装中に踏んだ）。
    local off_before = off_polls[name] or 0
    if now then
      off_polls[name] = 0
    else
      off_polls[name] = off_before + 1
    end

    if not (now and not was) then return false end

    local at = 0
    if clock ~= nil then
      at = clock()
    else
      pcall(function() at = os.clock() end)
    end
    local last = fired[name]
    if last ~= nil then
      -- ⚠⚠ **2 つとも満たさなければ 2 回目としない**（2026-08-29 / 2 度目の直し）。
      --   ★時間だけでは足りなかった: 0.2 秒より長く押していると、
      --   途中のちらつきが「間合いを過ぎた押し直し」に見える。
      local waited = at - last >= debounce
      local released = off_before >= release_polls
      if not (waited and released) then return false end
    end
    fired[name] = at
    off_polls[name] = 0
    return true
  end
end

----------------------------------------------------------------------
-- ★★ 記録を開く（⚠ 開けなくても本体を止めない）★★
--
-- ## ⚠⚠ 記録が開けないだけで、機能が丸ごと止まっていました
--
--   `mantan_v0.lua` は `assert(io.open(...))` でした。
--   ★`work/dq3-probe/` が無いと **まんたんが読み込みに失敗**し、
--   ⚠ `dev.lua` の `pcall` に飲まれて「機能が 1 件（2 のはず）」に
--   なっていました（2026-08-30 / RX-0114 で発覚）。
--
--   ⚠⚠ **記録は本体の付属品です。** 付属品が無いから本体を止める、は
--   順番が逆でした。
--
-- ## ★決めごと（依頼者の指示 2026-08-30）
--
--   1  必要な folder は作る
--   2  記録が出せないときは console に伝える
--   3  ⚠⚠ 記録の不調だけを理由に、本体機能を止めない
--
-- ⚠ Lua には mkdir がありません。★`os.execute` は**開けなかったときだけ**
--   呼びます（普段は 1 回も呼びません）。
----------------------------------------------------------------------

--: ★folder を作る（⚠ 開けなかったときだけ呼ばれる）
local function ensure_dir(path)
  local dir = path:match("^(.*)[/\][^/\]*$")
  if dir == nil or dir == "" then return false end
  local win = dir:gsub("/", string.char(92))
  -- ⚠ 失敗しても構わない（★すでに在る場合も失敗扱いになる）
  pcall(function() os.execute('mkdir "' .. win .. '" 2>nul') end)
  return true
end

--: ★記録を開く。⚠ 開けなければ nil を返す（★落とさない）
function M.open_log(path, tag)
  local fh = io.open(path, "a")
  if fh == nil and ensure_dir(path) then
    fh = io.open(path, "a")                     -- ★folder を作って、もう一度
  end
  if fh == nil then
    -- ⚠⚠ 記録に書けないので、★console にだけ伝える
    print("⚠⚠ " .. tostring(tag or "記録") .. " を開けません: " .. tostring(path))
    print("   ★機能そのものは動きます（⚠ 記録だけが残りません）")
  end
  return fh
end


-----------------------------------------------------------------------
-- ★★ JSON（RX3-0031 / 2026-08-31）
----------------------------------------------------------------------

--: ⚠ 引用符とバックスラッシュは番号で持つ（★ここで書くと読みにくい）
local QUOTE = string.char(34)
local BSLASH = string.char(92)

--: ⚠ 逃がす文字（★制御文字は JSON にそのまま書けない）
local ESCAPES = {}
ESCAPES[BSLASH] = BSLASH .. BSLASH
ESCAPES[QUOTE] = BSLASH .. QUOTE
ESCAPES[string.char(10)] = BSLASH .. "n"
ESCAPES[string.char(13)] = BSLASH .. "r"
ESCAPES[string.char(9)] = BSLASH .. "t"

local ESC_PAT = "[" .. BSLASH .. QUOTE .. string.char(10, 13, 9) .. "]"

local function esc(s)
  s = tostring(s)
  return (s:gsub(ESC_PAT, function(c) return ESCAPES[c] or c end))
end

--- ★★ Lua の値を JSON にする（⚠ 外部ライブラリを増やさない）。
--
-- ⚠⚠ **ここが唯一の実装**（RX3-0031 / 2026-08-31）。
--   ★`state_writer.lua` が同じものを持っていたので、こちらへ寄せた。
--   ⚠ 2 か所に書くと片方だけ古くなる（★2026-08-31 に `text_of` で踏んだ）。
--
-- ⚠ 整数は整数のまま出す（★`1.0` と書くと読む側で型が揺れる）。
-- ⚠ 辞書の鍵は**並べ替える**（★同じ中身なら同じ文字列になる）。
function M.json(v)
  local t = type(v)
  if v == nil then return "null" end
  if t == "boolean" then return v and "true" or "false" end
  if t == "number" then
    if v ~= v then return "null" end            -- ⚠ NaN は JSON に無い
    if v == math.floor(v) and math.abs(v) < 1e15 then
      return string.format("%d", v)
    end
    return string.format("%.6f", v)
  end
  if t == "table" then
    -- ★配列か辞書かを見分ける（⚠ Lua は同じ table）
    if #v > 0 or next(v) == nil then
      local parts = {}
      for i = 1, #v do parts[i] = M.json(v[i]) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys)
    local parts = {}
    for _, k in ipairs(keys) do
      parts[#parts + 1] = QUOTE .. esc(k) .. QUOTE .. ":" .. M.json(v[k])
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return QUOTE .. esc(v) .. QUOTE
end

--- ★★ 乱数の種を撒く（RX3-0047 / 2026-09-02）。
--
--   ⚠⚠ **撒かないと、毎回まったく同じ道を歩きます。**
--     ★Lua 5.1 の `math.random` は、`math.randomseed` を呼ばないかぎり
--     いつも同じ並びを返します。
--
--   ⚠ 2026-09-02 に実測しました（TOWN RUN を 2 回）:
--
--   ```text
--   run_002   歩いた 47 / 成功 35 / 升 23 / (8,18) → (13,26)
--   run_003   歩いた 47 / 成功 35 / 升 23 / (8,18) → (13,26)
--   diff run.jsonl → ★1 行も違わない
--   ```
--
--   ⚠⚠ 「ランダムウォークで探索する」道具が、★**同じ 23 升しか見ません**。
--     種を撒いたら 88〜92 升になりました（⚠ 4 倍）。
--
--   @param want ★使いたい種（⚠ nil なら時刻から作る）
--   @return     ★実際に使った種（⚠ **記録に残すため**返します）
function M.new_seed(want)
  local seed = tonumber(want)
  if seed == nil then
    -- ⚠ 秒だけだと、同じ秒に 2 回始めたとき同じ種になる
    local ms = 0
    pcall(function() ms = math.floor((os.clock() * 1000) % 1000) end)
    seed = (os.time() * 1000 + ms) % 2147483647
  end
  math.randomseed(seed)
  -- ⚠ Lua 5.1 は撒いた直後の数個が種に近い（★捨てる）
  for _ = 1, 5 do math.random() end
  return seed
end

--- ★★ 呪文がかき消される場所か（RX3-0320 / 2026-09-20）★★
--
--   ⚠⚠ 依頼者「save9 呪文をかきけすダンジョンでは、呪文をつかわないようにしたい」。
--
--   ★ゲームと**同じ順**で見ます（bank0 $A12C の写し）:
--     1 `$2F & kind_mask` … 地図の中か（⚠ 世界地図・アレフガルド広域では使える）
--     2 `$8B` が表に在るか
--
--   ⚠⚠ **戦闘のフラグ（`$0568` bit4）は使いません。**
--     ★あれは戦闘の初めに写されるもので、⚠ フィールドでは前の戦闘の残りです。
--     ⚠ パルプンテでも立つので「場所」専用でもありません。
--
--   ⚠ `cfg`（`CFG.no_magic`）が無ければ **false**（★今までどおり動く）。
function M.no_magic_here(cfg, read)
  if type(cfg) ~= "table" then return false end
  local maps = cfg.maps
  if type(maps) ~= "table" then return false end
  read = read or memory.readbyte
  local ok, kind = pcall(read, 0x002F)
  if not ok or kind == nil then return false end
  local mask = cfg.kind_mask or 1
  if kind % (mask * 2) < mask then return false end      -- ★地図の中でなければ使える
  local ok2, map_no = pcall(read, 0x008B)
  if not ok2 or map_no == nil then return false end
  return maps[map_no] == true
end

return M
