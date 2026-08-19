"""events.jsonl を追従して読む（Lua -> Python）。

ファイルベースIPC（D-3 / DEV-3）の読み側。LuaSocket が FCEUX に
同梱されていないためソケットではなくファイルを使っている。

Lua 側は追記のみを行う。ここでは読み取り位置を保持して差分だけを返す。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ..events import Event, parse_lines


class JsonlTailer:
    """追記されるテキストファイルを、前回の続きから読む。

    ファイルが縮んだ場合（Lua 側が新しいセッションで作り直した等）は
    先頭から読み直す。取りこぼしより二重取り込みのほうが害が小さいため。
    """

    def __init__(self, path: Path | str, *, from_start: bool = True,
                 start_offset: int | None = None) -> None:
        self.path = Path(path)
        self._offset = 0
        self._buffer = ""
        if start_offset is not None:
            # 前回の続きから読む（記録プロセスの再起動時）。
            # ファイルがそれより小さければ read_new_lines 側で 0 に戻す。
            self._offset = max(0, int(start_offset))
        elif not from_start and self.path.exists():
            self._offset = self.path.stat().st_size

    @property
    def offset(self) -> int:
        """次回読み始める位置。永続化して再起動時に渡す。"""
        return self._offset

    def read_new_lines(self) -> Iterator[str]:
        """前回の続きから、**改行で終わっている行だけ**を返す。

        書き込み途中の行を読まないよう、末尾の未完了部分は次回へ持ち越す。
        """
        if not self.path.exists():
            return

        size = self.path.stat().st_size
        if size < self._offset:
            # ローテートまたは作り直し
            self._offset = 0
            self._buffer = ""
        if size == self._offset:
            return

        with self.path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(self._offset)
            chunk = fh.read()
            self._offset = fh.tell()

        self._buffer += chunk
        *complete, self._buffer = self._buffer.split("\n")
        yield from complete

    def read_new_events(self) -> Iterator[Event]:
        yield from parse_lines(self.read_new_lines())
