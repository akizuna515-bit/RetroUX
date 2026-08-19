-- 任意倍率のエミュレーション速度を作る自前スロットル（DEV-2 / D-2）
--
-- なぜ必要か:
--   FCEUX の Lua には倍率指定が存在しない。emu.speedmode() が受け付けるのは
--   "normal" / "nothrottle" / "turbo" / "maximum" の4値のみで、
--   「4倍速」を直接指定する手段がない。
--   そこで maximum（上限なし）で走らせ、os.clock() を見て目標フレームレートに
--   合わせて待つことで、任意の倍率を作り出す。
--
-- ⚠⚠ 重要（2026-07-22 実機検証の結果）:
--   自前スロットル（mode="throttled"）は **実際には遊べない**。既定では使わない。
--
--   フレームレートの実測では 4.00 倍ちょうどを達成できていたが、
--   ビジーウェイト中は FCEUX の描画・音声・入力処理がすべて止まるため、
--   利用者から見ると次の状態になる:
--     ・画面が真っ暗になる
--     ・音楽がノイズになる（音声バッファが途切れる）
--     ・入力が処理されず戦闘が進まない（未解決だった B-7 の原因と考えられる）
--     ・FCEUX の表示は EMULATION SPEED 6400% になる
--
--   **fps が出ていることと、遊べることは別物だった。**
--   既定は mode="turbo"（FCEUX 標準の早送り）にしてある。倍率は指定できないが、
--   描画・音声・入力を FCEUX 自身が正しく扱う。
--
-- ⚠ 安全設計（2026-07-22 に実機でハングしたため追加）:
--   待機はビジーウェイトであり、この中では emu.frameadvance() が呼ばれない。
--   すなわち **ここを抜けられないとエミュレータごと停止する**。
--   実際に、フィールドに戻った後もフレームカウンタが止まりCPUが98%という
--   デッドロックが発生した（os.clock() 単体の挙動は正常だったため原因は未特定）。
--
--   原因が特定できていなくても、無限に回りうるループを残してはいけない。
--   そこで以下の三重の安全弁を設けている。
--     1. 回転数の上限（時計に依存しないため、時計が壊れても必ず抜ける）
--     2. os.time() による粗い壁時計の上限（os.clock() が壊れた場合の保険）
--     3. 安全弁が連続して作動したらスロットルを諦めて等速へ落とす
--
-- 既知の制約:
--   待機中は FCEUX のメッセージ処理が止まるため、倍速中は入力の取りこぼしや
--   ウィンドウ操作の反応低下が起こりうる。MVP1 では許容する。

local Throttle = {}
Throttle.__index = Throttle

local BASE_FPS = 60.0

-- 1フレーム分の待機で許す最大回転数。
-- 実測では 0.2 秒の待機で約570万回転だったので、
-- 4倍速の1フレーム分(約4.2ms)なら12万回転程度。20倍の余裕を持たせる。
local MAX_SPINS_PER_FRAME = 2500000

-- os.clock() が壊れた場合の保険。os.time() は1秒分解能なので粗い判定にしか使えない。
local MAX_WALL_SECONDS = 2

-- 安全弁がこの回数連続で作動したら、スロットル自体を諦める。
local BAILOUT_LIMIT = 10

function Throttle.new(opts)
  opts = opts or {}
  return setmetatable({
    mode          = opts.mode or "turbo",
    multiplier    = 1.0,
    deadline      = nil,
    frames        = 0,
    started_at    = nil,
    measured_fps  = nil,
    -- 安全弁
    guard_trips   = 0,      -- 安全弁が連続作動した回数
    disabled      = false,  -- スロットルを諦めたか
    on_guard      = opts.on_guard,  -- 安全弁作動時の通知（ログ用）
  }, Throttle)
end

function Throttle:set(multiplier)
  if multiplier == self.multiplier then return end

  self:_finish_measurement()
  self.multiplier = multiplier

  if multiplier <= 1.0 or self.disabled then
    emu.speedmode("normal")
    self.deadline = nil
  elseif self.mode == "turbo" then
    -- FCEUX 標準の早送り。倍率は指定できないが、描画・音声・入力を
    -- FCEUX 自身が正しく扱うため、実際に遊べる。
    emu.speedmode("turbo")
    self.deadline = nil
  else
    -- 自前スロットル（mode = "throttled"）。⚠ 下の警告を参照。
    emu.speedmode("maximum")
    self.deadline = os.clock()
  end

  self.frames = 0
  self.started_at = os.clock()
end

function Throttle:measured_multiplier()
  if self.measured_fps == nil then return nil end
  return self.measured_fps / BASE_FPS
end

-- 進行中の区間の実測倍率を、区間を終わらせずに取得する。
--
-- measured_multiplier() は set() の時点で確定した「直前の区間」の値を返すため、
-- 戦闘終了イベントの時点で読むと1区間ぶん古い値になる（実測でこの遅れを確認:
-- 1戦目が 1.0、危険状態で中断された戦闘は中断前の値を報告していた）。
-- 戦闘ログの speed_applied は「削減できた待ち時間」の集計に使うため、
-- 進行中の区間をその場で計測する必要がある。
function Throttle:sample()
  self:_finish_measurement()
  return self:measured_multiplier()
end

function Throttle:_finish_measurement()
  if self.started_at == nil or self.frames < 30 then return end
  local elapsed = os.clock() - self.started_at
  if elapsed > 0 then
    self.measured_fps = self.frames / elapsed
  end
end

-- スロットルを諦めて等速に落とす。原因不明のハングよりは遅い方がまし。
function Throttle:_bail_out(reason)
  self.disabled = true
  self.deadline = nil
  self.multiplier = 1.0
  emu.speedmode("normal")
  if self.on_guard then
    self.on_guard("スロットルを無効化しました（等速で継続します）: " .. reason)
  end
end

-- 毎フレーム、emu.frameadvance() の直後に呼ぶ。
function Throttle:tick()
  self.frames = self.frames + 1

  if self.deadline == nil then return end

  local budget = 1.0 / (BASE_FPS * self.multiplier)
  self.deadline = self.deadline + budget

  local now = os.clock()
  if now > self.deadline + 0.5 then
    -- 大きく遅延した場合は追いつこうとせず基準を引き直す。
    self.deadline = now
    self.guard_trips = 0
    return
  end

  -- ビジーウェイト。**必ず有限回で抜けること。**
  local spins = 0
  local wall_start = os.time()
  local tripped = nil
  while os.clock() < self.deadline do
    spins = spins + 1
    if spins > MAX_SPINS_PER_FRAME then
      tripped = string.format("回転数が上限(%d)に達しました", MAX_SPINS_PER_FRAME)
      break
    end
    -- os.clock() が壊れていても、こちらで必ず抜けられるようにする
    if spins % 100000 == 0 and (os.time() - wall_start) >= MAX_WALL_SECONDS then
      tripped = string.format("1フレームの待機が%d秒を超えました", MAX_WALL_SECONDS)
      break
    end
  end

  if tripped then
    self.deadline = os.clock()
    self.guard_trips = self.guard_trips + 1
    if self.on_guard then
      self.on_guard(string.format("スロットルの安全弁が作動 (%d/%d): %s",
                                  self.guard_trips, BAILOUT_LIMIT, tripped))
    end
    if self.guard_trips >= BAILOUT_LIMIT then
      self:_bail_out("安全弁が連続して作動したため")
    end
  else
    self.guard_trips = 0
  end
end

return Throttle
