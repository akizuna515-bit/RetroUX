-- AI がセーブステートを読み書きする入口（RX3-0031 / 2026-08-31）。
--
-- ## ⚠⚠ なぜ「別の入口」なのか
--
--   ★人が GUI から使う道（`retroux/emulator/fceux/bridge.lua` の `_save_state`）は
--   **0〜9 すべてに保存できます**。⚠ それでよいのです。人のセーブなので。
--
--   ⚠ AI は違います。依頼者の決めごと（PoC② §2）:
--
--       slot 0〜4  人間用。⚠⚠ **書き込み禁止**
--       slot 5〜9  AI が自由に load / save / 上書き / 作り直し
--
--   → ★人の道を触らずに、**AI 用だけを別に作る**。
--
-- ## ⚠ 読み込みは 0〜9 すべて許す
--
--   ★禁じられているのは**書き込み**だけ。人のセーブを見るのは無害です。
--
-- ## ⚠⚠ `persist` を忘れるとファイルにならない
--
--   ★2026-07-31 に実機で踏んでいます（`bridge.lua` の註）:
--   `savestate.save()` だけだと FCEUX の**メモリ上のスロット**に入るだけで、
--   ⚠ `<ROM名>.fc<番号>` は変わりません。それなのに例外は出ません。
--
-- ## ⚠ スロット番号の対応
--
--   `savestate.object(n)` は **n が 1〜10 以外だと Lua エラー**。
--   ★番号は QWERTY 式で 1〜9 → スロット 1〜9、**10 → スロット 0**。
--   ⚠ AI は 5〜9 しか書かないので、書き込み側でこの読み替えは要りません。

local M = {}

--: ★AI が書いてよい範囲（⚠ 依頼者の決めごと）
M.AI_MIN, M.AI_MAX = 5, 9
--: ⚠ 人のもの（★読むのは自由、書くのは禁止）
M.HUMAN_MIN, M.HUMAN_MAX = 0, 4

--- ★スロット番号として正しいか。
function M.valid(slot)
  return type(slot) == "number" and slot == math.floor(slot)
     and slot >= 0 and slot <= 9
end

--- ★★ AI が**書いて**よいスロットか。
--
-- ⚠⚠ ここが唯一の判定。★呼ぶ側で `if slot >= 5` と書かないこと
--   （2 か所に書くと片方だけ古くなる）。
--- ★隔離された置き場で動いているか（⚠ `dq3/testing/sandbox.py` が立てる）。
--
--   ★そこにあるのは本番の**コピー**なので、人のスロットへ書いても誰も困りません。
--   ⚠ 立っていなければ今までどおり 5〜9 だけ（★二重の歯止め / RX3-0128）。
function M.in_sandbox()
  return os.getenv("RETROUX_SANDBOX") == "1"
end

function M.can_write(slot)
  if not M.valid(slot) then return false end
  if M.in_sandbox() then return true end
  return slot >= M.AI_MIN and slot <= M.AI_MAX
end

--- ★AI が読んでよいスロットか（⚠ 読むのは全部よい）。
function M.can_read(slot)
  return M.valid(slot)
end

--: ⚠ `savestate.object` に渡す番号（★0 は 10）
local function api_slot(slot)
  if slot == 0 then return 10 end
  return slot
end

--- ★セーブする。⚠ 戻り値は `ok, 理由`。
--
-- ⚠⚠ **0〜4 は必ず拒む。** ★例外にせず、理由を返して呼び出し側に任せる。
function M.save(slot)
  if not M.can_write(slot) then
    return false, string.format(
      "⚠⚠ AI はスロット %s へ保存できません（★書けるのは %d〜%d）",
      tostring(slot), M.AI_MIN, M.AI_MAX)
  end
  if savestate == nil or savestate.object == nil then
    return false, "⚠ この FCEUX には savestate API がありません"
  end
  local ok, err = pcall(function()
    local obj = savestate.object(api_slot(slot))
    savestate.save(obj)
    -- ⚠⚠ **これが無いとディスクに書かれない**（★2026-07-31 実測）
    if savestate.persist ~= nil then savestate.persist(obj) end
  end)
  if not ok then return false, "⚠ 保存に失敗: " .. tostring(err) end
  return true, nil
end

--- ★ロードする。⚠ 戻り値は `ok, 理由`。
function M.load(slot)
  if not M.can_read(slot) then
    return false, string.format("⚠ スロット %s は範囲外（★0〜9）", tostring(slot))
  end
  if savestate == nil or savestate.object == nil or savestate.load == nil then
    return false, "⚠ この FCEUX には savestate API がありません"
  end
  local ok, err = pcall(function()
    savestate.load(savestate.object(api_slot(slot)))
  end)
  if not ok then return false, "⚠ 読み込みに失敗: " .. tostring(err) end
  return true, nil
end

return M
