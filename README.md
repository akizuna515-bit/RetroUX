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
#    tools\fceux\fceux64.exe になるように配置

# 4. ROM を置く
#    work\rom\DQ2_J.nes になるように配置（正規に所有するもの）

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
