-- 呪文の結果を見る（RX3-0271 / 2026-09-14 依頼者「S9,S10は提案通りでOK」）。
--
-- ## ★見るもの = ゲーム自身の耐性の判定
--
--   ```text
--   JP bank 4 $A3EF  判定の入口（A = 耐性の番号 / $64 = 相手のスロット / $49 = 呪文の番号）
--             $A40D  乱数で決めた（carry = 1 が効いた）
--             $A40E  効かない（段 3 / 比べずに CLC）
--             $A410  効いた（段 0・耐性を飛ばす分岐 / 比べずに SEC）
--   ```
--
--   ★RX3-0266 の実機（隔離した FCEUX）: 9 呪文・4,200 回の判定で、この結果と**本当の効き目**（眠り・封じ・幻の
--     書き込み / MP・素早さ・守備・HP の減り）が 1 回も食い違わなかった。
--   ⚠ 既にかかっている敵は判定の前に黙って戻る → **何も書かない**（★「効かなかった」と数えない）。
--   ⚠ 人が唱えても Auto が唱えても同じに見る（★AUTO の入り切りに関係しない）。
--
-- ## ★書く行（`work/runtime/dq3-probe/spell_watch.log` / 読むのは `dq3/ui/spell_watch.py`）
--
--   `SPELL_RESULT battle=<戦闘の番号> enemy=<敵の種類> index=<耐性の番号> spell=<呪文 / 道具は -1> ok=<0|1>`
--
-- ⚠ `registerafter` は使わない（★dev.lua の 1 つだけ）。★判定のときだけ動くので軽い。

local function clean(p) return (p:gsub(string.char(92), "/"):gsub("/$", "")) end
local root = os.getenv("RETROUX_ROOT")
-- ⚠⚠ 開発機のパスへ落ちない（RX3-0466 / 2026-09-29）
if root == nil or root == "" then
  error("RETROUX_ROOT が立っていません（★起動は DQ3.cmd から / RX3-0466）")
end
root = clean(root)
local write_root = os.getenv("RETROUX_WRITE_ROOT")
write_root = (write_root ~= nil and write_root ~= "") and clean(write_root) or root

local Core = dofile(root .. "/dq3/phase0/core.lua")
local HOST = rawget(_G, "DQ3_DEV")

local SW = {}
--: ★判定のコードの番地（JP bank 4 / ⚠ 他の bank の同じ番地を拾わないよう、入口の 3 バイトで確かめる）
SW.ENTRY, SW.RNG, SW.FAIL, SW.PASS = 0xA3EF, 0xA40D, 0xA40E, 0xA410
SW.SIGNATURE = {0x85, 0x65, 0xAD}                  --: ★`STA $65 / LDA $6A6B`
--: ★戦闘の RAM（★profile の battle_enemies と同じ / RX3-0268）
SW.TARGET, SW.SPELL, SW.ACTION = 0x64, 0x49, 0x0567
SW.STATUS, SW.GROUP_IDS = 0x0530, 0x07B9

local LOG = Core.open_log(write_root .. "/work/runtime/dq3-probe/spell_watch.log", "呪文の結果の記録")
local function write(line)
  if LOG == nil then return end
  local ok = pcall(function() LOG:write(line .. "\n"); LOG:flush() end)
  if not ok then LOG = nil end                      -- ⚠ 一度でも駄目なら、以後は書かない
end

local function bank4()
  for k, b in ipairs(SW.SIGNATURE) do
    if memory.readbyte(SW.ENTRY + k - 1) ~= b then return false end
  end
  return true
end

local function battle_no()
  local b = HOST ~= nil and HOST.battle or nil
  return (type(b) == "table" and tonumber(b.battle_no)) or 0
end

local cur = nil

--- ★判定の入口: 誰に・どの耐性で・何の呪文か（★群は状態の 1 バイト目の bit3-2 / RX3-0268）
function SW.on_entry()
  if not bank4() then return end
  local slot = memory.readbyte(SW.TARGET) % 8
  local group = math.floor(memory.readbyte(SW.STATUS + 2 * slot) / 4) % 4
  --: ★$0567 bit7 = いまの行動は呪文（★道具の効き目は bit7 が消える / RX3-0266）
  local is_spell = memory.readbyte(SW.ACTION) >= 0x80
  cur = {index = memory.getregister("a") or -1, enemy = memory.readbyte(SW.GROUP_IDS + group),
         spell = is_spell and memory.readbyte(SW.SPELL) or -1}
end

--- ★判定の出口（★ok = 1 が効いた）
function SW.finish(ok)
  if cur == nil or not bank4() then return end
  write(string.format("SPELL_RESULT battle=%d enemy=%d index=%d spell=%d ok=%d",
                      battle_no(), cur.enemy, cur.index, cur.spell, ok))
  cur = nil
end

local hooked = pcall(function()
  memory.registerexec(SW.ENTRY, 1, SW.on_entry)
  memory.registerexec(SW.RNG, 1, function() SW.finish((memory.getregister("p") or 0) % 2) end)
  memory.registerexec(SW.FAIL, 1, function() SW.finish(0) end)
  memory.registerexec(SW.PASS, 1, function() SW.finish(1) end)
end)
if HOST ~= nil and HOST.say ~= nil then
  HOST.say("★呪文の結果を見る（耐性の判定 $A3EF）: " .. (hooked and "見張りを置いた" or "⚠ 置けなかった"))
end
if HOST ~= nil then HOST.spell_watch = SW end
return SW
