"""移行のあとの作り直し（RX-0158 / 依頼 §13）。

★移行先に置いた**新しい版のプログラム**で動かす（★`-m` を移行先の cwd・PYTHONPATH で）。
⚠ 失敗は移行の失敗として扱う（★印を書かない = 起動しない）。

```text
generate_lua        work/generated/config.lua・memory_map.lua・keybindings.lua（★ROM があれば enemy_tables.json）
monster_art_setup   work/monster-art-rom/（★ROM と FCEUX の色見本があるとき）
map_meta_setup      work/map-data/maps.json（★ROM があるとき）
```

⚠ `tactics.lua`・`map_passability.json` は GUI の起動時に作られる（★ここでは作らない / 報告に書く）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MODULES = ("retroux.core.config.generate_lua", "retroux.tools.monster_art_setup",
           "retroux.tools.map_meta_setup")
ALWAYS = ("work/generated/config.lua", "work/generated/memory_map.lua", "work/generated/keybindings.lua")
WITH_ROM = ("work/generated/enemy_tables.json", "work/map-data/maps.json")
#: ★モンスターの絵の展開に要る FCEUX の色見本（`dq2rom monsters install` の既定）
PALETTE = "tools/fceux/palettes/FCEUX.pal"


def _rom_of(dest: Path) -> Path:
    env = {**os.environ, "PYTHONPATH": str(dest), "RETROUX_WRITE_ROOT": str(dest),
           "RETROUX_ROOT": str(dest), "PYTHONUTF8": "1"}
    done = subprocess.run([sys.executable, "-m", "retroux.core.dq2_paths", "--launch-json"],
                          cwd=str(dest), env=env, capture_output=True, timeout=120)
    try:
        return Path(json.loads((done.stdout or b"{}").decode("ascii", "replace"))["rom"])
    except (ValueError, KeyError):
        return dest / "work" / "rom" / "DQ2_J.nes"


def run(dest: Path, python: str | None = None) -> list[str]:
    """★移行先で作り直す。戻り値: 問題の一覧（★空なら成功）。"""
    dest = Path(dest)
    if not (dest / "retroux" / "core" / "dq2_paths.py").exists():
        return [f"移行先に新しい版のプログラムがありません（{dest}）"]
    env = {**os.environ, "PYTHONPATH": str(dest), "RETROUX_WRITE_ROOT": str(dest),
           "RETROUX_ROOT": str(dest), "PYTHONUTF8": "1"}
    problems: list[str] = []
    notes: list[str] = []
    for mod in MODULES:
        done = subprocess.run([python or sys.executable, "-m", mod], cwd=str(dest), env=env,
                              capture_output=True, timeout=600)
        if done.returncode != 0:
            tail = (done.stderr or done.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
            problems.append(f"{mod} が終了コード {done.returncode}: {' / '.join(tail)}")
    must = list(ALWAYS)
    if _rom_of(dest).exists():
        must += list(WITH_ROM)
        # ⚠ 絵の展開は FCEUX の色見本（palettes/FCEUX.pal）が要る（★2026-10-03 の実データで踏んだ）。
        #   FCEUX は移さない（J6）ので、置く前なら「置いたあとの起動で作られる」= 失敗にしない
        if (dest / PALETTE).exists() and not any((dest / "work" / "monster-art-rom").glob("*.png")):
            problems.append("work/monster-art-rom/ に絵がありません")
        elif not (dest / PALETTE).exists():
            notes.append(f"モンスターの絵は FCEUX（{PALETTE}）を置いたあとの起動で作られます")
    problems += [f"{rel} がありません" for rel in must if not (dest / rel).exists()]
    for note in notes:
        print(f"作り直し: {note}")
    return problems
