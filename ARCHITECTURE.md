# RetroUX アーキテクチャ概観

改造・機能追加をしたい人向けの「幹」の説明です。
枝葉の理由はソースコメントに濃く書いてあるので、ここでは全体の形だけを示します。

---

## プロセス構成

RetroUX は **3つのプロセス**が**ファイル経由**で会話します。

```
┌─────────────────────┐        work/command.json (GUI→Lua 単発要求)
│ RetroUX GUI          │ ───────────────────────────────┐
│ (Python / PySide6)   │                                 ▼
│  retroux/ui, core    │        work/state.json   ┌──────────────────┐
│                      │ ◀──────────────────────  │ FCEUX (fceux64)  │
│  events.jsonl を取込 │        (Lua→GUI 0.5秒毎) │  -lua run.lua    │
│  → SQLite / ログ     │ ◀──────────────────────  │  bridge.lua ほか │
└─────────────────────┘        work/events.jsonl  └──────────────────┘
          ▲                     (Lua→Python 追記)          ▲
          │                                                │
┌─────────────────────┐        work/gamepad_input.txt      │
│ セーブステート保護    │        (GUI→Lua 60Hz NESボタン) ──┘
│ (savestate_backup)   │
└─────────────────────┘
```

- **なぜファイルIPCか**: FCEUX の Lua は同梱 LuaSocket が不完全で、
  ソケット常駐はクラッシュ・保守性の問題があった。ファイルなら
  両側が独立に死ねる・後から中身を見られる（判断の記録が残る）。

## 通信ファイル（すべて `work/`）

| ファイル | 向き | 周期 | 中身 |
| --- | --- | --- | --- |
| `command.json` | GUI → Lua | 単発（Lua は 0.5 秒毎に読む） | 操作要求（まんたん・保存・倍速切替…）。`request_id` で重複実行を防ぐ |
| `state.json` | Lua → GUI | 0.5 秒毎 | パーティ・戦闘・戦況評価・地図サンプル（画面表示用） |
| `events.jsonl` | Lua → Python | 発生時に追記 | 戦闘記録・ログ行・レベルアップ等。Python が取り込み → SQLite と `retroux.log` へ |
| `gamepad_input.txt` | GUI → Lua | 押下中 60Hz / 待機中 2Hz | `<seq> <NESボタンのビットマスク>` 1行。bridge が実時間ゲートで読む |
| `generated/*.lua` | 起動時に生成 | 起動毎 | `config.yaml`＋`user_config.yaml` → Lua 定数（`generate_lua`） |

⚠ **1ファイル1書き手**が原則。両側から書くと必ず事故ります（実績あり）。

## ディレクトリの役割

| 場所 | 役割 |
| --- | --- |
| `retroux/core/` | 純ロジック（Qt・Win32・FCEUX を知らない）。設定・DB・地図・回復計画など |
| `retroux/ui/` | PySide6 の画面。⚠ Win32 は `ui/window_manager.py` だけが窓口（テストで強制） |
| `retroux/application/` | 入力・コマンドの束ね（ゲームパッド等） |
| `retroux/emulator/fceux/` | **Lua 側の本体**。`run.lua`（入口）→ `bridge.lua`（毎フレームの中枢）＋戦闘AI各モジュール |
| `retroux/plugins/dq2/` | **ゲーム知識**。`config.yaml`（振る舞いの設定）・`memory_map.yaml`（RAM/ROMアドレスと根拠。★敵の表は入っておらず、起動時に ROM から起こす → `retroux/core/enemy_tables.py`）・`dq2.lua`（読み取り関数） |
| `retroux/tools/` | 起動補助 CLI（倍率設定・絵の展開・プレイデータ退避…） |
| `dq2rom/` | ROM 解析 CLI（`python -m dq2rom --help`）。実行時に利用者の ROM から表や絵を抽出 |
| `tests/` | 3,000件超。`uv run pytest`（ROM が要るものは自動 skip） |
| `work/` | 実行時データ（DB・ログ・状態・生成物）。**消してよい**。Git 管理外 |

## 起動の流れ（`scripts/start-retroux.ps1`）

1. 多重起動チェック → 2. `generate_lua`（YAML→Lua） → 2.5 モンスター絵の初回展開
→ 3. ログ世代 → 4. セーブステート保護を起動 → 5. GUI 起動 → FCEUX 起動（`-lua run.lua`）
→ ウィンドウ整列。

## 押さえておくべき不変条件

1. **`joypad.set` を呼ぶのは `bridge.lua` の `_apply_input()` だけ。**
   入力は「claim（自動戦闘の主張）or requested（人の要求）」の優先解決を通す。
   別の場所から直接押すと入力の奪い合いになります。
2. **戦闘状態は `Bridge:step()` の in_battle 遷移が唯一の入口。**
   戦闘開始/終了のフックはここから呼ばれる（図鑑・記録・AIすべて）。
3. **層の規則はテストが守っている**（`tests/test_layer_rules.py` 等）。
   画面から ctypes を直に呼ぶ・core から Qt を触る、はテストが赤くなります。
4. **`memory_map.yaml` のアドレスには確度と根拠が書いてある。**
   新しいアドレスを足すときは推測ではなく実測を書くのがこのプロジェクトの流儀です。
5. **タイミングは2種類**: フレーム単位（Lua 側・入力/検知）と 0.5 秒単位
   （表示・記録）。1フレームで起きることを 0.5 秒側で拾おうとすると取りこぼします。

## 機能を足すときの入口

- **キー割り当て**: `config/keybindings.yaml`＋`Ctrl+K` 設定画面
- **振る舞いの設定**: `retroux/plugins/dq2/config.yaml`（ゲーム知識）と
  `user_config.example.yaml`（利用者設定）の使い分けに注意
- **パッドのボタン**: `retroux/application/gamepad.py`（純ロジック）→
  `ui/main_window.py` の `_on_gamepad_event` で配線
- **戦闘AI**: `retroux/emulator/fceux/` の `battle_*.lua` / `actor_*.lua` 群。
  エンジンは `layered`（既定）= legacy の判断＋拒否層
- **GUI 経由の新操作**: `CommandService` → `command.json` → `bridge.lua` の
  `_poll_command` にハンドラ追加

読み方に迷ったら、まずテストを見るのが早いです（テスト名が日本語で仕様を語ります）。
