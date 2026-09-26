-- 戦闘 AI の表（RX3-0126 / 2026-09-08）— ★Python が生成した `dq3_ai.lua` を読む。
--
-- ## ★ここは RAM もメニューも知りません
--
--   ★渡された 8 バイトと職業から「覚えている呪文」を解くだけです。
--   ⚠ 規則は Python 側 `dq3rom/spell_flags.py` と**同じ**（RX3-0125 で確定）:
--
--     勇者      bytes 0-3 → ブロック 0-3
--     それ以外  bytes 0-3 → ブロック 4-7（魔法使い系）/ bytes 4-7 → ブロック 8-11（僧侶系）
--     bit は LSB から。★戦闘で使えるのは各系統の前 2 ページ。

local Catalog = {}

--- ★生成物を読む。⚠ 無ければ nil（★AI を使わず、今までどおり動く）。
function Catalog.load(path)
  local ok, data = pcall(dofile, path)
  if not ok or type(data) ~= "table" or data.ok ~= true then return nil, data end
  return data
end

--- ★その人が覚えている戦闘呪文の ID（★ページ 0・1・2）。
--
--   `bytes8`   … `$078C + 人×8` の 8 バイト（★1 始まりの Lua 配列）
--   `class_id` … `$0718` の下位 3 bit
--
--   ⚠⚠ 2026-09-20（RX3-0326）: **ページ 2 を読んでいませんでした**。
--     ★ザラキ・イオナズン・ベギラゴン・ベホマラー・ザオリク等が AI から見えず、
--     ⚠ 「覚えているのに使わない」の直接の原因でした。
--     ★正本は `dq3rom/spell_flags.py` の `BATTLE_PAGES`（⚠ 2 か所に同じ規則がある）。
--   ⚠ ページ 3 は `Catalog.field_spells` の担当です（★移動・メニュー用 / RX3-0161）。
local spells_of

function Catalog.learned(cat, bytes8, class_id)
  if cat == nil or bytes8 == nil or #bytes8 < 8 then return {} end
  local plan
  if (tonumber(class_id) or 0) % 8 == 0 then
    -- ★勇者（ブロック 0,1,2 → Lua は 1,2,3）。⚠ ブロック 2 は空だが、★他職と同じ形にしておく
    plan = { {bytes8[1], 1}, {bytes8[2], 2}, {bytes8[3], 3} }
  else
    -- ★魔法使い系 ブロック 4,5,6 → Lua 5,6,7 ／ ★僧侶系 ブロック 8,9,10 → Lua 9,10,11
    plan = { {bytes8[1], 5}, {bytes8[2], 6}, {bytes8[3], 7},
             {bytes8[5], 9}, {bytes8[6], 10}, {bytes8[7], 11} }
  end
  return spells_of(cat, plan)
end

spells_of = function(cat, plan)
  local blocks = cat.blocks or {}
  local out = {}
  for _, pair in ipairs(plan) do
    local byte, block = pair[1], blocks[pair[2]]
    if block ~= nil then
      for bit = 0, 7 do
        if math.floor(byte / 2 ^ bit) % 2 == 1 then
          local sid = block[bit + 1]
          if sid ~= nil and sid ~= 255 then out[#out + 1] = sid end
        end
      end
    end
  end
  return out
end

--- ★フィールドで唱えられる呪文の ID（★各系統の**ページ 3** / RX3-0161 / 2026-09-12）。
--
--   勇者      byte 3 → ブロック 3
--   それ以外  byte 3 → ブロック 7（魔法使い系）/ byte 7 → ブロック 11（僧侶系）
--   ★実測（2026-09-12 のセーブ）: 僧侶のページ 0 = ルカニ ホイミ … / ページ 3 = ホイミ。
--     ★まんたん（ホイミが先頭でないと止まる）が僧侶で実機成功 → フィールドの並びは戦闘の並びではない。
--   ⚠ 並びの順は HYPOTHESIS（★まんたんは**名前で探して**押すので、並びには頼らない）。
function Catalog.field_spells(cat, bytes8, class_id)
  if cat == nil or bytes8 == nil or #bytes8 < 8 then return {} end
  local blocks = cat.blocks or {}
  local plan
  if (tonumber(class_id) or 0) % 8 == 0 then
    plan = { {bytes8[4], 4} }                                   -- ★勇者（ブロック 3 → Lua は 4）
  else
    plan = { {bytes8[4], 8}, {bytes8[8], 12} }                  -- ★ブロック 7 / 11 → Lua は 8 / 12
  end
  local out, seen = {}, {}
  for _, pair in ipairs(plan) do
    local byte, block = pair[1], blocks[pair[2]]
    if block ~= nil then
      for bit = 0, 7 do
        if math.floor(byte / 2 ^ bit) % 2 == 1 then
          local sid = block[bit + 1]
          if sid ~= nil and sid ~= 255 and not seen[sid] then
            out[#out + 1] = sid
            seen[sid] = true
          end
        end
      end
    end
  end
  return out
end

--: ★系統ごとのブロック（⚠ `dq3rom/spell_flags.py` の `MAGE_BLOCKS` / `PILGRIM_BLOCKS` と同じ）。
--   ⚠ Lua の配列は 1 始まりなので、ブロック N は `blocks[N + 1]`。
Catalog.FAMILY_BLOCKS = {mage = {5, 6, 7, 8}, pilgrim = {9, 10, 11, 12}}

--- ★★ その呪文はどちらの系統か（RX3-0293 / 2026-09-18）。
--
--   ⚠⚠ 賢者は「まほうつかい / そうりょ」を選ぶ窓が 1 段挟まります。
--   ★どちらを選ぶかは**職業ではなくブロック**で決めます
--     （⚠ 転職した人でも、覚えた呪文がどちらの表から来たかは変わらない）。
--
--   戻り値: `"mage"` / `"pilgrim"` / ⚠ 分からなければ `nil`（★呼ぶ側は押さずに止まる）
--   ⚠ 両方の表にある呪文は `nil`（★どちらを押すべきか決められない = 黙って選ばない）
function Catalog.family_of(cat, sid)
  if cat == nil or sid == nil then return nil end
  local blocks = cat.blocks or {}
  local found
  for _, family in ipairs({"mage", "pilgrim"}) do
    for _, n in ipairs(Catalog.FAMILY_BLOCKS[family]) do
      local block = blocks[n]
      if block ~= nil then
        for k = 1, 8 do
          if block[k] == sid then
            if found ~= nil and found ~= family then return nil end
            found = family
          end
        end
      end
    end
  end
  return found
end

function Catalog.spell(cat, sid)
  if cat == nil or sid == nil then return nil end
  return (cat.spells or {})[sid]
end

function Catalog.enemy(cat, id)
  if cat == nil or id == nil then return nil end
  return (cat.enemies or {})[id]
end

--- ★DQ3 の耐性の段階 → 効く確率（`dq3rom/enemy_detail.RESIST_PERCENT` と同じ）
--
--   ⚠⚠ **これは「状態をかける呪文」用です**（★眠り・封じ・即死…）。
--     `_rand_ex` と `byte_6B9CE`（$00 $4D $B3 $FF）を比べる判定なので、
--     ★効くか効かないかの**確率**になります。
Catalog.RESIST_RATE = { [0] = 1.0, [1] = 0.7, [2] = 0.3, [3] = 0.0 }

--- ★★ ダメージ側の耐性は**倍率**です（RX3-0137 / 2026-09-09）。
--
--   ⚠⚠ **2026-09-08 の v1 は、ここに上の確率表を使っていました。**
--     ★ROM は別の表 `byte_69837`（$FF $CC $99 $80）で、
--     ⚠ 効かない段でも **50% は通ります**（★0% ではない）。
--     → 「耐性 3 の敵には呪文がまったく効かない」と見て、★呪文を捨てていました。
--
--   ⚠⚠ 2026-09-14 訂正（RX3-0266 / JP ROM で確かめた）: 上の見立ては**誤り**でした。
--     ★この倍率表を使うのは**ブレスの 1 か所だけ**（JP bank 4 `$98C7` / 表 `$98F3`）。
--     ★攻撃呪文は呪文の番号で耐性 0〜3（メラ・ギラ・イオ系 / ヒャド系 / バギ系 / デイン系）を選び、
--       上の `RESIST_RATE` と同じ確率で「効く / 効かない」の**二択**（`$A4BF`〜`$A4DE`）。
--     ★★ RX3-0267 で直した: 戦闘 AI の攻撃呪文は `RESIST_RATE`（確率）と呪文ごとの耐性（`s.resist`）で見る
--       （`actions.lua` の `spell_effect`）。⚠ この表と `damage_scale` はブレス用として残すだけ（★AI は使わない）。
--
--   ```text
--   段 0  $FF = 255/255 = 100%
--   段 1  $CC = 204/255 =  80%
--   段 2  $99 = 153/255 =  60%
--   段 3  $80 = 128/255 =  50%
--   ```
Catalog.DAMAGE_SCALE = { [0] = 1.0, [1] = 0.8, [2] = 0.6, [3] = 0.5 }

function Catalog.success_rate(level)
  if level == nil then return nil end
  return Catalog.RESIST_RATE[tonumber(level) or 0]
end

--- ★ダメージがどれだけ通るか（⚠ 分からなければ nil = 呼ぶ側が 1.0 に倒す）。
function Catalog.damage_scale(level)
  if level == nil then return nil end
  return Catalog.DAMAGE_SCALE[tonumber(level) or 0]
end

return Catalog
