-- MAP 制約つき Random Walker v0（RX3-0031 / 2026-08-31）。
--
-- ★★ これは製品の機能ではありません ★★
--   AI が実機を自律で動かし、その証跡を残すための**テストの足**です。
--
-- ## ⚠⚠ 通行可否を**前提にしない**
--
--   ★DQ3 の「どの地形が歩けるか」は、世界地図もローカルも**未検証**です
--   （`RX3-0010`）。⚠ 予測を前提にすると、外れたときに
--   「walker のバグ」と「仮説の誤り」を切り分けられません。
--
--   → ★**押してみて、座標が変わったかで決める**。
--
--       ① 方向を選ぶ（⚠ 塞がっていると覚えている方向は避ける）
--       ② 押す
--       ③ 座標が変わったか見る
--          変わらなければ「そのマスからその向きは塞がっている」と**覚える**
--
--   ⚠⚠ これなら通行可否を 1 つも知らなくても歩けます。
--   ★しかも歩いた結果が、そのまま `RX3-0010` の材料になります。
--
-- ## ★重み（PoC② §4）
--
--       未訪問     5
--       既訪問     2
--       直前の升   1     ⚠ 戻りを弱く抑える（★禁止はしない。行き止まりで詰む）
--       塞がり     0     ⚠ 実際に押して動かなかった向き
--
-- ## ⚠ 1 歩ずつ `run.jsonl` へ**追記**する
--
--   ★まとめるのは Python（`dq3/testing/evidence.py`）の仕事です。
--   ⚠ 実機の中でまとめると、落ちたときにまとめごと失われます。

local M = {}

--: ★向きと、座標の動き（⚠ 画面の上が y-1）
M.DIRS = {
  {key = "up",    dx = 0,  dy = -1},
  {key = "down",  dx = 0,  dy = 1},
  {key = "left",  dx = -1, dy = 0},
  {key = "right", dx = 1,  dy = 0},
}

--: ★重み（⚠ 実装しやすい値でよい / 指示書 §4）
M.W_NEW, M.W_SEEN, M.W_BACK = 5, 2, 1

--: ⚠ 1 歩を待つ上限（★これを超えたら「動かなかった」とみなす）
M.STEP_FRAMES = 40

--- ★升の鍵（⚠ 地図をまたぐので map も入れる）。
function M.key(at)
  return string.format("%s:%s:%s:%s", tostring(at.kind), tostring(at.map_id),
                       tostring(at.x), tostring(at.y))
end

--- ★その向きの行き先（⚠ 実際に行けるかは押してみるまで分からない）。
function M.ahead(at, dir)
  return {kind = at.kind, map_id = at.map_id, x = at.x + dir.dx, y = at.y + dir.dy}
end

--- ★★ 次に押す向きを選ぶ。⚠ 選べなければ nil。
--
-- @param at      いまの場所
-- @param seen    ★これまでに居た升（鍵 → true）
-- @param blocked ⚠ 塞がっていると分かった「升＋向き」（鍵 → true）
-- @param prev    ★直前に居た升の鍵（⚠ 無ければ nil）
-- @param rand    ★0〜1 の乱数を返すもの（⚠ 検査で差し替えられるように）
--
-- @param allow   ⚠ 省ける。`allow(at, dir)` が false の向きは**候補にしない**
--                （★境界の決めごとは呼ぶ側のもの / RX3-0049 `--boundary stay`）
-- @param weight  ⚠ 省ける。`weight(at, dir, w)` が返した重みを使う
--                （★「未検証の edge を優先」「ROM が壁と言う向きは弱く」は呼ぶ側 / RX3-0051）
function M.choose(at, seen, blocked, prev, rand, allow, weight)
  local cand, total = {}, 0
  for _, dir in ipairs(M.DIRS) do
    local bkey = M.key(at) .. "|" .. dir.key
    if not blocked[bkey] and (allow == nil or allow(at, dir)) then
      local nkey = M.key(M.ahead(at, dir))
      local w = M.W_NEW
      if prev ~= nil and nkey == prev then
        w = M.W_BACK                       -- ⚠ 戻りは弱く
      elseif seen[nkey] then
        w = M.W_SEEN
      end
      if weight ~= nil then w = weight(at, dir, w) or w end
      if w < 0 then w = 0 end
      total = total + w
      cand[#cand + 1] = {dir = dir, w = w}
    end
  end
  if total <= 0 then return nil end
  local pick = (rand or math.random)() * total
  for _, c in ipairs(cand) do
    pick = pick - c.w
    if pick <= 0 then return c.dir end
  end
  return cand[#cand].dir                   -- ⚠ 端数で漏れたとき
end

--- ★歩く人を作る。
--
-- @param opts.where   ★いまの場所を返す（{kind, map_id, x, y}）
-- @param opts.press   ★向きのキーを押す
-- @param opts.record  ★1 歩ぶんを記録する（⚠ 追記）
-- @param opts.stop    ⚠ 止まるべきなら理由を返す（★無ければ nil）
-- @param opts.rand    ★乱数（⚠ 検査で差し替える）
-- @param opts.allow   ⚠ 省ける。`allow(at, dir)` が false の向きへは歩かない
--                     （★「町から出ない」などの境界は**ここで**渡す。walker は知らない）
-- @param opts.delivered ⚠ 省ける。「直前の押しが `$16` に出たか」を返す関数。★記録に添えるだけ。
--                     ⚠⚠ 2026-09-02 実機: DQ3 は**壁にぶつかった押しも `$16` に出ない**。
--                       だから「届かなかった」と「壁」は `$16` では区別できない。
--                       ★これで壁を覚えないようにしたら、300 歩で 67 歩しか進めなくなった。
-- @param opts.input_dead ⚠ 省ける。「いま入力が死んでいる時間か」を返す関数（★読み込み直後・
--                     戦闘の後・地図の切り替え直後）。true の間の失敗は**壁と覚えない**。
function M.new(opts)
  local self = {
    where = opts.where,
    press = opts.press,
    record = opts.record or function() end,
    stop_check = opts.stop or function() return nil end,
    rand = opts.rand or math.random,
    allow = opts.allow,
    delivered = opts.delivered,
    input_dead = opts.input_dead,
    weight = opts.weight,
    max_steps = opts.max_steps or 100,
    step_frames = opts.step_frames or M.STEP_FRAMES,

    seen = {},
    blocked = {},
    prev = nil,
    steps = 0,
    ok_steps = 0,
    stopped = nil,          -- ⚠ 止まった理由
    -- ★1 歩の途中の状態
    phase = "pick",
    waited = 0,
    from = nil,
    dir = nil,
  }

  --- ★歩いた升の数（⚠ 同じ升は 1 つ）。
  function self.unique()
    local n = 0
    for _ in pairs(self.seen) do n = n + 1 end
    return n
  end

  --- ★止める（⚠ 理由を残す）。
  function self.stop(reason)
    if self.stopped == nil then self.stopped = reason end
  end

  --- ⚠ その升からその向きへは**もう行かない**と覚える（★呼ぶ側が使う）。
  --
  --   ★`--boundary stay` が、地図を出てしまった 1 歩を戻したあとに呼びます。
  function self.forbid(at, dir_key)
    self.blocked[M.key(at) .. "|" .. dir_key] = true
  end

  --- ★★ その升で覚えた「壁」を忘れる（RX3-0131 / 2026-09-08）。
  --
  --   ⚠⚠ 4 方向とも動けなかったとき、それは**壁とは限りません**。
  --     ★窓が出ていて入力が吸われていただけ、ということがあります
  --     （2026-09-08 実測: メニューが開いたままのセーブで 4 歩で boxed_in）。
  --   → ★呼ぶ側が「窓を閉じてから覚え直す」ために使います。
  function self.unblock(at)
    for _, dir in ipairs(M.DIRS) do
      self.blocked[M.key(at) .. "|" .. dir.key] = nil
    end
  end

  --- ★止まったのを取り消して、もう一度歩き出す（⚠ 呼ぶ側が理由を分かっているときだけ）。
  function self.retry()
    self.stopped = nil
    self.phase, self.from, self.dir, self.waited = "pick", nil, nil, 0
    self.retries = (self.retries or 0) + 1
  end

  --- ⚠ 押しかけの 1 歩を**記録も学習もせずに**捨てる（★戦闘で中断されたとき）。
  --
  --   ⚠⚠ 捨てないと、戦闘で動けなかった 1 歩を「壁」と覚えます（RX3-0050）。
  function self.abort_step()
    if self.phase == "pressing" then
      self.aborted = (self.aborted or 0) + 1
    end
    self.phase, self.from, self.dir, self.waited = "pick", nil, nil, 0
  end

  --- ★直前の 1 歩（⚠ 戻すときに要る）。`{from = 升, dir = 向き}` か nil。
  function self.last_step()
    if self.from == nil or self.dir == nil then return nil end
    return {from = self.from, dir = self.dir}
  end

  --- ★毎フレーム呼ぶ。⚠ 終わっていれば false。
  function self.tick()
    if self.stopped ~= nil then return false end

    local why = self.stop_check()
    if why ~= nil then self.stop(why); return false end

    local at = self.where()
    if at == nil or at.x == nil or at.y == nil then
      self.stop("state_unavailable")
      return false
    end
    self.seen[M.key(at)] = true

    if self.phase == "pick" then
      if self.steps >= self.max_steps then
        self.stop("max_steps")
        return false
      end
      local dir = M.choose(at, self.seen, self.blocked, self.prev, self.rand,
                           self.allow, self.weight)
      if dir == nil then
        -- ⚠⚠ 4 方向とも塞がっている。★閉じ込められた
        self.stop("boxed_in")
        return false
      end
      self.from, self.dir = at, dir
      self.steps = self.steps + 1
      self.waited = 0
      self.phase = "pressing"
      self.press(dir.key)
      return true
    end

    -- ★押したあと、座標が変わるのを待つ
    self.waited = self.waited + 1
    local moved = (at.x ~= self.from.x) or (at.y ~= self.from.y)
                  or (at.map_id ~= self.from.map_id) or (at.kind ~= self.from.kind)
    if moved then
      self.ok_steps = self.ok_steps + 1
      self.record({step = self.steps, ok = true, input = self.dir.key,
                   kind = at.kind, map_id = at.map_id, x = at.x, y = at.y,
                   from_x = self.from.x, from_y = self.from.y,
                   from_kind = self.from.kind, from_map_id = self.from.map_id,
                   frames = self.waited})
      self.prev = M.key(self.from)
      self.phase = "pick"
      return true
    end

    if self.waited >= self.step_frames then
      -- ⚠⚠ **押したのに動かなかった。**
      --   ★入力が生きている時間なら、その向きは塞がっていると覚える。
      --   ⚠ 入力が死んでいる時間（読み込み直後・戦闘の後・切り替え直後）は壁ではないので覚えない。
      local delivered = (self.delivered == nil) or self.delivered()
      local dead = (self.input_dead ~= nil) and self.input_dead() or false
      if not dead then
        self.blocked[M.key(self.from) .. "|" .. self.dir.key] = true
      else
        self.undelivered = (self.undelivered or 0) + 1
      end
      self.record({step = self.steps, ok = false, input = self.dir.key,
                   kind = at.kind, map_id = at.map_id, x = at.x, y = at.y,
                   from_x = self.from.x, from_y = self.from.y,
                   from_kind = self.from.kind, from_map_id = self.from.map_id,
                   frames = self.waited, delivered = delivered, input_dead = dead})
      self.phase = "pick"
    end
    return true
  end

  return self
end

return M
