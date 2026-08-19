# dq2rom — FC版ドラゴンクエストII ROM解析ツール

RetroUX 本体とは**独立した CLI ツール**です（指示書 §19-9）。
`retroux` を import せず、本体のデータも書き換えません。

- 指示書: `input/claude_code_dq2_rom_analysis_tools.md`
- **仕様検討と疑問点（回答待ち7件）**: `docs/design/rom-analysis-tools-spec.md`
- 調査ログ: `docs/rom-analysis-notes.md`

---

## 使い方

```bash
.venv\Scripts\python.exe -m dq2rom inspect --rom work\rom\DQ2_J.nes
```

```bash
.venv\Scripts\python.exe -m dq2rom monsters table --rom work\rom\DQ2_J.nes -v
```

```bash
.venv\Scripts\python.exe -m dq2rom maps table --rom work\rom\DQ2_J.nes -v
```

| コマンド | 内容 |
| --- | --- |
| `inspect` | iNES情報・ハッシュ・表の位置。`--update-profile` でプロファイルへ書き戻す |
| `monsters table` | 絵の索引表を読む（82体 / 絵38枚 / 色違い35組）＋裏取り |
| `maps table` | マップのヘッダ表を読む（109マップ） |

共通オプション: `--profile` `--game-id` `--force` `--json` `-v/--verbose`

終了コード（指示書 §15）: `0` 成功 / `1` 一般エラー / `2` ROM不一致 / `3` 形式未対応 / `4` 検証不一致

---

## 設計で守っていること

### 1. ROMアドレスをソースに直書きしない

`locator.py` が持っているのは**署名（探し方）だけ**です。実行のたびに
バイト列を探索し、**候補が2つ以上あったら選ばずに例外**を投げます。

> 過去に、確率の署名だけで敵をひも付けて1つのIDに2つの名前を割り当てた事故があります。
> 「1つ選んで進む」をやると必ず間違えます。

見つかった位置は `profiles/dq2_fc_jp.json` に書き戻します。

### 2. 探索に使っていない列で裏を取る

たとえばモンスターの索引表は **count 列だけ**で場所を決めます。
そのあと **ポインタ列**（範囲・重複・単調増加）で確かめ、
落ちたら終了コード 4 を返します。

### 3. 北米版と日本版を混同しない

読める逆アセンブルは**北米版だけ**です
（`work/dq2-disasm/src/jp/main.asm` は `.sprintf("JP UNSUPPORTED")` の2行）。

- 北米版から使うのは**アルゴリズムとデータの形**
- 北米版の**アドレスは1つも使わない**

### 4. マッパーはヘッダから読む

指示書 2.2 は「Mapper 1 (MMC1)」と書いていますが、
**指示書自身が挙げたハッシュの ROM は Mapper 2 (UNROM)** でした。
定数で持たず、毎回ヘッダから読みます。

### 5. 範囲外は必ず例外

`bitstream.py` も `ines.py` も、範囲外アクセスで黙って 0 を返しません。
黙って返すと「それらしいが全部間違っている地図」が出てきて気づけません。

---

## ROM は同梱しません

- テストは**自作の極小疑似データだけ**を使います（指示書 4.4）
- 本物の ROM を使うテストは `DQ2_ROM_PATH` があるときだけ走ります（指示書 16.2）
  （未設定なら `work/rom/DQ2_J.nes` を探し、無ければ skip）

```bash
.venv\Scripts\python.exe -m pytest tests\test_dq2rom_ines.py tests\test_dq2rom_bitstream.py tests\test_dq2rom_locator.py -q
```

---

## 実装済み / 未実装

| | |
| --- | --- |
| ✅ | iNES解析・ハッシュ・バンク↔オフセット変換（UNROM） |
| ✅ | ROMプロファイル（照合・書き戻し） |
| ✅ | ビットストリーム（MSB/LSB / 範囲チェック / 座標ビット数） |
| ✅ | evidence / confidence |
| ✅ | 表の探索と裏取り（モンスターの絵 / マップのヘッダ） |
| ⏳ | **絵の展開ルーチン `B04_8971` の移植**（これができれば38枚出る） |
| ⏳ | マップのビットストリームデコーダ（4命令） |
| ⏳ | PNG出力・コンタクトシート |

⚠ FCEUX のキャプチャ Lua は**新規に作りません**。
既存の `retroux/emulator/fceux/bridge.lua` ＋ `retroux/core/art/trim.py` が実機で動いています。

⚠ 敵ステータス・耐性・ドロップ・行動は `retroux/plugins/dq2/memory_map.yaml` に
**確定済み**です。このツールでやり直さないでください。
