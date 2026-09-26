"""倒したことのある敵を Lua へ渡す（RX3-0166 / 2026-09-11）。

★戦闘の高速化（`dq3/phase0/battle_speed.lua`）は、**初見の敵がいる戦闘を速くしません**。
その「初見か」を決める材料が、Python の `EnemyBook`（`work/dq3-knowledge/enemy-names.json`）です。

```text
EnemyBook.defeated  ──write_overlay──►  work/generated/dq3_enemy_book.lua
                                             ★Lua は戦闘の頭で 1 回だけ読む（⚠ この戦闘で覚える前）
```

⚠ 渡すのは**敵の番号だけ**です（★名前も能力も渡さない / No-Spoiler）。
⚠ 「会っただけ（倒していない）」は初見と同じに扱います（★前に逃げた相手 / DQ2 の「警戒中」）。
"""
from __future__ import annotations

import pathlib

from .. import paths as P3

OVERLAY_NAME = "dq3_enemy_book.lua"


def overlay_path(out_dir: pathlib.Path | None = None) -> pathlib.Path:
    return pathlib.Path(out_dir or P3.work("generated")) / OVERLAY_NAME


def _set_lua(ids) -> str:
    keys = sorted({int(i) for i in ids or ()})
    return "{" + ", ".join("[%d] = true" % k for k in keys) + "}"


def overlay_lua(book) -> str:
    """★Lua の表（`{defeated = {...}, met = {...}}`）。⚠ 無い本でも空の表を返す。"""
    defeated = getattr(book, "defeated", ()) if book is not None else ()
    met = getattr(book, "met", ()) if book is not None else ()
    return ("-- ★生成物（dq3/phase0/enemy_book_overlay.py）。⚠ 手で書かない\n"
            "return {defeated = %s, met = %s}\n" % (_set_lua(defeated), _set_lua(met)))


def write_overlay(book, out_dir: pathlib.Path | None = None) -> pathlib.Path:
    """★書く（⚠ 途中を読まれないよう、一時ファイル → 置き換え）。"""
    path = overlay_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".lua.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(overlay_lua(book))
    tmp.replace(path)
    return path


__all__ = ["OVERLAY_NAME", "overlay_path", "overlay_lua", "write_overlay"]
