"""ずれたタイルIDで集めた記録を捨てる（2026-08-01 / 課題 #65）。

★★ **利用者のデータを消すので、明示的に実行したときだけ動く。** ★★
  取り込みや描画の副作用では絶対に呼ばれません。
  既定は**数えるだけ**で、消すには `--apply` が要ります。

## なぜ捨てるのか

ネームテーブル `$2000` を読むとき、**スクロール量を足していませんでした**。
`$2000` は 32×30 の固定の入れ物で、画面はその中を巡回して映すため、
足さずに読んだタイルIDは**別の場所のID**です。

  マスごとの照合: 足さない 459/704 (65%) -> ★足した 695/704 (98%)

つまり、これまで集めた「タイルID」と「そのIDの絵」は、**中身と名前が
食い違っています**。残したまま新しい記録を足すと、正しいものと間違った
ものが混ざり、原因を追えなくなります。

⚠ 歩けば自動で溜まり直します。**失うのは手間だけ**です。

## 何を消すのか（★歩いた記録そのものは消しません）

| 対象 | 中身 |
| --- | --- |
| `VisitedTile.tile` 列 | ずれたタイルID。★`NULL` に戻すだけ |
| `work/generated/tile_art.txt` | ずれたIDに紐づいたタイルの絵 |

★ 訪問記録（どこを歩いたか）は **1行も消しません**。

## 使い方

    .venv\\Scripts\\python.exe -m retroux.tools.tile_reset            # 数えるだけ
    .venv\\Scripts\\python.exe -m retroux.tools.tile_reset --apply    # 捨てる
"""

from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: タイルの絵の置き場所（`bridge.lua:_dump_tile_art` が追記する）
ART_PATH = PROJECT_ROOT / "work" / "generated" / "tile_art.txt"


def _out(text: str = "") -> None:
    print(text)


def _count_playing() -> int | None:
    """遊んでいる印（RetroUX の GUI / FCEUX）がいくつ動いているか数える。

    ★数えるだけにしてあるのは、**テストから差分で測れる**ようにするため。
      「動いている／いない」だけを返す形にしていたら、下のやらかしを
      テストで捕まえられなかった（skip されて素通りした）。

    数えられなければ `None`（★分からないものを 0 と混ぜない）。
    """
    import subprocess

    # ⚠⚠ **`*retroux*` で数えてはいけない**（2026-08-01 に実際にやらかした）。
    #   この道具自身が `python -m retroux.tools.tile_reset` なので、
    #   **自分を数えて**「2個動いています」と言い、永久に実行できなくなる。
    # ★数えるのは「遊んでいる印」だけ:
    #     retroux.gui   … GUI 本体（evidence.py と同じ絞り方）
    #     fceux64.exe   … エミュレータ（tile_art.txt へ追記している当人）
    try:
        out = subprocess.run(
            [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
             "-NoProfile", "-Command",
             "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe' or "
             "Name='pythonw.exe' or Name='fceux64.exe'\" | Where-Object { "
             "$_.CommandLine -like '*retroux.gui*' -or "
             "$_.Name -eq 'fceux64.exe' }).Count"],
            capture_output=True, text=True, timeout=30,
            creationflags=0x08000000)
        return int((out.stdout or "0").strip() or 0)
    except Exception:                                  # noqa: BLE001
        return None                                    # ★数えられなかった


def _someone_is_playing() -> str | None:
    """⚠⚠ **人が遊んでいる最中に走らせない**。

    `tile_art.txt` は動いている Lua が**追記中**です。その最中に消すと
    書きかけの行が残ります。DB も同じで、書き手が2人になります。

    ★止めるのではなく**教えて止まる**。判断は人がする。
    ⚠ 数えられなかったときは通す（分からないことを理由に止めない）。
    """
    count = _count_playing()
    if not count:
        return None
    return (f"⚠⚠ RetroUX / FCEUX が {count} 個動いています。\n"
            "   遊んでいる最中に消すと、書きかけの記録が壊れます。\n"
            "   ★終了してから実行してください。")


#: 控えの置き場所（2026-08-01）。
#:
#: ⚠⚠ **`work/generated/` に置いてはいけない。**
#:   `scripts/export-for-review.ps1` は `work/generated` を**丸ごと**
#:   相談用 ZIP に入れる。控えは「直す前の**間違ったデータ**」なので、
#:   相談相手がそれを解析してしまう（実際に 535KB 入って気づいた）。
#: ★`work/backups/` は書き出しの対象外。
BACKUP_DIR = PROJECT_ROOT / "work" / "backups"


def _backup(path: Path, stamp: str) -> Path | None:
    """★消す前に控えを取る。取れなければ**消さない**。"""
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"{path.name}.{stamp}-before-tile-reset"
    shutil.copy2(path, dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(
        description="ずれたタイルIDで集めた記録を捨てる（#65）")
    parser.add_argument("--apply", action="store_true",
                        help="実際に捨てる（付けないと数えるだけ）")
    parser.add_argument("--force", action="store_true",
                        help="⚠ 動作中でも実行する（既定は断る）")
    parser.add_argument("--config", default=None, help="user_config.yaml のパス")
    args = parser.parse_args(argv)

    if args.apply and not args.force:
        busy = _someone_is_playing()
        if busy:
            _out(busy)
            return 1

    from ..core.config import user_config as user_config_mod

    user_cfg, _warn = user_config_mod.load(args.config)
    db_path = user_cfg.path("db")
    if not db_path.exists():
        _out(f"✗ DB がありません: {db_path}")
        return 1
    _out(f"DB: {db_path}")

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        tiles = conn.execute(
            "SELECT COUNT(*) FROM VisitedTile WHERE tile IS NOT NULL"
        ).fetchone()[0]
        visited = conn.execute("SELECT COUNT(*) FROM VisitedTile").fetchone()[0]
        arts = 0
        if ART_PATH.exists():
            arts = sum(1 for line in ART_PATH.read_text(
                encoding="utf-8", errors="replace").splitlines() if "\t" in line)

        _out(f"  タイルIDのあるマス : {tiles}")
        _out(f"  タイルの絵         : {arts} 件  ({ART_PATH})")
        _out(f"  ★訪問記録         : {visited} マス（**消しません**）")
        _out()

        if not args.apply:
            if tiles or arts:
                _out("★数えただけです。捨てるには --apply を付けてください。")
            else:
                _out("★捨てるものはありませんでした。")
            return 0

        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M")
        db_bak = _backup(db_path, stamp)
        art_bak = _backup(ART_PATH, stamp)
        if db_bak:
            _out(f"控え: {db_bak.name}")
        if art_bak:
            _out(f"控え: {art_bak.name}")

        cur = conn.execute("UPDATE VisitedTile SET tile = NULL "
                           "WHERE tile IS NOT NULL")
        conn.commit()
        _out(f"★タイルIDを消しました: {cur.rowcount} マス")
        if ART_PATH.exists():
            ART_PATH.unlink()
            _out(f"★タイルの絵を消しました: {arts} 件")

        left = conn.execute("SELECT COUNT(*) FROM VisitedTile").fetchone()[0]
        _out(f"★訪問記録は {left} マスのまま（{visited} から変わらず）")
        if left != visited:
            _out("⚠⚠ 訪問記録が減りました。**想定外です。**控えから戻してください。")
            return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
