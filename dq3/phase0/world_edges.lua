-- 世界地図の入口・出口の升（RX3-0275 / 2026-09-14）。
--
-- ## ⚠⚠ なぜ要るか
--
--   依頼者「ここのmapに◯があるが、何もない」。★場所の世界座標は、Python が state.json を読んだ
--   （⚠ 0.5 秒おき）最後の世界地図の升だった → 町へ入る 1〜2 歩手前の升・ルーラで着いた升になる
--   （★アッサラーム L12 = (85,110) / 出ると立つ升は (86,110)）。
--
-- ## ★ここがすること（⚠ 押さない / 読むだけ）
--
--   `dev.lua` の `where()` が毎フレーム呼び、世界地図の升を覚える:
--
--   ```text
--   entry  ローカルへ移る直前に居た世界地図の升（= 入口の升）  ★次に世界地図へ出るまで持つ
--   exit   世界地図へ出た直後の升（= 出口の升）              ★次にローカルへ入るまで持つ
--   ```
--
--   ⚠ セーブを読んで巻き戻ったら、どちらも捨てる（★どこから入ったか分からない）。
--   ★世界地図は kind 0（上の世界）と 2（アレフガルド）。それ以外はローカル（`dev.lua` の `where()` と同じ）。
--   ★同じフレームに何度呼ばれても変わらない（★`where()` は機能ごとに何度も呼ばれる）。

local M = {}

function M.is_world(kind)
  return kind == 0 or kind == 2
end

function M.new()
  local self = {world = nil, entry = nil, exit = nil, was_world = nil, frame = nil}

  --- ★毎フレーム 1 回以上（★`kind` = $2F / 世界地図なら x, y は $2A/$2B）。
  function self.note(kind, x, y, frame)
    if kind == nil then return end
    if frame ~= nil and self.frame ~= nil and frame < self.frame then
      self.world, self.entry, self.exit, self.was_world = nil, nil, nil, nil   -- ★セーブを読んだ
    end
    if frame ~= nil then self.frame = frame end
    local world = M.is_world(kind)
    if world then
      if x == nil or y == nil then return end
      if self.was_world == false then self.exit = {x, y} end                 -- ★出た直後の升
      self.world, self.entry = {x, y}, nil
    elseif self.was_world == true and self.world ~= nil then
      self.entry, self.exit = self.world, nil                                -- ★入る直前の升
    end
    self.was_world = world
  end

  --- ★`where()` の表へ添える（⚠ 知らなければ何も足さない）。
  function self.decorate(out)
    if out == nil or out.loc_kind == nil then return out end
    if M.is_world(out.loc_kind) then
      if self.exit ~= nil then out.exit_x, out.exit_y = self.exit[1], self.exit[2] end
    elseif self.entry ~= nil then
      out.entry_x, out.entry_y = self.entry[1], self.entry[2]
    end
    return out
  end

  return self
end

return M
