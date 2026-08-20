"""FCEUX の映像倍率（窓の大きさ）を fceux.cfg に設定する（2026-08-20 / UAT）。

★★ **`--xscale/--yscale` は窓サイズを変えない**（実測: no-flag も --xscale2 も
  528x507）。窓の倍率は fceux.cfg の `winsizemulx` / `winsizemuly`（8バイトの
  倍精度小数を base64 で格納）が制御する。ここを起動前に書き換える。

- 例: 2倍 → `winsizemulx base64:AAAAAAAAAEA=`（AAAAAAAAAEA= は little-endian の 2.0）
- ⚠ 起動前（FCEUX が動いていないとき）に書く。FCEUX は起動時に読み、終了時に
  書き戻すので、一度設定すれば残る。
- ⚠ cfg が無ければ最小限の2行を作る（FCEUX が初回起動で残りを埋める）。
"""

from __future__ import annotations

import base64
import re
import struct
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CFG = PROJECT_ROOT / "tools" / "fceux" / "fceux.cfg"

_KEYS = ("winsizemulx", "winsizemuly")


def encoded(scale: float) -> str:
    """倍率を fceux.cfg 用の `base64:...` へ（little-endian double）。"""
    return "base64:" + base64.b64encode(
        struct.pack("<d", float(scale))).decode("ascii")


def set_scale(cfg_path: Path, scale: float) -> str:
    """winsizemulx/y を `scale` に設定する。戻り値は状況の一言。"""
    value = encoded(scale)
    text = cfg_path.read_text(encoding="utf-8", errors="replace") \
        if cfg_path.is_file() else ""
    new = text
    for key in _KEYS:
        line = f"{key} {value}"
        pat = re.compile(rf"^{re.escape(key)}\b.*$", re.MULTILINE)
        if pat.search(new):
            new = pat.sub(line, new)
        elif new:
            new = new.rstrip("\r\n") + "\n" + line + "\n"
        else:
            new = line + "\n"
    if new != text:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        # ⚠ 改行変換を挟まない（FCEUX が読める形のまま書く）。
        cfg_path.write_text(new, encoding="utf-8", newline="")
        return f"FCEUX の映像倍率を x{scale:g} に設定しました（{cfg_path.name}）"
    return f"FCEUX の映像倍率は既に x{scale:g} です"


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scale", type=float, help="映像倍率（例 2）")
    ap.add_argument("--cfg", type=Path, default=DEFAULT_CFG)
    args = ap.parse_args(argv)
    print(set_scale(args.cfg, args.scale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
