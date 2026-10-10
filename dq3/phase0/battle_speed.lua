-- ★★ 戦闘の AUTO と TURBO ― 2 つの別の状態（RX3-0166 → RX3-0169 → RX3-0237 / 2026-09-13）★★
--
-- ## ★意味（依頼者「DQ3 戦闘AUTO / TURBO UI見直し仕様」/ ★正本の写し docs/requests/260913_dq3-auto-turbo-ui.md）
--
--   ```text
--   AUTO    AI に戦闘を任せる / 手動へ戻す      ★auto_v0.lua の持ち物（⚠ ここは知らせてもらう）
--   TURBO   戦闘の速さ（高速 / 通常）            ★ここ（⚠ AUTO の従属ではない）
--   A キー・AUTO ボタン   OFF → ON: AUTO ＋ TURBO を入れる / ON → OFF: AUTO ＋ TURBO を切る
--   T キー・TURBO ボタン  TURBO だけ切り替える（★AUTO は変えない / 戦闘の本体 ACTIVE でだけ）
--   ```
--
--   ★状態は 4 つ（AUTO OFF・ON × TURBO OFF・ON）。⚠ RX3-0169（2026-09-11）は AUTO OFF / TURBO ON を作らなかった
--     → ★2026-09-13 の仕様で正式な状態に戻した（「手動操作・高速」）。
--
-- ## ★遷移（★ここ 1 か所 / ⚠ 場当たりの条件を足さない）
--
--   ```text
--   A・AUTO ボタン（OFF → ON）  AUTO ON ＋ TURBO ON（★人の選択 = 速さの判断を越える / origin USER）
--   戦闘開始時「自動」           may_auto_start を通れば AUTO ON ＋ TURBO ON（★origin AUTO = 危険化で TURBO だけ戻す）
--   A・AUTO ボタン（ON → OFF）  AUTO OFF ＋ TURBO OFF
--   T・TURBO ボタン             TURBO だけ反転（★ON は origin USER / ★AUTO OFF でもよい）
--   危険化（origin AUTO だけ）   TURBO OFF（★AUTO は続く / 例: 仲間を呼んで初見の敵）/ 安全に戻っても勝手に戻さない
--   窓の色・劣勢に「なった」     AUTO 中: AUTO も TURBO も人へ返す（下の節）/ AUTO OFF・TURBO ON: 窓の色で TURBO だけ OFF
--   勝利・出口・次の戦闘・セーブの読み込み・エラー   TURBO OFF（★AUTO は auto_v0 が切る）
--   ```
--
-- ## ★★ 人へ返す（Auto を切って手で戦う画面へ）― 窓の色と劣勢（RX3-0225 / 2026-09-12・09-13）
--
--   ```text
--   窓の色 $27（オレンジ）  死んでいる人がいる          → 印 take_manual → auto_v0 が Auto を切る（source=DANGER）
--   窓の色 $2A（緑）        生きている人の HP < 最大/4   → 同じ
--   窓の色 $21（夜）/ $30（白）                         → 返さない
--   AI の戦況が劣勢に**なった**（この Auto の前の作戦は劣勢でなかった）→ 同じ（理由「劣勢」/ Turbo もその場で OFF）
--     この Auto の最初の作戦がもう劣勢   自動で入った Auto（AUTO_KNOWN）→ 返す / 人が入れた Auto（UI / A_KEY）→ 返さない
--   ```
--   ★窓の色は、人が入れた Auto（UI / A_KEY）も、自動で入った Auto（AUTO_KNOWN）も、Turbo の有無も問わない。
--   ⚠ 白へ戻っても Auto を入れ直さない。
--   ★2026-09-13 依頼者「３割は廃止、劣勢はターボ＆オートを止める形にしたい」→ ⚠ 独自の 30%（danger_hp）は無い。
--   ★`judge` は**速さ**だけの判断（既知の敵・ボス候補・戦況）。⚠ 死者・HP は見ない（★窓の色が受け持つ）。
--
-- ## ★「元の速さ」
--
--   ★速くするのは `speed.want(true)`（機能の要求）だけ。⚠ 人の T はもう**Turbo の意味**なので、
--   速度のスイッチを直接は触らない（RX3-0169）。⚠ 管理画面の 2 倍速は Python が送り直す。
--
--   ⚠ ここはゲームを覗きません（★判断に要るものは `ctx` で受け取る / DQ2 と同じ作法）。

local BattleSpeed = {}

BattleSpeed.MANUAL = "MANUAL"            --: ★この Auto では通常の速さ（⚠ UI の AUTO_NORMAL）
BattleSpeed.AUTO_FAST = "AUTO_FAST"      --: ★この Auto では高速（⚠ UI の AUTO_TURBO）

--: ★速くしてよい戦況（⚠ AI の語 / 設定 `auto_battle.fast.situations` で変えられる）
--   ★均衡も（2026-09-12 依頼者「戦況が均衡でもターボして良い。劣勢になったら手動にするで良い」/ RX3-0199）
BattleSpeed.DEFAULT_SITUATIONS = {mop = true, advantage = true, even = true}
-- ⚠ `DEFAULT_DANGER_HP`（HP 30% を割ったら速くしない）は 2026-09-13 に外した（依頼者「３割は廃止」）。
--   ★HP は窓の色（緑 = HP 1/4 未満）で Auto ごと止まる。⚠ AI 自身の `danger_hp`（TUNING）は別物で、そのまま

--: ★★ 劣勢（AI の語 disadvantage）に**なった**ら Auto も Turbo も止める（2026-09-13 依頼者 / `watch_situation`）
BattleSpeed.DISADVANTAGE = "disadvantage"
BattleSpeed.WHY_DISADVANTAGE = "劣勢"

--: ★★ 膠着（RX3-0327 §11 / 2026-09-21 依頼者「最短撃破 v1 実装修正指示」）。
--
--   ⚠⚠ 依頼者「戦闘を終わらせられない状態で Auto＋Turbo が永久継続することを防ぐ」。
--   ★安全側の原則: **AI が「勝てない」と断定して勝手に逃げるより、まず Auto を停止して人間へ返す**。
--
--   ```text
--   STALL_MIN_TURNS  これ以上のターン経過（★短い戦いでは鳴らさない）
--   STALL_WINDOW     直近この数ターンで、敵 HP 合計が**減っていない**
--   ```
--
--   ⚠ どちらか片方では鳴らしません（★依頼者 §11-2「sit.win > W だけでは止めない」）。
--     理由: ★物理の見込みの式は攻略情報ベースで粗く（`damage_estimate.lua`）、
--     ⚠ 「あと 700 ターン」は**推定が外れているだけ**のことがあります。
--   → ★見るのは**実際に減ったか**です（⚠ 推定ではなく観測）。
--
--   ⚠⚠ 既存の `remember_hits`（`pipeline.lua`）は流用できません。
--     ★あれは「物理だけの群」しか測らず、攻撃呪文が 1 発でも混ざると**永久に測りません**。
--   → ★行動の種類を問わない、`{turn, enemy_hp}` だけの軽い履歴を別に持ちます。
BattleSpeed.STALL_MIN_TURNS = 8
BattleSpeed.STALL_WINDOW = 4
BattleSpeed.WHY_STALL = "敵HPに進捗なし"

--: ★★ 窓の色（RX3-0225）。★ゲームが HP と状態から 1 本の処理（JP bank 13 $959B–$961C）で決めて置く 1 バイト。
--   ★番地と色は生成物 `CFG.window_color`（profile の runtime.window_color が正本）で上書きされる。
--   ⚠ ここは RAM を読まない（★読むのは auto_v0 / 番地は `F.window.address` で渡す）
BattleSpeed.WINDOW_COLOR_ADDR = 0x06E0
BattleSpeed.WINDOW_DEAD = 0x27       --: ★オレンジ（死んでいる人がいる）
BattleSpeed.WINDOW_LOW_HP = 0x2A     --: ★緑（生きている人の HP < floor(最大 HP / 4)）
BattleSpeed.WHY_DEAD = "窓の色 オレンジ（死者あり）"
BattleSpeed.WHY_LOW_HP = "窓の色 緑（HP 1/4 未満）"

--- ★窓の色の番地と、人へ返す色 → 理由の文（⚠ 無い欄は上の既定）。
function BattleSpeed.window_spec(cfg)
  cfg = cfg or {}
  local dead = tonumber(cfg.dead) or BattleSpeed.WINDOW_DEAD
  local low = tonumber(cfg.low_hp) or BattleSpeed.WINDOW_LOW_HP
  return {address = tonumber(cfg.address) or BattleSpeed.WINDOW_COLOR_ADDR,
          release = {[dead] = BattleSpeed.WHY_DEAD, [low] = BattleSpeed.WHY_LOW_HP}}
end

--- @param opts table `speed`（core.lua の速度）/ `say` / `cfg`（auto_battle.fast）/
---   `load_book`（★既知の敵を返す関数。`{defeated = {[id] = true}}`）/
---   `window`（★生成物の `window_color` = {address, dead, low_hp} / RX3-0225）
function BattleSpeed.new(opts)
  opts = opts or {}
  local speed = opts.speed
  local say = opts.say or function() end
  local cfg = opts.cfg or {}
  local allowed = BattleSpeed.DEFAULT_SITUATIONS
  if type(cfg.situations) == "table" then
    allowed = {}
    for _, kind in ipairs(cfg.situations) do allowed[kind] = true end
  end
  local enabled = cfg.enabled ~= false
  local window = BattleSpeed.window_spec(opts.window)

  local F = {
    battle_no = nil,
    auto = false,             --: ★いま Auto か（⚠ 持ち主は auto_v0。★知らせてもらう）
    --: ★TURBO を入れたのは誰か（RX3-0237）: USER = 人（A・T・ボタン / 判断を越える）/ AUTO = 戦闘開始時の自動 / nil = OFF
    origin = nil,
    mode = nil,               --: ★いまの速さの決め（nil = まだ / MANUAL / AUTO_FAST）
    reason = nil,
    fast = false,             --: ★いま速くしているか（★UI の Turbo 表示はこれ）
    known = nil,              --: ★戦闘の頭で写し取った既知の敵（⚠ 覚える前 / 依頼者 §29）
    last_ctx = nil,           --: ★この戦闘で最後に立てた作戦の材料（★人の Turbo・途中の Auto で使う）
    last_frame = nil,
    --: ★★ 人へ返す印（RX3-0199 → RX3-0225: ★立てるのは窓の色だけ / `F.on_window`）。
    --:   ★立てるのはここ、Auto を切るのは auto_v0（⚠ Auto の持ち主は auto_v0）。★理由の文を入れる
    take_manual = nil,
    --: ★この Auto をどこから入れたか（★AUTO_KNOWN = 人が押さずに入った / RX3-0171）
    auto_source = nil,
    --: ★この Auto で前の作戦が見た戦況（★劣勢に「なった」を見る / 2026-09-13）。
    --:   ⚠ Auto を入れた・切った・次の戦闘で nil へ（★nil = この Auto の作戦はまだ無い）
    last_situation = nil,
    --: ★窓の色の番地と、人へ返す色（RX3-0225 / ★auto_v0 がこの番地を毎フレーム読む）
    window = window,
    history = {},             --: ★診断（⚠ 直近だけ）
    --: ★画面（state.json の battle_speed）へ渡す形（⚠ 同じ表を書き換える / 毎フレーム作らない）
    view = {mode = nil, reason = nil, fast = false, battle_no = nil, auto = false, origin = nil},
  }

  local function sync()
    local v = F.view
    v.mode, v.reason, v.fast, v.battle_no, v.auto, v.origin =
      F.mode, F.reason, F.fast, F.battle_no, F.auto, F.origin
  end

  local function note(line)
    F.history[#F.history + 1] = line
    if #F.history > 20 then table.remove(F.history, 1) end
    say(line)
  end

  --- ★速くする / 戻す（⚠ どの道から来ても 1 か所。★状態が変わったときだけ記録）。
  local function set_fast(on, source, why)
    on = on == true
    if F.fast == on then return false end
    F.fast = on
    if speed ~= nil then speed.want(on) end
    note(string.format("[TURBO] %s -> %s source=%s（%s）", on and "OFF" or "ON",
                       on and "ON" or "OFF", source, tostring(why)))
    sync()
    return true
  end

  --- ★新しい戦闘。⚠⚠ 既知の敵は**ここで**写し取る（★この戦闘で覚える前 / 依頼者 §29）。
  function F.begin(battle_no)
    set_fast(false, "NEXT_BATTLE", "次の戦闘")
    F.battle_no = battle_no
    F.mode, F.reason, F.last_ctx, F.origin = nil, nil, nil, nil
    F.take_manual, F.last_situation, F.last_window = nil, nil, nil
    F.hp_log = {}                                  -- ★膠着の見張り（RX3-0327 / ⚠ 戦闘ごとに忘れる）
    F.hazard_noted = false                         -- ★途中の判断の記録（RX3-0344 / ⚠ 1 戦闘 1 行）
    local ok, book = pcall(opts.load_book or function() return nil end)
    F.known = (ok and type(book) == "table") and book or nil
    if not ok then note("[TURBO] ⚠ 既知の敵を読めない: " .. tostring(book)) end
    sync()
  end

  --- ★その敵を倒したことがあるか（⚠ 写し取った表だけを見る）。
  local function beaten(id)
    local d = F.known and F.known.defeated
    return d ~= nil and id ~= nil and d[id] == true
  end

  --- ★速くしてよいか。戻り値 `ok, 理由`（★順番が仕様そのもの / DQ2 と同じ）。
  --
  --   ⚠ 2026-09-13 から「死者あり」「HP 危険（30%）」は見ない（依頼者「３割は廃止」）。
  --     ★死者・HP 1/4 未満は窓の色（オレンジ・緑）が Auto ごと止める（`F.on_window`）→ ★ここで二重に数えない。
  --     ★劣勢は下の `allowed` で速くしない ＋ 劣勢に「なった」ら Auto ごと止める（`watch_situation`）
  function F.judge(ctx)
    ctx = ctx or {}
    if not enabled then return false, "高速化オフ（設定）" end
    if not ctx.auto then return false, "AUTO でない" end
    if not ctx.ai_ok then return false, "AI の判断が無い" end
    if F.known == nil then return false, "既知の敵が分からない" end
    local ids = ctx.enemy_ids or {}
    if #ids == 0 then return false, "敵が分からない" end
    for _, id in ipairs(ids) do
      -- ⚠ 会っただけ（倒していない）も初見と同じに扱う（★前に逃げた相手 / DQ2 の「警戒中」）
      if not beaten(id) then return false, "初見の敵" end
    end
    if ctx.special then return false, "ボス・イベント戦の候補" end
    if ctx.situation == nil then return false, "戦況が分からない" end
    if not allowed[ctx.situation] then return false, "戦況 " .. tostring(ctx.situation) end
    return true, "既知・安全"
  end

  --- ★★ 人が A を押さなくても Auto に入ってよいか（2026-09-11 依頼者「勝利済のモンスターなら自動でオート・ターボ」）。
  --
  --   ★見るもの: 敵が全員「倒したことのある種類」/ ボス・イベント戦の候補でない /
  --     ★窓の色がオレンジ（$27 死者あり）でも緑（$2A HP 1/4 未満）でもない（RX3-0225）。
  --   ⚠ 以前（RX3-0171〜RX3-0219）は「死者なし / HP が danger_hp（30%）以上」を RetroUX が数えていた。
  --     ★入った直後に窓の色で切れる、を作らないよう、入る条件も同じ色で決める。
  --   ⚠ 窓の色が読めなければ入らない（★安全側）。
  --   ⚠ 戦況（消化戦・優勢）はここでは見ない（★AI の作戦は Auto が入ってから立つ）。
  --     → ★Turbo はこれまでどおり、入ったあとの `judge`（戦況も見る）で決まる。
  --     ★最初の作戦がもう劣勢なら、そこで人へ返す（★自動で入った Auto だけ / `watch_situation` / 2026-09-13）
  --   ⚠ Turbo の設定（`turbo_with_auto`）とは関係なく決める（★速さではなく「任せるか」の判断）。
  --   ctx: {enemy_ids = {…}, special = bool, window_color = 0x30 など, party = {{hp, hp_max}, …}}
  function F.may_auto_start(ctx)
    ctx = ctx or {}
    if F.known == nil then return false, "既知の敵が分からない" end
    local ids = ctx.enemy_ids or {}
    if #ids == 0 then return false, "敵が分からない" end
    for _, id in ipairs(ids) do
      if not beaten(id) then return false, "初見の敵" end
    end
    if ctx.special then return false, "ボス・イベント戦の候補" end
    if ctx.window_color == nil then return false, "窓の色が分からない" end
    local held = window.release[ctx.window_color]
    if held ~= nil then return false, held end
    local members = 0
    for _, m in ipairs(ctx.party or {}) do
      if (tonumber(m.hp_max) or 0) > 0 then members = members + 1 end
    end
    if members == 0 then return false, "味方が分からない" end
    return true, "倒したことのある敵だけ"
  end

  -- ⚠⚠ RX3-0219 の `is_danger`（劣勢 / 死者あり / HP < danger_hp で人へ返す）は RX3-0225 で外した。
  --   ★人へ返すのはゲームの窓の色（`F.on_window`）と、劣勢に「なった」とき（`watch_situation` / 2026-09-13）。
  --   ⚠ 死者・独自の 30% では返さない（★窓の色が受け持つ）

  --- ★TURBO を決める（⚠ どの道から来ても 1 か所 / RX3-0237）。`origin` = USER・AUTO（OFF なら捨てる）。
  local function turbo(on, origin, source, why)
    F.origin = on and origin or nil
    F.mode, F.reason = on and BattleSpeed.AUTO_FAST or BattleSpeed.MANUAL, why
    set_fast(on, source, why)
    sync()
    return F.fast
  end

  --- ★Auto を入れた（★TURBO も入れる / 仕様 §3・§5）。
  --   `source` … A_KEY / UI（人）→ origin USER（★速さの判断を越える）/ AUTO_KNOWN（戦闘開始時「自動」）→ origin AUTO
  --     （★入る前に may_auto_start を通っている / 入ったあとは危険化で TURBO だけ戻す）。
  --   `color` … ★Auto を入れたときの窓の色（★RX3-0225: 窓の色は「変わった瞬間」で見るので、ここが最初の色）。
  --     ⚠ nil（分からない）は「危なくない色」とみなす（★その後に緑・オレンジを見たら返す）
  --   ⚠ 設定で高速化を切ってあれば（`turbo_with_auto: false`）TURBO は入れない（★T では速くできる）
  function F.auto_on(battle_no, source, color)
    if battle_no ~= nil and battle_no ~= F.battle_no then F.begin(battle_no) end
    F.auto, F.auto_source, F.take_manual = true, source, nil
    F.last_window, F.last_situation = color, nil
    if not enabled then
      turbo(false, nil, source, "高速化オフ（設定）")
    elseif source == "AUTO_KNOWN" then
      turbo(true, "AUTO", source, "戦闘開始時 自動（倒したことのある敵だけ）")
    else
      turbo(true, "USER", source, "AUTO と一緒に")
    end
  end

  --- ★Auto を切った（★TURBO も OFF / 仕様 §3「AUTO終了 = AUTO＋TURBO終了」）。
  function F.auto_off(source)
    F.auto, F.take_manual, F.last_window, F.last_situation = false, nil, nil, nil
    turbo(false, nil, source or "AUTO_OFF", "Auto を切った")
    F.mode = nil
    sync()
  end

  --- ★★ 窓の色を受け取る（★auto_v0 が Auto 中に毎フレーム呼ぶ / RX3-0225）。戻り値: 人へ返す理由（nil = 返さない）。
  --
  --   ★オレンジ（$27）か緑（$2A）に**変わった瞬間**に印 `take_manual` を立てる → ★auto_v0 の frame が Auto を切る（source=DANGER）。
  --     ★依頼者「緑に画面が**なったら**止める」。⚠ 前のフレームと同じ色なら返さない
  --     （★緑のまま人が A で入れた Auto は続く / 緑 → オレンジ（死者が出た）・白 → 緑 では返す）。
  --     ⚠ 以前の作り（色そのもの）では、緑のまま人が入れた Auto が**そのフレームで切れた**（★人の選択を戻す）。
  --   ★人が入れた Auto も自動で入った Auto も、Turbo の有無も問わない（⚠ 人が押した Turbo も Auto と一緒に切れる）。
  --   ⚠ 白（$30）・夜（$21）では何もしない。⚠ 白へ戻っても Auto を入れ直さない（★入れるのは人か、次の戦闘の頭）。
  --   ★★ AUTO OFF・TURBO ON（人が T で速くして手で戦っている / RX3-0237）: 危ない色に変わったら**速さだけ**戻す
  --     （★AUTO は入れない / 人へ返すものが無い）。⚠ AUTO も TURBO も OFF なら何もしない。
  function F.on_window(color)
    if F.take_manual ~= nil or color == nil or not (F.auto or F.fast) then return nil end
    local before = F.last_window
    F.last_window = color
    local why = window.release[color]
    if why == nil or before == color then return nil end
    if not F.auto then
      note(string.format("[TURBO] 窓の色 $%02X → 通常の速さへ（手で戦っている / %s）", color, why))
      turbo(false, nil, "DANGER", why)
      return nil
    end
    F.take_manual = why
    F.mode, F.reason = BattleSpeed.MANUAL, why
    note(string.format("[AUTO] 窓の色 $%02X → 手動へ（%s / Auto は %s / Turbo %s）", color, why,
                       tostring(F.auto_source), F.fast and "ON" or "OFF"))
    sync()
    return why
  end

  --- ★★ 劣勢に「なった」ら Auto も Turbo も止める（★作戦ごと / 2026-09-13 依頼者
  --   「劣勢はターボ＆オートを止める形にしたい」）。戻り値: 人へ返す理由（nil = 返さない）。
  --
  --   ```text
  --   この Auto の前の作戦が劣勢でない → 劣勢           返す（★人が入れた Auto も / Turbo の有無も / 人が押した Turbo も）
  --   この Auto の最初の作戦がもう劣勢  AUTO_KNOWN       返す（★人は選んでいない）
  --                                     UI / A_KEY       返さない（★人が戦況を見て入れた）→ 劣勢を抜けて、また入ったら返す
  --   劣勢のまま                                         返さない（★同じ劣勢で何度も返さない）
  --   ```
  --   ★窓の色（`F.on_window`）と同じく「変わった瞬間」で見る。★印 take_manual → auto_v0 が Auto を切る（source=DANGER）。
  --   ★Turbo はここでその場で OFF（⚠ auto_v0 が切るのは次のフレーム）。⚠ 戦況が分からない（nil）作戦は数えない
  local function watch_situation(kind)
    if not F.auto or kind == nil then return nil end
    local before = F.last_situation
    F.last_situation = kind
    if kind ~= BattleSpeed.DISADVANTAGE or before == BattleSpeed.DISADVANTAGE then return nil end
    if F.take_manual ~= nil then return nil end      -- ★もう窓の色で返すと決まっている
    if before == nil and F.auto_source ~= "AUTO_KNOWN" then return nil end
    local why = BattleSpeed.WHY_DISADVANTAGE
    F.take_manual = why
    note(string.format("[AUTO] 劣勢 → 手動へ（前の作戦 %s / Auto は %s / Turbo %s）", tostring(before),
                       tostring(F.auto_source), F.fast and "ON" or "OFF"))
    F.mode, F.reason = BattleSpeed.MANUAL, why
    set_fast(false, "DANGER", why)
    return why
  end

  --- ★★ 膠着を見張る（RX3-0327 §11）。戻り値: 返す理由 / `nil`。
  --
  --   ⚠ 2 つを **AND** で見ます: ①一定ターン経過 ②直近 K ターンで敵 HP 合計が減っていない。
  --   ★「倒せない」と断定はしません（⚠ 依頼者 §11-4「厳密な撃破不能判定までは不要」）。
  --     ここでやるのは「**進んでいない**」の検知だけです。
  local function watch_stall(turn, enemy_hp)
    if not F.auto then return nil end
    if F.take_manual ~= nil then return nil end     -- ★もう別の理由で返すと決まっている
    turn, enemy_hp = tonumber(turn), tonumber(enemy_hp)
    if turn == nil or enemy_hp == nil then return nil end   -- ⚠ 読めないときは黙って見送る

    F.hp_log = F.hp_log or {}
    -- ⚠ 同じターンで 2 度呼ばれても増やさない（★1 ターン 1 点）
    local last = F.hp_log[#F.hp_log]
    if last ~= nil and last.turn == turn then
      last.hp = enemy_hp
    else
      F.hp_log[#F.hp_log + 1] = {turn = turn, hp = enemy_hp}
    end
    while #F.hp_log > BattleSpeed.STALL_WINDOW + 1 do table.remove(F.hp_log, 1) end

    if turn < BattleSpeed.STALL_MIN_TURNS then return nil end
    if #F.hp_log <= BattleSpeed.STALL_WINDOW then return nil end
    local oldest = F.hp_log[1]
    -- ★この窓のあいだに 1 も減っていない（⚠ 増えていても同じ = 敵が回復している）
    if enemy_hp < oldest.hp then return nil end

    local why = string.format("%s（%dターン）", BattleSpeed.WHY_STALL, turn)
    F.take_manual = why
    note(string.format("[AUTO] 膠着 → 手動へ（ターン %d / 敵HP %d → %d / Turbo %s）",
                       turn, oldest.hp, enemy_hp, F.fast and "ON" or "OFF"))
    F.mode, F.reason = BattleSpeed.MANUAL, why
    set_fast(false, "DANGER", why)
    return why
  end

  --- ★★ 途中の「速くできない」判断は、**何もしません**（★記録だけ / RX3-0344 / 2026-09-21）。
  --
  --   ⚠⚠ **2026-09-21 に 2 度外しました。** ★どちらも同じ根っこです:
  --
  --   ```text
  --   ① Turbo だけ OFF  → ⚠ 依頼者「ミミックの時に、オート（ターボなし）になる」
  --   ② Auto ごと返す    → ⚠ 依頼者「次ターンから Auto がオフになる」（★save9 / 調べる）
  --   ```
  --
  --   ★根っこ: **入口で通した判断を、毎ターン蒸し返していた**こと。
  --     ⚠ `judge` の材料（戦闘の種類・敵の id・戦況）は**入口でこそ意味がある**もので、
  --     ★戦闘の途中では「読めない瞬間」がふつうにあります（⚠ 実測で 2 種類の誤発火）。
  --
  --   ★いま止めるのは、**観測できた危険だけ**です（⚠ 見立てではなく）:
  --
  --   ```text
  --   ★窓の色 $27 / $2A   死者が出た / HP が 1/4 を割った   → Auto ごと人へ返す
  --   ★劣勢に「なった」                                    → Auto ごと人へ返す
  --   ★膠着（敵 HP が減っていない）                        → Auto ごと人へ返す
  --   ⚠ judge が途中で「速くできない」と言う                → ★記録するだけ（何もしない）
  --   ```
  --
  --   ⚠ 記録は**捨てません**（★1 戦闘 1 行）。★なぜ蒸し返しが要らなかったのかの証跡です。
  local function watch_hazard(why)
    if F.hazard_noted then return nil end           -- ★1 戦闘に 1 行だけ
    F.hazard_noted = true
    note(string.format(
      "[AUTO] ⚠ 途中の判断では「%s」（★入口で通したので続けます / Auto は %s / Turbo %s）",
      why, tostring(F.auto_source), F.fast and "ON" or "OFF"))
    return nil                                      -- ⚠⚠ 速さも Auto も変えない
  end

  --- ★ターンの頭（★AI が作戦を立てた直後）。
  function F.on_plan(ctx)
    ctx = ctx or {}
    if ctx.battle_no ~= nil and ctx.battle_no ~= F.battle_no then F.begin(ctx.battle_no) end
    F.last_ctx = ctx
    if ctx.auto and not F.auto then F.auto = true end
    -- ⚠ ACTIVE で見る（★ENTERING ではまだ速くしない / 依頼者 §12）
    if ctx.phase ~= nil and ctx.phase ~= "ACTIVE" then return F.mode end
    -- ★★ 劣勢に「なった」→ Auto ごと止める（★Turbo もここで OFF / 2026-09-13）
    --   ⚠ 膠着（RX3-0327）も同じ道で返します。★劣勢を先に見ます（理由が具体的なほうを残す）
    local danger = watch_situation(ctx.situation)
    if danger == nil then danger = watch_stall(ctx.turn, ctx.enemy_hp) end
    if danger == nil and F.fast and F.origin == "AUTO" then
      local ok, why = F.judge(ctx)
      if not ok then danger = watch_hazard(why) end
    end
    sync()
    return F.mode
  end

  --- ★人が TURBO を押した（★TURBO ボタン / T キー / 仕様 §4）。★TURBO だけ切り替える（AUTO は変えない）。
  --   戻り値: いま速いか。`color` … ★押したときの窓の色（★AUTO OFF で速くしたとき、窓の色の変わり目の基準）。
  --
  --   ★2026-09-13（RX3-0237）: AUTO OFF でも効く（★「手動操作・高速」/ ⚠ RX3-0169 は何もしなかった）。
  --   ★人が押したら速くする（2026-09-11 依頼者「早くして良い」）。⚠ 安全判定（初見・均衡など）は越える。
  --   ★人が選んだ速さなので、途中の危険化では勝手に戻さない（origin USER）。結果・Auto OFF・次の戦闘では戻す
  function F.user_toggle(color)
    if F.fast then
      turbo(false, nil, "USER", "人が通常の速さを選んだ")
      return F.fast
    end
    local why = "人が選んだ（手で戦う）"
    if F.auto then
      local ctx = {}
      for k, v in pairs(F.last_ctx or {}) do ctx[k] = v end
      ctx.auto = true
      local ok, got = F.judge(ctx)
      why = ok and ("人が選んだ・" .. got) or ("人が選んだ（" .. got .. " でも速く）")
    else
      F.last_window = color
    end
    return turbo(true, "USER", "USER", why)
  end

  --- ★毎フレーム。⚠ どの終わり方でも戻し漏れを起こさない（依頼者 §17 / §23）。
  function F.tick(ctx)
    ctx = ctx or {}
    local now = ctx.frame
    -- ⚠ セーブを読むとフレーム数が巻き戻る（RX3-0167）。★この戦闘の決めごとを捨てる
    if now ~= nil and F.last_frame ~= nil and now < F.last_frame then
      set_fast(false, "LOAD", "セーブを読んだ（フレームが戻った）")
      F.mode, F.origin = nil, nil
    end
    F.last_frame = now
    if ctx.battle_no ~= nil and ctx.battle_no ~= F.battle_no and ctx.phase ~= "NONE" then
      F.begin(ctx.battle_no)
    end
    if ctx.auto ~= nil and ctx.auto ~= F.auto and not ctx.auto then
      F.auto_off("AUTO_OFF")
    end
    if not F.fast then return end
    -- ★戦闘の終わりは AUTO・TURBO とも解除（仕様 §8 / ★人が T で速くした「手動操作・高速」も）
    if ctx.phase == "RESULT" then
      F.origin = nil
      set_fast(false, "RESULT", "勝利・結果")
    elseif ctx.phase ~= "ACTIVE" then
      F.origin = nil
      set_fast(false, "EXIT", "戦闘の終わり（" .. tostring(ctx.phase) .. "）")
    end
  end

  --- ★外から止める（★エラー・終了・セーブの読み込み）。
  function F.abort(why, source)
    F.auto, F.origin, F.mode = false, nil, nil
    set_fast(false, source or "ERROR", why or "中断")
    sync()
  end

  function F.status()
    sync()
    return F.view
  end

  return F
end

return BattleSpeed
