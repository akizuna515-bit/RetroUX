-- 補充（店で足りない道具を買い足す）
--
-- ねらい: 町に着くたび「やくそうを3個、どくけしを1個…」と数えて買う反復作業をなくす。
-- 待ち時間と反復作業だけを対象とし、ゲーム内の在庫・値段・所持金は一切変えない。
-- 買えない物は買えないままにする（難易度に触れない）。
--
-- 実測で確定した店の経路（work/buyherb/ / DEV-12 と同じ調査系統）:
--   店主に話す
--     -> 0x18 売買選択（かいにきた=行0 / うりにきた=行1）
--     -> 0x16 品揃えリスト（$0100 から3バイト刻み [ID, 値段16bitLE]）
--     -> アイテムを選ぶと購入が確定する（個数は聞かれない）
--
-- ★★ 訂正（2026-07-25）★★
--   当初「0x18 の時点で既に品揃えが埋まっており、押す前に計画を立てられる」
--   としていたが**誤りだった**。根拠が「一度品揃えを開いた履歴のあるセーブ
--   1件」しかなく、新しいセーブでは空で補充が動かなかった
--   （利用者の報告「R押しても動かない」/ 理由「店の品揃えを読めない」）。
--
--   品揃えは**リスト(0x16)を開いている間だけ**読める。
--   そのため 0x18 から始めた場合は「かいにきた」を押してから計画を立てる。
--   押す前に判定できるのは 0x16 から始めた場合だけ。
--   「かいにきた」を押すこと自体は無害（リストが開くだけ）なので、
--   買う物が無ければそのまま何も買わずに終える。
--
-- 設計上の約束（まんたんと同じ）:
--   ・入力は必ず bridge:request_input 経由（joypad.set を直接呼ばない）
--   ・**在庫が増えて所持金が減ったことを確認できなければ中止する。**
--     押したつもりで買えていない状態でループすると無駄な操作を続ける
--   ・すべてのループに上限を置く
--   ・欲しい物を扱っていない店では**ボタンを1つも押さずに終わる**
--
-- ⚠ 所持品IDの装備中フラグ: 持ち物のIDは装備中に bit6(0x40) が立つ。
--   在庫を数えるときは 0x3F でマスクして比べる。
--   これを忘れると「装備中のどうのつるぎ(0x46)」を別物と数えてしまう。

local Restock = {}
Restock.__index = Restock

local DEFAULTS = {
  press_hold   = 8,
  press_gap    = 20,
  wait_menu    = 90,
  wait_buy     = 120,   -- 購入が反映されるまで待つ上限
  max_seek     = 12,
  max_close    = 8,
  frame_budget = 10800, -- 約180秒

  -- ★メニューが「落ち着く」まで待つフレーム数。
  --
  -- 実測（work/restock/test.txt）で踏んだ不具合:
  --   品揃え画面(0x16)が開いた直後、誰も押していないのに
  --   cursor_x が 2 -> 3 -> 255 と動いていた。メニューがまだ開く途中で、
  --   その最中に A を押すとゲームに飲まれて購入が成立しない。
  --   menu の値だけを見て「開いた」と判断したのが誤りだった。
  --   同種の現象は DEV-14（戦闘後の遷移中は入力を無視する）でも見ている。
  --
  -- 対策: メニューID・カーソル位置が変化しないフレームが続いてから押す。
  settle_frames = 12,

  -- ★購入が成立した直後、ゲームが入力を受け付けない期間があるため待つ。
  --
  -- 実測（work/restock/test.txt）:
  --   購入の29フレーム後に送った A は**何も起きなかった**が、
  --   150フレーム後に送った A はメッセージを進めた。
  --   この期間中は menu もカーソルも変化しないため、
  --   settle_frames（状態が落ち着いたか）では検出できない。
  --   観測できる信号が無いので、ここだけは時間で待つ。
  post_buy_wait = 60,
}

local MENU_FIELD    = 0x00
local MENU_COMMAND  = 0x06
local COL_TALK_X, COL_TALK_Y = 0, 0   -- コマンドメニューの「はなす」
local MENU_TRADE    = 0x18   -- かいにきた / うりにきた
local MENU_SHOP     = 0x16   -- 品揃えリスト
-- ★購入時の持ち主選択「だれが おもちに なりますか？」。
--   2人以上のパーティのときだけ出る（1人なら誰に持たせるか選ぶ必要がない）。
--   まんたんの 0x0E/0x11 と同じパターン（B-11）。
--   行はパーティの並び順。行数は加入者数（$0081 で確認できる）。
--   ⚠ この画面では所持金が既に引かれた表示になるが、確定前なので
--     B で戻せば元に戻る（実測: 606 -> 591 -> B -> 606）。
local MENU_CARRIER  = 0x12
local ROW_BUY       = 0      -- 「かいにきた」
local ITEM_ID_MASK  = 0x3F   -- 装備中フラグ(0x40)を落とす

-- opts.game / opts.bridge 必須。opts.plan_only で計画だけ立てることもできる。
function Restock.new(opts)
  local self = setmetatable({}, Restock)
  self.game = opts.game
  self.bridge = opts.bridge
  self.on_progress = opts.on_progress
  local cfg = (opts.config or {})
  self.want_list = cfg.items or {}
  self.keep_gold = cfg.keep_gold or 0
  self.max_purchases = cfg.max_purchases or 20
  for k, v in pairs(DEFAULTS) do
    self[k] = (opts[k] ~= nil) and opts[k] or v
  end
  self.phase = "check"
  self.hold, self.gap, self.tries, self.frames = 0, 0, 0, 0
  -- 寄せ専用のカウンタ（待ちの tries とは独立。_seek_row のコメント参照）
  self.seek_tries = 0
  self.seek_key = nil
  self.bought = 0
  self.closes = 0
  self.status = "running"
  self.reason = nil
  self.plan = nil
  self.gold_start = nil
  return self
end

local function report(self, msg)
  if self.on_progress then self.on_progress(self.phase, msg) end
end

function Restock:_menu() return self.game:menu_state() end

function Restock:_item_name(id)
  return self.game:item_name(id)
end

-- パーティ全体の所持数。★装備中フラグを落として比べる。
function Restock:_have(item_id)
  local spec = self.game.a.inventory
  local slots = (spec and spec.slots or 8)
  local n = 0
  for _, m in ipairs(self.game:active_party()) do
    local inv = self.game:inventory(m.index)
    for i = 0, slots - 1 do
      local got = inv[i]
      if got ~= nil and got % 0x40 == item_id % 0x40 and got ~= 0 then
        -- 上の比較は bit6 を無視するための剰余。0x40 を足し引きしても一致する
        n = n + 1
      end
    end
  end
  return n
end

-- 1人ぶんの空きスロット数。
function Restock:_free_slots_of(who)
  local spec = self.game.a.inventory
  local slots = (spec and spec.slots or 8)
  local free = 0
  local inv = self.game:inventory(who)
  for i = 0, slots - 1 do
    if inv[i] == nil or inv[i] == 0 then free = free + 1 end
  end
  return free
end

-- 買った物を持たせる相手を選ぶ。
-- 戻り値: 行番号（0始まり / active_party 内の位置）, 名前, 空き数
-- ★行番号は並びの位置。RAM上のメンバー番号ではない（B-11 と同じ注意）。
--
-- ★★ 空きが最も多い人に持たせる（依頼者の要望）★★
--   > Restockのときに、荷物の空きをなるべく均等にしたい。
--   > なるべく平均的な荷物量になるように分配させたい
--
--   以前は「**最初に**空きがある人」を返していたため、
--   1人目が満杯になるまで全部その人に積まれて偏っていた。
--
--   空きが最も多い人を選ぶと、購入は1個ずつ持ち主を聞かれるので
--   **自動的に均等化する**。
--     例) 空き 3/3/3 で3個買う -> 1人目(3->2) / 2人目(3->2) / 3人目(3->2)
--         同数のときは並びの早い人が取り、次の周ではその人の空きが減るので
--         別の人に回る。特別な順番管理は要らない。
--
--   同数のときは**生存者を優先**する。死んでいる人に回復アイテムを預けると
--   まんたんが使いにくくなる（_pick_owner は生存者を優先するため）。
--   空きの均等さは損なわない（同数の中での優先なので）。
function Restock:_pick_carrier()
  local best_pos, best_name, best_free, best_alive = nil, nil, -1, false
  for pos, m in ipairs(self.game:active_party()) do
    local free = self:_free_slots_of(m.index)
    local alive = (m.alive == true)
    -- 空きが多い方を優先。同数なら生存者。さらに同じなら並びの早い方（>= にしない）
    local better = (free > best_free)
      or (free == best_free and alive and not best_alive)
    if free > 0 and better then
      best_pos, best_name, best_free, best_alive = pos - 1, m.name, free, alive
    end
  end
  if best_pos == nil then return nil, nil, 0 end
  return best_pos, best_name, best_free
end

-- 空きの偏りを人が読める形にする（報告用）。
-- ★「均等にした」と言うだけでは検証できないので、実際の数を出す。
function Restock:_free_slots_text()
  local t = {}
  for _, m in ipairs(self.game:active_party()) do
    t[#t + 1] = string.format("%s %d", tostring(m.name), self:_free_slots_of(m.index))
  end
  return table.concat(t, " / ")
end

-- 持ち物の空きスロット数。買っても入らなければ意味がない。
function Restock:_free_slots()
  local spec = self.game.a.inventory
  local slots = (spec and spec.slots or 8)
  local free = 0
  for _, m in ipairs(self.game:active_party()) do
    local inv = self.game:inventory(m.index)
    for i = 0, slots - 1 do
      if inv[i] == nil or inv[i] == 0 then free = free + 1 end
    end
  end
  return free
end

----------------------------------------------------------------------
-- 計画（★ボタンを押す前にすべて決める）
----------------------------------------------------------------------

-- 戻り値: 計画の配列, 説明文
-- 各要素: { id, name, row, price, need, buy }
--   need = 足りない数 / buy = 実際に買う数（所持金と空きスロットで削る）
function Restock:build_plan()
  local shop = self.game:shop_list()
  local gold = self.game:gold()
  local budget = gold - self.keep_gold
  local free = self:_free_slots()

  local plan, notes = {}, {}
  local total_cost, total_buy = 0, 0

  for _, want in ipairs(self.want_list) do
    local id = want.id
    local row, price = self.game:find_shop_row(id)
    local have = self:_have(id)
    local need = math.max(0, (want.want or 0) - have)

    if row == nil then
      if need > 0 then
        notes[#notes + 1] = string.format("%s は扱っていない", self:_item_name(id))
      end
    elseif need == 0 then
      notes[#notes + 1] = string.format("%s は足りている(%d個)", self:_item_name(id), have)
    else
      -- 所持金と空きスロットの範囲まで削る
      local affordable = (price > 0) and math.floor((budget - total_cost) / price) or 0
      local buy = math.min(need, affordable, free - total_buy,
                           self.max_purchases - total_buy)
      if buy > 0 then
        plan[#plan + 1] = {
          id = id, name = self:_item_name(id), row = row,
          price = price, need = need, buy = buy,
        }
        total_cost = total_cost + price * buy
        total_buy = total_buy + buy
      end
      if buy < need then
        notes[#notes + 1] = string.format(
          "%s は %d個足りないが %d個しか買えない（所持金%d / 空き%d）",
          self:_item_name(id), need, buy, gold, free)
      end
    end
  end

  local parts = {}
  for _, p in ipairs(plan) do
    parts[#parts + 1] = string.format("%s×%d(%dG)", p.name, p.buy, p.price * p.buy)
  end
  local summary
  if #plan == 0 then
    summary = "買う物がない"
  else
    summary = string.format("%s / 合計%dG（所持金%d）",
      table.concat(parts, " "), total_cost, gold)
  end
  if #notes > 0 then
    summary = summary .. " ｜ " .. table.concat(notes, " / ")
  end
  return plan, summary, total_cost
end

----------------------------------------------------------------------
-- 事前確認（★入力を1つも送る前に判定する）
----------------------------------------------------------------------

function Restock:precheck()
  if self.game:in_battle() then
    return false, "戦闘中は実行しない"
  end
  if #self.want_list == 0 then
    return false, "補充リストが空（config の restock.items を設定する）"
  end

  local st = self:_menu()
  -- ★店の前のフィールドからでも実行できる（依頼者の要望）。
  --   実測: A -> 06 -> はなす(0,0) -> A -> 04（会話）-> +40フレームで 18。
  --   店主の前でなければ会話が始まらず 0x18 に到達しないので、
  --   上限つきで待って安全に中止する。
  if st.menu == MENU_FIELD then
    return true, "店主に話しかけてから買う物を決めます"
  end
  -- 店の売買選択(0x18)か品揃え(0x16)から始めた場合。
  if st.menu ~= MENU_TRADE and st.menu ~= MENU_SHOP then
    return false, string.format(
      "店の前か、売買選択の画面で実行すること（現在 menu=%02X）", st.menu)
  end

  -- ★0x18（売買選択）の時点では品揃えを読めない。
  -- ここで「読めない」と拒否していたため、利用者が店で R を押しても
  -- 何も起きなかった。「かいにきた」を押してから計画を立てる。
  if st.menu == MENU_TRADE then
    return true, "品揃えを開いてから買う物を決めます"
  end

  -- 0x16（品揃え）から始めた場合は、押す前に計画まで立てられる
  local shop = self.game:shop_list()
  local count = 0
  for _ in pairs(shop) do count = count + 1 end
  if count == 0 then
    return false, "店の品揃えを読めない（品揃えの画面か確認する）"
  end

  local plan, summary = self:build_plan()
  if #plan == 0 then
    -- ★買う物が無いなら**ボタンを押さずに終わる**
    return false, summary
  end
  self.plan = plan
  self.plan_index = 1
  return true, summary
end

----------------------------------------------------------------------
-- 進行
----------------------------------------------------------------------

function Restock:_abort(reason)
  self.status = "abort"
  -- 直前のメニュー遷移を添える（原因を追えるようにするため）
  if self.menu_trail ~= nil and #self.menu_trail > 0 then
    local parts = {}
    for _, m in ipairs(self.menu_trail) do
      parts[#parts + 1] = string.format("%02X", m)
    end
    reason = reason .. "（経路: " .. table.concat(parts, "->") .. "）"
  end
  self.reason = reason
  self.phase = "closing"
  self.closes = 0
  report(self, "中止: " .. reason)
end

function Restock:_finish(reason)
  self.status = "done"
  self.reason = reason
  self.phase = "closing"
  self.closes = 0
  report(self, reason)
end

function Restock:done() return self.phase == "finished" end

function Restock:_do_press(btn, next_phase)
  self.pending_button = btn
  self.pending_next = next_phase
  self.hold = self.press_hold
  self.gap = self.press_gap
  self.phase = "pressing"
end

-- 押してよい状態か（メニューが落ち着いているか）
function Restock:_settled()
  return (self.stable_for or 0) >= self.settle_frames
end

-- カーソルを目標行へ寄せる。
--
-- ★★ 待ちと寄せでカウンタを共有してはいけない ★★
-- 実測（work/shoptalk/trace.txt）で踏んだ不具合:
--   購入後、持ち主選択(0x12)が出るまで menu は 16 のままで約25フレームかかる。
--   その待ちのあいだ carrier フェーズが tries を 25 まで増やし、
--   0x12 が実際に出た瞬間に _seek_row が上限(12)超過で即中止した。
--   **カーソルは動かせるのに、動かす前に諦めていた。**
--   実プレイでも「カーソルが行1 に寄らない」でどくけしそうが買えなかった。
-- そのため寄せ専用のカウンタを持ち、対象（メニュー＋目標行）が変わったら
-- ゼロに戻す。待ち側の tries とは独立させる。
function Restock:_seek_row(target, next_phase)
  -- ★落ち着くまで押さない。開く途中のカーソル値は当てにならない。
  if not self:_settled() then return end
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

function Restock:tick()
  if self.phase == "finished" then return true end

  self.frames = self.frames + 1
  if self.frames > self.frame_budget and self.status == "running" then
    self:_abort(string.format("時間切れ（%dフレーム）", self.frame_budget))
  end

  local st = self:_menu()

  -- ★直前のメニュー遷移を覚えておく。中止したときに何が起きたか分かるように。
  -- 「品揃えの画面が出ない（menu=06）」のように結果だけ見ても、
  -- どこから 06 になったのかが分からず原因を追えなかった。
  if self.menu_trail == nil then self.menu_trail = {} end
  if self.menu_trail[#self.menu_trail] ~= st.menu then
    self.menu_trail[#self.menu_trail + 1] = st.menu
    if #self.menu_trail > 10 then table.remove(self.menu_trail, 1) end
  end

  -- ★メニューが落ち着いているかを毎フレーム数える。
  -- メニューID・カーソル位置が変わらないフレームが続いていれば落ち着いている。
  -- 開く途中で押すとゲームに入力を飲まれる（DEFAULTS.settle_frames のコメント参照）。
  local key = string.format("%d,%d,%d", st.menu, st.cx, st.cy)
  if key == self.last_state then
    self.stable_for = (self.stable_for or 0) + 1
  else
    self.stable_for = 0
    self.last_state = key
  end

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
  -- 「かいにきた」を選んで品揃えへ
  ------------------------------------------------------------------
  if self.phase == "check" then
    if self.gold_start == nil then self.gold_start = self.game:gold() end
    if st.menu == MENU_SHOP then
      self.phase = "next_item"
      return false
    end
    -- ★フィールドから始めた場合は「はなす」で店に入る
    if st.menu == MENU_FIELD then
      self.tries = 0
      self:_do_press("A", "wait_command")
      return false
    end
    if st.menu ~= MENU_TRADE then
      self:_abort(string.format("売買選択の画面でない（menu=%02X）", st.menu))
      return false
    end
    self.seek_return = "check"
    self:_seek_row(ROW_BUY, "press_buy")
    return false
  end

  ------------------------------------------------------------------
  -- フィールドから: 06 コマンド -> はなす -> 会話 -> 18 売買選択
  ------------------------------------------------------------------
  if self.phase == "wait_command" then
    if st.menu == MENU_COMMAND then
      self.tries = 0
      self.phase = "seek_talk"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format("コマンドメニューが開かない（menu=%02X）", st.menu))
    end
    return false
  end

  if self.phase == "seek_talk" then
    if st.menu ~= MENU_COMMAND then
      self:_abort(string.format("コマンドメニューから外れた（menu=%02X）", st.menu))
      return false
    end
    if not self:_settled() then return false end
    if st.cx == COL_TALK_X and st.cy == COL_TALK_Y then
      self.tries = 0
      self:_do_press("A", "wait_trade")
      return false
    end
    self.seek_tries = (self.seek_tries or 0) + 1
    if self.seek_tries > self.max_seek then
      self:_abort(string.format("はなす(0,0)に寄らない（現在 (%d,%d)）", st.cx, st.cy))
      return false
    end
    local dir
    if st.cy > COL_TALK_Y then dir = "up"
    elseif st.cy < COL_TALK_Y then dir = "down"
    elseif st.cx > COL_TALK_X then dir = "left"
    else dir = "right" end
    self:_do_press(dir, "seek_talk")
    return false
  end

  -- 会話から売買選択(0x18)へ。店主の前でなければ到達しないので上限つきで待つ。
  if self.phase == "wait_trade" then
    if st.menu == MENU_TRADE then
      self.tries = 0
      self.seek_key = nil
      self.phase = "check"
      return false
    end
    if st.menu == MENU_SHOP then
      self.tries = 0
      self.phase = "next_item"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format(
        "店の売買選択に入れない（menu=%02X）。店主の前に立っているか確認する", st.menu))
    end
    return false
  end

  if self.phase == "press_buy" then
    if not self:_settled() then return false end
    -- ⚠ 行1は「うりにきた」。誤って選ぶと売却画面に入るので直前に確認する
    if st.menu ~= MENU_TRADE or st.cy ~= ROW_BUY then
      self:_abort(string.format("「かいにきた」に居ないため決定しない（menu=%02X 行%d）",
        st.menu, st.cy))
      return false
    end
    self:_do_press("A", "wait_shop")
    return false
  end

  if self.phase == "wait_shop" then
    if st.menu == MENU_SHOP then
      self.tries = 0
      self.phase = "next_item"
      return false
    end
    -- ★店の画面から外れていたら「はなす」経路で立て直す。
    -- 実プレイで 0x18 から A を押した結果が 06（フィールドのコマンドメニュー）
    -- になり中止していた。店の前に立っていれば話しかけ直せば入れる。
    if st.menu == MENU_COMMAND or st.menu == MENU_FIELD then
      if (self.recovered or 0) >= 1 then
        self:_abort(string.format("店に入り直せない（menu=%02X）", st.menu))
        return false
      end
      self.recovered = (self.recovered or 0) + 1
      self.tries = 0
      self.seek_key = nil
      report(self, "店の画面から外れていたため、話しかけ直します")
      -- 06 なら閉じてから、00 ならそのまま「はなす」へ
      if st.menu == MENU_COMMAND then
        self.phase = "seek_talk"
      else
        self:_do_press("A", "wait_command")
      end
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      self:_abort(string.format("品揃えの画面が出ない（menu=%02X）", st.menu))
    end
    return false
  end

  ------------------------------------------------------------------
  -- 計画に沿って1個ずつ買う
  ------------------------------------------------------------------
  if self.phase == "next_item" then
    -- ★0x18 から始めた場合、計画はここで初めて立てられる
    -- （品揃えは 0x16 を開いている間しか読めない）。
    if self.plan == nil then
      if st.menu ~= MENU_SHOP or not self:_settled() then
        self.tries = self.tries + 1
        if self.tries > self.wait_menu then
          self:_abort(string.format("品揃えの画面に落ち着かない（menu=%02X）", st.menu))
        end
        return false
      end
      local plan, summary = self:build_plan()
      report(self, summary)
      if #plan == 0 then
        self:_finish("完了: " .. summary)
        return false
      end
      self.plan = plan
      self.plan_index = 1
      self.tries = 0
    end

    local item = self.plan[self.plan_index]
    if item == nil then
      self:_finish(string.format("完了: %d個購入（所持金 %d -> %d）",
        self.bought, self.gold_start, self.game:gold()))
      return false
    end
    if item.bought == nil then item.bought = 0 end
    if item.bought >= item.buy then
      self.plan_index = self.plan_index + 1
      return false
    end

    -- ★品揃えの画面に落ち着くまで待つ。即座に中止してはいけない。
    -- 実測: 「かいにきた」を決めた直後、誰も押していないのに
    -- menu が 16 -> 1B -> 16 と動く（店主のメッセージが約30フレーム挟まる）。
    -- 厳格に「16 でなければ中止」にしていたため、その一瞬で中止していた。
    -- 一時的に別のメニューになるのは正常。上限つきで待つ。
    if st.menu ~= MENU_SHOP or not self:_settled() then
      self.tries = self.tries + 1
      if self.tries > self.wait_menu then
        self:_abort(string.format(
          "品揃えの画面に落ち着かない（menu=%02X）", st.menu))
      end
      return false
    end
    self.tries = 0

    -- ★毎回IDから行を引き直す。品揃えの行は固定と分かっているが、
    --   売り切れなどで並びが変わっても壊れないようにする。
    local row = self.game:find_shop_row(item.id)
    if row == nil then
      self:_abort(string.format("%s が品揃えから消えた", item.name))
      return false
    end
    self.current_row = row
    self.have_before = self:_have(item.id)
    self.gold_before = self.game:gold()
    -- 2人以上なら購入後に持ち主を聞かれる。空きのある人を選ぶ
    local carrier_row, carrier_name, carrier_free = self:_pick_carrier()
    if carrier_row == nil then
      self:_abort(string.format("持ち物に空きが無い（空き %s）", self:_free_slots_text()))
      return false
    end
    self.carrier_row = carrier_row
    self.carrier_name = carrier_name
    -- ★誰に持たせたかと、そのときの空き具合を残す。
    --   「均等にした」と主張するだけでは検証できないので実際の数を出す。
    report(self, string.format("  %s を %s に持たせる（空き %s）",
      item.name, tostring(carrier_name), self:_free_slots_text()))
    self.seek_return = "next_item"
    self:_seek_row(row, "press_item")
    return false
  end

  if self.phase == "press_item" then
    -- ★落ち着くまで押さない。開く途中に押すと購入が成立しない（実測）
    if not self:_settled() then return false end
    -- 画面が変わっていたら中止せずに寄せ直しへ戻る（上限は next_item 側にある）
    if st.menu ~= MENU_SHOP then
      self.phase = "next_item"
      return false
    end
    if st.cy ~= self.current_row then
      -- カーソルがずれた。寄せ直す（誤った行を買わないため決定しない）
      self.phase = "next_item"
      return false
    end
    self.tries = 0
    self:_do_press("A", "carrier")
    return false
  end

  ------------------------------------------------------------------
  -- ★2人以上では「だれが おもちに なりますか？」(0x12)が入る
  ------------------------------------------------------------------
  if self.phase == "carrier" then
    if st.menu == MENU_CARRIER then
      self.seek_return = "carrier"
      self:_seek_row(self.carrier_row, "press_carrier")
      return false
    end
    -- 1人パーティの店では聞かれず、そのまま購入が成立する
    local item = self.plan[self.plan_index]
    if self:_have(item.id) > self.have_before then
      self.tries = 0
      self.phase = "verify"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_buy then
      self:_abort(string.format(
        "アイテムを選んだ後に何も起きない（menu=%02X）", st.menu))
    end
    return false
  end

  if self.phase == "press_carrier" then
    if not self:_settled() then return false end
    if st.menu ~= MENU_CARRIER then
      -- 既に進んでいれば検証へ
      self.phase = "verify"
      return false
    end
    if st.cy ~= self.carrier_row then
      self.phase = "carrier"
      return false
    end
    self.tries = 0
    self:_do_press("A", "verify")
    return false
  end

  ------------------------------------------------------------------
  -- ★検証: 在庫が増えて所持金が減ったか
  ------------------------------------------------------------------
  if self.phase == "verify" then
    local item = self.plan[self.plan_index]
    local have_now = self:_have(item.id)
    local gold_now = self.game:gold()

    if have_now > self.have_before and gold_now < self.gold_before then
      item.bought = item.bought + 1
      self.bought = self.bought + 1
      report(self, string.format("  %s を購入（%d個目 / %dG -> %dG / 所持%d個）",
        item.name, item.bought, self.gold_before, gold_now, have_now))
      self.tries = 0
      self.closes = 0
      -- ★購入直後は入力を受け付けない期間がある。時間で待つ
      self.wait_left = self.post_buy_wait
      self.phase = "after_buy_wait"
      return false
    end

    self.tries = self.tries + 1
    if self.tries > self.wait_buy then
      self:_abort(string.format(
        "購入を確認できない（%s / 所持%d個のまま / 所持金%d のまま / menu=%02X）",
        item.name, have_now, gold_now, st.menu))
    end
    return false
  end

  -- 購入後は品揃えへ戻るまでメッセージを送る。
  --
  -- ★実測で確定した経路（work/restock/loop.txt）:
  --   16 品揃え --A--> 購入成立（所持金が減る。1フレーム後）
  --           --A--> 1B「まいど ありがとうございます」
  --           --A--> 19「ほかに なにか ひつょうですか？」
  --           --A--> 16 品揃えに戻る（ここでまた買える）
  --
  -- ★最大の落とし穴: **購入直後も menu は 16 のまま**。
  --   「まいど ありがとうございます」は menu を変えない。
  --   そのため「16 なら買える」と判断すると、次の A がメッセージ送りに
  --   使われて2個目が買えない（実測で踏んだ）。
  --   menu だけでは購入できる状態か分からないので、
  --   **A を押して一度16から離れ、再び16へ戻る**ことで区別する。
  --
  -- ★送るのは A。B は 19 の「いいえ」に当たり店から出てしまう。
  --   DEV-14（戦闘後のメッセージは B で送る）とは逆。
  --   フィールドと違い店の中では A に危険な副作用がない。
  -- 購入直後の入力を受け付けない期間を待つ（観測できる信号が無いため時間で待つ）
  if self.phase == "after_buy_wait" then
    self.wait_left = self.wait_left - 1
    if self.wait_left <= 0 then self.phase = "after_buy" end
    return false
  end

  if self.phase == "after_buy" then
    -- まず1回 A を送ってメッセージを進める（この時点の menu は 16 のまま）
    if not self:_settled() then return false end
    self.closes = 0
    self:_do_press("A", "await_leave")
    return false
  end

  -- 16 から離れるのを待つ。離れれば「メッセージが動いた」証拠。
  if self.phase == "await_leave" then
    if st.menu ~= MENU_SHOP then
      self.tries = 0
      self.phase = "ack_message"
      return false
    end
    self.tries = self.tries + 1
    if self.tries > self.wait_menu then
      -- 動かない。もう買える状態かもしれないので次の品へ進む
      self.tries = 0
      self.phase = "next_item"
    end
    return false
  end

  -- メッセージを送り切って品揃えへ戻る
  if self.phase == "ack_message" then
    if st.menu == MENU_SHOP then
      if self:_settled() then
        self.tries = 0
        self.closes = 0
        self.phase = "next_item"
      end
      return false
    end
    if not self:_settled() then return false end
    self.closes = self.closes + 1
    if self.closes > self.max_close then
      self:_abort(string.format("購入後に品揃えへ戻らない（menu=%02X）", st.menu))
      return false
    end
    self:_do_press("A", "ack_message")
    return false
  end

  ------------------------------------------------------------------
  -- 終了処理: 開いた画面を閉じる
  ------------------------------------------------------------------
  if self.phase == "closing" then
    if st.menu == MENU_FIELD or st.menu == MENU_TRADE then
      -- 店の画面まで戻れば十分。フィールドまで戻すかは利用者に委ねる
      self.phase = "finished"
      return true
    end
    self.closes = self.closes + 1
    if self.closes > self.max_close then
      report(self, string.format(
        "警告: 画面を閉じられませんでした（menu=%02X）。操作は利用者に戻します", st.menu))
      self.phase = "finished"
      return true
    end
    self:_do_press("B", "closing")
    return false
  end

  return false
end

function Restock:summary()
  return {
    status     = self.status,
    reason     = self.reason,
    bought     = self.bought,
    gold_from  = self.gold_start,
    gold_to    = self.game:gold(),
    spent      = (self.gold_start ~= nil) and (self.gold_start - self.game:gold()) or 0,
    frames     = self.frames,
    -- ★分配の結果を残す（依頼者の要望「空きをなるべく均等に」の確認用）
    free_slots = self:_free_slots_text(),
  }
end

return Restock
