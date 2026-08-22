--- 戦況の見立て（2026-08-04 / 戦闘AI再設計 Phase 2）。
--
-- 指示書 §18 Phase 2 の `BattleSituationAnalyzer`:
--   > 既存危険判定を集約 / 現行敵脅威値を保持 /
--   > 現行AUTO解除条件を集約 / 暫定的な BattleAssessment を返す
--
-- ★★ **ここは RAM もメニューも知りません。** ★★
--
-- ## ⚠⚠ Phase 2 の約束: **答えを変えない**
--
--   いまは `bridge.lua` が読んだ状態を**そのまま写す**だけです。
--   推計ターン・脅威度・戦況分類は **Phase 4** です（§18）。
--   ★ここで賢くすると、Phase 0 の基準と比べる意味がなくなります。
--
--   だから `balance` は必ず `UNKNOWN` を返します。
--   ⚠ 「まだ数えていない」を「均衡」と書かないため（0 と不明を混ぜない）。

local Assessment = {}

--- 現行の安全判定から見立てを作る。
--
--   `types`   … `battle_types.lua`
--   `safety`  … `{ danger, danger_reason, first_encounter,
--                  is_boss, is_caution }`（`_safety_context()` の戻り）
--   `party`   … `active_party()` の結果（★HPの読み取りは呼ぶ側の仕事）
--
-- ★戦況タグ（§6.4）のうち、**いま材料があるものだけ**を付けます。
--   ⚠ 材料が無いタグを推測で付けない。
function Assessment.from_safety(types, safety, party)
  local s = safety or {}
  local a = types.battle_assessment({})

  -- ⚠⚠ **まだ数えていないので `UNKNOWN` のまま**（Phase 4 で埋める）
  a:note_unknown("推計ターンは未実装（Phase 4）")

  -- ★AUTO を続けてよいか（§6 の出力の1つ）。
  --   ⚠ 現行の条件を**そのまま**写します。増やしも減らしもしません。
  local blocked = nil
  if s.danger == true then
    blocked = s.danger_reason or "危険状態"
  elseif s.first_encounter == true then
    blocked = "初遭遇のモンスター"
  elseif s.is_caution == true then
    blocked = "警戒中の相手"
  end
  a.auto_continue = (blocked == nil)
  if blocked ~= nil then
    a:why(string.format("AUTO を続けない: %s", blocked))
  end

  -- ★材料のあるタグだけ付ける（§6.4）
  if s.is_boss == true then
    a:tag("boss_battle", "ボス戦")
  end
  if s.first_encounter == true then
    a:tag("unknown_enemy", "初めて見る相手")
    -- ★耐性は初遭遇でも ROM の表から読む（B案 / 2026-08-22 / RX-0096）。
    --   ⚠ 以前ここに note_unknown("初遭遇の敵の耐性が分からない") があったのは方針の写し
  end
  if s.danger == true then
    a:tag("party_at_risk", tostring(s.danger_reason or "危険状態"))
  end

  -- ★守るべき人の目安（§8）。⚠ いまは「HPの割合が低い順」だけ。
  --   推計（失うと戦力がどれだけ落ちるか）は Phase 4 です。
  for _, who in ipairs(party or {}) do
    if who.alive and (who.max_hp or 0) > 0 then
      local p = types.protection_value({ actor_id = who.name })
      p.death_risk = 1 - ((who.hp or 0) / who.max_hp)
      -- ★戦力低下は estimate() の loss_impact が入れる（RX-0010 訂正）。ここは役割が無い段階
      p:note_unknown("失ったときの戦力低下は役割が決まるまで分からない")
      a.protections[who.name] = p
    end
  end
  return a
end

----------------------------------------------------------------------
-- ★★ 推計ターンと戦況分類（2026-08-05 / 戦闘AI再設計 Phase 4）★★
--
-- 指示書 §6.2:
--   > 敵撃破までの推計ターン ≒ 敵側の実効HP ÷ 味方側の実効ダメージ／ターン
--   > 味方崩壊までの推計ターン ≒ 味方側の実効HP ÷ 敵側の実効ダメージ／ターン
--
-- ★★ **粗い近似で十分です**（指示書 §6.1）:
--   > 厳密な戦闘シミュレーションは不要。平均値や近似値を使い、
--   > 十分に説明可能な判断を行う。
--
-- ⚠⚠ **出せないときは nil を返します。** 0 を返すと
--   「0ターンで倒せる」＝**最高の戦況**として扱われます。
----------------------------------------------------------------------

--- 敵1体の脅威を見立てる（指示書 §7）。
--
-- ★★ **1つの数値にまとめません。** ★★
--   「脅威度 8」では、なぜ優先するのかが説明できません。
--   ⚠ 火力が高いのか、回復するのか、即死を使うのかで**打つ手が違います**。
--
--   `enemy` … `{ id, name, hp, max_hp, stats = { attack, agility, ... } }`
--   `cfg`   … `auto_input.assessment`
function Assessment.threat_of(types, enemy, cfg)
  local t = types.threat_vector({ enemy_id = enemy.id, name = enemy.name })
  local stats = enemy.stats
  if stats == nil then
    -- ⚠ 図鑑に無い敵（初遭遇）。★「弱い」ではなく「分からない」
    t:note_unknown("能力が分からない敵")
    return t
  end
  local ratio = tonumber(cfg.enemy_damage_ratio) or 0.5
  if stats.attack ~= nil then
    t.direct_damage = stats.attack * ratio
  end
  t.durability = enemy.hp or stats.max_hp
  t.action_speed = stats.agility
  -- ★回復する敵・即死を使う敵は別枠で見る（§7）
  --   ⚠ いまは「そういう敵か」を渡された印でしか分かりません。
  if enemy.heals == true then t.healing = 1 end
  if enemy.disables == true then t.disable = 1 end
  return t
end

--- その敵を先に倒す価値（指示書 §7）。
--
--     攻撃優先度 = その敵を残した場合の損失 × 今排除できる可能性
--
-- ⚠⚠ **「脅威度順」ではありません。** ★倒しやすさを掛けるので、
--   「高火力・低HP」が先、「高耐久・低火力」が後回しになります
--   （§18 Phase 4 完了条件）。
--
-- 戻り値: 数値（★大きいほど先に倒す）。⚠ 見立てられなければ nil。
function Assessment.target_value(threat, cfg, party_damage)
  local loss = threat.direct_damage
  if loss == nil then return nil end
  -- ★回復する敵・止めてくる敵は、残したときの損失が大きい
  if threat.healing ~= nil then
    loss = loss * (tonumber((cfg.threat or {}).healer_weight) or 2.0)
  end
  if threat.disable ~= nil then
    loss = loss * (tonumber((cfg.threat or {}).disable_weight) or 1.5)
  end
  local hp = threat.durability
  if hp == nil or hp <= 0 then return loss end
  -- ★今排除できる可能性 ≒ 1ターンで削れる割合（★1 を超えたら 1）
  local removable = (party_damage or 40) / hp
  if removable > 1 then removable = 1 end
  return loss * removable
end

--- 戦況を見立てる（指示書 §6）。
--
--   `party`   … `{ {name, hp, max_hp, alive}, ... }`
--   `enemies` … `{ {id, name, hp, stats}, ... }`
--   `cfg`     … `auto_input.assessment`
--
-- ⚠ 材料が足りなければ `balance` は `UNKNOWN` のままにします。
function Assessment.estimate(types, party, enemies, cfg, base)
  cfg = cfg or {}
  local a = base or types.battle_assessment({})

  -- ⚠ `from_safety` が置いた「未実装」の但し書きを外す（★もう実装した）。
  --   ★残すと、見立てられているのに「分からない」と出続けます。
  for i = #a.unknown, 1, -1 do
    if a.unknown[i]:find("推計ターンは未実装") ~= nil then
      table.remove(a.unknown, i)
    end
  end

  local party_damage = tonumber(cfg.party_damage_per_turn) or 40
  local ratio = tonumber(cfg.enemy_damage_ratio) or 0.5

  -- ★敵側の実効HP と 敵の火力
  local enemy_hp, enemy_damage, unknown_enemies = 0, 0, 0
  local alive_enemies = 0
  for _, e in ipairs(enemies or {}) do
    if (e.hp or 0) > 0 then
      alive_enemies = alive_enemies + 1
      enemy_hp = enemy_hp + e.hp
      local threat = Assessment.threat_of(types, e, cfg)
      a.threats[tostring(e.name or e.id)] = threat
      if threat.direct_damage ~= nil then
        enemy_damage = enemy_damage + threat.direct_damage
      else
        unknown_enemies = unknown_enemies + 1
      end
    end
  end

  -- ★味方側の実効HP と 味方の火力
  local party_hp, alive = 0, 0
  for _, m in ipairs(party or {}) do
    if m.alive and (m.max_hp or 0) > 0 then
      alive = alive + 1
      party_hp = party_hp + (m.hp or 0)
      local p = types.protection_value({ actor_id = m.name })
      p.death_risk = 1 - ((m.hp or 0) / m.max_hp)
      -- ★失うと戦力がどれだけ落ちるか（§8）。
      --   ⚠ いまは「この人だけが持つ役割」を渡された印で見ます。
      p.loss_impact = m.role_weight
      a.protections[tostring(m.name)] = p
    end
  end

  if unknown_enemies > 0 then
    a:note_unknown(string.format("%d 体の能力が分からない", unknown_enemies))
    a:tag("unknown_enemy", "図鑑に無い敵が居る")
  end

  -- ★★ 推計ターン。⚠ 割れないときは nil のまま（0 にしない）
  if alive_enemies > 0 and alive > 0 then
    local ours = party_damage * alive
    if ours > 0 then
      a.enemy_defeat_turns = enemy_hp / ours
    end
    if enemy_damage > 0 then
      a.party_collapse_turns = party_hp / enemy_damage
    else
      a:note_unknown("敵の火力を見立てられない")
    end
  else
    a:note_unknown("生きている敵か味方が居ない")
  end

  -- ★★ 戦況の分類（§6.3）
  local win = a.enemy_defeat_turns
  local lose = a.party_collapse_turns
  local margin = tonumber(cfg.balance_margin) or 1.5
  if win ~= nil and lose ~= nil then
    if win + margin < lose then
      a.balance = types.Balance.ADVANTAGE
    elseif lose + margin < win then
      a.balance = types.Balance.DISADVANTAGE
    else
      a.balance = types.Balance.EVEN
    end
    a:why(string.format(
      "敵撃破 %.1fターン / 味方崩壊 %.1fターン（境目 ±%.1f）-> %s",
      win, lose, margin, a.balance))
  end
  -- ⚠ 片方しか出せないときは **UNKNOWN のまま**。
  --   ★「敵は倒せそう」だけで優勢と言わない。

  -- ★★ 戦闘の長さ（§6.2）
  if win ~= nil then
    local short = tonumber(cfg.short_turns) or 2
    local long = tonumber(cfg.long_turns) or 6
    if win <= short then
      a.length = types.Length.SHORT
      a:tag("short_battle_expected")
    elseif win >= long then
      a.length = types.Length.LONG
      a:tag("long_battle_expected")
    else
      a.length = types.Length.MEDIUM
    end
  end

  -- ★★ 戦況タグ（§6.4）。⚠ **材料のあるものだけ**
  if alive_enemies == 1 then a:tag("single_strong_enemy") end
  if alive_enemies >= 3 then a:tag("many_fragile_enemies") end
  for _, threat in pairs(a.threats) do
    if threat.healing ~= nil then a:tag("enemy_healer_present") end
    if threat.disable ~= nil then a:tag("enemy_disable_user") end
  end
  return a
end

--- 倒す順（★大きいほど先）。指示書 §7。
--
-- 戻り値: `{ {name, value}, ... }` を値の大きい順に並べたもの。
-- ⚠ 見立てられない敵は**最後に回します**（★捨てません）。
function Assessment.target_order(assessment, cfg, party_damage)
  local out = {}
  for name, threat in pairs(assessment.threats or {}) do
    out[#out + 1] = {
      name = name,
      value = Assessment.target_value(threat, cfg or {}, party_damage),
    }
  end
  table.sort(out, function(x, y)
    if x.value == nil and y.value == nil then return x.name < y.name end
    if x.value == nil then return false end      -- ★nil は後ろへ
    if y.value == nil then return true end
    if x.value == y.value then return x.name < y.name end
    return x.value > y.value
  end)
  return out
end

--- AUTO を続けてよいか（★呼ぶ側の early return に使う）。
--
-- ⚠ 読めないときは **true**（＝これまでどおり AI が動く）。
--   ★false にすると、見立てが作れない環境で自動戦闘が丸ごと止まります。
function Assessment.may_continue(assessment)
  if assessment == nil then return true end
  if assessment.auto_continue == nil then return true end
  return assessment.auto_continue == true
end

return Assessment
