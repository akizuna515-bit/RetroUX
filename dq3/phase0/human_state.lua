-- 人がパッドの RB でセーブステートを保存する入口（RX3-0486 / 2026-10-02）。
--
-- ## ⚠⚠ なぜ `ai_state.lua` を使わないのか
--
--   ★`ai_state.lua` は **AI 用**で、人のスロット 0〜4 への書き込みを**必ず拒みます**
--   （依頼者の決めごと / PoC② §2）。⚠ そこを緩めると AI の歯止めが消えます。
--   → ★人の保存はここに分けます（⚠ `ai_state.lua` は 1 行も変えません）。
--
-- ★読み込み（LB）は既存の `load_state` の頼み（`nav_v0.lua`）を使います
--   （★止める・`HOST.loaded` を呼ぶ、が既に入っているため / ⚠ 入口を 2 つにしない）。
--
-- ## ⚠⚠ `persist` を忘れるとファイルにならない
--
--   ★DQ2 の `bridge.lua` の `_save_state` と同じ（2026-07-31 実測）:
--   `savestate.save()` だけだと FCEUX の**メモリ上のスロット**に入るだけで、
--   ⚠ `<ROM名>.fc<番号>` は変わりません（★例外も出ません）。
--
-- ## ★スロット番号
--
--   `savestate.object(n)` は n が 1〜10。★1〜9 → スロット 1〜9、**10 → スロット 0**。

local M = {}

--- ★スロット番号として正しいか（0〜9）。
function M.valid(slot)
  return type(slot) == "number" and slot == math.floor(slot) and slot >= 0 and slot <= 9
end

local function api_slot(slot)
  if slot == 0 then return 10 end
  return slot
end

--- ★保存する。⚠ 戻り値は `ok, 理由`（★例外にしない）。
function M.save(slot)
  if not M.valid(slot) then
    return false, string.format("⚠ スロット %s は範囲外（★0〜9）", tostring(slot))
  end
  if savestate == nil or savestate.object == nil or savestate.save == nil then
    return false, "⚠ この FCEUX には savestate API がありません"
  end
  local ok, err = pcall(function()
    local obj = savestate.object(api_slot(slot))
    savestate.save(obj)
    -- ⚠⚠ **これが無いとディスクに書かれない**（★2026-07-31 実測 / DQ2 と同じ）
    if savestate.persist ~= nil then savestate.persist(obj) end
  end)
  if not ok then return false, "⚠ 保存に失敗: " .. tostring(err) end
  return true, nil
end

return M
