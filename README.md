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
- [FCEUX](https://fceux.com/)（Lua スクリプトが動く版。`fceux64.exe`）
- 正規に所有する DQ2(FC/JP) の ROM ファイル
- Python 3.12 と [uv](https://docs.astral.sh/uv/)
- （任意）XBOX の USB コントローラ

---

## セットアップ

```powershell
# 1. 取得
git clone https://github.com/akizuna515-bit/RetroUX.git
cd RetroUX

# 2. 依存をそろえる
uv sync

# 3. FCEUX を置く（Lua 対応版）
#    実行ファイルが tools\fceux\fceux64.exe になるように配置

# 4. ROM を置く（正規に所有するもの）
#    ★ファイル名を DQ2_J.nes にリネームし、work\rom\ に置く
#      → 最終的に work\rom\DQ2_J.nes になること
#    （別名・別の場所にしたい場合は user_config.yaml の paths.rom を変更）

# 5. 設定を用意する
copy user_config.example.yaml user_config.yaml
#    必要ならエディタで user_config.yaml を編集

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

### ゲームパッド（XBOX）

**挿すだけ**で使えます（FCEUX 側の設定は不要）。

| パッド | はたらき |
| --- | --- |
| 十字 / 左スティック・A・B・Start・Back | 移動と NES 各ボタン |
| LB / RB | セーブステートの**ロード / セーブ** |
| LT / RT | **AUTO** / **Turbo** のオンオフ |
| X / Y | どうぐや・ふくびき（`R`）/ まんたん（`M`） |

詳しくは [`docs/60-gamepad-setup.md`](docs/60-gamepad-setup.md)。

## 主な機能

- **戦闘の自動化**（省資源／全力などの戦術プロファイル、キャラ別の役割）
- **まんたん**（HP/MP 回復。ホイミ→ベホイミ→やくそう の優先）
- **倍速**（戦闘の高速化）
- **見た地図の可視化**（実際に歩いた範囲・ROM 由来のタイル）
- **セーブステートの世代バックアップ**（上書きしても直前へ戻せる）
- **XBOX ゲームパッド対応** … 挿すだけ。詳しくは
  [`docs/60-gamepad-setup.md`](docs/60-gamepad-setup.md)

---

## 設定

`user_config.yaml`（`user_config.example.yaml` をコピーして作る）で、
ウィンドウの並び・保存スロット・ゲームパッド・回復方針などを変えられます。
項目の説明は `user_config.example.yaml` のコメントを参照してください。

---

## フォルダ構成（どこに何を置くか）

| 場所 | 中身 |
| --- | --- |
| `tools\fceux\fceux64.exe` | **エミュレータ本体**（各自で配置。同梱しません） |
| `work\rom\DQ2_J.nes` | **ROM**（各自で用意し、この名前で配置） |
| `tools\fceux\fcs\` | **セーブステート**（FCEUX が書き出す先。例 `DQ2_J.fc1`） |
| `work\savestate-backup\` | セーブステートの**世代バックアップ**（上書きしても戻せる） |
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
