-- まんたん（やくそうでHPを満タンまで回復する）
--
-- ねらい: 宿屋の外で「どうぐ→やくそう→つかう→メッセージ送り」を人が何度も
-- 繰り返す作業をなくす。ビジョンどおり**待ち時間と反復作業だけ**を対象とし、
-- 難易度には触れない（消費するアイテムはゲーム内の在庫そのもの。増やさない）。
--
-- 実測で確定した経路（work/mantan/probe*.txt）:
--   menu=00 フィールド
--     -A-> 06 コマンドメニュー
--     -(1,1)へ寄せて A-> 15 持ち物一覧
--     -やくそうの行へ寄せて A-> 17 「つかう/わたす/すてる」
--     -行0(つかう)で A-> 04 メッセージ枠 -> +22フレームでHP回復 -> 01 メッセージ
--     -B を数回-> 00 フィールド
--
-- ★実測で外した推測（記録しておく。戻らないため）:
--   1. 「1人パーティなら対象選択は省略される」…**誤り**。0x17 は必ず出る。
--      ただし 0x17 は対象選択ではなく行動選択（つかう/わたす/すてる）だった。
--   2. 「メッセージは A で送る」…**誤り**。A では
--      01 -> 06 -> 04 -> 06 -> 04 ... と循環しフィールドに戻れない
--      （06 に戻った時点で A が「はなす」を実行してしまう）。**B で閉じる。**
--      同種の失敗は B-7（戦闘の ABAB 無限ループ）でも踏んでいる。
--
-- 設計上の約束:
--   ・入力は必ず bridge:request_input 経由。joypad.set を直接呼ばない
--     （入力の所有者はブリッジ一つ。docs/50-playbook.md #13）
--   ・**HPが増えたことを確認できなければ必ず中止する。**
--     押したつもりで回復していない状態でループすると、
--     アイテムを浪費し入力を吸い続ける。成否は機械的に検証できる
--     （HPの増加＋在庫の減少の2点。やくそう購入と同じ方式）
--   ・すべてのループに上限を置く。原因不明でも無限に回りうるループを残さない
--     （playbook #9）
--   ・0x17 では行0(つかう)に居ることを確認してから決定する。
--     行1(わたす)・行2(すてる)を誤って決定するとアイテムを失う
--
-- 2人以上のパーティでは経路が2段増える（B-11 / 実測 work/b11/probe.txt）:
--   1人: 00 -> 06 -> 15 -------> 17 --------> 04 -> 01
--   2人: 00 -> 06 -> 0E -> 15 -> 17 -> 11 -> 04 -> 01
--                    ^^^^          ^^^^
--                 持ち主選択      対象選択「だれに」
-- どちらも 1人のときは出ない。両方を受け付けて分岐する。
--
-- ⚠ 残っている未検証: **選んだ相手のHPが実際に増えるか**（行と人の対応）。
--   構造（メニューID・行数・行が並び順に対応すること）は実測で確定したが、
--   手持ちの2人セーブはHPが満タンで回復を観測できなかった。
--   対応がずれていた場合も「HPが増えなければ中止」で安全側に止まる。

local Mantan = {}
Mantan.__index = Mantan

-- 実測に基づく既定値
local DEFAULTS = {
  item_id     = 0x3C,   -- やくそう
  who         = 0,      -- 持ち物の持ち主（ローレシア）
  press_hold  = 8,      -- ボタンを押す長さ（探査で安定した値）
  press_gap   = 20,     -- 離してから次の操作までの間隔
  wait_menu   = 90,     -- メニュー遷移を待つ上限（実測は1フレーム）
  wait_heal   = 90,     -- HPが増えるのを待つ上限（実測は22フレーム）
  max_seek    = 12,     -- カーソルを寄せる試行の上限
  max_close   = 8,      -- B でメニューを閉じる試行の上限（実測は4回）
  max_uses    = 10,     -- 1回の実行で使うやくそうの上限
  frame_budget = 5400,  -- 全体の上限（約90秒）。これを超えたら中止
}

-- メニューID（memory_map.yaml と対応。ここでは判定にだけ使う）
local MENU_FIELD   = 0x00
local MENU_COMMAND = 0x06
local MENU_OWNER   = 0x0E   -- 持ち主選択（誰のどうぐを見るか）★2人以上のときだけ出る
local MENU_TARGET  = 0x11   -- 対象選択「だれに」★2人以上のときだけ出る
local MENU_ITEMS   = 0x15
local MENU_ACTION  = 0x17   -- つかう/わたす/すてる
local ROW_USE      = 0      -- 「つかう」

-- じゅもん経路（実測 work/hoimi/probe2.txt）
local MENU_CASTER  = 0x0D   -- 唱える人。★呪文を使える人だけが並ぶ（行数=その人数）
local MENU_SPELLS  = 0x14   -- 呪文リスト
local MENU_SPELL_TARGET = 0x10  -- 呪文の対象選択「だれに」（行数=加入者数）
local COL_JUMON_X, COL_JUMON_Y = 1, 0   -- コマンドメニューの「じゅもん」

-- ★2人以上のパーティでは経路が2段増える（B-11 / 実測 work/b11/probe.txt）:
--   1人: 00 -> 06 -> 15 -------> 17 --------> 04 -> 01
--   2人: 00 -> 06 -> 0E -> 15 -> 17 -> 11 -> 04 -> 01
--                    ^^^^          ^^^^
--                 持ち主選択      対象選択
-- 行はパーティの並び順に対応する（行0 = 1人目）。
-- 0x0E の行0 を選ぶとローレシアの持ち物が出たことで裏付けた。
-- 未加入メンバーは並びに入らないため、行番号は active_party() 内の位置で数える。
-- **メンバー番号（RAM上の 0..2）をそのまま行番号に使ってはいけない。**

-- opts.game / opts.bridge は必須。他は DEFAULTS を上書きする。
function Mantan.new(opts)
  local self = setmetatable({}, Mantan)
  self.game = opts.game
  self.bridge = opts.bridge
  self.on_progress = opts.on_progress
  -- 回復手段（優先順）。config の mantan.methods。
  -- 互換: 設定が無ければ従来どおり やくそう だけを使う。
  local mcfg = opts.config or {}

  -- 回復の目標割合。モード名で選ぶ（GUI からはモード名だけを渡せばよい）。
  -- opts.mode があればそれを優先する（command.json / GUI からの上書き用）。
  --
  -- ★モジュール側に既定を持つ。設定ファイルが無くても・古くても
  --   9割モードで動くようにするため（依頼者の指定: 既定は9割）。
  --   config の mantan.modes / mantan.mode があればそちらが優先される。
  local DEFAULT_MODES = {
    full    = { target_ratio = 1.0, label = "満タン" },
    ratio90 = { target_ratio = 0.9, label = "9割" },
  }
  local modes = mcfg.modes or DEFAULT_MODES
  local mode_name = opts.mode or mcfg.mode or "ratio90"
  local mode = modes[mode_name]
  if mode == nil then
    -- 知らないモード名は黙って無視せず、満タンにしてログに残せるようにする
    self.unknown_mode = mode_name
    mode = { target_ratio = 1.0, label = "満タン" }
    mode_name = "full"
  end
  self.mode_name = mode_name
  self.mode_label = mode.label or mode_name
  self.target_ratio = mode.target_ratio or 1.0

  -- ★★ **目標HPは割合で持つ**（2026-08-02 / 指示書 §6）★★
  --
  --   優先順（指示書 §6.2）:
  --     1. `target_hp_percent`（GUI で決めた値）
  --     2. 既存の mode（full / ratio90）
  --     3. どちらも無ければ 9割
  --
  --   ⚠ `mode` を消しません。`--mode full` を打つ手が覚えているためです。
  --   ⚠ ただし **`opts.mode` が明示されたときは mode を勝たせます**。
  --     その場で「満タンにしたい」と言われているのに、設定ファイルの
  --     90% で上書きしたら、指示を無視したことになります。
  local percent = mcfg.target_hp_percent
  if opts.mode == nil and type(percent) == "number"
    and percent >= 1 and percent <= 100 then
    self.target_ratio = percent / 100
    self.target_percent = percent
    self.mode_label = string.format("%d%%", percent)
  else
    self.target_percent = math.floor(self.target_ratio * 100 + 0.5)
  end

  -- ★まんたんの方針（指示書 §3.3）。⚠ 知らない値は安全側へ倒す。
  --   Python 側（`retroux/core/mantan/validation.py`）で検証済みだが、
  --   古い生成物が残っていることもあるので、ここでも確かめる。
  local function pick(value, allowed, fallback)
    if type(value) == "string" then
      for _, ok in ipairs(allowed) do
        if value == ok then return value end
      end
    end
    return fallback
  end
  local ITEM_POLICIES = { "before_spells", "after_spells", "disabled" }
  self.herb_policy = pick(mcfg.herb_policy, ITEM_POLICIES, "after_spells")
  self.antidote_policy = pick(mcfg.antidote_policy, ITEM_POLICIES,
                              "after_spells")
  self.mp_policy = pick(mcfg.mp_policy,
    { "remaining_ratio_balance", "spent_mp_balance", "most_mp", "list_order" },
    "remaining_ratio_balance")
  -- ★★ MP配分の効きぐあい（2026-08-03 / 依頼者の実機指摘）★★
  --
  --   ⚠⚠ 「残存MP率を揃える」を選んでいても、**安い呪文が必ず勝って**
  --     いました。比べる順が「総消費MP -> 過剰回復 -> MP配分」なので、
  --     ホイミ(MP3) と ベホイミ(MP5) では**同点にならず**、
  --     配分の出番が来なかったためです。
  --
  --   ★そこで「偏っている人が唱える候補は、MPが高くついたことにする」。
  --
  --       実効MP = 総消費MP × (1 + (みんなの平均率 - 唱える人の率) × 重み)
  --
  --   ★重み 2 のとき（実データで確かめた / ログ 21:43:53）:
  --
  --     | 率の差 | ホイミ(MP6) | ベホイミ(MP10) | 選ぶもの |
  --     | 0%    | 6.00 | 10.00 | ★ホイミ（安い） |
  --     | 10%   | 6.60 |  9.00 | ★ホイミ |
  --     | 20%   | 7.20 |  8.00 | ★ホイミ |
  --     | 31%   | 7.86 |  6.90 | ★★ベホイミ（率の高い人） |
  --
  --   ⚠ 0 にすると補正が消え、**これまでどおり安い呪文だけ**で選びます。
  self.mp_balance_weight = tonumber(mcfg.mp_balance_weight) or 2.0
  if self.mp_balance_weight < 0 then self.mp_balance_weight = 0 end
  -- ⚠ 指示書 §3.3「現時点では選択肢を増やさない」。★増やすときはここへ足す
  self.spell_policy = pick(mcfg.spell_policy,
    { "minimum_expected_total_mp" }, "minimum_expected_total_mp")
  -- ⚠ `~= false` にする。**設定が無いときは使う**（既定 ON / 指示書 §5.2）
  self.healing_spells_enabled = mcfg.healing_spells_enabled ~= false
  self.poison_cure_enabled = mcfg.poison_cure_enabled ~= false
  self.use_tactics_reserve = mcfg.use_tactics_reserve ~= false
  -- ★設定を読んだときに気づいたこと。**黙って捨てない**（画面とログへ）
  self.settings_problems = mcfg.settings_problems or {}

  -- ★このまんたん処理の中だけで数える消費MP（指示書 §9.3）。
  --   ⚠ ファイルにも DB にも残しません。1回ぶんの話です。
  self.spent_mp = {}

  self.methods = mcfg.methods
  if self.methods == nil or #self.methods == 0 then
    self.methods = { { kind = "item", id = opts.item_id or 0x3C, name = "やくそう" } }
  end

  -- ★毒を治す（依頼者の要望「毒のときはキアリー、毒消し草を使ってほしい」）。
  --
  -- ⚠ かつては既定で有効にできるのが**どくけしそう（道具）だけ**だった。
  --   道具はアイテムIDで確実に特定できるのに、**呪文は行番号でしか指定できず**
  --   （呪文の所持リストは RAM に無い、と思っていた / DEV-17）、
  --   行番号を間違えたときの被害が道具とは比べものにならなかった:
  --     隣が **ルーラ** だと**町へ飛ばされる**。プレイ中には取り返しがつかない。
  --
  -- ★2026-07-26: 習得済み呪文のビット($0618-$061B)が見つかり、
  --   **行番号を呪文IDから計算できる**ようになった（dq2.lua:find_spell_pos）。
  --   呪文も道具と同じ「IDで指定する」形に揃った。
  --   計算できない・設定と食い違うときは唱えず、道具へ落ちる（_spell_usable）。
  self.cure_poison = mcfg.cure_poison ~= false
  self.cure_methods = mcfg.cure_methods
  if self.cure_methods == nil or #self.cure_methods == 0 then
    self.cure_methods = { { kind = "item", id = 0x3B, name = "どくけしそう" } }
  end

  -- ★★ 誰のMPから使うか（2026-08-01 / 課題 #57）★★
  --   most_mp    … MPの残りが多い人の呪文から（既定）
  --   list_order … 書いてある順（従来）
  -- ⚠ 知らない値が来たら**既定へ倒す**（起動を止めない）。
  self.cure_order = mcfg.cure_order or "most_mp"
  if self.cure_order ~= "most_mp" and self.cure_order ~= "list_order" then
    self.cure_order = "most_mp"
  end

  -- ★呪文の行番号をどこから取るか（2026-07-26 / 上の警告への対策B）。
  --
  --   verify   … 設定の row と**ビットから計算した行**の両方を出し、
  --               **一致したときだけ**唱える。食い違えば唱えず報告する（既定）。
  --   computed … 計算だけを使う（設定の row は見ない）。
  --   config   … 従来どおり設定の row だけ（計算が壊れたときの逃げ道）。
  --
  --   いきなり computed にしないのは依頼者の指示（「両方が一致することを
  --   確かめてから移行する」）。verify は移行の途中段階そのもので、
  --   実機で一度も食い違わないことを確認できたら computed へ落とす。
  --   ★実機に入る前に全10セーブステートで一致を確認済み
  --     （research/probes/active/check_spellrows.py / 10件すべて 計算=1 設定=1）。
  self.spell_row_source = mcfg.spell_row_source or "verify"
  self.spell_row_notes = {}     -- 同じ理由を何度も報告しないための記録
  self.cures = 0
  self.max_cures = mcfg.max_cures or 6
  for k, v in pairs(DEFAULTS) do
    self[k] = (opts[k] ~= nil) and opts[k] or v
  end
  self.phase = "check"
  self.hold = 0
  self.tries = 0
  -- 寄せ専用のカウンタ（待ちの tries とは独立。_seek_row のコメント参照）
  self.seek_tries = 0
  self.seek_key = nil
  self.frames = 0
  self.uses = 0
  self.closes = 0
  self.status = "running"     -- running / done / abort
  self.reason = nil
  self.hp_start = nil
  self.herbs_start = nil
  return self
end

----------------------------------------------------------------------
-- 状態の読み取り
----------------------------------------------------------------------

function Mantan:_menu()
  return self.game:menu_state()
end

-- 加入しているメンバーのみ。★未加入メンバーの残留HPを見てはいけない（DEV-11）
function Mantan:_members()
  return self.game:active_party()
end

-- 指定メンバー（RAM上のメンバー番号）の所持数
function Mantan:_herb_count_of(who, item_id)
  local target = item_id or self.item_id
  local inv = self.game:inventory(who)
  local spec = self.game.a.inventory
  local n = 0
  for i = 0, (spec and spec.slots or 8) - 1 do
    if inv[i] == target then n = n + 1 end
  end
  return n
end

-- パーティ全体の在庫。誰の持ち物からでも使えるため合計で数える。
function Mantan:_herb_count()
  local n = 0
  for _, m in ipairs(self:_members()) do
    n = n + self:_herb_count_of(m.index)
  end
  return n
end

-- 在庫を持っている持ち主を選ぶ。
-- 戻り値: 行番号（0始まり / active_party 内の位置）, メンバー番号, 名前
--
-- ★生きている持ち主を優先する。
--   0x0E（どうぐの持ち主）には死者も並ぶ（実測: 死亡1人を含めて行数3＝加入者数）
--   ので行番号はずれない。それでも、死んだ人に道具を使わせる挙動は
--   ゲーム側で拒否される可能性があるため、生存者から選べるならそちらにする。
--   生きている持ち主が居ない場合だけ死者の持ち物を試す
--   （実行後に「HPが増えて在庫が減った」を検証するので、駄目なら中止できる）。
function Mantan:_pick_owner(item_id)
  local members = self:_members()
  local alt_row, alt_who, alt_name = nil, nil, nil
  for pos, m in ipairs(members) do
    if self:_herb_count_of(m.index, item_id) > 0 then
      if m.alive then return pos - 1, m.index, m.name end
      if alt_row == nil then alt_row, alt_who, alt_name = pos - 1, m.index, m.name end
    end
  end
  return alt_row, alt_who, alt_name
end

-- 呪文を使えるメンバー。★最大MPが 0 より大きい人だけが 0x0D に並ぶ（実測）。
-- ローレシアは MP 0/0 のため並ばず、行数が加入者数と一致しない。
--
-- ★★ 死者もこのリストに含める ★★
--   実測（work/mantan/dead.txt / スロット4）: ムーンブルクが死亡した状態で
--   ゲーム側の 0x0D の行数は **2**（生きている呪文使い1人 + 死者1人）だった。
--   **ゲームは死者も並べる。**
--   したがって死者を除いて数えると**行番号がずれて別の人を選ぶ**
--   （playbook #27 と同じ「行に並ぶ集合を取り違える」誤り）。
--   例: サマルトリアが死亡・ムーンブルク生存のとき
--     ゲーム: 行0 サマルトリア(死) / 行1 ムーンブルク
--     死者を除いた数え方: 行0 ムーンブルク -> **死んだサマルトリアを選んでしまう**
--
--   そこで**リストの構成は変えない**。「死者を選ばない」のは _pick_caster() で行う。
function Mantan:_casters()
  local out = {}
  local p = self.game.a.party
  local spec = p.fields.max_mp
  if spec == nil then return out end
  for _, m in ipairs(self:_members()) do
    local max_mp = memory.readbyte(spec.offset + m.index * p.member_stride)
    if max_mp > 0 then out[#out + 1] = m end
  end
  return out
end

function Mantan:_current_mp(member)
  local p = self.game.a.party
  local spec = p.fields.current_mp
  if spec == nil then return 0 end
  return memory.readbyte(spec.offset + member.index * p.member_stride)
end

--- その人の最大MP。⚠ **分からなければ nil**（0 と混ぜない）。
---
--- ⚠⚠ **`member.max_mp` は存在しない**（2026-08-02 に実データで判明）。
---   `_casters()` は最大MPを読んで**絞り込みに使うだけ**で、返す要素には
---   付けていない。`caster.max_mp` を見ていた私の MP配分は nil になり、
---   「残存MP率を揃える」が**実データでは一切効いていなかった**。
---   ★偽データを渡すハーネステストでは通っていた。実データで露呈した。
function Mantan:_max_mp(member)
  local p = self.game and self.game.a and self.game.a.party
  if p == nil then return member.max_mp end       -- ★差し替え時は素直に返す
  local spec = p.fields.max_mp
  if spec == nil then return member.max_mp end
  local value = memory.readbyte(spec.offset + member.index * p.member_stride)
  if value == nil or value <= 0 then return nil end
  return value
end

-- 呪文を唱えられる人を選ぶ。
-- 戻り値: 行番号（0始まり / **唱える人リスト内**の位置）, メンバー, 残MP
--
-- ★★ 死んだ人は選ばない ★★
--   依頼者の報告: 「死者が出たときのまんたんの動き確認して。薬草が使われない気がする」
--
--   原因（work/mantan/dead.txt で確認）: ここが生死を見ていなかった。
--   MPが最も多い人を選ぶため、**死んだムーンブルク（MP8）**を
--   サマルトリア（MP7）より優先して唱え手に選んでいた。
--   その結果 _pick_method() が「呪文が使える」と判断して呪文を返し、
--   **やくそうへ進まなかった**（＝何も回復されない）。
--
--   ⚠ 行番号は**リスト内の位置のまま**使う。死者を除いて数え直してはいけない
--     （ゲーム側は死者も並べる。_casters() の説明を参照）。
-- ★★ want で唱える人を固定できる ★★
--
--   **呪文の行番号は人によって違う。** 誰が唱えるか分からないまま行を指定すると、
--   別の人の同じ行にある別の呪文を唱えてしまう。
--   キアリーで実際に問題になった（work/mantan/kiari.txt）:
--     サマルトリアの行1 = キアリー（実測で確定）
--     しかし _pick_caster はMPが最も多い人を選ぶため、
--     MPの多いムーンブルクが選ばれる。彼女の行1は未確認で、
--     **ルーラだったら町へ飛ばされる**（取り返しがつかない）。
--
--   そこで methods に caster を書けるようにした。名前でもメンバー番号でもよい。
--     - { kind: spell, name: キアリー, row: 1, caster: samaltria }
--   caster が無い / "auto" なら従来どおりMPが最も多い人を選ぶ。
--
--   ⚠ 固定しても「その人のその行が本当にその呪文か」は保証されない
--     （覚える順で行はずれる）。だから効果での検証は今までどおり行う。
--
-- ★★ 候補は**MPの多い順に全員**返す（2026-07-26）★★
--   1人だけ返していたときの不具合（実機ログ 12:47:56 / 12:51:52）:
--     ホイミ(0x09) を指定 -> MPが最も多い ムーンブルク が選ばれる
--     -> 彼女は ホイミ を覚えない（持っているのは Healmore）
--     -> 「計算できない」で呪文ごと諦め、**やくそうを消費した**（5個 -> 2個）。
--   サマルトリアは ホイミ を使えたのに、MPの多い人しか見ていなかったため
--   気づけなかった。**唱えられる人が他に居るなら、そちらを使う。**
function Mantan:_casters_for(mp_cost, want)
  if want == "auto" then want = nil end
  local out = {}
  for pos, m in ipairs(self:_casters()) do
    local ok = m.alive
    if ok and want ~= nil then
      -- 名前（memory_map の party.members）かメンバー番号で指定できる
      ok = (tostring(m.name) == tostring(want)) or (m.index == tonumber(want))
    end
    if ok then
      local cur = self:_current_mp(m)
      -- ★MPの予約（Phase 6 P5）。依頼者の指定「まんたんのときも有効」。
      --   ルーラ・リレミトのぶんは残す。判定は DQ2:mp_reserve に集約してある
      --   （戦闘AIと**同じ数字**を使う。別々に計算すると静かに食い違う）。
      -- ★★ 戦術プロフィールの「最低残存MP」もここで効かせる ★★
      --   （2026-08-01 / 依頼者「まんたんの時、最低MP保持が効かない」）
      --
      --   ⚠⚠ それまでは `mp_reserve`（ルーラ・リレミトのぶん）しか
      --     見ておらず、戦闘では効く設定がまんたんでは無視されていた。
      --   ★足さず**大きいほうを採る**規則は `DQ2:reserved_mp` に1か所だけ。
      local reserve, breakdown = 0, nil
      if self.game.reserved_mp ~= nil then
        reserve, breakdown = self.game:reserved_mp(m.index,
                                                   self:_reserve_floor(m))
      elseif self.game.mp_reserve ~= nil then
        reserve, breakdown = self.game:mp_reserve(m.index)
      end
      if cur >= (mp_cost or 0) + reserve then
        out[#out + 1] = { row = pos - 1, member = m, mp = cur }
      elseif reserve > 0 and cur >= (mp_cost or 0) then
        -- ★「唱えられるのに予約で使わない」は必ず理由を残す。
        --   ここで黙って落ちると、**やくそう（ゴールドで買った在庫）が
        --   静かに減る**。利用者から見れば「なぜ呪文を使わないのか」が
        --   分からないまま在庫が消える（playbook #46 と同じ形）。
        --
        -- ⚠ _note_once を使う。_casters_for は回復のたびに呼ばれるので、
        --   毎回出すと同じ行が並んで本当の問題が埋もれる（playbook #4）。
        self:_note_once("mp_reserve:" .. tostring(m.index),
          string.format(
            "%s は %s のMPを残すため唱えません（残り%d / 必要%d + 予約%d）",
            m.name, breakdown or "予約", cur, mp_cost or 0, reserve))
      end
    end
  end
  table.sort(out, function(a, b) return a.mp > b.mp end)
  return out
end

-- MPが最も多い1人だけを返す従来の形（呪文以外の用途と互換のために残す）。
function Mantan:_pick_caster(mp_cost, want)
  local list = self:_casters_for(mp_cost, want)
  local first = list[1]
  if first == nil then return nil, nil, nil end
  return first.row, first.member, first.mp
end

-- パーティ全体のMP合計（報告用）
function Mantan:_total_mp()
  local sum = 0
  for _, m in ipairs(self:_members()) do sum = sum + self:_current_mp(m) end
  return sum
end

-- 呪文リスト(0x14)で、その呪文が何行目にあるかを決める。
-- 戻り値: 行番号, 説明 / 決められなければ nil, 理由
--
-- ★★ ここが「行番号を設定に書く」のをやめるための入口 ★★
--
--   設定の row は**書いた時点のスナップショット**でしかない。
--   呪文を覚えると並びが変わり、人が違えば並びも違う。古い数字を押すと
--   別の呪文を唱える。隣が ルーラ なら**町へ飛ばされて戻せない**。
--
--   習得済みビット($061A/$061B)から行を**計算**すれば、覚えても人が違っても
--   ずれない。計算の根拠は ROM（memory_map の learned_spells / dq2.lua）。
--
--   ⚠ 計算できない・食い違うときは**唱えない**。行番号を推測して押すより、
--     呪文を諦めて道具（どくけしそう・やくそう）へ落ちるほうが安全。
--     壊れ方を「効かない」に限定する（仕様7章の約束）。
function Mantan:_resolve_spell_row(method, caster)
  local name = self:_method_name(method)
  local cfg_row = method.row
  local src = self.spell_row_source

  if src == "config" then
    if cfg_row == nil then return nil, string.format("%s の行番号が設定に無い", name) end
    return cfg_row, string.format("設定の行%d", cfg_row)
  end

  if method.id == nil then
    -- ID が無いと計算できない。設定の行をそのまま押すのは危ないので唱えない。
    return nil, string.format(
      "%s に呪文ID(id)が設定されていないため行番号を計算できない", name)
  end
  if self.game.find_spell_pos == nil then
    return nil, "この dq2.lua は呪文の行番号を計算できない（更新が必要）"
  end

  -- ★拒否リストは**位置を計算する前**に見る（2026-07-26 / Phase 6 P4-0）。
  --   計算のあとだと、拒否する呪文でも一度は位置を引いてしまう。
  --   「押さない」だけでなく「探しにも行かない」ほうが経路が短く、間違いが減る。
  if self.game.spell_denied ~= nil then
    local denied = self.game:spell_denied(method.id)
    if denied ~= nil then
      return nil, string.format("%s は唱えない指定になっている（%s）", name, denied)
    end
  end

  -- ★マホトーンで封じられている人には唱えさせない。
  --   押しても呪文リストが開かず、上限まで押してから諦めることになる。
  if self.game.spell_blocked ~= nil then
    local blocked = self.game:spell_blocked(caster.index)
    if blocked ~= nil then
      return nil, string.format("%s は %s（%s）", caster.name, blocked, name)
    end
  end

  local row, col, entry = self.game:find_spell_pos(method.id, caster.index, "field")
  if row == nil then
    -- entry には理由の文字列が入っている
    return nil, string.format("%s の行番号を計算できない（%s / %s）",
      name, tostring(entry), caster.name)
  end
  -- フィールドの呪文リストは1列。列が付いたら前提が違う
  if col ~= 0 then
    return nil, string.format("%s が1列目に無い（列%d）", name, col)
  end
  -- ★三重の歯止め: **計算した先に何があるか**でもう一度見る。
  --   上の spell_denied(method.id) は「設定に書いた呪文」を見ているが、
  --   ここは「実際にその位置にある呪文」を見ている。**別のことを見ている。**
  --   計算が壊れて別の呪文を指した場合に効くのはこちら。
  if entry.info ~= nil and self.game.spell_denied ~= nil and entry.id ~= nil then
    local denied = self.game:spell_denied(entry.id)
    if denied ~= nil then
      return nil, string.format(
        "計算した行%d には %s があり、唱えない指定になっている（%s）",
        row, tostring(entry.name), denied)
    end
  elseif entry.info ~= nil and entry.info.irreversible then
    -- 古い dq2.lua（spell_denied が無い）向けの受け皿
    return nil, string.format("%s は取り返しがつかない呪文なので唱えない", entry.name)
  end

  if src ~= "verify" or cfg_row == nil then
    return row, string.format("計算した行%d（%s の %s）", row, caster.name, entry.name)
  end

  if cfg_row == row then
    return row, string.format("行%d（設定と計算が一致 / %s の %s）",
      row, caster.name, entry.name)
  end

  -- ★食い違い。設定の行に**いま何があるか**まで出す（ルーラなら特に重要）。
  local at_cfg = "不明"
  for _, e in ipairs(self.game:learned_spells(caster.index, "field")) do
    if e.row == cfg_row and e.col == 0 then at_cfg = e.name end
  end
  return nil, string.format(
    "%s の行番号が食い違う（設定=%d / 計算=%d / %s の行%d にあるのは %s）"
    .. " -> 唱えない。設定を直すか spell_row_source を computed にしてください",
    name, cfg_row, row, caster.name, cfg_row, at_cfg)
end

-- 手段の表示名。設定に name が無ければ memory_map の呪文名を使う。
-- ★日本語名が未確定の呪文は英語名のまま出す（推測で日本語名を書かない方針）。
function Mantan:_method_name(mth)
  if mth.name ~= nil then return mth.name end
  if mth.id ~= nil and self.game.spell_name ~= nil then
    return self.game:spell_name(mth.id)
  end
  return "呪文"
end

-- いま押すべき呪文の行。_resolve_spell_row が決めた値を使う。
-- 互換のため、決まっていなければ従来どおり設定の row に落ちる。
function Mantan:_want_spell_row()
  if self.spell_row ~= nil then return self.spell_row end
  return (self.method and self.method.row) or 0
end

-- 決定の直前に「その行にいま何があるか」を確かめる。
-- 戻り値: 真偽, 理由（偽のときだけ）
--
-- ★_resolve_spell_row と重複しているように見えるが、役割が違う。
--   あちらは「どの行を狙うか」を決める。こちらは**押す直前の最終確認**で、
--   DEV-12（どうぐの わたす／すてる 対策）と同じ位置づけ。
--   呪文IDが分からない設定では確かめようがないので通す（従来の動作）。
function Mantan:_row_still_matches(row)
  local mth = self.method
  if mth == nil or mth.id == nil then return true end
  if self.caster == nil or self.game.learned_spells == nil then return true end

  for _, e in ipairs(self.game:learned_spells(self.caster.index, "field")) do
    if e.col == 0 and e.row == row then
      if e.id == mth.id then return true end
      return false, string.format(
        "行%d にあるのは %s で、唱えたい %s ではない（%s）",
        row, e.name, mth.name or "呪文", self.caster.name)
    end
  end
  return false, string.format("行%d に呪文が無い（%s）", row, self.caster.name)
end

-- 呪文の手段が本当に使えるか。使えるなら 説明, 呪文の行番号 を返す。
-- 使えなければ nil（呼び出し側は次の手段＝道具へ落ちる）。
--
-- ★唱える人が居るだけでは足りない。**行番号を確定できて初めて使える**。
--   確定できないまま呪文へ進むと、行を推測して押すことになる。
function Mantan:_spell_usable(mth)
  local list = self:_spell_usable_all(mth)
  local first = list[1]
  if first == nil then return nil, nil end
  return first.detail, first.pick
end

--- ★★ その呪文を唱えられる人を**全員ぶん**返す（2026-08-03）。
---
--- ⚠⚠ **依頼者の実機指摘で分かった穴**:
---
---     「まんたんで残りMPの率を揃えるが効いていない
---       （サマルトリアを使いすぎている）」
---
---   ★原因は `_spell_usable` が**MP絶対量の1位で確定**していたこと。
---   `_mp_balance_score` は**決まった後の候補に点数を付ける**だけなので、
---   術者選びには一切効いていませんでした。
---
---   ★そこで「サマルが唱える」「ムーンが唱える」を**別の候補**にし、
---     並べ替え（`_rank_healing_methods`）に MP配分を効かせます。
---
--- 戻り値: `{ { detail, pick, caster }, ... }`（★MP の多い順）
function Mantan:_spell_usable_all(mth)
  local out, last_note = {}, nil
  for _, c in ipairs(self:_casters_for(mth.mp_cost or 0, mth.caster)) do
    local spell_row, note = self:_resolve_spell_row(mth, c.member)
    if spell_row ~= nil then
      out[#out + 1] = {
        detail = string.format("%s（%s のMP %d / %s）",
          self:_method_name(mth), c.member.name, c.mp, note),
        pick = { spell_row = spell_row, caster_row = c.row,
                 caster = c.member },
        caster = c.member,
      }
    else
      last_note = note
    end
  end
  -- 黙って道具へ落ちない。理由を必ず1回は出す（playbook #35）
  if #out == 0 and last_note ~= nil then
    self:_note_once("row:" .. tostring(self:_method_name(mth)), tostring(last_note))
  end
  return out
end

-- 使える回復手段を優先順に探す。戻り値: 手段, 説明, 選んだ内訳（呪文のときだけ）
--- 道具を呪文の前に出すか、後ろに回すか、混ぜないか（指示書 §7.1）。
---
--- 戻り値は並べ替えの重み。★小さいほど先。
--- ⚠ `disabled` は nil を返す（＝候補に入れない）。
function Mantan:_item_priority(policy)
  -- ⚠ nil は「設定が無い」＝既定（after_spells）。`disabled` と混ぜない
  if policy == "disabled" then return nil end
  if policy == "before_spells" then return 0 end
  return 2                                   -- after_spells（既定）
end

--- 目標まで回復するのに、その手段だと何MP要りそうか（指示書 §8.4・§8.5）。
---
---     推定回数     = ceil(不足HP / 期待回復量)
---     推定総消費MP = 推定回数 × 1回の消費MP
---
--- ⚠ **期待回復量が分からない手段は順位づけできません。** nil を返します。
---   ★推測で埋めません（指示書 §8.2「推測値を無断で追加しないこと」）。
---   分からないものは「比べない」だけで、使わないわけではありません。
function Mantan:_estimate_total_mp(mth, missing)
  local heal = tonumber(mth.expected_heal)
  local cost = tonumber(mth.mp_cost)
  if heal == nil or heal <= 0 or cost == nil then return nil end
  if missing == nil or missing <= 0 then return nil end
  local uses = math.ceil(missing / heal)
  return uses * cost, uses, uses * heal - missing   -- 総MP, 回数, 過剰回復
end

--- 使えるHP回復手段を全部集める（指示書 §8.8 の除外を通したもの）。
function Mantan:_usable_healing()
  local found = {}
  local item_weight = self:_item_priority(self.herb_policy)
  for order, mth in ipairs(self.methods) do
    if mth.kind == "spell" then
      -- ★GUI で「回復呪文を使わない」なら混ぜない（指示書 §8.8）
      -- ⚠ ここも `== false` で見る（nil は既定の ON）。上と同じ理由。
      if self.healing_spells_enabled ~= false then
        -- ★★ 唱えられる人ごとに**別の候補**にする（2026-08-03）。
        --   ⚠ 1人で確定させると、MP配分の点数が効きません
        --     （依頼者「残りMPの率を揃えるが効いていない」）。
        for _, u in ipairs(self:_spell_usable_all(mth)) do
          found[#found + 1] = { method = mth, detail = u.detail,
                                pick = u.pick, order = order, weight = 1 }
        end
      end
    elseif mth.kind == "item" and item_weight ~= nil then
      local row, _who, name = self:_pick_owner(mth.id)
      if row ~= nil then
        found[#found + 1] = {
          method = mth, order = order, weight = item_weight,
          detail = string.format("%s（%s の持ち物）",
            mth.name or self.game:item_name(mth.id), name) }
      end
    end
  end
  return found
end

--- HP回復の手段を選ぶ（指示書 §8）。
---
--- ★★ **順番でも現在MPでもなく、「目標まで何MP要るか」で選ぶ。** ★★
---
---   同点のときは指示書 §8.6 の順で決める:
---     1. 過剰回復が少ない
---     2. MP配分の方針に合う術者
---     3. 1回の消費MPが少ない
---     4. 設定ファイル上の順番
---
--- ⚠ 期待回復量が分からない手段は**比べられない**ので、
---   比べられるものの後ろへ回します（使わないわけではありません）。
--- ★★ 偏りをふまえた「実効MP」（2026-08-03 / 依頼者の実機指摘）。
---
---   実効MP = 総消費MP × (1 + (みんなの平均率 - 唱える人の率) × 重み)
---
--- ★率が低い人が唱える候補は**高くついたこと**にして、後ろへ回します。
--- ⚠ 率が読めない人が居るときは補正しません（★推測で重みを付けない）。
function Mantan:_effective_mp(entry)
  local total = entry.total_mp
  if total == nil then return nil end
  local weight = self.mp_balance_weight or 0
  if weight <= 0 then return total end
  if self.mp_policy ~= "remaining_ratio_balance" then return total end
  local caster = entry.pick and entry.pick.caster
  if caster == nil then return total end

  -- ★みんなの残存MP率の平均。⚠ 1 人でも読めなければ補正しない
  local sum, count, mine = 0, 0, nil
  for _, m in ipairs(self:_casters()) do
    if m.alive then
      local max_mp = self:_max_mp(m)
      if max_mp == nil or max_mp <= 0 then return total end
      local ratio = self:_current_mp(m) / max_mp
      sum = sum + ratio
      count = count + 1
      if m.index == caster.index then mine = ratio end
    end
  end
  -- ⚠ 唱える人が居ない／1 人しか居ないなら、比べる相手が無い
  if count < 2 or mine == nil then return total end
  local average = sum / count
  local adjusted = total * (1 + (average - mine) * weight)
  -- ⚠ 0 以下にしない（★「ただ」になると必ず選ばれてしまう）
  if adjusted < 0.01 then adjusted = 0.01 end
  return adjusted
end

function Mantan:_rank_healing_methods(missing)
  local found = self:_usable_healing()
  for _, e in ipairs(found) do
    if e.method.kind == "spell" then
      e.total_mp, e.uses, e.overheal = self:_estimate_total_mp(e.method, missing)
      e.balance = self:_mp_balance_score(e)
      -- ★偏りをふまえた実効MP（★これで並べる）
      e.effective_mp = self:_effective_mp(e)
    end
  end
  table.sort(found, function(a, b)
    -- ★やくそうを先に使う設定なら、道具が呪文より前に出る
    if a.weight ~= b.weight then return a.weight < b.weight end
    -- ⚠ 比べられるものが先。分からないものを上に置かない
    local a_known = (a.total_mp ~= nil)
    local b_known = (b.total_mp ~= nil)
    if a_known ~= b_known then return a_known end
    if a_known then
      -- ★★ 偏りをふまえた実効MPで比べる（2026-08-03）
      --   ⚠ 素の総消費MPで比べると、安い呪文が必ず勝って
      --     MP配分の出番が来ませんでした（依頼者の実機指摘）。
      local ae = a.effective_mp or a.total_mp
      local be = b.effective_mp or b.total_mp
      if ae ~= be then return ae < be end
      if a.total_mp ~= b.total_mp then return a.total_mp < b.total_mp end
      if a.overheal ~= b.overheal then return a.overheal < b.overheal end
      local ab, bb = a.balance, b.balance
      if ab ~= nil and bb ~= nil and ab ~= bb then return ab < bb end
      local ac = tonumber(a.method.mp_cost) or 0
      local bc = tonumber(b.method.mp_cost) or 0
      if ac ~= bc then return ac < bc end
    end
    return a.order < b.order
  end)
  return found
end

--- 回復の手段を1つ決める。戻り値は従来と同じ（手段, 説明, 選んだ内訳）。
---
--- ⚠ 呼ぶ側は**毎回**呼びます（指示書 §8.7「まとめて予約・実行しない」）。
---   1回回復するたびに現在HP・MPを読み直して選び直します。
function Mantan:_pick_method(missing)
  local ranked = self:_rank_healing_methods(missing)
  local best = ranked[1]
  if best == nil then return nil, nil end
  self.last_reason = self:_healing_reason(best, missing)
  return best.method, best.detail, best.pick
end

--- 実行開始時に出す方針の概要（指示書 §11.1）。
---
--- ★何が効いているかを、実機ログを見るだけで分かるようにする。
--- ⚠ 設定を読んだときの不備も**ここで一緒に出す**。黙って捨てない。
function Mantan:_settings_summary()
  -- ⚠ **画面の選択肢の文言をそのまま文に埋めない**（2026-08-02 / ご指摘）。
  --   「やくそうは呪文を優先する」は日本語として崩れる。
  --   ★選択肢は「やくそうの使用は？」への答え、ログは文の一部。用途が違う。
  local ITEM = { before_spells = "呪文より先に使う",
                 after_spells = "呪文の次に使う",
                 disabled = "使わない" }
  local MP = { remaining_ratio_balance = "残存MP率を揃える",
               spent_mp_balance = "消費MP量を揃える",
               most_mp = "現在MPが多い側を優先",
               list_order = "設定順" }
  local lines = {
    string.format("まんたん開始: 目標%d%%", self.target_percent or 90),
    string.format("回復手段: %s／やくそうは%s",
      self.healing_spells_enabled and "呪文を使う" or "呪文は使わない",
      ITEM[self.herb_policy] or tostring(self.herb_policy)),
    string.format("解毒手段: %s／どくけしそうは%s",
      self.poison_cure_enabled and "キアリーを使う" or "解毒しない",
      ITEM[self.antidote_policy] or tostring(self.antidote_policy)),
    string.format("MP配分: %s", MP[self.mp_policy] or tostring(self.mp_policy)),
    string.format("最低残存MP: %s",
      self.use_tactics_reserve and "戦術プロフィールを使用" or "使用しない"),
  }
  for _, p in ipairs(self.settings_problems or {}) do
    lines[#lines + 1] = "⚠ 設定: " .. tostring(p)
  end
  return lines
end

--- なぜそれを選んだかの一言（指示書 §11.2）。
function Mantan:_healing_reason(entry, missing)
  local name = self:_method_name(entry.method)
  if entry.total_mp == nil then
    return string.format("%s を選択: 不足HP %s（期待回復量が未確認のため"
      .. "コスパ比較の対象外）", name, tostring(missing))
  end
  local text = string.format(
    "%s を選択: 不足HP %d / 期待回復%s / 消費MP%s / 推定%d回 / 推定総消費MP%d",
    name, missing, tostring(entry.method.expected_heal),
    tostring(entry.method.mp_cost), entry.uses, entry.total_mp)
  -- ★偏りの補正が効いたときだけ、そのことを書く（2026-08-03）
  --   ⚠ 毎回出すと雑音になるので、素の値と変わったときだけ。
  local eff = entry.effective_mp
  if eff ~= nil and entry.total_mp ~= nil
    and math.abs(eff - entry.total_mp) >= 0.05 then
    local caster = entry.pick and entry.pick.caster
    text = text .. string.format(" / ★MP配分の補正後 %.1f（%s が唱える）",
      eff, caster and tostring(caster.name) or "?")
  end
  return text
end

-- 回復対象の行番号（0始まり / active_party 内の位置）
function Mantan:_target_row(target)
  for pos, m in ipairs(self:_members()) do
    if m.index == target.index then return pos - 1 end
  end
  return nil
end

-- そのメンバーの回復目標HP（このHP以上なら回復しない）。
-- ★「文字通り満タン」にすると最後の数ポイントのために1回余分に使うことになり、
--   やくそうもMPも無駄になる。既定は9割（config の mode）。
function Mantan:_target_hp(member)
  if self.target_ratio >= 1.0 then return member.max_hp end
  local t = math.floor(member.max_hp * self.target_ratio)
  if t < 1 then t = 1 end
  if t > member.max_hp then t = member.max_hp end
  return t
end

-- 回復が必要な人が居るか。居れば最も足りていない人を返す。
-- 「足りていない量」は目標HPまでの差で測る（満タンまでの差ではない）。
function Mantan:_most_hurt()
  local worst, worst_missing = nil, 0
  for _, m in ipairs(self:_members()) do
    if m.alive then
      local missing = self:_target_hp(m) - m.hp
      if missing > worst_missing then worst, worst_missing = m, missing end
    end
  end
  return worst, worst_missing
end

-- 毒になっている生存者のうち、最初の1人を返す（居なければ nil）。
-- ★死者は対象にしない（治しても起きない）。
-- ★毒の判定はビットマスク。等値比較してはいけない（playbook #15）:
--   通常時 $84 / 毒中 $A4 のどちらにも一致せず、一度も発火しなかった前例がある。
--   party() の m.poisoned が既にマスク判定してある。
function Mantan:_first_poisoned()
  for _, m in ipairs(self:_members()) do
    if m.alive and m.poisoned then return m end
  end
  return nil
end

-- 毒を治す手段を優先順に探す。戻り値: 手段, 説明, 選んだ内訳（呪文のときだけ）
-- ★HP回復の _pick_method と同じ作りにする（呪文なら唱えられる人、道具なら持ち主）。
--- その人の「最低残存MP」（戦術プロフィール）。無ければ nil。
---
--- ⚠ ボス戦の解除（`ignore_reserve_on_boss`）は**見ない**。
---   まんたんは戦闘外でしか動かないので、ボス戦という状態が無い。
function Mantan:_reserve_floor(member)
  local br = self.bridge
  if br == nil or br._tactic_num == nil then return nil end
  local ok, value = pcall(function()
    return br:_tactic_num(member.name, "resources", "reserve_mp", nil)
  end)
  if not ok then return nil end
  return value
end

--- 使える手段を全部集める。`{ method, detail, pick }` の並び。
function Mantan:_usable_cures()
  local found = {}
  for order, mth in ipairs(self.cure_methods) do
    if mth.enabled ~= false then
      if mth.kind == "spell" then
        local detail, pick = self:_spell_usable(mth)
        if detail ~= nil then
          found[#found + 1] = { method = mth, detail = detail, pick = pick,
                                order = order }
        end
      elseif mth.kind == "item" then
        local row, _, name = self:_pick_owner(mth.id)
        if row ~= nil then
          found[#found + 1] = {
            method = mth, order = order,
            detail = string.format("%s（%s の持ち物）",
              mth.name or self.game:item_name(mth.id), name) }
        end
      end
    end
  end
  return found
end

--- MP配分の点数（指示書 §9）。★小さいほど良い候補。
---
--- ⚠ **分からなければ nil**。0 と混ぜない（0 は「ぴったり揃う」の意味）。
---
--- ## remaining_ratio_balance（既定 / 指示書 §9.2）
---   その呪文を使ったあとの「最大MPに対する残り割合」が、
---   サマルトリアとムーンブルクで**近くなる**候補を選ぶ。
---   ⚠ 現在MPの**絶対値**では比べない。最大MPが違うと不公平になる。
---
--- ## spent_mp_balance（指示書 §9.3）
---   このまんたん処理の中で使ったMPの累計が、二人でそろう候補を選ぶ。
---   ⚠ 累計は1回のまんたんの中だけ。ファイルにも DB にも残さない。
---
--- ## most_mp / list_order（現行互換 / 指示書 §9.4・§9.5）
---   ここでは点数を付けない（並べ替えは呼ぶ側の規則に任せる）。
function Mantan:_mp_balance_score(entry)
  local how = self.mp_policy
  if how ~= "remaining_ratio_balance" and how ~= "spent_mp_balance" then
    return nil
  end
  local caster = entry.pick and entry.pick.caster
  if caster == nil then return nil end
  local cost = tonumber(entry.method.mp_cost) or 0

  -- ★比べる相手は「MPを持つ生存者」。⚠ 相手が居なければ点数を付けない
  --   （指示書 §9.2「利用可能な術者をそのまま選択する」）。
  local others = {}
  for _, m in ipairs(self:_casters()) do
    if m.alive and m.index ~= caster.index then others[#others + 1] = m end
  end
  if #others == 0 then return nil end

  if how == "spent_mp_balance" then
    local mine = (self.spent_mp[caster.index] or 0) + cost
    local worst = nil
    for _, m in ipairs(others) do
      local d = math.abs(mine - (self.spent_mp[m.index] or 0))
      if worst == nil or d > worst then worst = d end
    end
    return worst
  end

  -- remaining_ratio_balance
  local function ratio(mp, max_mp)
    if max_mp == nil or max_mp <= 0 then return nil end
    return mp / max_mp
  end
  -- ⚠ `caster.max_mp` は存在しない。★必ず `_max_mp()` から取る
  local mine = ratio(self:_current_mp(caster) - cost, self:_max_mp(caster))
  if mine == nil then return nil end
  local worst = nil
  for _, m in ipairs(others) do
    local theirs = ratio(self:_current_mp(m), self:_max_mp(m))
    if theirs ~= nil then
      local d = math.abs(mine - theirs)
      if worst == nil or d > worst then worst = d end
    end
  end
  return worst
end

--- 使ったMPを数える（指示書 §9.3）。⚠ 1回のまんたんの中だけ。
function Mantan:_note_spent_mp(pick, mth)
  local caster = pick and pick.caster
  if caster == nil then return end
  local cost = tonumber(mth and mth.mp_cost) or 0
  self.spent_mp[caster.index] = (self.spent_mp[caster.index] or 0) + cost
end

--- 唱える人の残りMP。
--- ⚠ **分からなければ -1**（後ろへ回す）。0 と混ぜない。
function Mantan:_caster_mp(entry)
  local caster = entry.pick and entry.pick.caster
  if caster == nil then return -1 end
  return caster.mp or -1
end

--- どの手段で治すかを決める。
---
--- ★★ 方針は設定で選べる（2026-08-01 / 課題 #57）★★
---
---   list_order … 書いてある順（従来）
---   most_mp    … **MPの残りが多い人の呪文から**使う（既定）
---
--- ⚠⚠ なぜ既定を変えたか（実機ログ 2026-08-01 13:33）:
---
---   | 時刻 | 使ったもの | サマルトリアMP | ムーンブルクMP |
---   | --- | --- | ---: | ---: |
---   | 13:33:57〜58 | ホイミ×4（samaltria） | 35 -> 23 | **83（手つかず）** |
---
---   書いてある順だと、先頭のホイミ（サマルトリア）が使える限り
---   Healmore（ムーンブルク）まで届かない。依頼者の指摘:
---   「まんたんでムーンブルグを使わなさ過ぎる」。
---
--- ★MPの多い人から使うと、**戦闘中に要るサマルトリアのMPが残る**
---   （戦闘の回復呪文はホイミだけなので、彼女しか唱えられない）。
--- ⚠ 道具（やくそう）は最後のまま。★買い足しにゴールドが要るので、
---   MPで済むならそちらを先に使う。
function Mantan:_pick_cure_method()
  -- ★GUI で「解毒しない」なら何も返さない（指示書 §5.2）
  --
  -- ⚠⚠ **`not self.x` と書いてはいけない**（2026-08-02 に実際にやらかした）。
  --   `Mantan.new` を通さずに作られた入れ物（検証ハーネスなど）では
  --   この項目が nil になり、**黙って解毒しなくなる**。
  --   既存の `cure_order_test.lua` が 9 件赤くなって気づいた。
  -- ★`new()` と同じ規則にそろえる: **nil は「設定が無い」＝既定の ON**。
  if self.poison_cure_enabled == false then return nil, nil end

  local found = self:_usable_cures()
  -- ★★ どくけしそうを先に使うか、後に回すか、使わないか（指示書 §7.2）★★
  --   ⚠ 呪文どうし・道具どうしの順は変えない。**道具の位置だけ**動かす。
  local item_weight = self:_item_priority(self.antidote_policy)
  local kept = {}
  for _, e in ipairs(found) do
    if e.method.kind == "item" then
      if item_weight ~= nil then
        e.weight = item_weight
        kept[#kept + 1] = e
      end
    else
      e.weight = 1
      kept[#kept + 1] = e
    end
  end
  found = kept
  if #found == 0 then return nil, nil end

  local how = self.cure_order or "most_mp"
  if item_weight == 0 then
    -- ★どくけしそうを先に。⚠ それ以外の並びは触らない
    table.sort(found, function(a, b)
      if a.weight ~= b.weight then return a.weight < b.weight end
      return a.order < b.order
    end)
  elseif how == "most_mp" then
    -- ★呪文どうしだけ並べ替える。道具は書いてある順のまま後ろ。
    table.sort(found, function(a, b)
      local a_spell = (a.method.kind == "spell")
      local b_spell = (b.method.kind == "spell")
      if a_spell ~= b_spell then return a_spell end       -- 呪文が先
      if a_spell then
        local am, bm = self:_caster_mp(a), self:_caster_mp(b)
        if am ~= bm then return am > bm end               -- MPが多い人が先
      end
      return a.order < b.order                            -- 同じなら書いた順
    end)
  end

  local best = found[1]
  return best.method, best.detail, best.pick
end

-- 全員が目標に達しているか
function Mantan:_all_reached()
  for _, m in ipairs(self:_members()) do
    if m.alive and m.hp < self:_target_hp(m) then return false end
  end
  return true
end

-- 合計HP。回復したかどうかの判定に使う（誰に使われても検出できる）。
function Mantan:_total_hp()
  local sum = 0
  for _, m in ipairs(self:_members()) do sum = sum + m.hp end
  return sum
end

----------------------------------------------------------------------
-- 事前確認（★入力を1つも送る前に判定する）
----------------------------------------------------------------------

-- ok, reason を返す。ok が false ならボタンを一切押さない。
-- 「開いてみたけど無かったので閉じる」という無駄な操作を避けるため、
-- 判定に必要な情報はすべて RAM から先に読む。
function Mantan:precheck()
  if self.game:in_battle() then
    return false, "戦闘中は実行しない"
  end

  local st = self:_menu()
  if st.menu ~= MENU_FIELD then
    return false, string.format("フィールドで実行すること（現在 menu=%02X）", st.menu)
  end

  local members = self:_members()
  if #members == 0 then
    return false, "パーティ状態を読めない"
  end

  -- ★毒だけが問題の場合も実行する（HPが満タンでも毒は治す）。
  --   これを入れないと「HPは足りているので何もしない」で見送ってしまう。
  local poisoned = self.cure_poison and self:_first_poisoned() or nil
  if poisoned ~= nil then
    local cure, cure_detail = self:_pick_cure_method()
    if cure ~= nil then
      return true, string.format("%s が毒 -> %s で治す", poisoned.name, cure_detail)
    end
    -- 毒は治せないが、HPが足りていなければHP回復のために続行する
  end

  local worst, missing = self:_most_hurt()
  if worst == nil then
    if poisoned ~= nil then
      return false, string.format(
        "%s が毒だが治す手段が無い（どくけしそうを持っていない"
        .. " / キアリーは行番号が未確定のため既定で無効）", poisoned.name)
    end
    -- ★死者が居るときは、それを明記する。
    --   依頼者から「2名死亡で薬草が使われない」という報告を受けたが、
    --   実際は生存者（ローレシア 68/68）が満タンで回復対象が居なかった
    --   （work/mantan/slot6.txt）。それでも
    --   「全員が目標に達している」だけでは**壊れているように見える**。
    --   やくそうは死者には効かない（教会かザオリクが必要）ので、
    --   「なぜ何もしないのか」を利用者が判断できる言葉で返す。
    local dead = {}
    for _, m in ipairs(self:_members()) do
      if not m.alive then dead[#dead + 1] = m.name end
    end
    if #dead > 0 then
      return false, string.format(
        "生存者は全員が目標(%s)に達している。死亡している %s は"
        .. "やくそうやホイミでは回復できない（教会かザオリクが必要）",
        self.mode_label, table.concat(dead, "・"))
    end
    return false, string.format("全員が目標(%s)に達している。回復の必要がない",
      self.mode_label)
  end

  local method, detail = self:_pick_method(missing)
  if method == nil then
    return false, "使える回復手段がない（MPも回復アイテムも足りない）"
  end

  return true, string.format(
    "%s のHPが %d/%d（目標%s=%d まで%d不足）/ 使うのは %s",
    worst.name, worst.hp, worst.max_hp,
    self.mode_label, self:_target_hp(worst), missing, detail)
end

----------------------------------------------------------------------
-- 進行
----------------------------------------------------------------------

local function report(self, msg)
  if self.on_progress then self.on_progress(self.phase, msg) end
end

-- 同じ理由を何度も報告しない（1回の実行につき1回だけ出す）。
-- ★呪文の行番号は毎周（回復のたび）に解決するため、
--   黙って落ちると気づけず、毎回報告すると同じ行が並ぶ。
function Mantan:_note_once(key, text)
  if self.spell_row_notes[key] then return end
  self.spell_row_notes[key] = true
  report(self, text)
end

function Mantan:_abort(reason)
  self.status = "abort"
  self.reason = reason
  self.phase = "closing"       -- ★中止でもメニューは閉じる。開いたままにしない
  self.closes = 0
  report(self, "中止: " .. reason)
end

--- ★★ 終わったときの残りMP率（2026-08-03 / 依頼者の要望）。
---
---     「満タン後に、サマルとムーンの残りMP率をログ表示して」
---
--- ★MP配分が効いているかを、遊びながら確かめられるようにします。
--- ⚠ 最大MPが読めない人は「率」を出せないので、実数だけ出します
---   （★分からないものを 0% と書かない）。
function Mantan:_mp_report()
  local parts = {}
  for _, m in ipairs(self:_casters()) do
    local cur = self:_current_mp(m)
    local max_mp = self:_max_mp(m)
    if max_mp ~= nil and max_mp > 0 then
      parts[#parts + 1] = string.format("%s %d/%d（%d%%）",
        m.name, cur, max_mp, math.floor(cur / max_mp * 100 + 0.5))
    elseif cur ~= nil then
      -- ⚠ 最大MPが読めない。★率は出さない
      parts[#parts + 1] = string.format("%s %d/?（率は不明）", m.name, cur)
    end
  end
  if #parts == 0 then return nil end
  local text = "残りMP: " .. table.concat(parts, " / ")
  -- ★どの方針で配ったかも一緒に出す（★効いているか見比べられるように）
  local MP = { remaining_ratio_balance = "残存MP率を揃える",
               spent_mp_balance = "消費MP量を揃える",
               most_mp = "MPが多い人から", list_order = "設定の順" }
  return text .. string.format("（配分: %s）",
    MP[self.mp_policy] or tostring(self.mp_policy))
end

function Mantan:_finish(reason)
  self.status = "done"
  self.reason = reason
  self.phase = "closing"
  self.closes = 0
  report(self, reason)
  -- ★残りMP率を出す（⚠ 出せなければ黙って飛ばす）
  local mp = self:_mp_report()
  if mp ~= nil then report(self, mp) end
end

function Mantan:done()
  return self.phase == "finished"
end

-- ボタンを press_hold フレーム押し、press_gap フレーム離す。
-- 押下中は毎フレーム要求を出す（1フレームだけでは取りこぼす）。
function Mantan:_do_press(btn, next_phase)
  self.pending_button = btn
  self.pending_next = next_phase
  self.hold = self.press_hold
  self.gap = self.press_gap
  self.phase = "pressing"
end

-- 1列メニューで目標行へ寄せる。端でラップしないので寄せ方は決定的。
-- カーソルを目標行へ寄せる。端でラップしないので寄せ方は決定的。
--
-- ★★ 待ちと寄せでカウンタを共有してはいけない ★★
-- 補充側で実害が出た（work/shoptalk/trace.txt）: メニューが出るのを待つ
-- あいだに tries が上限を超え、実際に出た瞬間に「寄らない」と中止していた。
-- **カーソルは動かせるのに、動かす前に諦めていた。**
-- まんたんでは表面化していなかったが同じ形なので揃えて直す。
function Mantan:_seek_row(target, next_phase)
  local st = self:_menu()

  local key = string.format("%d:%d", st.menu, target)
  if self.seek_key ~= key then
    self.seek_key = key
    self.seek_tries = 0
  end

  if st.cy == target then
    self.seek_tries = 0
    self.phase = next_phase
    return
  end
  self.seek_tries = (self.seek_tries or 0) + 1
  if self.seek_tries > self.max_seek then
    self:_abort(string.format("カーソルが行%d に寄らない（現在 行%d）", target, st.cy))
    return
  end
  self:_do_press(st.cy < target and "down" or "up", self.seek_return)
end

-- 毎フレーム呼ぶ。true を返したら終了。
function Mantan:tick()
  if self.phase == "finished" then return true end

  self.frames = self.frames + 1
  if self.frames > self.frame_budget and self.status == "running" then
    self:_abort(string.format("時間切れ（%dフレーム）", self.frame_budget))
  end

  local st = self:_menu()

  ------------------------------------------------------------------
  -- 共通: ボタンを押して離す
  ------------------------------------------------------------------
  if self.phase == "pressing" then
    if self.hold > 0 then
      self.bridge:request_input({ [self.pending_button] = true })
      self.hold = self.hold - 1
      return false
    end
    self.gap = self.gap - 1
    if self.gap <= 0 then self.phase = self.pending_next end
    return false
  end

  ------------------------------------------------------------------
  -- 1周の開始判定
  ------------------------------------------------------------------
  if self.phase == "check" then
    if self.hp_start == nil then
      self.hp_start = self:_total_hp()
      self.herbs_start = self:_herb_count()
      -- ★実行開始時に方針の概要を出す（指示書 §11.1）。
      --   ⚠ 1回のまんたんにつき1度だけ。毎フレーム出さない。
      for _, line in ipairs(self:_settings_summary()) do
        if self.on_progress then self.on_progress(self.phase, line) end
      end
    end

    -- ★毒を先に治す（依頼者の要望）。
    --   毒は歩くたびにHPを削るので、HPを戻す前に止めたほうが無駄が少ない。
    --   毒が無ければ従来どおりHP回復に進む。
    local poisoned = self.cure_poison and self:_first_poisoned() or nil
    -- ⚠⚠ **不足HPも受け取る**（2026-08-02）。
    --   受け取らないと `_pick_method(missing)` に nil が渡り、Lua は
    --   エラーにせず**静かにコスパ比較が効かなくなる**。
    local worst, missing = self:_most_hurt()

    if poisoned == nil and worst == nil then
      self:_finish(string.format("完了: 全員が目標(%s)に達した", self.mode_label))
      return false
    end
    if st.menu ~= MENU_FIELD then
      self:_abort(string.format("フィールドに戻っていない（menu=%02X）", st.menu))
      return false
    end

    if poisoned ~= nil then
      if self.cures >= self.max_cures then
        self:_abort(string.format("毒を治す回数の上限（%d回）に達した", self.max_cures))
        return false
      end
      local cure, cure_detail, cure_pick = self:_pick_cure_method()
      if cure == nil then
        -- ★毒を治せないだけで全体を止めない。HP回復は続ける価値がある。
        --   ただし黙って無視せず必ず報告する。
        --   （キアリーが落ちた理由は _spell_usable が別に1回だけ報告している）
        report(self, string.format(
          "%s の毒を治す手段が無い（どくけしそうが無い / 呪文も使えない）"
          .. " -> HP回復だけ続ける", poisoned.name))
        self.cure_poison = false          -- この実行中はもう探さない
        return false
      end
      self.round_kind = "cure"
      self.method = cure
      self.spell_pick = cure_pick
      self.spell_row = cure_pick and cure_pick.spell_row or nil
      self.cure_target = poisoned
      self.target_row = self:_target_row(poisoned)
      if self.target_row == nil then
        self:_abort("毒を治す対象の行を決められない")
        return false
      end
      -- 効果の判定に使う基準（毒が消えたか＋代価を払ったか）
      -- ⚠ 在庫の基準はここで取らない。_herb_count() は self.item_id を数えるので、
      --   item_id を どくけしそう に変える**前**に取ると
      --   「やくそうの個数」と「どくけしそうの個数」を比べてしまい、
      --   代価を払っていないのに払ったと誤判定する。道具の分岐で取り直す。
      self.status_before_use = poisoned.status
      self.hp_before_use = self:_total_hp()

      if cure.kind == "spell" then
        -- ★唱える人は _pick_cure_method が既に決めてある。
        --   ここで選び直すと**別の人**になりうる（MPが多いだけの人が選ばれ、
        --   その人はその呪文を覚えていないことがある / 実機ログ 12:47）。
        local pick = self.spell_pick
        if pick == nil then
          self:_abort("唱えられる人が居ない")
          return false
        end
        self.caster_row = pick.caster_row
        self.caster = pick.caster
        self.mp_before_use = self:_total_mp()
        -- 呪文の行は self.spell_row（_pick_cure_method が解決済み / seek_spell 参照）。
        report(self, string.format("毒を治す: %s に %s", poisoned.name, cure_detail))
        self:_do_press("A", "wait_command_spell")
        self.tries = 0
        return false
      end

      local owner_row, owner_who = self:_pick_owner(cure.id)
      if owner_row == nil then
        self:_abort(string.format("%s を持っている人が居ない",
          self.game:item_name(cure.id)))
        return false
      end
      self.owner_row = owner_row
      self.who = owner_who
      self.item_id = cure.id
      -- ★在庫の基準は item_id を決めた**後**に取る（上の警告のとおり）
      self.herbs_before_use = self:_herb_count()
      report(self, string.format("毒を治す: %s に %s", poisoned.name, cure_detail))
      self:_do_press("A", "wait_command")
      self.tries = 0
      return false
    end

    self.round_kind = "hp"
    if self.uses >= self.max_uses then
      self:_finish(string.format("終了: 使用回数の上限（%d個）に達した", self.max_uses))
      return false
    end

    -- この周で回復したかを判定するための基準を取る
    self.hp_before_use = self:_total_hp()
    self.herbs_before_use = self:_herb_count()

    -- ★この周で使う手段を選ぶ。優先順（既定は ホイミ -> やくそう）。
    -- MPが尽きたら自動でアイテムへ落ちる。
    -- ★不足HPを渡す（指示書 §8.3）。**毎回**選び直す（§8.7）
    local method, detail, method_pick = self:_pick_method(missing)
    if method == nil then
      self:_finish("終了: 使える回復手段がなくなった（MPも回復アイテムも不足）")
      return false
    end
    self.method = method
    self.spell_pick = method_pick
    self.spell_row = method_pick and method_pick.spell_row or nil
    -- ★消費MPを数える（指示書 §9.3）。⚠ 1回のまんたんの中だけ。
    --   `spent_mp_balance` はこの累計で「二人がそろう側」を選ぶ。
    self:_note_spent_mp(method_pick, method)
    -- ★なぜそれを選んだかを残す（指示書 §11.2）
    -- ⚠ 引数は (phase, msg)。1つで呼ぶと受け側が phase を msg と取り違える
    if self.last_reason ~= nil and self.on_progress ~= nil then
      self.on_progress(self.phase, self.last_reason)
    end

    -- 回復対象の行（0x11 / 0x10 で共通。パーティの並び順）
    self.target_row = self:_target_row(worst)
    if self.target_row == nil then
      self:_abort("回復対象の行を決められない")
      return false
    end

    if method.kind == "spell" then
      -- ★唱える人の行は「呪文を使える人の中での位置」。
      --   パーティの並びとは別（ローレシアは MP 0 で並ばない）。
      -- ★唱える人は _pick_method が既に決めてある（上と同じ理由で選び直さない）
      local pick = self.spell_pick
      if pick == nil then
        self:_abort("唱えられる人が居ない")
        return false
      end
      self.caster_row = pick.caster_row
      self.caster = pick.caster
      self.mp_before_use = self:_total_mp()
      report(self, string.format("%d回目: %s のHP %d/%d（目標%d）に %s（%s / MP %d）",
        self.uses + 1, worst.name, worst.hp, worst.max_hp, self:_target_hp(worst),
        self:_method_name(method), pick.caster.name, self:_current_mp(pick.caster)))
      self:_do_press("A", "wait_command_spell")
      self.tries = 0
      return false
    end

    -- 道具経路（従来どおり）
    local owner_row, owner_who, owner_name = self:_pick_owner(method.id)
    if owner_row == nil then
      self:_finish(string.format("終了: %s を持っている人が居ない",
        self.game:item_name(method.id)))
      return false
    end
    self.owner_row = owner_row
    self.who = owner_who
    self.item_id = method.id
    self.herbs_before_use = self:_herb_count()
    report(self, string.format("%d個目: %s のHP %d/%d（目標%d / %s の %s を使う）",
      self.uses + 1, worst.name, worst.hp, worst.max_hp, self:_target_hp(worst),
      owner_name, self.game:item_name(method.id)))
    self:_do_press("A", "wait_command")
    self.tries = 0
    return false
  end

  ------------------------------------------------------------------
  -- じゅもん経路: 06 -> 0D 唱える人 -> 14 呪文 -> 10 対象
  ------------------------------------------------------------------
  if self.phase == "wait_command_spell" then
    if st.menu == MENU_COMMAND then
      self.tries = 0
      self.phase = "seek_jumon"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format("コマンドメニューが開かない（menu=%02X）", st.menu))
    end
    return false
  end

  if self.phase == "seek_jumon" then
    if st.menu ~= MENU_COMMAND then
      self:_abort(string.format("コマンドメニューから外れた（menu=%02X）", st.menu))
      return false
    end
    if st.cx == COL_JUMON_X and st.cy == COL_JUMON_Y then
      self.tries = 0
      self:_do_press("A", "wait_caster")
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.max_seek then
      self:_abort(string.format("じゅもん(1,0)に寄らない（現在 (%d,%d)）", st.cx, st.cy))
      return false
    end
    local dir
    if st.cy > COL_JUMON_Y then dir = "up"
    elseif st.cy < COL_JUMON_Y then dir = "down"
    elseif st.cx < COL_JUMON_X then dir = "right"
    else dir = "left" end
    self:_do_press(dir, "seek_jumon")
    return false
  end

  if self.phase == "wait_caster" then
    -- 唱える人が1人だけでも 0x0D は出る（実測: 行数1）
    if st.menu == MENU_CASTER then
      self.tries = 0
      self.phase = "seek_caster"
      return false
    end
    if st.menu == MENU_SPELLS then     -- 省略された場合に備える
      self.tries = 0
      self.phase = "seek_spell"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format("唱える人の選択が出ない（menu=%02X）", st.menu))
    end
    return false
  end

  if self.phase == "seek_caster" then
    if st.menu ~= MENU_CASTER then
      if st.menu == MENU_SPELLS then self.phase = "seek_spell"; return false end
      self:_abort(string.format("唱える人の選択から外れた（menu=%02X）", st.menu))
      return false
    end
    self.seek_return = "seek_caster"
    self:_seek_row(self.caster_row, "press_caster")
    return false
  end

  if self.phase == "press_caster" then
    if st.menu ~= MENU_CASTER or st.cy ~= self.caster_row then
      self:_abort(string.format("唱える人の行に居ないため決定しない（menu=%02X 行%d）",
        st.menu, st.cy))
      return false
    end
    self.tries = 0
    self:_do_press("A", "wait_spell")
    return false
  end

  if self.phase == "wait_spell" then
    if st.menu == MENU_SPELLS then
      self.tries = 0
      self.phase = "seek_spell"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format("呪文リストが出ない（menu=%02X）", st.menu))
    end
    return false
  end

  if self.phase == "seek_spell" then
    if st.menu ~= MENU_SPELLS then
      self:_abort(string.format("呪文リストから外れた（menu=%02X）", st.menu))
      return false
    end
    -- ★行番号は _resolve_spell_row が決めた値（既定は習得済みビットからの計算）。
    --   決められなければここまで来ない（呪文の手段ごと落としてある）。
    self.seek_return = "seek_spell"
    self:_seek_row(self:_want_spell_row(), "press_spell")
    return false
  end

  if self.phase == "press_spell" then
    local want = self:_want_spell_row()
    if st.menu ~= MENU_SPELLS or st.cy ~= want then
      self:_abort(string.format("呪文の行に居ないため決定しない（menu=%02X 行%d）",
        st.menu, st.cy))
      return false
    end
    -- ★決定の直前にもう一度、その行に何があるかを読む（仕様7章の約束）。
    --   ここで見ているのは RAM の習得ビットであって画面ではないが、
    --   「唱えるつもりの呪文がその行に居るか」は確かめられる。
    --   ⚠ ルーラ（戻せない）を押す事故を最後に止める網。
    local ok, why = self:_row_still_matches(want)
    if not ok then
      self:_abort(why)
      return false
    end
    self.tries = 0
    self:_do_press("A", "wait_spell_target")
    return false
  end

  if self.phase == "wait_spell_target" then
    if st.menu == MENU_SPELL_TARGET then
      self.tries = 0
      self.phase = "seek_spell_target"
      return false
    end
    -- 対象を聞かれずに効く場合（1人パーティなど）
    if self:_total_hp() > self.hp_before_use then
      self.tries = 0
      self.phase = "verify"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_heal then
      self:_abort(string.format("呪文の対象選択が出ない（menu=%02X）", st.menu))
    end
    return false
  end

  if self.phase == "seek_spell_target" then
    if st.menu ~= MENU_SPELL_TARGET then
      self.phase = "verify"
      self.tries = 0
      return false
    end
    self.seek_return = "seek_spell_target"
    self:_seek_row(self.target_row, "press_spell_target")
    return false
  end

  if self.phase == "press_spell_target" then
    if st.menu ~= MENU_SPELL_TARGET or st.cy ~= self.target_row then
      self:_abort(string.format("対象の行に居ないため決定しない（menu=%02X 行%d）",
        st.menu, st.cy))
      return false
    end
    self.tries = 0
    self:_do_press("A", "verify")
    return false
  end

  ------------------------------------------------------------------
  -- コマンドメニュー(06) -> どうぐ
  ------------------------------------------------------------------
  if self.phase == "wait_command" then
    if st.menu == MENU_COMMAND then
      self.tries = 0
      self.phase = "seek_douguo"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format("コマンドメニューが開かない（menu=%02X）", st.menu))
    end
    return false
  end

  if self.phase == "seek_douguo" then
    -- どうぐ は (1,1)。グリッドなので縦横どちらも寄せる。
    if st.menu ~= MENU_COMMAND then
      self:_abort(string.format("コマンドメニューから外れた（menu=%02X）", st.menu))
      return false
    end
    if st.cx == 1 and st.cy == 1 then
      self.tries = 0
      self:_do_press("A", "wait_items")
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.max_seek then
      self:_abort(string.format("どうぐ(1,1)に寄らない（現在 (%d,%d)）", st.cx, st.cy))
      return false
    end
    local dir
    if st.cy < 1 then dir = "down"
    elseif st.cy > 1 then dir = "up"
    elseif st.cx < 1 then dir = "right"
    else dir = "left" end
    self:_do_press(dir, "seek_douguo")
    return false
  end

  ------------------------------------------------------------------
  -- 持ち物一覧(15) -> やくそうの行
  ------------------------------------------------------------------
  if self.phase == "wait_items" then
    -- ★2人以上では持ち物一覧の前に「持ち主選択」(0x0E)が入る（B-11）。
    -- 1人のときは出ないので、どちらでも受け付ける。
    if st.menu == MENU_OWNER then
      self.tries = 0
      self.phase = "seek_owner"
      return false
    end
    if st.menu == MENU_ITEMS then
      self.tries = 0
      self.phase = "seek_item"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format("持ち物一覧が開かない（menu=%02X）", st.menu))
    end
    return false
  end

  -- 持ち主選択(0x0E): 在庫を持っている人の行へ寄せて決定する
  if self.phase == "seek_owner" then
    if st.menu ~= MENU_OWNER then
      -- 既に一覧へ進んでいたなら続行する
      if st.menu == MENU_ITEMS then self.phase = "seek_item"; return false end
      self:_abort(string.format("持ち主選択から外れた（menu=%02X）", st.menu))
      return false
    end
    self.seek_return = "seek_owner"
    self:_seek_row(self.owner_row, "press_owner")
    return false
  end

  if self.phase == "press_owner" then
    if st.menu ~= MENU_OWNER or st.cy ~= self.owner_row then
      self:_abort(string.format("持ち主の行に居ないため決定しない（menu=%02X 行%d）",
        st.menu, st.cy))
      return false
    end
    self.tries = 0
    self:_do_press("A", "wait_items_only")
    return false
  end

  -- 持ち主を決めた後は必ず持ち物一覧が出るはず
  if self.phase == "wait_items_only" then
    if st.menu == MENU_ITEMS then
      self.tries = 0
      self.phase = "seek_item"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format("持ち主を決めたのに持ち物一覧が出ない（menu=%02X）",
        st.menu))
    end
    return false
  end

  if self.phase == "seek_item" then
    if st.menu ~= MENU_ITEMS then
      self:_abort(string.format("持ち物一覧から外れた（menu=%02X）", st.menu))
      return false
    end
    -- ★毎回IDから行を引き直す。使うたびに行が詰まるため行番号は固定できない。
    local row = self.game:find_item_row(self.item_id, self.who)
    if row == nil then
      self:_abort(string.format("%s が持ち物に無い", self.game:item_name(self.item_id)))
      return false
    end
    self.seek_return = "seek_item"
    self:_seek_row(row, "press_item")
    return false
  end

  if self.phase == "press_item" then
    self:_do_press("A", "wait_action")
    return false
  end

  ------------------------------------------------------------------
  -- 行動選択(17) -> つかう(行0)
  ------------------------------------------------------------------
  if self.phase == "wait_action" then
    if st.menu == MENU_ACTION then
      self.tries = 0
      self.phase = "seek_use"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format("行動選択(つかう/わたす/すてる)が出ない（menu=%02X）",
        st.menu))
    end
    return false
  end

  if self.phase == "seek_use" then
    -- ⚠ ここが最も危険。行1=わたす / 行2=すてる を決定するとアイテムを失う。
    if st.menu ~= MENU_ACTION then
      self:_abort(string.format("行動選択から外れた（menu=%02X）", st.menu))
      return false
    end
    self.seek_return = "seek_use"
    self:_seek_row(ROW_USE, "press_use")
    return false
  end

  if self.phase == "press_use" then
    -- 決定の直前にもう一度確認する。寄せた後にズレていたら押さない。
    if st.menu ~= MENU_ACTION or st.cy ~= ROW_USE then
      self:_abort(string.format(
        "「つかう」に居ないため決定しない（menu=%02X 行%d）", st.menu, st.cy))
      return false
    end
    self.tries = 0
    self:_do_press("A", "after_use")
    return false
  end

  ------------------------------------------------------------------
  -- ★2人以上では「つかう」の後に対象選択(0x11)が入る（B-11）
  ------------------------------------------------------------------
  if self.phase == "after_use" then
    if st.menu == MENU_TARGET then
      self.tries = 0
      self.phase = "seek_target"
      return false
    end
    -- 1人のときは対象選択が出ず、そのまま回復する
    if self:_total_hp() > self.hp_before_use then
      self.tries = 0
      self.phase = "verify"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_heal then
      self:_abort(string.format(
        "「つかう」の後に何も起きない（menu=%02X）", st.menu))
    end
    return false
  end

  if self.phase == "seek_target" then
    if st.menu ~= MENU_TARGET then
      -- 既に使用が始まっていれば検証へ進む
      self.phase = "verify"
      self.tries = 0
      return false
    end
    self.seek_return = "seek_target"
    self:_seek_row(self.target_row, "press_target")
    return false
  end

  if self.phase == "press_target" then
    if st.menu ~= MENU_TARGET or st.cy ~= self.target_row then
      self:_abort(string.format("対象の行に居ないため決定しない（menu=%02X 行%d）",
        st.menu, st.cy))
      return false
    end
    self.tries = 0
    self:_do_press("A", "verify")
    return false
  end

  ------------------------------------------------------------------
  -- ★検証: HPが増えたか。増えていなければ中止する
  ------------------------------------------------------------------
  if self.phase == "verify" then
    local hp_now = self:_total_hp()
    -- ★手段ごとに「代価が支払われたか」も見る。
    --   HPだけを見ると、別の呪文やアイテムが効いた場合を取り違える。
    --   呪文: MPが減った / 道具: 在庫が減った
    local paid, paid_text
    if self.method ~= nil and self.method.kind == "spell" then
      local mp_now = self:_total_mp()
      paid = mp_now < self.mp_before_use
      paid_text = string.format("MP %d -> %d", self.mp_before_use, mp_now)
    else
      local herbs_now = self:_herb_count()
      paid = herbs_now < self.herbs_before_use
      paid_text = string.format("%s 残り%d個",
        self.game:item_name(self.item_id), herbs_now)
    end

    -- ★毒を治す周は「HPが増えたか」ではなく「**毒が消えたか**」で判定する。
    --   HP回復と同じ条件で見ると、毒消しはHPを増やさないため必ず失敗と判断される。
    --   効果で検証するという規律は同じで、**見る効果が違う**。
    if self.round_kind == "cure" then
      local target = self.cure_target
      local still_poisoned = true
      -- 対象を並びから引き直す（保持した値は古い）
      for _, m in ipairs(self:_members()) do
        if target ~= nil and m.index == target.index then
          still_poisoned = m.poisoned
        end
      end
      if not still_poisoned and paid then
        self.cures = self.cures + 1
        report(self, string.format("  %s の毒が消えた / %s",
          target and target.name or "?", paid_text))
        self.tries = 0
        self.closes = 0
        self.phase = "closing_to_field"
        return false
      end
      self.tries = self.tries + 1
      if self.tries > self.wait_heal then
        self:_abort(string.format(
          "毒が消えたことを確認できない（%s / %s / menu=%02X）",
          target and target.name or "?", paid_text, st.menu))
      end
      return false
    end

    if hp_now > self.hp_before_use and paid then
      self.uses = self.uses + 1
      report(self, string.format("  HP %d -> %d（%+d）/ %s",
        self.hp_before_use, hp_now, hp_now - self.hp_before_use, paid_text))
      self.tries = 0
      self.closes = 0
      self.phase = "closing_to_field"
      return false
    end

    self.tries = self.tries + 1
    if self.tries > self.wait_heal then
      -- 押したのに回復していない。続けると代価を浪費する。
      self:_abort(string.format(
        "回復を確認できない（HP %d のまま / %s / menu=%02X）",
        hp_now, paid_text, st.menu))
    end
    return false
  end

  ------------------------------------------------------------------
  -- メッセージを閉じてフィールドへ戻る（★A ではなく B）
  ------------------------------------------------------------------
  if self.phase == "closing_to_field" then
    if st.menu == MENU_FIELD then
      self.phase = "check"
      return false
    end
    self.closes = self.closes + 1
    if self.closes > self.max_close then
      self:_abort(string.format("フィールドに戻れない（menu=%02X）", st.menu))
      return false
    end
    self:_do_press("B", "closing_to_field")
    return false
  end

  ------------------------------------------------------------------
  -- 終了処理: 開いたメニューを必ず閉じる
  ------------------------------------------------------------------
  if self.phase == "closing" then
    if st.menu == MENU_FIELD then
      self.phase = "finished"
      return true
    end
    self.closes = self.closes + 1
    if self.closes > self.max_close then
      -- 閉じられなくても報告して終わる。押し続けない。
      report(self, string.format(
        "警告: メニューを閉じられなかった（menu=%02X）。操作は利用者に戻す", st.menu))
      self.phase = "finished"
      return true
    end
    self:_do_press("B", "closing")
    return false
  end

  return false
end

-- 実行結果のまとめ。ログやGUIに出す。
--
-- ★指示書 §11.3 が求めるもの:
--   完了理由 / 前後の合計HP / 使った回数 / 消費MP / 使ったやくそう数 /
--   最終的な各メンバーのHP率 / 各術者のMPと残存率
function Mantan:summary()
  local hp_now = self:_total_hp()

  -- ★誰がどれだけMPを使ったか（指示書 §11.3）
  local spent, spent_total = {}, 0
  for _, m in ipairs(self:_casters()) do
    local used = self.spent_mp and self.spent_mp[m.index] or 0
    spent_total = spent_total + used
    local max_mp = self:_max_mp(m)
    spent[#spent + 1] = {
      name = m.name, spent = used,
      mp = self:_current_mp(m), max_mp = max_mp,
      -- ⚠ 最大MPが分からなければ**割合を出さない**。0 と混ぜない
      ratio = (max_mp and max_mp > 0)
        and (self:_current_mp(m) / max_mp) or nil,
    }
  end

  -- ★最終的な各メンバーのHP率（指示書 §11.3）
  local hp_ratio = {}
  for _, m in ipairs(self:_members()) do
    hp_ratio[#hp_ratio + 1] = {
      name = m.name, hp = m.hp, max_hp = m.max_hp, alive = m.alive,
      ratio = (m.max_hp and m.max_hp > 0) and (m.hp / m.max_hp) or nil,
    }
  end

  return {
    mode     = self.mode_name,
    mode_label = self.mode_label,
    target_percent = self.target_percent,
    status   = self.status,
    reason   = self.reason,
    uses     = self.uses,
    hp_from  = self.hp_start,
    hp_to    = hp_now,
    healed   = (self.hp_start ~= nil) and (hp_now - self.hp_start) or 0,
    herbs_from = self.herbs_start,
    herbs_to = self:_herb_count(),
    frames   = self.frames,
    -- ★2026-08-02 に足したぶん（指示書 §11.3）
    mp_spent = spent,
    mp_spent_total = spent_total,
    members = hp_ratio,
  }
end

return Mantan
