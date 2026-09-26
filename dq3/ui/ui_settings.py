"""画面の小さな設定を残す（RX3-0059 / 2026-09-02 依頼者「チェックボックスの選択が保存されるべき」）。

★保存先は `work/dq3-ui-settings.json`（★窓の位置 `work/window-state.json` と同じ考え: 遊びの記録ではなく画面の状態）。
⚠ `config/*.yaml` / `user_config.yaml` は人が書く設定なので、画面から書き換えない。

```json
{"admin": {"playdata_items": ["seen", "memos", "monsters"]},
 "automation": {"hearing_turbo": true, "move_turbo": true}}
```

⚠ `admin.speed_on_nav`（旧「街内の省力操作は 400%・無音」）は RX3-0170 で deprecated。
⚠ `automation.hearing_turbo` / `move_turbo`（管理画面の「高速実行」）も RX3-0259 で外した → ★どちらももう読まない（残っていても害は無い）。
"""
from __future__ import annotations

import json
import pathlib

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_PATH = paths.lazy_work("dq3-ui-settings.json")


class UiSettings:
    def __init__(self, path=None) -> None:
        self.path = pathlib.Path(path) if path else DEFAULT_PATH
        self.data: dict = self._load()

    def _load(self) -> dict:
        try:
            got = json.loads(self.path.read_text(encoding="utf-8"))
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, section: str, key: str, default=None):
        sec = self.data.get(section)
        if not isinstance(sec, dict):
            return default
        return sec.get(key, default)

    def set(self, section: str, key: str, value) -> None:
        """★覚えてすぐ書く（⚠ 書けなくても落とさない）。"""
        self.data.setdefault(section, {})[key] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass
