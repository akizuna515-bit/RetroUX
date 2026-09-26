-- 戦闘 AI v1 の入口（RX3-0126 / 2026-09-08）— ★指示書 §1 の流れをそのまま並べる。
--
-- ```text
-- 制約（MP）→ 作戦 → 戦況 → 必要な役割 → キャラへ割当 → 抽象コマンド → 実コマンド
--   catalog     ctx    situation   roles.needed   roles.assign   actions.concrete
-- ```
--
-- ## ★使い方（`auto_v0.lua` から）
--
--   local AI = dofile(root .. "/dq3/phase0/ai/pipeline.lua")
--   local ai = AI.new(root)            -- ★生成物と DQ2 の部品を読む（⚠ 無ければ ai.ok = false）
--   ai:reload()                        -- ★画面で設定を変えたとき
--   local plan = ai:plan_turn(ctx)     -- ★ターンの最初の手番で 1 回
--   plan.actions[slot]                 -- ★その人の実コマンド
--   plan.lines                         -- ★理由の記録（1 行ずつ）
--
-- ## ⚠ ここは RAM も画面も読まない
--
--   ★`ctx` は呼ぶ側が組む（★実機では `auto_v0.lua`、検査では足場）。
--   だから A〜H の場面を**実機なしで**通せる。

local Pipeline = {}
Pipeline.__index = Pipeline

--: ★生成物の場所（⚠ `RETROUX_ROOT` からの相対）
Pipeline.GENERATED = "/work/generated/dq3_ai.lua"

local function load_modules(root)
  local here = root .. "/dq3/phase0/ai/"
  local dq2 = root .. "/retroux/emulator/fceux/"
  local mods = {
    catalog = dofile(here .. "catalog.lua"),
    situation = dofile(here .. "situation.lua"),
    roles = dofile(here .. "roles.lua"),
    actions = dofile(here .. "actions.lua"),
    -- ★Enemy Action Model v1（RX3-0359 / ⚠ **shadow**。★判断は 1 つも読まない）
    enemy_model = dofile(here .. "enemy_model.lua"),
    -- ★DQ2 から継ぐ（⚠ `retroux/` は読むだけ / RX3-0011）
    damage = dofile(dq2 .. "damage_estimate.lua"),
    support = dofile(dq2 .. "support_plan.lua"),
    types = dofile(dq2 .. "battle_types.lua"),
  }
  mods.situation.use_damage(mods.damage)
  mods.situation.use_enemy_model(mods.enemy_model)
  mods.roles.use_catalog(mods.catalog)
  mods.roles.use_actions(mods.actions)
  mods.actions.use({catalog = mods.catalog, damage = mods.damage,
                    support = mods.support, roles = mods.roles})
  return mods
end

--- ★生成物の場所。⚠ 隔離して動くときは**書き先**の下を先に見る（RX3-0128）。
function Pipeline.find(root)
  local write_root = os.getenv("RETROUX_WRITE_ROOT")
  if write_root ~= nil and write_root ~= "" then
    write_root = (write_root:gsub(string.char(92), "/"):gsub("/$", ""))
    local candidate = write_root .. Pipeline.GENERATED
    local fh = io.open(candidate, "r")
    if fh ~= nil then fh:close(); return candidate end
  end
  return root .. Pipeline.GENERATED
end

--- ★作る。`opts.path` で生成物の場所を差し替えられる（★検査用）。
function Pipeline.new(root, opts)
  opts = opts or {}
  local self = setmetatable({root = root, path = opts.path or Pipeline.find(root),
                             say = opts.say or function() end, used = {}, last_turn = nil},
                            Pipeline)
  self.mods = load_modules(root)
  self:reload()
  return self
end

--- ★生成物を読み直す（★`ai_reload`）。⚠ 読めなければ `ok = false` のまま。
function Pipeline:reload()
  local cat, err = self.mods.catalog.load(self.path)
  self.cat = cat
  self.ok = cat ~= nil
  if cat == nil then
    self.error = tostring(err)
    self.say("AI ⚠ 表を読めない: " .. self.error)
  else
    -- ⚠ revision はミリ秒の時刻（13 桁）。`tostring` だと 1.78e+12 になるので整数で
    self.say(string.format("AI 表を読んだ revision=%.0f strategy=%s display_strategy=%s mp=%s",
      tonumber(cat.revision) or 0, tostring(cat.strategy),
      tostring(Pipeline.STRATEGY_LABEL[cat.strategy] or cat.strategy), tostring(cat.mp_policy)))
  end
  return self.ok
end

--- ★戦闘が終わったら呼ぶ（★支援の「1 戦闘に 1 度」を忘れる）。
function Pipeline:reset_battle()
  self.used = {}
  self.last_turn = nil
  self.hits, self.observed = nil, nil          -- ★RX3-0226（★実測は 1 戦闘の中だけ）
end

----------------------------------------------------------------------
-- ★★ 実測の比（RX3-0226 / 2026-09-13）— 表と RAM の守備力でも説明できない「通らない」の保険
----------------------------------------------------------------------
--
--   ```text
--   ターン N   物理**だけ**が向かった群ごとに、見込みの合計（★群の残り HP で頭打ち）と残り HP を控える
--   ターン N+1 その群の減り ÷ 見込み = 比。比 < observed_ratio（0.5）なら、物理の見込みを × 比（下限 0.05）
--   ```
--
--   ⚠ 攻撃呪文・道具の攻撃が向かった群は数えない（★物理の分だけを見る）。敵全体へ撃ったターンは測らない。
--   ⚠ 群の並びと種類が同じで、生きている数が増えていない群だけ（★仲間を呼んだ群は混ぜない）。
--   ⚠ 1 体ずつの HP を RAM で読めていない群・見込みが observed_min_expect（8）未満のターンは測らない。
--   ★見込みは「前の実測の比を外した値」で控える（⚠ 掛けたままだと、比が次のターンで 1 に戻って揺れる）。
--   ★比は次に測れるターンまで持つ（⚠ 呪文に切り替えたターンで忘れると、物理に戻って揺れる）。

local function spell_hits_enemies(cat, a)
  if a.kind == "item" then return a.item == "attack" end
  if a.kind ~= "spell" then return false end
  if a.target ~= nil and a.target.ally ~= nil then return false end
  local s = cat and cat.spells and cat.spells[a.spell] or nil
  if s == nil then return true end                     -- ⚠ 分からなければ「当たった」側（★測らない）
  local tgt = tostring(s.target or "")
  return s.kind == "attack" or tgt:find("enemy", 1, true) ~= nil
end

--- ★このターンに物理だけが向かった群を控える（★`plan_turn` の終わりで 1 回）。
function Pipeline:remember_hits(ctx, sit, actions)
  self.hits = nil
  local obs = tonumber(sit.observed_scale) or 1.0
  if obs <= 0 then obs = 1.0 end
  local phys, touched, all = {}, {}, false
  for _, a in pairs(actions) do
    local gi = a.target and a.target.group or nil
    if a.kind == "attack" and gi ~= nil and a.phys_dmg ~= nil then
      phys[gi] = (phys[gi] or 0) + a.phys_dmg / obs
    elseif spell_hits_enemies(self.cat, a) then
      if gi ~= nil then touched[gi] = true else all = true end
    end
  end
  if all then return end
  local rec = {turn = ctx.turn, groups = {}}
  for _, g in ipairs(sit.groups or {}) do
    local e = phys[g.index]
    if e ~= nil and e > 0 and not touched[g.index] and g.measured and g.alive_n > 0 then
      rec.groups[g.index] = {id = g.id, hp = g.hp_sum, alive_n = g.alive_n, expect = math.min(e, g.hp_sum)}
    end
  end
  self.hits = rec
end

--- ★前のターンに控えた群の減りから、実測の比を出す。戻り値: {scale, ratio, dealt, expect} / nil。
function Pipeline:observe(ctx, cat)
  local rec = self.hits
  if rec == nil or ctx.turn == nil or rec.turn == nil or ctx.turn ~= rec.turn + 1 then
    return self.observed
  end
  local now = self.mods.situation.groups(ctx.enemies, cat)
  local dealt, expect = 0, 0
  for i, r in pairs(rec.groups) do
    local g = now[i]
    if g ~= nil and g.id == r.id and g.measured and g.alive_n <= r.alive_n then
      dealt = dealt + math.max(r.hp - g.hp_sum, 0)
      expect = expect + r.expect
    end
  end
  local t = ctx.tuning or (cat and cat.tuning) or {}
  if expect <= 0 or expect < (tonumber(t.observed_min_expect) or 8) then return self.observed end
  local ratio = dealt / expect
  if ratio < (tonumber(t.observed_ratio) or 0.5) then
    self.observed = {scale = math.max(ratio, 0.05), ratio = ratio, dealt = dealt, expect = expect,
                     turn = rec.turn}
  else
    self.observed = nil                               -- ★見込みどおり通った（★補正をやめる）
  end
  return self.observed
end

local ROLE_LABEL = {physical = "物理", magic = "魔法", support = "支援", heal = "ヒール", defend = "防御"}
--: ★作戦の画面の名前（⚠ 正本は `dq3/battle_ai/settings.py` の STRATEGY_LABELS / 内部の語 leveling は保つ）。
--  ★RX3-0198（2026-09-12 依頼者）: 「レベル上げ」→「速攻」
--  ★RX3-0327（2026-09-20 依頼者）: 「速攻」→「最短撃破」
--  ⚠⚠ ここは**写し**です。★Python を直したら必ず同時に直してください
--    （`tests/test_dq3_battle_ai_labels.py` が突き合わせます）。
local STRATEGY_LABEL = {leveling = "最短撃破", economy = "リソース節約", survival = "生存優先"}
Pipeline.STRATEGY_LABEL = STRATEGY_LABEL
--: ★MP 制約の画面の名前（⚠ 正本は `dq3/battle_ai/settings.py` の MP_LABELS）。
--  ⚠⚠ 2026-09-21（RX3-0333）: `save` が **「温存」のまま**で、★画面の「半分程度残す」と
--    ずれていました。⚠ 突き合わせる検査が無かったためです（★いまは
--    `tests/test_dq3_battle_ai_labels.py` が止めます）。
--  ⚠ 過去のログに残る「温存」は**書き換えません**。★読む側（`coverage.py`）が寄せます。
local MP_LABEL = {auto = "おまかせ", save = "半分程度残す", forbid = "使用禁止"}
local KIND_LABEL = {mop = "消化戦", advantage = "優勢", even = "均衡", disadvantage = "劣勢"}

local function describe(action)
  local s = action.kind
  if action.kind == "spell" then s = "spell:" .. tostring(action.name or action.spell) end
  -- ★道具の名前（★攻撃の道具は name を持つ / RX3-0213）。⚠ やくそうの手は name が無い
  if action.kind == "item" then s = "item:" .. tostring(action.name or "やくそう") end
  local t = action.target
  if t ~= nil then
    if t.group then s = s .. "→g" .. t.group end
    if t.ally then s = s .. "→" .. t.ally end
  end
  return s
end

--- ★1 ターンぶんの判断。
--
--   `ctx` = { turn, party = {member...}, enemies = {group...} }
--   member = { slot, index, hp, hp_max, mp, mp_max, attack, defense, spells = {8 bytes},
--              class_id, herbs }
--   ★作戦・MP 制約・役割・閾値は生成物から入れる（⚠ ctx にあればそちらを優先 = 検査用）
function Pipeline:plan_turn(ctx)
  local M = self.mods
  local cat = self.cat
  if cat == nil then return nil end
  ctx.strategy = ctx.strategy or cat.strategy
  ctx.mp_policy = ctx.mp_policy or cat.mp_policy
  ctx.roles = ctx.roles or cat.roles
  ctx.tuning = ctx.tuning or cat.tuning
  ctx.items = ctx.items or cat.items
  for i, m in ipairs(ctx.party or {}) do m.index = m.index or i end

  -- ★★ このターンの「もう使った」を忘れる（RX3-0429 / P-1 / 2026-09-24）。
  --
  --   ⚠⚠ ここまで `self.used` は **`reset_battle()` でしか空になりませんでした**。
  --     ★`used.party_heal` は「全体回復をもう使ったか」なので、
  --     ⚠ **1 戦闘に 1 回**しか けんじゃのいし が出ない状態でした。
  --
  --     ```text
  --     turn 1  けんじゃのいし（全体 140 / MP 0）
  --     turn 2  ⚠⚠ ベホイミ（単体 80 / MP 5）  reason=party_heal_used_this_turn
  --     ```
  --
  --   ★ログの語も `..._this_turn` で、⚠ **名前のほうが正しかった**（実装が追いついていない）。
  --   ⚠ 作戦は問いません（★リソース節約でも同じ取りこぼしが出ていた / 依頼者の補足）。
  --
  --   ⚠ 同じターンで組み直したときは**忘れません**（★1 ターンに 2 回は使わせない）。
  if self.last_turn == nil or ctx.turn ~= self.last_turn then
    self.used = {}
  end

  local plan = M.types.party_plan({turn = ctx.turn})
  -- ★RX3-0226: 前のターンの物理が見込みどおり通ったか（★通っていなければ物理の見込みを下げる）
  ctx._observed = self:observe(ctx, cat)
  local sit = M.situation.assess(ctx, cat)
  local caps = {}
  -- ⚠ 作戦も渡す（★「使わせない呪文」は作戦ごと / RX3-0370）
  for _, m in ipairs(ctx.party or {}) do
    caps[m.slot] = M.roles.caps(m, cat, ctx.mp_policy, ctx.strategy)
  end
  -- ⚠⚠ **`_caps` と `_plan` を先に入れます**（RX3-0365）。
  --   ★リソース節約 v2 の `net_mp_cost` は「回復 1 手番ぶんの HP と MP」を
  --     `ctx._caps` から引きます。⚠ 後に入れると **nil のまま**で、
  --     ★差し引きが 0 になり、**v2 が黙って効きません**（`RX3-0356` と同じ型）。
  ctx._caps, ctx._plan = caps, plan
  -- ★★ 攻撃呪文の見立て（RX3-0198）: 役割を作る前に、唱えられる人ごとに 1 回だけ。
  --   ★同じ見立てを `actions.magic` がそのまま使う（⚠ 作り直すと 1 ターンの中で説明が揺れる）
  local magic = M.actions.magic_outlook(ctx, sit, caps, cat)
  ctx._magic = magic
  ctx._drain_idle = {}      -- ★このターンにマホトラへ回した人（RX3-0260 / ★2 人目は 1 人目も休ませて見る）
  local needs, defend_slots, notes = M.roles.needed(ctx, sit, caps, plan, magic)
  local assigned, unfilled = M.roles.assign(ctx, sit, needs, caps, defend_slots, magic)
  -- ★★ 割り当てを**手を作る側へ渡す**（RX3-0412 / 依頼者 §29 の producer）。
  --
  --   ⚠⚠ `Actions.survival_wait_defend` が「**誰が自分を回復するのか**」を見ます。
  --     ★`plan.reserved_healing` は**量**しか持たず、⚠ 「誰から誰へ」が分かりません。
  --   ⚠ ここを書き忘れると、★consumer 側は静かに `no_heal_reserved` になり、
  --     **実機で 1 度も防御しません**（`Enemy Action Model` で踏んだ形 / 依頼者 §29）。
  --     → ⚠ 検査で**両側**を縛っています（`WH-X`）。
  ctx._assigned = assigned

  local actions, lines = {}, {}
  lines[#lines + 1] = string.format("AI turn=%d 戦況=%s win=%s lose=%s 作戦=%s MP=%s / %s",
    ctx.turn or 0, KIND_LABEL[sit.kind] or sit.kind,
    sit.win and string.format("%.1f", sit.win) or "?",
    sit.lose and string.format("%.1f", sit.lose) or "?",
    STRATEGY_LABEL[ctx.strategy] or tostring(ctx.strategy),
    MP_LABEL[ctx.mp_policy] or tostring(ctx.mp_policy), sit.why or "")
  -- ★★ Enemy Action Model v1 の診断（RX3-0359 / ⚠ 1 群 1 行 / **shadow**）。
  --
  --   ⚠⚠ **ログの無い shadow は「動いているか分からない」**（★RX3-0356 の教訓）。
  --   ★出すだけで、⚠ この値を読む判断は 1 つもありません。
  for _, g in ipairs(sit.groups or {}) do
    if g.enemy_model_v1 ~= nil and (g.alive_n or 0) > 0 then
      -- ⚠ `g.alive_n` を渡します（★`legacy` は群の合計 / モデルは 1 体ぶん / RX3-0360）
      -- ⚠ 味方の人数も（★全体呪文の数え方 / あとで計算をやり直せる / RX3-0362）
      lines[#lines + 1] = M.enemy_model.tune(g.index, g.id, g.threat, g.enemy_model_v1,
                                             g.alive_n, #(sit.alive or {}))
    end
  end
  -- ★敵の粘り（RX3-0363 / ⚠ 粘る敵が居るときだけ 1 行）
  local endure = M.enemy_model.endure(sit)
  if endure ~= nil then lines[#lines + 1] = endure end
  -- ★★ 予測の記録（RX3-0371 / ⚠ **敵が動く前**に出す / 機械で読む）。
  --   ⚠⚠ 鍵にフレーム数を使いません（★セーブを読むと戻る / `RX3-0167`）。
  --     → ★`battle` / `turn` / `group` の 3 つ。
  -- ⚠⚠ 場に居る**群の数**と**敵の総数**を数えます（RX3-0372）。
  --   ★群が 2 つ以上のターンは、⚠ 実測をどの敵に付けるか決められません
  --     （★実際に 2026-09-22 の実測で、ブレスを持たない敵に「ブレス 15%」が付いた）。
  local groups_n, field_n = 0, 0
  for _, g in ipairs(sit.groups or {}) do
    if (g.alive_n or 0) > 0 then
      groups_n = groups_n + 1
      field_n = field_n + g.alive_n
    end
  end
  for _, g in ipairs(sit.groups or {}) do
    if g.enemy_model_v1 ~= nil and (g.alive_n or 0) > 0 then
      local got = M.enemy_model.predict_line(ctx.battle_no, ctx.turn, g,
        g.enemy_model_v1, g.alive_n, #(sit.alive or {}), g.threat, groups_n, field_n)
      if got ~= nil then lines[#lines + 1] = got end
    end
  end
  local need_words = {}
  for _, n in ipairs(needs) do
    need_words[#need_words + 1] = (ROLE_LABEL[n.role] or n.role)
      .. (n.job == "revive" and "(蘇生)" or "") .. (n.target and ("→" .. n.target) or "")
  end
  lines[#lines + 1] = "AI 必要=" .. table.concat(need_words, " ")
    .. (#notes > 0 and (" / " .. table.concat(notes, " / ")) or "")
  -- ★動けない人が居れば 1 行（RX3-0135）。⚠ 未観測のときは何も出さない
  local stuck = {}
  for _, m in ipairs(sit.alive) do
    local why = M.roles.blocked_by(m)
    if why ~= nil then stuck[#stuck + 1] = m.slot .. "=" .. why end
  end
  if #stuck > 0 then
    lines[#lines + 1] = "AI ⚠ 動けない: " .. table.concat(stuck, " ") .. "（★役割を振らない）"
  end
  for _, n in ipairs(unfilled) do
    lines[#lines + 1] = string.format("AI ⚠ %s ができる人が居ない（%s）",
      ROLE_LABEL[n.role] or n.role, n.why or "")
  end
  -- ★★ 開発用の判断ログ（RX3-0198 / 依頼者の指示書「判断理由」）— `AI tune …` の行。
  --   ★内部の語（strategy=leveling）と画面の名前（display_strategy=速攻）を両方書く。
  --   ⚠ `AI pN 役割=` の行とは別の形（★`coverage.py` の読み方を壊さない）
  local head = string.format("strategy=%s display_strategy=%s", tostring(ctx.strategy),
    tostring(STRATEGY_LABEL[ctx.strategy] or ctx.strategy))
  if magic.forbid then
    lines[#lines + 1] = "AI tune " .. head
      .. " mp_policy=forbid magic_candidate=none decision=skip reason=mp_forbid"
  end
  -- ★★ 物理の見込みを補正したとき（RX3-0226）: 何で補正したか ＋ 補正後の数字。
  --   ⚠ `AI tune pN …` ではない（★`coverage.py` の魔法の判断の読み方に混ざらない）
  if sit.phys_adjusted then
    lines[#lines + 1] = string.format("AI tune %s estimate=physical_adjusted %s our_dpt=%.1f win=%s kind=%s",
      head, table.concat(sit.phys_notes or {}, " "), sit.our_dpt or 0,
      sit.win and string.format("%.1f", sit.win) or "?", tostring(sit.kind))
  end
  for _, m in ipairs(sit.alive) do
    local a = assigned[m.slot]
    local action = M.actions.concrete(m, caps[m.slot], a, ctx, sit, plan, cat, self.used)
    action.slot = m.slot
    action.role = a.role
    actions[m.slot] = action
    lines[#lines + 1] = string.format("AI %s 役割=%s(%s) do=%s / %s", m.slot,
      ROLE_LABEL[a.role] or a.role, a.tier or "?", describe(action), action.why or a.why or "")
    -- ★魔法の役でない人の見立ても残す（⚠ 「なぜ魔術師が撃たなかったか」を後で追えるように）
    local ev = magic.by_slot[m.slot]
    if ev ~= nil and a.role ~= "magic" then
      local reason = ev.reason
      if ev.decision == "use" then reason = "assigned_other_role:" .. tostring(a.role) end
      ev.phys_rounds = magic.phys_rounds
      lines[#lines + 1] = "AI tune " .. m.slot .. " " .. head .. " "
        .. M.actions.magic_tune(ev, "skip", reason)
    end
    for _, t in ipairs(action.tune or {}) do
      lines[#lines + 1] = "AI tune " .. m.slot .. " " .. head .. " " .. t
    end
  end
  for _, line in ipairs(lines) do self.say(line) end
  self:remember_hits(ctx, sit, actions)        -- ★RX3-0226（★次のターンに減りと比べる）
  self.last_turn = ctx.turn
  return {turn = ctx.turn, situation = sit, needs = needs, assigned = assigned,
          actions = actions, lines = lines, caps = caps, magic = magic,
          strategy = ctx.strategy, mp_policy = ctx.mp_policy}
end

return Pipeline
