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

import datetime
import sys

from dq3 import paths as P3
from retroux.tools import savestate_backup as _dq2

#: ★DQ3 で保つ世代数（依頼者 2026-09-20「保持 100」/ RX3-0307）。
#   ⚠ スロットごとに 100。全部で 100 ではない（★上の註）。
DQ3_GENERATIONS = 100

#: ⚠ 世代数を指定する引数の書き方（★argparse は前置きの省略も受ける）。
_GENERATIONS_FLAG = "--generations"

#: ⚠ セーブステートの元を指定する引数（★`retroux/tools/savestate_backup.py:277`）
_SRC_FLAG = "--src"

#: ⚠⚠ 控えが空振りしたことを残す場所（★画面に出ない起動でも後から分かるように）
WARN_LOG = P3.lazy_work("dq3-log", "savestate-backup.log")


def with_src(argv: list[str]) -> list[str]:
    """★FCEUX の `fcs/` を `--src` に足す（RX3-0468 / 2026-09-29）。

    ⚠⚠ **FCEUX を外部指定すると、セーブステートも一緒に動きます**
      （★FCEUX は exe の隣の `fcs/` に書く / RX-0108）。
      ⚠ ここを足さないと、あちらの既定（同梱 `tools/fceux/fcs`）を見続け、
        **控えが静かに空振りします**。

    ★人が自分で `--src` を書いていたら触りません（⚠ 意図を上書きしない）。
    ⚠ 場所が分からないときは足しません（★でたらめな道を渡さない）。
    """
    for arg in argv:
        if arg.split("=", 1)[0] == _SRC_FLAG:
            return list(argv)
    fcs = P3.fceux_fcs()
    if fcs is None:
        return list(argv)
    return [_SRC_FLAG, str(fcs), *argv]


def warn_if_no_savestates(write=None) -> str | None:
    """⚠⚠ 控えの元が取れないときに**必ず知らせる**（依頼者 2026-09-29 §7）。

    ★「成功したように見えるがバックアップしていない」を禁止するための入口です。
    ⚠ 画面の無い起動（`pythonw`）でも後から分かるように、**記録にも残します**。

    戻り値: 出した言葉（⚠ 問題が無ければ `None`）。
    """
    message = P3.fcs_warning()
    if message is None:
        return None
    line = "%s %s" % (datetime.datetime.now().isoformat(timespec="seconds"), message)
    print(line, file=sys.stderr)
    try:
        target = (write if write is not None else WARN_LOG)
        import pathlib

        target = pathlib.Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # ⚠ 改行は LF で足す（★元の改行を混ぜない / RX-0121）
        with open(target, "a", encoding="utf-8", newline="") as fh:
            fh.write(line + "\n")
    except OSError:
        pass                                   # ⚠ 記録できなくても起動は止めない
    return message


def note(line: str, write=None) -> str:
    """★控えまわりの出来事を 1 行残す（RX3-0479 / 2026-10-01）。

    ## ⚠⚠ なぜ要るか

    `dq3/ui/main_window.py::_stop_own_backup()` は **3 つの道すべてで
    静かに `False` を返して**いました。★そのため「止めようとしたが止めなかった」と
    「そもそも止める相手が居なかった」を、⚠ **あとから区別できません**でした
    （2026-09-30 の実機で控えが止まらなかった件 / `RX3-0479`）。

    ⚠ 画面の無い起動（`pythonw`）では標準出力が捨てられるので、★記録に残します。
    ⚠⚠ ここで落ちても**閉じることは続けます**（★後始末で落ちない）。
    """
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    body = "%s %s" % (stamp, line)
    try:
        import pathlib

        target = pathlib.Path(write if write is not None else WARN_LOG)
        target.parent.mkdir(parents=True, exist_ok=True)
        # ⚠ 改行は LF で足す（★元の改行を混ぜない / RX-0121）
        with open(target, "a", encoding="utf-8", newline="") as fh:
            fh.write(body + "\n")
    except OSError:
        pass                                   # ⚠ 記録できなくても止めない
    return body


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
    # ⚠⚠ 先に知らせる（★空振りしていることに気づけないのが一番悪い / RX3-0468）
    warn_if_no_savestates()
    saved = sys.argv
    sys.argv = [saved[0], *with_src(with_generations(given))]
    try:
        return _dq2.main()
    finally:
        sys.argv = saved


if __name__ == "__main__":
    raise SystemExit(main())
