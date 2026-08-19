--- 攻撃呪文の候補をこしらえる（2026-08-03 / 「ガンガン行こうぜ」Phase 1）。
--
-- ★★ **ここは RAM を読みません。** ★★
--   「その人が覚えている呪文の一覧」と「いまの MP」を渡してもらい、
--   `attack_plan` が使える形の候補に整えるだけです。
--
-- ⚠ RAM から拾う仕事は `bridge.lua` の側にあります
--   （`learned_spells` / `current_mp` / `spell_blocked` / `spell_denied`）。
--
-- ## 候補にしない条件（指示書 §4・§5・§6）
--
--   ★ 威力が分からない呪文（`damage_avg` が無い）
--   ★ 回復呪文（`heal: true`）… **ガンガン行こうぜでは使わない**
--   ★ 唱えない指定（メガンテ・パルプンテ）
--   ★ MP が足りない（★予約ぶんを引いた残りで見る）
--   ★ 呪文リストに位置が無い（未習得・位置が食い違う）

local Candidates = {}

--- ★MP 下限を割るか（指示書 §4.1）。
--
--   `現在MP - 消費MP < 下限` なら使えません。
--
-- ⚠ `reserve` は「ルーラ・リレミトのぶん」と「最低残存MP」を
--   すでに合わせた数（`bridge` 側が `reserved_mp()` で出します）。
function Candidates.mp_allows(current_mp, cost, reserve)
  if type(current_mp) ~= "number" then return false end
  return current_mp >= (cost or 0) + (reserve or 0)
end

--- 1つの呪文を候補にしてよいか。
--
-- `entry` は `learned_spells` の1件（`id` / `name` / `row` / `col`）。
-- `info` は `memory_map.spells[id]`。
--
-- 戻り値: `使えるか, 使えない理由`
function Candidates.check(entry, info, opts)
  opts = opts or {}
  if type(info) ~= "table" then
    return false, "呪文の情報がない"
  end
  -- ★威力が分からないものは選ばない（⚠ 推測で埋めない）
  if type(info.damage_avg) ~= "number" then
    return false, "威力が分かっていない"
  end
  -- ★回復呪文は「ガンガン行こうぜ」では使わない（§5）
  if info.heal == true then
    return false, "回復呪文（この作戦では使わない）"
  end
  -- ★唱えない指定（メガンテ・パルプンテ）
  if info.never_cast == true then
    return false, info.never_cast_reason or "唱えない指定"
  end
  if opts.denied ~= nil then
    return false, opts.denied
  end
  -- ★呪文リストに位置が無い（未習得など）
  if type(entry) ~= "table" or entry.row == nil or entry.col == nil then
    return false, "呪文リストに位置がない"
  end
  -- ★MP（§4.1）
  if not Candidates.mp_allows(opts.current_mp, info.mp_battle, opts.reserve) then
    return false, "MP が足りない（予約ぶんを含む）"
  end
  return true, nil
end

--- ★その人の候補を並べる。
--
-- 引数:
--   ```
--   entries  … learned_spells の一覧（★呪文リストの順）
--   spells   … memory_map.spells
--   opts     … { actor, current_mp, reserve, index, denied_of = function(id) }
--   ```
--
-- 戻り値: `候補の一覧, 落としたものの一覧`
--
-- ⚠ 落としたものも返します（★黙って消さない。ログに出せるように）。
function Candidates.build(entries, spells, opts)
  opts = opts or {}
  local out, dropped = {}, {}
  for _, entry in ipairs(entries or {}) do
    local id = entry.id
    if id ~= nil and id ~= 0 then
      local info = (spells or {})[id]
      local denied = nil
      if opts.denied_of ~= nil then denied = opts.denied_of(id) end
      local ok, why = Candidates.check(entry, info, {
        current_mp = opts.current_mp, reserve = opts.reserve,
        denied = denied,
      })
      if ok then
        out[#out + 1] = {
          actor = opts.actor,
          spell_id = id,
          spell = info,
          row = entry.row,
          col = entry.col,
          index = opts.index or 1,
          usable = true,
        }
      else
        dropped[#dropped + 1] = {
          spell_id = id,
          name = (info or {}).name or entry.name,
          reason = why,
        }
      end
    end
  end
  return out, dropped
end

--- ⚠ 落とした理由をまとめて1行にする（ログ用）。
--
-- ★同じ理由はまとめます（「威力が分かっていない」が7個並ばないように）。
function Candidates.describe_dropped(dropped)
  if type(dropped) ~= "table" or #dropped == 0 then return "" end
  local by_reason, order = {}, {}
  for _, d in ipairs(dropped) do
    local key = tostring(d.reason)
    if by_reason[key] == nil then
      by_reason[key] = {}
      order[#order + 1] = key
    end
    local list = by_reason[key]
    list[#list + 1] = tostring(d.name or string.format("0x%02X", d.spell_id))
  end
  local parts = {}
  for _, key in ipairs(order) do
    parts[#parts + 1] = string.format("%s（%s）",
      key, table.concat(by_reason[key], "・"))
  end
  return table.concat(parts, " / ")
end

return Candidates
