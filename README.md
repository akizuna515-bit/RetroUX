# RetroUX

**RetroUX** は、ファミコン版『ドラゴンクエストII』『ドラゴンクエストIII』を
FCEUX 上で自動プレイ補助するデスクトップアプリです
（Windows / Python + PySide6 + FCEUX の Lua 連携）。

戦闘の自動化、まんたん（HP/MP 回復）、倍速、見た地図の可視化、
XBOX ゲームパッド対応などを備えます。
DQ3 では戦闘 AI・勇者メモ・聞き込み・街の自動移動・モンスター図鑑も使えます。

> ⚠ **これは補助ツールです。** ゲーム本体（ROM）もエミュレータ（FCEUX）も
> **同梱していません**。ご自身で用意してください（下記）。

---

## ★DQ3 をかんたんに使う（配布 ZIP / Python のインストール不要）

★DQ3 だけを遊ぶなら、[Releases](https://github.com/akizuna515-bit/RetroUX/releases) の
**配布 ZIP**（`retroux-dq3-<版>-<断面>.zip`）がいちばん簡単です。
Python と必要なライブラリを同梱しているので、`uv` も `git` も要りません。

1. ZIP を書き込める場所へ展開する（例 `D:\Games\` / ⚠ `C:\Program Files` の下は避ける）
2. ROM と FCEUX を置く（ZIP の中の `PLACE-ROM-HERE.txt` / `PLACE-FCEUX-HERE.txt`）
3. `DQ3.cmd` をダブルクリック

⚠ 使い方・セーブデータの扱い・新しい版への入れ替え方は、**ZIP の中の `README.md`** を読んでください
（★特に、FCEUX を ZIP のフォルダの中に置いた場合のセーブステートと冒険の書の扱い）。
★ZIP の SHA-256 は Release のページに書いてあります。

## ★DQ2 をかんたんに使う（配布 ZIP / Python のインストール不要）

★DQ2 も、[Releases](https://github.com/akizuna515-bit/RetroUX/releases) の
**配布 ZIP**（`retroux-dq2-<版>-<断面>.zip`）で動きます（★1.2.0 から）。

1. ZIP を書き込める場所へ展開する
2. ROM と FCEUX を置く（ZIP の中の `PLACE-ROM-HERE.txt` / `PLACE-FCEUX-HERE.txt`）
3. `DQ2.cmd` をダブルクリック

⚠ 旧い DQ2 のフォルダから移すときは、先に `migrate-dq2.cmd` を使います（**ZIP の中の `README.md`**）。
⚠ DQ2 と DQ3 は**同時に起動できません**（同じコントローラーを読むため）。

★版とタグは**製品ごと**です（DQ2 は `dq2-vX.Y.Z`、DQ3 は `dq3-vX.Y.Z`。旧タグ `v1.x.x` はそのまま）。

★ここから下は、**リポジトリを clone して使う方法**（開発・DQ2 を含む）です。

---

## ⚠ はじめに（法律・権利）

- **本ソフトは非公式のファンツールです。** 任天堂株式会社、株式会社スクウェア・
  エニックス、その他の権利者とは**一切関係がなく、承認・提携もありません**。
  『ドラゴンクエスト』は各権利者の商標・著作物です。
- **ROM は含まれていません。** 正規に所有する『ドラゴンクエストII』『ドラゴンクエストIII』
  (FC/日本版) の ROM をご自身で用意してください。
  ROM の入手・配布は各自の責任と法令に従ってください。
- **FCEUX は含まれていません。** 公式サイト等から入手してください（Lua 対応版）。
- **本ソフトはゲームの内容物を含みません。**
  - ⚠ 同梱しないもの: ROM / ROM から復元したグラフィック / 地図の画像 /
    ゲーム画面 / 音楽・効果音 / 原作の会話やメッセージ。
  - ★同梱するもの: RetroUX が ROM・RAM の解析や実機観測で得た**構造の情報**
    （番地・表の構造・ID の対応表・フラグの定義・タイル id の対応など）と、
    その解析プログラム。
  - ★**絵と文言は、起動時にお手元の ROM から読みます。**
    例: モンスターの絵、敵のデータ表、モンスター・道具・呪文・地名の名前。
- 本ソフト（RetroUX のソースコード）は MIT ライセンスです（`LICENSE` 参照）。
  ★ライセンスが及ぶのは RetroUX のコードだけで、ゲーム側の権利には及びません。
- RetroUX が使う第三者ライブラリ（PySide6・shiboken6・PyYAML など）は、それぞれのライセンスに従います。
  ★配布 ZIP に同梱しているものの表記は `THIRD_PARTY_LICENSES.txt` と `licenses\` にあります。

---

## 必要なもの

- Windows 10 / 11
- **FCEUX 2.6.6（win64）**で動作確認しています（Lua が動く版）。
  入手: 公式 GitHub Releases → <https://github.com/TASEmulators/fceux/releases/tag/v2.6.6>
  （他のバージョンでも動く可能性はありますが、未確認です）
  ⚠ **exe 単体では動きません。** RetroUX は Lua で制御するため、**`lua5.1.dll` が必須**です。
  配布 zip（`fceux-2.6.6-win64.zip`）を**丸ごと展開**してください（`fceux64.exe` /
  `lua5.1.dll` / `lua51.dll` / `7z_64.dll` / `auxlib.lua` などが揃った状態）。
- 正規に所有する ROM ファイル（**DQ2(FC/JP)** と **DQ3(FC/JP)** のどちらか、または両方）
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
#    ★遊びたいほうを置きます（両方でも可）
#      DQ2 → work\rom\DQ2_J.nes    にリネームして置く
#      DQ3 → work\rom\DQ3_J.nes    にリネームして置く
#    （DQ2 の別名・別の場所は dq2_user_config.yaml の paths.rom で変更できます）
#    （DQ3 の ROM・FCEUX の別の場所は user_config.yaml の paths.dq3_rom / paths.fceux で指定できます）
#    （DQ2 の FCEUX の別の場所は dq2_user_config.yaml の paths.fceux で指定できます）

# 5. 設定（任意。★無くても既定値で動きます）
#    カスタムしたいときだけ、雛形をコピーして編集:
#      DQ2 → copy dq2_user_config.example.yaml dq2_user_config.yaml
#      DQ3 → copy user_config.example.yaml user_config.yaml
#    ★DQ2 と DQ3 は設定ファイルが別です（2026-10-03）。
#    ⚠ dq2_user_config.yaml が無いときは、DQ2 は user_config.yaml を読むだけで使います。
#    以下は DQ2 の例:
#    例: emulator.window_scale（映像倍率。既定 2 = 2倍。1 で等倍）
#        gamepad.swap_ab（A/B 入れ替え。既定 true = ファミコン準拠）
#        shutdown.save_slot（保存/読込スロット。既定 1）
```

これで完了です。★設定から Lua への変換やモンスターの絵の展開は、
**起動のたびに自動で行われる**ので手動の手順はありません。

---

## 起動

遊びたいタイトルのランチャーを**ダブルクリック**します。それだけです。

```text
DQ2.cmd       … ドラゴンクエストII
DQ3.cmd       … ドラゴンクエストIII
```

★以前の `RetroUX.cmd` も 1 リリースだけ使えます（★中で `DQ2.cmd` を呼ぶだけ / 次のマイナー更新で削除予定）。

★モードや版を選ばせるダイアログは出ません。
⚠ 起動の一瞬だけ黒い窓が見えますが、★すぐ消えます（Windows の仕様です）。

デスクトップに置きたい場合は、**ショートカットを作って**それを置いてください
（⚠ `.cmd` 自体はフォルダの中に置いたままにします）。

コンソールを見ながら起動したいとき（DQ2）は:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-dq2.ps1
```

起動すると、設定の反映・世代バックアップの開始・GUI と FCEUX の起動・
ウィンドウ整列まで自動で行います。

★**初回起動時は、お手元の ROM から必要なデータを自動生成します。**
2 回目以降は生成済みなので何もしません（数 ms で抜けます）。

| タイトル | 初回に作られるもの | 置き場 |
| --- | --- | --- |
| DQ2 | モンスターの絵（図鑑用） | `work\monster-art-rom\` |
| DQ2 | マップの大きさ表（地図用） | `work\map-data\maps.json` |
| DQ3 | モンスターの絵（図鑑・戦闘画面用） | `work\cache\dq3-monster-art\` |
| DQ3 | 名前の辞書（モンスター・道具・呪文・地名） | `work\generated\dq3-names.json` |
| DQ3 | 戦闘 AI と設定の Lua | `work\generated\` |

⚠ 手で解析スクリプトを走らせる必要はありません。**ROM を置いて起動するだけ**です。

---

## 操作方法

### キーボード

#### ドラゴンクエストIII

| キー | はたらき |
| --- | --- |
| `A` | **オート戦闘**のオンオフ（⚠ ゲームの A ボタンは `F` です） |
| `T` | **ターボ**（倍速）のオンオフ |
| `M` | **まんたん**（全員を回復） |

⚠ 危ない場面（誰かが倒れた・HP が 1/4 を割った・劣勢になった）では、
★オートとターボを**自動で切って操作を返します**。

#### ドラゴンクエストII

RetroUX 固有の操作（`M` `R` `A` `T` `G` はゲーム画面を触りながら使えます。
`Ctrl` 系は RetroUX の窓にフォーカスがあるときに効きます）:

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

★キー割り当ては `work\dq2-settings\keybindings.yaml`（または `Ctrl+K` の設定画面）で変えられます。以前の版の `config\keybindings.yaml` は、新しい方が無いあいだ読むだけです。

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
| **X 長押し（戦闘中）** | **強制オート ＋ 一時的に倍速**（押している間だけ） |
| 右スティック / R3 押し込み | **マウス移動 / 左クリック**（押したままでドラッグ） |

⚠ 上の表は **DQ2** の割り当てです。★**DQ3** では次の 3 つが違います（ほかは同じ）。

| パッド（DQ3） | はたらき |
| --- | --- |
| X 短押し | **宿屋に移動**（画面の［宿］と同じ。「泊まりますか？」に「はい」まで進みます / 戦闘中は何もしません） |
| X 長押し（戦闘中） | **強制オート ＋ 一時ターボ**（離すと押す前の状態へ戻ります） |
| LB / RB | **ステート 0** の読込 / 保存（⚠ 番号は 0 固定 / RB はステート 0 を上書きします） |

★DQ3 のコントローラーの設定は DQ3 の［管理］にあります（⚠ `dq2_user_config.yaml` の `gamepad:` は DQ2 用）。
⚠ DQ2 と DQ3 は**同時には使えません**。片方の起動中にもう片方を起動すると、
「RetroUX DQ2 が起動中です。DQ2を終了してからRetroUX DQ3を起動してください。」のように理由を出して、何も起動せずに終わります（逆も同じ）。

- ⚠ 動作確認は XBOX(XInput) コントローラです。XInput 非対応のパッドは読めません。
- ★**戦闘中に X を押しっぱなし**にすると、押している間だけ「強制オート ＋ 倍速」に
  なります（危険判定・初遭遇・警戒中を無視して押し切るモード）。離すと**すぐ戻ります**。
  - ⚠ 倍速は**押す前の状態へ戻します**（押す前が ON なら ON のまま）。
  - ⚠ **ボスは対象外**です（既定）。戦闘が終わったとき・パッドを抜いたとき・
    RetroUX を終了したときも必ず解除されます。
  - ★入るまでの長さは `dq2_user_config.yaml` の `gamepad.force_auto_hold_ms`（既定 500ms）。
  - ⚠ 戦闘中の X の**短押し**は何も起きません（長押しに使うため）。
    非戦闘時の X は従来どおり「どうぐや・ふくびき」です。
  - ★キーボードの `A`（入り切りのトグル）はこれまでどおり使えます。
- ⚠⚠ **FCEUX の Input でパッドを割り当てないでください。** NES 入力は RetroUX が
  読んで渡すので、FCEUX 側でも同じパッドを割り当てると**二重入力**になり A と B が
  混ざるなどの誤動作が起きます。FCEUX の Port 1 は**キーボードのまま**でOKです。
- NES 入力を FCEUX 本体に任せたい場合や、うまく動かないときの切り分け
  （`inject_nes_input` の切替）は [`docs/guide/gamepad-setup.md`](docs/guide/gamepad-setup.md) を参照。

## 主な機能

### ドラゴンクエストII

- **戦闘の自動化**（省資源／全力などの戦術プロファイル、キャラ別の役割）
- **まんたん**（HP/MP 回復。ホイミ→ベホイミ→やくそう の優先）
- **倍速**（戦闘の高速化）
- **見た地図の可視化**（実際に歩いた範囲・ROM 由来のタイル）
- **セーブステートの世代バックアップ**（上書きしても直前へ戻せる）
- **ゲームパッド対応**（XInput / XBOX 系）… 基本操作も独自機能も。詳しくは
  [`docs/guide/gamepad-setup.md`](docs/guide/gamepad-setup.md)

### ドラゴンクエストIII

- **戦闘 AI**（作戦は 最短撃破 / リソース節約 / 生存優先。MP の使い方と、
  キャラごとの行動傾向も選べます）
- **オート戦闘とターボ**（⚠ 危ない場面では自動で操作を返します）
- **まんたん**（フィールドでの HP/MP 回復）
- **見た地図**（歩いた範囲だけを描きます。世界地図・街・ダンジョン）
- **勇者メモ**（聞いた会話を、誰から聞いたかごと残します）
- **聞き込み**（街の人を自動でまわって話を集めます）
- **街の中の自動移動**（宿屋・店・教会などへ自分で歩いていきます）
- **モンスター図鑑**（会った敵の絵・行動・耐性。⚠ 絵はお手元の ROM から作ります）
- **セーブステートの世代バックアップ**

- **勇者会議**（勇者メモのカードを、その時点で知っていることだけで束ねて見せます）

勇者会議の材料は `data/dq3/hero-memo.yaml` です（書き方は `data/dq3/README.md`）。
hero-memo / scenario データは、実プレイログおよびゲーム状態を参考にプロジェクト作者が独自に作成したものです。
第三者攻略サイトの文章や原作会話本文をそのまま収録するものではありません。

---

## 設定

DQ2 は `dq2_user_config.yaml`（`dq2_user_config.example.yaml` をコピーして作る）で、
ウィンドウの並び・保存スロット・ゲームパッド・世界地図の見せ方（`map.overworld_view`）などを変えられます。
項目の説明は `dq2_user_config.example.yaml` のコメントを参照してください。
★DQ3 の設定は `user_config.yaml`（`user_config.example.yaml` をコピー）です（2026-10-03 から別ファイル）。
⚠ `dq2_user_config.yaml` が無いときは、DQ2 は `user_config.yaml` を読むだけで使います（書き戻しません）。

★DQ3 の画面の見え方（FCEUX の映像フィルタ）は、DQ3 の［管理］→「画面の見え方」で選びます。
⚠ RetroUX は FCEUX を起動する直前に `fceux.cfg` の `winspecial` の行をその選択に書き換えます
（`fceux.cfg` がまだ無い FCEUX では、窓を縦横 2 倍にする設定で作ります。ほかの設定は変えません）。

### 終わるとき（DQ3）

★RetroUX の［終］は「FCEUX も一緒に閉じますか？」と聞きます（⚠ 自動ではセーブしません）。
RetroUX の窓の × は RetroUX だけを閉じます（FCEUX は開いたまま）。

### セーブについて

⚠ この節は **DQ2** の話です。★DQ3 のパッドの LB / RB は**ステート 0 固定**です（上の「ゲームパッド」）。

- **既定ではスロット 1 に保存/読込します。** 「保存して終了」も、ゲームパッドの
  **RB(セーブ) / LB(ロード)** も、**同じ 1 つのスロット**（`shutdown.save_slot`）を使います。
- スロットは変更できます（0〜9）:
  ```yaml
  shutdown:
    save_slot: 2
  ```
- 上書きしても、直前の内容は**世代バックアップ**（DQ2 は `work/runtime/dq2-backup/savestate-backup/`）に残るので戻せます。
- ★FCEUX 自身のセーブ/ロード（キーボード等）は別系統ですが、同じ番号のファイルを指します。

---

## フォルダ構成（どこに何を置くか）

| 場所 | 中身 |
| --- | --- |
| `tools\fceux\fceux64.exe` | **エミュレータ本体**（各自で配置。同梱しません） |
| `work\rom\DQ2_J.nes` | **DQ2 の ROM**（各自で用意し、この名前で配置） |
| `work\rom\DQ3_J.nes` | **DQ3 の ROM**（各自で用意し、この名前で配置） |
| `tools\fceux\fcs\` | **セーブステート**（FCEUX が書き出す先。例 `DQ2_J.fc1`） |
| `tools\fceux\sav\` | **冒険の書**（バッテリーセーブ。FCEUX が書き出す先） |
| `work\runtime\dq2-backup\savestate-backup\` | DQ2 のセーブステートの**世代バックアップ**（上書きしても戻せる） |
| `work\savestate-backup\` | DQ3 のセーブステートの**世代バックアップ**（★2026-10-03 より前は DQ2 の分もここ） |
| `work\monster-art-rom\` | DQ2 の**モンスターの絵**（初回起動時に ROM から自動展開） |
| `work\map-data\maps.json` | DQ2 の**マップの大きさ表**（初回起動時に ROM から自動生成） |
| `work\cache\dq3-monster-art\` | DQ3 の**モンスターの絵**（初回起動時に ROM から自動生成） |
| `work\dq3-knowledge\` | DQ3 の**あなたのプレイの記録**（勇者メモ・聞いた話・見た地図） |
| `work\generated\` | ROM と設定から作る中間データ（名前の辞書・Lua など） |
| `work\` | 実行時のデータ（DB・ログ・状態ファイル等。消えてよい生成物） |
| `dq2_user_config.yaml` | DQ2 のあなたの設定（`dq2_user_config.example.yaml` をコピーして作る） |
| `user_config.yaml` | DQ3 のあなたの設定（`user_config.example.yaml` をコピーして作る） |
| `scripts\` | 起動スクリプト（`start-dq2.ps1` / `start-dq3.ps1` ほか） |
| `retroux\` | **アプリ本体のソース**（Python + Lua 連携 / DQ2） |
| `dq3\` | **DQ3 の画面と戦闘 AI**（Python + Lua） |
| `dq2rom\` / `dq3rom\` | ROM 解析ツール（Python パッケージ） |
| `data\dq3\` | DQ3 の解析成果（番地・ID 対応表・升 id → CHR 索引） |
| `tests\` | テスト |

★DQ2 のセーブステートの保存/読み込みスロットや、ROM・各種パスは `dq2_user_config.yaml` で
変えられます（既定は保存スロット 1）。

⚠⚠ FCEUX を `tools\fceux\` に置いている場合、セーブステート（`fcs\`）と冒険の書（`sav\`）も
**このフォルダの中**にあります。★フォルダを消す・置き直す前に、`tools\fceux\` を中身ごと退避してください
（⚠ `work\savestate-backup\` と `work\runtime\dq2-backup\` の控えも、このフォルダと一緒に消えます）。

## 動作確認（任意）

```powershell
uv sync --extra dev   # ★テスト実行用に pytest を追加（初回のみ）
uv run pytest
```

★ROM やセーブステート、FCEUX が無くても**全部緑**になります
（要るものは自動でスキップ）。⚠ 赤が出たら、それは環境か不具合です。

---

## ライセンス

**MIT License** — 詳しくは [`LICENSE`](LICENSE) を参照してください。
© 2026 soichannel3590

★ライセンスが及ぶのは RetroUX のソースコードのみです（ゲーム側の権利には及びません）。

第三者ライブラリ（PySide6・shiboken6 = LGPLv3 / PyYAML = MIT など）は、それぞれのライセンスに従います。
★配布 ZIP に同梱しているものの表記: [`THIRD_PARTY_LICENSES.txt`](THIRD_PARTY_LICENSES.txt)（本文は `licenses\`）。

---

## 作者

soichannel3590 — YouTube: <https://www.youtube.com/@soichannel3590>

---

## 補足

- 本リポジトリは配布用です。開発は別のリポジトリで行っています。
- 不具合や要望は Issue へどうぞ。
- **改造・機能追加をしたい方へ**: 全体の構造は [`ARCHITECTURE.md`](ARCHITECTURE.md)、
  Issue / PR の作法は [`CONTRIBUTING.md`](CONTRIBUTING.md) を参照してください。
