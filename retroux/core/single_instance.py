"""同じ役目のプロセスが二重に動くのを防ぐ。

いま2か所で使っている:

| 役目 | 二重に動くと | ロック |
| --- | --- | --- |
| イベント取り込み（record / gui） | **全戦闘が二重に記録**される | `work/event_ingestor.lock` |
| セーブステートの世代バックアップ | **世代が倍の速さで流れ、古い世代が押し出される** | `work/savestate_backup.lock` |

どちらも**見た目では気づけない**のが共通点。前者は数字が静かに倍になり、
後者は「戻りたい世代が消えている」と分かった時にはもう遅い。

PID ではなく心拍（ファイルの更新時刻）で判定する。
異常終了して残った古いロックで起動できなくなるのを避けるため。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

HEARTBEAT_STALE_SECONDS = 10.0
"""この秒数より古い心拍は、落ちたプロセスの残骸とみなす。"""


class AlreadyRunningError(RuntimeError):
    """別の記録プロセスが動いている。"""


class RecorderLock:
    """心拍ファイルによる排他。

    使い方:
        with RecorderLock(path):
            ...   # ループ内で touch() を呼び続ける
    """

    def __init__(self, path: Path | str, *,
                 description: str = "記録プロセス",
                 consequence: str = ("record と gui を同時に動かすと"
                                     "戦闘が二重に記録されます。")) -> None:
        self.path = Path(path)
        # ★何が二重になると何が起きるかを**メッセージに書けるようにする**。
        #   「別のプロセスが動いています」だけでは、利用者は
        #   無視してよいのか止めるべきなのか判断できない。
        self.description = description
        self.consequence = consequence

    def acquire(self, *, force: bool = False) -> None:
        if not force and self.is_active():
            age = time.time() - self.path.stat().st_mtime
            raise AlreadyRunningError(
                f"別の{self.description}が動いています（{age:.1f}秒前に更新）。\n"
                f"{self.consequence}\n"
                "どちらか一方だけを起動してください。"
            )
        self.touch()

    def is_active(self) -> bool:
        if not self.path.exists():
            return False
        return (time.time() - self.path.stat().st_mtime) < HEARTBEAT_STALE_SECONDS

    def touch(self) -> None:
        """心拍を更新する。取り込みループから定期的に呼ぶ。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()), encoding="utf-8")

    def release(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "RecorderLock":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()
