-- 役割（RX3-0126 / 2026-09-08）— ★指示書 §5〜§9「必要な役割 → キャラへ割り当てる」。
--
-- ```text
-- 戦況 × 作戦 → 必要な役割の列（need）   ★パーティ単位で決める（§9）
-- need × 各人の「できること」 → 割当       ★第1 → 第2 → 臨時（§8）
-- ```
--
-- ## ⚠ 職業では決めない（§7）
--
--   ★「できること」は覚えている呪文・MP・攻撃力から出す（`Roles.caps`）。
--   転職して魔法使いになった元僧侶は、ホイミを覚えていればヒールになれる。
--
-- ## ⚠ MP 制約はここで効く（§13 / §1「制約 → 作戦」）
--
--   使用禁止 … 呪文の役割（魔法 / 支援）を**作らない**。回復は やくそう だけ
--              ★道具の攻撃（まどうしのつえ など）は MP を使わないので魔法の役を作る（RX3-0213）
--   温存     … 回復は「危ない」まで待つ。支援は劣勢だけ。★魔法は MP の床（半分）より上なら
--              作戦どおり（RX3-0198「速攻＋半分程度残す」/ ⚠ 以前は温存で魔法を作らなかった）
--   ★どちらも作戦（生存優先）で解除しない

local Roles = {}

Roles.PHYSICAL, Roles.MAGIC, Roles.SUPPORT, Roles.HEAL, Roles.DEFEND =
  "physical", "magic", "support", "heal", "defend"
Roles.LEVELING, Roles.ECONOMY, Roles.SURVIVAL = "leveling", "economy", "survival"
Roles.MP_AUTO, Roles.MP_SAVE, Roles.MP_FORBID = "auto", "save", "forbid"

--: ★★ 作戦ごとの「魔法の役の枠」（RX3-0324 / 2026-09-20 / ★依頼者の案 A）
--
--   ⚠⚠ 依頼者「やっぱり、作戦と個々の行動がリンクしてないのは違和感がある」。
--
--   ★それまでの作り:
--     作戦 → 「撃つ**価値**があるか」だけを決める（重み・gain の下限）
--     役割 → 「**誰が**撃つか」だけを決める
--   ⚠ この 2 つが繋がっておらず、★判定で `use` と出ても役割が無ければ捨てられていました
--     （実機ログ: `decision=skip reason=assigned_other_role:physical`）。
--
--   → ★**作戦が枠の数も決めます**。
--
--   ```text
--   速攻        ★撃つ価値のある人は**全員**（⚠ 早く終わらせるのが目的）
--   リソース節約 ★1 人（⚠ MP を残す）
--   生存優先     ★1 人（⚠ 回復・支援に手を残す）
--   ```
--
--   ⚠ 「撃つ価値があるか」は今までどおり `judge_magic` が 1 人ずつ決めます。
--     ★弱い敵・1 ターンで片づく戦いでは、⚠ **そもそも誰も `use` になりません**。
Roles.MAGIC_SLOTS = {leveling = 99, economy = 1, survival = 1}
Roles.MAGIC_SLOTS_DEFAULT = 1

--- ★★ 行動傾向（第1 / 第2）の重み（RX3-0327 §7-2 / 2026-09-20）。
--
--   ⚠⚠ 選抜の鍵は `rank * RANK_WEIGHT + 自分回復の罰 - min(score, 99)` です。
--     ★`score` は 0〜99 で頭打ちなので、⚠ 重みが 100 以上だと
--       **傾向の 1 段差は実力では絶対に覆りません**（= 事実上のハードな制約）。
--
--   ```text
--   最短撃破   15  ★はっきり優れた行動があれば**傾向を越える**（⚠ 同程度ならタイブレーク）
--   ほか     1000  ⚠ 今までどおり（★依頼者「他作戦は現行の役割影響を大きく変えない」）
--   ```
--
--   ⚠ 依頼者の例: 第1 が「物理攻撃」でも、通常攻撃 3 ターン / ザラキ 1.5 ターンならザラキ。
Roles.RANK_WEIGHT = {leveling = 15}
Roles.RANK_WEIGHT_DEFAULT = 1000

local SUPPORT_KINDS = {buff = true, debuff = true}
--: ★即死系のうち、支援として使えるもの（★眠らせる / 幻惑）
local SUPPORT_EFFECTS = {sleep = true, surround = true}
--: ★★ 即死そのもの（ザキ / ザラキ / ザラキーマ / RX3-0322 / 2026-09-20）
--
--   ⚠⚠ 依頼者「クラーゴンはザラキが効いて、HP高い。期待値的に速攻ならザラキも選択肢だと思う」。
--
--   ⚠ 今まで `caps` の**どの箱にも入っていません**でした（★黙って消えていた）:
--     `kind == "instant"` で `effect == "beat"` は、`robmagic` でも `SUPPORT_EFFECTS` でもない。
--   ★HP の高い敵ほど「効く確率 × 残り HP」が大きくなるので、⚠ 長期戦では最有力になりえます。
local BEAT_EFFECT = "beat"

local Catalog = nil
--: ⚠ 予防の無料回復の判断は `actions.lua` の 1 か所だけ（★ここに写さない / RX3-0398）
local Actions = nil
function Roles.use_catalog(module) Catalog = module end
--- ★`Actions` を受け取る（⚠ `pipeline` が渡す / 無ければ予防の回復は**作らない**）
function Roles.use_actions(module) Actions = module end

local function tuned(t, key, sub, default)
  local v = (t or {})[key]
  if type(v) == "table" then v = v[sub] end
  return tonumber(v) or default
end

--- ★動けない理由（⚠ 未観測は `nil` = 動ける扱い / RX3-0135）。
--
--   ```text
--   status.paralyzed == true   ★麻痺
--   status.asleep    == true   ★眠り
--   status.confused  == true   ★混乱（⚠ 命令が通らない）
--   status.xxx == nil / false  ⚠ 止めない
--   ```
function Roles.blocked_by(member)
  local st = (member or {}).status
  if st == nil then return nil end
  if st.paralyzed == true then return "麻痺" end
  if st.asleep == true then return "眠り" end
  if st.confused == true then return "混乱" end
  return nil
end

local function copy(t)
  local o = {}
  for k, v in pairs(t) do o[k] = v end
  return o
end

--- ★★ その手は「資源を使わない・減らない」か（RX3-0396 / 2026-09-23）。
--
--   ⚠⚠ **「道具だから枠外」ではありません。** ★意味は
--   **resource-free reusable action**（= MP を払わず、使っても減らない手）です。
--
--   ```text
--   ★MP 0            `mp` が 0（⚠ 呪文は 0 でない）
--   ★減らない        `consumed` が真でない（⚠ いまの表は非消耗しか入っていない）
--   ```
--
--   ⚠ いまは `item_id` を持つ手だけが該当しますが、★将来 `consumed = true` の
--     道具を入れたら**ここだけ**が変わります（⚠ 呼び出し側は直さなくてよい）。
function Roles.resource_free(s)
  if s == nil or s.item_id == nil then return false end
  if (tonumber(s.mp) or 0) > 0 then return false end
  return s.consumed ~= true
end

--- ★その人が持っていて、使えば攻撃呪文として働く道具（RX3-0213 / まどうしのつえ など）。
--
--   ★呪文の行を写し、`mp = 0` ＋ `item_id` / `item_tiles` / `item_name` を足した「偽の呪文」。
--   ★ROM は道具の効果で MP の判定と消費を通らない（`.bs_player_item_as_chant`）→ ★MP 制約の外。
--   ★装備していても、持っているだけでよい（★戦闘の どうぐ は装備の bit を落として使う）。
--   ⚠ 使える職業の表（`use_mask`）に無い人は入れない（★その人が使ったときの扱いは未確認）。
--   ⚠ 未確認: 封じ（マホトーン）の最中に使えるか / 実際のダメージが呪文と同じ式か。
--   ⚠ `member.battle_items` が無い（袋を読めていない）ときは空（★推測で「持っている」にしない）。
function Roles.attack_items(member, cat)
  local out = {}
  local bag = member.battle_items
  if Catalog == nil or cat == nil or bag == nil then return out end
  local cls = tonumber(member.class_id)
  for _, it in ipairs((cat.items or {}).attack or {}) do
    local mask = tonumber(it.use_mask)
    local allowed = mask == nil or cls == nil or math.floor(mask / 2 ^ (cls % 8)) % 2 == 1
    local s = Catalog.spell(cat, it.spell_id)
    if bag[it.id] and allowed and s ~= nil and s.kind == "attack" and #(it.tiles or {}) > 0 then
      local p = copy(s)
      p.mp, p.item_id, p.item_tiles, p.item_name = 0, it.id, it.tiles, it.name
      -- ⚠ 減る品かどうかを**そのまま運ぶ**（★`Roles.resource_free` が見る / RX3-0396）
      p.consumed = it.consumed == true
      out[#out + 1] = p
    end
  end
  return out
end

--- ★その人が持っていて、使えば**回復呪文**として働く道具（RX3-0346 / ちからのたて など）。
--
--   ★`Roles.attack_items` と**同じ作法**です（⚠ 2 つ目の書き方を作らない）:
--     呪文の行を写し、`mp = 0` ＋ `item_id` / `item_tiles` / `item_name` を足した「偽の呪文」。
--   ⚠ ROM は道具の効果で MP の判定と消費を通らない → ★**MP 制約の外**（使用禁止でも使える）。
--   ⚠ 減る品は表に入っていません（★`generate.py` が `consumed` を落としている）。
function Roles.heal_items(member, cat)
  local out = {}
  local bag = member.battle_items
  if Catalog == nil or cat == nil or bag == nil then return out end
  local cls = tonumber(member.class_id)
  for _, it in ipairs((cat.items or {}).heal_items or {}) do
    local mask = tonumber(it.use_mask)
    local allowed = mask == nil or cls == nil or math.floor(mask / 2 ^ (cls % 8)) % 2 == 1
    local s = Catalog.spell(cat, it.spell_id)
    if bag[it.id] and allowed and s ~= nil and s.kind == "heal" and #(it.tiles or {}) > 0 then
      local p = copy(s)
      p.mp, p.item_id, p.item_tiles, p.item_name = 0, it.id, it.tiles, it.name
      -- ⚠ 減る品かどうかを**そのまま運ぶ**（★`Roles.resource_free` が見る / RX3-0396）
      p.consumed = it.consumed == true
      out[#out + 1] = p
    end
  end
  return out
end

--- ★1 人が「できること」。⚠ 職業ではなく、呪文と MP と数字から。
--
--   戻り値: { heal={spell,...}, revive={...}, attack={...}, attack_items={...}, support={...},
--            heal_power, magic_power, physical, herb }
--   ★attack_items … 道具の攻撃（`Roles.attack_items` / RX3-0213）。⚠ MP 使用禁止でも入る
--- ★★ その呪文は、この作戦で**使ってよいか**（RX3-0370 / 2026-09-22）。
--
--   ⚠⚠ 依頼者「勇者がギガデインを使いすぎる。★使わない呪文をモード毎に設定する」。
--
--   ★表は `cat.banned[作戦] = {呪文 ID, ...}`。⚠ **無い ＝ 使ってよい**
--     （★新しく覚えた呪文は自動で使える / ⚠ 人が付け直さなくてよい）。
--   ⚠ 作戦が分からないときは**止めません**（★勝手に手を減らさない）。
--   ⚠ 2026-09-22: `strategy == nil` の歯止めは**外しました**。★壊す実験で
--     「外しても赤くならない」＝ 元から通らない道でした（⚠ Lua の `t[nil]` は nil）。
local function allowed(cat, strategy, sid)
  local rows = cat ~= nil and cat.banned or nil
  if rows == nil then return true end
  local list = rows[strategy]
  if list == nil then return true end
  for _, banned in ipairs(list) do
    if banned == sid then return false end
  end
  return true
end

--- ★足場から除外を確かめる口（⚠ 表だけ渡して見たい）。
function Roles.spell_allowed(cat, strategy, sid) return allowed(cat, strategy, sid) end

function Roles.caps(member, cat, mp_policy, strategy)
  -- ★drain … マホトラ（RX3-0260 / MP を吸う）。★作戦「リソース節約」の物理の代わりだけ（`Actions.drain`）
  local out = {heal = {}, revive = {}, attack = {}, attack_items = {}, support = {}, drain = {},
               instant = {},
               herb = (member.herbs or 0) > 0,
               heal_power = 0, magic_power = 0, physical = member.attack or 0, learned = {}}
  -- ★★ 動けない人は「何もできない」（RX3-0135）。⚠ 予定に数えると、
  --   ★居ない回復役をあてにして**誰も回復しない**ターンができます。
  --   ⚠ 未観測（nil）は動けるものとして扱います（指示書 §12-2）。
  local blocked = Roles.blocked_by(member)
  if blocked ~= nil then
    out.blocked = blocked
    out.herb = false
    out.physical = 0
    return out
  end
  if Catalog == nil or cat == nil then return out end
  out.learned = Catalog.learned(cat, member.spells, member.class_id)
  -- ★道具の攻撃は MP 制約より先に入れる（RX3-0213 / ⚠ MP を使わないので使用禁止でも残す）
  out.attack_items = Roles.attack_items(member, cat)
  for _, s in ipairs(out.attack_items) do
    local avg = (s.base or 0) + (s.delta or 0) / 2
    if avg > out.magic_power then out.magic_power = avg end
  end
  -- ★回復の道具も MP 制約より先に（RX3-0346 / ⚠ ちからのたて は MP を使わない）
  for _, s in ipairs(Roles.heal_items(member, cat)) do
    out.heal[#out.heal + 1] = s
    local avg = (s.base or 0) + (s.delta or 0) / 2
    if s.base == 255 then avg = member.hp_max or 255 end
    if avg > out.heal_power then out.heal_power = avg end
  end
  -- ★★ マホトラだけは「呪文使用禁止」でも入れる（RX3-0348 / 2026-09-21 依頼者
  --   「リソース節約、呪文使用禁止でもマホトラは使って良い」）。
  --
  --   ⚠ ROM 実測: **マホトラは MP 0**（`dq3rom/spells.py` id23）。
  --
  --   ```text
  --   ★禁止の理由  「呪文を使わない ＝ MP を減らさない」
  --   ⚠ マホトラ    MP 0 で、★MP を**増やす**側 → ⚠⚠ 理由が当てはまらない
  --   ```
  --
  --   ⚠ 使う条件は**今までどおり**です（`Actions.drain`）。★「禁止でも撃てる」だけで、
  --     ⚠ 撃ちやすくはしません。
  for _, sid in ipairs(out.learned) do
    local s = Catalog.spell(cat, sid)
    if s ~= nil and s.kind == "instant" and s.effect == "robmagic"
        and (s.mp or 0) <= (member.mp or 0)
        and allowed(cat, strategy, sid) then                  -- ★除外（RX3-0370）
      out.drain[#out.drain + 1] = s
    end
  end
  if mp_policy == Roles.MP_FORBID then return out end
  for _, sid in ipairs(out.learned) do
    local s = Catalog.spell(cat, sid)
    -- ⚠⚠ 除外された呪文は**手札に入れません**（★ここで落とすので、
    --   下流（`actions.lua`）は今までどおり「持っているものから選ぶ」だけで済みます）。
    if s ~= nil and (s.mp or 0) <= (member.mp or 0) and allowed(cat, strategy, sid) then
      local avg = (s.base or 0) + (s.delta or 0) / 2
      if s.kind == "heal" then
        out.heal[#out.heal + 1] = s
        if s.base == 255 then avg = member.hp_max or 255 end       -- ★ベホマ = 全快
        if avg > out.heal_power then out.heal_power = avg end
      elseif s.kind == "revive" then
        out.revive[#out.revive + 1] = s
      elseif s.kind == "attack" then
        out.attack[#out.attack + 1] = s
        if avg > out.magic_power then out.magic_power = avg end
      elseif s.kind == "instant" and s.effect == BEAT_EFFECT then
        -- ★即死（ザキ / ザラキ / RX3-0322）。⚠ 見込みは「効く確率 × 残り HP」（`Actions.spell_effect`）
        out.instant[#out.instant + 1] = s
      elseif s.kind == "instant" and s.effect == "robmagic" then
        -- ★マホトラ（RX3-0260）: ⚠ 役割ではなく**実際に覚えているか**（★転職で誰でも覚えうる / 指示書 §6）
        -- ⚠⚠ ここでは**足しません**（★上の「禁止でも入れる」ひと回りが済ませています / RX3-0348）。
        --   ⚠ 両方で足すと**二重**になります。
      elseif SUPPORT_KINDS[s.kind] or (s.kind == "instant" and SUPPORT_EFFECTS[s.effect or ""]) then
        out.support[#out.support + 1] = s
      end
    end
  end
  return out
end

--- ★★ 「資源を使わない回復」を**持っている人**の一覧（RX3-0417 / 2026-09-23）。
--
--   ⚠⚠ **DQ3 では、道具は持ち主しか使えません**（★パーティに石がある、ではない）。
--     → ★誰が持っているかを**席の配り方にも**渡します（依頼者 §9）。
--
--   ⚠ 予防の経路（`heals == 0`）と通常の経路（`heals > 0`）で、
--     ★**同じ関数から**候補を取ります（依頼者 §7・§15。⚠ 2 か所に書かない）。
--
--   ★並び: **全体回復 → 単体回復**（依頼者 §12。⚠ 石は 1 手で何人も戻せる）。
--     ⚠⚠ **新しい数値ボーナスは作りません**（★依頼者 §3・§4。`heal / MP` も使わない
--       ― MP 0 で無限大になり、★弱い無料回復を過大評価します）。
--
--   ⚠ 動けない人は入れません（★依頼者 §33。`caps.blocked`）。
--   ⚠ 使える職業かどうかは `Roles.heal_items` が ROM の `use_mask` で見ています（★§34）。
--   ⚠ 「資源を使わない」の判定は `Roles.resource_free` の 1 か所だけ（★§35）。
--
--   戻り値: `{ {slot=, action=, scope="party"|"single", heal=, consumed=, mp=}, ... }`
function Roles.free_heal_candidates(sit, caps_by_slot)
  if Actions == nil or Actions.free_heal_of == nil then return {} end
  local party, single = {}, {}
  for _, m in ipairs((sit or {}).alive or {}) do
    local caps = (caps_by_slot or {})[m.slot]
    if caps ~= nil and not caps.blocked then
      local s = Actions.free_party_heal(caps)
      local scope, into = "party", party
      if s == nil then
        s = Actions.free_heal_of(caps, Actions.SINGLE_HEAL_TARGET)
        scope, into = "single", single
      end
      if s ~= nil then
        into[#into + 1] = {slot = m.slot, action = s, scope = scope,
                           heal = (s.base or 0) + (s.delta or 0) / 2,
                           consumed = s.consumed == true, mp = tonumber(s.mp) or 0}
      end
    end
  end
  local out = {}
  for _, row in ipairs(party) do out[#out + 1] = row end
  for _, row in ipairs(single) do out[#out + 1] = row end
  return out
end

--- ★候補の名前（⚠ ログ用。★道具は道具の名前で）
function Roles.free_heal_name(row)
  local s = (row or {}).action
  if s == nil then return "none" end
  return s.item_name or ("道具" .. tostring(s.item_id))
end

--- ★その役割ができるか。
function Roles.can(caps, role)
  if role == Roles.PHYSICAL or role == Roles.DEFEND then return true end
  if role == Roles.HEAL then return #caps.heal > 0 or caps.herb end
  -- ★道具の攻撃（まどうしのつえ など）を持っていれば魔法の役もできる（RX3-0213）
  if role == Roles.MAGIC then
    return #caps.attack > 0 or #(caps.attack_items or {}) > 0 or #(caps.instant or {}) > 0
  end
  if role == Roles.SUPPORT then return #caps.support > 0 end
  return false
end

local function label(kind)
  return ({mop = "消化戦", advantage = "優勢", even = "均衡", disadvantage = "劣勢"})[kind] or kind
end

--- ★★ 回復の線 ― **ここが唯一の実装**（RX3-0429 / P-5 / 2026-09-24）★★
--
-- ## ⚠⚠ 線が 2 本あると、役割と行動で違うことを言います
--
--   ★2026-09-24 まで、⚠ **役割の側**は MP 方針と消化戦で線を下げ、
--     ★**行動の側**（`actions.lua`）は `heal_at` を**そのまま**使っていました。
--
--   ```text
--   生存優先 ＋ MP 半分程度残す
--     役割側 heal_line = min(0.60, 0.30) = 0.30 → ⚠ HP 40% には回復の役を作らない
--     行動側 heal_at   = 0.60                    → ⚠ 同じ人を `wanted` に数える
--   → ⚠⚠ 「回復は要らない」と決めた人を、★全体回復の要否では数えていた
--   ```
--
--   → ★線を引くのは**この関数だけ**にします（⚠ `actions.lua` もここを呼ぶ）。
--
-- ⚠ 防御戦術の無料回復は**この線を通りません**（★`defensive_formation` が別に決める / 依頼者 §15）。
function Roles.heal_line(ctx, sit)
  local t = (ctx or {}).tuning or {}
  local strategy = (ctx or {}).strategy or Roles.ECONOMY
  local policy = (ctx or {}).mp_policy or Roles.MP_AUTO
  local critical = tonumber(t.critical_hp) or 0.15
  local line = tuned(t, "heal_at", strategy, 0.35)
  -- ★MP 温存は「危ない」まで回復を待つ。使用禁止は瀕死だけ（やくそう）
  if policy == Roles.MP_SAVE then line = math.min(line, tonumber(t.danger_hp) or 0.3) end
  if policy == Roles.MP_FORBID then line = critical end
  if ((sit or {}).kind) == "mop" then line = math.min(line, critical) end  -- ★消化戦は回復しない
  return line
end

--- ★★ 防御戦術の陣形（RX3-0429 / 2026-09-24 / 依頼者 §3〜§11）★★
--
-- ⚠⚠ **通常の回復 need の結果として無料回復を選ぶのではありません。**
--   ★防御戦術では、無料回復を**戦術固有の上位ルール**として先に置きます。
--
--   ```text
--   1 けんじゃのいし   ★誰か 1 人でも HP < 最大 なら（⚠ 予防回復）
--   2 ちからのたて     ★**本人**が HP < 最大 なら（⚠ 自己回復）
--   3 攻撃役 1 名      ★無料回復を担当しない中で、物理攻撃力が最大の人
--   4 その他           ★防御（⚠ ぼうぎょ が窓に無ければ たたかう）
--   ```
--
-- ## ⚠ 新しい閾値は作りません
--
--   ★「1 ポイントでも減っていれば対象」です（依頼者 §4-1）。
--   ⚠ 「平均 HP ○%」「誰かが ○% 以下」のような線は**足しません**。
--   ⚠ 全員が満タンなら石も盾も使いません。
--
-- ## ★石と盾
--
--   ⚠ 同じ人が両方持っていれば **石を優先**（依頼者 §8）。
--     ★`free_heal_candidates` が全体回復を先に返すので、⚠ ここで並べ替えません。
--   ★別の人なら**同じターンに両方**使ってよい（依頼者 §7 / ⚠ 差し引きの最適化はしない）。
--
-- ## ⚠ 危険域はここでは見ません（依頼者 §12）
--
--   ★死者・HP 1/4・劣勢は **Auto の安全弁**（`battle_speed.lua` の窓の色）が先に
--   人へ返します。⚠ ここに「危険なら攻撃役を外す」等を足さないこと。
--
-- @return `needs, defend_slots, why`（⚠ 防御戦術でなければ `nil`）
function Roles.defensive_formation(ctx, sit, caps_by_slot, plan)
  if (ctx.strategy or "") ~= Roles.SURVIVAL then return nil end
  local needs, defend_slots, why = {}, {}, {}
  local alive = (sit or {}).alive or {}
  local n_alive = #alive
  if n_alive == 0 then return nil end

  local by_slot = {}
  for _, m in ipairs(alive) do by_slot[m.slot] = m end
  local function hurt(m)
    return m ~= nil and (m.hp or 0) < (m.hp_max or 0)
  end
  --: ★誰か 1 人でも減っているか（⚠ 1 ポイントでも）
  local anyone_hurt = false
  for _, m in ipairs(alive) do
    if hurt(m) then anyone_hurt = true end
  end

  local taken = {}
  -- ① / ② 無料回復（★全体が先 → 単体。⚠ 並びは `free_heal_candidates` のまま）
  local worst = (Actions ~= nil and Actions.most_hurt ~= nil) and Actions.most_hurt(sit) or nil
  for _, row in ipairs(Roles.free_heal_candidates(sit, caps_by_slot)) do
    local me = by_slot[row.slot]
    local want = (row.scope == "party") and anyone_hurt or hurt(me)
    local name = Roles.free_heal_name(row)
    if taken[row.slot] then
      -- ⚠ 同じ人が両方持っていた（★石を先に取っているので、ここは盾）
      why[#why + 1] = string.format(
        "AI defensive_free actor=%s item=%s scope=%s decision=skip reason=already_free_heal",
        row.slot, name, row.scope)
    elseif not want then
      why[#why + 1] = string.format(
        "AI defensive_free actor=%s item=%s scope=%s decision=skip reason=%s",
        row.slot, name, row.scope,
        (row.scope == "party") and "party_full_hp" or "self_full_hp")
    elseif #needs >= n_alive then
      why[#why + 1] = string.format(
        "AI defensive_free actor=%s item=%s scope=%s decision=skip reason=no_room",
        row.slot, name, row.scope)
    else
      taken[row.slot] = true
      needs[#needs + 1] = {
        role = Roles.HEAL, job = "heal", only = row.slot, proactive = true,
        -- ★★ どの無料回復を出すかを**名指し**で渡す（⚠ `Actions.heal` が読む）
        free_scope = row.scope, free_heal = name, _free_row = row,
        target = (row.scope == "party") and ((worst and worst.slot) or row.slot) or row.slot,
        why = string.format("%s が %s（防御戦術の無料回復 / %s）", row.slot, name,
                            (row.scope == "party") and "全体" or "自分"),
      }
      why[#why + 1] = string.format(
        "AI defensive_free actor=%s item=%s scope=%s decision=use reason=%s",
        row.slot, name, row.scope,
        (row.scope == "party") and "someone_hurt" or "self_hurt")
    end
  end

  -- ③ ★★ 通常回復を **1 名だけ**（RX3-0429 追補 / 2026-09-24 / 依頼者 §1・§3）
  --
  --   ⚠⚠ ①② を割り当てても**まだ線を割っている人が残る**ときだけです。
  --     ★無料回復が先（⚠ 石より先に ベホイミ、へは戻しません）。
  --
  --   ★足りるかの判断は**既存のもの**を使います（⚠ 新しい予測は作らない / 依頼者 §4）:
  --     `plan:reserve_healing`（無料回復で戻るぶんを予約）
  --     `plan:hp_after_reserved_healing`（予約を足した HP）
  --     `Roles.heal_line`（P-5 で 1 本にした線）
  --
  --   ⚠ MP 方針・legality はここでは見ません。★`Actions.heal` と `Legality.check` が
  --     今までどおり守ります（⚠ 迂回する別経路を作らない / 依頼者 §2）。
  local line = Roles.heal_line(ctx, sit)
  if plan ~= nil then
    -- ★無料回復で戻るぶんを予約（⚠ 全体は全員へ / 単体は本人へ）
    for _, need in ipairs(needs) do
      local row = need._free_row
      if row ~= nil then
        if row.scope == "party" then
          for _, m in ipairs(alive) do plan:reserve_healing(m.slot, row.heal) end
        else
          plan:reserve_healing(row.slot, row.heal)
        end
      end
    end
  end
  local short = nil
  for _, m in ipairs(alive) do
    local hp = m.hp or 0
    if plan ~= nil then hp = plan:hp_after_reserved_healing(m.slot, m.hp, m.hp_max) end
    local ratio = hp / math.max(m.hp_max or 1, 1)
    if ratio < line and (short == nil or ratio < short.ratio) then
      short = {member = m, ratio = ratio}
    end
  end
  if short ~= nil and #needs < n_alive then
    -- ⚠⚠ **誰が回復するかをここで決めます**（★席を空けたままだと、攻撃役の選抜と
    --   同じ人を取り合い、⚠ 結果として**攻撃役が居なくなります**（2026-09-24 に踏んだ））。
    --   ★選ぶのは「回復できる人のうち、**攻撃力がいちばん小さい**人」。
    --   ⚠ 攻撃力が大きい人は ④ の攻撃役に残します（★依頼者 §5 の DF-R）。
    --   ⚠ 同値は slot の小さいほう（★毎回同じ結果にする）。
    local healer = nil
    for _, m in ipairs(alive) do
      local caps = caps_by_slot[m.slot]
      if not taken[m.slot] and caps ~= nil and not caps.blocked
          and Roles.can(caps, Roles.HEAL) then
        local a = tonumber(m.attack) or 0
        local b2 = healer and (tonumber(healer.attack) or 0) or nil
        if healer == nil or a < b2
            or (a == b2 and tostring(m.slot) < tostring(healer.slot)) then
          healer = m
        end
      end
    end
    if healer ~= nil then
      taken[healer.slot] = true
      needs[#needs + 1] = {
        role = Roles.HEAL, job = "heal", target = short.member.slot,
        only = healer.slot,
        why = string.format("%s が %s を回復（防御戦術 / 無料回復だけでは %d%% に届かない）",
                            healer.slot, short.member.slot, math.floor(line * 100 + 0.5)),
      }
      why[#why + 1] = string.format(
        "AI defensive_heal_extra actor=%s target=%s ratio=%.2f line=%.2f"
        .. " decision=use reason=not_enough_free",
        healer.slot, short.member.slot, short.ratio, line)
    else
      why[#why + 1] = string.format(
        "AI defensive_heal_extra target=%s ratio=%.2f line=%.2f decision=skip reason=no_healer",
        short.member.slot, short.ratio, line)
    end
  else
    why[#why + 1] = string.format(
      "AI defensive_heal_extra target=none line=%.2f decision=skip reason=%s", line,
      (short == nil) and "free_heal_is_enough" or "no_room")
  end

  -- ④ ★攻撃役を 1 名（⚠ 無料回復・通常回復の担当は除く / ★物理攻撃力が最大 / 同値は slot 順）
  local best = nil
  for _, m in ipairs(alive) do
    local caps = caps_by_slot[m.slot]
    if not taken[m.slot] and caps ~= nil and not caps.blocked then
      local a, b = tonumber(m.attack) or 0, best and (tonumber(best.attack) or 0) or -1
      -- ⚠ 同値は slot の小さいほう（★毎回同じ結果にする / 依頼者 §9）
      if best == nil or a > b or (a == b and tostring(m.slot) < tostring(best.slot)) then
        best = m
      end
    end
  end
  if best ~= nil then
    taken[best.slot] = true
    needs[#needs + 1] = {role = Roles.PHYSICAL, only = best.slot,
                         why = string.format("%s が攻撃（防御戦術 / 攻撃力 %s が最大）",
                                             best.slot, tostring(best.attack or 0))}
    why[#why + 1] = string.format(
      "AI defensive_attacker actor=%s attack=%s reason=strongest_remaining",
      best.slot, tostring(best.attack or 0))
  end

  -- ⑤ ★残りは防御（⚠ ぼうぎょ が窓に無ければ たたかう / `auto_v0` の fallback）
  for _, m in ipairs(alive) do
    if not taken[m.slot] then
      defend_slots[m.slot] = "防御戦術"
    end
  end
  return needs, defend_slots, why
end

--- ★戦況 × 作戦 → 必要な役割の列。
--
--   `sit` … `Situation.assess` の戻り値
--   `caps_by_slot` … `Roles.caps` を人ごとに
--   `plan` … DQ2 の `party_plan`（★回復の予約に使う。⚠ nil でもよい）
--   `magic` … `Actions.magic_outlook` の戻り値（★RX3-0198 / ⚠ nil なら魔法の役を作らない）
function Roles.needed(ctx, sit, caps_by_slot, plan, magic)
  local t = ctx.tuning or {}
  local strategy = ctx.strategy or Roles.ECONOMY
  local policy = ctx.mp_policy or Roles.MP_AUTO
  local heal_at = tuned(t, "heal_at", strategy, 0.35)
  local danger = tonumber(t.danger_hp) or 0.3
  local critical = tonumber(t.critical_hp) or 0.15
  local support_min = tuned(t, "support_min_turns", strategy, 3)
  local kind = sit.kind
  local n_alive = #sit.alive
  local needs, why = {}, {}

  -- ★★ 防御戦術は**専用の陣形**で決める（RX3-0429 / 依頼者 §3〜§11）。
  --   ⚠ 石 / 盾 / 攻撃 1 名 / 残りは防御。★通常の回復 need の線（`heal_line`）は通しません。
  if strategy == Roles.SURVIVAL then
    local d_needs, d_defend, d_why = Roles.defensive_formation(ctx, sit, caps_by_slot, plan)
    if d_needs ~= nil then return d_needs, d_defend, d_why end
  end

  -- ★線を引くのは `Roles.heal_line` の 1 か所だけ（RX3-0429 / P-5）。
  --   ⚠ ここに式を写すと、★行動の側（`actions.lua`）と**また食い違います**。
  local heal_line = Roles.heal_line(ctx, sit)
  -- ⚠⚠ 2026-09-21（RX3-0327 §9-1）: ここに「このターンで終わるなら回復しない」を
  --   書きかけましたが、★**死んだコードでした**（壊す実験が緑のまま）。
  --   理由: `phys_rounds <= 1` になる場面は、ほぼそのまま `kind == "mop"` です
  --   （★`short_turns = 2` / 上の行が既に `critical` まで下げている）。
  --   → ★回復を遅らせるのは **`heal_at` の値 1 本**で行います（`generate.py` の TUNING）。

  -- ★パーティで出せる回復の目安（⚠ 予約に使う。誰が回復するかは割当で決まる）
  local best_heal, can_revive, anyone_heals = 0, false, false
  for _, caps in pairs(caps_by_slot) do
    if caps.heal_power > best_heal then best_heal = caps.heal_power end
    if #caps.revive > 0 then can_revive = true end
    if Roles.can(caps, Roles.HEAL) then anyone_heals = true end
  end
  if best_heal == 0 and anyone_heals then best_heal = tonumber(t.item_heal) or 30 end

  -- ① 死者の蘇生（⚠ 使用禁止では作れない。★呪文しか無い）
  if can_revive and policy ~= Roles.MP_FORBID and kind ~= "mop" then
    for _, m in ipairs(sit.dead) do
      needs[#needs + 1] = {role = Roles.HEAL, job = "revive", target = m.slot,
                           why = string.format("%s が倒れている", m.slot)}
    end
  end

  -- ② 怪我人の回復（★比率の小さい順。⚠ 予約した回復を差し引いて重ねない / §9）
  --
  -- ★★ 2026-09-23（RX3-0417）: **リソース節約では、席を「無料の手を持つ人」へ**。
  --
  --   ⚠⚠ 実機で **62 MP** を払いました（★依頼者の save9）:
  --   ```text
  --   AI 必要=ヒール→p2 ヒール→p1 魔法 魔法    ⚠ 石を持つ p3 は「魔法」へ
  --   AI p1 役割=ヒール do=spell:ベホマズン      ⚠ 62 MP
  --   ★けんじゃのいし は p3 の袋にあり、⚠ p1 の hand には入らない（＝候補にすらならない）
  --   ```
  --   ★`RX3-0411` の「席が回れば無料を選ぶ」は出来ていて、⚠ **席の配り方だけ**が
  --     無料の手を見ていませんでした（`score(caps, HEAL)` は `heal_power` だけ）。
  --
  --   ⚠⚠ **`score` は変えません**（★最短撃破・生存優先へ波及する / 依頼者 §2）。
  --     → ★economy のときだけ、⚠ 既に在る `need.only`（`RX3-0398` の持ち主拘束）を
  --       通常の席にも使います。⚠ 新しい定数もボーナスも作りません（★§3）。
  --
  --   ⚠ 席より持ち主が少なければ、★余った席は**今までどおり**配ります（§17・§31）。
  local free_seats = {}
  if strategy == Roles.ECONOMY then
    free_seats = Roles.free_heal_candidates(sit, caps_by_slot)
  end
  local seat_at = 0
  local heals = 0
  for _, inj in ipairs(sit.injured) do
    local m = inj.member
    local hp = m.hp
    if plan ~= nil then hp = plan:hp_after_reserved_healing(m.slot, m.hp, m.hp_max) end
    local ratio = hp / m.hp_max
    if anyone_heals and ratio < heal_line and heals < 2 and #needs < n_alive then
      local need = {role = Roles.HEAL, job = "heal", target = m.slot,
                    why = string.format("%s HP %d/%d < %d%%", m.slot, m.hp, m.hp_max,
                                        math.floor(heal_line * 100 + 0.5))}
      seat_at = seat_at + 1
      local row = free_seats[seat_at]
      if row ~= nil then
        -- ⚠ 持ち主しか使えないので、★席をその人に固定します（`RX3-0398` と同じ作法）
        need.only = row.slot
        need.free_heal = Roles.free_heal_name(row)
        need.why = need.why .. string.format("（%s %s）", row.slot, need.free_heal)
        why[#why + 1] = string.format(
          "AI role_assign role=heal actor=%s reason=economy_free_heal_holder item=%s"
          .. " scope=%s heal=%d mp=%d",
          row.slot, need.free_heal, row.scope, math.floor(row.heal + 0.5), row.mp)
      end
      needs[#needs + 1] = need
      if plan ~= nil then plan:reserve_healing(m.slot, best_heal) end
      heals = heals + 1
    end
  end

  -- ②' ★★ 予防の無料回復（RX3-0398 / 2026-09-23 / 相談相手「けんじゃのいし proactive 化」）。
  --
  --   ⚠⚠ **`heal_at` を割っていない場面だけ**です（★§15）。
  --     ★誰かが線を割っていれば、⚠ 上の ② が既に役を作っています。
  --     → ⚠ 緊急の回復を**上書きしません**（★§14）。
  --
  --   ★判断は「無料の全体回復 1 手」と「攻撃 1 手」を**同じ尺度**で比べるだけ。
  --   ⚠⚠ **新しい HP の閾値は作っていません**（★90% なら戻る量が小さく、自然に攻撃が勝つ）。
  --
  --   ⚠ 誰に渡すか: ★**使える人の中で、攻撃の寄与がいちばん小さい人**（§10）。
  -- ★★ 2026-09-23（RX3-0420）: **消化戦でも無料の回復だけは見ます**。
  --
  --   ⚠⚠ 依頼者の手動テストで、★**8 戦 22 手番のうち 18 手番が消化戦**でした。
  --     ⚠ 消化戦は `heal_line` が `critical`(0.15) まで下がるので `heals == 0` になり、
  --     ★さらにここの `kind ~= "mop"` で止まって、⚠ **無料の回復を 1 度も見ません**。
  --     → ⚠ HP が 42% → 16% まで落ちても戦闘間で戻さず、★最後は安全停止でした。
  --
  --   ★開けるのは**この門だけ**です（⚠ 依頼者 §3）:
  --   ```text
  --   ⚠ `heal_line` は触らない          → ★有料の回復は消化戦で復活しない（§27）
  --   ★`proactive_heal` は economy 専用   → ⚠ ほかの作戦へ漏れない（§18・§19）
  --   ★`proactive_heal` は無料の手だけ    → ⚠ `resource_free` のみ（§2）
  --   ★軽傷は `too_shallow` で落ちる      → ⚠ 乱発しない（§7・§26）
  --   ★席は `need.only = 持ち主`          → ⚠ `RX3-0417` の仕組みを再利用（§21）
  --   ★要らなければ need を作らない        → ⚠ マホトラ・攻撃が今までどおり残る（§10・§11）
  --   ```
  local mop_free_ok = (strategy == Roles.ECONOMY)
  -- ★門を通らなかったときも 1 行だけ残す（⚠ 「0 行 = 効いていない」と読み違えないため）
  if Actions ~= nil and Actions.proactive_heal ~= nil
      and not (heals == 0 and (kind ~= "mop" or mop_free_ok) and #needs < n_alive) then
    -- ⚠⚠ **誰が無料の回復を持っていたか**を添えます（RX3-0415 / 2026-09-23）。
    --   ★門で止まった手番では 1 人も評価しないので、⚠ このままだと
    --     「そもそも持っていない」のか「持っていたが場面ではない」のかが**読めません**。
    --   ★依頼者の手動テストは実際に 22 手番のうち 18 手番がここで止まっており、
    --     ⚠ けんじゃのいし を持つ人が居たことがログに**1 文字も残っていません**でした。
    -- ⚠ 持ち主の調べ方は `Roles.free_heal_candidates` の**1 か所だけ**（RX3-0417 / §7・§15）
    local have = {}
    for _, row in ipairs(Roles.free_heal_candidates(sit, caps_by_slot)) do
      have[#have + 1] = row.slot
    end
    why[#why + 1] = string.format(
      "AI proactive_heal actor=none item=none decision=skip reason=%s holders=%s",
      (heals > 0 and "heal_needed")
      or (kind == "mop" and not mop_free_ok and "mop") or "no_room",
      #have > 0 and table.concat(have, ",") or "none")
  end
  if heals == 0 and Actions ~= nil and Actions.proactive_heal ~= nil
      and (kind ~= "mop" or mop_free_ok) and #needs < n_alive then
    local pick, pick_info = nil, nil
    -- ⚠⚠ **見送った理由も残します**（RX3-0404 / 2026-09-23）。
    --   ★以前は `use` のときしか 1 行も出ず、⚠ 実機で 0 行だったとき
    --     「場面が来ていない」のか「比べて負けた」のか**区別できません**でした。
    --
    -- ⚠⚠ 2026-09-23 訂正（RX3-0415）: ★**1 人分しか残していませんでした**。
    --   ★`sit.alive` 全員に `proactive_heal` を呼んでいるのに、⚠ 出すのは
    --     採用 1 行か、見送り 1 行だけ。→ ⚠⚠ **持ち主の理由が消えます**。
    --
    --   ```text
    --   ★実機（2026-09-23 19:22 / 依頼者の手動テスト）
    --   AI proactive_heal actor=p2 scope=single item=ちからのたて … reason=attack_is_better
    --   ⚠ けんじゃのいし を持つ p3 の理由は**1 行も出ない**
    --   → ⚠⚠ 依頼者が「なぜ石を使わないのか」をログから読めなかった
    --   ```
    --
    --   → ★**道具を持っている人は全員**残します。⚠ 持っていない人は数だけ。
    local holders = {}                       -- ★無料の回復を持っている人の見送り理由
    local empty = 0                          -- ⚠ そもそも持っていない人の数
    for _, m in ipairs(sit.alive) do
      local caps = caps_by_slot[m.slot]
      if caps ~= nil and not caps.blocked then
        local ok, info = Actions.proactive_heal(m, caps, ctx, sit)
        if ok and (pick_info == nil or info.attack_gain < pick_info.attack_gain) then
          pick, pick_info = m, info
        elseif info ~= nil then
          -- ⚠ `no_free_party_heal` / `not_economy` は「持っていない」なので数だけ
          local weak = info.why == "no_free_party_heal" or info.why == "not_economy"
          if weak then
            empty = empty + 1
          else
            holders[#holders + 1] = {slot = m.slot, info = info}
          end
        end
      end
    end
    -- ★持ち主の理由は**全員分**（⚠ 採用された人はこの後 `use` で出す）
    for _, row in ipairs(holders) do
      if pick == nil or row.slot ~= pick.slot then
        why[#why + 1] = Actions.proactive_tune(row.slot, row.info, "skip")
      end
    end
    -- ⚠⚠ 1 行も出ないまま終わらせない（★「0 行 = 効いていない」と読み違えないため）
    if pick == nil and #holders == 0 then
      why[#why + 1] = string.format(
        "AI proactive_heal actor=none item=none decision=skip reason=no_free_party_heal"
        .. " holders=0 checked=%d", empty)
    end
    if pick ~= nil then
      -- ⚠⚠ `target` は**いちばん減っている人**にします（★`Actions.heal` が
      --   そこから「足りるか」を測るため）。⚠ 使い手を指すと、★本人が満タンのとき
      --   「欠け 0」と見て**安い単体回復**になってしまいます（2026-09-23 に踏んだ）。
      -- ⚠ 規則は `Actions.most_hurt` の 1 か所だけ（★ここに写さない / RX3-0411）
      local worst = Actions.most_hurt(sit)
      needs[#needs + 1] = {role = Roles.HEAL, job = "heal",
                           target = (worst and worst.slot) or pick.slot,
                           only = pick.slot, proactive = true,
                           why = string.format("%s が %s（無料 / 得 %.2f 対 攻撃 %.2f）",
                                               pick.slot, tostring(pick_info.item),
                                               pick_info.stone_gain, pick_info.attack_gain)}
      -- ⚠⚠ **回復の予約はしません**（★2026-09-23 / 壊す実験が緑のままでした）。
      --   ★予約が効くのは ③（瀕死は防御）の `reserved_healing` ですが、
      --   ⚠ 瀕死の人が居れば ② が役を作るので `heals == 0` が成り立たず、
      --     ★ここへは**来ません**。→ ⚠ 置いても**誰も読まない**行でした。
      --   ⚠ 予防の回復は 1 ターンに 1 つだけ作るので、二重予約も起きません。
      -- ⚠ `heals` も足しません（★ここより後で**誰も読みません** / 2026-09-23 の壊す実験）。
      why[#why + 1] = Actions.proactive_tune(pick.slot, pick_info, "use")
    end
  end

  -- ③ 瀕死は防御して耐える（★劣勢は必ず。均衡は**回復が来ないとき**だけ。
  --   ⚠ 消化戦・優勢では回復のほうが早い）
  --   ★2026-09-08 実機（セーブ 4 / MP 使用禁止 / やくそう無し）: HP 1/19 の人が均衡で殴りに行った
  local defend_slots = {}
  -- ★★ 最短撃破: **防御で 1 手を捨てるより、攻撃で終わらせる**（RX3-0327 §9-2）。
  --   ⚠ 依頼者「HPが低い → 自動的に防御 を強くしすぎない」
  --   ★劣勢のときは今までどおり守ります（⚠ 危険時の安全網は残す）。
  local defend_kinds = (strategy == Roles.LEVELING) and {disadvantage = true}
                       or {disadvantage = true, even = true}
  if defend_kinds[kind] then
    for _, inj in ipairs(sit.injured) do
      local healed = plan ~= nil and (plan.reserved_healing[inj.slot] or 0) > 0
      if inj.ratio < critical and n_alive >= 2 and (kind == "disadvantage" or not healed) then
        defend_slots[inj.slot] = true
        why[#why + 1] = inj.slot .. " は瀕死なので防御"
      end
    end
  end

  -- ★防御に固定した人のぶんは need を作らない（⚠ 作ると「物理ができる人が居ない」と嘘を言う）
  local cap = n_alive
  for _ in pairs(defend_slots) do cap = cap - 1 end
  while #needs > cap do table.remove(needs) end

  -- ④ 支援（★長引く戦いで元が取れるときだけ / ⚠ 使用禁止では作らない）
  local long_enough = (sit.win or 0) >= support_min
  local want_support = false
  if policy == Roles.MP_AUTO then
    if strategy == Roles.LEVELING then
      want_support = kind == "disadvantage" and long_enough          -- ★火力優先（§3）
    elseif strategy == Roles.ECONOMY then
      want_support = long_enough and (kind == "even" or kind == "disadvantage")
    else
      want_support = (kind == "even" and long_enough) or kind == "disadvantage"
    end
  elseif policy == Roles.MP_SAVE then
    want_support = kind == "disadvantage" and long_enough
  end
  if want_support and #needs < cap then
    needs[#needs + 1] = {role = Roles.SUPPORT, why = string.format("%s / %.1fT かかる", label(kind), sit.win or 0)}
  end

  -- ⑤ 魔法攻撃（★RX3-0198: 作戦の名前ではなく、唱えられる人ごとの見立て `magic` で決める）
  --
  --   ⚠⚠ 2026-09-12 までは「おまかせ ＋ 敵 2 体以上 ＋（速攻は消化戦以外 / 生存は均衡・劣勢）」で、
  --     ★節約は作らず、⚠ 敵 1 体では誰も作らなかった（依頼者「速攻でも結構魔術師が魔法使わない」）。
  --   ★いまは `Actions.magic_outlook` が「何ターン短くなるか」を作戦ごとの重みで見て、
  --     撃つと決めた人（`magic.use`）が居るときだけ 1 つ作る（★1 ターンに 1 つまで / 今までどおり）。
  --   ⚠ MP 制約は作戦より上: 使用禁止は候補が 0、半分程度残す（温存）は床より上の呪文だけ。
  --   ⚠ `casters` … この役を渡してよい人（★見立てで「撃つ」の人だけ。⚠ 渡したのに物理、を作らない）
  --   ★RX3-0213: 道具の攻撃（まどうしのつえ など）は MP を使わない → ★使用禁止でもこの役を作る。
  --     ⚠ 使用禁止で渡すのは、見立ての候補が道具の人だけ（★呪文の人には渡さない）
  local casters, why_magic = {}, nil
  local n_use = 0
  local free_slots = {}                 -- ★枠を使わない人（⚠ 下で必ず役を作る）
  -- ★★ その席に座れる人（⚠ **無料の手を持つ人だけ** / RX3-0407 / 2026-09-23）。
  --
  --   ⚠⚠ 実機で、⚠ 無料の手のために作った席を**有料の呪文の人が取っていました**:
  --   ```text
  --   AI 必要=魔法 魔法 物理 物理        ★economy は magic_slots = 1
  --   p3 役割=魔法 ヒャダイン 9 MP       ⚠ 席は無料の手のために作ったもの
  --   p4 役割=魔法 ヒャダイン 9 MP       ⚠⚠ 有料が 1 ターンで 2 発
  --   p1 おうじゃのけん / p2 いなづまのけん → ★物理にされた
  --   ```
  --   ★`assign` は `need.casters` しか見ません（⚠ `need.free` は読みません）。
  --     → ★席ごとに**候補の表そのものを分ける**（⚠ `need.only` と同じ作法）。
  local free_casters = {}
  for slot in pairs((magic or {}).use or {}) do
    local ev = magic.by_slot[slot]
    local s = ev ~= nil and ev.spell or nil
    local free = Roles.resource_free(s)
    if policy ~= Roles.MP_FORBID or free then
      casters[slot] = true
      -- ⚠⚠ **資源を使わない手は枠に数えません**（RX3-0396 / 2026-09-23）。
      --   ★`MAGIC_SLOTS` は「**MP を使う攻撃手段**を抑える」ための代理ルールです
      --     （⚠ 註に「MP を残す」と書いてある）。
      --   ⚠⚠ 実測（`RX3-0395`）: ★得が 2 倍近い無料の道具が、
      --     **枠が無いだけで**落ちていました:
      --   ```text
      --   p1 ベギラマ       gain= 9.35 mp=6 → ★use
      --   p2 いなづまのけん gain=17.53 mp=0 → ⚠⚠ skip: assigned_other_role:physical
      --   ```
      if free then
        free_slots[#free_slots + 1] = slot
        free_casters[slot] = true
      else
        n_use = n_use + 1
      end
      if ev ~= nil and (why_magic == nil or slot < why_magic.slot) then why_magic = ev end
    end
  end
  -- ★★ ⚠⚠ 魔法の役は長らく **1 ターンに 1 人だけ**でした（RX3-0323 / 2026-09-20）。
  --
  --   ⚠ 依頼者の実機ログ（save1 / クラーゴン 3 体 / 速攻）:
  --
  --   ```text
  --   AI 必要=魔法 物理 物理 物理        ← ★魔法の枠が 1 つしかない
  --   p1 役割=魔法  ライデイン val=240   ★これが採用
  --   p2 役割=物理  ザキ      val=249   ⚠ skip: assigned_other_role:physical
  --   p3 役割=物理  ザキ      val=249   ⚠ skip
  --   p4 役割=物理  イオラ    val=126   ⚠ skip
  --   ```
  --
  --   ★見込みがいちばん大きい ザキ（249）が、⚠ **枠が無いだけ**で落ちていました。
  --   → ★**長い戦いの速攻**では、撃つと決まった人を **2 人まで**通します。
  --     ⚠ 短い戦い・節約・生存優先は今までどおり 1 人（★MP を無駄にしない）。
  -- ★枠の数は**作戦**が決める（RX3-0324 / ⚠ 誰に渡すかは下の `casters` と `assign`）
  local magic_slots = Roles.MAGIC_SLOTS[strategy] or Roles.MAGIC_SLOTS_DEFAULT
  local made = 0
  -- ★★ 資源を使わない手は**枠の外**で先に席を作ります（RX3-0396）。
  --   ⚠ `casters` は同じ表なので、★誰に渡すかは今までどおり `assign` が決めます。
  --   ⚠⚠ 歯止めは `judge_magic`（★`gain > 0` か `saved >= 1` でなければ候補に来ない）。
  for _ = 1, #free_slots do
    if #needs >= cap then break end
    needs[#needs + 1] = {role = Roles.MAGIC, casters = free_casters, free = true,
                         why = string.format("敵 %d 体 / %s / 資源を使わない手",
                                             sit.enemy_alive, label(kind))}
  end
  while n_use > made and made < magic_slots and #needs < cap do
    made = made + 1
    needs[#needs + 1] = {role = Roles.MAGIC, casters = casters,
                         why = string.format("敵 %d 体 / %s / %s", sit.enemy_alive, label(kind),
                                             tostring(why_magic and why_magic.reason))}
  end

  -- ⑥ 残りは物理攻撃
  while #needs < cap do
    needs[#needs + 1] = {role = Roles.PHYSICAL, why = label(kind)}
  end
  return needs, defend_slots, why
end

local TIER = {"第1", "第2"}

local function pref_rank(prefs, role)
  for i, r in ipairs(prefs or {}) do
    if r == role then return i end
  end
  return 3
end

local function score(caps, role, ev)
  if role == Roles.HEAL then return caps.heal_power + (caps.herb and 1 or 0) end
  if role == Roles.MAGIC then
    -- ★★ その場の見込み（`magic_outlook` の val）で選ぶ（RX3-0323）。
    --   ⚠⚠ `magic_power` は呪文の base/delta から作るので、★即死（ザキ）は **0** です。
    --     → ⚠ 見込み 249 の ザキ が、見込み 126 の イオラ に負けていました。
    if ev ~= nil and (ev.val or 0) > 0 then return ev.val end
    return caps.magic_power
  end
  if role == Roles.SUPPORT then return #caps.support end
  if role == Roles.PHYSICAL then return caps.physical end
  return 0
end

--- ★need をキャラへ割り当てる（★第1 → 第2 → 臨時 / ⚠ 1 人 1 役）。
--
--   戻り値: assignments[slot] = {role, job, target, tier, why}, unfilled = {need,...}
function Roles.assign(ctx, sit, needs, caps_by_slot, defend_slots, magic)
  local assigned, unfilled = {}, {}
  local roles_cfg = ctx.roles or {}
  -- ★行動傾向をどれだけ重く見るか（⚠ 最短撃破では実力で覆せる / RX3-0327 §7-2）
  local rank_weight = Roles.RANK_WEIGHT[ctx.strategy or ""] or Roles.RANK_WEIGHT_DEFAULT

  -- ★★ 行動できない人を先に外す（RX3-0135 / 2026-09-09 / 指示書 v1.1 §4 Phase 2）。
  --   ⚠⚠ ここで**治療の作戦までは持ちません**。★「役割を振らない」だけです。
  --   ⚠ 未観測（nil）は外しません（★憶測で回復役を外すほうが危ない / §12-2）。
  local blocked = {}
  for _, m in ipairs(sit.alive) do
    local why = Roles.blocked_by(m)
    if why ~= nil then
      blocked[m.slot] = why
      assigned[m.slot] = {role = Roles.DEFEND, tier = "臨時",
                          why = string.format("%s で動けない", why)}
    end
  end

  -- ⚠ 値が文字列なら**それが理由**（RX3-0429 / ★防御戦術は「瀕死」ではない）
  for slot, mark in pairs(defend_slots or {}) do
    if blocked[slot] == nil then
      assigned[slot] = {role = Roles.DEFEND, tier = "臨時",
                        why = (type(mark) == "string") and mark or "瀕死"}
    end
  end

  -- ★回復と蘇生を先に埋める（⚠ 手遅れにしない）。次に支援・魔法・物理
  local order = {}
  for _, need in ipairs(needs) do
    local prio = ({heal = 1, support = 2, magic = 3, physical = 4})[need.role] or 5
    if need.job == "revive" then prio = 0 end
    order[#order + 1] = {need = need, prio = prio}
  end
  table.sort(order, function(a, b) return a.prio < b.prio end)

  for _, entry in ipairs(order) do
    local need = entry.need
    local best, best_key = nil, nil
    for _, m in ipairs(sit.alive) do
      if assigned[m.slot] == nil then
        local caps = caps_by_slot[m.slot]
        local able = Roles.can(caps, need.role)
        if need.job == "revive" then able = #caps.revive > 0 end
        -- ★魔法の役は、見立てで「撃つ」と出た人にだけ渡す（RX3-0198 / ⚠ 役割の好みより先）。
        --   ⚠ 以前は第1 が「魔法」の人に渡り、その人の呪文が弱ければ物理に落ちていた
        if need.role == Roles.MAGIC and need.casters ~= nil then able = able and need.casters[m.slot] == true end
        -- ★★ 予防の無料回復は「**その道具を持っている人**」だけ（RX3-0398 / 相談相手 §9）。
        --   ⚠⚠ パーティに石がある、では渡しません（★持っていない人に渡すと空振りします）。
        if need.only ~= nil then able = able and need.only == m.slot end
        if need.role == Roles.HEAL and need.target == m.slot and need.job == "heal" then
          -- ★自分を回復するのも可（⚠ ただし他に居ればそちらを優先）
          able = able and true
        end
        if able then
          local rank = pref_rank(roles_cfg[m.slot], need.role)
          local self_penalty = (need.target == m.slot) and 1 or 0
          local ev = (need.role == Roles.MAGIC) and ((magic or {}).by_slot or {})[m.slot] or nil
          -- ★行動傾向は「制約」ではなく「重み」（RX3-0327 §7-2）。⚠ 最短撃破では弱くする
          local key = rank * rank_weight + self_penalty * 100
            - math.min(score(caps, need.role, ev), 99)
          if best == nil or key < best_key or (key == best_key and (m.index or 0) < (best.index or 0)) then
            best, best_key = m, key
          end
        end
      end
    end
    if best ~= nil then
      local rank = pref_rank(roles_cfg[best.slot], need.role)
      assigned[best.slot] = {role = need.role, job = need.job, target = need.target,
                             -- ⚠ 予防の無料回復かどうかを**そのまま運ぶ**（RX3-0398）
                             proactive = need.proactive,
                             -- ⚠⚠ 防御戦術が**名指しした**無料回復も運ぶ（RX3-0429）。
                             --   ★ここで落とすと、`Actions.heal` は名指しを知らずに
                             --   ⚠ 損得の式へ落ち、**別の手**を選びます（★実際に踏んだ）。
                             free_scope = need.free_scope, free_heal = need.free_heal,
                             tier = TIER[rank] or "臨時", why = need.why}
    else
      unfilled[#unfilled + 1] = need
    end
  end

  -- ★余った人は物理攻撃（⚠ 埋まらなかった need も物理で代える）
  for _, m in ipairs(sit.alive) do
    if assigned[m.slot] == nil then
      assigned[m.slot] = {role = Roles.PHYSICAL, tier = "余り", why = "手が空いた"}
    end
  end
  return assigned, unfilled
end

return Roles
