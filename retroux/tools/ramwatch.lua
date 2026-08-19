-- 実機で RAM の変化を見張る（MVP2 Phase 5 / 指示書 5.4 F「RAM Watch」）。
--
-- ★`research/probes/archived/enemyhp_probe.lua` を汎用にしたもの。あれで敵HPのアドレスを見つけた
--   やり方（戦闘前後の差分を見る）を、範囲を指定して使えるようにしてある。
--
-- ★★ 通常プレイでは動かさない ★★
--   これは**解析用の別の入口**であって、`run.lua` には組み込んでいない。
--   指示書の受入条件「通常プレイ時は解析ログを無効化できる」を、
--   設定の分岐ではなく**別のスクリプトにする**ことで満たしている。
--   分岐で持つと「切ったつもりで動いていた」が起きる。
--
-- 使い方:
--   powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Lua research\probes\archived\ramwatch_run.lua
--
--   見る範囲と出力先は research/probes/archived/ramwatch_run.lua で指定する（この下の説明を参照）。
--
-- ⚠ **観測専用。** 入力もセーブも一切しない。

local RamWatch = {}
RamWatch.__index = RamWatch

-- opts:
--   low, high  … 見る範囲（$0000-$07FF）
--   path       … 書き出す先
--   label      … アドレスに名前を付ける関数（省略可）
--   only_down  … 減った変化だけ出す（HPを追うときに使う）
function RamWatch.new(opts)
  local self = setmetatable({}, RamWatch)
  self.low = opts.low or 0x0000
  self.high = opts.high or 0x07FF
  self.only_down = opts.only_down == true
  self.label = opts.label
  self.file = io.open(opts.path or "work/ramwatch.txt", "w")
  self.prev = nil
  self.changes = 0
  -- ★上限を置く。見張りが暴走してディスクを埋めない（playbook #9）。
  self.max_changes = opts.max_changes or 5000
  self:say(string.format("=== RAM Watch $%04X-$%04X ===", self.low, self.high))
  return self
end

function RamWatch:say(text)
  if self.file then
    self.file:write(tostring(text) .. "\n")
    self.file:flush()
  end
end

function RamWatch:snapshot()
  local t = {}
  for a = self.low, self.high do t[a] = memory.readbyte(a) end
  return t
end

-- いまの値をそのまま並べて残す（区切りの目印に使う）。
function RamWatch:dump(title, stride)
  self:say("--- " .. tostring(title) .. " ---")
  stride = stride or 16
  for base = self.low, self.high, stride do
    local parts = {}
    for i = 0, stride - 1 do
      if base + i <= self.high then
        parts[#parts + 1] = string.format("%02X", memory.readbyte(base + i))
      end
    end
    self:say(string.format("  $%04X: %s", base, table.concat(parts, " ")))
  end
end

-- 前回から変わったところを書く。戻り値: 書いた件数。
function RamWatch:tick(note)
  local now = self:snapshot()
  if self.prev == nil then
    self.prev = now
    return 0
  end
  local written = 0
  for a = self.low, self.high do
    local old, new = self.prev[a], now[a]
    if old ~= new then
      local down = new < old
      if (not self.only_down) or down then
        if self.changes < self.max_changes then
          self.changes = self.changes + 1
          written = written + 1
          local name = self.label and self.label(a) or ""
          self:say(string.format("%s $%04X %-24s %3d -> %3d（差 %+d）%s",
            down and "★減" or "  増", a, name, old, new, new - old,
            note and (" " .. note) or ""))
        end
      end
      self.prev[a] = new
    end
  end
  return written
end

function RamWatch:reset()
  self.prev = nil
end

return RamWatch
