"""Python 側のログ基盤（MVP2 Phase 1 / 指示書 6.2）。

出力先を1本の Logger にまとめ、複数の Handler へ同時に流す:

    retroux Logger
      ├─ RotatingFileHandler → work/retroux.log
      └─ GuiLogHandler       → GUI の System Log

★★ 同じファイルに **FCEUX の Lua も書いている** ★★

  `bridge.lua` は起動時に `work/retroux.log` を追記で開き、**開いたまま**
  1行ごとに書いて flush する。Python がローテーション（rename）すると:

    ・Windows では rename が失敗しうる（Lua がハンドルを持っているため）
    ・成功しても Lua は**名前が変わった側**に書き続ける（＝新しいログに出なくなる）

  どちらも「ログが静かに壊れる」ので、**Lua 側を書くたびに開き直す**形に
  変えてある（`Bridge:log`）。こちらだけ直しても片手落ちになる。

  ⚠ 実運用でローテーションが起きるのは稀（数週間使って 256KB）。
    だからこそ**起きたときに壊れる**設計を残してはいけない。

★GUI を固めないために Handler は**別スレッド**で動かす（指示書の受入条件）。
  `QueueHandler` に積むだけにして、実際のファイル書き込みは
  `QueueListener` のスレッドが行う。GUI スレッドはディスクを待たない。
"""

from __future__ import annotations

import logging
import logging.handlers
import queue
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path

LOGGER_NAME = "retroux"

DEFAULT_MAX_BYTES = 10 * 1024 * 1024   # 指示書 6.2 の推奨値
DEFAULT_BACKUP_COUNT = 5

# Lua が書く行と並ぶので、先頭の日時の形を揃える（grep しやすさのため）。
#   Lua : 2026-07-26 13:11:22 回復を確認: ...
#   これ: 2026-07-26 13:11:22 [INFO] record battle=12 event=battle_end ...
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(short_name)s%(context)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _ContextFilter(logging.Filter):
    """`battle_id` / `event_type` を書式に出せる形へ整える。

    指示書 6.2 が「battle_id と event_type を含む」ことを求めているが、
    毎回渡されるわけではない。**無いときに書式が壊れないようにする**のが役目。

    ★★ Logger ではなく **Handler に付ける** ★★
      Logger に付けたフィルタは、その Logger 自身が作ったレコードにしか効かない。
      実際の呼び出しは `get_logger("gui")` = 子ロガー（retroux.gui）なので、
      親のフィルタを通らずに書式へ届き、`KeyError: 'short_name'` で
      **ログが1行も出なくなった**（GUI を起動して初めて分かった）。
      Handler に付ければ、子から伝播してきたレコードにも効く。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        parts = []
        battle_id = getattr(record, "battle_id", None)
        event_type = getattr(record, "event_type", None)
        if battle_id is not None:
            parts.append(f"battle={battle_id}")
        if event_type is not None:
            parts.append(f"event={event_type}")
        record.context = (" " + " ".join(parts)) if parts else ""
        # retroux.core.recorder -> recorder（1行が長くなりすぎないように）
        record.short_name = record.name.rsplit(".", 1)[-1]
        return True


class GuiLogBuffer:
    """GUI が読む用の輪バッファ。

    ★GUI から「前回の続き」だけを取れるようにする。毎回全部を読み直すと
      行数が増えるほど描画が重くなる（指示書の禁止事項「ファイル全件再読込」）。

    ワーカースレッドが書き、GUI スレッドが読むのでロックで守る。
    """

    def __init__(self, capacity: int = 500) -> None:
        self._lines: deque[str] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._dropped = 0          # capacity を超えて捨てた行数
        self._total = 0            # これまでに積んだ総数（GUI 側の位置合わせ用）

    def append(self, line: str) -> None:
        with self._lock:
            if len(self._lines) == self._lines.maxlen:
                self._dropped += 1
            self._lines.append(line)
            self._total += 1

    def snapshot(self, since: int = 0) -> tuple[list[str], int]:
        """`since` 以降に積まれた行と、次に渡すべき位置を返す。

        バッファから溢れて読めなくなった行がある場合は、
        読める最も古い行から返す（黙って飛ばさない）。
        """
        with self._lock:
            first_available = self._total - len(self._lines)
            start = max(since, first_available)
            offset = start - first_available
            return list(self._lines)[offset:], self._total

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped


class GuiLogHandler(logging.Handler):
    """整形済みの1行を GUI 用バッファへ積むだけの Handler。"""

    def __init__(self, buffer: GuiLogBuffer) -> None:
        super().__init__()
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append(self.format(record))
        except Exception:      # noqa: BLE001 - ログが原因で落とさない
            self.handleError(record)


@dataclass
class LoggingHandle:
    """`setup_logging` の後始末と、GUI が読むバッファ。"""

    logger: logging.Logger
    buffer: GuiLogBuffer
    listener: logging.handlers.QueueListener | None
    handlers: list[logging.Handler]

    def shutdown(self) -> None:
        """★必ず呼ぶ。呼ばないと最後の数行がファイルに落ちない。"""
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        for handler in self.handlers:
            handler.close()
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
        self.handlers = []


#: ★出す量の段階（指示書 §19 の 2 モード）。
#
#   normal      … 製品利用。⚠ **DEBUG を書かない**（§20: retroux.log は INFO 以上）
#   diagnostic  … 不具合調査。DEBUG から（§21）
#
# ⚠⚠ **2026-08-09 の指示との関係**
#
#   > 画面にはださないが、ログボタンで見るとあとからわかる。
#
#   ★この形（ファイル DEBUG / 画面 INFO）は **diagnostic のとき**に残ります。
#   ⚠ normal では **ファイルにも DEBUG を書きません**（指示書 §20 が優先）。
#     あとから追いたいときは `logging.mode: diagnostic` にして再現します。
MODE_LEVELS = {
    "normal": {"level": logging.INFO, "gui_level": logging.INFO},
    "diagnostic": {"level": logging.DEBUG, "gui_level": logging.INFO},
}


def levels_for_mode(mode: str | None) -> dict[str, int]:
    """モード名から下限を決める。⚠ 読めない値は **normal**（静かなほうへ倒す）。

    ★「知らない綴りだから全部出す」は危険。
      ⚠ 設定の打ち間違いで、公開版が急に毎ポーリング出力になる。
    """
    key = str(mode or "normal").strip().lower()
    return dict(MODE_LEVELS.get(key, MODE_LEVELS["normal"]))


def _as_level(value: int | str) -> int:
    """`"INFO"` でも `logging.INFO` でも受ける。⚠ 読めなければ INFO。

    ★設定ファイルから来る値なので、綴り違いで落とさない。
    """
    if isinstance(value, int):
        return value
    resolved = logging.getLevelName(str(value).upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def setup_logging(
    log_path: Path | str,
    *,
    level: int | str = logging.DEBUG,
    gui_level: int | str = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    buffer_capacity: int = 500,
    use_queue: bool = True,
) -> LoggingHandle:
    """`retroux` Logger を組み立てる。

    use_queue=False にすると同期で書く（テスト用。書いた直後に読める）。

    ## ★★ ファイルと画面でレベルを分ける（2026-08-09 / 依頼者の指示）★★

        > 画面にはださないが、ログボタンで見るとあとからわかる。
        > ログは全体的にはそういう作りにしたい。ログレベル対応というか

        `level`     … **ファイル**（`work/retroux.log`）に残す下限。既定 DEBUG
        `gui_level` … **画面**（System Log）に出す下限。既定 INFO

    ★細かい記録（戦闘のターンごとの出来事・移動の観測）は DEBUG で書きます。
      ファイルには残り、画面には出ません。⚠ 画面へ出すと、1戦闘で数十行・
      移動で毎秒数行になり、**読みたい行が押し流されます**（実測: 1セッションで
      移動だけ145行）。

    ⚠⚠ Logger 自体の下限は**2つの低いほう**にします。ここで切ると
      Handler まで届きません（Handler 側の `setLevel` が効かなくなります）。
    """
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # ⚠ 設定から来る値は文字列（しかも綴り違いがありうる）。
    #   ★`setLevel` へ渡す前にここで数値へ直します。生の文字列を渡すと
    #     `ValueError: Unknown level` でログ基盤ごと落ちます。
    file_level = _as_level(level)
    screen_level = _as_level(gui_level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(file_level)

    buffer = GuiLogBuffer(capacity=buffer_capacity)
    gui_handler = GuiLogHandler(buffer)
    gui_handler.setFormatter(formatter)
    gui_handler.setLevel(screen_level)

    targets: list[logging.Handler] = [file_handler, gui_handler]

    logger = logging.getLogger(LOGGER_NAME)
    # ⚠ Logger で切ると Handler まで届きません。★低いほうに合わせます
    logger.setLevel(min(file_level, screen_level))
    logger.propagate = False        # ルートへ流さない（二重出力を防ぐ）
    for old in list(logger.handlers):
        logger.removeHandler(old)
    # ★フィルタは Handler 側に付ける（上のクラスの説明を参照）
    for handler in targets:
        handler.addFilter(_ContextFilter())

    listener: logging.handlers.QueueListener | None = None
    if use_queue:
        # ★GUI スレッドは put するだけ。ファイル書き込みは別スレッド。
        log_queue: queue.SimpleQueue = queue.SimpleQueue()
        logger.addHandler(logging.handlers.QueueHandler(log_queue))
        listener = logging.handlers.QueueListener(
            log_queue, *targets, respect_handler_level=True,
        )
        listener.start()
    else:
        for handler in targets:
            logger.addHandler(handler)

    return LoggingHandle(logger=logger, buffer=buffer,
                         listener=listener, handlers=targets)


def get_logger(name: str | None = None) -> logging.Logger:
    """`retroux.<name>` を返す。setup_logging を呼んでいなくても安全。"""
    if name is None:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
