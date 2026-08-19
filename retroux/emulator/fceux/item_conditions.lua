--- 戦闘中に道具を使う「条件」の判定（2026-08-01 / 課題 #62）。
--
-- ★★ **ここは RAM もメニューも知らない。** ★★
--   渡された数字を見て「使うか / 使わないか」を返すだけです。
--   ⚠ 知ってしまうと、条件を1つ試すのに実機が要ります。
--
-- ## なぜ条件が要るのか（依頼者の実機確認 2026-08-01）
--
--   > ちからのたてを使わない？（サマルトリア装備）
--   > ※本人へのベホイミなので本人向けの機能
--
--   > ひかりの剣をサマルトリアに渡した。マヌーサが聞きそうな的には使いたい
--
--   > いなずまの剣を手に入れた。ローレシアが雑魚多い場合は使いたい
--
--   いまの `battle_items` は「上から優先」で**いつでも使う**形でした。
--   ⚠ 杖（敵にダメージ）だけならそれでよかったのですが、
--     ・回復の盾を、無傷のときに使う
--     ・全体攻撃の剣を、敵1匹に使う
--   は明らかに無駄です。
--
-- ## 条件の種類
--
--   なし                使えるなら常に使う（従来どおり / 杖はこれ）
--   self_hp_below       **使う本人**のHPが割合を下回ったら
--   enemy_count_at_least 生きている敵が N 体以上なら
--   group_alive_at_least **同じ敵**が N 体まとまって生きていたら
--                        （`max_hp` を足すと、それ以下のHPの敵だけ数える）
--   status_may_land     その状態異常が**効きそうな敵が居たら**
--
--   `all: [...]` と書くと、**全部そろったときだけ**使います。
--
-- ⚠ 条件を書かなければ従来と同じ挙動です（既存の設定を壊しません）。

local Conditions = {}

--- その敵の「HP」。★いま残っているHPを優先し、無ければ最大HP。
--
-- ⚠⚠ どちらを見るかで意味が変わります（2026-08-01 の追加要望）:
--
--     > ローレシアのいなずまの剣は、敵HPが２０以下で、
--     > グループ敵が２体以上みたいな感じじゃないと逆にうまくいかない
--
--   ★狙いは「**1発で倒せる相手か**」なので、いま残っているHPが正解です。
--     ⚠ 傷ついた強敵も、残り15なら倒せます。
--   ★残りHPが読めないときだけ、種類としての最大HPで代用します
--     （memory_map の `monster_stats[id].max_hp`）。
local function enemy_hp(e)
  if e == nil then return nil end
  if e.hp ~= nil then return e.hp end
  return e.max_hp
end

--- 生きている敵の数。
-- @param enemies { {hp=..}, ... }
local function alive_count(enemies)
  local n = 0
  for _, e in ipairs(enemies or {}) do
    -- ⚠ hp が読めない個体は**居るものとして数える**。
    --   読めないことを理由に「敵が少ない」と判断すると、
    --   本当は多いのに全体攻撃を使わなくなる（安全でない側へ倒れる）。
    if e.hp == nil or e.hp > 0 then n = n + 1 end
  end
  return n
end

--- **同じ敵が何体まとまって生きているか**の最大数（2026-08-01 / 課題 #62）。
--
-- 依頼者の追加要望:
--     「いかづちの剣の使用条件はもっと厳しくしたい。
--       雑魚が１グループ複数で残っていたらぐらいでいいかもしれない。」
--
-- ★★ 「敵が3体」ではなく「**同じ敵が2体以上**」を見ます。★★
--   ⚠ 違う敵が1体ずつ3種類なら、全体攻撃の値打ちは薄い。
--     同じ敵がまとまっているときこそ効きます。
--
-- ⚠ **倒した個体は数えません**（`enemy_groups()` は最初の並びなので使えない）。
--
-- ★★ `max_hp` を渡すと、**それ以下のHPの敵だけ**を数えます
--   （2026-08-01 の追加要望 / 下の `enemy_hp` を参照）。
local function biggest_group(enemies, hp_cap)
  local counts = {}
  local best = 0
  for _, e in ipairs(enemies or {}) do
    -- ⚠ hp が読めない個体は生きているものとして数える（上と同じ理由）
    if e.hp == nil or e.hp > 0 then
      local weak = true
      if hp_cap ~= nil then
        local hp = enemy_hp(e)
        -- ⚠ HPが読めない敵は**数えない**。
        --   ★ここだけは「読めない＝弱い」と見なせません。強い敵に
        --     全体攻撃を撃つと1ターン無駄になるうえ、依頼者の
        --     「敵HPが20以下で」という条件の意味が消えます。
        weak = (hp ~= nil) and (hp <= hp_cap)
      end
      if weak then
        -- ★ID が読めない個体は**まとめない**（別々に数える）。
        --   まとめてしまうと、違う敵を同じ組と見なして使ってしまう。
        local key = e.id
        if key == nil then
          best = math.max(best, 1)
        else
          counts[key] = (counts[key] or 0) + 1
          best = math.max(best, counts[key])
        end
      end
    end
  end
  return best
end

--- その状態異常が効きそうな敵が居るか。
--
-- ★耐性は memory_map の `monster_stats[id].resist` から来ます。
--   値が小さいほど効きやすい（0 = 必ず効く）。
--
-- ⚠⚠ **耐性が読めない敵は「効くかもしれない」として数えます。**
--   読めないことを理由に使わないでいると、
--   「新しい敵にはいつまでも使わない」ことになります。
--   ★外しても1ターン損するだけ。使わないほうが損は大きい。
local function may_land(enemies, kind, threshold)
  local limit = threshold or 3
  for _, e in ipairs(enemies or {}) do
    if e.hp == nil or e.hp > 0 then
      local resist = e.resist and e.resist[kind]
      if resist == nil or resist < limit then return true end
    end
  end
  return false
end

--- この道具を、いま使ってよいか。
--
-- @param item   設定の1項目（`when` などを持つ）
-- @param ctx    { user = {hp=,max_hp=}, enemies = {...}, used = {道具ID=回数} }
-- @return boolean, string|nil  使うか, 使わない理由
function Conditions.allow(item, ctx)
  ctx = ctx or {}
  local when = item.when

  -- ★1戦闘に1回だけ（マヌーサのように、掛け直しても意味が薄いもの）
  if item.once_per_battle then
    local used = (ctx.used or {})[item.id] or 0
    if used > 0 then
      return false, "この戦闘では既に使いました"
    end
  end

  -- ★★ 条件を組み合わせる（2026-08-01）★★
  --   ⚠ 依頼者の要望は回を追って細かくなります。1つしか書けないと、
  --     そのたびに新しい条件名を足すことになり、名前が増え続けます。
  --   ★`all` は**全部そろったときだけ**使います。
  if item.all ~= nil then
    for _, part in ipairs(item.all) do
      -- ★`id` と `once_per_battle` は親のものを引き継ぐ
      -- ⚠⚠ **親から引き継ぐものを書き忘れると、子は黙って素通りします**
      --   （2026-08-08 に踏んだ）。★ を渡し忘れて、
      --      が「威力が分からない」で常に true でした。
      local sub = { id = item.id, when = part.when, ratio = part.ratio,
                    count = part.count, max_hp = part.max_hp,
                    status = part.status, resist_below = part.resist_below,
                    expected_damage = part.expected_damage
                      or item.expected_damage,
                    margin = part.margin or item.margin }
      local ok, why = Conditions.allow(sub, ctx)
      if not ok then return false, why end
    end
    return true, nil
  end

  if when == nil then
    return true, nil                       -- ★従来どおり（杖）
  end

  if when == "self_hp_below" then
    local u = ctx.user or {}
    -- ⚠ HPが読めなければ**使わない**。回復は急ぐものではないので、
    --   分からないまま使って1ターン損するより待つほうがよい。
    if u.hp == nil or u.max_hp == nil or u.max_hp <= 0 then
      return false, "HPが読めません"
    end
    local ratio = item.ratio or 0.5
    if u.hp / u.max_hp >= ratio then
      return false, string.format("HP %d/%d はまだ %d%% 以上です",
                                  u.hp, u.max_hp, math.floor(ratio * 100))
    end
    return true, nil
  end

  if when == "enemy_count_at_least" then
    local need = item.count or 3
    local got = alive_count(ctx.enemies)
    if got < need then
      return false, string.format("敵が %d 体（%d 体以上のときに使います）",
                                  got, need)
    end
    return true, nil
  end

  if when == "group_alive_at_least" then
    local need = item.count or 2
    local cap = item.max_hp
    local got = biggest_group(ctx.enemies, cap)
    if got < need then
      local limit = cap and string.format("HP%d以下の", cap) or ""
      return false, string.format(
        "%s同じ敵が最大 %d 体（%d 体まとまっているときに使います）",
        limit, got, need)
    end
    return true, nil
  end

  -- ★★★ **呪文と同じ効果の道具**（2026-08-07 / 依頼者の実機指摘）★★★
  --
  --   > キラーマシーン単体と戦闘。魔道士の杖を使っている？
  --
  -- ⚠⚠ まどうしのつえは**ギラと同じ効果**なのに、耐性を見ていませんでした。
  --   ★攻撃呪文の側は `attack_plan.lua` が守っていたのに、
  --     **道具だけ素通り**という「片側だけ」の状態でした。
  --
  -- ⚠⚠⚠ **判定は呪文と同じものを使います。** ★ここで別の式を書くと、
  --   片方だけ直したときに静かに食い違います（★今日それで何度も踏んだ）。
  if when == "spell_may_damage" then
    local kind = item.status or "spell_damage"
    -- ⚠ しきい値は書かなくてよい。★書かなければ「まったく効かない敵」だけを
    --   外します（`Damage.success_rate` と同じ規則）。
    local threshold = item.resist_below
    -- ⚠⚠⚠ **「敵が居ない」と「効かない敵しか居ない」を混ぜない**
    --   （2026-08-07 / 実機ログで発覚）★★★
    --   起動直後の戦闘外で「呪文が効かない敵しか居ません」と出ていました。
    --   ⚠ 敵は**0体**です。★理由が嘘だと、次に追うとき迷わせます。
    local alive = 0
    for _, e in ipairs(ctx.enemies or {}) do
      if e.hp == nil or e.hp > 0 then alive = alive + 1 end
    end
    if alive == 0 then
      return false, "⚠ 敵が居ません（★効かないという意味ではない）"
    end

    local any = false
    for _, e in ipairs(ctx.enemies or {}) do
      if e.hp == nil or e.hp > 0 then
        local resist = e.resist and e.resist[kind]
        -- ⚠⚠ **耐性が読めない敵は「効くかもしれない」として数えます。**
        --   ★読めないことを理由に使わないでいると、
        --     未知の敵にいつまでも使えません。
        if resist == nil then
          any = true
        elseif threshold ~= nil then
          if resist < threshold then any = true end
        elseif Conditions.spell_rate_of(resist) > 0 then
          any = true
        end
      end
    end
    if not any then
      return false, "呪文が効かない敵しか居ません（★杖は呪文と同じ効果）"
    end
    return true, nil
  end

  -- ★★★ 通常攻撃より強いときだけ使う（2026-08-08 / 依頼者の指摘）★★★
  --
  --   > サマルではやぶさの剣（2回攻撃）と、魔道士の杖（期待15ぐらい）だと、
  --   > はやぶさのほうが守備力大きい敵以外には期待値高いように思える
  --
  --   ⚠⚠ **そのとおりでした。** 杖は「効く敵が居れば使う」だけで、
  --     ★通常攻撃と**比べていませんでした**。
  --
  --   ⚠ 物理の見積もりは攻略情報どまりなので、**僅差では入れ替えません**
  --     （★`margin` を持って比べます）。
  --   ⚠⚠ 見積もれないときは**使ってよい**とします
  --     （★分からないことを理由に封じない）。
  if when == "beats_physical" then
    -- ⚠ 差し込み口は （★ が入れる名前）。
    local damage = Conditions._damage
    if damage == nil or damage.physical == nil then
      return true, nil                     -- ⚠ 見積もる道具が無い
    end
    local avg = tonumber(item.expected_damage)
    if avg == nil then
      return true, nil                     -- ⚠ 道具の威力が分からない
    end
    local attack = ctx.attack_power
    if attack == nil then
      return true, nil                     -- ⚠ こうげき力が読めない
    end
    -- ★いちばん**守備力が高い**敵で比べます。
    --   ⚠⚠ 平均にすると、硬い敵が1体混ざったときに読み違えます。
    local hardest = nil
    for _, e in ipairs(ctx.enemies or {}) do
      if (e.hp == nil or e.hp > 0) and e.defense ~= nil then
        if hardest == nil or e.defense > hardest then hardest = e.defense end
      end
    end
    local phys = damage.physical(attack, hardest, ctx.attack_hits)
    return damage.beats_physical(avg, phys, item.margin)
  end

  if when == "status_may_land" then
    local kind = item.status or "surround"
    if not may_land(ctx.enemies, kind, item.resist_below) then
      return false, string.format("%s が効きそうな敵が居ません", kind)
    end
    return true, nil
  end

  -- ⚠ 知らない条件は**使わない**。設定の綴り違いで、
  --   意図せず毎ターン使い続けるほうが困る。
  return false, string.format("知らない条件です: %s", tostring(when))
end

--- ★呪文ダメージの通りやすさ。⚠⚠ **`damage_estimate.lua` と同じ規則**。
--
-- ★呼ぶ側が `use()` で本物を差してくれば、そちらを使います。
--   ⚠ 差されていないときだけ、同じ式をここで持ちます
--     （★偽データの検査で読み込まなくても動くように）。
Conditions.RESIST_MAX = 7

function Conditions.spell_rate_of(resist_value)
  if Conditions._damage ~= nil then
    return Conditions._damage.success_rate(resist_value) or 1.0
  end
  if type(resist_value) ~= "number" then return 1.0 end
  if resist_value >= Conditions.RESIST_MAX then return 0.0 end
  if resist_value <= 0 then return 1.0 end
  return (Conditions.RESIST_MAX - resist_value) / Conditions.RESIST_MAX
end

--- ★本物の見積もりを差す（⚠ 規則を2か所に持たないため）。
function Conditions.use(damage_module)
  Conditions._damage = damage_module
end

Conditions.enemy_hp = enemy_hp
Conditions.alive_count = alive_count
Conditions.biggest_group = biggest_group
Conditions.may_land = may_land

return Conditions
