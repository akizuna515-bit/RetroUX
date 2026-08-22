"""地図の記録から、記録の不具合で入った行を消す（2026-07-30）。

★★ **利用者のデータを消すので、明示的に実行したときだけ動く。** ★★
  取り込みや描画の副作用では絶対に呼ばれません。
  既定は**数えるだけ**で、消すには `--apply` が要ります。

## 何を消すのか

記録側に2つの不具合があり、実データに残っています（どちらも修正済み）。

| # | 何 | どうして入ったか | 実データでの量 |
| --- | --- | --- | --- |
| 1 | **マップの外のマス** | `map_x + dx` を切らずに記録していた。座標は1バイト（`$16`/`$17`）なので x/y が 255 を超えることはありえない | 345 マス |
| 2 | **`map_id` とデータ位置が食い違う記録** | マップの切り替わりの瞬間に `$31` と `$23-$24` が食い違ったまま**1回だけ**記録された。各 225 マス（15×15 = 記録1回ぶん）ちょうど | 790 マス |

2 は地図の一覧に「幽霊のような項目」として並びます（依頼者の画面で確認）。

## 使い方

    .venv\\Scripts\\python.exe -m retroux.tools.map_prune            # 数えるだけ
    .venv\\Scripts\\python.exe -m retroux.tools.map_prune --apply    # 消す
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _out(text: str = "") -> None:
    print(text)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="地図の記録から、記録の不具合で入った行を消す")
    parser.add_argument("--apply", action="store_true",
                        help="実際に消す（付けないと数えるだけ）")
    parser.add_argument("--config", default=None, help="user_config.yaml のパス")
    args = parser.parse_args(argv)

    from ..core.config import user_config as user_config_mod
    from ..core.db.database import Database
    from ..gui import _load_map_meta, _load_yaml
    from ..ui.map_window import load_map_meta

    user_cfg, _warn = user_config_mod.load(args.config)
    config = _load_yaml(PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml")
    meta = _load_map_meta(config)
    overworld = (int((config.get("map") or {}).get("overworld_width", 256)),
                 int((config.get("map") or {}).get("overworld_height", 256)))
    del load_map_meta

    db_path = user_cfg.path("db")
    if not db_path.exists():
        _out(f"✗ DB がありません: {db_path}")
        return 1
    _out(f"DB: {db_path}")
    if not meta:
        _out("⚠ maps.json が無いので、マップの大きさと食い違いを判断できません。")
        _out("   ROM を置いて RetroUX を一度起動すれば自動生成されます（retroux.tools.map_meta_setup）。")
        return 1

    db = Database(db_path)
    try:
        rom_rows = db._conn.execute("SELECT rom_hash FROM Rom").fetchall()
        outside = mismatch = 0
        for rom in rom_rows:
            rom_hash = rom["rom_hash"]
            for map_id, map_ptr, count in db.visited_maps(rom_hash):
                info = meta.get(map_id) or {}
                # --- 1. データ位置の食い違い ---
                want = info.get("data_pointer")
                if want:
                    try:
                        want_int = int(str(want), 16)
                    except ValueError:
                        want_int = None
                    if want_int is not None and want_int != map_ptr:
                        _out(f"  食い違い  map {map_id:02X}: 表 0x{want_int:04X} ≠ "
                             f"記録 0x{map_ptr:04X}  ({count} マス)")
                        mismatch += count
                        if args.apply:
                            db.delete_visited(rom_hash, map_id, map_ptr)
                        continue
                # --- 2. マップの外 ---
                if info.get("type") == "overworld":
                    width, height = overworld
                else:
                    width, height = info.get("width"), info.get("height")
                if not width or not height:
                    continue          # ★大きさが分からないマップは触らない
                over = [t for t in db.visited_tiles(rom_hash, map_id, map_ptr)
                        if t[0] >= width or t[1] >= height]
                if over:
                    _out(f"  枠の外    map {map_id:02X} (0x{map_ptr:04X}): "
                         f"{len(over)} マス（{width}×{height} の外）")
                    outside += len(over)
                    if args.apply:
                        db.delete_visited_outside(rom_hash, map_id, map_ptr,
                                                  width, height)
        _out()
        _out(f"枠の外 {outside} マス / 食い違い {mismatch} マス")
        if args.apply:
            _out("★消しました。")
        elif outside or mismatch:
            _out("★数えただけです。消すには --apply を付けてください。")
        else:
            _out("★消すものはありませんでした。")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
