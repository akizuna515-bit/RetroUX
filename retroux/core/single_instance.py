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

## ★ 2026-08-22（RX-0064）: 誰が握っているかを言う／死んだ相手には譲らせる

⚠ 実機で「終了ボタンで『保存して終了』が押せない」が起きた。原因は、閉じ切らずに
起動し直したせいで**古い pythonw が生き残り**、心拍を打ち続けていたこと。
判定は正しいのに、⚠ 利用者には「誰のせいで閲覧専用なのか」が出ていなかった。

- ロックには **PID と実行ファイル名**（と任意のセッションID）を書く。
- `holder()` が「誰が・何秒前・生きているか」を返し、メッセージと画面に出す。
- ★書いた PID の**プロセスがもう居なければ**、心拍が新しくても**譲る**
  （落ちた直後の 10 秒間、後発が閲覧専用になっていた穴）。
- ⚠ **何も殺さない。** 掃除は「相手が死んでいたら引き継ぐ」だけ（`README §219` が
  取り違えを理由に保留にしたので、こちらから終了させには行かない）。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import process_probe

HEARTBEAT_STALE_SECONDS = 10.0
"""この秒数より古い心拍は、落ちたプロセスの残骸とみなす。"""


class AlreadyRunningError(RuntimeError):
    """別の記録プロセスが動いている。"""


@dataclass(frozen=True)
class Holder:
    """いまロックを握っている相手（★分からない項目は None のまま）。"""

    pid: int | None = None
    image: str | None = None
    session: str | None = None
    age_seconds: float | None = None
    alive: bool | None = None           # ⚠ None は「確かめられない」

    def describe(self) -> str:
        """人が読む1行。★分からないことは書かない。"""
        bits = []
        if self.pid:
            bits.append(f"PID {self.pid}")
        if self.image:
            bits.append(self.image)
        if self.session:
            bits.append(f"session={self.session}")
        if self.age_seconds is not None:
            bits.append(f"最終心拍 {self.age_seconds:.1f} 秒前")
        if self.alive is False:
            bits.append("⚠ そのプロセスはもう居ません")
        return " / ".join(bits) if bits else "（誰が握っているか分かりません）"


class RecorderLock:
    """心拍ファイルによる排他。

    使い方:
        with RecorderLock(path):
            ...   # ループ内で touch() を呼び続ける
    """

    def __init__(self, path: Path | str, *,
                 session: str | None = None,
                 description: str = "記録プロセス",
                 consequence: str = ("record と gui を同時に動かすと"
                                     "戦闘が二重に記録されます。")) -> None:
        self.path = Path(path)
        #: ★どの起動の組か（分かるなら書く。⚠ 無くても動く）
        self.session = session
        # ★何が二重になると何が起きるかを**メッセージに書けるようにする**。
        #   「別のプロセスが動いています」だけでは、利用者は
        #   無視してよいのか止めるべきなのか判断できない。
        self.description = description
        self.consequence = consequence

    def acquire(self, *, force: bool = False) -> None:
        if not force and self.is_active():
            holder = self.holder()
            raise AlreadyRunningError(
                f"別の{self.description}が動いています（{holder.describe()}）。\n"
                f"{self.consequence}\n"
                "どちらか一方だけを起動してください。"
            )
        self.touch()

    def read(self) -> dict:
        """ロックファイルの中身。⚠ 読めなければ空（★推測で埋めない）。

        ★2026-08-22 より前は **PID だけ**を書いていたので、その形も読む。
        """
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return {}
        if not raw:
            return {}
        if raw.startswith("{"):
            try:
                got = json.loads(raw)
            except ValueError:
                return {}
            return got if isinstance(got, dict) else {}
        try:
            return {"pid": int(raw)}           # ★古い形（PID だけ）
        except ValueError:
            return {}

    def holder(self) -> Holder:
        """いま握っている相手。★ファイルが無ければ空の Holder。"""
        if not self.path.exists():
            return Holder()
        got = self.read()
        pid = got.get("pid")
        image = got.get("image")
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            age = None
        return Holder(pid=int(pid) if pid else None, image=image,
                      session=got.get("session"), age_seconds=age,
                      alive=process_probe.alive(pid, image))

    def is_active(self) -> bool:
        """まだ誰かが握っているか。

        ★心拍が新しくても、**書いた相手がもう居なければ False**（RX-0064）。
          ⚠ 落ちた直後の 10 秒間、後発が理由もなく閲覧専用になっていた。
        ⚠ 生死を確かめられない環境（Windows 以外・API 不可）では、
          これまでどおり心拍だけで判断する。
        """
        if not self.path.exists():
            return False
        fresh = (time.time() - self.path.stat().st_mtime) < HEARTBEAT_STALE_SECONDS
        if not fresh:
            return False
        got = self.read()
        return process_probe.alive(got.get("pid"), got.get("image")) is not False

    def touch(self) -> None:
        """心拍を更新する。取り込みループから定期的に呼ぶ。

        ★誰が握っているかを後から言えるように、PID と実行ファイル名も書く
          （RX-0064）。⚠ 実行ファイル名は PID の使い回しを見抜くために要る。
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {"pid": os.getpid(), "image": process_probe.current_image_name()}
        if self.session:
            body["session"] = self.session
        self.path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")

    def release(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "RecorderLock":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()
