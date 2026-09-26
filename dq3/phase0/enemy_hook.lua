-- ★★ 敵の行動を**命令そのもの**で捕まえる（Observation v2 / RX3-0383 / 2026-09-22）★★
--
-- ## ⚠⚠ なぜ毎フレーム読みをやめたのか
--
--   ★`enemy_watch.lua`（v1）は毎フレーム `$51` / `$0540` / `$0558` / `$64` を読んで
--   「いま敵が何をしているか」を**推し量って**いました。⚠ 4 回直して 4 回とも足りず、
--   ★歩留まり **41%**・⚠ 残った行の **3 分の 1 が偽**でした（`RX3-0382`）。
--
--   ⚠ 理由は 2 つとも RAM 側にありました:
--   ```text
--   ⚠⚠ `$0558` は**行動順の並べ替えの作業場**でもある（★0〜11 の「何番目か」が入る）
--   ⚠⚠ `$51` は敵の演出の間その敵を指し続けない（★1 ターンで 6〜10 フレームしか見えない）
--   ```
--
--   → ★**「行動が決まって `$0558,X` に書かれる命令」を直接押さえます。**
--
-- ## ★JP ROM で確定した 3 か所（⚠ NA disassembly を教師に、JP から再発見）
--
--   ★4 か所とも、⚠ **`JSR $893F`（行動を選ぶ）の直後**という同じ形です:
--
--   ```text
--   JSR $893F      ★行動を選ぶ（→ $4F = 行動 / $50 = 相手）
--   LDX $51 / LDA $50 / STA $054C,X / LDA $4F / **STA $0558,X**
--   ```
--
--   ```text
--   $88FD  bank 4  ROM $01090D   → RTS                     ⚠⚠ **主経路**（★実測 20/22）
--   $8AC7  bank 4  ROM $010AD7   → JSR $8B15 / JSR $B46C   ★別の入口（⚠ 実測 2/22）
--   $8AF9  bank 4  ROM $010B09   LDA $0653,X / BEQ / STA    ★同じターンの **2 回目**
--   $8B12  bank 4  ROM $010B22   LDA $065B,X / BEQ / STA    ★同じターンの **3 回目**
--   ```
--
--   ⚠⚠ **4 か所あります。** ★1 か所だけ張ると取りこぼします。
--
--   ⚠⚠ 2026-09-22 の実機で踏みました: ★はじめ `$8AC7` だけを本物だと思っていました。
--     ⚠ NA の disassembly では `$88FD` に当たるコードが **bank 10** にあり、
--     ★bank 4 だけを読んでいた私には `.bs_enemy_turn` の 1 本しか見えていませんでした。
--     → ⚠ **書き込みを PC 別に数える**まで気づけませんでした（★依頼者 §18 のおかげ）。
--
--   ⚠ 紛らわしい書き込み先（★張らない）:
--   ```text
--   $81E7  ⚠⚠ **並べ替え**（`LDA $42 / STA $0558,X / ADC #1 / CMP #$0C`）← ★偽 move の正体
--   $873A  ⚠ 通常攻撃への差し戻し（`LDA #$02`）
--   $A135 / $A17B  ⚠ 回復の作業用（`LDA #$1F`）
--   ```
--
-- ## ⚠⚠ バンク切り替えの落とし穴
--
--   ★`$8AC7` は `$8000-$BFFF` の**切り替え窓**です。⚠ 別のバンクが載っている間も
--   同じ番地で発火しえます。→ ★callback の頭で**その場の 3 バイトが `9D 58 05` か**
--   を見ます（⚠ 違えば別のバンクなので捨てる）。
--
-- ## ★採る値（⚠ 推し量らない）
--
--   ```text
--   idx   = X レジスタ      ★`STA $0558,X` の X。⚠ `$51` ではなく**これが正本**
--   move  = A レジスタ      ★これから書かれる値。⚠ `$0558` を読むと**書かれる前**
--   slot  = $0540[idx] & 7  ★敵の枠
--   ⚠ 照合 = $64（`_acting_enemy`）。★食い違ったら**捨てずに印を付けて残す**
--   ```
--
-- ## ⚠⚠ callback の中で重いことをしない（★ターボ 100 戦のため）
--
--   ★数値を表に積むだけ。⚠ `string.format` / ファイル書き込み / `print` は**しません**。
--   ★文字にするのはフレームの境目（`EnemyHook.flush`）です。

local EnemyHook = {}

--: ★★ 本物の 4 か所（⚠ JP bank 4 / 上の註）
EnemyHook.PC = {0x88FD, 0x8AC7, 0x8AF9, 0x8B12}

--: ★その場が本物か見るための 3 バイト（`STA $0558,X`）
EnemyHook.OPCODE = {0x9D, 0x58, 0x05}

--: ★RAM（⚠ `enemy_watch.lua` と同じ）
EnemyHook.ORDER = 0x0540
EnemyHook.ACTING_ENEMY = 0x0064
EnemyHook.ENEMY_BIT = 0x80
EnemyHook.ENEMY_MASK = 0x07

--: ⚠ 1 戦闘に積む上限（★暴走しても記憶を食い潰さない）
EnemyHook.MAX_EVENTS = 600

--- ★★ まっさらな観測器（⚠ 状態は全部ここ / 大域に置かない）。
function EnemyHook.new()
  return {
    events = {},              -- ★{idx, move, slot, acting, pc, frame, seq}
    battle_no = nil, turn = nil,
    seq = 0,                  -- ★そのターンの中の通し番号（⚠ 多回行動を区別する）
    wrong_bank = 0,           -- ⚠ 別のバンクで発火した回数
    slot_mismatch = 0,        -- ⚠ `$64` と食い違った回数
    dropped = 0,              -- ⚠ 上限で捨てた数
    not_enemy = 0,            -- ⚠ 敵の札でなかった回数（★味方の行動）
  }
end

--- ★★ 中身を空に戻す（⚠⚠ **入れ物は作り直さない**）。
--
--   ⚠⚠ 2026-09-22 の実機: `W2.hook = EnemyHook.new()` で作り直したところ、
--     ★`install` の closure は**古い入れ物**を掴んだままで、
--     ⚠ 1 戦目のあと**すべての観測が迷子**になりました（★`battle=0` 以外 全部 0）。
--   → ★入れ物は 1 つのまま、**中身だけ**戻します。
function EnemyHook.reset(h)
  if h == nil then return end
  h.events = {}
  h.battle_no, h.turn, h.seq = nil, nil, 0
  h.wrong_bank, h.slot_mismatch, h.dropped, h.not_enemy = 0, 0, 0, 0
end

--- ★戦闘・ターンが変わった（⚠ 通し番号を 0 に戻す）。
function EnemyHook.begin(h, battle_no, turn)
  if h == nil then return end
  if h.battle_no ~= battle_no then h.seq = 0 end
  h.battle_no, h.turn = battle_no, turn
  h.seq = 0
end

--- ★★ 命令が来た（⚠ **ここは軽くする** / 数値を積むだけ）。
--
--   `pc`    … 発火した番地
--   `reg`   … `function(name) return 値 end`（★`"a"` / `"x"`）
--   `read`  … `memory.readbyte` 相当
--   `frame` … いまのフレーム数（⚠ 鍵には使わない / 目安）
--
--   戻り値: ★積んだら `true`、⚠ 捨てたら `false`
function EnemyHook.on_exec(h, pc, reg, read, frame)
  if h == nil or reg == nil or read == nil then return false end
  -- ⚠⚠ **別のバンクが載っていないか**（★同じ番地に別の命令があることがある）
  local op = EnemyHook.OPCODE
  if read(pc) ~= op[1] or read(pc + 1) ~= op[2] or read(pc + 2) ~= op[3] then
    h.wrong_bank = h.wrong_bank + 1
    return false
  end
  local idx = reg("x")
  local move = reg("a")
  if idx == nil or move == nil then return false end
  local card = read(EnemyHook.ORDER + idx)
  if card == nil then return false end
  -- ⚠ 味方の手番（★bit7 が立っていない）は敵の行動ではない
  if card % 256 < EnemyHook.ENEMY_BIT then
    h.not_enemy = h.not_enemy + 1
    return false
  end
  local slot = (card % 256) % (EnemyHook.ENEMY_MASK + 1)
  local acting = read(EnemyHook.ACTING_ENEMY)
  -- ⚠⚠ 食い違っても**捨てません**（★印を付けて残す / 依頼者 §10）
  local mismatch = 0
  if acting ~= nil and acting % (EnemyHook.ENEMY_MASK + 1) ~= slot then
    h.slot_mismatch = h.slot_mismatch + 1
    mismatch = 1
  end
  if #h.events >= EnemyHook.MAX_EVENTS then
    h.dropped = h.dropped + 1
    return false
  end
  h.seq = h.seq + 1
  -- ★数値だけ積む（⚠ 文字にするのは `flush`）
  h.events[#h.events + 1] = {idx, move, slot, acting or -1, pc, frame or -1,
                             h.seq, h.battle_no or -1, h.turn or -1, mismatch}
  return true
end

--- ★★ 溜めた分を行にする（⚠ フレームの境目・戦闘の終わりに呼ぶ）。
--
--   戻り値: ★行の配列（⚠ 無ければ空）
function EnemyHook.flush(h, name_of)
  if h == nil or #h.events == 0 then return {} end
  local out = {}
  for i = 1, #h.events do
    local e = h.events[i]
    out[i] = string.format(
      "AI action2 battle=%d turn=%d seq=%d actor=%d enemy_slot=%d move=%d"
      .. " category=%s pc=$%04X acting=%d slot_mismatch=%d frame=%d",
      e[8], e[9], e[7], e[1], e[3], e[2],
      tostring((name_of ~= nil and name_of(e[2])) or "?"),
      e[5], e[4], e[10], e[6])
  end
  h.events = {}
  return out
end

--- ★★ 1 戦闘の締め（⚠ 捨てた数・食い違いを**必ず出す** / 0 件を「静か」と読まない）。
function EnemyHook.stats_line(h)
  if h == nil then return nil end
  return string.format(
    "AI action2_stats battle=%d wrong_bank=%d not_enemy=%d slot_mismatch=%d dropped=%d",
    h.battle_no or -1, h.wrong_bank, h.not_enemy, h.slot_mismatch, h.dropped)
end

--- ★★ FCEUX に仕掛ける（⚠ 3 か所すべて / ★前のハンドラは潰さない）。
--
--   `mem`   … `memory` 相当（★検査では作り物）
--   `emu_`  … `emu` 相当（★`framecount`）
--   戻り値: ★仕掛けた番地の数
function EnemyHook.install(h, mem, emu_)
  if h == nil or mem == nil or mem.registerexec == nil then return 0 end
  local n = 0
  for i = 1, #EnemyHook.PC do
    local pc = EnemyHook.PC[i]
    local function reg(name) return mem.getregister(name) end
    local function read(addr) return mem.readbyte(addr) end
    -- ⚠⚠ `prev` は**先に宣言**します。★`local prev = f(function() ... prev ... end)` と
    --   書くと、⚠ closure の中の `prev` は**大域**を指します（`local` は文の**あと**から有効）。
    local prev
    prev = mem.registerexec(pc, 1, function()
      local frame = emu_ ~= nil and emu_.framecount and emu_.framecount() or -1
      EnemyHook.on_exec(h, pc, reg, read, frame)
      if prev ~= nil then pcall(prev) end
    end)
    n = n + 1
  end
  return n
end

return EnemyHook
