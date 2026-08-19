-- ふくびき（宝くじ）を券がある間だけ連続で回す。
--
-- ねらい: 依頼者の要望
--   「ふくびき券がある間はふくびきを連続でやりたい
--     やりますか？Yes / せつめいをききますか？No / Aボタン連打」
--
-- **待ち時間と反復作業だけ**を削る。券の枚数は増やさないし、当たりも操作しない
-- （ゲーム内の抽選結果にはいっさい触れない）。ビジョンどおり難易度は変えない。
--
-- ★実測で確定した経路（work/fukubiki/probe.txt / answers.txt）:
--   menu=00 フィールド
--     -A-> 06 コマンドメニュー
--     -はなす(0,0)で A-> 04 会話
--     -> 19 行数2「やりますか？」  -> **行0（はい）**
--     -> 19 行数2「せつめいをききますか？」-> **行1（いいえ）**
--     -> メッセージ（B で送る）-> 券が1枚減る
--
-- ★はい/いいえ の行は**画面の文字を読まずに**確定した。
--   4通りの答え方を実際に試し、**券が減る組み合わせ**を見つけた（効果で検証）。
--     Q1=行0 Q2=行1 -> 券 -1 ★
--     Q1=行0 Q2=行0 -> 説明を聞くだけ（減らない）
--     Q1=行1       -> 質問1回で会話終了（= いいえ）
--   字形の対応表を作らずに済み、対応表を間違える危険も無い。
--
-- ★実測で外した推測（記録しておく。戻らないため）:
--   1. 「フィールドで A を押せば話しかけられる」…**誤り**。
--      A 1回はコマンドメニュー(0x06)を開くだけ。**はなす(0,0)で もう1回 A** が必要。
--      これを「誤って開いたメニュー」と見なして閉じていたため、
--      最初の実験は4通りとも会話に入れず「質問0回」で終わっていた。
--   2. 「メッセージ送りは B」…**この会話では誤り**。
--      playbook #16（やくそう使用後のメッセージは B で閉じる）を広げすぎた。
--      ふくびき の会話では **B は「キャンセル」** で、
--      「やりますか？→はい」の直後に B を送ると**はいが取り消され、
--      質問がもう一度出る**。こちらは2回目の質問だと思って「いいえ」を選ぶため、
--      会話が終わって券が減らない（実測 work/fukubiki/verify.txt の1回目:
--      経路 19/2 -> 19/0 -> 19/2 -> 19/1 で券は減らなかった）。
--
--      **会話の中（menu=0x19 / 0x04）のメッセージ送りは A**。
--      依頼者の「Aボタン連打」が正しかった。
--      A が害になるのは**会話が終わった後**で、そのAがコマンドメニューを
--      開いてしまう場合だけ。だから 0x06 が出たら B で閉じる、と分ける。
--
--      教訓: 「このボタンで送る」はゲーム全体の規則ではなく**画面ごとの規則**。
--
-- 設計上の約束（他のマクロと同じ）:
--   ・入力は必ず bridge:request_input 経由（入力の所有者はブリッジ一つ / playbook #13）
--   ・**券が減ったことを確認できなければ中止する。**
--     押したつもりで回っていない状態でループすると入力を吸い続ける。
--   ・すべてのループに上限を置く（playbook #9）
--   ・待ちと寄せでカウンタを分ける（playbook #28）

local Fukubiki = {}
Fukubiki.__index = Fukubiki

local MENU_FIELD   = 0x00     -- フィールド
local MENU_COMMAND = 0x06     -- フィールドのコマンドメニュー
local MENU_DIALOG  = 0x19     -- ふくびき の会話（実測）
local ROW_TALK_X, ROW_TALK_Y = 0, 0   -- コマンドメニューの「はなす」

local ROW_YES = 0             -- 「やりますか？」の はい（実測）
local ROW_NO  = 1             -- 「せつめいをききますか？」の いいえ（実測）

local function report(self, phase, message)
  if self.on_progress then self.on_progress(phase, message) end
end

function Fukubiki.new(opts)
  local self = setmetatable({}, Fukubiki)
  self.game = opts.game
  self.bridge = opts.bridge
  self.on_progress = opts.on_progress
  local cfg = opts.config or {}

  -- ふくびき券のアイテムID。memory_map の items で確認（0x33）。
  -- ★設定で変えられるようにしておく（IDを直接コードへ書かない方針）
  self.ticket_id = cfg.ticket_id or 0x33

  -- 何回まで回すか。券の枚数で自然に止まるが、二重の安全弁として上限を持つ。
  self.max_rounds = cfg.max_rounds or 30
  -- 1周あたりのフレーム上限（抽選の演出を含む）
  self.round_budget = cfg.round_budget or 1800
  -- 全体のフレーム上限
  self.frame_budget = cfg.frame_budget or 40000

  self.press_hold = cfg.press_hold or 8
  self.press_gap  = cfg.press_gap or 18
  -- ★質問が出た直後は行数($0081)が 0 を返す過渡状態がある。
  --   その間は**何も押さない**で待つフレーム数（下の tick を参照）。
  self.settle_frames = cfg.settle_frames or 20
  -- メニューが変わるのを待つ上限。★寄せ用とは別に持つ（playbook #28）
  self.wait_tries = cfg.wait_tries or 40
  self.seek_tries = cfg.seek_tries or 12

  self.phase = "start"
  self.status = "running"
  self.reason = nil
  self.frames = 0
  self.round_frames = 0
  self.rounds = 0            -- 回した回数（券が減った回数）
  self.prompts = 0           -- この周で答えた質問の数
  self.waits = 0
  self.seeks = 0
  self.closes = 0
  self.hold, self.gap = 0, 0
  self.pending_button, self.pending_next = nil, nil
  self.tickets_start = nil
  self.gold_start = nil
  self.round_ticket_mark = nil
  self.settle = nil
  self.menu_trail = {}
  return self
end

----------------------------------------------------------------------
-- 読み取り
----------------------------------------------------------------------

function Fukubiki:_menu()
  return self.game:menu_state()
end

function Fukubiki:_rows()
  return self.game:menu_row_count()
end

function Fukubiki:_members()
  return self.game:active_party()
end

-- ふくびき券の枚数（パーティ全体の合計）。誰が持っていても回せる。
function Fukubiki:_tickets()
  local n = 0
  local spec = self.game.a.inventory
  local slots = (spec and spec.slots) or 8
  for _, m in ipairs(self:_members()) do
    local inv = self.game:inventory(m.index)
    for i = 0, slots - 1 do
      if inv[i] == self.ticket_id then n = n + 1 end
    end
  end
  return n
end

function Fukubiki:_gold()
  local spec = self.game.a.gold
  if spec == nil then return 0 end
  return memory.readbyte(spec.addr) + memory.readbyte(spec.addr + 1) * 256
end

-- はい/いいえ を聞かれている画面か。
-- ★メニューIDだけでなく**行数2**も条件にする。
--   同じ 0x19 が普通のメッセージ（行数1）にも使われるため（実測）。
function Fukubiki:_is_prompt()
  return self:_menu().menu == MENU_DIALOG and self:_rows() == 2
end

function Fukubiki:_note_menu(tag)
  local st = self:_menu()
  local line = string.format("%s:%02X/%d", tag, st.menu, self:_rows())
  local last = self.menu_trail[#self.menu_trail]
  if last ~= line then self.menu_trail[#self.menu_trail + 1] = line end
end

----------------------------------------------------------------------
-- 事前確認（★入力を1つも押す前に判定する）
----------------------------------------------------------------------

function Fukubiki:precheck()
  if self.game:in_battle() then
    return false, "戦闘中は実行しない"
  end

  local members = self:_members()
  if #members == 0 then
    return false, "パーティ状態を読めない"
  end

  local n = self:_tickets()
  if n == 0 then
    return false, string.format("%s を持っていない",
      self.game:item_name(self.ticket_id))
  end

  local st = self:_menu()
  -- フィールド、会話中、コマンドメニューのどれかから始められる。
  -- それ以外（店・戦闘メニュー等）から始めると経路が読めないので断る。
  if st.menu ~= MENU_FIELD and st.menu ~= MENU_COMMAND and st.menu ~= MENU_DIALOG then
    return false, string.format(
      "ふくびき場の人の前（フィールド）で実行すること（現在 menu=%02X）", st.menu)
  end

  return true, string.format("%s %d枚 / ゴールド %d から開始",
    self.game:item_name(self.ticket_id), n, self:_gold())
end

----------------------------------------------------------------------
-- 進行
----------------------------------------------------------------------

function Fukubiki:_abort(reason)
  self.status = "abort"
  -- ★経路を添えて中止する。「動かない」だけでは次に活かせない
  if #self.menu_trail > 0 then
    reason = reason .. "（経路 " .. table.concat(self.menu_trail, " ") .. "）"
  end
  self.reason = reason
  self.phase = "closing"        -- ★中止でもメニューは閉じる
  self.closes = 0
  report(self, "abort", "中止: " .. reason)
end

function Fukubiki:_finish(reason)
  self.status = "done"
  self.reason = reason
  self.phase = "closing"
  self.closes = 0
  report(self, "closing", reason)
end

function Fukubiki:done()
  return self.phase == "finished"
end

function Fukubiki:_do_press(btn, next_phase)
  self.pending_button = btn
  self.pending_next = next_phase
  self.hold = self.press_hold
  self.gap = self.press_gap
  self.phase = "pressing"
end

-- 1列メニューで目標行へ寄せる。端でラップしないので寄せ方は決定的。
-- 戻り値: true = 目標行に居る / false = 押下を要求した
function Fukubiki:_seek_row(want, next_phase)
  local st = self:_menu()
  if st.cy == want then
    self.seeks = 0
    return true
  end
  self.seeks = self.seeks + 1
  if self.seeks > self.seek_tries then
    self:_abort(string.format("行%d に寄らない（現在 行%d）", want, st.cy))
    return false
  end
  self:_do_press(st.cy < want and "down" or "up", next_phase)
  return false
end

function Fukubiki:tick()
  if self.phase == "finished" then return true end

  self.frames = self.frames + 1
  self.round_frames = self.round_frames + 1
  if self.frames > self.frame_budget and self.status == "running" then
    self:_abort(string.format("時間切れ（全体 %dフレーム）", self.frame_budget))
  end
  if self.round_frames > self.round_budget and self.status == "running" then
    self:_abort(string.format("1周が終わらない（%dフレーム / %d周目）",
      self.round_budget, self.rounds + 1))
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
  -- 開始
  ------------------------------------------------------------------
  if self.phase == "start" then
    self.tickets_start = self:_tickets()
    self.gold_start = self:_gold()
    self.phase = "round"
    return false
  end

  ------------------------------------------------------------------
  -- 1周の開始判定
  ------------------------------------------------------------------
  if self.phase == "round" then
    local n = self:_tickets()
    if n == 0 then
      self:_finish(string.format("完了: %d回まわして %s を使い切った",
        self.rounds, self.game:item_name(self.ticket_id)))
      return false
    end
    if self.rounds >= self.max_rounds then
      self:_finish(string.format("上限 %d回に達したので止めた（%s 残り%d枚）",
        self.max_rounds, self.game:item_name(self.ticket_id), n))
      return false
    end
    -- ★この周の基準を記録する。券がこの値より減れば1周まわったと判定できる
    self.round_ticket_mark = n
    self.round_frames = 0
    self.prompts = 0
    self.waits = 0
    self.menu_trail = {}
    report(self, "round", string.format("%d周目: %s 残り%d枚 / ゴールド %d",
      self.rounds + 1, self.game:item_name(self.ticket_id), n, self:_gold()))
    self.phase = "navigate"
    return false
  end

  ------------------------------------------------------------------
  -- 会話へ入る / 進める（出た画面に応じて振る舞う）
  ------------------------------------------------------------------
  if self.phase == "navigate" then
    self:_note_menu("nav")

    -- ★券が減ったら1周成立。効果で検証している
    if self.round_ticket_mark ~= nil and self:_tickets() < self.round_ticket_mark then
      self.rounds = self.rounds + 1
      report(self, "verify", string.format(
        "  %d周目まわった: %s 残り%d枚 / ゴールド %d",
        self.rounds, self.game:item_name(self.ticket_id),
        self:_tickets(), self:_gold()))
      self.phase = "round"
      return false
    end

    -- ★★ 質問が出た直後の過渡状態では何も押さない ★★
    --   実測（work/fukubiki/verify.txt の1回目）: 質問と質問のあいだに
    --   menu=19 行数0 が現れ、そこを「メッセージ」と見なして A を押していた。
    --   行数($0081)は**質問が出た直後にまだ 0 を返す**ため、
    --   その窓で押すと意図しない行が確定する。
    --   戦闘の敵選択でも同じ穴を踏んだ（メニューIDが変わった＝
    --   入力を受け付ける準備ができた、ではない）。
    --   落ち着くまで待ってから「質問か / メッセージか」を判定する。
    if st.menu == MENU_DIALOG and self:_rows() == 0 then
      if self.settle == nil then self.settle = self.settle_frames end
      if self.settle > 0 then
        self.settle = self.settle - 1
        return false                  -- 何も押さない
      end
      -- 落ち着いても行数0ならメッセージとして扱う（下へ落ちる）
    else
      self.settle = nil
    end

    -- はい/いいえ を聞かれている
    if self:_is_prompt() then
      -- 1つ目は「やりますか？」-> はい / 2つ目は「せつめい」-> いいえ
      local want = (self.prompts == 0) and ROW_YES or ROW_NO
      if self:_seek_row(want, "navigate") then
        self.prompts = self.prompts + 1
        report(self, "answer", string.format("  質問%d: 行%d を選ぶ（%s）",
          self.prompts, want, want == ROW_YES and "はい" or "いいえ"))
        self:_do_press("A", "navigate")
      end
      return false
    end

    -- フィールドのコマンドメニューが開いている
    if st.menu == MENU_COMMAND then
      -- ★1周目はここから「はなす」で会話に入る。
      --   2周目以降にここへ来た場合も同じ手順で入れる。
      if st.cx ~= ROW_TALK_X then
        self.seeks = self.seeks + 1
        if self.seeks > self.seek_tries then
          self:_abort(string.format("はなす(0,0)に寄らない（現在 (%d,%d)）", st.cx, st.cy))
          return false
        end
        self:_do_press(st.cx > ROW_TALK_X and "left" or "right", "navigate")
        return false
      end
      if self:_seek_row(ROW_TALK_Y, "navigate") then
        -- ★会話に入り直すので質問の数え直しをする。
        --   これを忘れると、1回目の会話が空振りしたあと
        --   「2つ目以降の質問」と見なして常に いいえ を選び、
        --   話しかける -> いいえ -> 会話終了 -> 話しかける … を繰り返す
        --   （実測 verify.txt の1回目で 質問3〜9 がすべて いいえ になった）。
        self.prompts = 0
        report(self, "talk", "  はなす で話しかける")
        self:_do_press("A", "navigate")
      end
      return false
    end

    -- フィールドに居る -> コマンドメニューを開く
    -- ⚠ A 1回では会話にならない。メニューが開くだけ（実測）
    if st.menu == MENU_FIELD then
      self.waits = self.waits + 1
      if self.waits > self.wait_tries then
        self:_abort("フィールドから会話に入れない（ふくびき場の人の前に居るか確認）")
        return false
      end
      self:_do_press("A", "navigate")
      return false
    end

    -- それ以外は会話中のメッセージ。
    -- ★★ ここは A で送る ★★
    --   この会話では B は「キャンセル」で、はい を取り消してしまう
    --   （実測: はい の直後に B を送ると質問がもう一度出て、券が減らなかった）。
    --   A が害になるのは会話が終わった後だけなので、
    --   コマンドメニュー(0x06)が出た場合を上で先に処理してある。
    self.waits = self.waits + 1
    if self.waits > self.wait_tries * 8 then
      self:_abort(string.format("メッセージが進まない（menu=%02X）", st.menu))
      return false
    end
    self:_do_press("A", "navigate")
    return false
  end

  ------------------------------------------------------------------
  -- 後始末: フィールドへ戻す（★開いたままにしない）
  ------------------------------------------------------------------
  if self.phase == "closing" then
    if st.menu == MENU_FIELD then
      self.phase = "finished"
      return true
    end
    self.closes = self.closes + 1
    if self.closes > 16 then
      -- 閉じきれなくても終了する。押し続けるほうが害が大きい
      self.phase = "finished"
      return true
    end
    self:_do_press("B", "closing")
    return false
  end

  return false
end

function Fukubiki:summary()
  local n = self:_tickets()
  return {
    status  = self.status,
    reason  = self.reason,
    rounds  = self.rounds,
    tickets_from = self.tickets_start,
    tickets_to   = n,
    gold_from = self.gold_start,
    gold_to   = self:_gold(),
    gold_delta = (self.gold_start ~= nil) and (self:_gold() - self.gold_start) or 0,
    frames  = self.frames,
  }
end

return Fukubiki
