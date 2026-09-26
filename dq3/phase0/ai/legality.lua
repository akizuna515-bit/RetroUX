-- 実行の直前に「まだ押せるか」だけ見る（RX3-0134 / 2026-09-09）— ★指示書 v1.1 §5。
--
-- ## ⚠⚠ ここは**再計画しません**
--
--   計画はターンの最初に 1 回だけ作ります（★理由の説明が安定する / 方針が揺れない）。
--   ⚠ ですがターンの途中で戦況は動きます。
--
--   ```text
--   計画時  p3 → ホイミ → p2
--   実行時  p2 は既に倒れている   ⚠ 古い計画のまま押してしまう
--   ```
--
--   → ★戦況分類も作戦も**見直しません**。⚠ 「いまの計画をまだ実行できるか」だけです。
--
-- ## ★見るもの（§5）
--
--   ```text
--   術者が生きている / 行動できる      ⚠ 駄目 → ぼうぎょ
--   MP がまだ足りる                    ★足りない → 安いほうへ / 道具 / ぼうぎょ
--   回復の相手がまだ有効               ★倒れた・満タン → 別の怪我人へ
--   蘇生の相手がまだ倒れている         ★生き返っていたら別の死者へ
--   敵の群がまだ居る                   ★消えていたら別の群へ
--   道具がまだ残っている               ★無ければ 呪文 / ぼうぎょ
--   ```
--
-- ## ⚠ 「分からない」は止めない
--
--   ★状態異常が未観測（`nil`）のときは、⚠ **行動できる**として通します
--   （★回復できる人を憶測で外すほうが危ない / 指示書 §12-2）。
--
-- ⚠ ここも RAM を読みません。★呼ぶ側が「いまの `party` と `enemies`」を渡します。

local Legality = {}

--: ★安全な逃げ道（⚠ 窓に ぼうぎょ が無ければ `auto_v0` が たたかう へ落とす）
local FALLBACK = "defend"

local function defend_action(why)
  return {kind = FALLBACK, target = nil, fallback = "attack", why = why}
end

--- ★その人が行動できるか。⚠ 未観測（nil）は **true**（★憶測で外さない）。
function Legality.can_act(member)
  if member == nil then return false, "居ない" end
  if (member.hp or 0) <= 0 then return false, "倒れている" end
  local st = member.status
  if st == nil then return true, nil end
  if st.paralyzed == true then return false, "麻痺" end
  if st.asleep == true then return false, "眠り" end
  return true, nil
end

local function by_slot(party, slot)
  for _, m in ipairs(party or {}) do
    if m.slot == slot then return m end
  end
  return nil
end

--- ★いま怪我をしている生存者（★HP の比が低い順）。
local function wounded(party)
  local out = {}
  for _, m in ipairs(party or {}) do
    if (m.hp or 0) > 0 and (m.hp_max or 0) > 0 and m.hp < m.hp_max then
      out[#out + 1] = m
    end
  end
  table.sort(out, function(a, b)
    return (a.hp / a.hp_max) < (b.hp / b.hp_max)
  end)
  return out
end

local function fallen(party)
  local out = {}
  for _, m in ipairs(party or {}) do
    if (m.hp or 0) <= 0 and (m.hp_max or 0) > 0 then out[#out + 1] = m end
  end
  return out
end

--- ★まだ生きている群（⚠ `hp` が届いていなければ「居る」と見る）。
function Legality.live_groups(enemies)
  local out = {}
  for i, g in ipairs(enemies or {}) do
    local n = 0
    if g.hp ~= nil and #g.hp > 0 then
      for k = 1, #g.hp do
        local alive = true
        if g.alive ~= nil and g.alive[k] ~= nil then alive = g.alive[k] end
        if alive and (g.hp[k] or 0) > 0 then n = n + 1 end
      end
    else
      n = g.n or 0
    end
    if n > 0 then out[#out + 1] = {index = i, alive_n = n} end
  end
  return out
end

--- ★呪文 1 つぶんの消費 MP（⚠ 表が無ければ 0 = 止めない）。
local function cost_of(spell_id, caps)
  -- ★drain … マホトラ（RX3-0260 / 消費 0）も見つける
  for _, group in ipairs({(caps or {}).heal or {}, (caps or {}).revive or {},
                          (caps or {}).attack or {}, (caps or {}).support or {}, (caps or {}).drain or {}}) do
    for _, s in ipairs(group) do
      if s.id == spell_id then return s.mp or 0, s end
    end
  end
  return nil, nil
end

--- ★同じ役目でもっと安い**呪文**（⚠ いまの MP で足りるもの）。
--
-- ## ⚠⚠ 2026-09-24（RX3-0429 / P-15・P-16）で 2 つ直しました
--
--   ```text
--   ⚠ 道具が混ざっていた    `caps.heal` は**回復の道具も入る**箱です。
--                           ★ここで道具を選ぶと `spell_action` が
--                           ⚠⚠ 道具の番号を**呪文として**押します（★別の行）。
--   ⚠ 床を見ていなかった    `mp_floor`（半分程度残す）も `forbid`（使用禁止）も
--                           ★素通りし、⚠ 上位の制約を破れました。
--   ```
--
-- @param floor ★残しておきたい MP（⚠ `nil` なら 0 = 今までどおり）
local function cheaper(list, mp, floor)
  local keep = tonumber(floor) or 0
  local best = nil
  for _, s in ipairs(list or {}) do
    -- ⚠⚠ 道具は**呪文として押せません**（★`item_id` を持つ手は除く / P-15）
    if s.item_id == nil and (s.mp or 0) <= mp and (mp - (s.mp or 0)) >= keep then
      if best == nil or (s.mp or 0) > (best.mp or 0) then best = s end
    end
  end
  return best
end

local function spell_action(s, target, why)
  return {kind = "spell", spell = s.id, spell_tiles = s.tiles, name = s.name,
          target = target, fallback = "attack", why = why}
end

----------------------------------------------------------------------
-- ★入口
----------------------------------------------------------------------

--- ★計画した 1 手を、いまの戦況で押せる形に直す。
--
--   `action` … 計画（`actions.concrete` の戻り値）
--   `now`    … `{party = {...}, enemies = {...}}`（★**いま読んだ**もの）
--   `member` … その人（★`now.party` の中の同じ人）
--   `caps`   … その人にできること（★`plan.caps[slot]`）
--
--   戻り値: `action, lines`（⚠ `lines` は理由ログ。★変えなかったときは空）
--   `ctx`    … ★作戦・MP 方針・道具（⚠ 無くても動く / RX3-0429）
function Legality.check(action, now, member, caps, ctx)
  local lines = {}
  if action == nil then return nil, lines end
  local slot = member and member.slot or action.slot or "?"
  local party = (now or {}).party or {}
  local live = Legality.live_groups((now or {}).enemies)

  local function note(text)
    lines[#lines + 1] = string.format("AI %s ⚠ 直前の見直し: %s", slot, text)
  end

  -- ① 術者（★倒れた / 動けない）
  local ok, why = Legality.can_act(member)
  if not ok then
    note(string.format("%s は行動できない（%s）→ ぼうぎょ", slot, why or "?"))
    return defend_action(string.format("行動できない（%s）", why or "?")), lines
  end

  -- ② 敵の群が消えた（★攻撃・攻撃呪文）
  local t = action.target
  if t ~= nil and t.group ~= nil then
    local found = nil
    for _, g in ipairs(live) do
      if g.index == t.group then found = g end
    end
    if found == nil then
      if #live == 0 then
        note("敵が居なくなった → ぼうぎょ")
        return defend_action("敵が居ない"), lines
      end
      local to = live[1].index
      note(string.format("g%d は全滅 → g%d へ", t.group, to))
      -- ★item_id も写す（RX3-0213 / ⚠ 落とすと ⑤ で道具の攻撃を見分けられない）
      action = {kind = action.kind, spell = action.spell, spell_tiles = action.spell_tiles,
                item = action.item, item_id = action.item_id, item_tiles = action.item_tiles,
                name = action.name,
                target = {group = to}, fallback = action.fallback or "attack",
                why = (action.why or "") .. string.format("（g%d 全滅 → g%d）", t.group, to)}
      t = action.target
    end
  end

  -- ③ 味方を選ぶ手（★回復 / 蘇生）
  if t ~= nil and t.ally ~= nil then
    local target = by_slot(party, t.ally)
    local reviving = (action.spell ~= nil and caps ~= nil and (function()
      for _, s in ipairs(caps.revive or {}) do
        if s.id == action.spell then return true end
      end
      return false
    end)())
    local bad = nil
    if target == nil then
      bad = "居ない"
    elseif reviving then
      if (target.hp or 0) > 0 then bad = "生き返っている" end
    else
      if (target.hp or 0) <= 0 then
        bad = "倒れている"
      elseif (target.hp_max or 0) > 0 and target.hp >= target.hp_max then
        bad = "満タン"
      end
    end
    if bad ~= nil then
      local pool = reviving and fallen(party) or wounded(party)
      local to = pool[1]
      if to == nil then
        note(string.format("%s は%s、他に相手が居ない → ぼうぎょ", t.ally, bad))
        return defend_action(string.format("回復の相手が居ない（%s は%s）", t.ally, bad)), lines
      end
      note(string.format("%s は%s → %s へ", t.ally, bad, to.slot))
      action = {kind = action.kind, spell = action.spell, spell_tiles = action.spell_tiles,
                item = action.item, item_id = action.item_id, item_tiles = action.item_tiles,
                name = action.name,
                target = {ally = to.slot}, fallback = action.fallback or "attack",
                why = (action.why or "") .. string.format("（%s は%s → %s）", t.ally, bad, to.slot)}
    end
  end

  -- ④ MP（★ターンの途中で減っている / 相手の マホトーン など）
  if action.kind == "spell" and action.spell ~= nil and caps ~= nil then
    local cost, spell = cost_of(action.spell, caps)
    if cost ~= nil and cost > (member.mp or 0) then
      local pool = nil
      for _, group in ipairs({caps.heal or {}, caps.revive or {}, caps.attack or {},
                              caps.support or {}}) do
        for _, s in ipairs(group) do
          if s.id == action.spell then pool = group end
        end
      end
      -- ⚠⚠ 上位の MP 制約を、★見直しでも通します（RX3-0429 / P-16）。
      --   ★使用禁止なら**安い呪文へも逃がしません**（⚠ やくそう / ぼうぎょ だけ）。
      local policy = (ctx or {}).mp_policy
      local other = nil
      if policy ~= "forbid" then
        local floor_ratio = nil
        if policy == "save" then
          local f = ((ctx or {}).tuning or {}).mp_floor
          floor_ratio = tonumber(type(f) == "table" and f.save or f)
        end
        local keep = floor_ratio and (floor_ratio * (member.mp_max or 0)) or 0
        other = cheaper(pool, member.mp or 0, keep)
      end
      if other ~= nil then
        note(string.format("MP %d では %s を使えない → %s へ", member.mp or 0,
                           (spell and spell.name) or ("呪文" .. action.spell),
                           other.name or ("呪文" .. other.id)))
        action = spell_action(other, action.target,
          string.format("MP 不足で安いほうへ（%d/%d）", member.mp or 0, cost))
      elseif caps.herb and (member.herbs or 0) > 0 and action.target ~= nil
          and action.target.ally ~= nil then
        note(string.format("MP %d では呪文を使えない → やくそう", member.mp or 0))
        -- ⚠⚠ やくそうのタイルは**道具の表**から取ります（RX3-0429 / P-14）。
        --   ★`action.item_tiles` は呪文の手なので**空**でした（⚠ 一覧で見つからず止まる）。
        local herb_tiles = (((ctx or {}).items or {}).herb or {}).tiles
        action = {kind = "item", item = "herb",
                  item_tiles = herb_tiles or action.item_tiles,
                  target = action.target, fallback = "attack", why = "MP 不足でやくそう"}
      else
        note(string.format("MP %d では呪文を使えない → ぼうぎょ", member.mp or 0))
        return defend_action(string.format("MP 不足（%d/%d）", member.mp or 0, cost)), lines
      end
    end
  end

  -- ⑤ 道具（★誰かが先に使い切った / 手放した）
  --   ★★ 品を名指しした手（`item_id` を持つ手）は やくそう の数で見ない。
  --     ⚠⚠ 以前は どの道具の手も「やくそう 0 個」で ぼうぎょ に書き換えていた（RX3-0213）。
  --     ⚠⚠ 2026-09-23 訂正: そのときの直しは **攻撃の道具にしか効いていません**でした
  --       （`RX3-0410`）。★回復の道具（けんじゃのいし / ちからのたて）は
  --       `item == "heal"` なので下の `elseif` に落ち、⚠ **やくそう 0 個で有料の呪文へ
  --       書き換わって**いました。★実機で `けんじゃのいし → ベホマラー（18 MP）`。
  --     ★見るのは「持ち主がまだ持っているか」だけ（★これらは**減りません**）。
  --     ⚠ 袋が読めていない（`battle_items == nil`）ときは止めない（★分からないは止めない）
  if action.kind == "item" and action.item_id ~= nil then
    local bag = member.battle_items
    if bag ~= nil and not bag[action.item_id] then
      local name = action.name or ("道具" .. action.item_id)
      if action.item == "attack" then
        note(string.format("%s が袋に無い → たたかう", name))
        return {kind = "attack", target = action.target, fallback = "attack",
                why = string.format("%s が無いので物理", name)}, lines
      end
      -- ★回復の道具が無くなっていたら、⚠ そのときだけ呪文（★無ければ ぼうぎょ）
      local heal = caps ~= nil and cheaper(caps.heal or {}, member.mp or 0) or nil
      if heal ~= nil then
        note(string.format("%s が袋に無い → %s", name, heal.name or ("呪文" .. heal.id)))
        action = spell_action(heal, action.target, string.format("%s が無いので呪文へ", name))
      else
        note(string.format("%s が袋に無い → ぼうぎょ", name))
        return defend_action(string.format("%s が無い", name)), lines
      end
    end
  elseif action.kind == "item" and (member.herbs or 0) <= 0 then
    local heal = caps ~= nil and cheaper(caps.heal or {}, member.mp or 0) or nil
    if heal ~= nil then
      note("やくそうが無くなった → " .. (heal.name or ("呪文" .. heal.id)))
      action = spell_action(heal, action.target, "やくそう切れで呪文へ")
    else
      note("やくそうが無くなった → ぼうぎょ")
      return defend_action("やくそうが無い"), lines
    end
  end

  return action, lines
end

return Legality
