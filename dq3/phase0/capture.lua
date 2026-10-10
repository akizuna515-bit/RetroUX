-- 画面を撮る（RX3-0031 / 2026-08-31）。
--
-- ## ★何で撮るか
--
--   `gui.savescreenshotas(<path>)` — ⚠ 同梱の `fceux64.exe` に**ある**
--   （★実行ファイルのバイト列で確認 / `docs/research/260831_dq3-poc1.md` F 章）。
--
--   ⚠⚠ **ただし、まだ実機で呼んだことがありません。**
--     ★だから「呼べなかった」を必ず記録に残します（黙って撮れないのが最悪）。
--
-- ## ⚠ 動画をここで作らない
--
--   ★この環境には **ffmpeg も Pillow もありません**（実測）。
--   ⚠ PNG を並べても動画にできないので、★ここは静止画だけにします。
--   動画は FCEUX の AVI（`WM_COMMAND`）か OBS。→ `RX3-0031` の別の段。
--
-- ## ⚠ リングバッファ（PoC② §11 の案 B）
--
--   ★直近 N 枚だけを持ち、⚠ 異常が出た瞬間に**残す**。
--   異常は予告なく来るので、★決め打ちの場所だけ撮ると撮り逃します。

local M = {}

--: ⚠ 何枚を「直近」として持つか（★30 秒 × 10fps ぶん）
M.RING = 300
--: ★何フレームおきに撮るか（⚠ 6 なら 10 枚/秒）
M.EVERY = 6

--- ★撮る。⚠ 戻り値は `ok, 理由`。
--
-- ⚠⚠ **撮れなかったことを黙らせない。** ★`gui.savescreenshotas` が無い版や、
--   書けない置き場のときに、⚠ 静かに何も残らないのがいちばん困ります。
function M.shot(path)
  if gui == nil or gui.savescreenshotas == nil then
    return false, "⚠ この FCEUX には gui.savescreenshotas がありません"
  end
  local ok, err = pcall(gui.savescreenshotas, path)
  if not ok then return false, "⚠ 撮れませんでした: " .. tostring(err) end
  return true, nil
end

--- ★撮る人を作る。
--
-- @param opts.dir    ★置き場（⚠ 呼ぶ側が作っておく）
-- @param opts.say    ⚠ 記録（★撮れなかったことを残す）
-- @param opts.every  ★何フレームおきか
-- @param opts.ring   ⚠ 直近を何枚持つか
function M.new(opts)
  opts = opts or {}
  local self = {
    dir = opts.dir,
    say = opts.say or function() end,
    every = opts.every or M.EVERY,
    ring = opts.ring or M.RING,
    frames = 0,
    taken = 0,
    failed = 0,
    first_error = nil,
    -- ★直近の名前（⚠ 古いものから消す）
    recent = {},
  }

  --- ★名前つきで 1 枚（⚠ start / end / error 用）。
  function self.named(name)
    local path = self.dir .. "/" .. name .. ".png"
    local ok, err = M.shot(path)
    if ok then
      self.taken = self.taken + 1
    else
      self.failed = self.failed + 1
      if self.first_error == nil then
        self.first_error = err
        self.say("⚠⚠ 画面を撮れませんでした: " .. tostring(err))
      end
    end
    return ok, path
  end

  --- ★毎フレーム呼ぶ（⚠ 間隔はこちらで見る）。
  function self.tick()
    self.frames = self.frames + 1
    if self.frames % self.every ~= 0 then return false end
    local name = string.format("f%06d", self.frames)
    local path = self.dir .. "/frames/" .. name .. ".png"
    local ok, err = M.shot(path)
    if ok then
      self.taken = self.taken + 1
      self.recent[#self.recent + 1] = path
      -- ⚠ 古いものは名前を忘れる（★消すのは後始末の仕事）
      if #self.recent > self.ring then table.remove(self.recent, 1) end
    else
      self.failed = self.failed + 1
      if self.first_error == nil then
        self.first_error = err
        self.say("⚠⚠ 画面を撮れませんでした: " .. tostring(err))
      end
    end
    return ok
  end

  --- ★いま持っている直近の枚数。
  function self.held()
    return #self.recent
  end

  --- ★記録に残すためのまとめ。
  function self.report()
    return string.format("撮った %d 枚 / ⚠ 失敗 %d 件%s",
      self.taken, self.failed,
      self.first_error and ("（" .. self.first_error .. "）") or "")
  end

  return self
end

return M
