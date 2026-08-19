"""キャラクター別戦術AI・プロフィール（2026-07-30 / 仕様書 17章）。

★★ **この機能の芯（仕様書 23章）** ★★

  > ゲーム側が用意した数種類の作戦を選ぶものではない。
  > **利用者がキャラクターごとに戦術を設計し、
  >   AI がその意図を再現可能な形で実行する。**

## 分担

| ファイル | 役割 |
| --- | --- |
| `models.py` | 語彙と**設定項目の一覧**（`FIELDS`）。★ここが唯一の出典 |
| `profile.py` | プロフィール1つ分。YAML の形・AI へ渡す形・人が読む要約 |
| `profile_repository.py` | 一覧・読み・保存・複製・削除・選択中の保持 |
| `profile_validator.py` | 型・必須・範囲・未知項目・版・キャラクターID |
| `import_export.py` | YAML の出し入れ（**安全な読み込み**・衝突処理） |
| `lua_bridge.py` | Lua へ渡す（`work/generated/tactics.lua` を書く） |

判断そのものは **Lua（`bridge.lua`）**。ここは設定を作って渡すだけ。

## ⚠⚠ フェーズを混ぜない（仕様書 20章）

  > Phase 3以降の設定項目は、データモデル上は追加可能にしておくが、
  > **未実装の判断ロジックを動作するように見せない。**

→ `models.IMPLEMENTED_PHASES` に無い項目は
  **読み込んで保存はするが、AI へは渡さない**。
  画面はグレーアウトして「今後のフェーズで対応」と出す。

## 既存AIを壊さない（仕様書 2.4）

既存の `config.yaml` の `auto_input.heal` などは**そのまま残す**。
プロフィールは「そこに書かれた値をキャラクターごとに上書きする」形で効く。
プロフィールが無い環境では、これまでとまったく同じ挙動になる。
"""

from .models import (
    CHARACTER_IDS, CHARACTER_LABELS, FIELDS, FallbackAction, Role, SpellPolicy,
)
from .profile import TacticsProfile
from .profile_repository import TacticsRepository
from .profile_validator import Result, validate_profile, validate_raw

__all__ = [
    "CHARACTER_IDS", "CHARACTER_LABELS", "FIELDS",
    "FallbackAction", "Role", "SpellPolicy",
    "TacticsProfile", "TacticsRepository",
    "Result", "validate_profile", "validate_raw",
]
