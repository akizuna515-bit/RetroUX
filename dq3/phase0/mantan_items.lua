-- ★まんたんで道具（やくそう / どくけしそう）を使う判断（2026-09-11 依頼者）。⚠ ゲームは覗かない（★材料は引数）。
--
-- ## ★依頼者の決定
--
--   「推奨案で良い。道具を優先するか、呪文を優先するか、道具を使わないを設定で選ばせる」
--
--   ```text
--   spell_first  ★既定。呪文（ホイミ）→ 唱えられなければ やくそう
--   item_first   やくそう → 無ければ呪文
--   spell_only   道具を使わない（★今までのまんたん）
--   毒           spell_only 以外なら、毒の人に どくけしそう（★HP の回復より先）
--   まひ         ★毒より先。キアリク / まんげつそう（RX3-0252 / 下）
--   ```
--
-- ## ★まひ（RX3-0252 / 2026-09-13 依頼者「save7 まひを満タンで直したい。まんげつそう or キアリク」）
--
--   ★順番は まひ → 毒 → HP。★呪文と道具のどちらが先かは毒と同じく「回復のしかた」に従う
--   （★道具を使わない設定でも キアリク なら治す / キアリーと同じ）。
--   ⚠ まひの人は動けない → ★唱える人・道具の持ち主にしない（ROM bank 13 $9F8E も「生きていて bit6 なし」を探す）。
--   ★印は状態の上位バイトの bit6（ROM bank 0 $A09F: `AND #$40` → `AND #$BF` で落とす / まんげつそう $B27B → $A09F）。
--
-- ## ★道具を使う手順は item_use_v0.lua に任せる（⚠ 二重に作らない / RX3-0159 で実機に通った手順）
--
--   どうぐ → 持ち主 → 道具 → つかう → ★誰に（RX3-0174 で足した段）→ 文を閉じる
--   ★まんたんは「誰の・何を・誰に」を決め、終わったら HP / 毒で**効いたか**を確かめるだけ。
--
-- ⚠ まんたん本体（mantan_v0.lua）は Lua 5.1 の upvalue 上限すれすれ → ★判断はここに置く。

local MI = {}

MI.SPELL_FIRST, MI.ITEM_FIRST, MI.SPELL_ONLY = "spell_first", "item_first", "spell_only"
MI.ORDERS = {spell_first = true, item_first = true, spell_only = true}
--: ★道具番号（⚠ 袋の値の下 7 ビット / ROM の名前表で確かめた既定 / 生成物で上書き）
MI.HERB_ID, MI.ANTIDOTE_ID = 101, 102
--: ★まんげつそう（RX3-0252 / ROM の名前表 108）
MI.MOON_ID = 108
MI.EMPTY = 0xFF

--- ★その人の袋（⚠ 読めなければ空）。`read(addr)` はバイトを返す関数。
function MI.bag(read, party_cfg, index)
  local out = {}
  local base, n = party_cfg.items, party_cfg.item_slots or 8
  if base == nil then return out end
  for k = 0, n - 1 do
    local raw = read(base + (index - 1) * n + k)
    if raw ~= nil and raw ~= MI.EMPTY then out[#out + 1] = raw % 128 end
  end
  return out
end

--- ★状態の旗が立っているか（⚠ 裏の取れた旗だけ / profile の status_flags。★来ていない旗は false）
local function flag_on(read, party_cfg, index, name)
  local flags = (party_cfg.status_flags or {})[name]
  if party_cfg.status == nil or flags == nil then return false end
  local size = party_cfg.status_size or 2
  local byte = read(party_cfg.status + (index - 1) * size + (flags.byte or 0)) or 0
  return math.floor(byte / (2 ^ (flags.bit or 0))) % 2 == 1
end

--- ★毒か（⚠ 裏の取れた旗だけ / profile の status_flags.poisoned）。
function MI.poisoned(read, party_cfg, index)
  return flag_on(read, party_cfg, index, "poisoned")
end

--- ★まひか（RX3-0252 / profile の status_flags.paralyzed = 上位バイトの bit6）。
function MI.paralyzed(read, party_cfg, index)
  return flag_on(read, party_cfg, index, "paralyzed")
end

--- ★動ける人か（★生きていて、まひでない / RX3-0252: ⚠ まひの人は唱えられず、道具も使えない）
local function can_act(m)
  return m ~= nil and m.hp > 0 and not m.paralyzed
end

local function holder(members, bags, item_id, prefer)
  if can_act(prefer) then
    for _, id in ipairs(bags[prefer.index] or {}) do
      if id == item_id then return prefer end
    end
  end
  for _, m in ipairs(members) do
    if can_act(m) then
      for _, id in ipairs(bags[m.index] or {}) do
        if id == item_id then return m end
      end
    end
  end
  return nil
end

----------------------------------------------------------------------
-- ★★ まんたん v1（RX3-0161 / RX3-0163 / RX3-0162 / 2026-09-12 依頼者「推奨順にどんどん進めて」）
--
--   ★「僧侶が回復する」ではなく「いま使える回復手段から一番よいものを選ぶ」
--     （`docs/research/260912_dq3-mantan-v1-kiary.md` §6）。
--   ★材料: 各人の `field`（フィールドで唱えられる呪文 ID / `Catalog.field_spells`）と
--          `opts.spells`（呪文の表 / ROM の MP・回復量）。⚠ どちらかが無ければ v0（今までの決め方）。
--
--   ★依頼者の判断（2026-09-12 / 4 件とも推奨どおり）:
--     min_mp は「唱えた**後**に残す MP」（既定 0）/ 相手は HP 割合が最小の人（今のまま）/
--     道具を使わない設定でも毒はキアリーで治す / ベホマラーは v1.1（★ここは単体だけ）
----------------------------------------------------------------------
MI.HOIMI, MI.BEHOIMI, MI.BEHOMA, MI.KIARY = 26, 27, 28, 52
--: ★キアリク（まひを治す / RX3-0252）
MI.KIARIKU = 53
MI.HEALS = {[26] = true, [27] = true, [28] = true}
--: ★呪文で進む plan の種類（★mantan_v0.lua はこれ以外を道具として item_use_v0 へ頼む）
--   ⚠ ここに無い呪文の種類を足すと、道具の道へ落ちて**やくそう を頼む**（RX3-0252 で足すときに気づいた）
MI.SPELL_KINDS = {spell = true, kiary = true, kiariku = true}
--: ★回復量の基本がこれ以上なら全快（★ベホマ / ROM の表 0xFF）
MI.FULL_HEAL = 255

local function expected(spell, target)
  if (spell.base or 0) >= MI.FULL_HEAL then return target.hp_max - target.hp end
  return (spell.base or 0) + (spell.delta or 0) / 2
end

local function ratio_after(m, cost)
  if (m.mp_max or 0) <= 0 then return 0 end
  return (m.mp - cost) / m.mp_max
end

--- ★唱えてよい人（RX3-0214 / 画面のチェック）→ 集合。⚠ 無い・空なら nil（= 全員）
local function allowed_set(list)
  if type(list) ~= "table" then return nil end
  local set, any = {}, false
  for _, slot in ipairs(list) do set[slot] = true; any = true end
  return any and set or nil
end

-- ★★ ⚠⚠ 「勇者の MP は最後の手段」は**外しました**（RX3-0318 / 2026-09-20）★★
--
--   ★もとの理由（RX3-0214 / 2026-09-12）:
--     「勇者の MP が少ない」「ルーラを唱える人が少ない」
--
--   ⚠ 依頼者 2026-09-20:
--     「今は勇者も対象に設定したら、唱えるようにしたい
--      ※単純に勇者外しのロジックはいらない」
--
--   → ★**唱えるかどうかは [唱えてよい人] のチェックだけ**で決めます。
--     ⚠ 勇者を唱えさせたくなければ、★そのチェックを外してください。
--   ⚠ `m.hero`（職業が勇者か）は `mantan_v0.lua` が読んでいますが、
--     ★ここではもう見ません（⚠ 記録・画面の材料としては残す）。

--- ★呪文の候補（★生きていて、覚えていて、唱えた**後**に min_mp 以上残る人ごと / ⚠ 職業では見ない）
--   ★`allowed` … 唱えてよい人（nil = 全員）
--   ⚠ まひの人は唱えられない（RX3-0252）
local function casts(members, spells, wanted, min_mp, allowed, no_magic)
  -- ★★ 呪文がかき消される場所では、唱えられる候補は 0（RX3-0320 / 2026-09-20）
  --   ⚠⚠ 依頼者「呪文をかきけすダンジョンでは、呪文をつかわないようにしたい」。
  --   ★実機は **MP を引いてから**消します（⚠ 唱えるだけ損）。
  --   ★キアリク・キアリー・HP の回復は**すべてここ**を通るので、1 か所で足ります。
  if no_magic then return {} end
  local out = {}
  for _, m in ipairs(members) do
    if can_act(m) and (allowed == nil or allowed[m.slot]) then
      for row, sid in ipairs(m.field or {}) do
        local s = spells[sid]
        if wanted[sid] and s ~= nil and m.mp - (s.mp or 0) >= min_mp then
          out[#out + 1] = {caster = m, spell_id = sid, row = row - 1, cost = s.mp or 0, spell = s}
        end
      end
    end
  end
  return out                    -- ⚠ 勇者外しはしません（RX3-0318）
end

--- ★同じくらい良いなら: 使った後の MP 率が高い人 → 設定の回復役 → 並びの前
local function better_caster(a, b, prefer)
  local ra, rb = ratio_after(a.caster, a.cost), ratio_after(b.caster, b.cost)
  if ra ~= rb then return ra > rb end
  local pa, pb = a.caster.slot == prefer, b.caster.slot == prefer
  if pa ~= pb then return pa end
  return a.caster.index < b.caster.index
end

--- ★HP の候補の並べ方（調査 §6-2）: 総 MP → 回数 → 過剰回復 → 術者（上）
local function heal_before(a, b, prefer)
  if a.total_mp ~= b.total_mp then return a.total_mp < b.total_mp end
  if a.uses ~= b.uses then return a.uses < b.uses end
  if a.overheal ~= b.overheal then return a.overheal < b.overheal end
  return better_caster(a, b, prefer)
end

--- ★状態を治す（まひ / 毒）。`cure` = {flag, spell_id, spell_kind, item_id, item_kind}
--   ★呪文と道具のどちらが先かは「回復のしかた」。⚠ 道具を使わない設定でも呪文なら治す（依頼者の判断）
--   ⚠ 治す手段が無い人は飛ばす（★次の状態 / HP の回復へ進む / DQ2 と同じ）
local function cure_v1(members, bags, opts, order, cure)
  local allowed = allowed_set(opts.casters)
  for _, m in ipairs(members) do
    if m.hp > 0 and m[cure.flag] then
      local best = nil
      for _, c in ipairs(casts(members, opts.spells, {[cure.spell_id] = true}, opts.min_mp or 0,
                               allowed, opts.no_magic)) do
        if best == nil or better_caster(c, best, opts.healer_slot) then best = c end
      end
      local h = (order ~= MI.SPELL_ONLY) and holder(members, bags, cure.item_id, m) or nil
      local by_spell = best and {kind = cure.spell_kind, target = m, holder = best.caster,
                                 spell_id = cure.spell_id, row = best.row, cost = best.cost}
      local by_item = h and {kind = cure.item_kind, target = m, holder = h, item_id = cure.item_id}
      if order == MI.ITEM_FIRST then
        if by_item then return by_item end
        if by_spell then return by_spell end
      else
        if by_spell then return by_spell end
        if by_item then return by_item end
      end
    end
  end
  return nil
end

local function plan_v1(members, bags, opts, order, herb_id, antidote_id, hp_below)
  local spells, prefer = opts.spells, opts.healer_slot
  local min_mp = opts.min_mp or 0
  local allowed = allowed_set(opts.casters)

  -- ★★ まひ（RX3-0252 / ★毒より先）。キアリク / まんげつそう。⚠ まひの人は唱える人・持ち主にしない
  local got = cure_v1(members, bags, opts, order, {flag = "paralyzed", spell_id = MI.KIARIKU,
                      spell_kind = "kiariku", item_id = opts.moon_id or MI.MOON_ID, item_kind = "moon"})
  if got then return got end
  -- ★毒（★HP より先）。⚠ 道具を使わない設定でも、キアリーなら治す（依頼者の判断）
  got = cure_v1(members, bags, opts, order, {flag = "poisoned", spell_id = MI.KIARY,
                spell_kind = "kiary", item_id = antidote_id, item_kind = "cure"})
  if got then return got end

  -- ★HP（★割合が最小の人 / 今のまま）
  local target, worst = nil, 101
  for _, m in ipairs(members) do
    if m.hp_max > 0 and m.hp > 0 then
      local ratio = m.hp * 100 / m.hp_max
      if ratio < hp_below and ratio < worst then target, worst = m, ratio end
    end
  end
  if target == nil then return nil, "全員 " .. hp_below .. "% 以上" end

  local deficit = target.hp_max - target.hp
  local best = nil
  for _, c in ipairs(casts(members, spells, MI.HEALS, min_mp, allowed, opts.no_magic)) do
    local e = expected(c.spell, target)
    if e > 0 then
      c.uses = math.ceil(deficit / e)
      c.total_mp, c.overheal = c.uses * c.cost, c.uses * e - deficit
      if best == nil or heal_before(c, best, prefer) then best = c end
    end
  end
  local herb = (order ~= MI.SPELL_ONLY) and holder(members, bags, herb_id, target) or nil
  local by_spell = best and {kind = "spell", target = target, holder = best.caster, spell_id = best.spell_id,
                             row = best.row, cost = best.cost, uses = best.uses}
  local by_herb = herb and {kind = "herb", target = target, holder = herb, item_id = herb_id}
  if order == MI.ITEM_FIRST then
    if by_herb then return by_herb end
    if by_spell then return by_spell end
  else
    if by_spell then return by_spell end
    if by_herb then return by_herb end
  end
  if order == MI.SPELL_ONLY then return nil, "唱えられる回復呪文が無い（覚えている人 / MP）" end
  return nil, "MP も やくそう も足りない"
end

--- ★v1 の材料がそろっているか（⚠ 生成物が無い・呪文が読めない環境では v0 のまま）
function MI.v1_ready(members, opts)
  if opts == nil or type(opts.spells) ~= "table" then return false end
  for _, m in ipairs(members or {}) do
    if type(m.field) == "table" then return true end
  end
  return false
end

--- ★★ 次にやること。戻り値 `plan, why`（★plan が nil なら終わる理由が why）。
--
--   members: {{slot, index, hp, hp_max, mp, poisoned, paralyzed}, ...}（★生きている人も倒れている人も）
--   bags:    {[index] = {道具番号, ...}}
--   opts:    {order, hp_below, min_mp, healer_slot, can_cast(healer), herb_id, antidote_id, moon_id}
--   plan:    {kind = "spell" | "herb" | "cure" | "moon", target = m, holder = m, item_id = n}
--   ★v1（members に `field`、opts に `spells`）: plan に spell_id / row / cost、毒は kind = "kiary" もある
--   ★まひ（RX3-0252）: 道具は kind = "moon"（まんげつそう）/ v1 の呪文は kind = "kiariku"（キアリク）
function MI.plan(members, bags, opts)
  opts = opts or {}
  local order = MI.ORDERS[opts.order or ""] and opts.order or MI.SPELL_FIRST
  local herb_id = opts.herb_id or MI.HERB_ID
  local antidote_id = opts.antidote_id or MI.ANTIDOTE_ID
  local hp_below = opts.hp_below or 90
  if MI.v1_ready(members, opts) then
    return plan_v1(members, bags, opts, order, herb_id, antidote_id, hp_below)
  end
  local min_mp = opts.min_mp or 4

  -- ★まひ → 毒（⚠ 道具を使わない設定では見ない / v0 は呪文の材料が無いので道具だけ）
  --   ★まひ（RX3-0252）は まんげつそう、毒は どくけしそう。⚠ まひの人は持ち主にしない（holder）
  if order ~= MI.SPELL_ONLY then
    for _, cure in ipairs({{"paralyzed", opts.moon_id or MI.MOON_ID, "moon"},
                           {"poisoned", antidote_id, "cure"}}) do
      for _, m in ipairs(members) do
        if m.hp > 0 and m[cure[1]] then
          local h = holder(members, bags, cure[2], m)
          if h ~= nil then
            return {kind = cure[3], target = m, holder = h, item_id = cure[2]}
          end
        end
      end
    end
  end

  -- ★HP がいちばん減っている人（⚠ 倒れている人は呪文でも薬草でも起きない）
  local target, worst = nil, 101
  for _, m in ipairs(members) do
    if m.hp_max > 0 and m.hp > 0 then
      local ratio = m.hp * 100 / m.hp_max
      if ratio < hp_below and ratio < worst then target, worst = m, ratio end
    end
  end
  if target == nil then return nil, "全員 " .. hp_below .. "% 以上" end

  local healer = nil
  for _, m in ipairs(members) do
    if m.slot == (opts.healer_slot or "p3") then healer = m end
  end
  -- ⚠ v0 は min_mp を「唱える前の MP」で見る。★呪文の MP（ホイミ 3）を下回っては唱えない
  --   （★v1 で min_mp の既定が 0 になったため / 2026-09-12）
  --   ⚠ まひの回復役は唱えられない（RX3-0252）
  --   ⚠ 呪文がかき消される場所では唱えない（RX3-0320 / ★v1 の `casts` と同じ決まり）
  local spell_ok = (not opts.no_magic)
    and can_act(healer) and healer.mp >= math.max(min_mp, opts.spell_cost or 3)
  local herb = (order ~= MI.SPELL_ONLY) and holder(members, bags, herb_id, target) or nil

  local function spell() return {kind = "spell", target = target, holder = healer} end
  local function use_herb() return {kind = "herb", target = target, holder = herb, item_id = herb_id} end

  if order == MI.ITEM_FIRST then
    if herb ~= nil then return use_herb() end
    if spell_ok then return spell() end
  else
    if spell_ok then return spell() end
    if herb ~= nil then return use_herb() end
  end
  if order == MI.SPELL_ONLY then
    return nil, (healer == nil) and "回復役がいない"
                or (healer.paralyzed and "回復役が まひ で唱えられない") or "MP が足りない"
  end
  return nil, "MP も やくそう も足りない"
end

--- ★効いたか（★HP が増えた / 毒が消えた / まひが消えた）。before / after は同じ人の表。
function MI.worked(plan, before, after)
  if plan == nil or before == nil or after == nil then return false end
  -- ★毒を治す（どくけしそう / キアリー / RX3-0162）は、毒が消えたら「効いた」
  if plan.kind == "cure" or plan.kind == "kiary" then return before.poisoned and not after.poisoned end
  -- ★まひを治す（まんげつそう / キアリク / RX3-0252）は、まひが消えたら「効いた」
  if plan.kind == "moon" or plan.kind == "kiariku" then
    return before.paralyzed == true and not after.paralyzed
  end
  return after.hp > before.hp
end

--- ★ログ用の短い言い方。
function MI.describe(plan)
  if plan == nil then return "-" end
  local what = (plan.kind == "cure" and "どくけしそう") or (plan.kind == "herb" and "やくそう")
               or (plan.kind == "kiary" and "キアリー")
               or (plan.kind == "moon" and "まんげつそう") or (plan.kind == "kiariku" and "キアリク")
               or plan.spell_name or (plan.spell_id and ("呪文 " .. plan.spell_id)) or "呪文"
  return string.format("%s: %s → %s", what, plan.holder and plan.holder.slot or "?",
                       plan.target and plan.target.slot or "?")
end

return MI
