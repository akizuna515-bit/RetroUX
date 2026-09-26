"""検査が使うセーブステートの置き場（RX-0135 案 A / 2026-09-07）。

## ⚠⚠ なぜ要るか

  ★依頼者は `tools/fceux/fcs/DQ3_J.fc*` を**遊びながら上書き**します（⚠ 当然の使い方）。
  ⚠ 検査はそれを資料として読んでいるので、★遊ぶたびに赤くなります
  （2026-08-31 に 10 件 / 2026-09-07 に 6 件。⚠ どちらも回帰ではない）。

  → ★**固定した写し**を使います。⚠ 遊んでも動きません。

```text
work/test-savestates/     ★固定した写し（⚠ Git の外 / 大きさは 1 本 12KB ほど）
tools/fceux/fcs/          ⚠ 依頼者が遊ぶ本物（★写しが無いときだけ使う）
```

## ★写しを作り直すとき

    PYTHONUTF8=1 python scripts/pin_savestates.py

⚠ 「いまのセーブで検査が通る」ことを**確かめてから**にしてください。
★写しを更新するのは「新しいセーブを正とする」という判断です。
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
#: ★固定した写し（⚠ Git の外）
PINNED = ROOT / "work" / "test-savestates"
#: ⚠ 依頼者が遊ぶ本物（★写しが無いときだけ）
LIVE = ROOT / "tools" / "fceux" / "fcs"


def states_dir() -> pathlib.Path:
    """★セーブを読む場所（⚠ 写しがあれば写し）。"""
    try:
        if PINNED.is_dir() and any(PINNED.glob("*.fc*")):
            return PINNED
    except OSError:
        pass
    return LIVE


def is_pinned() -> bool:
    return states_dir() == PINNED
