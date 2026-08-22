"""マップの大きさ表（maps.json）を ROM から自動生成する（RX-0093 / 2026-08-21）。

## ⚠ なぜ要るか（★公開クローンで実際に起きた）

地図ウィンドウは `work/map-data/maps.json`（`dq2rom maps export` の出力）から
「各マップの種別・大きさ・データ位置」を読む。⚠ `work/` は Git 管理外なので、
**clone しただけの環境には無い**。無くても動く設計だが、挙動が変わる:

  - 世界地図が「overworld」と分からず、街扱いで**歩いた範囲だけ**を枠に収める
    （開発環境では 256×256 を倍率2で固定表示。依頼者が見比べて気づいた）
  - マップの食い違い判定（`map_matches_pointer`）が素通しになる

★RX-0086（モンスターの絵）とまったく同じ構図。同じ形で起動のたびに呼ぶ:
  - `maps.json` があれば何もしない（1行出して終わり）
  - ROM が無ければ何もしない（★ROM を置けば次回そろう、と伝える）
  - 無く ROM があれば `dq2rom maps export --out work/map-data` を実行し、
    `work/map-data/<sha1>/maps.json` を `work/map-data/maps.json` へ複製する
    （⚠ RetroUX が読むのは平置きの方。`config.yaml map.meta_path`）

## ⚠ 失敗しても起動を止めない

地図は表示だけの機能で、自動戦闘には関係ない。失敗したら理由を1行出して続ける。
"""

from __future__ import annotations

import pathlib
import shutil
import sys

#: RetroUX が読む場所（`config.yaml map.meta_path` の既定と同じ）。
MAP_DATA_DIR = "work/map-data"
META_NAME = "maps.json"


def plan(rom_exists: bool, meta_exists: bool) -> str:
    """何をすべきか（★純ロジック）。

    - "skip"   … maps.json がある（何もしない）
    - "no-rom" … ROM が無い（作れない。⚠ 黙らず1行出す）
    - "export" … 無く ROM がある（初回。作る）
    """
    if meta_exists:
        return "skip"
    if not rom_exists:
        return "no-rom"
    return "export"


def find_exported(out_dir: pathlib.Path) -> pathlib.Path | None:
    """`dq2rom maps export` が書いた `<sha1>/maps.json` を見つける（最新の1つ）。"""
    hits = sorted(out_dir.glob(f"*/{META_NAME}"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def main(argv: list[str] | None = None) -> int:
    from ..core.config import user_config

    cfg, _notes = user_config.load()
    rom = pathlib.Path(cfg.paths.rom)
    out_dir = pathlib.Path(MAP_DATA_DIR)
    meta = out_dir / META_NAME

    what = plan(rom.exists(), meta.is_file())
    if what == "skip":
        print(f"マップの大きさ表: あります（{meta}）")
        return 0
    if what == "no-rom":
        print(f"マップの大きさ表: ROM が見つからないため作れません（{rom}）。"
              "★ROM を置けば次回の起動で自動生成します")
        return 0

    print("マップの大きさ表: 初回生成します（ROM -> work/map-data/maps.json）...")
    try:
        from dq2rom.cli import main as dq2rom_main
        rc = dq2rom_main(["maps", "export", "--rom", str(rom), "--out", str(out_dir)])
    except Exception as exc:                           # noqa: BLE001
        print(f"マップの大きさ表: 生成に失敗しました（起動は続けます）: {exc}")
        return 0
    if rc != 0:
        print(f"マップの大きさ表: 生成が失敗しました（exit={rc}）。起動は続けます")
        return 0
    src = find_exported(out_dir)
    if src is None:
        print("マップの大きさ表: 出力が見つかりません（起動は続けます）")
        return 0
    try:
        shutil.copyfile(src, meta)
    except OSError as exc:
        print(f"マップの大きさ表: 複製に失敗しました（起動は続けます）: {exc}")
        return 0
    print(f"マップの大きさ表: 生成しました（{meta}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
