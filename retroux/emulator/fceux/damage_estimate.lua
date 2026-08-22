--- 攻撃の結果を見積もる（2026-08-03 / 「ガンガン行こうぜ」Phase 1）。
--
-- ★★ **ここは RAM もメニューも知らない。** ★★
--   渡された数字を見て「どれくらい効くか」を返すだけです。
--   ⚠ 知ってしまうと、式を1つ試すのに実機が要ります
--     （`item_conditions.lua` と同じ流儀）。
--
-- ## 何を見積もるか
--
--   期待ダメージ      … ★平均。行動を比べるのに使う
--   最低ダメージ      … ★確定撃破の判定に使う（平均では倒せても
--                        最低では倒せないことがある）
--   期待実効ダメージ  … ★敵の残HPを超えた分は数えない（無駄打ち）
--   即死の成功率      … ★`(7 - 耐性) / 7`（ROM の実コードから確定）
--
-- ## ⚠ 分かっていないこと
--
--   ★呪文のダメージに**守備力が効くかどうか**は確かめていません。
--   ⚠ 攻略情報の「ギラ 12〜28」は守備力を含んだ後の値かもしれません。
--   ★第一版では**守備力を引きません**（引くと過小評価になり、
--     「倒せるのに倒しに行かない」ほうへ倒れる。安全側）。
--
--   ★物理攻撃はここでは扱いません（呪文だけ）。⚠ 2026-08-21 訂正（RX-0010）:
--     以前「式が未確定」と書いてあったが、物理の目安は `dq2.lua` の
--     `estimated_damage` / `estimated_damage_to`（(攻撃 - 守備/2)/2）にある。

local Damage = {}

--- ★耐性の段階（`memory_map` の `resist`）。ROM の実コードから確定。
--   成功率 = (7 - 値) / 7。⚠ 7 なら効かない、0 なら必ず効く。
Damage.RESIST_MAX = 7

--- 即死・状態異常が効く確率（0.0〜1.0）。
--
-- ⚠ 耐性が読めなければ `nil` を返します（★0 と混ぜない）。
--   「効かない」と「分からない」は別のことです。
function Damage.success_rate(resist_value)
  if type(resist_value) ~= "number" then return nil end
  if resist_value >= Damage.RESIST_MAX then return 0.0 end
  if resist_value <= 0 then return 1.0 end
  return (Damage.RESIST_MAX - resist_value) / Damage.RESIST_MAX
end

--- ★★ 呪文ダメージの通りやすさ（0.0〜1.0）。
--
-- ⚠⚠ **2026-08-03、これが抜けていて実機で見つかりました。**
--   依頼者の指摘:「呪文が効かない相手に呪文を使っている？」
--   ★キラーマシーンは `spell_damage: 7`（**まったく効かない**）なのに、
--     ギラ・ベギラマ・イオナズンを撃っていました。
--
-- ★どの呪文がこの耐性を見るかは ROM の分岐で確定しています
--   （`bank4.asm:6115-6215`）:
--
--     0x01 ギラ / 0x03 ベギラマ / 0x05 バギ / 0x0E イオナズン
--       -> `spell_damage`
--
-- ⚠ 耐性が読めなければ `nil` を返します（★0 と混ぜない）。
--   ★呼ぶ側は「分からない＝そのまま通る」として扱います
--     （⚠ 図鑑に載っていない初遭遇の敵で、呪文を封じないため）。
function Damage.spell_rate(enemy)
  if type(enemy) ~= "table" then return nil end
  local resist = enemy.resist
  if type(resist) ~= "table" then return nil end
  return Damage.success_rate(resist.spell_damage)
end

--- その敵のいまのHP。⚠ 読めなければ最大HP、それも無ければ nil。
--
-- ★`item_conditions.lua` の `enemy_hp` と同じ考え方です。
function Damage.enemy_hp(enemy)
  if type(enemy) ~= "table" then return nil end
  if type(enemy.hp) == "number" and enemy.hp > 0 then return enemy.hp end
  if type(enemy.max_hp) == "number" then return enemy.max_hp end
  return nil
end

--- 呪文1回ぶんの見積もり。
--
-- `spell` は `memory_map.spells[id]`（`damage_min` / `damage_max` /
-- `damage_avg` / `scope` を持つもの）。
--
-- 戻り値:
--   `{ min = 最低, avg = 平均, max = 最大 }`
--   ⚠ 威力が書かれていなければ `nil`（★推測で埋めない）。
function Damage.spell_damage(spell)
  if type(spell) ~= "table" then return nil end
  local avg = spell.damage_avg
  local low = spell.damage_min
  local high = spell.damage_max
  if type(avg) ~= "number" then return nil end
  -- ⚠ 幅が書かれていなければ平均で代用する（★無いものは作らない）
  if type(low) ~= "number" then low = avg end
  if type(high) ~= "number" then high = avg end
  return { min = low, avg = avg, max = high }
end

--- 通常攻撃（たたかう）1ターンぶんの見積もり（2026-08-08 / 依頼者の指摘）。
--
-- ## ★★★ なぜ要るのか
--
--   依頼者:
--     > サマルではやぶさの剣（2回攻撃）と、魔道士の杖（期待15ぐらい）だと、
--     > はやぶさのほうが守備力大きい敵以外には期待値高いように思える
--
--   ⚠⚠ **そのとおりでした。** 道具は `when: spell_may_damage`
--     （＝効く敵が居れば使う）だけで決めていて、
--     ★**通常攻撃と比べていませんでした**。
--
-- ## ⚠⚠ 式の出どころ（★ROM からではありません）
--
--     ダメージ ＝ (こうげき力 − 守備力/2) / 4 〜 (こうげき力 − 守備力/2) / 2
--
--   ★攻略情報を正本にしています。⚠ 呪文の威力表（`memory_map.spells`）と
--     **同じ扱い**です（あちらのコメントも「攻略情報を正本にし、ROM の値は
--     出典として併記」と書いています）。
--   ⚠ 該当ルーチンは bank4 の中にありますが、まだ特定できていません。
--
--   ⚠⚠ **だから「僅差」で判断を変えないこと。** ★呼ぶ側は余裕（margin）を
--     持って比べます（`Damage.beats_physical`）。
--
-- ## ★ 守備力が高い相手（★依頼者の言う「守備力大きい敵」）
--
--   こうげき力 <= 守備力/2 のときは、DQ2 では**かすり傷**になります。
--   ⚠ ここを 0 にすると「通常攻撃は無価値」と読めてしまうので、
--     ★小さい正の値（こうげき力/16 前後）を返します。
--   ⚠⚠ **この分岐の値はとくに粗い**（★実測していません）。
--
-- @param attack   こうげき力（★RAM から読んだ値）
-- @param defense  敵の守備力（★図鑑の値）。⚠ 分からなければ nil
-- @param hits     何回殴るか（★はやぶさのけんは 2）。既定 1
--
-- 戻り値: `{ min, avg, max, hits }`。⚠ こうげき力が分からなければ nil。
function Damage.physical(attack, defense, hits)
  local atk = tonumber(attack)
  if atk == nil or atk <= 0 then return nil end
  local n = tonumber(hits) or 1
  if n < 1 then n = 1 end

  -- ⚠ 守備力が読めない敵は **0 として扱いません**（★甘く見積もらない）。
  --   ★分からないときは「守備力が こうげき力の 1/4 ある」とみなします。
  --   ⚠⚠ 0 にすると、初見の敵に対して通常攻撃を過大評価します。
  local def = tonumber(defense)
  local guessed = false
  if def == nil then
    def = atk / 4
    guessed = true
  end

  local base = atk - def / 2
  local low, high
  if base <= 0 then
    -- ★かすり傷（⚠ 0 にしない / この値はとくに粗い）
    low, high = 0, atk / 16
  else
    low, high = base / 4, base / 2
  end
  return {
    min = low * n, avg = (low + high) / 2 * n, max = high * n,
    hits = n, defense_guessed = guessed,
  }
end

--- 道具（や呪文）が通常攻撃より**はっきり良い**か（2026-08-08）。
--
-- ⚠⚠ **僅差では入れ替えません。** ★物理の見積もりは攻略情報どまりなので、
--   1割2割の差で判断を変えると、⚠ 誤差で行ったり来たりします。
--
--   `margin` … 何倍以上なら「はっきり良い」とするか（★既定 1.0 ＝ 互角以上）
--
-- 戻り値: `使ってよいか, 理由`
-- ⚠ どちらかが見積もれなければ `true, nil`（★分からないことを理由に封じない）。
function Damage.beats_physical(item_avg, physical, margin)
  local a = tonumber(item_avg)
  if a == nil or physical == nil or physical.avg == nil then
    return true, nil
  end
  local m = tonumber(margin) or 1.0
  if a >= physical.avg * m then return true, nil end
  return false, string.format(
    "通常攻撃のほうが強い（★見込み %d に対し 通常攻撃 %d%s）",
    math.floor(a + 0.5), math.floor(physical.avg + 0.5),
    (physical.hits or 1) > 1
      and string.format(" / %d回攻撃", physical.hits) or "")
end

--- 1体に対する「無駄を除いたダメージ」。
--
-- ★敵の残HPを超えた分は数えません（`min(ダメージ, 残HP)`）。
--   ⚠ 超えた分を数えると、HP 5 の敵にイオナズンを撃つのが
--     「一番よい手」に見えてしまいます。
function Damage.effective(damage, enemy_hp)
  if type(damage) ~= "number" then return 0 end
  if type(enemy_hp) ~= "number" then return damage end
  if damage < enemy_hp then return damage end
  return enemy_hp
end

--- 確定で倒せるか。★**最低ダメージ**で判定します。
--
-- ⚠ 平均で判定すると「倒せるはずが倒せない」が起きます。
function Damage.certain_kill(estimate, enemy_hp)
  if type(estimate) ~= "table" or type(enemy_hp) ~= "number" then
    return false
  end
  return estimate.min >= enemy_hp
end

--- 平均では倒せるが、確定ではない。
function Damage.likely_kill(estimate, enemy_hp)
  if type(estimate) ~= "table" or type(enemy_hp) ~= "number" then
    return false
  end
  return (estimate.avg >= enemy_hp) and (estimate.min < enemy_hp)
end

--- その呪文が届く敵を選ぶ。
--
-- `scope`:
--   `single` … 指定した1体だけ
--   `group`  … 同じ `id` の敵すべて
--   `all`    … 生きている敵すべて
--
-- ⚠ `scope` が分からなければ `single` として扱います（★広く見積もらない）。
function Damage.targets(enemies, scope, index)
  local out = {}
  if type(enemies) ~= "table" then return out end
  if scope == "all" then
    for _, e in ipairs(enemies) do
      if (Damage.enemy_hp(e) or 0) > 0 then out[#out + 1] = e end
    end
    return out
  end
  local picked = enemies[index or 1]
  if picked == nil then return out end
  if scope ~= "group" then
    out[1] = picked
    return out
  end
  for _, e in ipairs(enemies) do
    if e.id == picked.id and (Damage.enemy_hp(e) or 0) > 0 then
      out[#out + 1] = e
    end
  end
  return out
end

--- 呪文1回ぶんの「効き目」をまとめて出す。
--
-- 戻り値:
--   ```
--   {
--     targets        = 届く敵の数,
--     effective      = 期待実効ダメージの合計,
--     certain_kills  = 確定で倒せる数,
--     likely_kills   = 平均なら倒せる数,
--     total_hp       = 届く敵の残HP合計,
--     wipes_targets  = 届いた敵を全部倒せるか（確定）,
--   }
--   ```
--   ⚠ 威力が分からなければ `nil`。
function Damage.evaluate_spell(spell, enemies, index)
  local estimate = Damage.spell_damage(spell)
  if estimate == nil then return nil end
  local scope = spell.scope or "single"
  local list = Damage.targets(enemies, scope, index)
  local out = { targets = #list, effective = 0, certain_kills = 0,
                likely_kills = 0, total_hp = 0, wipes_targets = false,
                immune = 0 }
  if #list == 0 then return out end
  local certain = 0
  for _, e in ipairs(list) do
    local hp = Damage.enemy_hp(e)
    out.total_hp = out.total_hp + (hp or 0)

    -- ★★ 呪文の通りやすさを掛ける（2026-08-03 に抜けていた）
    --   ⚠ 耐性が読めない敵は 1.0（そのまま通る）として扱う。
    --     ★図鑑に載っていない初遭遇の敵で呪文を封じないため。
    local rate = Damage.spell_rate(e)
    if rate == nil then rate = 1.0 end

    if rate <= 0 then
      -- ⚠⚠ **まったく効かない敵**。倒せる数にも実効ダメージにも数えない
      out.immune = out.immune + 1
    else
      out.effective = out.effective
        + Damage.effective(estimate.avg, hp) * rate
      -- ★確定撃破は「必ず効く」ときだけ（★1回でも外れる可能性があれば確定でない）
      if rate >= 1.0 and Damage.certain_kill(estimate, hp) then
        out.certain_kills = out.certain_kills + 1
        certain = certain + 1
      elseif Damage.likely_kill(estimate, hp)
        or (rate < 1.0 and Damage.certain_kill(estimate, hp)) then
        out.likely_kills = out.likely_kills + 1
      end
    end
  end
  -- ⚠ 効かない敵が1体でも居たら「全部倒せる」とは言えない
  out.wipes_targets = (certain == #list)
  return out
end

--- ★★ 2人の攻撃を合わせて倒せるか（指示書 §7 の中核）。
--
-- `a` と `b` は `evaluate_spell` の戻り値（どちらも同じ敵を狙う前提）。
-- `alive` は**その場に生きている敵の数**（★省略すると 1 とみなします）。
--
-- 戻り値:
--   `"a_alone"`  … ★a だけで倒しきれる（b は別の敵へ回してよい）
--   `"b_alone"`  … ★b だけで倒しきれる
--   `"either"`   … ★どちらでも倒しきれる（⚠ **選ぶのは呼ぶ側**）
--   `"together"` … ★2人ならちょうど倒せる
--   `"neither"`  … ⚠ 2人でも倒せない
--
-- ⚠⚠ **`wipes_targets` だけで決めてはいけません**（2026-08-03 に踏んだ）。
--   `wipes_targets` は「**届いた敵**を全部倒せるか」なので、
--   1 体にしか届かないギラでも `true` になります。
--   ★ドラキー 2 体に対して
--     サマルのギラ … 1 体だけ確定 → `wipes_targets = true`
--     ムーンのバギ … 2 体とも確定 → `wipes_targets = true`
--   となり、**先に見たほうが勝って「サマル単独で足りる」と誤判定**しました。
--
--   ★そこで「**その場の敵を何体倒せるか**」で見ます。
--
-- ⚠⚠ **どちらでも足りるときに、ここで選びません**（同日にもう一度踏んだ）。
--   最初は「多く倒せるほう」を返そうとしましたが、
--   ★両方が倒しきれるなら**戦闘はどちらでも終わる**ので、
--   本当に見るべきは MP や道具の残りです。
--   ⚠ ここは MP を知らないので、決めるのは筋違いでした。
--   ★`"either"` を返して、**呼ぶ側に選ばせます**（指示書 §7.2 の
--     「結果が同等なら MP 消費が少ないほう」は呼ぶ側の仕事）。
--
-- ⚠ どちらかが `nil`（威力が分からない）なら `nil` を返します。
function Damage.combined_verdict(a, b, enemy_hp, alive)
  if type(a) ~= "table" or type(b) ~= "table" then return nil end
  if type(enemy_hp) ~= "number" then return nil end
  local total = alive or 1
  -- ★単独で倒しきれるかは**確定撃破の数**で見る（平均だと取りこぼす）
  local a_clears = (a.certain_kills >= total)
  local b_clears = (b.certain_kills >= total)
  if a_clears and b_clears then return "either" end
  if a_clears then return "a_alone" end
  if b_clears then return "b_alone" end
  if (a.effective + b.effective) >= enemy_hp then return "together" end
  return "neither"
end

return Damage
