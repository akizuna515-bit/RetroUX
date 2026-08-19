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
import sys

from ..core.config import user_config as user_config_mod
from ..core.single_instance import RecorderLock


# どの役目を見るか -> user_config の paths のキー
_LOCKS = {
    "ingest": "lock",         # events.jsonl の取り込み（record / gui）
    "backup": "backup_lock",  # セーブステートの世代バックアップ
}


def status(config: str | None, what: str = "ingest") -> int:
    """その役目のプロセスが動いていれば BUSY、いなければ FREE を出す。"""
    cfg, warnings = user_config_mod.load(config)
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)
    busy = RecorderLock(cfg.path(_LOCKS[what])).is_active()
    print("BUSY" if busy else "FREE")
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
    args = parser.parse_args(argv)

    if args.command == "status":
        return status(args.config, args.what)
    return rotate_log(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
