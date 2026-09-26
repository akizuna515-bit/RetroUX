-- 戦況（RX3-0126 / 2026-09-08）— ★指示書 §4 の 4 分類を、数字から決める。
--
-- ```text
-- 消化戦   すぐ終わり、崩れる心配が無い
-- 優勢     倒すほうが、崩れるより明らかに早い
-- 均衡     どちらとも言えない（⚠ 分からないときもここ。★安全側）
-- 劣勢     崩れるほうが早い / 死者が居る / 瀕死が居る
-- ```
--
-- ## ★DQ2 から継いだもの
--
--   - ダメージの目安 … `damage_estimate.lua` の `Damage.physical`（★同じ式）
--   - 境目の作法     … `battle_assessment.lua`（敵撃破ターン / 味方崩壊ターン / ±margin）
--
-- ## ⚠ ここは RAM を読まない
--
--   ★`ctx.party` と `ctx.enemies`（群ごとの id / n / hp / alive / def）だけを見る。
--   敵の能力は表（`cat.enemies`）から。⚠ 表に無い敵は「分からない」として均衡に倒す。
--
-- ## ★★ 物理の見込みの補正（RX3-0226 / 2026-09-13）
--
--   ```text
--   いまの守備力  g.def[k]（RAM $0520 / 1 体ずつ）… 敵の スクルト（行動 0x2D / 0x2E）で上がる
--                 ⚠ 無ければ表の守備力（★今までどおり）
--   マヌーサ      m.status.illusion == true … その人の物理 × 0.375（ROM: 乱数 < $A0 で空振り）
--                 ⚠ nil / false は 1.0（★今までどおり）
--   実測の比      ctx._observed.scale（pipeline が前のターンの減りから出す）/ ⚠ 無ければ 1.0
--   ```
--
--   ★3 つとも「人ごとの倍率」（`sit.phys_scale[slot]`）と「群ごとの守備力」（`g.def` / `g.defs`）に
--   まとめて、`actions.lua` の物理の見立て（`physical_avg` / `clear_rounds`）も同じ値を使う。

local Situation = {}

Situation.MOP = "mop"
Situation.ADVANTAGE = "advantage"
Situation.EVEN = "even"
Situation.DISADVANTAGE = "disadvantage"

local Damage = nil
--: ★Enemy Action Model v1（RX3-0359 / ⚠ **shadow**。★誰も読まない）
local Model = nil

function Situation.use_damage(module) Damage = module end

--- ★shadow のモデルを差し込む（⚠ 無ければ `g.threat_v1` を作らないだけ）。
function Situation.use_enemy_model(module) Model = module end

--: ★★ どちらの見積りを**本番の判断に使うか**（RX3-0371 / 依頼者 §22〜§25）。
--
--   ⚠⚠ **既定は必ず `legacy`**。★`v1` は製品の画面からは選べません（⚠ 内部・検査だけ）。
--
--   ```text
--   Stage 0  shadow のみ                ★いまここ（既定）
--   Stage 1  enemy_dpt / lose だけ v1
--   Stage 2  sit.kind も v1
--   Stage 3  最短撃破の支援評価を v1
--   Stage 4  リソース節約 v2
--   ```
--
--   ⚠ 一度に全部へ流しません（★戻せなくなる / 悪くなったとき原因を切り分けられない）。
--   ⚠⚠ いまは**この値を読む判断が 1 つもありません**（★置き場と切替の道だけ用意）。
Situation.LEGACY, Situation.V1 = "legacy", "v1"
Situation.enemy_model_mode = Situation.LEGACY

--- ★切り替える（⚠ 知らない値は `legacy` へ倒す / ★黙って v1 にしない）。
function Situation.use_mode(mode)
  Situation.enemy_model_mode = (mode == Situation.V1) and Situation.V1 or Situation.LEGACY
  return Situation.enemy_model_mode
end

local function avg_physical(attack, defense)
  if Damage == nil then return nil end
  local est = Damage.physical(attack, defense)
  return est and est.avg or nil
end

--: ★マヌーサ（幻）の人の物理が当たる率（RX3-0226）。⚠ ROM の事実（`generate.py` の TUNING と同じ値）:
--    JP bank 8 $96EC `LDA $073C,X / AND #$10 / BEQ / JSR 乱数 / CMP #$A0 / BCS` → (256 − 160) / 256
Situation.ILLUSION_HIT = 0.375
--: ★敵のいまの守備力の上限（JP bank 9 $889E: 上げた結果を 999 = $03E7 で頭打ち）
Situation.DEF_CAP = 999

--- ★その人の物理が当たる率（⚠ 状態が分からない / マヌーサでなければ 1.0 = 今までどおり）。
function Situation.hit_rate(member, tuning)
  local st = (member or {}).status
  if st == nil or st.illusion ~= true then return 1.0 end
  return tonumber((tuning or {}).illusion_hit_rate) or Situation.ILLUSION_HIT
end

--- ★生きている敵 1 体ずつのいまの守備力（★RAM）。⚠ 1 体でも欠けていれば nil（★表の値に倒す）。
local function current_defs(g, alive_ks)
  if g.def == nil or #alive_ks == 0 then return nil end
  local out = {}
  for _, k in ipairs(alive_ks) do
    local d = tonumber(g.def[k])
    if d == nil or d < 0 or d > Situation.DEF_CAP then return nil end
    out[#out + 1] = d
  end
  return out
end

--- ★生きている味方（⚠ HP 0 は死者。★状態 bit より確か）。
function Situation.alive(party)
  local out = {}
  for _, m in ipairs(party or {}) do
    if (m.hp or 0) > 0 and (m.hp_max or 0) > 0 then out[#out + 1] = m end
  end
  return out
end

function Situation.dead(party)
  local out = {}
  for _, m in ipairs(party or {}) do
    if (m.hp or 0) <= 0 and (m.hp_max or 0) > 0 then out[#out + 1] = m end
  end
  return out
end

--- ★敵の群を「残り HP / 体数 / 能力」つきで並べ直す。
--
--   `hp[k]`・`alive[k]` が届いていなければ、表の HP × 体数で見る（★上限側）。
--
--   ★`hps` … 生きている敵 1 体ずつの残り HP（★並びは窓の順 / RX3-0198）。
--     ⚠ 合計（`hp_sum`）だけでは「倒し過ぎの無駄」も「呪文で倒し切れるか」も分からない。
--   ★`first_hp` … **生きている**先頭の敵の HP（★単体の呪文・ルカニが当たる相手）。
--     ⚠⚠ 2026-09-12 まで `g.hp[1]` でした（RX3-0198 の疑い (d)）。★先頭が倒れた群では
--       0 を拾い、⚠ 単体の呪文（メラ）を「見込み 0」と見て**捨てていました**。
--   ★★ `def` … その群のいまの守備力（★生きている敵の平均 / RX3-0226）。`defs` は 1 体ずつ（`hps` と同じ並び）。
--     ★RAM の値（`g.def[k]`）が生きている全員ぶん届いたときだけ使う。⚠ 無ければ表の守備力（今までどおり）。
--     `base_def` … 表の守備力 / `def_changed` … RAM の値が表と違う（★スクルトで上がった / ルカニで下がった）
--   ★`measured` … 1 体ずつの HP を RAM から読めている（⚠ 表の HP で見ている群は実測に使わない）
function Situation.groups(enemies, cat)
  local out = {}
  for i, g in ipairs(enemies or {}) do
    local stats = (cat and cat.enemies or {})[g.id]
    local alive_n, hp_sum, unknown = 0, 0, false
    local hps, alive_ks = {}, {}
    --: ★生きている敵の状態（RX3-0268 / `hps` と同じ並び）。⚠ 分からなければその枠は nil
    local statuses = {}
    --: ★倒した数と、⚠ 敵が回復したくなるほど傷んでいるか（RX3-0368）。
    --  ⚠⚠ 1 体ずつ読めているときだけ数えます（★読めていなければ `nil` = 分からない）。
    --    ⚠ 分からないときに「居ない」と言うと、★敵の蘇生・回復を**見落とします**。
    local dead_n, hurt = nil, nil
    local measured = g.hp ~= nil and #g.hp > 0
    if measured then
      dead_n, hurt = 0, false
      -- ★敵が「回復したい」と見る線（⚠ ROM の対象の種類 1 = HP が最大の半分未満 / RX3-0358）
      local half = (stats and (stats.hp or 0) or 0) / 2
      for k = 1, #g.hp do
        local alive = true
        if g.alive ~= nil and g.alive[k] ~= nil then alive = g.alive[k] end
        if alive and (g.hp[k] or 0) > 0 then
          alive_n = alive_n + 1
          hp_sum = hp_sum + g.hp[k]
          hps[#hps + 1] = g.hp[k]
          alive_ks[#alive_ks + 1] = k
          statuses[#hps] = g.status ~= nil and g.status[k] or nil
          if half > 0 and g.hp[k] < half then hurt = true end
        else
          dead_n = dead_n + 1
        end
      end
    else
      alive_n = g.n or 0
      if stats ~= nil then
        hp_sum = (stats.hp or 0) * alive_n
        for k = 1, alive_n do hps[k] = stats.hp or 0 end
      else
        unknown = true
      end
    end
    local base_def = stats and (stats.defense or 0) or nil
    local defs = current_defs(g, alive_ks)
    local def = base_def
    if defs ~= nil then
      local sum = 0
      for _, d in ipairs(defs) do sum = sum + d end
      def = sum / #defs
    end
    out[#out + 1] = {index = i, id = g.id, alive_n = alive_n, hp_sum = hp_sum,
                     stats = stats, unknown = unknown or (stats == nil), hps = hps, statuses = statuses,
                     first_hp = hps[1] or (stats and stats.hp) or nil,
                     measured = measured, def = def, defs = defs, base_def = base_def,
                     def_changed = defs ~= nil and base_def ~= nil and def ~= base_def,
                     -- ★敵の粘りの成立条件（RX3-0368 / ⚠ 読めていなければ nil）
                     dead_n = dead_n, hurt = hurt}
  end
  return out
end

--- ★物理の見込みを補正したか・何で補正したか（★開発用の判断ログ `AI tune … estimate=` の材料）。
local function phys_notes(groups, alive, tuning, observed)
  local notes, ill = {}, {}
  for _, g in ipairs(groups) do
    if g.def_changed and g.alive_n > 0 then
      notes[#notes + 1] = string.format("enemy_def=g%d:%d/%d", g.index, math.floor(g.def + 0.5), g.base_def)
    end
  end
  for _, m in ipairs(alive) do
    if Situation.hit_rate(m, tuning) < 1.0 then ill[#ill + 1] = m.slot end
  end
  if #ill > 0 then
    notes[#notes + 1] = string.format("illusion=%s hit_rate=%.3f", table.concat(ill, ","),
                                      tonumber((tuning or {}).illusion_hit_rate) or Situation.ILLUSION_HIT)
  end
  if observed ~= nil then
    notes[#notes + 1] = string.format("observed=%.2f(dealt=%d/expect=%d)", observed.scale,
                                      math.floor((observed.dealt or 0) + 0.5), math.floor((observed.expect or 0) + 0.5))
  end
  return notes
end

local function party_defense(alive)
  local sum = 0
  for _, m in ipairs(alive) do sum = sum + (m.defense or 0) end
  if #alive == 0 then return 0 end
  return sum / #alive
end

--- ★戦況を見立てる。
--
--   戻り値: { kind, win, lose, our_dpt, enemy_dpt, groups, alive, dead, injured,
--            worst, enemy_alive, why }
function Situation.assess(ctx, cat)
  local t = ctx.tuning or {}
  local short = tonumber(t.short_turns) or 2
  local margin = tonumber(t.margin) or 1.5
  local critical = tonumber(t.critical_hp) or 0.15
  local danger = tonumber(t.danger_hp) or 0.3

  local alive = Situation.alive(ctx.party)
  local dead = Situation.dead(ctx.party)
  local groups = Situation.groups(ctx.enemies, cat)

  -- ★敵側: 残り HP の合計と、こちらへ来る 1 ターンの目安
  local enemy_hp, enemy_dpt, enemy_alive, unknown = 0, 0, 0, 0
  local phys_dpt = 0
  -- ★shadow の合計（RX3-0359 / ⚠ `enemy_dpt` とは**別の欄**）
  local enemy_dpt_v1 = 0
  -- ★敵側へ 1 ターンに戻る HP（RX3-0363 / ⚠ 回復と仲間呼びだけ / 蘇生は未解析）
  local enemy_regen_v1 = 0
  -- ★味方が 1 ターンに失う手番（RX3-0373 / ⚠⚠ ダメージとは別）
  local lost_actions_v1, paralyze_rate_v1, status_unknown_v1 = 0, 0, 0
  local illusion_v1, stopspell_v1 = 0, 0
  -- ⚠⚠ いま場に居る敵の種類（★仲間呼びは「もう居る種類」しか呼べない / JP bank4 $8E1C）
  local present = {}
  -- ★いま生きている敵の数（⚠ 8 体で頭打ち / RX3-0368）と、
  --   ⚠ 蘇生で戻る相手の見積り（★場に居る中で一番 HP の高い敵 / 安全側）
  -- ★味方の運のよさ（平均）と、⚠ 麻痺が続く残りターン（RX3-0373）
  --   ⚠ 運が読めなければ nil（★モデルは 0 と数える = ⚠ 危なくないのではない）
  local party_luck, luck_n = 0, 0
  for _, m in ipairs(alive) do
    if m.luck ~= nil then party_luck = party_luck + m.luck; luck_n = luck_n + 1 end
  end
  party_luck = luck_n > 0 and (party_luck / luck_n) or nil
  local field_n, revive_hp = 0, 0
  -- ⚠⚠ 成立条件は「読めている群が 1 つでもあるか」で決めます（RX3-0368）。
  --   ★1 体も読めていなければ `nil` のまま ＝ **止めない**（⚠ 敵を弱く見積もらない）。
  local any_measured, any_dead, any_hurt = false, false, false
  for _, g in ipairs(groups) do
    if g.alive_n > 0 then
      present[g.id] = true
      field_n = field_n + g.alive_n
    end
    if g.dead_n ~= nil then
      any_measured = true
      if g.dead_n > 0 then
        any_dead = true
        -- ★生き返る相手は群をまたぐので、⚠ **死者が居る群の中で一番 HP の高い敵**で見る
        local hp = (g.stats or {}).hp
        if hp ~= nil and hp > revive_hp then revive_hp = hp end
      end
      if g.hurt == true then any_hurt = true end
    end
  end
  local enemy_dead = any_measured and any_dead or nil
  local enemy_hurt = any_measured and any_hurt or nil
  -- ⚠ `false` を作るのは「読めていて、居なかった」ときだけ（★nil と区別する）
  if any_measured then enemy_dead, enemy_hurt = any_dead, any_hurt end
  local our_def = party_defense(alive)
  for _, g in ipairs(groups) do
    enemy_hp = enemy_hp + g.hp_sum
    enemy_alive = enemy_alive + g.alive_n
    if g.stats ~= nil and g.alive_n > 0 then
      local per = avg_physical(g.stats.attack, our_def) or 0
      g.threat = per * g.alive_n
      -- ★★ 物理の土台を残す（RX3-0332 / 2026-09-21）。
      --   ⚠⚠ 下の割増（全体攻撃・状態異常）は**非物理の危なさ**を物理の土台に掛けたものです。
      --     ★だから `threat` から `phys_threat` を引いた残りが「物理でない分」になります。
      --   ⚠ これが無いと、マヌーサ（物理を外させる）やスクルト（物理を減らす）の効果を
      --     **非物理のダメージにまで掛けてしまい**、過大評価します（★依頼者 §6-1）。
      g.phys_threat = g.threat
      -- ★★ 敵の行動から脅威を足す（RX3-0136 / 2026-09-09 / 指示書 v1.1 §6）。
      --   ⚠ 「持っているか」は ROM の事実、★割増の数字は目安（`tuning`）。
      local acts = g.stats.acts
      if acts ~= nil then
        g.can_heal = acts.heal == true
        g.party_attack = acts.party_attack == true
        if g.party_attack then
          g.threat = g.threat * (tonumber((ctx.tuning or {}).enemy_party_attack) or 1.5)
        end
        if acts.status == true then
          g.threat = g.threat * (tonumber((ctx.tuning or {}).enemy_status_threat) or 1.2)
        end
      end
      enemy_dpt = enemy_dpt + g.threat
      phys_dpt = phys_dpt + g.phys_threat
      -- ★★ Enemy Action Model v1（RX3-0359）― **shadow**（⚠ 誰も読まない）。
      --   ⚠⚠ ここから下で `g.threat` / `enemy_dpt` を**書き換えません**。
      --     ★新しい欄を足すだけです（`g.enemy_model_v1` / `g.threat_v1`）。
      --   ⚠ 落ちても本番を止めない（★`pcall`）。表が無い敵では nil のまま。
      if Model ~= nil and acts ~= nil and acts.slots ~= nil then
        local ok, got = pcall(Model.of, acts, {
          phys = per,                         -- ★物理 1 発の期待値（★上で出した値）
          party_n = #alive,
          -- ★敵の粘り（RX3-0363 / ⚠ 回復量・呼ぶ敵の HP を出すのに要る）
          hp_max = (g.stats or {}).hp, group_n = g.alive_n, present = present,
          -- ★味方が失う手番の材料（RX3-0373）
          status = {luck = party_luck,
                    sleep_turns = cat and cat.party_sleep_turns or nil,
                    confuse_turns = cat and cat.party_confuse_turns or nil},
          -- ★敵の枠（⚠ 8 体で頭打ち）と蘇生の相手（RX3-0368）
          field_n = field_n, slot_limit = cat and cat.enemy_slots or nil,
          revive_hp = revive_hp > 0 and revive_hp or nil,
          -- ⚠ 表を直に引きます（★`Situation.groups` と同じ道 / 別の道を作らない）
          hp_of = function(id)
            local row = (cat and cat.enemies or {})[id]
            return row ~= nil and row.hp or nil
          end,
          state = {
            mp = (g.stats or {}).mp,          -- ⚠ 最大 MP（★いまの MP は読めていない）
            -- ⚠ 分からないものは nil のまま（★`can_act` は「止めない側」に倒す）
            -- ⚠⚠ 2026-09-22（RX3-0368）: ここは `ctx._enemy_hurt` / `ctx._enemy_dead` を
            --   読んでいましたが、★**誰も入れていませんでした**（= いつも nil ＝ 門が開きっぱなし）。
            --   → ⚠ 戦闘が始まった瞬間から「蘇生する」「回復する」と数えていました。
            --   ★いまは戦況から出します（⚠ 1 体ずつ読めている群があるときだけ）。
            heal_target = enemy_hurt, dead_target = enemy_dead,
            silenced = g.silenced,
          }})
        if ok and got ~= nil then
          g.enemy_model_v1 = got
          g.threat_v1 = got.damage_per_turn * g.alive_n
          enemy_dpt_v1 = enemy_dpt_v1 + g.threat_v1
          -- ★敵の粘り（RX3-0363 / ⚠ こちらの削りから引く分 / **shadow**）
          g.regen_v1 = got.regen_per_turn * g.alive_n
          enemy_regen_v1 = enemy_regen_v1 + g.regen_v1
          -- ★手番を奪う分（RX3-0373）
          g.lost_actions_v1 = (got.lost_actions_per_turn or 0) * g.alive_n
          g.paralyze_rate_v1 = (got.paralyze_rate or 0) * g.alive_n
          lost_actions_v1 = lost_actions_v1 + g.lost_actions_v1
          paralyze_rate_v1 = paralyze_rate_v1 + g.paralyze_rate_v1
          status_unknown_v1 = status_unknown_v1 + (got.status_unknown or 0)
          -- ★弱める状態（RX3-0375 / ⚠⚠ ダメージにも手番にも足さない）
          illusion_v1 = illusion_v1 + (got.illusion_rate or 0) * g.alive_n
          stopspell_v1 = stopspell_v1 + (got.stopspell_rate or 0) * g.alive_n
        end
      end
    elseif g.alive_n > 0 then
      unknown = unknown + 1
      g.threat = nil
      g.phys_threat = nil
    end
  end

  -- ★こちら側: 生きている味方が殴ったときの 1 ターンの目安
  --   ★RX3-0226: 守備力は群の**いまの**値（`g.def` / ⚠ 無ければ表）、人ごとに当たる率 × 実測の比
  local our_dpt, party_hp = 0, 0
  local enemy_def
  if enemy_alive > 0 then
    local sum, n = 0, 0
    for _, g in ipairs(groups) do
      if g.def ~= nil and g.alive_n > 0 then
        sum = sum + g.def * g.alive_n
        n = n + g.alive_n
      end
    end
    if n > 0 then enemy_def = sum / n end
  end
  local observed = ctx._observed
  local obs_scale = (observed ~= nil and tonumber(observed.scale)) or 1.0
  local phys_scale = {}
  for _, m in ipairs(alive) do
    party_hp = party_hp + (m.hp or 0)
    local scale = Situation.hit_rate(m, t) * obs_scale
    phys_scale[m.slot] = scale
    our_dpt = our_dpt + (avg_physical(m.attack, enemy_def) or 0) * scale
  end
  local notes = phys_notes(groups, alive, t, observed)

  local win, lose = nil, nil
  if enemy_alive > 0 and our_dpt > 0 and enemy_hp > 0 then win = enemy_hp / our_dpt end
  if enemy_alive > 0 and enemy_dpt > 0 and unknown == 0 then lose = party_hp / enemy_dpt end

  -- ★★ 敵の粘りを引いた撃破ターン（RX3-0363 / ⚠⚠ **shadow** / 誰も読まない）。
  --
  --   ★敵が回復・仲間呼びをすると、⚠ こちらの削りの一部が**そのまま戻されます**。
  --     → ★正味の削り = `our_dpt - enemy_regen_v1`。
  --   ⚠⚠ 正味が 0 以下なら**削り切れません**（★`stalemate_v1`）。
  --     ⚠ `win_v1` を大きな数にせず、**nil のまま**にします（★「長い」と「無理」は別）。
  --
  --   ⚠ 蘇生（ザオラル / ザオリク）は**入っていません**（★戻る HP が未解析 / `RX3-0364`）。
  local win_v1, stalemate_v1 = nil, false
  local net_dpt_v1 = our_dpt - enemy_regen_v1
  if enemy_alive > 0 and enemy_hp > 0 and our_dpt > 0 then
    if net_dpt_v1 > 0 then
      win_v1 = enemy_hp / net_dpt_v1
    else
      stalemate_v1 = true
    end
  end

  -- ★怪我人（★比率の小さい順）
  local injured, worst = {}, 1.0
  for _, m in ipairs(alive) do
    local ratio = (m.hp or 0) / m.hp_max
    if ratio < worst then worst = ratio end
    injured[#injured + 1] = {slot = m.slot, ratio = ratio, member = m}
  end
  table.sort(injured, function(a, b)
    if a.ratio == b.ratio then return (a.member.index or 0) < (b.member.index or 0) end
    return a.ratio < b.ratio
  end)

  local kind, why
  if win ~= nil and lose ~= nil then
    if win + margin < lose then
      kind = (win <= short) and Situation.MOP or Situation.ADVANTAGE
    elseif lose + margin < win then
      kind = Situation.DISADVANTAGE
    else
      kind = Situation.EVEN
    end
    why = string.format("敵撃破 %.1fT / 味方崩壊 %.1fT（境目 ±%.1f）", win, lose, margin)
  elseif win ~= nil and enemy_alive > 0 and enemy_dpt == 0 and unknown == 0 then
    -- ★敵の攻撃が通らない（守備が高い）: 崩れない
    kind = (win <= short) and Situation.MOP or Situation.ADVANTAGE
    why = string.format("敵撃破 %.1fT / 敵の攻撃は通らない", win)
  else
    kind = Situation.EVEN
    why = (unknown > 0) and string.format("能力の分からない敵が %d 群", unknown)
      or "見立てられない（★均衡に倒す）"
  end

  -- ⚠ 死者・瀕死が居れば、それだけで楽観しない（§4「劣勢 … 死者が出る可能性」）
  local rank = {[Situation.MOP] = 1, [Situation.ADVANTAGE] = 2,
                [Situation.EVEN] = 3, [Situation.DISADVANTAGE] = 4}
  local floor_kind = nil
  if #dead >= 2 or (#dead >= 1 and worst < danger) or (worst < critical and #alive <= 2) then
    floor_kind = Situation.DISADVANTAGE
  elseif #dead >= 1 or worst < critical then
    floor_kind = Situation.EVEN
  end
  if floor_kind ~= nil and rank[floor_kind] > rank[kind] then
    why = why .. string.format(" → %s（死者 %d / 最低 HP %d%%）", floor_kind, #dead,
                               math.floor(worst * 100 + 0.5))
    kind = floor_kind
  end

  return {
    kind = kind, win = win, lose = lose, our_dpt = our_dpt, enemy_dpt = enemy_dpt,
    -- ★Enemy Action Model v1 の合計（RX3-0359 / ⚠⚠ **誰も読まない** / shadow）
    enemy_dpt_v1 = enemy_dpt_v1,
    -- ★敵の粘り（RX3-0363 / ⚠⚠ **誰も読まない** / shadow）
    enemy_regen_v1 = enemy_regen_v1, net_dpt_v1 = net_dpt_v1,
    win_v1 = win_v1, stalemate_v1 = stalemate_v1,
    -- ★RX3-0332: `enemy_dpt` のうち**物理の土台**（⚠ 割増を掛ける前の合計）
    phys_dpt = phys_dpt,
    enemy_hp = enemy_hp, enemy_alive = enemy_alive, groups = groups,
    alive = alive, dead = dead, injured = injured, worst = worst,
    enemy_def = enemy_def, why = why,
    -- ★RX3-0226: 人ごとの物理の倍率 / 補正したか / 何で補正したか（⚠ 無ければ全員 1.0・false・空）
    phys_scale = phys_scale, phys_adjusted = #notes > 0, phys_notes = notes,
    observed_scale = obs_scale,
  }
end

return Situation
