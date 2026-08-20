-- DQ2 固有のゲーム状態解釈
--
-- core/ はゲーム非依存。DQ2 の知識（アドレス・状態遷移・危険判定）はすべてここに閉じる。
-- アドレスは memory_map.yaml が正であり、このファイルに直接書かない（指示書の方針）。
--
-- 特定の根拠と確度は docs/memory_map.md を参照。

local DQ2 = {}
DQ2.__index = DQ2

function DQ2.new(memory_map, config)
  local self = setmetatable({}, DQ2)
  self.map = memory_map
  self.cfg = config
  self.a = memory_map.addresses
  return self
end

-- 戦闘開始を検知できるか。
-- $016A はフィールドでも 0x01 が残るため、敵先頭IDとの複合条件を入口だけに使う。
function DQ2:battle_started()
  return memory.readbyte(self.a.enemy_instance_numbers.addr) ~= 0
     and memory.readbyte(self.a.enemy_ids.addr) ~= self.a.enemy_ids.empty
     and memory.readbyte(self.a.battle_active.addr) ~= 0
end

-- 戦闘が継続中か。敵IDは撃破済みスロットから 0xFF になるため使わない。
--
-- ⚠ battle_active($0400) は**勝利メッセージの表示中に降りる**（実測）。
-- そこだけを見ると、待ち時間そのものであるメッセージ送りが等速に戻ってしまい、
-- 仕様 DEV-4「倍速は勝利メッセージが終わるまで継続する」を満たせない。
-- そのため勝利表示メニューが出ている間も戦闘中として扱う。
function DQ2:in_battle()
  if memory.readbyte(self.a.battle_active.addr) ~= 0 then
    self._victory_hold_pos = nil
    return true
  end
  if self.cfg.speed and self.cfg.speed.include_victory_message
     and self:showing_victory() then
    -- ★★ 勝利表示の残留への締め切り（RX-0088 / 2026-08-20）★★
    --
    --   ⚠ 実機で、フィールドへ戻っても menu_id($0059) が 0x1D のまま残り、
    --     in_battle が**永久に降りない**事故が起きた（新規ゲーム・手動戦闘。
    --     以後の戦闘開始/終了/図鑑/Auto 判定が全部止まった）。
    --     ★セーブステートの RAM 解析と動画（BATTLE 表示のまま歩いている）で確認。
    --
    --   ★勝利（レベルアップ含む）メッセージの表示中、プレイヤーは**歩けない**。
    --     だから「battle_active=0 なのに位置が動いた」＝戦闘はもう終わっている。
    --     位置が動くまでは今までどおり true（DEV-4: 倍速をメッセージまで続ける）。
    local x, y = self:map_position()
    local key = (x or 0) * 256 + (y or 0)
    if self._victory_hold_pos == nil then
      self._victory_hold_pos = key
      return true
    end
    if key == self._victory_hold_pos then
      return true
    end
    self._victory_hold_pos = nil        -- 歩いた＝残留。戦闘終了として扱う
    return false
  end
  self._victory_hold_pos = nil
  return false
end

-- 勝利時の「経験値＋ゴールド」表示中か。
-- 報酬の値はこの表示中しか有効でないため、読み取りのタイミング判定に使う。
-- レベルアップ表示にも同じメニューIDが使われる点に注意。
function DQ2:showing_victory()
  local spec = self.a.menu_id
  if spec == nil then return false end
  local v = memory.readbyte(spec.addr)
  return v == spec.values.victory_1 or v == spec.values.victory_2
end

-- ★試して効かなかったこと（同じ道を辿らないために残す）:
--   「戦闘後に必ずコマンドメニューが開く」問題に対し、入力ラッチ $002F へ
--   0 を書いて残った A を消す方法を試したが**効かなかった**。
--   ラッチは確かに空になった（$002F=-）のにメニューは開いた。
--   つまりゲーム内部で1回の A が「勝利メッセージを閉じる」と
--   「フィールドのメニューを開く」の両方に使われており、
--   ラッチを消しても既に決まった動作は止まらない。
--   解決策は勝利メッセージを **B で送る**こと（config の victory_button）。
--   ゲームのRAMへ書く方法は採用していない。

-- 現在のメニュー状態（マクロの記録・再現が使う）。
function DQ2:menu_state()
  local a = self.a
  return {
    menu = a.menu_id and memory.readbyte(a.menu_id.addr) or 0,
    cx   = a.menu_cursor_x and memory.readbyte(a.menu_cursor_x.addr) or 0,
    cy   = a.menu_cursor_y and memory.readbyte(a.menu_cursor_y.addr) or 0,
  }
end

-- 指定キャラの持ち物一覧（アイテムIDの配列）。
-- **配列の添字がどうぐメニューの行番号に対応する**（実測で確認）。
function DQ2:inventory(member_index)
  local spec = self.a.inventory
  if spec == nil then return {} end
  local base = spec.addr + (member_index or 0) * spec.stride
  local out = {}
  for i = 0, spec.slots - 1 do
    out[i] = memory.readbyte(base + i)
  end
  return out
end

-- アイテムIDが持ち物の何行目にあるか。無ければ nil。
-- ★行番号ではなくIDで目標を指定するために使う。
-- 行番号で記録すると所持品が変わった時点で壊れる。
function DQ2:find_item_row(item_id, member_index)
  local inv = self:inventory(member_index)
  local spec = self.a.inventory
  for i = 0, (spec and spec.slots or 8) - 1 do
    if inv[i] == item_id then return i end
  end
  return nil
end

-- メニューの行数（$0081）。終端マーカーを持たないリストの長さに使う。
function DQ2:menu_row_count()
  local spec = self.a.menu_row_count
  if spec == nil then return 0 end
  return memory.readbyte(spec.addr)
end

-- 戦闘中、いま入力を求められているメンバー（O-2）。
--
-- 戻り値: そのメンバー（party() の要素）と添字。読めなければ nil。
--
-- ★なぜ必要か: 戦闘コマンドメニュー(0x09)の**行1は人によって中身が違う**。
--   ローレシア（MP 0）= にげる / MPを持つ人 = じゅもん。
--   誰の番か分からないまま行1を押すと**ローレシアが逃げ出す**。
--
-- ★なぜ「読めなければ nil」を返すか（値をそのまま返さない理由）:
--   フィールドでは $00A8=00 なのに $00B9=51（3人目を指す）という
--   **互いに矛盾した値**が残っていた（work/o2/verify.txt の V4）。
--   値があること≠有効（playbook #14）。そこで
--     1. 戦闘中か
--     2. $00B9 が 0x2D + 添字*0x12 と一致するか（交差検証）
--     3. その添字が加入しているメンバーを指しているか
--   の3つを通ったときだけ返す。フィールドの矛盾はこの検査で実際に弾ける。
--
-- ⚠ 未検証: 死亡・行動不能で1人飛ばされる場合に添字がどう動くか
--   （0,2 と飛ぶのか 0,1 と詰まるのか）。上の検査が通らなければ nil になり、
--   呼び出し側は手を出さない。**分からないときは動かない**を既定にしてある。
function DQ2:battle_input_member()
  local spec = self.a.battle_input_member
  if spec == nil then return nil end
  if not self:in_battle() then return nil end

  local idx = memory.readbyte(spec.addr)
  local p = self.a.party

  -- 交差検証: 状態バイトのアドレス下位1バイトと一致するか
  local ptr = self.a.battle_input_member_ptr
  if ptr ~= nil then
    local want = (p.fields.status.offset + idx * p.member_stride) % 0x100
    if memory.readbyte(ptr.addr) ~= want then return nil end
  end

  -- 添字が加入しているメンバーを指しているか
  local members = self:party()
  local m = members[idx + 1]
  if m == nil or not m.exists then return nil end

  return m, idx
end

-- いま入力待ちの人が呪文を使えるか（＝行1が「じゅもん」か）。
-- ★最大MPは「使えるか」しか教えない。「いまその人の番か」は上の添字で見る。
--   両方が揃って初めて行1を押してよい。
function DQ2:battle_input_member_can_cast()
  local m = self:battle_input_member()
  if m == nil then return false end
  local spec = self.a.party.fields.max_mp
  if spec == nil then return false end
  local max_mp = memory.readbyte(spec.offset + m.index * self.a.party.member_stride)
  return max_mp > 0
end

-- 店の品揃えリスト(0x16)を開いているか。
function DQ2:showing_shop_list()
  local spec = self.a.menu_id
  if spec == nil then return false end
  return memory.readbyte(spec.addr) == 0x16
end

-- 店の品揃え。{ [行番号] = { item = ID, price = 値段 } } を返す。
--
-- ★★ 読める条件が2つある。どちらも守らないとゴミを掴む ★★
--
-- 1. **品揃えリスト(0x16)を開いている間だけ有効。**
--    売買選択(0x18)の時点では埋まっていない（実測で確認）。
--    ここは 6502 のスタックページなので、別の場面では他の用途の値が残る。
--    当初「0x18 の時点で既に埋まっている」としていたが誤りで、
--    一度品揃えを開いた履歴のあるセーブ1件だけを見ていた。
--
-- 2. **終端マーカーは無い。行数は $0081 で決まる。**
--    ID=0 を終端とみなすと残骸を品揃えとして読む（実測では
--    5行目に ID=9A 値段=5、6行目に かわのたて 90G というゴミがあった）。
function DQ2:shop_list()
  local spec = self.a.shop_list
  if spec == nil then return {} end
  if not self:showing_shop_list() then return {} end

  local rows = self:menu_row_count()
  if rows <= 0 or rows > spec.max_rows then return {} end

  local out = {}
  for row = 0, rows - 1 do
    local a = spec.addr + row * spec.stride
    out[row] = {
      item = memory.readbyte(a),
      price = memory.readbyte(a + 1) + memory.readbyte(a + 2) * 256,
    }
  end
  return out
end

-- 店で指定アイテムが何行目にあるか。無ければ nil。
-- ★行番号ではなくIDで指定するため。店ごとに品揃えが違う。
function DQ2:find_shop_row(item_id)
  for row, entry in pairs(self:shop_list()) do
    if entry.item == item_id then return row, entry.price end
  end
  return nil, nil
end

function DQ2:gold()
  local spec = self.a.gold
  if spec == nil then return 0 end
  return memory.readbyte(spec.addr) + memory.readbyte(spec.addr + 1) * 256
end

-- 所持金で買える個数。値段が読めるので計算できる。
function DQ2:affordable_count(item_id)
  local _, price = self:find_shop_row(item_id)
  if price == nil or price <= 0 then return 0 end
  return math.floor(self:gold() / price)
end

function DQ2:item_name(item_id)
  local items = self.map.items
  if items and items[item_id] then return items[item_id] end
  return string.format("未知アイテム(0x%02X)", item_id)
end

-- カーソル位置に対応する項目名。マクロのログに人が読めるメモを残すために使う。
-- 未知のメニューでは空文字を返す（記録は続行できる）。
function DQ2:menu_item_name(state)
  local layouts = self.map.menu_layouts
  if layouts == nil then return "" end
  local layout = layouts[state.menu]
  if layout == nil then return "" end

  -- 内容が可変なメニュー（どうぐ・店）は行番号から実データを引く
  if layout.row_source == "inventory" then
    local inv = self:inventory(0)
    local id = inv[state.cy]
    if id == nil or id == 0 then return "" end
    return self:item_name(id)
  end
  if layout.row_source == "shop_list" then
    local entry = self:shop_list()[state.cy]
    if entry == nil then return "" end
    return string.format("%s(%dG)", self:item_name(entry.item), entry.price)
  end

  if layout.items == nil then return "" end
  return layout.items[state.cx .. "," .. state.cy] or ""
end

-- フィールドのコマンドメニュー（はなす/じゅもん/…）が開いているか。
-- 自動入力の最後の A 押下がフィールド復帰直後に届くと、意図せずこれが開く。
-- 開いたままだと、その後の方向キーがメニュー操作に吸われて移動できない。
function DQ2:showing_field_menu()
  local spec = self.a.menu_id
  if spec == nil then return false end
  return memory.readbyte(spec.addr) == spec.values.field_command
end

-- 勝利時の獲得経験値／ゴールド。showing_victory() が true のときだけ意味を持つ。
function DQ2:reward()
  local exp_spec, gold_spec = self.a.exp_gained, self.a.gold_gained
  if exp_spec == nil or gold_spec == nil then return nil, nil end
  return memory.readbyte(exp_spec.addr), memory.readbyte(gold_spec.addr)
end

-- 戦闘内フェーズ。単独では戦闘判定に使えない（フィールドでも 0 を取る）。
function DQ2:phase()
  local v = memory.readbyte(self.a.battle_phase.addr)
  if v == self.a.battle_phase.values.command then return "COMMAND" end
  return "MESSAGE"
end

-- 出現している敵IDの配列。空きスロット(0xFF)は含めない。
-- 非戦闘時はこの領域が別用途で使われており意味を持たないため空を返す。
-- （フィールドでそのまま読むと 0xFF 以外のゴミが8件返る）
function DQ2:enemy_ids()
  if not self:in_battle() then return {} end
  local spec = self.a.enemy_ids
  local ids = {}
  for i = 0, spec.size - 1 do
    local v = memory.readbyte(spec.addr + i)
    if v == spec.empty then break end
    ids[#ids + 1] = v
  end
  return ids
end

-- 敵IDの枠を**全部**返す（空きは nil）。添字は画面の並びと固定で対応する。
--
-- ★enemy_ids() との違い: あちらは**空きで打ち切る**。
--   「いま何と戦っているか」を知るにはそれでよいが、
--   **個体を追いかけるには使えない**。先頭の敵が倒れて 0xFF になった瞬間に
--   打ち切られ、生き残っている後ろの敵まで見えなくなるため。
--   実際、行動単位ログで敵のHP変化が1件も残らなかった原因がこれだった
--   （2026-07-26）。
function DQ2:enemy_id_slots()
  local spec = self.a.enemy_ids
  local out = {}
  for i = 0, spec.size - 1 do
    local v = memory.readbyte(spec.addr + i)
    -- ★空きは 0xFF だけではない。**ID 0 のモンスターは存在しない**ので、
    --   0 も空きとして扱う。そうしないと、まだ埋まっていない枠を
    --   「未知(0x00)」という敵として数えてしまう（テストで検出）。
    if v ~= spec.empty and v ~= 0 then out[i] = v end
  end
  return out
end

-- モンスターIDから ROM 由来のステータスを引く。無ければ nil。
-- ★出典は memory_map の monster_stats（日本版ROMから抽出）。
function DQ2:monster_stats(id)
  local t = self.map.monster_stats
  if t == nil then return nil end
  return t[id]
end

-- 出現している敵を**個体ごと**に返す（MVP2 Phase 2）。
--
-- 要素: { index, id, name, hp, status }
--
-- ★HPは16ビット（下位・上位）。1バイトだけ読むと 256 を超えたときに壊れる。
--   いまの敵は 255 以下だが、**表現できる形で読む**のが正しい。
--
-- ⚠ 最大HPは RAM に無い（ROM のステータス表にしかない）。
--   呼び出し側は「戦闘開始時のHP」を分母にすること。
--   それがプレイヤーの見ている「満タン」であり、推測の最大値ではない。
--
-- ⚠ 倒れた個体の領域は別用途へ回る。**enemy_ids が 0xFF の枠は読まない。**
function DQ2:enemy_instances()
  if not self:in_battle() then return {} end
  local spec = self.a.enemy_battle
  if spec == nil or spec.instance_fields == nil then return {} end

  local hp_off = spec.instance_fields.hp.offset
  local st_off = spec.instance_fields.status.offset
  local out = {}
  -- ★添字が動かない読み方をする（enemy_id_slots の説明を参照）
  local slots = self:enemy_id_slots()
  for i = 0, spec.instance_count - 1 do
    local id = slots[i]
    if id ~= nil then
    local base = spec.instance_base + i * spec.instance_stride
    local stats = self:monster_stats(id)
    local hp = memory.readbyte(base + hp_off)
             + memory.readbyte(base + hp_off + 1) * 256
    -- ★★ ありえない値を弾く ★★
    --
    --   倒れた個体の枠は 0xFF で埋められる。IDがまだ残っている数フレームの間に
    --   読むと HP が 65535 になり、それが「倒す直前のHP」として記録された
    --   （実際に enemy_defeated が 65525 などになった / 2026-07-26）。
    --
    --   最大HPは ROM から分かっているので、**それを超える値はこの敵のHPではない**。
    --   表に無い敵でも、ROM の最大HPは1バイトなので 255 を超えることはない。
    --   分からない値を掴んだら、その枠は**無かったことにする**（推測で埋めない）。
    local limit = (stats and stats.max_hp) or 255
    if hp <= limit then
    out[#out + 1] = {
      index  = i,
      id     = id,
      name   = self:monster_name(id),
      hp     = hp,
      -- ★最大HPは RAM に無い。ROM の表から引く（無ければ nil のまま）。
      max_hp = stats and stats.max_hp or nil,
      -- ★★★ **能力もそのまま渡す**（2026-08-07 / 依頼者の実機ログで発覚）★★★
      --
      --     [敵] キラーマシーン×1
      --     戦闘で まどうしのつえ を使います   ← ⚠⚠ 呪文が効かない敵なのに
      --
      --   ⚠⚠ ここで `max_hp` だけ抜き出して `stats` を**捨てて**いました。
      --     ★呼ぶ側（`_item_context` / `_attack_turn_plan`）は
      --       `e.stats.resist` を読むつもりで書かれており、
      --       ⚠ **受け渡しの両側が食い違って**いました。
      --     → `resist` が nil = 「効くかもしれない」として使ってしまう。
      --
      --   ⚠ 偽データでは `monster_stats` を直接渡していたので、
      --     ★**検査は全部通っていました**（実機でしか出ない食い違い）。
      stats  = stats,
      status = memory.readbyte(base + st_off),
    }
    end
    end
  end
  return out
end

-- 敵をグループにまとめる（連続する同じIDを1グループとして数える）。
-- 戦闘の敵選択メニューは種類ごとに1行なので、行番号はこのグループの位置になる。
-- 例: [18,6,6] -> リビングデッド(1体) / ホイミスライム(2体) の2グループ
-- いま居る場所のID（逆アセンブルの map_id / $31）。読めなければ nil。
--
-- ⚠⚠ **「この値は街」という判断をしてはいけない。**
--   街とフィールドの対応表は分かっていない（逆アセンブルにも無い）。
--   使えるのは「**変わったか / 同じか**」だけ。
--   値を並べて「4以上は街」のような規則を作らない（推測で列を作らない）。
--
-- ★何に使うか: 撮影ハーネスが「同じ場所に留まっていて戦闘が起きない」
--   （＝街や建物の中かもしれない）ことを見分けるため（依頼者の指摘 / 2026-07-27）。
function DQ2:map_id()
  local spec = self.a.map_id
  if spec == nil then return nil end
  return memory.readbyte(spec.addr)
end

-- 主人公の座標（マップ内のマス）。読めなければ nil, nil。
--
-- ★逆アセンブルの `map_xpos`($16) / `map_ypos`($17)。
--   10個のセーブステートで実測済み（`research/probes/archived/verify_disasm.py`）。
--
-- ★何に使うか: 「自分が歩いた所だけ」の地図（依頼者の決定 / Q3）。
--   ⚠ 完全地図を作るためではない。探索を潰さない。
function DQ2:map_position()
  local sx, sy = self.a.map_x, self.a.map_y
  if sx == nil or sy == nil then return nil, nil end
  return memory.readbyte(sx.addr), memory.readbyte(sy.addr)
end

-- ゲーム内で付けたキャラ名の**生バイト列**（16進の文字列）。
--
-- ★★ ここでは**文字にしない**（Lua に文字コード表を置かない）★★
--   表は `memory_map.yaml` の `text:` にあり、読むのは Python 側
--   （`retroux/core/text.py`）。2か所に表を持つと必ず食い違う。
--
-- 実測: $0113 から「1人4バイト + 区切り 0xFA」で3人ぶん（= 14バイト）。
function DQ2:party_name_bytes()
  local spec = self.a.party and self.a.party.names
  if spec == nil then return nil end
  local per = (spec.length or 4) + 1
  local total = per * #self.a.party.members
  local out = {}
  for i = 0, total - 1 do
    out[#out + 1] = string.format("%02X", memory.readbyte(spec.addr + i))
  end
  return table.concat(out)
end

-- いま押されている方向（"up"/"down"/"left"/"right"）。無ければ nil。
--
-- ★ゲームが**実際に読んだ**入力（`$002F`）を見る。`joypad.set` の側ではなく、
--   ゲームに届いた側を見るのが大事（B-7 の決め手になったアドレス）。
--
-- ★何に使うか: 「その方向へ進もうとして進めなかった」を観測するため
--   （移動知識ログ / `retroux/core/navigation/`）。
--   ⚠ 座標の変化だけでは「通れた」しか分からない。**通れなかった**ことは
--     入力を見ないと言えない。
--
-- ⚠ 2方向同時に押されている場合は nil を返す（どちらの結果か言えない）。
function DQ2:input_direction()
  local spec = self.a.input
  if spec == nil or spec.bits == nil then return nil end
  local value = memory.readbyte(spec.addr)
  local found = nil
  for _, name in ipairs({ "up", "down", "left", "right" }) do
    local mask = spec.bits[name]
    if mask ~= nil and value % (mask * 2) >= mask then
      if found ~= nil then return nil end   -- 同時押しは判定しない
      found = name
    end
  end
  return found
end

-- いま読み込んでいるマップのデータ位置（bank 2 の CPU アドレス）。
--
-- ★ROM のマップヘッダ表と突き合わせるための値。
--   map_id だけだと、同じ ID が別の階を指す場合に見分けられない。
function DQ2:map_data_pointer()
  local spec = self.a.map_data_pointer
  if spec == nil then return nil end
  return memory.readbyte(spec.addr) + memory.readbyte(spec.addr + 1) * 256
end

function DQ2:enemy_groups()
  local groups = {}
  for _, id in ipairs(self:enemy_ids()) do
    local last = groups[#groups]
    if last == nil or last.id ~= id then
      groups[#groups + 1] = { id = id, count = 1 }
    else
      last.count = last.count + 1
    end
  end
  return groups
end

-- 単一ビットが立っているか。
--
-- Lua 5.1 にビット演算子はない。FCEUX は AND() を提供しているとされるが、
-- **存在を確認していない関数を使うと nil 呼び出しでスクリプトごと落ちる**ため、
-- 依存のない算術で判定する（mask は単一ビット前提）。
local function has_bit(value, mask)
  return math.floor(value / mask) % 2 == 1
end

----------------------------------------------------------------------
-- 習得済みの呪文（$0618-$061B のビットマスク）
--
-- ★これが読めると「呪文リストの行番号を設定に書く」必要が無くなる。
--   行番号は**覚えると変わる**うえ**人によって違う**ので、設定に書いた数字は
--   いつか必ず古くなる。古くなった行番号を押すと別の呪文を唱える
--   （まんたんのキアリーで実際に問題になった。隣が ルーラ なら戻せない）。
--
-- ★変換の根拠は ROM。推測していない（memory_map の learned_spells を参照）:
--     戦闘(0x07) 枠k -> 列 floor(k/4), 行 k%4（固定の4行2列。空きは飛ばさない）
--     フィールド(0x14) 行 = それより前の枠で習得済みの数（詰まる）
--
--   ★2通りの数え方が同じ答えになることを**毎回確かめる**。
--     SpellLevels の習得レベルが列ごとに昇順なので、習得済みの枠は先頭から
--     連続する。だから「固定位置」と「詰める」は一致するはずで、
--     **一致しないなら前提が崩れている**（＝押してはいけない）。
--     分からないときは動かない（playbook #14 / battle_input_member と同じ方針）。
----------------------------------------------------------------------

-- 呪文ID -> memory_map の spells 定義。未知なら nil。
function DQ2:spell_info(id)
  local spells = self.map.spells
  if spells == nil then return nil end
  return spells[id]
end

function DQ2:spell_name(id)
  local info = self:spell_info(id)
  if info and info.name then return info.name end
  return string.format("未知呪文(0x%02X)", id or 0)
end

-- 唱えてはいけない呪文か。理由の文字列 / 唱えてよければ nil。
--
-- ★★ 判定を**1か所に集約する**（playbook #36「不変条件を1か所で持つ」）★★
--   mantan.lua と bridge.lua の両方が呼ぶ。呼び出し側で
--   `info.irreversible` を直接見ると、フラグを増やしたとき片方だけ直る。
--
-- ⚠⚠ Phase 6 でこれが必要になった理由:
--   P3（回復呪文）は「heal: true かつ味方を狙う」で絞っていたため、
--   危険な呪文は**構造的に候補へ入らなかった**。攻撃呪文を許すと絞りが消える。
--   戦闘呪文リストの**枠7（列1・行3）**は ROM の SpellLevels によると
--     サマルトリア LV28 -> メガンテ(0x0C) … **唱えた本人が死ぬ**
--     ムーンブルク LV25 -> パルプンテ(0x0F) … 効果がランダム
--   になる。呪文はIDで指定するので選ぶ経路自体が無いが、**二重の歯止め**として置く。
--
-- ★2つのフラグを両方見る:
--   irreversible … 「戻せない」という**事実**の記録（ルーラ）
--   never_cast   … 「選ばない」という**方針**
--   意味が違うので memory_map では両方書いてある。片方の書き忘れでも止まるように。
function DQ2:spell_denied(id)
  local info = self:spell_info(id)
  if info == nil then
    -- ★未知の呪文も拒否する。**知らないものを唱えない**
    --   （「値があること≠有効」と同じ考え方 / playbook #14）
    return string.format("memory_map に定義が無い呪文(0x%02X)", id or 0)
  end
  if info.never_cast then
    return info.never_cast_reason or "唱えない指定がある"
  end
  if info.irreversible then
    return "唱えると取り返しがつかない"
  end
  return nil
end

-- この人が残しておくべき MP（Phase 6 P5 / 依頼者の項目4・5）。
-- 戻り値: 予約するMP, 内訳の文字列（予約が無ければ 0, nil）
--
-- ★★ ここも判定を1か所に集約する ★★
--   戦闘AI（bridge.lua）と まんたん（mantan.lua）の両方が呼ぶ。
--   「まんたんのときも有効」という依頼なので、**同じ数字を使う**必要がある。
--   別々に計算すると片方だけ直って静かに食い違う（playbook #36）。
--
-- ★予約するのは「その人が**覚えている**呪文」だけ。
--   習得済みビットから見るので、覚える前は予約されず、覚えた瞬間から予約される。
--   ROM の SpellLevels（bank4.asm:9700）で確定した習得:
--     ルーラ(0x14)   … サマルトリアだけ LV10
--     リレミト(0x12) … サマルトリア LV12 / ムーンブルク LV17 の**両方**
--
-- ⚠ **位置（行番号）は見ない。** 予約に必要なのは「覚えているか」だけで、
--   どこに表示されるかは関係ない。find_spell_pos は
--   「未習得」と「2通りの数え方が食い違う」の両方で nil を返すため、
--   ここで使うと**食い違いを未習得と読み違えて予約が消える**（安全でない側に倒れる）。
--   だから learned_spells を直接見て、consistent は問わない。
function DQ2:mp_reserve(member_index)
  local cfg = self.cfg and self.cfg.mp_reserve
  if cfg == nil or cfg.enabled == false then return 0, nil end
  local wanted = cfg.spells
  if wanted == nil or #wanted == 0 then return 0, nil end

  -- フィールドの呪文リストを見る（ルーラ・リレミトはフィールド呪文）
  local learned = self:learned_spells(member_index, "field")
  if #learned == 0 then return 0, nil end

  local total, parts = 0, {}
  for _, want in ipairs(wanted) do
    local id = want.id or want
    for _, e in ipairs(learned) do
      if e.id == id then
        local info = e.info or {}
        -- ★消費MPは memory_map（ROM由来）から引く。設定に数値を書かせない。
        local mp = info.mp_field or 0
        if mp > 0 then
          total = total + mp
          parts[#parts + 1] = string.format("%s(%d)", tostring(e.name), mp)
        end
        break
      end
    end
  end
  if total == 0 then return 0, nil end
  return total, table.concat(parts, "+")
end

--- 予約MPと「最低残存MP」を合わせた、**実際に残す量**。
---
--- ★★ **足さない。大きいほうを採る**（2026-07-30 / 仕様書 5.5）★★
---   足し合わせると「ルーラのぶん + 最低残存MP」になり、
---   利用者が指定した数より多く残してしまう（設定と違う挙動）。
---
--- ⚠⚠ 2026-08-01 まで、この規則は **bridge.lua（戦闘）にしか無かった**。
---   まんたんは `mp_reserve`（ルーラ・リレミトのぶん）しか見ておらず、
---   依頼者の報告「まんたんの時、最低MP保持が効かない」になっていた。
---   ★注釈には「まんたんと同じ数字を使う」と書いてあったが、実際は違った。
---     計算をここ1か所に置き、両方から呼ぶ。
---
--- @param member_index number
--- @param floor_mp number|nil 戦術プロフィールの最低残存MP（無ければ nil）
--- @return number 残す量, string|nil 内訳
function DQ2:reserved_mp(member_index, floor_mp)
  local total, breakdown = self:mp_reserve(member_index)
  if floor_mp ~= nil and floor_mp > total then
    return floor_mp,
           string.format("最低残存MP %d（戦術プロフィール）", floor_mp)
  end
  return total, breakdown
end

-- この人がいま呪文を唱えられるか。理由の文字列 / 唱えられれば nil。
--
-- ★マホトーン（$062D の bit0 = 0x01）をかけられていると呪文が使えない。
--   いまの P3 はこれを見ていないため、呪文リストを開こうとして
--   進まず、上限（16回）まで押してから諦めていた。壊れはしないが無駄。
--
-- ⚠ 眠り（0x40）は**押しても何も起きないだけ**なので、ここでは見ない。
--   眠っている人は入力を求められない（そもそも番が来ない）。
--   見るビットを増やすほど「実測していない前提」が増えるので、必要な1つに絞る。
--
-- ⚠ 状態ビットの sleep / silence / surround は **ROM 由来だが実測前**
--   （memory_map の status_bits のコメント参照）。
--   ★だから「立っていたら止める」側にだけ使う。**立っていないことを根拠に
--     何かを進めることはしない**（外れていても被害が「唱えない」で済む）。
function DQ2:spell_blocked(member_index)
  local p = self.a.party
  local bits = p.status_bits
  if bits == nil or bits.silence == nil then return nil end
  local status = memory.readbyte(p.fields.status.offset
    + (member_index or 0) * p.member_stride)
  if has_bit(status, bits.silence) then
    return "マホトーンで呪文を封じられている"
  end
  return nil
end

-- 決定した直後に出る対象選択のメニューID。対象を聞かれない呪文は nil。
-- ★「これから押す行が本当に回復呪文か」を押す前に照合するために使う。
--   ROM の Base Target 表が根拠（memory_map の spells.target）。
local ENEMY_TARGET_MENU = 0x0A     -- 敵の対象選択（memory_map の menu_layouts）
local ALLY_TARGET_MENU  = 0x0B     -- 味方の対象選択
function DQ2:spell_target_menu(id)
  local info = self:spell_info(id)
  if info == nil then return nil end
  if info.target == 1 then return ENEMY_TARGET_MENU end
  if info.target == 2 then return ALLY_TARGET_MENU end
  return nil
end

-- メンバー番号(0始まり) -> learned_spells のキー（"samaltria" 等）。
-- ローレシアは呪文の領域を持たないため nil を返す。
function DQ2:spell_key(member_index)
  local spec = self.a.learned_spells
  if spec == nil then return nil end
  local name = self.a.party.members[(member_index or 0) + 1]
  if name == nil then return nil end
  if spec.battle[name] == nil and spec.field[name] == nil then return nil end
  return name
end

-- 習得済みビット。読めなければ nil（呪文を持たない人・未定義のリスト）。
function DQ2:learned_spell_bits(member_index, list)
  local spec = self.a.learned_spells
  if spec == nil then return nil end
  local key = self:spell_key(member_index)
  if key == nil then return nil end
  local group = spec[list]
  if group == nil or group[key] == nil then return nil end
  return memory.readbyte(group[key].addr)
end

-- 習得済み呪文の一覧。要素は
--   { id, slot, col, row, name, info, consistent }
-- consistent=false は上のコメントの「2通りの数え方が食い違った」印。
-- 呪文を持たない人・未定義のリストでは空を返す。
function DQ2:learned_spells(member_index, list)
  local spec = self.a.learned_spells
  if spec == nil then return {} end
  local key = self:spell_key(member_index)
  if key == nil then return {} end

  local bits = self:learned_spell_bits(member_index, list)
  if bits == nil then return {} end

  local table_for = spec.slot_table and spec.slot_table[key]
  local slots_def = table_for and table_for[list]
  local layout = spec.layout and spec.layout[list]
  if slots_def == nil or layout == nil then return {} end

  local n = spec.slots or 8
  local rows = layout.rows or n
  -- 列ごとに「その列で何番目か」を数える（フィールドは1列なので通し）
  local packed = {}
  local out = {}
  for k = 0, n - 1 do
    -- 枠0 が最上位ビット（ROM の rol が左回転のため）
    local mask = (spec.bit_order == "high_first") and 2 ^ (n - 1 - k) or 2 ^ k
    local def = slots_def[k + 1]
    if def ~= nil and def.id ~= nil and def.id ~= 0 and has_bit(bits, mask) then
      local col = math.floor(k / rows)
      local fixed_row = k % rows
      local packed_row = packed[col] or 0
      packed[col] = packed_row + 1
      out[#out + 1] = {
        id     = def.id,
        slot   = k,
        col    = col,
        row    = fixed_row,
        name   = self:spell_name(def.id),
        info   = self:spell_info(def.id),
        -- 固定位置と詰めた位置が一致したか
        consistent = (fixed_row == packed_row),
      }
    end
  end
  return out
end

-- 指定の呪文IDが画面のどこにあるか。
-- 戻り値: 行, 列, 項目 / 見つからなければ nil, nil, 理由の文字列
--
-- ★行番号ではなくIDで指定するための関数。持ち物の find_item_row と同じ役割。
function DQ2:find_spell_pos(spell_id, member_index, list)
  local entries = self:learned_spells(member_index, list)
  if #entries == 0 then return nil, nil, "呪文リストを読めない" end
  for _, e in ipairs(entries) do
    if e.id == spell_id then
      if not e.consistent then
        -- 前提が崩れている。位置を答えない（間違った行を押させない）
        return nil, nil, string.format(
          "%s の位置が2通りの数え方で食い違う（枠%d）", e.name, e.slot)
      end
      return e.row, e.col, e
    end
  end
  return nil, nil, "未習得"
end

-- パーティ各員の状態。
--
-- ⚠ 加入判定は状態バイト($062D+)の bit2 で行う。**max_hp では判定できない。**
--
-- 実測（research/probes/active/check_party.py、全10セーブステート）:
--   未加入メンバーの領域にも初期値が入っており、
--   ローレシア単独のセーブでも 3人分の max_hp / current_hp が 0 以外を持つ。
--     ch0 status=84 (加入+生存) HP 21/28
--     ch1 status=00 (未加入)    HP 31/31   <- max_hp/HP では加入と区別できない
--     ch2 status=00 (未加入)    HP 32/32
--
-- これを加入とみなすと、**未加入メンバーの残留HPが仲間の死亡を隠す**。
-- 例: 2人パーティでサマルトリアが死亡した場合、
--   正: 加入2人 / 生存1人 -> 1 < 2 なので危険と判定して等速に戻る
--   誤: 加入3人 / 生存2人（ムーンブルクの 32/32 を生存に数える）-> 危険と判定されない
-- つまり全滅寸前でも倍速が解除されなかった。
function DQ2:party()
  local p = self.map.addresses.party
  local bits = p.status_bits
  local out = {}
  for i = 1, #p.members do
    local base = (i - 1) * p.member_stride
    local max_hp = memory.readbyte(p.fields.max_hp.offset + base)
    local cur_hp = memory.readbyte(p.fields.current_hp.offset + base)
    local status = memory.readbyte(p.fields.status.offset + base)
    local in_party = has_bit(status, bits.in_party)
    out[i] = {
      name     = p.members[i],
      index    = i - 1,                    -- 0始まり（持ち物などの添字と揃える）
      exists   = in_party,
      max_hp   = max_hp,
      hp       = cur_hp,
      status   = status,
      poisoned = in_party and has_bit(status, bits.poison),
      alive    = in_party and has_bit(status, bits.alive) and cur_hp > 0,
    }
  end
  return out
end

-- 敵1体がこのパーティに与える1発の目安ダメージ。
--
-- ★DQ2 の通常攻撃は概ね **(攻撃力 - 守備力/2) / 2** を中心にばらつく
--   （公開されている式。ROM の計算を1バイトずつ追ってはいない）。
--   ⚠ **だから「目安」としか言えない。** 画面にもそう出すこと。
--     正確な式が要るなら ROM のダメージ計算を読む必要がある（未着手）。
--
-- ★守備力が高いと 0 になりうる。**最低1**にはしない
--   （本当に0なら0と出すのが正しい。丸めて安心させない）。
function DQ2:estimated_damage(monster_id, member_index)
  local stats = self:monster_stats(monster_id)
  if stats == nil then return nil end
  local p = self.a.party
  local dspec = p.fields.defense
  if dspec == nil then return nil end
  local defense = memory.readbyte(dspec.offset + member_index * p.member_stride)
  local d = (stats.attack - defense / 2) / 2
  if d < 0 then d = 0 end
  return math.floor(d + 0.5)
end

-- 味方1人が敵1体に与える1発の目安ダメージ（`estimated_damage` の逆向き）。
--
-- ★式は同じ **(こうげき力 - しゅび力/2) / 2**。
--   ⚠ **だから「目安」としか言えない**（公開されている近似式で、
--     ROM のダメージ計算を1バイトずつ追ってはいない）。
--   ★これを**行動の決定**に使うので、外したときの向きを意識すること:
--     過大に見積もる -> 早く次の敵へ移る -> **倒しきれずに残る**
--     過小に見積もる -> 重ねて攻撃する（無駄は残るが安全）
--   → 呼び出し側（bridge の無駄撃ち回避）に**安全側へ倒す係数**がある。
function DQ2:estimated_damage_to(member_index, monster_id)
  local stats = self:monster_stats(monster_id)
  if stats == nil then return nil end
  local p = self.a.party
  local aspec = p.fields.attack
  if aspec == nil then return nil end
  local attack = memory.readbyte(aspec.offset + member_index * p.member_stride)
  local d = (attack - (stats.defense or 0) / 2) / 2
  if d < 0 then d = 0 end
  return math.floor(d + 0.5)
end

-- 敵グループごとの「生きている個体のHPの合計」。
--
-- ★★ **敵選択メニューはグループ単位**なので、無駄撃ちの判断もグループで見る。
--   戻り値: `{ {id=..., count=..., hp=...}, ... }`（`enemy_groups()` と同じ並び）
--
-- ⚠ グループの作り方を**写さない**。`enemy_groups()` と同じ
--   「連続する同じIDをまとめる」を、ここでも枠の並び順で行う。
--   片方だけ直すと、行の番号と中身がずれて**別の敵を狙う**。
function DQ2:enemy_groups_hp()
  local slots = self:enemy_id_slots()
  local hp_by_slot = {}
  for _, e in ipairs(self:enemy_instances()) do
    hp_by_slot[e.index] = e.hp
  end

  local spec = self.a.enemy_ids
  local groups, last_id = {}, nil
  for i = 0, spec.size - 1 do
    local id = slots[i]
    if id == nil then
      -- ⚠ 空き枠でグループを切らない（`enemy_groups()` は打ち切るが、
      --   こちらは**倒れた個体の枠**を跨いで数えたい）
      last_id = nil
    else
      if last_id ~= id then
        groups[#groups + 1] = { id = id, count = 0, hp = 0 }
        last_id = id
      end
      local g = groups[#groups]
      g.count = g.count + 1
      g.hp = g.hp + (hp_by_slot[i] or 0)
    end
  end
  return groups
end

-- そのメンバーの経験値（3バイト）。
function DQ2:experience(member_index)
  local p = self.a.party
  local spec = p.fields.experience
  if spec == nil then return 0 end
  local base = spec.offset + member_index * p.member_stride
  return memory.readbyte(base)
       + memory.readbyte(base + 1) * 256
       + memory.readbyte(base + 2) * 65536
end

-- 次のレベルに必要な経験値と、あと何点か。
-- 戻り値: 次のレベル, 必要な累計, 残り / 最大レベルなら nil
--
-- ★表は ROM 由来（memory_map の exp_to_level）。人によって必要量が違う
--   （ムーンブルクは多い）ので、**必ずその人の表を引く**。
function DQ2:next_level(member_index)
  local p = self.a.party
  local name = p.members[member_index + 1]
  local table_for = self.map.exp_to_level and self.map.exp_to_level[name]
  if table_for == nil then return nil end

  local level = memory.readbyte(p.fields.level.offset
                                + member_index * p.member_stride)
  local need = table_for[level + 1]
  if need == nil then return nil end          -- 最大レベル
  local exp = self:experience(member_index)
  return level + 1, need, math.max(0, need - exp)
end

-- 加入している（=未加入の残留データを除いた）メンバーのみ。
-- まんたん等、対象選択の行数を数えるのに使う。
function DQ2:active_party()
  local out = {}
  for _, m in ipairs(self:party()) do
    if m.exists then out[#out + 1] = m end
  end
  return out
end

-- 危険状態か（DEV-5 / C-3）。
--   1. 生存者が min_alive_members 未満（例: 3人中2人が死んで1人になった）
--   2. 生存者の誰かが 現在HP <= 最大HP * hp_ratio_threshold
--   3. 誰かが毒（設定による。★眠りは**実測がまだ**なので対象外 / B-10。
--      ⚠ 2026-08-12 訂正: 「未特定のため」と書いてありましたが、
--      ビット位置は 2026-07-26 に判明しています（0x40））
--
-- 条件1には人数の下駄をはかせている。ゲーム開始直後は1人パーティのため、
-- 素朴に「生存者1人で危険」とすると常時危険になり倍速が一切効かなくなる。
-- 依頼者の意図は「死者が出て1人になった」状況なので、
-- パーティ人数が min_alive_members 以上ある場合にのみ条件1を適用する。
--
-- ★ 人数は必ず m.exists（status bit2）で数える。max_hp では数えない。
--   未加入メンバーの残留HPを生存に数えると死亡を見落とす。party() のコメント参照。
--
-- フェイルセーフ: 加入者が0人＝読み取り失敗とみなし危険側に倒す。
function DQ2:is_danger()
  local d = self.cfg.danger
  local party = self:party()

  local n_exists, n_alive = 0, 0
  for _, m in ipairs(party) do
    if m.exists then
      n_exists = n_exists + 1
      if m.alive then n_alive = n_alive + 1 end
    end
  end

  -- 誰も把握できない = 想定外。安全側に倒す。
  if n_exists == 0 then return true, "パーティ状態を読めない" end

  if n_exists >= d.min_alive_members and n_alive < d.min_alive_members then
    return true, "生存者が" .. n_alive .. "人"
  end

  for _, m in ipairs(party) do
    if m.alive then
      if m.hp <= m.max_hp * d.hp_ratio_threshold then
        return true, m.name .. " のHPが低い"
      end
      -- 毒のみ判定する。眠り／麻痺は扱わない（B-10）。
      -- ⚠ 2026-08-12 訂正: 理由を「**ビットが未特定**だから」と書いていましたが、
      --   眠りは **0x40** と判明しています（2026-07-26 / `memory_map.yaml`
      --   status_bits.sleep / 逆アセンブル bank4.asm:5077 の構造体表）。
      -- ★いま入れていない理由は **実測がまだ**だから（眠らされる場面を作れていない）。
      --   裏を取らずに入れると「危険なのに倍速のまま」か「常時危険」を招きます。
      if d.treat_status_as_danger and m.poisoned then
        return true, m.name .. " が毒"
      end
    end
  end

  return false, nil
end

-- ボス戦か。boss_monster_ids が空の間は常に false を返すが、
-- その場合は起動時に警告を出すこと（DEV-8）。
function DQ2:is_boss(ids)
  local bosses = self.cfg.boss_monster_ids
  if bosses == nil or #bosses == 0 then return false end
  for _, id in ipairs(ids) do
    for _, b in ipairs(bosses) do
      if id == b then return true end
    end
  end
  return false
end

function DQ2:monster_name(id)
  local m = self.map.monsters
  if m and m[id] then return m[id] end
  return string.format("未知(0x%02X)", id)
end

return DQ2
