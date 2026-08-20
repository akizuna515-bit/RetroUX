# Changelog

このファイルは公開版 RetroUX の変更履歴です。
形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に準じます。

## [Unreleased]

### 修正
- 新規セットアップ（clone 直後）でモンスターの絵が1枚も表示されなかった。
  初回起動時に ROM から自動展開するようにした（`work\monster-art-rom\`）。

## [1.0.1] - 2026-08-20

### 追加
- ゲームパッドの右スティックでマウスカーソルを移動、R3（右スティック押し込み）で
  左クリック（押したままでドラッグ）。パッドだけで GUI のボタン等を操作できる。
  `gamepad.mouse: false` で無効化、速度は `gamepad.mouse_speed`（px/秒）。

### 修正
- ゲームパッド入力ファイルの毎フレーム I/O が turbo 戦闘の実効倍率を大きく下げていた
  （実測 ×3〜6 → 修正後 ×30 前後）。放置中に数秒おきに音がもたつく症状も同じ原因。
  未押下時の書き込みを 0.5 秒に1回へ間引き、エミュレータ側の読み取りを実時間
  （最大125Hz）でゲートした。
- turbo 中にパッドの押しっぱなしが誤って解除されることがあった（生存判定が
  フレーム数計上だったため。実時間 0.24〜0.5 秒に正常化）。

## [1.0.0] - 2026-08-XX

初回公開。

### 追加
- ファミコン版『ドラゴンクエストII』の自動プレイ補助（Windows / FCEUX 連携）。
- 戦闘の自動化（戦術プロファイル・キャラ別の役割）。
- まんたん（HP/MP 回復。ホイミ→ベホイミ→やくそう の優先）。
- 戦闘の倍速。
- 見た地図の可視化（歩いた範囲・ROM 由来のタイル）。
- セーブステートの世代バックアップ。
- XBOX ゲームパッド対応（挿すだけ。移動・基本操作・独自機能）。

> ⚠ ROM と FCEUX は同梱していません（各自で用意）。

[Unreleased]: https://github.com/akizuna515-bit/RetroUX/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/akizuna515-bit/RetroUX/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/akizuna515-bit/RetroUX/releases/tag/v1.0.0
