"""DQ2 のログの世代を手で送る（RX-0149 / D-42 J3）。

★`retroux/tools/session.py` の `rotate-log` の写しです（⚠ 共有ではありません）。
⚠ あちらは `user_config.yaml` の `paths.log`（＝旧 `work/retroux.log`。DQ3 の控えも書く）を送ります。
  ★DQ2 のログ（`work/runtime/dq2-log/retroux.log`）は、DQ2 の設定の読み手から決めます。
⚠ `session.py` は DQ3 の起動スクリプトも使うので変えません（J1）。

使い方（★起動スクリプトの `-NewLog` が呼ぶ）:

    python -m retroux.tools.dq2_log rotate
"""

from __future__ import annotations

import argparse
import sys

from ..core.config import dq2_user_config


def rotate(config: str | None = None) -> int:
    """いまのログを .1 へ送り、次の書き込みから新しいファイルにする。

    ★サイズによる世代分けは Python 側の RotatingFileHandler が自動で行う。これは「今回の実行ぶんだけ切り分けたい」ときの手動操作。
    ⚠ FCEUX が動いている最中に呼ばない（★Lua は書くたびに開き直すので壊れはしないが、1 回の実行が 2 つに分かれる）。
    """
    cfg, warnings = dq2_user_config.load(config)
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
    ap = argparse.ArgumentParser(description="DQ2 のログの世代を送る")
    ap.add_argument("command", choices=["rotate"])
    ap.add_argument("--config", default=None, help="dq2_user_config.yaml のパス")
    args = ap.parse_args(argv)
    return rotate(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
