"""セーブステート保護の稼働状態（2026-07-30 / リリース調整 仕様書 6章）。

★★ **公開時の訴求機能。だから「動いていること」が見えないといけない。** ★★

  仕様書 6.1:
      セーブステート保護：稼働中
      最新バックアップ：09:14:32
      保持世代：10

  異常時:
      セーブステート保護：停止      ← 警告色で

## なぜ状態ファイルを作るのか

GUI とバックアップは**別プロセス**。GUI から中の様子は見えない。
既にある心拍（ロックファイルの更新時刻）で「動いているか」は分かるが、

  ・最終バックアップ時刻
  ・保持世代数
  ・監視対象と保存先
  ・最後のエラー

は分からない。→ バックアップ側が**小さな JSON を書く**。

⚠ **心拍と状態ファイルは役割が違う。** 混ぜない:

    ロックファイル … 二重起動を止める（更新時刻＝生きている証）
    状態ファイル   … 人に見せる内容（止まっても残す）

★状態ファイルは**止まっても消さない**。消すと GUI が
  「一度も動いていない」と「止まった」を区別できない。
  代わりに `running: false` を書く。

⚠ 「動いている」の判定は**状態ファイルの内容ではなく心拍**で行う。
  異常終了すると `running: true` のまま残るため。
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
import pathlib

#: 状態ファイルの名前（ロックと同じフォルダ）
STATUS_NAME = "savestate_backup.status.json"

#: 心拍がこれ以上古ければ「止まっている」とみなす（秒）。
#   ★`single_instance.HEARTBEAT_STALE_SECONDS` と同じ考え方だが、
#     表示用なので**少し甘く**する（1回の巡回が遅れただけで
#     「停止」と出ると、利用者を無駄に不安にさせる）。
STALE_SECONDS = 20.0


def status_path(lock_path) -> pathlib.Path:
    """ロックファイルの場所から状態ファイルの場所を作る。"""
    return pathlib.Path(lock_path).parent / STATUS_NAME


@dataclasses.dataclass(frozen=True)
class BackupStatus:
    """画面に出すための1件。⚠ **分からないものは None**（0 で埋めない）。"""

    #: ★心拍から見た「いま動いているか」。状態ファイルの中身では判断しない
    running: bool
    #: 状態ファイルがあったか（無ければ「一度も動いていない」）
    known: bool = False
    last_backup: str | None = None
    generations: int | None = None
    watching: str | None = None
    destination: str | None = None
    interval: float | None = None
    pid: int | None = None
    session: str | None = None
    last_error: str | None = None
    #: 心拍の古さ（秒）。None なら心拍が無い
    heartbeat_age: float | None = None

    # --- 画面に出す形 -----------------------------------------------

    @property
    def label(self) -> str:
        """1行の見出し（仕様書 6.1）。"""
        if self.running:
            return "セーブステート保護: 稼働中"
        if not self.known:
            # ★「停止」と言わない。**まだ動いたことがない**のとは違う
            return "セーブステート保護: 未起動"
        return "セーブステート保護: 停止"

    @property
    def is_warning(self) -> bool:
        """警告色で出すか（仕様書 6.1）。"""
        return (not self.running) or bool(self.last_error)

    def detail_lines(self) -> list:
        """詳細（仕様書 6.2）。★分からない項目は**出さない**。"""
        made = []
        if self.last_backup:
            made.append(f"最新バックアップ: {self.last_backup}")
        elif self.known:
            # ★動いてはいるが、まだ1件も世代を作っていない状態
            made.append("最新バックアップ: まだありません"
                        "（セーブステートを作ると世代が残ります）")
        if self.generations is not None:
            made.append(f"保持世代: {self.generations}")
        if self.interval is not None:
            made.append(f"監視間隔: {self.interval:g}秒")
        if self.watching:
            made.append(f"監視対象: {self.watching}")
        if self.destination:
            made.append(f"保存先: {self.destination}")
        if self.last_error:
            made.append(f"⚠ 最後のエラー: {self.last_error}")
        if not self.running and self.known:
            made.append("⚠ 止まっています。セーブステートの上書き事故から"
                        "守られていません。")
        return made

    def tooltip(self) -> str:
        lines = self.detail_lines()
        return "\n".join(lines) if lines else "まだ情報がありません。"


def read(lock_path) -> BackupStatus:
    """状態を読む。★**落ちない**（読めなければ「分からない」を返す）。

    ⚠ 「動いているか」は心拍（ロックの更新時刻）で見る。
      状態ファイルの `running` は当てにしない
      （異常終了すると true のまま残る）。
    """
    lock = pathlib.Path(lock_path)
    age = None
    try:
        if lock.exists():
            import time

            age = time.time() - lock.stat().st_mtime
    except OSError:
        age = None
    running = age is not None and age < STALE_SECONDS

    path = status_path(lock)
    raw: dict = {}
    known = False
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            known = isinstance(raw, dict)
            if not known:
                raw = {}
    except (OSError, ValueError):
        # ⚠ 壊れていても落ちない（表示のための処理で本体を止めない）
        raw = {}
        known = False

    def text(key):
        value = raw.get(key)
        return str(value) if value not in (None, "") else None

    def number(key, cast):
        value = raw.get(key)
        try:
            return cast(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return BackupStatus(
        running=running, known=known,
        last_backup=text("last_backup"),
        generations=number("generations", int),
        watching=text("watching"),
        destination=text("destination"),
        interval=number("interval", float),
        pid=number("pid", int),
        session=text("session"),
        last_error=text("last_error"),
        heartbeat_age=age)


def write(lock_path, *, running: bool, generations=None, watching=None,
          destination=None, interval=None, last_backup=None, session=None,
          last_error=None) -> bool:
    """状態を書く。戻り値は**書けたか**（書けなくても本体は止めない）。

    ★一時ファイル経由で置き換える。GUI が0.5秒ごとに読むので、
      書きかけを掴まれると**その瞬間だけ「分からない」になる**。
    """
    path = status_path(lock_path)
    payload = {
        "running": bool(running),
        "updated_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "pid": os.getpid(),
        "session": session,
        "generations": generations,
        "watching": str(watching) if watching is not None else None,
        "destination": str(destination) if destination is not None else None,
        "interval": interval,
        "last_backup": last_backup,
        "last_error": last_error,
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
        os.replace(temp, path)
        return True
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
