--- 攻撃呪文を選ぶ（2026-08-03 / 「ガンガン行こうぜ」Phase 1）。
--
-- ★★ **ここは RAM もメニューも知らない。** ★★
--   渡された数字を見て「誰が何を唱えるか」を返すだけです。
--   ⚠ 知ってしまうと、判断を1つ試すのに実機が要ります
--     （`item_conditions.lua` / `damage_estimate.lua` と同じ流儀）。
--
-- ## 何をするか（指示書 §7）
--
--   サマルとムーンの攻撃を**組み合わせて**評価し、
--
--     ムーン単独で倒せる  -> サマルは同じ敵へ重ねない
--     2人なら倒せる       -> 両方とも攻撃呪文
--     2人でも倒せない     -> 期待実効ダメージが最大の組み合わせ
--
--   を決めます。
--
-- ## ⚠ ここでしないこと
--
--   * 回復（★指示書 §5。既存の安全停止に任せる）
--   * MP の読み取り（★呼ぶ側が `usable` を判定して渡す）
--   * メニュー操作（★`bridge.lua` の仕事）
--   * 道具への置き換え（★Phase 3）

local Damage = nil                       -- ★呼ぶ側が inject する
local Plan = {}

--- 見積もりの道具を渡す。⚠ テストからも差し替えられるように。
function Plan.use(damage_module)
  Damage = damage_module
end

--- ★候補1つ。呼ぶ側が用意して渡します。
--
--   ```
--   {
--     actor    = "サマルトリア",      -- 誰が
--     spell_id = 0x01,                -- 何を
--     spell    = { ... },             -- memory_map.spells の中身
--     index    = 1,                   -- 狙う敵（scope が group/all なら起点）
--     usable   = true,                -- ★MP・封じ・拒否を見た結果
--   }
--   ```
--
-- ⚠ `usable ~= true` の候補は**最初から数えません**。

--- 使える候補だけ残す。
local function usable_only(candidates)
  local out = {}
  for _, c in ipairs(candidates or {}) do
    if c.usable == true and type(c.spell) == "table" then
      out[#out + 1] = c
    end
  end
  return out
end

--- 生きている敵の数。
local function alive_count(enemies)
  local n = 0
  for _, e in ipairs(enemies or {}) do
    if (Damage.enemy_hp(e) or 0) > 0 then n = n + 1 end
  end
  return n
end

--- 候補を1つ見積もる。⚠ 威力が分からなければ nil。
local function score(candidate, enemies)
  local got = Damage.evaluate_spell(candidate.spell, enemies, candidate.index)
  if got == nil then return nil end
  return {
    candidate = candidate,
    result = got,
    mp = candidate.spell.mp_battle or 0,
  }
end

--- ★比べる順（指示書 §7.2）。
--
--   1. 確定で倒せる数
--   2. 平均なら倒せる数
--   3. 期待実効ダメージ
--   4. ⚠ ここまで同じなら MP が安いほう
--
-- ⚠⚠ **引数の順番に意味があります。**
--   `challenger` … いま見ている新しい候補
--   `champion`   … これまでの一番
--
--   ★**すべて同点なら `champion`（先に見たほう）を残します。**
--   ⚠ 2026-08-03、ここで `challenger` を返していたため
--     「後に見たほうが勝つ」ことになり、設定に書いた順と
--     選ばれる呪文が食い違いました（★テストが捕まえました）。
local function pick_better(challenger, champion)
  if challenger == nil then return champion end
  if champion == nil then return challenger end
  local a, b = challenger.result, champion.result
  if a.certain_kills ~= b.certain_kills then
    return (a.certain_kills > b.certain_kills) and challenger or champion
  end
  if a.likely_kills ~= b.likely_kills then
    return (a.likely_kills > b.likely_kills) and challenger or champion
  end
  if a.effective ~= b.effective then
    return (a.effective > b.effective) and challenger or champion
  end
  if challenger.mp ~= champion.mp then
    return (challenger.mp < champion.mp) and challenger or champion
  end
  -- ★同点。先に見たほうを残す（★設定に書いた順が効く）
  return champion
end

--- その人の一番よい攻撃呪文を選ぶ。⚠ 無ければ nil。
--
-- ★候補の並び順は「設定に書いた順」です。同点なら**先のもの**が勝ちます。
--
-- ⚠⚠ **効き目が 0 のものは選びません**（2026-08-03 / 依頼者の実機指摘）。
--   「呪文が効かない相手に呪文を使っている？」
--   ★キラーマシーン（`spell_damage: 7`）にイオナズンを撃っていました。
--   MP を捨てるだけなので、**殴ったほうがまし**です。
--- ⚠⚠⚠ **狙い先を選べない呪文か**（2026-08-07 / 依頼者の実機指摘）★★★
--
--   > キラーマシン（呪文きかない）のに攻撃呪文使っている
--
-- ★原因は「判断」ではなく「操作」でした。`bridge.lua` の対象選択は
--   ⚠ **カーソルを動かさずそのまま A を押します**:
--
--     -- menu == 0x0A（敵の対象選択）
--     -- ⚠ 第一版では**先頭のグループ**を狙います。
--     return self:_ba_press("A")
--
--   つまり**ゲームが置いた既定の位置**に当たります。
--   ⚠ ところが判断側は `index = 1`（先頭）に効くかで決めていました。
--   → ★「1体目に効く」と思って選び、**別の敵に当たる**。
--
-- ⚠⚠ **本当の直し方はカーソルを合わせること**（Phase 7 以降）。
--   ★それまでの間は「外れても損しない」ことを条件にします:
--     **その場に「効かない敵」が1体でも居たら、単体・グループ呪文は使わない。**
--   ⚠ 全体呪文（`scope: all`）は狙いがずれようがないので、そのまま。
--
-- ★★★ **2026-08-07 追記: 狙いを合わせられるようになりました。**
--   `bridge.lua` の攻撃呪文が対象選択を `_claim_target_selection` に
--   任せ、そこで「呪文が効かない敵」を飛ばすようになりました。
--   → ⚠ この保守的な規則は**もう要りません**。
--
--   ⚠⚠ ただし**全部の敵が効かない**ときは、寄せる先がありません。
--     ★そのときだけ呪文をやめます（`best_for` の `effective > 0` が
--       すでに見ています）。
--
-- ★関数は残します（⚠ 消すと「なぜ緩めたか」が分からなくなる）。
local function aim_is_uncontrolled(candidate)
  -- ★狙いを合わせられるので、常に false。
  --   ⚠ 対象選択の作りを戻したら、ここを true に戻すこと。
  return false
end

--- その場に「呪文がまったく効かない敵」が居るか。
--
-- ⚠ 耐性が読めない敵（ROM の表が無い環境）は**居ないものとして扱います**。
--   ★初遭遇でも耐性は使います（B案 / 2026-08-22 / RX-0096）。
--   ★読めないことを理由に呪文を封じると、未知の敵に何もできません。
local function has_immune_enemy(enemies)
  for _, e in ipairs(enemies or {}) do
    if (Damage.enemy_hp(e) or 0) > 0 then
      local rate = Damage.spell_rate(e)
      if rate ~= nil and rate <= 0 then return true end
    end
  end
  return false
end

--- その人の一番よい攻撃呪文を選ぶ。⚠ 無ければ nil。
--
-- ★候補の並び順は「設定に書いた順」です。同点なら**先のもの**が勝ちます。
--
-- ⚠⚠ **効き目が 0 のものは選びません**（2026-08-03 / 依頼者の実機指摘）。
--   「呪文が効かない相手に呪文を使っている？」
--   ★キラーマシーン（`spell_damage: 7`）にイオナズンを撃っていました。
--   MP を捨てるだけなので、**殴ったほうがまし**です。
function Plan.best_for(candidates, enemies)
  local best = nil
  -- ★★ 狙いを選べないので、外れる先に「効かない敵」が居たら諦めます。
  local risky = has_immune_enemy(enemies)
  for _, c in ipairs(usable_only(candidates)) do
    local got = score(c, enemies)
    -- ⚠ 誰にも効かないなら候補にしない（★MP の無駄）
    if got ~= nil and got.result.effective > 0
      and not (risky and aim_is_uncontrolled(c)) then
      best = pick_better(got, best)
    end
  end
  return best
end

--- ★なぜ呪文を使わなかったかを言えるようにする（§17「説明できること」）。
--
-- ⚠ 「使わなかった」だけでは、⚠⚠ **壊れているのか正しいのか分かりません**。
function Plan.skipped_reason(candidates, enemies)
  if not has_immune_enemy(enemies) then return nil end
  for _, c in ipairs(usable_only(candidates)) do
    if aim_is_uncontrolled(c) then
      return "呪文が効かない敵が居て、狙いを選べないため使いません"
        .. "（★外れると MP を捨てるだけ）"
    end
  end
  return nil
end

--- ★呪文が効く敵が1体も居ないか（★そのときは撃つ先がありません）。
function Plan.all_immune(enemies)
  local any_alive, any_works = false, false
  for _, e in ipairs(enemies or {}) do
    if (Damage.enemy_hp(e) or 0) > 0 then
      any_alive = true
      local rate = Damage.spell_rate(e)
      -- ⚠ 読めない敵は「効くかもしれない」として数えます。
      if rate == nil or rate > 0 then any_works = true end
    end
  end
  return any_alive and not any_works
end

--- ★★ サマル＋ムーンの組み合わせを決める（指示書 §7 の中核）。
--
-- 引数:
--   `a_candidates` … サマルの候補（`usable` つき）
--   `b_candidates` … ムーンの候補
--   `enemies`      … いまの敵（`hp` / `max_hp` / `id` を持つもの）
--
-- 戻り値:
--   ```
--   {
--     verdict = "b_alone" など,
--     a = サマルの選択（nil なら「呪文を使わない」）,
--     b = ムーンの選択,
--     reason = 人に見せる理由,
--   }
--   ```
--   ⚠ どちらも選べなければ `verdict = "none"`。
function Plan.coordinate(a_candidates, b_candidates, enemies)
  local a = Plan.best_for(a_candidates, enemies)
  local b = Plan.best_for(b_candidates, enemies)
  local alive = alive_count(enemies)

  if a == nil and b == nil then
    return { verdict = "none", a = nil, b = nil,
             reason = "⚠ 使える攻撃呪文がありません" }
  end
  -- ⚠ 片方しか居ないなら、その人だけ唱える
  if a == nil then
    return { verdict = "b_only", a = nil, b = b,
             reason = "★ムーンだけが攻撃呪文を使えます" }
  end
  if b == nil then
    return { verdict = "a_only", a = a, b = nil,
             reason = "★サマルだけが攻撃呪文を使えます" }
  end

  -- ★総HPは「両方が狙う敵」ではなく、その場の敵の合計で見る
  local total_hp = 0
  for _, e in ipairs(enemies or {}) do
    total_hp = total_hp + (Damage.enemy_hp(e) or 0)
  end

  local verdict = Damage.combined_verdict(a.result, b.result, total_hp, alive)

  if verdict == "b_alone" then
    -- ★★ 指示書 §7.1 ケースB。**サマルは重ねない**
    return { verdict = verdict, a = nil, b = b,
             reason = "★ムーン単独で倒しきれるので、サマルは別行動へ" }
  end
  if verdict == "a_alone" then
    return { verdict = verdict, a = a, b = nil,
             reason = "★サマル単独で倒しきれるので、ムーンは別行動へ" }
  end
  if verdict == "either" then
    -- ★どちらでも足りる。⚠ **MP の安いほうを採る**（§7.2）
    if a.mp <= b.mp then
      return { verdict = verdict, a = a, b = nil,
               reason = string.format(
                 "★どちらでも倒しきれるので、MP の安いサマル（%d）を使う", a.mp) }
    end
    return { verdict = verdict, a = nil, b = b,
             reason = string.format(
               "★どちらでも倒しきれるので、MP の安いムーン（%d）を使う", b.mp) }
  end
  if verdict == "together" then
    -- ★★ 指示書 §7.1 ケースA。**両方とも攻撃呪文**
    return { verdict = verdict, a = a, b = b,
             reason = "★サマル＋ムーンの連携で倒しきれる" }
  end
  -- ケースC: 2人でも倒せない。★期待効果が高い組み合わせ（＝各自の最善）
  return { verdict = verdict or "neither", a = a, b = b,
           reason = "⚠ 2人でも倒しきれないので、期待効果の高い手を選ぶ" }
end

--- ★理由の文（ログ用 / 指示書 §14）。
function Plan.describe(choice)
  if type(choice) ~= "table" then return "" end
  local c = choice.candidate
  local r = choice.result
  return string.format(
    "%s: %s / 対象 %d体 / 期待実効 %.1f / 確定撃破 %d / MP %d",
    tostring(c.actor), tostring(c.spell.name or c.spell_id),
    r.targets, r.effective, r.certain_kills, choice.mp)
end

return Plan
