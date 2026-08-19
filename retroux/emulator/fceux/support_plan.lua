--- 補助行動（バフ・デバフ・停止・即死）の評価（2026-08-08 / Phase 7・8）。
---
--- 指示書 §18 Phase 7:
---   > 推計ターン改善を基に、補助行動を評価する。
---   > 効果適用後の戦力を近似 / 推計ターンを一度再計算
---   > 使用ターン・MPコストを差し引く / 効果中の再使用防止
---
--- 指示書 §18 Phase 8:
---   > ザラキ、ラリホー等を、成功率と戦況改善で評価する。
---
--- ## ★★★ いちばん大事な考え方: **ターンは整数**
---
---   ⚠⚠ 「推計ターンが 2.2 -> 2.09 に縮んだ」は**何の得にもなりません**。
---     ★どちらも**3ターンかかる**からです。
---
---   これが §18 Phase 7 の完了条件2つを、そのまま分けます:
---
---     短期優勢戦（2.2ターン）でルカナン
---       2.2 -> 2.09  ★切り上げると 3 -> 3。**得なし** -> ⚠ 使わない
---
---     均衡長期戦（8.0ターン）でルカナン
---       8.0 -> 6.73  ★切り上げると 8 -> 7。**1ターン得** -> ★使う
---
---   ⚠ 小数のまま比べると、短期戦でも「わずかに改善」となり、
---     **無意味なルカナンを唱え続けます**。
---
--- ## ⚠⚠ 効果の大きさは **近似** です（★指示書もそう書いています）
---
---   「効果適用後の戦力を**近似**」。★倍率は設定に置き、出典を書きます。
---   ⚠ ROM から取った値ではありません。★実測で直せるようにしてあります。
---
--- ## ⚠ このモジュールは RAM もメニューも知りません
---
---   ★画面も実機も無しで試せます（`support_plan_test.lua`）。

local Support = {}

--- 補助行動の種類。
Support.Kind = {
  --: 敵の守備を下げる（ルカナン）-> ★こちらの火力が上がる
  DEBUFF_DEFENSE = "debuff_defense",
  --: 味方の守備を上げる（スクルト）-> ★崩壊が遅くなる
  BUFF_DEFENSE = "buff_defense",
  --: 敵の命中を下げる（マヌーサ）-> ★崩壊が遅くなる
  DEBUFF_ACCURACY = "debuff_accuracy",
  --: 敵を止める（ラリホー）-> ★その敵の火力が消える
  DISABLE = "disable",
  --: 即死（ザキ）-> ★その敵が消える
  INSTANT_DEATH = "instant_death",
  --: 呪文を封じる（マホトーン）
  SILENCE = "silence",
}

--- 不確実な行動をどこまで許すか（指示書 §8「4段階」）。
---
--- ⚠ `battle_types.lua` の `Types.Risk` と**同じ4つ**です。
---   ★数字だけをここに持ちます（あちらは名前の定義）。
Support.RISK_MIN_RATE = {
  disabled = 1.0,    -- ⚠ 確実なものだけ（★成功率100%以外は使わない）
  cautious = 0.75,
  normal = 0.5,
  bold = 0.25,
}

--- 成功率の下限を引く。⚠ 知らない名前は **normal** に倒す。
function Support.min_rate(risk)
  return Support.RISK_MIN_RATE[risk] or Support.RISK_MIN_RATE.normal
end

--- ★切り上げたターン数。⚠ 分からなければ nil（0 にしない）。
local function whole_turns(value)
  if type(value) ~= "number" or value <= 0 then return nil end
  return math.ceil(value - 1e-9)
end

--- 1人が1ターン補助に回ることで、こちらの火力が何ターンぶん落ちるか。
---
--- ★3人なら 1/3 ターン。⚠ 人数が分からなければ 1 ターンぶんとみなす（安全側）。
local function action_cost(alive_allies)
  local n = tonumber(alive_allies) or 0
  if n <= 0 then return 1.0 end
  return 1.0 / n
end

--- その敵に効く確率。⚠ 耐性が読めなければ nil（★「効く」と決めない）。
---
--- `resist_field` … `sleep` / `defeat` / `surround` / `defense_down` / `stopspell`
function Support.rate_for(damage_module, enemy, resist_field)
  if damage_module == nil or enemy == nil or resist_field == nil then
    return nil
  end
  local stats = enemy.stats
  local resist = stats ~= nil and stats.resist or nil
  if type(resist) ~= "table" then return nil end
  return damage_module.success_rate(resist[resist_field])
end

--- 効く相手のうち、**いちばん効きにくい**確率を返す（★グループ全体に掛ける呪文）。
---
--- ⚠⚠ 平均を採ってはいけません。★「1体だけ効く」を「半分効く」と
---   読み替えると、⚠ 全体呪文の価値を実際より高く見ます。
--- ★戻り値: `確率, 効く体数, 生きている体数`。⚠ 1体も読めなければ nil。
function Support.group_rate(damage_module, enemies, resist_field)
  local worst, hits, alive, known = nil, 0, 0, 0
  for _, e in ipairs(enemies or {}) do
    if (e.hp or 0) > 0 then
      alive = alive + 1
      local rate = Support.rate_for(damage_module, e, resist_field)
      if rate ~= nil then
        known = known + 1
        if rate > 0 then hits = hits + 1 end
        if worst == nil or rate < worst then worst = rate end
      end
    end
  end
  if known == 0 then return nil, 0, alive end
  return worst, hits, alive
end

--- 倍率を「効いた割合」ぶんだけ薄める（2026-08-08）。
---
--- ★止める・消す呪文は、**何体に効いたか**で価値が変わります。
---   ⚠ 固定倍率だと、敵4体でも1体眠らせれば「火力が半分」になります。
---
---     倍率 0.5 / 割合 1.0  -> 0.5   （★全部に効いた）
---     倍率 0.5 / 割合 0.25 -> 0.875 （⚠ 4体中1体だけ）
---     倍率 1.5 / 割合 0.5  -> 1.25
---
--- ⚠ `nil` は `nil` のまま返します（★効果が無い軸を 1.0 にしない）。
function Support.scale_share(multiplier, share)
  local m = tonumber(multiplier)
  if m == nil then return nil end
  local s = tonumber(share)
  if s == nil or s <= 0 then return 1.0 end
  if s > 1 then s = 1 end
  return 1.0 + (m - 1.0) * s
end

----------------------------------------------------------------------
-- ★ Phase 7: 推計ターンがどれだけ縮む／延びるか
----------------------------------------------------------------------

--- 効果を当てはめたあとの推計ターン。
---
--- ⚠ 元の値が nil なら nil のまま（★「分からない」を数字にしない）。
---
--- `effect` … `{ our_damage_multiplier = 1.25 }` など（★設定から）
--- 戻り値: `倒すまで, 崩れるまで`
function Support.turns_after(assessment, effect)
  local win = assessment and assessment.enemy_defeat_turns or nil
  local lose = assessment and assessment.party_collapse_turns or nil
  effect = effect or {}

  local dmg = tonumber(effect.our_damage_multiplier)
  if win ~= nil and dmg ~= nil and dmg > 0 then win = win / dmg end

  -- ⚠ 敵の火力が下がる ＝ **崩れるまでが延びる**（★割り算の向きに注意）
  local taken = tonumber(effect.enemy_damage_multiplier)
  if lose ~= nil and taken ~= nil and taken > 0 then lose = lose / taken end

  return win, lose
end

--- その補助が「何ターン得か」。⚠ 得が無ければ 0。
---
--- ## ★★ 切り上げてから比べます（★このファイルの冒頭を参照）
---
--- 戻り値: `得たターン数, 説明`
function Support.turn_gain(assessment, effect, alive_allies, rate)
  local before_win = whole_turns(assessment and assessment.enemy_defeat_turns)
  local before_lose = whole_turns(assessment and assessment.party_collapse_turns)
  local raw_win, raw_lose = Support.turns_after(assessment, effect)

  -- ★補助に1ターン使うぶん、倒すのが遅れる
  local cost = action_cost(alive_allies)
  if raw_win ~= nil then raw_win = raw_win + cost end

  local after_win = whole_turns(raw_win)
  local after_lose = whole_turns(raw_lose)

  local gain, why = 0, nil
  if before_win ~= nil and after_win ~= nil and after_win < before_win then
    gain = gain + (before_win - after_win)
    why = string.format("倒すまで %d -> %d ターン", before_win, after_win)
  end

  -- ★★★ **必要より長く生き延びても価値はありません**（2026-08-08）★★★
  --
  --   ⚠⚠ 実機ログ（13:02）で **9戦中9戦**に候補が出ました。例:
  --
  --       [戦況] advantage（敵撃破 1.8ターン / 味方崩壊 8.3ターン）
  --       [補助] samaltria:Increase（崩れるまで 9 -> 11 ターン）
  --
  --   ★2ターンで勝つ戦いです。⚠ 崩れるまでが 9 だろうと 11 だろうと
  --     **何も変わりません**。それを「2ターン得」と数えていました。
  --
  --   → ★上限を **必要ターン + 1** にします。
  --     ⚠ 「+1」は余裕ぶん（★ぴったりで生き延びるのは危ういため）。
  --
  --   ⚠⚠ この上限が無いと、**守りのバフが常に最優先**になります
  --     （★耐性を持たないスクルトは必ず「延びる」ので）。
  if before_lose ~= nil and after_lose ~= nil and after_lose > before_lose then
    local needed = after_win or before_win
    local cap = needed ~= nil and (needed + 1) or nil
    local from, to = before_lose, after_lose
    if cap ~= nil then
      if from > cap then from = cap end
      if to > cap then to = cap end
    end
    if to > from then
      gain = gain + (to - from)
      local text = string.format("崩れるまで %d -> %d ターン",
        before_lose, after_lose)
      why = why and (why .. " / " .. text) or text
    end
  end

  -- ★★ 効かないかもしれないぶんを割り引く（§8「成功率と戦況改善で評価」）
  --   ⚠ `rate` が nil なら割り引きません（★分からないものを 0 にしない）。
  if rate ~= nil then gain = gain * rate end
  return gain, why
end

----------------------------------------------------------------------
-- ★ 候補づくり
----------------------------------------------------------------------

--- 補助行動の候補を評価して並べる。
---
--- `ctx`:
---   `spells`        … `{ { id, name, mp_battle, effect = {...} }, ... }`
---                     ★**唱えられるものだけ**を渡してください（呼ぶ側が絞る）
---   `assessment`    … `{ enemy_defeat_turns, party_collapse_turns }`
---   `enemies`       … `{ { id, hp, stats = { resist = {...} } }, ... }`
---   `alive_allies`  … 生きている味方の数
---   `mp`            … 唱える人のいまのMP
---   `risk`          … `disabled` / `cautious` / `normal` / `bold`
---   `active`        … `{ [呪文ID] = true }` ★効果が続いているもの（§7）
---   `damage`        … `damage_estimate.lua`（★成功率の計算に使う）
---
--- 戻り値: `候補の並び（★良い順）, 見送った理由の並び`
---
--- ⚠⚠ **見送った理由も返します。** ★「使わなかった」だけだと、
---   設定が悪いのか戦況が悪いのか分かりません（★黙って捨てない）。
function Support.evaluate(types, ctx)
  ctx = ctx or {}
  local out, skipped = {}, {}
  local min_rate = Support.min_rate(ctx.risk)

  for order, spell in ipairs(ctx.spells or {}) do
    local effect = spell.effect or {}
    local name = tostring(spell.name or spell.id)
    local skip = nil

    -- ★★ 効果が続いているうちは掛け直さない（§7「効果中の再使用防止」）
    if (ctx.active or {})[spell.id] then
      skip = string.format("%s は効果が続いています", name)

    -- ⚠ MPが足りない
    elseif ctx.mp ~= nil and (spell.mp_battle or 0) > ctx.mp then
      skip = string.format("%s のMPが足りません（必要%d / 残り%d）",
        name, spell.mp_battle or 0, ctx.mp)
    end

    local rate, hits, alive_enemies
    if skip == nil and effect.resist_field ~= nil then
      rate, hits, alive_enemies =
        Support.group_rate(ctx.damage, ctx.enemies, effect.resist_field)
      if rate == nil then
        -- ⚠⚠ **「分からない」を「効く」と決めない。**
        --   ★初遭遇の敵は図鑑に無いので耐性が読めません。
        skip = string.format("%s が効くか分かりません（敵の耐性が読めない）",
          name)
      elseif hits == 0 then
        skip = string.format("%s が効かない敵しか居ません", name)
      elseif rate < min_rate then
        skip = string.format(
          "%s の成功率 %d%% は %s の下限 %d%% 未満です",
          name, math.floor(rate * 100 + 0.5), tostring(ctx.risk or "normal"),
          math.floor(min_rate * 100 + 0.5))
      end
    end

    if skip == nil then
      -- ★★ 止める・消すものは「**何体に効くか**」で薄める（2026-08-08）★★
      --
      --   ⚠⚠ 実機へ繋いだ直後に見つけた欠陥です。
      --     `disable` の倍率を 0.5 固定にしていたので、⚠ **敵が4体でも
      --     1グループ眠らせれば「敵の火力が半分」**になっていました。
      --     ★その結果ラリホーが常に最強候補になります。
      --
      --   ★効いた割合ぶんだけ効果を薄めます:
      --       敵1体・1体に効く   -> 0.5（そのまま）
      --       敵4体・1体に効く   -> 1 - 0.5 × (1/4) = 0.875
      local applied = effect
      if hits ~= nil and alive_enemies ~= nil and alive_enemies > 0
         and (effect.kind == Support.Kind.DISABLE
              or effect.kind == Support.Kind.INSTANT_DEATH) then
        local share = hits / alive_enemies
        applied = {
          kind = effect.kind, resist_field = effect.resist_field,
          our_damage_multiplier = Support.scale_share(
            effect.our_damage_multiplier, share),
          enemy_damage_multiplier = Support.scale_share(
            effect.enemy_damage_multiplier, share),
        }
      end

      local gain, why = Support.turn_gain(
        ctx.assessment, applied, ctx.alive_allies, rate)
      if gain <= 0 then
        -- ★★ **これが「短期優勢戦で無意味なルカナンを使わない」** ★★
        skip = string.format(
          "%s を使ってもターンが縮みません（★ターンは整数です）", name)
      else
        out[#out + 1] = {
          id = spell.id, name = spell.name, kind = effect.kind,
          mp = spell.mp_battle, rate = rate, gain = gain,
          hits = hits, alive_enemies = alive_enemies,
          order = order,
          reason = string.format("%s（%s%s）",
            why or "戦況が良くなります",
            rate ~= nil
              and string.format("成功率 %d%% / ", math.floor(rate * 100 + 0.5))
              or "",
            string.format("%d ターンぶん", math.floor(gain * 100 + 0.5) / 100)),
        }
      end
    end

    if skip ~= nil then skipped[#skipped + 1] = skip end
  end

  table.sort(out, function(a, b)
    if a.gain ~= b.gain then return a.gain > b.gain end
    -- ⚠ 同じ得なら**安いほう**（★MPを無駄にしない）
    if (a.mp or 0) ~= (b.mp or 0) then return (a.mp or 0) < (b.mp or 0) end
    return a.order < b.order
  end)
  return out, skipped
end

----------------------------------------------------------------------
-- ★ Phase 8: 即死・停止のあとしまつ
----------------------------------------------------------------------

--- 即死・停止させた敵を「もう狙わない」印にする（§8）。
---
--- ⚠⚠ **これが無いと、眠った敵を殴って起こします**
---   （★指示書 完了条件「眠った敵を不用意に攻撃しない」）。
---
--- ★`battle_types.lua` の `directive.prohibited_targets` に足す形です。
--- ⚠ 即死は**確実なときだけ**印にします（★外れた敵を放置しては困る）。
function Support.reserve_removal(directive, entry, enemy_ids)
  if directive == nil or entry == nil then return false end
  local kind = entry.kind
  local certain = (entry.rate == nil) or (entry.rate >= 1.0)

  if kind == Support.Kind.INSTANT_DEATH and not certain then
    -- ⚠ 100% でない即死は「消えたつもり」にしない（★残っていたら殴る必要がある）
    return false
  end
  if kind ~= Support.Kind.INSTANT_DEATH and kind ~= Support.Kind.DISABLE then
    return false
  end

  local added = false
  for _, id in ipairs(enemy_ids or {}) do
    local seen = false
    for _, banned in ipairs(directive.prohibited_targets) do
      if banned == id then seen = true end
    end
    if not seen then
      directive.prohibited_targets[#directive.prohibited_targets + 1] = id
      added = true
    end
  end
  return added
end

--- 止めた敵を除いた戦力（§8「停止中の敵を除外した局所戦力計算」）。
---
--- ⚠ 元の敵リストは**変えません**（★呼ぶ側が別の用途で使うため）。
function Support.enemies_without(enemies, stopped_ids)
  local banned = {}
  for _, id in ipairs(stopped_ids or {}) do banned[id] = true end
  local out = {}
  for _, e in ipairs(enemies or {}) do
    if not banned[e.id] then out[#out + 1] = e end
  end
  return out
end

--- 即死より通常攻撃のほうがよいか（§8 完了条件）。
---
---   > 通常攻撃で確殺できる敵へ無駄な即死を使わない
---
--- ★`certain_kill` が真なら、⚠ 即死を使う理由がありません
---   （成功率100%でも、**MPを使うだけ損**です）。
--- 戻り値: `見送るか, 理由`
function Support.prefer_attack(entry, certain_kill)
  if entry == nil then return false, nil end
  if entry.kind ~= Support.Kind.INSTANT_DEATH then return false, nil end
  if certain_kill ~= true then return false, nil end
  return true, string.format(
    "%s は使いません（★通常攻撃で確実に倒せます）", tostring(entry.name))
end

return Support
