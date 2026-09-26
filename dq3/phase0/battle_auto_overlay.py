"""★戦闘開始時 自動 / 手動（倒したことのある敵とは自動で戦うか）— 画面の設定を Lua へ渡す（2026-09-11 依頼者）。

★2026-09-13（RX3-0237）: 画面は管理画面のチェックから、戦闘AI設定画面の「戦闘開始時 自動 / 手動」へ移した（★鍵は同じ）。

```text
画面（戦闘AI設定「戦闘開始時」）→ work/dq3-ui-settings.json の automation.battle_auto_known
                              → ★ここ → work/generated/dq3_battle_auto.lua → auto_v0.lua が戦闘ごとに読む
```

⚠ 画面で変えていなければ書かない（★YAML の `auto_battle.auto_start_known` が効く）。
⚠ `work/generated/` は生成物。⚠ 手で書かない。
"""
from __future__ import annotations

import pathlib

from .. import paths as P3

OVERLAY_NAME = "dq3_battle_auto.lua"
SECTION = "automation"
KEY = "battle_auto_known"


def enabled(settings) -> bool | None:
    """★画面の設定（⚠ 画面で決めていなければ None ＝ YAML の既定に任せる）。"""
    if settings is None:
        return None
    try:
        got = settings.get(SECTION, KEY, None)
    except Exception:                                            # noqa: BLE001
        return None
    return got if isinstance(got, bool) else None


def overlay_path(out_dir: pathlib.Path | None = None) -> pathlib.Path:
    return pathlib.Path(out_dir or P3.work("generated")) / OVERLAY_NAME


def overlay_lua(on: bool | None) -> str:
    body = "" if on is None else ("auto_known = %s" % ("true" if on else "false"))
    return ("-- ★倒したことのある敵とは自動で戦うか（画面の設定）。⚠ 手で書かない（画面が作り直します）\n"
            "return {%s}\n" % body)


def write_overlay(settings, out_dir: pathlib.Path | None = None) -> pathlib.Path:
    """★auto_v0 が次の戦闘で読む（⚠ 途中で書き換わらないよう一時ファイル → 置き換え）。"""
    path = overlay_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".lua.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(overlay_lua(enabled(settings)))
    tmp.replace(path)
    return path


__all__ = ["OVERLAY_NAME", "SECTION", "KEY", "enabled", "overlay_path", "overlay_lua", "write_overlay"]
