# ゲームパッド（XBOX）で遊ぶ

作成: 2026-08-19 / 対応: RX-0076

RetroUX は **XInput 対応（XBOX 系）のコントローラ**で操作できます。移動も基本ボタンも
独自機能も RetroUX 側で読み取るため、**FCEUX 本体でパッドを割り当てなくても動きます**
（起動前にコントローラを接続してください）。⚠ XInput 非対応のパッドは読めません。

> ⚠⚠ **FCEUX の Input でパッドを割り当てないでください。** ★NES 入力は RetroUX が
> 読んで注入します。FCEUX 側でも同じパッドを割り当てると**二重入力**になり、
> **A と B が混ざる**などの誤動作が起きます（実機で確認）。
> FCEUX の Port 1 は**キーボードのまま**でOKです（既定のまま何もしなくて良い）。
> Config→Input→Port 1 の割当は キーボード（矢印 / F=A / D=B / S=Select / Enter=Start）のみ。

## 割り当て一覧

| パッド | 機能 |
| --- | --- |
| 十字 / 左アナログ | 移動（NES 十字） |
| A / B | NES の A / B |
| Start / Back(View) | NES の Start / Select |
| **LB** | セーブステートを**ロード** |
| **RB** | セーブステートを**セーブ** |
| **LT** | **Auto**（AI操作）オンオフ |
| **RT** | **Turbo**（戦闘倍速）オンオフ |
| **X** | どうぐや / ふくびき（キーボード **R** と同じ） |
| **Y** | まんたん（キーボード **M** と同じ） |

- ロード/セーブのスロットは**終了時の保存と同じ**スロット（`shutdown.save_slot`）です。
  RB で保存 → LB で戻せます。
- LT / RT は**軽く触れただけでは効きません**（アナログの遊びを無視）。奥まで踏むと切り替わります。
- 独自機能を押すと RetroUX の下部（整列ステータス）に「パッド: …」と出ます。

## どう動いているか（仕組み）

RetroUX が XInput でパッドを読み、2 通りに振り分けます:

- **NES ボタン（十字/A/B/Start/Select）** … 押している間の**状態**を毎フレーム
  RetroUX → FCEUX（`work/gamepad_input.txt` 経由）へ渡し、ゲームへ入力します。
  ★キーボードと同じように扱われ、**Auto ON の自動プレイとも競合しません**
  （自動入力中はそちらが優先、非戦闘や Auto OFF ではパッドが効く）。
- **独自機能（LB/RB/LT/RT/X/Y）** … 押した瞬間に RetroUX が直接実行します。

★どちらも RetroUX が読むので、**FCEUX の Config→Input を触る必要はありません**。

## 効かないとき

- **パッドを挿してから RetroUX を起動**してください（起動後の抜き差しにも追従しますが、
  最初に挿しておくのが確実です）。
- **Auto が ON** だと移動は AI 側が優先します。自分で歩くときは LT で Auto を OFF に。
- XBOX パッドは XInput で読みます（Windows 同梱）。ごく古い環境で XInput が無い場合は、
  起動ログに「XInput が使えません」と 1 回出て、**キーボード操作のまま**動きます。
- パッドを無効にしたいときは、環境変数 `RETROUX_NO_GAMEPAD` を設定して起動します。
- ⚠ 反応が数フレーム遅れて感じることがあります（RetroUX→FCEUX へ状態を渡すため）。
  RPG の移動では通常気になりませんが、シビアな操作には向きません。

---

## 🧪 検証モード：NES 入力を FCEUX 本体に任せる（RX-0078）

★**現行方式は残したまま**、NES 標準入力だけを「FCEUX 本体のパッド割当」に切り替えて
比べられます（現行方式が既定。これは切り分け・比較のための任意モードです）。

`user_config.yaml`:

```yaml
gamepad:
  enabled: true            # RetroUX は XInput を読み続ける
  inject_nes_input: false  # ★NES 入力(十字/A/B/Start/Select)は RetroUX から送らない
```

- `inject_nes_input: false` にすると、RetroUX は `work/gamepad_input.txt` へ**常に 0**を
  書き、NES 入力を注入しません。NES 操作は **FCEUX の Config→Input** で割り当てて使います。
- ★このとき **RetroUX 独自機能（LB/RB/LT/RT/X/Y）は従来どおり効きます**（無効化されません）。
- 二重入力を避けるため、`inject_nes_input: false` のときは **RetroUX 側は NES を一切送りません**
  （FCEUX ネイティブと衝突しない）。★自動プレイの `joypad.set()` はこれとは別経路で無関係です。

### FCEUX 側の割り当て（検証モードのとき）

1. RetroUX からゲームを起動 → FCEUX の **Config → Input… → Port 1 → Configure**。
2. 十字・A・B・Start・Back(View) をパッドの対応ボタンへ割り当てて閉じる
   （`tools/fceux/fceux.cfg` に保存され、次回から不要）。
3. ⚠ **LB/RB/LT/RT/X/Y は FCEUX に割り当てない**（RetroUX が直接読むため。二重になる）。

### 切り分け用 DEBUG ログ

`gamepad.debug: true`（または環境変数 `RETROUX_GAMEPAD_DEBUG`）で、フォーカスと押した
ボタンを `work/retroux.log` に出せます（既定 OFF。製品では常用しません）:

```
[GAMEPAD DEBUG] focus=<最前面ウィンドウ名> retroux_event=toggle_turbo
[GAMEPAD DEBUG] focus=<最前面ウィンドウ名> nes=[← A] inject=OFF
```

---

## ボタン割り当て一覧（競合の有無）

| パッド | 用途 | 種別 |
| --- | --- | --- |
| 十字 / 左アナログ・A・B・Start・Back | NES 標準入力 | NES用（`inject_nes_input` で RetroUX 注入 / FCEUX 本体 を切替） |
| LB / RB / LT / RT / X / Y | ロード/セーブ/Auto/Turbo/どうぐや/まんたん | RetroUX 専用（常に有効） |
| 右スティック・スティック押し込み・Guide | — | 未使用 |

★**NES用と RetroUX専用はボタンが重ならない**ので、FCEUX ネイティブ割当（NES）と
RetroUX の XInput（独自機能）を**同時に使っても競合しません**（同じ物理ボタンを
両方が奪い合うことがない）。⚠ 唯一の二重入力リスクは「RetroUX が NES を注入」かつ
「FCEUX も NES を割当」の同時併用で、`inject_nes_input: false` がそれを防ぎます。
