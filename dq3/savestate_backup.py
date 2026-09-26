"""DQ3 側のセーブステート控えの入口（RX3-0307 / 2026-09-21）。

依頼者 2026-09-20:

    セーブステート保持 100 のしたい。そうすれば実質どこでもセーブになる

★仕組みそのものは DQ2 のものを使います（`retroux/tools/savestate_backup.py`）。
⚠ あちらは**公開済み**なので 1 バイトも変えません（RX3-0011 / RX3-0022）。
→ ★ここは「DQ3 の既定は 100 世代」だけを足す**薄い入口**です。

## ⚠⚠ なぜ起動スクリプトに `--generations 100` を足すだけでは足りないのか

★世代数は**引数で渡すもの**で、`rotate_in()` が**その場で**古い世代を削ります。

```text
★控える側   scripts/start-dq3.ps1 が --generations 100 で常駐  → 100 世代たまる
⚠⚠ 戻す側   python -m retroux.tools.savestate_backup --restore  → **既定の 10**
             → rotate_in(..., generations=10) が list_generations()[10:] を消す
             → ★たまった 90 世代が**黙って消える**
```

⚠ `--once` でも同じです（★中身が変わったファイルだけですが、消えることに変わりはない）。
→ ★だから**入口を 1 つにします**。控えるときも一覧するときも戻すときも、
  DQ3 では `python -m dq3.savestate_backup` を通します。

## 使い方

    python -m dq3.savestate_backup            # 監視し続ける（★起動スクリプトが使う）
    python -m dq3.savestate_backup --once     # 1 回だけ
    python -m dq3.savestate_backup --list     # 控えを一覧する
    python -m dq3.savestate_backup --restore DQ3_J.fc0 --gen 3

⚠ 引数は DQ2 の道具にそのまま渡ります（★`--help` もあちらのものが出ます）。

## ★100 は「スロットごと」です

⚠ 世代は**ファイル名ごと**のフォルダに積まれます（`work/savestate-backup/DQ3_J.fc0/`）。
★「全部で 100」にすると、よく使うスロットが**他のスロットの世代を押し出す**ので、
「あのときへ戻る」という目的を果たしません。
⚠ 容量は実測で 1 世代 13KB 前後（★100 世代 × 21 ファイル名でも 27MB 程度）。
"""

from __future__ import annotations

import sys

from retroux.tools import savestate_backup as _dq2

#: ★DQ3 で保つ世代数（依頼者 2026-09-20「保持 100」/ RX3-0307）。
#   ⚠ スロットごとに 100。全部で 100 ではない（★上の註）。
DQ3_GENERATIONS = 100

#: ⚠ 世代数を指定する引数の書き方（★argparse は前置きの省略も受ける）。
_GENERATIONS_FLAG = "--generations"


def with_generations(argv: list[str], generations: int = DQ3_GENERATIONS) -> list[str]:
    """DQ3 の既定（100 世代）を足した引数を返す。

    ★人が自分で世代数を書いていたら**触りません**（⚠ 意図を上書きしない）。

    ⚠ 足すときは**前へ**置きます。argparse は後から来たものを採るので、
      `--generation 5` のような省略形で書かれていても**人の指定が勝ちます**。
    """
    for arg in argv:
        # ★`--generations 100` と `--generations=100` の両方を見る。
        #   ⚠ argparse の省略形（`--generation`）も拾う。前置きで一致すれば人の指定とみなす。
        head = arg.split("=", 1)[0]
        if head.startswith("--gener") and _GENERATIONS_FLAG.startswith(head):
            return list(argv)
    return [_GENERATIONS_FLAG, str(generations), *argv]


def main(argv: list[str] | None = None) -> int:
    """DQ2 の道具を、DQ3 の既定で呼ぶ。

    ⚠ あちらの `main()` は引数を受け取らず `sys.argv` を読みます（★公開済みなので
      そのままにします）。→ ★ここで `sys.argv` を差し替えて呼び、必ず戻します。
    """
    given = list(sys.argv[1:] if argv is None else argv)
    saved = sys.argv
    sys.argv = [saved[0], *with_generations(given)]
    try:
        return _dq2.main()
    finally:
        sys.argv = saved


if __name__ == "__main__":
    raise SystemExit(main())
