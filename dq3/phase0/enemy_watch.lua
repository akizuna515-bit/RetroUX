-- ★★ 敵が**実際に何をしたか**を記録する（RX3-0371 / 2026-09-22）★★
--
-- ## ⚠⚠ これは「予測が当たっているか」を測るためだけのものです
--
--   ★`Enemy Action Model v1` は**予測器**です。⚠ 予測器は、実測と突き合わせない限り
--   「賢くなった」かどうかが分かりません。→ ★ここで**実測側**を採ります。
--
--   ```text
--   AI predict  … 敵が動く**前**に出す（★pipeline / 1 群 1 行）
--   AI actual   … 敵が動いた**あと**に出す（★ここ / 1 行動 1 行）
--   ```
--
-- ## ★ROM の事実（⚠ JP ROM で照合済み）
--
--   ```text
--   $51        ★いま動いている人の番号（`_bs_curr_actor` / `LDX $51` が 5 か所）
--   $0540,X    ★その人の札。⚠ **bit7 が立っていれば敵**（`AND #$87 / BMI` が 1 か所）
--              ★敵の番号は下位 3bit（`AND #7`）/ 味方は下位 2bit（`AND #3`）
--   $0558,X    ★その人がいま選んだ行動（`LDA $0558,X` が 18 か所）
--   $64        ★★ いま動いている**敵の番号**（`_acting_enemy` / RX3-0378）
--   ```
--
-- ## ⚠⚠ `$0558` は「選んだ行動」だけを持っているのではありません（RX3-0378）
--
--   ★disassembly の `ram.inc` に、⚠ **こう書いてあります**:
--
--   ```text
--   byte_558: "moveTable2" - "the actually selected action"
--     ALSO: some kind of speed order sorting writes into 12 entries here.
--           **like, the turn # of each of the actors**
--   ```
--
--   ⚠⚠ つまり、★**素早さの順番を決めている間、`$0558[0..11]` には「行動」ではなく
--     「そのターンの何番目か」（0〜11）が入っています。**
--
--   ★実測（2026-09-22 / 40 件）: ⚠ **枠に無い行動は 1 つ残らず `move=0..11`** でした。
--     ⚠ ラゴンヌ（枠は `2 / 27 / 56`）に `move=10,11`（息）・`move=9`（踊り）・
--       `move=8`（仲間呼び）・`move=0`（何もしない）が付いていました。
--     → ★これは**並べ替えの途中の順番の数字**を行動として読んでいたものです。
--
--   ★歯止め: `.bs_enemy_turn`（JP bank4 `$68998`）は、⚠ **敵が動き始めるときに必ず**
--
--   ```text
--   JSR _bs_get_current_actor_number   ; = $0540[$51] & 7（★敵なら下位 3bit）
--   STA _acting_enemy                  ; = $64
--   ```
--
--   を通ります。→ ★`$64` が**いまの敵の枠と一致するときだけ**記録します。
--   ⚠ 並べ替えの途中は、`$64` に**前の行動の値**が残っています。
--
-- ## ⚠ 鍵にフレーム数を使いません
--
--   ★セーブを読むとフレーム数は**戻ります**（`RX3-0167`）。
--   → ⚠ `battle` / `turn` / `actor` の 3 つで結びつけます。
--
-- ## ⚠⚠ ダメージの割り当てについて（★正直に）
--
--   ★1 行動ごとの被害は「その行動の前後で味方の HP 合計がどれだけ減ったか」で出します。
--   ⚠ **1 行動に 1 つの被害**という前提です。★毒のダメージ・反射などが同じ隙間に
--     入れば混ざります。→ ⚠ `AI actual` は**目安**として読んでください
--     （★カテゴリの頻度は確か / ⚠ 1 行動のダメージは荒い）。

local EnemyWatch = {}

--: ★RAM の番地（⚠ JP ROM のコードで確かめた / 上の註）
EnemyWatch.CUR_ACTOR = 0x0051
EnemyWatch.ORDER = 0x0540
EnemyWatch.MOVE = 0x0558
--: ★★ いま動いている敵の番号（`_acting_enemy` / RX3-0378）。
--   ⚠ 並べ替えの途中は前の値が残るので、★枠と一致するかで見ます。
EnemyWatch.ACTING_ENEMY = 0x0064
--: ★敵の状態（RX3-0368 / ⚠ 1 体 2 バイト / bit7 = 割り当て・生死）
EnemyWatch.STATUS = 0x0530
--: ★敵の札の印（⚠ `AND #$87 / BMI`）
EnemyWatch.ENEMY_BIT = 0x80
--: ★敵の番号のマスク（⚠ `AND #7`）
EnemyWatch.ENEMY_MASK = 0x07

--: ★1 戦闘に残す行の上限（⚠ 記録でログを埋めない）
EnemyWatch.MAX_ROWS = 400

--: ★★ 行動と認めるまでに**続けて見たいフレーム数**（RX3-0379）。
--
--   ⚠ 並べ替えの途中の値は **1 フレームで消えます**。
--   ★本当の行動は、文と絵が出る間（⚠ 何十フレームも）居座ります。
--   → ★3 なら、⚠ 本物を落とす心配はまず無く、★ちらつきは確実に外せます。
EnemyWatch.STABLE_FRAMES = 3

local function byte_at(read, addr)
  local ok, got = pcall(read, addr)
  return ok and tonumber(got) or nil
end

--- ★★ まっさらな見張り（⚠ 状態は全部ここに持つ / 大域に置かない）。
function EnemyWatch.new()
  return {
    battle_no = nil, turn = nil,
    last_actor = nil, last_move = nil,
    last_hp = nil, seen_hp = nil,
    act_taken = 0, turn_taken = 0,
    rows = 0,
    -- ★★ 歯止めで外した回数（RX3-0378）。⚠⚠ **0 件を「静か」と読み違えないため**に出します
    --   （★`work/` の教訓: ⚠ 何も出ないのは「正しい」ではなく「通っていない」ことがある）。
    gated = 0,
    --: ★ちらつきで外した数（RX3-0379 / ⚠ こちらも出します）
    flicker = 0,
    pend_actor = nil, pend_move = nil, pend_n = 0,
    --: ★いま手番の敵（RX3-0381 / ⚠ `$64` の立ち上がりで掛ける掛け金）
    armed = nil,
    --: ★掛け金が掛かった回数（⚠ 0 でないのに行が 0 なら、歯止めより後ろが壊れている）
    armed_n = 0,
  }
end

--- ★★ 味方の HP の**減り**を積む（RX3-0372 / ⚠ 毎フレーム）。
--
--   ⚠⚠ 2026-09-22 の実測で、**85% の行が `damage=0`** でした。
--     ★原因は「行動が切り替わった瞬間の HP の差」で見ていたこと。
--     ⚠ ダメージは絵と文が出たあとに入るので、**次の行動が始まるまでに間に合いません**。
--   → ★毎フレーム `前 - いま` の**正の分だけ**積みます（⚠ 回復は数えない）。
local function take(w, party_hp)
  local now = tonumber(party_hp)
  if now == nil then return end
  if w.seen_hp ~= nil and now < w.seen_hp then
    local lost = w.seen_hp - now
    w.act_taken = (w.act_taken or 0) + lost
    w.turn_taken = (w.turn_taken or 0) + lost
  end
  w.seen_hp = now
end

--- ★戦闘・ターンが変わったら数え直す（⚠ 跨いで比べない）。
--   戻り値: ⚠ **締め残し**の 1 行（★前のターンの最後の行動 / 無ければ nil）
function EnemyWatch.begin(w, battle_no, turn, party_hp, name_of)
  if w == nil then return nil end
  take(w, party_hp)
  local tail = EnemyWatch.close(w, party_hp, name_of)
  -- ★前のターンの**受けた合計**（RX3-0372 / ⚠ 1 行動ごとより確か）
  local turn_line = nil
  if w.battle_no ~= nil and w.turn ~= nil and (w.turn_taken or 0) >= 0 then
    -- ⚠⚠ `gated=` は**歯止めで外した回数**（RX3-0378）。
    --   ★`rows=0` かつ `gated` が大きければ、⚠ **歯止めが行き過ぎ**です。
    -- ⚠⚠ `rows` は**そのターンに書けた行の数**（★`armed` と並べて読みます）。
    --   ★`armed>0` なのに `rows=0` なら、⚠ 歯止めより後ろが食べています。
    turn_line = string.format(
      "AI actual_turn battle=%s turn=%s damage_taken=%d gated=%d flicker=%d"
      .. " armed=%d rows=%d",
      tostring(w.battle_no), tostring(w.turn), math.floor(w.turn_taken or 0),
      math.floor(w.gated or 0), math.floor(w.flicker or 0),
      math.floor(w.armed_n or 0), math.floor(w.turn_rows or 0))
  end
  if w.battle_no ~= battle_no then w.rows = 0 end
  w.gated, w.flicker, w.armed_n, w.turn_rows = 0, 0, 0, 0
  w.pend_actor, w.pend_move, w.pend_n = nil, nil, 0
  -- ⚠ 掛け金はターンごとに外します（★前のターンの敵を引きずらない / RX3-0381）
  w.armed = nil
  w.battle_no, w.turn = battle_no, turn
  w.last_hp = tonumber(party_hp)
  w.seen_hp = tonumber(party_hp)
  w.turn_taken, w.act_taken = 0, 0
  return tail, turn_line
end

--- ★★ 1 フレーム見る。⚠ 新しい**敵の行動**が始まったときだけ 1 行返す。
--
--   `read`     … `memory.readbyte` 相当（★検査では作り物を渡す）
--   `party_hp` … いまの味方 HP の合計（⚠ 分からなければ nil）
--   `name_of`  … 行動 ID → 分類（★生成物から / ⚠ 無ければ nil）
--
--   戻り値: ログの 1 行 / `nil`
function EnemyWatch.step(w, read, party_hp, name_of)
  if w == nil or read == nil then return nil end
  take(w, party_hp)                       -- ★毎フレーム積む
  if w.rows >= EnemyWatch.MAX_ROWS then return nil end
  local idx = byte_at(read, EnemyWatch.CUR_ACTOR)
  if idx == nil then return nil end
  local card = byte_at(read, EnemyWatch.ORDER + idx)
  if card == nil then return nil end
  -- ⚠ 味方の手番は見ません（★bit7 が立っていれば敵）
  if card % 256 < EnemyWatch.ENEMY_BIT then
    w.last_actor, w.last_move = nil, nil
    w.last_hp = tonumber(party_hp) or w.last_hp
    return nil
  end
  -- ⚠⚠ **生きている敵だけ**記録します（RX3-0374 / 2026-09-22）。
  --
  --   ★`$51` は「順番を探す輪」の中で 0..b を走査します（JP bank4 `$8A60`）。
  --   ⚠ そのたびに `$0558[$51]` を読むと、**まだ動いていない / 倒した敵**の
  --     古い値まで拾います。→ ★実測が **6 倍**に膨らんでいました
  --     （⚠ 2026-09-22: ブレス枠を持たないラゴンヌに「ブレス」が付いた）。
  --
  --   ★`RX3-0368` で確定した事実を使います:
  --   ```text
  --   $0530[slot*2] bit7 … その枠に敵が**割り当てられている**
  --   $0531[slot*2] bit7 … その敵が**生きている**
  --   ```
  local slot = (card % 256) % (EnemyWatch.ENEMY_MASK + 1)
  local here = byte_at(read, EnemyWatch.STATUS + slot * 2)
  local live = byte_at(read, EnemyWatch.STATUS + slot * 2 + 1)
  if here == nil or live == nil then return nil end
  if here < 0x80 or live < 0x80 then
    -- ⚠ 居ない / 倒した敵の枠。★何も記録しません（⚠ ただし積んだ被害は消さない）
    return nil
  end
  -- ⚠⚠ **並べ替えの途中は `$0558` が「順番の数字」です**（RX3-0378 / 上の註）。
  --
  --   ★`.bs_enemy_turn` が `$64` に「いま動き始めた敵の番号」を置きます。
  --
  -- ## ⚠⚠ ただし `$64` は**手番のあいだ持ちません**（RX3-0381 / 2026-09-22）
  --
  --   ★`ram.inc` の註がすでに疑っていました:
  --   *"usually contains the index of the acting enemy. **but it must have some
  --     other use... maybe the enemy target of a player action?**"*
  --
  --   ⚠ JP bank4 で `_acting_enemy` への書き込みは **20 か所以上**（`STA` / `STX` /
  --     `STY` / `DEC`）。★狙いを決める・数えるたびに**使い回されます**。
  --
  --   ⚠⚠ 実測（2026-09-22 / 13 ターン）: 「毎フレーム一致を要求」にしたら、
  --     ★受けた被害は出ているのに **13 ターンで行動が 2 件**しか残りませんでした
  --     （⚠ `gated=` 5〜63 / `flicker=` 1〜5）。
  --     → ★`$64` が合うのは**手番の頭の短いあいだだけ**で、
  --       ⚠ そこを `RX3-0379` の「3 フレーム居座れ」が弾いていました（★歯止めどうしの衝突）。
  --
  --   → ★`$64` は **「手番が始まった」の合図**としてだけ使います（⚠ 掛け金）。
  --     ★一度その敵に掛かったら、⚠ 手番のあいだ `$64` が変わっても読み続けます。
  local acting = byte_at(read, EnemyWatch.ACTING_ENEMY)
  if acting == nil then return nil end
  if acting % (EnemyWatch.ENEMY_MASK + 1) == slot then
    if w.armed ~= idx then
      -- ★掛け金が**掛かった回数**（⚠ = そのターンに動き始めた敵の数）。
      --   ⚠⚠ これが 0 でないのに行が 0 なら、★歯止めより**後ろ**が壊れています。
      w.armed_n = (w.armed_n or 0) + 1
    end
    w.armed = idx                       -- ★この敵の手番が始まった（⚠ 掛け金を掛ける）
  end
  if w.armed ~= idx then
    w.gated = (w.gated or 0) + 1        -- ★どれだけ外したかを数える（⚠ 黙って減らさない）
    return nil
  end
  local move = byte_at(read, EnemyWatch.MOVE + idx)
  if move == nil then return nil end
  -- ★同じ人が同じ行動のままなら、まだ同じ 1 回（⚠ 毎フレーム出さない）
  if w.last_actor == idx and w.last_move == move then
    w.pend_actor, w.pend_move, w.pend_n = idx, move, EnemyWatch.STABLE_FRAMES
    return nil
  end
  -- ⚠⚠ **1 フレームだけ見えた値は行動ではありません**（RX3-0379 / 2026-09-22）。
  --
  --   ★`RX3-0378` の歯止めを入れても、⚠ **9 ターン中 8 ターンで「1 行目」が偽**でした。
  --     ⚠⚠ 理由: `$64` には**前のターンで最後に動いた敵の番号が残ります**。
  --     ★新しいターンの並べ替えで `$51` がその敵の札まで来ると、
  --       ⚠ 番号が一致してしまい、`$0558` の**順番の数字**を通してしまいます。
  --
  --   ★見分け方は**居座る長さ**です:
  --   ```text
  --   並べ替え中   ⚠ `$51` は毎フレーム動く → **1 フレームで消える**
  --   本当の行動   ★文と絵が出る間ずっと → **何十フレームも居座る**
  --   ```
  --   ⚠⚠ 「枠に有るか」では切りません（★切った後のデータで切る必要は確かめられない）。
  if w.pend_actor ~= idx or w.pend_move ~= move then
    w.pend_actor, w.pend_move, w.pend_n = idx, move, 1
    -- ⚠ **初回も数えます**（★数えないと、ちらつきだけの回が 0 に見える）
    w.flicker = (w.flicker or 0) + 1
    return nil
  end
  w.pend_n = (w.pend_n or 1) + 1
  if w.pend_n < EnemyWatch.STABLE_FRAMES then
    w.flicker = (w.flicker or 0) + 1   -- ★外した数（⚠ 黙って減らさない）
    return nil
  end
  -- ⚠⚠ **1 つ前の行動**を書き出します（★その行動の被害は「始まってから次が始まるまで」
  --   の HP の減りだからです）。⚠ 新しい行動に前の被害を付けない。
  local line = EnemyWatch.close(w, party_hp, name_of)
  w.last_actor, w.last_move = idx, move
  w.last_card = card % 256
  w.last_hp = tonumber(party_hp) or w.last_hp
  return line
end

--- ★★ いま出ている行動を締めて 1 行にする（⚠ 無ければ nil）。
--
--   ★ターンの終わり・戦闘の終わりにも呼びます（⚠ 最後の 1 回を落とさない）。
function EnemyWatch.close(w, party_hp, name_of)
  if w == nil or w.last_actor == nil or w.last_move == nil then return nil end
  -- ★積んだ減りを使う（RX3-0372 / ⚠ 前後の差だけだと間に合わない）
  take(w, party_hp)
  local hurt = math.floor(w.act_taken or 0)
  w.act_taken = 0
  local idx, move = w.last_actor, w.last_move
  w.last_actor, w.last_move = nil, nil
  w.rows = w.rows + 1
  w.turn_rows = (w.turn_rows or 0) + 1   -- ★そのターンに書けた行（⚠ `armed` と並べて読む）
  local slot = (w.last_card or 0) % (EnemyWatch.ENEMY_MASK + 1)
  return string.format(
    "AI actual battle=%s turn=%s actor=%d enemy_slot=%d move=%d category=%s damage=%s",
    tostring(w.battle_no or "?"), tostring(w.turn or "?"), idx,
    slot, move,
    tostring((name_of ~= nil and name_of(move)) or "?"),
    hurt ~= nil and string.format("%d", hurt) or "?")
end

return EnemyWatch
