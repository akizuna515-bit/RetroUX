# RetroUX

**RetroUX** は、ファミコン版『ドラゴンクエストII』を FCEUX 上で自動プレイ補助する
デスクトップアプリです（Windows / Python + PySide6 + FCEUX の Lua 連携）。

戦闘の自動化（バッチリがんばれ相当）、まんたん（HP/MP 回復）、倍速、
見た地図の可視化、XBOX ゲームパッド対応などを備えます。

> ⚠ **これは補助ツールです。** ゲーム本体（ROM）もエミュレータ（FCEUX）も
> **同梱していません**。ご自身で用意してください（下記）。

---

## ⚠ はじめに（法律・権利）

- **本ソフトは非公式のファンツールです。** 任天堂株式会社、株式会社スクウェア・
  エニックス、その他の権利者とは**一切関係がなく、承認・提携もありません**。
  『ドラゴンクエスト』は各権利者の商標・著作物です。
- **ROM は含まれていません。** 正規に所有する『ドラゴンクエストII』(FC/日本版) の
  ROM をご自身で用意してください。ROM の入手・配布は各自の責任と法令に従ってください。
- **FCEUX は含まれていません。** 公式サイト等から入手してください（Lua 対応版）。
- 本ソフトはゲームの内容物を含みません。解析情報は相互運用のための最小限です。
- 本ソフト（RetroUX のソースコード）は MIT ライセンスです（`LICENSE` 参照）。
  ★ライセンスが及ぶのは RetroUX のコードだけで、ゲーム側の権利には及びません。

---

## 必要なもの

- Windows 10 / 11
- **FCEUX 2.6.6（win64）**で動作確認しています（Lua が動く版）。
  入手: 公式 GitHub Releases → <https://github.com/TASEmulators/fceux/releases/tag/v2.6.6>
  （他のバージョンでも動く可能性はありますが、未確認です）
  ⚠ **exe 単体では動きません。** RetroUX は Lua で制御するため、**`lua5.1.dll` が必須**です。
  配布 zip（`fceux-2.6.6-win64.zip`）を**丸ごと展開**してください（`fceux64.exe` /
  `lua5.1.dll` / `lua51.dll` / `7z_64.dll` / `auxlib.lua` などが揃った状態）。
- 正規に所有する DQ2(FC/JP) の ROM ファイル
- Python 3.12 と [uv](https://docs.astral.sh/uv/)
- （任意）XInput 対応のコントローラ（XBOX 系）

---

## セットアップ

```powershell
# 1. 取得
git clone https://github.com/akizuna515-bit/RetroUX.git
cd RetroUX

# 2. 依存をそろえる
uv sync

# 3. FCEUX を置く（fceux-2.6.6-win64.zip を丸ごと展開）
#    ★exe だけでは不可。lua5.1.dll などの DLL も要る。
#    tools\fceux\ の中に fceux64.exe と lua5.1.dll が揃うように展開する
#    → 例: tools\fceux\fceux64.exe / tools\fceux\lua5.1.dll

# 4. ROM を置く（正規に所有するもの）
#    ★ファイル名を DQ2_J.nes にリネームし、work\rom\ に置く
#      → 最終的に work\rom\DQ2_J.nes になること
#    （別名・別の場所にしたい場合は user_config.yaml の paths.rom を変更）

# 5. 設定（任意。★user_config.yaml が無くても既定値で動きます）
#    カスタムしたいときだけ、雛形をコピーして編集:
#      copy user_config.example.yaml user_config.yaml
#    例: emulator.window_scale（映像倍率。既定 2 = 2倍。1 で等倍）
#        gamepad.swap_ab（A/B 入れ替え。既定 true = ファミコン準拠）
#        shutdown.save_slot（保存/読込スロット。既定 1）

# 6. 設定から Lua を生成する
uv run python -m retroux.core.config.generate_lua
```

---

## 起動

```text
RetroUX.vbs をダブルクリック
```

コンソールを見ながら起動したいときは:

```text
Start-RetroUX-Console.cmd
```

起動すると、設定の反映・世代バックアップの開始・GUI と FCEUX の起動・
ウィンドウ整列まで自動で行います。
★初回起動時は、モンスターの絵（図鑑用）を ROM から自動展開します
（`work\monster-art-rom\`。2回目以降は展開済みなので何もしません）。

---

## 操作方法

### キーボード

RetroUX 固有の操作（ゲーム画面を触りながら使えます）:

| キー | はたらき |
| --- | --- |
| `M` | **まんたん**（HP/MP を回復。毒も治す） |
| `R` | **はなす**（相手に応じて どうぐや補充 / ふくびき を自動選択） |
| `A` | **AUTO**（AI 操作）オンオフ ※キーボードの A |
| `T` | **Turbo**（戦闘倍速）オンオフ |
| `G` | 見た**地図**を開く |
| `F9` | ゲーム画面へフォーカスを戻す |
| `Ctrl+F` | 地図で現在地を追う（地図ウィンドウ） |
| `Ctrl+M` | いる場所に**メモ**を書く（地図ウィンドウ） |
| `Ctrl+Shift+M` | マップの**名前・階層**を直す（地図ウィンドウ） |
| `Ctrl+Shift+R` | 標準レイアウトに戻す |
| `Ctrl+K` | キー割り当ての設定 |
| `Ctrl+Shift+L` | Lua ウィンドウを出す（障害調査用） |

ゲーム本体の操作（FCEUX の既定。**FCEUX の Config→Input で変更可**）:

| キー | NES |
| --- | --- |
| 矢印キー | 十字（移動） |
| `F` / `D` | A / B |
| `Enter` / `S` | Start / Select |
| `P` | セーブステートの**読み込み**（ロード） |

★キー割り当ては `config/keybindings.yaml`（または `Ctrl+K` の設定画面）で変えられます。

### ゲームパッド

**XInput 対応（XBOX 系）のコントローラに対応**しています。基本操作も独自機能も
RetroUX 側で読み取って FCEUX へ渡すため、**FCEUX 本体でパッドを割り当てなくても
動きます**（起動前にコントローラを接続してください）。

| パッド | はたらき |
| --- | --- |
| 十字 / 左スティック・A・B・Start・Back | 移動と NES 各ボタン |
| LB / RB | セーブステートの**ロード / セーブ** |
| LT / RT | **AUTO** / **Turbo** のオンオフ |
| X / Y | どうぐや・ふくびき（`R`）/ まんたん（`M`） |
| 右スティック / R3 押し込み | **マウス移動 / 左クリック**（押したままでドラッグ） |

- ⚠ 動作確認は XBOX(XInput) コントローラです。XInput 非対応のパッドは読めません。
- ⚠ **「強制オート高速戦闘」（キーボード `A` の押しっぱなし）はパッド未対応**です。
  パッドの LT は AUTO のオンオフで、押しているあいだだけ高速化する動きはできません
  （キーボードの `A` を使ってください）。
- ⚠⚠ **FCEUX の Input でパッドを割り当てないでください。** NES 入力は RetroUX が
  読んで渡すので、FCEUX 側でも同じパッドを割り当てると**二重入力**になり A と B が
  混ざるなどの誤動作が起きます。FCEUX の Port 1 は**キーボードのまま**でOKです。
- NES 入力を FCEUX 本体に任せたい場合や、うまく動かないときの切り分け
  （`inject_nes_input` の切替）は [`docs/60-gamepad-setup.md`](docs/60-gamepad-setup.md) を参照。

## 主な機能

- **戦闘の自動化**（省資源／全力などの戦術プロファイル、キャラ別の役割）
- **まんたん**（HP/MP 回復。ホイミ→ベホイミ→やくそう の優先）
- **倍速**（戦闘の高速化）
- **見た地図の可視化**（実際に歩いた範囲・ROM 由来のタイル）
- **セーブステートの世代バックアップ**（上書きしても直前へ戻せる）
- **ゲームパッド対応**（XInput / XBOX 系）… 基本操作も独自機能も。詳しくは
  [`docs/60-gamepad-setup.md`](docs/60-gamepad-setup.md)

---

## 設定

`user_config.yaml`（`user_config.example.yaml` をコピーして作る）で、
ウィンドウの並び・保存スロット・ゲームパッド・回復方針などを変えられます。
項目の説明は `user_config.example.yaml` のコメントを参照してください。

### セーブについて

- **既定ではスロット 1 に保存/読込します。** 「保存して終了」も、ゲームパッドの
  **RB(セーブ) / LB(ロード)** も、**同じ 1 つのスロット**（`shutdown.save_slot`）を使います。
- スロットは変更できます（1〜9。⚠ 0 は使えません）:
  ```yaml
  shutdown:
    save_slot: 2
  ```
- 上書きしても、直前の内容は**世代バックアップ**（`work/savestate-backup/`）に残るので戻せます。
- ★FCEUX 自身のセーブ/ロード（キーボード等）は別系統で、そちらは 0〜9 を使えます。

---

## フォルダ構成（どこに何を置くか）

| 場所 | 中身 |
| --- | --- |
| `tools\fceux\fceux64.exe` | **エミュレータ本体**（各自で配置。同梱しません） |
| `work\rom\DQ2_J.nes` | **ROM**（各自で用意し、この名前で配置） |
| `tools\fceux\fcs\` | **セーブステート**（FCEUX が書き出す先。例 `DQ2_J.fc1`） |
| `work\savestate-backup\` | セーブステートの**世代バックアップ**（上書きしても戻せる） |
| `work\monster-art-rom\` | **モンスターの絵**（初回起動時に ROM から自動展開） |
| `work\` | 実行時のデータ（DB・ログ・状態ファイル等。消えてよい生成物） |
| `user_config.yaml` | あなたの設定（`user_config.example.yaml` をコピーして作る） |
| `scripts\` | 起動スクリプト（`start-retroux.ps1` ほか） |
| `retroux\` | **アプリ本体のソース**（Python + Lua 連携） |
| `dq2rom\` | ROM 解析ツール（Python パッケージ） |
| `tests\` | テスト |

★セーブステートの保存/読み込みスロットや、ROM・各種パスは `user_config.yaml` で
変えられます（既定は保存スロット 1）。

## 動作確認（任意）

```powershell
uv run pytest
```

（ROM やセーブステートを要する一部の検査は、無ければ自動でスキップします）

---

## ライセンス

**MIT License** — 詳しくは [`LICENSE`](LICENSE) を参照してください。
© 2026 soichannel3590

★ライセンスが及ぶのは RetroUX のソースコードのみです（ゲーム側の権利には及びません）。

---

## 作者

soichannel3590 — YouTube: <https://www.youtube.com/@soichannel3590>

---

## 補足

- 本リポジトリは配布用です。開発は別のリポジトリで行っています。
- 不具合や要望は Issue へどうぞ。
