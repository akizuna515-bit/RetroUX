"""モンスターの絵を ROM から自動展開する（RX-0086 / 2026-08-20）。

## ⚠ なぜ要るか（★公開クローンで実際に起きた）

RetroUX の「出会った敵」の絵は `work/monster-art-rom/`（`dq2rom monsters
install` の出力）から読む。⚠ `work/` は Git 管理外なので、**clone した
だけの環境には絵が1枚も無く、モンスターが表示されない**（依頼者の指摘）。

★そこで起動スクリプト（`start-retroux.ps1`）が毎回これを呼ぶ:
  - 絵がそろっていれば何もしない（1行出して終わり。数ms）
  - ROM が無ければ何もしない（★ROM を置けば次回そろう、と伝える）
  - 絵が無く ROM があれば `dq2rom monsters install` を実行する（初回のみ）

## ⚠ 失敗しても起動を止めない

絵は図鑑の表示だけの機能で、ゲームの進行・自動戦闘には関係ない。
展開に失敗したら理由を1行出して**そのまま起動を続ける**。
"""

from __future__ import annotations

import pathlib
import sys

#: RetroUX が ROM 由来の絵を読む場所（`gui.py` の既定と同じ）。
ART_ROM_DIR = "work/monster-art-rom"


def plan(rom_exists: bool, art_count: int) -> str:
    """何をすべきか（★純ロジック）。

    - "skip"    … 絵がそろっている（何もしない）
    - "no-rom"  … ROM が無い（展開できない。⚠ 黙らず1行出す）
    - "install" … 絵が無く ROM がある（初回。展開する）
    """
    if art_count > 0:
        return "skip"
    if not rom_exists:
        return "no-rom"
    return "install"


def main(argv: list[str] | None = None) -> int:
    from ..core.config import user_config

    cfg, _notes = user_config.load()
    rom = pathlib.Path(cfg.paths.rom)
    into = pathlib.Path(ART_ROM_DIR)
    art_count = len(list(into.glob("*.png"))) if into.is_dir() else 0

    what = plan(rom.exists(), art_count)
    if what == "skip":
        print(f"モンスターの絵: そろっています（{art_count} 枚）")
        return 0
    if what == "no-rom":
        print(f"モンスターの絵: ROM が見つからないため展開できません（{rom}）。"
              "★ROM を置けば次回の起動で自動展開します")
        return 0

    print("モンスターの絵: 初回展開します（ROM -> work/monster-art-rom）...")
    try:
        from dq2rom.cli import main as dq2rom_main
        rc = dq2rom_main(["monsters", "install", "--rom", str(rom),
                          "--into", str(into)])
    except Exception as exc:                           # noqa: BLE001
        print(f"モンスターの絵: 展開に失敗しました（起動は続けます）: {exc}")
        return 0
    if rc != 0:
        # ⚠ 絵は表示だけの機能。失敗しても起動を止めない（理由は上の docstring）
        print(f"モンスターの絵: 展開が失敗しました（exit={rc}）。起動は続けます")
        return 0
    done = len(list(into.glob("*.png"))) if into.is_dir() else 0
    print(f"モンスターの絵: 展開しました（{done} 枚）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
