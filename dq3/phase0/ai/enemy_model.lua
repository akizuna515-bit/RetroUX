-- ★★ Enemy Action Model v1 ― 敵が「何を何回やるか」を ROM の重みから出す（RX3-0359 / 2026-09-21）★★
--
-- ## ⚠⚠ これは **shadow** です。★既存の判断は 1 つもここを読みません。
--
--   ```text
--   ★既存      g.threat / sit.enemy_dpt / sit.lose / sit.kind    ⚠ 触らない
--   ★新規      g.enemy_model_v1 / g.threat_v1 / sit.enemy_dpt_v1  ★誰も読まない
--   ```
--
-- ## ★なぜ要るか（RX3-0357 の実測）
--
--   ⚠ 現行は「敵の**攻撃力** × 手置き倍率（1.5 / 1.2）」しか見ていません。
--   ★ところが呪文・ブレスのダメージは**攻撃力と無関係**です。
--
--   ```text
--   ★物理だけの敵      トロル 1.00x / クラーゴン 0.91x   → ⚠ 現行でほぼ正しい
--   ⚠ 呪文が主の敵     ハンターフライ 10.6x / ドルイド 6.8x → ★現行は**桁で過小**
--   ⚠ 状態異常が主の敵  ミミック 0.28x（★行動の 92% が状態）→ ★現行は**過大**
--   ```
--
-- ## ★ROM の事実（RX3-0357 / RX3-0358 で確定 / JP ROM 照合済み）
--
--   ```text
--   重み表   JP bank4 $34C7 … 3 種 ＋ 順ぐり（★`select_mode` が選ぶ）
--   成立判定 `_b4_s28` … ⚠ 見るのは **MP / マホトーン / 対象の有無** の 3 つだけ
--   ⚠⚠ 耐性は 1 か所も見ない → ★状態異常も即死も「唱えてから失敗」
--   再抽選   ⚠ 不成立なら**その枠を除いて引き直す**（★byte_49）
--   全滅時   ★通常攻撃（move 2）へフォールバック
--   ```
--
-- ## ⚠ v1 で反映する成立条件は **4 つだけ**（依頼者 §7）
--
--   ```text
--   ① MP 不足      （★純粋な呪文 = gating_mode 2 のみ）
--   ② マホトーン    （★同上 / `$0530` bit5）
--   ③ 回復対象なし  （⚠ HP が閾値未満の仲間が居ない）
--   ④ 死者なし      （★蘇生）
--   ```
--   ⚠⚠ **耐性は入れません**（★それは「効果失敗」であって「行動不成立」ではない / RX3-0358 §9）。

local EnemyModel = {}

--: ★成立判定の型（⚠ 旧 `unknown_pair_10_11` / RX3-0358 で解決）
EnemyModel.GATING_SPELL = 2

--: ★枠の数（⚠ ROM の `ACTION_COUNT`）
EnemyModel.SLOTS = 8

--: ★`per_turn`（ROM の 2bit）→ 1 ターンの期待行動回数（RX3-0336）
--   ⚠⚠ 値そのものを掛けてはいけません（★0 は「0 回」ではなく「1 回」）。
EnemyModel.ACTIONS_PER_TURN = {[0] = 1.0, [1] = 1.5, [2] = 2.125, [3] = 2.0}

--: ★行動の選び方の重み（⚠ **ROM の事実** / JP bank4 $34C7）。★mode 3 は順ぐり = 均等
EnemyModel.WEIGHTS = {
  [0] = {32, 32, 32, 32, 32, 32, 32, 32},
  [1] = {18, 22, 26, 30, 34, 38, 42, 46},
  [2] = {2, 4, 6, 8, 10, 12, 14, 200},
  [3] = {1, 1, 1, 1, 1, 1, 1, 1},
}

--: ★フォールバックの行動（⚠ 8 枠すべて不成立なら通常攻撃 / `_bA_s3`）
EnemyModel.FALLBACK = "physical_damage"

--- ★`per_turn` の分類値 → 期待行動回数（⚠ 知らない値は**ふつうの敵**として 1.0）。
function EnemyModel.actions_per_turn(per_turn)
  local n = tonumber(per_turn)
  if n == nil then return 1.0 end
  return EnemyModel.ACTIONS_PER_TURN[n] or 1.0
end

--- ★★ その枠が**いま成立するか**（RX3-0358 の 4 条件だけ）。
--
--   `state` … {mp = 敵のいまの MP, silenced = bool,
--              heal_target = bool（★HP が閾値未満の仲間が居る）,
--              dead_target = bool（★死者が居る）}
--   ⚠ 分からない欄は**成立側**に倒します（★推測で敵を弱く見積もらない）。
--   ⚠ `gating_mode` は**敵ごと**の値です（★枠ごとではない / `acts.gating_mode`）。
function EnemyModel.can_act(slot, state, gating_mode)
  if slot == nil then return false end
  state = state or {}
  local spell = (tonumber(gating_mode) or 0) == EnemyModel.GATING_SPELL
    and (slot.mp or 0) > 0
  if spell then
    -- ① ⚠ MP が足りない（★MP が分からなければ止めない）
    local mp = tonumber(state.mp)
    if mp ~= nil and (slot.mp or 0) > mp then return false end
    -- ② ⚠ マホトーン（★`$0530` bit5）
    if state.silenced == true then return false end
  end
  -- ③ ⚠ 回復する相手が居ない
  if slot.needs_heal_target and state.heal_target == false then return false end
  -- ④ ⚠ 起こす相手が居ない
  if slot.needs_dead_target and state.dead_target == false then return false end
  return true
end

--- ★★ 実効の行動分布（⚠ 8 枠なので**近似せず数え上げ**ます / 依頼者 §6）。
--
--   ★不成立の枠はその場で除き、⚠ **残りの重みで正規化して引き直し**ます
--     （`sub_6840C` と同じ）。→ ★成立する枠だけで重みを分け合う形になります。
--   ⚠ 1 つも成立しなければ、★通常攻撃へのフォールバックを 1.0 で返します。
--
--   戻り値: `{[slot index] = 確率}`, フォールバックの確率
function EnemyModel.distribution(acts, state)
  local out, fallback = {}, 0.0
  if acts == nil or acts.slots == nil then return out, 1.0 end
  local w = EnemyModel.WEIGHTS[tonumber(acts.select_mode) or 0] or EnemyModel.WEIGHTS[0]
  local total = 0
  for i, slot in ipairs(acts.slots) do
    if EnemyModel.can_act(slot, state, acts.gating_mode) then
      out[i] = w[i] or 0
      total = total + (w[i] or 0)
    end
  end
  if total <= 0 then
    -- ⚠⚠ 全部不成立 → ★通常攻撃（move 2）へ（`_bA_s3` の `byte_49 == $FF`）
    return {}, 1.0
  end
  for i, v in pairs(out) do out[i] = v / total end
  return out, fallback
end

--- ★その枠 1 回ぶんの期待ダメージ（⚠ 状態異常・回復・バフは 0 / 別に数える）。
--
--   `phys` … その敵の物理 1 発の期待ダメージ（★呼ぶ側が守備力から出す）
--   ⚠ 呪文・ブレスの威力は生成物の `dmg`（★ROM の base/delta から）。無ければ 0。
local function slot_damage(slot, phys, party_n)
  local klass = slot.klass
  if klass == "physical_damage" then return phys or 0 end
  if klass ~= "magic_damage" then return 0 end
  local d = tonumber(slot.dmg) or 0
  if d <= 0 then return 0 end
  -- ★全体に届く呪文は人数ぶん（⚠ ブレスの範囲は名前に出ないので掛けない）
  if slot.party_wide then return d * math.max(party_n or 1, 1) end
  return d
end

--- ★★ その枠 1 回で**敵側に戻る HP**（RX3-0363 / ⚠ 回復と仲間呼びだけ）。
--
--   ```text
--   仲間を呼ぶ  ★呼ぶ敵の最大 HP がまるごと増える（⚠ `"self"` は自分と同じ敵）
--   全回復      ⚠ 相手の最大 HP まで（★上限 / 実際は削った分だけ）
--   ふつうの回復 ★ROM の量（⚠ 群に届くものは人数ぶん）
--   ```
--
--   ⚠⚠ **蘇生はここに入れません**（★戻る HP が未解析 / `RX3-0364`）。
--     ⚠ 0 と数えるのではなく、★別に「蘇生の割合」として出します。
local function slot_regen(slot, opts)
  local n = math.max(tonumber(opts.group_n) or 1, 1)
  -- ★★ 蘇生（RX3-0368 / ⚠ 最大 HP × 割合 × 成功率）。
  --
  --   ```text
  --   ザオリク（0x30）  ★全快 / 必ず成功        → 1.00 × 1.0
  --   ザオラル（0x2F）  ⚠ 半分 / 半々           → 0.50 × 0.5 ＝ 0.25
  --   ```
  --   ⚠ 生き返る相手は**群をまたぎます**（★`byte_54C` で選ばれた敵）。
  --     → ★場に居る中で一番 HP の高い敵で見積もります（⚠ 安全側 / 弱く見積もらない）。
  --   ⚠ 死者が居ないときは `can_act` が先に落とします（★`needs_dead_target`）。
  if slot.revives then
    local ratio = tonumber(slot.revive_ratio)
    local rate = tonumber(slot.revive_success)
    if ratio == nil or rate == nil then return 0 end       -- ⚠ 読めない版では数えない
    local hp = tonumber(opts.revive_hp) or tonumber(opts.hp_max) or 0
    return hp * ratio * rate
  end
  if slot.calls ~= nil then
    -- ⚠⚠ 戦闘に入る敵は **8 体まで**（★JP bank4 の空き探しが 16 バイト＝8 体）。
    --   ★埋まっていれば呼べません（⚠ 手番を 1 つ捨てる）。
    local limit = tonumber(opts.slot_limit)
    if limit ~= nil and (tonumber(opts.field_n) or 0) >= limit then return 0 end
    local hp
    if slot.calls == "self" then
      hp = opts.hp_max
    else
      -- ⚠⚠ 呼べるのは**もう場に居る種類**だけ（★JP bank4 $8E1C / RX3-0363）。
      --   ★居なければ何も起きません（⚠ 敵は手番を 1 つ捨てる）。
      if slot.calls_present_only and opts.present ~= nil
          and not opts.present[slot.calls] then
        return 0
      end
      if opts.hp_of ~= nil then hp = opts.hp_of(slot.calls) end
    end
    return tonumber(hp) or 0
  end
  if slot.heal_full then
    local hp = tonumber(opts.hp_max) or 0
    return slot.heal_group and (hp * n) or hp
  end
  local h = tonumber(slot.heal_hp) or 0
  if h <= 0 then return 0 end
  return slot.heal_group and (h * n) or h
end

--- ★★ その枠 1 回で**味方が失う手番**（RX3-0373 / 2026-09-22）。
--
--   ⚠⚠ **ダメージには足しません**（★依頼者 §10）。
--     ★眠り・麻痺・混乱・即死は性質が違いすぎます。
--     → ★**失う手番の数**という別の物差しで持ちます。
--
--   ```text
--   眠り    ★P × 2.737 ターン（⚠ ROM の表 $B4EF）
--   麻痺    ★P × 残りのターン（⚠ 戦闘中には治らない）
--   毒      ⚠ 手番は奇わない（★数えない）
--   ```
--
--   `opts.status` … {luck = 味方の運のよさ（平均）, sleep_turns = 眠りのターン,
--                     turns_left = 残りのターン（★麻痺用）}
--   ⚠ 読めないものは **0**（★推測で埋めない / ⚠⚠ 「危なくない」ではない）。
local function slot_lost_actions(slot, opts)
  if not slot.steals_turn then return 0, 0 end
  local prob = tonumber(slot.status_prob)
  if prob == nil then return 0, 0 end                       -- ⚠ 確率が読めない
  local st = opts.status or {}
  local luck = tonumber(st.luck)
  if luck == nil then return 0, 0 end                       -- ⚠ 運が分からない
  if luck < 0 then luck = 0 elseif luck > 255 then luck = 255 end
  local p = (384 - luck) * prob / 65536.0
  if p <= 0 then return 0, 0 end
  if p > 1 then p = 1 end
  if slot.status_kind == "sleep" then
    return p * (tonumber(st.sleep_turns) or 0), 0
  end
  if slot.status_kind == "confuse" then
    -- ★混乱は毎ターン 12.5% で覚めます（JP bank4 $97DF）→ ⚠ 期待 8 ターン。
    --   ⚠⚠ ただし**戦闘の長さで頭打ち**なので、★残りターンと短いほうを採ります。
    local want = tonumber(st.confuse_turns) or 0
    local left = tonumber(st.turns_left)
    if left ~= nil and left < want then want = left end
    return p * want, 0
  end
  if slot.status_kind == "paralyze" then
    -- ⚠⚠ 戦闘中には治りません（★`$073D` bit6 を落とすのは薬・呪文だけ）。
    --   ★何ターン続くかは戦況（残りターン）次第なので、⚠ **割合だけ**返します。
    return 0, p
  end
  return 0, 0
end

--- ★★ 敵 1 体ぶんのモデル（⚠ 純粋関数 / RAM も画面も見ない）。
--
--   `acts`  … 生成物の `enemies[id].acts`
--   `opts`  … {phys = 物理 1 発の期待値, party_n = 味方の人数, state = 上の `state`}
--   戻り値:
--   ```text
--   {physical, spell, breath, status, heal, buff, special, other}  ★1 行動あたりの確率
--   damage_per_action / damage_per_turn                            ★期待ダメージ
--   damage_by = {physical, spell, breath}                          ★1 ターンの**内訳**
--   party_wide                                                     ★全体攻撃の確率
--   acts_per_turn / fallback / gated                               ★診断用
--   ```
--
--   ⚠⚠ `damage_by` は**確率 × 総量ではありません**（RX3-0360）。
--   ★枠ごとの期待ダメージを種類別に足したものです。
--   ⚠ 確率 × 総量だと「どの種類も 1 発の威力が同じ」と仮定したことになり、
--     ★キメラで 物理 12.8 / ブレス 7.7（**本当は 11.1 / 9.4**）と逆さまに出ました。
function EnemyModel.of(acts, opts)
  opts = opts or {}
  -- ★`escape`（逃げる）は `special` から**分けます**（RX3-0371 / 依頼者 §3-1）。
  --   ⚠ 逃げるのと仲間を呼ぶのは**意味が逆**なので、★同じ箱に入れない。
  local share = {physical = 0, spell = 0, breath = 0, status = 0,
                 heal = 0, buff = 0, special = 0, escape = 0, other = 0}
  if acts == nil or acts.slots == nil then return nil end
  local dist, fallback = EnemyModel.distribution(acts, opts.state)
  local phys = tonumber(opts.phys) or 0
  local party_n = tonumber(opts.party_n) or 1
  local by = {physical = 0, spell = 0, breath = 0}
  local dmg, wide, gated = 0, 0, 0
  -- ★敵側に戻る HP と、⚠ **値を付けられない蘇生**の割合（RX3-0363）
  local regen, revive = 0, 0
  -- ★味方が失う手番（RX3-0373 / ⚠⚠ ダメージとは**別の勘定**）
  local lost, paralyze, status_unknown = 0, 0, 0
  -- ★手番は奪わないが、⚠ こちらの手を**弱める**もの（RX3-0375）
  local weaken = {illusion = 0, stopspell = 0}
  for i, slot in ipairs(acts.slots) do
    local p = dist[i]
    if p == nil then
      gated = gated + 1                          -- ⚠ いま成立しない枠の数（★診断）
    else
      local bucket = "other"
      local klass = slot.klass
      if klass == "physical_damage" then bucket = "physical"
      elseif klass == "magic_damage" then
        bucket = (slot.category == "breath") and "breath" or "spell"
      elseif klass == "status" then bucket = "status"
      elseif klass == "heal" then bucket = "heal"
      elseif klass == "support" then bucket = "buff"
      elseif klass == "escape" then bucket = "escape"
      elseif klass == "special" then bucket = "special"
      end
      share[bucket] = share[bucket] + p
      local d = p * slot_damage(slot, phys, party_n)
      dmg = dmg + d
      -- ★内訳は**その枠の期待ダメージ**を足します（⚠ 確率 × 総量ではない / RX3-0360）
      if by[bucket] ~= nil then by[bucket] = by[bucket] + d end
      if slot.party_wide then wide = wide + p end
      -- ★敵の粘り（⚠ ダメージとは**別の勘定** / 足し算しない）
      regen = regen + p * slot_regen(slot, opts)
      if slot.revives then revive = revive + p end
      -- ★手番を奪う行動（⚠ ダメージには足さない）
      local l1, l2 = slot_lost_actions(slot, opts)
      lost = lost + p * l1
      paralyze = paralyze + p * l2
      -- ⚠ マヌーサ・マホトーンは**別の欄**（★ダメージにも手番にも足さない）
      if slot.weakens ~= nil and weaken[slot.weakens] ~= nil then
        local prob = tonumber(slot.status_prob)
        local luck = tonumber((opts.status or {}).luck)
        if prob ~= nil and luck ~= nil then
          if luck < 0 then luck = 0 elseif luck > 255 then luck = 255 end
          local q = (384 - luck) * prob / 65536.0
          if q > 1 then q = 1 elseif q < 0 then q = 0 end
          weaken[slot.weakens] = weaken[slot.weakens] + p * q
        end
      end
      if bucket == "status" and not slot.steals_turn then
        status_unknown = status_unknown + p    -- ⚠ まだ値を付けられない
      end
    end
  end
  -- ⚠ 全部不成立なら通常攻撃（★フォールバック）
  if fallback > 0 then
    share.physical = share.physical + fallback
    dmg = dmg + fallback * phys
    by.physical = by.physical + fallback * phys
  end
  local per_turn = EnemyModel.actions_per_turn(acts.per_turn)
  for k, v in pairs(by) do by[k] = v * per_turn end
  return {
    share = share, party_wide = wide, damage_by = by,
    damage_per_action = dmg, damage_per_turn = dmg * per_turn,
    -- ★★ 敵の粘り（RX3-0363 / ⚠ 1 ターンに敵側へ戻る HP）
    --   ★`RX3-0368` で蘇生も `regen` に入りました（⚠ `revive_rate` は診断用に残します）。
    regen_per_turn = regen * per_turn, revive_rate = revive,
    -- ★★ 味方が失う手番（RX3-0373）。
    --   ⚠⚠ `status_unknown` は「危なくない」ではなく
    --     「**まだ値を付けられない**」の印です（`RX3-0374`）。
    lost_actions_per_turn = lost * per_turn,
    paralyze_rate = paralyze * per_turn, status_unknown = status_unknown,
    -- ★弱める状態の割合（RX3-0375 / ⚠⚠ ダメージにも手番にも足しません）
    illusion_rate = weaken.illusion * per_turn,
    stopspell_rate = weaken.stopspell * per_turn,
    acts_per_turn = per_turn, fallback = fallback, gated = gated,
    select_mode = tonumber(acts.select_mode) or 0,
  }
end

--- ★診断ログの 1 行（RX3-0359 / ⚠ 1 群 1 行 / 1 ターン 1 回）。
--
--   ⚠⚠ **ログの無い shadow は「動いているか分からない」**（★RX3-0356 の教訓）。
--
--   ⚠⚠ `alive_n` は**必ず渡してください**（RX3-0360）。
--   ★`legacy`（= `g.threat`）は**群の合計**です。⚠ モデルは**敵 1 体**ぶんなので、
--     人数を掛けないと**並べても比べられません**
--     （★実機で キメラ 4 体のとき legacy 71.1 / v1 20.5 と 3.5 倍ずれて出た）。
--   ★`party_n` も出します（RX3-0362）。⚠ 全体呪文は人数ぶん数えるので、
--     **人数が分からないとログから計算をやり直せません**
--     （★あとで「この行はいまの ROM で再現できるか」を見るのに要ります）。
function EnemyModel.tune(index, name, legacy, model, alive_n, party_n)
  if model == nil then
    return string.format("AI enemy_model g%s enemy=%s legacy=%s v1=none（★表が無い）",
                         tostring(index), tostring(name or "?"), tostring(legacy or "?"))
  end
  local n = tonumber(alive_n) or 1
  if n < 1 then n = 1 end
  local s, by = model.share, model.damage_by or {}
  return string.format(
    "AI enemy_model g%s enemy=%s alive=%d party=%d legacy=%.1f v1=%.1f "
    .. "physical=%.1f spell=%.1f breath=%.1f status_rate=%.2f heal_rate=%.2f "
    .. "buff_rate=%.2f special_rate=%.2f party_wide=%.2f "
    .. "mode=%d per_turn=%.3f gated=%d fallback=%.2f",
    tostring(index), tostring(name or "?"), n, tonumber(party_n) or 0,
    tonumber(legacy) or 0, model.damage_per_turn * n,
    (by.physical or 0) * n, (by.spell or 0) * n, (by.breath or 0) * n,
    s.status, s.heal, s.buff, s.special + s.escape, model.party_wide,
    model.select_mode, model.acts_per_turn, model.gated, model.fallback)
    .. string.format(" regen=%.1f revive_rate=%.2f",
                     (model.regen_per_turn or 0) * n, model.revive_rate or 0)
end

--- ★★ 予測の 1 行（RX3-0371 / ⚠ **敵が動く前**に出す / 機械で読む）。
--
--   ⚠⚠ これは人が読む `AI enemy_model` とは**別の行**です。
--     ★あとで「予測 vs 実測」を突き合わせるための、**鍵つきの記録**です。
--
--   ```text
--   AI predict battle=12 turn=3 group=1 enemy=121 slot=1 alive=2 party=4 …
--   ```
--
--   ⚠ 鍵に**フレーム数を使いません**（★セーブを読むと戻るため / `RX3-0167`）。
--     → ★`battle` / `turn` / `group` の 3 つで一意にします。
function EnemyModel.predict_line(battle_no, turn, g, model, alive_n, party_n, legacy,
                                 groups_n, field_n)
  if model == nil then return nil end
  local s, by = model.share, model.damage_by or {}
  local n = math.max(tonumber(alive_n) or 1, 1)
  return string.format(
    "AI predict battle=%s turn=%s group=%s enemy=%s alive=%d party=%d "
    .. "groups=%d field=%d select_mode=%d per_turn=%.3f "
    .. "physical_rate=%.4f spell_rate=%.4f breath_rate=%.4f status_rate=%.4f "
    .. "heal_rate=%.4f support_rate=%.4f escape_rate=%.4f special_rate=%.4f "
    .. "physical_dpt=%.2f spell_dpt=%.2f breath_dpt=%.2f damage_dpt=%.2f "
    .. "regen_v1=%.2f legacy_dpt=%.2f gated=%d fallback=%.3f",
    tostring(battle_no or "?"), tostring(turn or "?"), tostring(g and g.index or "?"),
    tostring(g and g.id or "?"), n, tonumber(party_n) or 0,
    -- ⚠⚠ 場に居る**群の数**と**敵の総数**（RX3-0372）。
    --   ★群が 2 つ以上のターンは、⚠ 実測を**どの敵に付けるか決められません**。
    tonumber(groups_n) or 0, tonumber(field_n) or 0,
    model.select_mode, model.acts_per_turn,
    s.physical, s.spell, s.breath, s.status,
    s.heal, s.buff, s.escape, s.special,
    (by.physical or 0) * n, (by.spell or 0) * n, (by.breath or 0) * n,
    model.damage_per_turn * n, (model.regen_per_turn or 0) * n,
    tonumber(legacy) or 0, model.gated, model.fallback)
end

--- ★★ 敵の粘りを入れた撃破ターンの 1 行（RX3-0363 / ⚠ 1 ターン 1 回）。
--
--   ⚠⚠ **`win` と `win_v1` は同じものさし**です（★どちらも「あと何ターンで倒せるか」）。
--   ⚠ `stalemate` は「長い」ではなく「**削り切れない**」です（★回復が削りに追いつく）。
function EnemyModel.endure(sit)
  if sit == nil then return nil end
  local regen = sit.enemy_regen_v1 or 0
  if regen <= 0 and not sit.stalemate_v1 then return nil end   -- ★粘らない敵は出さない
  local win_v1 = sit.stalemate_v1 and "削り切れない"
    or (sit.win_v1 ~= nil and string.format("%.1f", sit.win_v1) or "?")
  return string.format(
    "AI enemy_endure win=%s win_v1=%s our_dpt=%.1f regen=%.1f net=%.1f enemy_hp=%.0f",
    sit.win ~= nil and string.format("%.1f", sit.win) or "?", win_v1,
    sit.our_dpt or 0, regen, sit.net_dpt_v1 or 0, sit.enemy_hp or 0)
end

return EnemyModel
