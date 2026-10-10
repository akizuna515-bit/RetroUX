-- ★★ 戦闘の状態 ― DQ3 自身の判定を 1 か所で持つ（RX3-0166 / 2026-09-11）★★
--
-- ## ★根拠（RX3-0165 / docs/research/260911_dq3-battle-state.md）
--
--   ★DQ3 は固定バンク $C8F8 で `$32 == $FD かつ $60B7 & $20` を「戦闘中」として読んでいます。
--   ★実機 5 戦 ＋ 町・建物・預かり所・登録所・メニュー・店（スナップ 5,084 枚）で誤検出 0。
--
--   ```text
--   $32            画面の型: $FD = 戦闘 / $00 = フィールド（bank0 $86B6 で FD / $8707 で 00）
--   $60B7 bit5     戦闘の本体（bank0 $86BD で立ち、出口 bank4 $80D5 で落ちる）
--   $06F0          音のドライバの「いまの曲」×2（bank1 $85C1 / bit0 は処理中の印）
--   ```
--
-- ⚠⚠ **`$62` は戦闘中フラグではありません**（入口で種類を渡す引数 ＋ 汎用の作業バイト /
--   最初の行動の実行で FF でなくなり、にげた後は FF のまま残る）。
-- ⚠⚠ **画面の非 0 マスでも決めません**（建物の中が 200〜400 マスで「戦闘」になった）。
--
-- ## ★段階
--
--   ```text
--   NONE      戦闘ではない
--   ENTERING  曲が戦闘 / bit5 まだ          ★初期化 +37（曲の要求）〜 +78（bit5）
--   ACTIVE    bit5 / $32 = $FD / 曲が戦闘   ★戦闘の本体
--   RESULT    bit5 / $32 = $FD / 曲が戦闘でない   ★勝ったときのファンファーレ〜結果の文
--   EXITING   bit5 落ちた / $32 = $FD       ★出口から 42〜50 フレーム
--   ```
--
--   ⚠ 初期化 +0〜+37（曲を頼む前）は RAM に印が無く、NONE に見えます（★実測）。
--
-- ## ★is_in_battle
--
--   ★DQ3 自身の式（ACTIVE と RESULT）。⚠ RESULT は戦闘画面のままの結果の文なので
--     「戦闘中」に入れます（★歩き・会話・補充が勝利の文の最中に動かないように）。
--   ★ENTERING から止まりたい機能は `phase()` を見ます（`in_encounter()`）。
--
-- ⚠ ここはゲームの番地を知る唯一の場所です。★機能の側で `$32` や `$60B7` を読まないこと。

local BattleState = {}

BattleState.MODE_ADDR = 0x0032
BattleState.MODE_BATTLE = 0xFD
BattleState.FLAGS_ADDR = 0x60B7
BattleState.FLAG_BATTLE = 0x20
BattleState.TRACK_ADDR = 0x06F0
--: ★戦闘の初期化 bank0 $8693-$869D が頼む曲（`$62 == 9` なら $12）。⚠ ほかで頼むのは bank4 $B186 の $10 だけ
BattleState.BATTLE_TRACKS = {[0x10] = true, [0x12] = true}
BattleState.VICTORY_TRACK = 0x16
--: ★本体の入口 bank4 $8056 が入口の `$62`（戦闘の種類）を写す。⚠ 通常戦闘は 0（実測 5/5）
BattleState.KIND_ADDR = 0x6A6B
--: ★特殊な経路（bank4 $80E5 = $80 / $80F0 = $C0）。⚠ 通常戦闘は 0（実測 5/5）
BattleState.SPECIAL_ADDR = 0x6A63

BattleState.NONE = "NONE"
BattleState.ENTERING = "ENTERING"
BattleState.ACTIVE = "ACTIVE"
BattleState.RESULT = "RESULT"
BattleState.EXITING = "EXITING"

local function has_bit(v, bit)
  return math.floor((v or 0) / bit) % 2 == 1
end

--- ★番地の組（⚠ 既定は上の定数 / 生成物 `CFG.battle_state` が profile から上書きする）。
function BattleState.spec(cfg)
  cfg = cfg or {}
  local tracks = BattleState.BATTLE_TRACKS
  if type(cfg.battle_tracks) == "table" then
    tracks = {}
    for _, v in ipairs(cfg.battle_tracks) do tracks[v] = true end
  end
  return {mode = cfg.mode or BattleState.MODE_ADDR,
          mode_battle = cfg.mode_battle or BattleState.MODE_BATTLE,
          flags = cfg.flags or BattleState.FLAGS_ADDR,
          flag_bit = cfg.flag_bit or BattleState.FLAG_BATTLE,
          track = cfg.track or BattleState.TRACK_ADDR,
          tracks = tracks}
end

local DEFAULT_SPEC = BattleState.spec()

--- ★3 つのバイトから段階を決める（⚠ 純粋 / 検査から直接呼べる）。
function BattleState.classify(mode, flags, track_raw, spec)
  spec = spec or DEFAULT_SPEC
  local bit5 = has_bit(flags, spec.flag_bit)
  local battle_screen = mode == spec.mode_battle
  local track = math.floor((track_raw or 0) / 2)
  local music = spec.tracks[track] == true
  if bit5 and battle_screen then
    return music and BattleState.ACTIVE or BattleState.RESULT
  end
  if battle_screen then return BattleState.EXITING end
  return music and BattleState.ENTERING or BattleState.NONE
end

--- @param opts table|nil `read(addr)`（⚠ 省略時は `memory.readbyte`）/ `frame()` / `say` /
---   `cfg`（★生成物の `battle_state` = profile の番地）
function BattleState.new(opts)
  opts = opts or {}
  local spec = BattleState.spec(opts.cfg)
  local read = opts.read or function(a) return memory.readbyte(a) end
  local frame = opts.frame or function()
    local ok, f = pcall(emu.framecount)
    return ok and f or 0
  end
  local say = opts.say or function() end
  local S = {
    --: ★いまの段階（⚠ `tick()` が更新する / 読むだけの人は `phase()`）
    current = BattleState.NONE,
    --: ★NONE から出た回数（★「新しい戦闘」を見分ける）
    battle_no = 0,
    --: ★最後に NONE でなかったフレーム（★地図の絵を採る側の猶予）
    last_seen_frame = nil,
    --: ★段階が変わったフレーム
    since = 0,
    --: ★戦闘の外で最後に鳴っていた曲（★勝ったあとに戻る「場所の曲」/ ⚠ まだ見ていなければ nil）
    field_track = nil,
  }

  --- ★いまの段階（⚠ 毎回 RAM を読む。3 バイトだけ）。
  S.spec = spec

  function S.phase()
    return BattleState.classify(read(spec.mode), read(spec.flags), read(spec.track), spec)
  end

  --- ★DQ3 自身の式（$C8F8）。★ACTIVE と RESULT。
  function S.is_in_battle()
    return read(spec.mode) == spec.mode_battle and has_bit(read(spec.flags), spec.flag_bit)
  end

  --- ★遭遇してから出るまで（★歩き・街ナビ・補充はここから止まる）。
  function S.in_encounter()
    return S.phase() ~= BattleState.NONE
  end

  --- ★いまの曲の番号（★診断 / 勝利の検知）。
  function S.track()
    return math.floor(read(spec.track) / 2)
  end

  --- ⚠ 生の読み（★診断と検査のため / ⚠ 判断には `S.special()` を使う）。戻り値: 種類, 特殊, 曲。
  function S.special_raw()
    return read(BattleState.KIND_ADDR), read(BattleState.SPECIAL_ADDR), S.track()
  end

  --- ★★ ボス・イベント・特殊な戦闘の候補（★高速化しない側へ倒すためだけに使う）。
  --
  --   ⚠⚠ **1 つの戦闘につき 1 回しか決めません**（RX3-0344 / 2026-09-21）。
  --     ★戦闘の種類は入口で決まるもので、⚠ 途中で変わるものではありません。
  --
  --   ⚠ 以前は**呼ばれるたびに RAM を読み直して**いました。★依頼者のログに、
  --     同じ戦闘のうちに false → true へ変わった跡が残っています:
  --
  --     ```text
  --     [AUTO] 倒したことのある敵か: はい → Auto に入る     ★入口では false
  --     [TURBO] ON -> OFF source=DANGER（ボス・イベント戦の候補）  ⚠⚠ 1 ターン目で true
  --     ```
  --
  --     → ⚠ Auto だけ走って Turbo が切れる（★依頼者「ミミックの時に、オート（ターボなし）になる」）。
  --
  --   ⚠ この規則は `RX3-0166` の時点で **未実測**と書かれています。★どの番地が動くのかは
  --     まだ分かっていないので、⚠ **断定せずに記録**します（`S.special_drift`）。
  --
  --   ★忘れる仕掛けは `battle_no` **1 本**です（⚠ 戦闘の外で消す行は足しません）。
  --     ⚠ `tick()` が NONE → 戦闘で番号を増やすので、★次の戦闘では自然に読み直します
  --     （⚠ 2026-09-21 の壊す実験: 消す行を外しても検査が緑 = **その行は効いていなかった**）。
  function S.special()
    if S.special_no ~= S.battle_no then
      local kind, flags, track = S.special_raw()
      S.special_no = S.battle_no
      S.special_latched = kind ~= 0 or flags ~= 0 or track == 0x12
      S.special_seen = string.format("$6A6B=%02X $6A63=%02X 曲=%02X", kind, flags, track)
      S.special_drifted = false
    end
    return S.special_latched
  end

  --- ⚠⚠ 診断: 決めたあとの生の読みが食い違っていないか（★1 戦闘に 1 行だけ言う / RX3-0344）。
  --
  --   ★これは**判断には使いません**。⚠ 次の実機 run で「どの番地が動くのか」を掴むためだけです。
  --   戻り値: 食い違った最初の 1 回だけ説明の文 / ⚠ ふだんは nil。
  function S.special_drift()
    if S.special_no ~= S.battle_no or S.special_drifted then return nil end
    local kind, flags, track = S.special_raw()
    local now = kind ~= 0 or flags ~= 0 or track == 0x12
    if now == S.special_latched then return nil end
    S.special_drifted = true
    local line = string.format(
      "⚠⚠ 戦闘の種類が入口と食い違う（★入口 %s / いま %s）入口: %s → いま: $6A6B=%02X $6A63=%02X 曲=%02X",
      tostring(S.special_latched), tostring(now), tostring(S.special_seen), kind, flags, track)
    say(line)
    return line
  end

  --- ★毎フレーム 1 回（★段階の変わり目を覚える / ⚠ 呼び忘れても phase() は正しい）。
  function S.tick()
    local now = frame()
    local ph = S.phase()
    if ph ~= BattleState.NONE then S.last_seen_frame = now else S.field_track = S.track() end
    if ph ~= S.current then
      if S.current == BattleState.NONE then S.battle_no = S.battle_no + 1 end
      say(string.format("★戦闘の段階: %s → %s（$32=%02X $60B7=%02X 曲=%02X）",
        S.current, ph, read(spec.mode), read(spec.flags), S.track()))
      S.current = ph
      S.since = now
    end
    return ph
  end

  --- ★戦闘中か、終わってから `frames` 以内か（★地図の絵を採る側 / 安全側）。
  --
  --   ⚠ 出た直後はまだ CHR に敵の絵が残っているかもしれない。★少し待ってから採る。
  function S.recently(frames)
    if S.phase() ~= BattleState.NONE then return true end
    if S.last_seen_frame == nil then return false end
    local gap = frame() - S.last_seen_frame
    -- ⚠ セーブを読むとフレーム数が巻き戻る（RX3-0167）。★巻き戻ったら「最近ではない」
    return gap >= 0 and gap <= (frames or 0)
  end

  return S
end

return BattleState
