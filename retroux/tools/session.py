"""起動スクリプトから使う小さなコマンド群（MVP2 Phase 1）。

    python -m retroux.tools.session status       # 取り込みプロセスの有無
    python -m retroux.tools.session rotate-log   # 今回から新しいログ世代にする

★なぜ独立したコマンドにするか:

  最初は起動スクリプトから `python -c "..."` で直接書いていたが、
  **Windows PowerShell から native exe へ引用符を渡すと壊れる**。
  実際に `cfg.path("lock")` が `cfg.path(lock)` になって
  `NameError: name 'lock' is not defined` で落ちた。

  引用符を含む処理は**モジュール側に置いて名前で呼ぶ**。
  こうすればシェルの引用符規則に依存しないし、テストもできる。

★判定は Python 側と同じコードを使う。起動スクリプトに同じ判定を書き写すと、
  片方だけ直したときに静かにずれる。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from ..core.config import user_config as user_config_mod
from ..core.single_instance import RecorderLock


# どの役目を見るか -> user_config の paths のキー
_LOCKS = {
    "ingest": "lock",         # events.jsonl の取り込み（record / gui）
    "backup": "backup_lock",  # セーブステートの世代バックアップ
}


def status(config: str | None, what: str = "ingest", who: bool = False,
           out: str | None = None) -> int:
    """その役目のプロセスが動いていれば BUSY、いなければ FREE を出す。

    ★`who=True` なら**代わりに**「誰が握っているか」の1行を出す（RX-0064）。
      ⚠ BUSY/FREE の行に足さない。起動スクリプトが**丸ごと文字列比較**しているので、
        1文字でも増やすと判定が壊れる（★実際にそういう作りになっている）。
    """
    cfg, warnings = user_config_mod.load(config)
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)
    lock = RecorderLock(cfg.path(_LOCKS[what]))
    if who:
        said = lock.holder().describe()
        if out:
            # ★★ ⚠⚠ **日本語は標準出力で渡さない**（2026-08-22 実測 / RX-0064）★★
            #   PowerShell 5.1 は native exe の出力を `[Console]::OutputEncoding`
            #   （既定 cp932）で復号するので、UTF-8 の日本語が化ける
            #   （「最終心拍 0.4 秒前」→「譛邨ょｿ・牛 0.4 遘貞燕」）。
            #   ★`[Console]::OutputEncoding` の差し替えはコンソールが無い起動で
            #     効かないことがあった（実測）。**ファイル経由が確実**。
            path = pathlib.Path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(said, encoding="utf-8")
            return 0
        print(said)
        return 0
    print("BUSY" if lock.is_active() else "FREE")
    return 0


def rotate_log(config: str | None) -> int:
    """いまのログを .1 へ送り、次の書き込みから新しいファイルにする。

    ★サイズによる世代分けは Python 側の RotatingFileHandler が自動で行う。
      これは「今回の実行ぶんだけ切り分けたい」ときの手動操作。

    ⚠ FCEUX が動いている最中に呼ばない。Lua は**書くたびに開き直す**ので
      壊れはしないが、1回の実行のログが2つのファイルに分かれて読みにくい。
    """
    cfg, warnings = user_config_mod.load(config)
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)

    log = cfg.path("log")
    if not log.exists() or log.stat().st_size == 0:
        print("ログはまだありません。")
        return 0

    # 古い世代から順に押し出す（.4 -> .5, .3 -> .4, ...）
    for i in range(cfg.logging.backup_count - 1, 0, -1):
        src = log.with_name(f"{log.name}.{i}")
        dst = log.with_name(f"{log.name}.{i + 1}")
        if src.exists():
            dst.unlink(missing_ok=True)
            src.rename(dst)
    log.rename(log.with_name(f"{log.name}.1"))
    print(f"前回までのログを {log.name}.1 へ送りました。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RetroUX の起動補助")
    parser.add_argument("command", choices=["status", "rotate-log"])
    parser.add_argument("--what", choices=sorted(_LOCKS), default="ingest",
                        help="status で見る役目（既定: ingest）")
    parser.add_argument("--config", default=None, help="user_config.yaml のパス")
    # ★誰が握っているか（RX-0064）。⚠ BUSY/FREE とは**別の出力**にする
    parser.add_argument("--who", action="store_true",
                        help="BUSY/FREE の代わりに、握っている相手を1行で出す")
    # ★日本語は標準出力に出さずファイルへ（PowerShell の復号が cp932 のため）
    parser.add_argument("--out", default=None,
                        help="--who の結果を UTF-8 でこのファイルへ書く（標準出力に出さない）")
    args = parser.parse_args(argv)

    if args.command == "status":
        return status(args.config, args.what, who=args.who, out=args.out)
    return rotate_log(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
