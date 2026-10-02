-- 人のパッド入力を読む（RX3-0486 / 2026-10-02）。
--
-- ★RetroUX（`dq3/ui/gamepad_link.py`）が XInput のパッドを読み、
--   NES のボタンを `work/dq3-gamepad.txt` へ `"<seq> <mask>"` で書きます。
--   ★ここはそれを読んで「いま人が押しているボタン」を返すだけです。
--   ⚠ `joypad.set` は呼びません（★呼ぶのは `core.lua` の `B.tick` の 1 か所だけ）。
--
-- ★形は DQ2 の `retroux/emulator/fceux/bridge.lua` の `_poll_pad_input` と同じです
--   （⚠ DQ2 のファイルは読むだけ / 1 行も変えていません）。
--
-- ## ⚠⚠ DQ2 から変えたところ — 「古い入力」を**時間**で決める
--
--   DQ2 は「seq が 30 回（8 ms ごとの読み）変わらなければ 0」でした。
--   ★ここでは **seq が 0.5 秒変わらなければ 0** にします（依頼者 2026-10-02 §5:
--   ターボ中でも正常な長押しが途切れないこと）。
--   ★`os.clock()` は Windows では**経過時間**（CPU 時間ではない）なので、
--     ターボでフレームが速く回っても 0.5 秒は 0.5 秒です。
--   ★RetroUX は押している間は約 16 ms ごとに seq を進めるので、0.5 秒は十分な余裕です。
--
-- ## ★ファイルは開いたまま読む
--
--   ⚠ 書き換わったファイルを毎回開き直すと高い（DQ2 の実測 2,839 µs → 開いたまま 137 µs）。
--   ★8 ms に 1 回だけ読み、間のフレームは前の値を返します。

local M = {}

--: ★bridge.lua と同じビット（⚠ `retroux/application/gamepad.py` の NES_* と揃える）
M.BITS = {
  {0x01, "up"}, {0x02, "down"}, {0x04, "left"}, {0x08, "right"},
  {0x10, "A"}, {0x20, "B"}, {0x40, "start"}, {0x80, "select"},
}

--: ★読む間隔（秒）と、古いとみなす時間（秒）
M.POLL_EVERY = 0.008
M.STALE_AFTER = 0.5

--- ★mask → `joypad.set` に渡せる表（⚠ **true だけ**。false は強制的に離す意味になる）。
function M.buttons_of(mask)
  local out, any = {}, false
  mask = tonumber(mask) or 0
  for _, bit in ipairs(M.BITS) do
    if math.floor(mask / bit[1]) % 2 == 1 then
      out[bit[2]] = true
      any = true
    end
  end
  return any and out or nil
end

--- ★読み手を作る。
-- @param opts.path   ★`work/dq3-gamepad.txt`
-- @param opts.clock  ⚠ 検査で差し替える（★既定は `os.clock`）
-- @param opts.open   ⚠ 検査で差し替える（★既定は `io.open`）
function M.new(opts)
  opts = opts or {}
  local path = opts.path
  local clock = opts.clock or os.clock
  local open = opts.open or io.open
  local R = {mask = 0, seq = nil, polled_at = nil, changed_at = nil,
             handle = nil, stale_releases = 0}

  local function close()
    local h = R.handle
    R.handle = nil
    if h ~= nil then pcall(function() h:close() end) end
  end
  R.close = close

  --- ★入力を捨てる（★セーブを読んだ直後・終わるとき）。
  function R.reset()
    R.mask = 0
    R.changed_at = nil
  end

  --- ★毎フレーム呼ぶ。戻り値は「いま押しているボタン」の表（⚠ 押していなければ nil）。
  function R.tick()
    if path == nil then return nil end
    local now = clock()
    if R.polled_at == nil or now - R.polled_at >= M.POLL_EVERY or now < R.polled_at then
      R.polled_at = now
      local h = R.handle
      if h == nil then
        h = open(path, "r")
        if h == nil then
          R.mask = 0               -- ★ファイルが無い = パッドを使っていない
          return nil
        end
        R.handle = h
      end
      local ok, body = pcall(function()
        h:seek("set", 0)
        return h:read("*a")
      end)
      if not ok or body == nil then
        close()                     -- ⚠ 差し替わった等。★次で開き直す
      else
        local seq, mask = tostring(body):match("(%d+)%s+(%d+)")
        -- ★半端に読めたときは前の値を保つ（⚠ 1 フレームの穴を作らない）
        if seq ~= nil then
          seq = tonumber(seq)
          if seq ~= R.seq then
            R.seq, R.mask, R.changed_at = seq, tonumber(mask) or 0, now
          end
        end
      end
    end
    -- ⚠⚠ seq が止まった = RetroUX が書いていない → 全部離す（★押しっぱなしを残さない）
    if R.mask ~= 0 and R.changed_at ~= nil and now - R.changed_at >= M.STALE_AFTER then
      R.mask = 0
      R.stale_releases = R.stale_releases + 1
      close()                       -- ★開き直す（⚠ 作り直したファイルを掴み損ねている可能性）
    end
    if R.mask == 0 then return nil end
    return M.buttons_of(R.mask)
  end

  return R
end

return M
