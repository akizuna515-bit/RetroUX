-- 「話しかけて、相手に応じたマクロを走らせる」振り分け役。
--
-- 依頼者の要望:
--   「ふくびきのキーバインドはRestockと同じくR
--     （はなす→ 返答が違うので区分けできる）」
--
-- ★区分けは推測ではなく**実測したメニューID**で行う。
--   はなした直後に出る画面が相手ごとに違う:
--     0x18 店の売買選択（かいにきた / うりにきた）-> 補充（restock）
--     0x19 ふくびき の会話（行数2 で はい/いいえ）  -> ふくびき（fukubiki）
--   どちらでもなければ**何もせず中止**する（経路を添えて報告）。
--   知らない相手に対して勝手にボタンを押さないため。
--
-- ★なぜ振り分け役を別に作るか:
--   ホットキーは「1キー = 1つの操作要求」で ActionDriver に渡る。
--   同じ R に2つの操作を割り当てると、片方が必ず「実行中」で無視される。
--   そこで **R = この振り分け役**にして、中で本物のマクロへ委譲する。
--
-- ★委譲先のマクロには手を入れない。
--   Restock も Fukubiki も「自分の画面から始める」ことを precheck で認めている
--   （Restock は 0x18 から、Fukubiki は 0x19 から）。
--   だから話しかけた後にそのまま渡せばよい。
--   委譲先を書き換えずに済むぶん、単独で使う経路（M キーなど）も壊れない。

local TalkDispatch = {}
TalkDispatch.__index = TalkDispatch

local MENU_FIELD   = 0x00
local MENU_COMMAND = 0x06
local ROW_TALK_X, ROW_TALK_Y = 0, 0    -- コマンドメニューの「はなす」

function TalkDispatch.new(opts)
  local self = setmetatable({}, TalkDispatch)
  self.game = opts.game
  self.bridge = opts.bridge
  self.on_progress = opts.on_progress
  -- { [メニューID] = { name = "...", build = function(bridge) return runner end } }
  self.routes = opts.routes or {}
  local cfg = opts.config or {}

  self.press_hold = cfg.press_hold or 8
  self.press_gap  = cfg.press_gap or 18
  -- ★待ちと寄せでカウンタを分ける（playbook #28）
  self.wait_tries = cfg.wait_tries or 40
  self.seek_tries = cfg.seek_tries or 12
  self.frame_budget = cfg.frame_budget or 3000
  -- ★「はなす」を試す回数の上限。
  --   相手が居ないと 06 -> 04（だれもいない）-> 06 … を延々と繰り返す。
  --   実測では28回話しかけて922フレーム分ボタンを押していた（うるさいだけで無害だが、
  --   利用者から見ると暴走しているように見える）。数回で諦める。
  self.max_talks = cfg.max_talks or 3
  self.talks = 0

  self.phase = "talk"
  self.status = "running"
  self.reason = nil
  self.frames = 0
  self.waits = 0
  self.seeks = 0
  self.closes = 0
  self.hold, self.gap = 0, 0
  self.pending_button, self.pending_next = nil, nil
  self.inner = nil            -- 委譲先のマクロ
  self.inner_name = nil
  self.menu_trail = {}
  return self
end

local function report(self, phase, message)
  if self.on_progress then self.on_progress(phase, message) end
end

function TalkDispatch:_menu()
  return self.game:menu_state()
end

function TalkDispatch:_note(tag)
  local st = self:_menu()
  local line = string.format("%s:%02X/%d", tag, st.menu, self.game:menu_row_count())
  if self.menu_trail[#self.menu_trail] ~= line then
    self.menu_trail[#self.menu_trail + 1] = line
  end
end

function TalkDispatch:_route_names()
  local t = {}
  for id, r in pairs(self.routes) do
    t[#t + 1] = string.format("%02X=%s", id, r.name or "?")
  end
  table.sort(t)
  return table.concat(t, " ")
end

function TalkDispatch:precheck()
  if self.game:in_battle() then
    return false, "戦闘中は実行しない"
  end
  local st = self:_menu()

  -- 既に相手の画面が出ているなら、話しかけずにそのまま委譲する
  local route = self.routes[st.menu]
  if route ~= nil then
    return true, string.format("%s の画面(%02X)から始める", route.name or "?", st.menu)
  end

  if st.menu ~= MENU_FIELD and st.menu ~= MENU_COMMAND then
    return false, string.format(
      "フィールドで相手の前に立って実行すること（現在 menu=%02X / 対応 %s）",
      st.menu, self:_route_names())
  end
  return true, string.format("話しかけて相手を見分ける（対応 %s）", self:_route_names())
end

function TalkDispatch:_abort(reason)
  self.status = "abort"
  if #self.menu_trail > 0 then
    reason = reason .. "（経路 " .. table.concat(self.menu_trail, " ") .. "）"
  end
  self.reason = reason
  self.phase = "closing"
  self.closes = 0
  report(self, "abort", "中止: " .. reason)
end

function TalkDispatch:done()
  return self.phase == "finished"
end

function TalkDispatch:_do_press(btn, next_phase)
  self.pending_button = btn
  self.pending_next = next_phase
  self.hold = self.press_hold
  self.gap = self.press_gap
  self.phase = "pressing"
end

function TalkDispatch:tick()
  if self.phase == "finished" then return true end

  -- ★委譲したら以降は完全に任せる。二重に入力を出さない
  if self.phase == "inner" then
    self.inner:tick()
    if self.inner:done() then
      self.phase = "finished"
      return true
    end
    return false
  end

  self.frames = self.frames + 1
  if self.frames > self.frame_budget and self.status == "running" then
    self:_abort(string.format("相手を見分けられない（%dフレーム）", self.frame_budget))
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

  local st = self:_menu()

  if self.phase == "talk" then
    self:_note("talk")

    -- ★相手の画面が出たら委譲する
    local route = self.routes[st.menu]
    if route ~= nil then
      local runner = route.build(self.bridge)
      if runner == nil then
        self:_abort(string.format("%s は無効になっている", route.name or "?"))
        return false
      end
      local ok, reason = runner:precheck()
      if not ok then
        -- ★委譲先が断ったら、こちらもボタンを押さずに終わる
        self.status = "skipped"
        self.reason = string.format("%s: %s", route.name or "?", tostring(reason))
        report(self, "skipped", self.reason)
        self.phase = "closing"
        self.closes = 0
        return false
      end
      self.inner = runner
      self.inner_name = route.name
      report(self, "dispatch", string.format(
        "%s と判定して %s を実行する（menu=%02X / %s）",
        route.name or "?", route.name or "?", st.menu, tostring(reason)))
      self.phase = "inner"
      return false
    end

    -- コマンドメニュー -> 「はなす」へ寄せて決定
    if st.menu == MENU_COMMAND then
      if st.cx ~= ROW_TALK_X then
        self.seeks = self.seeks + 1
        if self.seeks > self.seek_tries then
          self:_abort(string.format("はなす(0,0)に寄らない（現在 (%d,%d)）", st.cx, st.cy))
          return false
        end
        self:_do_press(st.cx > ROW_TALK_X and "left" or "right", "talk")
        return false
      end
      if st.cy ~= ROW_TALK_Y then
        self.seeks = self.seeks + 1
        if self.seeks > self.seek_tries then
          self:_abort(string.format("はなす(0,0)に寄らない（現在 (%d,%d)）", st.cx, st.cy))
          return false
        end
        self:_do_press(st.cy > ROW_TALK_Y and "up" or "down", "talk")
        return false
      end
      self.seeks = 0
      -- ★話しかけた回数で諦める（相手が居ないと延々と繰り返すため）
      self.talks = self.talks + 1
      if self.talks > self.max_talks then
        self:_abort(string.format(
          "%d回はなしても 補充/ふくびき の相手ではなかった（対応 %s）",
          self.max_talks, self:_route_names()))
        return false
      end
      report(self, "talk", string.format("はなす で話しかける（%d回目）", self.talks))
      self:_do_press("A", "talk")
      return false
    end

    -- フィールド -> コマンドメニューを開く
    -- ⚠ A 1回では会話にならない。メニューが開くだけ（ふくびきの実測で確認）
    if st.menu == MENU_FIELD then
      self.waits = self.waits + 1
      if self.waits > self.wait_tries then
        self:_abort("話しかけられない（相手の前に立っているか確認）")
        return false
      end
      self:_do_press("A", "talk")
      return false
    end

    -- 会話のメッセージなど。★A で送る（会話の中では B はキャンセル）
    self.waits = self.waits + 1
    if self.waits > self.wait_tries * 4 then
      self:_abort(string.format("相手の画面が出ない（menu=%02X / 対応 %s）",
        st.menu, self:_route_names()))
      return false
    end
    self:_do_press("A", "talk")
    return false
  end

  if self.phase == "closing" then
    if st.menu == MENU_FIELD then
      self.phase = "finished"
      return true
    end
    self.closes = self.closes + 1
    if self.closes > 16 then
      self.phase = "finished"
      return true
    end
    self:_do_press("B", "closing")
    return false
  end

  return false
end

function TalkDispatch:summary()
  -- ★委譲先の要約をそのまま返す（利用者が見たいのは中身の結果）
  if self.inner ~= nil then
    local s = self.inner:summary()
    s.dispatched_to = self.inner_name
    return s
  end
  return {
    status = self.status,
    reason = self.reason,
    dispatched_to = nil,
    frames = self.frames,
  }
end

return TalkDispatch
